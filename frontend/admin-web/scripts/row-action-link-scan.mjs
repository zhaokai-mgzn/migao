#!/usr/bin/env node
// case_ids: MC-151
/**
 * 「单据列表行内动作的链接规格**只有一处定义**」判据**单一源**（issue #7082）。
 *
 * ## 为什么要有它（而不是把四处手改完就完）
 *
 * 2026-10-17 用户裁定「行内按钮样式让全部单据统一向订单保持一致，不要有多种风格设计」之后，
 * 共享原语 `src/components/ui/RowActionLink.tsx` 有了，但**同一份视觉规格的字面量**仍在几处
 * 各抄一份（售后 / 员工 / 员工资料面板 / 加工项面板 …）。抄一份 = 第二份会漂的口径
 * （原语改一次、副本不跟 ⇒ 两步之后没人知道哪个才是"对的"）。
 * ⇒ 本文件把 issue #7082 的判据 ② 落成**扫描器**：
 * 规格 token 串在 `src/**` 里**只许出现在原语自己身上**，副本必须**登记**（台账）或**已迁移**。
 *
 * ## 判的是什么（口径）
 *
 * 「链接规格」= 同一个类名串里**同时**含 `text-primary-600` + `hover:text-primary-700` + `hover:underline`
 * （= 原语可用态的视觉规格）—— **token 集合**比对，不是逐字节子串比对。
 * 这是对 issue 原文（「`text-primary-600 hover:text-primary-700 hover:underline transition-colors`
 * 这一串只允许出现一次」）的**一点收紧**：逐字节比对会漏掉四个迁移点里的三个
 * （它们各自带 `text-sm` / `text-xs` / `transition-colors` 且**词序不同**）⇒ 那条判据按字面实现是
 * **空断言**（实测：现取只命中 `after-sales` 一处 + 原语）。收紧后同一判据命中全部副本。
 *
 * ## 判据（各自独立红）
 *
 * ① **未登记即红**：出现规格副本且既不是已迁移文件、也不在 `exempt` 台账 ⇒ 红（具名文件 + 行）；
 * ② **回退即红**：台账 `migrated` 的文件里**又**出现规格副本（= 迁回手抄）⇒ 红；
 * ③ **接线在**：`migrated` 的文件必须逐字含 `<RowActionLink` 且含登记的变体 prop
 *    （`size="sm"` 这类）—— 把整段动作删掉 / 改回裸类名都会让「副本消失」变成假绿，这条堵掉；
 * ④ **台账只许缩短**：`exempt` 条数 > `frozen_exempt_count` ⇒ 红；条目**已不再命中** ⇒ 僵尸红（逼着删）；
 * ⑤ **形态台账不撒谎**：`conformant`（有意**不**走本组件的行内动作）必须在位：
 *    要求锚 `required_anchor` 在、`forbidden_anchor` 不在 ⇒ 「悄悄改成 RowActionLink 却没改台账」当场红；
 * ⑥ **原语自证**（fail-closed）：原语文件必须真的含这三个 token（否则扫描面是空的 ⇒ 恒绿假绿）；
 * ⑦ **射程非空**：扫到的源文件数 < 50 ⇒ 红（root 走错 / 目录改名时不许静默通过）。
 *
 * ## 射程与边界（照实登记，`migao-dev-flow` §19.1）
 *
 * - 只扫 `frontend/admin-web/src/**`（`mini-app` / H5 不在面内，各自一套 token）；
 * - 🔴 **只裁「与原语同规格」的副本**：缺 `hover:text-primary-700` 的**漂移副本**（如
 *   `purchase-orders` / `suppliers` 的行内链接 `text-primary-600 hover:underline`）**不在面内** ——
 *   它们已经不是同一份规格，收口要先逐页裁定形态（`RowActions` 还是 `RowActionLink`），不是本单能一刀切的；
 * - 静态文本判据：判不了「渲染出来是否同色同字号」（那是原语自己的判据
 *   `tests/unit/components/RowActionLink.test.tsx` 的变体断言 + 真机读图）；
 * - 判不了「新页面拿 `Button` 手拼了一个行内动作」（形态判据说不了意图）—— 那一半由
 *   `row-action-flat-scan.mjs`（操作列不得折叠成「⋯」）与评审承担。
 */
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

/** 共享原语（唯一允许出现规格串的地方） */
export const PRIMITIVE = 'src/components/ui/RowActionLink.tsx'

/** 链接规格的 token 集合（同时命中才算同一份规格） */
export const SPEC_TOKENS = ['text-primary-600', 'hover:text-primary-700', 'hover:underline']

/** 射程 */
export const SCAN_DIR = 'src'
const SKIP_DIRS = new Set(['node_modules', '.next', 'dist', 'coverage', '__snapshots__'])

/** 台账落点（相对 frontend/admin-web） */
export const LEDGER_PATH = 'tests/unit/row-action-link-ledger.json'

/** 扫描面下限（fail-closed：目录改名 / root 走错 ⇒ 红，而不是"零命中 = 通过"） */
export const MIN_SCOPE_FILES = 50

/** 默认 root = `frontend/admin-web`（本文件在 `scripts/` 下） */
export function defaultRoot() {
  return join(dirname(fileURLToPath(import.meta.url)), '..')
}

/** 去掉注释（注释里写「改前长这样」不该判红 —— 迁移说明必须能写字） */
export function stripComments(text) {
  return text.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '')
}

/** 类名串（单/双引号单行 + 反引号可跨行） */
const CLASS_STRING_RE = /'[^'\n]*'|"[^"\n]*"|`[^`]*`/g

function lineOf(code, index) {
  let line = 1
  for (let i = 0; i < index && i < code.length; i += 1) if (code[i] === '\n') line += 1
  return line
}

/**
 * 纯函数：给定 `{ 相对路径: 源码 }` ⇒ `{ 相对路径: [{line, classString}] }`。
 * **原语自身不进射程**（负控：它的 class 串就是判据比对的基准，扫它等于恒红）。
 */
export function specCopiesIn(sources) {
  const found = {}
  for (const [rel, text] of Object.entries(sources)) {
    if (rel === PRIMITIVE) continue
    const code = stripComments(text)
    const hits = []
    CLASS_STRING_RE.lastIndex = 0
    let m
    while ((m = CLASS_STRING_RE.exec(code))) {
      const value = m[0]
      if (!SPEC_TOKENS.every((t) => value.includes(t))) continue
      hits.push({ line: lineOf(code, m.index), classString: value })
    }
    if (hits.length) found[rel] = hits
  }
  return found
}

/** 读目录（`src/**` 下的 .ts / .tsx），键 = 相对 root 的路径（正斜杠） */
export function readSources(root = defaultRoot()) {
  const sources = {}
  const walk = (abs, rel) => {
    for (const entry of readdirSync(abs)) {
      if (SKIP_DIRS.has(entry)) continue
      const absChild = join(abs, entry)
      const relChild = `${rel}/${entry}`
      if (statSync(absChild).isDirectory()) walk(absChild, relChild)
      else if (entry.endsWith('.ts') || entry.endsWith('.tsx')) {
        sources[relChild] = readFileSync(absChild, 'utf-8')
      }
    }
  }
  walk(join(root, SCAN_DIR), SCAN_DIR)
  return sources
}

export function loadLedger(root = defaultRoot()) {
  return JSON.parse(readFileSync(join(root, LEDGER_PATH), 'utf-8'))
}

/**
 * 取出某个组件的**开标签**全文（跨行、跳过字符串里的 `>`、用括号深度跳过 `=>` 与表达式）。
 *
 * 为什么不能用 `<RowActionLink[\s\S]*?>`：箭头函数里的 `=>` 也含 `>` ⇒ 正则会在 `onClick={() =>
 * handleEdit(record)}` 处**提前截断**，于是「tag 里有没有这个 prop」这类判据全部失准（会假绿）。
 */
export function openingTags(text, component) {
  const tags = []
  const re = new RegExp(`<${component}\\b`, 'g')
  let m
  while ((m = re.exec(text))) {
    let depth = 0
    let quote = null
    for (let i = m.index + m[0].length; i < text.length; i += 1) {
      const ch = text[i]
      if (quote) {
        if (ch === quote && text[i - 1] !== '\\') quote = null
        continue
      }
      if (ch === '"' || ch === "'" || ch === '`') quote = ch
      else if (ch === '{' || ch === '(' || ch === '[') depth += 1
      else if (ch === '}' || ch === ')' || ch === ']') depth -= 1
      else if (ch === '>' && depth === 0) {
        tags.push(text.slice(m.index, i + 1))
        re.lastIndex = i + 1
        break
      }
    }
  }
  return tags
}

/**
 * 「接线在」的**逐处**读数：每个迁移点必须能在同一个开标签里同时找到
 * `requires` 里的全部 prop 串 + `marker`（该调用点唯一的一句话）。
 *
 * 🔴 为什么按**同一个开标签**判（而不是"文件里有 `<RowActionLink`"）：实测踩过 ——
 * 员工页本来就有另一处 `<RowActionLink>`（操作列的「编辑」）⇒ 文件级判据在
 * 「把姓名格的接线整段摘掉」时**照样绿**（这就是 §28.2 的「判据绿 ≠ 接线在」）。
 * 另：注释也**先剥掉**再找（实测：迁移说明里写了 `disabledStyle="keep"`，够让文件级判据假绿）。
 */
export function wiringGaps(sources, migrated) {
  return migrated.filter((m) => {
    const text = sources[m.file]
    if (!text) return true
    const code = stripComments(text)
    return !openingTags(code, 'RowActionLink').some(
      (tag) =>
        (m.requires ?? []).every((needle) => tag.includes(needle)) &&
        (m.marker ? tag.includes(m.marker) : true),
    )
  })
}

/**
 * 一次取全部读数，返回**每类红各自一条**（守卫逐条断言，命令行逐条打印）。
 * 纯读：不写盘、不联网。
 */
export function audit(root = defaultRoot()) {
  const sources = readSources(root)
  const ledger = loadLedger(root)
  const copies = specCopiesIn(sources)
  const migrated = ledger.migrated ?? []
  const exempt = ledger.exempt ?? []
  const conformant = ledger.conformant ?? []

  const exemptFiles = new Set(exempt.map((e) => e.file))
  const migratedFiles = new Set(migrated.map((m) => m.file))

  return {
    scopeFiles: Object.keys(sources).length,
    copies,
    // ① 未登记即红（已迁移文件另有 ② 的单条读数，便于归因）
    unregistered: Object.keys(copies).filter((f) => !exemptFiles.has(f) && !migratedFiles.has(f)),
    // ② 已迁移又出现副本 = 迁回手抄
    regressed: [...migratedFiles].filter((f) => copies[f]),
    // ③ 接线在（**同一个开标签**里：组件 + 该处变体 prop + 该调用点 marker）
    wiringMissing: wiringGaps(sources, migrated),
    // ④ 僵尸豁免 / 超基线
    staleExempt: exempt.filter((e) => !copies[e.file]),
    exemptOverBaseline: exempt.length - (ledger.frozen_exempt_count ?? 0),
    // ⑤ 形态台账不撒谎（**双读**：禁止锚不在 + 要求形态在）
    //    - 禁止锚（`forbidden_anchors`）：出现即红 —— 悄悄改成原语形态却不改台账；
    //    - 要求形态（`forms`）：每个形态都要能在**同一个开标签**里同时找到 marker 与 requires。
    //      只判「某个字符串在文件里」是不够的：同一文件里往往还有别的同名组件（实测）。
    conformantBroken: conformant.filter((c) => {
      const text = sources[c.file]
      if (!text) return true
      const code = stripComments(text)
      if ((c.forbidden_anchors ?? []).some((needle) => code.includes(needle))) return true
      return (c.forms ?? []).some(
        (f) =>
          !openingTags(code, f.component).some(
            (tag) =>
              tag.includes(f.marker) && (f.requires ?? []).every((needle) => tag.includes(needle)),
          ),
      )
    }),
    // ⑥ 原语自证
    primitiveBlind: !sources[PRIMITIVE] || !SPEC_TOKENS.every((t) => sources[PRIMITIVE].includes(t)),
    migrated,
    exempt,
    conformant,
  }
}

/** 任一类红 ⇒ 返回条数（命令行退出码据此；0 = 绿） */
export function redCount(report) {
  return (
    report.unregistered.length +
    report.regressed.length +
    report.wiringMissing.length +
    report.staleExempt.length +
    Math.max(0, report.exemptOverBaseline) +
    report.conformantBroken.length +
    (report.primitiveBlind ? 1 : 0) +
    (report.scopeFiles < MIN_SCOPE_FILES ? 1 : 0)
  )
}

const isMain = process.argv[1] && import.meta.url.endsWith(process.argv[1].split('/').pop())
if (isMain) {
  const report = audit(process.env.MIGAO_SCAN_ROOT || defaultRoot())
  console.log(
    `扫描 ${report.scopeFiles} 个源文件 · 规格副本 ${Object.keys(report.copies).length} 处 ` +
      `（已迁移 ${report.migrated.length} / 豁免 ${report.exempt.length} / 有意不走原语 ${report.conformant.length}）\n`,
  )
  for (const [file, hits] of Object.entries(report.copies)) {
    const mark = report.regressed.includes(file) ? '❌ 回退（已迁移却又手抄）' : '📒 已豁免'
    console.log(`  ${mark}  ${file}`)
    for (const h of hits) console.log(`      L${h.line}: ${h.classString}`)
  }
  if (report.unregistered.length) console.log(`\n❌ 未登记即红：${report.unregistered.join('、')}`)
  if (report.regressed.length) console.log(`❌ 迁移回退：${report.regressed.join('、')}`)
  if (report.wiringMissing.length)
    console.log(`❌ 接线缺失：${report.wiringMissing.map((m) => m.file).join('、')}`)
  if (report.staleExempt.length)
    console.log(`❌ 僵尸豁免（已不再命中，请删）：${report.staleExempt.map((e) => e.file).join('、')}`)
  if (report.exemptOverBaseline > 0) console.log(`❌ 豁免超基线：${report.exemptOverBaseline} 条（只许缩短）`)
  if (report.conformantBroken.length)
    console.log(`❌ 形态台账不实：${report.conformantBroken.map((c) => c.file).join('、')}`)
  if (report.primitiveBlind) console.log('❌ 原语自证失败：原语里找不到规格 token（扫描面为空 = 假绿）')
  if (report.scopeFiles < MIN_SCOPE_FILES)
    console.log(`❌ 射程可疑：只扫到 ${report.scopeFiles} 个文件（< ${MIN_SCOPE_FILES}）`)
  const red = redCount(report)
  console.log(red ? `\n结论：❌ ${red} 类/条判红` : '\n结论：✅ 行内动作链接规格只有一处定义')
  process.exit(red ? 1 : 0)
}
