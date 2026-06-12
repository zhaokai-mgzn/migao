# CLAUDE.md — 项目指令

> 本文件在每次 Claude Code (cc) 启动时自动加载，定义项目规范和操作约束。

## 项目 Wiki

> **开发前先查 [`docs/wiki/INDEX.md`](docs/wiki/INDEX.md)** — 按场景索引：架构、AI Agent、部署、开发规范。
> 每个页面 ~50 行，按需 Read，节省上下文。

## GitHub 操作规范

**所有 Issue、PR、分支、Label、CI/CD 操作必须遵循 `github-ops` skill 规范。**

核心铁律：
- **禁止直接 push 到 `main`**，必须走 PR
- **本地单测 + 集测全绿才能合并** — 未完成本地验证的 PR 禁止合并
- 所有 PR 必须关联 Issue（`Fixes #xxx` / `Closes #xxx`）
- 所有 Issue 必须打 Label（角色 + 类型）
- 发现问题自动创建 Issue → 立即修复 → 不询问用户
- 测试失败自动创建 Issue → 自动修复
- 互不阻塞的任务**并行**派遣

操作前执行 `/github-ops` 加载完整规范。

## 研发范式：AI-TDD（AI 强制测试驱动开发）

> **⚠️ 本章是铁律中的铁律，违反即视为严重违规。AI 必须严格遵守，不得跳过任何检查点。**
>
> **📋 完整铁律详见 [`.claude/skills/tdd-iron-law.md`](.claude/skills/tdd-iron-law.md) — 包含 PR 合并前置条件、E2E 质量要求、违规后果。**

### 核心原则

**本项目强制遵循 TDD 研发范式，所有功能开发必须遵循 Red → Green → Refactor 循环。**

```
1. Red（红）   → 先写测试，运行确认测试失败（证明测试有效）
2. Green（绿） → 写最小实现代码，让测试通过
3. Refactor    → 重构代码，保持测试持续通过
```

### AI-TDD 强制流程（7 个检查点，缺一不可）

**每次代码变更前，AI 必须按顺序执行以下 7 个检查点，禁止跳过任何一个：**

#### CP-1：识别变更范围（Identify Scope）

**必须回答**：本次变更涉及哪些模块？涉及哪些文件？

```
□ 后端：admin-api / ai-agent-service
□ 前端：admin-web / mini-app
□ 配置：terraform / CI/CD
□ 测试：新增测试文件 / 修改现有测试
```

**输出**：明确列出受影响的模块和测试文件路径。

#### CP-2：Red 阶段 — 先写测试（Write Tests First）

**铁律：禁止先写实现代码再补测试。**

**测试覆盖范围评估**：
- 新增功能：先写功能测试（单元测试 + 集成测试 + **E2E 测试**）
- 修复 Bug：先写能复现 Bug 的失败测试（单元测试 + **E2E 测试**）
- 重构：先确保现有测试覆盖重构目标

**E2E 测试评估（必须执行）**：
```
□ 检查 tests/e2e/ 目录，确认是否有覆盖本次变更的 E2E 测试
□ 如果没有，评估是否需要新增 E2E 测试：
  - 需要：用户交互流程、API 端点、跨模块集成、数据持久化
  - 不需要：纯内部逻辑、配置变更、文档更新、已有 E2E 覆盖
□ 如果需要，先写 E2E 测试用例（tests/e2e/specs/）
```

**运行测试，确认失败**：
```bash
# 运行新增/修改的测试，必须看到 FAIL
cd backend/ai-agent-service && .venv/bin/python -m pytest tests/test_xxx.py -v
cd backend/admin-api && ./mvnw test -Dtest=XxxTest
cd frontend/admin-web && npx vitest run tests/unit/lib/utils.test.ts
cd tests && npx playwright test tests/e2e/specs/xxx.spec.ts  # 如有新增 E2E
```

**输出**：测试运行结果，必须包含 `FAILED` 或 `FAIL`。

#### CP-3：Green 阶段 — 写最小实现（Implement Minimal Code）

**铁律：只写能让测试通过的最小代码，禁止过度设计。**

- 实现功能代码
- 运行测试，确认通过

```bash
# 运行同一组测试，必须看到 PASS
cd backend/ai-agent-service && .venv/bin/python -m pytest tests/test_xxx.py -v
cd backend/admin-api && ./mvnw test -Dtest=XxxTest
cd frontend/admin-web && npx vitest run tests/unit/lib/utils.test.ts
```

**输出**：测试运行结果，必须包含 `passed` 或 `PASS`。

#### CP-4：Refactor 阶段 — 重构代码（Refactor）

**铁律：重构时必须保持测试持续通过，禁止破坏现有功能。**

- 优化代码结构、消除重复、提升可读性
- 每次重构后运行测试，确认仍然通过

**输出**：重构后的代码，测试仍然 PASS。

#### CP-5：单测全量验证（Full Unit Test）

**铁律：变更涉及的所有模块，必须运行全量单测。**

```bash
# 后端 AI 服务（全量）
cd backend/ai-agent-service && .venv/bin/python -m pytest tests/ -v

# 后端 Java 服务（全量）
cd backend/admin-api && ./mvnw test

# 前端管理后台（全量，注意是 vitest 不是 jest）
cd frontend/admin-web && npx vitest run
```

**输出**：所有单测必须 `passed`，无 `failed`。

#### CP-6：集成测试 + E2E 测试增量验证（Incremental Integration & E2E Test）

**铁律：仅运行本次变更涉及的集成测试和 E2E 测试文件，避免全量回归耗时过长。**

```bash
# 后端 AI 服务（增量，替换为实际涉及的测试文件）
cd backend/ai-agent-service && .venv/bin/python -m pytest tests/test_vision_integration.py -v

# 后端 Java 服务（增量，替换为实际涉及的测试类）
cd backend/admin-api && ./mvnw test -Dtest=OrderServiceTest,ProductControllerTest

# 前端类型检查（必跑）
cd frontend/admin-web && npx tsc --noEmit

# E2E 测试（增量，替换为实际涉及的测试文件）
# 注意：跑 E2E 前需重启本地服务，详见 tests/README.md
cd tests && npx playwright test tests/e2e/specs/products.spec.ts
```

**输出**：所有集测必须 `passed`，`tsc` 必须 `EXIT: 0`，E2E 测试必须 `passed`（如有新增）。

#### CP-7：完成自检清单（Self-Check Before Completion）

**铁律：声称"完成"或准备合并 PR 前，必须逐项勾选以下清单。**

```
□ CP-1：已识别变更范围，列出受影响模块
□ CP-2：已先写测试，运行确认 FAIL
□ CP-3：已写实现代码，运行确认 PASS
□ CP-4：已重构代码，测试仍 PASS
□ CP-5：已运行所有受影响模块的全量单测，全部 PASS
□ CP-6：已运行本次变更涉及的增量集测 + E2E 测试，全部 PASS
□ CP-7：已完成本自检清单，无遗漏
□ E2E 测试覆盖决策：
  - [ ] 已检查 tests/e2e/ 目录
  - [ ] 已评估是否需要新增 E2E 测试
  - [ ] 已新增 E2E 测试 / 确认已有 E2E 覆盖 / 确认不需要 E2E（需说明原因）
□ 代码符合项目规范（命名、格式、注释）
□ 无硬编码密钥、无敏感信息泄露
□ 已更新相关文档（如有必要）
```

**输出**：勾选完整的自检清单，无 `□` 未勾选项。

### 违规后果

**违反任何检查点，即视为严重违规：**

| 违规行为 | 后果 |
|---------|------|
| 先写实现后补测试 | 立即停止，删除实现代码，回到 CP-2 重做 |
| 跳过单测全量验证 | 禁止合并 PR，必须补跑 |
| 跳过集成测试增量验证 | 禁止合并 PR，必须补跑 |
| **跳过 E2E 测试评估** | **禁止合并 PR，必须执行 E2E 测试覆盖决策** |
| 未完成自检清单就声称"完成" | 视为虚假完成，必须重新执行所有检查点 |
| 测试失败仍然提交代码 | 立即回滚，修复测试后再提交 |

### 各模块测试要求

| 模块 | 测试类型 | 工具 | 覆盖率要求 |
|------|---------|------|-----------|
| admin-api | 单元测试 + 集成测试 | JUnit 5 + MockMvc + TestContainers | 核心 Service ≥ 80% |
| ai-agent-service | 单元测试 + 集成测试 | pytest + httpx | 核心工具 ≥ 80% |
| admin-web | 组件测试 + E2E 测试 | Vitest + Testing Library + Playwright | 关键页面 100% |
| 全链路 | E2E 冒烟测试 | Playwright (tests/smoke/) | 核心流程 100% |

### 测试分层策略

```
           ┌─────────────┐
           │  E2E 冒烟    │  ← Playwright，覆盖核心用户流程
           ├─────────────┤
           │ 集成测试     │  ← API 端到端，连接云 dev 数据库
           ├─────────────┤
           │ 单元测试     │  ← 纯逻辑，Mock 外部依赖
           └─────────────┘
```

### 本地开发环境

> **⚠️ 铁律：本地只启动米高系统 3 个组件，DB/Redis/中间件全部用云 dev。**
>
> 详见 [`.claude/local-dev-config.md`](.claude/local-dev-config.md) — 包含启动命令、连接信息、禁止行为、测试依赖。

- **本地启动**：admin-api (:8080) + ai-agent-service (:8001) + admin-web (:3001)
- **云 dev 环境**：PostgreSQL + Redis + DashVector + DashScope + OSS 全部用云端
- **配置文件**：各模块 `.env` 已预置云 dev 环境的连接信息，禁止改成 localhost

**启动本地服务**（用于真实场景验证）：

```bash
# 1. 启动 admin-api（Java 后端，端口 8080）
cd backend/admin-api && ./mvnw spring-boot:run

# 2. 启动 ai-agent-service（Python AI 服务，端口 8001）
cd backend/ai-agent-service && python -m uvicorn app.main:app --port 8001 --reload

# 3. 启动 admin-web（Next.js 前端，端口 3000）
cd frontend/admin-web && npm run dev
```

启动后可进行真实场景测试：
- 在 admin-web 页面实际操作
- 调用 API 验证端到端流程
- 验证 LLM 真实响应（如图片识别、对话建议）

### 铁律（再次强调）

**所有代码变更必须遵守 `.claude/skills/tdd-iron-law.md`，以下为摘要：**

- **禁止**先写代码再补测试 — 必须测试先行
- **禁止**提交未通过测试的代码到任何分支
- **PR 合并前必须**：① 重启本地服务 ② 全量单测 PASS ③ 增量集成测试 PASS ④ 增量 E2E 测试 PASS
- **禁止**未完成以上 4 步就合并 PR — 缺一不可
- 每个 PR 必须包含对应的测试用例（单测 + 集成 + E2E）
- CI 流水线中测试不通过 → **禁止合并**
- 发现 Bug 时：先写一个能复现 Bug 的失败测试 → 修复代码 → 测试通过
- E2E 测试必须覆盖所有页面的核心交互路径，禁止弱断言
- 新增交互组件必须覆盖完整点击链路（渲染→点击→发送→验证）
- **禁止手写 E2E mock 数据**。使用 Record-Replay 模式：`cd tests && BASE_URL=http://localhost:8080 npx tsx e2e/scripts/record-fixtures.ts` 录制真实 API 响应到 `fixtures/`，测试中 `import fixture from '../fixtures/xxx.json'`
- **新增数据列表页必须在 `tests/e2e/specs/quality/anti-placeholder.spec.ts` 的 `PAGES` 数组中注册**，确保关键列不会全线显示占位符 `-`
- **新增/修改 API 返回字段必须在 `tests/e2e/specs/quality/api-contract.spec.ts` 中验证**：必填字段存在、类型正确（number/string/object）、金额字段不能是 string
- **跨页面数据一致性**：列表页和详情页的同一字段值必须相等（`tests/e2e/specs/quality/cross-page-consistency.spec.ts`）

## 米宝 Skill/Tool 研发标准

> **⚠️ 所有新增或修改的米宝 Skill 和 Tool 必须遵循此标准。**

### Skill 标准化要求

每个 Skill 必须包含：
```
app/graph/skills/
├── {name}_skill.py          # Skill 节点定义 + System Prompt
└── references/
    ├── SKILL-{name}.md      # 元数据：name, domain, tools, triggers, constraints
    └── EXAMPLES-{name}.md   # Few-shot 示例：正确流程 + 反例
```

### Tool 标准要求

| 要求 | 说明 |
|------|------|
| 写操作前校验 | 所有写 Tool 前应有 `validate_input` 校验参数完整性 |
| 错误即建议 | Tool 失败时必须返回 `suggestion` 字段，告诉 LLM 如何修复 |
| confirm 强制 | 写操作前 LLM 必须弹 confirm 卡片，不弹 confirm 就不能调写 Tool |
| 反幻觉 | Prompt 中必须包含 few-shot 示例 + 明确的禁止编造规则 |

### 通用 Skill（兜底）

- `general_skill` 仅持有**只读查询 Tool**，不执行任何写操作
- 用户意图模糊时引导澄清，而非猜测执行
- 引导话术必须具体（✅ "请说'创建商品'" / ❌ "请切换模块"）

### 状态持久化

- 跨 graph 调用的状态必须持久化到 DB（参考 `pending_interact_skill`）
- 新增状态字段必须通过 `test_pending_interact_persistence.py` 验证

### 完整验证命令清单（PR 合并前必须按顺序执行）

```bash
# ═══════════════════════════════════════════════════════════════
# 第〇步：重启本地服务（确保运行最新代码）
# ═══════════════════════════════════════════════════════════════

# 重启 admin-api（Java 后端，端口 8080）
kill $(lsof -t -i :8080) 2>/dev/null
cd backend/admin-api && ./mvnw spring-boot:run &

# 重启 ai-agent-service（Python AI 服务，端口 8001）
kill $(lsof -t -i :8001) 2>/dev/null
cd backend/ai-agent-service && .venv/bin/python -m uvicorn app.main:app --port 8001 --reload &

# 重启 admin-web（Next.js 前端，端口 3001）
kill $(lsof -t -i :3001) 2>/dev/null
cd frontend/admin-web && npm run dev &

# 验证服务就绪
lsof -i :8080 -sTCP:LISTEN && lsof -i :8001 -sTCP:LISTEN && lsof -i :3001 -sTCP:LISTEN

# ═══════════════════════════════════════════════════════════════
# 第一步：单测全量（变更涉及的所有模块）
# ═══════════════════════════════════════════════════════════════

# 后端 AI 服务
cd backend/ai-agent-service && .venv/bin/python -m pytest tests/ -v

# 后端 Java 服务
cd backend/admin-api && ./mvnw test

# 前端管理后台（注意：是 vitest，不是 jest）
cd frontend/admin-web && npx vitest run

# ═══════════════════════════════════════════════════════════════
# 第二步：集成测试增量（仅运行本次变更涉及的文件/类）
# ═══════════════════════════════════════════════════════════════

# 后端 AI 服务 — 真实 LLM 调用（替换为实际涉及的测试类）
cd backend/ai-agent-service && .venv/bin/python -m pytest tests/test_e2e_mibao_scenarios.py -v -k "TestP3InteractiveComponents"

# 后端 Java 服务（替换为实际涉及的测试类）
cd backend/admin-api && ./mvnw test -Dtest=OrderServiceTest,ProductControllerTest

# ═══════════════════════════════════════════════════════════════
# 第三步：类型检查（前端变更必跑）
# ═══════════════════════════════════════════════════════════════

cd frontend/admin-web && npx tsc --noEmit

# ═══════════════════════════════════════════════════════════════
# 第四步：E2E 测试增量（Playwright，对本地服务）
# ═══════════════════════════════════════════════════════════════

cd tests && rm -f e2e/.auth/admin.json
cd tests && BASE_URL=http://localhost:3001 npx playwright test specs/chat/chat.spec.ts --reporter=list

# ═══════════════════════════════════════════════════════════════
# 第五步：完成自检清单（tdd-iron-law CP-7）
# ═══════════════════════════════════════════════════════════════

# 勾选所有检查点，无遗漏后才能声称"完成"
```

**验证通过 → 自动 commit + push + 合并 PR**  
**验证失败 → 禁止合并，必须先修复测试**

## 项目概述

米高 AI 智能客服系统 — 面向布艺行业的多租户 SaaS 平台。

## 技术栈

| 模块 | 技术 |
|------|------|
| admin-api（管理后端） | Java 21 + Spring Boot 3.3 + MyBatis-Plus |
| ai-agent-service（AI 服务） | Python 3.11 + FastAPI + LangChain + LangGraph |
| admin-web（管理前端） | Next.js 14 (App Router) + TypeScript + Tailwind |
| mini-app（微信小程序） | Taro 3.6 + React + TypeScript |
| 数据库 | PostgreSQL 15 + Redis 7 |
| 向量库 | DashVector |
| LLM | 阿里云百炼 DashScope (qwen-3.7-max) |
| 部署 | 阿里云 SAE + RDS + OSS + CDN + Terraform + GitHub Actions |

## 目录结构

```
youke/
├── backend/
│   ├── admin-api/          # Java 管理后端
│   └── ai-agent-service/   # Python AI 服务
├── frontend/
│   ├── admin-web/          # Next.js 管理后台
│   └── mini-app/           # Taro 微信小程序
├── deploy/
│   └── terraform/          # 阿里云 IaC
├── docs/
│   ├── deployment/         # 部署文档
│   ├── architecture/       # 架构文档
│   └── design/             # 设计文档
├── knowledge_base/         # RAG 种子数据
└── tests/
    ├── e2e/                # E2E 浏览器测试（Playwright）
    └── smoke/              # E2E 冒烟测试（pytest）
```

## 分支策略

```
feat/<scope>-<short-desc>     # 新功能
fix/<scope>-<short-desc>      # Bug 修复
chore/<scope>-<short-desc>    # 杂项/配置/文档
```

scope 取值：`frontend` / `backend` / `ai-agent` / `qa` / `infra`

## Commit 规范

```
feat(frontend): 新增商品管理页面
fix(backend): 修复 JWT Token 过期未正确返回 401
test: 补充订单 API 集成测试
refactor(backend): 优化商品查询 SQL 性能
chore: 更新部署文档
```

## 构建与验证命令

```bash
# ═══════════════════════════════════════════════════════════════
# Java 后端（admin-api）
# ═══════════════════════════════════════════════════════════════
cd backend/admin-api
./mvnw clean compile
./mvnw test                              # 单测全量
./mvnw test -Dtest=XxxTest               # 单测增量（指定类）
./mvnw clean package -DskipTests

# ═══════════════════════════════════════════════════════════════
# Python AI 服务（ai-agent-service）
# ═══════════════════════════════════════════════════════════════
cd backend/ai-agent-service
pip install -r requirements.txt
.venv/bin/python -m pytest tests/ -v     # 单测全量
.venv/bin/python -m pytest tests/test_xxx.py -v  # 单测增量

# ═══════════════════════════════════════════════════════════════
# 前端管理后台（admin-web）— 使用 vitest，不是 jest
# ═══════════════════════════════════════════════════════════════
cd frontend/admin-web
npm install
npx vitest run                           # 单测全量
npx vitest run tests/unit/lib/utils.test.ts  # 单测增量
npx tsc --noEmit                         # 类型检查
npm run build

# ═══════════════════════════════════════════════════════════════
# E2E 浏览器测试（Playwright，对 admin-web 全链路）
# ═══════════════════════════════════════════════════════════════
cd tests
npm install && npx playwright install chromium
npm run e2e                              # 对云 dev 环境：BASE_URL=https://dev.example.com npm run e2e

# ═══════════════════════════════════════════════════════════════
# E2E 冒烟测试（pytest，对后端 API）
# ═══════════════════════════════════════════════════════════════
cd tests/smoke && pytest
```

## CI/CD 部署

代码合并到 `main` 分支后，GitHub Actions 自动触发部署：

| 变更路径 | 工作流 | 部署目标 |
|---------|--------|---------|
| `backend/admin-api/**` | deploy-admin-api | SAE (FatJar) |
| `backend/ai-agent-service/**` | deploy-ai-agent-service | SAE (Docker) |
| `frontend/admin-web/**` | deploy-admin-web | OSS + CDN |

详细 CI/CD 文档：[deployment-aliyun.md § 10](docs/deployment/deployment-aliyun.md)

## Skill 使用规范

以下 skill 已纳入项目规范，对应场景必须调用：

### 开发框架（写代码时自动遵循）

| Skill | 触发场景 |
|-------|---------|
| `/next-best-practices` | 编写或修改 Next.js 前端代码（admin-web） |
| `/springboot-tdd` | 编写或修改 Java Spring Boot 后端（admin-api） |
| `/fastapi-templates` | 编写或修改 Python FastAPI 服务（ai-agent-service） |

### 质量保障（每次代码变更必须遵循）

| Skill | 触发场景 |
|-------|---------|
| `/systematic-debugging` | 遇到任何 Bug、测试失败、异常行为时，修复前必须先诊断根因 |
| `/verification-before-completion` | **声称任务完成前，必须完成 AI-TDD CP-1 ~ CP-7 全部检查点，逐项勾选自检清单并确认输出** |
| `/security-review` | 涉及认证、用户输入、密钥、API 端点、支付等敏感功能时 |
| `/code-review-excellence` | PR Review 时，按规范审查代码质量 |
| `/5-whys-root-cause-analysis` | 生产事故分析、反复出现的问题、用户说"找根因""排查问题"时 |

### 阿里云运维（操作云资源时使用）

| Skill | 触发场景 |
|-------|---------|
| `/aliyun-cli-manage` | 通用阿里云 CLI 操作（凭证、Region、API 发现） |
| `/aliyun-oss-ossutil` | OSS 对象存储操作（前端部署、文件上传） |
| `/aliyun-sls-log-query` | SLS 日志查询与故障排查 |
| `/aliyun-dns-cli` | DNS 记录管理（域名解析、CNAME 配置） |
| `/aliyun-cdn-manage` | CDN 缓存刷新、证书更新、域名管理 |
| `/aliyun-dashvector-search` | DashVector 向量检索（RAG 知识库操作） |

### 项目流程

| Skill | 触发场景 |
|-------|---------|
| `/github-ops` | 所有 GitHub 操作（Issue、PR、分支、Label、CI/CD） |
| `/triage` | Issue 分类、优先级评估、准备开发任务 |
| `/writing-plans` | 多步骤功能实现前的计划编写 |

## 已安装插件（Plugin）

以下插件已安装并启用，自动生效无需手动调用：

### LSP 语言服务器（提供代码智能）

| 插件 | 覆盖模块 | 能力 |
|------|---------|------|
| `typescript-lsp` | admin-web (Next.js/TS) | 类型检查、跳转定义、引用查找、错误诊断 |
| `jdtls-lsp` | admin-api (Java/Spring Boot) | 代码补全、重构辅助、类型推导 |
| `pyright-lsp` | ai-agent-service (Python/FastAPI) | 类型检查、LangChain 类型推导 |

### 安全与质量（自动运行）

| 插件 | 作用 |
|------|------|
| `security-guidance` | 三层安全防线：① 写代码时即时模式警告 ② 回合结束 diff 安全审查 ③ git commit 时跨文件漏洞追踪 |
| `code-review` | `/code-review` — 4 个并行 Agent 自动 Review PR（CLAUDE.md 合规 + Bug 扫描 + Git 历史分析） |

### 基础设施与测试

| 插件 | 作用 |
|------|------|
| `terraform` | Terraform IaC 智能辅助（HCL 补全、plan 分析、drift 检测） |
| `playwright` | 浏览器自动化 MCP，用于 admin-web 前端调试和 E2E 测试 |

### 开发效率

| 插件 | 作用 |
|------|------|
| `commit-commands` | `/commit` — 自动生成符合规范的 commit message 并提交 |
| `claude-md-management` | `/revise-claude-md` — 会话结束后自动更新 CLAUDE.md 捕获学习要点 |
