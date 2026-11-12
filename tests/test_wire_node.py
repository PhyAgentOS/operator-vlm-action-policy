import asyncio
import base64
import io

import numpy as np
import pyarrow as pa
import pytest
from PIL import Image
from test_runtime import Backend, settle

from operator_vlm_action_policy.contracts import PolicyConfig
from operator_vlm_action_policy.node import NodeDriver
from operator_vlm_action_policy.runtime import PolicyRuntime
from operator_vlm_action_policy.wire import batch, image_input, joint_command, state_values


def state():
    return pa.RecordBatch.from_pydict(
        {
            "name": [[f"joint{i}" for i in range(1, 8)] + ["gripper"]],
            "position": [[0, 0, 0.5, 0, 0, 0, 0, 0]],
            "velocity": [[]],
            "effort": [[]],
        }
    )


def frame():
    return pa.RecordBatch.from_pydict(
        {
            "height": [1],
            "width": [1],
            "step": [4],
            "encoding": ["bgr8"],
            "data": [bytes([3, 2, 1, 0])],
        }
    )


def test_wire_stride_bgr_and_missing_state_rejection():
    result = image_input(frame(), 1024)
    pixels = np.asarray(Image.open(io.BytesIO(base64.b64decode(result.data))))
    assert pixels[0, 0].tolist() == [1, 2, 3]
    with pytest.raises(ValueError, match="missing"):
        state_values(state(), ["absent"])
    command = joint_command({"name": ["a", "g"], "position": [0.1, -1]})
    assert command.schema.field("position").type == pa.list_(pa.float64())
    assert command["mode"][0].as_py() == "position"
    buffer = pa.BufferOutputStream()
    with pa.ipc.new_stream(buffer, command.schema) as writer:
        writer.write_batch(command)
    assert batch(buffer.getvalue().to_pybytes()).equals(command)


def test_legacy_fresh_bundle_barrier_no_extra_action_on_ticks():
    async def scenario():
        runtime = PolicyRuntime(PolicyConfig(auto_start=True, instruction="pick"), Backend())
        driver = NodeDriver(runtime)
        driver.input("image/second", frame())
        driver.input("proprio_state", state())
        assert runtime.latest is None
        driver.input("image/main", frame())
        outputs = await settle(runtime)
        assert len([x for x in outputs if x[0] == "action"]) == 1
        assert not await settle(runtime)
        driver.input("proprio_state", state())
        driver.input("image/main", frame())
        assert not await settle(runtime)
        driver.input("image/second", frame())
        outputs = await settle(runtime)
        assert len([x for x in outputs if x[0] == "action"]) == 1
        driver.input("benchmark_result", pa.array(["finished"]))
        assert runtime.phase == "idle" and not runtime.rows
        await runtime.close()

    asyncio.run(scenario())


def test_causally_new_state_delivered_before_reset_is_retained():
    runtime = PolicyRuntime(PolicyConfig(auto_start=True, instruction="pick"), Backend())
    driver = NodeDriver(runtime)
    driver.input("proprio_state", state(), {"timestamp": 30})
    command = pa.RecordBatch.from_pydict(
        {
            "policy_id": ["vlm_libero"],
            "command": ["reset_scene"],
            "inputs_json": ["{}"],
            "request_id": ["reset-1"],
        }
    )
    driver.input("policy_command", command, {"timestamp": 20})
    driver.input("image/main", frame(), {"timestamp": 31})
    driver.input("image/second", frame(), {"timestamp": 32})
    assert runtime.latest is not None
    assert runtime.latest.epoch == 1
    driver.input("proprio_state", state(), {"timestamp": 19})
    assert "proprio_state" not in driver.fresh
