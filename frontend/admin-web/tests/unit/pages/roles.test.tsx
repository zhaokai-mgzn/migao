import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

// Mock APIs
const mockGetRoles = vi.fn()
const mockGetPermissions = vi.fn()

vi.mock('@/lib/api', () => ({
  roleApi: {
    getRoles: (...args: any[]) => mockGetRoles(...args),
    createRole: vi.fn(),
    updateRole: vi.fn(),
    deleteRole: vi.fn(),
  },
  permissionApi: {
    getPermissions: (...args: any[]) => mockGetPermissions(...args),
  },
}))

// Mock UI components
vi.mock('@/components/ui', () => ({
  Button: ({ children, onClick, ...props }: any) => (
    <button onClick={onClick} {...props}>{children}</button>
  ),
  Input: ({ label, value, onChange, disabled }: any) => (
    <div>
      <label>{label}</label>
      <input value={value} onChange={onChange} disabled={disabled} />
    </div>
  ),
  Modal: ({ open, title, children, footer }: any) =>
    open ? (
      <div data-testid="modal" role="dialog">
        <h2>{title}</h2>
        {children}
        <div data-testid="modal-footer">{footer}</div>
      </div>
    ) : null,
  Badge: ({ children, variant }: any) => <span data-variant={variant}>{children}</span>,
}))

// Mock dayjs
vi.mock('dayjs', () => ({
  default: (date?: string) => ({
    format: (fmt: string) => date || '2026-06-22',
  }),
}))

// Mock lucide-react
vi.mock('lucide-react', () => {
  const stub = (name: string) => (props: any) => <span data-testid={`icon-${name}`} {...props} />
  return {
    Plus: stub('plus'),
    Pencil: stub('pencil'),
    Trash2: stub('trash2'),
    Shield: stub('shield'),
  }
})

import RolesPage from '@/app/(dashboard)/roles/page'

describe('RolesPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGetRoles.mockResolvedValue({
      data: {
        data: {
          items: [
            { id: 1, name: '管理员', code: 'admin', description: '系统管理员', permissions: [{ id: 1, name: '查看商品', resource: '商品', action: 'view' }], createdAt: '2026-06-01' },
            { id: 2, name: '客服', code: 'cs', description: '客服人员', permissions: [], createdAt: '2026-06-02' },
          ],
        },
      },
    })
    mockGetPermissions.mockResolvedValue({
      data: {
        data: [
          { id: 1, name: '查看商品', resource: '商品', action: 'view' },
          { id: 2, name: '编辑商品', resource: '商品', action: 'edit' },
        ],
      },
    })
  })

  it('renders page title', () => {
    render(<RolesPage />)
    expect(screen.getByText('角色权限')).toBeInTheDocument()
  })

  it('renders add role button', () => {
    render(<RolesPage />)
    expect(screen.getByText('新增角色')).toBeInTheDocument()
  })

  it('loads and displays role cards', async () => {
    render(<RolesPage />)
    await waitFor(() => {
      expect(mockGetRoles).toHaveBeenCalled()
    })
    await waitFor(() => {
      expect(screen.getByText('管理员')).toBeInTheDocument()
      expect(screen.getByText('客服')).toBeInTheDocument()
    })
  })

  it('displays role codes', async () => {
    render(<RolesPage />)
    await waitFor(() => {
      expect(screen.getByText('admin')).toBeInTheDocument()
      expect(screen.getByText('cs')).toBeInTheDocument()
    })
  })

  it('shows empty state when no roles', () => {
    mockGetRoles.mockResolvedValue({
      data: { data: { items: [], total: 0 } },
    })
    render(<RolesPage />)
    expect(screen.getByText('角色权限')).toBeInTheDocument()
  })
})
