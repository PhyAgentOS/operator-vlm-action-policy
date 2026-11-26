"""Validated standalone-policy configuration. Unsupported contracts fail at startup."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class ModelConfig:
    backend: str = "provider_api"
    api_style: str = "chat_completions"
    api_base_env: str = "VLM_API_BASE"
    api_key_env: str = "VLM_API_KEY"
    model_name_env: str = "VLM_MODEL"
    effort_env: str = "VLM_REASONING_EFFORT"
    structured_output: bool = True
    max_output_tokens: int = 2048
    local_factory: str = ""
    # Explicit YAML values override environment defaults. None means fallback.
    api_base: str | None = None
    api_key: str | None = field(default=None, repr=False)
    model_name: str | None = None
    reasoning_effort: str | None = None


@dataclass(frozen=True)
class ObservationConfig:
    image_inputs: dict[str, str] = field(default_factory=lambda: {
        "image/main": "main", "image/second": "wrist",
    })
    state_semantics: list[str] = field(default_factory=lambda: [
        "eef_x_m", "eef_y_m", "eef_z_m", "eef_rx_rad", "eef_ry_rad",
        "eef_rz_rad", "finger_left_m", "finger_right_m",
    ])
    state_names: list[str] = field(default_factory=lambda: [
        "joint1", "joint2", "joint3", "joint4", "joint5", "joint6", "joint7", "gripper",
    ])
    synchronization: str = "correlated_observation"
    require_identity: bool = True


@dataclass(frozen=True)
class ActionConfig:
    space: str = "eef_delta"
    frame: str = "world"
    dimension: int = 7
    layout: list[str] = field(default_factory=lambda: ["dx", "dy", "dz", "drx", "dry", "drz", "gripper"])
    units: list[str] = field(default_factory=lambda: ["m", "m", "m", "rad", "rad", "rad", "normalized"])
    gripper_convention: str = "minus1_open_plus1_close"
    prediction_horizon: int = 4
    max_prediction_horizon: int = 8
    execute_horizon: int = 2
    control_dt_s: float = 0.05
    joint_names: list[str] = field(default_factory=list)
    # Per-step maximum change in the corresponding action unit, including gripper.
    max_step_delta: list[float] = field(default_factory=list)
    # Generic vector semantics, one description per output coordinate.
    descriptions: list[str] = field(default_factory=list)
    # Optional observed-state name per coordinate for absolute-target step limits.
    state_keys: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AdapterConfig:
    type: str = "libero_osc_delta"
    native_dimension: int = 7
    translation_scale_m: float = 0.05
    rotation_scale_rad: float = 0.5
    limits_source: str = "robot_control_profile"
    lower_bounds: list[float] = field(default_factory=list)
    upper_bounds: list[float] = field(default_factory=list)
    # Generic native[i] = model[i] * scale[i] + offset[i]; empty means identity.
    scale: list[float] = field(default_factory=list)
    offset: list[float] = field(default_factory=list)


@dataclass(frozen=True)
class RuntimeConfig:
    tick_ms: int = 20
    inference_deadline_ms: int = 60000
    inference_timeout_retries: int = 2
    feedback_timeout_ms: int = 5000
    observation_timeout_ms: int = 60000
    on_error: str = "abort_evaluation"
    async_prefetch: bool = False
    exit_on_benchmark_result: bool = True


@dataclass(frozen=True)
class ContextConfig:
    scope: str = "episode"
    max_executed_history: int = 4
    include_unexecuted_actions: bool = False


@dataclass(frozen=True)
class LifecycleConfig:
    reset_history_per_episode: bool = True
    reject_stale_results: bool = True


@dataclass(frozen=True)
class PolicyConfig:
    policy_id: str = "vlm_libero"
    mode: str = "standalone"
    model: ModelConfig = field(default_factory=ModelConfig)
    observation: ObservationConfig = field(default_factory=ObservationConfig)
    action: ActionConfig = field(default_factory=ActionConfig)
    control_adapter: AdapterConfig = field(default_factory=AdapterConfig)
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    context: ContextConfig = field(default_factory=ContextConfig)
    lifecycle: LifecycleConfig = field(default_factory=LifecycleConfig)

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> PolicyConfig:
        if not isinstance(raw, dict):
            raise ValueError("policy YAML must be a mapping")
        unknown = set(raw) - {f.name for f in fields(cls)}
        if unknown:
            raise ValueError(f"unsupported policy fields: {sorted(unknown)}")
        values = dict(raw)
        for name, section in {
            "model": ModelConfig, "observation": ObservationConfig, "action": ActionConfig,
            "control_adapter": AdapterConfig, "runtime": RuntimeConfig,
            "context": ContextConfig, "lifecycle": LifecycleConfig,
        }.items():
            if name not in raw:
                continue
            part = raw[name]
            if not isinstance(part, dict):
                raise ValueError(f"{name} must be a mapping")
            extra = set(part) - {f.name for f in fields(section)}
            if extra:
                raise ValueError(f"unsupported {name} fields: {sorted(extra)}")
            values[name] = section(**part)
        result = cls(**values)
        result.validate()
        return result

    def with_contract(self, contract: dict[str, Any]) -> PolicyConfig:
        """Apply benchmark-owned sections only; model/runtime settings remain local."""
        if not isinstance(contract, dict) or contract.get("version") != 1 or type(contract.get("version")) is not int:
            raise ValueError("benchmark contract requires version=1")
        allowed = {"version", "action", "control_adapter", "observation"}
        if set(contract) - allowed or not {"action", "control_adapter"} <= set(contract):
            raise ValueError("contract requires action/control_adapter and optional observation")
        raw = asdict(self)
        # Sections are complete declarations; do not inherit a previous robot's layout.
        for name in allowed - {"version"}:
            if name in contract:
                raw[name] = contract[name]
        if not isinstance(raw["action"], dict) or raw["action"].get("space") != "generic":
            raise ValueError("benchmark-supplied contracts must use generic action space")
        required = {"space", "frame", "dimension", "layout", "units", "descriptions",
                    "prediction_horizon", "execute_horizon", "control_dt_s", "gripper_convention"}
        if not required <= set(raw["action"]):
            raise ValueError("benchmark action contract is incomplete")
        return self.from_mapping(raw)

    @classmethod
    def load(cls, path: str | Path) -> PolicyConfig:
        with Path(path).open(encoding="utf-8") as stream:
            return cls.from_mapping(yaml.safe_load(stream))

    def validate(self) -> None:
        a, adapter, obs = self.action, self.control_adapter, self.observation
        def require(condition: bool, message: str) -> None:
            if not condition:
                raise ValueError(message)
        def positive(value: Any) -> bool:
            return type(value) in (int, float) and math.isfinite(value) and value > 0
        def strings(value: Any) -> bool:
            return isinstance(value, list) and bool(value) and all(
                isinstance(x, str) and bool(x.strip()) for x in value
            ) and len(set(value)) == len(value)
        require(isinstance(self.policy_id, str) and bool(self.policy_id.strip()), "policy_id is required")
        require(self.mode == "standalone", "only mode=standalone (design section 2) is implemented")
        for name in ("dimension", "prediction_horizon", "max_prediction_horizon", "execute_horizon"):
            require(type(getattr(a, name)) is int and getattr(a, name) > 0, f"action.{name} must be a positive integer")
        require(1 <= a.execute_horizon <= a.prediction_horizon <= a.max_prediction_horizon <= 256,
                "require 1 <= M <= H <= max_prediction_horizon <= 256")
        require(strings(a.layout) and len(a.layout) == a.dimension, "action.layout must have D distinct names")
        require(isinstance(a.units, list) and len(a.units) == a.dimension, "action.units must have D entries")
        require(positive(a.control_dt_s), "control_dt_s must be positive and finite")
        require(a.space == "generic" or a.gripper_convention == "minus1_open_plus1_close", "unsupported gripper convention")
        require(type(adapter.native_dimension) is int and adapter.native_dimension == a.dimension, "native dimension must equal D")
        require(adapter.limits_source == "robot_control_profile", "unsupported limits_source")
        require(strings(obs.state_semantics), "state_semantics must be distinct nonempty names")
        require(strings(obs.state_names) and len(obs.state_names) == len(obs.state_semantics), "state_names must match the wire labels and state dimension")
        require(isinstance(obs.image_inputs, dict) and bool(obs.image_inputs) and all(
            isinstance(k, str) and bool(k) and isinstance(v, str) and bool(v)
            for k, v in obs.image_inputs.items()), "image_inputs must map input IDs to camera names")
        reserved = {"tick", "policy_command", "proprio_state", "benchmark_result"}
        require(not reserved.intersection(obs.image_inputs), "image inputs collide with reserved ports")
        require(len(set(obs.image_inputs.values())) == len(obs.image_inputs), "camera names must be unique")
        require(obs.synchronization in {"legacy_lockstep", "correlated_observation"}, "unknown synchronization")
        require(type(obs.require_identity) is bool and obs.require_identity == (obs.synchronization == "correlated_observation"),
                "require_identity must agree with synchronization")
        if a.space == "eef_delta":
            require(a.frame == "world" and a.dimension == 7, "eef_delta requires world frame and D=7")
            require(a.layout == ["dx", "dy", "dz", "drx", "dry", "drz", "gripper"], "unsupported EEF layout")
            require(a.units == ["m", "m", "m", "rad", "rad", "rad", "normalized"], "EEF units must be m/rad/normalized")
            require(adapter.type == "libero_osc_delta", "eef_delta requires libero_osc_delta adapter")
            require(positive(adapter.translation_scale_m) and positive(adapter.rotation_scale_rad), "controller scales must be positive")
            require(not a.joint_names, "eef_delta does not take joint_names")
        elif a.space == "joint_position":
            require(a.frame == "joint_space" and adapter.type == "joint_position", "joint_position requires matching frame/adapter")
            require(strings(a.joint_names) and len(a.joint_names) == a.dimension - 1, "provide D-1 unique joint_names")
            require(a.layout == a.joint_names + ["gripper"] and a.units == ["rad"] * (a.dimension - 1) + ["normalized"], "joint layout/units mismatch")
            require(all(name in obs.state_semantics for name in a.joint_names), "joint_position requires actual named joint positions in state_semantics")
            require(len(adapter.lower_bounds) == a.dimension and len(adapter.upper_bounds) == a.dimension, "joint_position requires explicit D-element bounds")
            require(len(a.max_step_delta) == a.dimension and all(
                positive(value) for value in a.max_step_delta
            ), "joint_position requires positive max_step_delta for every action dimension")
            require("gripper" in obs.state_semantics,
                    "joint_position requires gripper in state_semantics")
        elif a.space == "generic":
            require(adapter.type == "affine", "generic actions require affine adapter")
            require(isinstance(a.frame, str) and bool(a.frame.strip()), "generic action frame is required")
            require(all(isinstance(unit, str) and unit.strip() for unit in a.units), "generic units must be nonempty strings")
            require(isinstance(a.descriptions, list) and len(a.descriptions) == a.dimension
                    and all(isinstance(text, str) and text.strip() for text in a.descriptions),
                    "generic actions require D descriptions")
            require(len(adapter.lower_bounds) == a.dimension == len(adapter.upper_bounds),
                    "generic actions require explicit D-element bounds")
            require(not a.joint_names, "generic actions use layout and state_keys instead of joint_names")
            require(isinstance(a.state_keys, list) and (not a.state_keys or (
                len(a.state_keys) == a.dimension and all(key in obs.state_semantics for key in a.state_keys))),
                "state_keys must name D observed state coordinates")
            require(isinstance(a.max_step_delta, list) and (not a.max_step_delta or (
                len(a.max_step_delta) == a.dimension and all(positive(v) for v in a.max_step_delta)
                and bool(a.state_keys))), "generic max_step_delta requires D positive limits and state_keys")
        else:
            raise ValueError(f"unsupported action space: {a.space}")
        for name in ("scale", "offset"):
            values = getattr(adapter, name)
            require(isinstance(values, list) and (not values or (
                a.space == "generic" and len(values) == a.dimension and all(
                    type(v) in (int, float) and math.isfinite(v)
                    and (name != "scale" or v != 0) for v in values))),
                f"adapter.{name} requires D finite values (nonzero scales) for generic actions")
        if adapter.lower_bounds or adapter.upper_bounds:
            require(len(adapter.lower_bounds) == a.dimension == len(adapter.upper_bounds), "bounds must have D entries")
            require(all(type(x) in (int, float) and math.isfinite(x) for x in adapter.lower_bounds + adapter.upper_bounds), "bounds must be finite numbers")
            require(all(lo < hi for lo, hi in zip(adapter.lower_bounds, adapter.upper_bounds)), "lower bounds must be less than upper bounds")
            if a.space == "eef_delta":
                physical = [adapter.translation_scale_m] * 3 + [adapter.rotation_scale_rad] * 3 + [1.0]
                require(all(-bound <= lo < hi <= bound for lo, hi, bound in zip(adapter.lower_bounds, adapter.upper_bounds, physical)), "EEF bounds exceed controller range")
            if a.space != "generic":
                require(-1 <= adapter.lower_bounds[-1] < adapter.upper_bounds[-1] <= 1, "gripper bounds must stay within [-1,1]")
        for name in ("tick_ms", "inference_deadline_ms", "feedback_timeout_ms", "observation_timeout_ms"):
            value = getattr(self.runtime, name)
            require(type(value) is int and value > 0, f"runtime.{name} must be a positive integer")
        require(type(self.runtime.inference_timeout_retries) is int
                and 0 <= self.runtime.inference_timeout_retries <= 2,
                "runtime.inference_timeout_retries must be an integer between 0 and 2")
        require(type(self.runtime.exit_on_benchmark_result) is bool, "exit_on_benchmark_result must be boolean")
        require(self.runtime.on_error == "abort_evaluation" and self.runtime.async_prefetch is False, "only serial inference with abort_evaluation is supported")
        require(self.context.scope == "episode" and self.context.include_unexecuted_actions is False, "context must contain confirmed episode history only")
        require(type(self.context.max_executed_history) is int and 0 <= self.context.max_executed_history <= 256, "invalid history bound")
        require(self.lifecycle.reset_history_per_episode is True and self.lifecycle.reject_stale_results is True, "lifecycle isolation must stay enabled")
        require(self.model.backend in {"provider_api", "local_python"}, "unknown model backend")
        require(self.model.api_style in {"chat_completions", "responses"}, "unknown model.api_style")
        require(type(self.model.structured_output) is bool, "structured_output must be boolean")
        require(type(self.model.max_output_tokens) is int and self.model.max_output_tokens > 0, "max_output_tokens must be positive")
        for name in ("api_base", "api_key", "model_name", "reasoning_effort"):
            value = getattr(self.model, name)
            require(value is None or (isinstance(value, str) and "\x00" not in value
                    and (name == "reasoning_effort" or bool(value.strip()))),
                    f"model.{name} must be a string or null (base/key/model cannot be empty)")
        for name in ("api_base_env", "api_key_env", "model_name_env", "effort_env"):
            value = getattr(self.model, name)
            valid_name = (isinstance(value, str) and bool(value)
                          and (value[0].isascii() and (value[0].isalpha() or value[0] == "_"))
                          and all(char.isascii() and (char.isalnum() or char == "_") for char in value))
            require(valid_name, f"model.{name} must name an environment variable")
        if self.model.backend == "local_python":
            require(isinstance(self.model.local_factory, str) and ":" in self.model.local_factory, "local_python requires local_factory=module:factory")
