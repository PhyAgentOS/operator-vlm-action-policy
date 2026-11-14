from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from vlm_action_policy.environment import load_environment
from vlm_action_policy.main import main

NAMES = {"VLM_API_BASE": "VLM_API_BASE", "VLM_API_KEY": "VLM_API_KEY",
         "VLM_MODEL": "VLM_MODEL", "VLM_REASONING_EFFORT": "VLM_REASONING_EFFORT"}


def private_file(tmp_path, values):
    path = tmp_path / "private.json"
    path.write_text(json.dumps(values))
    path.chmod(0o600)
    return path


def test_private_defaults_preserve_exported_overrides(tmp_path, monkeypatch):
    for name in NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("VLM_MODEL", "exported-model")
    monkeypatch.setenv("VLM_API_KEY", "")
    path = private_file(tmp_path, {"VLM_MODEL": "file-model", "VLM_API_KEY": "dummy-file-key"})
    load_environment(str(path), NAMES)
    assert os.environ["VLM_MODEL"] == "exported-model"
    assert os.environ["VLM_API_KEY"] == "dummy-file-key"


@pytest.mark.parametrize("values", [["invalid"], {"OTHER": "value"}, {"VLM_MODEL": 42}])
def test_private_configuration_rejects_invalid_values(tmp_path, values):
    with pytest.raises(ValueError):
        load_environment(str(private_file(tmp_path, values)), NAMES)


def test_private_configuration_rejects_world_readable_file(tmp_path):
    path = private_file(tmp_path, {"VLM_API_KEY": "dummy-key"})
    path.chmod(0o644)
    with pytest.raises(ValueError):
        load_environment(str(path), NAMES)


def test_offline_environment_check_does_not_infer(tmp_path, monkeypatch, capsys):
    import vlm_action_policy.main as cli

    for name in NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(cli, "run_node", lambda *_: pytest.fail("offline check started Dora"))
    path = private_file(tmp_path, {"VLM_API_BASE": "http://127.0.0.1:1/v1",
                                   "VLM_API_KEY": "dummy-secret-not-logged", "VLM_MODEL": "local-model"})
    config = Path(__file__).resolve().parents[1] / "examples/libero/policy.yaml"
    assert main(["--config", str(config), "--env-file", str(path), "--check-env", "--check-config"]) == 0
    output = capsys.readouterr()
    assert '"valid": true' in output.out
    assert "dummy-secret-not-logged" not in output.out + output.err
