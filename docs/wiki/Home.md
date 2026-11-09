# 观星台 — 布艺行业 AI 经营平台

> 面向布艺 / 窗帘商家的多租户 AI 经营平台：顾客侧由 **元元** 提供 7×24 智能客服与下单，
> 经营侧由 **黄金策** 覆盖商品、订单、生产、质量、仓储、财务与供应链。
> 智能客服只是「客户服务」能力域的一部分，不再代表系统定位。
>
> 产品定位、四端与能力地图的单一源 = [Product](Product.md)。

## 一分钟了解

- **两位 Agent** — 元元（C 端顾客，小程序内对话）+ 黄金策（B 端经营，后台 / 商家小程序内对话）
- **四端** — 观星台管理后台、顾客微信小程序、商家小程序、员工端 H5 / 安卓终端
- **全链路** — 询价算料 → 下单 → 生产（裁床 / 车位 / 后整）→ 入库 → 发货 → 售后与对账
- **行业纵深** — 窗帘算料、SKU 矩阵、工序路线、批次成本、余料台账、计件工资
- **多租户** — 租户身份只取自登录凭证；查询自动按租户过滤；跨租户访问一律 404

## 架构

```
四端（观星台后台 / 顾客小程序 / 商家小程序 + 员工端 H5 / 安卓终端）
     → nginx（域名分流 / TLS）
     → admin-api(:8080, Java 21 / Spring Boot)  ⇄  ai-agent-service(:8001 宿主，容器内 8000；Python / FastAPI / LangGraph)
     → PostgreSQL 15（RLS）+ Redis 7 + DeepSeek（主模型 / 视觉模型可配）
     → OSS（图片与文件）
```

业务真值在 `admin-api`：价格、库存、权限、单据状态由服务端裁决；AI 服务只经工具读写，
不持有独立业务库。知识问答走 `knowledge_cards`（结构化过滤 + 关键词，无向量库；
RAG 已随 issue #3051 移除）。完整拓扑与多租户隔离见 [Architecture](Architecture.md)。

## 技术栈

| 层 | 技术（**版本不抄数**，真值源见括号） |
|----|------|
| Admin API | Java 21 / Spring Boot / MyBatis-Plus（`backend/admin-api/pom.xml`） |
| AI Service | Python 3.11 / FastAPI / LangChain Core / LangGraph（`backend/ai-agent-service/requirements.txt`） |
| Admin Web | Next.js（App Router）/ React / TypeScript / Tailwind（`frontend/admin-web/package.json`） |
| Mini App | Taro（`frontend/mini-app/package.json`）/ React / Sass |
| Bmini App | Taro（`frontend/bmini-app/package.json`）/ React / TypeScript（H5 + 小程序双编译） |
| DB | PostgreSQL 15 + Redis 7 |
| 知识库 | `knowledge_cards`（LLM WIKI 词条模型） |
| LLM | DeepSeek（主模型 / 视觉模型由 `PRIMARY_MODEL` / `VISION_MODEL` 配置） |
| Auth | RS256 JWT + 微信登录 + 短信验证码 |
| Deploy | SWAS 轻量应用服务器 + RDS + Redis(Tair) + OSS + GitHub Actions |

> **业务工具数量**以 `backend/ai-agent-service/app/tools/registry.py` 为单一源；
> **workflow 数量**用 `ls .github/workflows/*.yml .github/workflows/*.yaml 2>/dev/null | wc -l` 现取。
> 本页不写死任何现值（issue #5082）。

## 仓库地图

```
migao/
├── backend/admin-api/          # Java 管理 API（业务真值 / 租户 / 权限 / 单据）
├── backend/ai-agent-service/   # Python AI 服务（元元 / 黄金策 / 工具 / Skill）
├── frontend/admin-web/         # 观星台后台 + 官网
├── frontend/mini-app/          # 顾客微信小程序
├── frontend/bmini-app/         # 商家小程序 + 员工端 H5
├── frontend/worker-h5/         # 兼容期旧工人端（/w/，不再新增功能）
├── deploy/                     # SWAS 部署（compose / nginx / 脚本）
├── docs/                       # wiki + 设计 / 部署 / 测试文档
├── tests/                      # 工作流守卫 / E2E / 冒烟
└── .github/                    # CI/CD + 行为用例（cases/）
```

## 文档怎么读

完整索引见 [INDEX](INDEX.md)；最常用的入口：

| 你要做什么 | 先读 |
|------------|------|
| 了解产品全貌 | [Product](Product.md) |
| 首次搭建 / 本地运行 | [Quick-Start](Quick-Start.md) |
| 写代码前确认规范 | [Development](Development.md) |
| 改 AI 服务 / Tool / Skill | [AI-Agent](AI-Agent.md) · [agent-capability-paradigm](agent-capability-paradigm.md) |
| 改前端 / 小程序 | [Frontend](Frontend.md) |
| 改数据库 / 查表结构 | [Database](Database.md) |
| 部署 / CI/CD | [Deployment](Deployment.md) · [CI-CD](CI-CD.md) |
| 写测试 / 做验收 | [Testing](Testing.md) · [acceptance-protocol](../testing/acceptance-protocol.md) |
| 遇到问题 | [Troubleshooting](Troubleshooting.md) |
