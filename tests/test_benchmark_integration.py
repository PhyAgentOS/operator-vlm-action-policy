"""Exercise the actual BenchmarkRunner/PolicyRuntime contract without simulator dependencies."""
from __future__ import annotations

import importlib
from pathlib import Path

import numpy as np
import pytest
from forge_msgs import JointCommand, PolicyCommand
from test_runtime import Worker, actions, sent

from vlm_action_policy.config import PolicyConfig
from vlm_action_policy.runtime import PolicyRuntime


@pytest.fixture
def benchmark_modules(monkeypatch):
    root = next((parent / "benchmark-libero" for parent in Path(__file__).resolve().parents
                 if (parent / "benchmark-libero").is_dir()), Path("/nonexistent/benchmark-libero"))
    if not root.is_dir():
        pytest.skip("sibling benchmark-libero source is not available")
    monkeypatch.syspath_prepend(str(root))
    return tuple(importlib.import_module(name) for name in ("_core.runner", "_core.config", "_core.adapter"))


def test_actual_benchmark_runner_h_m_terminal_and_error_contract(benchmark_modules, tmp_path):
    runner_module, cfg_module, adapter_module = benchmark_modules
    config = PolicyConfig()
    outputs, worker = [], Worker()
    policy = PolicyRuntime(config, None, lambda *args: outputs.append(args), worker=worker)

    class Node:
        def __init__(self):
            self.messages = []

        def send_output(self, port, value, metadata=None):
            self.messages.append((port, value, metadata or {}))

    class Adapter:
        def __init__(self):
            self.steps = 0
            self.closed = False

        def state_joint_names(self):
            return config.observation.state_names

        def task_language(self, _):
            return "pick cup"

        def reset_episode(self, **kwargs):
            self.steps = 0
            return {}

        def to_state(self, obs):
            return np.zeros(8)

        def to_images(self, obs):
            return {port: np.zeros((2, 2, 3), dtype=np.uint8) for port in config.observation.image_inputs}

        def step(self, action):
            self.steps += 1
            assert action.shape == (7,)
            return adapter_module.StepOutcome(obs={}, reward=0.0, done=self.steps == 3, success=self.steps == 3)

        def close(self):
            self.closed = True

    node, adapter = Node(), Adapter()
    cfg = cfg_module.BaseBenchmarkConfig(task_ids=[0], init_state_ids=[0], num_runs=2,
        policy_id=config.policy_id, correlated_observations=True, result_dir=str(tmp_path), max_steps=10)
    runner = runner_module.BenchmarkRunner(node, cfg, adapter, log=lambda _: None)

    def feed_messages():
        while node.messages:
            port, value, metadata = node.messages.pop(0)
            if port == "policy_command":
                command = PolicyCommand.from_arrow(value)
                policy.command(command.policy_id, command.command, command.inputs())
            elif port == "proprio_state":
                policy.observe(port, [0.] * 8, metadata)
            elif port in config.observation.image_inputs:
                policy.observe(port, b"png", metadata)
            elif port == "benchmark_result":
                policy.benchmark_result()

    runner.policy_command("start")
    runner.advance()
    feed_messages()
    assert len(worker.requests) == 1
    seen_actions = 0
    for step in range(3):
        if not policy.pending:
            worker.complete(actions())
            policy.tick()
        output = sent(outputs, "action")[seen_actions]
        seen_actions += 1
        assert runner.accepts_action(output[2])
        runner.on_action(JointCommand(name=config.action.layout, position=output[1]), output[2])
        feed_messages()
    assert len(runner.result.episodes) == 1 and runner.result.episodes[0].success
    assert runner.plan_index == 1
    assert not policy.history
    assert policy.binding.epoch != sent(outputs, "action")[0][2]["epoch"]
    assert len(worker.requests) == 3
    worker.complete(error="BackendFailure")
    policy.tick()
    error = sent(outputs, "policy_error")[-1][1]
    import json

    import pyarrow as pa
    assert runner.on_policy_error(pa.array([json.dumps(error)]))
    assert runner.finished and runner.result.status == "failed"
    assert len(runner.result.episodes) == 2 and not runner.result.episodes[-1].success
    assert adapter.closed
    assert Path(runner.result_path).is_file()
