#!/usr/bin/env bash
set -euo pipefail
exec "$VLM_ACTION_PYTHON" -m operator_vlm_action_policy.cli run --config "$PAOS_SKILL_ROOT/profiles/libero/policy.yaml"
