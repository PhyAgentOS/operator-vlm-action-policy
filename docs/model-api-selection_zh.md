# 多模型 API 选择方案

需求：支持 GPT、Claude、Gemini、DeepSeek、Qwen、GLM、Kimi 七个系列中具备图像输入能力的具体模型。每次运行由 `policy.yaml` 明确选择协议，通过所配置的环境变量指定 API base、密钥和模型 ID。`libero_benchmark` 提供观测并执行、评测动作；厂商协议适配由 `operator-vlm-action-policy` 完成。

代码支持下列四种 HTTP 协议，支持协议不等于已验证每个厂商或模型的实际可用性、JSON Schema 能力与任务成功率。本次验证使用本地 HTTP 服务，没有调用付费模型。下列模型 ID 是可配置示例，不表示最新型号或当前账户已经获得访问权限；运行前应以部署服务的模型清单确认。

## YAML 配置

以下配置保留现有字段，已有 Chat/Responses 配置继续有效：

```yaml
model:
  backend: provider_api
  api_style: chat_completions
  api_base_env: VLM_API_BASE
  api_key_env: VLM_API_KEY
  model_name_env: VLM_MODEL
  effort_env: VLM_REASONING_EFFORT
  structured_output: true
  max_output_tokens: 16384
  chat_token_parameter: max_completion_tokens
```

`*_env` 的值是环境变量名称，不是 API 地址、密钥或模型 ID 本身。可以将其改成 `QWEN_API_BASE`、`QWEN_API_KEY`、`QWEN_MODEL` 等名称，为不同配置分别注入环境。模型名称不会触发隐式厂商识别；协议始终以 `api_style` 为准。切换配置后重新启动节点，已 prepare 的评测目录需要重新 prepare。

| `api_style` | 在 base 后追加的路径 | 鉴权 | 输出 token 参数 |
| --- | --- | --- | --- |
| `chat_completions` | `/chat/completions` | `Authorization: Bearer …` | 默认 `max_completion_tokens`，可配置为 `max_tokens` |
| `responses` | `/responses` | `Authorization: Bearer …` | `max_output_tokens` |
| `anthropic_messages` | `/messages` | `x-api-key` 与 `anthropic-version: 2023-06-01` | `max_tokens` |
| `gemini_generate_content` | `/models/{模型 ID}:generateContent` | `x-goog-api-key` | `generationConfig.maxOutputTokens` |

base 保留厂商要求的版本前缀，不自动添加 `/v1`，末尾斜杠会移除。Gemini 模型 ID 可写成 `gemini-2.5-pro` 或 `models/gemini-2.5-pro`。这一路径使用 Gemini Developer API 的 API key 鉴权，Vertex AI 的项目路径及 OAuth 不在本实现内。

## 七个模型系列的选择

| 系列 | 具体视觉模型 ID 示例 | API base 示例 | `api_style` | 部署要求 |
| --- | --- | --- | --- | --- |
| GPT | `gpt-4.1` | `https://api.openai.com/v1` | `responses`，也可选 `chat_completions` | 使用支持图像输入的模型；不支持推理强度参数的型号应清空 effort 环境变量。 |
| Claude | `claude-sonnet-4-5-20250929` | `https://api.anthropic.com/v1` | `anthropic_messages` | 模型与账户需支持所选输出格式；原生接口不发送 OpenAI 字段。 |
| Gemini | `gemini-2.5-pro` | `https://generativelanguage.googleapis.com/v1beta` | `gemini_generate_content` | 使用 Developer API key；确认模型是否接受动作 JSON Schema。 |
| DeepSeek | `deepseek-ai/deepseek-vl2-small`（权重标识） | 自建视觉推理服务地址，例如 `http://127.0.0.1:8000/v1` | 仅在部署服务实现视觉 Chat 协议时用 `chat_completions` | 权重标识不等于官方托管 API 模型 ID。自建端点须明确支持图像；不能把文字对话接口默认视为视觉接口。也可实现 `local_python` 插件。 |
| Qwen | `qwen2.5-vl-72b-instruct` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `chat_completions` | 示例为中国大陆地域；其他地域需使用对应端点。按服务能力选择 `max_tokens` 与结构化输出开关。 |
| GLM | `glm-4v-plus-0111` | `https://open.bigmodel.cn/api/paas/v4` | `chat_completions` | 确认账户仍可访问该视觉模型；兼容端点可配置 `max_tokens`。 |
| Kimi | `moonshot-v1-32k-vision-preview` | `https://api.moonshot.cn/v1` | `chat_completions` | 必须选择支持图像的具体型号；确认 preview 型号可用性。兼容端点可配置 `max_tokens`。 |

示例中的 DeepSeek 权重标识只在自建服务将它注册为模型名时可直接用作 `VLM_MODEL`；否则填写该服务实际注册的模型 ID。使用网关接入其他系列时，同样以网关的协议和模型名为准。

GPT Responses 示例（模型 ID 和 API base 通过环境注入）：

```bash
export VLM_API_BASE='https://api.openai.com/v1'
export VLM_MODEL='gpt-4.1'
unset VLM_REASONING_EFFORT
# 单独设置 VLM_API_KEY；policy.yaml 中设 api_style: responses。
```

Qwen 兼容 Chat 示例：

```bash
export VLM_API_BASE='https://dashscope.aliyuncs.com/compatible-mode/v1'
export VLM_MODEL='qwen2.5-vl-72b-instruct'
unset VLM_REASONING_EFFORT
# 单独设置 VLM_API_KEY；policy.yaml 中设 api_style: chat_completions，
# chat_token_parameter: max_tokens；不支持 JSON Schema 时设 structured_output: false。
```

## 在 LIBERO 评测中配置与切换

### 1. 确认修改的是策略配置

从当前仓库根目录操作，修改 `examples/gpt6_vlm/policy.yaml` 中已有的 `model` 字段，保留动作、观测、grounding 等其他配置。上面的最小 YAML 仅展示模型字段，不能直接覆盖完整 LIBERO profile。`examples/gpt6_vlm/benchmark.yaml` 不接收模型 API 参数；`gpt6_vlm` 只是 profile 名称，可以运行上表的其他视觉模型。

按系列选择以下字段；`chat_token_parameter` 仅影响 `chat_completions`，其他协议会使用自己的 token 字段。

| 系列 | `model.api_style` | `model.chat_token_parameter` | `model.structured_output` |
| --- | --- | --- | --- |
| GPT | `responses`，兼容服务也可用 `chat_completions` | Chat 默认 `max_completion_tokens` | 服务和模型接受动作 schema 时设 `true` |
| Claude | `anthropic_messages` | 不适用，原生发送 `max_tokens` | 接受 `output_config.format` 及动作 schema 时设 `true` |
| Gemini | `gemini_generate_content` | 不适用，原生发送 `maxOutputTokens` | 接受 `responseJsonSchema` 及动作 schema 时设 `true` |
| DeepSeek 视觉服务 | `chat_completions`（须由部署服务实现） | 按服务协议，可设 `max_tokens` | 按实际视觉服务的 JSON Schema 能力设置 |
| Qwen | `chat_completions` | 兼容服务可设 `max_tokens` | 按具体视觉模型的 JSON Schema 能力设置 |
| GLM | `chat_completions` | 兼容服务可设 `max_tokens` | 按具体视觉模型的 JSON Schema 能力设置 |
| Kimi | `chat_completions` | 兼容服务可设 `max_tokens` | 按具体视觉模型的 JSON Schema 能力设置 |

例如接入 Qwen 时，修改已有 `model` section 中的以下字段：

```yaml
model:
  backend: provider_api
  api_style: chat_completions
  chat_token_parameter: max_tokens
  api_base_env: VLM_API_BASE
  api_key_env: VLM_API_KEY
  model_name_env: VLM_MODEL
  effort_env: VLM_REASONING_EFFORT
  structured_output: false
  max_output_tokens: 16384
```

这里用 `structured_output: false` 演示不发送服务端 JSON Schema 的接法，不表示所有 Qwen 型号都不支持结构化输出。确认所选模型支持本项目完整动作 schema 后可改为 `true`。`max_output_tokens` 也应按模型上限、动作长度和推理预算调整。模型仍须输出合法动作 JSON；profile 开启 `require_grounding` 时仍须输出 grounding。

GPT、Claude、Gemini 分别将 `api_style` 改为 `responses`、`anthropic_messages`、`gemini_generate_content`；DeepSeek 视觉服务、GLM、Kimi 使用表中 Chat 配置，并按服务能力调整 token 字段与结构化输出开关。不要仅修改模型 ID 而保留错误的 API 协议。

### 2. 每个服务保存独立的私有 JSON

例如在仓库和结果目录之外创建 `~/.config/paos/libero/qwen_vl.json`，填入：

```json
{
  "VLM_API_BASE": "https://dashscope.aliyuncs.com/compatible-mode/v1",
  "VLM_API_KEY": "replace-with-your-api-key",
  "VLM_MODEL": "qwen2.5-vl-72b-instruct",
  "VLM_REASONING_EFFORT": ""
}
```

其他系列分别保存为 `gpt.json`、`claude.json`、`gemini.json`、`deepseek_vl.json`、`glm_vl.json`、`kimi_vision.json` 即可；字段名相同，将 base、模型 ID 替换成上方对应示例或部署服务实际提供的值，密钥使用对应服务的密钥。文件名不会选择协议。不要在私有 JSON 中增加 `api_style` 或其他字段：协议属于 policy YAML，加载器只接受上述四个 JSON 键。

```bash
export MODEL_CONFIG="$HOME/.config/paos/libero/qwen_vl.json"
chmod 600 "$MODEL_CONFIG"
# 使用私有 JSON 时，清理当前终端中优先级更高的旧配置。
unset VLM_API_BASE VLM_API_KEY VLM_MODEL VLM_REASONING_EFFORT
VLM_ENV_FILE="$MODEL_CONFIG" ./operator-vlm-action-policy.sh \
  --config examples/gpt6_vlm/policy.yaml --check-env --check-config
```

`VLM_REASONING_EFFORT` 的 JSON 值也应清空；只在 shell 中 unset 不能阻止 JSON 重新提供非空值。Claude/Gemini 的原生协议目前要求它为空；其他模型也应确认支持后再设置。已有 Dora/PAOS daemon 可能携带旧的非空环境变量，必须同时检查节点实际继承的环境；当前终端中的 unset 不会清理已运行 daemon 的环境。

### 3. 配置完成后重新 prepare

在当前仓库根目录运行；示例假定已安装依赖，且集成仓库的 gateway/benchmark 已准备好：

```bash
export LIBERO_ROOT=/home/gx/python_project/gitlab/libero
export MODEL_CONFIG="$HOME/.config/paos/libero/qwen_vl.json"
export GATEWAY_BIN="$HOME/.PhyAgentOS/forge_runtime/nodes/gateway/versions/gateway-1.1.0-linux-x86_64/gateway"
export RUN_DIR="$PWD/work2/qwen_vl_$(date +%Y%m%d_%H%M%S)"

.venv/bin/python scripts/eval_libero.py prepare \
  --work-dir "$RUN_DIR" \
  --gateway-bin "$GATEWAY_BIN" \
  --model-config "$MODEL_CONFIG" \
  --tasks 2 --init-states 0 --num-runs 1 --max-steps 20 \
  --port 19035 --gl egl
```

当前集成脚本 `scripts/eval_gpt6_vlm.py` 的 `--api-style` 仅接受 `chat_completions` 和 `responses`。使用 Claude/Gemini 时，先在当前仓库的 `examples/gpt6_vlm/policy.yaml` 设置原生协议，prepare 时**省略 `--api-style`**，脚本会保留源 profile 的值。不要传 `--api-style anthropic_messages` 或 `--api-style gemini_generate_content`，也不要等到 drive 阶段才改协议。上述省略参数的方式同样适用于其他系列。

prepare 默认要求 `$LIBERO_ROOT/build/benchmark-policy-errors/libero_benchmark` 通过精确身份/action ACK 自检；可用 `--benchmark-bin` 指定其他制品。只有使用不支持该检查的旧 benchmark 时，才显式增加 `--legacy-observations`，并接受旧观测协议的限制。

prepare 后检查 `$RUN_DIR/policy.yaml` 的协议、token 字段和结构化输出开关，再按 [真实仿真说明](../examples/gpt6_vlm/TESTING.md) 启动 Dora、drive 和收集结果。不要手改已 prepare 的 YAML：manifest 会检查摘要。切换模型时先更新源 policy 和私有 JSON，再 prepare 新运行目录并重新启动节点；`drive --work-dir` 不会替换常驻节点的模型。

## 请求、返回值与错误处理

四种协议都传入任务文字、本体状态、当前主视角和腕部 PNG 图像；启用历史图像后也传入上次规划的图像。Claude 使用 base64 image source，Gemini 使用 inlineData，Chat/Responses 使用各自的图像字段。

`structured_output: true` 分别发送 Chat 的 `response_format.json_schema`、Responses 的 `text.format`、Claude 的 `output_config.format` 或 Gemini 的 `generationConfig.responseJsonSchema`。厂商和型号支持的 JSON Schema 子集可能不同；本项目动作 schema 包含数组长度等约束，服务拒绝时可显式设为 false。不会自动重试成其他协议，也不会默默关闭结构化输出。关闭后仍在提示词中提供完整 schema，并对返回 JSON 执行同样的动作校验。

`effort_env` 仅映射 Chat 的 `reasoning_effort` 与 Responses 的 `reasoning.effort`。Claude/Gemini 的原生推理配置具有不同语义，本实现暂不映射：这两种协议要求对应环境变量未设置或为空，非空时离线检查就会失败。部分兼容 Chat 服务也不接受推理强度参数，使用时应清空该变量。

返回文本必须是动作 JSON 对象，启用 grounding 时还须包含 grounding。拒绝、截断、工具调用、非 JSON 或缺失字段均按错误返回；模型输出继续经过完整 H×D、物理范围、观测身份与动作回执检查。所有协议沿用单 worker 和推理截止时间，API key 放在请求头中，不写入 URL 或诊断日志。

## 验证与上线

```bash
./operator-vlm-action-policy.sh --config examples/gpt6_vlm/policy.yaml --check-env --check-config
```

该命令检查 YAML、环境变量和协议配置，不请求模型。通过后，还需用实际部署账户完成双相机请求、动作 JSON 解析和单任务闭环验证，再运行固定任务集、初始状态、H/M 的正式评测。报告中记录实际模型 ID、API 协议、token 配置、延迟、错误与任务成功率；不要仅凭品牌或端点名称宣称七个系列已全部通过评测。

参考官方接口文档（本地环境未完成这些网页的在线抓取，模型可用性仍需部署时核验）：

- [OpenAI 图像输入](https://developers.openai.com/api/docs/guides/images-vision)
- [Anthropic 视觉输入](https://platform.claude.com/docs/en/build-with-claude/vision)
- [Gemini 图像理解](https://ai.google.dev/gemini-api/docs/image-understanding)
- [DeepSeek-VL2 权重与推理示例](https://github.com/deepseek-ai/DeepSeek-VL2)
- [Qwen 视觉理解 API](https://help.aliyun.com/zh/model-studio/vision)
- [GLM 视觉模型](https://docs.bigmodel.cn/cn/guide/models/vlm/glm-4v-plus)
- [Kimi 视觉模型](https://platform.moonshot.cn/docs/guide/use-kimi-vision-model)
