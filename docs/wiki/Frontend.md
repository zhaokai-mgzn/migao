# 前端架构

## admin-web (Next.js 14 App Router)

22 页面，按路由组分层：

| 路由组 | 域名 | 页面 |
|--------|------|------|
| `(dashboard)` | merchant.migaozn.com | 数据看板 · 商品(SKU矩阵) · 分类 · 加工项 · 订单(全生命周期) · 售后 · 客户CRM · 聊天坐席 · 知识库 · 通知 · 员工 · 角色 · 财务 · 设置 (16页) |
| `(corporate)` | migaozn.com | 首页 · 关于 · 联系 · 服务 (4页) |
| `(ops)` | ops.migaozn.com | 租户注册审批 (1页) |
| 根路由 | — | 登录 · 注册 |

## 技术栈

| 层 | 选型 |
|----|------|
| 框架 | Next.js 14.2 (App Router, SSR) |
| 语言 | TypeScript 5.7 |
| 样式 | Tailwind CSS |
| 状态 | Zustand (persist + in-memory) |
| HTTP | Axios (REST) + fetch (SSE) |
| 图表 | Recharts |
| 通知 | Sonner (toast) |
| 图标 | Lucide |

## 状态管理

- **authStore** (Zustand + localStorage persist): `user`, `accessToken`, `refreshToken`, `isAuthenticated`, 自动 token 刷新队列
- **chatStore** (Zustand in-memory): `sessions`, `messages`, `isStreaming`, SSE 事件解析

## API 层

- `lib/request.ts`: Axios 实例，请求拦截(加 Bearer token)，响应拦截(401 刷新队列，业务错误 toast)
- `lib/api.ts`: 18 API 模块 (auth, product, order, customer, chat, knowledge 等)，chat 用原生 fetch 走 SSE
- `lib/sse-parser.ts`: SSE 协议解析，emit 类型化事件

## 关键组件 (~40+)

`components/ui/` — Button, Input, Select, Modal, Table, Pagination, Card, Badge 等
`components/products/` — ProductForm, SkuMatrix, CategoryTree, ImageUploader, RichTextEditor
`components/orders/` — OrderTable, OrderTimeline, OrderProgressSteps, LogisticsForm
`components/chat/` — ChatArea, SessionList, MessageList, InteractiveMessage, ToolResultCard

## 中间件 (多域名)

`src/middleware.ts` 按域名路由：
- `ops.migaozn.com` → 仅 ops 路径
- `merchant.migaozn.com` → dashboard，拦截 super-admin 路径
- `migaozn.com` → corporate 页面

## mini-app (Taro 3.6 微信小程序)

3 个 tab 页：对话(SSE流式) · 会话历史 · 个人中心
5 种卡片组件：ProductCard, KnowledgeCard, LogisticsCard, ToolCallIndicator
技术：Taro 3.6 / React 18 / Sass / Zustand

---
详见: [UI 设计规范](../design/ui-design-spec.md) · [管理后台设计](../design/admin-dashboard-design.md)
