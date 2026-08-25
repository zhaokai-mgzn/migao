// case_ids: UI-003
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import TodayOverviewBar, { processingRatio, formatOrderChange } from '@/components/dashboard/TodayOverviewBar'

describe('TodayOverviewBar 组件', () => {
  it('渲染「订单环比 / 含加工占比 / 低库存预警」三个区块', () => {
    render(<TodayOverviewBar orderChange={25.5} processingCount={3} pendingCount={8} lowStockCount={2} />)
    expect(screen.getByText('订单环比')).toBeInTheDocument()
    expect(screen.getByText('含加工占比')).toBeInTheDocument()
    expect(screen.getByText('低库存预警')).toBeInTheDocument()
  })

  it('渲染米宝品牌与「今日经营速览」标题', () => {
    render(<TodayOverviewBar orderChange={0} processingCount={0} pendingCount={0} lowStockCount={0} />)
    expect(screen.getByText(/今日经营速览/)).toBeInTheDocument()
    expect(screen.getByText('AI 生成内容仅供参考')).toBeInTheDocument()
  })

  it('订单环比渲染 API 派生数值（带符号），无硬编码', () => {
    render(<TodayOverviewBar orderChange={25.5} processingCount={0} pendingCount={0} lowStockCount={0} />)
    expect(screen.getByText('+25.5%')).toBeInTheDocument()
  })

  it('订单环比负值渲染负号', () => {
    render(<TodayOverviewBar orderChange={-12.3} processingCount={0} pendingCount={0} lowStockCount={0} />)
    expect(screen.getByText('-12.3%')).toBeInTheDocument()
  })

  it('含加工占比 = processingCount / pendingCount', () => {
    render(<TodayOverviewBar orderChange={0} processingCount={3} pendingCount={8} lowStockCount={0} />)
    expect(screen.getByText('38%')).toBeInTheDocument()
  })

  it('低库存预警渲染 SKU 数', () => {
    render(<TodayOverviewBar orderChange={0} processingCount={0} pendingCount={0} lowStockCount={5} />)
    expect(screen.getByText('5 款')).toBeInTheDocument()
  })

  it('改变 props 数值则渲染数值随之变化（证明无硬编码固定值）', () => {
    const { rerender } = render(
      <TodayOverviewBar orderChange={1} processingCount={1} pendingCount={2} lowStockCount={1} />,
    )
    expect(screen.getByText('+1%')).toBeInTheDocument()
    expect(screen.getByText('50%')).toBeInTheDocument()
    expect(screen.getByText('1 款')).toBeInTheDocument()

    rerender(<TodayOverviewBar orderChange={9} processingCount={3} pendingCount={4} lowStockCount={7} />)
    expect(screen.getByText('+9%')).toBeInTheDocument()
    expect(screen.getByText('75%')).toBeInTheDocument()
    expect(screen.getByText('7 款')).toBeInTheDocument()
  })
})

describe('processingRatio（含加工占比公式）', () => {
  it('范围 [0,1]：正常输入返回占比', () => {
    expect(processingRatio(3, 8)).toBeCloseTo(0.375)
  })

  it('pendingCount 为 0 时返回 0（不得 NaN/Infinity）', () => {
    expect(processingRatio(3, 0)).toBe(0)
    expect(Number.isFinite(processingRatio(3, 0))).toBe(true)
  })

  it('processingCount 超过 pendingCount 时 clamp 到 1', () => {
    expect(processingRatio(10, 5)).toBe(1)
  })
})

describe('formatOrderChange（订单环比格式化）', () => {
  it('正数带加号', () => {
    expect(formatOrderChange(25.5)).toBe('+25.5%')
  })

  it('负数带负号', () => {
    expect(formatOrderChange(-12.3)).toBe('-12.3%')
  })

  it('0 渲染 0%', () => {
    expect(formatOrderChange(0)).toBe('0%')
  })

  it('非有限值渲染 —（不得 NaN/Infinity）', () => {
    expect(formatOrderChange(NaN)).toBe('—')
    expect(formatOrderChange(Infinity)).toBe('—')
  })
})
