# gpt6_vlm 在 libero_10 上的真实仿真测试

测试脚本：[scripts/eval_gpt6_vlm.py](../../scripts/eval_gpt6_vlm.py)。

## 推荐：与 gpt6 相同的 prepare → Dora → drive → collect 流程

现在可以像 `eval_gpt6.py` 一样，将任务、初始状态、重复次数和步数预算放在
`prepare` 阶段保存，再只用 `drive --work-dir` 启动测试。原来的 `run` 命令仍兼容。

区别在于：`gpt6` 的 drive 自己调用模型并操作五个工具；本 profile 的 drive
只提交 benchmark Session，**实际模型调用与动作循环由 dataflow 内的常驻策略节点完成**。
`serve: true` 意味着 Dora 启动后等待提交，不会立即跑 episode。

以下全部从 libero 仓库自身的根目录开始，与后文保留的父目录启动示例区分开。

**终端 A：准备环境与模型配置。** 可以复用 gpt6 已跑通的 gateway、benchmark、
LIBERO 资产和模型服务。模型 ID/API key 使用同样的 `VLM_*` 四字段私有 JSON；
本策略加载器额外要求私有 JSON 的权限为 `0600`。模型还需要支持图像输入和
JSON schema 结构化输出；gpt6 的函数工具调用跑通，不自动证明结构化动作输出可用。

```bash
export ROOT=/home/gx/python_project/gitlab/libero
export PATH="$HOME/.dora/bin:$HOME/.local/bin:$PATH"
cd "$ROOT"

uv sync --project "$ROOT/nodes/operator-vlm-action-policy" --frozen --python 3.12
export PY="$ROOT/nodes/operator-vlm-action-policy/.venv/bin/python"
export EVAL="$ROOT/scripts/eval_gpt6_vlm.py"

export GATEWAY_BIN="$HOME/.PhyAgentOS/forge_runtime/nodes/gateway/versions/gateway-1.1.0-linux-x86_64/gateway"
export BENCHMARK_BIN="$HOME/.PhyAgentOS/forge_runtime/nodes/libero_benchmark/versions/libero_benchmark-1.0.1-ubuntu20.1-linux-x86_64/libero_benchmark"

# 换成你已经可用的私有模型 JSON 的真实路径。
export MODEL_CONFIG=/absolute/path/to/private/model.json
chmod 600 "$MODEL_CONFIG"
```

私有 JSON 格式（实际文件放在结果目录与仓库之外）：

```json
{
  "VLM_API_BASE": "https://你的模型服务/v1",
  "VLM_API_KEY": "你的实际密钥",
  "VLM_MODEL": "服务中实际可用的模型ID",
  "VLM_REASONING_EFFORT": ""
}
```

非空 `VLM_*` 环境变量仍优先于 JSON；要固定使用 JSON 时，检查终端没有遗留的
其它模型配置。`prepare` 仅保存私有文件路径，不读取或复制密钥。
也可以不传 `--model-config`：直接 Dora 本地启动时复用启动终端的 `VLM_*` 环境变量，
或者使用策略启动器默认的 `${XDG_CONFIG_HOME:-$HOME/.config}/paos/libero/gpt6_vlm.json`。

**单集 20 步冒烟，终端 A：**

```bash
export RUN_DIR="$ROOT/work/gpt6_vlm_smoke_$(date +%Y%m%d_%H%M%S)"

"$PY" "$EVAL" prepare \
  --work-dir "$RUN_DIR" \
  --gateway-bin "$GATEWAY_BIN" --benchmark-bin "$BENCHMARK_BIN" \
  --model-config "$MODEL_CONFIG" --api-style chat_completions \
  --tasks 2 --init-states 0 --num-runs 1 --max-steps 20 --seed 0 \
  --port 19013 --gl egl

# 只检查配置，不调用模型、不启动仿真。
VLM_ENV_FILE="$MODEL_CONFIG" \
  "$ROOT/nodes/operator-vlm-action-policy/operator-vlm-action-policy.sh" \
  --config "$RUN_DIR/policy.yaml" --check-env --check-config

cd "$RUN_DIR"
dora run dataflow.yaml
```

如果服务需要 Responses，在 **prepare** 时指定 `--api-style responses`。
`--model-config`、`--api-style`、`--model-timeout`、`--max-output-tokens`
均在节点启动前配置，不能等到终端 B 的 drive 才更换。
测试时固定原 profile 的控制参数；当前源码为 H=4/M=4，prepare 不修改这些值。

**终端 B：提交保存好的批次。** 新终端中重新设置路径，将 RUN_DIR 换成 A 的实际输出。
终端 B 不需要再提供 API key，因为调用模型的是终端 A 启动的策略进程。

```bash
ROOT=/home/gx/python_project/gitlab/libero
PY="$ROOT/nodes/operator-vlm-action-policy/.venv/bin/python"
EVAL="$ROOT/scripts/eval_gpt6_vlm.py"
RUN_DIR='/终端A输出的实际运行目录'

# 可选：仅验证实时能力和保存的任务计划，不提交 episode。
"$PY" "$EVAL" drive --work-dir "$RUN_DIR" --check-only

# 开始真实模型 + LIBERO 执行；地址、任务、预算和 report 路径自动读取。
"$PY" "$EVAL" drive --work-dir "$RUN_DIR" --wall-timeout 3600
```

`--wall-timeout` 是 `--wait-timeout` 的别名，限制整个批次的客户端等待时间。
20 步用于贯通链路，不能作为模型成功率结论。正常结束后在终端 A Ctrl+C 回收节点。

**全部 10 个任务：** 冒烟后，在终端 A 新建另一轮目录，保持模型配置相同：

```bash
cd "$ROOT"
export RUN_DIR="$ROOT/work/gpt6_vlm_libero10_$(date +%Y%m%d_%H%M%S)"

"$PY" "$EVAL" prepare \
  --work-dir "$RUN_DIR" \
  --gateway-bin "$GATEWAY_BIN" --benchmark-bin "$BENCHMARK_BIN" \
  --model-config "$MODEL_CONFIG" --api-style chat_completions \
  --tasks 0-9 --init-states 0 --num-runs 1 --max-steps 520 --seed 0 \
  --max-total-episodes 10 --port 19013 --gl egl --record

cd "$RUN_DIR"
dora run dataflow.yaml
```

终端 B 更新实际 RUN_DIR，然后执行：

```bash
"$PY" "$EVAL" drive --work-dir "$RUN_DIR" --wall-timeout 43200
```

这是 10 任务 × 1 初始状态 × 1 次运行 = 10 episodes，覆盖任务但不是完整初始状态评测。
需要 100 集时，prepare 改为 `--init-states 0-4 --num-runs 2 --max-total-episodes 100`。
所有 ID 和预算仍会由实时 describe 校验，`all` 也只根据实时能力展开。
prepare 不调用模型；drive 前可以用 `drive --work-dir ... --dry-run` 离线预览。

**同一运行目录下的结果：**

```text
RUN_DIR/
  profile_manifest.json         来源 YAML 摘要、模型协议、H/M、批次计划
  evaluation_plan.json          prepare 保存的任务/init/run/seed/预算
  batch_state.json              是否已提交、invocation ID、客户端状态
  benchmark_results/*.json      benchmark 原始评分
  report/describe.json          实时能力
  report/arguments.json         实际提交参数（all 已展开）
  report/client_state.json      客户端状态
  report/gateway_result.json    gateway 终态原文
  report/benchmark_result.json  benchmark 原始 JSON 副本
  report/summary.json           成功率、成功/完成/总集数、主指标、耗时等
  report/episodes.csv           task/init/run/seed/success/termination/步数
  recordings/                  --record 请求的视频，需检查实际文件
  out/                         Dora 节点日志（依 Dora 版本）
```

像 gpt6 一样离线重新导出（Dora 停止后也可运行）：

```bash
"$PY" "$EVAL" collect --work-dir "$RUN_DIR"
cat "$RUN_DIR/report/summary.json"
```

离线导出验证实际提交的 episode 身份、seed、预算和完成数，不连接模型或 gateway。
它将 `result_source` 标为 `benchmark_file`，`tool_result_status` 为 null，
不伪造 gateway 的最终状态。在线完成时 `result_source=gateway_invocation`。
评分字段均复制 benchmark，`complete=true` 不表示任务全成功。

使用 `--work-dir` 的新流程每目录只允许一次批次提交；断连后换输出目录也不能重发。
`collect` 不会提交新批次。若没有 benchmark JSON，不能把未完成批次记成 0% 成功率。
旧 benchmark 忽略 policy_error，推理报错后可能一直等动作：查看终端 A 的策略日志，
必要时停止本轮 Dora，再用新的 prepare 目录重试。参见下文第 8 节的 invocation 收取方式。

需要实时画面时，prepare 加 `--viewer --viewer-port 19014`，然后查看本机的
`http://127.0.0.1:19014`；此时副本多一个只读节点，原三节点连线不变。详细说明见第 9 节。

下面保留显式 `run --gateway-url --output-dir` 的兼容用法与更多说明。

脚本复用本 profile 的三个节点及原有连线：

```text
gateway → libero_benchmark → 双视角图像、EEF 状态、任务指令 → operator-vlm-action-policy
                  ↑                                              │
                  └────────────────── action ────────────────────┘
```

benchmark 负责真实 LIBERO 环境、任务成功判定和评分；策略直接调用你配置的 VLM 服务。
不需要 `libero.policy` Session。脚本只控制 gateway，不替换环境、不生成模拟成功率。

## 1. 运行前准备

在工作区根目录（包含 `libero/` 和 `benchmark-libero/`）执行。

- 准备 `dora` CLI 0.4.1，并确保其所在目录在 PATH。通过 PAOS 启动则还需 `paos`。
- 宿主需要 `uv`、Python 3.12、可用的 EGL/OpenGL 环境和相应显卡驱动。
- LIBERO 的 bddl、init_states、assets 必须已配置到 `~/.libero/config.yaml`。
- 准备真实的 `gateway` 和 `libero_benchmark` 可执行程序。不要使用 smoke 的合成 benchmark。
- 按 [README 的模型配置说明](README.md#模型配置) 准备私有 JSON；模型名称由 `VLM_MODEL` 决定，profile 名称不选择模型。

```bash
uv sync --project libero/nodes/operator-vlm-action-policy --frozen --python 3.12
PY="$PWD/libero/nodes/operator-vlm-action-policy/.venv/bin/python"
EVAL="$PWD/libero/scripts/eval_gpt6_vlm.py"

# 默认私有文件；已有非空 VLM_* 环境变量仍会覆盖 JSON。
MODEL_CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}/paos/libero/gpt6_vlm.json"

# 离线检查，不调用真实模型、不启动仿真。
VLM_ENV_FILE="$MODEL_CONFIG" \
  libero/nodes/operator-vlm-action-policy/operator-vlm-action-policy.sh \
  --config libero/profiles/gpt6_vlm/policy.yaml --check-env --check-config
```

需要创建私有 JSON 时，只在本机编辑并设为 `600`，内容使用 README 中的四个 `VLM_*` 字段。
不要把凭据放进 dataflow、policy YAML 或测试结果目录。
`--check-env --check-config` 不验证认证、网络连通性或模型支持。

## 2. 创建隔离的运行目录

推荐直接以 Dora 启动工作区内 profile 的副本，避免误用 PAOS 中尚未更新的安装版本。
`prepare` 会固定 `libero_10`、替换可执行路径和结果路径、设置批次上限；保留原策略、控制器和三节点连线。
源 profile 文件保持不变。

本机已有的 binary 缓存结构如下；换机器或版本时替换路径：

```bash
GATEWAY_BIN="$HOME/.PhyAgentOS/forge_runtime/nodes/gateway/versions/gateway-1.1.0-linux-x86_64/gateway"
BENCHMARK_BIN="$HOME/.PhyAgentOS/forge_runtime/nodes/libero_benchmark/versions/libero_benchmark-1.0.1-ubuntu20.1-linux-x86_64/libero_benchmark"

# 每轮使用新的绝对路径，已存在的目录会被拒绝。
RUN_DIR="$PWD/work/gpt6_vlm_$(date +%Y%m%d_%H%M%S)"

"$PY" -I "$EVAL" prepare \
  --work-dir "$RUN_DIR" \
  --gateway-bin "$GATEWAY_BIN" \
  --benchmark-bin "$BENCHMARK_BIN" \
  --vlm-env-file "$MODEL_CONFIG" \
  --max-total-episodes 10 \
  --port 19013
```

`prepare` 不启动节点、不读取私有 JSON 内容、不调用模型。
原 profile 的批次上限为 1；副本设为 10 后，可先跑单集，再跑 10 任务抽样。
端口 19013 用于与默认 19003 区分，但仍应确认没有其他进程占用。

需要视频时，在 `prepare` 后面加 `--record`。录像是否可用取决于实际 benchmark
制品及编码环境，必须检查 `episodes[].metrics.video` 和对应文件。它是视频，不是动作/状态数值轨迹。
同一运行目录再次评测相同 task/init/run 可能覆盖旧视频，留证时每轮使用新的运行目录。

## 3. 启动三节点 dataflow

在终端 A 中，使用 prepare 输出的实际运行目录：

```bash
cd /absolute/path/to/work/gpt6_vlm_YYYYMMDD_HHMMSS
# 如 dora 不在 PATH，使用 /absolute/path/to/dora。
dora run dataflow.yaml
```

保留终端 A 查看节点日志；下面的评测命令在终端 B 执行。
`serve: true` 表示启动后等待 run 请求，此时没有动作是正常状态。
策略由 dataflow 自动启动，无需额外启动 policy Session。

## 4. 先做 task 2 的 20 步真实冒烟

终端 B 回到工作区根目录，重新设置 `PY`、`EVAL`：

```bash
PY="$PWD/libero/nodes/operator-vlm-action-policy/.venv/bin/python"
EVAL="$PWD/libero/scripts/eval_gpt6_vlm.py"

# 可先做纯离线参数预览：不会连接 gateway，也不会创建输出文件。
"$PY" -I "$EVAL" run \
  --tasks 2 --init-states 0 --max-steps 20 \
  --output-dir "$PWD/results/unused_dry_run" --dry-run

# 检查实时 suite、policy_id、任务/初始状态及预算，不提交 episode。
"$PY" -I "$EVAL" run \
  --gateway-url http://127.0.0.1:19013 \
  --tasks 2 --init-states 0 --max-steps 20 \
  --output-dir "$PWD/results/gpt6_vlm_preflight_$(date +%Y%m%d_%H%M%S)" \
  --check-only

# 真正调用 VLM 并执行 LIBERO 仿真：最多 20 个控制步。
"$PY" -I "$EVAL" run \
  --gateway-url http://127.0.0.1:19013 \
  --tasks 2 --init-states 0 --num-runs 1 \
  --max-steps 20 --seed 0 --wait-timeout 3600 \
  --output-dir "$PWD/results/gpt6_vlm_smoke_$(date +%Y%m%d_%H%M%S)"
```

20 步用于验证图像→推理→动作→结果链路，不足以评价任务表现。
当前 profile 预测 H=4、执行 M=4，20 步大约需 5 次模型请求；提前成功时更少。
批次正常完成且任务未成功时，脚本仍可返回 0；退出码 0 表示执行和导出通过，不表示任务成功。

## 5. 覆盖 libero_10 全部任务：每任务一个初始状态

确认冒烟正常后执行以下命令。保持同一个健康运行的 dataflow 即可；若策略曾报错，先停止并重启。

```bash
"$PY" -I "$EVAL" run \
  --gateway-url http://127.0.0.1:19013 \
  --tasks all --init-states 0 --num-runs 1 \
  --max-steps 520 --seed 0 --wait-timeout 86400 \
  --output-dir "$PWD/results/gpt6_vlm_10tasks_$(date +%Y%m%d_%H%M%S)"
```

脚本通过实时 describe 展开任务 ID，一次提交 10 个 episode，评分由 benchmark 统一计算。
520 步是当前 profile 的预算，不声明为外部排行榜的标准预算。
这覆盖 10 个任务，但每任务只取一个初始状态，属于抽样评测。
按当前 M=4，若全部跑满，约需 `10 × ceil(520/4) = 1300` 次模型请求；墙钟时间取决于服务延迟。
`--wait-timeout` 是整个批次的客户端等待时限，不是仿真步数上限。

要增加初始状态或重复次数，例如 `--init-states 0-4 --num-runs 2`，
共需 `10 × 5 × 2 = 100` 集；应先在新的运行目录 prepare，设置 `--max-total-episodes 100`，再启动新 dataflow。
`num_runs` 原样交给 benchmark，保留其 task/init/run_index 派生种子规则。
固定 seed 不保证远程模型采样及整个系统完全确定性。

## 6. 全初始状态评测

需要全量时，先 `describe`/`--check-only` 确认运行环境的初始状态数量。
`--init-states all` 使用所选任务共同可用的初始状态范围，不把 50 写死。
如果每任务恰好 50 个初始状态且 `num_runs=1`，10 个任务共 500 集。

在新目录用 `prepare --max-total-episodes 500`（实际数量不同时相应调整），启动该副本后：

```bash
"$PY" -I "$EVAL" run \
  --gateway-url http://127.0.0.1:19013 \
  --tasks all --init-states all --num-runs 1 \
  --max-steps 520 --seed 0 --wait-timeout 604800 \
  --output-dir "$PWD/results/gpt6_vlm_full_$(date +%Y%m%d_%H%M%S)"
```

按当前 M=4，500 集全部跑满约需 65000 次请求。建议先完成单集和 10 集测试，再决定全量预算。
若要与某个公开基准对比，还需对齐其步数、初始化和评测协议；仅覆盖所有初始状态不自动等于官方可比成绩。

## 7. 结果文件和解释

每个 `--output-dir` 必须是新目录，成功完成后包含：

| 文件 | 内容 |
| --- | --- |
| `describe.json` | 实时任务、初始状态、默认值、限制 |
| `arguments.json` | 实际提交的完整批次参数 |
| `client_state.json` | invocation ID、客户端状态、错误及可能的 stop 请求 |
| `gateway_result.json` | 原始 ToolResult，包括失败或 stopped 结果 |
| `benchmark_result.json` | benchmark 原始 JSON 的逐字节副本 |
| `summary.json` | 从 benchmark 原样摘取的成功率、主指标、步数、延迟、耗时和完成情况 |
| `episodes.csv` | 每集 task/init/run、任务描述、success、termination、步数、延迟和错误码 |

按 `episodes.csv` 的 `task_id` 筛选可查看分任务表现。
脚本不自行重算成功率，不跨 invocation 汇总指标，也不把环境错误当作任务失败重新打分。
`mean_policy_latency_ms` 是 benchmark 原有指标，不应直接解释为模型单次 HTTP 延迟。
`null` 延迟保留为缺失值。

- `status=succeeded`：批次流程完成；还要查看 `success_rate` 和 `episodes[].success`。
- `termination=timed_out`：达到步数预算而未成功；与客户端墙钟超时不同。
- `failed/stopped/partial`：保留已产出的结果并返回非零退出码，不能当完整评测。
- `valid_episodes` 少于计划数量或逐集出现 `error_code`：需检查环境或策略执行错误。
- 没有 `result_file` 或文件不可读：gateway 终态仍会保存，但无法完成原始结果/CSV 导出。

## 8. 超时、断连和收取已有结果

脚本提交 run 仅一次。若收到 invocation ID，会立即存到 `client_state.json`。
等待超时或被中断时，run 会尝试发送该 Session 的 stop；接受 stop 不证明已经停止。
旧 benchmark 不处理 `policy_error`，策略推理失败后可能一直等待 action；
此时需要在终端 A 停止 Dora，排查策略日志并重启，客户端 timeout 不能保证节点自行回收。

只收取已有 invocation，可使用：

```bash
"$PY" -I "$EVAL" collect \
  --gateway-url http://127.0.0.1:19013 \
  --invocation-id YOUR_SAVED_INVOCATION_ID \
  --wait-timeout 3600 \
  --output-dir "$PWD/results/gpt6_vlm_collect_$(date +%Y%m%d_%H%M%S)"
```

collect 不提交 run。Gateway/benchmark 重启或历史记录被清理后，不保证还能查询旧 invocation。
POST 在返回 invocation ID 之前断连也可能已被接收，此时应先核对现有运行状态和日志，不要直接重发。

如果使用原 PAOS 安装版本：

```bash
export PAOS_SKILL_PROFILE=gpt6_vlm
paos skill start libero --profile gpt6_vlm
paos skill status libero
```

脚本改用 `--gateway-url http://127.0.0.1:19003`。
原 profile 上限是 1 集，因此先做单集；多集需重新部署调整过上限的配置。
若结果路径为相对路径，加 `--benchmark-workdir /absolute/path/to/runtime/launch/profiles/gpt6_vlm`，
传节点实际 cwd，不是任意工作区目录。直接 Dora 的 prepare 副本使用绝对结果路径，无需该参数。

## 9. 测试时实时观看双相机

当前 benchmark 使用 `OffScreenRenderEnv`，不会弹出桌面窗口；无需将 EGL 改为 GLFW。
可在测试副本上加一个只读的 `libero_viewer` 节点，通过浏览器显示策略输入的主视角和腕部视角。
默认三节点 profile 不变，只有使用 `prepare --viewer` 的副本增加第四个节点。
预览不会发送动作，但图像订阅和 JPEG 编码会带来少量额外开销。

以下命令从 **libero 仓库自身的根目录**执行，与前面以父目录为起点的示例不同：

```bash
cd /home/gx/python_project/gitlab/libero
ROOT="$PWD"
PY="$ROOT/nodes/operator-vlm-action-policy/.venv/bin/python"
EVAL="$ROOT/scripts/eval_gpt6_vlm.py"
RUN_DIR="$ROOT/work/gpt6_vlm_live_$(date +%Y%m%d_%H%M%S)"

"$PY" -I "$EVAL" prepare \
  --work-dir "$RUN_DIR" \
  --gateway-bin "$HOME/.PhyAgentOS/forge_runtime/nodes/gateway/versions/gateway-1.1.0-linux-x86_64/gateway" \
  --benchmark-bin "$HOME/.PhyAgentOS/forge_runtime/nodes/libero_benchmark/versions/libero_benchmark-1.0.1-ubuntu20.1-linux-x86_64/libero_benchmark" \
  --vlm-env-file "${XDG_CONFIG_HOME:-$HOME/.config}/paos/libero/gpt6_vlm.json" \
  --max-total-episodes 10 --port 19013 \
  --viewer --viewer-port 19014

cd "$RUN_DIR"
dora run dataflow.yaml
```

浏览器打开 `http://127.0.0.1:19014`。第二个终端提交实际评测后才会出现首帧：

```bash
ROOT=/home/gx/python_project/gitlab/libero
"$ROOT/nodes/operator-vlm-action-policy/.venv/bin/python" -I \
  "$ROOT/scripts/eval_gpt6_vlm.py" run \
  --gateway-url http://127.0.0.1:19013 \
  --tasks 2 --init-states 0 --num-runs 1 \
  --max-steps 20 --wait-timeout 3600 \
  --output-dir "$ROOT/results/gpt6_vlm_live_$(date +%Y%m%d_%H%M%S)"
```

之后可用 `--tasks all --max-steps 520` 进行十任务测试，结果导出方式不变。
相机图像已由 benchmark 处理方向，预览不再次翻转、不改变分辨率（当前为 256×256）。
页面每 250 ms 查询最新图像，仿真只在控制步推进时更新画面；VLM 推理期间停留在上一帧属于正常现象。
页面显示接收帧数、上一帧距今时间、benchmark 和 policy 状态；接收帧数不等同于官方步数。
两路相机独立显示最新帧，不保证每次网页刷新严格配对，也不是可拖动视角的 MuJoCo 交互窗口。

若在远程服务器运行，预览仅绑定服务器回环地址。在本地电脑终端执行
`ssh -N -L 19014:127.0.0.1:19014 用户名@服务器地址`，然后本地浏览器打开上述地址。
已有 dataflow 需先停止，再以新 prepare 目录启动；单独运行 viewer 脚本不会自动订阅已有 Dora 图像流。
viewer 的可执行入口必须使用 `scripts/view_gpt6_vlm.sh`，参数为 `--port 19014`。
Dora 会解析可执行路径的软链接，直接将 `.venv/bin/python` 写为节点 path 可能变成系统 Python，
导致 `ModuleNotFoundError: No module named 'dora'`。启动器在进程内部调用策略虚拟环境，避免此问题。
可从仓库根目录执行 `scripts/view_gpt6_vlm.sh --check-env`，检查依赖而不连接 Dora。
PAOS 安装版本和本地源码可能不同，修改工作区不会更新已运行节点。

结束测试：直接 Dora 在终端 A 按 Ctrl+C；PAOS 使用 `paos skill stop libero`。

## 10. 本地回归

```bash
"$PY" -I -m pytest libero/tests/test_eval_gpt6_vlm.py libero/tests/test_view_gpt6_vlm.py -q
libero/nodes/operator-vlm-action-policy/.venv/bin/ruff check \
  libero/scripts/eval_gpt6_vlm.py libero/scripts/view_gpt6_vlm.py \
  libero/tests/test_eval_gpt6_vlm.py libero/tests/test_view_gpt6_vlm.py
```

本地回归使用回环 HTTP 服务与临时结果文件，不调用真实模型、不运行 LIBERO 物理仿真。
原有 `smoke_gpt6_vlm.py` 同样使用合成 adapter，只用于链路验证，不能产出真实任务成功率。
