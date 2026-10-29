// case_ids: CU-009, UI-047

import { describe, it, expect } from 'vitest'
import {
  LOGISTICS_TYPES,
  LOGISTICS_COMPANIES,
  DEFAULT_LOGISTICS_TYPE,
  isLogisticsType,
  logisticsCompaniesFor,
  logisticsTypeLabel,
  describeLogisticsProfile,
  switchCarrier,
} from '@/lib/logistics'

/**
 * 物流口径单一真值（issue #4419）——客户管理「收货信息」卡片与发货页共用同一份词表。
 *
 * 这层看起来「只是常量」，但它承载两条会静默出错的约定：
 * ① 类型枚举值必须与后端列口径一致（`express` 快递 / `logistics` 物流专线，V47 列注释），
 *    写错值不会报错，只会让 order_logistics.logistics_type 变成未知值；
 * ② `describeLogisticsProfile` **缺值不得补默认值** —— 否则「客户没录过常用物流」会被
 *    渲染成「快递」，看起来像已配置（假信息比空白更坏）。
 */
describe('logistics 词表（issue #4419）', () => {
  it('物流类型枚举值与后端列口径一致（express/logistics）', () => {
    expect(LOGISTICS_TYPES.map((t) => t.value)).toEqual(['express', 'logistics'])
    expect(LOGISTICS_TYPES.map((t) => t.label)).toEqual(['快递', '物流/专线'])
  })

  it('常用承运商候选含原发货页 6 家 + 域文档点名的物流专线承运商', () => {
    // 发货页原有 6 家必须保留（E2E 断言默认值为「德邦快递」，顺序不可乱）
    expect(LOGISTICS_COMPANIES.slice(0, 6).map((c) => c.name)).toEqual([
      '德邦快递',
      '顺丰速运',
      '中通快递',
      '圆通速递',
      '韵达快递',
      '申通快递',
    ])
    expect(LOGISTICS_COMPANIES.map((c) => c.name)).toContain('四季安物流')
  })

  it('logisticsTypeLabel：已知值给中文，未知/空值回退「快递」（与列默认 express 一致）', () => {
    expect(logisticsTypeLabel('express')).toBe('快递')
    expect(logisticsTypeLabel('logistics')).toBe('物流/专线')
    expect(logisticsTypeLabel('')).toBe('快递')
    expect(logisticsTypeLabel(undefined)).toBe('快递')
    expect(logisticsTypeLabel(null)).toBe('快递')
    expect(logisticsTypeLabel('未知值')).toBe('快递')
  })

  it('describeLogisticsProfile：方式+公司都给时拼接，只给一个时只显示一个', () => {
    expect(describeLogisticsProfile('logistics', '四季安物流')).toBe('物流/专线 · 四季安物流')
    expect(describeLogisticsProfile('express', '顺丰速运')).toBe('快递 · 顺丰速运')
    expect(describeLogisticsProfile('logistics', '')).toBe('物流/专线')
    expect(describeLogisticsProfile(undefined, '四季安物流')).toBe('四季安物流')
  })

  it('describeLogisticsProfile：两者都缺返回空串（不编造「快递」默认值）', () => {
    expect(describeLogisticsProfile(undefined, undefined)).toBe('')
    expect(describeLogisticsProfile(null, null)).toBe('')
    expect(describeLogisticsProfile('', '   ')).toBe('')
  })
})

/**
 * 承运商候选按物流类型收敛（issue #8079）。
 *
 * 病根（真机复核）：`LOGISTICS_TYPES` 与 `LOGISTICS_COMPANIES` 原是**两套互不相关的词表** ——
 * 选「快递」照样能选「四季安物流」，选「物流/专线」照样全是快递公司；默认值又恰好是
 * `德邦快递`（快递）配「物流/专线」⇒ 「快递 + 德邦物流」这种自相矛盾的组合随手可填。
 * 用户 2026-10-29 裁定：「全链路都要区分」。
 */
describe('承运商候选按物流类型收敛（issue #8079）', () => {
  /** 词表里的全部承运商名（顺序 = 词表顺序） */
  const names = LOGISTICS_COMPANIES.map((c) => c.name)

  it('7 家承运商全部保留、各归一类：前 6 家快递、四季安物流是专线', () => {
    expect(names).toHaveLength(7)
    expect(LOGISTICS_COMPANIES.filter((c) => c.type === 'express').map((c) => c.name)).toEqual(
      names.slice(0, 6),
    )
    expect(LOGISTICS_COMPANIES.filter((c) => c.type === 'logistics').map((c) => c.name)).toEqual([
      '四季安物流',
    ])
  })

  it('选「快递」⇒ 候选不含专线公司；选「物流/专线」⇒ 候选不含任何快递公司', () => {
    expect(logisticsCompaniesFor('express')).toEqual(names.slice(0, 6))
    expect(logisticsCompaniesFor('express')).not.toContain('四季安物流')
    expect(logisticsCompaniesFor('logistics')).toEqual(['四季安物流'])
    expect(logisticsCompaniesFor('logistics')).not.toContain('顺丰速运')
    expect(logisticsCompaniesFor('logistics')).not.toContain('德邦快递')
  })

  it('未指定 / 未知类型 ⇒ 全量候选（档案面「未指定」不凭空缩小候选）', () => {
    expect(logisticsCompaniesFor('')).toEqual(names)
    expect(logisticsCompaniesFor(undefined)).toEqual(names)
    expect(logisticsCompaniesFor(null)).toEqual(names)
    expect(isLogisticsType('carrier-x')).toBe(false)
    expect(isLogisticsType('logistics')).toBe(true)
  })

  it('默认承运商 = 该类型第一家（后端列默认 express ⇒ 德邦快递；专线 ⇒ 四季安物流）', () => {
    expect(DEFAULT_LOGISTICS_TYPE).toBe('express')
    expect(logisticsCompaniesFor(DEFAULT_LOGISTICS_TYPE)[0]).toBe('德邦快递')
    expect(logisticsCompaniesFor('logistics')[0]).toBe('四季安物流')
  })

  it('从「快递-顺丰」切到「物流/专线」⇒ 落到专线第一家并给提示，不残留顺丰', () => {
    const next = switchCarrier('顺丰速运', 'logistics')
    expect(next.company).toBe('四季安物流')
    expect(next.notice).toContain('四季安物流')
    expect(next.notice).toContain('物流/专线')
  })

  it('反向同理：从「物流/专线-四季安物流」切到「快递」⇒ 落到快递第一家', () => {
    const next = switchCarrier('四季安物流', 'express')
    expect(next.company).toBe('德邦快递')
    expect(next.notice).not.toBeNull()
  })

  it('已在新类型里 ⇒ 不动、不提示（商家自己的选择不被覆盖）', () => {
    expect(switchCarrier('顺丰速运', 'express')).toEqual({ company: '顺丰速运', notice: null })
    expect(switchCarrier('四季安物流', 'logistics')).toEqual({
      company: '四季安物流',
      notice: null,
    })
  })

  it('词表之外的自定义承运商 ⇒ 不改写（词表只是候选，归属无从判断 —— 改它等于替商家丢数据）', () => {
    expect(switchCarrier('本地专线·老王', 'logistics')).toEqual({
      company: '本地专线·老王',
      notice: null,
    })
    expect(switchCarrier('本地专线·老王', 'express').company).toBe('本地专线·老王')
  })
})
