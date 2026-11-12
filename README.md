English | [简体中文](README_zh.md)

# operator-vlm-action-policy

**Design proposal only. No approved implementation or runnable Node is provided.**

Plan a standalone persistent internal VLM action-policy Node. It accepts instruction,
images and robot state, performs model inference within its own runtime boundary,
and produces EEF or joint action chunks. It does not depend on the existing
`operator-vlm-policy` service.

- [Complete design and diagrams](docs/DESIGN.md)
- [中文完整方案](docs/DESIGN_zh.md)
- [Proposed LIBERO dataflow.yaml](examples/libero/dataflow.yaml)
- [Proposed policy configuration](examples/libero/policy.yaml)
- [Proposed joint-output configuration](examples/joint/policy.yaml)

The documents define planned Node inputs/outputs, action contracts, lifecycle,
benchmark integration and Skill packaging. Configuration files are design examples;
executable paths refer to future artifacts. No implementation, model evaluation,
Dora integration test or installed Skill acceptance is claimed by this proposal.

Default LIBERO actions are seven-dimensional EEF controls. Joint output needs a
matching controller and genuine joint observations. EEF-to-joint IK, if selected,
belongs to an explicit control adapter.

Apache-2.0: [LICENSE](LICENSE), [NOTICE](NOTICE).
