# AIKF — AI 智能客服系统

面向布艺行业的多租户 AI 智能客服 SaaS。DeepSeek V4 Pro + MiniMax M3 + RAG + 23 Tools，覆盖售前→售后全链路。

## 架构

```
客户端: 微信小程序(SSE) + 管理后台(REST)
     → API 网关
     → Admin API(:8080, Java 21/Spring Boot 3.3) + AI Agent(:8000, Python 3.11/FastAPI)
     → PostgreSQL 15(RLS) + Redis 7 + DashVector + DeepSeek V4 Pro / MiniMax M3
```

## 技术栈

| 层 | 技术 |
|----|------|
| Admin API | Java 21 / Spring Boot 3.3.5 / MyBatis-Plus 3.5.8 |
| AI Service | Python 3.11 / FastAPI 0.115 / LangChain 0.3.14 / LangGraph 0.2.60 |
| Admin Web | Next.js 14.2 (App Router) / React 18 / TypeScript 5.7 / Tailwind |
| Mini App | Taro 3.6.40 / React 18 / Sass |
| DB | PostgreSQL 15 + Redis 7 |
| Vector | DashVector |
| LLM | DeepSeek V4 Pro (主) + MiniMax M3 (视觉) |
| Auth | RS256 JWT + 微信登录 + 短信验证码 |
| Deploy | SAE + RDS + OSS + CDN + Terraform + GitHub Actions |

## 目录

```
migao/
├── backend/admin-api/          # Java 管理后台 (19 Controllers, 21 Services, 31 Entities)
├── backend/ai-agent-service/   # Python AI 服务 (双Agent, 23 Tools, RAG)
├── frontend/admin-web/         # Next.js 管理后台 (12+ 页面)
├── frontend/mini-app/          # Taro 微信小程序
├── deploy/terraform/           # 阿里云 IaC
├── docs/                       # 文档 + wiki
├── tests/                      # E2E (Playwright) + Smoke (pytest)
└── knowledge_base/             # RAG 种子数据
```

## 功能

**C端(小程序)**: 售前咨询 · 订单查询 · 售后处理 · 物流追踪 · 知识问答 · 图片识别 · 人工转接 · 多轮对话

**B端(后台)**: 数据看板 · 商品CRUD(SKU矩阵) · 分类树 · 加工项 · 订单生命周期 · 售后工单 · CRM(RFM) · 人工坐席 · 知识库 · 通知 · RBAC(五角色) · 系统设置
