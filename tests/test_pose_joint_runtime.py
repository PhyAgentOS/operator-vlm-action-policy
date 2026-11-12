import asyncio

from test_actions import joint_config
from test_runtime import Backend, obs, settle

from operator_vlm_action_policy.contracts import ImageInput, ModelActions, Observation, PolicyConfig
from operator_vlm_action_policy.runtime import PolicyRuntime


def test_pose_waypoint_stays_queued_until_feedback_reaches_target():
    class PoseBackend(Backend):
        async def infer(self, *args):
            return ModelActions(
                action_space="eef_pose", frame="world", actions=[[0.05, 0, 0.5, 0, 0, 0, 1, 1]]
            ), {}

    async def scenario():
        cfg = PolicyConfig(action_space="eef_pose", auto_start=True, instruction="move")
        runtime = PolicyRuntime(cfg, PoseBackend())
        runtime.observe(obs())
        first = await settle(runtime)
        assert len(runtime.rows) == 1
        following = obs(1)
        following.state[0] = 0.049
        runtime.observe(following)
        second = await settle(runtime)
        assert not runtime.rows
        a = next(d for p, d in first if p == "action")["position"]
        b = next(d for p, d in second if p == "action")["position"]
        assert b[0] < a[0] and b[-1] == 1
        await runtime.close()

    asyncio.run(scenario())


def test_joint_runtime_emits_joint_targets_without_eef_scaling():
    class JointBackend(Backend):
        async def infer(self, *args):
            return ModelActions(
                action_space="joint_position", frame="joint_space", actions=[[0.05, -0.05, 1]]
            ), {}

    async def scenario():
        cfg = joint_config(auto_start=True, instruction="move", image_inputs={"image/main": "main"})
        runtime = PolicyRuntime(cfg, JointBackend())
        runtime.observe(
            Observation(
                episode_id="joint",
                epoch=0,
                step_id=0,
                obs_id="joint:0",
                state=[0, 0, -1],
                images={"main": ImageInput(data="AA==")},
            )
        )
        outputs = await settle(runtime)
        native = next(d for p, d in outputs if p == "action")
        assert native["position"] == [0.05, -0.05, 1]
        assert native["name"] == ["a", "b", "gripper"]
        await runtime.close()

    asyncio.run(scenario())
