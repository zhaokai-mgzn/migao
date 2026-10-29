// case_ids: UI-003, DA-005, DA-006, DA-007
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'

/**
 * 「黄金策 · 今日经营」合并卡（issue #8114）的**四态**判据。
 *
 * 合并前的形态（用户 2026-10-29 截图圈出两块）：速览条 + 简报卡**各占一张卡**，
 * 都在说「订单 / 销售额 / 66 款商品库存偏低」—— 重复说同一件事（§31 P2）。
 *
 * 合并后**一张卡**：收起态 = 速览那一句话；展开态 = 那句话 + 简报内容。
 * 四种状态都在这里各有一条断言（页面级接线判据在 `pages/dashboard-first-screen.test.tsx`）：
 *   ① 开启 + 有数据 ⇒ 展开出完整简报；
 *   ② 开启 + 未生成 ⇒ 「今日简报尚未生成」+ 生成入口（沿用 `briefing-collapsed-hint`）；
 *   ③ **未开启**        ⇒ 🔴 卡片**仍在**（速览不依赖简报开关），展开说「未开启」+ 去开启入口；
 *   ④ 加载中            ⇒ 收起态不等简报，展开出简报骨架。
 */

vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: any) => <a href={href} {...props}>{children}</a>,
}))

const getToday = vi.fn()
vi.mock('@/lib/api', () => ({
  briefingApi: { getToday: () => getToday() },
}))

import DailyBusinessCard from '@/components/dashboard/DailyBusinessCard'

/** 速览入参（真实数据形态：10 单 / ¥3.98 万 / 环比 / 含加工 3/8 / 2 款低库存） */
const overview = {
  todayOrders: 10,
  todaySales: 39800,
  orderChange: 25.5,
  salesChange: -12.3,
  processingCount: 3,
  pendingCount: 8,
  lowStockCount: 2,
}

function mockBriefingWithData() {
  getToday.mockResolvedValue({
    data: {
      data: {
        generated: true,
        verifyStatus: 'verified',
        content: {
          summary: '昨日订单 5 单，经营平稳',
          review: [{ label: '今日订单', value: 5, unit: '单', change: '较昨日 +66.7%' }],
          todo: [{ priority: 'high', title: '10 个订单待发货', reason: '超过发货时效' }],
          risks: [],
          suggestions: [],
        },
        proactive_status: null,
      },
    },
  })
}

describe('DailyBusinessCard（黄金策 · 今日经营，issue #8114）', () => {
  beforeEach(() => {
    getToday.mockReset()
    mockBriefingWithData()
  })

  it('收起态（默认）= 速览那一句话：头部有标题 + AI 标记 + 可聚焦的展开按钮', () => {
    render(<DailyBusinessCard {...overview} briefingEnabled={false} />)

    expect(screen.getByTestId('today-overview-sentence').textContent).toContain('今日订单 10 单、销售额 ¥3.98万')
    expect(screen.getByText(/黄金策 · 今日经营/)).toBeInTheDocument()
    expect(screen.getByText('AI 生成内容仅供参考')).toBeInTheDocument()

    const toggle = screen.getByTestId('briefing-toggle')
    expect(toggle.tagName).toBe('BUTTON')           // 键盘可聚焦
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(toggle.textContent).toContain('展开')
    // 收起态不渲染简报内容（不是 CSS 隐藏）
    expect(screen.queryByText('昨日回顾')).toBeNull()
  })

  it('① 开启 + 有数据 ⇒ 展开出完整简报（摘要 / 昨日回顾 / 今日必办），再收起消失', async () => {
    render(<DailyBusinessCard {...overview} briefingEnabled />)

    fireEvent.click(screen.getByTestId('briefing-toggle'))
    await waitFor(() => expect(screen.getByText('昨日回顾')).toBeInTheDocument())
    expect(screen.getByText('昨日订单 5 单，经营平稳')).toBeInTheDocument()
    expect(screen.getByText('10 个订单待发货')).toBeInTheDocument()
    // 展开态下速览那句仍在（同一张卡里两层信息，不是二选一）
    expect(screen.getByTestId('today-overview-sentence')).toBeInTheDocument()
    expect(screen.getByTestId('briefing-toggle')).toHaveAttribute('aria-expanded', 'true')
    // 空态提示与「有数据」是两套形态，不许同屏
    expect(screen.queryByTestId('briefing-collapsed-hint')).toBeNull()

    fireEvent.click(screen.getByTestId('briefing-toggle'))
    await waitFor(() => expect(screen.queryByText('昨日回顾')).toBeNull())
    expect(screen.getByTestId('briefing-toggle')).toHaveAttribute('aria-expanded', 'false')
  })

  it('② 开启 + 未生成 ⇒ 展开说「今日简报尚未生成」+ 生成入口（沿用 briefing-collapsed-hint）', async () => {
    getToday.mockResolvedValue({ data: { data: { generated: false, verifyStatus: null, content: null } } })
    render(<DailyBusinessCard {...overview} briefingEnabled />)

    fireEvent.click(screen.getByTestId('briefing-toggle'))
    const hint = await screen.findByTestId('briefing-collapsed-hint')
    expect(hint.textContent).toContain('今日简报尚未生成')
    expect(hint.textContent).toContain('查看设置')
    // 卡片与速览那句仍在
    expect(screen.getByTestId('daily-business-card')).toBeInTheDocument()
    expect(screen.getByTestId('today-overview-sentence')).toBeInTheDocument()
  })

  it('③ 🔴 未开启 ⇒ 卡片**仍在**（速览不依赖简报开关），展开说「未开启」+ 去开启入口', () => {
    render(<DailyBusinessCard {...overview} briefingEnabled={false} />)

    // 最易做错的一条：开关关掉不等于把整张卡藏起来
    expect(screen.getByTestId('daily-business-card')).toBeInTheDocument()
    expect(screen.getByTestId('today-overview-sentence').textContent).toContain('今日订单 10 单')
    // 未开启不请求简报
    expect(getToday).not.toHaveBeenCalled()
    // 收起态不带简报空态文字
    expect(screen.queryByTestId('briefing-collapsed-hint')).toBeNull()

    fireEvent.click(screen.getByTestId('briefing-toggle'))
    const hint = screen.getByTestId('briefing-collapsed-hint')
    expect(hint.textContent).toContain('每日经营简报未开启')
    expect(hint.textContent).toContain('开启后每日自动整理经营要点')
    // 不是「加载中」
    expect(screen.queryByTestId('briefing-skeleton')).toBeNull()
  })

  it('④ 加载中 ⇒ 收起态**不等简报**（先显示速览），展开才出简报骨架', async () => {
    getToday.mockReturnValue(new Promise(() => {})) // 永不落定
    render(<DailyBusinessCard {...overview} briefingEnabled />)

    // 收起态：速览那句话在，简报骨架不在
    expect(screen.getByTestId('today-overview-sentence').textContent).toContain('今日订单 10 单')
    expect(screen.queryByTestId('briefing-skeleton')).toBeNull()

    fireEvent.click(screen.getByTestId('briefing-toggle'))
    expect(await screen.findByTestId('briefing-skeleton')).toBeInTheDocument()
    expect(screen.getByTestId('today-overview-sentence')).toBeInTheDocument()
  })

  it('④ 变体：开关接口还没回来（enabled=null）⇒ 也出骨架，不先闪「未开启」', () => {
    render(<DailyBusinessCard {...overview} briefingEnabled={null} />)

    fireEvent.click(screen.getByTestId('briefing-toggle'))
    expect(screen.getByTestId('briefing-skeleton')).toBeInTheDocument()
    expect(screen.queryByText('每日经营简报未开启')).toBeNull()
    expect(getToday).not.toHaveBeenCalled()
  })

  it('负控：`stats` 读不到（null）⇒ 说「没读到」，**不说**「今日 0 单」（#6701 不回退）', () => {
    render(
      <DailyBusinessCard
        {...overview}
        todayOrders={null}
        todaySales={null}
        orderChange={null}
        salesChange={null}
        briefingEnabled={false}
      />,
    )
    const sentence = screen.getByTestId('today-overview-sentence')
    expect(sentence.textContent).toContain('经营数据没读到')
    expect(sentence.textContent).toContain('今日订单数 —')
    expect(sentence.textContent).not.toContain('今日暂无新订单')
    expect(sentence.textContent).not.toMatch(/今日订单 0 单/)
  })
})
