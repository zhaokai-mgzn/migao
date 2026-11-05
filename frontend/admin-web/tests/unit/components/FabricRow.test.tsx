// case_ids: MC-243
/**
 * `components/orders/order-create/FabricRow.tsx` —— 下单页切片的**布料行**
 * （issue #8725 第一档）。单一职责：按米卖布时的米数 / 单价 / 卷数录入。
 *
 * 判据是 issue #4493 的裁定：布料单**无加工** ⇒ 这一行里不许出现宽高 / 工艺规格 /
 * 加工项 / 加工费（那些控件对布料全是噪音，而且会让人以为布料也要算料）。
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { FabricRow } from '@/components/orders/order-create/FabricRow'
import { createEmptyLineItem } from '@/lib/order-create/calc'

function renderRow(overrides: Partial<Parameters<typeof FabricRow>[0]> = {}) {
  const line = createEmptyLineItem('g1')
  line.saleForm = '布料'
  return render(
    <FabricRow
      line={line}
      errors={{}}
      onChangeQty={vi.fn()}
      onChangePrice={vi.fn()}
      onChangeRollCount={vi.fn()}
      onChangeRollLength={vi.fn()}
      {...overrides}
    />
  )
}

describe('FabricRow — 布料行', () => {
  it('只有米数 / 单价 / 卷数 / 卷长四个录入面（**没有**加工）', () => {
    const { container } = renderRow()
    expect(screen.getByText('数量')).toBeInTheDocument()
    expect(screen.getByText('单价 (¥/米)')).toBeInTheDocument()
    expect(screen.getByText('卷数')).toBeInTheDocument()
    expect(screen.getByText('每卷米数')).toBeInTheDocument()
    // 反向：布料行不许出现加工侧的**录入面**（「没有加工费」这句说明是有意的告知，不算噪音）
    for (const noise of ['用料米数', '窗宽 (米)', '窗高 (米)', '用料与规格', '加工项']) {
      expect(container.textContent).not.toContain(noise)
    }
    expect(container.textContent).toContain('布料按米计价：没有加工费，也不生成加工单')
  })

  it('卷数 / 卷长的校验错误各自具名渲染（不是一处通用提示）', () => {
    const line = createEmptyLineItem('g1')
    line.saleForm = '布料'
    const { getByTestId } = renderRow({
      line,
      errors: {
        [`line_${line.id}_rollCount`]: '卷数必须是正整数',
        [`line_${line.id}_rollLengthM`]: '每卷米数必须大于 0',
      },
    })
    expect(getByTestId('roll-count-error').textContent).toBe('卷数必须是正整数')
    expect(getByTestId('roll-length-error').textContent).toBe('每卷米数必须大于 0')
  })

  it('整卷体积差提示按「行米数 vs 卷数 × 卷长」实时算（不改写行米数）', () => {
    const line = createEmptyLineItem('g1')
    line.saleForm = '布料'
    line.quantity = 117
    line.rollCount = 2
    line.rollLengthM = 50
    const { container, getByTestId } = renderRow({ line })
    expect(getByTestId('roll-diff').textContent).toContain('整卷合计 2 × 50 = 100 米')
    // 负差额（整卷 100 < 行米数 117）⇒ 不出「整卷大于行米数」的告警
    expect(container.textContent).not.toContain('系统不会自动改数量')
  })
})
