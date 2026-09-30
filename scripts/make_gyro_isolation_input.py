#!/usr/bin/env python3
"""DIAGNOSTIC ONLY: isolate short gyro impulses without using ground truth.

Centered 11-sample medians use future samples. This is an offline causal-impact
experiment, NOT a deployable IMU filter or evidence of a hardware fault.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import numpy as np
from scipy.ndimage import median_filter


def main():
    p=argparse.ArgumentParser(__doc__);p.add_argument('--input',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=False)
    lines=a.input.read_text().splitlines()
    rows=list(csv.reader(l for l in lines if l and not l.startswith('#')))
    gyro=np.array([[float(v) for v in row[1:4]] for row in rows])
    median=median_filter(gyro,size=(11,1),mode='nearest')
    mad=median_filter(abs(gyro-median),size=(11,1),mode='nearest')
    flags=abs(gyro-median)>np.maximum(.5,6*1.4826*mad)
    changes=[]
    for i in np.flatnonzero(flags.any(axis=1)):
        before=rows[i][1:4].copy()
        for axis in range(3):
            if flags[i,axis]:rows[i][axis+1]=format(median[i,axis],'.17g')
        changes.append(dict(row=int(i),timestamp_ns=int(rows[i][0]),before=before,after=rows[i][1:4]))
    with (a.output/'data.csv').open('w') as f:csv.writer(f).writerows(rows)
    meta=dict(purpose='diagnostic_only_not_final_fix',uses_gt=False,causal_filter=False,
              input=str(a.input.resolve()),input_sha256=hashlib.sha256(a.input.read_bytes()).hexdigest(),
              output_sha256=hashlib.sha256((a.output/'data.csv').read_bytes()).hexdigest(),
              window_samples=11,min_deviation_rad_s=.5,mad_multiplier=6*1.4826,changes=changes)
    (a.output/'changes.json').write_text(json.dumps(meta,indent=2)+'\n')
    print(f'Flagged {len(changes)} rows; timestamps and accelerometer unchanged.')


if __name__=='__main__':main()
