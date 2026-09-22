#!/usr/bin/env python3
"""Interpolate derived IMU ground truth at exact VIO timestamps, without extrapolation."""
import argparse
import bisect
import csv
import json
import math
from pathlib import Path
from capture_pipeline_common import read_poses, ns_seconds, tum_time, slerp, write_json


def interpolate(gt_path, trajectory, output, max_gap_ns=50_000_000):
    poses,qa=read_poses(gt_path,max_gap_ns=max_gap_ns)
    conversion=gt_path.with_name('conversion.json')
    intervals=json.loads(conversion.read_text()).get('valid_segments_ns') if conversion.exists() else None
    # Ground truth conversion may have removed invalid rows. Its segment metadata
    # preserves those holes even if neighbouring valid timestamps are close.
    times=[p[0] for p in poses];starts=[r[0] for r in intervals] if intervals else []
    def same_segment(lo,hi):
        if not intervals:return True
        i=bisect.bisect_right(starts,lo)-1
        return i>=0 and lo>=intervals[i][0] and hi<=intervals[i][1]
    output.mkdir(parents=True,exist_ok=True)
    estimates=[];previous=None
    for line in trajectory.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith('#'):continue
        r=line.split()
        if len(r)!=8:raise ValueError('Expected TUM t xyz xyzw')
        t=ns_seconds(r[0],allow_rounding=True);v=list(map(float,r[1:]))
        if not all(math.isfinite(x) for x in v) or abs(sum(x*x for x in v[3:])-1)>.01:raise ValueError('Invalid VIO pose')
        if previous is not None and t<=previous:raise ValueError('VIO timestamps must strictly increase')
        previous=t;estimates.append((t,r[1:]))
    accepted=[];audit=[]
    for t,v in estimates:
        j=bisect.bisect_left(times,t)
        if j<len(times) and times[j]==t:
            _,p,q,_=poses[j];accepted.append((t,p,q,v));audit.append([t,'exact',t,t,0]);continue
        if j==0 or j==len(times):audit.append([t,'outside_gt_coverage','','','']);continue
        a,b=poses[j-1],poses[j]
        if a[3]!=b[3] or b[0]-a[0]>max_gap_ns or not same_segment(a[0],b[0]):
            audit.append([t,'invalid_or_large_gap',a[0],b[0],'']);continue
        weight=(t-a[0])/(b[0]-a[0])
        p=[x+(y-x)*weight for x,y in zip(a[1],b[1])];q=slerp(a[2],b[2],weight)
        accepted.append((t,p,q,v));audit.append([t,'interpolated',a[0],b[0],weight])
    with (output/'mocap_imu.tum').open('w') as f:
        for t,p,q,_ in poses:f.write(f'{tum_time(t)} '+ ' '.join(map(str,[*p,*q[1:],q[0]]))+'\n')
    with (output/'mocap_at_vio.csv').open('w') as f:
        f.write('#timestamp [ns],px,py,pz,qw,qx,qy,qz\n')
        csv.writer(f).writerows([t,*p,*q] for t,p,q,v in accepted)
    with (output/'mocap_at_vio.tum').open('w') as g,(output/'vio_matched.tum').open('w') as e:
        for t,p,q,v in accepted:
            g.write(f'{tum_time(t)} '+' '.join(map(str,[*p,*q[1:],q[0]]))+'\n')
            e.write(f'{tum_time(t)} '+' '.join(v)+'\n')
    with (output/'interpolation_audit.csv').open('w') as f:
        w=csv.writer(f);w.writerow(['vio_timestamp_ns','status','left_gt_ns','right_gt_ns','weight']);w.writerows(audit)
    result=dict(input_vio_poses=len(estimates),accepted_poses=len(accepted),skipped_poses=len(estimates)-len(accepted),max_gap_ns=max_gap_ns,position='linear in mocap world',orientation='shortest-arc SLERP, wxyz internally',extrapolation=False,tum_timestamp_conversion='Decimal seconds rounded to nearest integer ns (Basalt exports floating seconds)',gt=str(gt_path.resolve()),trajectory=str(trajectory.resolve()),invalid_segments_source=str(conversion.resolve()) if conversion.exists() else None)
    write_json(output/'interpolation.json',result)
    if len(accepted)<5:raise ValueError('Fewer than 5 valid overlapping interpolated poses; see interpolation.json')
    return result


def main():
    ap=argparse.ArgumentParser(__doc__)
    ap.add_argument('--groundtruth',required=True,type=Path);ap.add_argument('--trajectory',required=True,type=Path)
    ap.add_argument('--output',required=True,type=Path);ap.add_argument('--max-gap-ms',type=float,default=50)
    a=ap.parse_args()
    if not math.isfinite(a.max_gap_ms) or a.max_gap_ms<=0:ap.error('max-gap-ms must be finite and positive')
    print(json.dumps(interpolate(a.groundtruth,a.trajectory,a.output,round(a.max_gap_ms*1e6)),indent=2))
if __name__=='__main__':main()
