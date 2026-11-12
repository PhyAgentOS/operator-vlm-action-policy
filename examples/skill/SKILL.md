---
name: vlm-libero-benchmark
description: Run LIBERO evaluation batches using the resident VLM action policy and retrieve official results.
---

# VLM LIBERO benchmark

This is a source template, not a validated installed Skill artifact. Before
release, validate its manifest expansion, pinned Gateway/benchmark compatibility
and a real Session roundtrip in the target PAOS runtime.

Use `vlm_libero.benchmark.describe` to discover actual suites, task/init-state
ranges and limits. Start `vlm_libero.benchmark.run` as a Session for the agreed
plan; poll status, then read the terminal result. Stop takes effect at an episode
boundary. Acceptance or successful batch execution is not task success.

The runtime owns the observation/action loop. Do not inject additional movement
Tools, object ground truth, or evaluator predicates into an evaluation. Preserve
model, effort, prompt, control profile and episode plan for comparison. Report
success and failure counts alongside wall-clock time and model consumption.

Preconditions: compatible Dora 0.4.1 CLI and node environments, LIBERO assets,
separately running generic VLM service, writable output workspace, configured
model credentials in that service. Never package credentials or model weights.
The template uses EEF delta output; joint output needs a matching environment.

If the policy/flow fails, record an interrupted batch and retain scheduled
incomplete episodes. Do not silently remove them from the denominator. Retrieve
available reports and explain the failure before starting a new batch.
