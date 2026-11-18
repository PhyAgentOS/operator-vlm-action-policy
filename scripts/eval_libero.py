#!/usr/bin/env python3
"""Run the LIBERO evaluation client with THIS checkout's policy and profile.

The LIBERO repository supplies its benchmark/gateway driver and camera viewer.
Only the profile and policy launcher are selected here, so a second policy copy
inside that repository cannot silently replace the source being tested.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, add_help=False)
    parser.add_argument("--libero-root", default=os.environ.get("LIBERO_ROOT"),
                        help="LIBERO integration checkout containing scripts/eval_gpt6_vlm.py")
    parser.add_argument("--legacy-observations", action="store_true",
                        help="Prepare without exact episode/action ACKs (old benchmarks only)")
    args, remaining = parser.parse_known_args(argv)
    if not args.libero_root and any(flag in remaining for flag in ("--help", "-h")):
        parser.print_help()
        print("\nCommands: prepare, drive, run, collect.\n"
              "Set --libero-root or LIBERO_ROOT for the integration command help.")
        return 0
    if remaining and remaining[0] == "prepare" and not args.legacy_observations:
        # Across Dora input ports a new episode's images may precede its reset.
        # Exact identities prevent those frames from advancing an old M-step chunk.
        if "--strict-observations" not in remaining:
            remaining.append("--strict-observations")
    if not args.libero_root:
        parser.error("--libero-root or LIBERO_ROOT is required")
    integration = Path(args.libero_root).expanduser().resolve()
    driver_path = integration / "scripts/eval_gpt6_vlm.py"
    if not driver_path.is_file():
        parser.error("LIBERO checkout must contain scripts/eval_gpt6_vlm.py")
    spec = importlib.util.spec_from_file_location("libero_evaluation_driver", driver_path)
    if spec is None or spec.loader is None:
        parser.error("cannot load LIBERO evaluation driver")
    driver = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(driver)
    driver.PROFILE = ROOT / "examples/gpt6_vlm"
    driver.POLICY = ROOT / "operator-vlm-action-policy.sh"
    # An imported driver must not derive the default benchmark from this repo.
    driver.TEST_BENCHMARK = integration / "build/benchmark-policy-errors/libero_benchmark"
    original_prepare = driver.prepare

    def prepare_current_checkout(options):
        result = original_prepare(options)
        if result == 0:
            import yaml

            stage = Path(options.work_dir).expanduser().absolute()
            policy_path = stage / "policy.yaml"
            config = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
            # Check unsupported external-driver flags before any node can start.
            sys.path.insert(0, str(ROOT / "src"))
            try:
                from vlm_action_policy.config import PolicyConfig

                PolicyConfig.from_mapping(config)
            finally:
                sys.path.pop(0)
            flow_path = stage / "dataflow.yaml"
            flow = yaml.safe_load(flow_path.read_text(encoding="utf-8"))
            policy_node = next(node for node in flow["nodes"] if node["id"] == "operator-vlm-action-policy")
            policy_node["env"]["POLICY_PREPARED_MANIFEST"] = str(stage / "profile_manifest.json")
            flow_path.write_text(yaml.safe_dump(flow, sort_keys=False), encoding="utf-8")
        return result

    driver.prepare = prepare_current_checkout
    result = driver.main(remaining)
    if result == 0 and "prepare" in remaining:
        print("Use this checkout's client for drive/collect:")
        print(f"  {sys.executable} {Path(__file__).resolve()} --libero-root {integration} "
              "drive --work-dir YOUR_RUN_DIR")
    return result


if __name__ == "__main__":
    sys.exit(main())
