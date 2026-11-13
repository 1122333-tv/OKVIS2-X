"""Measured-GT sampling and paired comparison regression checks."""
import csv
import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
import numpy as np
from convert_okvis_trajectory import write
from interpolate_mocap_to_vio import sample_at_mocap
from poc_evaluation import compare, segment_labels

class SparseMocapEvaluation(unittest.TestCase):
    def test_actual_gt_only_and_no_extrapolation_gap_or_reset(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);gt=p/'gt.csv';est=p/'est';origin=1_000_000_000
            times=[origin+i*100_000_000 for i in range(20)]
            gt.write_text('#timestamp,px,py,pz,qw,qx,qy,qz\n'+''.join(f'{t},1,2,3,1,0,0,0\n' for t in times))
            # High-rate estimates, with one missing bracket and one reset.
            ns=[origin+i*10_000_000 for i in range(181) if not 75<=i<=85]
            write([(t,[0,0,0,0,0,0,1]) for t in ns],est)
            states=p/'states.csv';states.write_text(f'timestamp_ns,state_reset\n{origin+1_005_000_000},1\n')
            info=sample_at_mocap(gt,est/'trajectory.tum',p/'out',states=states)
            self.assertFalse(info['gt_interpolated']);self.assertFalse(info['extrapolation'])
            accepted=[int(r[0]) for r in csv.reader((p/'out/mocap_at_vio.csv').read_text().splitlines()[1:])]
            self.assertTrue(set(accepted)<=set(times));self.assertNotIn(origin+800_000_000,accepted)
            self.assertNotIn(origin+1_900_000_000,accepted)
            audit=list(csv.DictReader((p/'out/interpolation_audit.csv').read_text().splitlines()))
            self.assertTrue(all(int(r['right_estimate_ns'])-int(r['left_estimate_ns'])<=50_000_000 for r in audit if r['status'] in ('exact','estimate_interpolated')))
            labels=segment_labels(np.array(times),gt,sampling='mocap',output_times=ns)
            self.assertNotEqual(labels[7],labels[9])

    def test_sparse_common_uses_interpolated_estimates_and_identical_pairs(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);gt=p/'data.csv';origin=1_000_000_000
            stamps=[origin+i*200_000_000+5_000_000 for i in range(16)]
            def pose(t):
                u=(t-origin)/1e9
                return [u,u*u/5,np.sin(u),0,0,0,1]
            gt.write_text('#timestamp,px,py,pz,qw,qx,qy,qz\n'+''.join(str(t)+','+','.join(map(str,[*pose(t)[:3],1,0,0,0]))+'\n' for t in stamps))
            (p/'conversion.json').write_text(json.dumps({'measurement_segments_ns':[[stamps[0],stamps[-1]]]}))
            tracks=[]
            for name,step in [('okvis',10_000_000),('basalt',20_000_000)]:
                folder=p/name;write([(t,pose(t)) for t in range(origin,origin+3_300_000_000,step)],folder);tracks.append(folder/'trajectory_euroc.csv')
            r=compare(SimpleNamespace(output=p/'comparison',input_first_ns=origin,start=Decimal(0),end=None,okvis=tracks[0],basalt=tracks[1],groundtruth=gt,evaluation_profile='motion',evaluation_sampling='mocap',basalt_states=None))
            self.assertEqual(r['common_timestamps']['n'],16);self.assertTrue(r['common_pairs_verified'])
            for v in r['common'].values():
                self.assertLess(v['metrics']['ape_translation']['rmse'],1e-4)
                self.assertIn('rpe_translation_1m',v['unavailable_metrics'])
                self.assertEqual(v['metric_records']['rpe_translation_1s']['stats']['n'],11)

if __name__=='__main__':unittest.main()
