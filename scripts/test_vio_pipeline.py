"""Regression tests for conversion and reproducibility boundaries."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
import subprocess
import sys
import yaml
import numpy as np
from PIL import Image
from convert_rig_to_okvis import convert,pose_matrix,sha
from convert_okvis_trajectory import load,write

ROOT=Path(__file__).resolve().parents[1]
class Contracts(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.d=Path(self.tmp.name)
        self.c=dict(intrinsics=[dict(camera_type='kb4',intrinsics=dict(fx=10.,fy=11.,cx=2.,cy=1.,k1=.1,k2=.01,k3=0.,k4=0.)) for _ in range(4)],
            T_imu_cam=[dict(px=float(i),py=0.,pz=0.,qx=0.,qy=0.,qz=0.,qw=1.) for i in range(4)],resolution=[[4,3]]*4,
            calib_accel_bias=[0.]*9,calib_gyro_bias=[0.]*12,cam_time_offset_ns=3621516,
            gyro_noise_std=[.001]*3,accel_noise_std=[.01]*3,gyro_bias_std=[.0001]*3,accel_bias_std=[.001]*3)
        for i in range(4):Image.fromarray(np.array([[0,127,128,255]]*3,dtype='uint8')).save(self.d/f'cam{i}.png')
    def conversion(self):
        p=self.d/'cal.json';p.write_text(json.dumps({'value0':self.c}))
        return convert(p,ROOT/'config/oak4p/layout0916_vio.yaml',self.d/'out/okvis.yaml',self.d)
    def test_offset_sign_and_mask_boundary(self):
        r=self.conversion();self.assertEqual(r['image_delay_seconds'],-.003621516)
        np.testing.assert_array_equal(np.asarray(Image.open(self.d/'out/masks/cam0.png'))[0],[255,255,0,0])
        self.c['cam_time_offset_ns']=-3621516;self.assertEqual(self.conversion()['image_delay_seconds'],.003621516)
    def test_camera_order_and_rigid_transform(self):
        self.conversion()
        import yaml
        o=yaml.safe_load('\n'.join((self.d/'out/okvis.yaml').read_text().splitlines()[1:]))
        self.assertEqual([x['T_SC'][3] for x in o['cameras']],[0.,1.,2.,3.])
        T=pose_matrix(dict(px=1.,py=2.,pz=3.,qx=0.,qy=0.,qz=2**-.5,qw=2**-.5))
        np.testing.assert_allclose(T@np.array([1.,0.,0.,1.]),[1,3,3,1],atol=1e-14)
    def test_unsupported_calibration_is_rejected(self):
        self.c['intrinsics'][0]['camera_type']='ds'
        with self.assertRaises(ValueError):self.conversion()
        self.c['intrinsics'][0]['camera_type']='kb4';self.c['calib_accel_bias'][0]=.01
        with self.assertRaises(ValueError):self.conversion()
    def test_anisotropic_noise_is_rejected(self):
        self.c['accel_noise_std'][0]=.02
        with self.assertRaises(ValueError):self.conversion()
    def test_raw_imu_zero_prior_policy_preserves_source_and_rejects_scale(self):
        self.c['calib_accel_bias'][:3]=[.01,.02,-.03]
        self.c['calib_gyro_bias'][:3]=[.001,-.002,.003]
        p=self.d/'cal.json';p.write_text(json.dumps({'value0':self.c}));before=p.read_bytes()
        template=yaml.safe_load((ROOT/'config/oak4p/layout0916_vio.yaml').read_text())
        template['imu_parameters'].update(a0=[1,2,3],g0=[4,5,6],s_a=[2,2,2])
        t=self.d/'template.yaml';t.write_text(yaml.safe_dump(template))
        r=convert(p,t,self.d/'out/okvis.yaml',self.d,'estimate-from-zero')
        o=yaml.safe_load('\n'.join((self.d/'out/okvis.yaml').read_text().splitlines()[1:]))
        self.assertEqual(o['imu_parameters']['a0'],[0,0,0]);self.assertEqual(o['imu_parameters']['g0'],[0,0,0])
        self.assertEqual(o['imu_parameters']['s_a'],[1,1,1]);self.assertEqual(p.read_bytes(),before)
        self.assertFalse(r['imu_correction']['fixed_bias_applied'])
        self.assertEqual(r['imu_correction']['source_accel'],self.c['calib_accel_bias'])
        for key in ('calib_accel_bias','calib_gyro_bias'):
            c=copy.deepcopy(self.c);c[key][3]=1e-6;p.write_text(json.dumps({'value0':c}))
            with self.assertRaisesRegex(ValueError,'scale/misalignment'):
                convert(p,t,self.d/'out/okvis.yaml',self.d,'estimate-from-zero')
    def test_exact_large_timestamp_and_quaternion_order(self):
        t=1789539918207227402;p=self.d/'raw.csv';p.write_text(f'timestamp,px,py,pz,qx,qy,qz,qw\n{t},1,2,3,0,0,0,1\n')
        write(load(p),self.d/'normalized')
        self.assertTrue((self.d/'normalized/trajectory.tum').read_text().startswith('1789539918.207227402 '))
        self.assertEqual(load(self.d/'normalized/trajectory_euroc.csv','wxyz'),load(p))
    def test_duplicate_time_nan_and_nonunit_rejected(self):
        p=self.d/'raw.csv'
        for text in ['1,0,0,0,0,0,0,1\n1,0,0,0,0,0,0,1\n','1,nan,0,0,0,0,0,1\n','1,0,0,0,0,0,0,2\n']:
            p.write_text(text)
            with self.assertRaises(ValueError):load(p)
    def test_legacy_run_rejected(self):
        from pipeline_layout import read_manifest
        (self.d/'manifest.yaml').write_text('version: 1\n')
        with self.assertRaisesRegex(ValueError,'historical'):read_manifest(self.d)

if __name__=='__main__':unittest.main()


class ImuSupportBoundaries(unittest.TestCase):
    def test_signed_offsets_and_exact_tail(self):
        from vio_pipeline_common import validate_imu_support
        for offset in (-5000000,0,5000000):
            with self.subTest(offset=offset):
                first=100000000+offset-20000000
                last=200000000+offset+20000000
                validate_imu_support([first-1,last],[100000000,200000000],offset,20000000)
                for samples in ([first,last],[first-1,last-1]):
                    with self.assertRaisesRegex(ValueError,'Insufficient IMU support'):
                        validate_imu_support(samples,[100000000,200000000],offset,20000000)


class BasaltImageGroups(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.data=Path(self.tmp.name)
        for i in range(4):
            camera=self.data/f'cam{i}';camera.mkdir()
            # The referenced image directory does not exist: no image I/O is allowed here.
            (camera/'data.csv').write_text('#timestamp [ns],filename\n100000000,missing.jpg\n200000000,nested/image.jpg\n')

    def test_reuses_existing_groups_without_image_access(self):
        from unittest.mock import patch
        from vio_pipeline_common import read_basalt_image_groups
        with patch.object(Path,'is_file',side_effect=AssertionError('Unexpected file existence check')), \
             patch('PIL.Image.open',side_effect=AssertionError('Unexpected image open')):
            times,hashes,count=read_basalt_image_groups(self.data)
        self.assertEqual(times,[100000000,200000000]);self.assertEqual(count,8)
        self.assertEqual(hashes,{f'cam{i}':sha(self.data/f'cam{i}/data.csv') for i in range(4)})

    def test_still_rejects_bad_indices_and_grouping(self):
        from vio_pipeline_common import read_basalt_image_groups
        for text in ['100000000,../escape.jpg\n','100000000,/absolute.jpg\n',
                     '100000000,\n','100000000,image.jpg,extra\n',
                     '200000000,a.jpg\n100000000,b.jpg\n',
                     '100000000,a.jpg\n100000000,b.jpg\n',
                     '100000001,a.jpg\n200000000,b.jpg\n','']:
            with self.subTest(text=text):
                (self.data/'cam3/data.csv').write_text(text)
                with self.assertRaisesRegex(ValueError,'Invalid image index|Invalid synchronized groups'):
                    read_basalt_image_groups(self.data)
