#!/usr/bin/env bash
# Bundled source-node entrypoint; preserve Dora's profile working directory.
set -euo pipefail
NODE_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if ! command -v uv >/dev/null 2>&1; then
  printf 'operator-vlm-action-policy requires uv and Python 3.12\n' >&2
  exit 2
fi
# Frozen sync repairs editable paths and entrypoint shebangs after a directory move.
# Keep development tools for local tests/builds; they are not bundled in Skill archives.
uv sync --project "$NODE_ROOT" --frozen --quiet
DEFAULT_ENV_FILE="${XDG_CONFIG_HOME:-${HOME:?HOME is required}/.config}/paos/libero/gpt6_vlm.json"
export PYTHONPATH="${NODE_ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}"
exec "$NODE_ROOT/.venv/bin/python" -m vlm_action_policy.main \
  --env-file "${VLM_ENV_FILE:-$DEFAULT_ENV_FILE}" "$@"
