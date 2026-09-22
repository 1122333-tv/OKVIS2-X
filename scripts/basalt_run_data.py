"""Read Basalt result artifacts, never import or execute its project code."""
from pathlib import Path
import json
import shutil
import yaml
from pipeline_layout import sha, dump
from convert_okvis_trajectory import load

def choose(root, *names):
    found=[root/n for n in names if (root/n).is_file()]
    if not found:raise ValueError('Missing Basalt artifact: '+', '.join(names))
    if len(found)>1 and len({sha(p) for p in found})>1:raise ValueError('Conflicting Basalt artifacts: '+str(found))
    return found[0]

def inspect(root, mask_dir=None):
    root=Path(root).resolve();m=yaml.safe_load((root/'manifest.yaml').read_text())
    for stage in ('prepare','gt','vio'):
        if m.get('stages',{}).get(stage,{}).get('status') not in ('complete','reused'):
            raise ValueError('Basalt prerequisite incomplete: '+stage)
    prep=root/m['stages']['prepare'].get('directory','01_preparation')
    gt=root/m['stages']['gt'].get('directory','02_mocap_alignment')
    vio=root/m['stages']['vio'].get('directory','03_vio')
    pr=choose(prep,'preparation.json','outputs/preparation.json');p=json.loads(pr.read_text())
    dataset=prep/'dataset'
    if not dataset.is_dir():dataset=prep/'outputs/dataset'
    if not (dataset/'mav0').is_dir():raise ValueError('Missing prepared dataset or broken link')
    source=m.get('dataset') or m.get('parameters',{}).get('dataset')
    if not source or not p.get('source') or Path(source).resolve()!=Path(p['source']).resolve():
        raise ValueError('Dataset identity mismatch between manifest and preparation')
    offset=p.get('cam_time_offset_ns')
    if type(offset)!=int:raise ValueError('Preparation must record integer cam_time_offset_ns')
    cal=choose(prep,'inputs/calibration.json','calibration.json')
    if json.loads(cal.read_text())['value0']['cam_time_offset_ns']!=offset:raise ValueError('Prepared camera time offset conflicts')
    ground=choose(gt,'state_groundtruth_estimate0/data.csv','outputs/state_groundtruth_estimate0/data.csv')
    conversion=ground.with_name('conversion.json')
    if not conversion.is_file():raise ValueError('Missing GT conversion/valid-segment metadata')
    meta=json.loads(conversion.read_text())
    if not meta.get('valid_segments_ns'):raise ValueError('Missing GT valid segments')
    trajectory=choose(vio,'outputs/oak4p_trajectory.csv','oak4p_trajectory.csv')
    g=load(ground,'wxyz');v=load(trajectory,'wxyz')
    if max(g[0][0],v[0][0])>=min(g[-1][0],v[-1][0]):raise ValueError('Reference trajectories do not overlap')
    masks=Path(mask_dir).resolve() if mask_dir else root/m.get('camera_masks',{}).get('directory','camera_masks')
    if not mask_dir and not m.get('camera_masks',{}).get('enabled'):raise ValueError('Provide --camera-mask-dir; Basalt run has no enabled masks')
    for i in range(4):
        if not (masks/f'cam{i}.png').is_file():raise ValueError('Missing camera mask '+str(masks))
    return dict(root=root,manifest=m,preparation=p,preparation_file=pr,dataset=dataset.resolve(),dataset_identity=source,
                gt=ground,conversion=conversion,trajectory=trajectory,masks=masks,offset=offset,gt_stage=gt)

def import_reference(info, target):
    target=Path(target);target.mkdir(parents=True,exist_ok=True)
    files={info['root']/'manifest.yaml':'basalt_manifest.yaml',info['preparation_file']:'preparation.json',
           info['gt']:'groundtruth/data.csv',info['conversion']:'groundtruth/conversion.json',info['trajectory']:'basalt_trajectory.csv'}
    for name in ('total_offset.json','time_alignment.json'):
        for sub in ('time_alignment','outputs/time_alignment'):
            p=info['gt_stage']/sub/name
            if p.is_file():files[p]='time_alignment/'+name;break
    records={}
    for source,relative in files.items():
        dest=target/relative;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,dest)
        records[relative]={'source':str(source),'sha256':sha(dest)}
    dump(target/'sources.json',dict(files=records,gt_policy='Imported unchanged; no time or pose transform',
         unchecked=['physical IMU frame consistency','marker-IMU calibration consistency']))
    return records
