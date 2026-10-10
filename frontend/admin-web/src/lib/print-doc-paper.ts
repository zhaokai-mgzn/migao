// case_ids: UI-040, UI-053
/**
 * 纸面（**客户拿到手的凭证**）的缺值口径 + 实例判据（issue #6720）。
 *
 * 放在 `src/lib/` 而不是 `scripts/*.mjs` 或测试文件里，是为了让**组件测试可以直接 import**
 * —— 不必 import 一个 `*.test.ts`（那会把整套判据当副作用带进来）。
 * 静态判据面（`SCOPE` / 台账 / 命中形态）在 `frontend/admin-web/scripts/print-doc-zero-fallback-scan.mjs`，
 * 类级元守卫在 `frontend/admin-web/tests/unit/lib/print-doc-paper.test.ts`。
 *
 * ⚠️ **异常消息的措辞是刻意的**（别「顺手润色」回去）：本文件里的中文串会被
 * `tests/unit/user-copy-jargon-guard.test.ts`（`scripts/user-copy-scan.mjs` 的 R3/R5）当成
 * 「可能上屏的文案」体检 ⇒ 消息里**不写**「判据 / issue #NNNN / `标识符`」这类形态
 * （所以有「检查范围为空」这种说法）。改回去就是给商家看研发腔，CI 会红。
 * 本模块是**开发者面**的调用方契约（只有各单据测试 import），不是屏幕文案。
 */

/** 纸面缺值的**唯一**允许形态（与 `SalesDoc.SALES_DOC_MISSING` / `ProcessingDoc.MISSING` 同字符） */
export const PAPER_MISSING = '—'

/**
 * 纸面**禁止**的假读数：金额格式化后的 `0.00`。
 *
 * ⚠️ 为什么不把裸 `0` 也列进来（实测踩过，别加回去）：**真 0 是合法读数**
 * （0 元 / 0 米的订单行在发货单上与 `—` 并列出现），而「发货单 17.5」「第1套/共1套」
 * 这类**含 0 的数字**也天然含 `0` ⇒ 按子串判 `0` 会把**真 0 判红**
 * （= 把修好的东西喂红、逼人回退），正是 issue #6720 明令禁止的反向对照。
 * 裸数量位的判据改按**单元格取值**判（见下 `assertPaperKeepsMissingDistinct`）。
 */
const FORBIDDEN_PAPER_ZEROS = ['0.00']

/** 纸面正文里的「未知被印成 0」命中（具名报出命中的串，便于归因） */
export function paperZeroFills(text: unknown): string[] {
  const hay = String(text)
  return FORBIDDEN_PAPER_ZEROS.filter((zero) => hay.includes(zero))
}

/**
 * **纸面正文文本**（DOM 侧取用）：`textContent` 里去掉 `<style>` 与 `<svg>`。
 *
 * 为什么必须去掉这两样（实测坑）：单据把打印 CSS 内联在自己的 `<style>` 里（`@page`、
 * `width: 100%`、`9pt`），而 QR 是 `<svg>` —— 它们的 `textContent` 里天然含数字片段
 * （实测：只按 `textContent` 判，报价单会因内联样式里的 `100%` 判红 = **假红**，逼人回退真修复）。
 * （`<style>` 与 `<svg>` **都不是**「印给客户看的数字」—— 本条只判后者。）
 */
export function paperTextOf(host: Element | null | undefined): string {
  if (!host) return ''
  const clone = host.cloneNode(true) as Element
  for (const el of Array.from(clone.querySelectorAll('style, svg'))) el.remove()
  return clone.textContent || ''
}

/** 纸面里所有**数值形**单元格的取值（`—` / `0` / `12.5` / `1,250.00` …），按 DOM 顺序 */
const NUMERIC_CELL_RE = /^[^A-Za-z\u4e00-\u9fff]*$/

/**
 * **指定 ○张表 / ○行**的取值，按**列位置**取（同列同一语义 ⇒ 判据面天然对齐）。
 *
 * 为什么按列而不按行（实测坑）：同一行的「单价」缺值印 `—`，而另一行的「单价」可能是真 `0.00`
 * 或 `100.00` —— 只要**把列选对**，判据就是同义词比较；选整行/整表都会混进别的列的真值。
 * 表可能有多张（`rows: 'all'`）或只有一张（`rows: [i]`）；选中的格子一个都没有 ⇒ 抛错
 * （**空集不得被读成通过**）。
 */
export function paperNumericColumn(
  scope: Element | null | undefined,
  { column, rows = 'all' }: { column: number; rows?: number[] | 'all' }
): string[] {
  if (!scope) throw new Error('paperNumericColumn 收到了空容器（找不到纸面根元素）')
  const tables = Array.from(scope.querySelectorAll('table'))
  const picked: string[] = []
  for (const table of tables) {
    const trs = Array.from(table.querySelectorAll('tr'))
    for (const [index, tr] of trs.entries()) {
      if (rows !== 'all' && !rows.includes(index)) continue
      const tds = Array.from(tr.querySelectorAll('td'))
      // 单格即整行（`colSpan` 的合计行）或列越界 ⇒ 跳过（不是本列的数据格）
      if (tds.length <= 1 || column >= tds.length) continue
      picked.push((tds[column].textContent || '').trim())
    }
  }
  if (picked.length === 0) {
    throw new Error(
      `检查范围为空：第 ${column} 列、第 ${Array.isArray(rows) ? rows.join(',') : rows} 行 ` +
        '在容器里一个数值格都没选到（版式变了 / 传错容器）—— 空集不得被读成通过。'
    )
  }
  return picked
}
/** 「整格 = 未知被印成 0」的形态（`0` / `0.00`）；⚠️ **锚定整格**，不许退化成子串判定 */
const PAPER_ZERO_CELL_RE = /^0(?:\.0+)?$/
export function paperNumberCells(host: Element | null | undefined): string[] {
  if (!host) return []
  return Array.from(host.querySelectorAll('td, th'))
    .map((cell) => (cell.textContent || '').trim())
    .filter((text) => NUMERIC_CELL_RE.test(text))
}

/**
 * **实例不变量（① 纸面不得把「未知」印成 0）**。
 *
 * `values` = 调用方**显式圈定**的判据面上的取值（纸面数值格 / 金额格 —— 由各单据测试自己选取，
 * 因为「哪些格是金额格」是版式知识，不该由本库猜）。
 *
 * 🔴 两条硬口径（都是**实测踩过**的假红）：
 * 1. **整格锚定**，不是子串匹配 —— `100.00` / `1,250.00` 里的 `0.00` 是**真值的一部分**，
 *    按子串判会把真值判红（issue #6720 明令「不许把真值 0 判红」）；
 * 2. 判据面**只圈缺值那几格** —— 同一版式里另一行可能本来就有真 `0`（那是合法读数），
 *    把整表圈进来一样是假红。
 *
 * `label` 缺省即抛错 ⇒ **未登记即红**（新单据的测试不调这条不变量，谁都发现不了）。
 * 与 ②（`assertPaperKeepsMissingDistinct`）**配套**：① 只看「有没有印成 0」，② 逐值区分 `—` 与真 `0`。
 */
export function assertNoPaperZeroFill(
  values: readonly string[],
  { label, presence = [] }: { label?: string; presence?: readonly string[] } = {}
): void {
  if (!label) throw new Error('调用本不变量必须给 label（报红时要点得出是哪份单据）')
  const where = presence.length > 0 ? `（已注入：${presence.join(' / ')}）` : ''
  const offenders = values
    .map((value) => String(value).trim())
    .filter((text) => PAPER_ZERO_CELL_RE.test(text))
  if (offenders.length > 0) {
    throw new Error(
      `${label} 的纸面出现「未知 ⇒ 0」的回退形态：${offenders.map((h) => `「${h}」`).join(' / ')}${where} —— ` +
        `纸面缺值一律印 ${PAPER_MISSING}（范式：SalesDoc 的 SALES_DOC_MISSING / ProcessingDoc 的 MISSING），` +
        '真值 0 才印 0.00（否则客户会把「没有这个数」读成「这一项是零元」）。'
    )
  }
}

/**
 * **实例不变量（② 逐格：未知与真 0 可分）**：该单据的纸面数值格里**必须同时**出现
 * 缺值占位 `—`（未知）与真 `0`（合法读数）—— 两者缺任一 ⇒ 红。
 *
 * 为什么必须**双向**钉（issue #6720 明令「真 0 仍印 0，不许把真值 0 判红」）：
 * - 有 `—` 无真 `0` ⇒ 该测试**没有**覆盖「真 0 不被误判」那一半（空跑）；
 * - 有真 `0` 无 `—` ⇒ 缺值那一半没被渲染 ⇒ 判据在空气上跑（假绿）。
 * ⇒ 这条同时也是**证据锚判据**：「这条判据真跑过」由纸面自己给出读数，不靠调用方声明。
 */
export function assertPaperKeepsMissingDistinct(
  cells: readonly string[],
  { label, presence = [] }: { label?: string; presence?: readonly string[] } = {}
): void {
  if (!label) throw new Error('调用本不变量必须给 label（报红时要点得出是哪份单据）')
  const where = presence.length > 0 ? `（已注入：${presence.join(' / ')}）` : ''
  const missing = cells.filter((cell) => cell === PAPER_MISSING)
  const realZero = cells.filter((cell) => cell === '0' || cell === '0.00')
  if (missing.length === 0 || realZero.length === 0) {
    throw new Error(
      `${label} 的纸面数值格没有把「未知」与「真 0」两种形态同时摆出来${where}：` +
        `读到 ${cells.length} 格，其中 ${PAPER_MISSING} × ${missing.length}、真 0 × ${realZero.length} —— ` +
        `两边都必须有：缺 ${PAPER_MISSING} ⇒ 缺值那半没渲染（这条检查范围等于空跑）；缺真 0 ⇒ ` +
        '没覆盖「真 0 必须仍印 0」的反向对照。'
    )
  }
}

/**
 * **聚合不变量（issue #6731）**：`聚合求和必须区分「未知」与「0」—— 任一加数不可知则不得输出数值`。
 *
 * ## 为什么必须单独有一条（#6720 那把尺子量不到它）
 *
 * #6720 的形态判据只认「`?? 0` / `|| 0` **落进印数值的表达式**」；而本形态是**语义**的：
 * `subtotal` 缺席时 `0 + 0 = 0` —— 代码里一个 `?? 0` 都没有，却把「不可知」印成了确定值
 * （实证读数：真机形态下纸面印 `本套金额 0.00`，而同一行「小计」栏印 `—`）。
 *
 * ## 判据面 = **两加数 × 已知/不可知 的矩阵**（含反例，缺任一侧都是空跑）
 *
 * - 任一加数不可知（缺席 / `NaN`）⇒ `sum(...)` 必须返回 `null`；
 * - 两个加数都已知（**含两个都是真 `0`**）⇒ 必须返回数值（不许把 `0` 判成「不可知」）。
 *
 * ⚠️ **登记的一处不对称（有意，不是漏洞）**：`processingFee` **缺席**按 `0` 计
 * （存量单没有该字段 = 当时没有加工费这回事 ⇒ 真值就是 0）。改它会制造**假 `—`**；
 * 故样本矩阵里 `{ subtotal: 1250 }`（缺加工费）**必须**返回 `1250`。
 *
 * 承载体：`frontend/admin-web/tests/unit/lib/print-doc-paper.test.ts`（**判别力自证**：把实现换回
 * 旧的「两者都缺才判不可知」⇒ 当场红）+ 各单据测试（`QuotationDoc.test.tsx` 用它钉住真渲染值）。
 * 静态那一半（**列表形聚合**：把「某一项不可知」摊成 0 的那种求和）在同一把尺子的形态表里
 * （`frontend/admin-web/scripts/print-doc-zero-fallback-scan.mjs` 的「聚合摊零补位」——
 * 形态**字面写法只写在那一处**，本文件只描述语义）。
 *
 * ⚠️ 本文件**不**出现那个聚合写法的字面源码（注释里也不写）：`src/**` 另有一条既有守卫
 * （`frontend/admin-web/tests/unit/order-fee-composition-guard.test.ts`，issue #5843）按**原文**
 * 扫「累加器 + 加工费字段名」同现的形态，它**不看注释** ⇒ 在这里写例子会被误判成「又一套加工费求和」
 * （实测踩过：注释 + 下面的 `PaperAddendPair` 字段名落进 300 字窗口 ⇒ 该守卫当场红）。
 */
export interface PaperAddendPair {
  subtotal?: number
  processingFee?: number
}

/** 不可知那一半的样本（**每一格都必须 `null`**）：含 issue #6731 的真机形态 `{ subtotal: 缺席, processingFee: 0 }` */
export const AGGREGATE_UNKNOWN_SAMPLES: readonly (readonly [PaperAddendPair, string])[] = [
  [{ subtotal: undefined, processingFee: 0 }, '面料小计不可知 + 加工费真 0（真机形态，修前印 0.00）'],
  [{ subtotal: undefined, processingFee: 250 }, '面料小计不可知 + 加工费 250'],
  [{ subtotal: undefined, processingFee: undefined }, '两个加数都不可知'],
  [{ subtotal: Number.NaN, processingFee: 0 }, '面料小计 NaN + 加工费真 0'],
  [{ subtotal: undefined, processingFee: Number.NaN }, '面料小计不可知 + 加工费 NaN'],
]

/** 已知那一半的样本（**每一格都必须返回数值**）：反向对照，防「把所有 0 都改成 —」 */
export const AGGREGATE_KNOWN_SAMPLES: readonly (readonly [PaperAddendPair, number, string])[] = [
  [{ subtotal: 0, processingFee: 0 }, 0, '两个真 0 ⇒ 0（不加"不可知"）'],
  [{ subtotal: 100, processingFee: 0 }, 100, '真 100 + 真 0 ⇒ 100'],
  [{ subtotal: 1250, processingFee: 250 }, 1500, '两个都有值 ⇒ 相加'],
  [{ subtotal: 1250 }, 1250, '加工费缺省 ⇒ 按 0（存量单既有口径，登记的不对称）'],
]

export function assertAggregateUnknownIsContagious(
  compute: (item: PaperAddendPair) => number | null,
  { label }: { label?: string } = {}
): void {
  if (!label) throw new Error('调用本不变量必须给 label（报红时要点得出是哪份单据）')
  for (const [sample, why] of AGGREGATE_UNKNOWN_SAMPLES) {
    const got = compute(sample)
    if (got !== null) {
      throw new Error(
        `${label} 的聚合把「不可知」当成了确定值：${why} ⇒ 得到 ${JSON.stringify(got)}，` +
          `应当是 ${PAPER_MISSING === '—' ? 'null（纸面印 —）' : 'null'} —— ` +
          '不确定性的算术是「未知 + 0 = 未知」，不是 0。'
      )
    }
  }
  for (const [sample, expected, why] of AGGREGATE_KNOWN_SAMPLES) {
    const got = compute(sample)
    if (got !== expected) {
      throw new Error(
        `${label} 的聚合把「已知」判成了不可知 / 算错：${why} ⇒ 得到 ${JSON.stringify(got)}，应当是 ${expected}` +
          '（真 0 是合法读数，不许改成缺值占位）。'
      )
    }
  }
}
