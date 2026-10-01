// case_ids: PR-062
//
// 批次建账/初始化入口（V118 / issue #5153）—— **前端**动线：
//   ① 单条录入：来源选「期初建账」⇒ 出现「旧系统批次号」列、**0.5 米的实物尾料能提交**
//      —— 🔴 该动线随建单入口一起**迁到独立整页** `/inbound-orders/new`（issue #5844），
//      判据落在 `tests/unit/pages/inbound-orders-new.test.tsx`（**一条未弱化**，只是换了落点）；
//   ② Excel 批量（本文件；仍在列表页的弹窗里）：模板下载 + 上传 + 幂等键（导入标识）
//      + **逐行校验报告**渲染。
//   ⚠️ 判据本体在 `src/lib/stock-quantity.ts`（下限 > 0）与后端 admin-api；
//   本文件守的是「它们**确实被接进了这条动线**」—— 前端不接线，后端再对也没用。
//   后端侧判据：backend/admin-api/src/test/java/com/migao/admin/service/
//   InboundOrderServiceTest.java（PR-060）、OpeningRegisterImportServiceTest.java（PR-060）、
//   tests/unit_ci_workflows/test_inbound_opening_register.py（PR-060，真 PG）。
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

const mockList = vi.fn()
const mockDetail = vi.fn()
const mockPost = vi.fn()
const mockCancel = vi.fn()
const mockOpeningImport = vi.fn()
const mockOpeningTemplate = vi.fn()

vi.mock('@/lib/api', () => ({
  inboundOrderApi: {
    list: (...a: unknown[]) => mockList(...a),
    detail: (...a: unknown[]) => mockDetail(...a),
    create: vi.fn(),
    post: (...a: unknown[]) => mockPost(...a),
    cancel: (...a: unknown[]) => mockCancel(...a),
    openingImport: (...a: unknown[]) => mockOpeningImport(...a),
    openingTemplate: (...a: unknown[]) => mockOpeningTemplate(...a),
  },
  productApi: {
    getProducts: vi.fn(),
    getProduct: vi.fn(),
  },
}))

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

import InboundOrdersPage from '@/app/(dashboard)/inbound-orders/page'

const listRow = {
  id: 'o-1',
  inboundNo: 'RK-20260924-0301',
  inboundDate: '2026-09-24',
  supplier: '柯桥××布行',
  warehouse: '一号仓',
  status: 'draft' as const,
  totalAmount: 6.25,
  itemCount: 1,
  totalQuantity: 0.5,
}

/** 逐行报告：一行通过、一行 2.755 被拒 —— 与后端「全或无」语义一致（created=false） */
const failedReport = {
  importRunId: 'opening-20260924-abc',
  inboundNo: null,
  orderId: null,
  status: null,
  created: false,
  total: 2,
  okCount: 1,
  failCount: 1,
  message: '共 2 行，1 行未通过校验 ⇒ **未建账**（一行都没写、库存一分未动）—— 按下面逐行原因改好后，用**同一次导入标识**重跑即可',
  rows: [
    { rowNo: 2, skuCode: 'HUOHAO-01', quantity: 0.5, dyeLot: '缸A-8891', legacyBatchNo: 'OLD-2024-0001', ok: true, message: null },
    { rowNo: 3, skuCode: 'HUOHAO-02', quantity: 2.755, dyeLot: null, legacyBatchNo: null, ok: false, message: '第 3 行剩余米数 最多支持 1 位小数（库存按 0.1 米粒度记账），当前值 2.755 有 2 位小数' },
  ],
}

describe('批次建账入口（V118 / issue #5153，PR-062）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockList.mockResolvedValue({ data: { data: [listRow] } })
  })

  it('批量导入：下载模板 + 上传 + 幂等键 ⇒ 逐行校验报告逐行渲染（失败行给原因）', async () => {
    mockOpeningTemplate.mockResolvedValue({ data: new Blob(['x']) })
    mockOpeningImport.mockResolvedValue({ data: { data: failedReport } })
    // jsdom 没有 createObjectURL
    ;(URL as unknown as { createObjectURL: () => string }).createObjectURL = () => 'blob:mock'
    ;(URL as unknown as { revokeObjectURL: () => void }).revokeObjectURL = () => {}

    render(<InboundOrdersPage />)
    await screen.findByText('RK-20260924-0301')

    fireEvent.click(screen.getByRole('button', { name: /期初建账导入/ }))
    fireEvent.click(screen.getByRole('button', { name: /下载模板/ }))
    await waitFor(() => expect(mockOpeningTemplate).toHaveBeenCalledTimes(1))

    // 导入标识（幂等键）在打开弹窗时就生成好了 —— 重跑同一份文件时用户不必改它
    const runIdInput = screen.getByLabelText('导入标识') as HTMLInputElement
    expect(runIdInput.value).not.toBe('')

    const file = new File(['x'], 'opening.xlsx', {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    })
    fireEvent.change(screen.getByLabelText('选择建账文件'), { target: { files: [file] } })
    fireEvent.click(screen.getByRole('button', { name: /开始导入/ }))

    await waitFor(() => expect(mockOpeningImport).toHaveBeenCalledTimes(1))
    // 幂等键**随文件一起**提交（没有它就不许上批量导入）
    expect(mockOpeningImport.mock.calls[0][0]).toBe(file)
    expect(mockOpeningImport.mock.calls[0][1]).toBe(runIdInput.value)

    // 逐行报告：通过的显示「通过」、不通过的显示**可行动原因**（含行号与位数）
    expect(await screen.findByText('通过')).toBeInTheDocument()
    expect(
      screen.getByText(/第 3 行剩余米数 最多支持 1 位小数/),
    ).toBeInTheDocument()
    expect(screen.getByText(/未建账/)).toBeInTheDocument()
    // 未建账 ⇒ 不刷新列表（没有任何东西被写进去）
    const { toast } = await import('sonner')
    expect(toast.error).toHaveBeenCalledWith(expect.stringContaining('未建账'))
  })

  it('批量导入：幂等命中（created=false 且无失败行）⇒ 提示「已建过账」，不当作失败', async () => {
    mockOpeningImport.mockResolvedValue({
      data: {
        data: {
          ...failedReport,
          created: false,
          inboundNo: 'RK-20260924-0301',
          status: 'posted',
          okCount: 2,
          failCount: 0,
          message: '这次导入运行已经建过账（单号 RK-20260924-0301）—— 幂等命中：**没有**重复建单、**没有**重复加库存',
          rows: [],
        },
      },
    })

    render(<InboundOrdersPage />)
    await screen.findByText('RK-20260924-0301')
    fireEvent.click(screen.getByRole('button', { name: /期初建账导入/ }))
    const file = new File(['x'], 'opening.xlsx')
    fireEvent.change(screen.getByLabelText('选择建账文件'), { target: { files: [file] } })
    fireEvent.click(screen.getByRole('button', { name: /开始导入/ }))

    await waitFor(() => {
      expect(mockOpeningImport).toHaveBeenCalledTimes(1)
    })
    const { toast } = await import('sonner')
    expect(toast.success).toHaveBeenCalledWith(
      expect.stringContaining('已经建过账'),
    )
    expect(toast.error).not.toHaveBeenCalled()
  })

  it('批量导入：没选文件就点导入 ⇒ 拦住（不调接口）', async () => {
    render(<InboundOrdersPage />)
    await screen.findByText('RK-20260924-0301')
    fireEvent.click(screen.getByRole('button', { name: /期初建账导入/ }))
    fireEvent.click(screen.getByRole('button', { name: /开始导入/ }))

    expect(mockOpeningImport).not.toHaveBeenCalled()
    const { toast } = await import('sonner')
    expect(toast.error).toHaveBeenCalledWith(expect.stringContaining('请先选择'))
  })
})
