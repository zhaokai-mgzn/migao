# CLAUDE.md — 项目指令

> 本文件在每次 Claude Code (cc) 启动时自动加载，定义项目规范和操作约束。

## GitHub 操作规范

**所有 Issue、PR、分支、Label、CI/CD 操作必须遵循 `github-ops` skill 规范。**

核心铁律：
- **禁止直接 push 到 `main`**，必须走 PR
- 所有 PR 必须关联 Issue（`Fixes #xxx` / `Closes #xxx`）
- 所有 Issue 必须打 Label（角色 + 类型）
- 发现问题自动创建 Issue → 立即修复 → 不询问用户
- 测试失败自动创建 Issue → 自动修复
- 互不阻塞的任务**并行**派遣

操作前执行 `/github-ops` 加载完整规范。

## 研发范式：TDD（测试驱动开发）

**本项目严格遵循 TDD 研发范式，所有功能开发必须遵循以下流程：**

### Red → Green → Refactor

```
1. Red（红）   → 先写测试，运行确认测试失败
2. Green（绿） → 写最小实现代码，让测试通过
3. Refactor    → 重构代码，保持测试持续通过
```

### 各模块测试要求

| 模块 | 测试类型 | 工具 | 覆盖率要求 |
|------|---------|------|-----------|
| admin-api | 单元测试 + 集成测试 | JUnit 5 + MockMvc + TestContainers | 核心 Service ≥ 80% |
| ai-agent-service | 单元测试 + 集成测试 | pytest + httpx | 核心工具 ≥ 80% |
| admin-web | 组件测试 + E2E 测试 | Playwright (tests/e2e/) + Testing Library | 关键页面 100% |
| 全链路 | E2E 冒烟测试 | Playwright (tests/smoke/) | 核心流程 100% |

### 铁律

- **禁止**先写代码再补测试 — 必须测试先行
- **禁止**提交未通过测试的代码到任何分支
- 每个 PR 必须包含对应的测试用例
- CI 流水线中测试不通过 → **禁止合并**
- 发现 Bug 时：先写一个能复现 Bug 的失败测试 → 修复代码 → 测试通过
- E2E 测试必须覆盖所有页面的核心交互路径

### 测试分层策略

```
           ┌─────────────┐
           │  E2E 冒烟    │  ← Playwright，覆盖核心用户流程
           ├─────────────┤
           │ 集成测试     │  ← API 端到端，数据库真实交互
           ├─────────────┤
           │ 单元测试     │  ← 纯逻辑，Mock 外部依赖
           └─────────────┘
```

## 项目概述

优客 AI 智能客服系统 — 面向布艺行业的多租户 SaaS 平台。

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
│   ├── docker-compose.yml  # 本地开发
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
# Java 后端
cd backend/admin-api
./mvnw clean compile
./mvnw test
./mvnw clean package -DskipTests

# Python AI 服务
cd backend/ai-agent-service
pip install -r requirements.txt
pytest tests/ -v

# 前端管理后台
cd frontend/admin-web
npm install
npm run build
npx tsc --noEmit

# E2E 浏览器测试（Playwright，对 admin-web 全链路）
cd tests
npm install && npx playwright install chromium
npm run e2e                              # 对云 dev 环境：BASE_URL=https://dev.example.com npm run e2e

# E2E 冒烟测试（pytest，对后端 API）
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
| `/verification-before-completion` | 声称任务完成前，必须运行验证命令并确认输出 |
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
