# Node 打包与登记

本项目按 paos-resource-manager 的 Node 规范准备，类型为 `operator`，当前登记配置为 `0.1.0 / linux / x86_64`，制品类型为 `directory_tar_gz`。规范来源是资源管理器仓库的 `docs/node-registration.md` 和 `examples/registration/node.json`。

## 文件及用途

| 文件 | 用途 | 是否提交给平台 |
| --- | --- | --- |
| `node.json` | 记录名称、版本、目标平台、入口、源码地址和制品发布仓库，供登记脚本读取；页面登记时也可照此填写 | 脚本输入，放在压缩包外；页面不需要上传此 JSON |
| `scripts/build_bundle.sh` | 从 `pyproject.toml` 读取版本，在当前 Linux 架构构建独立可执行目录，检查入口后生成归档 | 本地构建工具 |
| `scripts/verify_bundle.py` | 检查目录包布局、可执行权限、成员和链接等，并输出整包大小及 SHA-256 | 本地预检查工具；不代替服务端校验 |
| `dist/release/*.tar.gz` | 包含可执行程序、Python 和依赖运行库、策略配置及许可证的完整 Node 原包 | 上传此完整文件 |
| `dist/release/*.tar.gz.sha256` | 保存整包摘要，方便传输后用 `sha256sum -c` 核对 | 本地辅助文件；不打入原包 |
| `.gitignore` | 忽略虚拟环境、构建产物、上传断点、编辑器文件及常见私有模型配置文件 | 随源码提交 |
| `LICENSE`、`NOTICE` | 保留项目许可证和版权声明；构建时复制到包内 | 已随原包包含 |

本项目已有 `pyproject.toml`、`uv.lock`、启动器和策略示例，继续复用。Node 不要求额外的 `node.yaml`、`SKILL.md`、Skill 的 `archive-manifest.json` 或运行视频。运行配置使用现有 `examples/libero/policy.yaml`，构建后放到包内 `config/policy.yaml`。

## 本地构建

在项目根目录执行；宿主需提供 `uv` 和 Python 3.12：

```bash
uv sync --frozen
bash scripts/build_bundle.sh
```

默认产物：

```text
node.json
dist/release/
├── operator-vlm-action-policy-0.1.0-linux-x86_64.tar.gz
└── operator-vlm-action-policy-0.1.0-linux-x86_64.tar.gz.sha256
```

脚本从当前 Linux 主机的 `uname -m` 获取架构，不进行交叉编译。默认输出目录是 `dist/release`，可通过 `VLM_BUNDLE_OUTPUT_DIR` 指定其他目录；更换目录后同步修改 `node.json` 的 `bundle`。脚本拒绝覆盖同名归档。需要重新准备同版本候选包时，使用新的输出目录并更新登记文件；已发布版本不可覆盖。

目录包内容：

```text
operator-vlm-action-policy/
├── operator-vlm-action-policy      # 普通文件，权限 0755
├── _internal/                     # Python 及依赖运行库
├── config/
│   └── policy.yaml
├── LICENSE
└── NOTICE
```

根目录名和可执行文件名都必须等于 `metadata.entrypoint`。PyInstaller 运行时需要 `_internal/`，因此上传整个目录包，不能只上传入口文件。构建脚本先在临时目录构建并验证配置，检查归档后再移入输出目录，最后生成摘要文件。

## 登记字段

`node.json` 使用当前 Git remote 对应的源码地址。各字段含义如下：

| 字段 | 当前值或规则 |
| --- | --- |
| `kind` | `node` |
| `name`、`version` | `operator-vlm-action-policy`、`0.1.0`，需与实际发布版本一致 |
| `bundle` | 完整原包路径，相对路径以 `node.json` 所在目录为基准 |
| `metadata.artifact_id` | `operator-vlm-action-policy-0.1.0-linux-x86_64`；每个新版本／构建使用未占用的 ID |
| `metadata.node_type` | `operator`；本节点执行模型推理和策略计算 |
| `metadata.repository` | `operator-vlm-action-policy`；平台发布制品的仓库名称，首次登记后同名 Node 的后续版本不能随意更换 |
| `metadata.github_url` | `https://github.com/PhyAgentOS/operator-vlm-action-policy`；源码仓库根地址，不带 `.git`、分支路径或查询参数 |
| `metadata.platform`、`metadata.arch` | 当前目标 `linux`、`x86_64`；更换构建平台时修改为实际值 |
| `metadata.artifact_type` | `directory_tar_gz` |
| `metadata.entrypoint` | `operator-vlm-action-policy` |

`metadata.version` 由登记脚本从顶层 `version` 同步，不必重复填写。SHA-256 和字节数也由登记脚本计算，不放入 `metadata`。平台对 Node 元数据有字段白名单，不要直接添加描述、依赖或自定义校验字段。

本地文件不能证明平台上的名称、版本和制品 ID 尚未使用。如果 `0.1.0` 已发布，应先确定新版本，同步更新 `pyproject.toml`、`src/vlm_action_policy/__init__.py` 和 `node.json` 的版本、制品 ID、包路径，再更新 `uv.lock` 并重新构建。

## 上传前检查

```bash
uv run --frozen pytest -q
uv run --frozen ruff check --select E4,E7,E9,F,I src tests scripts
uv run --frozen python scripts/verify_bundle.py \
  dist/release/operator-vlm-action-policy-0.1.0-linux-x86_64.tar.gz
(cd dist/release && sha256sum -c operator-vlm-action-policy-0.1.0-linux-x86_64.tar.gz.sha256)
```

构建脚本还会在源码目录外执行冻结程序的 `--check-config`，该检查不调用模型。默认包使用 API 后端，不包含模型密钥、权重或部署方的本地 Python 插件。真实推理仍需设置 `VLM_API_BASE`、`VLM_API_KEY`、`VLM_MODEL` 等环境变量，并配置 Dora 数据流。使用本地模型插件时，必须在构建阶段显式包含插件和依赖。

此包是在 Linux x86_64、glibc 2.39 环境构建并检查的；不要据此假定兼容其他架构、macOS 或较旧 glibc。归档预检查、配置检查和协议测试不等于真实模型的 LIBERO 成功率评测。

## 上传方式

### 平台页面

在开发工作区选择登记 Node，参照 `node.json` 填写字段，上传 `bundle` 指向的完整 `.tar.gz`，然后提交技术校验并按平台流程完成本地运行审核和发布。页面登记不需要上传 `node.json` 或 `.sha256` 文件。

### 管理员脚本

在本项目根目录执行以下命令。按实际部署修改资源管理器仓库位置、API 地址和管理员账号；密码由脚本交互读取：

```bash
python3 /home/gx/python_project/gitlab/paos-resource-manager/scripts/register-resource.py \
  --base-url https://paos-resource-platform.dev.x-era.com \
  --username YOUR_ADMIN_USERNAME \
  --spec ./node.json
```

该命令会实际上传并登记，脚本管理员入口通过校验后自动发布。本文档的本地准备步骤不会执行它。平台表单入口仍走审核流程，二者权限和发布流程不同。

脚本会在 `node.json` 旁生成 `.local/node.receipt.json`，用于断点续传和查询进度，不需要预先创建，也不要提交到 Git。保留回执后可重跑相同登记命令。只有结果显示 `published` 且 `completed: true`，并完成目录查询和下载摘要核对，才算登记完成。
