// case_ids: UI-040, UI-053
/**
 * 纸面（**客户拿到手的凭证**）的缺值口径 + 实例判据（issue #6720）。
 *
 * 放在 `src/lib/` 而不是 `scripts/*.mjs` 或测试文件里，是为了让**组件测试可以直接 import**
 * —— 不必 import 一个 `*.test.ts`（那会把整套判据当副作用带进来）。
 * 静态判据面（`SCOPE` / 台账 / 命中形态）在 `frontend/admin-web/scripts/print-doc-zero-fallback-scan.mjs`，
 * 类级元守卫在 `frontend/admin-web/tests/unit/print-doc-zero-fallback-guard.test.ts`。
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
      `判据面为空：column=${column} / rows=${Array.isArray(rows) ? rows.join(',') : rows} ` +
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
  if (!label) throw new Error('调用本不变量必须给 `label`（报红时要点得出是哪份单据）')
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
  if (!label) throw new Error('调用本不变量必须给 `label`（报红时要点得出是哪份单据）')
  const where = presence.length > 0 ? `（已注入：${presence.join(' / ')}）` : ''
  const missing = cells.filter((cell) => cell === PAPER_MISSING)
  const realZero = cells.filter((cell) => cell === '0' || cell === '0.00')
  if (missing.length === 0 || realZero.length === 0) {
    throw new Error(
      `${label} 的纸面数值格没有把「未知」与「真 0」两种形态**同时**摆出来${where}：` +
        `读到 ${cells.length} 格，其中 ${PAPER_MISSING} × ${missing.length}、真 0 × ${realZero.length} —— ` +
        `两边都必须有：缺 ${PAPER_MISSING} ⇒ 缺值那半没渲染（判据在空气上跑）；缺真 0 ⇒ ` +
        '没覆盖 issue #6720 的反向对照（真 0 必须仍印 0，不许把真值判红）。'
    )
  }
}
