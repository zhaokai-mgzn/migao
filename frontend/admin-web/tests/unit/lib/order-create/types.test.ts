// case_ids: MC-243
/**
 * `lib/order-create/types.ts` —— 下单页切片的**共享形状层**（issue #8725 第一档）。
 *
 * 单一职责是「只声明形状与常量、零实现」，所以本文件只钉两件在运行期可判的事：
 * ① 售卖形态两个取值的**字面量**（下游落库、组头展示、布料判型都按它逐字比）；
 * ② `布料` 的**唯一真值源**仍是 `lib/sale-form.ts`（本模块只转出，不另写一份）。
 */
import { describe, it, expect } from 'vitest'
import { SALE_FORM_FABRIC, SALE_FORM_FINISHED } from '@/lib/order-create/types'
import { SALE_FORM_FABRIC as SALE_FORM_FABRIC_LIB } from '@/lib/sale-form'

describe('order-create/types — 共享形状的取值', () => {
  it('售卖形态两个取值逐字固定（改一个字就改变落库口径与组头展示）', () => {
    expect(SALE_FORM_FINISHED).toBe('成品帘')
    expect(SALE_FORM_FABRIC).toBe('布料')
  })

  it('布料字面量只有 `lib/sale-form.ts` 一处真值源：本模块是**同一个值**的转出，不是第二份定义', () => {
    expect(SALE_FORM_FABRIC).toBe(SALE_FORM_FABRIC_LIB)
  })
})
