// case_ids: PP-011, UI-061
// @vitest-environment jsdom
//
// issue #7833（用户 2026-10-26 逐字）：「JG-20261026-8172 这个加工单有**超高倒幅**，但是在加工单的
// 各个环节都没有体现出来」。
//
// 加工费组合 = 加工费定价的「组合键」（`processingItems[].name` 的集合，自动特征超高/超宽/倒幅
// 与手选加工项韩褶/定型都在里面）—— 四个展示面（加工单 A4 / 生产明细页 / 水洗唛 / 订单加工单块）
// 若各取一遍，就是同一真值四处投影。⇒ 取值 / 去重 / 空值口径收敛到 `lib/processing-combo.ts`。
//
// 逐条判据（都能判红）：
// ① 去空 + 去重 + **保序**（顺序沿用后端数组 = 算钱用的组合顺序，不重排）；
// ② 缺键 / 非数组 / 脏元素（非字符串 name）⇒ 丢弃，**绝不**产出 `undefined` / `null` / `NaN`；
// ③ 一行文本用顿号（与「特殊选项」同口径）；空 ⇒ 空串（调用方据此整行不渲染）；
// ④ 单/多条快照行的**并集**（生产明细页头部）—— 去重保序、跨行合并；
// ⑤ 只读**快照**：不改入参、不回落到订单侧现值（入参是加工单快照行）。
import { describe, expect, it } from 'vitest'
import {
  processingComboNames,
  processingComboText,
  processingComboTextOfRows,
} from '@/lib/processing-combo'

/** 加工单快照行的最小形态（`ProcessingOrderItem.processingItems`） */
const row = (names: Array<string | null | undefined> | null) =>
  names === null
    ? {}
    : { processingItems: names.map((name, index) => ({ id: `pi-${index}`, name })) }

describe('processingComboNames / processingComboText —— 加工费组合的展示取值口（issue #7833）', () => {
  it('判据 ①：去空 + 去重 + 保序（顺序 = 后端数组序，不重排）', () => {
    const source = row(['韩褶', '超高', '倒幅', '定型', '超高'])
    expect(processingComboNames(source)).toEqual(['韩褶', '超高', '倒幅', '定型'])
    // 前后空白按「值」trim，不整行丢（后端历史数据带空格）
    expect(processingComboNames(row([' 韩褶 ', '超高  ']))).toEqual(['韩褶', '超高'])
    // 空串 / 纯空白名字 ⇒ 丢弃（不留空壳项）
    expect(processingComboNames(row(['韩褶', '', '   ', '定型']))).toEqual(['韩褶', '定型'])
  })

  it('判据 ②：缺键 / 非数组 / 脏元素 ⇒ 空数组（不编造、不产出 undefined/null）', () => {
    expect(processingComboNames(undefined)).toEqual([])
    expect(processingComboNames(null)).toEqual([])
    expect(processingComboNames({})).toEqual([])
    expect(processingComboNames({ processingItems: null })).toEqual([])
    // 非数组（脏数据）
    expect(processingComboNames({ processingItems: '韩褶' as unknown as [] })).toEqual([])
    // 非字符串 name / null 元素
    expect(
      processingComboNames({
        processingItems: [
          { name: 123 as unknown as string },
          { name: null },
          { id: 'x' } as unknown as { name?: string | null },
        ],
      }),
    ).toEqual([])
    // 绝不把「缺值」渲染成字符串
    expect(processingComboText({ processingItems: [{ name: null }] })).toBe('')
  })

  it('判据 ③：一行文本用顿号（与特殊选项同口径）；空 ⇒ 空串', () => {
    expect(processingComboText(row(['韩褶', '超高', '倒幅', '定型']))).toBe('韩褶、超高、倒幅、定型')
    expect(processingComboText(row([]))).toBe('')
    expect(processingComboText(undefined)).toBe('')
    // 分隔符可换（水洗唛那行用「 · 」，与加工行的其余段同口径）
    expect(processingComboText(row(['超高', '倒幅']), ' · ')).toBe('超高 · 倒幅')
  })

  it('判据 ④：多条快照行的并集 —— 去重保序、跨行合并（生产明细页头部摘要）', () => {
    const rows = [row(['韩褶', '超高']), row(['倒幅', '超高']), row([])]
    expect(processingComboTextOfRows(rows)).toBe('韩褶、超高、倒幅')
    expect(processingComboTextOfRows(undefined)).toBe('')
    expect(processingComboTextOfRows([])).toBe('')
    // 空行不制造空壳分隔符
    expect(processingComboTextOfRows([row([]), row(['超高'])])).toBe('超高')
  })

  it('判据 ⑤：只读 —— 不改入参（同一份快照被四个面共用）', () => {
    const items = [{ name: '韩褶' }, { name: '超高' }]
    const source = { processingItems: items }
    const before = JSON.stringify(source)
    processingComboNames(source)
    processingComboTextOfRows([source])
    expect(JSON.stringify(source)).toBe(before)
    expect(items.map((item) => item.name)).toEqual(['韩褶', '超高'])
  })
})
