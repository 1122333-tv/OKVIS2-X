"""Auditable OKVIS four-stage pipeline with immutable runs."""
import argparse
import importlib.metadata
import platform
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import statistics
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid
import yaml
from PIL import Image
from convert_rig_to_okvis import convert, sha, write_yaml
from convert_okvis_trajectory import load, write

from pipeline_layout import VERSION, STAGES, artifact, read_manifest, artifact_hashes, dump
from basalt_run_data import inspect, import_reference

ROOT=Path(__file__).resolve().parents[1]
def rows(p):
    with p.open() as f:return list(csv.reader(l for l in f if not l.startswith('#')))


def read_imu_support(binary):
    result=subprocess.run([str(binary),'--imu-support-ns'],capture_output=True,text=True)
    if result.returncode or not result.stdout.strip().isdigit() or int(result.stdout)<=0:
        raise ValueError('Binary cannot report IMU support; rebuild okvis_app_synchronous: '+str(binary))
    return int(result.stdout)


def validate_imu_support(imu_times,image_times,offset_ns,support_ns):
    first=image_times[0]+offset_ns-support_ns
    last=image_times[-1]+offset_ns+support_ns
    if imu_times[0]>=first or imu_times[-1]<last:
        raise ValueError(f'Insufficient IMU support: need first IMU < {first} ns and last IMU >= {last} ns; '
                         f'actual [{imu_times[0]}, {imu_times[-1]}] ns; overlap={support_ns} ns')


def git_info(root):
    def run(*args):return subprocess.run(['git','-C',str(root),*args],capture_output=True,text=True).stdout
    return dict(head=run('rev-parse','HEAD').strip(),status=run('status','--short'),diff=run('diff','--binary'),submodules=run('submodule','status'))


def audit_models(config,masks,output):
    binary=ROOT/'build-vio/audit_camera_models';source=ROOT/'scripts/audit_camera_models.cpp'
    includes=[ROOT/'okvis_cv/include',ROOT/'okvis_util/include']
    flags=subprocess.check_output(['pkg-config','--cflags','--libs','opencv4'],text=True).split()
    command=['c++','-std=c++17','-O2','-I/usr/include/eigen3',*[f'-I{p}' for p in includes],str(source),str(ROOT/'okvis_cv/src/CameraBase.cpp'),'-o',str(binary),*flags]
    binary.parent.mkdir(exist_ok=True)
    with (output/'camera_audit_build.log').open('w') as f:subprocess.run(command,stdout=f,stderr=subprocess.STDOUT,check=True)
    result=subprocess.check_output([str(binary),str(config),str(masks)],text=True)
    data=json.loads(result);dump(output/'camera_models.json',data)
    dump(output/'camera_audit_provenance.json',dict(command=command,binary_sha256=sha(binary),source_sha256=sha(source),precision='double',gate='Local KB4 polynomial and OKVIS valid-domain/roundtrip checks; no fitted parameters.',camera_headers={str(p):sha(p) for p in [ROOT/'okvis_cv/include/okvis/cameras/implementation/PinholeCamera.hpp',ROOT/'okvis_cv/include/okvis/cameras/implementation/EquidistantDistortion.hpp']}))
    if any(not r['pixels'] or r['failed'] or r['max_projection_difference_px']>1e-5 or r['max_refined_bearing_angle_rad']>1e-7 or r['min_refined_z']<=0 or r['min_radial_derivative']<=0 or r['max_roundtrip_px']>1e-5 for r in data):
        raise ValueError('Camera model compatibility gate failed; see camera_models.json')
    return data


def main():
    ap=argparse.ArgumentParser(__doc__)
    for name in ('basalt-run','calibration-dir','from-run','output','config','camera-mask-dir'):
        ap.add_argument('--'+name,type=Path)
    ap.add_argument('--step',choices=['all','prepare','vio','compare','report'],default='all')
    ap.add_argument('--run-name',default='vio')
    ap.add_argument('--show-gui',action='store_true',help='OKVIS GUI only')
    ap.add_argument('--evo-show-gui',action='store_true',help='Open evo metric and trajectory windows')
    ap.add_argument('--vio-max-frames',type=int,default=None)
    ap.add_argument('--binary',type=Path,default=ROOT/'build-vio/okvis_app_synchronous')
    a=ap.parse_args()
    if a.vio_max_frames is not None and a.vio_max_frames<0:ap.error('Frame limit must be nonnegative')
    prior=read_manifest(a.from_run) if a.from_run else None
    if prior:
        a.from_run=a.from_run.resolve()
        if any((a.basalt_run,a.calibration_dir,a.config,a.camera_mask_dir)):ap.error('Reuse takes frozen inputs; do not override input parameters')
        params=prior['parameters'].copy()
    else:
        if not a.basalt_run or not a.calibration_dir:ap.error('--basalt-run and --calibration-dir required')
        if a.step not in ('all','prepare'):ap.error('Later stages require --from-run')
        a.basalt_run=a.basalt_run.resolve();a.calibration_dir=a.calibration_dir.resolve()
        a.config=(a.config or ROOT/'config/oak4p/layout0916_vio.yaml').resolve()
        info=inspect(a.basalt_run,a.camera_mask_dir)
        params=dict(basalt_run=str(a.basalt_run),calibration_dir=str(a.calibration_dir),config=str(a.config),
                    config_sha256=sha(a.config),dataset=info['dataset_identity'],prepared_dataset=str(info['dataset']))
    a.vio_max_frames=a.vio_max_frames if a.vio_max_frames is not None else (prior or {}).get('vio',{}).get('max_frames',0)
    if a.step=='report':
        from generate_pipeline_report import generate
        print(generate(a.from_run));return
    if not a.run_name or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in a.run_name):ap.error('Unsafe run name')
    base=(a.output or ROOT/'results'/Path(params['dataset']).name).resolve()
    for protected in (Path(params['dataset']),Path(params['prepared_dataset']),Path(params['basalt_run'])):
        if base==protected.resolve() or protected.resolve() in base.parents:ap.error('Output must be outside source data/run')
    path=base/('run_'+datetime.now().strftime('%Y%m%dT%H%M%S')+'_'+a.run_name+'_'+uuid.uuid4().hex[:6]);path.mkdir(parents=True)
    m=dict(format='okvis-vio',version=VERSION,status='running',parameters=params,invocation=sys.argv,python=sys.executable,
           stages={},from_run=str(a.from_run) if prior else None,started_utc=datetime.now(timezone.utc).isoformat(),software={'okvis':git_info(ROOT)})
    def save():(path/'manifest.yaml').write_text(yaml.safe_dump(m,sort_keys=False,allow_unicode=True))
    provenance=path/'provenance';provenance.mkdir()
    names=['run_vio_pipeline.py','vio_pipeline_common.py','pipeline_layout.py','basalt_run_data.py','convert_rig_to_okvis.py',
           'convert_okvis_trajectory.py','rig_calibration.py','capture_pipeline_common.py','interpolate_mocap_to_vio.py',
           'extend_evo_stats.py','compare_vio_runs.py','generate_pipeline_report.py','audit_camera_models.cpp']
    m['source_files']={}
    for name in names:
        source=ROOT/'scripts'/name;shutil.copy2(source,provenance/name);m['source_files'][name]=sha(source)
    shutil.copytree(ROOT/'scripts/vendor',provenance/'vendor')
    m['environment']=dict(platform=platform.platform(),cpu_count=os.cpu_count(),python_packages={p:importlib.metadata.version(p) for p in ['numpy','Pillow','PyYAML','matplotlib','evo']})
    save();print(path,flush=True)
    def command(stage,argv,cwd=None):
        m['stages'][stage].setdefault('commands',[]).append([str(x) for x in argv]);save()
        env=dict(os.environ,PYTHON_BIN=sys.executable,MPLBACKEND='Agg',OKVIS_FEATURE_AUDIT='1')
        with (path/STAGES[stage]/'logs/stage.log').open('a') as f:
            subprocess.run(list(map(str,argv)),cwd=cwd or ROOT,env=env,stdout=f,stderr=subprocess.STDOUT,check=True)
    def stage(name,action):
        directory=path/STAGES[name]
        for sub in ('inputs','outputs','logs','diagnostics'):(directory/sub).mkdir(parents=True,exist_ok=True)
        m['stages'][name]=dict(status='running',directory=STAGES[name]);save();print('Starting '+name,flush=True);t=time.monotonic()
        try:action(directory)
        except BaseException as e:m['stages'][name].update(status='failed',error=str(e));raise
        else:
            m['stages'][name]['status']='complete'
            m['stages'][name]['artifact_sha256']=artifact_hashes(directory)
        finally:m['stages'][name]['wall_seconds']=time.monotonic()-t;save()
    def reuse(name):
        record=prior['stages'].get(name,{})
        if record.get('status') not in ('complete','reused'):raise ValueError('Incomplete prerequisite '+name)
        source=a.from_run/STAGES[name]
        if artifact_hashes(source)!=record.get('artifact_sha256'):raise ValueError('Prior artifacts changed: '+name)
        shutil.copytree(source,path/STAGES[name],symlinks=True)
        for link in (path/STAGES[name]).rglob('*'):
            if link.is_symlink():
                target=os.readlink(link)
                if target.startswith(str(a.from_run)+'/'):
                    link.unlink();link.symlink_to(str(path)+target[len(str(a.from_run)):])
        for relative in ('outputs/okvis2.yaml','inputs/okvis2.yaml'):
            config_file=path/STAGES[name]/relative
            if config_file.is_file():config_file.write_text(config_file.read_text().replace(str(a.from_run),str(path)))
        m['stages'][name]=dict(status='reused',directory=STAGES[name],source=str(source),artifact_sha256=artifact_hashes(path/STAGES[name]))
        if name in prior:m[name]=prior[name]
        for k in ({'prepare':['preparation'],'vio':['binary','effective_config_sha256']}.get(name,[])):
            m[k]=prior[k]
        save()
    prep=path/STAGES['prepare'];ref=path/STAGES['reference'];vio=path/STAGES['vio']
    def check_indices():
        meta=json.loads((prep/'outputs/preparation.json').read_text())
        for name,digest in meta['index_sha256'].items():
            if sha(prep/'outputs/dataset/mav0'/name/'data.csv')!=digest:raise ValueError('Referenced input index changed: '+name)
    def prepare(d):
        from rig_calibration import load_delivery
        c,delivery,time_ref,files=load_delivery(a.calibration_dir,require_mocap=False)
        for f in files:shutil.copyfile(f,d/'inputs'/f.name)
        shutil.copyfile(a.config,d/'inputs/algorithm_template.yaml')
        shutil.copyfile(ROOT/'config/oak4p/layout0916_vio.yaml',d/'inputs/default_config.yaml')
        shutil.copyfile(info['root']/'manifest.yaml',d/'inputs/basalt_manifest.yaml')
        shutil.copyfile(info['preparation_file'],d/'inputs/basalt_preparation.json')
        shutil.copytree(info['masks'],d/'inputs/source_masks',symlinks=False)
        (d/'outputs/dataset').symlink_to(info['dataset'],target_is_directory=True)
        # Transfer only the grouping-reference offset; physical calibration comes from the supplied delivery.
        bp=info['preparation'];group=bp.get('group_time_reference');calref=bp.get('calibration_time_reference')
        if calref and calref!=f'cam{time_ref}':raise ValueError('Camera time reference differs from prepared input')
        adjustment=bp.get('reference_offset_adjustment_ns',0)
        if type(adjustment)!=int:raise ValueError('Invalid group-reference adjustment')
        if group and calref and group!=calref and 'reference_offset_adjustment_ns' not in bp:raise ValueError('Missing group-reference transfer')
        effective=c['value0']['cam_time_offset_ns']+adjustment
        if effective!=info['offset']:raise ValueError('Delivery camera offset conflicts with prepared group timing')
        c['value0']['cam_time_offset_ns']=effective;dump(d/'outputs/calibration.json',c)
        conversion=convert(d/'outputs/calibration.json',d/'inputs/algorithm_template.yaml',d/'outputs/okvis2.yaml',d/'inputs/source_masks')
        data=d/'outputs/dataset/mav0';times=None;count=0;hashes={}
        for i in range(4):
            name=f'cam{i}';cp=data/name;r=rows(cp/'data.csv');ts=[int(x[0]) for x in r]
            if not ts or any(y<=x for x,y in zip(ts,ts[1:])) or (times is not None and ts!=times):raise ValueError('Invalid synchronized groups')
            times=ts;hashes[name]=sha(cp/'data.csv')
            def check_image(row):
                if len(row)!=2 or Path(row[1]).is_absolute() or '..' in Path(row[1]).parts:raise ValueError('Invalid image index')
                f=cp/'data'/row[1]
                if not f.is_file():raise ValueError('Missing image '+str(f))
                with Image.open(f) as im:
                    if list(im.size)!=c['value0']['resolution'][i]:raise ValueError('Image resolution mismatch')
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=16) as pool:
                for _ in pool.map(check_image,r):
                    count+=1
                    if count%1200==0:print(f'Checked {count} images',flush=True)
        ir=rows(data/'imu0/data.csv');it=[int(x[0]) for x in ir]
        if not it or any(y<=x for x,y in zip(it,it[1:])) or any(len(r)!=7 or not all(__import__('math').isfinite(float(v)) for v in r[1:]) for r in ir):raise ValueError('Invalid IMU samples')
        hashes['imu0']=sha(data/'imu0/data.csv')
        support_ns=read_imu_support(a.binary.resolve())
        validate_imu_support(it,times,effective,support_ns)
        dump(d/'outputs/imu_support.json',dict(overlap_ns=support_ns,binary_sha256=sha(a.binary.resolve()),
             first_required_before_ns=times[0]+effective-support_ns,
             last_required_at_or_after_ns=times[-1]+effective+support_ns))
        models=audit_models(d/'outputs/okvis2.yaml',d/'inputs/source_masks',d/'diagnostics')
        m['preparation']=dict(groups=len(times),images_checked=count,index_sha256=hashes,prepared_dataset=str(info['dataset']),
             first_camera_timestamp_ns=times[0],last_camera_timestamp_ns=times[-1],cam_time_offset_ns=effective,
             conversion=conversion,models=models,image_content_checksums='Not recomputed; existence and dimensions checked')
        dump(d/'outputs/preparation.json',m['preparation'])
    def reference(d):
        import_reference(info,d/'inputs')
    def estimate(d):
        check_indices()
        cfg=yaml.safe_load('\n'.join((prep/'outputs/okvis2.yaml').read_text().splitlines()[1:]))
        for flag in ('do_loop_closures','do_final_ba','enforce_realtime'):
            if cfg['estimator_parameters'][flag]:raise ValueError('Pure offline VIO requires '+flag+'=false')
        if any(cfg['camera_parameters']['online_calibration'][k] for k in ('do_extrinsics','do_extrinsics_final_ba')):raise ValueError('Online calibration disabled')
        if cfg['frontend_parameters']['use_cnn']:raise ValueError('CNN disabled')
        for i,camera in enumerate(cfg['cameras']):camera['mask_file']=str((prep/f'outputs/masks/cam{i}.png').resolve())
        cfg['output_parameters']['display_matches']=a.show_gui;cfg['output_parameters']['display_topview']=a.show_gui
        write_yaml(d/'inputs/okvis2.yaml',cfg)
        semantic=json.loads(json.dumps(cfg))
        for camera in semantic['cameras']:camera['mask_file']='sha256:'+sha(camera['mask_file'])
        m['effective_config_sha256']=hashlib.sha256(json.dumps(semantic,sort_keys=True).encode()).hexdigest()
        data=prep/'outputs/dataset/mav0';input_rows=rows(data/'cam0/data.csv')
        if a.vio_max_frames:
            view=d/'inputs/dataset/mav0';view.mkdir(parents=True)
            for i in range(4):
                cp=view/f'cam{i}';cp.mkdir();(cp/'data').symlink_to(data/f'cam{i}/data')
                with (cp/'data.csv').open('w') as f:
                    f.write('#timestamp [ns],filename\n');csv.writer(f).writerows(rows(data/f'cam{i}/data.csv')[:a.vio_max_frames])
            (view/'imu0').symlink_to(data/'imu0');data=view;input_rows=input_rows[:a.vio_max_frames]
        binary=a.binary.resolve()
        if not binary.is_file():raise ValueError('Build OKVIS first: '+str(binary))
        support_ns=read_imu_support(binary)
        validate_imu_support([int(r[0]) for r in rows(data/'imu0/data.csv')],
                             [int(r[0]) for r in input_rows],m['preparation']['cam_time_offset_ns'],support_ns)
        m['imu_support']=dict(overlap_ns=support_ns,binary_sha256=sha(binary))
        voc=binary.parent/'small_voc.yml.gz'
        if not voc.exists():shutil.copy2(ROOT/'resources/small_voc.yml.gz',voc)
        m['binary']=dict(path=str(binary),sha256=sha(binary),vocabulary_sha256=sha(voc),cmake_cache_sha256=sha(binary.parent/'CMakeCache.txt'))
        start_wall=time.monotonic()
        command('vio',['/usr/bin/time','-v','-o',d/'diagnostics/resource_usage.txt',binary,d/'inputs/okvis2.yaml',data,d/'outputs'],cwd=d/'outputs')
        wall=time.monotonic()-start_wall
        poses=load(d/'outputs/okvis2-vio_trajectory.csv');summary=write(poses,d/'outputs')
        features={i:[] for i in range(4)}
        for cam,stamp,count,excluded in re.findall(r'FEATURE_AUDIT camera=(\d+) timestamp_ns=(\d+) features=(\d+) excluded=(\d+)',(d/'logs/stage.log').read_text()):
            if int(excluded):raise ValueError('Features survived excluded mask')
            features[int(cam)].append((int(stamp),int(count)))
        if any(not v or max(n for t,n in v)==0 for v in features.values()):raise ValueError('No feature evidence from a camera')
        feature_report={i:dict(frames=len(v),min=min(n for t,n in v),median=statistics.median(n for t,n in v),max=max(n for t,n in v),excluded=0) for i,v in features.items()}
        dump(d/'diagnostics/feature_summary.json',feature_report)
        resource=(d/'diagnostics/resource_usage.txt').read_text()
        rss=re.search(r'Maximum resident set size \(kbytes\): (\d+)',resource)
        summary.update(wall_seconds=wall,peak_rss_kb=int(rss.group(1)) if rss else None,feature_audit_enabled=True,features=feature_report)
        offset=json.loads((prep/'outputs/calibration_conversion.json').read_text())['cam_time_offset_ns']
        expected={int(r[0])+offset for r in input_rows};actual={r[0] for r in poses}
        if not actual<=expected:raise ValueError('Output timestamps not in corrected input group timestamps')
        first,last=min(expected),max(expected)
        summary.update(input_groups=len(expected),missing_groups=len(expected-actual),initialization_delay_s=(poses[0][0]-first)/1e9,end_gap_s=(last-poses[-1][0])/1e9,
            input_first_imu_ns=first,input_last_imu_ns=last,show_gui=a.show_gui,max_frames=a.vio_max_frames,cache_state='uncontrolled')
        summary['wall_realtime_factor']=wall/((last-first)/1e9) if last>first else None
        dump(d/'outputs/trajectory_summary.json',summary);m['vio']=summary
    def compare(d):
        command('compare',[sys.executable,ROOT/'scripts/compare_vio_runs.py','--okvis',artifact(path,'trajectory'),
            '--basalt',artifact(path,'basalt'),'--groundtruth',artifact(path,'gt'),'--output',d,
            '--input-first-ns',json.loads(artifact(path,'vio_summary').read_text())['input_first_imu_ns']])
        m['comparison']=json.loads(artifact(path,'comparison').read_text())
    try:
        if prior:
            reuse('prepare');reuse('reference');check_indices()
        else:
            stage('prepare',prepare);stage('reference',reference)
        if a.step in ('all','vio'):stage('vio',estimate)
        elif a.step=='compare':reuse('vio')
        if a.step in ('all','compare'):
            stage('compare',compare)
            from generate_pipeline_report import generate
            stage('report',lambda d:generate(path,automatic=True))
        m['status']='complete'
    except BaseException as e:m.update(status='failed',error=str(e));raise
    finally:
        m['ended_utc']=datetime.now(timezone.utc).isoformat();save()
        print('Run '+m['status']+': '+str(path),flush=True)
    if a.evo_show_gui and a.step in ('all','compare'):
        from compare_vio_runs import show_gui
        show_gui(path/STAGES['compare'])

if __name__=='__main__':main()
