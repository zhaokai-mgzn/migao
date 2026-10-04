// case_ids: UI-082
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { readFileSync } from 'fs'
import { join } from 'path'

vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: any) => <a href={href} {...props}>{children}</a>,
}))

import ContactPage from '@/app/(corporate)/contact/page'

describe('CorporateContactPage（官网联系页 v4：只保留在线留言 + 常见问题，issue #6291）', () => {
  it('renders page header', () => {
    render(<ContactPage />)
    expect(screen.getByRole('heading', { level: 1, name: '联系我们' })).toBeInTheDocument()
  })

  it('renders header description（按业务场景演示 + 不公示价格）', () => {
    render(<ContactPage />)
    expect(screen.getByText('按业务场景演示')).toBeInTheDocument()
    expect(screen.getByText('不公示价格 · 按需报价')).toBeInTheDocument()
  })

  it('renders 留言引导（四类常见诉求）', () => {
    render(<ContactPage />)
    expect(screen.getByText('想看产品演示')).toBeInTheDocument()
    expect(screen.getByText('想聊 AI 客服边界')).toBeInTheDocument()
    expect(screen.getByText('想评估落地成本')).toBeInTheDocument()
    expect(screen.getByText('想了解合作与代理')).toBeInTheDocument()
  })

  it('renders 入驻通道（不必等回信，直接提交入驻申请）', () => {
    render(<ContactPage />)
    const registerLink = screen.getByText('去提交入驻申请').closest('a')
    expect(registerLink).toHaveAttribute('href', '/register')
    expect(screen.getAllByText(/通过即自动开通账号/).length).toBeGreaterThanOrEqual(1)
  })

  it('renders online message form section', () => {
    render(<ContactPage />)
    expect(screen.getByText('在线留言')).toBeInTheDocument()
    expect(screen.getByText('给我们留言')).toBeInTheDocument()
  })

  it('renders form fields', () => {
    render(<ContactPage />)
    expect(screen.getByLabelText(/姓名/)).toBeInTheDocument()
    expect(screen.getByLabelText(/电话/)).toBeInTheDocument()
    expect(screen.getByLabelText(/邮箱/)).toBeInTheDocument()
    expect(screen.getByLabelText(/留言内容/)).toBeInTheDocument()
  })

  it('renders submit button', () => {
    render(<ContactPage />)
    expect(screen.getByText('提交留言')).toBeInTheDocument()
  })

  it('提交成功后有成功反馈（反馈不再自动消失）', async () => {
    const user = userEvent.setup()
    render(<ContactPage />)
    await user.type(screen.getByLabelText(/姓名/), '张老板')
    await user.type(screen.getByLabelText(/电话/), '13800138000')
    await user.type(screen.getByLabelText(/邮箱/), 'boss@example.com')
    await user.type(screen.getByLabelText(/留言内容/), '窗帘店 3 家门店，想了解 AI 客服落地成本')
    await user.click(screen.getByText('提交留言'))
    expect(await screen.findByText('留言提交成功')).toBeInTheDocument()
  })

  it('renders 常见问题四条（含 AI 边界与价格口径）', () => {
    render(<ContactPage />)
    expect(screen.getByText('开通需要多久？')).toBeInTheDocument()
    expect(screen.getByText('需要我们自己准备服务器吗？')).toBeInTheDocument()
    expect(screen.getByText('AI 会替我做主退款、改价或取消订单吗？')).toBeInTheDocument()
    expect(screen.getByText('价格在哪里看？')).toBeInTheDocument()
    expect(screen.getByText(/本页面不公示价格/)).toBeInTheDocument()
  })

  it('宣传真实性：联系页不得出现占位联系方式（电话 / 邮箱 / 地址 / 通勤话术）', () => {
    render(<ContactPage />)
    expect(screen.queryByText(/400-888-8888/)).not.toBeInTheDocument()
    expect(screen.queryByText(/contact@migao-ai\.com/)).not.toBeInTheDocument()
    expect(screen.queryByText(/浙江省杭州市余杭区文一西路000号/)).not.toBeInTheDocument()
    expect(screen.queryByText(/地铁5号线/)).not.toBeInTheDocument()
    expect(screen.queryByText(/周一至周五 9:00-18:00/)).not.toBeInTheDocument()
    // 旧地图占位也不得回归
    expect(screen.queryByText('地图加载区域')).not.toBeInTheDocument()
  })

  it('视觉口径：不再使用通用蓝色渐变模板', () => {
    const { container } = render(<ContactPage />)
    expect(container.innerHTML).not.toContain('from-blue-600')
    expect(container.innerHTML).not.toContain('to-indigo-800')
  })

  // ── 服务端组件契约（issue #6307） ─────────────────────────────
  // 这一页必须是服务端组件：声明 'use client' 会让它在 SSR 阶段整段不渲染，
  // 正文进不了初始 HTML（SEO / 无 JS 环境读到空壳），而浏览器里看起来完全正常。
  // 形态类判据在 corporate-pages-server-component-guard.test.ts；这里是**本页**的实例判据。

  it("page.tsx 是服务端组件：不声明 'use client'，而是把交互部分 import 成同目录子组件", () => {
    const src = readFileSync(
      join(process.cwd(), 'src/app/(corporate)/contact/page.tsx'),
      'utf-8',
    ).replace(/^\uFEFF/, '')
    const firstStatement = src
      .split(/\r?\n/)
      .find((l) => l.trim() !== '' && !/^\s*(\/\/|\/\*|\*)/.test(l))
    expect(firstStatement?.trim(), 'contact 页必须是服务端组件（否则正文进不了初始 HTML）').not.toMatch(
      /^['"]use client['"]/,
    )
    // 反向自证：交互态确实被拆出去了（不是把 'use client' 删掉就完事）
    expect(src).toMatch(/import\s+ContactForm\s+from\s+['"]\.\/ContactForm['"]/)
  })

  it('表单校验口径不变：空白提交逐字段报错，且不出现成功反馈', async () => {
    const user = userEvent.setup()
    render(<ContactPage />)
    await user.click(screen.getByText('提交留言'))
    expect(await screen.findByText('请输入您的姓名')).toBeInTheDocument()
    expect(screen.getByText('请输入您的联系电话')).toBeInTheDocument()
    expect(screen.getByText('请输入您的电子邮箱')).toBeInTheDocument()
    expect(screen.getByText('请输入留言内容')).toBeInTheDocument()
    expect(screen.queryByText('留言提交成功')).not.toBeInTheDocument()
  })
})
