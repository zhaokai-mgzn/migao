// case_ids: MC-217, MC-219
/**
 * 取号**能力位**判定（issue #8698 P0）。
 *
 * ## 本文件钉的是「能力位驱动 UI」这一条
 *
 * 判据 2 的红证形态：**注册表新增 / 删除一家承运商 ⇒ 设置页与发货页的能力位跟着变**。
 * 这里用纯函数（`@/lib/waybill`）证明：
 * - 给注册表加一家 `canCreate=true` 的承运商 ⇒ 该承运商的按钮判定变为可用（不是恒 false）；
 * - 把它从注册表删掉 ⇒ 同一家公司立刻退回手填（禁用 + 「请手填单号」）；
 * - 未登记 / 能力面读不到 ⇒ 手填（**fail-closed**：不编「可以取号」）。
 *
 * 另有一条**源码形态**判据：动词「取号」这条链上不许出现承运商名字面量
 * （硬编码 ⇒ 红）—— 名字只能来自服务端注册表。
 */
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import {
  MANUAL_CARRIER,
  carrierSummary,
  carriersOfType,
  emptyCapabilities,
  findCarrier,
  findCarrierByName,
  waybillCapabilityFor,
} from '@/lib/waybill'
import type { WaybillCapabilities, WaybillCarrier } from '@/types/waybill'

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

const caps = (carriers: WaybillCarrier[], configured: string | null = null): WaybillCapabilities => ({
  carriers: [MANUAL_CARRIER, ...carriers],
  configuredCarrier: configured,
  effectiveCarrier: carriers[0] ?? MANUAL_CARRIER,
  manualFallback: !(carriers[0]?.canCreate ?? false),
})

describe('判据 2：能力位来自注册表 —— 注册表增删 ⇒ 判定跟着变（硬编码 ⇒ 红）', () => {
  it('注册表里有这家且能取号 ⇒ 按钮可用（不是恒 false）', () => {
    const view = waybillCapabilityFor(caps([sf(true)], 'sf'), '顺丰速运')
    expect(view.canCreate).toBe(true)
    expect(view.mode).toBe('api')
    expect(view.hint).toContain('自动取号')
  })

  it('同一家从注册表里删掉 ⇒ 立刻退回手填（未登记即 manual）', () => {
    const withoutSf = caps([], null)
    const view = waybillCapabilityFor(withoutSf, '顺丰速运')
    expect(view.canCreate).toBe(false)
    expect(view.mode).toBe('manual')
    expect(view.carrier.code).toBe('manual')
    expect(view.hint).toContain('请手填单号')
  })

  it('注册表里有这家但没接入 ⇒ 禁用 + 说清「未接入取号」（不是笼统不可用）', () => {
    const view = waybillCapabilityFor(caps([sf(false)], 'sf'), '顺丰速运')
    expect(view.canCreate).toBe(false)
    expect(view.carrier.code).toBe('sf')
    expect(view.hint).toContain('未接入取号')
    expect(view.hint).toContain('顺丰速运')
  })

  it('新增一家（原先不存在）⇒ 设置页候选与能力摘要都多一条', () => {
    const before = caps([sf(false)], null)
    const added: WaybillCarrier = {
      code: 'zto',
      displayName: '中通快递',
      logisticsType: 'express',
      trackQueryCode: 'ZTO',
      canCreate: true,
      canCancel: false,
      canTrack: false,
      mode: 'api',
    }
    const after = caps([sf(false), added], null)

    expect(carriersOfType(before, 'express')).toHaveLength(1)
    expect(carriersOfType(after, 'express')).toHaveLength(2)
    expect(carriersOfType(after, 'express').map((c) => c.displayName)).toContain('中通快递')
    expect(carrierSummary(added)).toContain('已接入取号')
    expect(carrierSummary(sf(false))).toContain('未接入取号')
  })
})

describe('判据 4：manual 兜底 —— 读不到 / 未登记 ⇒ 手填（不编能力）', () => {
  it('能力面为 null（读失败 / 还没读）⇒ 全手填', () => {
    const view = waybillCapabilityFor(null, '任意承运商')
    expect(view.canCreate).toBe(false)
    expect(view.carrier.code).toBe('manual')
    expect(view.mode).toBe('manual')
  })

  it('能力面为空（接口回了空表）⇒ 全手填', () => {
    const empty = emptyCapabilities()
    expect(empty.manualFallback).toBe(true)
    expect(empty.effectiveCarrier.code).toBe('manual')
    expect(waybillCapabilityFor(empty, '').canCreate).toBe(false)
  })

  it('自定义承运商（词表外的名字）⇒ 手填，且不编一个注册表条目', () => {
    const view = waybillCapabilityFor(caps([sf(true)], 'sf'), '某某本地物流')
    expect(view.canCreate).toBe(false)
    expect(view.carrier).toBe(MANUAL_CARRIER)
  })

  it('按名字 / code 查找：找不到就是 undefined（不返回默认承运商）', () => {
    const c = caps([sf(true)], 'sf')
    expect(findCarrier(c, 'nope')).toBeUndefined()
    expect(findCarrierByName(c, '不存在物流')).toBeUndefined()
    const found = findCarrierByName(c, ' 顺丰速运 ')
    expect(found?.code).toBe('sf')
  })

  it('物流类型收敛：专线不出现在快递候选里', () => {
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
    const c = caps([sf(false), sja], null)
    expect(carriersOfType(c, 'express').map((x) => x.code)).toEqual(['sf'])
    expect(carriersOfType(c, 'logistics').map((x) => x.code)).toEqual(['sja'])
    expect(carriersOfType(c, null).map((x) => x.code)).toEqual(['sf', 'sja'])
  })
})

describe('判据 2b：取号链路上没有承运商名字面量（硬编码 ⇒ 红）', () => {
  /** 与注册表同字的名字（出现即说明有人把词表抄进了判定逻辑） */
  const CARRIER_NAMES = ['德邦快递', '顺丰速运', '中通快递', '圆通速递', '韵达快递', '申通快递', '四季安物流']

  const sources = [
    'src/lib/waybill.ts',
    'src/lib/api-waybill.ts',
    'src/app/(dashboard)/orders/[id]/ship/ShipOrder.tsx',
    'src/components/settings/LogisticsDomainPanel.tsx',
  ].map((rel) => ({ rel, text: readFileSync(join(process.cwd(), rel), 'utf8') }))

  it.each(sources)('$rel 里不出现任何承运商名字面量', ({ rel, text }) => {
    const hits = CARRIER_NAMES.filter((name) => text.includes(name))
    expect(hits, `${rel} 把承运商名写死了（能力位必须来自服务端注册表）`).toEqual([])
  })
})
