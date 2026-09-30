#!/usr/bin/env python3
"""Plot velocity and bias from saved, full-precision online state CSVs."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import numpy as np


def main():
    p=argparse.ArgumentParser(__doc__)
    p.add_argument('--runs',nargs='+',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(3,1,figsize=(12,9),sharex=True,layout='constrained')
    origins=set();sources={}
    for run in a.runs:
        path=run/'outputs/okvis2-vio_trajectory.csv'
        with path.open() as f:rows=list(csv.DictReader(f,skipinitialspace=True))
        origin=int(rows[0]['timestamp']);origins.add(origin)
        times=np.array([(int(r['timestamp'])-origin)/1e9 for r in rows])
        if len(origins)!=1:raise ValueError('Different recording origins')
        label=run.name.split('_',1)[1].rsplit('_',1)[0]
        color={'recovery_control':'C0','visual_recovery':'C1','imu_huber5':'C2',
               'combined_recovery_huber5':'C3'}.get(label)
        for ax,prefix in zip(axes,['v_WS_W','b_g','b_a']):
            values=np.array([[float(r[prefix+'_'+c]) for c in 'xyz'] for r in rows])
            ax.plot(times,np.linalg.norm(values,axis=1),label=label,lw=1,color=color)
        sources[str(path.resolve())]=hashlib.sha256(path.read_bytes()).hexdigest()
    axes[0].set_yscale('symlog',linthresh=.05)
    for ax,label in zip(axes,['Estimated speed norm (m/s)','Gyroscope bias norm (rad/s)',
                              'Accelerometer bias norm (m/s²)']):
        ax.set_ylabel(label);ax.set_ylim(bottom=0);ax.grid(alpha=.2);ax.legend(fontsize=8)
        for lo,hi in [(34,38),(44,55),(63,66)]:ax.axvspan(lo,hi,color='gray',alpha=.08)
        for t in [36.067299,44.500779]:ax.axvline(t,color='black',ls=':',lw=.7)
    axes[-1].set_xlabel('Seconds since first input frame')
    fig.savefig(a.output/'velocity_bias.png',dpi=170);plt.close(fig)
    (a.output/'provenance.json').write_text(json.dumps(sources,indent=2))


if __name__=='__main__':main()
