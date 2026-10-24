// case_ids: UI-126
/**
 * **类级元守卫**：B 端与 C 端「同口径」富文本解析器必须逐值同源（issue #7235）
 *
 * ## 为什么这条必须存在（缺陷的「类」）
 *
 * `frontend/bmini-app/src/utils/richText.ts`（B 端黄金策）与
 * `frontend/mini-app/src/utils/richText.ts`（C 端元元）是**两份本地实现的同一套口径**
 * （#6306：不建跨 App 共享模块 —— 共享模块落在发布集之外会白屏）。这条架构取舍的代价就是
 * **一端修、一端漏**，而它已经发生过两次：
 *   - 2026-09-15 UI-042 修 C 端（`**` / 列表裸奔）⇒ B 端漏课到 #6346（2026-10-05）才发现；
 *   - 2026-10-18 #7235 修 B 端表格 ⇒ 同一轮还要手工回头补 C 端（表格同样裸奔，只是没人报）。
 * ⇒ 实例判据（两端各自的表格测试）只能证明「这一次两端都修了」；本文件证明「**以后也不会再漏一端**」：
 * 同一组语料喂给两个解析器，输出必须**逐值相等**（`toEqual`，不是「都非空」）。
 *
 * ## 判据（逐条能红）
 *
 * ① 语料非空自证：≥6 条，且解析结果里 **lines 与 table 两种块都出现**（防「两边都返回空数组 ⇒ 相等」假绿）；
 * ② 逐值相等：每条语料 `parseC(md)` 与 `parseB(md)` 深度相等（新增构造只改一端 ⇒ 当场红）；
 * ③ 表格语料必须真的解析出表格（防语料退化成普通文本 ⇒ 判据 ② 变成比较两个空结果）。
 *
 * 红证（可复算）：只给 B 端加一种构造（例如把表格分隔行改成必须三列）⇒ 判据 ② 在最长的表格语料上红；
 * 把两端都退回 origin/main ⇒ 本文件 import 失败（`parseRichContent` 不存在）整 suite 红。
 */
import { parseRichContent as parseC } from '../src/utils/richText'
import { parseRichContent as parseB } from '../../bmini-app/src/utils/richText'

const CORPUS: string[] = [
  '欢迎咨询窗帘定制',
  '**订单与履约** - 订单/物流查询\n**生产与算料** - 工序库',
  '- 轨道顺滑\n• 静音',
  '第一段\n\n第二段',
  '尺码 a | b 都可以',
  ['最近的工单：', '| 工单号 | 客户 | 状态 |', '| --- | --- | --- |', '| AS-001 | 张女士 | 待处理 |'].join('\n'),
  ['| 左 | 中 | 右 |', '| :-- | :-: | --: |', '| 1 | 2 | 3 |'].join('\n'),
  '| 只有表头还没有分隔行 |\n| 流式中间态 |',
  // 单列表格：GFM 允许；这条语料曾让「只改一端的一条口径」逃过本守卫（自我判据实测）
  '| 单列 |\n| --- |\n| 1 |',
]

describe('富文本解析器「同口径」守卫（B 端 bmini ⇄ C 端 mini-app）', () => {
  it('① 语料非空自证：≥6 条，且 lines 与 table 两种块都出现', () => {
    expect(CORPUS.length).toBeGreaterThanOrEqual(6)
    const kinds = new Set(CORPUS.flatMap((md) => parseB(md).map((block) => block.kind)))
    expect(Array.from(kinds).sort()).toEqual(['lines', 'table'])
  })

  it('② 同一语料两端解析结果逐值相等（一端改口径 ⇒ 红）', () => {
    for (const md of CORPUS) {
      // 把语料一起放进比较对象：红的时候 diff 里直接能看出是**哪一条**语料漂了
      expect({ md, parsed: parseC(md) }).toEqual({ md, parsed: parseB(md) })
    }
  })

  it('③ 表格语料真的解析出表格（不是退化成普通文本）', () => {
    const tableBlocks = CORPUS.flatMap((md) => parseB(md)).filter((block) => block.kind === 'table')
    expect(tableBlocks.length).toBeGreaterThanOrEqual(2)
  })
})
