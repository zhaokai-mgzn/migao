// case_ids: OB-004, UI-082
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: any) => <a href={href} {...props}>{children}</a>,
}))

vi.mock('@/components/ui/Logo', () => ({
  default: () => <div data-testid="logo">Logo</div>,
}))

import CorporateFooter from '@/components/corporate/CorporateFooter'

describe('CorporateFooter（官网页脚 v4：主体事实 + 能力入口，issue #6291）', () => {
  it('renders company legal name in description', () => {
    render(<CorporateFooter />)
    expect(screen.getAllByText(/杭州词元通达科技有限公司/).length).toBeGreaterThanOrEqual(1)
  })

  it('renders quick links', () => {
    render(<CorporateFooter />)
    expect(screen.getByText('首页')).toBeInTheDocument()
    expect(screen.getByText('产品服务')).toBeInTheDocument()
    expect(screen.getAllByText('商家入驻').length).toBeGreaterThanOrEqual(1)
  })

  it('renders 产品能力入口（都指向 /services 的能力清单）', () => {
    render(<CorporateFooter />)
    expect(screen.getByText('产品能力')).toBeInTheDocument()
    const capabilityLink = screen.getByText('生产工序与计件工资').closest('a')
    expect(capabilityLink).toHaveAttribute('href', '/services')
  })

  it('renders 合规免责小字（国标为推荐性标准，不构成认证结论）', () => {
    render(<CorporateFooter />)
    expect(screen.getByText(/不构成任何认证、检测或备案结论/)).toBeInTheDocument()
  })

  it('renders copyright with legal company name', () => {
    render(<CorporateFooter />)
    expect(
      screen.getByText(/© 2026 杭州词元通达科技有限公司 · 米高 版权所有/)
    ).toBeInTheDocument()
  })

  it('宣传真实性：页脚不得出现占位联系方式（电话 / 邮箱 / 地址）', () => {
    render(<CorporateFooter />)
    expect(screen.queryByText(/400-888-8888/)).not.toBeInTheDocument()
    expect(screen.queryByText(/contact@migao-ai\.com/)).not.toBeInTheDocument()
    expect(screen.queryByText(/文一西路000号/)).not.toBeInTheDocument()
  })
})
