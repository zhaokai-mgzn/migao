/**
 * 两位 AI 的**定位标签单一源**（issue #6330）。
 *
 * 为什么单独成模块：这对定位此前在仓里有 **4 套写法** ——
 * 官网「企业智能工作助手 / AI 智能客服」、入驻页「企业智能助手 / 智能客服」、
 * 后台悬浮助手「黄金策 · 智能助手」、客服工作台「黄金策 · B端工作助手」
 * ⇒ 用户要的「定位清晰」正好被写法漂移抵销：同一个 AI 在不同页面叫不同名字。
 * 同 `frontend/admin-web/src/components/corporate/capability-map.ts` 的理由（单一源，两处各写必然漂移）。
 *
 * ## 口径（用户 2026-10-05 裁定，逐字）
 *
 * > 对内的AI可以说成企业智能管家，对外AI定义成企业智能客服 这样的定位多清晰
 * > （随即更正：）改成 企业智能生产管家
 *
 * | AI | 定位 | 朝向 |
 * |---|---|---|
 * | 黄金策 | 企业智能生产管家 | 对内：面向商家的经营侧 |
 * | 元元 | 企业智能客服 | 对外：面向顾客的服务侧 |
 *
 * ## 改动纪律
 *
 * 改这两个词 ⇒ **只改这里**，不要在页面里另写一份。
 * 硬编码会被 `frontend/admin-web/tests/unit/pages/corporate-home.test.tsx` 的
 * 「定位标签单一源」判据检出（源码级扫描，命中即红且具名）。
 *
 * ## 覆盖边界（照实登记）
 *
 * **已覆盖**（admin-web，共 6 个定位面，全部走本模块、硬编码即红）：
 *   - 对外介绍：官网首页 `app/(corporate)/page.tsx`、产品服务页 `app/(corporate)/services/page.tsx`、入驻页 `app/register/page.tsx`
 *   - 产品内（#6333 起）：悬浮助手 `components/ai-assistant/FloatingAssistant.tsx`、
 *     客服工作台 `components/chat/SessionInsight.tsx`、
 *     人工会话记录 `app/(dashboard)/agent-workspace/human-sessions/page.tsx`
 *
 * **未覆盖**（有意，附理由）：
 *   - 两个**小程序**（`frontend/mini-app` / `frontend/bmini-app`）是**独立工程**，各自本地字面量 +
 *     各自测试钉值 —— **不建跨 App 共享模块**：`#6306` 的教训是共享模块一旦落在发布集之外 ⇒ 白屏。
 *   - **功能名 / 页面名**不是 AI 身份，不适用本模块：`黄金策 · 今日经营速览`（数据栏标题）、
 *     `黄金策 · 在线对话`（`/chat` 面包屑）。
 *   - **店铺 / App 描述**不是 AI 角色：`frontend/mini-app/src/utils/brand.ts` 的
 *     `buildBrandSubtitle` = `{企业名} · 智能购物助手`（C 端导航副标题）。
 */

/** 对内：面向商家的经营侧助手 */
export const AI_ROLE_MIBAO = '企业智能生产管家'

/** 对外：面向顾客的服务侧客服 */
export const AI_ROLE_XIAOBU = '企业智能客服'

export const AI_ROLES = {
  mibao: AI_ROLE_MIBAO,
  xiaobu: AI_ROLE_XIAOBU,
} as const
