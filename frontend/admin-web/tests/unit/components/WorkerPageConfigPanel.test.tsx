// @vitest-environment jsdom
// case_ids: PG-045
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

/**
 * 工人端页面开关面板（V141，母单 #5161）—— 四条判据，每条都能红：
 *   ① 打开即读 `GET /api/admin/worker-page-config`，并把读面的**页面清单与勾选态**画出来
 *      （页面名与键**来自服务端** `labels`，前端不维护第二份词表）；
 *   ② `source='default'` ⇒ 显式标「未配置（正在用默认值 = 全部页面都开）」——
 *      **不把默认值伪装成商家配置**；
 *   ③ 保存走 **PUT 全量替换**（把当前勾选的页面集整体发出去，不发明「部分更新」）；
 *   ④ 面板把「页面开关 ≠ 权限」这句话**显式印出来**（商家最容易误读的那件事），
 *      且保存失败时把服务端**逐条理由**贴出来、不冒充成功。
 */

const mockGet = vi.fn()
const mockUpdate = vi.fn()

vi.mock('@/lib/api', () => ({
  workerPageConfigApi: {
    get: (...a: unknown[]) => mockGet(...a),
    update: (...a: unknown[]) => mockUpdate(...a),
  },
}))

import { WorkerPageConfigPanel } from '@/components/settings/WorkerPageConfigPanel'

const LABELS = { report: '报工', order: '订单', cut_calc: '裁高计算器', shipment: '发货' }

const readResponse = (source: string, pages: string[]) => ({
  data: { data: { source, pages, labels: LABELS } },
})

describe('WorkerPageConfigPanel 工人端页面开关（V141 / 母单 #5161）', () => {
  beforeEach(() => {
    mockGet.mockReset()
    mockUpdate.mockReset()
  })

  it('① 打开即读读面，页面清单与勾选态由服务端 labels/pages 决定', async () => {
    mockGet.mockResolvedValue(readResponse('stored', ['report', 'shipment']))

    render(<WorkerPageConfigPanel />)

    await waitFor(() => expect(screen.getByText('报工')).toBeTruthy())
    expect(screen.getByText('订单')).toBeTruthy()
    expect(screen.getByText('裁高计算器')).toBeTruthy()
    expect(screen.getByText('发货')).toBeTruthy()
    expect(mockGet).toHaveBeenCalledTimes(1)

    const report = screen.getByTestId('worker-page-report').querySelector('input') as HTMLInputElement
    const order = screen.getByTestId('worker-page-order').querySelector('input') as HTMLInputElement
    expect(report.checked).toBe(true)
    expect(order.checked).toBe(false)
  })

  it('② source=default ⇒ 显式标「未配置（正在用默认值）」', async () => {
    mockGet.mockResolvedValue(readResponse('default', ['report', 'order', 'cut_calc', 'shipment']))

    render(<WorkerPageConfigPanel />)

    await waitFor(() => expect(screen.getByTestId('worker-page-config-default')).toBeTruthy())
    expect(screen.getByTestId('worker-page-config-default').textContent).toContain('默认值')
  })

  it('③ 保存走 PUT 全量替换：发**当前勾选的整个页面集**', async () => {
    mockGet.mockResolvedValue(readResponse('stored', ['report', 'order']))
    mockUpdate.mockResolvedValue(readResponse('stored', ['report']))

    render(<WorkerPageConfigPanel />)
    await waitFor(() => expect(screen.getByTestId('worker-page-order')).toBeTruthy())

    fireEvent.click(screen.getByTestId('worker-page-order').querySelector('input')!)
    fireEvent.click(screen.getByText('保存'))

    await waitFor(() => expect(mockUpdate).toHaveBeenCalledTimes(1))
    expect(mockUpdate).toHaveBeenCalledWith({ pages: ['report'] })
    await waitFor(() => expect(screen.getByTestId('worker-page-config-saved')).toBeTruthy())
  })

  it('④ 面板显式声明「页面开关 ≠ 权限」', async () => {
    mockGet.mockResolvedValue(readResponse('default', []))

    render(<WorkerPageConfigPanel />)
    await waitFor(() => expect(screen.getByTestId('worker-page-config')).toBeTruthy())

    const text = screen.getByTestId('worker-page-config').textContent ?? ''
    expect(text).toContain('不代表权限')
    expect(text).toContain('进不了管理后台')
  })

  it('⑤ 保存失败（422）⇒ 贴出服务端逐条理由，不冒充成功', async () => {
    mockGet.mockResolvedValue(readResponse('stored', ['report']))
    mockUpdate.mockRejectedValue({
      response: {
        data: {
          error: {
            message: '工人端页面配置有 1 处不合法',
            details: [{ field: 'pages[1]', message: '不是工人端页面键：stock' }],
          },
        },
      },
    })

    render(<WorkerPageConfigPanel />)
    await waitFor(() => expect(screen.getByTestId('worker-page-report')).toBeTruthy())

    fireEvent.click(screen.getByText('保存'))

    await waitFor(() => expect(screen.getByTestId('worker-page-config-error')).toBeTruthy())
    // 2026-10-10（issue #6663）：判据面**只收紧不放宽** —— 服务端**语义**照旧贴出来
    //（「不是工人端页面键」+ 哪个值不行），但**字段名 `pages[1]` 不上屏**（§31 P3 不摆内部标识）。
    expect(screen.getByTestId('worker-page-config-error').textContent).toContain('不是工人端页面键')
    expect(screen.getByTestId('worker-page-config-error').textContent).toContain('stock')
    expect(screen.getByTestId('worker-page-config-error').textContent).not.toContain('pages[')
    expect(screen.queryByTestId('worker-page-config-saved')).toBeNull()
  })

  it('⑤b 保存失败（422）⇒ 字段名与 JSON 示例都不上屏，但**逐条理由**一条不少（issue #6663）', async () => {
    mockGet.mockResolvedValue(readResponse('stored', ['report', 'shipment']))
    mockUpdate.mockRejectedValue({
      response: {
        data: {
          error: {
            message: '工人端页面配置有 2 处不合法',
            details: [
              // 服务端原文形态（`WorkerPageConfigService` 的 422）：字段名 + JSON 示例
              { field: 'pages', message: '必须是数组（如 ["report","order"]）' },
              { field: 'pages[0]', message: '不是工人端页面键：stock（合法页面键：[report, order]）' },
            ],
          },
        },
      },
    })

    render(<WorkerPageConfigPanel />)
    await waitFor(() => expect(screen.getByTestId('worker-page-report')).toBeTruthy())
    fireEvent.click(screen.getByText('保存'))
    await waitFor(() => expect(screen.getByTestId('worker-page-config-error')).toBeTruthy())

    const text = screen.getByTestId('worker-page-config-error').textContent ?? ''
    // ① 逐条理由仍在（没有静默丢弃被拒的键）
    expect(text).toContain('必须是数组')
    expect(text).toContain('不是工人端页面键')
    // ② 内部标识与代码示例不上屏
    expect(text).not.toContain('pages')
    expect(text).not.toContain('"report"')
    expect(text).not.toContain('["')
  })
})
