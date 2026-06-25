import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

// Mock lucide-react — icons used by contact page
vi.mock('lucide-react', () => {
  const stub = (name: string) => (props: any) => <span data-testid={`icon-${name}`} {...props} />
  return {
    MapPin: stub('map-pin'),
    Phone: stub('phone'),
    Mail: stub('mail'),
    Clock: stub('clock'),
    Send: stub('send'),
    CheckCircle: stub('check-circle'),
    Building2: stub('building2'),
  }
})

import ContactPage from '@/app/(corporate)/contact/page'

describe('CorporateContactPage', () => {
  it('renders page header', () => {
    render(<ContactPage />)
    expect(screen.getByText('联系我们')).toBeInTheDocument()
  })

  it('renders header description', () => {
    render(<ContactPage />)
    expect(screen.getByText(/无论您有任何疑问或合作意向/)).toBeInTheDocument()
  })

  it('renders contact info section', () => {
    render(<ContactPage />)
    expect(screen.getByText('联系信息')).toBeInTheDocument()
  })

  it('renders contact items', () => {
    render(<ContactPage />)
    // '公司地址' and '工作时间' appear in both contact info and the new info card
    expect(screen.getAllByText('公司地址').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('工作时间').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText('联系电话')).toBeInTheDocument()
    expect(screen.getByText('电子邮箱')).toBeInTheDocument()
  })

  it('renders contact values', () => {
    render(<ContactPage />)
    // Address appears in both contact info and company info card
    expect(screen.getAllByText('浙江省杭州市余杭区文一西路000号').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('400-888-8888').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText('contact@migao-ai.com')).toBeInTheDocument()
    expect(screen.getByText('周一至周五 9:00-18:00')).toBeInTheDocument()
  })

  it('renders online message form section', () => {
    render(<ContactPage />)
    expect(screen.getByText('在线留言')).toBeInTheDocument()
  })

  it('renders form fields', () => {
    render(<ContactPage />)
    // Labels now include asterisk (*) as required field indicator
    expect(screen.getByLabelText(/姓名/)).toBeInTheDocument()
    expect(screen.getByLabelText(/电话/)).toBeInTheDocument()
    expect(screen.getByLabelText(/邮箱/)).toBeInTheDocument()
    expect(screen.getByLabelText(/留言内容/)).toBeInTheDocument()
  })

  it('renders submit button', () => {
    render(<ContactPage />)
    expect(screen.getByText('提交留言')).toBeInTheDocument()
  })

  it('renders company info card instead of map placeholder', () => {
    render(<ContactPage />)
    // Company info card replaces the old map placeholder
    expect(screen.getByText('距地铁5号线创景路站步行10分钟')).toBeInTheDocument()
    expect(screen.getByText('周一至周五')).toBeInTheDocument()
    // Phone link should be present in the info card
    const phoneLinks = screen.getAllByText('400-888-8888')
    // Appears in both contact info section and company info card bottom bar
    expect(phoneLinks.length).toBeGreaterThanOrEqual(1)
  })

  it('should not render old map placeholder', () => {
    render(<ContactPage />)
    expect(screen.queryByText('地图加载区域')).not.toBeInTheDocument()
  })
})
