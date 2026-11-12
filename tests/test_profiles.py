from pathlib import Path

import yaml

from operator_vlm_action_policy.contracts import PolicyConfig

ROOT = Path(__file__).resolve().parents[1]


def test_profiles_validate_and_all_dataflow_sources_resolve():
    for path in ROOT.glob("examples/**/policy.yaml"):
        PolicyConfig.model_validate(yaml.safe_load(path.read_text()))
    for path in ROOT.glob("examples/**/dataflow.yaml"):
        graph = yaml.safe_load(path.read_text())
        nodes = {node["id"]: node for node in graph["nodes"]}
        for node in graph["nodes"]:
            for value in node["inputs"].values():
                source = value["source"] if isinstance(value, dict) else value
                if source.startswith("dora/"):
                    continue
                provider, port = source.split("/", 1)
                assert port in nodes[provider]["outputs"], (path, source)


def test_skill_tools_and_policy_identity_match():
    root = ROOT / "examples/skill"
    manifest = yaml.safe_load((root / "skill.yaml").read_text())
    gateway = yaml.safe_load((root / "profiles/libero/gateway.yaml").read_text())
    assert set(manifest["required_tools"]) == {s["tool_id"] for s in gateway["tools"]["specs"]}
    benchmark = yaml.safe_load((root / "profiles/libero/benchmark.yaml").read_text())
    policy = yaml.safe_load((root / "profiles/libero/policy.yaml").read_text())
    assert benchmark["policy_id"] == policy["policy_id"]
    assert benchmark["serve"]
