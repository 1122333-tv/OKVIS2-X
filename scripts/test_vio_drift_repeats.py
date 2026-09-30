import json
from pathlib import Path
import tempfile
import unittest
from validate_vio_drift_repeats import validate

class DriftAcceptance(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.baseline=[];self.candidate=[]
        for group,value in [(self.baseline,1.0),(self.candidate,.5)]:
            for i in range(3):
                r=self.root/(('baseline' if group is self.baseline else 'candidate')+str(i));r.mkdir();group.append(r)
                meta=dict(status='complete',diagnostic_input_only=False,binary_sha256='binary',input_hashes_sha256='input',input_indices={},masks={},runtime_libraries={})
                (r/'experiment.json').write_text(json.dumps(meta));(r/'stage.log').write_text('SAMPLING deterministic=1 seed=12345')
                (r/'outputs').mkdir();(r/'outputs/okvis2-vio_trajectory.csv').write_text('timestamp,values\n'+''.join(str(t)+','+','.join(map(str,[0]*6+[1]+[0]*9))+',\n' for t in [1,2]))
                final='timestamp,'+','.join(['state']*16)+',NrGps,SID,gpsMode,keyframeId\n'
                final+=''.join(str(t)+','+','.join(map(str,[0]*6+[1]+[0]*9+[0,t,0,0]))+'\n' for t in [1,2])
                for suffix in ['final','final-ba']:(r/f'outputs/okvis2-vio-{suffix}_trajectory.csv').write_text(final)
                windows={w:dict(translation=dict(rmse=value,p95=value,max=value)) for w in ['event_44_55','event_63_66','normal_0_44','normal_55_63','normal_66_end']}
                summary=dict(poses=2,common_poses=2,reference_sha256='gt',ape=dict(rmse=value),metrics={'0.1m':dict(pair_sha256='pairs',windows=windows)})
                (r/'analysis').mkdir();(r/'analysis/summary.json').write_text(json.dumps(summary))
    def test_exact_half_boundary_and_repeatability(self):
        r=validate(self.baseline,self.candidate)
        self.assertTrue(r['repeatability_pass']);self.assertTrue(r['relative_accuracy_pass'])
    def test_final_exports_included(self):
        r=validate(self.baseline,self.candidate,True)
        self.assertTrue(r['repeatability_pass'])
        self.assertTrue(r['groups']['candidate']['final_exports']['byte_identical'])
    def test_uninitialized_final_metadata_rejected(self):
        p=self.candidate[0]/'outputs/okvis2-vio-final_trajectory.csv'
        text=p.read_text().splitlines();row=text[1].split(',');row[19]='99112921';text[1]=','.join(row);p.write_text('\n'.join(text)+'\n')
        with self.assertRaisesRegex(ValueError,'GPS metadata'):validate(self.baseline,self.candidate,True)
    def test_final_physical_state_difference_fails_repeatability(self):
        for suffix in ['final','final-ba']:
            p=self.candidate[0]/f'outputs/okvis2-vio-{suffix}_trajectory.csv'
            text=p.read_text().splitlines();row=text[1].split(',');row[1]='0.01';text[1]=','.join(row);p.write_text('\n'.join(text)+'\n')
        self.assertFalse(validate(self.baseline,self.candidate,True)['repeatability_pass'])
    def test_reused_launch_rejected(self):
        with self.assertRaisesRegex(ValueError,'independent'):validate(self.baseline,[self.candidate[0]]*3)
    def test_pair_change_rejected(self):
        p=self.candidate[0]/'analysis/summary.json';d=json.loads(p.read_text());d['metrics']['0.1m']['pair_sha256']='different';p.write_text(json.dumps(d))
        with self.assertRaisesRegex(ValueError,'pairs'):validate(self.baseline,self.candidate)
    def test_runtime_change_rejected(self):
        p=self.candidate[0]/'experiment.json';d=json.loads(p.read_text());d['runtime_libraries']={'lib':'other'};p.write_text(json.dumps(d))
        with self.assertRaisesRegex(ValueError,'runtime'):validate(self.baseline,self.candidate)
    def test_midpoint_above_threshold_fails(self):
        for r in self.candidate[:2]:
            p=r/'analysis/summary.json';d=json.loads(p.read_text());d['ape']['rmse']=.5001;p.write_text(json.dumps(d))
        self.assertFalse(validate(self.baseline,self.candidate)['relative_accuracy_pass'])
    def test_new_trigger_window_regression_is_not_hidden_by_legacy_gates(self):
        for runs,value in [(self.baseline,.01),(self.candidate,.03)]:
            for r in runs:
                p=r/'analysis/summary.json';d=json.loads(p.read_text())
                d['metrics']['0.1m']['windows']['trigger_34_38']={'translation':{'rmse':value}}
                p.write_text(json.dumps(d))
        result=validate(self.baseline,self.candidate)
        self.assertTrue(result['relative_accuracy_pass'])
        self.assertFalse(result['all_window_accuracy_pass'])

if __name__=='__main__':unittest.main()
