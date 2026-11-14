"""Observation identity and physical action contracts; no transport dependencies."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from .config import PolicyConfig

IDENTITY_KEYS = ("episode_id", "epoch", "obs_id", "step_id", "instruction_version")


@dataclass(frozen=True)
class Identity:
    episode_id: str
    epoch: str
    obs_id: str
    step_id: int
    instruction_version: int

    @classmethod
    def parse(cls, metadata: dict[str, Any]) -> Identity:
        values = {key: metadata.get(key) for key in IDENTITY_KEYS}
        for key in ("episode_id", "epoch", "obs_id"):
            if not isinstance(values[key], str) or not values[key]:
                raise ValueError(f"missing or invalid observation {key}")
        for key, minimum in (("step_id", 0), ("instruction_version", 1)):
            if type(values[key]) is not int or values[key] < minimum:
                raise ValueError(f"invalid observation {key}")
        return cls(**values)

    def metadata(self) -> dict[str, Any]:
        return {key: getattr(self, key) for key in IDENTITY_KEYS}

    @property
    def episode_key(self) -> tuple[str, str, int]:
        return self.episode_id, self.epoch, self.instruction_version


@dataclass(frozen=True)
class Observation:
    identity: Identity
    state: tuple[float, ...]
    images: dict[str, bytes]  # immutable PNG byte strings, keyed by camera alias
    last_action_id: str | None = None


@dataclass
class _Parts:
    identity: Identity
    values: dict[str, Any] = field(default_factory=dict)
    last_action_id: str | None = None


class ObservationBuffer:
    """Strict grouping by identity, or explicitly limited serial legacy grouping."""

    def __init__(self, config: PolicyConfig):
        self.config = config
        self.required = {"proprio_state", *config.observation.image_inputs}
        self.parts: dict[Identity, _Parts] = {}
        self.consumed: set[Identity] = set()
        self.binding: Identity | None = None
        self.legacy_step = 0
        self.legacy_generation = 0

    def reset(self, binding: Identity | None = None) -> None:
        self.parts.clear()
        self.consumed.clear()
        self.binding = binding
        self.legacy_step = 0
        self.legacy_generation += 1

    def add(self, port: str, value: Any, metadata: dict[str, Any], *,
            expected_step: int | None) -> Observation | None:
        if port not in self.required:
            return None
        if self.config.observation.require_identity:
            identity = Identity.parse(metadata)
            if self.binding is None:
                return None  # reset_scene must establish the active epoch first
            if identity.episode_key != self.binding.episode_key:
                return None
            if expected_step is None or identity.step_id != expected_step:
                return None
        else:
            epoch = self.binding.epoch if self.binding else str(self.legacy_generation)
            episode = self.binding.episode_id if self.binding else "legacy"
            version = self.binding.instruction_version if self.binding else 1
            identity = Identity(episode, epoch, f"{epoch}:{self.legacy_step}",
                                self.legacy_step, version)
        if identity in self.consumed:
            return None
        part = self.parts.setdefault(identity, _Parts(identity))
        if len(self.parts) > 8:
            del self.parts[next(iter(self.parts))]
        ack = metadata.get("last_action_id")
        if ack is not None:
            if not isinstance(ack, str) or not ack:
                raise ValueError("last_action_id must be a nonempty string")
            if part.last_action_id is not None and part.last_action_id != ack:
                raise ValueError("observation parts have conflicting action acknowledgements")
            part.last_action_id = ack
        # First message wins: a duplicate cannot overwrite half of an observation.
        part.values.setdefault(port, value)
        if set(part.values) != self.required:
            return None
        state = part.values["proprio_state"]
        if len(state) != len(self.config.observation.state_semantics):
            raise ValueError("state dimension does not match configured state_semantics")
        if any(type(v) not in (float, int) or not math.isfinite(v) for v in state):
            raise ValueError("state must contain finite numbers")
        images = {alias: part.values[input_id]
                  for input_id, alias in self.config.observation.image_inputs.items()}
        if any(not isinstance(image, bytes) or not image for image in images.values()):
            raise ValueError("each camera must provide an encoded nonempty PNG")
        observation = Observation(identity, tuple(float(v) for v in state), images, part.last_action_id)
        self.consumed.add(identity)
        if len(self.consumed) > 16:
            self.consumed = {identity}
        self.parts.pop(identity, None)
        if not self.config.observation.require_identity:
            self.legacy_step += 1
        return observation


class ActionAdapter:
    def __init__(self, config: PolicyConfig):
        self.config = config

    def bounds(self) -> tuple[list[float], list[float]]:
        c = self.config.control_adapter
        if c.lower_bounds:
            return c.lower_bounds, c.upper_bounds
        high = [c.translation_scale_m] * 3 + [c.rotation_scale_rad] * 3 + [1.0]
        return [-v for v in high], high

    def validate_chunk(self, response: Any) -> list[list[float]]:
        if not isinstance(response, dict) or set(response) != {"actions"}:
            raise ValueError("model response must be exactly an object with an actions array")
        rows = response["actions"]
        a = self.config.action
        if not isinstance(rows, list) or len(rows) != a.prediction_horizon:
            raise ValueError(f"expected exactly H={a.prediction_horizon} action rows")
        low, high = self.bounds()
        result = []
        for index, row in enumerate(rows):
            if not isinstance(row, list) or len(row) != a.dimension:
                raise ValueError(f"action row {index} must contain D={a.dimension} numbers")
            if any(type(v) not in (float, int) or not math.isfinite(v) for v in row):
                raise ValueError(f"action row {index} contains nonfinite or nonnumeric values")
            if any(v < lo or v > hi for v, lo, hi in zip(row, low, high)):
                raise ValueError(f"action row {index} exceeds configured physical limits")
            result.append([float(v) for v in row])
        return result

    def to_native(self, action: list[float]) -> list[float]:
        c = self.config.control_adapter
        if c.type == "joint_position":
            return list(action)
        scales = [c.translation_scale_m] * 3 + [c.rotation_scale_rad] * 3 + [1.0]
        return [value / scale for value, scale in zip(action, scales)]

    def schema(self) -> dict[str, Any]:
        a = self.config.action
        return {
            "type": "object", "additionalProperties": False, "required": ["actions"],
            "properties": {"actions": {
                "type": "array", "minItems": a.prediction_horizon,
                "maxItems": a.prediction_horizon, "items": {
                    "type": "array", "minItems": a.dimension, "maxItems": a.dimension,
                    "items": {"type": "number"},
                },
            }},
        }
