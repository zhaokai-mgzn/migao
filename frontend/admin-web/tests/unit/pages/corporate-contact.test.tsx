// case_ids: UI-082
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { readFileSync } from 'fs'
import { join } from 'path'

vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: any) => <a href={href} {...props}>{children}</a>,
}))

import ContactPage from '@/app/(corporate)/contact/page'
import {
  findColloquialMarkers,
  findPersonifiedAi,
  findQuantifierRhetoric,
} from './copy-voice-banlist'

describe('CorporateContactPage（官网联系页 v5：按用户裁定隐藏留言表单，issue #6291 / #6326 / #6665）', () => {
  it('renders page header', () => {
    render(<ContactPage />)
    expect(screen.getByRole('heading', { level: 1, name: '联系我们' })).toBeInTheDocument()
  })

  it('renders header description（按业务场景演示 + 不公示价格）', () => {
    render(<ContactPage />)
    expect(screen.getByText('按业务场景演示')).toBeInTheDocument()
    expect(screen.getByText('不公示价格 · 按需报价')).toBeInTheDocument()
  })

  it('renders 四类常见诉求', () => {
    render(<ContactPage />)
    expect(screen.getByText('了解产品演示')).toBeInTheDocument()
    expect(screen.getByText('沟通 AI 客服边界')).toBeInTheDocument()
    expect(screen.getByText('评估落地成本')).toBeInTheDocument()
    expect(screen.getByText('合作与代理')).toBeInTheDocument()
  })

  it('renders 入驻通道（不必等回信，直接提交入驻申请）', () => {
    render(<ContactPage />)
    const registerLink = screen.getByText('提交入驻申请').closest('a')
    expect(registerLink).toHaveAttribute('href', '/register')
    expect(screen.getAllByText(/通过即自动开通账号/).length).toBeGreaterThanOrEqual(1)
  })

  it('renders 常见问题四条（含 AI 边界与价格口径）', () => {
    render(<ContactPage />)
    expect(screen.getByText('开通需要多久？')).toBeInTheDocument()
    expect(screen.getByText('需要我们自己准备服务器吗？')).toBeInTheDocument()
    expect(screen.getByText('AI 会替我做主退款、改价或取消订单吗？')).toBeInTheDocument()
    expect(screen.getByText('价格在哪里查看？')).toBeInTheDocument()
  })

  // ── 留言表单：按用户裁定隐藏（issue #6665 追加裁定） ─────────────
  // 用户 2026-10-10 逐字裁定：「先不放邮箱：表单直接隐藏，只留现有联系方式/FAQ」。
  // 原表单是**假成功**（`await new Promise(r => setTimeout(r, 800))`，全仓无任何留言接口，
  // 然后渲染绿框「留言提交成功」并清空表单）⇒ 隐藏之前先别让人填。

  it('留言表单**取不到**：没有表单元素、没有任何输入控件、没有提交按钮', () => {
    const { container } = render(<ContactPage />)
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /提交留言/ })).not.toBeInTheDocument()
    expect(container.querySelectorAll('form').length).toBe(0)
    expect(container.querySelectorAll('input, textarea, select').length).toBe(0)
    for (const label of ['姓名', '电话', '邮箱', '留言内容']) {
      expect(screen.queryByLabelText(new RegExp(label))).not.toBeInTheDocument()
    }
  })

  it('页面不含「提交成功」类字面量（假成功反馈一条都不许留）', () => {
    const { container } = render(<ContactPage />)
    const text = container.textContent ?? ''
    for (const literal of ['提交成功', '留言提交成功', '提交留言', '在线留言', '给我们留言', '留言受理']) {
      expect(text.includes(literal), `联系页仍出现「${literal}」`).toBe(false)
    }
  })

  it('不留指向已隐藏控件的承诺句（不得出现「请在下方留言」这类空承诺）', () => {
    const { container } = render(<ContactPage />)
    const text = container.textContent ?? ''
    const promises = [...text.matchAll(/[^。；\n]{0,18}留言[^。；\n]{0,18}/g)].map((m) => m[0].trim())
    expect(
      promises,
      `联系页还有指向留言的承诺句：${promises.join(' ｜ ')}。` +
        `表单已隐藏（用户 2026-10-10 裁定）⇒ 这些句子指向一个不存在的控件，必须同步改成当前形态口径。`,
    ).toEqual([])
  })

  it('宣传真实性：联系页不得出现占位联系方式（电话 / 邮箱 / 地址 / 通勤话术）', () => {
    render(<ContactPage />)
    expect(screen.queryByText(/400-888-8888/)).not.toBeInTheDocument()
    expect(screen.queryByText(/contact@migao-ai\.com/)).not.toBeInTheDocument()
    expect(screen.queryByText(/浙江省杭州市余杭区文一西路000号/)).not.toBeInTheDocument()
    expect(screen.queryByText(/地铁5号线/)).not.toBeInTheDocument()
    expect(screen.queryByText(/周一至周五 9:00-18:00/)).not.toBeInTheDocument()
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
  // 形态类判据在 corporate-pages-server-component-guard.test.ts；首屏实例判据在
  // anonymous-first-screen-pages.ssr.test.tsx；这里是**本页源码**的形态自证。

  it("page.tsx 是服务端组件：不声明 'use client'，且不再 import 已隐藏的表单组件", () => {
    const src = readFileSync(join(process.cwd(), 'src/app/(corporate)/contact/page.tsx'), 'utf-8').replace(
      /^\uFEFF/,
      '',
    )
    const firstStatement = src
      .split(/\r?\n/)
      .find((l) => l.trim() !== '' && !/^\s*(\/\/|\/\*|\*)/.test(l))
    expect(firstStatement?.trim(), 'contact 页必须是服务端组件（否则正文进不了初始 HTML）').not.toMatch(
      /^['"]use client['"]/,
    )
    expect(src, '表单已按裁定隐藏，页面不得再 import ContactForm').not.toMatch(/ContactForm/)
  })

  // ── 文案口吻（issue #6326：去 AI 口语，改「能力陈述型」书面语）──

  it('文案口吻：联系我们页渲染文本不含 AI 口语词表', () => {
    const { container } = render(<ContactPage />)
    const hits = findColloquialMarkers(container.textContent ?? '')
    expect(hits, `联系我们页渲染文本出现 AI 口语词：${hits.join(' / ')}`).toEqual([])
  })

  it('文案质感：联系我们页渲染文本无量化排比、无拟人量词', () => {
    const { container } = render(<ContactPage />)
    const text = container.textContent ?? ''

    // 判别力自证：病症样本必须被检出、合规样本必须零命中（否则本判据是空断言）
    expect(findQuantifierRhetoric('一套经营平台，一次咨询，一张订单')).toEqual(['一套', '一次', '一张'])
    expect(findPersonifiedAi('两位 AI 助手')).toEqual(['两位 AI'])
    expect(findQuantifierRhetoric('六个能力域 · 4 个终端 · 至少10个字符')).toEqual([])
    expect(findPersonifiedAi('元元与黄金策')).toEqual([])

    const quantifiers = findQuantifierRhetoric(text)
    expect(
      quantifiers,
      `联系我们页渲染文本出现量化排比：${quantifiers.join(' / ')}`,
    ).toEqual([])
    const personified = findPersonifiedAi(text)
    expect(personified, `联系我们页渲染文本出现拟人量词：${personified.join(' / ')}`).toEqual([])
  })
})
