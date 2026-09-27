/**
 * 「调用点级」射程的**共享读法**（issue #5052 验收 D7 修复；AGENTS.md 铁律 8「类级固化」）
 *
 * ## 治的形态：不变式停在**文件/字符串级**，同文件旁路恒绿
 *
 * 两条"最贵的红线"（① 只有一个函数能送数据给打印机 ② 新开一处绕过码空间门禁的详情查询）
 * 原来的判据都只做到文件级/字符串级：
 * ① `inbound-print-channel` 的源码扫描射程 = `src/utils/inbound`，**页面不在射程** ⇒ 页面里
 *    加一条直连 `transport.print()`（不留痕）时 13/13 全绿；
 * ② `inbound-reprint-code-space` 的 G2 只比对 `LABEL_DETAIL_CALLERS` 的**文件集合** ⇒
 *    在**已登记文件**里新加一处绕过门禁的调用仍然 20/20 绿。
 *
 * ⇒ 本文件把「调用点」抽成一个可复用的读法：`<文件>::<所在函数>`，
 * 于是判据能从"这个文件里有这个词"升级到"**这一处**调用在哪里、由谁兜着"。
 *
 * ## 边界（不要把本读法读成 AST 级解析）
 *
 * 它是**基于行首声明的近似**：认 `function NAME(` / `const NAME = (…) =>` / `const NAME = useCallback(…)`
 * 三种定义形态，作用域 = 到**下一个同类声明**为止。够用即可：判据要的是"这个调用落在哪个函数里"，
 * **宁可把作用域判大**（少报），也不要把同一函数里的调用判成别人的（假红）。
 * 写成共享件而不是各判据各抄一份：射程两处各抄一份 = 第二份必漂（本仓明令禁止）。
 */

/** 一个函数（或具名 `const` 箭头）在源码里的位置与范围 */
export interface FnSpan {
  name: string
  start: number
  end: number
}

/** 一个调用点在源码里的位置与**所在函数**（`''` = 不在任何具名函数里） */
export interface CallSite {
  index: number
  fn: string
  /** 所在函数的源码片段（不在具名函数里时 = 从文件开头到调用点） */
  span: string
}

/** 定义形态：`function NAME(` / `const NAME = (…) =>` / `const NAME = useCallback(…)` */
const DECL_RE =
  /(?:^|\n)[ \t]*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(|\n[ \t]*(?:export\s+)?const\s+([A-Za-z_$][\w$]*)\s*(?::[^=\n]*)?=\s*(?:useCallback\(|useMemo\(|useEffect\(|useRef\()?\s*(?:async\s*)?(?:\(|function)/g

/** 全文件的函数声明（按出现顺序） */
export function functionSpans(code: string): FnSpan[] {
  const spans: FnSpan[] = []
  for (const match of code.matchAll(DECL_RE)) {
    const name = match[1] || match[2]
    if (!name) continue
    // 声明起点 = 名字之前的换行 + 缩进（不是整个 match，match 里带着前导 `\n` 与缩进）
    spans.push({ name, start: match.index + match[0].indexOf(name), end: code.length })
  }
  for (let i = 0; i < spans.length - 1; i += 1) spans[i].end = spans[i + 1].start
  return spans
}

/** 某个字符位置落在哪个函数里（取**最后一个**起点在它之前的声明） */
export function enclosingSpan(code: string, index: number): FnSpan | null {
  let hit: FnSpan | null = null
  for (const span of functionSpans(code)) {
    if (span.start <= index) hit = span
    else break
  }
  return hit
}

/**
 * 抽调用点：`pattern` 带 `g` 且**只匹配调用形态本身**（如 `/\.print\s*\(/g`）。
 * `skipDefinitions` = 命中处紧邻 `function ` 时跳过（那是**定义**不是调用）。
 */
export function callSites(code: string, pattern: RegExp, options: { skipDefinitions?: boolean } = {}): CallSite[] {
  const out: CallSite[] = []
  for (const match of code.matchAll(pattern)) {
    const index = match.index || 0
    if (options.skipDefinitions && /function\s+$/.test(code.slice(0, index))) continue
    const span = enclosingSpan(code, index)
    out.push({
      index,
      fn: span ? span.name : '',
      span: code.slice(span ? span.start : 0, span ? span.end : index),
    })
  }
  return out
}

/**
 * 「这个调用点真的会被执行吗」的近似判定（issue #5052 验收 D3）。
 *
 * 认三种**可执行**形态：① 落在组件里（大写开头，宿主会渲染它）；② 落在 hook 名里（`use*`）；
 * ③ 落在具名函数里，而该名字在**文件内**至少出现两次（定义 + 至少一处调用）。
 * 其余（例：把 `Taro.redirectTo` 挪进一个**没人调用**的导出函数、字面量都还在）判为**不可达**。
 *
 * ⚠️ 边界：跨文件调用（A 文件定义、B 文件调用）本读法看不见 ⇒ 具名函数的 `reachableBy`
 * 由台账显式登记（见 `src/utils/pageEntries.ts` 的 `reachableBy` 字段），不做"猜"。
 */
export function reachableFromSpan(code: string, call: CallSite): boolean {
  if (!call.fn) return true
  if (/^[A-Z]/.test(call.fn)) return true
  if (/^use[A-Z]/.test(call.fn)) return true
  const references = code.match(new RegExp(`\\b${call.fn}\\b`, 'g')) || []
  return references.length >= 2
}
