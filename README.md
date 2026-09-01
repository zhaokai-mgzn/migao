# AI 智能客服系统（AIKF）

[![CI](https://github.com/zhaokai-mgzn/migao/actions/workflows/pr-check.yml/badge.svg)](https://github.com/zhaokai-mgzn/migao/actions/workflows/pr-check.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

> 面向通用行业的多租户 AI 智能客服 SaaS 平台，以布艺窗帘行业为示例场景。  
> 基于大语言模型（DeepSeek V4 Pro + DeepSeek V4 Flash Vision）+ 31 个业务工具，覆盖售前咨询到售后服务全链路。

## ✨ 核心亮点

- **双 Agent 架构** — C 端客服"小布" + B 端工作助手"米高"，LangGraph 状态图驱动
- **31 个 AI 工具** — 商品搜索、订单管理、物流追踪、客户查询等，自动意图路由
- **多租户 SaaS** — 租户隔离（JWT 派生 tenant_id → MyBatis 租户拦截器 → 字段脱敏）
- **完整业务后台** — 商品、订单、CRM、人工坐席、数据看板等 12+ 管理模块
- **微信小程序** — Taro 跨端框架，SSE 流式对话，原生体验
- **阿里云全栈部署** — SWAS 轻量应用服务器（CI 构建镜像 + 服务器 pull）+ RDS + Redis(Tair) + OSS，GitHub Actions CI/CD

> ℹ️ **知识库（RAG）说明**：POC 阶段暂不开放（决策记录见 `docs/audit-2026-08/06-open-source-production-gap-analysis.md` 决策 D1），知识问答当前走 LLM 通用知识。

## 🏗️ 系统架构

```mermaid
graph TB
    subgraph 客户端
        A[微信小程序<br/>Taro 3.6] --> |SSE| GW[API 网关]
        B[管理后台<br/>Next.js 14] --> |REST| GW
    end

    subgraph 后端服务
        GW --> C[Admin API<br/>Java 21 · Spring Boot 3.3]
        GW --> D[AI Agent Service<br/>Python 3.11 · FastAPI]
        C <--> |Service Token| D
    end

    subgraph 数据层
        C --> E[(PostgreSQL 15<br/>41 张表)]
        C --> F[(Redis 7<br/>会话 / 缓存)]
        D --> E
        D --> F
    end

    subgraph AI 能力
        D --> H[DeepSeek<br/>V4 Pro / V4 Flash Vision]
        D --> I[意图路由 → 工具调用<br/>LangGraph 状态机]
        D --> J[31 Tools<br/>业务工具 + 权限/确认守卫]
    end

    subgraph 基础设施
        K[OSS 对象存储]
        L[CDN 内容分发]
        M[SLS 日志服务]
        N[ACR 容器镜像]
    end
```

## 🛠️ 技术栈

| 层级 | 技术 | 版本 |
|------|------|------|
| **后端 — 管理 API** | Java + Spring Boot + MyBatis-Plus + Spring Security | JDK 21 / Boot 3.3.9 / MP 3.5.8 |
| **后端 — AI 服务** | Python + FastAPI + LangChain + LangGraph | 3.11 / FastAPI 0.115 / LC 0.3.14 / LG 0.2.60 |
| **前端 — 管理后台** | Next.js (App Router) + React + TypeScript + Tailwind CSS | 14.2 / React 18 / TS 5.7 |
| **前端 — 微信小程序** | Taro + React + TypeScript + Sass | 4.2.1 / React 18 |
| **数据库** | PostgreSQL + Redis | PG 15 / Redis 7 |
| **向量数据库** | DashVector（阿里云，RAG 恢复时启用） | — |
| **大语言模型** | DeepSeek V4 Pro (主) + DeepSeek V4 Flash Vision (视觉) | V4-Pro / V4-Flash / V4-Flash-Vision |
| **认证** | RS256 JWT (BouncyCastle) + 微信小程序登录 + 短信验证码 | — |
| **部署** | 阿里云 SWAS + RDS + Redis(Tair) + OSS + GitHub Actions | — |

## 📦 功能概览

### C 端 — AI 智能客服（微信小程序）

| 能力 | 说明 |
|------|------|
| 售前咨询 | 产品推荐、材质介绍、风格搭配、窗帘尺寸计算 |
| 订单服务 | 下单查询、状态跟踪、历史订单 |
| 售后处理 | 退货/换货/投诉、问题跟踪 |
| 物流查询 | 实时物流状态、配送时间预估 |
| 知识库问答 | 基于 LLM 通用知识的产品和 FAQ 问答（RAG 暂不开放，见决策 D1） |
| 图片识别 | 窗帘/面料图片分析（DeepSeek V4 Flash Vision） |
| 人工转接 | AI 自动判断并转接人工坐席 |
| 多轮对话 | 上下文维护、会话记忆、智能追问 |

### B 端 — 管理后台

| 模块 | 说明 |
|------|------|
| 数据看板 | 订单趋势、状态分布、活跃会话、关键指标 |
| 商品管理 | CRUD、SKU 矩阵（颜色×售卖方式×门幅）、加工项关联、批量上下架 |
| 分类管理 | 树形商品分类 |
| 加工项管理 | 窗帘加工工艺（锁边、褶皱、挂钩等）及计价 |
| 订单管理 | 全生命周期（待付款→确认→生产→发货→完成）、发货、退款、跟进状态 |
| 售后工单 | 退货/换货/维修/投诉工单流转 |
| 客户 CRM | 客户画像、标签管理、客户分群、RFM 评分 |
| 人工坐席 | 坐席管理、会话分配、快捷回复 |
| 知识库 | 文档上传与管理（RAG 检索暂不开放，见决策 D1） |
| 通知中心 | 模板消息、规则引擎、多渠道推送 |
| 角色权限 | RBAC 五角色、细粒度权限、动态菜单 |
| 系统设置 | AI 配置（模型/温度/提示词）、租户信息、密码管理 |

## 📁 项目结构

```
migao/
├── backend/
│   ├── admin-api/              # Java 管理后台 API（Spring Boot 3.3）
│   │   ├── src/main/java/com/migao/admin/
│   │   │   ├── controller/     # 27 个 REST Controller
│   │   │   ├── service/        # 23 个业务 Service
│   │   │   ├── entity/         # 44 个数据实体
│   │   │   ├── mapper/         # 44 个 MyBatis-Plus Mapper
│   │   │   ├── dto/            # 请求/响应 DTO
│   │   │   ├── security/       # JWT RS256 + RBAC + 多租户
│   │   │   └── config/         # 全局配置、异常处理、多租户拦截器
│   │   ├── src/test/           # 80+ 单元/集成测试
│   │   ├── pom.xml
│   │   ├── Dockerfile
│   │   └── .env.example
│   │
│   └── ai-agent-service/       # Python AI Agent 服务（FastAPI + LangGraph）
│       ├── app/
│       │   ├── agents/         # 双 Agent：小布（C端）+ 米高（B端）
│       │   ├── api/            # SSE 流式聊天 + 内部 API
│       │   ├── graph/          # LangGraph 状态图（意图路由→工具调用→响应）
│       │   ├── tools/          # 31 个业务工具（注册于 registry.py）
│       │   ├── router/         # 意图分类（LLM + 规则引擎）
│       │   ├── llm/            # LLM 工厂、模型路由、成本追踪
│       │   ├── cache/          # 语义缓存
│       │   └── memory/         # 会话记忆
│       ├── tests/              # 30+ 测试用例
│       ├── requirements.txt
│       ├── Dockerfile
│       └── .env.example
│
├── frontend/
│   ├── admin-web/              # Next.js 14 管理后台（App Router + 静态导出）
│   │   ├── src/app/            # 页面路由（Dashboard、商品、订单、CRM…）
│   │   ├── src/components/     # 40+ React 组件
│   │   ├── src/lib/            # API 客户端、工具函数
│   │   ├── package.json
│   │   └── .env.development / .env.production
│   │
│   └── mini-app/               # Taro 3.6 微信小程序
│       ├── src/pages/          # 对话、会话列表、个人中心
│       ├── src/components/     # 消息气泡、产品卡片、物流卡片等
│       └── package.json
│
├── deploy/
│   ├── swas/                   # SWAS 生产部署（deploy.sh + compose + nginx.conf）
│   ├── docker-compose.yml      # 本地开发（PostgreSQL + Redis + 双后端）
│   └── scripts/                # 部署辅助脚本（swas-deploy-ci.sh）
│
├── docs/
│   ├── wiki/                   # 现役 Wiki（架构/开发/部署/测试，见 INDEX.md）
│   ├── api/                    # API 参考文档
│   ├── design/                 # 产品设计文档
│   ├── deployment/             # 部署踩坑与清单
│   ├── testing/                # 测试工程规范
│   ├── sql/                    # 数据库 Schema + 增量迁移脚本
│   └── audit-2026-08/          # 2026-08 审计与决策记录
│
├── tests/smoke/                # E2E 冒烟测试（pytest）
├── knowledge_base/             # 行业知识种子数据
└── .github/workflows/          # CI/CD（16 个工作流）
```

## 🚀 快速开始

### 前置条件

| 工具 | 最低版本 | 用途 |
|------|---------|------|
| JDK | 21 | admin-api 编译运行 |
| Node.js | 18+ | admin-web 前端 |
| Python | 3.11+ | ai-agent-service |
| Docker + Docker Compose | — | 本地数据库（推荐） |

### 方式一：Docker Compose（推荐）

一键启动数据库和双后端服务：

```bash
cd deploy

# 配置 AI 服务环境变量（首次）
export PRIMARY_API_KEY=your_deepseek_key
export PRIMARY_MODEL=deepseek-v4-flash

# 启动所有服务
docker-compose up --build

# 服务启动后：
# - Admin API:       http://localhost:8080
# - AI Agent:        http://localhost:8001（compose 宿主映射，容器内 8000）
# - PostgreSQL:      localhost:5432
# - Redis:           localhost:6379
```

### 方式二：逐服务启动

#### 1. 启动基础设施

```bash
cd deploy
docker-compose up postgres redis   # 仅启动数据库和缓存
```

#### 2. 启动 Admin API（Java）

```bash
cd backend/admin-api
cp .env.example .env
# 编辑 .env 配置数据库、Redis、JWT 密钥等

./mvnw spring-boot:run
# → http://localhost:8080
```

#### 3. 启动 AI Agent Service（Python）

```bash
cd backend/ai-agent-service
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# 编辑 .env 配置 LLM API Key、数据库、Redis 等

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
# → http://localhost:8000
```

#### 4. 启动管理后台前端（Next.js）

```bash
cd frontend/admin-web
npm install
npm run dev
# → http://localhost:3001
```

#### 5. 启动微信小程序（Taro）

```bash
cd frontend/mini-app
npm install
npm run dev:weapp
# 微信开发者工具打开 dist/ 目录
```

## 🧪 测试

```bash
# Java 单元测试（admin-api）
cd backend/admin-api && ./mvnw test

# Python 测试（ai-agent-service）
cd backend/ai-agent-service && pytest

# E2E 冒烟测试
cd tests/smoke && pytest
```

## 🚢 部署

本项目使用 **GitHub Actions** 自动部署到阿里云。标准流程：

```
本地开发 → 创建功能分支 → 提交代码 → 创建 PR → Review 通过 → 合并到 main → 自动部署
```

### 自动触发规则

代码合并到 `main` 分支时，根据变更文件路径自动触发对应工作流：

| 工作流 | 触发 | 构建方式 | 部署目标 |
|--------|------|---------|---------|
| `deploy-admin-api` | push main（`backend/admin-api/**`）/ tag v* / 手动 | Maven 单测 + 构建（tag=git SHA） | 测试环境 SWAS（自动） |
| `deploy-ai-agent-service` | push main（`backend/ai-agent-service/**`）/ tag v* / 手动 | 全量单测 + buildx 构建 | 测试环境 SWAS（自动） |
| `deploy-frontend` | push main（`frontend/admin-web/**`）/ tag v* / 手动 | tsc + vitest + 构建 | 测试环境 SWAS（自动）+ 部署后域名探测 |
| `deploy-prod` | 手动（指定版本 + 生产审批） | 拉取已构建镜像 | **生产（未来，受控发布）** |
| `release` | 手动（patch/minor/major） | 打 semver tag + Release notes | 触发 tag 镜像构建 |

> 镜像 tag 为 git SHA 前 7 位（不可变、可追溯）；手动运行 deploy workflow 填 image_tag 可**回滚到指定版本**。
> 生产发布流程见 [production-deployment.md](docs/deployment/production-deployment.md)；回滚见 [rollback.md](docs/deployment/rollback.md)。

### 快速部署示例

```bash
# 1. 创建功能分支
git checkout -b feat/backend/xxx

# 2. 开发完成后提交
git add . && git commit -m "feat(backend): xxx"
git push origin feat/backend/xxx

# 3. 创建 PR 并合并
gh pr create --title "[backend] xxx" --base main
gh pr merge --squash --delete-branch

# 4. ✅ GitHub Actions 自动部署，无需额外操作
```

每个工作流都支持在 GitHub Actions 页面手动触发（`workflow_dispatch`）。

### 详细部署文档
- [SWAS 迁移踩坑](docs/deployment/swas-migration-lessons.md) — SWAS 部署的 16 个坑与经验
- [部署检查清单](docs/deployment/deployment-checklist.md) — 历史踩坑记录（可参考）
- [生产部署方案](docs/deployment/production-deployment.md) — 未来生产环境受控发布设计
- [回滚 Runbook](docs/deployment/rollback.md) — 快速/手动回滚流程
- 当前部署以 `deploy/swas/deploy.sh` + [docs/wiki/Deployment.md](docs/wiki/Deployment.md) 为准

## 📖 项目文档

| 类别 | 文档 | 说明 |
|------|------|------|
| **架构** | [系统架构](docs/wiki/Architecture.md) | 双微服务拓扑、多租户、Agent 框架 |
| **API** | [API 参考文档](docs/api/api-reference.md) | 全量接口定义 + SSE 协议 |
| **设计** | [UI 设计规范](docs/design/ui-design-spec.md) | 色彩、字体、组件、响应式 |
| | [管理后台设计](docs/design/admin-dashboard-design.md) | 页面路由、权限矩阵、CRM |
| | [坐席工作台设计](docs/design/agent-workspace-design.md) | 人工坐席流程、WebSocket |
| | [工具规范](docs/design/skill-spec.md) | 31 个 AI 工具定义与安全层 |

## 📊 项目进度

当前整体进度 **~74%**，处于第三阶段（MVP 测试与上线）。

| 阶段 | 进度 | 说明 |
|------|------|------|
| 阶段一：基础设施 | 85% | 脚手架、数据库 41 张表、Docker、CI/CD |
| 阶段二：MVP 核心 | 97% | 商品 CRUD、AI 工具、小程序、SSE |
| 阶段三：测试上线 | 20% | 单元测试、集成测试、生产部署 |

## 🤝 贡献指南

欢迎贡献！详细流程见 [CONTRIBUTING.md](CONTRIBUTING.md)（Issue 先行 → 分支 → 测试先行 → PR 门禁）。

### 分支策略

| 分支 | 用途 |
|------|------|
| `main` | 受保护，仅通过 PR 合入 |
| `feat/frontend/*` | 前端功能 |
| `feat/backend/*` | 后端功能 |
| `fix/*` | Bug 修复 |
| `hotfix/*` | 紧急修复 |

### Commit 规范

```
feat(frontend): 添加商品批量上架功能
fix(backend): 修复多租户数据隔离问题
test: 补充订单状态机单元测试
```

## 📄 许可证

[MIT License](LICENSE)
