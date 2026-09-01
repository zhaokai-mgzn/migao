# 前端架构

## admin-web (Next.js 14 App Router)

22 页面，按路由组分层：

| 路由组 | 域名 | 页面 |
|--------|------|------|
| `(dashboard)` | merchant.migaozn.com | 数据看板 · 商品(SKU矩阵) · 分类 · 加工项 · 订单(全生命周期) · 售后 · 客户CRM · 聊天坐席 · 知识库 · 通知 · 员工 · 角色 · 财务 · 设置 (16页) |
| `(corporate)` | migaozn.com | 首页 · 关于 · 联系 · 服务 (4页) |
| 根路由 | — | 登录 · 注册 |

> 注：`(ops)` 路由组（租户注册审批）已于 2026-08-30 废弃——商家入驻改为 AI 自动甄别（`POST /api/auth/register` 同步返回 approved/rejected），不再有人工审批页面；`ops.migaozn.com` 域名分支与超管「入驻审批」菜单同步移除，超管兜底接口（`/api/super-admin/registrations*`）保留供 API 应急。

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
- `merchant.migaozn.com` → dashboard（根路径跳登录）
- `migaozn.com` → corporate 页面（dashboard 前缀跳 merchant，未知路径回首页）

## mini-app (Taro 3.6 微信小程序)

3 个 tab 页：对话(SSE流式) · 会话历史 · 个人中心
5 种卡片组件：ProductCard, KnowledgeCard, LogisticsCard, ToolCallIndicator
技术：Taro 3.6 / React 18 / Sass / Zustand

---
详见: [UI 设计规范](../design/ui-design-spec.md) · [管理后台设计](../design/admin-dashboard-design.md)

## Tailwind className 冲突反模式（前端开发必读）

`cn()` 底层用 tailwind-merge，同 class group 中**后者覆盖前者**。以下为项目实际踩过的坑：

### 1. className prop 覆盖组件默认布局
组件默认 `flex-col`（垂直堆叠），调用方传 `className="flex"` → `cn('flex flex-col', 'flex')` 的 `flex-col` 被覆盖成 `flex`（水平），布局完全错乱。
**修复**：传 prop 时明确方向语义（`flex-row`/`flex-col`），不依赖默认值；或 `!flex-col` 防覆盖。

### 2. 组件迁移机械搬运 className
把 `<div className="flex">` 换成 `<Wrapper className="flex">`：原 div 的 `flex` 作用于自己子元素；换到 Wrapper 后变成外层布局方向，与 Wrapper 内部子元素布局**完全无关**。
**修复**：迁移时检查 className 的布局作用对象是否变化。

### 3. class group 冲突速查表

| 危险组合 (先 → 后) | twMerge 结果 | 视觉后果 |
|-------------------|-------------|---------|
| `flex-col` → `flex` | `flex` (row) | 垂直布局变水平 |
| `flex-row` → `flex-col` | `flex-col` | 水平布局变垂直 |
| `p-4` → `p-0` | `p-0` | padding 消失 |
| `rounded-lg` → `rounded-none` | `rounded-none` | 圆角消失 |
| `bg-white` → `bg-transparent` | `bg-transparent` | 背景消失 |
| `text-sm` → `text-lg` | `text-lg` | 字号变大 |

> **铁律**：传入组件 prop 的 className 含 Tailwind class 时，必须检查是否与组件默认 className 在同一 class group 中冲突（真值断言：组件两个子区域 rect.top 差 >10px 为垂直排列，而非 rect.left）。
