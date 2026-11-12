#!/usr/bin/env bash
set -euo pipefail
exec "$VLM_ACTION_PYTHON" -m operator_vlm_action_policy.cli run --config "$VLM_ACTION_CONFIG"
