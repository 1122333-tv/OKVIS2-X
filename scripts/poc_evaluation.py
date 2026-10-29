#!/usr/bin/env python3
"""Standalone OKVIS/Basalt POC comparison.

Alignment, integer-ns time pairs and continuity rules adapted from the local
Basalt POC evaluator; its source hash is recorded in poc_evaluation_origin.json.
No Basalt project code is imported or executed.
"""
import argparse
import copy
import csv
import json
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation
from evo.core import filters, metrics, result
from evo.tools import file_interface
from capture_pipeline_common import ns_seconds
from interpolate_mocap_to_vio import interpolate
import hashlib
import shutil
from convert_okvis_trajectory import load, write

COLORS={'okvis':'#D55E00','basalt':'#0072B2'}
LABELS={'okvis':'OKVIS2','basalt':'Basalt'}


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False)+'\n')


def statistics(errors):
    x=np.asarray(errors, dtype=float)
    if not len(x):return None
    if not np.isfinite(x).all():raise ValueError('Non-finite metric errors')
    return dict(n=len(x),rmse=float(np.sqrt(np.mean(x*x))),mean=float(x.mean()),
                median=float(np.median(x)),std=float(x.std()),min=float(x.min()),
                max=float(x.max()),p95=float(np.quantile(x,.95)),p99=float(np.quantile(x,.99)))


def timestamps(path):
    return np.array([ns_seconds(line.split()[0],allow_rounding=True)
                     for line in path.read_text().splitlines() if line.strip() and not line.startswith('#')],dtype=np.int64)


def time_pairs(ts,delta,tolerance=.1):
    """Nearest endpoint to each start+delta; relative tolerance, integer ns."""
    step=round(delta*1e9);out=[]
    for i,t in enumerate(ts[:-1]):
        k=int(np.searchsorted(ts,t+step))
        candidates=[j for j in (k-1,k) if i<j<len(ts)]
        if not candidates:continue
        j=min(candidates,key=lambda j:abs(int(ts[j]-t)-step))
        if abs(int(ts[j]-t)-step)<=round(step*tolerance):out.append((i,j))
    return out


def segment_labels(ts,groundtruth,states=None):
    """Never form relative pairs across GT holes, missing output or state resets."""
    labels=np.zeros(len(ts),dtype=int)
    conv=groundtruth.with_name('conversion.json')
    spans=json.loads(conv.read_text()).get('valid_segments_ns',[]) if conv.exists() else []
    gt_labels=[]
    for t in ts:
        matches=[i for i,(a,b) in enumerate(spans) if a<=int(t)<=b]
        gt_labels.append(matches[0] if matches else -1)
    dt=np.diff(ts);nominal=int(np.median(dt)) if len(dt) else 0
    resets=[]
    if states and states.is_file():
        with states.open() as f:
            for r in csv.DictReader(f):
                if int(r.get('state_reset','0')):resets.append(int(r['timestamp_ns']))
    for i in range(1,len(ts)):
        split=(int(ts[i]-ts[i-1])>1.8*nominal or
               (bool(spans) and gt_labels[i]!=gt_labels[i-1]) or
               any(int(ts[i-1])<r<=int(ts[i]) for r in resets))
        labels[i]=labels[i-1]+int(split)
    return labels


def align(ref,est,ts,profile):
    est=copy.deepcopy(est)
    raw_cov=np.linalg.svd(np.cov(ref.positions_xyz.T),compute_uv=False)
    if profile=='static':
        ids=np.flatnonzero(ts-ts[0]<=1_000_000_000)
        rr=np.asarray([ref.poses_se3[i][:3,:3]@est.poses_se3[i][:3,:3].T for i in ids])
        r=Rotation.from_matrix(rr).mean().as_matrix()
        t=ref.positions_xyz[ids].mean(0)-r@est.positions_xyz[ids].mean(0)
        name='Initial 1 s mean pose alignment; SE(3), no scale correction'
    else:
        r,t,s=est.align(ref,correct_scale=False)
        if abs(s-1)>1e-9:raise ValueError('Unexpected scale correction')
        return est,dict(method='Full matched-trajectory position SE(3) Umeyama; no scale correction',rotation=r.tolist(),translation=t.tolist(),reference_position_covariance_singular_values=raw_cov.tolist())
    tf=np.eye(4);tf[:3,:3]=r;tf[:3,3]=t;est.transform(tf)
    return est,dict(method=name,rotation=r.tolist(),translation=t.tolist(),reference_position_covariance_singular_values=raw_cov.tolist())


def metric_dir(name):
    if name=='ape_translation':return Path('ape')
    if name=='are_rotation':return Path('are')
    family,_,delta=name.split('_',2)
    return Path(family)/delta


def evaluate_matched(folder, profile, labels):
    """Evaluate already paired trajectories; all associations remain integer ns."""
    gt_file=folder/'mocap_at_vio.tum';est_file=folder/'vio_matched.tum'
    ts=timestamps(gt_file)
    if not np.array_equal(ts,timestamps(est_file)) or len(labels)!=len(ts):
        raise ValueError('Mismatched evaluation timestamps or continuity labels')
    ref=file_interface.read_tum_trajectory_file(gt_file)
    raw=file_interface.read_tum_trajectory_file(est_file)
    est,alignment=align(ref,raw,ts,profile)
    # Preserve exact timestamps when writing aligned poses, avoiding float epoch formatting.
    with (folder/'estimate_aligned.tum').open('w') as f:
        from convert_okvis_trajectory import tum_time
        for t,p,q in zip(ts,est.positions_xyz,est.orientations_quat_wxyz):
            f.write(tum_time(int(t))+' '+' '.join(format(x,'.17g') for x in [*p,*q[1:],q[0]])+'\n')
    out=dict(alignment=alignment,metrics={},metric_units={},metric_records={},unavailable_metrics={},
             pairing=dict(segment_count=int(labels[-1]+1),
                          exclusions='GT invalid segments, output gaps >1.8 median periods, available state-reset events'))
    def emit(name,errors,unit,pairs,eligible=None):
        errors=np.asarray(errors,dtype=float);st=statistics(errors)
        endpoints=[(int(ts[i]),int(ts[j])) for i,j in pairs]
        digest=hashlib.sha256(''.join(f'{a},{b}\n' for a,b in endpoints).encode()).hexdigest()
        record=dict(status='OK' if st else 'NOT_APPLICABLE',unit=unit,stats=st,
                    pairs_sha256=digest,candidate_pairs=eligible,
                    rejected_pairs=eligible-len(pairs) if eligible is not None else None)
        out['metric_records'][name]=record;out['metric_units'][name]=unit
        if st:out['metrics'][name]=st
        else:out['unavailable_metrics'][name]='No valid pose pairs for this interval'
        with (folder/(name+'_errors.csv')).open('w') as f:
            w=csv.writer(f);w.writerow(['start_ns','end_ns','segment','error_'+unit])
            w.writerows((a,b,int(labels[j]),float(e)) for (a,b),(i,j),e in zip(endpoints,pairs,errors))
        save(folder/(name+'_extended_stats.json'),record)
        if st:
            res=result.Result();res.add_info(dict(title=name,label=name+' ('+unit+')'))
            res.add_stats(st);res.add_np_array('error_array',errors)
            file_interface.save_res_file(folder/(name+'.zip'),res,confirm_overwrite=False)
    for relation,name,unit in [(metrics.PoseRelation.translation_part,'ape_translation','m'),
                               (metrics.PoseRelation.rotation_angle_deg,'are_rotation','deg')]:
        metric=metrics.APE(relation);metric.process_data((ref,est))
        emit(name,metric.error,unit,[(i,i) for i in range(len(ts))])
    specs=[('0.1s',time_pairs(ts,.1)),('1s',time_pairs(ts,1.))]
    if profile=='motion':
        specs += [(f'{d:g}m',filters.filter_pairs_by_path(ref.poses_se3,d,d*.1,all_pairs=True)) for d in (.1,.5,1.)]
    for key,candidates in specs:
        pairs=[(i,j) for i,j in candidates if labels[i]==labels[j]]
        errors=[metrics.RPE.rpe_base(ref.poses_se3[i],ref.poses_se3[j],est.poses_se3[i],est.poses_se3[j]) for i,j in pairs]
        trans=[np.linalg.norm(e[:3,3]) for e in errors]
        angles=np.rad2deg(Rotation.from_matrix(np.array([e[:3,:3] for e in errors])).magnitude()) if errors else []
        emit('rpe_translation_'+key,trans,'m',pairs,len(candidates))
        emit('rre_rotation_'+key,angles,'deg',pairs,len(candidates))
    if profile=='static':
        pos=raw.positions_xyz;rs=Rotation.from_quat(raw.orientations_quat_wxyz[:,[1,2,3,0]])
        n0=np.flatnonzero(ts-ts[0]<=1e9);n1=np.flatnonzero(ts[-1]-ts<=1e9)
        out['static_stability']=dict(
            position_jitter_about_whole_run_mean_m=statistics(np.linalg.norm(pos-pos.mean(0),axis=1)),
            rotation_jitter_about_whole_run_mean_deg=statistics(np.rad2deg((rs.mean().inv()*rs).magnitude())),
            end_minus_start_mean_position_m=float(np.linalg.norm(pos[n1].mean(0)-pos[n0].mean(0))),
            end_minus_start_mean_rotation_deg=float(np.rad2deg((rs[n0].mean().inv()*rs[n1].mean()).magnitude())))
    return out


def common_labels(common, native):
    """Union of both algorithms' discontinuities on the common timestamps."""
    changes=np.zeros(max(0,len(common)-1),dtype=bool)
    for record in native.values():
        values=np.array([record[t] for t in common])
        changes |= np.diff(values)!=0
    return np.r_[0,np.cumsum(changes)].astype(int)


def plot_comparison(output, scope, records, origin_ns):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    def broken(x,y,segments):
        cuts=np.flatnonzero(np.diff(segments)!=0)+1
        return np.insert(x,cuts,np.nan),np.insert(y,cuts,np.nan,axis=0)
    names=list(dict.fromkeys(k for r in records.values() for k in r.get('metric_records',{})))
    for metric in names:
        fig,ax=plt.subplots(figsize=(10,3.2),layout='constrained')
        plotted=False
        for name,r in records.items():
            p=output/scope/name/(metric+'_errors.csv')
            if not p.is_file():continue
            with p.open() as f:rows=list(csv.DictReader(f))
            if not rows:continue
            unit=r['metric_units'][metric];factor=100 if unit=='m' else 1
            x=np.array([(int(v['end_ns'])-origin_ns)/1e9 for v in rows])
            y=np.array([float(v['error_'+unit])*factor for v in rows])
            x,y=broken(x,y,np.array([int(v['segment']) for v in rows]))
            st=r['metrics'][metric]
            ax.plot(x,y,color=COLORS[name],ls='-' if name=='okvis' else '--',lw=1,
                    label=f"{LABELS[name]}: RMSE {st['rmse']*factor:.3f}, P95 {st['p95']*factor:.3f}")
            plotted=True
        if plotted:
            ax.set(xlabel='Time since first input group (s)',ylabel='Error ('+('cm' if unit=='m' else 'deg')+')',title=metric)
            ax.set_ylim(bottom=0);ax.grid(alpha=.2);ax.legend(fontsize=8)
            fig.savefig(output/(scope+'_'+metric+'.png'),dpi=150)
        plt.close(fig)
    # Both algorithms and GT in the mocap world; Y up, XZ horizontal.
    fig,axes=plt.subplots(1,2,figsize=(11,4.5),layout='constrained')
    for name,r in records.items():
        folder=output/scope/name
        if not (folder/'estimate_aligned.tum').is_file():continue
        ts=timestamps(folder/'estimate_aligned.tum');est=np.loadtxt(folder/'estimate_aligned.tum')[:,1:4]
        labels=np.asarray(json.loads((folder/'segments.json').read_text()))
        _,pos=broken((ts-origin_ns)/1e9,est,labels)
        axes[0].plot(pos[:,0],pos[:,2],color=COLORS[name],ls='-' if name=='okvis' else '--',label=LABELS[name])
        axes[1].plot(pos[:,0],pos[:,1],color=COLORS[name],ls='-' if name=='okvis' else '--',label=LABELS[name])
        if name=='okvis':
            gt=np.loadtxt(folder/'mocap_at_vio.tum')[:,1:4];_,gt=broken((ts-origin_ns)/1e9,gt,labels)
            axes[0].plot(gt[:,0],gt[:,2],color='#555555',ls=':',label='GT')
            axes[1].plot(gt[:,0],gt[:,1],color='#555555',ls=':',label='GT')
    for ax,y in zip(axes,['Z','Y']):
        ax.set(xlabel='World X (m)',ylabel='World '+y+' (m)');ax.set_aspect('equal',adjustable='datalim');ax.grid(alpha=.2);ax.legend()
    fig.savefig(output/(scope+'_trajectory.png'),dpi=150);plt.close(fig)


def compare(a):
    output=a.output;output.mkdir(parents=True,exist_ok=True)
    snapshot=output/'inputs/evaluator_sources';snapshot.mkdir(parents=True,exist_ok=True)
    source_hashes={}
    for name in ['poc_evaluation.py','poc_evaluation_origin.json','compare_vio_runs.py','interpolate_mocap_to_vio.py','capture_pipeline_common.py','convert_okvis_trajectory.py']:
        p=Path(__file__).with_name(name);shutil.copyfile(p,snapshot/name)
        source_hashes[name]=hashlib.sha256(p.read_bytes()).hexdigest()
    lo=a.input_first_ns+int(a.start*10**9);hi=a.input_first_ns+int(a.end*10**9) if a.end is not None else None
    tracks={name:[r for r in load(p,'wxyz') if r[0]>=lo and (hi is None or r[0]<=hi)] for name,p in [('okvis',a.okvis),('basalt',a.basalt)]}
    result_data=dict(profile=a.evaluation_profile,evaluator_sources=source_hashes,
        alignment='Initial 1 s mean pose SE(3)' if a.evaluation_profile=='static' else 'Full matched-trajectory position SE(3)',
        scale_corrected=False,time_offset='Frozen per-recording IMU GT; no VIO fitting',origin_ns=a.input_first_ns,
        native={},common={},quality_status='NOT_GATED',
        continuity_policy='Common RPE/RRE use the union of both native continuity boundaries and identical GT-based pairs',
        reset_evidence={'basalt':str(a.basalt_states) if a.basalt_states else 'unavailable',
                        'okvis':'No explicit reset event stream; output timestamp gaps checked'},
        imu_policy_note='OKVIS raw IMU, zero initial bias, online total-bias estimation; Basalt baseline retains fixed calibration correction')
    native_labels={};matched={}
    for name,poses in tracks.items():
        d=output/'native'/name;d.mkdir(parents=True,exist_ok=True)
        if not poses:
            result_data['native'][name]={'metrics':{},'unavailable_metrics':{'all':'Empty trajectory window'}};native_labels[name]={};matched[name]=[];continue
        write(poses,d)
        try:info=interpolate(a.groundtruth,d/'trajectory.tum',d)
        except ValueError as e:
            if 'Fewer than 5 valid' not in str(e):raise
            result_data['native'][name]={'metrics':{},'unavailable_metrics':{'all':str(e)}};native_labels[name]={};matched[name]=[];continue
        ts=timestamps(d/'vio_matched.tum')
        labels=segment_labels(ts,a.groundtruth,a.basalt_states if name=='basalt' else None)
        native_labels[name]=dict(zip(map(int,ts),map(int,labels)))
        accepted=set(map(int,ts));matched[name]=[r for r in poses if r[0] in accepted]
        record=evaluate_matched(d,a.evaluation_profile,labels);record['interpolation']=info
        result_data['native'][name]=record;save(d/'segments.json',labels.tolist());save(d/'metrics.json',record)
    common=sorted(set(native_labels['okvis'])&set(native_labels['basalt']))
    result_data['common_timestamps']=dict(n=len(common),status='complete' if len(common)>=5 else 'unavailable')
    if len(common)>=5:
        result_data['common_timestamps'].update(first_ns=common[0],last_ns=common[-1])
        labels=common_labels(common,native_labels);commonset=set(common)
        for name in tracks:
            d=output/'common'/name;write([r for r in matched[name] if r[0] in commonset],d)
            info=interpolate(a.groundtruth,d/'trajectory.tum',d)
            if list(map(int,timestamps(d/'vio_matched.tum')))!=common:raise ValueError('Common interpolation changed timestamp set')
            record=evaluate_matched(d,a.evaluation_profile,labels);record['interpolation']=info
            result_data['common'][name]=record;save(d/'segments.json',labels.tolist());save(d/'metrics.json',record)
        if (output/'common/okvis/mocap_at_vio.tum').read_bytes()!=(output/'common/basalt/mocap_at_vio.tum').read_bytes():
            raise ValueError('Common GT differs')
        for metric,r in result_data['common']['okvis']['metric_records'].items():
            if r['pairs_sha256']!=result_data['common']['basalt']['metric_records'][metric]['pairs_sha256']:
                raise ValueError('Common metric pairs differ: '+metric)
        result_data['common_pairs_verified']=True
    else:result_data['common_timestamps']['reason']='Fewer than five exact common valid timestamps'
    save(output/'summary/summary.json',result_data)
    for scope in ('native','common'):
        if result_data[scope]:plot_comparison(output,scope,result_data[scope],a.input_first_ns)
    print(json.dumps({'profile':a.evaluation_profile,'common':len(common)},ensure_ascii=False))
    return result_data
