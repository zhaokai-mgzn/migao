// case_ids: OR-010, CH-010, CH-030, CH-038
/**
 * QuotationCard 交互测试 — 报价单确认下单（interact 报价 → 防连点锁）
 *
 * 覆盖：报价单明细/合计渲染、确认下单按钮点击触发 onConfirm 一次后锁卡
 * （防重复下单，issue #3040 收尾 #3038）。
 *
 * issue #4355（设计文档 §4.9 ① 报价单）：工艺规格展示 —— 与 mini-app 同款卡片同源实现
 * （同一份 spec 三处渲染；**缺值不渲染**，绝不出现 undefined/null/NaN）。
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

  // ── issue #4355：工艺规格展示（设计文档 §4.9 ①）─────────────────────

  /** 与 `curtain_calc.build_quote` 返回同形的工艺规格键（snake_case，§4.5） */
  const craftSpec = {
    curtain_type: '布帘',
    craft: '韩褶',
    formula_used: 'fixed_height_pleats',
    open_count: 2,
    is_shaped: true,
    style: '拼色',
    special_options: ['加铅线', '双褶'],
    pleat_count: 52,
    per_panel_pleats: 26,
    pleat_spacing: 0.1,
    has_pattern: true,
    pattern_repeat: 0.32,
    processing_meters: 13.3,
  }

  it('渲染工艺规格：部位/工艺/加工类型/打开方式/是否定型/款式/特殊选项', () => {
    render(<QuotationCard data={{ ...baseQuote, ...craftSpec }} />)
    expect(screen.getByText('工艺规格')).toBeTruthy()
    expect(screen.getByText('布帘')).toBeTruthy()
    expect(screen.getByText('韩褶')).toBeTruthy()
    // 加工类型由 `formula_used` 映射（§4.2 的真值来源），不另写推导
    expect(screen.getByText('定高买宽')).toBeTruthy()
    expect(screen.getByText('双开')).toBeTruthy()
    // 「是否定型」「是否对花」都是「是」⇒ 按行断言，避免命中歧义
    expect(screen.getByText('是否定型').parentElement?.textContent).toContain('是')
    expect(screen.getByText('拼色')).toBeTruthy()
    expect(screen.getByText('加铅线、双褶')).toBeTruthy()
  })

  it('缺值不渲染：键缺席 / null / 空串 ⇒ 该行不出现，且不出现 undefined/null/NaN', () => {
    const { container } = render(
      <QuotationCard
        data={{
          ...baseQuote,
          craft: null,
          curtain_type: undefined,
          open_count: null,
          style: '',
          special_options: [],
          formula_used: undefined,
        }}
      />
    )
    expect(screen.queryByText('工艺规格')).toBeNull()
    for (const label of ['部位', '工艺', '加工类型', '打开方式', '是否定型', '款式', '特殊选项']) {
      expect(screen.queryByText(label)).toBeNull()
    }
    expect(container.textContent).not.toMatch(/undefined|null|NaN/)
  })

  it('旧载荷（无工艺键）时报价卡渲染与改动前一致（向后兼容）', () => {
    const { container } = render(<QuotationCard data={baseQuote} />)
    expect(screen.queryByText('工艺规格')).toBeNull()
    expect(container.textContent).not.toMatch(/undefined|null|NaN/)
  })
})
