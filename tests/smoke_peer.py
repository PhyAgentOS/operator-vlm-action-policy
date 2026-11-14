"""Real Dora/Arrow peer for protocol smoke tests; does not simulate LIBERO physics."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import pyarrow as pa
from dora import Node
from forge_msgs import Image, JointCommand, JointState, PolicyCommand

node = Node()
epoch = "smoke-episode"
step = 0
acks = []


def identity():
    return {"episode_id": "smoke-task", "epoch": epoch, "obs_id": f"{epoch}:{step}",
            "step_id": step, "instruction_version": 1}


def command(name, **inputs):
    msg = PolicyCommand.from_inputs(policy_id="vlm_libero", command=name,
                                    inputs={**identity(), **inputs})
    node.send_output("policy_command", msg.to_arrow(), identity())


def observation(last_action_id=None):
    meta = identity()
    if last_action_id:
        meta["last_action_id"] = last_action_id
    state = JointState(name=["joint1", "joint2", "joint3", "joint4", "joint5", "joint6", "joint7", "gripper"], position=[0.] * 8)
    image = Image.from_numpy(np.zeros((16, 16, 3), dtype=np.uint8), "rgb8")
    node.send_output("proprio_state", state.to_arrow(), meta)
    node.send_output("image/main", image.to_arrow(), meta)
    node.send_output("image/second", image.to_arrow(), meta)


started = False
for event in node:
    if event["type"] == "STOP":
        break
    if event["type"] != "INPUT":
        continue
    if event["id"] == "policy_state":
        print(event["value"].to_pylist(), flush=True)
    if event["id"] == "tick" and not started:
        print("smoke peer starting", flush=True)
        started = True
        command("start")
        command("set_instruction", instruction="transport smoke test")
        command("reset_scene")
        observation()
    elif event["id"] == "action":
        action = JointCommand.from_arrow(event["value"])
        meta = event["metadata"]
        assert meta["step_id"] == step
        assert abs(action.position[0] - 0.02) < 1e-8
        assert len(action.position) == 7
        acks.append(meta["action_id"])
        step += 1
        if step == 3:
            report = {"passed": True, "steps": step, "unique_action_ids": len(set(acks))}
            Path(os.environ["SMOKE_REPORT"]).write_text(json.dumps(report))
            node.send_output("benchmark_result", pa.array([json.dumps({"status": "succeeded"})]))
            command("stop")
            break
        observation(meta["action_id"])
    elif event["id"] == "policy_error":
        print(event["value"].to_pylist(), file=sys.stderr)
        raise SystemExit(1)
