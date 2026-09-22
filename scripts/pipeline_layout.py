"""OKVIS standalone evaluation layout. No legacy OKVIS reader."""
from pathlib import Path
import hashlib
import json
import yaml

VERSION = 2
STAGES = {'prepare':'01_preparation','reference':'02_reference','vio':'03_vio','compare':'04_vio_comparison','report':'report'}
PATHS = {
 'dataset':'01_preparation/outputs/dataset',
 'config':'03_vio/inputs/okvis2.yaml',
 'trajectory':'03_vio/outputs/trajectory_euroc.csv',
 'vio_summary':'03_vio/outputs/trajectory_summary.json',
 'gt':'02_reference/inputs/groundtruth/data.csv',
 'basalt':'02_reference/inputs/basalt_trajectory.csv',
 'comparison':'04_vio_comparison/summary/summary.json',
}
def artifact(root, key):return Path(root)/PATHS[key]
def read_manifest(root):
    m=yaml.safe_load((Path(root)/'manifest.yaml').read_text())
    if m.get('format')!='okvis-vio' or m.get('version')!=VERSION:
        raise ValueError('Unsupported historical OKVIS run; create a new version-2 run')
    return m
def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()
def dump(path,obj):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,indent=2,ensure_ascii=False,allow_nan=False)+'\n')
def artifact_hashes(directory):
    return {str(p.relative_to(directory)):sha(p) for p in sorted(Path(directory).rglob('*')) if p.is_file() and not p.is_symlink()}
