"""Numerical checks for POC pose metrics and continuity boundaries."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from scipy.spatial.transform import Rotation
from evo.core import filters, metrics, units
from evo.core.trajectory import PoseTrajectory3D
from poc_evaluation import align, segment_labels, time_pairs, statistics, common_labels, evaluate_matched


class PocEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.ts=1792993000000000001+np.arange(200,dtype=np.int64)*33333333
        q=np.tile([1.,0.,0.,0.],(len(self.ts),1))
        p=np.c_[np.sin(np.arange(200)/30),np.cos(np.arange(200)/40),np.arange(200)/100]
        self.ref=PoseTrajectory3D(positions_xyz=p,orientations_quat_wxyz=q,timestamps=(self.ts-self.ts[0])/1e9)

    def test_rigid_gauge_is_removed_without_scale(self):
        est=copy.deepcopy(self.ref);t=np.eye(4)
        t[:3,:3]=Rotation.from_euler('xyz',[.2,.3,.4]).as_matrix();t[:3,3]=[3,4,2];est.transform(t)
        aligned,_=align(self.ref,est,self.ts,'motion')
        np.testing.assert_allclose(aligned.positions_xyz,self.ref.positions_xyz,atol=1e-12)
        ape=metrics.APE(metrics.PoseRelation.rotation_angle_deg);ape.process_data((self.ref,aligned))
        self.assertLess(ape.error.max(),1e-10)

    def test_static_alignment_does_not_fit_noise_position_rotation(self):
        q=np.tile([1.,0,0,0],(len(self.ts),1));ref=PoseTrajectory3D(positions_xyz=np.zeros((len(q),3)),orientations_quat_wxyz=q,timestamps=(self.ts-self.ts[0])/1e9)
        est=copy.deepcopy(ref);t=np.eye(4);t[:3,:3]=Rotation.from_euler('xyz',[.4,.5,.6]).as_matrix();t[:3,3]=[1,2,3];est.transform(t)
        aligned,_=align(ref,est,self.ts,'static')
        np.testing.assert_allclose(aligned.positions_xyz,ref.positions_xyz,atol=1e-12)

    def test_distance_translation_and_rotation_match_evo(self):
        p=self.ref.positions_xyz*1.02
        quat=Rotation.from_euler('z',np.linspace(0,.1,len(p))[:,None]).as_quat()[:,[3,0,1,2]]
        est=PoseTrajectory3D(positions_xyz=p,orientations_quat_wxyz=quat,timestamps=self.ref.timestamps)
        pairs=filters.filter_pairs_by_path(self.ref.poses_se3,.5,.05,True)
        errors=[metrics.RPE.rpe_base(self.ref.poses_se3[i],self.ref.poses_se3[j],est.poses_se3[i],est.poses_se3[j]) for i,j in pairs]
        for relation,expected in [(metrics.PoseRelation.translation_part,[np.linalg.norm(e[:3,3]) for e in errors]),(metrics.PoseRelation.rotation_angle_deg,np.rad2deg(Rotation.from_matrix(np.array([e[:3,:3] for e in errors])).magnitude()))]:
            metric=metrics.RPE(relation,delta=.5,delta_unit=units.Unit.meters,all_pairs=True,pairs_from_reference=True);metric.process_data((self.ref,est))
            np.testing.assert_allclose(metric.error,expected,atol=1e-10)

    def test_time_pairs_preserve_integer_epoch_and_tolerance(self):
        for delta in (.1,1.):
            pairs=time_pairs(self.ts,delta)
            elapsed=np.array([int(self.ts[j]-self.ts[i])/1e9 for i,j in pairs])
            self.assertTrue(np.all(abs(elapsed-delta)<=delta*.1+1e-9))
            self.assertEqual(len(set(i for i,j in pairs)),len(pairs))
        self.assertEqual(time_pairs(np.array([1,2],dtype=np.int64),1.),[])
        self.assertIsNone(statistics([]))

    def test_pairs_cannot_cross_gt_holes_output_gaps_or_resets(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);gt=p/'data.csv';gt.touch()
            ts=self.ts.copy();ts[100:]+=200000000
            (p/'conversion.json').write_text(json.dumps({'valid_segments_ns':[[int(ts[0]),int(ts[49])],[int(ts[50]),int(ts[-1])]]}))
            states=p/'states.csv';states.write_text(f'timestamp_ns,state_reset\n{ts[150]},1\n')
            labels=segment_labels(ts,gt,states)
            self.assertEqual(list(labels[[0,49,50,99,100,149,150,199]]),[0,0,1,1,2,2,3,3])
            valid=[(i,j) for i,j in time_pairs(ts,1) if labels[i]==labels[j]]
            self.assertTrue(all(not any(i<k<=j for k in (50,100,150)) for i,j in valid))

    def test_common_continuity_preserves_both_algorithms_boundaries(self):
        common=[10,20,30,40]
        labels=common_labels(common,{'okvis':{10:0,20:0,30:1,40:1},'basalt':{10:0,20:2,30:2,40:2}})
        self.assertEqual(labels.tolist(),[0,1,2,2])

    def test_stationary_metrics_keep_rotation_units_and_empty_pairs(self):
        from convert_okvis_trajectory import tum_time
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);ts=self.ts[:10]
            gt=''.join(f'{tum_time(int(t))} 0 0 0 0 0 0 1\n' for t in ts)
            # A fixed gauge rotation/translation must vanish under static pose alignment.
            q=Rotation.from_euler('z',.3).as_quat()
            est=''.join(f'{tum_time(int(t))} 1 2 3 '+ ' '.join(map(str,q))+'\n' for t in ts)
            (p/'mocap_at_vio.tum').write_text(gt);(p/'vio_matched.tum').write_text(est)
            r=evaluate_matched(p,'static',np.zeros(len(ts),dtype=int))
            self.assertLess(r['metrics']['ape_translation']['rmse'],1e-12)
            self.assertLess(r['metrics']['are_rotation']['rmse'],1e-10)
            self.assertEqual(r['metric_units']['are_rotation'],'deg')
            self.assertIn('rpe_translation_1s',r['unavailable_metrics'])
            self.assertEqual(r['metric_records']['rpe_translation_1s']['status'],'NOT_APPLICABLE')


if __name__=='__main__':unittest.main()
