English | [简体中文](CONTRACTS_zh.md) · [Back to design](DESIGN.md)

# Interface details for implementation planning

These are proposed contracts, not implemented interfaces. See the [main design](DESIGN.md) and complete YAML drafts in examples.

## Actions and time

- Configure candidate horizon H_vla, final horizon H_final, executed prefix M and row width D separately. Initially validate fixed shapes; B keep/bounded-refine requires H_vla ≥ H_final ≥ M ≥ 1.
- Bind D to space, layout, units, frame, joint ordering and gripper convention. Checkpoint-native VLA H/D constrain configuration; define truncation/resampling explicitly.
- Model and native action dimensions may differ through a declared adapter. For example an 8D pose can map to 7D OSC; changing a dimension setting alone performs no conversion.
- Separate model-statistic denormalization from controller scaling. Convert B candidates to canonical physical units before review; avoid dimensionless values, double scaling and frame mismatches.
- dt is the environment period. Absolute targets need not be reached in one step; bound multi-step servo and account in native control steps. B initially uses equal-period EEF delta or joint actions.
- Validate translation/joint corrections against step and absolute bounds; compose rotations explicitly on SO(3); preserve the gripper by default. Numeric bounds do not establish collision safety.

## Correlation

Observations carry episode_id, epoch, obs_id, step_id and instruction_version. Images and state share identity. Chunks add chunk_id, source_obs_id, start_control_step, control_dt_s, action semantics and normalization_profile.

A legacy_lockstep is a restricted prototype. Production A/B require common benchmark metadata or an observation envelope, plus action identity checks. Independent latest image/state values do not prove synchronization.

LIBERO's existing 8D state is EEF position(3), rotation vector(3) and fingers(2). Default native action is six EEF controls plus one gripper. Joint output requires actual joint state and a matching controller. Any EEF→joint IK uses an explicit adapter.

## B internal streams

| Message | Purpose |
|---|---|
| candidate_command | Forward instruction/reset/stop to the VLA policy_id, distinct from the final actor ID |
| vla_policy_state | Confirm reset/readiness for the current episode/epoch before candidate requests |
| candidate_request | Bind request ID, observation identity, scheduled start, horizon and deadline; one live request per replan |
| vla_action_chunk | Return matching request/identity/semantics without independent execution |
| execution_feedback | After acknowledgement, report final action ID, candidate index, actual final command and acknowledgement observation for VLA history |
| decision_trace | Preserve candidate, keep/refine/replan, corrections, final output and rejection/fallback reasons |

These need VLA-runner extensions; they are not assumed existing. See [scenario B dataflow](../examples/vla_vlm/dataflow.yaml). Benchmark commands address the final policy, which forwards directed commands to VLA.

## Queues, cancellation and errors

- A complete fresh observation grants one action credit. Only the VLM Node owns the final queue and environment output.
- Reset/instruction/pause/stop invalidate requests, candidates and final queues. Late uncancellable inference is discarded. Context is episode-scoped and contains only acknowledged execution.
- Start with serial lockstep. Future async prefetch must commit only to unexecuted steps with atomic queue replacement.
- Timeout/invalid actions default to evaluation abort. Any later valid-candidate fallback requires explicit configuration, age checks and reporting; it is not fully VLM-reviewed execution.
- Upstream benchmark needs an immediate policy-failure/abort finalization contract to avoid hanging while awaiting actions and to persist outcomes. Drafts invent no existing abort port.
- Preserve incomplete/failed episodes in reporting. Official benchmark scoring owns success; model completion is not a success label.

## Skill and versions

Each profile contains dataflow, policy and benchmark settings; B adds VLA settings. Optional Gateway binds benchmark.controller describe Query/run Session. No new policy ToolEndpoint is proposed.

Pin compatible Dora/Forge/messages/controllers together. Model settings belong directly to the action Node; keep credentials outside packages and exclude weights/datasets.
