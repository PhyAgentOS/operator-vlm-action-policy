"""Persistent Dora node; ticks pump asynchronous inference and consume action credits."""

from __future__ import annotations

import asyncio
import json

from .backend import VLMClient
from .contracts import Observation, PolicyConfig
from .runtime import PolicyRuntime
from .wire import image_input, joint_command, row, state_values


class NodeDriver:
    def __init__(self, runtime):
        self.runtime = runtime
        self.cfg = runtime.cfg
        self.pending = {}
        self.stamps = {}
        self.fresh = set()
        self.cutoff = None
        self.sequence = 0

    def clear(self, cutoff=None):
        # Dora may deliver a later-produced state before an earlier reset on another port.
        # Keep only messages causally newer than that reset, even if already received.
        self.pending = {
            k: v
            for k, v in self.pending.items()
            if cutoff is not None and self.stamps.get(k) is not None and self.stamps[k] > cutoff
        }
        self.stamps = {k: self.stamps[k] for k in self.pending}
        self.fresh = set(self.pending)
        self.cutoff = cutoff
        self.sequence = 0

    def publish_bundle(self):
        runtime = self.runtime
        required = {"proprio_state", *self.cfg.image_inputs}
        if not (
            self.fresh >= required and runtime.phase == "running" and runtime.instruction.strip()
        ):
            return
        state = state_values(self.pending["proprio_state"], self.cfg.state_names)
        images = {
            alias: image_input(self.pending[port], self.cfg.max_image_pixels)
            for port, alias in self.cfg.image_inputs.items()
        }
        self.fresh.clear()
        obs = Observation(
            episode_id=f"legacy:{runtime.instance}:{runtime.generation}",
            epoch=runtime.generation,
            step_id=self.sequence,
            obs_id=f"legacy:{runtime.instance}:{runtime.generation}:{self.sequence}",
            state=state,
            images=images,
        )
        runtime.observe(obs)
        self.sequence += 1

    def input(self, name, value, metadata=None):
        runtime = self.runtime
        stamp = (metadata or {}).get("timestamp")
        if name == "benchmark_result":
            runtime.command("stop")
            self.clear()
        elif name == "policy_command":
            message = row(value)
            if message["policy_id"] not in {self.cfg.policy_id, "*"}:
                return
            runtime.command(message["command"], json.loads(message["inputs_json"]))
            self.clear(
                stamp
                if message["command"] in {"start", "resume", "reset_scene", "set_instruction"}
                else None
            )
            self.publish_bundle()
        elif name == "observation" and self.cfg.transport == "observation_v1":
            runtime.observe(Observation.model_validate_json(value[0].as_py()))
        elif self.cfg.transport == "legacy_libero" and (
            name == "proprio_state" or name in self.cfg.image_inputs
        ):
            if self.cutoff is not None and stamp is not None and stamp <= self.cutoff:
                return
            self.pending[name] = value
            self.stamps[name] = stamp
            self.fresh.add(name)
            self.publish_bundle()


def run(cfg: PolicyConfig):
    import pyarrow as pa
    from dora import Node

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    client = VLMClient(cfg)
    runtime = PolicyRuntime(cfg, client)
    driver = NodeDriver(runtime)
    node = Node()
    try:
        for event in node:
            if event["type"] == "STOP":
                break
            if event["type"] == "ERROR":
                raise RuntimeError("Dora transport error")
            if event["type"] != "INPUT":
                continue
            try:
                if event["id"] != "tick":
                    driver.input(event["id"], event["value"], event.get("metadata"))
                outputs = loop.run_until_complete(runtime.tick())
            except Exception as exc:
                runtime.fail(exc)
                outputs = [("policy_error", runtime.state())]
            for port, data in outputs:
                if port == "action":
                    metadata = {
                        k: data[k] for k in ("episode_id", "epoch", "step_id", "source_obs_id")
                    }
                    node.send_output(port, joint_command(data), metadata=metadata)
                else:
                    node.send_output(port, pa.array([json.dumps(data, allow_nan=False)]))
            if event["id"] == "tick" or outputs:
                node.send_output("policy_state", pa.array([json.dumps(runtime.state())]))
            if runtime.phase == "error":
                # Upstream LIBERO has no policy-error input: fail the flow instead of waiting forever.
                raise RuntimeError(runtime.error)
    finally:
        loop.run_until_complete(runtime.close())
        loop.close()
