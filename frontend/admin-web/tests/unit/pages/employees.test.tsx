// case_ids: HR-001, HR-002
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react'

// Mock sonner toast
const mockToastError = vi.fn()
const mockToastSuccess = vi.fn()
vi.mock('sonner', () => ({
  toast: {
    error: (...args: any[]) => mockToastError(...args),
    success: (...args: any[]) => mockToastSuccess(...args),
  },
}))

// Mock useAuthStore — 默认 admin(*)，可在用例中覆盖模拟员工权限
// 支持 selector 调用（usePermission 用 useAuthStore(s => s.user)）
const mockUseAuthStore = vi.fn()
vi.mock('@/store/auth', () => ({
  useAuthStore: (selector: any) => (selector ? selector(mockUseAuthStore()) : mockUseAuthStore()),
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
    // 默认当前用户为 admin（全部权限），按钮可见
    mockUseAuthStore.mockReturnValue({
      user: { id: '1', name: '管理员', roles: ['admin'], permissions: ['*'] },
    })
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

  it('#1830/#2907: 新增弹窗仅含姓名/手机号/岗位/账号权限 4 字段，不含角色/用户名字段', async () => {
    render(<EmployeesPage />)
    fireEvent.click(screen.getByText('新增员工'))
    await waitFor(() => {
      expect(screen.getByTestId('modal')).toBeInTheDocument()
    })
    const modal = within(screen.getByTestId('modal'))
    // 必须看到这 4 个 label
    expect(modal.getByText('姓名 *')).toBeInTheDocument()
    expect(modal.getByText('手机号 *')).toBeInTheDocument()
    expect(modal.getByText('岗位 *')).toBeInTheDocument()
    expect(modal.getByText('账号权限 *')).toBeInTheDocument()
    // 不包含用户名字段（#1830）
    expect(modal.queryByText('用户名')).not.toBeInTheDocument()
    // 不包含角色字段（#2907：新增员工弹窗去掉「角色」）
    expect(modal.queryByText('角色')).not.toBeInTheDocument()
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

  it('#1830/#2907: 创建员工 payload 不含 username/role 字段', async () => {
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
    expect(callArgs).not.toHaveProperty('role')
    expect(callArgs).toHaveProperty('name', '张三')
    expect(callArgs).toHaveProperty('phone', '13800138000')
    expect(callArgs).toHaveProperty('position', '管理员')
    expect(callArgs).toHaveProperty('permissions')
  })

  // ==================== 员工管理权限全链路（按钮级权限） ====================

  it('仅 employee:list 权限：不显示新增员工/编辑/删除按钮，操作列为只读', async () => {
    mockUseAuthStore.mockReturnValue({
      user: { id: '2', name: '客服小王', roles: ['operator'], permissions: ['employee:list'] },
    })
    render(<EmployeesPage />)
    // 页面可访问（路由层要求 employee:list），但写操作按钮不可见
    expect(screen.getByText('员工管理')).toBeInTheDocument()
    expect(screen.queryByText('新增员工')).not.toBeInTheDocument()
    await waitFor(() => {
      expect(screen.getAllByText('只读').length).toBeGreaterThan(0)
    })
    expect(screen.queryByText('编辑')).not.toBeInTheDocument()
    expect(screen.queryByText('删除')).not.toBeInTheDocument()
  })

  it('无 employee:list 权限：新增员工按钮同样不可见（后端会 403，前端隐藏入口）', () => {
    mockUseAuthStore.mockReturnValue({
      user: { id: '3', name: '收银员', roles: ['operator'], permissions: ['dashboard:view'] },
    })
    render(<EmployeesPage />)
    expect(screen.queryByText('新增员工')).not.toBeInTheDocument()
  })

  it('employee:create 权限：显示新增员工与行内编辑/删除按钮', async () => {
    mockUseAuthStore.mockReturnValue({
      user: { id: '4', name: '人事主管', roles: ['operator'], permissions: ['employee:list', 'employee:create'] },
    })
    render(<EmployeesPage />)
    expect(screen.getByText('新增员工')).toBeInTheDocument()
    await waitFor(() => {
      expect(screen.getAllByText('编辑').length).toBeGreaterThan(0)
    })
    expect(screen.getAllByText('删除').length).toBeGreaterThan(0)
  })
})
