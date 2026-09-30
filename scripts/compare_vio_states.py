#!/usr/bin/env python3
"""Compare native OKVIS state rows, retaining integer timestamps and bias columns."""
import argparse
import csv
import hashlib
import itertools
import json
from pathlib import Path
import numpy as np

FIELDS = ['px','py','pz','qx','qy','qz','qw','vx','vy','vz','bgx','bgy','bgz','bax','bay','baz']

def read_states(path):
    stamps, values = [], []
    with Path(path).open() as stream:
        for row in csv.reader(stream):
            if not row or row[0].strip().startswith('#') or row[0].strip() == 'timestamp': continue
            while row and not row[-1].strip(): row.pop()
            if len(row) != 17: raise ValueError('Expected timestamp plus 16 state values')
            stamp = int(row[0]); value = [float(x) for x in row[1:]]
            if stamps and stamp <= stamps[-1]: raise ValueError('Non-monotonic timestamps')
            if not np.all(np.isfinite(value)): raise ValueError('Nonfinite state')
            if abs(np.linalg.norm(value[3:7])-1) > 1e-5: raise ValueError('Non-unit quaternion')
            stamps.append(stamp); values.append(value)
    if not stamps: raise ValueError('Empty states')
    return np.asarray(stamps,dtype=np.int64), np.asarray(values)

def compare(a, b):
    ta, va = read_states(a); tb, vb = read_states(b)
    result = dict(a=str(a), b=str(b), rows_a=len(ta), rows_b=len(tb),
                  timestamps_equal=np.array_equal(ta,tb),
                  csv_sha256_a=hashlib.sha256(Path(a).read_bytes()).hexdigest(),
                  csv_sha256_b=hashlib.sha256(Path(b).read_bytes()).hexdigest())
    result['byte_identical'] = result['csv_sha256_a'] == result['csv_sha256_b']
    result['states_exact'] = False
    if not result['timestamps_equal']: return result
    different = va != vb
    result['states_exact'] = not bool(different.any())
    result['pose_exact'] = not bool(different[:,:7].any())
    result['fields'] = {}
    for i, field in enumerate(FIELDS):
        indices = np.flatnonzero(different[:,i])
        result['fields'][field] = dict(max_abs_difference=float(np.abs(va[:,i]-vb[:,i]).max()),
            first_different_timestamp_ns=int(ta[indices[0]]) if len(indices) else None)
    indices = np.flatnonzero(different.any(axis=1))
    result['first_different_time_s'] = float((ta[indices[0]]-ta[0])/1e9) if len(indices) else None
    qa=va[:,3:7]/np.linalg.norm(va[:,3:7],axis=1)[:,None]
    qb=vb[:,3:7]/np.linalg.norm(vb[:,3:7],axis=1)[:,None]
    qb *= np.where(np.sum(qa*qb,axis=1)<0,-1,1)[:,None]
    angle=4*np.arctan2(np.linalg.norm(qa-qb,axis=1),np.linalg.norm(qa+qb,axis=1))
    result['max_rotation_difference_rad']=float(angle.max())
    for name, sl in [('position',slice(0,3)),('velocity',slice(7,10)),('gyro_bias',slice(10,13)),('accel_bias',slice(13,16))]:
        result['max_'+name+'_difference']=float(np.linalg.norm(va[:,sl]-vb[:,sl],axis=1).max())
    return result

def compare_group(paths):
    if len(paths)<2: raise ValueError('Need at least two independent runs')
    pairs=[compare(a,b) for a,b in itertools.combinations(paths,2)]
    return dict(strict_pass=all(p['states_exact'] for p in pairs),pairs=pairs)

if __name__=='__main__':
    p=argparse.ArgumentParser(__doc__);p.add_argument('trajectories',nargs='+',type=Path);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();result=compare_group(a.trajectories)
    with a.output.open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps({'strict_pass':result['strict_pass']}))
