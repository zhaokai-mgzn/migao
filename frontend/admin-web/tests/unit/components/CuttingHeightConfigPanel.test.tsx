// @vitest-environment jsdom
// case_ids: PG-045
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

/**
 * 裁高配置面板（母单 #5161）——四条判据，每条都能红：
 *   ① 打开即读 `GET /api/admin/production/cutting-height-config`，并把 `source` 画出来
 *      （`default` ⇒ 「当前使用系统默认值」—— **不把默认值伪装成商家配置**）；
 *   ② 保存走 **PUT 全量替换**（items + rounding 一起发，不发明「部分更新」）；
 *   ③ 预演走 `POST …/preview`（命中口径**由服务端判**，前端不自己比名字），
 *      并把「命中但未配置取值」的项**显式**画出来（壁达的「画线」形态）；
 *   ④ 保存失败**不冒充成功**（不弹成功 toast、来源徽标不变）。
 */

const mockGet = vi.fn()
const mockUpdate = vi.fn()
const mockPreview = vi.fn()

vi.mock('@/lib/api', () => ({
  cuttingHeightApi: {
    get: (...a: unknown[]) => mockGet(...a),
    update: (...a: unknown[]) => mockUpdate(...a),
    preview: (...a: unknown[]) => mockPreview(...a),
  },
}))

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

import { CuttingHeightConfigPanel } from '@/components/production/CuttingHeightConfigPanel'
import { toast } from 'sonner'

const configResponse = (source: string) => ({
  data: {
    data: {
      source,
      config: {
        items: [
          {
            key: 'butie',
            name: '布贴',
            value: 0.015,
            direction: 'add',
            height_join: false,
            hit: { trigger_kind: 'option', trigger_value: '布贴', position: '布帘' },
            hit_expr: null,
            enabled: true,
            order: 10,
          },
          {
            key: 'huaxian',
            name: '画线',
            value: null,
            direction: 'add',
            height_join: false,
            hit: { trigger_kind: 'option', trigger_value: '画线', position: null },
            hit_expr: null,
            enabled: true,
            order: 20,
          },
        ],
        rounding: { mode: 'half_up', digits: 3 },
      },
    },
  },
})

describe('CuttingHeightConfigPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGet.mockResolvedValue(configResponse('default'))
  })

  it('① 打开即读配置，并把「当前使用系统默认值」画出来（不伪装成商家配置）', async () => {
    render(<CuttingHeightConfigPanel />)

    await waitFor(() => expect(screen.getByTestId('cutting-height-source')).toBeTruthy())
    expect(mockGet).toHaveBeenCalledTimes(1)
    expect(screen.getByTestId('cutting-height-source').textContent).toBe('当前使用系统默认值')
    expect((screen.getByLabelText('名称-0') as HTMLInputElement).value).toBe('布贴')
    expect((screen.getByLabelText('触发值-0') as HTMLInputElement).value).toBe('布贴')
    // 有项无值：取值输入框留空（不是 0）
    expect((screen.getByLabelText('取值-1') as HTMLInputElement).value).toBe('')
  })

  it('② 保存 = PUT 全量替换（items 与 rounding 一起发）', async () => {
    mockUpdate.mockResolvedValue(configResponse('stored'))
    render(<CuttingHeightConfigPanel />)
    await waitFor(() => expect(screen.getByTestId('cutting-height-save')).toBeTruthy())

    fireEvent.click(screen.getByTestId('cutting-height-save'))

    await waitFor(() => expect(mockUpdate).toHaveBeenCalledTimes(1))
    const body = mockUpdate.mock.calls[0][0] as { items: unknown[]; rounding: unknown }
    expect(body.items).toHaveLength(2)
    expect(body.rounding).toEqual({ mode: 'half_up', digits: 3 })
    expect(toast.success).toHaveBeenCalled()
  })

  it('③ 预演：命中口径由服务端判；「命中但未配置取值」显式画出', async () => {
    mockPreview.mockResolvedValue({
      data: {
        data: {
          source: 'default',
          base: 2.92,
          cutting_height: 2.935,
          rounding: { mode: 'half_up', digits: 3 },
          hits: [{ key: 'butie', name: '布贴', value: 0.015, direction: 'add', height_join: false }],
          misses: [{ key: 'huaxian', name: '画线', reason: 'unresolved' }],
        },
      },
    })
    render(<CuttingHeightConfigPanel />)
    await waitFor(() => expect(screen.getByTestId('cutting-height-preview')).toBeTruthy())

    fireEvent.change(screen.getByLabelText('预演成品高'), { target: { value: '2.92' } })
    fireEvent.change(screen.getByLabelText('预演特殊选项'), { target: { value: '布贴, 画线' } })
    fireEvent.click(screen.getByTestId('cutting-height-preview'))

    await waitFor(() => expect(screen.getByTestId('cutting-height-preview-result')).toBeTruthy())
    expect(mockPreview.mock.calls[0][0]).toMatchObject({
      position: '布帘',
      finished_height: '2.92',
      special_options: ['布贴', '画线'],
    })
    const result = screen.getByTestId('cutting-height-preview-result')
    expect(result.textContent).toContain('2.935')
    expect(result.textContent).toContain('未配置取值')
  })

  it('④ 保存失败不冒充成功：不弹成功 toast，来源徽标不变', async () => {
    mockUpdate.mockRejectedValue(new Error('boom'))
    render(<CuttingHeightConfigPanel />)
    await waitFor(() => expect(screen.getByTestId('cutting-height-save')).toBeTruthy())

    fireEvent.click(screen.getByTestId('cutting-height-save'))

    await waitFor(() => expect(toast.error).toHaveBeenCalled())
    expect(toast.success).not.toHaveBeenCalled()
    expect(screen.getByTestId('cutting-height-source').textContent).toBe('当前使用系统默认值')
  })
})
