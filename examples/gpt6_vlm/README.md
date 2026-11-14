# gpt6_vlm：三节点 VLM 控制

真实 `libero_10` 仿真测试与结果导出见 [TESTING.md](TESTING.md)，配套脚本为 `scripts/eval_gpt6_vlm.py`，支持隔离准备、单集冒烟、多任务批次和收取已有结果。

推荐使用与 `gpt6` 一致的入口：`prepare --work-dir ... --tasks ... --max-steps ...`
→ `dora run dataflow.yaml` → `drive --work-dir ...` → `collect --work-dir ...`。
模型 JSON 和 API 协议在 prepare 时指定，drive 只提交 benchmark 批次；结果默认在运行目录的 `report/`。

测试时实时观看主视角和腕部视角，可使用 `prepare --viewer --viewer-port 19014`；浏览器预览启动步骤见 [TESTING.md 第 9 节](TESTING.md#9-测试时实时观看双相机)。

本 profile 使用 `operator-vlm-action-policy` 直接调用多模态模型，读取 LIBERO 主视角、腕部视角和 EEF 状态，生成物理单位动作，再转换成 LIBERO OSC 增量输入。模型名称由 `VLM_MODEL` 指定，profile 名称不会自动选择服务中的某个模型。

运行时恰好三个节点：

| 节点 | 职责 |
| --- | --- |
| `gateway` | 提供 `libero.benchmark.describe` 和 `libero.benchmark.run` 两个工具 |
| `libero_benchmark` | 场景、观测、动作执行、官方成功判定与结果落盘 |
| `operator-vlm-action-policy` | 模型推理、动作校验、H/M 队列与控制器适配 |

主视角、腕部视角、状态和 `policy_command` 从 benchmark 直达策略；`action` 与 `policy_error` 返回 benchmark。gateway 不参与逐步动作执行。策略没有 ToolEndpoint，也无需先启动 `libero.policy` Session。

## 准备可执行程序

本 profile 的 `required_binaries` 为 `gateway` 和 `libero_benchmark`，由 PAOS 的 runtime binary provisioning 提供；策略源码随 Skill 放在 `nodes/operator-vlm-action-policy/`。dataflow 固定使用：

- `${FORGE_RUNTIME_BIN}/gateway`
- `${FORGE_RUNTIME_BIN}/libero_benchmark`
- `${PAOS_SKILL_ROOT}/nodes/operator-vlm-action-policy/operator-vlm-action-policy.sh`

策略入口为 `.sh` 启动器，保留的同名无扩展名可执行文件只是兼容 wrapper。宿主 PATH 需要 `uv` 和可用的 Python 3.12；启动器按节点锁文件准备依赖环境。可在工作区根目录预先准备：

```bash
uv sync --project libero/nodes/operator-vlm-action-policy --frozen --python 3.12
```

本 profile 使用 `synchronization: legacy_lockstep`、`require_identity: false`，兼容已安装的旧 `libero_benchmark-1.0.1-ubuntu20.1`，无需更新 benchmark。`benchmark.yaml` 显式设置 `correlated_observations: false`，当前源码据此发送旧格式消息，旧二进制忽略该配置键。全局制品锁和三个节点路径保持原样。本 profile 没有新增本地模型权重依赖；目标系统的依赖和 ABI 仍需单独验收。

Legacy 模式假设只有一个观测生产者，每个端口保持发送顺序，每一步恰好发布一份完整状态和两路图像。策略按各端口顺序配对这些消息，用本地合成的 epoch/step 管理生命周期；发送动作后的下一组完整观测作为隐式确认。这无法证明某个精确 action 的 ACK，也无法识别跨端口延迟的旧 epoch 消息；单端口丢帧、重复消息或跨批次积压会破坏配对假设。

启动钩子只调用 bundled `.sh` 启动器的 `--config ... --check-env --check-config`，离线检查模型配置与 policy YAML，无需 `LIBERO_BENCHMARK_BIN` 或 `VLM_ACTION_POLICY_BIN`。PAOS 不向 hook 注入 runtime bin，hook 不探测或启动 benchmark；制品兼容性需在部署时另行确认。

## 模型配置

推荐把服务配置放在 Skill 之外的私有 JSON 文件，默认路径为 `${XDG_CONFIG_HOME:-$HOME/.config}/paos/libero/gpt6_vlm.json`。示例仅含占位值，使用前在本机填写真实服务配置，并将文件权限设为 `600`：

```json
{
  "VLM_API_BASE": "https://your-provider.example/v1",
  "VLM_API_KEY": "replace-with-your-api-key",
  "VLM_MODEL": "your-multimodal-model",
  "VLM_REASONING_EFFORT": ""
}
```

启动器读取 `${VLM_ENV_FILE:-${XDG_CONFIG_HOME:-$HOME/.config}/paos/libero/gpt6_vlm.json}`，现有**非空**环境变量覆盖 JSON 默认值；`VLM_REASONING_EFFORT` 可留空或填写服务支持的值。若 API base、key 和 model 已完整导出，JSON 文件可以不存在。不要将真实 key 或服务配置写入 policy YAML、dataflow、Skill 归档或测试目录。

PAOS/Dora 已运行的 daemon 可能保留旧环境，当前 shell 的新 exports 不保证传给节点；默认私有 JSON 路径由 launcher 在节点进程内直接读取，部署时更可靠。dataflow 不包含 `VLM_API_*`、`VLM_MODEL` 或 reasoning effort 占位符，因此解析 YAML 无需先导出模型变量。若 daemon 已有非空模型环境覆盖值，应在受控部署流程中清理后重启，使 JSON 默认值生效。

仅直接启动节点时，可以用完整 exports 代替私有文件：

```bash
export VLM_API_BASE='https://your-provider.example/v1'
export VLM_MODEL='your-multimodal-model'
read -rsp 'VLM API key: ' VLM_API_KEY; printf '\n'
export VLM_API_KEY
export VLM_REASONING_EFFORT=''
libero/nodes/operator-vlm-action-policy/operator-vlm-action-policy.sh \
  --config libero/profiles/gpt6_vlm/policy.yaml --check-env --check-config
```

`VLM_API_BASE` 是 base，不包含末尾的 `/chat/completions` 或 `/responses`。`policy.yaml` 默认 `api_style: chat_completions`；若服务使用 Responses 接口，改为 `responses`。需要支持图像输入和当前配置的严格 JSON Schema 输出；若服务不支持结构化输出，可显式设置 `structured_output: false`，本地动作校验仍然执行。

当前 profile 预测 `H=4`、执行 `M=4`，所有 4 行先校验，每发送一行动作后等待下一组完整观测作为隐式确认；执行 4 行后重新观测规划。该确认依赖上述 Legacy 顺序假设，不验证精确 action ACK。模型输出世界坐标系米/弧度增量，适配器按平移 `0.05 m`、旋转 `0.5 rad` 缩放。控制器配置必须与这些数值一致。

私有 JSON、节点进程环境，以及 Dora/PAOS 的运行配置和日志均按凭据文件管理。

Skill 打包使用 `libero/scripts/package_skill.py`：`--refresh` 更新已索引文件的摘要并加入 bundled 策略源码；`--output /absolute/path/to/new-skill.tar.gz` 仅从校验通过的 allowlist 创建新归档。该脚本排除 `.venv`、`dist`、`build`、缓存和本地环境/私有配置；私有 JSON 始终保留在 Skill 外。不要直接递归归档开发目录。

## 启动与调用

安装包含本次改动的本地 Skill 后：

```bash
export PAOS_SKILL_PROFILE=gpt6_vlm
paos skill start libero --profile gpt6_vlm
paos skill status libero
```

运行顺序：

1. 等待 `libero.benchmark.describe` 和 `libero.benchmark.run` 两个工具 ready。
2. 调用 `libero.benchmark.describe`，确认实时任务、初始状态和限制。
3. 调用一次 `libero.benchmark.run`，例如 `{ "task_ids": [2], "init_state_ids": [0], "num_runs": 1, "max_steps": 520, "seed": 0 }`。
4. 保留 invocation ID，查询该 Session 的状态和结果直至终态；以 benchmark 结果文件为准。
5. 可以继续启动下一批；结束后执行 `paos skill stop libero`。

配置保留旧 `gpt6` 文件中的实际默认值：`libero_10`、task 2、init 0、520 步。默认每批最多 1 episode、最多 1000 步；需要多 episode 时显式调整 `max_total_episodes`。不根据旧文件注释将 suite 擅自改成 `libero_spatial`。

benchmark 使用 `serve: true`，启动后等待工具调用，**不会自动跑任务**。策略设置 `exit_on_benchmark_result: false`，每个正常结束的批次清空上下文后继续常驻。当前 benchmark 源码支持 `policy_error`，可结束失败批次并落盘；**旧安装二进制不处理 `policy_error`**，策略推理、动作校验或观测超时报错后，benchmark 可能一直等待 action。此时须手动停止运行（`paos skill stop libero`），检查日志并排除原因后重新启动；旧二进制下不保证自动结束失败批次、落盘或下一次 run 恢复。

直接用 Dora 时，先通过 runtime binary provisioning 准备含 gateway 和已有 benchmark 的 `FORGE_RUNTIME_BIN`，并将 `PAOS_SKILL_ROOT` 设为已安装 Skill 的绝对路径；保留默认私有 JSON 配置。在本目录运行：

```bash
dora run dataflow.yaml
```

gateway 使用端口 19003，与其他 LIBERO profile 共用；同一端口只启动一个实例。

## 排查首帧后没有 action

启动 run 后，benchmark 必须主动 reset 并发布 step 0 的状态和两路图像，然后才等待 action；不需要先发送空动作。仅启动 profile 未调用 run 时，benchmark 等待工具请求属于正常空闲。

若已出现 `episode 1/1 开始` 却一直无动作，先查看策略节点日志，确认 `legacy_lockstep` 已生效、任务指令已到达，且完整状态、主视角、腕部视角都已发布。旧 benchmark 不发送 `episode_id/epoch/obs_id/step_id/instruction_version` 是预期行为。若看到 `missing_identity`，应检查是否误用了严格模式的 policy 配置。若策略已报告错误，旧二进制不会处理 `policy_error`，须手动停止运行后排查。不要注入空动作绕过观测等待；策略日志输出状态、错误码与固定诊断类别，不打印指令、图像、模型凭据或服务端错误原文。

### 已进入 INFER 后出现 inference_error

`state=INFER` 表示完整观测已组装并已提交推理请求；`inference_error` 表示后端调用或响应解析失败，单凭这个错误码无法确定具体原因。更新后的策略在错误码后输出一行脱敏诊断，例如：

```text
[vlm_policy] error=inference_error
[vlm_policy] model backend failed (provider_http_401)
[vlm_policy] state=ERROR
```

stdout 和 stderr 的合并顺序可能不同。诊断类别含义如下；这些是排查方向，不是对某次运行原因的确认：

| 类别 | 排查方向 |
| --- | --- |
| `provider_http_400` | 服务拒绝请求；核对该服务支持的接口、模型、图像、token 参数与 JSON Schema，不能仅据此认定是结构化输出问题 |
| `provider_http_401` / `provider_http_403` | 核对凭据是否有效、模型和接口访问权限是否足够，以及环境变量是否覆盖私有 JSON |
| `provider_http_404` | 核对 API base、接口路径和模型名称；API base 不包含 `/chat/completions` 或 `/responses` |
| `provider_http_429` | 核对服务的限流、配额和余额 |
| 其他 `provider_http_<状态码>` | 按服务对应状态排查；节点不输出服务端错误正文 |
| `connection_timeout` / `tls_error` / `dns_error` / `connection_failed` | 分别检查超时、TLS 证书、域名解析或网络连接；不自动关闭证书校验 |
| `output_truncated` | 服务报告输出达到 token 限制；核对输出预算与推理配置 |
| `model_refusal` | 服务返回拒绝或内容过滤结果 |
| `response_incomplete` / `unexpected_finish_reason` | 响应未正常完成；检查服务是否支持当前 API 协议 |
| `malformed_response` / `invalid_action_json` | 外层响应格式异常，或动作内容不是可解析的 JSON 对象；动作维度和范围仍由后续校验检查 |
| `response_too_large` | 响应超过节点的 4 MiB 上限 |
| `backend_exception` | 未分类异常，包括本地插件异常；异常原文不会进入日志 |

修改工作区源码不会更新已安装的 Skill 或已运行的进程。需要先用 `paos skill stop libero` 停止旧运行，通过本地 Skill 包更新安装，再重新启动 profile 并调用 run。`--check-env --check-config` 仅离线检查配置，不验证认证、连通性或模型支持。不要把私有 JSON、请求图像或服务端错误原文粘贴到公开日志中。

### 第二轮推理出现 output_truncated

第一轮成功不保证下一轮也能在相同预算内完成。`output_truncated` 与本地 `inference_timeout` 是不同失败；已经确认实际加载的输出预算与时限后，应检查服务的结束标记和用量，不能直接归因于旧的超时设置。

截断诊断现在会带上可用的数字统计。以下仅为示例，并非真实运行数据：

```text
[vlm_policy] model backend failed (output_truncated; request_max_output_tokens=8192, input_tokens=1200, output_tokens=8192, reasoning_tokens=8180, visible_output_chars=24)
```

- `request_max_output_tokens`：本节点请求的预算，不证明服务实际采用了相同上限。
- `input_tokens`、`output_tokens`、`reasoning_tokens`：服务返回的用量。Chat Completions 的 `prompt_tokens` / `completion_tokens` 和 Responses 的 `input_tokens` / `output_tokens` 在这里使用统一名称。
- `visible_output_chars`：可见输出的字符数，不是 token 数。不输出模型内容或推理原文。
- 服务未提供的用量不会显示，不能将缺失值当作 0；异常的字段类型和值会被过滤。

每次收到可解析的服务响应，还会输出一行 `[vlm_provider]` JSON，记录请求/响应模型标识、实际发送的预算参数名、推理强度参数、结束标记和数字用量。未提供的用量以 `null` 表示；标识做格式限制和 key 过滤，日志不含 endpoint、请求图像、动作正文或推理原文。可对照第一轮成功与第二轮截断的记录，检查服务是否返回了相同模型以及请求参数是否一致。

某些推理模型的输出预算同时覆盖推理和可见答案。因此，只要求 4×7 个动作数值，也不能据此认定 8192 一定足够。若 `reasoning_tokens` 接近输出总量且可见内容很少，可以在服务和模型明确支持时，尝试把私有 JSON 中的 `VLM_REASONING_EFFORT` 设为 `low`。本节点只有在该值非空时才发送推理强度参数；留空表示省略参数，不表示关闭推理。现有非空环境变量会覆盖 JSON。

若统计显示预算耗尽，可在确认服务输出上限和调用成本后，单独提高 `max_output_tokens` 做对比；若输出用量明显低于请求预算仍被截断，则进一步核对服务侧限制和接口实现。不要同时修改预算、时限和推理强度，以免无法判断哪项变化起作用。仅增加时限不能补全一个已经返回截断标记的响应。

节点继续拒绝截断响应，丢弃上一轮未执行的 H−M 行，不自动重试或解析半截动作。旧 benchmark 仍需手动停止并重新启动。统计补丁只改善诊断，不保证真实模型能完成 20 步；本地回归不调用真实服务。

## 本地验证

在工作区根目录：

```bash
libero/nodes/operator-vlm-action-policy/operator-vlm-action-policy.sh \
  --config libero/profiles/gpt6_vlm/policy.yaml --check-env --check-config
libero/nodes/operator-vlm-action-policy/.venv/bin/python -I -m pytest libero/tests/test_gpt6_vlm_profile.py -q
```

测试检查三节点连线、两个工具、bundled launcher、空 `required_environment`、模型环境变量名和 Legacy 配置，并使用实际 `BenchSession`、`BenchmarkRunner` 和 `PolicyRuntime` 验证无身份消息下的跨批次复用。本地合成 epoch 只验证策略内部隔离。失败后下一批恢复的参数化用例使用**支持 `policy_error` 的当前 benchmark 源码**，不代表旧安装二进制支持错误恢复。hook 测试只使用临时 `VLM_ENV_FILE`，不读取用户默认配置、不探测 benchmark；运行前需有 PATH 中的 uv 和 bundled launcher 的依赖环境。

真实 gateway/Dora 三节点烟雾测试可用以下命令复现，gateway 路径需替换为已安装的 1.1.0 可执行文件：

```bash
libero/nodes/operator-vlm-action-policy/.venv/bin/python -I libero/scripts/smoke_gpt6_vlm.py \
  --gateway-bin /absolute/path/to/gateway \
  --dora /absolute/path/to/dora
```

脚本在临时目录准备本 profile，替换 gateway 端口、节点路径与结果目录，并先移除原 model 配置，再重建固定 `VLM_*` 引用和本地测试值；不复制生产 key 或私有 JSON，显式使用不存在的测试 `VLM_ENV_FILE` 隔离默认配置。默认策略入口为 bundled `.sh`。benchmark 使用当前源码的实际 `run_serve_tool`、`correlated_observations: false` 与合成 adapter，策略使用实际节点。测试预期经过 gateway 工具查询和 Session 调用，连续跑两批、每批 3 步，共 4 次双图模型 HTTP 请求，并检查策略本地合成 epoch/step 和结果落盘。这些身份来自策略内部，不证明 benchmark 的精确 action ACK。HTTP 服务仅监听回环地址，退出时回收测试进程，不调用真实模型服务。

2026-11-13 截断统计补丁后：策略测试与 profile 测试共 129 项通过，Ruff 检查通过。新增覆盖 Chat Completions / Responses 用量、异常或缺失 usage、截断统计的日志传递，以及第一轮动作成功后第二轮截断时不再执行动作。全部为本地模拟异常或回环 HTTP 测试，未调用真实模型、运行物理仿真或证明完成 20 步。

2026-11-13 推理错误诊断补丁后：策略测试 106 项、profile 测试 5 项（共 111 项）通过，Ruff 检查通过。新增测试覆盖 HTTP 状态、网络错误、拒绝/截断/异常响应、4 MiB 响应限制，以及实际推理线程到节点日志的脱敏错误传递；测试只使用模拟异常与回环 HTTP 服务，没有调用真实模型服务，也未确认某次部署的推理失败原因。

2026-11-13 Legacy 兼容修改后：策略测试 68 项、profile 测试 5 项通过；真实 gateway/Dora 三节点烟雾测试通过，连续两批、每批 3 步，共 4 次双图本地模型 HTTP 请求。验证目录为 `/tmp/libero-gpt6-vlm-smoke-uslecamw`。烟雾测试使用当前 benchmark 源码关闭关联身份的兼容模式及合成 adapter，未调用真实模型服务或运行旧二进制的物理仿真。

2026-11-12 的历史验证记录为严格身份模式：三节点烟雾测试连续两批、每批 3 步、共 4 次双图本地 HTTP 请求通过，当时策略节点 61 项、profile 5 项、benchmark 回归 130 项测试通过。该记录不验证本次 Legacy 配置。

合成模型与 adapter 的成功标记不代表 LIBERO 任务成功率；源码测试不验证已锁定的旧 benchmark 二进制。实际 VLM 服务、物理仿真和成功率仍需在部署环境验收。
