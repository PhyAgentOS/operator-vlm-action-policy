English | [简体中文](README_zh.md)

# operator-vlm-action-policy

A persistent internal Dora Node that maps task instructions, images and robot state
to bounded **EEF or joint action chunks**. It reuses the existing
[operator-vlm-policy](https://github.com/PhyAgentOS/operator-vlm-policy) HTTP service.
The Node owns observation synchronization, async inference, chunk consumption,
pose servo, reset invalidation and execution-feedback history.

## Node, Endpoint and Tool API

| Item | Implementation |
|---|---|
| Production Nodes | 1: `operator-vlm-action-policy run --config policy.yaml`; [entrypoint](src/operator_vlm_action_policy/node.py) |
| Inputs | `tick`, `policy_command`, `proprio_state`, configured `image/*`, `benchmark_result`; optional strict `observation` |
| Outputs | `action` (Forge-compatible JointCommand), `action_chunk`, `policy_state`, `policy_error` |
| Endpoint / Tool / HTTP listener | 0 / 0 / 0; this is a dataflow policy |
| External inference | Existing generic service `/v1/infer:wait`; no model weights/credentials in this Node |
| Example deployment | 2 Dora Nodes + existing HTTP service; optional Gateway makes 3 Dora Nodes |
| Optional benchmark Tools | `benchmark.controller / describe` Query, `/ run` Session, supplied by benchmark-libero; deployment Tool IDs `vlm_libero.benchmark.describe`, `vlm_libero.benchmark.run` |

## Install and run

```bash
uv sync --frozen --all-extras --group dev
uv run operator-vlm-action-policy validate --config examples/libero/policy.yaml
uv run operator-vlm-action-policy schema --config examples/libero/policy.yaml
uv run operator-vlm-action-policy run --config examples/libero/policy.yaml
```

`run` requires a Dora-launched environment. Start the generic VLM service first;
its existing model/effort settings remain authoritative. Provider credentials stay
there. Optional service authentication uses `VLM_SERVICE_TOKEN` (never a literal
key in tracked configuration).

Use [LIBERO dataflow.yaml](examples/libero/dataflow.yaml), replacing executable
paths and the benchmark checkout path. Run it from `examples/libero`. Both node
runtimes and the Dora CLI must match the pinned Dora **0.4.1** line. LIBERO,
robosuite and benchmark assets are separate installation prerequisites.

## Actions

| Space | Model output | Execution |
|---|---|---|
| `eef_delta` | xyz metres + world rotation-vector radians + gripper | Normalize to LIBERO OSC, one row per observation |
| `eef_pose` | xyz metres + unit quaternion xyzw + gripper | Feedback servo until tolerance or step limit |
| `joint_position` | N joint radians + gripper | Absolute joint targets with joint/step limits |

EEF profiles currently require world-frame LIBERO OSC delta control. The
[joint example](examples/joint/policy.yaml) requires real joint observations and a
matching joint-position controller. **The default LIBERO seven-dimensional action
is EEF control, not seven joint angles.** No IK or collision planner is included.

Generate H actions and consume only the configured first M. Every native action
requires a fresh complete observation. `tick` never repeats an action without that
credit. Reset, instruction changes, pause and stop invalidate old requests/queues.
Generic inference is stateless with bounded acknowledged execution history in the
policy; context never leaks across episodes.

## Design, Skill and validation

- [Complete design and flowcharts](docs/DESIGN.md), [中文方案](docs/DESIGN_zh.md): every Node I/O, action contracts, states, dataflow, evaluation and integration boundaries.
- [Source Skill template](examples/skill): three-Node Tool profile, manifest, Gateway bindings and launchers. PAOS installation/Session acceptance is pending runtime validation.
- [Developer guide](DEVELOPING.md), [中文开发指南](DEVELOPING_zh.md).

`legacy_libero` collects fresh separate streams and assumes ordered single-writer
lockstep. It cannot guarantee atomic camera/state synchronization or eliminate all
cross-port stale-frame races. `observation_v1` requires a producer extension with
explicit episode/step identity; current upstream LIBERO does not publish it.

Tests cover controlled inference, physical contracts, fresh-observation credits,
reset cancellation, pose feedback and joint limits. They do not establish a real
VLM LIBERO success rate, actual simulator acceptance or physical robot safety.
Policy errors fail the flow; interrupted batches require explicit failure accounting.

Apache-2.0: [LICENSE](LICENSE), [NOTICE](NOTICE), [third-party notices](THIRD_PARTY_NOTICES.md).
See [security](SECURITY.md), [contributing](CONTRIBUTING.md), [publication review](OPEN_SOURCE_AUDIT.md).
