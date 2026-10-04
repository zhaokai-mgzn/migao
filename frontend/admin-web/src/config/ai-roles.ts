/**
 * 两位 AI 的**定位标签单一源**（issue #6330）。
 *
 * 为什么单独成模块：这对定位此前在仓里有 **4 套写法** ——
 * 官网「企业智能工作助手 / AI 智能客服」、入驻页「企业智能助手 / 智能客服」、
 * 后台悬浮助手「米宝 · 智能助手」、客服工作台「米宝 · B端工作助手」
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
 * | 米宝 | 企业智能生产管家 | 对内：面向商家的经营侧 |
 * | 小布 | 企业智能客服 | 对外：面向顾客的服务侧 |
 *
 * ## 改动纪律
 *
 * 改这两个词 ⇒ **只改这里**，不要在页面里另写一份。
 * 硬编码会被 `frontend/admin-web/tests/unit/pages/corporate-home.test.tsx` 的
 * 「定位标签单一源」判据检出（源码级扫描，命中即红且具名）。
 *
 * ⚠️ 覆盖边界（照实登记）：本单一源目前只覆盖**对外介绍的三个定位面**
 * （官网首页 / 产品服务页 / 入驻页）。产品内 UI 的标签
 * （`frontend/admin-web/src/components/ai-assistant/FloatingAssistant.tsx`、
 * `frontend/admin-web/src/components/chat/SessionInsight.tsx`）**尚未纳入** ——
 * 那是已开通商家日常面对的界面，改动面与测试面另议（issue #6330 有登记）。
 */

/** 对内：面向商家的经营侧助手 */
export const AI_ROLE_MIBAO = '企业智能生产管家'

/** 对外：面向顾客的服务侧客服 */
export const AI_ROLE_XIAOBU = '企业智能客服'

export const AI_ROLES = {
  mibao: AI_ROLE_MIBAO,
  xiaobu: AI_ROLE_XIAOBU,
} as const
