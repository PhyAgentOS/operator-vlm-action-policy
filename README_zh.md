[English](README.md) | 简体中文

# operator-vlm-action-policy

**当前仅提供设计方案，没有确认后的实现或可运行节点。**

规划同一个独立、内部常驻动作策略节点，覆盖两种方案：

| 方案 | 输入 | 输出 | 业务节点 |
|---|---|---|---|
| A：VLM 独立策略 | instruction、obs_state、obs_image | 从生成片段中逐步输出 final_action | benchmark + VLM 动作策略 |
| B：VLA + VLM | VLA 候选 chunk + 同样的指令与观测 | 保留/修正后的单步 final_action | benchmark + VLA 候选 + 同一个 VLM 动作策略 |

节点自身接入模型 API 或进程内本地模型，不依赖已有 `operator-vlm-policy` 服务。
动作片段长度和维度可配置，同时严格绑定动作语义；只有最终 VLM 动作节点向环境输出动作。

- [简明中文方案](docs/DESIGN_zh.md)、[English design](docs/DESIGN.md)：分别说明两种方案的架构图、数据流图、节点分工和关键参数，并链接完整 dataflow 草案与接口细节。
- 方案 A：[dataflow](examples/libero/dataflow.yaml)、[policy](examples/libero/policy.yaml)、[benchmark](examples/libero/benchmark.yaml)。
- 方案 B：[dataflow](examples/vla_vlm/dataflow.yaml)、[最终策略](examples/vla_vlm/policy.yaml)、[VLA 候选](examples/vla_vlm/vla.yaml)、[benchmark](examples/vla_vlm/benchmark.yaml)。
- [关节输出草案](examples/joint/policy.yaml)：要求真实关节状态和匹配控制器。

所有新配置键与 candidate/request/feedback 端口均为拟议契约。现有 VLA runner 需扩展，
严格观测身份和 benchmark 即时失败收尾也需集成工作。YAML 路径对应未来制品，
不宣称已实现、运行模型测试或通过 Skill 安装验收。

默认 LIBERO 接收单步七维动作（六维末端控制量 + 一维夹爪），不直接消费 H×D 片段或七个关节角。
修改维度不能自动改变坐标系、单位、控制类型和夹爪语义。

采用 Apache-2.0，见 [LICENSE](LICENSE)、[NOTICE](NOTICE)。
