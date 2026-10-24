// case_ids: PG-091
//
// 整卷布料单「出库」配置页人话（issue #7523，用户裁定 2026-10-23）
// —— 卖布单的售卖方式规则（`trigger_kind='sales_form'`）在商家屏上必须读成
//    「售卖方式 = 整卷 / 散剪」，**机器值 full_roll / bulk_cut 不得上屏**（migao-dev-flow §31 P3）。
//
// 红证（改回改前形态即红）：
//   · 删掉 `TRIGGER_KIND_LABEL.sales_form` ⇒ 文案里出现 `sales_form`（判据 1 红）；
//   · 删掉 `SALES_FORM_LABEL` ⇒ 文案里出现 `full_roll`（判据 2 红）；
//   · 把 `conditionText` 的 sales_form 分支去掉 ⇒ 渲染原始机器值（判据 2 红）。

import { describe, expect, it } from 'vitest'

import type { RouteRule } from '@/types'
import {
  conditionText,
  SALES_FORM_LABEL,
  TRIGGER_KIND_LABEL,
} from '@/components/production-config/utils'

function rule(overrides: Partial<RouteRule>): RouteRule {
  return {
    id: 1,
    trigger_kind: 'sales_form',
    trigger_value: 'full_roll',
    action: 'insert',
    operation: '出库',
    after_operation: '裁剪',
    position: null,
    priority: 270,
    status: 'active',
    ...overrides,
  } as RouteRule
}

describe('售卖方式规则的人话（issue #7523）', () => {
  it('判据 1：触发类型标签是「售卖方式」，不是机器键', () => {
    expect(TRIGGER_KIND_LABEL.sales_form).toBe('售卖方式')
    expect(conditionText(rule({}))).toContain('售卖方式')
    expect(conditionText(rule({}))).not.toContain('sales_form')
  })

  it('判据 2：整卷读「整卷」、散剪读「散剪」，机器值不上屏', () => {
    expect(SALES_FORM_LABEL.full_roll).toBe('整卷')
    expect(SALES_FORM_LABEL.bulk_cut).toBe('散剪')

    const fullRoll = conditionText(rule({}))
    expect(fullRoll).toContain('售卖方式 = 整卷')
    expect(fullRoll).toContain('在「裁剪」之后')
    expect(fullRoll).not.toContain('full_roll')

    const bulkCut = conditionText(rule({ trigger_value: 'bulk_cut', action: 'remove', after_operation: null }))
    expect(bulkCut).toContain('售卖方式 = 散剪')
    expect(bulkCut).toContain('时不做')
    expect(bulkCut).not.toContain('bulk_cut')
  })
})
