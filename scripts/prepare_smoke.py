"""Generate an isolated descriptor for the real Dora smoke test."""
import sys
from pathlib import Path

import yaml

root = Path(__file__).resolve().parents[1]
work = Path(sys.argv[1]).resolve()
work.mkdir(parents=True, exist_ok=True)
config = yaml.safe_load((root / "examples/libero/policy.yaml").read_text())
config["model"] = {"backend": "local_python", "local_factory": "smoke_backend:create"}
(work / "policy.yaml").write_text(yaml.safe_dump(config))
peer_launcher = work / "peer.sh"
peer_launcher.write_text(f'#!/usr/bin/env bash\nexec "{root / ".venv/bin/python"}" "{root / "tests/smoke_peer.py"}"\n')
peer_launcher.chmod(0o755)
ports = ["proprio_state", "image/main", "image/second", "policy_command", "benchmark_result"]
flow = {"nodes": [
    {"id": "peer", "path": str(peer_launcher),
     "env": {"SMOKE_REPORT": str(work / "report.json")},
     "inputs": {"tick": "dora/timer/millis/20", "action": "policy/action", "policy_error": "policy/policy_error", "policy_state": "policy/policy_state"},
     "outputs": ports},
    {"id": "policy", "path": str(root / "operator-vlm-action-policy"),
     "args": f"--config {work / 'policy.yaml'}",
     "env": {"PYTHONPATH": str(root / "tests")},
     "inputs": {"tick": "dora/timer/millis/20", **{p: {"source": f"peer/{p}", "queue_size": 32 if p == "policy_command" else 1} for p in ports}},
     "outputs": ["action", "action_chunk", "policy_state", "policy_error"]},
]}
(work / "dataflow.yaml").write_text(yaml.safe_dump(flow))
print(work / "dataflow.yaml")
