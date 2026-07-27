import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'

// Mock sonner toast
const mockToastError = vi.fn()
const mockToastSuccess = vi.fn()
vi.mock('sonner', () => ({
  toast: {
    error: (...args: any[]) => mockToastError(...args),
    success: (...args: any[]) => mockToastSuccess(...args),
  },
}))

// Mock APIs
const mockGetEmployees = vi.fn()
const mockCreateEmployee = vi.fn()

vi.mock('@/lib/api', () => ({
  employeeApi: {
    getEmployees: (...args: any[]) => mockGetEmployees(...args),
    createEmployee: (...args: any[]) => mockCreateEmployee(...args),
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
    Search: stub('search'),
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
            { id: 1, name: '张三', phone: '13800001111', position: '客服', permissions: ['products:view'], status: 'active', createdAt: '2026-06-01T10:00:00' },
            { id: 2, name: '李四', phone: '13800002222', position: '管理员', permissions: [], status: 'disabled', createdAt: '2026-06-02T10:00:00' },
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
    expect(screen.getByText('新增员工')).toBeInTheDocument()
  })

  it('renders search filter labels', () => {
    render(<EmployeesPage />)
    expect(screen.getByText('姓名/手机号')).toBeInTheDocument()
    expect(screen.getByText('状态')).toBeInTheDocument()
    expect(screen.getByText('角色')).toBeInTheDocument()
  })

  it('renders search and reset buttons', () => {
    render(<EmployeesPage />)
    expect(screen.getByText('查询')).toBeInTheDocument()
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

  // ==================== #1830: username 字段残留清理 ====================

  it('#1830: 新增弹窗不包含用户名字段', async () => {
    render(<EmployeesPage />)
    const addBtn = screen.getByText('新增员工')
    fireEvent.click(addBtn)
    await waitFor(() => {
      expect(screen.getByTestId('modal')).toBeInTheDocument()
    })
    // 弹窗表单不应包含「用户名」label
    expect(screen.queryByText('用户名')).not.toBeInTheDocument()
  })

  it('#1830: 新增弹窗仅含姓名/手机号/岗位/账号权限 4 字段', async () => {
    render(<EmployeesPage />)
    fireEvent.click(screen.getByText('新增员工'))
    await waitFor(() => {
      expect(screen.getByTestId('modal')).toBeInTheDocument()
    })
    // 必须看到这 4 个 label
    expect(screen.getByText('姓名 *')).toBeInTheDocument()
    expect(screen.getByText('手机号 *')).toBeInTheDocument()
    expect(screen.getByText('岗位 *')).toBeInTheDocument()
    expect(screen.getByText('账号权限 *')).toBeInTheDocument()
    // 不包含用户名字段
    expect(screen.queryByText('用户名')).not.toBeInTheDocument()
  })

  it('#1830: 填写完整表单点创建不触发「请输入用户名」错误', async () => {
    mockCreateEmployee.mockResolvedValue({ data: { data: { id: 99 } } })
    render(<EmployeesPage />)
    // 打开新增弹窗
    fireEvent.click(screen.getByText('新增员工'))
    await waitFor(() => {
      expect(screen.getByTestId('modal')).toBeInTheDocument()
    })
    // 获取姓名和手机号输入框
    const inputs = screen.getAllByRole('textbox')
    const nameInput = inputs.find((el) => el.getAttribute('placeholder')?.includes('姓名'))
    const phoneInput = inputs.find((el) => el.getAttribute('placeholder')?.includes('手机号'))
    if (nameInput) fireEvent.change(nameInput, { target: { value: '张三' } })
    if (phoneInput) fireEvent.change(phoneInput, { target: { value: '13800138000' } })
    // 点击创建按钮
    const createBtn = screen.getByText('创建')
    fireEvent.click(createBtn)
    await waitFor(() => {
      // 不应弹出「请输入用户名」错误
      expect(mockToastError).not.toHaveBeenCalledWith('请输入用户名')
    })
  })

  it('#1830: 创建员工 payload 不含 username 字段', async () => {
    mockCreateEmployee.mockResolvedValue({ data: { data: { id: 99 } } })
    render(<EmployeesPage />)
    fireEvent.click(screen.getByText('新增员工'))
    await waitFor(() => {
      expect(screen.getByTestId('modal')).toBeInTheDocument()
    })
    // Fill name → mocked Input with placeholder "请输入姓名"
    const nameInput = screen.getByPlaceholderText('请输入姓名')
    fireEvent.change(nameInput, { target: { value: '张三' } })
    // Fill phone → mocked Input with placeholder "请输入手机号"
    const phoneInput = screen.getByPlaceholderText('请输入手机号')
    fireEvent.change(phoneInput, { target: { value: '13800138000' } })
    // Fill position → raw input with placeholder "选择或输入岗位"
    const posInput = screen.getByPlaceholderText('选择或输入岗位，如：客服')
    fireEvent.change(posInput, { target: { value: '管理员' } })
    // Click create
    fireEvent.click(screen.getByText('创建'))
    await waitFor(() => {
      expect(mockCreateEmployee).toHaveBeenCalled()
    })
    const callArgs = mockCreateEmployee.mock.calls[0]?.[0]
    expect(callArgs).toBeDefined()
    expect(callArgs).not.toHaveProperty('username')
    expect(callArgs).toHaveProperty('name', '张三')
    expect(callArgs).toHaveProperty('phone', '13800138000')
    expect(callArgs).toHaveProperty('position', '管理员')
    expect(callArgs).toHaveProperty('permissions')
  })
})
