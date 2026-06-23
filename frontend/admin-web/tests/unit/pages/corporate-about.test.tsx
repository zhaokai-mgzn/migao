import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

// Mock lucide-react — icons used by about page
vi.mock('lucide-react', () => {
  const stub = (name: string) => (props: any) => <span data-testid={`icon-${name}`} {...props} />
  return {
    Lightbulb: stub('lightbulb'),
    Heart: stub('heart'),
    Sprout: stub('sprout'),
    Lock: stub('lock'),
  }
})

import AboutPage from '@/app/(corporate)/about/page'

describe('CorporateAboutPage', () => {
  it('renders page header', () => {
    render(<AboutPage />)
    expect(screen.getByText('关于米高')).toBeInTheDocument()
  })

  it('renders header description', () => {
    render(<AboutPage />)
    expect(screen.getByText(/以AI双助手重新定义企业电商管理/)).toBeInTheDocument()
  })

  it('renders company intro text', () => {
    render(<AboutPage />)
    expect(screen.getByText(/米高是词元通达旗下的AI智能电商管理平台/)).toBeInTheDocument()
  })

  it('renders mission and vision', () => {
    render(<AboutPage />)
    expect(screen.getByText('我们的使命')).toBeInTheDocument()
    expect(screen.getByText('我们的愿景')).toBeInTheDocument()
  })

  it('renders core values section', () => {
    render(<AboutPage />)
    expect(screen.getByText('核心价值观')).toBeInTheDocument()
  })

  it('renders value names', () => {
    render(<AboutPage />)
    expect(screen.getByText('技术驱动')).toBeInTheDocument()
    expect(screen.getByText('客户至上')).toBeInTheDocument()
    expect(screen.getByText('行业深耕')).toBeInTheDocument()
    expect(screen.getByText('数据安全')).toBeInTheDocument()
  })

  it('renders timeline section', () => {
    render(<AboutPage />)
    expect(screen.getByText('发展历程')).toBeInTheDocument()
  })

  it('renders timeline entries', () => {
    render(<AboutPage />)
    expect(screen.getByText('项目启动')).toBeInTheDocument()
    expect(screen.getByText('核心引擎开发')).toBeInTheDocument()
    expect(screen.getByText('平台上线')).toBeInTheDocument()
    expect(screen.getByText('多渠道接入')).toBeInTheDocument()
    expect(screen.getByText('能力进化')).toBeInTheDocument()
  })
})
