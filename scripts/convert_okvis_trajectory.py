#!/usr/bin/env python3
"""Strict, integer-nanosecond trajectory normalization."""
import argparse
import csv
import json
import math
from pathlib import Path


def load(path, order='xyzw'):
    rows=[]
    for r in csv.reader(Path(path).read_text().splitlines()):
        if not r or r[0].lstrip().startswith('#') or r[0].strip()=='timestamp':continue
        if len(r)<8:raise ValueError('Expected at least 8 columns')
        t=int(r[0]);v=list(map(float,r[1:8]))
        if not all(math.isfinite(x) for x in v):raise ValueError('Nonfinite pose')
        if abs(sum(x*x for x in v[3:])-1)>1e-5:raise ValueError('Non-unit quaternion')
        if rows and t<=rows[-1][0]:raise ValueError('Duplicate or non-monotonic timestamp')
        if order=='wxyz':v=v[:3]+v[4:7]+[v[3]]
        rows.append((t,v))
    if not rows:raise ValueError('Empty trajectory')
    return rows


def tum_time(t):return f'{t//1000000000}.{t%1000000000:09d}'


def write(rows, output):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    with (output/'trajectory.tum').open('w') as f:
        for t,v in rows:f.write(tum_time(t)+' '+' '.join(format(x,'.17g') for x in v)+'\n')
    with (output/'trajectory_euroc.csv').open('w') as f:
        f.write('#timestamp [ns],px,py,pz,qw,qx,qy,qz\n');w=csv.writer(f)
        for t,v in rows:w.writerow([t,*v[:3],v[6],*v[3:6]])
    report=dict(poses=len(rows),first_timestamp_ns=rows[0][0],last_timestamp_ns=rows[-1][0],
        max_gap_ns=max((b[0]-a[0] for a,b in zip(rows,rows[1:])),default=0),time_conversion='integer ns split into exact decimal seconds')
    (output/'trajectory_summary.json').write_text(json.dumps(report,indent=2)+'\n')
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser(__doc__);p.add_argument('input',type=Path);p.add_argument('output',type=Path)
    p.add_argument('--order',choices=['xyzw','wxyz'],default='xyzw');a=p.parse_args();write(load(a.input,a.order),a.output)
