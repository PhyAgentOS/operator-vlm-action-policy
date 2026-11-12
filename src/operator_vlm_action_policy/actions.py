"""Bounded action conversion; no collision-planning or IK claims."""

from __future__ import annotations

import numpy as np

from .contracts import PolicyConfig


def rotvec_quaternion(vector):
    vector = np.asarray(vector, dtype=float)
    angle = np.linalg.norm(vector)
    if angle < 1e-12:
        return np.array([0.0, 0.0, 0.0, 1.0])
    return np.r_[vector / angle * np.sin(angle / 2), np.cos(angle / 2)]


def rotation_error(target, current_rotvec):
    """World-frame log(R_target R_current^-1); quaternion order xyzw."""
    a = np.asarray(target, dtype=float)
    b = rotvec_quaternion(current_rotvec) * np.array([-1, -1, -1, 1])
    q = np.r_[
        a[3] * b[:3] + b[3] * a[:3] + np.cross(a[:3], b[:3]), a[3] * b[3] - np.dot(a[:3], b[:3])
    ]
    if q[3] < 0:
        q = -q
    n = np.linalg.norm(q[:3])
    return np.zeros(3) if n < 1e-12 else q[:3] / n * (2 * np.arctan2(n, q[3]))


def _bounded(vector, limit):
    vector = np.asarray(vector, dtype=float)
    norm = np.linalg.norm(vector)
    return vector if norm <= limit else vector * (limit / norm)


def native_action(cfg: PolicyConfig, row: list[float], state: list[float]):
    """Return (native vector, waypoint reached). Recompute pose error on each observation."""
    if len(state) != len(cfg.state_names) or not np.isfinite(state).all():
        raise ValueError("invalid observed state")
    if cfg.action_space == "joint_position":
        n = len(cfg.joint_names)
        if np.any(np.abs(np.asarray(row[:n]) - state[:n]) > cfg.max_joint_step):
            raise ValueError("joint step exceeds configured limit")
        return list(row), True
    if cfg.action_space == "eef_pose":
        delta = np.asarray(row[:3]) - state[:3]
        rotation = rotation_error(row[3:7], state[3:6])
        reached = (
            np.linalg.norm(delta) <= cfg.position_tolerance
            and np.linalg.norm(rotation) <= cfg.rotation_tolerance
        )
        delta = _bounded(delta, cfg.max_translation)
        rotation = _bounded(rotation, cfg.max_rotation)
    else:
        delta = np.asarray(row[:3])
        rotation = np.asarray(row[3:6])
        reached = True
    predicted = np.asarray(state[:3]) + delta
    if np.any(predicted < cfg.workspace_lower) or np.any(predicted > cfg.workspace_upper):
        raise ValueError("next EEF command leaves configured workspace")
    return [*(delta / cfg.translation_scale), *(rotation / cfg.rotation_scale), row[-1]], reached
