import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

// Mock APIs
const mockGetEmployees = vi.fn()

vi.mock('@/lib/api', () => ({
  employeeApi: {
    getEmployees: (...args: any[]) => mockGetEmployees(...args),
    createEmployee: vi.fn(),
    updateEmployee: vi.fn(),
    deleteEmployee: vi.fn(),
    toggleEmployeeStatus: vi.fn(),
  },
  roleApi: {
    getAllRoles: vi.fn().mockResolvedValue({ data: { data: [] } }),
  },
}))

const mockRequestGet = vi.fn()
vi.mock('@/lib/request', () => ({
  default: {
    get: (...args: any[]) => mockRequestGet(...args),
  },
}))

// Mock TreeCheckbox
vi.mock('@/components/ui/TreeCheckbox', () => ({
  TreeCheckbox: ({ tree }: any) => (
    <div data-testid="tree-checkbox">
      {tree.map((node: any) => (
        <div key={node.code}>
          <span>{node.label}</span>
          {node.children?.map((child: any) => <span key={child.code}>{child.label}</span>)}
        </div>
      ))}
    </div>
  ),
}))

// Mock UI components
vi.mock('@/components/ui', () => ({
  Table: ({ columns, dataSource, loading, rowKey }: any) => (
    <div data-testid="data-table">
      {loading && <div data-testid="table-loading">加载中...</div>}
      {!loading && (!dataSource || dataSource.length === 0) && <div>暂无数据</div>}
      {dataSource?.map((record: any, index: number) => (
        <div
          key={typeof rowKey === 'function' ? rowKey(record) : record[rowKey]}
          data-testid={`employee-${record.id}`}
        >
          {columns.map((col: any) => (
            <span key={col.key} data-testid={`cell-${col.key}`}>
              {col.dataIndex ? record[col.dataIndex] : col.render ? col.render(record, index) : null}
            </span>
          ))}
        </div>
      ))}
    </div>
  ),
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
  Input: ({ label, placeholder, value, onChange }: any) => (
    <div>
      <label>{label}</label>
      <input placeholder={placeholder} value={value} onChange={onChange} />
    </div>
  ),
  Select: ({ label, options, value, onChange }: any) => (
    <div>
      <label>{label}</label>
      <select value={value} onChange={onChange}>
        {options?.map((o: any) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </div>
  ),
  StatusBadge: ({ label, color, dot, className, onClick }: any) => React.createElement('span', { onClick, className, title: label }, dot ? React.createElement('span', { className: 'w-1.5 h-1.5 rounded-full' }) : null, label),
  Badge: ({ children, variant }: any) => <span data-variant={variant}>{children}</span>,
}))

// Mock dayjs
vi.mock('dayjs', () => ({
  default: (date?: any) => ({
    format: (fmt: string) => date || '2026-06-22',
  }),
}))

// Mock lucide-react — icons used by employees page
vi.mock('lucide-react', () => {
  const stub = (name: string) => (props: any) => <span data-testid={`icon-${name}`} {...props} />
  return {
    Plus: stub('plus'),
    Pencil: stub('pencil'),
    Trash2: stub('trash2'),
  }
})

import EmployeesPage from '@/app/(dashboard)/employees/page'

describe('EmployeesPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGetEmployees.mockResolvedValue({
      data: {
        data: {
          items: [
            { id: 1, username: 'zhangsan', name: '张三', phone: '13800001111', position: '客服', permissions: ['products:view'], status: 'active', createdAt: '2026-06-01T10:00:00' },
            { id: 2, username: 'lisi', name: '李四', phone: '13800002222', position: '管理员', permissions: [], status: 'disabled', createdAt: '2026-06-02T10:00:00' },
          ],
          total: 2,
        },
      },
    })
    mockRequestGet.mockResolvedValue({
      data: { data: [{ code: 'products', label: '商品管理', children: [{ code: 'products:view', label: '查看商品' }] }] },
    })
  })

  it('renders page title', () => {
    render(<EmployeesPage />)
    expect(screen.getByText('员工管理')).toBeInTheDocument()
  })

  it('renders add employee button', () => {
    render(<EmployeesPage />)
    expect(screen.getByText('添加员工')).toBeInTheDocument()
  })

  it('renders search filter labels', () => {
    render(<EmployeesPage />)
    expect(screen.getByText('姓名/手机号')).toBeInTheDocument()
    expect(screen.getByText('状态')).toBeInTheDocument()
    expect(screen.getByText('角色')).toBeInTheDocument()
  })

  it('renders search and reset buttons', () => {
    render(<EmployeesPage />)
    expect(screen.getByText('搜索')).toBeInTheDocument()
    expect(screen.getByText('重置')).toBeInTheDocument()
  })

  it('loads and displays employees', async () => {
    render(<EmployeesPage />)
    await waitFor(() => {
      expect(mockGetEmployees).toHaveBeenCalled()
    })
    await waitFor(() => {
      expect(screen.getByTestId('employee-1')).toBeInTheDocument()
    })
  })

  it('renders pagination', async () => {
    render(<EmployeesPage />)
    await waitFor(() => {
      expect(screen.getByTestId('pagination')).toBeInTheDocument()
    })
  })
})
