"""Client of the existing generic service; provider credentials stay in that service."""

from __future__ import annotations

import asyncio
import json
import os

import httpx

from .contracts import ModelActions, Observation, PolicyConfig


class VLMClient:
    def __init__(self, cfg: PolicyConfig, client=None):
        self.cfg = cfg
        token = os.environ.get(cfg.token_env)
        self.client = client or httpx.AsyncClient(
            base_url=cfg.service_url.rstrip("/"),
            headers={"Authorization": f"Bearer {token}"} if token else {},
            timeout=cfg.deadline_ms / 1000 + 5,
            follow_redirects=False,
        )

    def request(self, obs: Observation, instruction, history, request_id):
        cfg = self.cfg
        data = {
            "instruction": instruction,
            "observation": obs.model_dump(exclude={"images"}),
            "state_semantics": cfg.state_semantics,
            "executed_history": history,
            "contract": {
                "action_space": cfg.action_space,
                "frame": cfg.frame,
                "dt_s": cfg.dt_s,
                "eef_delta": "dx,dy,dz in m; world rotation vector in rad; gripper [-1,1]",
                "eef_pose": "x,y,z in m; quaternion xyzw; gripper [-1,1]",
                "joint_position": "joint_names order in rad; final normalized gripper",
                "joint_names": cfg.joint_names,
                "joint_lower": cfg.joint_lower,
                "joint_upper": cfg.joint_upper,
                "max_joint_step": cfg.max_joint_step,
                "max_translation_m": cfg.max_translation,
                "max_rotation_rad": cfg.max_rotation,
                "workspace_lower_m": cfg.workspace_lower,
                "workspace_upper_m": cfg.workspace_upper,
                "gripper_convention": "LIBERO Panda: -1 open, +1 close; joint adapter must match",
            },
        }
        content = [{"type": "text", "text": json.dumps(data, allow_nan=False)}]
        for alias, media in obs.images.items():
            content.append(
                {
                    "type": "image",
                    "image_id": f"{obs.obs_id}:{alias}",
                    "source": {"type": "inline_base64", **media.model_dump()},
                    "metadata": {"camera_id": alias, "obs_id": obs.obs_id},
                }
            )
        return {
            "request_id": request_id,
            "messages": [
                {"role": "system", "content": cfg.prompt},
                {"role": "user", "content": content},
            ],
            "context": {"mode": "stateless"},
            "response_format": {"type": "json_schema", "schema": cfg.output_schema()},
            "model_route": cfg.model_route,
            "limits": {"deadline_ms": cfg.deadline_ms, "max_output_tokens": cfg.max_output_tokens},
        }

    async def infer(self, obs, instruction, history, request_id):
        try:
            async with asyncio.timeout(self.cfg.deadline_ms / 1000 + 5):
                response = await self.client.post(
                    "/v1/infer:wait", json=self.request(obs, instruction, history, request_id)
                )
                response.raise_for_status()
                result = response.json()
                if result.get("execution_status") != "succeeded":
                    raise ValueError(f"inference terminal status: {result.get('execution_status')}")
                actions = ModelActions.model_validate(result["output"]["json"])
                return actions.validate_for(self.cfg), {
                    "request_id": request_id,
                    "usage": result.get("usage"),
                    "provenance": result.get("provenance"),
                }
        except (asyncio.CancelledError, TimeoutError):
            # Disconnecting infer:wait alone does not cancel the generic service job.
            try:
                await self.client.post(f"/v1/requests/{request_id}/cancel", timeout=2)
            except httpx.HTTPError:
                pass
            raise

    async def close(self):
        await self.client.aclose()
