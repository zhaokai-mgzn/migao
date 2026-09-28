// @vitest-environment jsdom
// case_ids: HR-001, HR-002, UI-024
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
 */

const mockListWorkers = vi.fn()
const mockCreateWorker = vi.fn()
const mockSetWorkerStatus = vi.fn()

vi.mock('@/lib/api', () => ({
  workerApi: {
    listWorkers: (...a: unknown[]) => mockListWorkers(...a),
    createWorker: (...a: unknown[]) => mockCreateWorker(...a),
    setWorkerStatus: (...a: unknown[]) => mockSetWorkerStatus(...a),
  },
}))

import WorkerProfilesPanel from '@/components/employees/WorkerProfilesPanel'
import { markErrorToastShown } from '@/lib/api-error'

const okPage = (items: unknown[]) => ({ data: { data: { items, total: items.length } } })

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
    ;(toast.error as ReturnType<typeof vi.fn>).mockClear()
    mockListWorkers.mockResolvedValue(okPage([worker()]))
  })

  it('① 列表列出工人档案：工号 / 姓名 / 状态', async () => {
    render(<WorkerProfilesPanel canWrite />)

    expect(await screen.findByText('W-1001')).toBeInTheDocument()
    expect(screen.getByText('张三')).toBeInTheDocument()
    expect(mockListWorkers).toHaveBeenCalledWith(
      expect.objectContaining({ page: 1, size: 10 })
    )
  })

  it('① 工人与员工分得清：页面显式说明工人不进管理后台、无菜单权限', async () => {
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
      expect(mockCreateWorker).toHaveBeenCalledWith({ workerNo: 'W-1002', name: '李四', pin: '135791' })
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
})
