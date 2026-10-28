// case_ids: AU-007, HR-001, HR-002, UI-028, HR-013
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react'
import { formatMobileTitles } from '@/lib/mobile-surface-label'

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
const mockUpdateEmployee = vi.fn()
const mockResetPassword = vi.fn()
const mockGetAllRoles = vi.fn()

vi.mock('@/lib/api', () => ({
  employeeApi: {
    loadPositions: (...args: any[]) => mockGetAllRoles(...args),
    getEmployees: (...args: any[]) => mockGetEmployees(...args),
    createEmployee: (...args: any[]) => mockCreateEmployee(...args),
    updateEmployee: (...args: any[]) => mockUpdateEmployee(...args),
    resetPassword: (...args: any[]) => mockResetPassword(...args),
    deleteEmployee: vi.fn(),
    toggleEmployeeStatus: vi.fn(),
  },
  roleApi: {
    getAllRoles: (...args: any[]) => mockGetAllRoles(...args),
  },
}))

const mockRequestGet = vi.fn()
vi.mock('@/lib/request', () => ({
  default: {
    get: (...args: any[]) => mockRequestGet(...args),
  },
}))

// Mock TreeCheckbox — 暴露 selected 以便断言岗位默认权限预填（#2969）
// 🔴 issue #6759：本假组件也必须渲染**手机端标注**（真组件按下发的 `node.mobileTitles` 追加
// ` · 手机端：X`）—— 否则「标注有没有渲染出来」在本文件里是**测不到的**（假绿）。
// 拼接串与真组件**同一实现**（`@/lib/mobile-surface-label`）。
const mockTreeOnChange = vi.fn()
vi.mock('@/components/ui/TreeCheckbox', () => ({
  TreeCheckbox: ({ tree, selected, onChange }: any) => {
    mockTreeOnChange.mockImplementation(onChange || (() => {}))
    const label = (node: any) => `${node.label}${formatMobileTitles(node.mobileTitles)}`
    return (
      <div data-testid="tree-checkbox" data-selected={JSON.stringify(selected || [])}>
        {tree.map((node: any) => (
          <div key={node.code}>
            <span>{label(node)}</span>
            {node.children?.map((child: any) => <span key={child.code}>{label(child)}</span>)}
          </div>
        ))}
      </div>
    )
  },
}))

// Mock UI components
vi.mock('@/components/ui', async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>()
  return {
    // issue #7007：**先摊开真原语，再覆盖**（`...actual` 在前 ⇒ 显式 mock 仍然赢）。
    // 此前这里是**整模块** mock 且不合并真值，只列被替身的几个原语 ⇒ 页面一旦用上
    // **当时不存在的原语**（本轮加了 PageHeader / PageCard / SearchPanel）就报
    // `No "PageHeader" export is defined on the "@/components/ui" mock` ——
    // 报错离病灶很远（本轮 144 条红的根因，与页面改动对错无关）。
    // 摊开真值后，新增原语不必再逐个补 mock。口径与同目录
    // `production-remnants-paging.test.tsx` 既有写法同源。
    ...actual,
  Table: ({ columns, dataSource, loading, rowKey, emptyText }: any) => (
    <div data-testid="data-table">
      {loading && <div data-testid="table-loading">加载中...</div>}
      {/* issue #8040：把页面传的 `emptyText` **真的**渲染出来 —— 改前这里写死「暂无数据」，
          页面怎么改空态话术，判据都看不见（撞的正是本单要修的那句裸文案）。 */}
      {!loading && (!dataSource || dataSource.length === 0) && <div data-testid="table-empty">{emptyText}</div>}
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
  }
})

// Mock dayjs
vi.mock('dayjs', () => ({
  default: (date?: any) => ({
    format: (fmt: string) => date || '2026-06-22',
  }),
}))

// Mock lucide-react — icons used by employees page
vi.mock('lucide-react', async (importOriginal) => {
  // ⚠️ 必须 spread `...actual`：本 mock 是**闭合集合**（只列页面直接用到的那几个图标），
  // 而模块一旦经 `@/components/ui` 桶加载真 `EmptyState`（它自己 import `Package`），
  // 闭集就漏了它 ⇒ 报 `No "Package" export is defined on the "lucide-react" mock`
  // （与「整模块 mock `@/components/ui`」同一种病，见 issue #7007）。
  // `...actual` 在前 ⇒ 显式桩的 testid 仍然赢。
  const actual = await importOriginal<Record<string, unknown>>()
  const stub = (name: string) => (props: any) => <span data-testid={`icon-${name}`} {...props} />
  return {
    ...actual,
    Plus: stub('plus'),
    Search: stub('search'),
    // issue #6663：失败态行用的图标
    AlertTriangle: stub('alert-triangle'),
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
            // #5485：`employeeUsername` 才是登录账号（`username` 仍是手机号，后端未动）
            { id: 1, name: '张三', phone: '13800001111', position: '客服', permissions: ['products:view'], status: 'active', createdAt: '2026-06-01T10:00:00', employeeUsername: 'zhangsan' },
            // 存量员工：管理员尚未补设用户名 ⇒ 显示「未设置」，且这个员工当前登不进来
            { id: 2, name: '李四', phone: '13800002222', position: '管理员', permissions: [], status: 'disabled', createdAt: '2026-06-02T10:00:00' },
          ],
          total: 2,
        },
      },
    })
    mockRequestGet.mockResolvedValue({
      data: { data: [{ code: 'products', label: '商品管理', children: [{ code: 'products:view', label: '查看商品' }] }] },
    })
    // #2969 岗位下拉数据源：角色体系即岗位，permissions 为岗位默认权限
    mockGetAllRoles.mockResolvedValue({
      data: {
        data: [
          { id: 'r1', name: '客服', code: 'customer_service', permissions: [{ id: 'p1', code: 'products:view', name: '查看商品' }, { id: 'p2', code: 'order:list', name: '订单列表' }] },
          { id: 'r2', name: '运营', code: 'operator', permissions: [{ id: 'p3', code: 'dashboard:view', name: '经营看板' }] },
        ],
      },
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
    // #2946：列表页移除「角色/全部角色」筛选下拉（前端去角色化，仅岗位展示）
    expect(screen.queryByText('角色')).not.toBeInTheDocument()
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

  it('#2946: 列表查询请求参数不含 role（列表页已移除角色筛选）', async () => {
    mockGetEmployees.mockClear()
    render(<EmployeesPage />)
    // 🔴 issue #7116：**先等挂载那次请求落地**，再做交互。
    // 本页是「草稿 state + 已提交 state」两段式（`keyword` → `handleSearch` → `searchKeyword` → `useEffect` 重发），
    // 挂载请求未落地时，`setSearchKeyword` 触发的重发**排在同一条微任务链后**，而断言在
    // `waitFor(toHaveBeenCalled())` 上被**挂载那次**满足 ⇒ 读到的是挂载那次的入参（不带 keyword）。
    // 这不是迁移引入的行为变化 —— 迁移前后请求序列逐字相同（实测 `[{page,size}, {page,size,keyword:'张'}]`），
    // 只是**交互与挂载请求的竞争**在 `SearchPanel` 下更容易显现。等挂载落地再点，就是确定的。
    await waitFor(() => expect(mockGetEmployees).toHaveBeenCalled())
    // 触发一次查询：输入关键字后点「查询」，请求参数只含 page/size/keyword/status，不含 role
    const searchInput = screen.getByPlaceholderText(/输入姓名或手机号搜索/)
    fireEvent.change(searchInput, { target: { value: '张' } })
    fireEvent.click(screen.getByText('查询'))
    await waitFor(() => {
      expect(mockGetEmployees).toHaveBeenCalled()
    })
    const calls = mockGetEmployees.mock.calls
    const lastArgs = calls[calls.length - 1]?.[0] || {}
    expect(lastArgs).not.toHaveProperty('role')
    expect(lastArgs).toHaveProperty('keyword', '张')
  })

  it('空态分流（issue #8040）：真没有员工 ⇒ 说清去哪建；筛选下为空 ⇒ 说清换个条件', async () => {
    mockGetEmployees.mockResolvedValue({ data: { data: { items: [], total: 0 } } })
    render(<EmployeesPage />)

    // ① 真为空：说清下一步（去哪建员工）—— 不再是裸「暂无数据」
    const trulyEmpty = await screen.findByTestId('table-empty')
    expect(trulyEmpty.textContent).toContain('还没有员工')
    expect(trulyEmpty.textContent).toContain('新增员工')
    expect(screen.queryByText('暂无数据')).toBeNull()

    // ② 筛选下为空：改口说「换个条件」，不让商家以为一个员工都没有
    fireEvent.change(screen.getByPlaceholderText('输入姓名或手机号搜索'), { target: { value: '不存在的人' } })
    fireEvent.click(screen.getByRole('button', { name: '查询' }))
    await waitFor(() =>
      expect(mockGetEmployees).toHaveBeenLastCalledWith(expect.objectContaining({ keyword: '不存在的人' })),
    )
    expect(screen.getByTestId('table-empty').textContent).toContain('没有符合筛选条件的员工')
  })

  it('renders pagination', async () => {
    render(<EmployeesPage />)
    await waitFor(() => {
      expect(screen.getByTestId('pagination')).toBeInTheDocument()
    })
  })

  it('#6083: 同码多节点时权限徽标 label 取菜单树首见（dashboard:view → 经营看板，不被「每日简报」覆盖）', async () => {
    // #5699/#5291 的设计：后端菜单树允许同码多节点（workspace 组两个 dashboard:view 叶子）
    // ⇒ 前端 labelMap 不能「后写覆盖先写」，必须首见优先，否则徽标名随数据顺序漂移
    mockRequestGet.mockResolvedValue({
      data: {
        data: [
          {
            code: 'workspace',
            label: '工作台',
            children: [
              { code: 'dashboard:view', label: '经营看板' },
              { code: 'dashboard:view', label: '每日简报' },
            ],
          },
        ],
      },
    })
    mockGetEmployees.mockResolvedValue({
      data: {
        data: {
          items: [
            { id: 1, name: '张三', phone: '13800001111', position: '客服', permissions: ['dashboard:view'], status: 'active', createdAt: '2026-06-01T10:00:00' },
          ],
          total: 1,
        },
      },
    })
    render(<EmployeesPage />)
    await waitFor(() => {
      expect(screen.getByTestId('employee-1')).toBeInTheDocument()
    })
    // 修复前：labelMap 按 code 后写覆盖先写 ⇒ 徽标显示「每日简报」；修复后首见优先 ⇒ 「经营看板」
    expect(within(screen.getByTestId('employee-1')).getByText('经营看板')).toBeInTheDocument()
    expect(within(screen.getByTestId('employee-1')).queryByText('每日简报')).not.toBeInTheDocument()
  })

  // ==================== #5485: 员工登录账号（用户名 + 初始密码） ====================
  // ⚠️ #1830 曾断言「弹窗不含用户名字段」—— 那时「用户名」只是手机号的别名、无独立含义。
  // #5485 起「用户名」是**登录账号**（与手机号分离、租户内唯一、员工靠它登录），
  // 故这条判据按新契约**反向重写**（不是删掉，见下方逐条）。

  it('#5485: 新增弹窗含「登录用户名」与「初始密码」字段', async () => {
    render(<EmployeesPage />)
    fireEvent.click(screen.getByText('新增员工'))
    await waitFor(() => {
      expect(screen.getByTestId('modal')).toBeInTheDocument()
    })
    expect(screen.getByPlaceholderText('员工登录账号，如 zhangsan')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('请输入初始密码')).toBeInTheDocument()
  })

  it('#1830/#2907/#5485: 新增弹窗含姓名/手机号/登录用户名/初始密码/岗位/账号权限 6 字段，仍不含角色', async () => {
    render(<EmployeesPage />)
    fireEvent.click(screen.getByText('新增员工'))
    await waitFor(() => {
      expect(screen.getByTestId('modal')).toBeInTheDocument()
    })
    const modal = within(screen.getByTestId('modal'))
    expect(modal.getByText('姓名 *')).toBeInTheDocument()
    expect(modal.getByText('手机号 *')).toBeInTheDocument()
    expect(modal.getByText('登录用户名 *')).toBeInTheDocument()
    expect(modal.getByText('初始密码 *')).toBeInTheDocument()
    expect(modal.getByText('岗位 *')).toBeInTheDocument()
    expect(modal.getByText('账号权限 *')).toBeInTheDocument()
    // 角色字段仍不在（#2907：新增员工弹窗去掉「角色」）
    expect(modal.queryByText('角色')).not.toBeInTheDocument()
  })

  it('#5485: 弹窗说明登录方式「用户名@企业编码」与「员工首次登录需修改密码」', async () => {
    render(<EmployeesPage />)
    fireEvent.click(screen.getByText('新增员工'))
    await waitFor(() => {
      expect(screen.getByTestId('modal')).toBeInTheDocument()
    })
    expect(screen.getByText(/用户名@企业编码/)).toBeInTheDocument()
    expect(screen.getByText(/员工首次登录需修改密码/)).toBeInTheDocument()
  })

  it('#5485: 列表显示登录账号 employeeUsername（手机号列仍是手机号）；未设置的存量员工显示「未设置」', async () => {
    render(<EmployeesPage />)
    await waitFor(() => {
      expect(screen.getByTestId('employee-1')).toBeInTheDocument()
    })
    expect(within(screen.getByTestId('employee-1')).getByTestId('cell-employeeUsername')).toHaveTextContent('zhangsan')
    expect(within(screen.getByTestId('employee-1')).getByTestId('cell-phone')).toHaveTextContent('13800001111')
    // 存量员工（管理员尚未补设用户名）：显示「未设置」，而不是拿手机号冒充账号
    expect(within(screen.getByTestId('employee-2')).getByTestId('cell-employeeUsername')).toHaveTextContent('未设置')
  })

  it('#5485: 新建时未填登录用户名 → 提示「请设置登录用户名」且不发请求（没有账号的员工登不进来）', async () => {
    render(<EmployeesPage />)
    // 打开新增弹窗
    fireEvent.click(screen.getByText('新增员工'))
    await waitFor(() => {
      expect(screen.getByTestId('modal')).toBeInTheDocument()
    })
    fireEvent.change(screen.getByPlaceholderText('请输入姓名'), { target: { value: '张三' } })
    fireEvent.change(screen.getByPlaceholderText('请输入手机号'), { target: { value: '13800138000' } })
    // 用户名留空点创建
    fireEvent.click(screen.getByText('创建'))
    expect(mockToastError).toHaveBeenCalledWith('请设置登录用户名')
    expect(mockCreateEmployee).not.toHaveBeenCalled()
  })

  it('#5485: 新建时未填初始密码 → 提示「请设置初始密码」且不发请求', async () => {
    render(<EmployeesPage />)
    fireEvent.click(screen.getByText('新增员工'))
    await waitFor(() => {
      expect(screen.getByTestId('modal')).toBeInTheDocument()
    })
    fireEvent.change(screen.getByPlaceholderText('请输入姓名'), { target: { value: '张三' } })
    fireEvent.change(screen.getByPlaceholderText('请输入手机号'), { target: { value: '13800138000' } })
    fireEvent.change(screen.getByPlaceholderText('员工登录账号，如 zhangsan'), { target: { value: 'zhangsan' } })
    fireEvent.click(screen.getByText('创建'))
    expect(mockToastError).toHaveBeenCalledWith('请设置初始密码')
    expect(mockCreateEmployee).not.toHaveBeenCalled()
  })

  it('#5485: 创建员工 payload 带 username + password（仍不含 role）', async () => {
    mockCreateEmployee.mockResolvedValue({ data: { data: { id: 99 } } })
    render(<EmployeesPage />)
    fireEvent.click(screen.getByText('新增员工'))
    await waitFor(() => {
      expect(screen.getByTestId('modal')).toBeInTheDocument()
    })
    fireEvent.change(screen.getByPlaceholderText('请输入姓名'), { target: { value: '张三' } })
    fireEvent.change(screen.getByPlaceholderText('请输入手机号'), { target: { value: '13800138000' } })
    fireEvent.change(screen.getByPlaceholderText('员工登录账号，如 zhangsan'), { target: { value: 'zhangsan' } })
    fireEvent.change(screen.getByPlaceholderText('请输入初始密码'), { target: { value: 'Init#12345' } })
    // 选岗位（#2969 岗位下拉）：选「客服」→ 自动带出岗位默认权限（products:view + order:list）
    const posSelect = within(screen.getByTestId('modal')).getByRole('combobox')
    fireEvent.change(posSelect, { target: { value: '客服' } })
    // Click create
    fireEvent.click(screen.getByText('创建'))
    await waitFor(() => {
      expect(mockCreateEmployee).toHaveBeenCalled()
    })
    const callArgs = mockCreateEmployee.mock.calls[0]?.[0]
    expect(callArgs).toMatchObject({
      name: '张三',
      phone: '13800138000',
      position: '客服',
      username: 'zhangsan',
      password: 'Init#12345',
    })
    expect(callArgs).not.toHaveProperty('role')
    expect(callArgs.permissions).toEqual(expect.arrayContaining(['products:view', 'order:list']))
  })

  // ==================== #5485: 编辑员工（不回显/不清空既有账号） ====================

  it('#5485: 编辑弹窗用户名预填 employeeUsername（**不是** 手机号）且密码不回显', async () => {
    render(<EmployeesPage />)
    await waitFor(() => {
      expect(screen.getAllByText('编辑').length).toBeGreaterThan(0)
    })
    fireEvent.click(screen.getAllByText('编辑')[0])
    await waitFor(() => {
      expect(screen.getByTestId('modal')).toBeInTheDocument()
    })
    const usernameInput = screen.getByPlaceholderText('员工登录账号，如 zhangsan') as HTMLInputElement
    expect(usernameInput.value).toBe('zhangsan')
    // 密码不回显（后端不下发；留空即不改）
    const passwordInput = screen.getByPlaceholderText('留空则保持原密码') as HTMLInputElement
    expect(passwordInput.value).toBe('')
  })

  it('#5485: 编辑保存时用户名留空 → payload 不含 username/password（不把已有账号悄悄清掉）', async () => {
    mockUpdateEmployee.mockResolvedValue({ data: { data: { id: 2 } } })
    render(<EmployeesPage />)
    await waitFor(() => {
      expect(screen.getAllByText('编辑').length).toBeGreaterThan(0)
    })
    // 第 2 行（李四）没有 employeeUsername（存量员工）
    fireEvent.click(screen.getAllByText('编辑')[1])
    await waitFor(() => {
      expect(screen.getByTestId('modal')).toBeInTheDocument()
    })
    fireEvent.click(screen.getByText('保存'))
    await waitFor(() => {
      expect(mockUpdateEmployee).toHaveBeenCalled()
    })
    const callArgs = mockUpdateEmployee.mock.calls[0]?.[1]
    expect(callArgs).toMatchObject({ name: '李四', phone: '13800002222', position: '管理员' })
    expect(callArgs).not.toHaveProperty('username')
    expect(callArgs).not.toHaveProperty('password')
  })

  // ==================== #5485: 重置密码（员工忘记密码时的找回路径） ====================

  it('#5485: 重置密码 → 提交新初始密码并提示「下次登录需先修改密码」', async () => {
    mockResetPassword.mockResolvedValue({ data: { data: null } })
    render(<EmployeesPage />)
    await waitFor(() => {
      expect(screen.getAllByText('重置密码').length).toBeGreaterThan(0)
    })
    fireEvent.click(screen.getAllByText('重置密码')[0])
    await waitFor(() => {
      expect(screen.getByTestId('modal')).toBeInTheDocument()
    })
    fireEvent.change(screen.getByPlaceholderText('请输入新的初始密码'), { target: { value: 'Reset#12345' } })
    fireEvent.click(screen.getByText('确认重置'))

    await waitFor(() => {
      expect(mockResetPassword).toHaveBeenCalledWith(1, { newPassword: 'Reset#12345' })
    })
    expect(mockToastSuccess).toHaveBeenCalledWith('密码已重置，请告知员工：下次登录需先修改密码')
  })

  it('#5485: 重置密码未填新密码 → 提示且不发请求', async () => {
    render(<EmployeesPage />)
    await waitFor(() => {
      expect(screen.getAllByText('重置密码').length).toBeGreaterThan(0)
    })
    fireEvent.click(screen.getAllByText('重置密码')[0])
    await waitFor(() => {
      expect(screen.getByTestId('modal')).toBeInTheDocument()
    })
    fireEvent.click(screen.getByText('确认重置'))
    expect(mockToastError).toHaveBeenCalledWith('请输入新的初始密码')
    expect(mockResetPassword).not.toHaveBeenCalled()
  })

  // ==================== #2969 岗位权限体系：选岗位自动带出默认权限（快照可自定义） ====================

  it('#2969: 新增弹窗选择岗位 → 权限树自动预填该岗位默认权限（快照式，可再自定义）', async () => {
    render(<EmployeesPage />)
    fireEvent.click(screen.getByText('新增员工'))
    await waitFor(() => {
      expect(screen.getByTestId('modal')).toBeInTheDocument()
    })
    // 初始权限树为空
    expect(screen.getByTestId('tree-checkbox').getAttribute('data-selected')).toBe('[]')
    // 选「客服」岗位 → 自动带出岗位默认权限
    const posSelect = within(screen.getByTestId('modal')).getByRole('combobox')
    fireEvent.change(posSelect, { target: { value: '客服' } })
    const tree = screen.getByTestId('tree-checkbox')
    expect(JSON.parse(tree.getAttribute('data-selected') || '[]')).toEqual(
      expect.arrayContaining(['products:view', 'order:list'])
    )
    // 切到「运营」岗位 → 权限重置为新岗位默认（#2969：改岗位则重置为新岗位默认）
    fireEvent.change(posSelect, { target: { value: '运营' } })
    expect(JSON.parse(screen.getByTestId('tree-checkbox').getAttribute('data-selected') || '[]'))
      .toEqual(expect.arrayContaining(['dashboard:view']))
  })

  // ==================== 员工管理权限全链路（按钮级权限） ====================

  // ══════════════════════════════════════════════════════════════════════════
  // issue #6759 需求①：权限树标注「手机端可见面」（真值 = 服务端派生下发的 mobileTitles）
  //
  // 🔴 本用例的**唯一输入**是 `GET /api/admin/menus` 的响应 —— 服务端给什么就渲染什么；
  //    前端**没有任何**「码 → 手机端面」的常量表（判据 =
  //    tests/unit_ci_workflows/test_mobile_surface_annotation_single_source.py）。
  // ══════════════════════════════════════════════════════════════════════════
  it('#6759: 权限树渲染服务端下发的手机端标注；没有手机端面的码**不渲染**（负控）', async () => {
    mockRequestGet.mockResolvedValue({
      data: {
        data: [
          {
            code: 'production-center',
            label: '生产管理',
            children: [
              // 手机端有面 ⇒ 必须出现标注
              { code: 'processing:view', label: '智能派单', mobileTitles: ['智能派单'] },
              // 手机端没有面 ⇒ 不得出现标注（纯 PC 权限）
              { code: 'production:view', label: '作业看板', mobileTitles: [] },
            ],
          },
          {
            code: 'inventory-center',
            label: '仓储与物料',
            children: [
              { code: 'inbound:view', label: '入库单', mobileTitles: ['入库过账'] },
              // 缺字段（老服务端 / 尚未下发）⇒ 同样不得出现标注
              { code: 'order:list', label: '发货单' },
            ],
          },
        ],
      },
    })
    render(<EmployeesPage />)
    fireEvent.click(screen.getByText('新增员工'))
    await waitFor(() => expect(screen.getByTestId('modal')).toBeInTheDocument())

    // ① 有手机端面的码 ⇒ 渲染「 · 手机端：X」标注（逐字）
    await waitFor(() => {
      expect(screen.getByText('智能派单 · 手机端：智能派单')).toBeInTheDocument()
    })
    expect(screen.getByText('入库单 · 手机端：入库过账')).toBeInTheDocument()

    // ② 没有手机端面的码 ⇒ **不追加任何标注**（不摆内部标识、不产生噪音）
    expect(screen.getByText('作业看板')).toBeInTheDocument()
    expect(screen.queryByText(/作业看板 · 手机端/)).not.toBeInTheDocument()
    expect(screen.getByText('发货单')).toBeInTheDocument()
    expect(screen.queryByText(/发货单 · 手机端/)).not.toBeInTheDocument()
    // ③ 反向自证：整个树上「手机端：」只出现**两处**（= 服务端给了 mobileTitles 的那两个码）
    expect(screen.queryAllByText(/手机端：/)).toHaveLength(2)
  })

  it('#6759 对照读数: 服务端**没有**下发任何 mobileTitles ⇒ 树上零标注（标注不是前端自造的）', async () => {
    mockRequestGet.mockResolvedValue({
      data: {
        data: [
          {
            code: 'production-center',
            label: '生产管理',
            children: [{ code: 'processing:view', label: '智能派单' }],
          },
        ],
      },
    })
    render(<EmployeesPage />)
    fireEvent.click(screen.getByText('新增员工'))
    await waitFor(() => expect(screen.getByTestId('modal')).toBeInTheDocument())
    expect(screen.getByText('智能派单')).toBeInTheDocument()
    expect(screen.queryAllByText(/手机端：/)).toHaveLength(0)
  })

  // ══════════════════════════════════════════════════════════════════════════
  // 2026-10-18 用户验收截图（三处「内部标识 / 缺面」）：
  //   ① 岗位列印角色码（`knowledge_editor`）
  //   ② 权限列印权限码（`dashboard:view`，顶层独立项没有中文名）
  //   ③ 员工弹窗看不到手机端菜单（「我之前让你设计落地过，可能漏做了？」）
  // ══════════════════════════════════════════════════════════════════════════
  it('岗位列显示岗位名 —— 角色码（API/脚本建号）不得原样上屏；行内无 roles 时用岗位清单兜底', async () => {
    mockGetEmployees.mockResolvedValue({
      data: {
        data: {
          items: [
            // 存量脏数据形态：position 存的是**角色码**，中文名在 roles[] 里（user_roles 投影）
            { id: 11, name: '回归知识编辑', phone: '13900002007', position: 'knowledge_editor',
              roles: [{ id: 'r9', name: '知识编辑', code: 'knowledge_editor' }],
              permissions: [], status: 'active', createdAt: '2026-10-18T07:09:00', employeeUsername: 'reg_knowledge' },
            // 行内 roles 缺失 ⇒ 用页面已加载的岗位清单（/api/admin/roles/all）兜底
            { id: 12, name: '运营小李', phone: '13900002003', position: 'operator',
              roles: [], permissions: [], status: 'active', createdAt: '2026-10-18T07:09:00' },
          ],
          total: 2,
        },
      },
    })
    render(<EmployeesPage />)
    await waitFor(() => expect(screen.getByTestId('employee-11')).toBeInTheDocument())
    expect(within(screen.getByTestId('employee-11')).getByTestId('cell-position').textContent).toBe('知识编辑')
    expect(within(screen.getByTestId('employee-12')).getByTestId('cell-position').textContent).toBe('运营')
    // 负控：角色码一个字都不许上屏
    expect(screen.queryByText('knowledge_editor')).not.toBeInTheDocument()
    expect(screen.queryByText('operator')).not.toBeInTheDocument()
  })

  it('权限列显示中文名 —— 顶层独立项的权限码（dashboard:view）不得回退成英文码', async () => {
    mockRequestGet.mockResolvedValue({
      data: {
        data: [
          // #7087 后「经营看板」是**顶层独立项**（无 children）—— 改前只扫 children ⇒ 这个码没中文名
          { code: 'dashboard:view', label: '经营看板' },
          {
            code: 'inventory-center',
            label: '仓储与物料',
            children: [
              { code: 'product:list', label: '库存明细' },
              // 叶子数（3）> 该员工的权限数（2）⇒ 不会折叠成「全部权限」徽章（否则测不到逐个中文名）
              { code: 'inbound:view', label: '入库单' },
            ],
          },
        ],
      },
    })
    mockGetEmployees.mockResolvedValue({
      data: {
        data: {
          items: [
            { id: 21, name: '回归销售', phone: '13900002001', position: '销售', roles: [],
              permissions: ['dashboard:view', 'product:list'], status: 'active', createdAt: '2026-10-18T07:09:00' },
          ],
          total: 1,
        },
      },
    })
    render(<EmployeesPage />)
    await waitFor(() => expect(screen.getByTestId('employee-21')).toBeInTheDocument())
    const cell = within(screen.getByTestId('employee-21')).getByTestId('cell-permissions')
    expect(cell.textContent).toContain('经营看板')
    expect(cell.textContent).toContain('库存明细')
    expect(cell.textContent).not.toContain('dashboard:view')
  })

  it('编辑弹窗「手机端菜单」按服务端 mobileTitles 渲染；勾选改动的是**同一份**权限（不产生第二套授权）', async () => {
    mockRequestGet.mockResolvedValue({
      data: {
        data: [
          { code: 'dashboard:view', label: '经营看板', mobileTitles: ['数据'] },
          {
            code: 'production-center',
            label: '生产管理',
            children: [
              { code: 'processing:view', label: '智能派单', mobileTitles: ['智能派单'] },
              { code: 'production:view', label: '作业看板', mobileTitles: ['计件工资报表', '生产待办'] },
            ],
          },
        ],
      },
    })
    render(<EmployeesPage />)
    fireEvent.click(screen.getByText('新增员工'))
    await waitFor(() => expect(screen.getByTestId('modal')).toBeInTheDocument())

    const box = await screen.findByTestId('employees-mobile-menus')
    expect(within(box).getByText('数据')).toBeInTheDocument()
    expect(within(box).getByText('智能派单')).toBeInTheDocument()
    // 多个面共用同一权限码 ⇒ 同一行展示（不拆成两个不能独立勾选的格子）
    expect(within(box).getByText('计件工资报表、生产待办')).toBeInTheDocument()

    // 勾选 = 授予该权限码 ⇒ 权限树（同一份 formData.permissions）同步出现这个码
    const label = within(box).getByText('数据').closest('label') as HTMLElement
    fireEvent.click(within(label).getByRole('checkbox'))
    await waitFor(() => {
      expect(JSON.parse(screen.getByTestId('tree-checkbox').getAttribute('data-selected') || '[]'))
        .toContain('dashboard:view')
    })
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

// ══════════════════════════════════════════════════════════════════════════════
// issue #6663：岗位下拉读失败 ≠ 空下拉（三维审计逐条复核）
//
// 改前 `employeeApi.loadPositions()` 的 catch 是**空的**（注释还写着「岗位为空时可手输」——
// 而反：岗位用 `Select`，**不能手输**）⇒ 下拉空 ⇒ **建不出员工**，页面一言不发。
// 类级收口 = tests/unit/read-failure-empty-state-guard.test.ts（本文件是它的实例面）。
// ══════════════════════════════════════════════════════════════════════════════
describe('EmployeesPage 岗位下拉读失败态（issue #6663）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockUseAuthStore.mockReturnValue({
      user: { id: '1', name: '管理员', roles: ['admin'], permissions: ['*'] },
    })
    mockGetEmployees.mockResolvedValue({ data: { data: { items: [], total: 0 } } })
    mockRequestGet.mockResolvedValue({ data: { data: [] } })
  })

  it('岗位清单读失败 ⇒ 弹窗里显示失败态 + 重试出口（不再一言不发）', async () => {
    mockGetAllRoles.mockRejectedValue(new Error('500'))
    render(<EmployeesPage />)

    await waitFor(() => expect(screen.getByText('新增员工')).toBeInTheDocument())
    fireEvent.click(screen.getByText('新增员工'))

    const failure = await screen.findByTestId('employees-positions-error')
    expect(failure).toHaveTextContent('岗位清单读取失败')
    // 重试出口真可点（这次成功 ⇒ 失败态退场、下拉有选项）
    mockGetAllRoles.mockResolvedValue({
      data: { data: [{ id: 'r1', name: '客服', code: 'customer_service', permissions: [] }] },
    })
    fireEvent.click(within(failure).getByRole('button', { name: '重新加载' }))
    await waitFor(() =>
      expect(screen.queryByTestId('employees-positions-error')).not.toBeInTheDocument(),
    )
    expect(screen.getByRole('option', { name: '客服' })).toBeInTheDocument()
  })

  it('岗位清单读成功 ⇒ 不显示失败态（对照读数：失败态不是恒显）', async () => {
    mockGetAllRoles.mockResolvedValue({
      data: { data: [{ id: 'r1', name: '客服', code: 'customer_service', permissions: [] }] },
    })
    render(<EmployeesPage />)

    await waitFor(() => expect(screen.getByText('新增员工')).toBeInTheDocument())
    fireEvent.click(screen.getByText('新增员工'))
    await waitFor(() => expect(screen.getByRole('option', { name: '客服' })).toBeInTheDocument())
    expect(screen.queryByTestId('employees-positions-error')).not.toBeInTheDocument()
  })
})
