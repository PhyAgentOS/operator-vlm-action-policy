[English](README.md) | 简体中文

# operator-vlm-action-policy

内部常驻 Dora 节点，将任务指令、图片和机器人状态转换为有界的 **EEF 或关节动作片段**。
复用已有 [operator-vlm-policy](https://github.com/PhyAgentOS/operator-vlm-policy) HTTP 服务，
独立承担观测同步、异步推理、chunk 消费、位姿伺服、reset 隔离与执行反馈历史。

## Node、Endpoint 与 Tool API

| 项目 | 实现 |
|---|---|
| 生产节点 | 一个：`operator-vlm-action-policy run --config policy.yaml`；[入口](src/operator_vlm_action_policy/node.py) |
| 输入 | `tick`、`policy_command`、`proprio_state`、配置的 `image/*`、`benchmark_result`；可选严格 `observation` |
| 输出 | `action`（兼容 Forge JointCommand）、`action_chunk`、`policy_state`、`policy_error` |
| Endpoint / Tool / HTTP 监听 | 0 / 0 / 0，节点通过数据流运行 |
| 外部推理 | 现有通用服务 `/v1/infer:wait`，本节点不持有模型权重和 provider 凭据 |
| 示例部署 | 两个 Dora 节点 + 已有 HTTP 服务；增加 Gateway 后为三个 Dora 节点 |
| 可选 benchmark Tool | 由 benchmark-libero 提供 `benchmark.controller / describe` Query、`/ run` Session；部署绑定 `vlm_libero.benchmark.describe`、`vlm_libero.benchmark.run` |

## 安装与运行

```bash
uv sync --frozen --all-extras --group dev
uv run operator-vlm-action-policy validate --config examples/libero/policy.yaml
uv run operator-vlm-action-policy schema --config examples/libero/policy.yaml
uv run operator-vlm-action-policy run --config examples/libero/policy.yaml
```

`run` 需要在 Dora 启动环境下执行。先启动已有通用 VLM 服务，其模型和 effort 配置继续生效；
provider 凭据留在该服务。可选服务鉴权使用 `VLM_SERVICE_TOKEN` 环境变量，不在跟踪配置中填写密钥。

使用 [LIBERO dataflow.yaml](examples/libero/dataflow.yaml)，替换可执行路径和 benchmark 源码路径，
从 `examples/libero` 目录运行。两个节点环境和 Dora CLI 均匹配锁定的 **Dora 0.4.1**。
LIBERO、robosuite 和 benchmark 资产需单独安装。

## 动作输出

| 类型 | 模型输出 | 执行方式 |
|---|---|---|
| `eef_delta` | xyz 米 + 世界系旋转增量向量（弧度）+ 夹爪 | 转为 LIBERO OSC，每份新观测执行一行 |
| `eef_pose` | xyz 米 + 单位四元数 xyzw + 夹爪 | 按反馈持续伺服，直到容差或步数上限 |
| `joint_position` | N 个关节角（弧度）+ 夹爪 | 检查关节上下限和单步变化，输出绝对目标 |

当前 EEF profile 要求世界系 LIBERO OSC 增量控制。[关节示例](examples/joint/policy.yaml)需要
真实关节观测及匹配的关节位置控制器。**默认 LIBERO 七维动作是末端控制量，不是七个关节角。**
本节点不包含 IK 或碰撞规划器。

生成 H 个动作，仅消费配置的前 M 个；每次原生输出必须有完整新观测，tick 不会凭空重复动作。
reset、指令变更、暂停、停止会作废旧请求与队列。通用推理使用 stateless，由动作节点维护有限的
已回执执行历史，episode 之间清空。

## 完整方案、Skill 与验证

- [中文完整方案与流程图](docs/DESIGN_zh.md)、[English design](docs/DESIGN.md)：节点输入输出、动作协议、状态、dataflow、测评和集成边界。
- [Skill 源码模板](examples/skill)：三节点 Tool profile、manifest、Gateway 绑定和启动脚本；PAOS 安装及 Session 验收待运行时验证。
- [中文开发指南](DEVELOPING_zh.md)、[English developer guide](DEVELOPING.md)。

`legacy_libero` 收集各端口的新消息，依赖有序单写入者锁步，不能保证图片与状态原子同步，也不能
完全排除跨端口迟到帧。`observation_v1` 要求生产者扩展显式 episode/step 身份；当前上游 LIBERO
尚未提供这一端口。

测试覆盖受控推理、物理契约、新观测额度、reset 取消、位姿反馈和关节限制，不证明真实 VLM 的
LIBERO 成功率、真实仿真验收或实机安全。策略错误会终止 flow，中断批次需显式记为失败。

Apache-2.0：[LICENSE](LICENSE)、[NOTICE](NOTICE)、[第三方声明](THIRD_PARTY_NOTICES.md)。
另见[安全政策](SECURITY.md)、[贡献指南](CONTRIBUTING.md)、[发布审查](OPEN_SOURCE_AUDIT.md)。
