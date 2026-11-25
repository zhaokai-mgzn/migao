/**
 * 微信客服会话的附加状态位（issue #9202 / 母单 #9194 子项 2 前端面）。
 *
 * 单独成文件而不是塞进 `lib/api.ts`：后者是 LOC 棘轮冻结文件（只许向下），
 * 新字段通过 `AgentSession extends KfSessionStatus` 合并，故 `api.ts` 一行不涨。
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
