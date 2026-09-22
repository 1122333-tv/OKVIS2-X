#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-/home/yuewang/.local/share/pipx/venvs/evo/bin/python}"
exec "$PYTHON_BIN" "$ROOT/scripts/run_vio_pipeline.py" \
  --calibration-dir /home/yuewang/Project/Calib/calibration_workspace/runs/layout0916_DOHC2_joint_dynamic_01_retry01/delivery/vio/kalibr_handeye \
  --config "$ROOT/config/oak4p/layout0916_vio.yaml" \
  "$@"
