"""Transport diagnostics without exposing instructions or provider exception text."""
import json
import threading
import time

import pytest
from forge_msgs import JointState, PolicyCommand

from vlm_action_policy.backend import ProviderHTTPError, ProviderResponseError
from vlm_action_policy.config import PolicyConfig
from vlm_action_policy.main import run_node


def test_legacy_reset_reports_protocol_error_without_inference(capsys):
    class Backend:
        def infer(self, request):
            raise AssertionError("legacy observations must not trigger model inference")

    class Node:
        def __init__(self):
            self.outputs = []

        def send_output(self, port, value, metadata):
            self.outputs.append((port, value, metadata))

        def __iter__(self):
            for command, inputs in (
                ("start", {}),
                ("set_instruction", {"instruction": "private instruction not logged"}),
                ("reset_scene", {}),
            ):
                yield {"type": "INPUT", "id": "policy_command", "value":
                       PolicyCommand.from_inputs(policy_id="vlm_libero", command=command,
                                                 inputs=inputs).to_arrow()}
            yield {"type": "STOP"}

    node = Node()
    assert run_node(PolicyConfig(), node=node, backend=Backend()) == 1
    errors = [json.loads(value[0].as_py()) for port, value, _ in node.outputs
              if port == "policy_error"]
    assert len(errors) == 1
    assert errors[0]["code"] == "missing_identity"
    output = capsys.readouterr()
    assert "state=WAIT_RESET" in output.out
    assert "error=missing_identity" in output.err
    assert "benchmark protocol incompatible" in output.err
    assert "correlated_observations" in output.err
    assert "private instruction" not in output.out + output.err


@pytest.mark.parametrize("failure,label", [
    (ProviderHTTPError(401), "provider_http_401"),
    (ProviderResponseError("output_truncated", statistics={
        "request_max_output_tokens": 8192, "output_tokens": 8192,
        "reasoning_tokens": 8192, "visible_output_chars": 0,
        "provider_body": "unit-test-secret private provider body",
    }), "output_truncated; request_max_output_tokens=8192, output_tokens=8192, "
        "reasoning_tokens=8192, visible_output_chars=0"),
    (RuntimeError("unit-test-secret private provider body"), "backend_exception"),
])
def test_inference_failure_reaches_logs_without_private_text(monkeypatch, capsys, failure, label):
    called = threading.Event()
    config = PolicyConfig.from_mapping({"observation": {
        "synchronization": "legacy_lockstep", "require_identity": False,
    }})
    monkeypatch.setattr("vlm_action_policy.main.image_to_png", lambda value: b"test-png")

    class Backend:
        def infer(self, request):
            called.set()
            raise failure

    class Node:
        def __init__(self):
            self.outputs = []

        def send_output(self, port, value, metadata):
            self.outputs.append((port, value, metadata))

        def __iter__(self):
            for command, inputs in (
                ("start", {}),
                ("set_instruction", {"instruction": "private instruction not logged"}),
                ("reset_scene", {}),
            ):
                yield {"type": "INPUT", "id": "policy_command", "value":
                       PolicyCommand.from_inputs(policy_id="vlm_libero", command=command,
                                                 inputs=inputs).to_arrow()}
            yield {"type": "INPUT", "id": "proprio_state", "value":
                   JointState(name=config.observation.state_names, position=[0.0] * 8).to_arrow()}
            for port in config.observation.image_inputs:
                yield {"type": "INPUT", "id": port, "value": None}
            assert called.wait(timeout=2), "inference worker did not run"
            deadline = time.monotonic() + 2
            while not any(port == "policy_error" for port, _, _ in self.outputs):
                assert time.monotonic() < deadline, "worker error did not reach event loop"
                threading.Event().wait(0.001)
                yield {"type": "INPUT", "id": "tick"}
            yield {"type": "STOP"}

    node = Node()
    assert run_node(config, node=node, backend=Backend()) == 1
    assert not any(port == "action" for port, _, _ in node.outputs)
    errors = [json.loads(value[0].as_py()) for port, value, _ in node.outputs
              if port == "policy_error"]
    assert len(errors) == 1
    assert errors[0]["code"] == "inference_error"
    assert errors[0]["message"] == f"model backend failed ({label})"
    output = capsys.readouterr()
    assert "state=INFER" in output.out
    assert "state=ERROR" in output.out
    assert "error=inference_error" in output.err
    assert f"model backend failed ({label})" in output.err
    exposed = output.out + output.err + json.dumps(errors)
    assert "unit-test-secret" not in exposed
    assert "private instruction" not in exposed
    assert "private provider body" not in exposed
