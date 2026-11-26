from __future__ import annotations

import json
import os

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
    # Even a malformed legacy JSON must not be opened during startup.
    path = tmp_path / "obsolete.json"
    path.write_text("not valid JSON")
    monkeypatch.setenv("VLM_ENV_FILE", str(path))
    config = tmp_path / "policy.yaml"
    config.write_text("""model:
  api_base: http://127.0.0.1:1/v1
  api_key: dummy-secret-not-logged
  model_name: local-model
  reasoning_effort: ""
""")
    assert main(["--config", str(config), "--check-env", "--check-config"]) == 0
    output = capsys.readouterr()
    assert '"valid": true' in output.out
    assert "dummy-secret-not-logged" not in output.out + output.err


def test_normal_startup_ignores_legacy_file(tmp_path, monkeypatch):
    import vlm_action_policy.main as cli
    from vlm_action_policy.backend import ProviderBackend

    for name in NAMES:
        monkeypatch.delenv(name, raising=False)
    obsolete = tmp_path / "obsolete.json"
    obsolete.write_text("not valid JSON")
    monkeypatch.setenv("VLM_ENV_FILE", str(obsolete))
    config = tmp_path / "policy.yaml"
    config.write_text("""model:
  api_base: http://127.0.0.1:1/v1
  api_key: dummy-secret-not-logged
  model_name: local-model
  reasoning_effort: ""
""")
    called = []
    def run(config):
        client = ProviderBackend(config)
        called.append(client.model)
        return 0
    monkeypatch.setattr(cli, "run_node", run)
    assert main(["--config", str(config)]) == 0
    assert called == ["local-model"]
