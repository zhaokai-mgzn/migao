// case_ids: MC-217
/**
 * 设置页「物流取号」域面板（issue #8698 P0；`/settings?domain=logistics`）。
 *
 * 判据（都能红）：
 * 1. **能力位来自服务端注册表**：面板逐行渲染服务端下发的承运商 + 它们的「能不能自动取号」
 *    （红证：把 `carrierSummary` 改成常量 ⇒ 判据 1 红）；
 * 2. **注册表增删 ⇒ 面板跟着变**：mock 里多一家 / 少一家，行数与文案同步
 *    （红证：在面板里写死一份承运商清单 ⇒ 判据 2 红）；
 * 3. **读失败 ≠ 全手填**：读不到时**不画**下拉与清单，只说明「读不到」
 *    （红证：把 catch 里的 `setReadError(true)` 删掉 ⇒ 面板会把「不知道」画成「全手填」，判据 3 红）；
 * 4. **写面**：改选即保存，空值 ⇒ `saveCarrier(null)`（= 回到全 manual）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { WaybillCapabilities, WaybillCarrier } from '@/types/waybill'

const mockGetCapabilities = vi.fn()
const mockSaveCarrier = vi.fn()
const mockToastSuccess = vi.fn()
const mockToastError = vi.fn()

vi.mock('@/lib/api-waybill', () => ({
  waybillApi: {
    getCapabilities: (...args: any[]) => mockGetCapabilities(...args),
    saveCarrier: (...args: any[]) => mockSaveCarrier(...args),
    createWaybill: vi.fn(),
  },
}))
vi.mock('sonner', () => ({
  toast: {
    success: (...args: any[]) => mockToastSuccess(...args),
    error: (...args: any[]) => mockToastError(...args),
  },
}))

import LogisticsDomainPanel from '@/components/settings/LogisticsDomainPanel'

const manual: WaybillCarrier = {
  code: 'manual',
  displayName: '手填单号',
  logisticsType: null,
  trackQueryCode: null,
  canCreate: false,
  canCancel: false,
  canTrack: false,
  mode: 'manual',
}

const sf = (canCreate: boolean): WaybillCarrier => ({
  code: 'sf',
  displayName: '顺丰速运',
  logisticsType: 'express',
  trackQueryCode: 'SF',
  canCreate,
  canCancel: false,
  canTrack: false,
  mode: canCreate ? 'api' : 'manual',
})

const sja: WaybillCarrier = {
  code: 'sja',
  displayName: '四季安物流',
  logisticsType: 'logistics',
  trackQueryCode: 'SJA56',
  canCreate: false,
  canCancel: false,
  canTrack: false,
  mode: 'manual',
}

function caps(carriers: WaybillCarrier[], configured: string | null = 'sf'): WaybillCapabilities {
  return {
    carriers: [manual, ...carriers],
    configuredCarrier: configured,
    effectiveCarrier: carriers[0] ?? manual,
    manualFallback: !(carriers[0]?.canCreate ?? false),
  }
}

describe('设置页物流取号域（issue #8698 P0）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('判据 1：逐行渲染服务端注册表 + 每家的取号能力（不是写死的清单）', async () => {
    mockGetCapabilities.mockResolvedValue({ data: { data: caps([sf(false), sja]) } })

    render(<LogisticsDomainPanel />)

    await screen.findByTestId('settings-logistics-carrier-sf')
    expect(screen.getByTestId('settings-logistics-capability-sf').textContent).toContain('未接入取号')
    expect(screen.getByTestId('settings-logistics-capability-sja').textContent).toContain('未接入取号')
    // 能力位为真时文案换掉（证明它不是常量）
    expect(screen.getByTestId('settings-logistics-capability-manual').textContent).toContain('手填单号')
  })

  it('判据 1b：能力位为 true ⇒ 该行显示「已接入取号」', async () => {
    mockGetCapabilities.mockResolvedValue({ data: { data: caps([sf(true)]) } })

    render(<LogisticsDomainPanel />)

    await screen.findByTestId('settings-logistics-carrier-sf')
    expect(screen.getByTestId('settings-logistics-capability-sf').textContent).toContain('已接入取号')
  })

  it('判据 2：注册表增删 ⇒ 面板行跟着变（多一家就多一行，少一家就少一行）', async () => {
    mockGetCapabilities.mockResolvedValue({ data: { data: caps([sf(false), sja]) } })
    const first = render(<LogisticsDomainPanel />)
    await first.findByTestId('settings-logistics-carrier-sja')
    expect(first.queryByTestId('settings-logistics-carrier-zto')).toBeNull()
    first.unmount()

    const zto: WaybillCarrier = {
      code: 'zto',
      displayName: '中通快递',
      logisticsType: 'express',
      trackQueryCode: 'ZTO',
      canCreate: true,
      canCancel: false,
      canTrack: false,
      mode: 'api',
    }
    mockGetCapabilities.mockResolvedValue({ data: { data: caps([sf(false), sja, zto]) } })
    render(<LogisticsDomainPanel />)

    const row = await screen.findByTestId('settings-logistics-carrier-zto')
    expect(row.textContent).toContain('中通快递')
    expect(screen.getByTestId('settings-logistics-capability-zto').textContent).toContain('已接入取号')
  })

  it('判据 3：读失败 ⇒ 只说「读不到」，不画成「全手填」', async () => {
    mockGetCapabilities.mockRejectedValue(new Error('boom'))

    render(<LogisticsDomainPanel />)

    await screen.findByTestId('settings-logistics-read-error')
    expect(screen.queryByTestId('settings-logistics-carrier-select')).toBeNull()
    expect(screen.getByTestId('settings-logistics-read-error').textContent).toContain('不代表「没有配置」')
  })

  it('判据 4：改选即保存（空值 ⇒ 全手填）', async () => {
    mockGetCapabilities.mockResolvedValue({ data: { data: caps([sf(false), sja]) } })
    mockSaveCarrier.mockResolvedValue({ data: { data: caps([sja], 'sja') } })

    render(<LogisticsDomainPanel />)

    const select = await screen.findByTestId('settings-logistics-carrier-select')
    await userEvent.selectOptions(select, 'sja')
    await waitFor(() => expect(mockSaveCarrier).toHaveBeenCalledWith('sja'))
    await waitFor(() => expect(mockToastSuccess).toHaveBeenCalledWith(expect.stringContaining('四季安物流')))

    await userEvent.selectOptions(select, '')
    await waitFor(() => expect(mockSaveCarrier).toHaveBeenLastCalledWith(null))
  })
})
