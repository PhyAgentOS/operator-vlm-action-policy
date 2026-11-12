"""One logical inference and one action credit per environment observation."""

from __future__ import annotations

import asyncio
import copy
import time
import uuid
from collections import deque

from .actions import native_action
from .contracts import Observation, PolicyConfig


class PolicyRuntime:
    def __init__(self, cfg: PolicyConfig, backend):
        self.cfg, self.backend = cfg, backend
        self.phase = "running" if cfg.auto_start else "idle"
        self.instruction = cfg.instruction
        self.generation = 0
        self.instance = uuid.uuid4().hex
        self.latest: Observation | None = None
        self.consumed_obs = None
        self.task = None
        self.tasks = set()
        self.rows = deque()
        self.history = deque(maxlen=cfg.history_size)
        self.pending_action = None
        self.chunk = None
        self.servo_steps = 0
        self.last_progress = time.monotonic()
        self.error = None
        self.inference_count = 0
        self.expected_identity = None

    def invalidate(self):
        self.generation += 1
        if self.task:
            self.task.cancel()
        self.task = None
        self.rows.clear()
        self.latest = None
        self.consumed_obs = None
        self.pending_action = None
        self.history.clear()
        self.servo_steps = 0
        self.error = None
        self.last_progress = time.monotonic()
        self.expected_identity = None

    def command(self, command, inputs=None):
        inputs = inputs or {}
        if command == "set_instruction":
            instruction = inputs.get("instruction")
            if not isinstance(instruction, str) or not instruction.strip():
                raise ValueError("set_instruction needs a nonempty instruction")
            self.invalidate()
            self.instruction = instruction
        elif command in {"reset_scene", "reset"}:
            if self.cfg.transport == "observation_v1" and command == "reset_scene":
                if not inputs.get("episode_id") or type(inputs.get("epoch")) is not int:
                    raise ValueError("strict reset_scene requires episode_id and integer epoch")
            self.invalidate()
            if self.cfg.transport == "observation_v1" and command == "reset_scene":
                self.expected_identity = (inputs["episode_id"], inputs["epoch"])
            self.phase = "idle" if command == "reset" else self.phase
            if self.phase == "error":
                self.phase = "running"
        elif command in {"pause", "stop", "start", "resume"}:
            self.invalidate()
            self.phase = {"pause": "paused", "stop": "idle"}.get(command, "running")
        else:
            raise ValueError(f"unsupported command: {command}")

    def observe(self, observation: Observation):
        cfg = self.cfg
        if len(observation.state) != len(cfg.state_names):
            raise ValueError("observation state does not match configured semantics")
        if set(observation.images) != set(cfg.image_inputs.values()):
            raise ValueError("observation camera aliases do not match configuration")
        if self.expected_identity and self.expected_identity != (
            observation.episode_id,
            observation.epoch,
        ):
            raise ValueError("observation belongs to a stale or unexpected episode")
        if self.latest:
            old = self.latest
            if (old.episode_id, old.epoch) != (observation.episode_id, observation.epoch):
                raise ValueError("episode identity changed without reset_scene")
            if observation.step_id <= old.step_id:
                return False
            if observation.obs_id == old.obs_id:
                raise ValueError("observation ID reused for a different step")
            if observation.step_id != old.step_id + 1 or self.pending_action is None:
                raise ValueError("unexpected observation advance without an outstanding action")
        if self.pending_action:
            self.history.append(
                {
                    **self.pending_action,
                    "ack_obs_id": observation.obs_id,
                    "observed_state": observation.state,
                }
            )
            self.pending_action = None
        self.latest = observation
        self.last_progress = time.monotonic()
        return True

    def fail(self, exc):
        self.invalidate()
        self.error = type(exc).__name__ + ": " + str(exc)
        self.phase = "error"

    def state(self):
        return {
            "schema_version": "vlm.policy.state.v1",
            "policy_id": self.cfg.policy_id,
            "phase": self.phase,
            "generation": self.generation,
            "obs_id": self.latest.obs_id if self.latest else None,
            "queue_length": len(self.rows),
            "inference_pending": self.task is not None,
            "inference_count": self.inference_count,
            "error": self.error,
            "synchronization": self.cfg.transport,
        }

    async def tick(self):
        """Nonblocking scheduler. Returns output tuples: (port, JSON-compatible data)."""
        outputs = []
        if self.phase != "running":
            return outputs
        try:
            if time.monotonic() - self.last_progress > self.cfg.observation_timeout_s:
                raise TimeoutError("no observation/execution progress before watchdog deadline")
            if self.task and self.task.done():
                task, self.task = self.task, None
                result, provenance = task.result()
                result.validate_for(self.cfg)
                if self.latest and self.latest.obs_id == self.request_obs:
                    self.rows.extend(copy.deepcopy(result.actions[: self.cfg.execute_horizon]))
                    self.chunk = {
                        "schema_version": "vlm.action_chunk.v1",
                        "chunk_id": self.request_id,
                        "episode_id": self.latest.episode_id,
                        "epoch": self.latest.epoch,
                        "source_obs_id": self.latest.obs_id,
                        "source_step_id": self.latest.step_id,
                        "action_space": result.action_space,
                        "frame": result.frame,
                        "dt_s": self.cfg.dt_s,
                        "actions": result.actions,
                        "execute_horizon": self.cfg.execute_horizon,
                        "provenance": provenance,
                    }
                    outputs.append(("action_chunk", self.chunk))
            obs = self.latest
            if not obs or obs.obs_id == self.consumed_obs:
                return outputs
            if self.rows:
                action, reached = native_action(self.cfg, self.rows[0], obs.state)
                self.servo_steps += 1
                if self.servo_steps > self.cfg.max_servo_steps:
                    raise TimeoutError("EEF waypoint did not converge within servo-step budget")
                if reached:
                    self.rows.popleft()
                    self.servo_steps = 0
                self.consumed_obs = obs.obs_id
                self.pending_action = {
                    "source_obs_id": obs.obs_id,
                    "chunk_id": self.chunk["chunk_id"],
                    "native_action": action,
                    "action_space": self.cfg.action_space,
                }
                outputs.append(
                    (
                        "action",
                        {
                            "name": self.cfg.action_names,
                            "position": action,
                            "episode_id": obs.episode_id,
                            "epoch": obs.epoch,
                            "step_id": obs.step_id,
                            "source_obs_id": obs.obs_id,
                        },
                    )
                )
            elif self.task is None:
                if not self.instruction.strip():
                    raise ValueError("instruction is empty")
                self.request_obs = obs.obs_id
                self.inference_count += 1
                self.request_id = f"act:{self.instance}:{self.generation}:{self.inference_count}"
                self.task = asyncio.create_task(
                    self.backend.infer(obs, self.instruction, list(self.history), self.request_id)
                )
                self.tasks.add(self.task)

                def finished(task):
                    self.tasks.discard(task)
                    if not task.cancelled():
                        task.exception()  # Retrieve retired failures after a reset.

                self.task.add_done_callback(finished)
        except Exception as exc:
            self.fail(exc)
            outputs.append(("policy_error", self.state()))
        return outputs

    async def close(self):
        self.invalidate()
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await self.backend.close()
