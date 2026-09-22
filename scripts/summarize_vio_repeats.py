#!/usr/bin/env python3
"""Summarize repeated runs without presenting reruns as independent datasets."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import zipfile
import numpy as np
import yaml
from convert_rig_to_okvis import sha
from pipeline_layout import read_manifest


def semantic_config(path):
    c=yaml.safe_load('\n'.join(path.read_text().splitlines()[1:]))
    for camera in c['cameras']:camera['mask_file']='sha256:'+sha(camera['mask_file'])
    return hashlib.sha256(json.dumps(c,sort_keys=True).encode()).hexdigest()


def main():
    p=argparse.ArgumentParser(__doc__);p.add_argument('--runs',nargs='+',required=True,type=Path);p.add_argument('--output',required=True,type=Path)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    records=[];provenance={};signatures=set()
    for run in a.runs:
        run=run.resolve();m=read_manifest(run)
        if m['status']!='complete':raise ValueError('Incomplete run '+str(run))
        v=json.loads((run/'03_vio/outputs/trajectory_summary.json').read_text());s=json.loads((run/'04_vio_comparison/summary/summary.json').read_text())
        signature=(m['binary']['sha256'],semantic_config(run/'03_vio/inputs/okvis2.yaml'),sha(run/'02_reference/inputs/groundtruth/data.csv'),tuple(sha(run/f'01_preparation/outputs/dataset/mav0/{name}/data.csv') for name in ('cam0','cam1','cam2','cam3','imu0')))
        signatures.add(signature)
        records.append(dict(run=str(run),input_groups=v['input_groups'],poses=v['poses'],missing_groups=v['missing_groups'],end_gap_s=v['end_gap_s'],
            wall_seconds=v['wall_seconds'],wall_realtime_factor=v['wall_realtime_factor'],peak_rss_kb=v['peak_rss_kb'],
            common_poses=s['common_timestamps']['n'],okvis_metrics=s['common']['okvis']['metrics'],basalt_metrics=s['common']['basalt']['metrics']))
        provenance[str(run)]=dict(binary_sha256=signature[0],semantic_config_sha256=signature[1],gt_sha256=signature[2],input_index_sha256=signature[3])
    if len(signatures)!=1:raise ValueError('Different binary/config/masks/GT/input signatures; cannot call these same-configuration repeats')
    output=dict(replicate_unit='Repeated execution of one recording; not independent datasets',same_configuration_verified=True,runs=records,
                wall_seconds_range=[min(r['wall_seconds'] for r in records),max(r['wall_seconds'] for r in records)],
                okvis_ape_rmse_range_m=[min(r['okvis_metrics']['ape_translation']['rmse'] for r in records),max(r['okvis_metrics']['ape_translation']['rmse'] for r in records)],
                limitations=['Cache/system load not isolated; resource measurements are descriptive.',
                             'Physical frame and marker calibration consistency not checked.',
                             'No cross-algorithm speed acceptance or independent accuracy acceptance.'])
    (a.output/'summary.json').write_text(json.dumps(output,indent=2)+'\n')
    os.environ['MPLCONFIGDIR']=str(a.output/'plot_cache')
    import matplotlib;matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(1,2,figsize=(13,4.8),layout='constrained')
    colors=['#D55E00','#009E73','#CC79A7'];styles=['-',':','-.']
    source_data={}
    def draw(ax,t,y,**kwargs):
        gaps=np.flatnonzero(np.diff(t)>1.5*np.median(np.diff(t)))+1
        ax.plot(np.insert(t,gaps,np.nan),np.insert(y,gaps,np.nan),**kwargs)
    for idx,record in enumerate(records):
        run=Path(record['run']);d=run/'04_vio_comparison/common';t0=json.loads((run/'03_vio/outputs/trajectory_summary.json').read_text())['input_first_imu_ns']/1e9
        e=np.loadtxt(d/'okvis/vio_matched.tum');t=e[:,0]-t0
        with zipfile.ZipFile(d/'okvis/ape_translation.zip') as z:err=np.load(z.open('error_array.npy'))
        if len(t)!=len(err):raise ValueError('APE sample/time mismatch')
        disp=np.linalg.norm(e[:,1:4]-e[0,1:4],axis=1)
        draw(axes[0],t,err,label=f'OKVIS run {idx+1}',color=colors[idx%3],linestyle=styles[idx%3],lw=1.3)
        draw(axes[1],t,disp,label=f'OKVIS run {idx+1}',color=colors[idx%3],linestyle=styles[idx%3],lw=1.3)
        np.savetxt(a.output/f'run{idx+1}_plot_data.csv',np.column_stack([t,err,disp]),delimiter=',',header='time_since_first_input_s,ape_m,displacement_from_own_first_pose_m',comments='')
        source_data[str(d/'okvis/ape_translation.zip')]=sha(d/'okvis/ape_translation.zip')
        source_data[str(d/'okvis/vio_matched.tum')]=sha(d/'okvis/vio_matched.tum')
        if idx==0:
            b=np.loadtxt(d/'basalt/vio_matched.tum');g=np.loadtxt(d/'basalt/mocap_at_vio.tum')
            with zipfile.ZipFile(d/'basalt/ape_translation.zip') as z:be=np.load(z.open('error_array.npy'))
            bt=b[:,0]-t0;bd=np.linalg.norm(b[:,1:4]-b[0,1:4],axis=1);gd=np.linalg.norm(g[:,1:4]-g[0,1:4],axis=1)
            draw(axes[0],bt,be,label='Basalt baseline',color='#0072B2',linestyle='--',lw=1.6)
            draw(axes[1],bt,bd,label='Basalt baseline',color='#0072B2',linestyle='--',lw=1.6)
            draw(axes[1],bt,gd,label='Mocap GT',color='#000000',linestyle='-',lw=1.)
            np.savetxt(a.output/'baseline_plot_data.csv',np.column_stack([bt,be,bd,gd]),delimiter=',',header='time_s,ape_m,basalt_displacement_m,gt_displacement_m',comments='')
            for f in [d/'basalt/ape_translation.zip',d/'basalt/vio_matched.tum',d/'basalt/mocap_at_vio.tum']:source_data[str(f)]=sha(f)
    axes[0].set_title('Full-trajectory SE(3) APE; no scale correction')
    axes[1].set_title('Displacement relative to each own first pose')
    for ax in axes:
        ax.set_yscale('symlog',linthresh=.001,base=10);ax.set_ylim(bottom=0)
        ax.set(xlabel='Seconds since first input group',ylabel='Metres (symlog base 10; linear below 1 mm)')
        ax.legend(fontsize=8);ax.grid(alpha=.25,which='both')
    fig.savefig(a.output/'comparison.png',dpi=180,facecolor='white');fig.savefig(a.output/'comparison.svg',facecolor='white');plt.close(fig)
    figure_info=dict(raw_sources=source_data,source_code_sha256=sha(__file__),configuration_signatures=provenance,
        transformations=['APE arrays from evo full-trajectory SE3 without scale adjustment','Own-first-position subtraction and Euclidean norm for displacement','Symlog base 10 with 1 mm linear threshold; zeros retained','Line breaks at timestamp gaps over 1.5 times median interval'],
        uncertainty='Individual repeated executions shown; no confidence interval; n='+str(len(records))+' repeats of one recording',
        image=dict(width_px=2340,height_px=864,dpi=180),audience='Local engineering validation report; no journal compliance claim')
    (a.output/'figure_provenance.json').write_text(json.dumps(figure_info,indent=2)+'\n')
    lines=['# Repeated VIO validation','',f'{len(records)} executions of the same recording, binary and semantic configuration. Cache/system load were not isolated.','',
        '| Run | Poses | Common GT poses | APE RMSE (m) | p95 (m) | VIO wall (s) | Wall/data duration | Peak RSS (GiB) |',
        '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for r in records:
        e=r['okvis_metrics']['ape_translation'];lines.append(f"| {Path(r['run']).name} | {r['poses']} | {r['common_poses']} | {e['rmse']:.6f} | {e['p95']:.6f} | {r['wall_seconds']:.3f} | {r['wall_realtime_factor']:.3f} | {r['peak_rss_kb']/1048576:.3f} |")
    baseline=records[0]['basalt_metrics']['ape_translation']
    lines+=['',f"Basalt fixed baseline APE RMSE: {baseline['rmse']:.6f} m; p95: {baseline['p95']:.6f} m.",'',
        '![Repeated APE and displacement on symlog axes; zeros retained, individual executions shown.](comparison.png)','',
        'Left: full-trajectory rigid alignment can move the initial segment when the trajectory diverges. Right: displacement magnitude is independent of a rigid world rotation; it makes late divergence visible without that alignment. All source values and transformations are saved beside the figure.']
    (a.output/'report.md').write_text('\n'.join(lines)+'\n')
if __name__=='__main__':main()
