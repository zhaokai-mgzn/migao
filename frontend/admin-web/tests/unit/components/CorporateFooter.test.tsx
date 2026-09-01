// case_ids: OB-004
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

// Mock next/link
vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: any) => <a href={href} {...props}>{children}</a>,
}))

// Mock Logo
vi.mock('@/components/ui/Logo', () => ({
  default: () => <div data-testid="logo">Logo</div>,
}))

import CorporateFooter from '@/components/corporate/CorporateFooter'

describe('CorporateFooter（公司主体：杭州词元通达科技有限公司）', () => {
  it('renders company legal name in description', () => {
    render(<CorporateFooter />)
    expect(screen.getAllByText(/杭州词元通达科技有限公司/).length).toBeGreaterThanOrEqual(1)
  })

  it('renders quick links', () => {
    render(<CorporateFooter />)
    expect(screen.getByText('首页')).toBeInTheDocument()
    expect(screen.getByText('商家入驻')).toBeInTheDocument()
  })

  it('renders copyright with legal company name', () => {
    render(<CorporateFooter />)
    expect(screen.getByText(/© 2026 杭州词元通达科技有限公司 · 米高 版权所有/)).toBeInTheDocument()
  })
})
