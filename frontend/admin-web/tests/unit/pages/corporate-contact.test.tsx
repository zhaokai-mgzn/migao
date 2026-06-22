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
    expect(screen.getByText('公司地址')).toBeInTheDocument()
    expect(screen.getByText('联系电话')).toBeInTheDocument()
    expect(screen.getByText('电子邮箱')).toBeInTheDocument()
    expect(screen.getByText('工作时间')).toBeInTheDocument()
  })

  it('renders contact values', () => {
    render(<ContactPage />)
    expect(screen.getByText('浙江省杭州市余杭区文一西路000号')).toBeInTheDocument()
    expect(screen.getByText('400-888-8888')).toBeInTheDocument()
    expect(screen.getByText('contact@migao-ai.com')).toBeInTheDocument()
    expect(screen.getByText('周一至周五 9:00-18:00')).toBeInTheDocument()
  })

  it('renders online message form section', () => {
    render(<ContactPage />)
    expect(screen.getByText('在线留言')).toBeInTheDocument()
  })

  it('renders form fields', () => {
    render(<ContactPage />)
    expect(screen.getByLabelText('姓名')).toBeInTheDocument()
    expect(screen.getByLabelText('电话')).toBeInTheDocument()
    expect(screen.getByLabelText('邮箱')).toBeInTheDocument()
    expect(screen.getByLabelText('留言内容')).toBeInTheDocument()
  })

  it('renders submit button', () => {
    render(<ContactPage />)
    expect(screen.getByText('提交留言')).toBeInTheDocument()
  })

  it('renders map placeholder section', () => {
    render(<ContactPage />)
    expect(screen.getByText('地图加载区域')).toBeInTheDocument()
  })
})
