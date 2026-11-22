# 通用 benchmark 契约

策略节点支持两种接入方式：旧 benchmark 不发送契约，继续使用本地 YAML；新 benchmark 在 `PolicyCommand.inputs_json` 的 `start` 或 `reset` / `reset_scene` 中发送 `contract`。任务 prompt 仍通过 `set_instruction` 的 `instruction` 发送，额外场景信息通过生命周期命令中的 `context` JSON 对象传入。

节点提供通用数值向量接口，不自动识别机器人或调用任意仿真 API。benchmark 的桥接端负责将相机、状态和动作转换到 Forge/Dora 协议，并实现仿真推进、重置和动作反馈。任意动作维度不等于任意控制器语义都可自动互换。

## 命令格式

下面展示一个两维示意；双臂 14 维使用相同结构，将所有逐维数组扩展到 14 个元素，并准确描述左右臂和两个夹爪。

```json
{
  "episode_id": "task-1",
  "epoch": "reset-1",
  "obs_id": "observation-0",
  "step_id": 0,
  "instruction_version": 1,
  "contract": {
    "version": 1,
    "action": {
      "space": "generic",
      "frame": "joint_space",
      "dimension": 2,
      "layout": ["joint_target", "gripper_width"],
      "units": ["rad", "m"],
      "descriptions": ["Absolute joint target in radians", "Absolute jaw opening width in meters, zero is closed"],
      "gripper_convention": "gripper_width is jaw opening in meters; zero closed",
      "prediction_horizon": 1,
      "execute_horizon": 1,
      "control_dt_s": 0.05,
      "state_keys": ["joint_position", "jaw_width"],
      "max_step_delta": [0.1, 0.01]
    },
    "control_adapter": {
      "type": "affine",
      "native_dimension": 2,
      "lower_bounds": [-2, 0],
      "upper_bounds": [2, 0.08]
    },
    "observation": {
      "state_names": ["joint_position", "jaw_width"],
      "state_semantics": ["joint_position", "jaw_width"],
      "image_inputs": {
        "image/head": "head",
        "image/left": "left_wrist",
        "image/right": "right_wrist"
      },
      "synchronization": "correlated_observation",
      "require_identity": true
    }
  },
  "context": {"scene_description": "A cup is on the table"}
}
```

## 兼容规则

- `version` 必须为整数 `1`。动作、适配器必须声明，观测段可选。契约不能修改模型、密钥、运行时和生命周期配置。
- `action.space=generic`，`control_adapter.type=affine`。每维名称、单位、描述和上下限必须匹配 D；不假定任何夹爪索引、范围或机械臂数量。描述必须写明绝对目标/增量、旋转表示和开合方向。
- 上下限约束模型输出坐标。可选 `scale`、`offset` 各有 D 个元素，输出到 benchmark 时计算 `native[i] = model[i] * scale[i] + offset[i]`；省略时为恒等转换。非线性转换、IK、插值和控制器切换由 benchmark 桥接端完成。
- 可选 `max_step_delta` 配合 D 个 `state_keys`，适用于绝对目标：从当前观测开始，逐行比较目标变化；增量动作应使用逐维上下限。
- 契约的段是完整替换声明，基于启动 YAML 构建；不会合并上一台机器人的字段。省略整个 `contract` 时保留当前有效契约；从未发送契约则一直使用启动 YAML。
- 契约在 reset 边界可切换；`start` 只允许在需要 reset 的状态切换。切换清空动作、历史并使旧推理结果失效。观测配置改变时，提前缓存的观测也会丢弃，benchmark 应在重置后发送完整新观测。
- 传输同步模式不能通过契约改变，必须与启动 YAML 一致。严格模式的 reset 仍要求全部五个身份字段；旧 `legacy_lockstep` 模式可不发送身份字段，但契约观测段也应明确填写对应同步设置。
- `context` 在省略时沿用当前值；发送 `{}` 可清空。它作为模型输入数据，不取代动作契约或系统规则。
- 相机数量由 `image_inputs` 决定。Dora dataflow 必须预先接好对应端口，契约不能动态增加 dataflow 边。每一步状态和全部相机到齐才推理。
- `proprio_state` 使用 Forge `JointState`，名称和顺序必须匹配 `state_names`；相机使用 Forge `Image`。输出 `action` 继续使用 Forge `JointCommand` 的 `name=layout`、`position=原生动作向量`。该消息名不表示 generic 向量必然是关节角。
- 模型输出仍为 `{"actions": [[...D...], ...H...]}`；节点严格检查 H、D、有限数值和范围，再执行前 M 行。输入状态维度独立于 D。
- Python 本地模型插件须使用 `request.config` 获取当前契约和 `request.context` 获取场景信息；仅使用工厂初始化时 config 的旧插件需要更新才能支持动态契约。

## 接入验证

先以 H=M=1 验证：正确的 D 维输出、三个相机全部参与请求、动作顺序和夹爪方向、单位转换、ACK 后新观测、跨回合旧结果丢弃、非法输出拒绝。确认闭环后再增加预测和执行步数。已有 LIBERO 的 eef_delta/joint_position 模式保持原行为。
