[English](README.md) | 简体中文

# operator-vlm-action-policy

**当前仅提供设计方案，没有确认后的代码实现或可运行节点。**

规划一个独立、内部常驻的 VLM 动作策略节点：输入任务指令、图片和机器人状态，
由节点自身负责模型推理，输出 EEF 或关节动作片段。**不依赖已有 `operator-vlm-policy` 服务。**

- [完整方案与流程图](docs/DESIGN_zh.md)
- [English design](docs/DESIGN.md)
- [LIBERO dataflow.yaml 草案](examples/libero/dataflow.yaml)
- [策略配置草案](examples/libero/policy.yaml)
- [关节输出配置草案](examples/joint/policy.yaml)

方案定义计划中的节点输入输出、动作契约、生命周期、benchmark 接入和 Skill 封装。
配置文件均为设计样例，可执行路径对应未来制品；本方案不宣称已经实现、完成模型测评、
跑通 Dora 集成或通过 Skill 安装验收。

默认 LIBERO 七维动作是 EEF 控制量。关节输出需匹配控制器和真实关节观测；
如果采用 EEF→joint 的 IK 路线，由显式控制适配模块承担。

采用 Apache-2.0，见 [LICENSE](LICENSE)、[NOTICE](NOTICE)。
