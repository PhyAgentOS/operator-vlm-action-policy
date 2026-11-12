from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from .contracts import PolicyConfig


def main():
    parser = argparse.ArgumentParser(prog="operator-vlm-action-policy")
    parser.add_argument("command", choices=["run", "validate", "schema"])
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    cfg = PolicyConfig.model_validate(yaml.safe_load(Path(args.config).read_text()))
    if args.command == "schema":
        print(json.dumps(cfg.output_schema(), indent=2))
    elif args.command == "validate":
        print(f"Valid: {cfg.policy_id}, {cfg.action_space}, {cfg.transport}")
    else:
        from .node import run

        run(cfg)


if __name__ == "__main__":
    main()
