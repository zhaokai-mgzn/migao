/**
 * 富文本 → **可读纯文本**（issue #6403 缺陷 2）—— 纯函数，**只给展示层用**。
 *
 * 病（用户 2026-10-06 实测，图 1 / 图 3）：识别结果卡的「商品描述」逐字显示
 * `<p>常青藤系列纯色遮光窗帘，18 款…</p><p>色号包含：…</p>`。
 * 值本身是 HTML 是**对的**（落点是 `ProductForm` 的 `RichTextEditor`，入库需要 HTML）
 * ⇒ **不许**从落值里删标签；要改的只是「摆给商家看的那一眼」。
 *
 * 口径（issue #6403，AI 裁定）：块级标签 ⇒ 分段 / 换行、实体解码、其余标签剥掉、连续空行收敛。
 * 🔴 本模块**不得**被用在提交 / 落值路径上（那是 `buildProductPrefill` 的 `description` 原样透传）。
 */

/**
 * 块级标签（含 `<br>`）：开合都落成一次换行 —— `<p>a</p><p>b</p>` ⇒ 两段。
 * 只列**真会分段**的标签；行内标签（`span` / `strong` / `a` …）交给下面剥掉、不制造换行。
 */
const BLOCK_TAGS =
  /<\/?(?:p|div|br|li|ul|ol|h[1-6]|tr|td|th|table|section|article|blockquote|figure|figcaption|pre|hr)\b[^>]*>/gi

/**
 * 注释与其余标签：一律剥掉。
 * ⚠️ 只认「字母 / 斜杠 / 叹号开头」——纯文本里的 `2.8 < 3.2` 这种数学写法**不会被吃掉**
 * （`< 3.2` 后面没有 `>`，且 `<` 后不是字母）。
 */
const OTHER_TAGS = /<!--[\s\S]*?-->|<[a-zA-Z/!][^>]*>/g

/** 常见命名实体（表格外的一律原样保留 —— 猜错一个实体比留着更糟） */
const NAMED_ENTITIES: Record<string, string> = {
  amp: '&',
  lt: '<',
  gt: '>',
  quot: '"',
  apos: "'",
  nbsp: ' ',
  ldquo: '“',
  rdquo: '”',
  hellip: '…',
  mdash: '—',
  ndash: '–',
}

/** 实体解码（命名 + 十进制 + 十六进制）；认不出 / 越界 ⇒ 原样保留 */
function decodeEntities(text: string): string {
  return text.replace(/&(#[xX]?[0-9a-fA-F]+|[a-zA-Z]+);/g, (whole, body: string) => {
    if (body[0] === '#') {
      const hex = body[1] === 'x' || body[1] === 'X'
      const code = parseInt(hex ? body.slice(2) : body.slice(1), hex ? 16 : 10)
      const valid = Number.isFinite(code) && code >= 0 && code <= 0x10ffff
      return valid ? String.fromCodePoint(code) : whole
    }
    return NAMED_ENTITIES[body.toLowerCase()] ?? whole
  })
}

/**
 * HTML 片段 → 可读纯文本。
 *
 * - 空 / `null` / `undefined` ⇒ `''`；
 * - 纯文本入参 ⇒ **原样**（无标签可剥、无实体可解，只有首尾 trim 与空行收敛）；
 * - 顺序固定：先换行化块级标签 → 剥其余标签 → **再**解实体
 *   （反过来会把文本里的 `&lt;p&gt;` 当成标签剥掉）。
 */
export function htmlToPlainText(raw: string | null | undefined): string {
  if (!raw) return ''
  const withBreaks = raw.replace(BLOCK_TAGS, '\n')
  const stripped = decodeEntities(withBreaks.replace(OTHER_TAGS, ''))
  return stripped
    .split('\n')
    .map((line) => line.trim())
    .join('\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}
