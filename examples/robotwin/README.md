# RoboTwin 14 维三摄像头示例

`policy.yaml` 声明双臂各 6 个关节加 1 个夹爪，`dataflow.yaml` 连接 RoboTwin 桥接端与 VLM 节点。关节限位、夹爪约定和周期是示例，使用前须与具体机器人核对。

本目录提供配置，不包含 RoboTwin 桥接程序，也没有完成真实 RoboTwin 闭环验证。不能把 RoboTwin 的任意原生启动脚本直接当作符合以下协议的桥接端。

## 启动

准备两个可执行入口的绝对路径：

- `ROBOTWIN_BRIDGE_BIN`：实现下述 Dora/Forge 接口的 RoboTwin 桥接程序。该变量由 dataflow 使用，不是 RoboTwin 官方环境变量。桥接端自行配置模型、任务和仿真环境；`POLICY_ID=vlm_robotwin` 作为双方约定传入。
- `VLM_POLICY_BIN`：本项目当前版本的 `operator-vlm-action-policy` 入口，支持 `--config` 以及 `generic` 动作。确认安装的是当前工作区版本，避免调用旧版安装包。

先配置 `VLM_API_BASE`、`VLM_API_KEY`、`VLM_MODEL`，可选配置 `VLM_REASONING_EFFORT`。本例直接使用模型环境变量，没有 gateway 或私有配置加载脚本。

在仓库根目录可离线检查策略配置：

```bash
PYTHONPATH=src .venv/bin/python -m vlm_action_policy.main \
  --config examples/robotwin/policy.yaml --check-config
```

设置两个入口变量后，从本目录启动，以保证 `--config policy.yaml` 的相对路径正确：

```bash
cd examples/robotwin
dora run dataflow.yaml
```

## 桥接端端口协议

| 方向（相对于桥接端） | 端口 | 类型和要求 |
|---|---|---|
| 输出 | `policy_command` | Forge `PolicyCommand`；`policy_id=vlm_robotwin` |
| 输出 | `proprio_state` | Forge `JointState`；名称、顺序和单位匹配 policy.yaml |
| 输出 | `image/head` | Forge `Image`，头部 RGB 相机 |
| 输出 | `image/left_wrist` | Forge `Image`，左腕 RGB 相机 |
| 输出 | `image/right_wrist` | Forge `Image`，右腕 RGB 相机 |
| 输出 | `benchmark_result` | 回合/评估结束通知；当前策略仅检查端口事件 |
| 输入 | `action` | Forge `JointCommand`，14 维绝对目标，name=动作 layout |
| 输入 | `policy_error` | 单元素 Arrow 字符串数组，内容为 JSON；应终止/记录失败并停止执行动作 |
| 输入 | `tick` | Dora 定时器；桥接端自行定义其仿真调度方式 |

图像支持 rgb8、bgr8、rgba8、bgra8、mono8。三个图像端口缺少任何一个都会等待完整观测，不能发送不同时间步拼成的图像组。

## 生命周期与同步

1. 发送 `start`；本例使用本地 policy.yaml，无需再附动态契约。
2. 准备回合身份，发送 `set_instruction`，inputs 中包含 `instruction` 和完整身份字段。
3. 发送 `reset_scene`，inputs 包含完整身份字段；每次真正重置生成新的 epoch。
4. 发送当前状态与三张图片，每条消息 metadata 都带相同的 `episode_id`、`epoch`、`obs_id`、`step_id`、`instruction_version`。
5. 收到 `action` 后执行一次；记录其 metadata 中的 `action_id`。
6. 执行后发送下一步完整观测，增加 step_id、更新 obs_id，并在状态及三张图片 metadata 中附上相同的 `last_action_id`，值为刚执行动作的 action_id。
7. 完成时输出 `benchmark_result`；本例 `exit_on_benchmark_result=false`，策略驻留等待下一轮命令。关闭整个进程使用 Dora stop。

第一步身份示例：

```json
{"episode_id":"task-0","epoch":"reset-unique-1","obs_id":"obs-0","step_id":0,"instruction_version":1}
```

本例 H=M=1，每次观测只授予一个动作执行机会。`control_dt_s=0.05` 是动作时间语义，桥接端实现实际仿真推进/插值；dataflow 中 20ms tick 不表示模型每 20ms 生成一次动作。

后续可通过 start/reset_scene 中的动态契约切换机器人，但不会动态增加 Dora 连线，详见 [通用契约](../../docs/benchmark-contract_zh.md)。
