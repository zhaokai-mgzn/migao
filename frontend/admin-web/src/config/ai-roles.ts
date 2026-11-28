/**
 * 两位 AI 的**定位标签 / 产品名单一源**（issue #6330；产品名同源 issue #9306）。
 *
 * 为什么单独成模块：这对定位此前在仓里有 **4 套写法** ——
 * 官网「企业智能工作助手 / AI 智能客服」、入驻页「企业智能助手 / 智能客服」、
 * 后台悬浮助手「黄金策 · 智能助手」、客服工作台「黄金策 · B端工作助手」
 * ⇒ 用户要的「定位清晰」正好被写法漂移抵销：同一个 AI 在不同页面叫不同名字。
 * 同 `frontend/admin-web/src/components/corporate/capability-map.ts` 的理由（单一源，两处各写必然漂移）。
 *
 * ## 口径（用户 2026-10-05 裁定 + 2026-11-28 改判）
 *
 * | 内部 id | 产品名 | 定位标签 | 朝向 / 形态 |
 * |---|---|---|---|
 * | `mibao` | 黄金策 | 企业智能生产管家 | 对内：B 端经营侧（**agent 形态**） |
 * | `xiaobu` | 智能客服 | 企业智能客服 | 对外：C 端顾客服务（**无 agent 形态**、不拟人、不自称名字） |
 *
 * 2026-11-28 用户裁定逐字：「C 端也不叫米宝了，C 端现在不提供 agent 形态，只提供技术能力，直接叫智能客服」
 * ⇒ 旧拟人名**退役**：不得再出现在任何用户可见面（本文件的产品名以 `AGENT_NAMING` 为准）。
 *
 * 🔴 **产品名的真值不在前端**：在 `backend/ai-agent-service/app/agents/naming.py` 的 `AGENT_NAMING`
 * （`mibao` → 黄金策 / `xiaobu` → 智能客服）。本模块的 `AI_NAMES` 与那份映射表**逐字同源**（两侧独立写，
 * 不是一份复制两份）：改一侧另一侧没跟 ⇒ `tests/unit_ci_workflows/test_agent_naming_source_of_truth.py`
 * 的判据 4 具名红。
 * 内部 id（`mibao` / `xiaobu`）是**技术标识**，不要为了「对齐产品名」去改 —— 会连带改路由键 /
 * 会话状态键 / 评测用例的 `persona` 字段。
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
 *   - 两个**小程序**（`frontend/bmini-app`；C 端顾客小程序已于 2026-11-26 下线）是**独立工程**，各自本地字面量 +
 *     各自测试钉值 —— **不建跨 App 共享模块**：`#6306` 的教训是共享模块一旦落在发布集之外 ⇒ 白屏。
 *   - **功能名 / 页面名**不是 AI 身份，不适用本模块：`黄金策 · 今日经营速览`（数据栏标题）、
 *     `黄金策 · 在线对话`（`/chat` 面包屑）。
 *   - **店铺 / App 描述**不是 AI 角色：`frontend/bmini-app/src/utils/brand.ts` 的
 *     `buildBrandSubtitle` = `{企业名} · 商家经营助手`（B 端导航副标题）。
 */

/** 产品名：B 端经营侧（**agent 形态**）—— 真值 = `naming.py` 的 `AGENT_NAMING['mibao'].display_name` */
export const AI_NAME_MIBAO = '黄金策'

/** 产品名：C 端（**无 agent 形态**，不拟人、不自称名字）—— 真值 = `AGENT_NAMING['xiaobu'].display_name` */
export const AI_NAME_XIAOBU = '智能客服'

/** 定位标签：对内，面向商家的经营侧助手 */
export const AI_ROLE_MIBAO = '企业智能生产管家'

/** 定位标签：对外，面向顾客的服务侧客服 */
export const AI_ROLE_XIAOBU = '企业智能客服'

export const AI_ROLES = {
  mibao: AI_ROLE_MIBAO,
  xiaobu: AI_ROLE_XIAOBU,
} as const

/** 产品名映射（键 = `naming.py` 的内部 id；值 = 对客产品名） */
export const AI_NAMES = {
  mibao: AI_NAME_MIBAO,
  xiaobu: AI_NAME_XIAOBU,
} as const
