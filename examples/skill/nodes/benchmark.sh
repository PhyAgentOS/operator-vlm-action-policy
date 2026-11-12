#!/usr/bin/env bash
set -euo pipefail
mkdir -p "$VLM_BENCHMARK_WORKSPACE"
cd "$VLM_BENCHMARK_WORKSPACE"
export BENCHMARK_CONFIG="$PAOS_SKILL_ROOT/profiles/libero/benchmark.yaml"
export MUJOCO_GL=egl
export PYOPENGL_PLATFORM=egl
exec "$LIBERO_PYTHON" -u "$LIBERO_NODE_ROOT/main.py"
