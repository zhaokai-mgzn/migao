# 生产语音识别走 Token Plan HTTP 通道（不是实时 WebSocket）

> 适用：生产用阿里云**百炼 Token Plan 订阅**（API key 前缀 `sk-sp-`）的部署面。
> 关联 issue #8987（2026-11-21 生产实测）。官方契约：
> <https://help.aliyun.com/zh/model-studio/token-plan-speech-recognition>

## 一句话

订阅里唯一可用的语音识别模型 `qwen-audio-3.0-asr-flash` 是**非实时**的：它走
**与商品生图完全相同**的多模态端点（HTTP POST），**不接** WebSocket 实时识别。
所以生产要把 `ASR_MODE` 设成 `http`，`realtime` 通道保留为回滚口。

## 端点与请求形态

```
POST https://token-plan.cn-beijing.maas.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation
Authorization: Bearer <sk-sp key>
Content-Type: application/json

{
  "model": "qwen-audio-3.0-asr-flash",
  "input": {"messages": [{"role": "user", "content": [
    {"type": "input_audio", "input_audio": {"data": "data:audio/wav;base64,<b64>"}}
  ]}]},
  "parameters": {"format": "wav", "sample_rate": 16000, "language_hints": ["zh"]}
}
```

- 端点 URL 与生图**同一个**（`/api/v1/services/aigc/multimodal-generation/generation`），
  两个面各自有独立配置项（`ASR_HTTP_URL` / `IMAGE_GEN_BASE_URL`），改一个不影响另一个。
- 响应：识别文本 = **`output.text`**；句子级 = `output.sentence.text`（含 `words`）；时长 = `usage.duration`。
- `input_audio.data` 也可以直接填**公网 URL**（本仓当前不落盘、只发 base64 data-URI）。
- 限制：单次音频 ≤ 5 分钟；`wav` / `mp3` / `opus` 等。

## 🔴 最容易卡的坑：`parameters.format` 必填

少了 `parameters.format`，网关直接回 **`400 {}`** —— **空 body**、**约 90ms 拒单**、没有任何
`message` 可读，日志里也看不到原因（这正是 2026-11-21 卡了半天的直接原因）。
同一请求加上 `"parameters": {"format": "wav"}` 立刻 200。

⇒ 生产排查顺序：**先看请求体有没有 `parameters.format`**，再怀疑 key / 模型 / 网络。
本仓把它固化成注入式判据（把实现里的 `parameters` 块删掉，判据必须红）：
`backend/ai-agent-service/tests/test_asr_http_mode.py`（用例 `API-024`）。

## 配置

| 配置项 | 缺省 | 说明 |
|---|---|---|
| `ASR_MODE` | `realtime` | **缺省不变**（既有实时流式通道，逐字保留为回滚口）；生产切 `http` |
| `ASR_HTTP_MODEL` | `qwen-audio-3.0-asr-flash` | 非实时通道模型（与实时模型 `ASR_MODEL` 不是同一个名字） |
| `ASR_HTTP_URL` | 上面的 MaaS 端点 | 可用 env 覆盖 |
| `ASR_API_KEY` | 空 ⇒ fail-closed | Token Plan 的 `sk-sp-` key（语音 / 生图共用同一个 MaaS 账号） |

生产切换（部署侧动作，**不在代码 PR 里**）：在 `.env.ai-agent` 里写 `ASR_MODE=http`
（`ASR_HTTP_MODEL` / `ASR_HTTP_URL` 用缺省即可），然后按发布线重新部署 ai-agent-service。

## 错误口径（沿用既有对外语义）

| 上游返回 | 内部异常 | 对外 |
|---|---|---|
| 401 / 403 | `ASRAuthError` | 503「语音识别服务暂时不可用」（**账号级**：换 key 才会好，重试没用） |
| 429 | `ASRQuotaError` | 503（配额：等额度 / 换套餐） |
| 5xx / 网络 / 非 JSON | `ASRUnavailableError` | 503（可稍后重试） |
| 200 但文本为空 | `ASRNoSpeechError` | 400「未识别到语音内容」（静音 / 没说话） |
| 400 | `ASRUnavailableError` | 503（**先查 `parameters.format`**） |

日志只记**状态码**与异常类型：**不得**出现 API key，也**不得**出现响应体（响应体可能回显请求片段）。

## 回滚

把 `ASR_MODE` 改回 `realtime`（或删掉该变量）即回到既有实时流式通道 ——
实时通道的代码与端点（`ASR_WEBSOCKET_BASE_URL`）**一个字节没动**。

## 实测证据

2026-11-21 16:45，生产容器内对上面的端点发同一份请求：

- 带 `"parameters": {"format": "wav"}` ⇒ `200`，`output.text`
- 去掉 `parameters.format` ⇒ `400`，**空 body**

判据与 CI：`backend/ai-agent-service/tests/test_asr_http_mode.py`（`# case_ids: API-024`），
CI job = `ai-agent-tests.yml`。
