#!/usr/bin/env python3
"""Export opt-in VIO log records and compare fixed windows; no estimator feedback."""
import argparse
import csv
import json
from pathlib import Path
import re
import numpy as np


def finite_stats(values):
    values=np.asarray(values,dtype=float)
    valid=values[np.isfinite(values)]
    result=dict(n=len(values),nonfinite=int(len(values)-len(valid)))
    if len(valid):
        result.update(median=float(np.median(valid)),p95=float(np.quantile(valid,.95)),
                      min=float(valid.min()),max=float(valid.max()))
    return result


def trajectory_bias(path, origin_ns):
    records=[]
    with path.open() as f:
        for row in csv.DictReader(f,skipinitialspace=True):
            stamp=int(row['timestamp'])
            record=dict(timestamp_ns=stamp,time_s=(stamp-origin_ns)/1e9)
            for prefix in ('b_g','b_a'):
                for axis in 'xyz':record[prefix+'_'+axis]=float(row[prefix+'_'+axis])
            records.append(record)
    stamps=[r['timestamp_ns'] for r in records]
    if any(b<=a for a,b in zip(stamps,stamps[1:])):
        raise ValueError('Bias timestamps must be strictly increasing')
    return records


def summarize(log, output, origin_ns, trajectory=None):
    output.mkdir(parents=True, exist_ok=False)
    records={name:[] for name in ('VIO_SOLVER','VIO_CONSTRAINT','VIO_FRONTEND','VIO_MATCH','FEATURE_AUDIT','VIO_RANSAC','VIO_REJECTION')}
    for line in log.read_text().splitlines():
        for name in records:
            marker=name+' '
            if marker not in line: continue
            tail=line.split(marker,1)[1]
            record={k:float(v) if any(c in v.lower() for c in '.enai') else int(v)
                    for k,v in re.findall(r'(\w+)=([^\s]+)',tail)}
            record['time_s']=(int(record['timestamp_ns'])-origin_ns)/1e9
            records[name].append(record)
    if trajectory:
        records['VIO_BIAS']=trajectory_bias(trajectory,origin_ns)
        bias_stamps={r['timestamp_ns'] for r in records['VIO_BIAS']}
        if not all(r['timestamp_ns'] in bias_stamps for name,rows in records.items() for r in rows):
            raise ValueError('Solver timestamp absent from bias trajectory')
    windows={'trigger_34_38':(34,38),'second_43_46':(43,46),'late_60_70':(60,70),'before_30_35':(30,35),'trigger_35_37':(35,37),'before_40_44':(40,44),
             'event_44_55':(44,55),'normal_55_63':(55,63),'event_63_66':(63,66),'after_66_80':(66,81)}
    report={}
    for name,rows in records.items():
        if not rows:continue
        with (output/(name.lower()+'.csv')).open('w') as f:
            writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
        report[name]={}
        for window,(lo,hi) in windows.items():
            subset=[r for r in rows if lo<=r['time_s']<hi]
            if not subset:continue
            report[name][window]={k:finite_stats([r[k] for r in subset])
                                  for k in rows[0] if k not in ('time_s','timestamp_ns','camera')}
    (output/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    import os
    os.environ.setdefault('MPLCONFIGDIR',str(output/'plot_cache'))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(4,1,figsize=(12,10),sharex=True,layout='constrained')
    for metric,label,ax in [('map_matches','Map matches',axes[0]),('map_tracking_quality','Spatial tracking quality',axes[1])]:
        rows=records['VIO_FRONTEND'];ax.plot([r['time_s'] for r in rows],[r[metric] for r in rows],lw=.7);ax.set_ylabel(label)
    rows=[r for r in records['VIO_SOLVER'] if not r.get('only_newest',0)]
    axes[2].plot([r['time_s'] for r in rows],[r['imu_sse']/max(1,15*r['imu_links']) for r in rows],lw=.7)
    axes[2].set_ylabel('Retained IMU SSE / (15 links)');axes[2].set_yscale('symlog',linthresh=1)
    for camera in range(4):
        rows=[r for r in records['VIO_CONSTRAINT'] if r['camera']==camera]
        axes[3].plot([r['time_s'] for r in rows],[r['temporal'] for r in rows],label=f'cam{camera}',lw=.7)
    axes[3].set_ylabel('Temporal observations');axes[3].legend(ncol=4);axes[3].set_xlabel('Seconds since first input frame')
    for ax in axes:
        ax.axvspan(44,55,color='orange',alpha=.12);ax.axvspan(63,66,color='orange',alpha=.12);ax.grid(alpha=.2)
    fig.savefig(output/'diagnostics.png',dpi=160);plt.close(fig)
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(__doc__);p.add_argument('--log',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--origin-ns',type=int,required=True)
    p.add_argument('--trajectory',type=Path,help='Online CSV for exact bias/timestamp association')
    a=p.parse_args();summarize(a.log,a.output,a.origin_ns,a.trajectory)
