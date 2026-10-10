// case_ids: UI-001
/**
 * `displayEnum` 的**行为**判据（issue #6668 盲区①的运行时那一半）。
 *
 * 静态那一半（`frontend/admin-web/tests/unit/design-baseline-expression-fallback.test.ts`）
 * 只保证「没人再写 `LABELS[x] || x`」；本文件保证**出口本身**是安全的：
 * 未知枚举值必须渲染成**人话**，**绝不回显入参**。
 *
 * 判别力自证：把「回显入参」这条坏形态注进去（用 `||` 的表内实现）⇒ 未知值那条当场红。
 */
import { describe, it, expect } from 'vitest'

import {
  displayEnum,
  ENUM_EMPTY_LABEL,
  ENUM_UNKNOWN_LABEL,
  type EnumLabelMap,
} from '@/lib/enum-display'

/** 模拟服务端的一份枚举（前端只认识前两个） */
const LABELS: EnumLabelMap = { wechat: '微信', alipay: '支付宝' }

describe('displayEnum：未知枚举值必须渲染成人话（issue #6668 盲区①）', () => {
  it('已登记值逐字返回（修复不得改动已知形态）', () => {
    expect(displayEnum(LABELS, 'wechat')).toBe('微信')
    expect(displayEnum(LABELS, 'alipay')).toBe('支付宝')
  })

  it('🔴 未知服务端值 ⇒ 人话兜底，不回显入参', () => {
    const out = displayEnum(LABELS, 'wechat_pay_v2')
    expect(out).toBe(ENUM_UNKNOWN_LABEL)
    expect(out).not.toContain('wechat_pay_v2')
  })

  it('🔴 未知机器键（UUID / 复合键）⇒ 同样不回显', () => {
    const uuid = 'a61daac3-3e1a-4997-4577-d3ca81c4500b'
    expect(displayEnum(LABELS, uuid)).toBe(ENUM_UNKNOWN_LABEL)
    expect(displayEnum(LABELS, uuid)).not.toContain(uuid)
  })

  it('缺值（空串 / 空白 / null / undefined）⇒ 走空值文案，不是「其他」', () => {
    for (const v of ['', '   ', null, undefined]) {
      expect(displayEnum(LABELS, v), String(v)).toBe(ENUM_EMPTY_LABEL)
    }
  })

  it('表里登记了空串 ⇒ 视同未命中（不印空字符串上屏）', () => {
    expect(displayEnum({ wechat: '  ' }, 'wechat')).toBe(ENUM_UNKNOWN_LABEL)
  })

  it('兜底可以按域覆盖（如「未知方式」），但仍不得回显入参', () => {
    const out = displayEnum(LABELS, 'unknown_x', '未知方式')
    expect(out).toBe('未知方式')
    expect(out).not.toContain('unknown_x')
  })

  it('判别力自证：把「回显入参」的坏实现注进来 ⇒ 未知值那两条必红', () => {
    /** 历史坏形态：`LABELS[x] || x` */
    const bad = (labels: EnumLabelMap, value: string) => labels[value] || value
    expect(bad(LABELS, 'wechat')).toBe('微信') // 已知值两边一样 ⇒ 判别力只在未知值上
    expect(bad(LABELS, 'wechat_pay_v2')).toBe('wechat_pay_v2') // 坏形态：机器值上屏
    expect(displayEnum(LABELS, 'wechat_pay_v2')).not.toBe(bad(LABELS, 'wechat_pay_v2'))
  })
})
