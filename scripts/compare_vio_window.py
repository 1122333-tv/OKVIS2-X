#!/usr/bin/env python3
"""Re-evaluate a window in a new-format run; never rerun VIO."""
import argparse
from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path
import subprocess
import sys
import uuid
from pipeline_layout import read_manifest, artifact

def main():
    p=argparse.ArgumentParser(__doc__)
    p.add_argument('--run',type=Path,required=True);p.add_argument('--start',type=Decimal,default=Decimal(0))
    p.add_argument('--end',type=Decimal,required=True);p.add_argument('--show-gui',action='store_true')
    a=p.parse_args();r=a.run.resolve();read_manifest(r)
    if not a.start.is_finite() or not a.end.is_finite() or not 0<=a.start<a.end:p.error('Require finite 0 <= start < end')
    out=r/('window_'+str(a.start)+'_'+str(a.end)+'s_'+datetime.now().strftime('%Y%m%dT%H%M%S')+'_'+uuid.uuid4().hex[:6])
    cmd=[sys.executable,str(Path(__file__).with_name('compare_vio_runs.py')),'--okvis',str(artifact(r,'trajectory')),
         '--basalt',str(artifact(r,'basalt')),'--groundtruth',str(artifact(r,'gt')),'--output',str(out),
         '--input-first-ns',str(json.loads(artifact(r,'vio_summary').read_text())['input_first_imu_ns']),
         '--start',str(a.start),'--end',str(a.end)]
    if a.show_gui:cmd.append('--show-gui')
    subprocess.run(cmd,check=True);print(out)
if __name__=='__main__':main()
