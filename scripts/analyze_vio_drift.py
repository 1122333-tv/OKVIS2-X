#!/usr/bin/env python3
"""Evaluate fixed timestamps and GT-selected pairs without fitting timing or scale."""
import argparse
import copy
import csv
import hashlib
import json
from decimal import Decimal
from pathlib import Path

import numpy as np
from evo.core import metrics, units
from evo.core.trajectory import PoseTrajectory3D
from evo.tools import file_interface
from convert_okvis_trajectory import load

WINDOWS = {'trigger_34_38':(34,38),'pre_trigger_15_35':(15,35),'normal_0_44': (0, 44), 'event_44_55': (44, 55),
           'normal_55_63': (55, 63), 'event_63_66': (63, 66),
           'normal_66_end': (66, float('inf'))}


def stats(a):
    a = np.asarray(a)
    return dict(n=len(a), rmse=float(np.sqrt(np.mean(a*a))),
                p95=float(np.quantile(a, .95)), max=float(a.max())) if len(a) else dict(n=0)


def pair_errors(ref, est, pairs):
    errors = [metrics.RPE.rpe_base(ref.poses_se3[i], ref.poses_se3[j],
                                 est.poses_se3[i], est.poses_se3[j]) for i, j in pairs]
    trans = np.array([np.linalg.norm(e[:3, 3]) for e in errors])
    from evo.core import lie_algebra
    rot = np.array([abs(lie_algebra.so3_log_angle(e[:3, :3], True)) for e in errors])
    return trans, rot


def analyze(trajectory, baseline, output):
    output.mkdir(parents=True, exist_ok=False)
    gt_file = baseline/'04_vio_comparison/common/okvis/mocap_at_vio.tum'
    ref = file_interface.read_tum_trajectory_file(str(gt_file))
    rows = load(trajectory)
    baseline_rows = load(baseline/'03_vio/outputs/okvis2-vio_trajectory.csv')
    if [t for t,_ in rows] != [t for t,_ in baseline_rows]:
        raise ValueError('Full output timestamp coverage changed, including poses outside GT support')
    indexed = dict(rows)
    stamps = np.array([int(Decimal(line.split()[0])*1_000_000_000)
                       for line in gt_file.read_text().splitlines()
                       if line.strip() and not line.lstrip().startswith('#')],dtype=np.int64)
    missing = [int(t) for t in stamps if int(t) not in indexed]
    if missing:
        raise ValueError(f'Missing {len(missing)} frozen common poses; do not silently shrink evaluation')
    poses = np.array([indexed[int(t)] for t in stamps])
    est = PoseTrajectory3D(poses[:, :3], poses[:, [6, 3, 4, 5]], ref.timestamps)
    origin = rows[0][0]
    expected_origin = baseline_rows[0][0]
    if origin != expected_origin:
        raise ValueError('Input origin changed')
    times = (stamps-origin)/1e9
    aligned = copy.deepcopy(est)
    aligned.align(ref, correct_scale=False)
    ape = np.linalg.norm(aligned.positions_xyz-ref.positions_xyz, axis=1)
    result = dict(trajectory=str(trajectory), origin_ns=origin, poses=len(rows),
                  common_poses=len(stamps), ape=stats(ape), metrics={},
                  reference_sha256=hashlib.sha256(gt_file.read_bytes()).hexdigest(),
                  trajectory_sha256=hashlib.sha256(trajectory.read_bytes()).hexdigest())
    # Use moving data before the user-reported window; the 36 s precursor is audited separately.
    fit_ids = np.flatnonzero((times >= 15) & (times < 40))
    ref_fit, est_fit = copy.deepcopy(ref), copy.deepcopy(est)
    ref_fit.reduce_to_ids(fit_ids); est_fit.reduce_to_ids(fit_ids)
    spread = np.linalg.svd(ref_fit.positions_xyz-ref_fit.positions_xyz.mean(axis=0),
                           compute_uv=False)/np.sqrt(len(fit_ids))
    if spread[1] >= .01:
        r, t, _ = est_fit.align(ref_fit, correct_scale=False)
        early_ape = np.linalg.norm((r@est.positions_xyz.T).T+t-ref.positions_xyz, axis=1)
        result['pre_event_alignment'] = dict(window_s=[15, 40], spread_m=spread.tolist(),
                                               windows={k: stats(early_ape[(times>=a)&(times<b)])
                                                        for k,(a,b) in WINDOWS.items()})
    else:
        early_ape = np.full(len(times), np.nan)
        result['pre_event_alignment'] = dict(status='insufficient motion', spread_m=spread.tolist())
    # Additional fixed window ends before the input-only 36.05 s trigger.
    # Keep the original 15-40 s supplemental evaluation for historical comparability.
    trigger_ids=np.flatnonzero((times>=15)&(times<35))
    trigger_ref,trigger_est=copy.deepcopy(ref),copy.deepcopy(est)
    trigger_ref.reduce_to_ids(trigger_ids);trigger_est.reduce_to_ids(trigger_ids)
    trigger_spread=np.linalg.svd(trigger_ref.positions_xyz-trigger_ref.positions_xyz.mean(axis=0),
                                compute_uv=False)/np.sqrt(len(trigger_ids))
    if trigger_spread[1]>=.01:
        r,t,_=trigger_est.align(trigger_ref,correct_scale=False)
        trigger_ape=np.linalg.norm((r@est.positions_xyz.T).T+t-ref.positions_xyz,axis=1)
        result['pre_trigger_alignment']=dict(window_s=[15,35],spread_m=trigger_spread.tolist(),
                                             windows={k:stats(trigger_ape[(times>=a)&(times<b)])
                                                      for k,(a,b) in WINDOWS.items()})
    else:
        trigger_ape=np.full(len(times),np.nan)
        result['pre_trigger_alignment']=dict(status='insufficient motion',spread_m=trigger_spread.tolist())
    np.savetxt(output/'ape.csv', np.column_stack([times,ape,early_ape,trigger_ape]),delimiter=',',
               header='time_s,full_alignment_m,pre_event_alignment_m,pre_trigger_alignment_m',comments='')
    for label, delta in [('0.1m', .1), ('0.5m', .5), ('1m', 1.)]:
        pairs = metrics.id_pairs_from_delta(ref.poses_se3,delta,units.Unit.meters,.1,all_pairs=True)
        result['metrics'][label] = export_pairs(ref,est,pairs,times,output/('rpe_'+label+'.csv'))
    # Frame offsets approximate time only after confirming cadence; export actual dt.
    for delta in (.1, 1.):
        pairs=[]
        for i, stamp in enumerate(ref.timestamps):
            j=int(np.searchsorted(ref.timestamps,stamp+delta-.0005))
            if j<len(times) and abs(ref.timestamps[j]-stamp-delta)<.001:
                pairs.append((i,j))
        result['metrics'][f'{delta:g}s'] = export_pairs(ref,est,pairs,times,output/f'rpe_{delta:g}s.csv')
    (output/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


def export_pairs(ref, est, pairs, times, path):
    tr, ro = pair_errors(ref,est,pairs)
    pairs=np.asarray(pairs,dtype=int)
    start,end=times[pairs[:,0]],times[pairs[:,1]]
    distance=np.array([np.linalg.norm(ref.positions_xyz[j]-ref.positions_xyz[i]) for i,j in pairs])
    arc=ref.distances[pairs[:,1]]-ref.distances[pairs[:,0]]
    cross=np.array([any(a<c<=b for c in (44,55,63,66)) for a,b in zip(start,end)])
    np.savetxt(path,np.column_stack([pairs,start,end,end-start,distance,arc,tr,ro,cross]),delimiter=',',
               header='i,j,start_s,end_s,dt_s,reference_chord_m,reference_arc_m,translation_m,rotation_deg,cross_window',comments='')
    return dict(translation=stats(tr),rotation_deg=stats(ro),
                pair_sha256=hashlib.sha256(pairs.tobytes()).hexdigest(),
                windows={k:dict(translation=stats(tr[(end>=a)&(end<b)]),
                                rotation_deg=stats(ro[(end>=a)&(end<b)]),
                                crossing_pairs=int(cross[(end>=a)&(end<b)].sum()))
                         for k,(a,b) in WINDOWS.items()})


if __name__=='__main__':
    p=argparse.ArgumentParser(__doc__)
    p.add_argument('--trajectory',required=True,type=Path)
    p.add_argument('--baseline',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path)
    a=p.parse_args(); print(json.dumps(analyze(a.trajectory,a.baseline,a.output)['ape']))
