English | [简体中文](README_zh.md)

# operator-vlm-action-policy

A persistent Dora node implementing section 2, “Option A · Standalone VLM Policy,” of DESIGN_zh.html. Task instructions, dual-camera images, and proprioceptive state enter the same process. The node calls a VLM API directly or invokes an in-process local model plugin to generate an H×D action chunk. After validation, it sends actions to the benchmark one step at a time, waiting for an environment acknowledgment after each action. After executing M steps, it discards the remaining H−M steps and replans.

This version implements only `standalone`; `vla_conditioned` is rejected at startup. It neither calls the existing operator-vlm-policy service nor adds a ToolEndpoint. The default environment pins `dora-rs==0.4.1`, `forge-msgs==1.2.0`, and Python 3.12; dependencies are locked in `uv.lock`.

## Running from source

```bash
cd libero/nodes/operator-vlm-action-policy
./operator-vlm-action-policy.sh --config examples/libero/policy.yaml --check-config
```

The launcher requires `uv` and Python 3.12 on the host, prepares dependencies with `uv sync --frozen`, and preserves the caller's working directory. `operator-vlm-action-policy` remains a compatibility entry point for the same launcher.

`gpt6_vlm` can read private local model configuration from `${XDG_CONFIG_HOME:-$HOME/.config}/paos/libero/gpt6_vlm.json`, or from a file specified through `VLM_ENV_FILE` / `--env-file`. The JSON keys are `VLM_API_BASE`, `VLM_API_KEY`, `VLM_MODEL`, and optionally `VLM_REASONING_EFFORT`. File permissions should be 0600; existing nonempty environment variables take precedence. `--check-env --check-config` performs local checks only and does not call the model. This private file is not distributed with the node or Skill.

Before calling the model, you can also set the values supplied by your deployment environment in the current shell; do not put these values in YAML files or archives:

```bash
export VLM_API_BASE='https://your-provider.example/v1'
export VLM_API_KEY='your-key'
export VLM_MODEL='your-vision-capable-model'
# Set only if supported by the model:
export VLM_REASONING_EFFORT='low'
```

`model.api_style` supports `chat_completions` and `responses`. The base URL is the API prefix; the program appends `/chat/completions` or `/responses`, respectively. JSON Schema structured output is enabled by default. If a compatible service does not support it, set `structured_output: false`; all local action validation remains in effect. Chat requests use `max_completion_tokens`, while Responses requests use `max_output_tokens`. The model must support images and the corresponding request fields.

`examples/libero/dataflow.yaml` is the reference example for strict observation correlation. Before starting it, change the benchmark's `path` to a locally built executable that includes the optional benchmark-libero protocol extensions introduced for this integration. Then run from the example directory:

```bash
cd examples/libero
dora run dataflow.yaml
```

The example connects `policy_error` to the benchmark and enables `correlated_observations: true`. Older benchmarks, or benchmarks that have not been rebuilt with these extensions, do not support this capability. All nodes must use the same Dora/Forge message versions. The benchmark environment supplies LIBERO data, the MuJoCo/robosuite environment, and GPU/offscreen rendering.

## Inputs and outputs

| Direction | Port | Message |
| --- | --- | --- |
| Input | `policy_command` | Forge PolicyCommand; target policy_id, command, and inputs_json |
| Input | `proprio_state` | Forge JointState.position; transport labels are validated against state_names, while state_semantics describes the values to the model |
| Input | `image/main`, `image/second` | Forge Image; ports and camera names are configured through image_inputs |
| Input | `tick` | Dora timer; checks inference completion, timeouts, and scheduling without granting permission to send an action |
| Input | `benchmark_result` | Benchmark completion event; success is determined by the benchmark |
| Output | `action` | Forge JointCommand.position; adapted to the environment's native single-step control values |
| Output | `action_chunk` | Single-element Arrow string array containing JSON: the full chunk in canonical units, chunk_id, identity, layout, units, H/M, and inference time |
| Output | `policy_state` | The same JSON transport, containing logical state and identity |
| Output | `policy_error` | The same JSON transport, containing policy_id, code, message, and observation identity; includes action_id when an error concerns an action awaiting acknowledgment |

Strict identity consists of `episode_id, epoch, obs_id, step_id, instruction_version`. The epoch is a new UUID string for each episode, obs_id=`epoch:step_id`, step_id starts at 0, and instruction_version starts at 1. Lifecycle command inputs carry the same five values. Action metadata preserves the source observation identity and adds a unique action_id, chunk_id, and row_index. All state/image metadata for the next step carries the same `last_action_id` as acknowledgment.

Strict mode assembles camera images and state into an observation only when all five identity fields match exactly. Each complete observation grants permission to send exactly one action. Messages may arrive out of order across input ports, so observations arriving before reset with the matching identity are held in bounded buffers and consumed after reset binds that identity. Old episodes and instruction versions are not mixed in. Missing acknowledgments, type errors, invalid actions, and inference/feedback timeouts all publish errors; the benchmark immediately records the current episode as failed and ends the batch.

`legacy_lockstep + require_identity:false` provides compatibility with older benchmarks and is the default mode for the Skill's `gpt6_vlm` profile. Each reset generates a new UUID epoch inside the policy. Complete state and dual-camera observations trigger the first action; subsequent complete observations implicitly acknowledge the previous action. The policy replans after executing M rows. Observations arriving before reset are held in bounded per-port buffers. This mode requires a single serial benchmark, ordered messages on each port, and exactly one message per port per step. Without identity metadata, it cannot prove an exact action ACK or reliably detect stale frames, duplicate frames, or mismatches across ports. The policy can isolate late inference results, but cannot reconstruct sender identity for old messages. Older binaries do not handle `policy_error`, so a run must be stopped manually after an inference or feedback failure. The separate `examples/libero` example retains strict mode for the updated benchmark.

## Action semantics and safety boundaries

The default is `eef_delta/world/D=7`: the first three dimensions are in meters, the next three form a rotation vector in radians, and the final dimension controls the gripper (-1 open, +1 closed). World-frame rotation deltas are composed by left multiplication as `delta_R @ current_R`, matching the LIBERO OSC profile. The `libero_osc_delta` adapter scales translation by a 0.05 m profile and rotation by a 0.5 rad profile into native [-1,1] commands. Use the actual profile of the deployed controller as the authority for these values. The model returns canonical physical units; do not normalize them beforehand.

Every response must contain exactly H rows, each with exactly D finite numeric values. All H rows are validated before the first step executes, including the unused tail. Out-of-range values cause failure rather than silent clipping. Physical bounds checks do not provide collision detection or reachability guarantees.

A `joint_position` pass-through adapter is also available, but requires explicit configuration of actual joint names, joint-ordered state_names/state_semantics, D−1 joints plus the gripper, and per-dimension lower and upper bounds. LIBERO's default 8-dimensional EEF state must not be interpreted as seven joint angles. Absolute EEF poses, implicit IK, and switching joint controllers are outside the scope of this version.

The benchmark's `joint1..joint7,gripper` names are historical transport labels. The actual state consists of 3 EEF position values, 3 axis-angle values, and 2 finger positions. This node handles that difference explicitly through separate state_names and state_semantics.

## Lifecycle and context

Supported commands are `start, set_instruction, reset_scene, reset, pause, resume, stop`. The benchmark's common sequence is `start → set_instruction → reset_scene → complete observation`. reset_scene preserves the running state; reset clears state and returns to READY. pause, stop, and instruction changes invalidate queued actions and in-flight inference. Resuming after pause requires another reset_scene and a complete fresh observation to reestablish the environment's position. reset clears execution history; model context includes only the most recent max_executed_history steps acknowledged by the environment.

There is a single background inference worker, so model calls do not block Dora event handling. Local inference that cannot be canceled occupies the worker until it returns, but results from an old generation are always rejected. Exceeding the wait budget causes failure instead of spawning additional uncontrolled threads. tick_ms is not a guarantee of model inference frequency.

One-shot evaluation exits after receiving benchmark_result by default. To support multiple runs against a benchmark with `serve:true`, set `runtime.exit_on_benchmark_result:false`. The node then remains in DONE/STOPPED, waiting for the next start/reset.

## In-process model plugins

```yaml
model:
  backend: local_python
  local_factory: your_package.your_module:create
```

`create(config)` returns an object exposing `infer(request)->dict`. The request contains instruction, Observation (state, PNG bytes for each camera, and identity), and executed_history. The response must be `{"actions": [[...], ...]}` and satisfy the same physical action contract. The deployment environment supplies plugins and model weights. When running from source, install the plugin into the same .venv. For frozen artifacts, explicitly include the plugin and its dependencies at build time; do not assume external Python plugins are automatically included in the PyInstaller bundle. The test smoke_backend is only a fixed-action stub and is not intended for real control.

## Testing and packaging

```bash
uv run --frozen pytest -q
uv run --frozen ruff check --select E4,E7,E9,F,I src tests scripts
# Three-step protocol test using real Dora/Arrow; does not run LIBERO physics:
uv run --frozen python scripts/prepare_smoke.py /tmp/vlm-policy-smoke
# The generated dataflow preserves the virtual environment through a script
# entry point, avoiding a switch to the system interpreter when Dora resolves
# Python symlinks.
dora run /tmp/vlm-policy-smoke/dataflow.yaml
# PRM Linux x86_64 directory_tar_gz:
bash scripts/build_bundle.sh
```

The directory bundle follows paos-resource-manager/docs/node-registration.md:

```text
operator-vlm-action-policy-0.1.0-linux-x86_64.tar.gz
└── operator-vlm-action-policy/
    ├── operator-vlm-action-policy      # 0755; standalone PyInstaller executable
    ├── _internal/                      # Python and dependency runtimes; valid relative symlinks within the bundle
    ├── config/policy.yaml
    ├── LICENSE
    └── NOTICE
```

`verify_bundle.py` checks the root directory, executable entry-point permissions, member count, extraction limits, and relative links, rejects hard links and special files, and reports the archive's SHA-256 and size. Registration metadata should use `node_type:operator`, `artifact_type:directory_tar_gz`, `entrypoint:operator-vlm-action-policy`, and the corresponding version/platform/arch. Source files and artifacts are generated locally and are not automatically uploaded or published.

The build reads the version from `pyproject.toml` and writes the archive plus a `.sha256` file to `dist/release/` by default. It includes `LICENSE` and `NOTICE`, validates the frozen executable's configuration outside the source tree, and refuses to overwrite an existing archive. `node.json` contains the registration metadata for version `0.1.0` on Linux x86_64; keep it outside the archive. See [Node packaging and registration](docs/node-registration.md) (Chinese) for file purposes, upload instructions, and version management.

Local HTTP and fixed-model protocol tests validate requests/responses and runtime contracts. They do not establish real VLM control quality or LIBERO success rates; those require evaluation with the deployed model in the benchmark environment.

Licensed under Apache-2.0; see LICENSE and NOTICE.
