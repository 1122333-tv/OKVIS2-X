#!/usr/bin/env python3
"""Sequential POC VIO batch using saved Basalt runs; never edits baseline inputs."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from datetime import datetime,timezone
import yaml
from pipeline_layout import sha,dump
from basalt_run_data import inspect

ROOT=Path(__file__).resolve().parents[1]
SCENES=['static_H_30s','static_V_30s','small_move','big_move','dynamic_background','static_H_30s_humanmove']


def checkpoint(path, value):
    temporary=path.with_suffix('.json.tmp')
    dump(temporary,value)
    temporary.replace(path)


def resume_point(destination):
    """Reuse completed stages; an interrupted VIO must restart from its beginning."""
    candidates=[]
    for path in destination.glob('*/manifest.yaml'):
        manifest=yaml.safe_load(path.read_text())
        candidates.append((manifest['started_utc'],path.parent,manifest))
    if not candidates:return None,'all',False
    _,run,manifest=max(candidates,key=lambda entry:entry[0])
    done=lambda stage:manifest.get('stages',{}).get(stage,{}).get('status') in ('complete','reused')
    if all(done(stage) for stage in ('prepare','reference','vio','compare','report')):
        return run,None,True
    if done('prepare') and done('reference'):
        return run,'compare' if done('vio') else 'all',False
    return None,'all',False


def main():
    p=argparse.ArgumentParser(__doc__)
    for name in ('basalt-experiment','calibration-dir','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--resume',action='store_true',help='Preserve attempts and reuse completed stages after interruption')
    a=p.parse_args();base=a.basalt_experiment.resolve();out=a.output.resolve()
    if out==base or base in out.parents:raise ValueError('Output must be separate from Basalt source')
    out.mkdir(parents=True,exist_ok=True)
    lock=(out/'batch.lock').open('a')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise RuntimeError('This batch is already running')
    exists=(out/'state.json').exists()
    if exists and not a.resume:raise ValueError('Batch state already exists; use --resume')
    if a.resume and not exists:raise ValueError('No batch exists to resume')
    if exists:
        state=json.loads((out/'state.json').read_text())
        if state['basalt_experiment']!=str(base) or state['calibration_dir']!=str(a.calibration_dir.resolve()):
            raise ValueError('Resume input paths differ from frozen batch')
    runs={}
    protected={}
    # Hash existing result/report files. Large run-specific marginalization caches are not consumed.
    for f in base.rglob('*'):
        if 'marg_data' in f.parts or 'dataset' in f.parts or '__pycache__' in f.parts:continue
        if f.is_file() and not f.is_symlink():protected[str(f)]=sha(f)
    for scene in SCENES:
        candidates=list((base/'runs'/scene).glob('*/manifest.yaml'))
        if len(candidates)!=1:raise ValueError('Expected exactly one Basalt run: '+scene)
        run=candidates[0].parent;info=inspect(run);runs[scene]=run
        for camera in ['cam0','cam1','cam2','cam3','imu0']:
            f=info['dataset']/'mav0'/camera/'data.csv';protected[str(f)]=sha(f)
    for f in a.calibration_dir.iterdir():
        if f.is_file():protected[str(f)]=sha(f)
    if exists:
        previous=json.loads((out/'input_hashes.json').read_text())
        if protected!=previous:raise ValueError('Protected batch inputs changed since interruption')
    else:dump(out/'input_hashes.json',protected)
    binary=out/'binary'
    if not exists:
        binary.mkdir()
        for name in ('okvis_app_synchronous','CMakeCache.txt','small_voc.yml.gz'):
            shutil.copy2(ROOT/'build-vio'/name,binary/name)
    config=ROOT/'config/oak4p/layout0916_vio_recovery.yaml'
    if not exists:shutil.copyfile(config,out/'algorithm_template.yaml')
    libs=subprocess.check_output(['ldd',str(binary/'okvis_app_synchronous')],text=True)
    if not exists:(out/'ldd.txt').write_text(libs)
    libraries={}
    for line in libs.splitlines():
        for token in line.split():
            if token.startswith('/') and Path(token).is_file():libraries[token]=sha(Path(token))
    if exists:
        if libraries!=json.loads((out/'libraries.json').read_text()):raise ValueError('Runtime libraries changed')
        if state['binary_sha256']!=sha(binary/'okvis_app_synchronous') or state['config_sha256']!=sha(out/'algorithm_template.yaml'):
            raise ValueError('Frozen executable or algorithm template changed')
        state.setdefault('resumptions',[]).append(datetime.now(timezone.utc).isoformat())
        state['status']='running'
        state.pop('ended_utc',None)
    else:
        dump(out/'libraries.json',libraries)
        state=dict(status='running',started_utc=datetime.now(timezone.utc).isoformat(),
        basalt_experiment=str(base),calibration_dir=str(a.calibration_dir.resolve()),
        binary_sha256=sha(binary/'okvis_app_synchronous'),config_sha256=sha(out/'algorithm_template.yaml'),
        policy=dict(imu_bias='estimate-from-zero',parallel_detection=True,matching_threads=4,solver_threads=3,
                    visual_recovery=True,imu_huber=5,deterministic_sampling=True,seed=12345,gui=False,repeats=1),runs={})
    checkpoint(out/'state.json',state)
    for scene,reference in runs.items():
        profile='static' if scene.startswith('static') else 'motion';dest=out/'runs'/scene
        prior,step,complete=resume_point(dest)
        if complete:
            state['runs'].setdefault(scene,{}).update(status='complete',run=str(prior),basalt_run=str(reference),profile=profile)
            checkpoint(out/'state.json',state);print('REUSED '+scene,flush=True);continue
        cmd=[sys.executable,str(ROOT/'scripts/run_vio_pipeline.py'),
            '--binary',str(binary/'okvis_app_synchronous'),'--evaluation-profile',profile,
            '--step',step,'--vio-max-frames','0','--run-name','poc1026_'+scene,
            '--output',str(dest)]
        if prior:cmd+=['--from-run',str(prior)]
        else:cmd+=['--basalt-run',str(reference),'--calibration-dir',str(a.calibration_dir.resolve()),
                   '--config',str(out/'algorithm_template.yaml'),'--imu-bias-policy','estimate-from-zero']
        if step!='compare':cmd+=['--deterministic','1']
        record=dict(status='running',basalt_run=str(reference),profile=profile,command=cmd,
                    started_utc=datetime.now(timezone.utc).isoformat())
        previous=state['runs'].get(scene)
        if previous:
            record['attempts']=previous.get('attempts',[])+[{k:v for k,v in previous.items() if k!='attempts'}]
        if prior:record['resume_from']=str(prior)
        state['runs'][scene]=record;checkpoint(out/'state.json',state)
        print('START '+scene,flush=True)
        env=dict(os.environ,MPLBACKEND='Agg',MPLCONFIGDIR=str(out/'plot_cache'),PYTHONDONTWRITEBYTECODE='1')
        before=set(dest.glob('*/manifest.yaml'))
        with (out/(scene+'_pipeline.log')).open('a') as log:
            log.write('\nATTEMPT '+record['started_utc']+'\n');log.flush()
            done=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,env=env)
        manifests=list(set(dest.glob('*/manifest.yaml'))-before)
        if len(manifests)==1:record['run']=str(manifests[0].parent)
        record.update(returncode=done.returncode,status='complete' if done.returncode==0 else 'failed',
                      ended_utc=datetime.now(timezone.utc).isoformat())
        checkpoint(out/'state.json',state);print(record['status'].upper()+' '+scene,flush=True)
        # A failed stage is preserved; other independent recordings remain useful.
    changed=[p for p,h in protected.items() if not Path(p).is_file() or sha(Path(p))!=h]
    library_changes=[p for p,h in libraries.items() if not Path(p).is_file() or sha(Path(p))!=h]
    dump(out/'preservation.json',dict(protected_files=len(protected),changed=changed,runtime_library_changes=library_changes,
        scope='Basalt result files excluding marg_data/dataset trees; explicit image/IMU indexes and calibration delivery. Image content not rehashed.'))
    state.update(status='complete' if all(r['status']=='complete' for r in state['runs'].values()) and not changed and not library_changes else 'failed',ended_utc=datetime.now(timezone.utc).isoformat())
    checkpoint(out/'state.json',state)
    subprocess.run([sys.executable,str(ROOT/'scripts/summarize_poc_batch.py'),str(out)],check=True,
                   env=dict(os.environ,MPLBACKEND='Agg',MPLCONFIGDIR=str(out/'plot_cache')))
    print('BATCH '+state['status'],flush=True)


if __name__=='__main__':main()
