// case_ids: WH-009
//
// issue #7785：出库单页「仓位管理」—— 仓位档案的新建 / 编辑 / 启停 / 删除。
//
// 守六件事（每条都有后端同源判据）：
//   ① 清单显示仓位号 / 区域 / 三态（空闲 / 占用中 / 已停用），读失败 ≠ 空态（常驻错误 + 重试）；
//   ② 写动作受 `inbound:create` 门控（`canWrite=false` 时新建 / 编辑 / 启停 / 删除全部不可达）；
//   ③ 新建：仓位号必填，提交体把区域 / 区域名 / 备注一起带上；
//   ④ 占用中：编辑弹窗里仓位号禁用、行内删除禁用（在库成品与已贴标签认这个号）；
//   ⑤ 停用 / 启用走同一接口，只发 `status`（不碰别的字段）；
//   ⑥ 删除要二次确认；删除成功后重读清单。
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'

const mockLocations = vi.fn()
const mockCreate = vi.fn()
const mockUpdate = vi.fn()
const mockDelete = vi.fn()

vi.mock('@/lib/api', () => ({
  finishedGoodsApi: {
    locations: (...a: unknown[]) => mockLocations(...a),
    createLocation: (...a: unknown[]) => mockCreate(...a),
    updateLocation: (...a: unknown[]) => mockUpdate(...a),
    deleteLocation: (...a: unknown[]) => mockDelete(...a),
  },
}))

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

import WarehouseLocationPanel from '@/components/stock/WarehouseLocationPanel'

const freeRow = {
  id: 11,
  warehouseId: 9,
  zoneCode: 'A',
  zoneName: '成品区',
  binCode: 'A-01',
  status: 'active' as const,
  occupied: false,
  remark: null,
}

const occupiedRow = {
  id: 12,
  warehouseId: 9,
  zoneCode: 'A',
  zoneName: '成品区',
  binCode: 'A-02',
  status: 'active' as const,
  occupied: true,
  remark: '靠门',
}

const inactiveRow = {
  id: 13,
  warehouseId: 9,
  zoneCode: 'B',
  zoneName: '挂衣区',
  binCode: 'B-01',
  status: 'inactive' as const,
  occupied: false,
  remark: null,
}

beforeEach(() => {
  vi.clearAllMocks()
  mockLocations.mockResolvedValue({ data: { data: [freeRow, occupiedRow, inactiveRow] } })
  mockCreate.mockResolvedValue({ data: { data: freeRow } })
  mockUpdate.mockResolvedValue({ data: { data: freeRow } })
  mockDelete.mockResolvedValue({ data: {} })
})

describe('仓位管理清单（WH-009）', () => {
  it('显示仓位号 / 区域 / 三态（空闲 / 占用中 / 已停用）', async () => {
    render(<WarehouseLocationPanel canWrite refreshKey={0} />)

    expect(await screen.findByText('A-01')).toBeTruthy()
    expect(screen.getByText('A-02')).toBeTruthy()
    expect(screen.getByText('B-01')).toBeTruthy()
    expect(screen.getAllByText('成品区（A）').length).toBeGreaterThanOrEqual(2)
    expect(screen.getByText('挂衣区（B）')).toBeTruthy()
    expect(screen.getByText('空闲')).toBeTruthy()
    expect(screen.getByText('占用中')).toBeTruthy()
    expect(screen.getByText('已停用')).toBeTruthy()
    // 管理面要能看到停用仓位（includeInactive），否则无法重新启用
    expect(mockLocations).toHaveBeenCalledWith({ includeInactive: true })
  })

  it('读失败 ≠ 空态：常驻错误出口 + 重试再读', async () => {
    mockLocations.mockRejectedValueOnce(new Error('boom'))
    render(<WarehouseLocationPanel canWrite refreshKey={0} />)

    const alert = await screen.findByTestId('warehouse-locations-load-error')
    expect(alert.getAttribute('role')).toBe('alert')
    fireEvent.click(screen.getByTestId('warehouse-locations-load-error-retry'))
    await waitFor(() => expect(mockLocations).toHaveBeenCalledTimes(2))
  })

  it('没有仓位 ⇒ 空态 + 新建入口（不是错误）', async () => {
    mockLocations.mockResolvedValue({ data: { data: [] } })
    render(<WarehouseLocationPanel canWrite refreshKey={0} />)

    expect(await screen.findByTestId('warehouse-locations-empty')).toBeTruthy()
    expect(screen.getByTestId('warehouse-location-create-empty')).toBeTruthy()
    // 空态不再重复一个同名工具栏按钮（读图判定 2026-10-25：两个一模一样的「新建仓位」相距 ~100px）
    expect(screen.queryByTestId('warehouse-location-create')).toBeNull()
  })

  it('🔴 无 inbound:create ⇒ 只读：没有新建 / 编辑 / 启停 / 删除', async () => {
    render(<WarehouseLocationPanel canWrite={false} refreshKey={0} />)
    await screen.findByText('A-01')

    expect(screen.queryByTestId('warehouse-location-create')).toBeNull()
    expect(screen.queryByText('编辑')).toBeNull()
    expect(screen.queryByText('停用')).toBeNull()
  })
})

describe('新建 / 编辑仓位（WH-009）', () => {
  it('新建：仓位号必填；提交体带上区域 / 区域名 / 备注，成功后重读清单', async () => {
    render(<WarehouseLocationPanel canWrite refreshKey={0} />)
    await screen.findByText('A-01')

    fireEvent.click(screen.getByTestId('warehouse-location-create'))
    fireEvent.change(screen.getByTestId('warehouse-bin-code-input'), {
      target: { value: 'b-03' },
    })
    fireEvent.change(screen.getByTestId('warehouse-zone-code-input'), {
      target: { value: 'B' },
    })
    fireEvent.change(screen.getByTestId('warehouse-zone-name-input'), {
      target: { value: '挂衣区' },
    })
    fireEvent.change(screen.getByTestId('warehouse-remark-input'), {
      target: { value: '靠门' },
    })
    fireEvent.click(screen.getByTestId('warehouse-location-save'))

    await waitFor(() => expect(mockCreate).toHaveBeenCalledTimes(1))
    expect(mockCreate.mock.calls[0][0]).toEqual({
      binCode: 'b-03',
      zoneCode: 'B',
      zoneName: '挂衣区',
      remark: '靠门',
    })
    const { toast } = await import('sonner')
    expect(toast.success).toHaveBeenCalledWith(expect.stringContaining('已创建'))
    await waitFor(() => expect(mockLocations).toHaveBeenCalledTimes(2))
  })

  it('仓位号为空 ⇒ 前端先拦（不发请求）', async () => {
    render(<WarehouseLocationPanel canWrite refreshKey={0} />)
    await screen.findByText('A-01')

    fireEvent.click(screen.getByTestId('warehouse-location-create'))
    fireEvent.click(screen.getByTestId('warehouse-location-save'))

    const { toast } = await import('sonner')
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(expect.stringContaining('请填写仓位号')),
    )
    expect(mockCreate).not.toHaveBeenCalled()
  })

  it('🔴 占用中编辑：仓位号禁用，改备注可保存（不改号）', async () => {
    render(<WarehouseLocationPanel canWrite refreshKey={0} />)
    await screen.findByText('A-02')

    fireEvent.click(screen.getByTestId('warehouse-location-edit-12'))

    const binInput = screen.getByTestId('warehouse-bin-code-input') as HTMLInputElement
    expect(binInput.disabled).toBe(true)
    fireEvent.change(screen.getByTestId('warehouse-remark-input'), {
      target: { value: '靠近门口' },
    })
    fireEvent.click(screen.getByTestId('warehouse-location-save'))

    await waitFor(() => expect(mockUpdate).toHaveBeenCalledTimes(1))
    expect(mockUpdate.mock.calls[0][0]).toBe(12)
    expect(mockUpdate.mock.calls[0][1]).toEqual({
      binCode: 'A-02',
      zoneCode: 'A',
      zoneName: '成品区',
      remark: '靠近门口',
    })
  })

  it('空闲仓位可改号', async () => {
    render(<WarehouseLocationPanel canWrite refreshKey={0} />)
    await screen.findByText('A-01')

    fireEvent.click(screen.getByTestId('warehouse-location-edit-11'))
    fireEvent.change(screen.getByTestId('warehouse-bin-code-input'), {
      target: { value: 'A-09' },
    })
    fireEvent.click(screen.getByTestId('warehouse-location-save'))

    await waitFor(() => expect(mockUpdate).toHaveBeenCalledTimes(1))
    expect(mockUpdate.mock.calls[0][1]).toMatchObject({ binCode: 'A-09' })
  })
})

describe('启停 / 删除（WH-009）', () => {
  it('停用只发 status（不碰别的字段）', async () => {
    render(<WarehouseLocationPanel canWrite refreshKey={0} />)
    await screen.findByText('A-01')

    fireEvent.click(screen.getByTestId('warehouse-location-toggle-11'))

    await waitFor(() => expect(mockUpdate).toHaveBeenCalledWith(11, { status: 'inactive' }))
    const { toast } = await import('sonner')
    expect(toast.success).toHaveBeenCalledWith(expect.stringContaining('已停用'))
  })

  it('🔴 占用中的仓位删除按钮禁用（在库成品认这个号）', async () => {
    render(<WarehouseLocationPanel canWrite refreshKey={0} />)
    await screen.findByText('A-02')

    const deleteButton = screen.getByTestId('warehouse-location-delete-12') as HTMLButtonElement
    expect(deleteButton.disabled).toBe(true)
    expect(deleteButton.getAttribute('title')).toContain('不能删除')
  })

  it('空闲仓位删除要二次确认，确认后调用删除并重读', async () => {
    render(<WarehouseLocationPanel canWrite refreshKey={0} />)
    await screen.findByText('A-01')

    fireEvent.click(screen.getByTestId('warehouse-location-delete-11'))
    const dialog = await screen.findByRole('dialog', { name: '删除仓位' })
    expect(within(dialog).getByText('A-01')).toBeTruthy()

    fireEvent.click(screen.getByTestId('warehouse-location-delete-confirm'))
    await waitFor(() => expect(mockDelete).toHaveBeenCalledWith(11))
    await waitFor(() => expect(mockLocations).toHaveBeenCalledTimes(2))
  })
})
