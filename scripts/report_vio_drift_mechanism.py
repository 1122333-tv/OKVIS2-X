#!/usr/bin/env python3
"""Plot the saved trigger chain; diagnostic logs never feed the estimator."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import numpy as np
from report_reproducible_drift import read_records


def main():
    p=argparse.ArgumentParser(__doc__)
    p.add_argument('--runs',nargs='+',type=Path,required=True)
    p.add_argument('--imu',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(5,2,figsize=(14,14),layout='constrained')
    sources={};events={};origin=None
    for run in a.runs:
        summary=json.loads((run/'analysis/summary.json').read_text())
        if origin is None:origin=summary['origin_ns']
        if origin!=summary['origin_ns']:raise ValueError('Different input origins')
        records=read_records(run/'stage.log')
        label=run.name.split('_',1)[1].rsplit('_',1)[0]
        matches={r['timestamp_ns']:r for r in records['VIO_MATCH']}
        rejection={}
        for r in records['VIO_REJECTION']:
            rejection.setdefault((r['timestamp_ns'],r['camera']),r['kept'])
        temporal={}
        for r in records['VIO_CONSTRAINT']:
            temporal[r['timestamp_ns'],r['camera']]=r['temporal']
        rows=[]
        for r in records['VIO_RECOVERY']:
            stamp=r['timestamp_ns'];m=matches[stamp]
            angle=float('nan')
            if r['accepted']:
                q=np.array([m['predicted_q'+c] for c in 'xyzw'])
                v=np.array([r['visual_q'+c] for c in 'xyzw'])
                angle=float(np.rad2deg(2*np.arccos(np.clip(abs(q@v)/(np.linalg.norm(q)*np.linalg.norm(v)),0,1))))
            rows.append(dict(timestamp_ns=stamp,time_s=(stamp-origin)/1e9,
                             prediction_visual_deg=angle,accepted_inliers=r['inliers'] if r['accepted'] else 0,
                             recovery=r['activated'],first_prune_kept=sum(rejection.get((stamp,c),0) for c in range(4)),
                             temporal=sum(temporal.get((stamp,c),0) for c in range(4))))
        with (a.output/(label+'_chain.csv')).open('w') as f:
            writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
        full=[r for r in records['VIO_SOLVER'] if not r['only_newest']]
        for col,(lo,hi) in enumerate([(34,38),(43,46)]):
            subset=[r for r in rows if lo<=r['time_s']<hi]
            t=[r['time_s'] for r in subset]
            axes[1,col].plot(t,[r['prediction_visual_deg'] for r in subset],'.',label=label,ms=3)
            axes[2,col].plot(t,[r['first_prune_kept'] for r in subset],label=label,lw=.8)
            axes[3,col].plot(t,[r['temporal'] for r in subset],label=label,lw=.8)
            subset=[r for r in full if lo<=(r['timestamp_ns']-origin)/1e9<hi]
            axes[4,col].plot([(r['timestamp_ns']-origin)/1e9 for r in subset],
                             [r['latest_imu_weight'] for r in subset],label=label,lw=.8)
        events[label]={str(stamp):{tag:[r for r in rr if r['timestamp_ns']==stamp] for tag,rr in records.items()}
                       for stamp in (80681030516,89114510516)}
        sources[str((run/'stage.log').resolve())]=hashlib.sha256((run/'stage.log').read_bytes()).hexdigest()
    imu=np.loadtxt(a.imu,delimiter=',',skiprows=1)
    t=(imu[:,0]-origin)/1e9
    for col,(lo,hi) in enumerate([(34,38),(43,46)]):
        sel=(t>=lo)&(t<hi)
        axes[0,col].plot(t[sel],np.linalg.norm(imu[sel,1:4],axis=1),color='black',lw=.8,label='Original gyro norm')
        for row,title in enumerate(['Gyroscope norm (rad/s)','Prediction vs accepted visual pose (deg)',
                                    'Observations after first pruning','Temporal observations after full solve',
                                    'Latest IMU robust weight after full solve']):
            ax=axes[row,col];ax.set_xlim(lo,hi);ax.set_ylabel(title);ax.grid(alpha=.2)
            ax.axvline(36.067299 if col==0 else 44.500779,color='gray',ls=':',lw=.8)
            ax.legend(fontsize=7)
        axes[1,col].set_ylim(bottom=0)
        axes[4,col].set_yscale('log');axes[4,col].set_xlabel('Seconds since first input frame')
    fig.savefig(a.output/'mechanism.png',dpi=170);plt.close(fig)
    (a.output/'events.json').write_text(json.dumps(events,indent=2))
    sources[str(a.imu.resolve())]=hashlib.sha256(a.imu.read_bytes()).hexdigest()
    (a.output/'provenance.json').write_text(json.dumps(sources,indent=2))


if __name__=='__main__':main()
