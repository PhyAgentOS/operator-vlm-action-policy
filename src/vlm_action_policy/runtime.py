"""Serial H/M policy state machine. Only the event-loop thread emits outputs."""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from queue import Empty, Queue
from typing import Any, Callable
from uuid import uuid4

from .backend import Backend, InferenceRequest, inference_diagnostic
from .config import PolicyConfig
from .contracts import ActionAdapter, Identity, Observation, ObservationBuffer


class InferenceWorker:
    """One bounded daemon worker; lifecycle invalidation never creates more workers."""

    def __init__(self, backend: Backend):
        self.backend = backend
        self.jobs: Queue = Queue(maxsize=1)
        self.results: Queue = Queue(maxsize=1)
        self.busy = False
        self.closed = False
        self.thread = threading.Thread(target=self._run, name="vlm-inference", daemon=True)
        self.thread.start()

    def submit(self, token: tuple[int, str], request: InferenceRequest) -> None:
        if self.busy or self.closed:
            raise RuntimeError("inference worker is unavailable")
        self.busy = True
        self.jobs.put_nowait((token, request))

    def _run(self) -> None:
        while True:
            item = self.jobs.get()
            if item is None:
                return
            token, request = item
            try:
                result = self.backend.infer(request)
                self.results.put((token, result, None))
            except Exception as exc:  # Plugin/provider failures must reach the event loop.
                self.results.put((token, None, inference_diagnostic(exc)))

    def poll(self) -> tuple | None:
        try:
            result = self.results.get_nowait()
        except Empty:
            return None
        self.busy = False
        return result

    def close(self) -> None:
        self.closed = True
        if not self.busy:
            self.jobs.put_nowait(None)
        # A blocked local model cannot be killed safely; daemon + epoch rejection isolates it.


@dataclass
class PendingAction:
    action_id: str
    chunk_id: str
    row_index: int
    physical: list[float]
    native: list[float]
    observation: Observation
    sent_at: float


class PolicyRuntime:
    def __init__(self, config: PolicyConfig, backend: Backend,
                 emit: Callable[[str, Any, dict[str, Any]], None], *,
                 clock: Callable[[], float] = time.monotonic, worker=None):
        config.validate()
        self.config, self.emit, self.clock = config, emit, clock
        self.adapter = ActionAdapter(config)
        self.buffer = ObservationBuffer(config)
        self.worker = worker or InferenceWorker(backend)
        self.generation = 0
        self.running = False
        self.failed = False
        self.needs_reset = True
        self.instruction = ""
        self.binding: Identity | None = None
        self.retired_epochs: set[str] = set()
        self.latest: Observation | None = None
        self.failure_identity: Identity | None = None
        self.pending: PendingAction | None = None
        self.history: deque[dict[str, Any]] = deque(maxlen=config.context.max_executed_history)
        self.chunk: list[list[float]] = []
        self.chunk_id = ""
        self.cursor = 0
        self.active_token: tuple[int, str] | None = None
        self.inference_started: float | None = None
        self.wait_started: float | None = None
        self.resume_required = False
        self.closed = False
        self.seen_commands: set[tuple] = set()
        self.early_parts: dict[Identity, dict[str, tuple[Any, dict[str, Any]]]] = {}
        self.legacy_early: dict[str, tuple[Any, dict[str, Any]]] = {}
        self._state("IDLE")

    def _metadata(self) -> dict[str, Any]:
        identity = self.failure_identity or self.binding
        return identity.metadata() if identity else {}

    def _state(self, state: str, **extra) -> None:
        self.emit("policy_state", {"policy_id": self.config.policy_id, "state": state,
                                   **self._metadata(), **extra}, self._metadata())

    def _invalidate(self, *, clear_history: bool = False) -> None:
        self.generation += 1
        self.active_token = None
        self.inference_started = None
        self.chunk = []
        self.cursor = 0
        self.chunk_id = ""
        self.latest = None
        self.pending = None
        self.wait_started = None
        self.buffer.reset(self.binding)
        if clear_history:
            self.history.clear()

    def _fail(self, code: str, message: str) -> None:
        if self.failed:
            return
        self.failed = True
        self.running = False
        self.needs_reset = True
        action_id = self.pending.action_id if self.pending else None
        self._invalidate()
        payload = {"policy_id": self.config.policy_id, "code": code, "message": message,
                   **self._metadata()}
        if action_id:
            payload["action_id"] = action_id
        self.emit("policy_error", payload, self._metadata())
        self._state("ERROR", code=code, message=message)

    def command(self, policy_id: str, command: str, inputs: dict[str, Any]) -> None:
        if policy_id != self.config.policy_id or self.closed:
            return
        if not isinstance(inputs, dict):
            self._fail("invalid_command", "command inputs must be an object")
            return
        identity = None
        has_identity = any(key in inputs for key in ("episode_id", "epoch", "obs_id"))
        if has_identity:
            try:
                identity = Identity.parse(inputs)
            except ValueError as exc:
                self._fail("invalid_command", str(exc))
                return
            if identity.epoch in self.retired_epochs:
                return
            if self.binding and identity.epoch == self.binding.epoch:
                active_identity = self.failure_identity or self.binding
                if identity.instruction_version < active_identity.instruction_version:
                    return
                if identity.step_id < active_identity.step_id:
                    return
            signature = (command, identity, repr(sorted(inputs.items())))
            if signature in self.seen_commands and not (
                command in {"reset", "reset_scene"} and self.resume_required
            ):
                return
            self.seen_commands.add(signature)
        if command == "start":
            self.running = True
            self.failed = False
            if not self.needs_reset:
                self.wait_started = self.clock()
                self._replay_early()
            self._state("READY" if self.needs_reset else "WAIT_OBSERVATION")
        elif command == "set_instruction":
            instruction = inputs.get("instruction")
            if not isinstance(instruction, str) or not instruction.strip():
                self._fail("invalid_instruction", "instruction must be a nonempty string")
                return
            self.instruction = instruction
            self._invalidate(clear_history=True)
            self.needs_reset = True
            if identity:
                self.failure_identity = identity
            self._state("WAIT_RESET")
        elif command in {"reset", "reset_scene"}:
            if self.config.observation.require_identity and identity is None:
                self._fail("missing_identity", "strict reset requires a complete observation identity")
                return
            if not self.config.observation.require_identity:
                # Old benchmarks carry no episode identity. This local UUID fences
                # inference results only; it cannot identify stale wire messages.
                epoch = uuid4().hex
                identity = Identity("legacy", epoch, f"{epoch}:0", 0, 1)
            if self.config.observation.require_identity and identity and self.binding and identity.epoch != self.binding.epoch:
                self.retired_epochs.add(self.binding.epoch)
                self.instruction = self.instruction if self.failure_identity == identity else ""
            self.binding = identity
            self.failure_identity = identity
            self._invalidate(clear_history=True)
            self.failed = False
            self.needs_reset = False
            self.resume_required = False
            if command == "reset":
                self.running = False
            if self.running:
                self.wait_started = self.clock()
            self._state("WAIT_OBSERVATION" if self.running else "READY")
            self._replay_early()
        elif command == "pause":
            self.running = False
            self.resume_required = True
            self.needs_reset = True
            self._invalidate()
            self.early_parts.clear()
            self.legacy_early.clear()
            self._state("PAUSED")
        elif command == "resume":
            self.running = True
            # A reset plus a complete observation must reconcile any in-flight action.
            self._state("WAIT_RESET" if self.needs_reset else "WAIT_OBSERVATION")
            if not self.needs_reset:
                self.wait_started = self.clock()
                self._replay_early()
        elif command == "stop":
            self.running = False
            self.needs_reset = True
            self._invalidate(clear_history=True)
            self.early_parts.clear()
            self.legacy_early.clear()
            self._state("STOPPED")
        else:
            self._fail("unsupported_command", f"unsupported policy command: {command}")

    def _replay_early(self) -> None:
        if not self.running or self.needs_reset or self.binding is None:
            return
        if not self.config.observation.require_identity:
            early, self.legacy_early = self.legacy_early, {}
        else:
            early = self.early_parts.pop(self.binding, {})
        self.early_parts = {key: value for key, value in self.early_parts.items()
                            if key.epoch not in self.retired_epochs}
        for port, (value, metadata) in early.items():
            self.observe(port, value, metadata)

    def expected_step(self) -> int | None:
        if self.pending:
            return self.pending.observation.identity.step_id + 1
        if self.latest:
            return None  # Already granted a single action credit; duplicates grant nothing.
        return self.binding.step_id if self.binding else None

    def observe(self, port: str, value: Any, metadata: dict[str, Any]) -> None:
        if self.closed:
            return
        if not self.config.observation.require_identity:
            if self.failed or self.resume_required or port not in self.buffer.required:
                return
            if self.needs_reset or not self.running or self.binding is None:
                # Different Dora ports can arrive before reset_scene. Retain one
                # frame, bounded by the configured state/camera port count.
                self.legacy_early.setdefault(port, (value, dict(metadata)))
                return
            if self.pending is None and (self.latest is not None or self.active_token is not None):
                return  # Unsolicited duplicates while inferring grant no action credit.
        if self.config.observation.require_identity:
            try:
                candidate = Identity.parse(metadata)
            except ValueError as exc:
                if self.running and not self.needs_reset:
                    self._fail("invalid_observation", str(exc))
                return
            if candidate.epoch in self.retired_epochs:
                return
            if self.binding and candidate.epoch == self.binding.epoch and candidate.instruction_version < self.binding.instruction_version:
                return
            # Dora preserves a port's order, but images can precede reset on another port.
            if self.needs_reset or not self.running or self.binding is None or candidate.episode_key != self.binding.episode_key:
                if len(self.early_parts) >= 8 and candidate not in self.early_parts:
                    del self.early_parts[next(iter(self.early_parts))]
                self.early_parts.setdefault(candidate, {}).setdefault(port, (value, dict(metadata)))
                return
        if not self.running or self.failed or self.needs_reset:
            return
        try:
            expected = self.expected_step()
            if self.config.observation.require_identity:
                candidate = Identity.parse(metadata)
                if not self.binding or candidate.episode_key != self.binding.episode_key:
                    return
                if expected is None or candidate.step_id != expected:
                    return
                self.failure_identity = candidate
                if self.pending and metadata.get("last_action_id") != self.pending.action_id:
                    self._fail("invalid_feedback", "observation channel does not acknowledge the pending action")
                    return
            observation = self.buffer.add(port, value, metadata, expected_step=expected)
            if observation is None:
                return
            if self.pending:
                pending = self.pending
                if self.config.observation.require_identity and observation.last_action_id != pending.action_id:
                    self._fail("invalid_feedback", "new observation does not acknowledge the pending action")
                    return
                self.history.append({
                    "action_id": pending.action_id, "chunk_id": pending.chunk_id,
                    "row_index": pending.row_index, "action": pending.physical,
                    "native_action": pending.native,
                    "source_observation": pending.observation.identity.metadata(),
                    "ack_observation": observation.identity.metadata(),
                })
                self.pending = None
            self.latest = observation
            self.failure_identity = observation.identity
            self.wait_started = None
            if self.chunk and self.cursor < min(len(self.chunk), self.config.action.execute_horizon):
                self._send_one()
            else:
                self.chunk = []  # Discard H-M rows before requesting a new plan.
                self.cursor = 0
                self._maybe_infer()
        except (ValueError, TypeError) as exc:
            self._fail("invalid_observation", str(exc))

    def _maybe_infer(self) -> None:
        if not self.latest or self.pending or self.active_token or self.worker.busy:
            return
        if not self.instruction:
            self._fail("missing_instruction", "set_instruction must precede the first inference")
            return
        token = (self.generation, uuid4().hex)
        request = InferenceRequest(self.instruction, self.latest, tuple(self.history))
        self.wait_started = None
        self.worker.submit(token, request)
        self.active_token = token
        self.inference_started = self.clock()
        self._state("INFER", request_id=token[1])

    def _send_one(self) -> None:
        if self.pending or self.latest is None or not self.running or self.failed:
            return
        observation = self.latest
        physical = self.chunk[self.cursor]
        native = self.adapter.to_native(physical)
        pending = PendingAction(uuid4().hex, self.chunk_id, self.cursor, physical, native,
                                observation, self.clock())
        self.pending = pending
        self.latest = None
        self.cursor += 1
        self.emit("action", native, {
            **observation.identity.metadata(), "action_id": pending.action_id,
            "chunk_id": pending.chunk_id, "row_index": pending.row_index,
        })
        self._state("WAIT_ACK", action_id=pending.action_id)

    def tick(self) -> None:
        if self.closed:
            return
        result = self.worker.poll()
        if result is not None:
            token, response, error = result
            if token == self.active_token and self.running and not self.failed and not self.needs_reset:
                self.active_token = None
                elapsed_ms = (self.clock() - self.inference_started) * 1000
                self.inference_started = None
                if elapsed_ms > self.config.runtime.inference_deadline_ms:
                    self._fail("inference_timeout", "model inference deadline exceeded")
                elif error:
                    # Worker returns only fixed diagnostic labels, never raw exceptions.
                    self._fail("inference_error", f"model backend failed ({error})")
                else:
                    try:
                        self.chunk = self.adapter.validate_chunk(response)
                    except (ValueError, TypeError) as exc:
                        self._fail("invalid_action", str(exc))
                    else:
                        self.cursor = 0
                        self.chunk_id = token[1]
                        self.emit("action_chunk", {
                            "policy_id": self.config.policy_id, **self._metadata(),
                            "chunk_id": self.chunk_id, "actions": self.chunk,
                            "action_space": self.config.action.space,
                            "frame": self.config.action.frame,
                            "layout": self.config.action.layout, "units": self.config.action.units,
                            "prediction_horizon": self.config.action.prediction_horizon,
                            "execute_horizon": self.config.action.execute_horizon,
                            "control_dt_s": self.config.action.control_dt_s,
                            "inference_wall_ms": elapsed_ms,
                        }, self._metadata())
                        self._send_one()
        if not self.running or self.failed or self.needs_reset:
            return
        now = self.clock()
        if self.active_token and (now - self.inference_started) * 1000 > self.config.runtime.inference_deadline_ms:
            self._fail("inference_timeout", "model inference deadline exceeded")
        elif self.pending and (now - self.pending.sent_at) * 1000 > self.config.runtime.feedback_timeout_ms:
            self._fail("feedback_timeout", "environment action acknowledgement timed out")
        elif self.wait_started is not None and (now - self.wait_started) * 1000 > self.config.runtime.observation_timeout_ms:
            self._fail("observation_timeout", "complete observation did not arrive before deadline")
        elif self.latest:
            # A stale, uninterruptible model call may still occupy the sole worker.
            if self.worker.busy and self.active_token is None:
                if self.wait_started is None:
                    self.wait_started = now
            else:
                self._maybe_infer()

    def benchmark_result(self) -> None:
        self.running = False
        self.needs_reset = True
        self._invalidate(clear_history=True)
        self.early_parts.clear()
        self.legacy_early.clear()
        self._state("DONE")

    def fail_input(self, code: str, message: str) -> None:
        self._fail(code, message)

    def close(self) -> None:
        self.running = False
        self._invalidate()
        self.closed = True
        self.worker.close()
