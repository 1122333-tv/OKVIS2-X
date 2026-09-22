#!/usr/bin/env python3
"""Add sample count and linear-interpolated P95/P99 from evo's saved errors.

Uses only the standard library; reads one-dimensional float NPY arrays without
pickle. Original evo ZIP archives and their native statistics stay unchanged.
"""
import argparse
import ast
import json
import math
from pathlib import Path
import struct
from zipfile import ZipFile


def read_error_array(data):
    if data[:6] != b'\x93NUMPY' or len(data) < 10:
        raise ValueError('Invalid NPY error array')
    version = tuple(data[6:8])
    if version == (1, 0):
        start = 10
        length = struct.unpack('<H', data[8:10])[0]
    elif version in ((2, 0), (3, 0)) and len(data) >= 12:
        start = 12
        length = struct.unpack('<I', data[8:12])[0]
    else:
        raise ValueError(f'Unsupported NPY version: {version}')
    header = ast.literal_eval(data[start:start+length].decode('utf-8' if version == (3, 0) else 'latin1'))
    shape = header.get('shape')
    dtype = header.get('descr')
    if not isinstance(shape, tuple) or len(shape) != 1 or type(shape[0]) is not int or shape[0] <= 0:
        raise ValueError('Expected a nonempty one-dimensional error array')
    if dtype not in ('<f8', '>f8', '<f4', '>f4'):
        raise ValueError(f'Unsupported error dtype: {dtype}')
    body = data[start+length:]
    if len(body) != shape[0]*int(dtype[2]):
        raise ValueError('Error array payload length does not match shape')
    errors = [x[0] for x in struct.iter_unpack(dtype[0]+('d' if dtype[2] == '8' else 'f'), body)]
    if any(not math.isfinite(x) or x < 0 for x in errors):
        raise ValueError('Errors must be finite and nonnegative')
    return errors


def percentiles(errors):
    values = sorted(errors)
    def percentile(q):
        index = (len(values)-1)*q
        lo, hi = math.floor(index), math.ceil(index)
        return values[lo]+(values[hi]-values[lo])*(index-lo)
    return dict(n=len(values), p95=percentile(.95), p99=percentile(.99))


def read_stats(path, require_errors=True):
    with ZipFile(path) as archive:
        stats = json.loads(archive.read('stats.json'))
        if 'error_array.npy' not in archive.namelist():
            if require_errors:
                raise ValueError(f'Missing error_array.npy: {path}')
            return stats  # Legacy stats-only archives: no invented percentiles.
        stats.update(percentiles(read_error_array(archive.read('error_array.npy'))))
        return stats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('--append-text', type=Path)
    args = parser.parse_args()
    stats = read_stats(args.archive)
    output = args.archive.with_name(args.archive.stem+'_extended_stats.json')
    output.write_text(json.dumps(dict(source=args.archive.name,
                                     percentile_method='linear: (n-1)*q', stats=stats), indent=2)+'\n')
    text = ('\n补充统计：N 为误差样本数（APE 位姿 / RPE 帧对），P95/P99 与原指标同单位\n'
            f"{'n':>10}\t{stats['n']}\n{'p95':>10}\t{stats['p95']:.6f}\n{'p99':>10}\t{stats['p99']:.6f}\n")
    print(text, end='')
    if args.append_text:
        with args.append_text.open('a') as stream:
            stream.write(text)


if __name__ == '__main__':
    main()
