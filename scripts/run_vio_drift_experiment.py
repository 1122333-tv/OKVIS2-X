#!/usr/bin/env python3
"""Run one immutable, full-recording, single-factor experiment on frozen inputs."""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time
import uuid
import yaml
from analyze_vio_drift import analyze
from convert_rig_to_okvis import write_yaml


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def run_owned_process(command, cwd, env, log, cancel_file):
    process=subprocess.Popen(command,cwd=cwd,env=env,stdout=log,
                             stderr=subprocess.STDOUT,start_new_session=True)
    try:
        while True:
            if cancel_file.exists():
                raise RuntimeError('Explicit cancellation requested via run/CANCEL')
            try:
                code=process.wait(timeout=2)
                break
            except subprocess.TimeoutExpired:
                pass
        if code:raise subprocess.CalledProcessError(code,command)
    finally:
        # Killing an outer queue is not evidence that the VIO child died.
        # A CANCEL file lets this owner stop and reap its process group.
        if process.poll() is None:
            os.killpg(process.pid,signal.SIGTERM)
            try:process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid,signal.SIGKILL);process.wait()


def validate_isolation(original_path, modified_path):
    import csv
    original_lines=original_path.read_bytes().splitlines()
    modified_lines=modified_path.read_bytes().splitlines()
    if not original_lines or not modified_lines or original_lines[0]!=modified_lines[0]:
        raise ValueError('Isolation must preserve the IMU header consumed by DatasetReader')
    def rows(lines):
        return list(csv.reader(l.decode() for l in lines if l and not l.startswith(b'#')))
    original=rows(original_lines);modified=rows(modified_lines)
    if len(original)!=len(modified) or any(x[0]!=y[0] or x[4:]!=y[4:] for x,y in zip(original,modified)):
        raise ValueError('Isolation must preserve all timestamps and accelerometer samples')


def main():
    p=argparse.ArgumentParser(__doc__)
    p.add_argument('--baseline',required=True,type=Path)
    p.add_argument('--binary',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path)
    p.add_argument('--name',required=True)
    p.add_argument('--set',action='append',default=[],metavar='SECTION.KEY=JSON')
    p.add_argument('--diagnostics',action='store_true')
    p.add_argument('--parent',required=True)
    p.add_argument('--input-hashes',required=True,type=Path)
    p.add_argument('--diagnostic-imu-csv',type=Path,help='Offline isolation only; never a final candidate')
    a=p.parse_args()
    if not a.name or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789_-' for c in a.name):
        p.error('Unsafe name')
    base=a.baseline.resolve(); binary=a.binary.resolve()
    run=a.output.resolve()/f'{datetime.now():%Y%m%dT%H%M%S}_{a.name}_{uuid.uuid4().hex[:6]}'
    run.mkdir(parents=True,exist_ok=False)
    cfg=yaml.safe_load('\n'.join((base/'03_vio/inputs/okvis2.yaml').read_text().splitlines()[1:]))
    from run_vio_reproducibility import profile_config
    cfg=profile_config(cfg,'frontend-single')
    frozen_input_hashes=json.loads(a.input_hashes.read_text())
    for path,expected in frozen_input_hashes.items():
        if sha(Path(path))!=expected:raise ValueError('Frozen input changed: '+path)
    libraries=json.loads((binary.parent/'libraries.json').read_text())
    for path,expected in libraries.items():
        if sha(Path(path))!=expected:raise ValueError('Runtime library changed: '+path)
    changes={}
    for change in a.set:
        key,value=change.split('=',1); section,field=key.split('.')
        if key=='imu_parameters.huber_loss_scale':cfg[section].setdefault(field,0.0)
        if key=='frontend_parameters.visual_recovery':cfg[section].setdefault(field,False)
        old=cfg[section][field]; cfg[section][field]=json.loads(value)
        changes[key]={'old':old,'new':cfg[section][field]}
    if any(cfg['estimator_parameters'][k] for k in ('do_loop_closures','do_final_ba','enforce_realtime')):
        raise ValueError('Must remain pure offline VIO')
    cfg['output_parameters'].update(display_matches=False,display_topview=False,display_overhead=False)
    for i,camera in enumerate(cfg['cameras']):
        mask=Path(camera['mask_file']); frozen=run/f'cam{i}.png'
        shutil.copy2(mask,frozen); camera['mask_file']=str(frozen)
    config=run/'okvis2.yaml'; write_yaml(config,cfg)
    data=(base/'01_preparation/outputs/dataset/mav0').resolve()
    original_data=data
    if a.diagnostic_imu_csv:
        validate_isolation(original_data/'imu0/data.csv',a.diagnostic_imu_csv)
        data=run/'diagnostic_dataset/mav0';data.mkdir(parents=True)
        for i in range(4):(data/f'cam{i}').symlink_to(original_data/f'cam{i}')
        (data/'imu0').mkdir();shutil.copy2(a.diagnostic_imu_csv,data/'imu0/data.csv')
    outputs=run/'outputs'; outputs.mkdir()
    env=os.environ.copy(); env['OKVIS_FEATURE_AUDIT']='1'
    env.pop('OKVIS_VIO_DIAGNOSTICS',None)
    env.pop('OKVIS_REPRO_AUDIT',None)
    if a.diagnostics:env['OKVIS_VIO_DIAGNOSTICS']='1'
    command=[str(binary),str(config),str(data),str(outputs),'--deterministic','1']
    root=Path(__file__).resolve().parents[1]
    meta=dict(environment={k:env.get(k) for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','OKVIS_FEATURE_AUDIT','OKVIS_VIO_DIAGNOSTICS','OKVIS_REPRO_AUDIT')},runtime_libraries=libraries,parent=a.parent,sampling={'deterministic':True,'seed':12345},input_hashes_sha256=sha(a.input_hashes),status='running',baseline=str(base),changes=changes,diagnostics=a.diagnostics,
              diagnostic_input_only=bool(a.diagnostic_imu_csv),original_imu_sha256=sha(original_data/'imu0/data.csv'),
              command=command,binary_sha256=sha(binary),config_sha256=sha(config),
              input_indices={str(x):sha(data/x/'data.csv') for x in ['imu0','cam0','cam1','cam2','cam3']},
              masks={str(i):sha(run/f'cam{i}.png') for i in range(4)},
              git_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip())
    (run/'launch_source.diff').write_text(subprocess.check_output(['git','diff','--binary'],cwd=root,text=True))
    # A frozen binary can intentionally differ from the checkout at launch time.
    # Keep its build-time snapshot separate from the experiment driver's checkout.
    build_sources=binary.parent/'build_sources'
    meta['build_source_snapshot_available']=build_sources.is_dir()
    if build_sources.is_dir():
        shutil.copytree(build_sources,run/'build_sources')
        meta['build_source_sha256']={str(f.relative_to(build_sources)):sha(f)
                                     for f in build_sources.rglob('*') if f.is_file()}
    shutil.copy2(__file__,run/Path(__file__).name)
    shutil.copy2(root/'scripts/analyze_vio_drift.py',run/'analyze_vio_drift.py')
    manifest=run/'experiment.json'
    manifest.write_text(json.dumps(meta,indent=2)+'\n')
    print(run,flush=True); start=time.monotonic()
    try:
        with (run/'stage.log').open('w') as log:
            run_owned_process(command,outputs,env,log,run/'CANCEL')
        meta['vio_wall_seconds']=time.monotonic()-start
        result=analyze(outputs/'okvis2-vio_trajectory.csv',base,run/'analysis')
        for path,expected in frozen_input_hashes.items():
            if sha(Path(path))!=expected:raise ValueError('Input changed: '+path)
        if sha(binary)!=meta['binary_sha256']:raise ValueError('Binary changed during replay')
        for path,expected in libraries.items():
            if sha(Path(path))!=expected:raise ValueError('Runtime library changed: '+path)
        meta['trajectory_sha256']=sha(outputs/'okvis2-vio_trajectory.csv')
        meta.update(status='complete',ape=result['ape'],poses=result['poses'])
    except BaseException as error:
        meta.update(status='failed',error=str(error));raise
    finally:
        meta['wall_seconds']=time.monotonic()-start
        manifest.write_text(json.dumps(meta,indent=2)+'\n')
    print(json.dumps(meta['ape']),flush=True)


if __name__=='__main__':main()
