# operator-vlm-action-policy

实现 DESIGN_zh.html 第 2 点「方案 A · VLM 独立策略」的常驻 Dora 节点。任务指令、双相机图像和本体状态进入同一进程，由节点直接调用 VLM API，或调用进程内本地模型插件；生成 H×D 动作片段，校验后逐步向 benchmark 发送动作。每个动作等待环境回执，执行 M 步后丢弃剩余 H−M 步并重新规划。

本版只实现 `standalone`。`vla_conditioned` 会在启动时被拒绝。没有调用已有 operator-vlm-policy 服务，也没有新增 ToolEndpoint。默认固定 `dora-rs==0.4.1`、`forge-msgs==1.2.0`、Python 3.12；uv.lock 锁定依赖。

## 源码运行

```bash
cd operator-vlm-action-policy
./operator-vlm-action-policy.sh --config examples/gpt6_vlm/policy.yaml --check-config
```

启动器要求宿主提供 `uv` 和 Python 3.12，通过 `uv sync --frozen` 准备依赖，并保留调用方工作目录。`operator-vlm-action-policy` 保留为同一启动器的兼容入口。

在 `policy.yaml` 的 `model` 段直接填写 `api_base`、`api_key`、`model_name` 和 `reasoning_effort`。启动器和 Python 入口不再读取默认私有 JSON、`VLM_ENV_FILE` 或 `--env-file`。显式 YAML 值优先；字段为 null 或省略时，仍兼容对应的 `*_env` 环境变量。`reasoning_effort: ""` 明确禁用推理强度。`--check-env --check-config` 只做本地检查，不请求模型。

使用旧的环境变量配置时，需省略或设为 null 对应的 YAML 显式字段，再设置：

```bash
export VLM_API_BASE='https://your-provider.example/v1'
export VLM_API_KEY='your-key'
export VLM_MODEL='your-vision-capable-model'
# 模型支持时再设置：
export VLM_REASONING_EFFORT='low'
```

`model.api_style` 支持 `chat_completions` 和 `responses`。base 是 API 前缀，程序会分别追加 `/chat/completions` 或 `/responses`。默认使用 JSON Schema 结构化输出；兼容服务不支持时可将 `structured_output: false`，本地动作校验仍全部保留。Chat 请求使用 `max_completion_tokens`，Responses 请求使用 `max_output_tokens`。模型必须支持图像与相应请求字段。

`examples/gpt6_vlm/dataflow.yaml` 使用现有 LIBERO benchmark wire 协议，配置 `correlated_observations: false`，并通过 legacy lockstep 模式兼容已安装的 `libero_benchmark-1.0.1-ubuntu20.1`。配置好部署路径后，在示例目录执行：

```bash
cd examples/gpt6_vlm
dora run dataflow.yaml
```

严格身份/ACK 协议需要 benchmark 扩展后才能设置 `correlated_observations: true`；这些扩展不属于已安装的 1.0.1 制品，不能对该二进制启用 strict 模式。所有节点使用匹配的 Dora/Forge 消息版本。LIBERO 数据、MuJoCo/robosuite 环境和 GPU/离屏渲染由 benchmark 环境提供。

## 输入与输出

| 方向 | 端口 | 消息 |
| --- | --- | --- |
| 输入 | `policy_command` | Forge PolicyCommand；目标 policy_id、command、inputs_json |
| 输入 | `proprio_state` | Forge JointState.position；按 state_names 校验传输标签，按 state_semantics 提供给模型 |
| 输入 | `image/main`、`image/second` | Forge Image；由 image_inputs 配置端口与相机名称 |
| 输入 | `tick` | Dora timer；检查推理完成、超时及调度，不产生动作额度 |
| 输入 | `benchmark_result` | benchmark 完成事件；成功判据来自 benchmark |
| 输出 | `action` | Forge JointCommand.position；适配为环境原生的单步控制量 |
| 输出 | `action_chunk` | 单元素 Arrow string array，内含 JSON：完整规范单位片段、chunk_id、身份、布局、单位、H/M、推理耗时 |
| 输出 | `policy_state` | 同样的 JSON 传输，含逻辑状态与身份 |
| 输出 | `policy_error` | 同样的 JSON 传输，含 policy_id、code、message、观测身份；待确认动作出错时附 action_id |

严格身份为 `episode_id, epoch, obs_id, step_id, instruction_version`，其中 epoch 是每 episode 新建的 UUID 字符串，obs_id=`epoch:step_id`，step_id 从 0 起，instruction_version 从 1 起。生命周期命令的 inputs 也携带这五个值。动作 metadata 原样携带源观测身份，并添加唯一 action_id、chunk_id、row_index。下一步所有状态/图像的 metadata 携带相同 `last_action_id` 作为确认。

严格模式只把五字段完全相同的相机和状态拼成观测；一个完整观测只授予一个动作额度。输入端口之间可乱序，因此 reset 前到达的同身份观测会在有界缓冲中暂存，reset 绑定后再读取；旧 episode 和旧指令版本不会混入。缺少确认、类型错误、非法动作和推理/反馈超时均发布错误，由 benchmark 立即记录当前集失败并结束该批次。

`legacy_lockstep + require_identity:false` 用于兼容当前安装的 `libero_benchmark-1.0.1-ubuntu20.1`，`gpt6_vlm` 使用此模式。每次 reset 在策略内部生成新 UUID epoch；完整状态和双相机观测触发第一条动作，后续完整观测作为上一动作的隐式确认，执行 M 行后重新推理。该模式要求单一串行 benchmark、各端口保序、每步每端口恰好一条消息；没有身份时无法证明精确 action ACK，也无法区分所有旧帧。因此收到 pause 后当前策略实例会失败关闭，resume/reset/start 不会继续发动作；需要停止并重新启动整个 dataflow。strict 扩展目前只存在于修改中的 benchmark 源码树，尚无已发布的配套版本。

## 动作语义与安全边界

默认 `eef_delta/world/D=7`：前三维米、接着三维旋转向量弧度、最后一维夹爪（-1 张开、+1 闭合）。世界系旋转增量按 `delta_R @ current_R` 左乘组合，与 LIBERO OSC profile 对齐。`libero_osc_delta` 适配器用平移 0.05 m、旋转 0.5 rad 的 profile 缩放为原生 [-1,1] 命令。数值以部署控制器的实际 profile 为准；模型返回的是规范物理单位，不能预先再归一化。

每次必须返回恰好 H 行、每行恰好 D 个有限数值；所有 H 行都在执行首步前校验，包括不会执行的尾部。超范围数值逐维限幅：超过上界取上界，低于下界取下界；动作块、实际下发和执行历史均使用限幅后的值。物理范围检查不包含碰撞检测或可达性保证。

也提供 `joint_position` 透传适配器，但必须显式配置实际关节名字、按关节排列的 state_names/state_semantics、D−1 个关节与夹爪、逐维上下界，以及每动作维一个 `max_step_delta`（按对应单位）。状态语义必须包含关节和 `gripper`。整段动作会在首步发出前校验：首行以源观测为基准，后续行以上一行限幅后的目标为基准，将目标限制在物理边界与 `max_step_delta` 允许范围的交集内；交集为空时拒绝整段。不能把 LIBERO 默认 8 维 EEF 状态当成七个关节角。EEF 绝对位姿、隐式 IK 与关节控制器切换不在本版范围。

benchmark 的 `joint1..joint7,gripper` 是历史传输标签，实际状态语义是 EEF 位置 3、轴角 3、双指位置 2。本节点用独立 state_names 与 state_semantics 显式处理该差异。

## 生命周期与上下文

支持 `start, set_instruction, reset_scene, reset, pause, resume, stop`。benchmark 的常见序列为 `start → set_instruction → reset_scene → 完整观测`。reset_scene 保留运行状态；reset 清理并回到 READY。pause/stop/换指令会作废队列和在途推理。严格身份模式中，暂停后恢复只接受相对暂停前最后观测前进的 step 或新 epoch；相同/更早身份会继续等待，避免重放可能过期的状态。旧版无身份模式暂停后不能证明帧的新旧，因此会失败关闭并要求重启整个 dataflow。reset 清空执行历史，模型上下文只记录已获得回执的最近 max_executed_history 步。

后台只有一个推理 worker，Dora 事件处理不会被模型调用阻塞。不能取消的本地推理占用该 worker 直到返回，但旧 generation 的结果始终拒绝；等待超预算会失败，不创建更多失控线程。tick_ms 不是模型频率承诺。

一次性评测默认收到 benchmark_result 后退出。对接 benchmark `serve:true` 的多次 run 时，设 `runtime.exit_on_benchmark_result:false`，节点保留在 DONE/STOPPED，等待下一次 start/reset。

## 进程内模型插件

VLA 接入沿用同一动作入口，暂不定义策略组合逻辑。候选动作使用规范物理单位，封装为 `candidate_id`、`source`、完整源观测身份、动作空间/坐标系/布局/单位及 H×D `actions`；候选必须匹配当前观测身份并通过同一整段校验，再由事件循环统一排队，最终只从 `action` 端口发出。每个最终动作分配 `action_id`，benchmark 在下一完整观测的 `last_action_id` 中回执；策略将该回执对应的候选 ID、最终动作、执行观测和结果状态作为反馈交给 VLA。未确认动作的状态必须标记为 `unknown`，不得作为已执行结果输入。该候选输入/反馈传输端口尚未实现，本契约是后续实现的兼容边界。

```yaml
model:
  backend: local_python
  local_factory: your_package.your_module:create
```

`create(config)` 返回具有 `infer(request)->dict` 的对象。request 包含 instruction、Observation（state、各相机 PNG bytes、identity）、executed_history。返回格式必须为 `{"actions": [[...], ...]}`，遵守相同物理动作契约。插件和模型权重由部署环境提供。源码运行时安装插件到同一 .venv；冻结制品需在构建阶段显式加入插件及其依赖，不能假定外部 Python 插件自动进入 PyInstaller 包。测试用 smoke_backend 只是固定动作桩，不用于真实控制。

## 测试与打包

```bash
uv run --frozen pytest -q
uv run --frozen ruff check --select E4,E7,E9,F,I src tests scripts
# 真实 Dora/Arrow 三步协议测试；不运行 LIBERO 物理仿真：
uv run --frozen python scripts/prepare_smoke.py /tmp/vlm-policy-smoke
# 生成的 dataflow 通过脚本入口保留虚拟环境，避免 Dora 解析 Python 软链接
# 时切到系统解释器。
dora run /tmp/vlm-policy-smoke/dataflow.yaml
# PRM Linux x86_64 directory_tar_gz：
bash scripts/build_bundle.sh
```

目录包结构遵循 paos-resource-manager/docs/node-registration.md：

```text
operator-vlm-action-policy-0.1.0-linux-x86_64.tar.gz
└── operator-vlm-action-policy/
    ├── operator-vlm-action-policy      # 0755；PyInstaller 独立程序
    ├── _internal/                      # Python 与依赖运行库，合法包内相对软链接
    ├── config/policy.yaml
    ├── LICENSE
    └── NOTICE
```

`verify_bundle.py` 检查根目录、入口执行位、成员数、展开限制、相对链接、禁止硬链接/特殊文件，并输出整包 SHA-256/大小。登记元数据应使用 `node_type:operator`、`artifact_type:directory_tar_gz`、`entrypoint:operator-vlm-action-policy`、本次 version/platform/arch。源码文件和制品在本地生成，不会自动上传或发布。

构建脚本从 `pyproject.toml` 读取版本，默认将归档和 `.sha256` 文件输出到 `dist/release/`，随包包含 `LICENSE` 和 `NOTICE`，在源码目录外检查冻结程序的配置，并拒绝覆盖已有归档。`node.json` 包含 `0.1.0 / linux / x86_64` 的登记元数据，放在归档外。各文件用途、上传步骤和版本管理见 [Node 打包与登记](docs/node-registration.md)。

本地 HTTP 与固定模型协议测试验证请求/响应和运行契约，不代表真实 VLM 的控制质量或 LIBERO 成功率；需要部署实际模型后在 benchmark 环境评测。
