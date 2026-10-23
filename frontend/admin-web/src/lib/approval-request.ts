// 审批申请的三类对象口径（issue #7374 段 3）—— **与后端闸门的 consume 调用逐字对齐**。
//
// 写错了 ref 等于「批了也用不上」：闸门按 `objectType + objectRef` 找已通过的审批，
// 金额还要 ≥ 闸门要求的门槛。三处口径分别来自：
//   · price_change    → `PriceBookService.assertPriceFloorAllows`：ref = skuId，金额 ≥ 该 SKU 成本价
//   · stocktake_diff  → `StocktakeService.complete`：ref = **盘点单号**，金额 ≥ 合计绝对差异
//   · credit_override → `CustomerService` 授信闸门：ref = 客户手机号，金额 ≥ 本次超出额
//
// 本文件只做「表单默认值与提示」的纯函数，不发请求（便于逐格判据）。

export type ApprovalObjectKind = 'price_change' | 'stocktake_diff' | 'credit_override'

export interface ApprovalDraft {
  objectType: ApprovalObjectKind
  /** 闸门用来找审批的键（见上：skuId / 盘点单号 / 客户手机号）。 */
  objectRef: string
  /** 给人看的对象名（审批中心列表里显示这一列）。 */
  objectLabel?: string
  /** 默认金额：闸门要求「金额 ≥ 门槛」，所以默认值取**门槛本身**最不容易填错。 */
  defaultAmount?: number | null
  /** 金额提示（写清门槛是什么，避免「批了用不上」）。 */
  amountHint: string
  /** 申请人自己要写的一句话（必填）。 */
  reasonHint: string
}

/** 改价：ref = SKU id；金额门槛 = 该 SKU 成本价（前端不一定拿得到 ⇒ 不预填，只给提示）。 */
export function priceChangeDraft(input: {
  skuId: string
  skuLabel?: string | null
  costHint?: string | null
}): ApprovalDraft {
  return {
    objectType: 'price_change',
    objectRef: input.skuId,
    objectLabel: input.skuLabel ?? undefined,
    defaultAmount: null,
    amountHint: input.costHint
      ? `审批金额要 ≥ 这个 SKU 的成本价（${input.costHint}），否则批了也用不上`
      : '审批金额要 ≥ 这个 SKU 的成本价，否则批了也用不上',
    reasonHint: '例如：老客户长期合作，本次按成本价出货',
  }
}

/** 盘点差异：ref = 盘点单号；金额门槛 = 差异合计（页面本来就有这个数 ⇒ 直接预填）。 */
export function stocktakeDiffDraft(input: {
  stocktakeNo: string
  diffTotal: number | null
}): ApprovalDraft {
  const amount = input.diffTotal === null ? null : Math.abs(input.diffTotal)
  return {
    objectType: 'stocktake_diff',
    objectRef: input.stocktakeNo,
    objectLabel: input.stocktakeNo,
    defaultAmount: amount,
    amountHint:
      amount === null
        ? '审批金额要 ≥ 本次差异合计（还没数完，先补齐实盘再申请）'
        : `审批金额要 ≥ 本次差异合计（${amount}），否则批了也用不上`,
    reasonHint: '例如：盘库时发现帘头受潮，实物已报废',
  }
}

/** 超授信：ref = 客户手机号；金额门槛 = 本次超出额。 */
export function creditOverrideDraft(input: {
  customerPhone: string
  customerName?: string | null
  excess: number | null
}): ApprovalDraft {
  return {
    objectType: 'credit_override',
    objectRef: input.customerPhone,
    objectLabel: input.customerName ?? input.customerPhone,
    defaultAmount: input.excess,
    amountHint:
      input.excess === null
        ? '审批金额要 ≥ 本次超出额，否则批了也用不上'
        : `审批金额要 ≥ 本次超出额（${input.excess}），否则批了也用不上`,
    reasonHint: '例如：老客户本月集中下单，临时提额',
  }
}

/**
 * 从「超出客户授信额度」的**服务端原话**里生成授信申请草稿（issue #7374 段 4）。
 *
 * 为什么做成纯函数：订单创建页是个多步向导，把「解析尚缺额 + 兜底」的判据塞进页面测试会很脆；
 * 抽出来后可以逐句断言不同文案形态。**不是**授信拒绝的文案 ⇒ 返回 `null`（页面上不该凭空冒入口）。
 */
export function creditDraftFromRejection(
  message: string,
  ctx: { customerPhone: string; customerName?: string | null; fallbackAmount: number | null },
): ApprovalDraft | null {
  if (!message || !message.includes('超出客户授信额度')) return null
  const phone = (ctx.customerPhone || '').trim()
  if (!phone) return null
  // 千分位逗号要一起吃掉：`尚缺 ¥1,200.50` 若只认到 `1`，申请的额度会小 1000+ 倍 ⇒ 批了还是过不了
  const shortfall = message.match(/尚缺\s*¥?\s*([0-9][0-9,]*(?:\.[0-9]+)?)/)
  // 金额取「尚缺额」（批多了会白占额度）；解析不到才退回订单实收总额
  const excess = shortfall ? Number(shortfall[1].replace(/,/g, '')) : ctx.fallbackAmount
  return creditOverrideDraft({
    customerPhone: phone,
    customerName: ctx.customerName ?? null,
    excess: Number.isFinite(excess as number) ? (excess as number) : null,
  })
}
