[English](CONTRACTS.md) | 简体中文 · [返回方案](DESIGN_zh.md)

# 接口细节：实施时参考

以下均为设计约定，不是已实现接口。主方案见[设计文档](DESIGN_zh.md)，完整 YAML 保留在 examples。

## 动作与时间

- 分别配置 VLA 候选长度 H_vla、VLM 最终长度 H_final、执行长度 M、每步维数 D。初版严格校验固定形状；B 的保留/有界修正要求 H_vla ≥ H_final ≥ M ≥ 1。
- D 与 action_space、layout、units、frame、joint_names、夹爪约定绑定。预训练 VLA 原生 H/D 受 checkpoint 约束，截取或重采样须显式定义。
- 模型片段与环境原生动作可以有不同维数，通过明确的控制适配器转换。例如 EEF 位姿八维可转成七维 OSC；不能只改数字。
- 模型统计去归一化和控制器缩放分别处理。B 的候选先转换成约定的米/弧度等规范表示，避免无量纲值、重复缩放或坐标混用。
- dt 表示环境控制周期。绝对位姿不保证一个周期内到达；跨步伺服要限制收敛步数，并按原生动作步记账。B 首版采用等时 EEF 增量或 joint 动作。
- 修正平移/关节时检查步长和绝对范围；旋转使用明确的 SO(3) 组合；夹爪默认不覆盖。数值范围检查不等于碰撞安全。

## 关联身份

观测包含 episode_id、epoch、obs_id、step_id、instruction_version。图片和状态共享同一身份。片段还包含 chunk_id、source_obs_id、start_control_step、control_dt_s、动作语义与 normalization_profile。

A 的 legacy_lockstep 仅用于受限原型。正式 A 和 B 需 benchmark 增加共同身份元数据或完整 observation 信封，接收动作时也校验身份。不能将不同时间的“最新图片”和“最新状态”直接视为同步。

LIBERO 的现有八维 proprio_state 是 EEF 位置三维、旋转向量三维和双指位置二维。默认原生 action 是六维末端控制量加一维夹爪。joint 输出需真实关节状态与匹配控制器，EEF→joint 如需 IK 也由显式适配器完成。

## B 的内部数据流

| 消息 | 作用 |
|---|---|
| candidate_command | VLM 节点转发指令/reset/stop，使用目标 VLA policy_id；不能误用 benchmark 最终策略的 ID |
| vla_policy_state | 确认当前 episode/epoch 已 reset 且 ready，再派发候选请求 |
| candidate_request | 携带 request_id、观测身份、计划起步位置、候选长度与期限；每次重规划一个有效请求 |
| vla_action_chunk | 返回对应请求、身份和动作契约的候选片段，不自行执行 |
| execution_feedback | 执行确认后反馈 final_action_id、候选索引、实际最终命令及回执观测，供 VLA 更新历史 |
| decision_trace | 保留候选、keep/refine/replan 决策、修正量、最终输出及拒绝/回退原因 |

这些候选接口需要扩展现有 VLA runner，不能假定已经提供。完整连线见[方案 B dataflow](../examples/vla_vlm/dataflow.yaml)。benchmark 的生命周期命令先到最终策略，再定向转发给 VLA。

## 队列、取消与错误

- 一个完整新观测只授予一个动作额度；只有 VLM 节点拥有最终队列和环境动作输出。
- reset、指令变更、pause、stop 同时作废本地请求、候选和最终队列；取消不了计算也不能应用迟到结果。上下文以 episode 为边界，只记录已确认执行动作。
- 初版按串行锁步运行。异步预取以后再设计，必须只向尚未执行的控制步提交结果，并原子替换队列。
- 默认超时/非法动作中断评测。未来如允许保留有效候选作为回退，必须显式配置、检查有效期并统计，不能假装全程已由 VLM 审核。
- 当前 benchmark 尚缺完整的即时策略失败/abort 收尾协议，需要扩展以避免等待动作时挂起并正确落盘。YAML 没有虚构现成 abort 端口。
- 未完成和失败 episode 必须保留在统计中；官方判分来自 benchmark。VLM 自报完成不能当成功标签。

## Skill 与版本

两个 profile 使用各自 dataflow、policy、benchmark 配置；B 另加 vla 配置。可选 Gateway 绑定 benchmark.controller 的 describe Query、run Session；动作节点不新增 ToolEndpoint。

统一锁定 Dora、Forge、消息和控制器版本。模型参数直接归动作节点管理，凭据留在部署环境，Skill 不打包密钥、权重或 benchmark 数据。
