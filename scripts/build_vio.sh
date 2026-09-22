#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cmake -S "$ROOT" -B "$ROOT/build-vio" \
  -DCMAKE_BUILD_TYPE=Release -DBUILD_APPS=ON -DBUILD_ROS2=OFF \
  -DUSE_NN=OFF -DUSE_GPU=OFF -DUSE_CUDA=OFF -DHAVE_LIBREALSENSE=OFF -DDO_TIMING=ON
cmake --build "$ROOT/build-vio" --target okvis_app_synchronous -j"${BUILD_JOBS:-8}"
cp "$ROOT/resources/small_voc.yml.gz" "$ROOT/build-vio/small_voc.yml.gz"
