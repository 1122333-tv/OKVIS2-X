#!/usr/bin/env python3
"""Lossless four-camera KB4 rig conversion. No camera model fitting."""
import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import sys
import numpy as np
from PIL import Image
import yaml


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_yaml(path, config):
    # OpenCV's YAML reader needs block mappings and inline scalar sequences.
    def emit(value, indent=0):
        lines=[]
        for key,v in value.items():
            prefix=' '*indent+key+':'
            if isinstance(v,dict): lines += [prefix]+emit(v,indent+2)
            elif isinstance(v,list) and v and isinstance(v[0],dict):
                lines.append(prefix)
                for item in v:
                    fields=emit(item,indent+4)
                    lines.append(' '*(indent+2)+'- '+fields[0].lstrip())
                    lines.extend(fields[1:])
            else:
                lines.append(prefix+' '+json.dumps(v,ensure_ascii=False))
        return lines
    Path(path).write_text('%YAML:1.0\n---\n'+'\n'.join(emit(config))+'\n')


def pose_matrix(p):
    q=np.array([p[k] for k in ('qx','qy','qz','qw')],float)
    if not np.isfinite(q).all() or abs(np.linalg.norm(q)-1)>1e-5:
        raise ValueError('Invalid calibration quaternion')
    x,y,z,w=q/np.linalg.norm(q)
    R=np.array([[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],
                [2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],
                [2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]])
    T=np.eye(4);T[:3,:3]=R;T[:3,3]=[p[k] for k in ('px','py','pz')]
    if not np.isfinite(T).all(): raise ValueError('Nonfinite transform')
    return T


def convert(calibration, template, output, mask_dir, imu_bias_policy='require-zero'):
    c=json.loads(Path(calibration).read_text())['value0']
    config=copy.deepcopy(yaml.safe_load(Path(template).read_text()))
    if any(len(c[k])!=4 for k in ('intrinsics','T_imu_cam','resolution')):
        raise ValueError('Expected four physical cameras')
    if imu_bias_policy not in ('require-zero', 'estimate-from-zero'):
        raise ValueError('Unknown IMU bias policy: '+imu_bias_policy)
    for key,size in (('calib_accel_bias',9),('calib_gyro_bias',12)):
        if len(c[key])!=size or not all(math.isfinite(v) for v in c[key]):
            raise ValueError('Invalid IMU correction: '+key)
        if any(v!=0 for v in c[key][3:]):
            raise ValueError('Nonzero IMU scale/misalignment unsupported: '+key)
        if imu_bias_policy=='require-zero' and any(v!=0 for v in c[key]):
            raise ValueError('Nonzero IMU correction unsupported: '+key)
    if imu_bias_policy=='estimate-from-zero':
        config['imu_parameters']['a0']=[0.,0.,0.]
        config['imu_parameters']['g0']=[0.,0.,0.]
        config['imu_parameters']['s_a']=[1.,1.,1.]
    cameras=[];reports=[]
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    masks=output.parent/'masks';masks.mkdir(exist_ok=True)
    for i,(intr,res,p) in enumerate(zip(c['intrinsics'],c['resolution'],c['T_imu_cam'])):
        if intr['camera_type']!='kb4': raise ValueError('Only exact KB4 mapping audited in this pipeline')
        a=intr['intrinsics'];T=pose_matrix(p)
        if not all(math.isfinite(v) for v in a.values()) or min(a['fx'],a['fy'])<=0: raise ValueError('Invalid intrinsics')
        mask_path=Path(mask_dir)/f'cam{i}.png';mask=np.asarray(Image.open(mask_path).convert('L'))
        if list(mask.shape)!=list(res[::-1]): raise ValueError('Mask resolution mismatch')
        target=masks/mask_path.name;Image.fromarray(np.where(mask<=127,255,0).astype('uint8')).save(target)
        cameras.append(dict(T_SC=T.reshape(-1).tolist(),image_dimension=res,
            distortion_coefficients=[a[f'k{j}'] for j in range(1,5)],distortion_type='equidistant',
            focal_length=[a['fx'],a['fy']],principal_point=[a['cx'],a['cy']],cam_model='pinhole',
            camera_type='gray',mapping_rectification=False,slam_use='okvis',mask_file=str(target.resolve())))
        reports.append(dict(camera=i,source_mask_sha256=sha(mask_path),mask_sha256=sha(target),
            valid_pixels=int((mask<=127).sum()),transform_inverse_error=float(np.max(np.abs(T@np.linalg.inv(T)-np.eye(4))))))
    config['cameras']=cameras
    offset=c['cam_time_offset_ns']
    if type(offset)!=int or abs(offset)>=100000000: raise ValueError('Invalid integer camera offset')
    config['camera_parameters']['image_delay']=-offset/1e9
    config['camera_parameters']['sync_cameras']=[0,1,2,3]
    for source,target in [('gyro_noise_std','sigma_g_c'),('accel_noise_std','sigma_a_c'),
                          ('gyro_bias_std','sigma_gw_c'),('accel_bias_std','sigma_aw_c')]:
        v=c[source]
        if len(v)!=3 or not all(math.isfinite(x) and x>0 for x in v) or len(set(v))!=1:
            raise ValueError('Expected positive isotropic continuous noise: '+source)
        config['imu_parameters'][target]=float(v[0])
    write_yaml(output,config)
    report=dict(calibration_sha256=sha(calibration),template_sha256=sha(template),cameras=reports,
                imu_bias_policy=imu_bias_policy,
                imu_correction=dict(source_accel=c['calib_accel_bias'],source_gyro=c['calib_gyro_bias'],
                    fixed_bias_applied=False,raw_samples_unchanged=True,
                    initial_accel_bias=config['imu_parameters']['a0'],initial_gyro_bias=config['imu_parameters']['g0'],
                    online_bias_estimation=True),
                cam_time_offset_ns=offset,image_delay_seconds=-offset/1e9,
                timestamp_equation='t_imu_ns = t_camera_ns + cam_time_offset_ns',
                transform_equation='T_SC = T_imu_cam; S=physical IMU',
                model_audit='Local polynomial and OKVIS valid-domain/roundtrip check')
    (output.parent/'calibration_conversion.json').write_text(json.dumps(report,indent=2)+'\n')
    return report

if __name__=='__main__':
    ap=argparse.ArgumentParser(__doc__)
    for name in ('calibration','template','output','mask-dir'):ap.add_argument('--'+name,type=Path,required=True)
    ap.add_argument('--imu-bias-policy',choices=['require-zero','estimate-from-zero'],default='require-zero')
    a=ap.parse_args();convert(a.calibration,a.template,a.output,a.mask_dir,a.imu_bias_policy)
