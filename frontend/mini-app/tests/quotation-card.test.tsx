// case_ids: OR-010, CH-010, CH-030
/**
 * QuotationCard 交互测试 — 报价单确认下单（interact 报价 → 防连点锁）
 *
 * 覆盖：报价单明细/合计渲染、确认下单按钮点击触发 onConfirm 一次后锁卡
 * （防重复下单，issue #3040 收尾 #3038）。
 */
import React from 'react'
import '@testing-library/jest-dom'
import { render, screen, fireEvent } from '@testing-library/react'
import QuotationCard from '../src/components/cards/QuotationCard'

describe('QuotationCard — 报价单确认下单', () => {
  const baseQuote = {
    fullness: 2,
    fabric_meters: 6.5,
    fabric_cost: 780,
    processing_cost: 193.6,
    accessory_cost: 0,
    install_cost: 0,
    total: 973.6,
    breakdown: [
      { name: '主帘面料', detail: '雪尼尔 2.8米宽 × 6.5米', cost: 780 },
      { name: '加工费', detail: '韩式褶', cost: 193.6 },
    ],
  }

  afterEach(() => {
    jest.clearAllMocks()
  })

  it('渲染报价明细与合计', () => {
    render(<QuotationCard data={baseQuote} />)
    expect(screen.getByText(/973\.60/)).toBeTruthy()
    expect(screen.getByText(/主帘面料/)).toBeTruthy()
    expect(screen.getByText(/韩式褶/)).toBeTruthy()
  })

  it('点「确认下单」触发 onConfirm 一次后锁卡（防重复下单）', () => {
    const onConfirm = jest.fn()
    render(<QuotationCard data={baseQuote} onConfirm={onConfirm} />)
    fireEvent.click(screen.getByText('确认下单'))
    fireEvent.click(screen.getByText('确认下单'))
    expect(onConfirm).toHaveBeenCalledTimes(1)
  })

  it('实际褶倍 ≠ 理论褶倍时同时展示实际值（issue #4118 ④）', () => {
    // 客户自报 48 折场景：`fullness`=档位理论值 2，`fullness_actual`=12.3÷6.6=1.86
    render(
      <QuotationCard
        data={{ ...baseQuote, fullness: 2, fullness_actual: 1.86, fabric_meters: 12.3 }}
      />
    )
    expect(screen.getByText(/2 倍褶皱/)).toBeTruthy()
    expect(screen.getByText(/实际 1\.86 倍/)).toBeTruthy()
    expect(screen.getByText(/12\.3 米面料/)).toBeTruthy()
  })

  it('实际褶倍 = 理论褶倍时不重复标注「实际」', () => {
    render(<QuotationCard data={{ ...baseQuote, fullness: 2, fullness_actual: 2 }} />)
    expect(screen.queryByText(/实际/)).toBeNull()
  })

  it('无 fullness_actual 字段（旧载荷）时保持原渲染（向后兼容）', () => {
    render(<QuotationCard data={{ ...baseQuote, fullness: 2 }} />)
    expect(screen.getByText(/2 倍褶皱/)).toBeTruthy()
    expect(screen.queryByText(/实际/)).toBeNull()
  })
})
