[English](DEVELOPING.md) | 简体中文

# 开发指南

使用 Python 3.11+，上游 LIBERO 例子将 Dora CLI 锁定到 0.4.1。
`uv sync --frozen --all-extras --group dev` 安装公共来源的锁定依赖。

```bash
uv run pytest -q
uv run ruff check src tests scripts
uv run python -m compileall -q src tests scripts
uv run python scripts/check_publication.py
uv build
```

## 模块

- `contracts.py`：严格配置、观测及动作契约，输出 schema、物理范围。
- `backend.py`：已有通用服务协议与取消；终态字段为 `execution_status`，结构化内容为 `output.json`。
- `actions.py`：世界系 EEF 比例、四元数反馈、关节约束。
- `runtime.py`：新观测动作额度、队列所有权、有限已执行历史、生命周期代际和异步推理，不依赖传输。
- `wire.py`：原生实现公共 Forge Arrow 字段及 RGB/BGR→PNG 编码。
- `node.py`：Dora 事件循环和输入驱动，timer 推进 asyncio；不能在事件循环加入同步模型请求。

reset、指令变更、暂停、停止均作废旧代际，迟到结果不能重新填充可执行队列。
动作仅在收到下一观测回执后进入执行历史。不能把 LIBERO 历史 EEF 标签当成真实关节角，
也不能将缺失的状态名称默认为零。

`observation_v1` 需要生产者扩展及动作关联校验。legacy 夹具便于现有 LIBERO 接入，
不证明传感器原子同步，测试和报告必须保持这一界限。

失败后不发默认移动。上游 benchmark 没有 abort 输入，发布验收需验证真实 Dora/PAOS
运行管理中的中断批次统计；数值约束不能证明碰撞安全。

Skill 源码是部署模板，尚未成为验收制品。打包时保留 Apache 声明、生成 PAOS 逐文件归档清单，
并在目标版本验证 install/start/describe/run/result/stop。[完整方案](docs/DESIGN_zh.md)列出验收要求。

协议修改应配语义测试，例如 reset 迟到结果、错误关节顺序、一观测一动作、真实通用服务响应格式。
同步更新中英文 README、方案及开发文档。公共仓库 PR 使用个人 fork 的 `feature/`、`fix/` 或 `docs/` 分支。

示例使用 shell 启动脚本：Dora 0.4.1 会规范化可执行路径，直接使用虚拟环境 Python 符号链接可能丢失环境；在脚本内启动解释器可以保留目标环境。
