import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

// Mock API
const mockGetRegistrations = vi.fn()

vi.mock('@/lib/api', () => ({
  registrationApi: {
    getRegistrations: (...args: any[]) => mockGetRegistrations(...args),
    approveRegistration: vi.fn(),
    rejectRegistration: vi.fn(),
    getRegistrationDetail: vi.fn(),
  },
}))

// Mock UI components
vi.mock('@/components/ui', () => ({
  Pagination: ({ current, total, pageSize }: any) => (
    <div data-testid="pagination">第 {current} 页, 共 {total} 条</div>
  ),
  Modal: ({ open, title, children, footer }: any) =>
    open ? (
      <div data-testid="modal" role="dialog">
        <h2>{title}</h2>
        {children}
        <div data-testid="modal-footer">{footer}</div>
      </div>
    ) : null,
  Button: ({ children, onClick, ...props }: any) => (
    <button onClick={onClick} {...props}>{children}</button>
  ),
  Badge: ({ children, variant }: any) => <span data-variant={variant}>{children}</span>,
}))

// Mock dayjs
vi.mock('dayjs', () => ({
  default: (date?: string) => ({
    format: (fmt: string) => date || '2026-06-22',
  }),
}))

// Mock utils
vi.mock('@/lib/utils', () => ({
  cn: (...classes: any[]) => classes.filter(Boolean).join(' '),
  resolveImageUrl: (url: string) => url,
}))

// Mock types
vi.mock('@/types', () => ({
  RegistrationStatusLabels: {
    pending: '待审核',
    approved: '已通过',
    rejected: '已驳回',
  },
  RegistrationStatusColors: {
    pending: 'warning',
    approved: 'success',
    rejected: 'error',
  },
}))

// Mock lucide-react
vi.mock('lucide-react', () => {
  const stub = (name: string) => (props: any) => <span data-testid={`icon-${name}`} {...props} />
  return {
    Eye: stub('eye'),
  }
})

import RegistrationsPage from '@/app/(platform)/registrations/page'

describe('RegistrationsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGetRegistrations.mockResolvedValue({
      data: {
        data: {
          items: [
            { id: '1', companyName: '测试企业', contactName: '王经理', phone: '13800001111', industry: '布艺', status: 'pending', createdAt: '2026-06-20T10:00:00' },
          ],
          total: 1,
        },
      },
    })
  })

  it('renders page title', () => {
    render(<RegistrationsPage />)
    expect(screen.getByText('企业入驻审批')).toBeInTheDocument()
  })

  it('renders status tabs', () => {
    render(<RegistrationsPage />)
    expect(screen.getByText('全部')).toBeInTheDocument()
    expect(screen.getByText('待审核')).toBeInTheDocument()
    expect(screen.getByText('已通过')).toBeInTheDocument()
    expect(screen.getByText('已驳回')).toBeInTheDocument()
  })

  it('loads and displays registrations', async () => {
    render(<RegistrationsPage />)
    await waitFor(() => {
      expect(mockGetRegistrations).toHaveBeenCalled()
    })
    await waitFor(() => {
      expect(screen.getByText('测试企业')).toBeInTheDocument()
    })
  })

  it('displays approval/rejection buttons for pending items', async () => {
    render(<RegistrationsPage />)
    await waitFor(() => {
      expect(screen.getByText('审批通过')).toBeInTheDocument()
      expect(screen.getByText('驳回')).toBeInTheDocument()
    })
  })

  it('shows empty state when no data', () => {
    mockGetRegistrations.mockResolvedValue({
      data: { data: { items: [], total: 0 } },
    })
    render(<RegistrationsPage />)
    expect(screen.getByText('企业入驻审批')).toBeInTheDocument()
  })
})
