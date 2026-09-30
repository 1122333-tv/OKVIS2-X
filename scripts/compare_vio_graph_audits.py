#!/usr/bin/env python3
"""Locate the first mismatch in optional, semantic optimization graph fingerprints."""
import argparse
import json
from pathlib import Path

FIELDS = ('parameters', 'residuals', 'values', 'measurements', 'parameter_order', 'residual_order')

def read_audit(path):
    records = []
    counts = {}
    for line in Path(path).read_text().splitlines():
        if 'REPRO_AUDIT ' not in line:
            continue
        record = dict(item.split('=', 1) for item in line.split('REPRO_AUDIT ', 1)[1].split())
        stamp = int(record['timestamp_ns'])
        if int(record['unknown']):
            raise ValueError('Unidentified parameter blocks; fingerprints cannot be compared safely')
        if record['phase'] == 'before':
            counts[stamp] = counts.get(stamp, 0) + 1
        elif record['phase'] != 'after':
            raise ValueError('Unknown solve phase')
        record['solve_index'] = counts.get(stamp, 0)
        record['timestamp_ns'] = stamp
        records.append(record)
    if not records:
        raise ValueError('No graph audit records')
    for i in range(0, len(records), 2):
        if i + 1 == len(records):
            raise ValueError('Incomplete solve audit')
        a, b = records[i:i+2]
        if (a['phase'], b['phase']) != ('before', 'after') or any(a[k] != b[k] for k in ('timestamp_ns','solve_index','iterations')):
            raise ValueError('Unpaired solve audit')
    return records

def compare_audits(a, b):
    left, right = read_audit(a), read_audit(b)
    result = {'records_a':len(left), 'records_b':len(right), 'structure_aligned':len(left)==len(right), 'first_differences':{}}
    for x, y in zip(left, right):
        if any(x[k] != y[k] for k in ('timestamp_ns','solve_index','phase','iterations')):
            result['structure_aligned'] = False
            result['unaligned_records'] = [x, y]
            break
        for key in FIELDS:
            if key not in result['first_differences'] and x[key] != y[key]:
                result['first_differences'][key] = dict(timestamp_ns=x['timestamp_ns'], time_s=(x['timestamp_ns']-left[0]['timestamp_ns'])/1e9,
                    solve_index=x['solve_index'], phase=x['phase'], iterations=int(x['iterations']), a=x[key], b=y[key])
    result['parameter_order_note'] = 'GetParameterBlocks address-ordered enumeration; not the internal solver program order'
    result['fingerprints_equal'] = result['structure_aligned'] and not result['first_differences']
    return result

if __name__ == '__main__':
    parser=argparse.ArgumentParser(__doc__)
    parser.add_argument('a',type=Path);parser.add_argument('b',type=Path);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();result=compare_audits(args.a,args.b)
    with args.output.open('x') as stream:json.dump(result,stream,indent=2)
    print(json.dumps(result,indent=2))
