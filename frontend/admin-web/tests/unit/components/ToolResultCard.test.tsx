// case_ids: PR-100, PR-101
/**
 * `ToolResultCard` 卡型分发（B 端桌面唯一的渲染入口）— issue #5188 补齐配套判据
 *
 * ## 为什么这个文件必须有（不是凑数）
 *
 * 卡型的**唯一产出源**在后端 `app/api/chat.py::_detect_card_type`，而 B 端桌面的**唯一**渲染入口
 * 就是本组件：它少一个 `case` ⇒ 后端真发过来的卡会被 `default` 吞掉，渲染成
 * 「📎 消息内容暂不支持预览」灰盒（**不可理解、不可点击**），而**不会有任何东西变红**
 * ——这正是 #3960 的缺陷形态。跨端契约（
 * `backend/ai-agent-service/tests/test_card_type_cross_end_contract.py`）只校验
 * 「case 标签集合」，**校验不了「标签背后的组件是否真渲染出东西」**：
 * `case 'x': return null` 也能过那条判据。
 *
 * ⇒ 本文件补的是**接线层**：每个卡型都真渲染出对应组件（用各卡的 testid 断言），
 * 未知卡型走可理解占位且**不回显内部类型名**（#3960 的泄漏判据）。
 */
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import ToolResultCard from '@/components/chat/ToolResultCard'
import type { CardType } from '@/types'

/**
 * 每个可产出卡型 → 渲染后必须能看到的锚点。
 *
 * 有的卡有 `data-testid`（order / production_progress / batch_stock），有的卡按文案断言
 * （ProductCard / LogisticsCard 无 testid）—— 两种都要求**真渲染出内容**，
 * 而不是「case 分支返回了某个组件」。
 */
const CARD_CASES: Array<{ type: CardType; data: Record<string, unknown>; testId?: string; text: RegExp }> = [
  {
    type: 'product_list',
    data: { products: [{ id: 'p1', name: '雪尼尔窗帘', price: 88 }] },
    text: /雪尼尔窗帘/,
  },
  {
    type: 'product_detail',
    data: { product: { id: 'p1', name: '雪尼尔窗帘', price: 88 } },
    text: /雪尼尔窗帘/,
  },
  {
    type: 'logistics',
    data: { tracking_info: { trackingNo: 'SF123456789', company: '顺丰', status: '运输中' } },
    text: /SF123456789/,
  },
  {
    type: 'order',
    data: { order: { id: 'o1', orderNo: 'ORD-1001', status: 'producing', totalAmount: 299.5 } },
    testId: 'order-card',
    text: /ORD-1001/,
  },
  {
    type: 'production_progress',
    data: { progress_percent: 40, current_operation: '韩褶' },
    testId: 'production-progress-card',
    text: /40%/,
  },
  {
    // issue #5188：批次/省料卡（米宝 B 端；`product:list` 门禁 ⇒ C 端不可达）
    type: 'batch_stock',
    data: { action: 'batches', batches: [{ batchNo: 'PC-20260901-0001', remainingMeters: 0.2 }] },
    testId: 'batch-stock-card',
    text: /PC-20260901-0001/,
  },
]

describe('ToolResultCard 卡型分发', () => {
  it('每个可产出卡型都渲染出真实内容（少一个 case ⇒ 落到占位灰盒 ⇒ 本条红）', () => {
    for (const { type, data, testId, text } of CARD_CASES) {
      const { unmount } = render(<ToolResultCard card={{ type, data }} />)
      expect(screen.getByText(text), `${type} 未渲染出预期内容`).toBeInTheDocument()
      if (testId) {
        expect(screen.getByTestId(testId), `${type} 未渲染 ${testId}`).toBeInTheDocument()
      }
      expect(screen.queryByTestId('tool-result-card-unsupported')).not.toBeInTheDocument()
      unmount()
    }
  })

  it('覆盖集合与 CardType 联合体一致（新增卡型必须同批补本表，否则本条红）', () => {
    const covered = new Set(CARD_CASES.map((c) => c.type))
    // 卡型联合的**真值**来自 `@/types`（与后端 `_detect_card_type` 收敛对齐，见该处注释）
    const declared: CardType[] = [
      'product_list', 'product_detail', 'logistics', 'order', 'production_progress', 'batch_stock',
    ]
    expect([...covered].sort()).toEqual([...declared].sort())
  })

  it('未知卡型：给可理解占位，且不回显内部类型名（#3960 泄漏判据）', () => {
    render(<ToolResultCard card={{ type: 'legacy_unknown' as CardType, data: {} }} />)
    expect(screen.getByTestId('tool-result-card-unsupported')).toBeInTheDocument()
    expect(screen.queryByText(/legacy_unknown/)).not.toBeInTheDocument()
  })

  it('红证（判别性自检）：把 batch_stock 的载荷换成空对象也不得崩、不得泄漏类型名', () => {
    // 空载荷是**合法**输入（工具成功但无数据时 `action` 仍在；这里取更严的空对象）
    render(<ToolResultCard card={{ type: 'batch_stock', data: {} }} />)
    expect(screen.getByTestId('batch-stock-card')).toBeInTheDocument()
    expect(screen.queryByText(/batch_stock/)).not.toBeInTheDocument()
  })
})
