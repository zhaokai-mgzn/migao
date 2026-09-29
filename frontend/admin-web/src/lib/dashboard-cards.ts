// 经营看板的**指标卡注册表**（issue #5792 的可插拔基座）
//
// ## 为什么要有它
//
// 用户 2026-09-29 追加要求：「**AI 接待占比这个需要设计成可插拔的，未来有部分企业可能未购买智能客服**」。
// ⇒ 看板上「依赖某个企业能力」的卡片不能在组件里散落 `if`，而要**声明式**登记：
// 每张卡声明自己依赖哪个能力位，由本模块**统一**判定显隐。
//
// ## 口径（三条，缺一不可）
//
//   ① **保守**：能力位**缺省/undefined ⇒ 不渲染**（与 `false` 同待遇）——
//      宁可不显示，也不要显示一个来源不明的数字；
//   ② **未购买 ⇒ 卡片不渲染**，**不是**渲染成 0、**不是**空白占位（0 会被读成业务事实）；
//   ③ 判定**只读服务端下发的能力位**，端侧不判权限码（与既有 `capabilities.mibaoChat` 同一范式：
//      单一真值在服务端 `AdminGate`，端侧只消费布尔位）。

/** 服务端下发的能力位（`GET /api/auth/me` ⇒ `data.capabilities`） */
export interface CapabilityBits {
  mibaoChat?: boolean
  aiService?: boolean
}

/** 依赖某能力位的看板卡片（当前只有一张；将来「待支付/超时工单」等若也要可插拔，在此登记即可） */
export interface PluggableCard {
  /** 卡片标识（判据与 `data-testid` 用） */
  key: string
  /** 依赖的能力位键 */
  requires: keyof CapabilityBits
  /** 卡片标题（用户可见文案） */
  title: string
}

/** 注册表：**新增可插拔卡片只改这里** */
export const PLUGGABLE_DASHBOARD_CARDS: readonly PluggableCard[] = [
  { key: 'ai-service-rate', requires: 'aiService', title: 'AI 接待占比' },
] as const

/**
 * 该卡片此刻是否应该渲染。
 *
 * 🔴 「缺省 = 不渲染」是**有意**的保守口径（见文件头 ①）：
 * 能力位没下发（老后端 / 请求失败 / 字段拼错）时，我们**不知道**企业有没有买 ⇒ 不显示，
 * 而不是显示一个可能误导的数字。
 */
export function shouldRenderCard(card: PluggableCard, bits: CapabilityBits | undefined): boolean {
  return bits?.[card.requires] === true
}

/** 过滤出应渲染的卡片（渲染侧唯一入口，避免各卡自己判） */
export function visiblePluggableCards(
  bits: CapabilityBits | undefined,
  cards: readonly PluggableCard[] = PLUGGABLE_DASHBOARD_CARDS,
): PluggableCard[] {
  return cards.filter((c) => shouldRenderCard(c, bits))
}
