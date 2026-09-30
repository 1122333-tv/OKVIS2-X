#!/usr/bin/env python3
"""Validate exact repeatability, fixed frame pairs and the prespecified drift gates."""
import argparse
import json
from pathlib import Path
import numpy as np
from compare_vio_states import compare_group


def validate(baseline, candidate):
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
    return dict(groups=groups,checks=checks,
                repeatability_pass=all(g['strict_pass'] and g['byte_identical'] for g in groups.values()),
                relative_accuracy_pass=all(c['pass_gate'] for c in checks.values()),
                interpretation='Relative gates against a divergent baseline do not alone establish a resolved accuracy problem.',
                baseline_runs=list(map(str,baseline)),candidate_runs=list(map(str,candidate)))

if __name__=='__main__':
    p=argparse.ArgumentParser(__doc__);p.add_argument('--baseline',nargs=3,type=Path,required=True)
    p.add_argument('--candidate',nargs=3,type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();result=validate(a.baseline,a.candidate)
    with a.output.open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps({k:result[k] for k in ['repeatability_pass','relative_accuracy_pass']}))
