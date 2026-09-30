#!/usr/bin/env python3
"""Render saved, fixed-pair evaluation and diagnostics; never rerun estimation."""
import argparse
import base64
import csv
import hashlib
import html
import json
import re
from pathlib import Path
import numpy as np


def read_records(path):
    records={}
    for line in path.read_text().splitlines():
        match=re.search(r'\b(VIO_\w+) (.*)',line)
        if not match:continue
        row={k:(float(v) if any(c in v.lower() for c in '.enai') else int(v))
             for k,v in re.findall(r'(\w+)=([^\s]+)',match[2])}
        if 'timestamp_ns' not in row:continue
        records.setdefault(match[1],[]).append(row)
    return records


def main():
    p=argparse.ArgumentParser(__doc__)
    p.add_argument('--runs',nargs='+',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(3,1,figsize=(12,10),sharex=True,layout='constrained')
    event,ea=plt.subplots(3,2,figsize=(13,10),layout='constrained')
    table=[];sources={};expected=None
    for run in a.runs:
        manifest=run/'reconciled_experiment.json'
        if not manifest.exists():manifest=run/'experiment.json'
        meta=json.loads(manifest.read_text())
        if meta['status']!='complete':raise ValueError('Incomplete run: '+str(run))
        summary=json.loads((run/'analysis/summary.json').read_text())
        hashes={k:v['pair_sha256'] for k,v in summary['metrics'].items()}
        if expected is None:expected=hashes
        if hashes!=expected:raise ValueError('Different reference frame pairs')
        label=run.name.split('_',1)[1].rsplit('_',1)[0]
        data=np.genfromtxt(run/'analysis/ape.csv',delimiter=',',names=True)
        rpe=np.genfromtxt(run/'analysis/rpe_0.1m.csv',delimiter=',',names=True)
        axes[0].plot(data['time_s'],data['pre_trigger_alignment_m'],label=label,lw=1)
        axes[1].plot(rpe['end_s'],rpe['translation_m'],label=label,lw=.7)
        records=read_records(run/'stage.log');origin=summary['origin_ns']
        last={}
        for row in records.get('VIO_CONSTRAINT',[]):last[row['timestamp_ns'],row['camera']]=row['temporal']
        totals={}
        for (t,c),n in last.items():totals[t]=totals.get(t,0)+n
        t=np.array(sorted(totals));n=np.array([totals[x] for x in t]);t=(t-origin)/1e9
        axes[2].plot(t,n,label=label,lw=.7)
        for col,(lo,hi) in enumerate([(34,38),(43,46)]):
            dm=(data['time_s']>=lo)&(data['time_s']<=hi);rm=(rpe['end_s']>=lo)&(rpe['end_s']<=hi);tm=(t>=lo)&(t<=hi)
            ea[0,col].plot(data['time_s'][dm],data['pre_trigger_alignment_m'][dm],label=label,lw=1)
            ea[1,col].plot(rpe['end_s'][rm],rpe['translation_m'][rm],label=label,lw=.8)
            ea[2,col].plot(t[tm],n[tm],label=label,lw=.8)
            for ax in ea[:,col]:ax.set_xlim(lo,hi)
        for name,rows in records.items():
            stamps={int(line.split(',')[0]) for line in (run/'outputs/okvis2-vio_trajectory.csv').read_text().splitlines()[1:] if line.strip()}
            if any(row['timestamp_ns'] not in stamps for row in rows):raise ValueError('Diagnostic timestamp mismatch')
            dest=a.output/(label+'_'+name.lower()+'.csv')
            fields=list(dict.fromkeys(k for row in rows for k in row))
            with dest.open('w') as f:
                w=csv.DictWriter(f,fieldnames=['time_s']+fields);w.writeheader()
                w.writerows(dict(time_s=(r['timestamp_ns']-origin)/1e9,**r) for r in rows)
        table.append(dict(label=label,run=str(run.resolve()),ape=summary['ape'],rpe=summary['metrics'],
                          poses=summary['poses'],common_poses=summary['common_poses'],
                          wall_seconds=meta.get('vio_wall_seconds'),diagnostic_input_only=meta['diagnostic_input_only'],
                          trajectory_sha256=summary['trajectory_sha256']))
        for f in [run/'stage.log',run/'analysis/summary.json',run/'outputs/okvis2-vio_trajectory.csv']:
            sources[str(f.resolve())]=hashlib.sha256(f.read_bytes()).hexdigest()
    for ax,label in zip(axes,['APE, fixed alignment 15-35 s (m)','RPE 0.1 m translation (m)','Temporal observations after full solve']):
        ax.set_ylabel(label);ax.grid(alpha=.2);ax.legend(fontsize=8)
        for x in [36.05,44.5]:ax.axvline(x,color='black',ls=':',lw=.7)
    for ax in axes[:2]:ax.set_yscale('symlog',linthresh=.01)
    axes[-1].set_xlabel('Seconds since first input frame')
    for col in range(2):
        for i,label in enumerate(['Fixed-alignment APE (m)','RPE 0.1 m (m)','Temporal observations']):
            ea[i,col].set_ylabel(label);ea[i,col].grid(alpha=.2);ea[i,col].legend(fontsize=7)
        ea[-1,col].set_xlabel('Seconds since first input frame')
    fig.savefig(a.output/'timeline.png',dpi=170);event.savefig(a.output/'events.png',dpi=170)
    plt.close(fig);plt.close(event)
    head='<meta charset="utf-8"><title>稳定模式漂移对照</title><style>body{font:16px sans-serif;max-width:1250px;margin:30px auto}table{border-collapse:collapse}td,th{padding:8px;border:1px solid #aaa}img{width:100%}</style>'
    body='<h1>稳定模式漂移对照</h1><p>所有曲线来自保存的完整运行。IMU isolation 是使用未来样本的离线机制干预，不能作为最终修复。全程图使用对称对数轴，局部图使用线性轴。时序观测数取每帧最后一次求解后的记录，只统计同时关联其他帧的地图点观测。</p><table><tr><th>实验</th><th>APE RMSE (m)</th><th>44–55 s RPE RMSE (m)</th><th>63–66 s RPE RMSE (m)</th><th>输出/评估</th></tr>'
    for row in table:
        windows=row['rpe']['0.1m']['windows']
        body+=f"<tr><td>{html.escape(row['label'])}</td><td>{row['ape']['rmse']:.6f}</td><td>{windows['event_44_55']['translation']['rmse']:.6f}</td><td>{windows['event_63_66']['translation']['rmse']:.6f}</td><td>{row['poses']}/{row['common_poses']}</td></tr>"
    body+='</table>'
    from PIL import Image
    for name in ['timeline.png','events.png']:
        path=a.output/name
        with Image.open(path) as im:im.verify()
        body+=f'<h2>{name}</h2><img alt="{name}" src="data:image/png;base64,{base64.b64encode(path.read_bytes()).decode()}">'
    (a.output/'report_embedded.html').write_text(head+body)
    (a.output/'metrics.json').write_text(json.dumps(table,indent=2))
    (a.output/'provenance.json').write_text(json.dumps(dict(source_sha256=sources,pair_sha256=expected,images_verified=True),indent=2))

if __name__=='__main__':main()
