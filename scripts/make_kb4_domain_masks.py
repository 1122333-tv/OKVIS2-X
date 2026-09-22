#!/usr/bin/env python3
"""Intersect Basalt exclusion masks with the first monotonic KB4 branch."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

import numpy as np
from PIL import Image


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--calibration', type=Path, required=True)
    parser.add_argument('--source-mask-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--margin-px', type=float, default=2.0)
    args = parser.parse_args()
    if not np.isfinite(args.margin_px) or args.margin_px <= 0:
        parser.error('--margin-px must be finite and positive')
    calibration = json.loads(args.calibration.read_text())['value0']
    if len(calibration['intrinsics']) != 4 or len(calibration['resolution']) != 4:
        parser.error('Expected four cameras')
    records, masks = [], []
    for i, camera in enumerate(calibration['intrinsics']):
        if camera['camera_type'] != 'kb4':
            raise ValueError('Only KB4 supported')
        p = camera['intrinsics']
        if not all(np.isfinite(v) for v in p.values()) or min(p['fx'], p['fy']) <= 0:
            raise ValueError('Invalid camera intrinsics')
        k = np.array([p[f'k{j}'] for j in range(1, 5)])
        # d(rho)/d(theta) is a quartic in theta**2. Stop at its first
        # positive zero, or the front-hemisphere boundary, whichever is first.
        roots = np.polynomial.polynomial.polyroots([1, *((2*np.arange(1, 5)+1)*k)])
        limits = [np.sqrt(z.real) for z in roots
                  if abs(z.imag) < 1e-10 and 0 < z.real < (np.pi/2)**2]
        theta = min([np.pi/2, *limits])
        radius = theta + sum(k[j-1]*theta**(2*j+1) for j in range(1, 5))
        # min(fx,fy) gives a conservative normalized margin in all directions.
        safe_radius = radius - args.margin_px/min(p['fx'], p['fy'])
        if safe_radius <= 0:
            raise ValueError('Margin leaves no valid domain')
        source = args.source_mask_dir/f'cam{i}.png'
        mask = np.asarray(Image.open(source).convert('L'))
        if list(mask.shape[::-1]) != calibration['resolution'][i]:
            raise ValueError('Mask resolution mismatch')
        y, x = np.indices(mask.shape)
        rho = np.hypot((x-p['cx'])/p['fx'], (y-p['cy'])/p['fy'])
        valid = (mask <= 127) & (rho <= safe_radius)
        if not valid.any():
            raise ValueError('Empty valid mask')
        masks.append(np.where(valid, 0, 255).astype('uint8'))
        records.append(dict(camera=i, source=str(source.resolve()), source_sha256=digest(source),
                            theta_limit_deg=float(np.degrees(theta)), radius_limit=float(radius),
                            safe_radius=float(safe_radius), intrinsics=p,
                            source_valid_pixels=int((mask <= 127).sum()),
                            valid_pixels=int(valid.sum()),
                            newly_excluded_pixels=int(((mask <= 127) & ~valid).sum())))
    args.output.mkdir(parents=True, exist_ok=False)
    for i, mask in enumerate(masks):
        target = args.output/f'cam{i}.png'
        Image.fromarray(mask).save(target)
        records[i]['output_sha256'] = digest(target)
    shutil.copyfile(__file__, args.output/'generator.py')
    report = dict(calibration=str(args.calibration.resolve()), calibration_sha256=digest(args.calibration),
                  margin_px=args.margin_px, mask_convention='Basalt: 0 valid, 255 excluded',
                  policy='Original valid pixels intersected with first monotonic front-facing KB4 branch',
                  generator_sha256=digest(__file__), cameras=records)
    (args.output/'manifest.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
