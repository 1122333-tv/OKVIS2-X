#!/usr/bin/env python3
"""Freeze a debug executable with its build configuration, sources and runtime libraries."""
from pathlib import Path
import subprocess,sys,shutil,json,hashlib,re
import argparse
p=argparse.ArgumentParser(__doc__);p.add_argument('--output',required=True,type=Path);p.add_argument('--build-dir',type=Path,default=Path('build-vio'));a=p.parse_args()
out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
for n in ['okvis_app_synchronous','small_voc.yml.gz','CMakeCache.txt']:shutil.copy2(a.build_dir/n,out/n)
src=out/'build_sources';src.mkdir()
(src/'head.txt').write_bytes(subprocess.check_output(['git','rev-parse','HEAD']))
(src/'build.diff').write_bytes(subprocess.check_output(['git','diff','--binary','HEAD']))
for name in subprocess.check_output(['git','ls-files','--others','--exclude-standard'],text=True).splitlines():
 p=Path(name)
 if p.is_file() and p.parts[0] in ['scripts','okvis_frontend','okvis_ceres']:
  d=src/'untracked'/p;d.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,d)
for name in ['DBoW2','opengv']:
 (src/(name+'.diff')).write_bytes(subprocess.check_output(['git','-C','external/'+name,'diff','--binary']))
 (src/(name+'.head')).write_bytes(subprocess.check_output(['git','-C','external/'+name,'rev-parse','HEAD']))
ldd=subprocess.check_output(['ldd',str(out/'okvis_app_synchronous')],text=True);(out/'ldd.txt').write_text(ldd)
libs={p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in re.findall(r'(/\S+) \(',ldd) if Path(p).is_file()}
(out/'libraries.json').write_text(json.dumps(libs,indent=2))
(out/'bundle.json').write_text(json.dumps({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir() if p.is_file()},indent=2))
