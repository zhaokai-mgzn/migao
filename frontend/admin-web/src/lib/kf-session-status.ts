/**
 * 微信客服会话的附加状态位与展示规则（issue #9202 / 母单 #9194 子项 2 前端面）。
 *
 * 单独成文件而不是塞进 `lib/api.ts`：后者是 LOC 棘轮冻结文件（只许向下），
 * 新字段通过 `AgentSession extends KfSessionStatus` 合并，故 `api.ts` 一行不涨。
 *
 * 展示规则（徽标是否出现 / 状态人话 / 额度是否用尽）放在这里而不是页面组件里：
 * 它们是**纯函数**，可以逐条判红（`tests/unit/lib/kf-session-status.test.ts`），
 * 页面只负责把它们画出来。
 *
 * 非微信客服会话：这四项全部为 `null`/`undefined`（服务端不会兜底给默认渠道）。
 */
export interface KfSessionStatus {
  /** 渠道标识：微信客服来源为 `wechat_kf`。 */
  channel?: 'wechat_kf' | string | null
  /** 该会话最新一条微信客服发送状态。 */
  sendStatus?: 'pending' | 'sending' | 'accepted' | 'failed' | 'unknown' | string | null
  /** 48h 窗口内已用条数（窗口过期或无记录 ⇒ 0）。 */
  budgetUsed?: number | null
  /** 48h 窗口上限（恒 5）。 */
  budgetLimit?: number | null
}

/** 服务端只在**真有镜像行**时下发；前端**不得**兜底成默认渠道（伪造渠道会让坐席等错地方）。 */
export const KF_CHANNEL = 'wechat_kf'
/** 48h 发送预算上限（与服务端 `kf_send_budget` 的 CHECK 同源，仅作缺失兜底展示）。 */
export const KF_BUDGET_LIMIT_FALLBACK = 5

const KF_SEND_STATUS_LABEL: Record<string, string> = {
  pending: '待发送',
  sending: '发送中',
  accepted: '已接收',
  failed: '发送失败',
  unknown: '状态未知',
}

/** 发送状态未知时不留空白（空白会被读成「没问题」）。 */
export function kfSendStatusLabel(status?: string | null): string {
  return KF_SEND_STATUS_LABEL[status ?? ''] ?? '状态未知'
}

/** 48h 额度读数（缺失字段按 0 / 5 兜底展示，不改服务端真值）。 */
export function kfBudget(session?: KfSessionStatus | null): { used: number; limit: number } {
  return {
    used: session?.budgetUsed ?? 0,
    limit: session?.budgetLimit ?? KF_BUDGET_LIMIT_FALLBACK,
  }
}

/** 列表里的「额度 2/5」。 */
export function kfBudgetLabel(session?: KfSessionStatus | null): string {
  const { used, limit } = kfBudget(session)
  return `${used}/${limit}`
}

/**
 * 额度用尽 ⇒ 输入区禁用。**只对微信客服成立**：普通人工会话没有 48h 预算，
 * 绝不能因为服务端漏字段就把坐席锁死。
 */
export function isKfBudgetExhausted(session?: KfSessionStatus | null): boolean {
  if (session?.channel !== KF_CHANNEL) return false
  const { used, limit } = kfBudget(session)
  return used >= limit
}
