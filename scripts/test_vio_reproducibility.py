import copy
import tempfile
from pathlib import Path
import unittest
import numpy as np
from compare_vio_states import compare, compare_group, read_states
from run_vio_reproducibility import profile_config

class Reproducibility(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.values=np.zeros((2,16));self.values[:,6]=1
    def file(self,name,values=None,stamps=(44613731516,44647068516)):
        values=self.values if values is None else values;p=self.root/name
        p.write_text('timestamp,values\n'+''.join(str(t)+','+','.join(format(x,'.18e') for x in row)+',\n' for t,row in zip(stamps,values)))
        return p
    def test_exact(self):
        r=compare(self.file('a'),self.file('b'))
        self.assertTrue(r['states_exact']);self.assertTrue(r['byte_identical']);self.assertEqual(r['max_rotation_difference_rad'],0)
    def test_bias_is_not_ignored(self):
        v=self.values.copy();v[1,13]=1e-12;r=compare(self.file('a'),self.file('b',v))
        self.assertFalse(r['states_exact']);self.assertTrue(r['pose_exact']);self.assertEqual(r['fields']['bax']['first_different_timestamp_ns'],44647068516)
    def test_timestamp_mismatch(self):
        r=compare(self.file('a'),self.file('b',stamps=(44613731517,44647068517)))
        self.assertFalse(r['timestamps_equal']);self.assertFalse(r['states_exact'])
    def test_quaternion_sign_is_reported(self):
        v=self.values.copy();v[:,6]=-1;r=compare(self.file('a'),self.file('b',v))
        self.assertFalse(r['pose_exact']);self.assertEqual(r['max_rotation_difference_rad'],0)
    def test_reject_invalid(self):
        for value in (float('nan'),float('inf')):
            v=self.values.copy();v[0,0]=value
            with self.assertRaises(ValueError):read_states(self.file('a',v))
        with self.assertRaises(ValueError):read_states(self.file('a',stamps=(1,1)))
        with self.assertRaises(ValueError):compare_group([self.file('a')])
    def test_profiles_only_change_authorized_keys(self):
        cfg={'cameras':[{}]*4,'estimator_parameters':{'realtime_num_threads':3,'enforce_realtime':False,'do_loop_closures':False,'do_final_ba':False},'frontend_parameters':{'parallelise_detection':True,'num_matching_threads':4}}
        original=copy.deepcopy(cfg);solver=profile_config(cfg,'solver-single')
        self.assertEqual(cfg,original);self.assertEqual(solver['frontend_parameters'],cfg['frontend_parameters'])
        self.assertEqual(solver['estimator_parameters']['realtime_num_threads'],1)
        serial=profile_config(cfg,'frontend-single');self.assertFalse(serial['frontend_parameters']['parallelise_detection']);self.assertEqual(serial['frontend_parameters']['num_matching_threads'],1)
        cfg['estimator_parameters']['enforce_realtime']=True
        with self.assertRaises(ValueError):profile_config(cfg,'solver-single')

if __name__=='__main__':unittest.main()
