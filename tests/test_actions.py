import numpy as np
import pytest

from operator_vlm_action_policy.actions import native_action, rotation_error
from operator_vlm_action_policy.contracts import ModelActions, PolicyConfig


def joint_config(**kwargs):
    return PolicyConfig(
        action_space="joint_position",
        controller="joint_position",
        frame="joint_space",
        joint_names=["a", "b"],
        joint_lower=[-2, -2],
        joint_upper=[2, 2],
        state_names=["a", "b", "gripper"],
        state_semantics=["a_rad", "b_rad", "gripper"],
        action_names=["a", "b", "gripper"],
        **kwargs,
    )


def test_eef_si_to_native_and_workspace_check():
    cfg = PolicyConfig()
    action, reached = native_action(cfg, [0.01, 0, 0, 0, 0, 0.1, -1], [0, 0, 0.5, 0, 0, 0, 0, 0])
    assert reached
    assert action == pytest.approx([0.2, 0, 0, 0, 0, 0.2, -1])
    with pytest.raises(ValueError, match="workspace"):
        native_action(cfg, [0.01, 0, 0, 0, 0, 0, -1], [1, 0, 0.5, 0, 0, 0, 0, 0])


def test_pose_servo_uses_latest_state_and_shortest_rotation():
    cfg = PolicyConfig(action_space="eef_pose")
    target = [0.1, 0, 0.5, 0, 0, 0, 1, 1]
    far, reached = native_action(cfg, target, [0, 0, 0.5, 0, 0, 0, 0, 0])
    assert far[0] == pytest.approx(0.4)
    assert not reached
    near, reached = native_action(cfg, target, [0.099, 0, 0.5, 0, 0, 0, 0, 0])
    assert near[0] < far[0] and reached
    np.testing.assert_allclose(rotation_error([0, 0, 0, -1], [0, 0, 0]), [0, 0, 0])
    np.testing.assert_allclose(rotation_error([0, 0, 1, 0], [0, 0, np.pi / 2]), [0, 0, np.pi / 2])


def test_joint_limits_order_and_step():
    cfg = joint_config()
    result = ModelActions(
        action_space="joint_position", frame="joint_space", actions=[[0.05, -0.05, 1]]
    )
    result.validate_for(cfg)
    assert native_action(cfg, result.actions[0], [0, 0, -1])[0] == result.actions[0]
    with pytest.raises(ValueError, match="step"):
        native_action(cfg, [1, 0, 1], [0, 0, -1])
    with pytest.raises(ValueError, match="limits"):
        ModelActions(
            action_space="joint_position", frame="joint_space", actions=[[3, 0, 1]]
        ).validate_for(cfg)
    with pytest.raises(ValueError):
        PolicyConfig(action_space="joint_position")


@pytest.mark.parametrize(
    "row",
    [
        [0, 0, 0, 0, 0, 0],
        [float("nan"), 0, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0, 2],
        [0.02, 0.02, 0, 0, 0, 0, -1],
        [0, 0, 0, 0, 0, 0.3, -1],
    ],
)
def test_invalid_actions_rejected(row):
    with pytest.raises(ValueError):
        ModelActions(action_space="eef_delta", frame="world", actions=[row]).validate_for(
            PolicyConfig()
        )
