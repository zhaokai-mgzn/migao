// @vitest-environment jsdom
// case_ids: PG-072, HR-001, HR-002, UI-024, UI-091
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { toast } from 'sonner'

/**
 * 工人档案面板（issue #4869）：**首个工人怎么建出来** + 工人与员工必须一眼分得清。
 *
 * 改前形态（红证形态）：`frontend/admin-web` 全仓零命中「工人档案」/`/api/admin/workers`
 * ⇒ 本测试引用的 `@/components/employees/WorkerProfilesPanel` **不存在**（导入即红）；
 * 且员工管理页里**没有任何入口**能设 `users.worker_no` ⇒ 真实部署里第一个工人都建不出来。
 *
 * 判据（逐条对应验收标准 1 / 4）：
 *   ① 列表**只**列工人档案（工号 / 姓名 / 状态），且页面显式说明工人不等同员工；
 *   ② 建号 = 工号 + 姓名 + PIN 三项，调的是新端点 `/api/admin/workers`（不是 `POST /api/admin/users`）；
 *   ③ 无 `employee:create` ⇒ 建号入口不出现（权限码复用员工域，不新增权限码）；
 *   ④ 建号失败 ⇒ 弹窗**不关**、列表**不假装刷新**（失败不得冒充成功）；错误提示走统一去重链
 *      （UI-024：拦截器已提示具体错误 ⇒ 页面不再叠加通用 toast）。
 *
 * issue #6788 追加判据（工人端菜单权限；单层口径 issue #6828）：
 *   ⑥ 选项逐值 = 服务端**页面目录**（`GET /api/admin/worker-pages`）—— 页键与人话名都由服务端给，
 *      前端不自己编一份清单；
 *   ⑦ 默认**全勾** ⇒ 建号请求发 `workerPages: null`（= 不限制，零回归）；只勾一页 ⇒ 发那一页（**收窄**）；
 *   ⑧ 列表列出每位工人的菜单口径：未收窄 ⇒「全部页面」；收窄 ⇒ 逐个人话名。
 */

const mockListWorkers = vi.fn()
const mockCreateWorker = vi.fn()
const mockSetWorkerStatus = vi.fn()
const mockResetWorkerPin = vi.fn()
const mockGetWorkerPageCatalog = vi.fn()

vi.mock('@/lib/api', () => ({
  workerApi: {
    listWorkers: (...a: unknown[]) => mockListWorkers(...a),
    createWorker: (...a: unknown[]) => mockCreateWorker(...a),
    setWorkerStatus: (...a: unknown[]) => mockSetWorkerStatus(...a),
    resetWorkerPin: (...a: unknown[]) => mockResetWorkerPin(...a),
  },
  workerPageCatalogApi: {
    get: (...a: unknown[]) => mockGetWorkerPageCatalog(...a),
  },
}))

import WorkerProfilesPanel from '@/components/employees/WorkerProfilesPanel'
import { markErrorToastShown } from '@/lib/api-error'

const okPage = (items: unknown[]) => ({ data: { data: { items, total: items.length } } })

/** 工人端页面目录（读面形状：pages + labels；issue #6828）。 */
const catalog = () => ({
  data: {
    data: {
      pages: ['report', 'order', 'cut_calc', 'shipment'],
      labels: { report: '报工', order: '订单', cut_calc: '裁高计算器', shipment: '发货' },
    },
  },
})

const worker = (over: Record<string, unknown> = {}) => ({
  id: 'w-1',
  workerNo: 'W-1001',
  name: '张三',
  status: 'active',
  createdAt: '2026-09-26T10:00:00+08:00',
  ...over,
})

describe('WorkerProfilesPanel（issue #4869）', () => {
  beforeEach(() => {
    mockListWorkers.mockReset()
    mockCreateWorker.mockReset()
    mockSetWorkerStatus.mockReset()
    mockResetWorkerPin.mockReset()
    mockGetWorkerPageCatalog.mockReset()
    ;(toast.error as ReturnType<typeof vi.fn>).mockClear()
    mockListWorkers.mockResolvedValue(okPage([worker()]))
    // 缺省：企业四页全开（逐人菜单的选项来源）
    mockGetWorkerPageCatalog.mockResolvedValue(catalog())
  })

  it('① 列表列出工人档案：工号 / 姓名 / 状态', async () => {
    render(<WorkerProfilesPanel canWrite />)

    expect(await screen.findByText('W-1001')).toBeInTheDocument()
    expect(screen.getByText('张三')).toBeInTheDocument()
    expect(mockListWorkers).toHaveBeenCalledWith(
      expect.objectContaining({ page: 1, size: 10 })
    )
  })

  it('① 工人与员工分得清：页面显式说明工人不进管理后台', async () => {
    render(<WorkerProfilesPanel canWrite />)

    expect(await screen.findByText(/不进入管理后台/)).toBeInTheDocument()
    expect(screen.getByText(/工号 \+ PIN/)).toBeInTheDocument()
  })

  it('② 建号：工号 + 姓名 + PIN ⇒ 调新端点封装（不是员工创建接口）', async () => {
    mockCreateWorker.mockResolvedValue({ data: { data: worker({ id: 'w-2', workerNo: 'W-1002', name: '李四' }) } })
    render(<WorkerProfilesPanel canWrite />)

    fireEvent.click(await screen.findByText('新建工人档案'))
    fireEvent.change(screen.getByPlaceholderText(/W-1002/), { target: { value: 'W-1002' } })
    fireEvent.change(screen.getByPlaceholderText(/李四/), { target: { value: '李四' } })
    fireEvent.change(screen.getByPlaceholderText(/位数字/), { target: { value: '135791' } })
    fireEvent.click(screen.getByText('创建'))

    await waitFor(() => {
      // 默认全勾 = 不限制 ⇒ 这一格发 null（收窄是**减**，默认不减任何东西）
      expect(mockCreateWorker).toHaveBeenCalledWith({
        workerNo: 'W-1002', name: '李四', pin: '135791', workerPages: null,
      })
    })
    // 建号成功后回到列表并刷新（新工人必须立刻可见，否则管理员会重复建号）
    await waitFor(() => expect(mockListWorkers).toHaveBeenCalledTimes(2))
  })

  it('③ 无 employee:create ⇒ 不出现建号入口，只读提示可见', async () => {
    render(<WorkerProfilesPanel canWrite={false} />)

    await screen.findByText('W-1001')
    expect(screen.queryByText('新建工人档案')).not.toBeInTheDocument()
    expect(screen.getByText(/只读/)).toBeInTheDocument()
  })

  it('④ 工号冲突（服务端 409）⇒ 弹窗不关、列表不假装刷新、不叠加通用错误 toast', async () => {
    const conflict = new Error('工号已被占用：W-1001（本企业内工号必须唯一）')
    // 拦截器已弹具体错误（request.ts 的口径）⇒ 页面 catch 走 toastRequestError，不得再弹通用文案
    markErrorToastShown(conflict)
    mockCreateWorker.mockRejectedValue(conflict)

    render(<WorkerProfilesPanel canWrite />)
    fireEvent.click(await screen.findByText('新建工人档案'))
    fireEvent.change(screen.getByPlaceholderText(/W-1002/), { target: { value: 'W-1001' } })
    fireEvent.change(screen.getByPlaceholderText(/李四/), { target: { value: '王五' } })
    fireEvent.change(screen.getByPlaceholderText(/位数字/), { target: { value: '246810' } })
    fireEvent.click(screen.getByText('创建'))

    await waitFor(() => expect(mockCreateWorker).toHaveBeenCalledTimes(1))
    // 弹窗仍在（管理员可直接改工号重试 —— 工号冲突是**可修正**的错误）
    expect(screen.getByDisplayValue('W-1001')).toBeInTheDocument()
    // 没有假装成功：列表没有因为失败而刷新
    expect(mockListWorkers).toHaveBeenCalledTimes(1)
    // UI-024：拦截器已提示具体错误，页面不再叠加通用 toast
    expect(toast.error).not.toHaveBeenCalled()
  })

  it('⑤ 重置 PIN（留空 ⇒ 服务端随机）：结果面板显示**服务端返回的新 PIN** + 「只显示这一次」提醒', async () => {
    mockResetWorkerPin.mockResolvedValue({ data: { data: { pin: '654321' } } })
    render(<WorkerProfilesPanel canWrite />)

    fireEvent.click(await screen.findByText('重置 PIN'))
    fireEvent.click(screen.getByText('确认重置'))

    await waitFor(() => expect(mockResetWorkerPin).toHaveBeenCalledWith('w-1', undefined))
    expect(await screen.findByTestId('worker-new-pin')).toBeInTheDocument()
    expect(screen.getByText('654321')).toBeInTheDocument()
    // 明文**只在这里出现一次**（关掉即查不到）—— 页面必须把这一点说清，否则管理员会以为以后还能看
    expect(screen.getByText(/关掉本窗口后就查不到了/)).toBeInTheDocument()
  })

  it('⑤ 手输新 PIN ⇒ 原样透传（页面只做形态拦阻，形态真值仍以服务端为准）', async () => {
    mockResetWorkerPin.mockResolvedValue({ data: { data: { pin: '135791' } } })
    render(<WorkerProfilesPanel canWrite />)

    fireEvent.click(await screen.findByText('重置 PIN'))
    fireEvent.change(screen.getByPlaceholderText(/留空则由系统随机生成/), { target: { value: '135791' } })
    fireEvent.click(screen.getByText('确认重置'))

    await waitFor(() => expect(mockResetWorkerPin).toHaveBeenCalledWith('w-1', '135791'))
    expect(await screen.findByText('135791')).toBeInTheDocument()
  })

  it('⑤ 无 employee:create ⇒ 重置 PIN 入口不可用（与建号同档写权限；只读角色点不动）', async () => {
    render(<WorkerProfilesPanel canWrite={false} />)

    const resetBtn = await screen.findByText('重置 PIN')
    expect(resetBtn).toBeDisabled()
    fireEvent.click(resetBtn)
    expect(mockResetWorkerPin).not.toHaveBeenCalled()
  })

  it('⑤ 重置失败 ⇒ 弹窗不关、**不显示任何 PIN**（失败不得冒充成功）且不叠加通用 toast', async () => {
    const notFound = new Error('工人档案不存在')
    markErrorToastShown(notFound)
    mockResetWorkerPin.mockRejectedValue(notFound)

    render(<WorkerProfilesPanel canWrite />)
    fireEvent.click(await screen.findByText('重置 PIN'))
    fireEvent.click(screen.getByText('确认重置'))

    await waitFor(() => expect(mockResetWorkerPin).toHaveBeenCalledTimes(1))
    // 弹窗仍在（可改值重试），且没有伪造一个「新 PIN」出来
    expect(screen.getByText('确认重置')).toBeInTheDocument()
    expect(screen.queryByTestId('worker-new-pin')).not.toBeInTheDocument()
    expect(toast.error).not.toHaveBeenCalled()
  })

  // ════════════════════════════════════════════════════════════════════════════
  // ⑥⑦⑧ 工人端菜单权限（issue #6788；用户 2026-10-13 逐字「工人档案上也应该设置 h5 工人端的
  //      菜单权限，这样让不同岗位的工人只关注他自己有权限的功能了」）
  // ════════════════════════════════════════════════════════════════════════════

  it('⑥ 选项逐值 = 服务端页面目录（页键与人话名都由服务端给，前端不自己编一份）', async () => {
    mockGetWorkerPageCatalog.mockResolvedValue(catalog())
    render(<WorkerProfilesPanel canWrite />)

    fireEvent.click(await screen.findByText('新建工人档案'))

    // 目录给的是闭词表全部页 ⇒ 四个选项一个不少、一个不多
    for (const key of ['report', 'order', 'cut_calc', 'shipment']) {
      expect(await screen.findByTestId(`worker-page-option-${key}`)).toBeInTheDocument()
    }
    // 每个选项只有**一份**人话名（服务端给的 label，不另写一套）
    expect(screen.getAllByText('报工')).toHaveLength(1)
  })

  it('⑦ 只勾一页 ⇒ 建号请求带 workerPages=[那一页]（收窄；不同岗位的工人只看自己有份的功能）', async () => {
    mockCreateWorker.mockResolvedValue({ data: { data: worker({ id: 'w-3', workerNo: 'W-1003' }) } })
    render(<WorkerProfilesPanel canWrite />)

    fireEvent.click(await screen.findByText('新建工人档案'))
    fireEvent.change(screen.getByPlaceholderText(/W-1002/), { target: { value: 'W-1003' } })
    fireEvent.change(screen.getByPlaceholderText(/李四/), { target: { value: '赵六' } })
    fireEvent.change(screen.getByPlaceholderText(/位数字/), { target: { value: '246810' } })
    // 默认全勾 ⇒ 先取消三个，只留「裁高计算器」
    fireEvent.click(await screen.findByTestId('worker-page-option-report'))
    fireEvent.click(screen.getByTestId('worker-page-option-order'))
    fireEvent.click(screen.getByTestId('worker-page-option-shipment'))
    fireEvent.click(screen.getByText('创建'))

    await waitFor(() => {
      expect(mockCreateWorker).toHaveBeenCalledWith({
        workerNo: 'W-1003', name: '赵六', pin: '246810', workerPages: ['cut_calc'],
      })
    })
  })

  it('⑦ 「全部页面」一键回全勾 ⇒ 又发 null（可回退，不会误收窄）', async () => {
    mockCreateWorker.mockResolvedValue({ data: { data: worker({ id: 'w-4' }) } })
    render(<WorkerProfilesPanel canWrite />)

    fireEvent.click(await screen.findByText('新建工人档案'))
    fireEvent.change(screen.getByPlaceholderText(/W-1002/), { target: { value: 'W-1004' } })
    fireEvent.change(screen.getByPlaceholderText(/李四/), { target: { value: '钱七' } })
    fireEvent.change(screen.getByPlaceholderText(/位数字/), { target: { value: '246810' } })
    fireEvent.click(await screen.findByTestId('worker-page-option-report'))
    fireEvent.click(screen.getByTestId('worker-pages-select-all'))
    fireEvent.click(screen.getByText('创建'))

    await waitFor(() => {
      expect(mockCreateWorker).toHaveBeenCalledWith({
        workerNo: 'W-1004', name: '钱七', pin: '246810', workerPages: null,
      })
    })
  })

  it('⑧ 列表标出每位工人的菜单口径：未收窄 ⇒「全部页面」；收窄 ⇒ 逐个人话名', async () => {
    mockListWorkers.mockResolvedValue(okPage([
      worker({ id: 'w-1', workerNo: 'W-1001', name: '张三' }),
      worker({ id: 'w-2', workerNo: 'W-1002', name: '李四', workerPages: ['cut_calc'] }),
      worker({ id: 'w-3', workerNo: 'W-1003', name: '王五', workerPages: [] }),
    ]))
    render(<WorkerProfilesPanel canWrite />)

    expect(await screen.findByTestId('worker-menu-w-1')).toHaveTextContent('全部页面')
    expect(screen.getByTestId('worker-menu-w-2')).toHaveTextContent('裁高计算器')
    // 🔴 空数组（历史脏数据）显示成「全部页面」—— 与**读面契约**一致（`WorkerPages.effectiveFor`
    // 对归一后为空集一律回落全部页面，issue #6828 复核发现旧的「未开放任何页面」与契约相反）
    expect(screen.getByTestId('worker-menu-w-3')).toHaveTextContent('全部页面')
  })

  it('⑧ 企业级页面读不到（如岗位没有生产域读码）⇒ 建号主流程照旧，只是不显示菜单一节', async () => {
    mockGetWorkerPageCatalog.mockRejectedValue(new Error('403'))
    mockCreateWorker.mockResolvedValue({ data: { data: worker({ id: 'w-5' }) } })
    render(<WorkerProfilesPanel canWrite />)

    fireEvent.click(await screen.findByText('新建工人档案'))
    await waitFor(() => expect(mockGetWorkerPageCatalog).toHaveBeenCalled())

    expect(screen.queryByTestId('worker-pages-picker')).not.toBeInTheDocument()
    // PIN / 工号 / 姓名三件套照旧可建号（菜单读不到不得挡住建号）
    fireEvent.change(screen.getByPlaceholderText(/W-1002/), { target: { value: 'W-1005' } })
    fireEvent.change(screen.getByPlaceholderText(/李四/), { target: { value: '孙八' } })
    fireEvent.change(screen.getByPlaceholderText(/位数字/), { target: { value: '246810' } })
    fireEvent.click(screen.getByText('创建'))

    await waitFor(() => {
      expect(mockCreateWorker).toHaveBeenCalledWith({
        workerNo: 'W-1005', name: '孙八', pin: '246810', workerPages: null,
      })
    })
  })

  it('⑨ 全部取消勾选 ⇒ 就地拦住、**不发请求**（空集在工人端会被读成「没读到权限 ⇒ 全开」，与意图相反）', async () => {
    render(<WorkerProfilesPanel canWrite />)

    fireEvent.click(await screen.findByText('新建工人档案'))
    fireEvent.change(screen.getByPlaceholderText(/W-1002/), { target: { value: 'W-1006' } })
    fireEvent.change(screen.getByPlaceholderText(/李四/), { target: { value: '周九' } })
    fireEvent.change(screen.getByPlaceholderText(/位数字/), { target: { value: '246810' } })
    for (const key of ['report', 'order', 'cut_calc', 'shipment']) {
      fireEvent.click(await screen.findByTestId(`worker-page-option-${key}`))
    }
    // 就地给一句人话（不是等 422 回来才说），并指路既有出口「停用」
    expect(screen.getByTestId('worker-pages-empty-hint')).toHaveTextContent(/停用/)
    fireEvent.click(screen.getByText('创建'))

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith(expect.stringContaining('至少要留一个页面')))
    expect(mockCreateWorker).not.toHaveBeenCalled()
  })

  it('⑨ 弹窗打开后才拿到页面目录 ⇒ 仍是「全勾 = 不限制」（不发空集）', async () => {
    let resolveConfig: (v: unknown) => void = () => {}
    mockGetWorkerPageCatalog.mockReturnValue(new Promise((resolve) => { resolveConfig = resolve }))
    mockCreateWorker.mockResolvedValue({ data: { data: worker({ id: 'w-7' }) } })
    render(<WorkerProfilesPanel canWrite />)

    // 配置还没回来就打开弹窗（真实网络下很常见）
    fireEvent.click(await screen.findByText('新建工人档案'))
    resolveConfig(catalog())
    await screen.findByTestId('worker-page-option-report')

    fireEvent.change(screen.getByPlaceholderText(/W-1002/), { target: { value: 'W-1007' } })
    fireEvent.change(screen.getByPlaceholderText(/李四/), { target: { value: '吴十' } })
    fireEvent.change(screen.getByPlaceholderText(/位数字/), { target: { value: '246810' } })
    fireEvent.click(screen.getByText('创建'))

    await waitFor(() => {
      expect(mockCreateWorker).toHaveBeenCalledWith({
        workerNo: 'W-1007', name: '吴十', pin: '246810', workerPages: null,
      })
    })
  })
})
