// case_ids: WH-010
//
// issue #7791：仓位管理的水位列 + 区域容量 + 批量建号。
//
// 守五件事（后端同源判据）：
//   ① 水位 = 在库件数 / 容量；满仓状态是「已满」，不是「占用中」；
//   ② 批量建号：数字区间 ⇒ A-01…A-20，已存在的跳过；默认从本区最大号 +1 起；
//   ③ 区间 / 容量前端先拦（不发请求）；
//   ④ 容量按区域统一：单仓新建 / 编辑都把 capacity 带上；
//   ⑤ 空态也能进批量建号。
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

const mockLocations = vi.fn()
const mockCreate = vi.fn()
const mockUpdate = vi.fn()
const mockDelete = vi.fn()
const mockBatch = vi.fn()

vi.mock('@/lib/api', () => ({
  finishedGoodsApi: {
    locations: (...a: unknown[]) => mockLocations(...a),
    createLocation: (...a: unknown[]) => mockCreate(...a),
    batchCreateLocations: (...a: unknown[]) => mockBatch(...a),
    updateLocation: (...a: unknown[]) => mockUpdate(...a),
    deleteLocation: (...a: unknown[]) => mockDelete(...a),
  },
}))

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

import WarehouseLocationPanel from '@/components/stock/WarehouseLocationPanel'

const rows = [
  {
    id: 11,
    warehouseId: 9,
    zoneCode: 'A',
    zoneName: '成品区',
    binCode: 'A-01',
    status: 'active' as const,
    occupied: true,
    capacity: 10,
    inStockCount: 3,
    remark: null,
  },
  {
    id: 12,
    warehouseId: 9,
    zoneCode: 'A',
    zoneName: '成品区',
    binCode: 'A-02',
    status: 'active' as const,
    occupied: true,
    capacity: 10,
    inStockCount: 10,
    remark: null,
  },
  {
    id: 13,
    warehouseId: 9,
    zoneCode: 'A',
    zoneName: '成品区',
    binCode: 'A-03',
    status: 'active' as const,
    occupied: false,
    capacity: 10,
    inStockCount: 0,
    remark: null,
  },
]

beforeEach(() => {
  vi.clearAllMocks()
  mockLocations.mockResolvedValue({ data: { data: rows } })
  mockCreate.mockResolvedValue({ data: { data: rows[0] } })
  mockUpdate.mockResolvedValue({ data: { data: rows[0] } })
  mockBatch.mockResolvedValue({
    data: { data: { created: 17, skipped: 3, fromCode: 'A-01', toCode: 'A-20', capacity: 10 } },
  })
  mockDelete.mockResolvedValue({ data: {} })
})

describe('仓位水位 / 批量建号（WH-010）', () => {
  it('水位列显示在库件数 / 容量；满仓 = 已满，部分占用 = 占用中，空闲 = 空闲', async () => {
    render(<WarehouseLocationPanel canWrite refreshKey={0} />)
    await screen.findByTestId('warehouse-location-water-11')

    expect(screen.getByTestId('warehouse-location-water-11')).toHaveTextContent('3 / 10')
    expect(screen.getByTestId('warehouse-location-water-12')).toHaveTextContent('10 / 10')
    expect(screen.getByTestId('warehouse-location-water-13')).toHaveTextContent('0 / 10')
    expect(screen.getByText('已满')).toBeTruthy()
    expect(screen.getByText('占用中')).toBeTruthy()
    expect(screen.getByText('空闲')).toBeTruthy()
  })

  it('批量新建：默认从本区最大号 +1 起，区间 A 1~20 ⇒ 调用批量接口并提示新建/跳过', async () => {
    render(<WarehouseLocationPanel canWrite refreshKey={0} />)
    await screen.findByText('A-01')

    fireEvent.click(screen.getByTestId('warehouse-location-batch'))
    // 默认：A 区最大号 A-03 ⇒ from=4 / to=23
    expect((screen.getByTestId('warehouse-batch-from') as HTMLInputElement).value).toBe('4')
    fireEvent.change(screen.getByTestId('warehouse-batch-from'), { target: { value: '1' } })
    fireEvent.change(screen.getByTestId('warehouse-batch-to'), { target: { value: '20' } })

    expect(screen.getByTestId('warehouse-batch-preview').textContent).toContain('A-01 ~ A-20')
    expect(screen.getByTestId('warehouse-batch-preview').textContent).toContain('3 个已存在')

    fireEvent.click(screen.getByTestId('warehouse-batch-submit'))

    await waitFor(() =>
      expect(mockBatch).toHaveBeenCalledWith({
        zoneCode: 'A',
        zoneName: '成品区',
        numberFrom: 1,
        numberTo: 20,
        capacity: 10,
      }),
    )
    const { toast } = await import('sonner')
    expect(toast.success).toHaveBeenCalledWith(expect.stringContaining('已新建 17 个'))
    expect(toast.success).toHaveBeenCalledWith(expect.stringContaining('跳过 3 个已存在'))
    await waitFor(() => expect(mockLocations).toHaveBeenCalledTimes(2))
  })

  it('批量区间倒置 ⇒ 前端先拦（不发请求）', async () => {
    render(<WarehouseLocationPanel canWrite refreshKey={0} />)
    await screen.findByText('A-01')
    fireEvent.click(screen.getByTestId('warehouse-location-batch'))
    fireEvent.change(screen.getByTestId('warehouse-batch-from'), { target: { value: '5' } })
    fireEvent.change(screen.getByTestId('warehouse-batch-to'), { target: { value: '2' } })
    fireEvent.click(screen.getByTestId('warehouse-batch-submit'))

    const { toast } = await import('sonner')
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(expect.stringContaining('结束编号不能小于起始编号')),
    )
    expect(mockBatch).not.toHaveBeenCalled()
  })

  it('批量全部已存在 ⇒ 提示「都已存在」，不报错', async () => {
    mockBatch.mockResolvedValue({
      data: { data: { created: 0, skipped: 20, fromCode: 'A-01', toCode: 'A-20', capacity: 10 } },
    })
    render(<WarehouseLocationPanel canWrite refreshKey={0} />)
    await screen.findByText('A-01')
    fireEvent.click(screen.getByTestId('warehouse-location-batch'))
    fireEvent.change(screen.getByTestId('warehouse-batch-from'), { target: { value: '1' } })
    fireEvent.change(screen.getByTestId('warehouse-batch-to'), { target: { value: '20' } })
    fireEvent.click(screen.getByTestId('warehouse-batch-submit'))

    const { toast } = await import('sonner')
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith(expect.stringContaining('都已存在')),
    )
    expect(toast.error).not.toHaveBeenCalled()
  })

  it('新建仓位带上容量（区域统一）', async () => {
    render(<WarehouseLocationPanel canWrite refreshKey={0} />)
    await screen.findByText('A-01')
    fireEvent.click(screen.getByTestId('warehouse-location-create'))
    fireEvent.change(screen.getByTestId('warehouse-bin-code-input'), { target: { value: 'A-04' } })
    fireEvent.change(screen.getByTestId('warehouse-capacity-input'), { target: { value: '20' } })
    fireEvent.click(screen.getByTestId('warehouse-location-save'))

    await waitFor(() =>
      expect(mockCreate).toHaveBeenCalledWith(expect.objectContaining({ binCode: 'A-04', capacity: 20 })),
    )
  })

  it('编辑仓位改容量 ⇒ 提交 capacity（服务端同步本区）', async () => {
    render(<WarehouseLocationPanel canWrite refreshKey={0} />)
    await screen.findByText('A-01')
    fireEvent.click(screen.getByTestId('warehouse-location-edit-11'))
    expect((screen.getByTestId('warehouse-capacity-input') as HTMLInputElement).value).toBe('10')
    fireEvent.change(screen.getByTestId('warehouse-capacity-input'), { target: { value: '8' } })
    fireEvent.click(screen.getByTestId('warehouse-location-save'))

    await waitFor(() =>
      expect(mockUpdate.mock.calls[0][1]).toMatchObject({ capacity: 8 }),
    )
  })

  it('空态也能批量新建（不要求先有仓位）', async () => {
    mockLocations.mockResolvedValue({ data: { data: [] } })
    render(<WarehouseLocationPanel canWrite refreshKey={0} />)
    await screen.findByTestId('warehouse-locations-empty')

    fireEvent.click(screen.getByTestId('warehouse-location-batch-empty'))
    expect(screen.getByRole('dialog', { name: '批量新建仓位' })).toBeTruthy()
    expect((screen.getByTestId('warehouse-batch-from') as HTMLInputElement).value).toBe('1')
    expect((screen.getByTestId('warehouse-batch-to') as HTMLInputElement).value).toBe('20')
  })
})
