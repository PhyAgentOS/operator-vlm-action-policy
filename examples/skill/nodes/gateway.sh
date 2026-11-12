#!/usr/bin/env bash
set -euo pipefail
exec "$GATEWAY_BINARY" --config "$PAOS_SKILL_ROOT/profiles/libero/gateway.yaml"
