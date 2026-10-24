// case_ids: UI-119
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

/**
 * 作业单生产明细里的**质检区**（`QualityCheckPanel`，issue #7140 = #5652 的商家面）。
 *
 * ## 为什么要有这一区
 *
 * 商家是**按单**看生产的：他在「生产明细」上要看的是「这一张单的每一件成品帘检过了没有、
 * 判了什么」。独立质检员也有同样的诉求（他手上就是一张单）—— 所以入口既在「质检记录」菜单页，
 * 也在**本单的生产明细**里（用户 2026-10-17 选定的落位 = 两者都要）。
 *
 * ## 本文件钉住的事（每条都能单独变红）
 *
 * ① **未检 ≠ 合格**：没有记录 ⇒ 「未检」；有记录 ⇒ 用服务端判定（含原因 / 检验人 / 检验时刻）；
 * ② 🔴 **最新一条胜出**（同一件多条 = 返工后复检）：取读面给的**第一条**（读面已按时间倒序），
 *    本组件**不重排**（排序口径在服务端，前端重排 = 第二份口径）；
 * ③ **录入口**：未检 ⇒「录入判定」、已判 ⇒「复检」，点开就是同一个表单；
 * ④ 🔴 **读失败不画成「没有质检」**：失败锚常驻，空态**不出现**（同族 issue #6691 / #6703）。
 */

const mockList = vi.fn()
const mockCreate = vi.fn()

vi.mock('@/lib/api', () => ({
  qualityInspectionApi: {
    list: (...args: unknown[]) => mockList(...args),
    create: (...args: unknown[]) => mockCreate(...args),
  },
}))

import QualityCheckPanel from '@/components/production/QualityCheckPanel'
import type { ProductionPosition } from '@/types'

const positions: ProductionPosition[] = [
  {
    position_name: '布帘',
    order_item_id: 'item-1',
    product_name: '布艺遮光帘A',
    operations: [],
  },
  {
    position_name: '纱帘',
    order_item_id: 'item-2',
    product_name: '纱帘B',
    operations: [],
  },
]

const reworkRecord = {
  id: 'qi-1',
  order_item_id: 'item-1',
  processing_order_id: 'po-1',
  position_name: '布艺遮光帘A 米白',
  result: 'rework' as const,
  result_label: '返工',
  reason: '缝线开裂',
  inspector_name: '质检员小李',
  inspected_at: '2026-10-17T09:00:00+08:00',
}

const passRecord = {
  ...reworkRecord,
  id: 'qi-2',
  result: 'pass' as const,
  result_label: '合格',
  reason: null,
  inspected_at: '2026-10-17T11:00:00+08:00',
}

describe('质检区（作业单生产明细内嵌）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockCreate.mockResolvedValue({ data: { data: passRecord } })
  })

  it('① 逐件成品帘显示最新判定：有记录=判定（含原因/检验人/时刻），无记录=未检', async () => {
    mockList.mockResolvedValue({ data: { data: [passRecord] } })
    render(<QualityCheckPanel processingOrderId="po-1" positions={positions} />)

    await waitFor(() => expect(screen.getByTestId('quality-state-item-1')).toHaveTextContent('合格'))
    expect(screen.getByTestId('quality-state-item-2')).toHaveTextContent('未检')
    expect(screen.getByText('质检员小李')).toBeInTheDocument()
    expect(screen.getByTestId('quality-record-item-1')).toHaveTextContent('复检')
    expect(screen.getByTestId('quality-record-item-2')).toHaveTextContent('录入判定')
  })

  it('② 同一件多条记录 ⇒ 取读面第一条（不在前端重排时间）', async () => {
    // 第一条是最新（服务端倒序）；第二条虽"更晚"也不该被选中 —— 见证行：故意让旧记录的时间更晚
    mockList.mockResolvedValue({
      data: { data: [passRecord, { ...reworkRecord, inspected_at: '2026-10-18T23:00:00+08:00' }] },
    })
    render(<QualityCheckPanel processingOrderId="po-1" positions={positions} />)

    await waitFor(() => expect(screen.getByTestId('quality-state-item-1')).toHaveTextContent('合格'))
  })

  it('③ 点「录入判定」打开弹窗，提交后带上这件成品帘的 id', async () => {
    const user = userEvent.setup()
    mockList.mockResolvedValue({ data: { data: [] } })
    render(<QualityCheckPanel processingOrderId="po-1" positions={positions} />)

    await waitFor(() => expect(screen.getByTestId('quality-record-item-2')).toBeInTheDocument())
    await user.click(screen.getByTestId('quality-record-item-2'))
    // issue #7160：录入 = 弹窗（与「质检记录」页同一份表单，两处都必须是弹窗）
    expect(screen.getByRole('dialog', { name: /录入质检判定/ })).toBeInTheDocument()
    await user.click(screen.getByTestId('quality-result-scrap'))
    await user.type(screen.getByTestId('quality-inspection-reason'), '尺寸偏差')
    await user.click(screen.getByRole('button', { name: '提交判定' }))

    await waitFor(() =>
      expect(mockCreate).toHaveBeenCalledWith({
        order_item_id: 'item-2',
        result: 'scrap',
        reason: '尺寸偏差',
      }),
    )
  })

  it('④ 🔴 读失败 ⇒ 失败锚常驻，且不出现「本单还没有…」这类空态断言', async () => {
    mockList.mockRejectedValue(new Error('500'))
    render(<QualityCheckPanel processingOrderId="po-1" positions={positions} />)

    await waitFor(() => expect(screen.getByTestId('quality-inspection-load-error')).toBeInTheDocument())
    expect(screen.getByTestId('quality-inspection-load-error')).toHaveAttribute('role', 'alert')
    expect(screen.queryByTestId('quality-inspection-empty')).not.toBeInTheDocument()
    expect(screen.queryByTestId('quality-state-item-1')).not.toBeInTheDocument()
  })
})
