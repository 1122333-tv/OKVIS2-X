#!/usr/bin/env python3
"""Validate exact repeatability, fixed frame pairs and the prespecified drift gates."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import numpy as np
from compare_vio_states import compare_group, read_states


def validate_final_exports(runs):
    """Include all serialized metadata, not just the 16 physical state columns."""
    files={name:[] for name in ['okvis2-vio-final_trajectory.csv','okvis2-vio-final-ba_trajectory.csv']}
    for run in runs:
        timestamps,_=read_states(run/'outputs/okvis2-vio_trajectory.csv')
        for name,hashes in files.items():
            path=run/'outputs'/name
            with path.open() as stream:rows=list(csv.reader(stream))
            if len(rows[0])!=21 or rows[0][-1].strip()!='keyframeId':
                raise ValueError('Incomplete final CSV metadata header')
            if any(len(row)!=21 for row in rows[1:]):raise ValueError('Invalid final CSV row width')
            if [int(row[0]) for row in rows[1:]]!=timestamps.tolist():
                raise ValueError('Final CSV timestamp coverage changed')
            if any(int(row[17])!=0 or int(row[19])!=0 for row in rows[1:]):
                raise ValueError('Unexpected GPS metadata in pure VIO')
            values=np.asarray([[float(v) for v in row[1:17]] for row in rows[1:]])
            if not np.isfinite(values).all():raise ValueError('Nonfinite final CSV state')
            hashes.append(hashlib.sha256(path.read_bytes()).hexdigest())
        if len({hashes[-1] for hashes in files.values()})!=1:
            raise ValueError('Final exports differ despite disabled final BA')
    return dict(sha256=files,byte_identical=all(len(set(v))==1 for v in files.values()))


def validate(baseline, candidate, check_final_exports=False):
    if len(baseline)!=3 or len(candidate)!=3:raise ValueError('Exactly three independent launches per group required')
    if len({p.resolve() for p in baseline+candidate})!=6:raise ValueError('Runs must be independent')
    groups={};summaries={};manifests=[]
    for name,runs in [('baseline',baseline),('candidate',candidate)]:
        for run in runs:
            m=json.loads((run/'experiment.json').read_text())
            if m['status']!='complete' or m['diagnostic_input_only']:raise ValueError('Only completed runs with original inputs are eligible')
            if 'SAMPLING deterministic=1 seed=12345' not in (run/'stage.log').read_text():raise ValueError('Fixed sampling not confirmed')
            manifests.append(m)
        groups[name]=compare_group([r/'outputs/okvis2-vio_trajectory.csv' for r in runs])
        groups[name]['byte_identical']=all(p['byte_identical'] for p in groups[name]['pairs'])
        if check_final_exports:groups[name]['final_exports']=validate_final_exports(runs)
        summaries[name]=[json.loads((r/'analysis/summary.json').read_text()) for r in runs]
    if len({m['binary_sha256'] for m in manifests})!=1:raise ValueError('All controls/candidates must use the same binary')
    for key in ['input_hashes_sha256','input_indices','masks','runtime_libraries']:
        if any(m[key]!=manifests[0][key] for m in manifests[1:]):raise ValueError('Frozen inputs/runtime changed: '+key)
    reference=summaries['baseline'][0]
    for s in summaries['baseline']+summaries['candidate']:
        if (s['poses'],s['common_poses'],s['reference_sha256'])!=(reference['poses'],reference['common_poses'],reference['reference_sha256']):raise ValueError('Coverage/reference changed')
        if {k:v['pair_sha256'] for k,v in s['metrics'].items()}!={k:v['pair_sha256'] for k,v in reference['metrics'].items()}:raise ValueError('Reference frame pairs changed')
    def median(group,path):
        def value(s):
            for key in path:s=s[key]
            return s
        return float(np.median([value(s) for s in summaries[group]]))
    checks={}
    def add(label,path,limit):
        base=median('baseline',path);value=median('candidate',path);threshold=limit(base)
        checks[label]=dict(baseline=base,candidate=value,limit=threshold,pass_gate=value<=threshold)
    add('ape_rmse',['ape','rmse'],lambda b:b*.5)
    for window in ['event_44_55','event_63_66']:
        for metric in ['rmse','p95','max']:
            add(window+':'+metric,['metrics','0.1m','windows',window,'translation',metric],lambda b:b*.5)
    for window in ['normal_0_44','normal_55_63','normal_66_end']:
        add(window+':rmse',['metrics','0.1m','windows',window,'translation','rmse'],lambda b:b+max(b*.1,.001))
    local_checks={}
    for window in ['pre_trigger_15_35','trigger_34_38']:
        if window not in reference['metrics']['0.1m']['windows']:continue
        path=['metrics','0.1m','windows',window,'translation','rmse']
        base=median('baseline',path);value=median('candidate',path);limit=base+max(base*.1,.001)
        local_checks[window]=dict(baseline=base,candidate=value,limit=limit,pass_gate=value<=limit)
    return dict(groups=groups,checks=checks,
                additional_window_checks=local_checks,
                repeatability_scope='online states and all CSV bytes' if check_final_exports else 'online states and CSV bytes only',
                repeatability_pass=all(g['strict_pass'] and g['byte_identical'] and
                                       g.get('final_exports',{}).get('byte_identical',True) for g in groups.values()),
                relative_accuracy_pass=all(c['pass_gate'] for c in checks.values()),
                all_window_accuracy_pass=all(c['pass_gate'] for c in list(checks.values())+list(local_checks.values())),
                interpretation='Relative gates against a divergent baseline do not alone establish a resolved accuracy problem.',
                baseline_runs=list(map(str,baseline)),candidate_runs=list(map(str,candidate)))

if __name__=='__main__':
    p=argparse.ArgumentParser(__doc__);p.add_argument('--baseline',nargs=3,type=Path,required=True)
    p.add_argument('--candidate',nargs=3,type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--check-final-exports',action='store_true')
    a=p.parse_args();result=validate(a.baseline,a.candidate,a.check_final_exports)
    with a.output.open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps({k:result[k] for k in ['repeatability_pass','relative_accuracy_pass']}))
