"""Analytic checks for pair indexing, rigid invariance and evaluation coverage."""
import tempfile
import unittest
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation
from evo.core.trajectory import PoseTrajectory3D
from analyze_vio_drift import pair_errors, export_pairs, analyze


class DriftMetricsTest(unittest.TestCase):
    def trajectory(self, positions, rot=None):
        n=len(positions)
        q=np.tile([1.,0.,0.,0.],(n,1)) if rot is None else rot
        return PoseTrajectory3D(np.array(positions,dtype=float),q,np.arange(n,dtype=float))

    def test_rigid_world_transform_does_not_change_rpe(self):
        import copy
        ref=self.trajectory([[0,0,0],[1,0,0],[1,1,0]])
        est=copy.deepcopy(ref)
        transform=np.eye(4);transform[:3,:3]=Rotation.from_euler('xyz',[.2,.3,.7]).as_matrix()
        transform[:3,3]=[3,4,5];est.transform(transform)
        tr,ro=pair_errors(ref,est,[(0,1),(0,2),(1,2)])
        np.testing.assert_allclose(tr,0,atol=1e-12)
        np.testing.assert_allclose(ro,0,atol=1e-12)

    def test_known_translation_and_pair_endpoint_window(self):
        ref=self.trajectory([[0,0,0],[.1,0,0],[.2,0,0]])
        est=self.trajectory([[0,0,0],[.12,0,0],[.24,0,0]])
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'pairs.csv'
            result=export_pairs(ref,est,[(0,1),(1,2)],np.array([43.9,44.1,55.1]),f)
            rows=np.loadtxt(f,delimiter=',',skiprows=1)
        np.testing.assert_allclose(rows[:,7],.02,atol=1e-12)
        self.assertEqual(result['windows']['event_44_55']['translation']['n'],1)
        self.assertEqual(result['windows']['normal_55_63']['translation']['n'],1)
        self.assertEqual(result['windows']['event_44_55']['crossing_pairs'],1)

    def test_cancellation_reaps_owned_child_before_return(self):
        import os,sys,threading,time
        from run_vio_drift_experiment import run_owned_process
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);cancel=root/'CANCEL';pidfile=root/'child.pid'
            def request_cancel():
                deadline=time.monotonic()+5
                while not pidfile.exists() and time.monotonic()<deadline:time.sleep(.01)
                cancel.write_text('test cancellation')
            thread=threading.Thread(target=request_cancel);thread.start()
            code="import os,time;from pathlib import Path;Path('child.pid').write_text(str(os.getpid()));time.sleep(300)"
            with (root/'log').open('w') as log:
                with self.assertRaisesRegex(RuntimeError,'cancellation requested'):
                    run_owned_process([sys.executable,'-c',code],root,os.environ.copy(),log,cancel)
            thread.join()
            with self.assertRaises(ProcessLookupError):os.kill(int(pidfile.read_text()),0)

    def test_bias_timestamp_keeps_nanosecond_precision(self):
        from summarize_vio_diagnostics import trajectory_bias
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'online.csv';stamp=1789539918207227402
            path.write_text('timestamp, b_g_x, b_g_y, b_g_z, b_a_x, b_a_y, b_a_z\n'
                            +f'{stamp}, 1, 2, 3, 4, 5, 6\n')
            rows=trajectory_bias(path,stamp-17)
            self.assertEqual(rows[0]['timestamp_ns'],stamp)
            self.assertEqual(rows[0]['time_s'],17e-9)
            self.assertEqual(rows[0]['b_a_z'],6.)

    def test_rotation_units_degrees(self):
        ref=self.trajectory([[0,0,0],[0,0,0]])
        q=Rotation.from_euler('z',[[0],[10]],degrees=True).as_quat()[:,[3,0,1,2]]
        est=self.trajectory([[0,0,0],[0,0,0]],q)
        tr,ro=pair_errors(ref,est,[(0,1)])
        np.testing.assert_allclose(tr,0,atol=1e-12)
        np.testing.assert_allclose(ro,10,atol=1e-12)

    def test_dropped_tail_outside_gt_support_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);base=root/'baseline'
            gt=base/'04_vio_comparison/common/okvis/mocap_at_vio.tum'
            gt.parent.mkdir(parents=True)
            gt.write_text(''.join(f'{i}.000000000 0 0 0 0 0 0 1\n' for i in range(1,7)))
            source=base/'03_vio/outputs/okvis2-vio_trajectory.csv'
            source.parent.mkdir(parents=True)
            source.write_text(''.join(f'{i*10**9},0,0,0,0,0,0,1\n' for i in range(1,8)))
            candidate=root/'candidate.csv'
            candidate.write_text(''.join(source.read_text().splitlines(keepends=True)[:-1]))
            with self.assertRaisesRegex(ValueError,'Full output timestamp coverage'):
                analyze(candidate,base,root/'analysis')


if __name__=='__main__': unittest.main()
