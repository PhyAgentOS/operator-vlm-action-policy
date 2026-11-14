"""Deterministic in-process backend for transport smoke tests ONLY, never a real policy."""
from __future__ import annotations


class SmokeBackend:
    def __init__(self, config):
        self.config = config

    def infer(self, request):
        return {"actions": [[0.001, 0, 0, 0, 0, 0, -1]] * self.config.action.prediction_horizon}


def create(config):
    return SmokeBackend(config)
