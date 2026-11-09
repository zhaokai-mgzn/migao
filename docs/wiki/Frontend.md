# 前端架构

> 四个前端包：**admin-web**（观星台后台 + 官网）、**mini-app**（顾客小程序）、
> **bmini-app**（商家小程序 + 员工端 H5）、**worker-h5**（兼容期旧工人端）。
> **页面数 / 组件数 / 依赖版本不写死** —— 真值源在各包 `package.json` 与 `src/`。

## admin-web（Next.js App Router）

### 路由组

| 路由组 | 域名 | 内容 |
|--------|------|------|
| `(dashboard)` | `merchant.migaozn.com` | 观星台经营后台：经营概览 / 报表 / 客户服务 / 订单商品 / 生产 / 质量 / 仓储 / 财务 / 供应链 / 组织 / 设置 |
| `(corporate)` | 裸域 `migaozn.com` | 官网：首页 / 产品与服务 / 关于我们 / 联系我们 / 终端下载 |
| 根路由 | — | 登录 / 注册 / 首登改密 |

> `(ops)` 路由组（租户注册审批）已于 2026-08-30 废弃：商家入驻改为 AI 自动甄别
> （`POST /api/auth/register` 同步返回 approved/rejected），不再有人工审批页面。

菜单 IA 的真值源 = `frontend/admin-web/src/config/menu.ts`（分组 / 菜单名 / 权限码 / 路径）；
官网能力地图 `src/components/corporate/capability-map.ts` 与它逐字对齐。

### 技术栈

| 层 | 选型（版本见 `frontend/admin-web/package.json`） |
|----|------|
| 框架 | Next.js（App Router） |
| 语言 | TypeScript |
| 样式 | Tailwind CSS（设计 token 真值源见 [design-baseline](../design/design-baseline.md)） |
| 状态 | Zustand（persist + in-memory） |
| HTTP | Axios（REST）+ fetch（SSE） |
| 图表 | Recharts |
| 通知 | Sonner（toast） |
| 图标 | Lucide |

### 状态管理

- **authStore**（Zustand + localStorage persist）：`user` / `accessToken` / `refreshToken` / `isAuthenticated`，自动 token 刷新队列
- **chatStore**（Zustand in-memory）：`sessions` / `messages` / `isStreaming` / SSE 事件解析

### API 层

- `lib/request.ts`：Axios 实例，请求拦截（Bearer token），响应拦截（401 刷新队列，业务错误 toast）
- `lib/api.ts`：按域拆分的 API 模块（auth / product / order / customer / chat / knowledge 等），chat 用原生 fetch 走 SSE
- `lib/sse-parser.ts`：SSE 协议解析，emit 类型化事件

### 组件

`components/ui/`（Button / Input / Select / Modal / Table / Pagination / Card / Badge 等）、
`components/products/`（ProductForm / SkuMatrix / CategoryTree / ImageUploader）、
`components/orders/`、`components/chat/`、`components/corporate/`、`components/ai-assistant/`。

### 域名分流

`src/proxy.ts`（Next.js 16 起取代旧的 `middleware.ts` 命名）：

- 裸域 → corporate 页面（`/dashboard` 等前缀跳 `merchant`，未知路径回首页）
- `merchant.migaozn.com` → dashboard（未登录跳登录）
- 静态资源（`robots.txt` / `sitemap.xml` / `og-image.png` 等）不进 proxy

## mini-app（顾客微信小程序）

- **3 个 tab 页**：对话（SSE 流式）· 会话历史 · 个人中心
- 卡片组件：真值源 `frontend/mini-app/src/components/cards/`
  （ProductCard / KnowledgeCard / LogisticsCard / QuotationCard / OrderCard / PaymentCard /
  ConfirmCard / ChoiceCard / FormCard / ProductionProgressCard 等）
- 技术：Taro（**版本不抄数**，真值源 `frontend/mini-app/package.json` 的 `@tarojs/taro`）/ React / Sass / Zustand
- 品牌：顾客侧 Agent 名 = **元元**（`src/utils/brand.ts`）

## bmini-app（商家小程序 + 员工端 H5）

独立微信小程序（与 C 端元元不同 appid / 主体），同一份代码双编译出小程序与 H5（`/b/`）。
复用 C 端 mini-app 的基建（SSEClient / authStore / request / chatService）。

| 面 | 内容 |
|----|------|
| 商家小程序 | 问黄金策（SSE 对话）· 数据（经营一屏）· 坐席（移动坐席）· 我的 |
| 员工端 H5 / 工人工作台 | 扫码报工、入库、发货、返工、计件等工人面（`/b/`） |

- 登录：`用户名@企业编码` + 密码 → `POST /api/auth/employee/login`
  （租户只由企业编码解析，前端不传 `tenantId`）
- 首登强制改密：`pages/auth/change-password`（`POST /api/auth/password/change` 在强制改密白名单内）
- 后端接口全复用 admin-api（dashboard / agent-sessions / chat SSE），零新增后端功能
- CI：`.github/workflows/bmini-app.yml`（typecheck + 单测）

## worker-h5（兼容期旧工人端）

线上 `/w/` 的静态多页（零构建纯 ESM），**只服务已印出的纸码**，不再新增功能，
也不再是任何跳转的目标。新的工人面统一做在 `frontend/bmini-app`。

- 判据：`tests/unit_ci_workflows/test_w_compat_period.py`
- 边界与退役计划见 `frontend/worker-h5/README.md`

## 设计基线

颜色 / 字号 / 阴影 / 四态契约的真值源：

- `frontend/admin-web/tailwind.config.ts`
- `frontend/admin-web/src/lib/design-tokens.ts`

口径与自检五问见 [design-baseline](../design/design-baseline.md)；
页面级视觉验收（Playwright 截图 + 多模态读图）见 `migao-dev-flow` §15.7。

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

---

详见：[UI 设计规范](../design/ui-design-spec.md) · [管理后台设计](../design/admin-dashboard-design.md) · [Product](Product.md)
