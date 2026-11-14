"""Native Dora/Forge transport boundary and CLI."""
from __future__ import annotations

import argparse
import json
import os
import sys
from io import BytesIO
from typing import Any

from .backend import create_backend
from .config import PolicyConfig


def image_to_png(value) -> bytes:
    import numpy as np
    from forge_msgs import Image
    from PIL import Image as PILImage

    message = Image.from_arrow(value)
    frame = message.to_numpy()
    if message.encoding not in {"rgb8", "bgr8", "rgba8", "bgra8", "mono8"}:
        raise ValueError("only 8-bit color or grayscale camera inputs are supported")
    if frame.size == 0 or frame.dtype != np.uint8:
        raise ValueError("camera image must be nonempty uint8")
    if message.encoding == "bgr8":
        frame = frame[:, :, ::-1]
    elif message.encoding == "bgra8":
        frame = frame[:, :, [2, 1, 0, 3]]
    image = PILImage.fromarray(frame).convert("RGB")
    out = BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def run_node(config: PolicyConfig, node=None, backend=None) -> int:
    import pyarrow as pa
    from forge_msgs import JointCommand, JointState, PolicyCommand

    from .runtime import PolicyRuntime

    if backend is None:
        backend = create_backend(config)
    if node is None:
        from dora import Node
        node = Node()

    def emit(port: str, payload: Any, metadata: dict[str, Any]) -> None:
        if port == "action":
            names = config.action.joint_names + ["gripper"] if config.action.space == "joint_position" else config.action.layout
            value = JointCommand(name=names, position=payload).to_arrow()
        else:
            value = pa.array([json.dumps(payload, ensure_ascii=False, allow_nan=False)])
        node.send_output(port, value, metadata)
        # State/error outputs may have no subscriber. Keep startup stalls visible in
        # Dora logs without logging observations, instructions or provider settings.
        if port == "policy_state":
            print(f"[vlm_policy] state={payload['state']}", flush=True)
        elif port == "policy_error":
            print(f"[vlm_policy] error={payload['code']}", file=sys.stderr, flush=True)
            if payload["code"] == "inference_error":
                # InferenceWorker supplies only fixed diagnostic labels/status codes.
                print(f"[vlm_policy] {payload['message']}", file=sys.stderr, flush=True)
            if payload["code"] == "missing_identity":
                print(
                    "[vlm_policy] benchmark protocol incompatible: reset_scene requires "
                    "episode_id, epoch, obs_id, step_id and instruction_version; "
                    "use the updated benchmark with correlated_observations enabled.",
                    file=sys.stderr, flush=True,
                )

    if not config.observation.require_identity:
        print("[vlm_policy] synchronization=legacy_lockstep; complete observations "
              "provide implicit feedback (no exact action ACK)", flush=True)
    runtime = PolicyRuntime(config, backend, emit)
    rc = 0
    try:
        for event in node:
            kind = event["type"]
            if kind == "STOP":
                break
            if kind == "ERROR":
                runtime.fail_input("transport_error", "Dora transport reported an error")
                rc = 1
                break
            if kind != "INPUT":
                continue
            port = event["id"]
            metadata = event.get("metadata") or {}
            try:
                if port == "policy_command":
                    command = PolicyCommand.from_arrow(event["value"])
                    runtime.command(command.policy_id, command.command, command.inputs())
                elif port == "proprio_state":
                    state = JointState.from_arrow(event["value"])
                    if state.name != config.observation.state_names:
                        raise ValueError("state wire names/order must match configured state_names")
                    runtime.observe(port, state.position, metadata)
                elif port in config.observation.image_inputs:
                    runtime.observe(port, image_to_png(event["value"]), metadata)
                elif port == "benchmark_result":
                    runtime.benchmark_result()
                    if config.runtime.exit_on_benchmark_result:
                        break
                elif port != "tick":
                    raise ValueError(f"unexpected input port: {port}")
                runtime.tick()
            except (ValueError, TypeError, KeyError) as exc:
                runtime.fail_input("invalid_input", str(exc))
                rc = 1
            # Stay alive for benchmark_result/stop, allowing benchmark to persist failure.
            if runtime.failed:
                rc = 1
    finally:
        runtime.close()
    return rc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Standalone VLM action policy Dora node")
    parser.add_argument("--config", default=os.environ.get("POLICY_CONFIG"), help="policy YAML path (or POLICY_CONFIG)")
    parser.add_argument("--check-config", action="store_true", help="validate YAML without loading a model or Dora")
    parser.add_argument("--env-file", default=os.environ.get("VLM_ENV_FILE"), help="optional private JSON model defaults")
    parser.add_argument("--check-env", action="store_true", help="also validate provider settings offline")
    args = parser.parse_args(argv)
    if not args.config:
        parser.error("--config or POLICY_CONFIG is required")
    try:
        config = PolicyConfig.load(args.config)
        if args.check_env or not args.check_config:
            from .environment import load_environment

            load_environment(args.env_file, {
                "VLM_API_BASE": config.model.api_base_env,
                "VLM_API_KEY": config.model.api_key_env,
                "VLM_MODEL": config.model.model_name_env,
                "VLM_REASONING_EFFORT": config.model.effort_env,
            })
            if args.check_env and config.model.backend == "provider_api":
                from .backend import ProviderBackend

                ProviderBackend(config)  # Construction validates settings; it sends no request.
        if args.check_config or args.check_env:
            print(json.dumps({"policy_id": config.policy_id, "mode": config.mode, "valid": True}))
            return 0
        return run_node(config)
    except (ValueError, OSError, ImportError):
        # Config/provider initialization exceptions can contain secrets or source code.
        print("VLM policy startup failed; check configuration, dependencies and model environment.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
