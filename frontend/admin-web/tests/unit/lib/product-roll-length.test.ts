// case_ids: PR-044
/**
 * 卷长文案常量 —— **单点定义**的本模块判据（issue #5919）。
 *
 * `src/lib/product-roll-length.ts` 是「1 卷 = 多少米（标称）」这份文案的**唯一**来源：
 * 商品表单的字段标签与商品详情页的 `dt` 都从它取（同源，见
 * `frontend/admin-web/tests/unit/roll-length-copy-single-source.test.ts` 的类级元守卫）。
 * 本文件钉住的是**这份文案本身**：口径（标称 / 只作默认值 / 实际以入库单与订单行为准）
 * 被改动时，这里先红 —— 而不是等两页渲染出别的说法。
 */
import { describe, it, expect } from 'vitest'
import {
  ROLL_LENGTH_FORM_NOTE,
  ROLL_LENGTH_HINT,
  ROLL_LENGTH_LABEL,
} from '@/lib/product-roll-length'

describe('product-roll-length 文案常量（issue #5919）', () => {
  it('标签：保留原字段名的可辨识度，并含「标称」', () => {
    expect(ROLL_LENGTH_LABEL).toContain('1 卷 = 多少米')
    expect(ROLL_LENGTH_LABEL).toContain('标称')
    // 单行文本（两页都按一个文本节点渲染，不吃换行符）
    expect(ROLL_LENGTH_LABEL).not.toContain('\n')
  })

  it('副说明：说清「仅作建单时的默认值」与「实际卷长以入库单 / 订单行为准」', () => {
    expect(ROLL_LENGTH_HINT).toContain('默认值')
    expect(ROLL_LENGTH_HINT).toContain('整卷换算')
    expect(ROLL_LENGTH_HINT).toContain('实际卷长以入库单')
    expect(ROLL_LENGTH_HINT).toContain('订单行')
    expect(ROLL_LENGTH_HINT).toContain('标称')
  })

  it('表单追加句：留空 = 未配置，且未配置时不推算整卷（不改写「未知」）', () => {
    expect(ROLL_LENGTH_FORM_NOTE).toContain('留空表示未配置')
    expect(ROLL_LENGTH_FORM_NOTE).toContain('不会推算整卷发货')
  })

  it('副说明与追加句各管一段：拼接后不出现重复的「标称值」前缀', () => {
    // 表单把两句拼成一段渲染（`{HINT}。{NOTE}`）⇒ 追加句不得再带自证式前缀
    expect(ROLL_LENGTH_FORM_NOTE).not.toContain('标称值')
    expect(ROLL_LENGTH_HINT.startsWith('标称值')).toBe(true)
  })
})
