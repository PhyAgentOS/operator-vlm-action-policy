"""Strict application contracts; physical quantities use SI units."""

from __future__ import annotations

from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ImageInput(Strict):
    mime_type: Literal["image/png", "image/jpeg"] = "image/png"
    data: str


class Observation(Strict):
    episode_id: str = Field(min_length=1)
    epoch: int = Field(ge=0)
    step_id: int = Field(ge=0)
    obs_id: str = Field(min_length=1)
    state: list[float] = Field(min_length=1)
    images: dict[str, ImageInput] = Field(min_length=1)


class PolicyConfig(Strict):
    policy_id: str = "vlm_libero"
    service_url: str = "http://127.0.0.1:19120"
    token_env: str = "VLM_SERVICE_TOKEN"
    model_route: str | None = None
    instruction: str = ""
    prompt: str = "Produce short robot actions from the supplied observations and task."
    auto_start: bool = False
    transport: Literal["legacy_libero", "observation_v1"] = "legacy_libero"
    action_space: Literal["eef_delta", "eef_pose", "joint_position"] = "eef_delta"
    frame: Literal["world", "robot_base", "joint_space"] = "world"
    controller: Literal["libero_osc_delta", "joint_position"] = "libero_osc_delta"
    state_names: list[str] = Field(
        default_factory=lambda: [
            "joint1",
            "joint2",
            "joint3",
            "joint4",
            "joint5",
            "joint6",
            "joint7",
            "gripper",
        ]
    )
    state_semantics: list[str] = Field(
        default_factory=lambda: [
            "eef_x_m",
            "eef_y_m",
            "eef_z_m",
            "eef_rx_rad",
            "eef_ry_rad",
            "eef_rz_rad",
            "finger_left_m",
            "finger_right_m",
        ]
    )
    image_inputs: dict[str, str] = Field(
        default_factory=lambda: {"image/main": "main", "image/second": "wrist"}
    )
    action_names: list[str] = Field(default_factory=lambda: [f"joint{i}" for i in range(1, 8)])
    joint_names: list[str] = Field(default_factory=list)
    joint_lower: list[float] = Field(default_factory=list)
    joint_upper: list[float] = Field(default_factory=list)
    max_joint_step: float = Field(default=0.1, gt=0)
    # Positions are world-frame values from upstream LIBERO; scaling must match its controller.
    translation_scale: float = Field(default=0.05, gt=0)
    rotation_scale: float = Field(default=0.5, gt=0)
    max_translation: float = Field(default=0.02, gt=0)
    max_rotation: float = Field(default=0.2, gt=0)
    workspace_lower: list[float] = Field(default_factory=lambda: [-1.0, -1.0, 0.0])
    workspace_upper: list[float] = Field(default_factory=lambda: [1.0, 1.0, 1.5])
    position_tolerance: float = Field(default=0.005, gt=0)
    rotation_tolerance: float = Field(default=0.05, gt=0)
    max_servo_steps: int = Field(default=60, ge=1)
    max_chunk: int = Field(default=4, ge=1, le=32)
    execute_horizon: int = Field(default=2, ge=1, le=32)
    dt_s: float = Field(default=0.05, gt=0)
    deadline_ms: int = Field(default=60000, ge=1)
    max_output_tokens: int = Field(default=2048, ge=1)
    observation_timeout_s: float = Field(default=120.0, gt=0)
    history_size: int = Field(default=4, ge=0, le=32)
    max_image_pixels: int = Field(default=4_194_304, ge=1)

    @model_validator(mode="after")
    def consistent(self):
        if self.execute_horizon > self.max_chunk:
            raise ValueError("execute_horizon exceeds max_chunk")
        if not self.state_names or len(self.state_names) != len(self.state_semantics):
            raise ValueError("state names/semantics must have equal nonzero lengths")
        if len(set(self.state_names)) != len(self.state_names):
            raise ValueError("state names must be unique")
        if not self.image_inputs or len(set(self.image_inputs.values())) != len(self.image_inputs):
            raise ValueError("camera aliases must be nonempty and unique")
        if any(not k.startswith("image/") for k in self.image_inputs):
            raise ValueError("image inputs must use image/ topics")
        if not self.action_names or len(set(self.action_names)) != len(self.action_names):
            raise ValueError("action names must be nonempty and unique")
        if len(self.workspace_lower) != 3 or len(self.workspace_upper) != 3:
            raise ValueError("workspace bounds must be 3D")
        if any(a >= b for a, b in zip(self.workspace_lower, self.workspace_upper, strict=True)):
            raise ValueError("invalid workspace bounds")
        if self.max_translation > self.translation_scale or self.max_rotation > self.rotation_scale:
            raise ValueError("per-step limits must fit the controller input range")
        if self.action_space == "joint_position":
            n = len(self.joint_names)
            if self.controller != "joint_position" or self.frame != "joint_space":
                raise ValueError(
                    "joint output requires joint_position controller/joint_space frame"
                )
            if not n or len(set(self.joint_names)) != n:
                raise ValueError("joint_names must be nonempty and unique")
            if len(self.joint_lower) != n or len(self.joint_upper) != n:
                raise ValueError("joint bounds must match joint_names")
            if any(a >= b for a, b in zip(self.joint_lower, self.joint_upper, strict=True)):
                raise ValueError("invalid joint bounds")
            if len(self.action_names) != n + 1 or len(self.state_names) < n:
                raise ValueError("joint output needs N+1 action names and at least N state values")
            if self.state_names[:n] != self.joint_names:
                raise ValueError("joint state must start with joint_names in the declared order")
        elif self.controller != "libero_osc_delta" or self.frame != "world":
            raise ValueError("implemented LIBERO EEF adapter requires world-frame OSC delta")
        elif len(self.action_names) != 7 or len(self.state_names) < 6:
            raise ValueError("LIBERO EEF adapter needs seven action names and EEF state")
        return self

    @property
    def action_dim(self):
        return {"eef_delta": 7, "eef_pose": 8}.get(self.action_space, len(self.joint_names) + 1)

    def output_schema(self):
        n = self.action_dim
        return {
            "type": "object",
            "additionalProperties": False,
            "required": ["action_space", "frame", "actions"],
            "properties": {
                "action_space": {"type": "string", "const": self.action_space},
                "frame": {"type": "string", "const": self.frame},
                "actions": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": self.max_chunk,
                    "items": {
                        "type": "array",
                        "minItems": n,
                        "maxItems": n,
                        "items": {"type": "number"},
                    },
                },
            },
        }


class ModelActions(Strict):
    action_space: Literal["eef_delta", "eef_pose", "joint_position"]
    frame: Literal["world", "robot_base", "joint_space"]
    actions: list[list[float]] = Field(min_length=1)

    def validate_for(self, cfg: PolicyConfig):
        if self.action_space != cfg.action_space or self.frame != cfg.frame:
            raise ValueError("model output action contract mismatch")
        if len(self.actions) > cfg.max_chunk:
            raise ValueError("chunk exceeds configured horizon")
        if any(len(row) != cfg.action_dim for row in self.actions):
            raise ValueError("action dimension mismatch")
        values = np.asarray(self.actions, dtype=float)
        if not np.isfinite(values).all() or np.any(np.abs(values[:, -1]) > 1):
            raise ValueError("actions must be finite; gripper must be in [-1,1]")
        if cfg.action_space == "eef_delta":
            if np.any(np.linalg.norm(values[:, :3], axis=1) > cfg.max_translation):
                raise ValueError("EEF translation exceeds per-step limit")
            if np.any(np.linalg.norm(values[:, 3:6], axis=1) > cfg.max_rotation):
                raise ValueError("EEF rotation exceeds per-step limit")
        elif cfg.action_space == "eef_pose":
            if np.any(values[:, :3] < cfg.workspace_lower) or np.any(
                values[:, :3] > cfg.workspace_upper
            ):
                raise ValueError("EEF target outside workspace")
            if np.any(np.abs(np.linalg.norm(values[:, 3:7], axis=1) - 1) > 1e-3):
                raise ValueError("EEF quaternion must be normalized xyzw")
        elif np.any(values[:, :-1] < cfg.joint_lower) or np.any(values[:, :-1] > cfg.joint_upper):
            raise ValueError("joint target outside joint limits")
        return self
