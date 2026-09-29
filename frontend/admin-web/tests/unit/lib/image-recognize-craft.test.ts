// case_ids: OR-008, OR-048
/**
 * **客户写明的工艺要求 → 页面勾选面**的映射（issue #5794）。
 *
 * 用户 2026-09-29 逐字：「如果用户是根据图片下单的，就需要**根据图中客户要求来决定工艺规格和
 * 加工项选择了，不能选错**」。
 *
 * 本文件钉的是**纯函数半边**（`lib/image-recognize.ts`）：
 * ① 打开方式 → 开数 `1`~`4`（表外 / 认不出 ⇒ `undefined`，**不猜一档**）；
 * ② 款式 → `单色` / `拼色`（含「拼」优先判拼色）；
 * ③ 加工项 → 目录名清单（分隔符归一 + 去重 + **只登记改名别名**：V139 `韩折` ⇒ `韩褶`）；
 * ④ `buildOrderPrefill` 只在**认得出**时才出键（认不出 ⇒ 该键不出现，页面据此一格都不动）。
 *
 * 页面级半边（真的按图勾选 / 覆盖默认 / 留痕可见）在
 * `frontend/admin-web/tests/unit/pages/orders-new-layout.test.tsx` 的「判据 12」。
 */
import { describe, expect, it } from 'vitest'
import {
  buildOrderPrefill,
  openCountOf,
  processingItemNamesOf,
  styleOf,
} from '@/lib/image-recognize'
import type { RecognizedField } from '@/lib/api'

const TAG = '[图片识别]'
const EMPTY_ORDER = { customerName: '', customerPhone: '', customerAddress: '', remark: '' }

function field(key: string, value: string | null, label = key, reason: string | null = null): RecognizedField {
  return { key, label, value, source: value ? TAG : null, reason }
}

describe('打开方式 → 开数（1~4，表外不猜）', () => {
  it.each([
    ['单开', 1],
    ['双开', 2],
    ['两开', 2],
    ['2 开', 2],
    ['三开', 3],
    ['四开', 4],
    ['双开（左右各一片）', 2],
  ])('「%s」⇒ %i', (raw, expected) => {
    expect(openCountOf(raw)).toBe(expected)
  })

  it.each(['5 开', '开着', '看不清', '', '左右各一片'])('「%s」认不出 ⇒ undefined（不猜）', (raw) => {
    expect(openCountOf(raw)).toBeUndefined()
  })
})

describe('款式 → 单色 / 拼色', () => {
  it.each([
    ['单色', '单色'],
    ['素色', '单色'],
    ['拼色', '拼色'],
    ['双拼色', '拼色'],
    ['单色拼边', '拼色'],
  ])('「%s」⇒ %s', (raw, expected) => {
    expect(styleOf(raw)).toBe(expected)
  })

  it('既不是单色也不是拼色 ⇒ undefined（不替客户选一档）', () => {
    expect(styleOf('粉红色')).toBeUndefined()
    expect(styleOf('')).toBeUndefined()
  })
})

describe('加工项 → 目录名清单（分隔符归一 + 去重 + 改名别名）', () => {
  it('顿号 / 逗号 / 斜杠 / 空白都当分隔符，去重且去空', () => {
    expect(processingItemNamesOf('韩褶、定型, 打孔／韩褶  ')).toEqual(['韩褶', '定型', '打孔'])
  })

  it('**目录改名别名**（V139 韩折 ⇒ 韩褶）归一：图上照旧写「韩折」也能匹配上目录', () => {
    expect(processingItemNamesOf('韩折、定型')).toEqual(['韩褶', '定型'])
  })

  it('目录里没有的名字**原样保留**（匹配是页面侧的事，这里不替客户改需求）', () => {
    expect(processingItemNamesOf('加铅块、某种没听过的做法')).toEqual(['加铅块', '某种没听过的做法'])
  })

  it('空 / 全是分隔符 ⇒ 空数组（该键不出现 ⇒ 页面一格都不动）', () => {
    expect(processingItemNamesOf('')).toEqual([])
    expect(processingItemNamesOf(' 、, ')).toEqual([])
  })
})

describe('buildOrderPrefill：只出**认得出**的键（认不出 ⇒ 不出现）', () => {
  it('三格都认得出 ⇒ 三个键 + 三个 recognizedFields 都在', () => {
    const prefill = buildOrderPrefill(
      [
        field('open_count', '双开', '打开方式'),
        field('style', '拼色', '款式'),
        field('processing_items', '韩折、定型', '加工项'),
      ],
      EMPTY_ORDER,
    )
    expect(prefill.openCount).toBe(2)
    expect(prefill.style).toBe('拼色')
    expect(prefill.processingItemNames).toEqual(['韩褶', '定型'])
    expect(prefill.recognizedFields).toEqual(['open_count', 'style', 'processing_items'])
  })

  it('内核有意留空（`value: null`）⇒ 三个键都不出现（页面据此**一格都不动**）', () => {
    const prefill = buildOrderPrefill(
      [
        field('open_count', null, '打开方式', '图上没写打开方式'),
        field('style', null, '款式', '图上没写款式'),
        field('processing_items', null, '加工项', '图上没写加工要求'),
      ],
      EMPTY_ORDER,
    )
    expect(prefill.openCount).toBeUndefined()
    expect(prefill.style).toBeUndefined()
    expect(prefill.processingItemNames).toBeUndefined()
    expect(prefill.recognizedFields).toEqual([])
  })

  it('表外档 / 认不出的值 ⇒ 同样不出键（**绝不**猜一个默认档填进去）', () => {
    const prefill = buildOrderPrefill(
      [field('open_count', '5开', '打开方式'), field('style', '粉红色', '款式')],
      EMPTY_ORDER,
    )
    expect(prefill.openCount).toBeUndefined()
    expect(prefill.style).toBeUndefined()
    expect(prefill.recognizedFields).toEqual([])
  })
})
