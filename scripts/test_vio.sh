#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-/home/yuewang/.local/share/pipx/venvs/evo/bin/python}"
"$PYTHON_BIN" -m unittest discover -s "$ROOT/scripts" -p 'test_*pipeline*.py' -v
mkdir -p "$ROOT/build-vio"
read -r -a CV_FLAGS <<< "$(pkg-config --cflags --libs opencv4)"
for name in test_camera_mask test_frame_mask; do
  c++ -std=c++17 -O2 -I/usr/include/eigen3 \
    -I"$ROOT/okvis_cv/include" -I"$ROOT/okvis_util/include" \
    -I"$ROOT/okvis_common/include" -I"$ROOT/okvis_time/include" \
    "$ROOT/scripts/$name.cpp" "$ROOT/okvis_cv/src/CameraBase.cpp" \
    -o "$ROOT/build-vio/$name" "${CV_FLAGS[@]}"
  "$ROOT/build-vio/$name"
done
