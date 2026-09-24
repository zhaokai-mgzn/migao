'use client'

/**
 * 「识别到的明细 ⇒ **选品**」面板（issue #5345）—— 订单侧建订单行的**必经一步**。
 *
 * ## 为什么必须有这一步
 * 识别出来的商品名 **≠** 目录里的商品（图上写「雪尼尔遮光窗帘」，目录里可能叫
 * 「雪尼尔 遮光窗帘 成品」）⇒ **不能识别即建行**（那是猜商品、猜错就是钱错）。
 * 本面板把「给候选 + 说清为什么 + 人来选」摆到商家面前：
 * 每条明细一行，候选按相似度排序并附**可核对的理由**（重合 N/M 字 / 规格命中），
 * 末位恒为「**都不是**」（匹配不到时的出口）。
 *
 * ## 🔴 三条不变量（判据见 `tests/unit/lib/order-line-match.test.ts` 与
 * `tests/unit/pages/orders-new-image-lines.test.tsx`）
 * 1. **不落库**：本组件**没有任何 API 调用**，只 `onPick` / `onSkipAll` / `onClose` 回调
 *    —— 建行由页面完成，「提交」永远是人在页面上点按钮；
 * 2. **不猜商品**：只有商家点了某个候选才会建行；不点 / 点「都不是」⇒ **不建行**（明细留在备注）；
 * 3. **单向**：本组件**零引用** `craft-calc-request` / 任何算料实现 —— 门幅、用料、加工类型
 *    一律由页面既有的推导链算（本面板不持有第二份口径）。
 */
import { Modal, Button } from '@/components/ui'
import { RECOGNIZE_SOURCE_TAG } from '@/lib/image-recognize'
import { NO_MATCH_CHOICE, NO_MATCH_LABEL, type DetailEntry, type LineCandidate } from '@/lib/order-line-match'

/** 一条明细当前的状态（`resolved` 非空 ⇒ 这条已经处理过；**条目按索引稳定**，不因处理而移位） */
export interface PickerEntryState {
  entry: DetailEntry
  options: LineCandidate[]
  /** 候选还在查（服务端按关键词搜目录）⇒ 先显示"匹配中…"，不给假的候选 */
  loading: boolean
  /** 已处理：`{ productId, label }` —— `NO_MATCH_CHOICE` 表示商家选了「都不是」 */
  resolved: { productId: string; label: string } | null
}

interface OrderLinePickerProps {
  entries: PickerEntryState[]
  onPick: (entry: DetailEntry, productId: string) => void
  /** 「都不建行（跳过剩余）」—— 一次性放弃剩下的明细（它们只留在备注里） */
  onSkipAll: () => void
  onClose: () => void
}

export default function OrderLinePicker({
  entries,
  onPick,
  onSkipAll,
  onClose,
}: OrderLinePickerProps) {
  const open = entries.length > 0
  const pending = entries.filter((e) => e.resolved === null).length

  return (
    <Modal
      open={open}
      onClose={onClose}
      width={640}
      title={`识别到 ${entries.length} 条明细 —— 请选择商品`}
      footer={
        <div className="flex items-center justify-between gap-2">
          <span className="text-xs text-neutral-500">
            {pending > 0 ? `还有 ${pending} 条待选` : '已全部处理'}
          </span>
          <Button type="button" variant="secondary" onClick={onSkipAll} data-testid="order-line-picker-skip-all">
            都不建行（跳过剩余）
          </Button>
        </div>
      }
    >
      <div data-testid="order-line-picker" className="space-y-4">
        <p className="text-xs leading-5 text-neutral-500">
          识别到的明细不会自动建行 —— 每条都要你选一个商品（系统只按名称/规格给候选，不替你拍板）；
          匹配不到就点「{NO_MATCH_LABEL}」，那条明细只留在备注里。
        </p>
        {entries.map((item, index) => (
          <div
            key={`${item.entry.name}-${index}`}
            data-testid={`order-line-picker-entry-${index}`}
            className="rounded-lg border border-neutral-200 bg-neutral-50/60 px-3 py-2"
          >
            <div className="flex items-baseline justify-between gap-2">
              <span className="text-sm font-medium text-neutral-900">{item.entry.name}</span>
              <span className="shrink-0 text-xs text-neutral-500">
                {item.entry.quantity !== null ? `数量 ${item.entry.quantity}` : '数量未逐条对应'}
              </span>
            </div>
            {item.entry.priceHint !== null && (
              <p
                data-testid={`order-line-picker-price-hint-${index}`}
                className="mt-1 text-xs text-amber-700"
              >
                图上写「{item.entry.priceHint}」—— 行价一律取自目录 / SKU（识别的价格不是真值）
              </p>
            )}
            {item.resolved !== null ? (
              <p
                data-testid={`order-line-picker-resolved-${index}`}
                className="mt-1.5 text-xs text-neutral-600"
              >
                {item.resolved.productId === NO_MATCH_CHOICE
                  ? `${RECOGNIZE_SOURCE_TAG} 已跳过「${item.entry.name}」—— 不建行，明细留在备注`
                  : `${RECOGNIZE_SOURCE_TAG} 已建订单行：${item.resolved.label}（请在行上核对数量 / 规格 / 单价）`}
              </p>
            ) : item.loading ? (
              <p className="mt-1.5 text-xs text-neutral-400">正在匹配目录里的商品…</p>
            ) : (
              <div className="mt-2 space-y-1.5">
                {item.options.map((option) => (
                  <button
                    key={option.productId}
                    type="button"
                    data-testid={`order-line-picker-option-${index}-${option.productId}`}
                    onClick={() => onPick(item.entry, option.productId)}
                    className="w-full rounded border border-neutral-300 bg-white px-3 py-2 text-left transition-colors hover:border-primary-500"
                  >
                    <span className="text-sm text-neutral-900">{option.productName}</span>
                    <span
                      data-testid={`order-line-picker-reason-${index}-${option.productId}`}
                      className="mt-0.5 block text-xs text-neutral-500"
                    >
                      {option.reason}
                    </span>
                  </button>
                ))}
                {item.options.length === 0 && (
                  <p data-testid={`order-line-picker-no-candidate-${index}`} className="text-xs text-neutral-500">
                    目录里没有相似的商品（或候选查询失败）⇒ 只能点「{NO_MATCH_LABEL}」
                  </p>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    </Modal>
  )
}