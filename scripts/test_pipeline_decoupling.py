import json
from pathlib import Path
import tempfile
import unittest
import yaml
from PIL import Image
from basalt_run_data import inspect, import_reference
from pipeline_layout import dump, sha, read_manifest, artifact_hashes
from generate_pipeline_report import generate, differences

class DataImport(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.r=self.root/'basalt';self.r.mkdir()
        self.man=dict(dataset=str(self.root/'raw'),stages={s:{'status':'complete'} for s in ('prepare','gt','vio')},camera_masks={'enabled':True,'directory':'camera_masks'})
        dump(self.r/'01_preparation/preparation.json',{'source':self.man['dataset'],'cam_time_offset_ns':3})
        dump(self.r/'01_preparation/calibration.json',{'value0':{'cam_time_offset_ns':3}})
        (self.r/'01_preparation/dataset/mav0').mkdir(parents=True)
        text='#timestamp,px,py,pz,qw,qx,qy,qz\n'+''.join(f'{i*10000000},0,0,0,1,0,0,0\n' for i in range(10))
        gt=self.r/'02_mocap_alignment/state_groundtruth_estimate0';gt.mkdir(parents=True)
        (gt/'data.csv').write_text(text);dump(gt/'conversion.json',{'valid_segments_ns':[[0,90000000]]})
        (self.r/'03_vio').mkdir();(self.r/'03_vio/oak4p_trajectory.csv').write_text(text)
        (self.r/'camera_masks').mkdir()
        for i in range(4):Image.new('L',(4,3),0).save(self.r/f'camera_masks/cam{i}.png')
        self.save()
    def save(self):(self.r/'manifest.yaml').write_text(yaml.safe_dump(self.man))
    def test_legacy_import_unchanged(self):
        info=inspect(self.r);out=self.root/'copy';import_reference(info,out)
        self.assertEqual(sha(out/'groundtruth/data.csv'),sha(info['gt']))
        self.assertFalse((out/'groundtruth/data.csv').is_symlink())
        self.assertEqual(info['dataset'],(self.r/'01_preparation/dataset').resolve())
    def test_v5_paths(self):
        p=self.r/'01_preparation';(p/'inputs').mkdir();(p/'calibration.json').rename(p/'inputs/calibration.json')
        v=self.r/'03_vio';(v/'outputs').mkdir();(v/'oak4p_trajectory.csv').rename(v/'outputs/oak4p_trajectory.csv')
        self.man['version']=5;self.man['stages']['report']={'status':'failed'};self.save()
        self.assertIn('/outputs/',str(inspect(self.r)['trajectory']))
    def test_identity_mismatch(self):
        self.man['dataset']='/different';self.save()
        with self.assertRaisesRegex(ValueError,'identity'):inspect(self.r)
    def test_missing_gt_segments(self):
        (self.r/'02_mocap_alignment/state_groundtruth_estimate0/conversion.json').unlink()
        with self.assertRaisesRegex(ValueError,'conversion'):inspect(self.r)
    def test_invalid_trajectory(self):
        (self.r/'03_vio/oak4p_trajectory.csv').write_text('2,0,0,0,1,0,0,0\n1,0,0,0,1,0,0,0\n')
        with self.assertRaisesRegex(ValueError,'monotonic'):inspect(self.r)
    def test_mask_override(self):
        self.man['camera_masks']['enabled']=False;self.save()
        with self.assertRaisesRegex(ValueError,'mask'):inspect(self.r)
        self.assertTrue(inspect(self.r,self.r/'camera_masks')['masks'].is_dir())
    def test_missing_mask(self):
        (self.r/'camera_masks/cam3.png').unlink()
        with self.assertRaisesRegex(ValueError,'mask'):inspect(self.r)
    def test_time_offset_conflict(self):
        dump(self.r/'01_preparation/calibration.json',{'value0':{'cam_time_offset_ns':4}})
        with self.assertRaisesRegex(ValueError,'offset'):inspect(self.r)
    def test_broken_dataset(self):
        (self.r/'01_preparation/dataset/mav0').rmdir()
        with self.assertRaisesRegex(ValueError,'dataset'):inspect(self.r)
    def test_ambiguous_paths(self):
        p=self.r/'03_vio/outputs';p.mkdir();(p/'oak4p_trajectory.csv').write_text('different')
        with self.assertRaisesRegex(ValueError,'Conflicting'):inspect(self.r)
    def test_report_partial_and_immutable_manifest(self):
        r=self.root/'okvis';r.mkdir();m={'format':'okvis-vio','version':2,'status':'failed','parameters':{'name':'<script>alert(1)</script>'},'stages':{}}
        (r/'manifest.yaml').write_text(yaml.safe_dump(m));before=sha(r/'manifest.yaml')
        dest=generate(r)
        self.assertEqual(sha(r/'manifest.yaml'),before)
        page=dest.read_text();self.assertIn('&lt;script&gt;',page);self.assertNotIn('<script>alert',page)
        self.assertTrue(json.loads((r/'report/generation.json').read_text())['missing'])
    def test_configuration_type_difference(self):
        self.assertTrue(differences({'x':True},{'x':1}))
        self.assertEqual(differences({'x':[1,2]},{'x':[1,2]}),[])
    def test_readonly_source_snapshots(self):
        before=artifact_hashes(self.r);import_reference(inspect(self.r),self.root/'out')
        self.assertEqual(before,artifact_hashes(self.r))

class Reuse(unittest.TestCase):
    def test_changed_artifact_records_failed_run(self):
        import subprocess,sys
        with tempfile.TemporaryDirectory() as tmp:
            r=Path(tmp)/'prior';p=r/'01_preparation';p.mkdir(parents=True)
            (p/'x.json').write_text('original');expected=artifact_hashes(p);(p/'x.json').write_text('changed')
            m={'format':'okvis-vio','version':2,'status':'complete','parameters':{'dataset':tmp+'/data','prepared_dataset':tmp+'/data','basalt_run':tmp+'/baseline'},
               'stages':{'prepare':{'status':'complete','artifact_sha256':expected}}}
            (r/'manifest.yaml').write_text(yaml.safe_dump(m))
            out=Path(tmp)/'runs'
            result=subprocess.run([sys.executable,str(Path(__file__).with_name('run_vio_pipeline.py')),'--step','vio','--from-run',str(r),'--output',str(out)],capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0);self.assertIn('Prior artifacts changed',result.stderr)
            state=yaml.safe_load(next(out.glob('*/manifest.yaml')).read_text());self.assertEqual(state['status'],'failed')
    def test_required_run_and_removed_flags(self):
        import subprocess,sys
        cmd=[sys.executable,str(Path(__file__).with_name('run_vio_pipeline.py'))]
        for args,message in [([], '--basalt-run and --calibration-dir required'),(['--gt-mode','baseline'],'unrecognized arguments'),(['--basalt-root','x'],'unrecognized arguments')]:
            done=subprocess.run(cmd+args,capture_output=True,text=True)
            self.assertNotEqual(done.returncode,0);self.assertIn(message,done.stderr)
    def test_type_inside_array(self):
        self.assertTrue(differences({'a':[True]},{'a':[1]}))

if __name__=='__main__':unittest.main()
