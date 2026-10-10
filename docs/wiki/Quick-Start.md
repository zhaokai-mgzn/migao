# 快速开始

## 前置：RDS 白名单（必做，否则本地服务连不上 dev 库）

本地起服务时，admin-api(:8080) / ai-agent-service(:8001) 会**真实连接云 dev 的 RDS**（`.env` 里是公网地址）。阿里云 RDS 有 IP 白名单：**当前公网 IP 不在白名单 → TCP 被 DROP → 连接挂起 30 秒超时**，本地服务起不来、测试也会被拖慢到小时级（issue #2957 实证）。

```bash
# 查当前公网 IP
curl -s https://ifconfig.me
```

### 添加方式（优先：aliyun CLI 自服务，无需进控制台）

本机 aliyun CLI 已配置运维权限账号（`aliyun configure list` 显示 Valid，区域 cn-hangzhou），**AI 可直接自服务**（2026-09-06 实证 TaskId 707541181）：

```bash
# 1) 查当前白名单（必须：ModifySecurityIps 是整体覆盖语义，先取完整旧列表）
aliyun rds DescribeDBInstanceIPArrayList --DBInstanceId pgm-bp1p7w92k81ob5to

# 2) 把旧列表原样保留 + 追加当前 IP 后整体写回 dev_local 组（禁止覆盖/清空他人 IP；勿动 default 组）
aliyun rds ModifySecurityIps --DBInstanceId pgm-bp1p7w92k81ob5to \
  --SecurityIps "<旧列表,当前公网IP/32>" --DBInstanceIPArrayName dev_local

# 3) 验证
aliyun rds DescribeDBInstanceIPArrayList --DBInstanceId pgm-bp1p7w92k81ob5to
```

手动控制台路径（备用）：阿里云 RDS 控制台 → 白名单设置 → 添加 `当前公网IP/32`。运营商 IP 漂移时更新即可，**不建议 /0**。

**重要边界：白名单只服务于「本地起服务联调」，单测/verify-all 不需要也不允许白名单**——`tests/conftest.py` 已用环境变量把单测的 DATABASE_URL/REDIS_URL 钉死在 localhost（环境变量优先级高于 .env 文件），单测连不上/不连云库是**设计行为**（毫秒级失败走降级）。若本地验证变慢，先查 conftest 隔离是否被破坏，而不是加白名单（见 `docs/testing/test-engineering-standards.md` §6）。

## 本地开发

本地只启 3 组件，DB/Redis/中间件全用云 dev（需先完成上面 RDS 白名单）：
**admin-api(:8080) + ai-agent-service(:8001) + admin-web(:3001)**。

### ⚠️ 先做一次「AI 接线」（否则真实入驻必然静默失败）

`admin-api` 调 ai-agent-service 做入驻 AI 甄别的两个开关**默认值都是坏值**
（`backend/admin-api/src/main/resources/application.yml` 的 `ai-agent:` 块）：

| 变量 | 默认值 | 本地为什么是坏的 |
|---|---|---|
| `AI_AGENT_BASE_URL` | `http://localhost:8000` | 8000 是**容器内**端口（`deploy/docker-compose.yml` 的 `8001:8000`）；本地直起 ai-agent 在 **8001** |
| `AI_AGENT_SERVICE_TOKEN` | **空串** | ai-agent 侧 `verify_service_token` 对空配置 **fail-closed**（拒绝全部内部调用） |

**不给这两个变量的症状（最贵的部分，先认症状再排查）**：`POST /api/auth/register` 返回
`status=rejected` + `message=系统繁忙` + `rejectReason=入驻审核系统繁忙，请稍后重试`
（`review_source=system`，且**不进 24h 冷却** ⇒ 同一个用户会反复撞同一句）；
而同一时刻 `curl http://127.0.0.1:8001/health` 是 `{"status":"healthy"}` —— **服务是好的，坏的是接线**。

### 三件套启动命令（顺序：先 ai-agent，再 admin-api）

```bash
# 1. AI Agent（宿主端口 8001；容器内才是 8000）——必须先起，admin-api 要调它
cd backend/ai-agent-service
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload

# 2. Admin API（:8080）——两条 AI 接线必须显式给，否则真实入驻静默 fail-closed「系统繁忙」
cd backend/admin-api
set -a && . ./.env && set +a
export AI_AGENT_BASE_URL=http://localhost:8001
export AI_AGENT_SERVICE_TOKEN="$(grep -E '^SERVICE_TOKEN=' ../ai-agent-service/.env | cut -d= -f2- | tr -d '\"')"
./mvnw spring-boot:run

# 3. Admin Web（:3001）
cd frontend/admin-web && npm run dev
```

> `AI_AGENT_SERVICE_TOKEN` 必须与 ai-agent 的 `SERVICE_TOKEN` **逐字相同**；
> 上面那条命令直接从 `backend/ai-agent-service/.env` 取值（部署侧同一套做法见
> `deploy/swas/deploy.sh` 的 `.env.admin-api` 自动补齐）。该 `.env` 不在版本库里
> （`.gitignore` 排除），首次本地开发按 `backend/ai-agent-service/.env.example` 建。

### 验证接线真的通了（一条可复制命令 + 期望输出）

```bash
# ① ai-agent 活着
curl -s http://127.0.0.1:8001/health
# 期望输出：{"status":"healthy",...}

# ② admin-api 真的带着 token 打到了内部端点（不带 token ⇒ 必须被拒，不能是「连不上」）
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://127.0.0.1:8001/api/internal/registration/review \
  -H 'Content-Type: application/json' -d '{}'
# 期望输出：401（未带 token 被拒 = 服务在且鉴权在）
```

**判读口径（这一步就是省钱的地方）**：`②` 返回 **401** ⇒ 接线在（服务在跑 + 鉴权生效）；
返回 **`Connection refused`** ⇒ **ai-agent 没在跑**；返回 **503** ⇒ ai-agent 侧 `SERVICE_TOKEN` 没配
（不是你的 admin-api 的错）。**接好线后**同一条入驻请求约 **8 秒**返回 `status=approved`。

### 失败态第一步：先问「依赖的服务在不在跑」

看到任何失败态（尤其 500 / 「系统繁忙」）**先确认依赖服务在不在**：`lsof -i :8001`（ai-agent）、
`lsof -i :8080`（admin-api）。**「ai-agent 没起」与「页面坏了」在观感上无法区分** ——
2026-10-10 实测为此浪费过排查时间（issue #6674）。

### 本地跑不了的边界（正确表现，不是缺陷）

本地 `backend/ai-agent-service/.env` **没有 DeepSeek key** ⇒ 真实 LLM 审核在本地跑不了。
此时入驻的**正确表现** = **请求返回 200**，判定由**规则层**给出
（`review_source` 可能是 `rule` 或 `system`，见 `backend/ai-agent-service/app/api/registration_review.py` 开头的四行语义）；
而**接线坏了**是另一条分支 —— `admin-api` 侧 HTTP 层就失败了（连不上 / 401），
`RegistrationReviewClient` 返回 null ⇒ 驳回「系统繁忙」。**两者都不该被读成「LLM 生效了」**；
需要真 LLM 结论的验证要在**云测试环境**做。

## 构建/测试

```bash
# Java
cd backend/admin-api
./mvnw clean compile           # 编译
./mvnw test                    # 全量单测
./mvnw test -Dtest=XxxTest     # 增量

# Python
cd backend/ai-agent-service
.venv/bin/python -m pytest tests/ -v

# Frontend
cd frontend/admin-web
npx vitest run                 # 单测 (vitest, 非 jest)
npx tsc --noEmit               # 类型检查

# E2E
cd tests && npm run e2e
```

## 环境变量

各模块 `.env` 已预置云 dev 连接信息（**DB/Redis 不许改回 localhost** —— 单测的 localhost 钉死由 `tests/conftest.py` 负责，不靠 `.env`）。

| 模块 | 关键变量 |
|------|---------|
| admin-api | DB_URL, REDIS_URL, JWT_PRIVATE_KEY, JWT_PUBLIC_KEY, **AI_AGENT_BASE_URL（本地 `http://localhost:8001`）、AI_AGENT_SERVICE_TOKEN** |
| ai-agent-service | PRIMARY_API_KEY, PRIMARY_MODEL, DASHVECTOR_*, DB_URL, REDIS_URL, **SERVICE_TOKEN** |
| admin-web | NEXT_PUBLIC_API_URL, NEXT_PUBLIC_AI_URL |

> `AI_AGENT_*` 两条**必须显式在启动环境里给**（见前面「先做一次 AI 接线」）：它们不写进 `.env` 时
> 取的是 `application.yml` 里那两个**坏默认值**（8000 / 空串）。
