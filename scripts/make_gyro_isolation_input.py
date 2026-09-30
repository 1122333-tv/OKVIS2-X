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


def isolate(input_path, output):
    output.mkdir(parents=True,exist_ok=False)
    raw_lines=input_path.read_bytes().splitlines(keepends=True)
    indices=[i for i,line in enumerate(raw_lines) if line.strip() and not line.startswith(b'#')]
    rows=list(csv.reader(raw_lines[i].decode().strip() for i in indices))
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
    result=raw_lines.copy()
    for change in changes:
        i=change['row'];line_index=indices[i]
        original=raw_lines[line_index]
        ending=original[len(original.rstrip(b'\r\n')):]
        result[line_index]=','.join(rows[i]).encode()+ending
    (output/'data.csv').write_bytes(b''.join(result))
    meta=dict(purpose='diagnostic_only_not_final_fix',uses_gt=False,causal_filter=False,
              input=str(input_path.resolve()),input_sha256=hashlib.sha256(input_path.read_bytes()).hexdigest(),
              output_sha256=hashlib.sha256((output/'data.csv').read_bytes()).hexdigest(),
              window_samples=11,min_deviation_rad_s=.5,mad_multiplier=6*1.4826,changes=changes)
    (output/'changes.json').write_text(json.dumps(meta,indent=2)+'\n')
    return meta


def main():
    p=argparse.ArgumentParser(__doc__);p.add_argument('--input',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    meta=isolate(a.input,a.output)
    print(f"Flagged {len(meta['changes'])} rows; header, timestamps and accelerometer unchanged.")

if __name__=='__main__':main()
