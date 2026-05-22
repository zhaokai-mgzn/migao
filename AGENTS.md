# AI 智能客服系统 - 开发规范

> 项目：优客 AI 智能客服系统（布艺行业）
> 仓库：https://github.com/zhaokai-mgzn/youke.git

## 项目概述

面向布艺行业（窗帘生产与家装）的 AI 智能客服 SaaS 系统，支持：
- 售前咨询（AI 商品推荐、材质介绍、风格搭配）
- 订单查询（物流跟踪、订单状态）
- 售后处理（退货换货、投诉跟踪）
- 管理后台（商品/订单/客户/知识库管理）

## 技术栈

| 层级 | 技术 |
|------|------|
| 管理后端 | Java 21 + Spring Boot 3.3 + MyBatis-Plus |
| AI 服务 | Python 3.11 + FastAPI + LangChain |
| 管理前端 | Next.js 14 + TypeScript + Tailwind + Zustand |
| 微信小程序 | Taro 3.x + React + TypeScript |
| 数据库 | PostgreSQL 14 + Redis 7 |
| 向量库 | DashVector |
| LLM | 阿里云百炼 DashScope |
| 部署 | 阿里云 SAE + RDS + OSS + API Gateway |

## 目录结构

```
youke/
├── backend/
│   ├── admin-api/          # Java 管理后端（认证 + 业务 API）
│   └── ai-agent-service/   # Python AI 服务（对话 + RAG）
├── frontend/
│   ├── admin-web/          # Next.js 管理后台
│   └── mini-app/           # Taro 微信小程序
├── deploy/
│   └── terraform/          # 阿里云基础设施配置
├── docs/
│   ├── sql/                # 数据库迁移脚本
│   ├── deployment/         # 部署文档
│   └── TEST_REPORT.md      # 测试报告
├── knowledge_base/         # 知识库原始数据
└── .qoder/
    └── agents/             # QoderWake Agent 定义
```

## 分支策略

### 分支命名

| 分支 | 用途 | 命名规范 |
|------|------|---------|
| `main` | 生产分支，稳定可部署 | 受保护，仅通过 PR 合并 |
| `feat/frontend/*` | 前端功能开发 | `feat/frontend/add-product-page` |
| `feat/backend/*` | 后端功能开发 | `feat/backend/order-api` |
| `feat/qa/*` | 测试相关 | `feat/qa/integration-tests` |
| `fix/*` | Bug 修复 | `fix/login-token-expire` |
| `hotfix/*` | 紧急修复 | `hotfix/security-patch` |

### PR 规范

1. **标题格式**：`[角色] 简要描述`，如 `[frontend] 新增商品管理页面`
2. **描述内容**：变更说明 + 测试方式 + 影响范围
3. **Review 要求**：至少 1 人 review 后合并
4. **合并方式**：Squash merge 保持 main 分支整洁

### 提交规范

```
feat(frontend): 新增商品管理列表页面
fix(backend): 修复 JWT Token 过期未正确返回 401
test: 补充订单 API 集成测试
refactor(backend): 优化商品查询 SQL 性能
docs: 更新部署文档中的 API Gateway 配置
chore: 升级 Next.js 到 14.2
```

## 角色分工

| 角色 | Agent 名称 | 负责范围 | 工作分支 |
|------|-----------|---------|---------|
| 前端开发 | `frontend-dev` | admin-web + mini-app | `feat/frontend/*` |
| 后端开发 | `backend-dev` | admin-api + ai-agent-service + DB | `feat/backend/*` |
| QA 工程师 | `qa-engineer` | 测试 + 部署验证 + 质量保障 | `feat/qa/*` / `test/*` |

## 通用开发规范

### 代码质量
- TypeScript strict 模式，零编译错误
- Java 编译零错误，关键警告需评估
- Python 代码通过 ruff 检查
- 所有 PR 必须通过 CI 检查

### 多租户隔离
- 所有业务表必须有 `tenant_id` 字段
- 所有查询必须过滤 `tenant_id`（从 JWT 获取，不可伪造）
- 数据库层配置 RLS (Row Level Security)

### API 规范
- RESTful 设计，统一响应格式 `{ code, message, data }`
- 分页参数：`page`（页码）、`size`（每页条数）
- 错误码体系：业务错误码 + HTTP 状态码
- API 文档：Swagger/OpenAPI（Java）、FastAPI 自动生成（Python）

### 安全规范
- 敏感信息（密钥、密码）通过环境变量，不硬编码
- JWT 使用 RS256 非对称签名
- 认证接口启用防重放（timestamp + nonce）
- CORS 仅允许已知前端域名

## 构建与验证命令

```bash
# Java 后端
cd backend/admin-api
./mvnw clean compile        # 编译
./mvnw test                 # 测试
./mvnw clean package -DskipTests  # 打包

# Python AI 服务
cd backend/ai-agent-service
pip install -r requirements.txt
pytest tests/ -v            # 测试
python -m py_compile app/main.py  # 语法检查

# 前端管理后台
cd frontend/admin-web
npm install
npm run build               # 构建
npx tsc --noEmit            # 类型检查
npx next lint               # ESLint

# 部署验证
curl http://<admin-api>/actuator/health
curl http://<ai-agent>/health
```
