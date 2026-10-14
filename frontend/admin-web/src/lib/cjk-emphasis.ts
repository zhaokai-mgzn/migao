/**
 * 聊天正文的「中文标点旁强调失效」修复（issue #6910，用户 2026-10-14 实测截图）。
 *
 * ## 缺陷形态（复算命令见 issue #6910 正文）
 *
 * 助手回复里 `下单入口：后台的**「订单列表」页**，…` 的 `**` **原样上屏**（商家看见可见星号），
 * 而同一条回复里 `**下单（新建订单）不在我这边办理——…**` 加粗正常 ⇒ 不是「markdown 没渲染」，
 * 是 **CommonMark 的左右 flanking 规则**在「汉字紧邻中文标点」时判这对标记**不能开 / 不能闭**
 * （两条规则都以紧邻字符是否为 Unicode 标点 P/S 为条件）：`的**「…」**` 的开标记「前=汉字、后=`「`」
 * ⇒ 不能开；`**「重点」**文本` 的闭标记「前=`」`、后=汉字」⇒ 不能闭。配对不上就按字面输出。
 * 英文里同样的形态（`abc**"x"**`）在 CommonMark 下同样不加粗 —— 不是本仓自造的解析器问题。
 *
 * ## 做法
 *
 * 交给 `react-markdown` 之前做一次**零可见变化**的归一化：只给「汉字 ↔ 标点」相邻、
 * 且 CommonMark 判它**不能开 / 不能闭**的那一侧插入零宽空格（U+200B）—— ZWSP 既不是空白、也不是标点
 * ⇒ flanking 条件当场成立，强调配上对，屏幕上不多任何可见字符（`**` 消失）。
 *
 * ## 有意收窄（这不是通用 markdown 修复器）
 *
 * - **只在 CJK 区动手**：`abc**"x"**`（纯 ASCII 前后）在 CommonMark 里同样失效，但**有意不修** ——
 *   否则 `(**kwargs)`、`a**"b"**` 这类代码随笔也会被插入 ZWSP。
 *   重启用条件 = 真出现非中文语种的商家可见缺陷。
 * - **只认成对**：先按「同字符 + 同长度」配对，只修「该开却开不了 / 该闭却闭不了」的那一侧
 *   ⇒ 已在正常工作的标记**一个都不动**（若把 `**A**：**B**` 里作 closer 的标记也变成 opener，
 *   新旧能力叠加会让后面的 `**B**` 落单 —— 那是本模块必须避免的回归）。
 * - **不碰代码面**：行内代码（`` `…` ``）与围栏代码块（```` ``` ```` / `~~~`）逐字不动 ——
 *   注入的 ZWSP 会污染从聊天里复制出去的代码。
 * - **不修** `_` 的词内斜体（`中文_斜体_中文`）：那是 CommonMark 对 `_` 的独立规则（不是 flanking 缺陷），
 *   修它会连坐 `snake_case`。用例面登记为未覆盖，重启用条件 = 真出现该形态的商家可见缺陷。
 * - 跨行内代码的配对（``**中文 `code` 中文**``）**不修**：配对按代码面切分后各自独立 ⇒ 不配对 = 保持原样，
 *   宁可不改也不破坏（边界如实登记，不假装覆盖）。
 *
 * ## 判据
 *
 * - 纯函数面：`frontend/admin-web/tests/unit/lib/cjk-emphasis.test.ts`（该插的插、不该插的逐字不动 + 类级接线守卫）；
 * - 真渲染管线面：`frontend/admin-web/tests/unit/components/MessageList-cjk-emphasis.test.tsx`
 *   （真 `react-markdown`，截图原句渲染后 `<strong>` 在、`textContent` 不含 `**`）。
 */

/** 零宽空格：既非空白（Zs）也非标点（P/S）⇒ 插入后 flanking 条件成立，且屏幕上不可见 */
export const ZWSP = '\u200B'

/**
 * CJK 区（汉字 / 假名 / 谚文 / 全角与中文标点区）。
 *
 * ⚠️ 用 `new RegExp` 逐块写范围（而不是 `\p{Script=Han}`）：本包 `tsconfig.json` 的
 * `target` 仍是 ES2017，字面量里的 Unicode 属性转义会被 TS 判语法错误（`new RegExp('…', 'u')`
 * 的字符串形态不受该检查约束，运行时现代浏览器/Node 均支持）。
 */
const CJK_ZONE = /[\u2E80-\u303F\u3040-\u30FF\u3130-\u318F\u3400-\u4DBF\u4E00-\u9FFF\uA960-\uA97F\uAC00-\uD7AF\uF900-\uFAFF\uFE30-\uFE4F\uFF00-\uFFEF]/

/** Unicode 标点（P/S）—— CommonMark flanking 规则里的「punctuation」就是这两类 */
const PUNCTUATION = new RegExp('[\\p{P}\\p{S}]', 'u')

/** 空白（含全角空格 U+3000、不换行空格）—— 与 CommonMark 的「whitespace」口径一致 */
const WHITESPACE = /\s/

/** 文档首尾之外的位置一律当空白（CommonMark 对行首/行尾的处理） */
function charAt(text: string, index: number): string {
  return index < 0 || index >= text.length ? '' : text[index]
}

const isWhitespace = (c: string): boolean => c === '' || WHITESPACE.test(c)
const isPunctuation = (c: string): boolean => c !== '' && PUNCTUATION.test(c)
/** 「CJK 词字符」= CJK 区里的非标点（汉字/假名/谚文；`「」（）` 这类中文标点不算） */
const isCjkWord = (c: string): boolean => c !== '' && CJK_ZONE.test(c) && !isPunctuation(c)

interface DelimiterRun {
  start: number
  end: number
  ch: string
  len: number
}

/** 扫描 `*` / `_` / `~` 的连续段（`*`/`_` 1~3 个、`~` 恰好 2 个才可能是强调；4+ 个如掩码 `****` 直接跳过） */
function scanRuns(segment: string): DelimiterRun[] {
  const runs: DelimiterRun[] = []
  const re = /\*+|_+|~+/g
  let match: RegExpExecArray | null
  while ((match = re.exec(segment)) !== null) {
    const len = match[0].length
    if (match[0][0] === '~' ? len !== 2 : len > 3) continue
    runs.push({ start: match.index, end: match.index + len, ch: match[0][0], len })
  }
  return runs
}

/** CommonMark「左 flanking」= 这一段能不能**开** */
function canOpen(segment: string, run: DelimiterRun): boolean {
  const before = charAt(segment, run.start - 1)
  const after = charAt(segment, run.end)
  return !isWhitespace(after) && (!isPunctuation(after) || isWhitespace(before) || isPunctuation(before))
}

/** CommonMark「右 flanking」= 这一段能不能**闭** */
function canClose(segment: string, run: DelimiterRun): boolean {
  const before = charAt(segment, run.start - 1)
  const after = charAt(segment, run.end)
  return !isWhitespace(before) && (!isPunctuation(before) || isWhitespace(after) || isPunctuation(after))
}

/** 本单要修的那两种形态：`汉字**「` （不能开）与 `」**汉字`（不能闭） */
const brokenOpen = (segment: string, run: DelimiterRun): boolean =>
  !canOpen(segment, run) && isCjkWord(charAt(segment, run.start - 1)) && isPunctuation(charAt(segment, run.end))

const brokenClose = (segment: string, run: DelimiterRun): boolean =>
  !canClose(segment, run) && isPunctuation(charAt(segment, run.start - 1)) && isCjkWord(charAt(segment, run.end))

/** 单段（不含代码面）的归一化：只给配对里「做不到本职」的那一侧插 ZWSP */
function normalizeSegment(segment: string): string {
  const runs = scanRuns(segment)
  if (runs.length < 2) return segment
  const insertBefore = new Set<number>()
  const insertAfter = new Set<number>()
  const openers: DelimiterRun[] = []
  for (const run of runs) {
    const opens = canOpen(segment, run) || brokenOpen(segment, run)
    const closes = canClose(segment, run) || brokenClose(segment, run)
    const top = openers[openers.length - 1]
    if (closes && top && top.ch === run.ch && top.len === run.len) {
      openers.pop()
      if (!canOpen(segment, top)) insertAfter.add(top.end)
      if (!canClose(segment, run)) insertBefore.add(run.start)
    } else if (opens) {
      openers.push(run)
    }
  }
  if (insertBefore.size === 0 && insertAfter.size === 0) return segment
  let out = ''
  for (let i = 0; i < segment.length; i++) {
    if (insertBefore.has(i)) out += ZWSP
    out += segment[i]
    if (insertAfter.has(i + 1)) out += ZWSP
  }
  return out
}

const FENCE = /^\s{0,3}(`{3,}|~{3,})/

/**
 * 按「代码面」切分后逐段归一化：围栏代码块（``` / ~~~，按行状态跟踪）与行内代码（`` `…` ``）**逐字返回**。
 * 行内代码用 `split` 的捕获组切分 ⇒ 偶数下标是普通文本、奇数下标是代码段（不动）。
 */
function mapOutsideCode(text: string, fn: (plain: string) => string): string {
  let fenceChar = ''
  let fenceLen = 0
  return text
    .split('\n')
    .map((line) => {
      const open = FENCE.exec(line)
      if (fenceChar) {
        const closing = new RegExp('^\\s{0,3}\\' + fenceChar + '{' + fenceLen + ',}\\s*$')
        if (closing.test(line)) {
          fenceChar = ''
          fenceLen = 0
        }
        return line
      }
      if (open) {
        fenceChar = open[1][0]
        fenceLen = open[1].length
        return line
      }
      return line
        .split(/(`+[^`]*`+)/g)
        .map((part, index) => (index % 2 === 0 ? fn(part) : part))
        .join('')
    })
    .join('\n')
}

/**
 * 把中文标点旁「配不上对」的强调标记归一化成 CommonMark 认得的形态。
 *
 * **不改变可见文本**（只插不可见的 U+200B），因此可以直接替换 `ReactMarkdown` 的 children 入参；
 * 复制按钮走的仍是**原始**内容（`MessageList` 的 `cleanContent`），不受影响。
 */
export function normalizeCjkEmphasis(text: string): string {
  if (!text || (!text.includes('*') && !text.includes('_') && !text.includes('~'))) return text
  return mapOutsideCode(text, normalizeSegment)
}

export default normalizeCjkEmphasis
