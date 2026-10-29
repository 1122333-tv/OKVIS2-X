#!/usr/bin/env python3
"""Evaluate native coverage and exact common timestamps with frozen IMU GT."""
import argparse
import json
from pathlib import Path
import subprocess
import shutil
import hashlib
import sys
import numpy as np
from convert_okvis_trajectory import load,write


def dump(p,obj):p.write_text(json.dumps(obj,indent=2,ensure_ascii=False)+'\n')

def stats(values):
    a=np.asarray(values)
    return dict(n=len(a),rmse=float(np.sqrt(np.mean(a*a))),median=float(np.median(a)),p95=float(np.quantile(a,.95)),max=float(a.max())) if len(a) else dict(n=0)


def main():
    p=argparse.ArgumentParser(__doc__)
    for name in ('okvis','basalt','groundtruth','output'):p.add_argument('--'+name,required=True,type=Path)
    p.add_argument('--input-first-ns',required=True,type=int)
    p.add_argument('--start',type=__import__('decimal').Decimal,default=__import__('decimal').Decimal('0'))
    p.add_argument('--end',type=__import__('decimal').Decimal)
    p.add_argument('--show-gui',action='store_true')
    p.add_argument('--evaluation-profile',choices=['legacy','static','motion'],default='legacy')
    p.add_argument('--basalt-states',type=Path)
    a=p.parse_args()
    if not a.start.is_finite() or a.start<0 or (a.end is not None and (not a.end.is_finite() or a.end<=a.start)):p.error('Require 0 <= start < end')
    if a.evaluation_profile!='legacy':
        from poc_evaluation import compare
        compare(a)
        return
    a.output.mkdir(parents=True,exist_ok=True)
    for sub in ('inputs','logs','summary'):(a.output/sub).mkdir(exist_ok=True)
    effective=a.output/'inputs/evaluator_sources';effective.mkdir(exist_ok=True)
    evaluator_hashes={}
    for source in [Path(__file__).resolve(),Path(__file__).with_name('convert_okvis_trajectory.py'),*[Path(__file__).parent/n for n in ['interpolate_mocap_to_vio.py','capture_pipeline_common.py','extend_evo_stats.py']]]:
        shutil.copy2(source,effective/source.name);evaluator_hashes[str(source)]=hashlib.sha256(source.read_bytes()).hexdigest()
    dump(effective/'sha256.json',evaluator_hashes)
    from interpolate_mocap_to_vio import interpolate
    from capture_pipeline_common import ns_seconds
    tracks={'okvis':load(a.okvis,'wxyz'),'basalt':load(a.basalt,'wxyz')}
    lo=a.input_first_ns+int(a.start*1000000000)
    hi=a.input_first_ns+int(a.end*1000000000) if a.end is not None else None
    tracks={name:[r for r in poses if r[0]>=lo and (hi is None or r[0]<=hi)] for name,poses in tracks.items()}
    accepted={};result=dict(evaluator_sources=evaluator_hashes,alignment='SE(3), no scale',time_offset='frozen GT; no VIO fitting',native={},common={},window_seconds=[str(a.start),str(a.end) if a.end is not None else None],origin_ns=a.input_first_ns)
    env=__import__('os').environ.copy();env.update(PYTHON_BIN=sys.executable,MPLBACKEND='Agg')
    plot_cache=a.output/'plot_cache';plot_cache.mkdir(exist_ok=True)
    env['MPLCONFIGDIR']=str(plot_cache)
    __import__('os').environ['MPLCONFIGDIR']=str(plot_cache)
    def evaluate(name,poses,kind):
        d=a.output/kind/name
        d.mkdir(parents=True,exist_ok=True)
        if not poses:
            return {'interpolation':{'input_vio_poses':0,'accepted_poses':0,'skipped_poses':0},'metrics':{},'unavailable_metrics':{'all':'Empty evaluation window'}}
        write(poses,d)
        try:interpolation=interpolate(a.groundtruth,d/'trajectory.tum',d)
        except ValueError as e:
            if 'Fewer than 5 valid' not in str(e):raise
            return {'interpolation':json.loads((d/'interpolation.json').read_text()),'metrics':{},'unavailable_metrics':{'all':str(e)}}
        config=d/'evo_plot_config.json';dump(config,dict(plot_backend='Agg',plot_usetex=False))
        common_args=['tum',str(d/'mocap_at_vio.tum'),str(d/'vio_matched.tum'),
                     '--align','--pose_relation','trans_part','--t_max_diff','0.000000001',
                     '--config',str(config),'--no_warnings']
        metrics=[('ape_translation',['evo_ape',*common_args])]
        for delta in (.1,.5,1):
            label=format(delta,'g')
            metrics.append((f'rpe_translation_{label}m',['evo_rpe',*common_args,'--delta',label,
                            '--delta_unit','m','--delta_tol','0.1','--all_pairs','--pairs_from_reference']))
        out={'interpolation':interpolation,'metrics':{},'unavailable_metrics':{}};commands=[]
        with (d/'evaluation.log').open('w') as f:
            for metric,cmd in metrics:
                cmd+=['--save_results',str(d/(metric+'.zip')),'--save_plot',str(d/(metric+'.png'))]
                cmd[0]=str(Path(sys.executable).parent/cmd[0])
                commands.append(cmd)
                completed=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,env=env,text=True)
                f.write(completed.stdout);f.flush()
                if completed.returncode:
                    if metric.startswith('rpe_') and 'empty index list' in completed.stdout:
                        out['unavailable_metrics'][metric]='No reference-distance pairs for configured delta/tolerance';continue
                    raise RuntimeError('evo failed: '+metric+'; see '+str(d/'evaluation.log'))
                subprocess.run([sys.executable,str(Path(__file__).with_name('extend_evo_stats.py')),str(d/(metric+'.zip'))],env=env,stdout=f,stderr=subprocess.STDOUT,check=True)
                out['metrics'][metric]=json.loads((d/(metric+'_extended_stats.json')).read_text())['stats']
            cmd=[str(Path(sys.executable).parent/'evo_traj'),'tum',str(d/'vio_matched.tum'),'--ref',str(d/'mocap_at_vio.tum'),'--align',
                 '--t_max_diff','0.000000001','--plot_mode','xyz','--config',str(config),'--save_plot',str(d/'trajectory.png')]
            commands.append(cmd);subprocess.run(cmd,env=env,stdout=f,stderr=subprocess.STDOUT,check=True)
        dump(d/'commands.json',commands);dump(d/'metrics.json',out)
        return out
    for name,poses in tracks.items():
        result['native'][name]=evaluate(name,poses,'native')
        d=a.output/'native'/name
        accepted[name]={ns_seconds(line.split()[0],allow_rounding=True) for line in ((d/'vio_matched.tum').read_text().splitlines() if (d/'vio_matched.tum').exists() else []) if line.strip()}
    common=sorted(accepted['okvis']&accepted['basalt'])
    if len(common)<5:
        result['common_timestamps']={'n':len(common),'status':'unavailable','reason':'Fewer than five exact common valid timestamps'}
        dump(a.output/'summary/summary.json',result)
        return
    commonset=set(common);result['common_timestamps']=dict(n=len(common),first_ns=common[0],last_ns=common[-1])
    for name,poses in tracks.items():
        selected=[r for r in poses if r[0] in commonset]
        result['common'][name]=evaluate(name,selected,'common')
    # Reproducible diagnostic alignment windows, without mixing them into evo APE.
    import matplotlib;matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,ax=plt.subplots(figsize=(11,4));diagnostics={}
    def fit(x,y):
        xc=x-x.mean(axis=0);yc=y-y.mean(axis=0);u,_,vt=np.linalg.svd(xc.T@yc)
        D=np.eye(3);D[-1,-1]=np.linalg.det(u@vt);R=u@D@vt
        return R,y.mean(axis=0)-x.mean(axis=0)@R
    for name in tracks:
        d=a.output/'common'/name
        x=np.loadtxt(d/'vio_matched.tum')[:,1:4];y=np.loadtxt(d/'mocap_at_vio.tum')[:,1:4]
        t=(np.asarray(common,dtype=np.int64)-a.input_first_ns)/1e9
        modes={}
        for mode,idx in [('full',np.ones(len(t),dtype=bool)),('first_10s',t<=10)]:
            if idx.sum()<3 or np.linalg.matrix_rank(x[idx]-x[idx].mean(axis=0),tol=1e-8)<2:
                modes[mode]={'status':'insufficient alignment motion'};continue
            spread=np.linalg.svd(y[idx]-y[idx].mean(axis=0),compute_uv=False)/np.sqrt(idx.sum())
            if mode=='first_10s' and spread[1]<.01:
                modes[mode]={'status':'insufficient alignment motion','gt_rms_principal_spread_m':spread.tolist(),
                             'minimum_second_axis_spread_m':.01};continue
            R,tr=fit(x[idx],y[idx]);err=np.linalg.norm(x@R+tr-y,axis=1)
            modes[mode]=dict(status='complete',alignment_samples=int(idx.sum()),overall=stats(err),
                startup_0_10s=stats(err[(t>=0)&(t<=10)]),segment_45_55s=stats(err[(t>=45)&(t<=55)]),
                rotation=R.tolist(),translation=tr.tolist())
            gap_indices=np.flatnonzero(np.diff(t)>1.5*np.median(np.diff(t)))+1
            plot_t=np.insert(t,gap_indices,np.nan);plot_error=np.insert(err,gap_indices,np.nan)
            ax.plot(plot_t,plot_error,label=name+' '+mode,lw=1.2,
                    color='#D55E00' if name=='okvis' else '#0072B2',
                    linestyle=('-' if name=='okvis' else '--') if mode=='full' else ':')
        diagnostics[name]=modes
    ax.set(xlabel='Seconds since first input group (IMU clock)',ylabel='Position error [m]');ax.legend();ax.grid(alpha=.3);fig.tight_layout();fig.savefig(a.output/'alignment_windows.png',dpi=160);plt.close(fig)
    result['diagnostics']=diagnostics;dump(a.output/'summary/summary.json',result)
    lines=['# OKVIS / Basalt VIO comparison','', 'Frozen IMU GT; SE(3) alignment without scale correction. Exact common timestamps: '+str(len(common))+'.','',
        '| Scope | Algorithm | APE RMSE (m) | APE p95 (m) | Samples |','| --- | --- | ---: | ---: | ---: |']
    for scope in ('native','common'):
        for name,r in result[scope].items():
            if 'ape_translation' not in r['metrics']:continue
            v=r['metrics']['ape_translation'];lines.append(f"| {scope} | {name} | {v['rmse']:.6f} | {v.get('p95',float('nan')):.6f} | {v['n']} |")
    lines+=['','See summary.json for RPE pair counts, GT interpolation coverage and alignment-window diagnostics.','',
        'GT is imported unchanged. Physical IMU frame and marker-IMU calibration consistency are not checked. This is one recording, not independent generalization acceptance.','',
        '![Alignment windows](alignment_windows.png)']
    (a.output/'summary/report.md').write_text('\n'.join(lines).replace('(alignment_windows.png)','(../alignment_windows.png)')+'\n')
    if a.show_gui:show_gui(a.output)
def show_gui(output):
    output=Path(output)
    gui=output/'inputs/gui';gui.mkdir(parents=True,exist_ok=True)
    config=gui/'config.json';dump(config,dict(plot_backend='QtAgg',plot_usetex=False))
    env=__import__('os').environ.copy();env.update(MPLBACKEND='QtAgg',MPLCONFIGDIR=str(output/'plot_cache'))
    print('Close each evo window to continue.',flush=True)
    for metric in ('ape_translation','rpe_translation_0.1m','rpe_translation_0.5m','rpe_translation_1m'):
        folder=gui/metric;folder.mkdir(exist_ok=True);files=[]
        for name in ('okvis','basalt'):
            source=output/'common'/name/(metric+'.zip')
            if source.is_file():
                target=folder/(name+'.zip');shutil.copyfile(source,target);files.append(target)
        if files:subprocess.run([str(Path(sys.executable).parent/'evo_res'),*map(str,files),'--use_filenames','--use_rel_time','--plot','--config',str(config)],env=env,check=True)
    trajectories=[]
    for name in ('okvis','basalt'):
        source=output/'common'/name/'vio_matched.tum'
        if source.is_file():
            target=gui/(name+'.tum');shutil.copyfile(source,target);trajectories.append(str(target))
    if len(trajectories)==2:
        subprocess.run([str(Path(sys.executable).parent/'evo_traj'),'tum',*trajectories,'--ref',str(output/'common/okvis/mocap_at_vio.tum'),'--align','--t_max_diff','0.000000001','--plot','--plot_mode','xyz','--config',str(config)],env=env,check=True)

if __name__=='__main__':main()
