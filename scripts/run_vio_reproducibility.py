#!/usr/bin/env python3
"""Run immutable, sequential thread-profile comparisons using frozen original inputs."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
import uuid
import yaml
from compare_vio_states import read_states, compare_group
from pipeline_layout import sha, dump
from convert_rig_to_okvis import write_yaml

PROFILES={'solver-single': {'estimator_parameters.realtime_num_threads':1},
          'frontend-single': {'estimator_parameters.realtime_num_threads':1,
                              'frontend_parameters.parallelise_detection':False,
                              'frontend_parameters.num_matching_threads':1}}

def profile_config(original, profile):
    cfg=copy.deepcopy(original)
    if cfg['estimator_parameters']['enforce_realtime']: raise ValueError('Expected offline baseline')
    if cfg['estimator_parameters']['do_loop_closures'] or cfg['estimator_parameters']['do_final_ba']: raise ValueError('Expected pure VIO')
    if len(cfg['cameras'])!=4: raise ValueError('Expected four cameras')
    for dotted,value in PROFILES[profile].items():
        group,key=dotted.split('.');cfg[group][key]=value
    return cfg

def main():
    p=argparse.ArgumentParser(__doc__)
    for name in ('baseline','binary','analyzer','input-hashes','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--profiles',nargs='+',choices=list(PROFILES),default=list(PROFILES))
    p.add_argument('--repeats',type=int,default=3)
    a=p.parse_args()
    if a.repeats<2:p.error('At least two independent runs required')
    if len(set(a.profiles))!=len(a.profiles):p.error('Duplicate profile')
    root=Path(__file__).resolve().parents[1];base=a.baseline.resolve();binary=a.binary.resolve();out=a.output.resolve()
    out.mkdir(parents=True,exist_ok=False)
    hashes=json.loads(a.input_hashes.read_text())
    print('Verifying frozen input content',flush=True)
    for path,expected in hashes.items():
        if sha(path)!=expected:raise ValueError('Frozen input changed: '+path)
    cfg_text=(base/'03_vio/inputs/okvis2.yaml').read_text()
    cfg=yaml.safe_load('\n'.join(x for x in cfg_text.splitlines() if not x.startswith('%YAML:')))
    for camera in cfg['cameras']:
        path=Path(camera['mask_file']);hashes[str(path)]=sha(path)
    for path in (base/'03_vio/inputs/okvis2.yaml', base/'04_vio_comparison/common/okvis/mocap_at_vio.tum'):
        hashes[str(path)]=sha(path)
    # Freeze the runtime bundle used by every child process.
    bundle=out/'binary';bundle.mkdir()
    for name in ('okvis_app_synchronous','small_voc.yml.gz','CMakeCache.txt'):
        shutil.copy2(binary if name=='okvis_app_synchronous' else binary.parent/name,bundle/name)
    binary=bundle/'okvis_app_synchronous'
    shutil.copy2(a.analyzer,out/'analyze_vio_drift.py');shutil.copy2(__file__,out/Path(__file__).name)
    shutil.copy2(root/'scripts/compare_vio_states.py',out/'compare_vio_states.py')
    dump(out/'input_hashes.json',hashes)
    env=dict(os.environ,OKVIS_FEATURE_AUDIT='1',MPLBACKEND='Agg',PYTHONPATH=str(root/'scripts'))
    dump(out/'study.json',dict(baseline=str(base),binary_sha256=sha(binary),original_config_sha256=sha(base/'03_vio/inputs/okvis2.yaml'),
         commit=subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip(),
         profiles={k:PROFILES[k] for k in a.profiles},repeats=a.repeats,platform=platform.platform(),
         invocation=sys.argv,environment={k:env.get(k) for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS')},
         binary_bundle={p.name:sha(p) for p in bundle.iterdir()},analyzer_sha256=sha(out/'analyze_vio_drift.py')))
    expected_stamps,_=read_states(base/'03_vio/outputs/okvis2-vio_trajectory.csv')
    completed=[];groups={}
    for profile in a.profiles:
        group=[]
        for repeat in range(1,a.repeats+1):
            run=out/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+profile+f'_{repeat}_'+uuid.uuid4().hex[:6])
            run.mkdir();(run/'outputs').mkdir()
            config=run/'config.yaml';write_yaml(config,profile_config(cfg,profile))
            command=[str(binary),str(config),str(base/'01_preparation/outputs/dataset/mav0'),str(run/'outputs'),'--deterministic','1']
            manifest=dict(profile=profile,repeat=repeat,sampling={'deterministic':True,'seed':12345},command=command,binary_sha256=sha(binary),config_sha256=sha(config),status='running',baseline=str(base))
            dump(run/'manifest.json',manifest);print('START',run,flush=True);start=time.monotonic()
            try:
                with (run/'stage.log').open('x') as log:subprocess.run(command,env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
                trajectory=run/'outputs/okvis2-vio_trajectory.csv';stamps,_=read_states(trajectory)
                if not __import__('numpy').array_equal(stamps,expected_stamps):raise ValueError('Output timestamp coverage changed')
                if 'SAMPLING deterministic=1 seed=12345' not in (run/'stage.log').read_text():raise ValueError('Sampling mode not confirmed')
                manifest['vio_wall_seconds']=time.monotonic()-start
                analysis=[sys.executable,str(out/'analyze_vio_drift.py'),'--trajectory',str(trajectory),'--baseline',str(base),'--output',str(run/'analysis')]
                manifest['analysis_command']=analysis
                with (run/'analysis.log').open('x') as log:subprocess.run(analysis,env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
                manifest.update(status='complete',trajectory_sha256=sha(trajectory),poses=len(stamps))
            except BaseException as e:
                manifest.update(status='failed',error=str(e));dump(run/'manifest.json',manifest);raise
            dump(run/'manifest.json',manifest);completed.append(str(run));group.append(trajectory)
            dump(out/'completed.json',completed);print('COMPLETE',run,flush=True)
        groups[profile]=compare_group(group);dump(out/'comparisons.json',groups)
        print('GROUP',profile,'strict_pass=',groups[profile]['strict_pass'],flush=True)
    for path,expected in hashes.items():
        if sha(path)!=expected:raise ValueError('Input changed during study: '+path)
    for name,expected in json.loads((out/'study.json').read_text())['binary_bundle'].items():
        if sha(bundle/name)!=expected:raise ValueError('Binary bundle changed')
    dump(out/'preservation.json',dict(inputs_unchanged=True,files=len(hashes),binary_unchanged=True))
    print('ALL COMPLETE',flush=True)

if __name__=='__main__':main()
