"""Read the calibration project's complete physical-camera rig delivery."""
import hashlib
import json
import math
from pathlib import Path

CAMERAS = ['cam0', 'cam1', 'cam2', 'cam3']
# Keep in sync with GenericCamera::VariantT and cereal's named parameters.
MODEL_FIELDS = {
    'pinhole': 'fx fy cx cy',
    'eucm': 'fx fy cx cy alpha beta',
    'ds': 'fx fy cx cy xi alpha',
    'kb4': 'fx fy cx cy k1 k2 k3 k4',
    'ucm': 'fx fy cx cy alpha',
    'pinhole-radtan8': 'fx fy cx cy k1 k2 p1 p2 k3 k4 k5 k6 rpmax',
    'fisheye624': 'fx fy cx cy k1 k2 k3 k4 k5 k6 p1 p2 s1 s2 s3 s4',
}


def validate_pose(pose):
    values = [pose[k] for k in ('px', 'py', 'pz', 'qw', 'qx', 'qy', 'qz')]
    if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in values):
        raise ValueError('Invalid calibration transform')
    if abs(sum(pose[k]**2 for k in ('qw', 'qx', 'qy', 'qz')) - 1) > 1e-5:
        raise ValueError('Calibration quaternion must have unit norm')


def load_delivery(directory, require_mocap=False):
    directory = Path(directory)
    manifest = json.loads((directory/'export_manifest.json').read_text())
    if manifest.get('schema_version') != 1 or manifest.get('camera_order') != CAMERAS:
        raise ValueError('Expected schema 1 delivery in physical cam0..cam3 order')
    reference = manifest.get('time_reference_camera', manifest.get('calibrated_camera'))
    if reference not in CAMERAS:
        raise ValueError('Delivery must identify its camera time reference')
    required = ['calibration.json', 'export_manifest.json']
    if require_mocap:
        required += ['mocap_calibration.json', 'mocap_imu_time_offset.json']
    for name in required:
        if not (directory/name).is_file():
            raise ValueError(f'Missing delivery file: {name}')
    hashes = manifest.get('files_sha256', {})
    for name, expected in hashes.items():
        if Path(name).name != name:
            raise ValueError('Delivery hashes must refer to local filenames')
        path = directory/name
        if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f'Delivery hash mismatch: {name}')
    obj = json.loads((directory/'calibration.json').read_text())
    c = obj['value0']
    for key in ('T_imu_cam', 'intrinsics', 'resolution'):
        if len(c[key]) != 4:
            raise ValueError(f'Complete rig requires four {key} entries')
    if len(c.get('vignette', [])) not in (0, 4):
        raise ValueError('Vignette must be empty or contain four entries')
    for pose in c['T_imu_cam']:
        validate_pose(pose)
    for intr, resolution in zip(c['intrinsics'], c['resolution']):
        if intr['camera_type'] not in MODEL_FIELDS:
            raise ValueError(f'Unsupported camera model: {intr["camera_type"]}')
        values = intr['intrinsics']
        if not set(MODEL_FIELDS[intr['camera_type']].split()).issubset(values):
            raise ValueError('Missing camera intrinsic parameters')
        if values['fx'] <= 0 or values['fy'] <= 0:
            raise ValueError('Camera focal lengths must be positive')
        if not all(math.isfinite(v) for v in values.values()):
            raise ValueError('Nonfinite camera intrinsics')
        if len(resolution) != 2 or any(type(v) is not int or v <= 0 for v in resolution):
            raise ValueError('Invalid camera resolution')
    if type(c['cam_time_offset_ns']) is not int or abs(c['cam_time_offset_ns']) >= 100_000_000:
        raise ValueError('Invalid camera time offset')
    for key, size in [('calib_accel_bias', 9), ('calib_gyro_bias', 12),
                      ('accel_noise_std', 3), ('gyro_noise_std', 3),
                      ('accel_bias_std', 3), ('gyro_bias_std', 3)]:
        if len(c[key]) != size or not all(math.isfinite(v) for v in c[key]):
            raise ValueError(f'Invalid IMU parameter: {key}')
        if key.endswith('_std') and any(v < 0 for v in c[key]):
            raise ValueError(f'Negative IMU noise: {key}')
    if not math.isfinite(c['imu_update_rate']) or c['imu_update_rate'] <= 0:
        raise ValueError('Invalid IMU update rate')
    if require_mocap:
        mocap = json.loads((directory/'mocap_calibration.json').read_text())['value0']
        validate_pose(mocap['T_imu_marker'])
        sidecar = json.loads((directory/'mocap_imu_time_offset.json').read_text())
        if sidecar['raw_mocap_to_imu_total_offset_ns'] != mocap['mocap_time_offset_ns'] + mocap['mocap_to_imu_offset_ns']:
            raise ValueError('Inconsistent delivered mocap time offsets')
    files = [directory/name for name in dict.fromkeys(required + ['mocap_calibration.json', 'mocap_imu_time_offset.json'] + list(hashes)) if (directory/name).is_file()]
    return obj, manifest, CAMERAS.index(reference), files
