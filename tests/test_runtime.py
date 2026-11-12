import asyncio

import pytest

from operator_vlm_action_policy.contracts import ImageInput, ModelActions, Observation, PolicyConfig
from operator_vlm_action_policy.runtime import PolicyRuntime


class Backend:
    def __init__(self, rows=None):
        self.calls = []
        self.rows = rows or [[0.01, 0, 0, 0, 0, 0, -1]] * 4

    async def infer(self, *args):
        self.calls.append(args)
        return ModelActions(action_space="eef_delta", frame="world", actions=self.rows), {}

    async def close(self):
        pass


def obs(step=0, epoch=0):
    return Observation(
        episode_id="ep",
        epoch=epoch,
        step_id=step,
        obs_id=f"{epoch}:{step}",
        state=[0, 0, 0.5, 0, 0, 0, 0, 0],
        images={"main": ImageInput(data="AA=="), "wrist": ImageInput(data="AA==")},
    )


async def settle(runtime):
    results = []
    for _ in range(8):
        results.extend(await runtime.tick())
        await asyncio.sleep(0)
    return results


def test_one_credit_per_observation_and_replan_with_acknowledged_history():
    async def scenario():
        backend = Backend()
        runtime = PolicyRuntime(PolicyConfig(auto_start=True, instruction="pick"), backend)
        runtime.observe(obs())
        outputs = await settle(runtime)
        assert len([x for x in outputs if x[0] == "action"]) == 1
        assert len(backend.calls) == 1
        assert not runtime.history
        assert not runtime.observe(obs())
        runtime.observe(obs(1))
        outputs = await settle(runtime)
        assert len([x for x in outputs if x[0] == "action"]) == 1
        runtime.observe(obs(2))
        await settle(runtime)
        assert len(backend.calls) == 2
        assert len(backend.calls[1][2]) == 2
        assert backend.calls[1][2][0]["ack_obs_id"] == "0:1"
        await runtime.close()

    asyncio.run(scenario())


def test_reset_discards_late_result_even_if_backend_ignores_cancel():
    class Slow(Backend):
        async def infer(self, *args):
            try:
                await asyncio.sleep(100)
            except asyncio.CancelledError:
                return await super().infer(*args)

    async def scenario():
        runtime = PolicyRuntime(PolicyConfig(auto_start=True, instruction="pick"), Slow())
        runtime.observe(obs())
        await runtime.tick()
        await asyncio.sleep(0)
        runtime.command("reset_scene")
        outputs = await settle(runtime)
        assert not any(port in {"action", "action_chunk"} for port, _ in outputs)
        assert not runtime.rows and runtime.latest is None
        await runtime.close()

    asyncio.run(scenario())


def test_strict_episode_binding_and_step_jump():
    runtime = PolicyRuntime(PolicyConfig(transport="observation_v1"), Backend())
    with pytest.raises(ValueError, match="requires"):
        runtime.command("reset_scene")
    runtime.command("reset_scene", {"episode_id": "ep", "epoch": 2})
    with pytest.raises(ValueError, match="stale"):
        runtime.observe(obs(epoch=1))
    runtime.observe(obs(epoch=2))
    with pytest.raises(ValueError, match="advance"):
        runtime.observe(obs(step=3, epoch=2))


def test_invalid_output_fail_closed_and_pause_reset():
    async def scenario():
        runtime = PolicyRuntime(
            PolicyConfig(auto_start=True, instruction="pick"), Backend([[9, 0, 0, 0, 0, 0, 0]])
        )
        runtime.observe(obs())
        outputs = await settle(runtime)
        assert runtime.phase == "error"
        assert not any(port == "action" for port, _ in outputs)
        assert any(port == "policy_error" for port, _ in outputs)
        runtime.command("reset_scene")
        assert runtime.phase == "running"
        runtime.command("pause")
        assert runtime.phase == "paused" and not runtime.rows
        await runtime.close()

    asyncio.run(scenario())
