"""Legacy wire contract: no identity fields, one complete observation per action."""
import pytest
from test_runtime import Clock, Worker, actions, sent

from vlm_action_policy.config import PolicyConfig
from vlm_action_policy.runtime import PolicyRuntime


def parts(runtime, ports=None):
    values = {"proprio_state": [0.] * 8, "image/main": b"png-main",
              "image/second": b"png-wrist"}
    for port in ports or values:
        runtime.observe(port, values[port], {})


def command(runtime, name):
    runtime.command("vlm_libero", name, {"instruction": "pick cup"} if name == "set_instruction" else {})


def rig():
    config = PolicyConfig.from_mapping({"observation": {
        "synchronization": "legacy_lockstep", "require_identity": False,
    }})
    output, worker, clock = [], Worker(), Clock()
    runtime = PolicyRuntime(config, None, lambda *args: output.append(args),
                            worker=worker, clock=clock)
    return runtime, output, worker, clock


@pytest.mark.parametrize("early_ports", [[], ["image/main"],
                                        ["proprio_state", "image/main", "image/second"]])
def test_legacy_initial_observation_crosses_reset_and_start(early_ports):
    runtime, output, worker, _ = rig()
    if early_ports:
        parts(runtime, early_ports)
    command(runtime, "set_instruction")
    command(runtime, "reset_scene")
    command(runtime, "start")
    remaining = [port for port in runtime.buffer.required if port not in early_ports]
    if remaining:
        parts(runtime, remaining)
    assert len(worker.requests) == 1
    assert worker.requests[0][1].observation.identity.step_id == 0
    assert worker.requests[0][1].instruction == "pick cup"
    assert not sent(output, "action")
    worker.complete()
    runtime.tick()
    assert len(sent(output, "action")) == 1


def test_legacy_complete_feedback_advances_h_m_but_ticks_and_duplicates_do_not():
    runtime, output, worker, _ = rig()
    for name in ("start", "set_instruction", "reset_scene"):
        command(runtime, name)
    parts(runtime)
    parts(runtime)  # While inference is pending, this grants nothing.
    assert len(worker.requests) == 1
    worker.complete(actions())
    runtime.tick()
    for _ in range(20):
        runtime.tick()
    assert len(sent(output, "action")) == 1
    parts(runtime, ["image/second", "proprio_state"])
    assert len(sent(output, "action")) == 1
    parts(runtime, ["image/main"])
    assert len(sent(output, "action")) == 2
    assert len(worker.requests) == 1
    parts(runtime)
    assert len(worker.requests) == 2
    request = worker.requests[-1][1]
    assert request.observation.identity.step_id == 2
    assert [item["row_index"] for item in request.executed_history] == [0, 1]
    assert request.observation.identity.epoch == worker.requests[0][1].observation.identity.epoch
    assert not runtime.chunk  # Discard the unused H-M tail.


def test_legacy_reset_discards_late_model_result_and_starts_new_local_epoch():
    runtime, output, worker, _ = rig()
    for name in ("start", "set_instruction", "reset_scene"):
        command(runtime, name)
    parts(runtime)
    old_epoch = worker.requests[-1][1].observation.identity.epoch
    command(runtime, "set_instruction")
    command(runtime, "reset_scene")
    parts(runtime)
    worker.complete()
    runtime.tick()
    assert not sent(output, "action")
    assert len(worker.requests) == 2
    new = worker.requests[-1][1]
    assert new.observation.identity.step_id == 0
    assert new.observation.identity.epoch != old_epoch
    assert not new.executed_history
    assert new.instruction == "pick cup"


def test_second_inference_truncation_never_executes_partial_or_unused_actions():
    runtime, output, worker, _ = rig()
    for name in ("start", "set_instruction", "reset_scene"):
        command(runtime, name)
    parts(runtime)
    worker.complete(actions())
    runtime.tick()
    parts(runtime)  # The next observation acknowledges row 0 and grants row 1.
    assert len(sent(output, "action")) == 2
    parts(runtime)  # After M=2, replan instead of executing the H-M tail.
    assert len(worker.requests) == 2
    assert not runtime.chunk
    worker.complete(error=(
        "output_truncated; request_max_output_tokens=8192, output_tokens=8192, "
        "reasoning_tokens=8192, visible_output_chars=0"
    ))
    runtime.tick()
    for _ in range(5):
        parts(runtime)
        runtime.tick()
    errors = sent(output, "policy_error")
    assert len(errors) == 1
    assert errors[0][1]["code"] == "inference_error"
    assert "output_truncated" in errors[0][1]["message"]
    assert errors[0][1]["step_id"] == 2
    assert runtime.failed and runtime.needs_reset
    assert not runtime.pending and not runtime.chunk
    assert len(sent(output, "action")) == 2
    assert len(worker.requests) == 2  # No automatic retry or extra paid request.
    assert sent(output, "policy_state")[-1][1]["state"] == "ERROR"


def test_legacy_missing_camera_times_out_without_action():
    runtime, output, _, clock = rig()
    for name in ("start", "set_instruction", "reset_scene"):
        command(runtime, name)
    parts(runtime, ["proprio_state", "image/main"])
    clock.advance(61)
    runtime.tick()
    assert not sent(output, "action")
    assert sent(output, "policy_error")[-1][1]["code"] == "observation_timeout"
