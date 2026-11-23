"""Compatibility tests for benchmark-owned vector contracts."""
import json
from copy import deepcopy

import pytest
from test_runtime import Worker

from vlm_action_policy.backend import InferenceRequest, ProviderBackend
from vlm_action_policy.config import PolicyConfig
from vlm_action_policy.contracts import ActionAdapter, Identity, Observation
from vlm_action_policy.runtime import PolicyRuntime


def contract(d=14):
    names = [f"coordinate_{i}" for i in range(d)]
    return {
        "version": 1,
        "action": {
            "space": "generic", "frame": "benchmark_native", "dimension": d,
            "layout": names, "units": ["rad"] * d,
            "descriptions": [f"Absolute target for {name}" for name in names],
            "gripper_convention": "No implicit gripper; see coordinate descriptions",
            "prediction_horizon": 1, "execute_horizon": 1, "control_dt_s": 0.05,
        },
        "control_adapter": {
            "type": "affine", "native_dimension": d,
            "lower_bounds": [-2.0] * d, "upper_bounds": [2.0] * d,
            "scale": [2.0] * d, "offset": [0.1] * d,
        },
        "observation": {
            "state_names": names, "state_semantics": names,
            "image_inputs": {"image/head": "head", "image/left": "left", "image/right": "right"},
        },
    }


def test_generic_vector_bounds_and_conversion():
    base = PolicyConfig()
    cfg = base.with_contract(contract())
    assert cfg.model == base.model and cfg.runtime == base.runtime
    adapter = ActionAdapter(cfg)
    assert adapter.validate_chunk({"actions": [[0.5] * 14]}) == [[0.5] * 14]
    assert adapter.to_native([0.5] * 14) == pytest.approx([1.1] * 14)
    assert adapter.validate_chunk({"actions": [[3, -3] * 7]}) == [[2.0, -2.0] * 7]
    for rows in ([[0] * 13], [[float("nan")] * 14]):
        with pytest.raises(ValueError):
            adapter.validate_chunk({"actions": rows})


@pytest.mark.parametrize("patch", [
    {"version": True}, {"version": 2}, {"model": {}},
    {"action": {"space": "generic", "dimension": 14}},
    {"control_adapter": {"type": "affine", "native_dimension": 14}},
])
def test_invalid_contracts_rejected(patch):
    raw = contract()
    raw.update(patch)
    with pytest.raises((ValueError, TypeError)):
        PolicyConfig().with_contract(raw)


def test_dynamic_contract_three_cameras_and_old_worker_fence():
    outputs, worker = [], Worker()
    runtime = PolicyRuntime(PolicyConfig(), None, lambda *args: outputs.append(args), worker=worker)
    identity = Identity("task", "first", "obs", 0, 1).metadata()
    runtime.command("vlm_libero", "start", {})
    runtime.command("vlm_libero", "set_instruction", {"instruction": "move", **identity})
    runtime.command("vlm_libero", "reset_scene", identity)
    for port, value in {"proprio_state": [0] * 8, "image/main": b"png", "image/second": b"png"}.items():
        runtime.observe(port, value, identity)
    old_token = worker.requests[-1][0]
    new_identity = Identity("task", "second", "obs2", 0, 1).metadata()
    runtime.command("vlm_libero", "reset_scene", {**new_identity, "contract": contract(), "context": {"robot": "dual"}})
    worker.result = (old_token, {"actions": [[0] * 7] * 4}, None)
    runtime.tick()
    assert not [item for item in outputs if item[0] == "action"]
    runtime.command("vlm_libero", "set_instruction", {"instruction": "move", **new_identity})
    runtime.command("vlm_libero", "reset_scene", {**new_identity, "contract": contract(), "context": {"robot": "dual"}, "retry": True})
    runtime.observe("proprio_state", [0] * 14, new_identity)
    runtime.observe("image/head", b"png", new_identity)
    runtime.observe("image/left", b"png", new_identity)
    assert len(worker.requests) == 1
    runtime.observe("image/right", b"png", new_identity)
    request = worker.requests[-1][1]
    assert request.config.action.dimension == 14
    assert request.context == {"robot": "dual"}
    worker.complete({"actions": [[0.5] * 14]})
    runtime.tick()
    assert [item for item in outputs if item[0] == "action"][-1][1] == pytest.approx([1.1] * 14)
    runtime.close()


def test_provider_uses_effective_contract(monkeypatch):
    for key, value in {"VLM_API_BASE": "https://example.invalid/v1", "VLM_API_KEY": "test", "VLM_MODEL": "test"}.items():
        monkeypatch.setenv(key, value)
    cfg = PolicyConfig().with_contract(contract())
    observation = Observation(Identity("ep", "e", "o", 0, 1), (0.0,) * 14,
                              {"head": b"png", "left": b"png", "right": b"png"})
    body = ProviderBackend(PolicyConfig()).payload(InferenceRequest("move", observation, (), cfg, {"scene": "test"}))
    content = body["messages"][1]["content"]
    context = json.loads(content[0]["text"])
    assert context["action_contract"]["dimension"] == 14
    assert context["benchmark_context"] == {"scene": "test"}
    assert len([part for part in content if part["type"] == "image_url"]) == 3
    assert body["response_format"]["json_schema"]["schema"]["properties"]["actions"]["items"]["minItems"] == 14


def test_generic_contract_preserves_legacy_transport_without_identity():
    base = PolicyConfig.from_mapping({"observation": {
        "synchronization": "legacy_lockstep", "require_identity": False,
    }})
    raw = contract(2)
    raw["observation"].update(synchronization="legacy_lockstep", require_identity=False)
    outputs, worker = [], Worker()
    runtime = PolicyRuntime(base, None, lambda *args: outputs.append(args), worker=worker)
    runtime.command(base.policy_id, "start", {"contract": raw})
    runtime.command(base.policy_id, "set_instruction", {"instruction": "move"})
    runtime.command(base.policy_id, "reset_scene", {})
    runtime.observe("proprio_state", [0, 0], {})
    for port in raw["observation"]["image_inputs"]:
        runtime.observe(port, b"png", {})
    worker.complete({"actions": [[0.5, 0.5]]})
    runtime.tick()
    assert not runtime.failed
    assert [item for item in outputs if item[0] == "action"][-1][1] == pytest.approx([1.1, 1.1])
    runtime.close()


def test_contract_cannot_downgrade_identity_protocol():
    outputs = []
    runtime = PolicyRuntime(PolicyConfig(), None, lambda *args: outputs.append(args), worker=Worker())
    raw = contract()
    raw["observation"].update(synchronization="legacy_lockstep", require_identity=False)
    runtime.command("vlm_libero", "start", {"contract": raw})
    assert runtime.failed and runtime.config.observation.require_identity
    runtime.close()


def test_invalid_contract_does_not_replace_config():
    outputs = []
    runtime = PolicyRuntime(PolicyConfig(), None, lambda *args: outputs.append(args), worker=Worker())
    raw = deepcopy(contract())
    raw["version"] = 9
    runtime.command("vlm_libero", "start", {"contract": raw})
    assert runtime.config == PolicyConfig()
    assert len([item for item in outputs if item[0] == "policy_error"]) == 1
    runtime.close()
