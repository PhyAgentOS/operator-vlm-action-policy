English | [简体中文](README_zh.md)

# operator-vlm-action-policy

**Design proposal only. No approved implementation or runnable Node is provided.**

A standalone persistent internal action-policy Node is planned with two scenarios:

| Scenario | Inputs | Output | Business Nodes |
|---|---|---|---|
| A: VLM-only | instruction, obs_state, obs_image | single-step final_action from a generated chunk | benchmark + VLM action policy |
| B: VLA + VLM | VLA candidate chunk plus the same instruction/observations | single-step final_action after retention/refinement | benchmark + VLA candidate + the same VLM action policy |

The Node owns its model backend and inference, directly accessing a provider API
or an in-process local model. It does not depend on operator-vlm-policy service.
Chunk horizons and dimensions are configurable with strict action semantics.
Only the final VLM action Node writes to the environment.

- [Complete design](docs/DESIGN.md), [中文完整方案](docs/DESIGN_zh.md): separate flowcharts, Node I/O/responsibilities, state/sequence, important parameters and full dataflows for both scenarios.
- Scenario A: [dataflow](examples/libero/dataflow.yaml), [policy](examples/libero/policy.yaml), [benchmark](examples/libero/benchmark.yaml).
- Scenario B: [dataflow](examples/vla_vlm/dataflow.yaml), [final policy](examples/vla_vlm/policy.yaml), [VLA candidate](examples/vla_vlm/vla.yaml), [benchmark](examples/vla_vlm/benchmark.yaml).
- [Joint-output draft](examples/joint/policy.yaml): requires genuine joint state and a matching controller.

All configuration keys and new candidate/request/feedback ports are proposals.
The existing VLA runner needs extensions; strict observation identity and immediate
benchmark abort handling also require integration work. YAML paths name future
artifacts. No implementation, model tests or installed Skill acceptance is claimed.

Default LIBERO consumes a single-step seven-dimensional vector: six EEF controls and one gripper command.
It does not directly accept an H×D chunk or seven joint angles. Changing dimension
alone cannot change frames, units, control type or gripper semantics.

Apache-2.0: [LICENSE](LICENSE), [NOTICE](NOTICE).
