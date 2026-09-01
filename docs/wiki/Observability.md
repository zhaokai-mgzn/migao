# 可观测性（阿里云 ARMS 大模型可观测）落地

> **2026-09-01 定案**：生产可观测性采用阿里云 ARMS 大模型可观测（Agent 观测与优化 AgentLoop），通过官方 Python 探针（基于 OpenTelemetry 标准）对 LangGraph 应用自动埋点。本文档为生产落地唯一依据；开发/测试环境可选 LangSmith 免费档（见 §8）。

## 1. 背景与选型结论

- **现状缺口**：ai-agent-service（LangGraph 双 Agent：小布/米宝）目前仅有 `loguru` + `RequestLoggingMiddleware`（request_id）日志与 circuit_breaker/fallback，缺少图内逐节点 trace、LLM 调用级观测、token 成本、bad case 回放。
- **选型结论**：
  - 生产监控 → **ARMS 大模型可观测**（数据留阿里云、零业务代码埋点、成本≈0）；
  - 开发调试 → 可选 **LangSmith Developer 免费档**（5k traces/月，SDK 已随 langchain-core 安装，仅配环境变量）；
  - 评估回归平台化（deep-eval-migao）→ 独立议题，后续单独评估，与本方案解耦。
- **成本结论**（万级/天 ≈ 30 万会话/月）：月写入 ≈ 44GB（38GB 链路 + 6GB 指标保底）< 50GB 免费额度 → **≈ 0 元/月**；超出按 0.4 元/GB。详见 §7。

## 2. 前置条件（一次性）

| 项 | 说明 | 获取方式 |
|---|---|---|
| 开通 ARMS 应用监控 | 新版按写入量计费，新用户默认 | 阿里云控制台搜索「应用实时监控服务」开通 |
| `ARMS_REGION_ID` | 与资源同地域（如 `cn-hangzhou`） | 账号 RegionID |
| `ARMS_LICENSE_KEY` | 探针上报凭证 | 控制台/OpenAPI「获取应用可观测」接口返回值 `authToken` 字段 |
| SWAS 出站连通性 | 服务器能访问 ARMS 采集端点 | 开通后在服务器 `curl` 验证（端点以控制台为准） |

> ⚠️ `ARMS_LICENSE_KEY` 属敏感凭证：生产走服务器侧 `.env.ai-agent`（不入仓，与现有 env 约定一致），禁止写进 Dockerfile 或镜像。

## 3. 接入改造（ai-agent-service，Python 探针手动接入）

官方步骤：`pip install aliyun-bootstrap` → `aliyun-bootstrap -a install` → 环境变量 → `aliyun-instrument python app.py` 启动。

### 3.1 Dockerfile（`backend/ai-agent-service/Dockerfile`）

```dockerfile
# 在 pip install requirements.txt 之后、USER app 之前（需 root 权限安装探针）：
RUN pip install --no-cache-dir aliyun-bootstrap -i ${PIP_INDEX_URL} \
        --trusted-host mirrors.aliyun.com --trusted-host pypi.org --trusted-host files.pythonhosted.org \
    && aliyun-bootstrap -a install

# CMD 改为经 aliyun-instrument 启动（注意保持 --workers 1，探针按进程装载）：
CMD ["sh", "-c", "aliyun-instrument python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1 --timeout-keep-alive 65"]
```

- 探针**不要加进 `requirements.txt`**：CI/本地测试不加载探针，避免影响单测与 gate。
- `ARMS_*` 环境变量通过 compose env_file 注入（§3.2），不写进 Dockerfile。

### 3.2 生产 compose（`deploy/swas/docker-compose.yml` + 服务器侧 `.env.ai-agent`）

`.env.ai-agent`（服务器侧）新增：

```bash
ARMS_APP_NAME=migao-ai-agent-prod   # dev/测试环境用 migao-ai-agent-dev 区分项目
ARMS_REGION_ID=cn-hangzhou          # 以实际地域为准
ARMS_LICENSE_KEY=<LicenseKey>
```

`docker-compose.yml` 的 `ai-agent` 服务：**`mem_limit: 1024m` → `1280m`**（探针内存开销约 100-200MB；注意 SWAS 单机内存总量，4 容器已分配 3328m）。`env_file: .env.ai-agent` 无需改动（新增变量自动注入）。

### 3.3 代码配合点（接入 trace 完整性的两个必改项）

1. **流式 Token 用量**（官方明确：流式调用须开启 `stream_usage` 才能采集 Token 用量）：
   - `app/llm/factory.py`：`create_skill_llm`（约 L54-62）与 `create_vision_llm`（约 L83-91）的 kwargs 增加 `stream_usage=True`。
   - ⚠️ 实施时验证 `ChatDeepSeek`（langchain-deepseek）对 `stream_usage` 参数的支持；不支持则仅在 `ChatOpenAI` 分支传入（CI 回退路径为 ChatOpenAI）。
2. **会话/租户维度关联**（官方支持 LangGraph `config.metadata` 透传 session_id/user_id）：
   - `app/api/chat.py` `_agent_stream_to_sse`（约 L513 `agent.astream_chat(...)` 调用点）已有 `session_id`/`tenant_id`/`customer_id` 上下文，将三者经 LangGraph `config={"metadata": {...}}` 传入 graph run，用于 ARMS 按会话/租户统计与过滤。

### 3.4 验证步骤

1. 本地/dev 起服务 → 控制台 **ARMS → LLM 应用监控 → 应用列表** → 点击应用查看 trace（图节点、LLM 调用、工具调用、Token 用量）。
2. 构造一次多轮对话（含工具调用，如订单查询）→ 确认瀑布图中出现完整链路与 Token 用量。
3. 控制台 **概览 → 用量统计** 查看实际写入量，与 §7 估算比对。

## 4. 用量限额与告警（必须配置）

- 免费额度 50GB/月按账号共享（指标 25GB + 链路 25GB），**建议接入后立即设置**：
  - 控制台 用量统计 → **设置限额**：写入量上限（建议 45GB 触发告警）+ 告警通知对象（钉钉/短信）。
- ARMS 免费留存 90 天（bad case 复盘窗口足够）。

## 5. 与现有可观测体系的关系

| 层 | 工具 | 职责 | 是否保留 |
|---|---|---|---|
| 请求日志 | loguru + RequestLoggingMiddleware | request_id、状态码、耗时、错误 | **保留**（trace 是叠加，不是替代） |
| 图内 trace | ARMS 探针（自动） | 节点/LLM/工具/Token 链路 | 新增 |
| 兜底指标 | circuit_breaker / fallback | 熔断与降级状态 | 保留 |
| 关联手段 | request_id ↔ traceId | 排障时日志与 trace 互查 | 后续验证 HTTP span 是否自动携带 X-Request-ID；长期可把 request_id 写入 LangGraph metadata |

## 6. 生产上线检查清单

- [ ] ARMS 已开通，LicenseKey/RegionID 已获取
- [ ] SWAS 出站到 ARMS 采集端点连通性已验证
- [ ] Dockerfile 探针安装（root 阶段）+ CMD 改 `aliyun-instrument` 启动
- [ ] `.env.ai-agent` 注入 3 个 `ARMS_*` 变量（服务器侧）
- [ ] `ai-agent` 服务 `mem_limit` 已上调（1024m → 1280m），SWAS 内存余量确认
- [ ] `factory.py` 流式 LLM 加 `stream_usage=True`（含 ChatDeepSeek 兼容性验证）
- [ ] `chat.py` 图调用传入 `session_id/tenant_id/customer_id` metadata
- [ ] 用量限额 + 告警已配置
- [ ] 生产验证：真实会话在 ARMS 控制台可见完整 trace 与 Token 用量
- [ ] 回滚预案：CI 重建镜像（去探针 CMD）+ 移除 `.env.ai-agent` 变量即可恢复（`stream_usage`/metadata 改动无害可保留）

## 7. 成本与额度管理

| 项 | 数值 |
|---|---|
| 免费额度 | 指标 25GB + 链路 25GB = **50GB/月**（账号级共享） |
| 超出单价 | **0.4 元/GB**（中国内地公有云） |
| 留存 | 90 天（免费） |
| 30 万会话/月估算 | 38GB 链路 + 6GB 指标保底 ≈ **44GB（免费额度 88%）** |
| 60 万会话/月（翻倍） | 约 82GB → **≈ 13 元/月** |

- 口径：1 Span ≈ 1.27KB（阿里云官方）；每次客服会话 ≈ 100 span（多轮 + 工具）。
- 每应用每天每数据类型 0.1GB 保底计费，不影响上述量级结论。
- 决策依据详见仓库内成本评估结论（§1 选型结论 + 本表），以控制台用量统计实际数字为准。

## 8. 开发/测试环境（可选）

- 推荐：ARMS 单独项目名 `migao-ai-agent-dev`，与生产 `-prod` 隔离，避免污染生产统计；
- 或 LangSmith Developer 免费档（5k traces/月）：SDK 已装（langsmith 0.10.18），仅需 `LANGSMITH_TRACING=true` + `LANGSMITH_API_KEY`，用于 trace 回放/调试，不留存生产敏感对话。

## 9. 常见问题排查

| 现象 | 可能原因 | 处理 |
|---|---|---|
| 控制台看不到应用 | CMD 未走 `aliyun-instrument` / env 缺失 | 检查启动命令与 `ARMS_*` 变量 |
| 数据不上报 | SWAS 出站不通 / LicenseKey 或 Region 错误 | 服务器 curl 验证端点；核对 authToken 与 RegionID |
| 流式无 Token 用量 | 未开 `stream_usage` | 按 §3.3-1 修改 |
| 内存超限重启 | 探针开销 + mem_limit 不足 | 上调 mem_limit，观察 SWAS 内存 |
| 与 langgraph 版本冲突 | 探针版本滞后 | 升级 aliyun-bootstrap，以官方文档兼容性为准 |

## 10. 参考

- [接入 LangChain & LangGraph 应用（官方文档）](https://help.aliyun.com/zh/document_detail/3042580.html)
- [AI Agent 可观测接入总览](https://help.aliyun.com/zh/cms/cloudmonitor-2-0/overview-of-ai-application-monitoring-access)
- [ARMS 产品计费（新版，按写入数据量）](https://help.aliyun.com/zh/arms/product-overview/product-billing-new-version)
- [ARMS 定价页](https://cn.aliyun.com/product/arms/pricing)
- [SearchTraces API 文档](https://help.aliyun.com/en/arms/application-monitoring/developer-reference/api-arms-2019-08-08-searchtraces-apps)（含 RAM 授权说明）
- [LLM Trace Explorer（trace 字段说明）](https://help.aliyun.com/en/arms/application-monitoring/user-guide/llm-trace-explorer)
- [AgentLoop API 概览（2026-05-20）](https://help.aliyun.com/zh/document_detail/3041792.html)
- 相关仓库文档：部署拓扑见 [Deployment](Deployment.md)；AI 服务结构见 [AI-Agent](AI-Agent.md)

## 11. 附录：ARMS 数据读取（CLI / SDK）

> 用途：bad case 复盘、trace 批量拉取对接评估工程（deep-eval-migao）、按会话/租户统计成本。数据读取是**查询能力**，与 §4 写入限额/告警互不影响。

### 11.1 数据分层（先分清"读什么"）

| 数据 | 存储位置 | 读取途径 |
|---|---|---|
| 原始 LLM trace（图节点/LLM/工具 span、input/output、Token） | ARMS 应用监控（探针上报） | `aliyun arms`（CLI）或 ARMS SDK（`SearchTraces/SearchTracesByPage/GetTrace`） |
| AgentLoop 平台数据（数据集/评估任务/实验） | AgentLoop 产品（2026-05-20） | `aliyun agentloop`（需装插件）或 AgentLoop SDK（`ListDatasets/ExecuteQuery` 等） |
| 业务日志（loguru + request_id） | 自有日志（容器 stdout/SLS 另配） | 与 ARMS 互补，不在 ARMS 内 |

> ⚠️ ARMS 存的是 **trace 结构数据，不是业务日志原文**；trace 里的 Token 用量依赖 §3.3-1 的 `stream_usage` 已开启。

### 11.2 前置条件：最小权限 RAM 用户

创建只读 RAM 用户并授予以下策略（禁止用主账号 AccessKey）：

```json
{
  "Version": "1",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "arms:SearchTraces",
        "arms:SearchTracesByPage",
        "arms:GetTrace",
        "arms:GetMultipleTrace",
        "arms:ListTraceApps",
        "arms:SearchTraceAppByName",
        "arms:DescribeTraceLicenseKey"
      ],
      "Resource": "*"
    }
  ]
}
```

### 11.3 aliyun CLI 查询（ad-hoc 排障用）

本地已装 `aliyun` CLI 3.4.11，`arms` 产品内置（API 版本 2019-08-08），`aliyun configure` 配置好 RAM 用户密钥即可：

```bash
# ① 查 trace 列表（StartTime/EndTime 为毫秒时间戳，必填；单页最多 100 条）
aliyun arms SearchTracesByPage \
  --StartTime 1756000000000 --EndTime 1756003600000 \
  --RegionId cn-hangzhou --ServiceName migao-ai-agent-prod \
  --PageNumber 1 --PageSize 100

# ② 查某条 trace 详情（完整 span 树，含 LLM input/output/Token）
aliyun arms GetTrace --RegionId cn-hangzhou --TraceID <traceId>

# ③ 按异常过滤（Tag 数组参数需传 JSON）
aliyun arms SearchTraces --StartTime 1756000000000 --EndTime 1756003600000 \
  --RegionId cn-hangzhou --ServiceName migao-ai-agent-prod \
  --Tag '[{"Key":"isError","Value":"true"}]'
```

AgentLoop 平台数据（可选）：`aliyun plugin install --names aliyun-cli-agentloop` 后可用 `aliyun agentloop ListDatasets --RegionId cn-beijing ...`，非必需。

### 11.4 Python SDK 批量拉取（程序化消费，对接评估工程）

```bash
pip install alibabacloud_arms20190808
```

```python
"""按时间窗口分页拉取 migao trace 列表并获取详情（字段名以当前 SDK 版本为准）。"""
from alibabacloud_arms20190808.client import Client
from alibabacloud_arms20190808 import models as arms_models
from alibabacloud_tea_openapi import models as open_api_models

client = Client(open_api_models.Config(
    access_key_id="<AK>",
    access_key_secret="<SK>",
    endpoint="arms.cn-hangzhou.aliyuncs.com",   # 与 ARMS_REGION_ID 一致
))

page, total = 1, 0
while True:
    resp = client.search_traces_by_page(arms_models.SearchTracesByPageRequest(
        start_time=1756000000000,                # 毫秒时间戳
        end_time=1756003600000,
        region_id="cn-hangzhou",
        service_name="migao-ai-agent-prod",
        page_number=page,
        page_size=100,
    ))
    infos = resp.page_bean.trace_infos or []
    for info in infos:
        detail = client.get_trace(arms_models.GetTraceRequest(
            region_id="cn-hangzhou",
            trace_id=info.trace_id,
        ))
        # detail.spans 含每个 span 的 input/output/token/attribute；
        # 通过 metadata 里的 session_id/tenant_id/customer_id 维度聚合（§3.3-2）
        yield info.trace_id, detail
    total += len(infos)
    if total >= resp.page_bean.total:
        break
    page += 1
```

### 11.5 限制与注意

| 限制 | 说明 |
|---|---|
| 单页上限 | `SearchTraces` 最多 100 条；全量必须用 `SearchTracesByPage` 分页 |
| 查询语义 | 读的是 trace 结构数据，不是业务日志；loguru 日志需另配 SLS 才能程序化查询 |
| 权限 | 只读 RAM 用户 + 最小权限；密钥泄露风险按账号安全规范管控 |
| Token 完整性 | 流式 Token 用量依赖 `stream_usage=True`（§3.3-1），未开则字段为空 |
| 地域 | API 的 RegionId 必须与探针上报地域一致 |
