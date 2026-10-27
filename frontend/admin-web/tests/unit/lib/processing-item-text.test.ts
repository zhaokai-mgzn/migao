// case_ids: UI-040, UI-053, UI-061, UI-062
/**
 * 商品行加工项的**纸面单一文案**（issue #7891）。
 *
 * 断言的是「三份纸渲染同一份结果」这件事本身：文案只在这里拼一次，销售单 / 报价单 / 发货单
 * 都只渲染它的输出（类级守卫 = `tests/unit_ci_workflows/test_print_media_matrix_guard.py` C9）。
 */
import { describe, expect, it } from 'vitest'
import {
  PROCESSING_TEXT_MISSING,
  formatProcessingQty,
  processingItemsOf,
  processingItemsText,
  processingPaperLine,
  processingPaperRows,
  specialOptionsTextOf,
} from '@/lib/processing-item-text'

describe('processingItemsText：加工项一行文案（三态）', () => {
  it('数量全等 ⇒ 「各」只说一遍数字（用户 #7605 的省法）', () => {
    expect(
      processingItemsText([
        { name: '定型', quantity: 6.3 },
        { name: '韩褶', quantity: 6.3 },
      ])
    ).toBe('定型、韩褶 各 6.3')
  })

  it('数量不等 ⇒ 逐项印各自的数（**不许**提公因子压成一个数）', () => {
    expect(
      processingItemsText([
        { name: '定型', quantity: 6.3 },
        { name: '韩褶', quantity: 2 },
      ])
    ).toBe('定型 6.3 + 韩褶 2')
  })

  it('单项 ⇒ 不写「各」（「定型 各 6」是病句）', () => {
    expect(processingItemsText([{ name: '定型', quantity: 6 }])).toBe('定型 6')
  })

  it('缺数量 ⇒ 该项显式印 `—`（不静默吞掉、不摊成 0）', () => {
    expect(processingItemsText([{ name: '打孔' }])).toBe(`打孔 ${PROCESSING_TEXT_MISSING}`)
    expect(
      processingItemsText([
        { name: '定型', quantity: 6 },
        { name: '打孔', quantity: null },
      ])
    ).toBe(`定型 6 + 打孔 ${PROCESSING_TEXT_MISSING}`)
  })

  it('真 0 仍印 0（真 0 ≠ 未知）', () => {
    expect(processingItemsText([{ name: '定型', quantity: 0 }])).toBe('定型 0')
  })

  it('🔴 文案里不出现 `×`（纸面读成乘法 ⇒ 客户会拿它去乘加工费）', () => {
    expect(
      processingItemsText([
        { name: '定型', quantity: 6 },
        { name: '韩褶', quantity: 6 },
      ])
    ).not.toContain('×')
  })

  it('无名字的行被丢弃；全都无名 ⇒ 空串（调用方整块不渲染）', () => {
    expect(processingItemsText([{ quantity: 6 }])).toBe('')
    expect(processingItemsText([])).toBe('')
  })
})

describe('formatProcessingQty', () => {
  it('有限数 ⇒ 原值字符串；缺值 / NaN / Infinity ⇒ `—`', () => {
    expect(formatProcessingQty(6.3)).toBe('6.3')
    expect(formatProcessingQty(0)).toBe('0')
    expect(formatProcessingQty(undefined)).toBe(PROCESSING_TEXT_MISSING)
    expect(formatProcessingQty(null)).toBe(PROCESSING_TEXT_MISSING)
    expect(formatProcessingQty(Number.NaN)).toBe(PROCESSING_TEXT_MISSING)
    expect(formatProcessingQty(Number.POSITIVE_INFINITY)).toBe(PROCESSING_TEXT_MISSING)
  })
})

describe('processingItemsOf / specialOptionsTextOf：取值口', () => {
  it('读 `processingInfo.processingItems[]` 的 name + quantity', () => {
    expect(
      processingItemsOf({
        processingItems: [
          { id: 'p1', name: '定型', quantity: 6.3, unit: '米' },
          { id: 'p2', name: '韩褶', quantity: 6.3 },
        ],
      })
    ).toEqual([
      { name: '定型', quantity: 6.3 },
      { name: '韩褶', quantity: 6.3 },
    ])
  })

  it('特殊选项走 `craftSpecRows()` 的同一份格式化（数组 ⇒ 顿号连接）', () => {
    expect(specialOptionsTextOf({ specialOptions: ['拼2次-布', '接高-布'] })).toBe('拼2次-布、接高-布')
    // 快照口径的 snake_case 别名同样认（`craftSpecRows` 已登记两个键）
    expect(specialOptionsTextOf({ special_options: ['拼2次-布'] })).toBe('拼2次-布')
  })

  it('缺键 / 空数组 / 布料行（没有 processingInfo）⇒ 都不编内容', () => {
    expect(processingItemsOf(undefined)).toEqual([])
    expect(processingItemsOf({})).toEqual([])
    expect(processingItemsOf({ processingItems: 'not-an-array' })).toEqual([])
    expect(specialOptionsTextOf(undefined)).toBe('')
    expect(specialOptionsTextOf({ specialOptions: [] })).toBe('')
  })

  it('`processingInfo` 是 JSON 字符串时也认（历史/自定义查询路径的形态）', () => {
    const info = JSON.stringify({ processingItems: [{ name: '定型', quantity: 6 }] })
    expect(processingItemsOf(info)).toEqual([{ name: '定型', quantity: 6 }])
    // 解析不了 ⇒ 当没有（不猜）
    expect(processingItemsOf('{oops')).toEqual([])
  })
})

describe('processingPaperRows / processingPaperLine：纸面行清单', () => {
  const info = {
    processingItems: [
      { name: '定型', quantity: 6.3 },
      { name: '韩褶', quantity: 6.3 },
    ],
    specialOptions: ['拼2次-布'],
  }

  it('加工项 + 特殊选项 = 两行（水洗唛式的「标签 / 值」）', () => {
    expect(processingPaperRows(info)).toEqual([
      { label: '加工项', value: '定型、韩褶 各 6.3' },
      { label: '特殊选项', value: '拼2次-布' },
    ])
  })

  it('只有特殊选项时只出一行（缺的组不占位、不印空行）', () => {
    expect(processingPaperRows({ specialOptions: ['接高-布'] })).toEqual([
      { label: '特殊选项', value: '接高-布' },
    ])
  })

  it('什么都没有 ⇒ 空清单（布料行整块不渲染）', () => {
    expect(processingPaperRows(undefined)).toEqual([])
    expect(processingPaperRows({})).toEqual([])
    expect(processingPaperLine(undefined)).toBe('')
  })

  it('单行形态：`加工项：… · 特殊选项：…`（窄纸面用）', () => {
    expect(processingPaperLine(info)).toBe('加工项：定型、韩褶 各 6.3 · 特殊选项：拼2次-布')
  })
})
