// case_ids: UI-003, DA-005
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import TodayOverviewBar, {
  processingRatio,
  formatOrderChange,
  buildInsightSentence,
} from '@/components/dashboard/TodayOverviewBar'

describe('TodayOverviewBar 组件（一句话经营解读）', () => {
  it('渲染「米宝 · 今日经营速览」品牌标签', () => {
    render(
      <TodayOverviewBar
        todayOrders={10}
        todaySales={39800}
        orderChange={25.5}
        salesChange={-12.3}
        processingCount={3}
        pendingCount={8}
        lowStockCount={2}
      />,
    )
    expect(screen.getByText(/今日经营速览/)).toBeInTheDocument()
  })

  it('一句话解读串联今日订单/销售额/环比/提醒，数字来自 API 派生', () => {
    render(
      <TodayOverviewBar
        todayOrders={10}
        todaySales={39800}
        orderChange={25.5}
        salesChange={-12.3}
        processingCount={3}
        pendingCount={8}
        lowStockCount={2}
      />,
    )
    // 主句 + 环比 + 提醒全部串联在一句话里（子串断言，无硬编码写死值）
    expect(screen.getByText(/今日订单 10 单、销售额 ¥3\.98万/)).toBeInTheDocument()
    expect(screen.getByText(/较昨日订单 \+25\.5%、销售额 -12\.3%/)).toBeInTheDocument()
    expect(screen.getByText(/含加工订单占 38%/)).toBeInTheDocument()
    expect(screen.getByText(/2 款商品库存偏低/)).toBeInTheDocument()
  })

  it('无提醒项（加工占比 0、低库存 0）时只输出主句+环比，不出现提醒文案', () => {
    render(
      <TodayOverviewBar
        todayOrders={5}
        todaySales={0}
        orderChange={0}
        salesChange={0}
        processingCount={0}
        pendingCount={0}
        lowStockCount={0}
      />,
    )
    expect(screen.getByText(/今日订单 5 单/)).toBeInTheDocument()
    expect(screen.queryByText(/含加工订单占/)).not.toBeInTheDocument()
    expect(screen.queryByText(/库存偏低/)).not.toBeInTheDocument()
  })

  it('今日无订单且无销售额时展示空态解读', () => {
    render(
      <TodayOverviewBar
        todayOrders={0}
        todaySales={0}
        orderChange={0}
        salesChange={0}
        processingCount={0}
        pendingCount={0}
        lowStockCount={0}
      />,
    )
    expect(screen.getByText(/今日暂无新订单/)).toBeInTheDocument()
  })

  it('改变 props 数值则一句话随之变化（证明无硬编码固定值）', () => {
    const { rerender } = render(
      <TodayOverviewBar
        todayOrders={1}
        todaySales={100}
        orderChange={1}
        salesChange={2}
        processingCount={1}
        pendingCount={2}
        lowStockCount={1}
      />,
    )
    expect(screen.getByText(/今日订单 1 单、销售额 ¥100/)).toBeInTheDocument()

    rerender(
      <TodayOverviewBar
        todayOrders={9}
        todaySales={3000}
        orderChange={9}
        salesChange={-4}
        processingCount={3}
        pendingCount={4}
        lowStockCount={7}
      />,
    )
    expect(screen.getByText(/今日订单 9 单、销售额 ¥3,000/)).toBeInTheDocument()
    expect(screen.getByText(/较昨日订单 \+9%、销售额 -4%/)).toBeInTheDocument()
    expect(screen.getByText(/含加工订单占 75%/)).toBeInTheDocument()
    expect(screen.getByText(/7 款商品库存偏低/)).toBeInTheDocument()
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

describe('buildInsightSentence（一句话经营解读生成）', () => {
  it('主句 + 环比 + 提醒完整串联', () => {
    const s = buildInsightSentence({
      todayOrders: 10,
      todaySales: 39800,
      orderChange: 25.5,
      salesChange: -12.3,
      processingRatioPct: 38,
      lowStockCount: 2,
    })
    expect(s).toContain('今日订单 10 单、销售额 ¥3.98万')
    expect(s).toContain('较昨日订单 +25.5%、销售额 -12.3%')
    expect(s).toContain('含加工订单占 38%')
    expect(s).toContain('2 款商品库存偏低')
  })

  it('全零数据输出空态解读（不得 NaN/Infinity）', () => {
    const s = buildInsightSentence({
      todayOrders: 0,
      todaySales: 0,
      orderChange: 0,
      salesChange: 0,
      processingRatioPct: 0,
      lowStockCount: 0,
    })
    expect(s).toContain('今日暂无新订单')
    expect(s).not.toContain('NaN')
    expect(s).not.toContain('Infinity')
  })

  it('无提醒项时省略提醒片段', () => {
    const s = buildInsightSentence({
      todayOrders: 5,
      todaySales: 1000,
      orderChange: 0,
      salesChange: 0,
      processingRatioPct: 0,
      lowStockCount: 0,
    })
    expect(s).toContain('今日订单 5 单、销售额 ¥1,000')
    expect(s).not.toContain('含加工订单占')
    expect(s).not.toContain('库存偏低')
  })
})
