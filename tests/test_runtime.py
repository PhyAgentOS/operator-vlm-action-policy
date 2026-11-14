from copy import deepcopy

import pytest

from vlm_action_policy.config import PolicyConfig
from vlm_action_policy.contracts import Identity
from vlm_action_policy.runtime import PolicyRuntime


class Clock:
    value = 10.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class Worker:
    busy = False
    result = None

    def __init__(self):
        self.requests = []

    def submit(self, token, request):
        assert not self.busy
        self.busy = True
        self.requests.append((token, request))

    def complete(self, response=None, error=None):
        token = self.requests[-1][0]
        self.result = (token, response or actions(), error)

    def poll(self):
        result, self.result = self.result, None
        if result:
            self.busy = False
        return result

    def close(self):
        pass


def actions():
    return {"actions": [[0.01, 0, 0, 0, 0, 0, -1] for _ in range(4)]}


def identity(step=0, epoch="epoch1", episode="task0"):
    return Identity(episode, epoch, f"{epoch}:{step}", step, 1).metadata()


@pytest.fixture
def rig():
    outputs, worker, clock = [], Worker(), Clock()
    runtime = PolicyRuntime(PolicyConfig(), None, lambda *args: outputs.append(args),
                            clock=clock, worker=worker)
    runtime.command("vlm_libero", "start", {})
    runtime.command("vlm_libero", "set_instruction", {"instruction": "pick the cup", **identity()})
    runtime.command("vlm_libero", "reset_scene", identity())
    return runtime, outputs, worker, clock


def observation(runtime, step=0, *, ack=None, epoch="epoch1", order=None):
    meta = identity(step, epoch)
    if ack:
        meta["last_action_id"] = ack
    values = {"proprio_state": [0.0] * 8, "image/main": b"png-main", "image/second": b"png-wrist"}
    for port in order or values:
        runtime.observe(port, values[port], meta)


def sent(outputs, port):
    return [item for item in outputs if item[0] == port]


def test_single_credit_and_h_m_replanning(rig):
    runtime, outputs, worker, _ = rig
    observation(runtime)
    assert len(worker.requests) == 1
    assert not sent(outputs, "action")
    worker.complete()
    runtime.tick()
    first = sent(outputs, "action")[0]
    assert first[1] == pytest.approx([0.2, 0, 0, 0, 0, 0, -1])
    for _ in range(50):
        runtime.tick()
    observation(runtime, 0)
    assert len(sent(outputs, "action")) == 1
    observation(runtime, 1, ack=first[2]["action_id"], order=["image/second", "proprio_state", "image/main"])
    assert len(sent(outputs, "action")) == 2
    assert len(worker.requests) == 1
    second = sent(outputs, "action")[-1]
    observation(runtime, 2, ack=second[2]["action_id"])
    assert len(worker.requests) == 2
    assert len(sent(outputs, "action")) == 2
    assert [entry["row_index"] for entry in worker.requests[-1][1].executed_history] == [0, 1]
    assert worker.requests[-1][1].observation.identity.step_id == 2
    assert runtime.chunk == []


def test_camera_parts_cannot_mix_steps_or_episodes(rig):
    runtime, outputs, worker, _ = rig
    runtime.observe("proprio_state", [0.0] * 8, identity())
    runtime.observe("image/main", b"image", identity(1))
    runtime.observe("image/second", b"image", identity(epoch="old"))
    assert not worker.requests
    runtime.observe("image/main", b"image", identity())
    runtime.observe("image/second", b"image", identity())
    assert len(worker.requests) == 1


def test_reset_discards_late_inference_and_clears_history(rig):
    runtime, outputs, worker, _ = rig
    observation(runtime)
    runtime.history.append({"old": True})
    runtime.command("vlm_libero", "set_instruction", {"instruction": "pick new cup", **identity(epoch="epoch2")})
    runtime.command("vlm_libero", "reset_scene", identity(epoch="epoch2"))
    observation(runtime, epoch="epoch2")
    assert len(worker.requests) == 1
    worker.complete()
    runtime.tick()
    assert not sent(outputs, "action")
    assert len(worker.requests) == 2
    assert worker.requests[-1][1].observation.identity.epoch == "epoch2"
    assert not worker.requests[-1][1].executed_history
    worker.complete()
    runtime.tick()
    assert len(sent(outputs, "action")) == 1


def test_wrong_ack_fails_without_extra_action(rig):
    runtime, outputs, worker, _ = rig
    observation(runtime)
    worker.complete()
    runtime.tick()
    observation(runtime, 1, ack="wrong-action")
    assert runtime.failed
    assert sent(outputs, "policy_error")[-1][1]["code"] == "invalid_feedback"
    assert sent(outputs, "policy_error")[-1][1]["step_id"] == 1
    assert len(sent(outputs, "action")) == 1
    assert not runtime.history


@pytest.mark.parametrize("response", [
    {"actions": [[0] * 7]},
    {"actions": [[float("nan")] * 7] * 4},
    {"actions": [[True] * 7] * 4},
    {"actions": [[0, 0, 0, 0, 0, 0, 2]] * 4},
    {"actions": [[0.06, 0, 0, 0, 0, 0, -1]] * 4},
    {"actions": [[0] * 8] * 4},
    {"actions": [[0] * 7] * 4, "success": True},
])
def test_invalid_entire_chunk_never_executes(rig, response):
    runtime, outputs, worker, _ = rig
    observation(runtime)
    worker.complete(response)
    runtime.tick()
    assert runtime.failed and not sent(outputs, "action")


def test_validate_unused_tail_before_any_execution(rig):
    runtime, outputs, worker, _ = rig
    response = deepcopy(actions())
    response["actions"][-1][0] = 10
    observation(runtime)
    worker.complete(response)
    runtime.tick()
    assert runtime.failed and not sent(outputs, "action")


@pytest.mark.parametrize("phase,code", [("infer", "inference_timeout"), ("ack", "feedback_timeout"), ("obs", "observation_timeout")])
def test_deadlines_fail_once(rig, phase, code):
    runtime, outputs, worker, clock = rig
    if phase != "obs":
        observation(runtime)
    if phase == "ack":
        worker.complete()
        runtime.tick()
    clock.advance(61)
    runtime.tick()
    runtime.tick()
    assert len(sent(outputs, "policy_error")) == 1
    assert sent(outputs, "policy_error")[0][1]["code"] == code


@pytest.mark.parametrize("command", ["pause", "stop", "set_instruction"])
def test_lifecycle_invalidates_inflight(rig, command):
    runtime, outputs, worker, _ = rig
    observation(runtime)
    runtime.command("vlm_libero", command, {"instruction": "different task"})
    worker.complete()
    runtime.tick()
    assert not sent(outputs, "action")
    assert runtime.needs_reset


def test_benchmark_result_controls_completion(rig):
    runtime, outputs, worker, _ = rig
    observation(runtime)
    runtime.benchmark_result()
    worker.complete()
    runtime.tick()
    assert not sent(outputs, "action")
    assert sent(outputs, "policy_state")[-1][1]["state"] == "DONE"


def test_wrong_target_and_old_reset_are_ignored(rig):
    runtime, outputs, worker, _ = rig
    runtime.command("other", "stop", {})
    observation(runtime)
    runtime.command("vlm_libero", "reset_scene", identity(epoch="epoch2"))
    runtime.command("vlm_libero", "reset_scene", identity())
    assert runtime.binding.epoch == "epoch2"
    assert runtime.running


def test_legacy_lockstep_reassembles_only_complete_observations():
    config = PolicyConfig.from_mapping({"observation": {"synchronization": "legacy_lockstep", "require_identity": False}})
    outputs, worker = [], Worker()
    runtime = PolicyRuntime(config, None, lambda *args: outputs.append(args), worker=worker)
    runtime.command("vlm_libero", "start", {})
    runtime.command("vlm_libero", "set_instruction", {"instruction": "pick"})
    runtime.command("vlm_libero", "reset_scene", {})
    for port, value in [("proprio_state", [0] * 8), ("image/main", b"png")]:
        runtime.observe(port, value, {})
    assert not worker.requests
    runtime.observe("image/second", b"png", {})
    worker.complete()
    runtime.tick()
    assert len(sent(outputs, "action")) == 1


def test_early_observation_survives_cross_port_reset_order(rig):
    runtime, outputs, worker, _ = rig
    observation(runtime, epoch="next-epoch")
    assert not worker.requests
    runtime.command("vlm_libero", "set_instruction", {"instruction": "new task", **identity(epoch="next-epoch")})
    runtime.command("vlm_libero", "reset_scene", identity(epoch="next-epoch"))
    assert len(worker.requests) == 1
    assert worker.requests[0][1].observation.identity.epoch == "next-epoch"
    assert worker.requests[0][1].instruction == "new task"


def test_duplicate_reset_does_not_create_action_credit(rig):
    runtime, outputs, worker, _ = rig
    observation(runtime)
    worker.complete()
    runtime.tick()
    runtime.command("vlm_libero", "reset_scene", identity())
    assert runtime.pending
    observation(runtime, 0)
    assert len(sent(outputs, "action")) == 1


def test_every_observation_channel_requires_matching_ack(rig):
    runtime, outputs, worker, _ = rig
    observation(runtime)
    worker.complete()
    runtime.tick()
    ack = runtime.pending.action_id
    runtime.observe("proprio_state", [0.] * 8, {**identity(1), "last_action_id": ack})
    runtime.observe("image/main", b"png", identity(1))
    assert runtime.failed
    assert sent(outputs, "policy_error")[-1][1]["code"] == "invalid_feedback"


def test_pause_reset_same_identity_can_resume_with_fresh_observation(rig):
    runtime, outputs, worker, _ = rig
    runtime.command("vlm_libero", "pause", identity())
    runtime.command("vlm_libero", "resume", {})
    runtime.command("vlm_libero", "reset_scene", identity())
    observation(runtime)
    assert len(worker.requests) == 1


def test_reset_before_start_retains_complete_observation(rig):
    runtime, outputs, worker, _ = rig
    runtime.command("vlm_libero", "reset", identity())
    observation(runtime)
    assert not worker.requests
    runtime.command("vlm_libero", "start", {})
    assert len(worker.requests) == 1
