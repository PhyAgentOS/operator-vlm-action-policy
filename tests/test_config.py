from pathlib import Path

import pytest

from vlm_action_policy.config import PolicyConfig
from vlm_action_policy.contracts import ActionAdapter


@pytest.mark.parametrize("patch", [
    {"mode": "vla_conditioned"},
    {"unknown": True},
    {"model": {"made_up": True}},
    {"model": {"api_base_env": "https://provider.example/v1"}},
    {"model": {"api_key_env": "literal-key-is-not-an-env-name"}},
    {"model": {"model_name_env": "model-v1.2"}},
    {"action": {"execute_horizon": 5}},
    {"action": {"prediction_horizon": True}},
    {"action": {"dimension": 8}},
    {"action": {"frame": "tool"}},
    {"action": {"control_dt_s": float("nan")}},
    {"observation": {"synchronization": "legacy_lockstep"}},
    {"observation": {"image_inputs": {"tick": "main"}}},
    {"runtime": {"async_prefetch": True}},
    {"context": {"include_unexecuted_actions": True}},
    {"control_adapter": {"translation_scale_m": 0}},
    {"lifecycle": {"reject_stale_results": False}},
])
def test_invalid_contract_fails_startup(patch):
    with pytest.raises(ValueError):
        PolicyConfig.from_mapping(patch)


def test_example_config_is_loadable():
    root = Path(__file__).resolve().parents[1]
    cfg = PolicyConfig.load(root / "examples/libero/policy.yaml")
    assert cfg.action.execute_horizon == 2
    assert cfg.observation.require_identity


def test_joint_position_requires_real_state_and_explicit_limits():
    raw = {
        "observation": {"state_names": ["j1", "j2", "gripper"],
                        "state_semantics": ["j1", "j2", "gripper"]},
        "action": {"space": "joint_position", "frame": "joint_space",
                   "dimension": 3, "layout": ["j1", "j2", "gripper"],
                   "joint_names": ["j1", "j2"], "units": ["rad", "rad", "normalized"]},
        "control_adapter": {"type": "joint_position", "native_dimension": 3,
                            "lower_bounds": [-2, -2, -1], "upper_bounds": [2, 2, 1]},
    }
    cfg = PolicyConfig.from_mapping(raw)
    adapter = ActionAdapter(cfg)
    rows = adapter.validate_chunk({"actions": [[0.3, -0.2, -1]] * 4})
    assert adapter.to_native(rows[0]) == [0.3, -0.2, -1]
    del raw["control_adapter"]["lower_bounds"]
    with pytest.raises(ValueError):
        PolicyConfig.from_mapping(raw)
