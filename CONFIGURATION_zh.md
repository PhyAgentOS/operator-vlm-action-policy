# operator-vlm-action-policy 配置说明

本文对应本仓库 `src/vlm_action_policy/config.py` 中的 `PolicyConfig`。这里的 YAML 是 VLM 策略节点配置，不是 LIBERO benchmark 配置，也不是机器人驱动配置。它定义模型调用、输入观测解释、动作空间和策略运行时行为。

本项目当前真正接通的仿真数据流是 `examples/gpt6_vlm/` 下的 LIBERO dataflow。根目录的 `config/policy.example.yaml` 按参考项目在 `config/` 下提供 example 的组织方式编写，但字段和取值依据本策略节点自己的 schema 与现有 LIBERO profile，不包含参考项目机器人的硬件参数。

项目运行环境锁定 Python 3.12、`dora-rs==0.4.1`、`forge-msgs==1.2.0`。配置加载器拒绝未知字段，下面列出的字段必须使用对应拼写。

## 使用方法

可以把本文件理解为“策略端的接口约定和运行参数”。一个 episode 开始后，benchmark 通过 `policy_command` 给出指令和生命周期命令；策略节点把 `proprio_state` 与配置列出的相机图像组装成观测，再把状态语义、指令和动作契约交给 VLM。模型返回动作片段后，节点先验证行数、维数、数值和物理限制，通过后才经 `action` 发给 benchmark。策略等待环境反馈，确认动作后再更新历史并规划后续动作。因此 YAML 中的状态名称、动作单位、时域和同步模式必须与 dataflow 两端共同遵守，不能只改其中一侧。

建议先从仓库已有 profile 开始，而不是从空文件逐项猜默认值。`examples/gpt6_vlm/policy.yaml` 与 `examples/gpt6_vlm/dataflow.yaml` 配套，适合当前 LIBERO 集成；根目录 `config/policy.example.yaml` 是完整、带注释的通用副本，便于复制后定制。修改后先用 `--check-config` 验证 schema，再用 `--check-env --check-config` 验证模型环境，然后在已配置好的 benchmark 环境里运行 Dora dataflow。前两步都不会启动 VLM 推理，也不会证明相机或动作端口在真实环境中已连接。

在仓库根目录检查已接入的 LIBERO 配置：

```bash
./operator-vlm-action-policy.sh --config examples/gpt6_vlm/policy.yaml --check-config
```

检查模型环境配置，不发送模型请求：

```bash
./operator-vlm-action-policy.sh --config examples/gpt6_vlm/policy.yaml --check-env --check-config
```

启动 LIBERO dataflow 需在已安装 Dora、LIBERO benchmark 和仿真依赖的环境中执行：

```bash
cd examples/gpt6_vlm
dora run dataflow.yaml
```

`--config` 也可由 `POLICY_CONFIG` 环境变量替代。`--check-config` 只解析并验证 YAML，不加载模型或启动 Dora；`--check-env` 离线检查 provider 配置，不会验证模型质量。模型凭据通过环境变量或私有 JSON 环境文件提供，不能写进 YAML。私有文件格式、变量优先级和权限要求见 [README_zh.md](README_zh.md)。

在本机调试时，命令行参数能清楚地表明本次启动使用哪份配置。部署到 Skill 或由 Dora 启动时，dataflow 环境中的 `POLICY_CONFIG` 通常指向部署包里的 `config/policy.yaml`。发布配置时应把示例复制到该位置并按部署环境修改，API key 仍单独注入运行环境。`policy_id` 要与 benchmark 发送的目标 ID 一致；如果两边不同，配置文件本身虽能通过校验，策略仍不会响应发给另一个 ID 的命令。

在 dataflow 中，benchmark/gateway/策略节点的连接由 `examples/gpt6_vlm/dataflow.yaml` 决定，benchmark 自身参数在 `benchmark.yaml`。策略节点固定接收 `policy_command`、`proprio_state`、配置中的图像端口、`tick`、`benchmark_result`，输出 `action`、`action_chunk`、`policy_state`、`policy_error`。`image_inputs` 只配置相机输入端口；不能通过 policy YAML 修改其他协议端口。

如果图像 producer 的 ID 或数量改变，需要同时调整 dataflow 的连线和 `image_inputs`。状态端口名仍固定为 `proprio_state`，其消息类型是 Forge `JointState`；`state_names` 是消息内部名称列表，不是 Dora 端口名。benchmark YAML 负责任务集合、初始状态和评测参数，policy YAML 不会改变这些内容。把 benchmark 参数写进 policy YAML 会因未知字段校验而启动失败。

## 顶层结构

顶层只接受 `PolicyConfig` 定义的九个字段。每个 section 都是结构化配置，不支持任意扩展字段；这一点可以在开发期尽早暴露拼写错误和未实现功能。字段没有写入 YAML 时会使用表格中的代码默认值，不过项目样例会显式列出关键值，让部署 profile 的行为更容易复查。

| 字段 | 默认值 | 本项目中的作用 |
|---|---|---|
| `policy_id` | `vlm_libero` | 收到 `policy_command` 时匹配的策略标识，非空字符串。应与 benchmark 发出的 ID 对齐。 |
| `mode` | `standalone` | 当前只实现 `standalone`；`vla_conditioned` 会被拒绝。 |
| `model` | 默认值 | provider API 或进程内 Python 模型插件参数。 |
| `observation` | 默认值 | 图像输入、Forge 状态 wire 标签及提供给模型的状态语义。 |
| `action` | 默认值 | 模型必须返回的动作格式和预测/执行时域。 |
| `control_adapter` | 默认值 | 校验动作边界并将规范动作转换为 benchmark/控制器动作。 |
| `runtime` | 默认值 | 推理、反馈、观测超时和 benchmark 结束行为。 |
| `context` | 默认值 | 限定模型上下文中已确认执行历史的长度。 |
| `lifecycle` | 默认值 | episode 历史清理和过期推理结果拒绝策略。 |

## `model`

| 字段 | 默认值 | 说明 |
|---|---|---|
| `backend` | `provider_api` | `provider_api` 调用 HTTP API；`local_python` 调用进程内插件。 |
| `api_style` | `chat_completions` | API 路径风格：`chat_completions` 或 `responses`。程序在 base 后追加 `/chat/completions` 或 `/responses`。 |
| `api_base_env` | `VLM_API_BASE` | API base URL 所在环境变量的名字，不是 URL 值。 |
| `api_key_env` | `VLM_API_KEY` | API key 所在环境变量的名字。 |
| `model_name_env` | `VLM_MODEL` | 模型名所在环境变量的名字。 |
| `effort_env` | `VLM_REASONING_EFFORT` | 推理强度所在环境变量的名字。 |
| `structured_output` | `true` | 请求 JSON Schema 结构化响应；关闭时本地动作校验仍然执行。 |
| `max_output_tokens` | `2048` | 模型输出 token 上限，正整数。 |
| `local_factory` | `""` | `local_python` 工厂函数，格式 `module:factory`；工厂返回实现 `infer(request)` 的对象。 |

模型需支持图像输入和动作 JSON。Provider 请求超时由 `runtime.inference_deadline_ms` 限制。API base 是服务前缀（通常包含 `/v1`），不要把完整 `/chat/completions` 路径填入。

`backend: provider_api` 是当前 `gpt6_vlm` profile 的模式：配置只保存环境变量名称，实际 URL、密钥、模型名由运行环境提供。`api_style` 决定请求和响应解析协议，必须与所用服务兼容。服务无法返回结构化输出时可以关闭 `structured_output`，但模型仍必须返回本项目规定的 `actions` 对象；解析后的动作仍经过相同本地检查。`max_output_tokens` 要能容纳 H 行动作和模型附带内容，过小可能造成被截断的 JSON，导致该轮失败。

`local_python` 是进程内扩展点，不会自动加载任意 VLA 服务或外部进程。`local_factory` 指向 Python 可导入的工厂函数，返回对象需实现 `infer(request)`。本地插件接收结构化 request，并返回同一个 `{"actions": [...]}` 格式；它使用相同动作验证和排队流程。插件依赖需存在于当前 Python 环境或显式打进冻结包。

## `observation`

| 字段 | 默认值 | 说明 |
|---|---|---|
| `image_inputs` | `image/main: main`, `image/second: wrist` | Dora 图像输入端口到模型相机别名的映射。所有配置的图像端口都要到齐才形成完整观测。 |
| `state_names` | `joint1`…`joint7`, `gripper` | Forge `JointState.name` 必须与该列表逐项、按顺序完全一致，否则输入被判为非法。 |
| `state_semantics` | EEF 和双指语义 | 将同索引的状态值以这些名称传给模型；不改变数据或单位。应描述实际物理含义。 |
| `synchronization` | `correlated_observation` | `correlated_observation` 用身份元数据拼合状态和相机；`legacy_lockstep` 用于无身份元数据的串行旧协议。 |
| `require_identity` | `true` | 必须与同步方式一致：相关身份模式为 true，legacy lockstep 为 false。 |

状态输入来自 `proprio_state` 的 Forge `JointState.position`。图像输入来自 Forge `Image`，支持 8-bit RGB/BGR/RGBA/BGRA/灰度，再编码为 PNG 发给模型。当前 LIBERO 示例中 `state_names` 是历史 wire 标签 `[joint1..joint7, gripper]`，而 `state_semantics` 实际为 EEF XYZ、旋转向量和双指位置；这是传输协议标签与状态物理含义不同的显式映射。

LIBERO 当前配套 `libero_benchmark-1.0.1-ubuntu20.1` 不提供完整观测身份/action ACK 扩展，所以 `examples/gpt6_vlm/policy.yaml` 使用 `legacy_lockstep`。不要单独将它改为 correlated 模式，除非 benchmark 端也提供 `episode_id`、`epoch`、`obs_id`、`step_id`、`instruction_version` 和 `last_action_id` ACK。

严格模式会按观测身份把来自不同输入端口的图像和状态配成同一帧，并拒绝重复消费的身份；它适合能为观测、动作回执提供稳定元数据的 benchmark。legacy 模式依赖旧 benchmark 保序、单步串行地发布状态和图像，节点无法从元数据证明某帧对应哪个 action。这个差异影响暂停恢复：严格模式可以要求恢复后收到新的 step/epoch；legacy 模式暂停时无法辨别缓存帧的新旧，所以会失败关闭。切换同步模式是 benchmark/dataflow 的协议变更，不是单纯性能调参。

## `action`

| 字段 | 默认值 | 说明 |
|---|---|---|
| `space` | `eef_delta` | `eef_delta` 或 `joint_position`。 |
| `frame` | `world` | EEF 模式必须是 `world`；关节模式必须是 `joint_space`。 |
| `dimension` | `7` | 每行动作维数 D，正整数。 |
| `layout` | `[dx,dy,dz,drx,dry,drz,gripper]` | 每一维的名称，必须唯一且正好 D 项。 |
| `units` | `[m,m,m,rad,rad,rad,normalized]` | 与布局逐维对应的单位。 |
| `gripper_convention` | `minus1_open_plus1_close` | 夹爪动作 -1 张开、+1 闭合。 |
| `prediction_horizon` | `4` | VLM 每次必须返回的动作行数 H。 |
| `max_prediction_horizon` | `8` | 配置允许的最大 H；需满足 `1 <= execute_horizon <= H <= max_prediction_horizon <= 256`。 |
| `execute_horizon` | `2` | 每次执行前 M 行，之后等待反馈并重新规划；剩余预测行丢弃。 |
| `control_dt_s` | `0.05` | 预测动作行之间的时间间隔，秒。 |
| `joint_names` | `[]` | 关节模式需要，列出 D-1 个实际关节名。 |
| `max_step_delta` | `[]` | 关节模式需要，逐维目标变化上限，单位与动作维相同，含夹爪维。 |

模型响应必须严格为 `{"actions": [[...], ...]}`，恰好 H 行、每行 D 个有限数。整个 H 行在发第一条动作前一起校验和限幅，包括未执行的尾行：超过上界取上界，低于下界取下界。动作块、实际下发和执行历史均使用限幅后的值；维度错误、非数字、NaN 和无穷值仍会拒绝整段。

`eef_delta` 当前只支持固定世界系 7 维布局：平移 m、旋转向量 rad、夹爪 normalized。`libero_osc_delta` 再按 adapter scale 缩放为 benchmark 原生 [-1,1] 命令，模型不得预先归一化。`joint_position` 透传绝对关节目标，不做 IK、插值或控制器切换；需要 D-1 个关节加夹爪，关节单位 rad，夹爪 normalized。每步变化从观测中的当前状态开始比较，再与前一行目标比较。

H 和 M 是滚动规划的核心参数。H 越大，模型一次预测的未来越长；M 决定其中多少行在下一次重新观测前被执行。当前实现会完整验证 H 行，但只执行 M 行，然后丢弃剩余预测并重新调用模型。调小 M 会更频繁地根据新状态规划，增加模型请求次数；调大 M 会减少请求次数，但执行中间重新感知和纠偏的机会也变少。`control_dt_s` 是动作序列的时间语义，不代表 Dora tick 或机器人控制器一定能精确按该周期执行。

选择 `joint_position` 时，模型输出每行是完整的绝对关节目标，而不是关节增量。`max_step_delta` 从当前观测开始，将第一行目标限制在允许步长内，后续行以上一行限幅后的目标为基准；最终范围取步长范围与物理边界的交集，交集为空时拒绝整段。它是幅度上限，不是速度规划器。上下界与步长限制都不能代替驱动侧限位、速度限制、碰撞检查或急停。当前 LIBERO `gpt6_vlm` 使用的是 `eef_delta`，LiteArm 等关节控制器需要各自完成观测单位映射和实际动作桥接。

## `control_adapter`

| 字段 | 默认值 | 说明 |
|---|---|---|
| `type` | `libero_osc_delta` | EEF 用 `libero_osc_delta`；关节位置用 `joint_position`。 |
| `native_dimension` | `7` | 原生动作维数，必须等于 D。 |
| `translation_scale_m` | `0.05` | EEF 平移缩放的正尺度，单位米。 |
| `rotation_scale_rad` | `0.5` | EEF 旋转缩放的正尺度，单位弧度。 |
| `limits_source` | `robot_control_profile` | 当前唯一支持值。 |
| `lower_bounds` / `upper_bounds` | `[]` | 可选逐维边界；提供时各需 D 个有限值、逐维下界小于上界。关节模式必须提供。夹爪范围在 [-1,1]。 |

EEF 未提供显式 bounds 时由平移/旋转 scale 推导对称范围，夹爪范围为 [-1,1]。关节边界需从实际机器人/控制器获取；节点不会自动查询固件，也不提供碰撞、可达性或负载安全保证。

对 LIBERO OSC 来说，默认 `translation_scale_m: 0.05` 表示规范平移增量的最大绝对幅度为 5 cm，`rotation_scale_rad: 0.5` 表示旋转向量每维最大绝对幅度为 0.5 rad；节点将这些规范值换算为 benchmark 控制器接受的归一化动作。若改为不同控制 profile，应确认 profile 所定义的缩放和动作坐标系一致，并重跑环境集成验证。`limits_source` 当前是固定兼容字段，写成别的来源并不会触发动态读取。

## `runtime`

| 字段 | 默认值 | 说明 |
|---|---|---|
| `tick_ms` | `20` | Dora tick 轮询间隔，毫秒；不是 VLM 调用频率承诺。 |
| `inference_deadline_ms` | `60000` | 单次推理截止时间，毫秒。超时失败，旧 generation 的结果会被丢弃。 |
| `feedback_timeout_ms` | `5000` | 动作发出后等待执行反馈的超时，毫秒。 |
| `observation_timeout_ms` | `60000` | 等待完整状态和图像观测的超时，毫秒。 |
| `on_error` | `abort_evaluation` | 当前仅支持失败时终止本次评测。 |
| `async_prefetch` | `false` | 当前仅支持串行推理，必须为 false。 |
| `exit_on_benchmark_result` | `true` | 收到 benchmark 结果时退出；serve 多批次驻留时设 false。 |

`legacy_lockstep` 没有精确 ACK，后续完整观测仅作隐式确认。无身份帧无法可靠区分暂停前后的新旧；该模式 pause 后失败关闭，resume 不会重用旧状态，需停止并重启整个 dataflow。严格身份模式会拒绝重复或过期 step。

超时的量纲都是毫秒。提高 `inference_deadline_ms` 只会让节点更久地等待慢模型，不会改善动作质量；`observation_timeout_ms` 应覆盖 benchmark 生成一帧完整观测的最坏正常耗时。`feedback_timeout_ms` 应大于动作发出到环境产生确认观测的正常延迟，否则健康环境也可能被判为失败。`tick_ms` 控制事件循环多久检查一次状态和截止时间，因此实际超时检测会有至多一个 tick 左右的调度偏差。当前 `on_error`、prefetch 行为受实现限制，配置不能把节点切成自动重试或并行推理模式。

## `context` 与 `lifecycle`

上下文只累计已经确认执行的动作和相关观测，不把刚生成或刚发送但结果未明的动作当作事实。这样模型下一轮看到的是环境确认过的历史，而不是计划中的历史。`max_executed_history: 0` 表示不保留过去动作；设为正数时，按 episode 保存最近 N 条已执行历史。episode reset 会清空这段历史，pause 不会把未确认动作变成已执行记录。

| 字段 | 默认值 | 说明 |
|---|---|---|
| `context.scope` | `episode` | 当前只支持 episode 范围。 |
| `context.max_executed_history` | `4` | 最多提供给模型的已确认执行历史条数，0–256。 |
| `context.include_unexecuted_actions` | `false` | 当前必须为 false；未确认动作不能算作已执行历史。 |
| `lifecycle.reset_history_per_episode` | `true` | 每个 episode 清空历史，当前必须为 true。 |
| `lifecycle.reject_stale_results` | `true` | 拒绝旧 episode/旧观测对应的推理结果，当前必须为 true。 |

## 仓库示例配置

[`config/policy.example.yaml`](config/policy.example.yaml) 按参考项目在 `config/` 下放置 example 的方式组织，但字段和取值来自本节点 schema 与现有 LIBERO profile。它是可以由本节点加载的策略配置，不是 LiteArm adapter 的 `robot.yaml`。当前节点虽支持通用 `joint_position` 动作校验，但不会自动读取 LiteArm 限位，也没有 LiteArm 专用 gripper 单位转换和硬件 dataflow。

检查仓库示例：

```bash
./operator-vlm-action-policy.sh --config config/policy.example.yaml --check-config
```

该 example 与运行中的 `examples/gpt6_vlm/policy.yaml` 具有相同的 LIBERO 协议选择，但面向作为项目根目录模板的阅读和复制场景。要运行已整理好的仿真流程，优先使用 `examples/gpt6_vlm/` 内成套的 `policy.yaml`、`dataflow.yaml` 和 `benchmark.yaml`，不要只替换其中一份配置。若要接 LiteArm，应先补齐适配器 dataflow、gripper 单位转换、反馈身份契约和硬件限位来源，再为该部署维护独立 profile；不能把 LIBERO OSC 参数直接挪作 LiteArm 硬件参数。
