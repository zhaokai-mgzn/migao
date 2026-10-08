// case_ids: UI-094
/**
 * 类级元守卫（issue #6552）：**服务端的机器键不得被当展示文本上屏**。
 *
 * 病根（两个现场，同一族，都是**被人 / 真机截图撞见**才修的）：
 *   · `frontend/admin-web/src/app/(dashboard)/production/pool/page.tsx`（#6523）——
 *     「可合并的待派订单（按料分组）」的组标题原样渲染 `PoolGroup.materialKey`（= `productId|skuCode`，
 *     productId 是 UUID）⇒ 真机看到 `a61daac33e1a49974577d3ca81c4500b|SD07演示-2.8-8141273`；
 *   · `frontend/admin-web/src/app/(dashboard)/production/saving-board/page.tsx`（#6535）——
 *     省料看板「省下多少」表的「物料」列原样渲染 `SavedGroup.materialKey`（同一个键，换了一个 DTO）。
 * 两处都已按「展示名与标识分家」修好（服务端下发 `materialLabel`，`materialKey` 一字不改、
 * 只继续承载 React `key` / `data-testid` / 分组判据）。
 *
 * 为什么还要这个守卫：本仓唯一的跨页面**上屏**类级收口是
 * `frontend/admin-web/scripts/user-copy-scan.mjs`，它的 `candidateStrings()` **只抽字面量**
 * （JSX 文本节点 / 白名单属性 / 含中文的字符串与模板串）⇒ `{group.materialKey}` 这种
 * **JSX 表达式渲染**整段在它射程之外 ⇒ 第三处同类缺陷**不会有任何东西变红**。
 *
 * ## 判的是「机器键被当文本渲染」，不是「渲染了变量」
 *
 * 判定对象 = **JSX 文本位**（元素子节点位置）里的表达式 —— **属性位不算**：
 * `key={…materialKey}` / `data-testid={…materialKey}` / `href` / `value` / `title` 是机器键的
 * **合法承载面**（#6523 / #6535 的修复正是把 `materialKey` 留在这两处、只换展示文本）。
 *
 * 命中形态（**只收服务端机器键这一族**）：文本位里的**纯成员链**（`x` / `a.b` / `a?.b`）
 * 末端标识符以**小写驼峰**命中 `*Key` / `*Uuid` / `*Hash` / `*Token`，或正好叫
 * `hash` / `token` / `uuid` —— 即「机器算出来的复合键 / 内部标识」的命名指纹。
 *
 * 🔴 为什么**不**一把梭收所有 `*Key`：`composition_key`（snake_case）、`OTHER_KEY`（全大写常量）、
 * `p.key` / `{key}`（字典键）、`itemKey`（**内容本身**）都不是机器键 ——「小写驼峰 + Key」这条
 * 结构约束把它们放行，判别力用例逐条钉住。`itemKey` / `composition_key` **确实出现在文本位**，
 * 所以进 `HUMAN_KEY_WHITELIST` 显式登记（**只许缩短**：条目必须仍出现在语料里，死条目即红）。
 *
 * ## 假绿教训（issue 里逐字，写进判据设计）
 *
 * 发现 #6535 的那次扫描，第一版正则要求表达式**在行首**（`^\s*\{x\.Key\}`）⇒ 对
 * `<span …>{group.materialKey}</span>` 这种**同行**形态给出「0 处命中」的假绿。
 * ⇒ 本判据的**发现面**用 TypeScript AST 取「子节点位置的表达式」：**不看行首、不看同行**、
 * 也不要求 `>{` 紧跟 —— 同行 / 独占一行 / 跨行表达式都在面内（判别力用例把行首锚定那条
 * 坏形态明确判红）。
 *
 * ## 空集必须显式断言 + 扫描面必须自证活着
 *
 * 现在违例是**空集**（两处都已修）⇒ 只写「扫到 0 条 ⇒ expect([])」是**假绿**：
 * 扫描面坏掉（目录搬了 / AST 口径改了 / 规则被删空）也照样绿。所以下面逐条钉：
 * ① 文件数与文本位表达式数下限（扫空气 ⇒ 红）；② 已知对象在场（两个现场页面必须在语料里，
 * 且它们**仍然**在用 `materialKey`，证明坐标系里有被测对象）；③ 规则表不许被删空；
 * ④ 注入式对照 —— 把 #6523 / #6535 的**历史形态逐字**写进 `src/` 里再扫 ⇒ 必红，删掉 ⇒ 回到空集；
 * ⑤ 把扫描面 / 规则弄坏 ⇒ 门禁口径（文件数下限 + 空集断言）必须红。
 *
 * ## 边界（照实登记，有意不判 / 判不了）
 *
 *   · **属性位不判**：那是合法承载面（见上）。
 *   · **不重复 `user-copy-scan.mjs` 的字面量射程**：字符串 / 模板串里的文案由 UI-093 守；
 *     本守卫只判**表达式**（`{"materialKey"}`、`t("materialKey")` 不在面内）。
 *   · **`id` / `code` / `orderNo` 这类正常业务字段不判** —— 不是「什么变量都不能渲染」的宽泛规则。
 *   · **元素访问（`x['materialKey']`）、函数调用（`x.getMaterialKey()`）、模板串插值
 *     （`` `${x.materialKey}` ``）不在面内**：本仓 0 处；要收就是另一条规则（须另开单），
 *     不是本守卫放水。
 *   · **机器键嵌在三元 / 逻辑 / 调用里**（`{ok ? row.materialKey : '—'}`）**不在面内**：
 *     本判据只收「文本位**整个表达式就是一条成员链**」（#6523 / #6535 的真实形态）。
 *     这条边界在判别力自证①里被**钉成断言**（两边都断言）—— 扩面必须先显式改它。
 *   · **判不了「这个值此刻是不是人话」**：若服务端把机器键装进一个不带机器键指纹的字段名
 *     （如 `display`），本判据看不见 ⇒ 那一半只能靠 `migao-dev-flow` §31 P3 的评审与人肉眼。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync, writeFileSync, unlinkSync, existsSync, mkdirSync, rmdirSync } from 'node:fs'
import { join, relative, sep } from 'node:path'
import ts from 'typescript'

const ROOT = process.cwd()
const SRC_DIR = join(ROOT, 'src')

// ───────────────────────── 规则（纯函数，可内存注入取证） ─────────────────────────

/** 末端标识符里的「小写驼峰段」：`materialKey` 的 `material` 部分。 */
const CAMEL = '[a-z][A-Za-z0-9]*'

/**
 * 机器键形态（**只收服务端机器键这一族**）：
 * 小写驼峰 `*Key` / `*Uuid` / `*Hash` / `*Token`，或正好叫 `hash` / `token` / `uuid`。
 * 结构约束（`[a-z]…Key` 必须连续）天然放行 `composition_key`（`_` 打断）/ `OTHER_KEY`（全大写）。
 */
export const MACHINE_KEY_RULES: Array<{ id: string; desc: string; test: RegExp }> = [
  { id: 'MK-compound-key', desc: '复合键 `*Key`（如 materialKey）', test: new RegExp(`(?:^|\\.)${CAMEL}Key$`) },
  { id: 'MK-uuid', desc: 'UUID 字段 `*Uuid` / 裸 `uuid`', test: new RegExp(`(?:^|\\.)${CAMEL}Uuid$|(?:^|\\.)uuid$`) },
  { id: 'MK-hash', desc: '哈希字段 `*Hash` / 裸 `hash`', test: new RegExp(`(?:^|\\.)${CAMEL}Hash$|(?:^|\\.)hash$`) },
  { id: 'MK-token', desc: '令牌字段 `*Token` / 裸 `token`', test: new RegExp(`(?:^|\\.)${CAMEL}Token$|(?:^|\\.)token$`) },
]

/**
 * 已确认为**人话 / 内容本身**的 `*Key` 名字（**只许缩短**）：每条都必须在语料里**仍然**
 * 出现（死条目即红，逼着删干净）；当前两条都是实测的合法现存形态。
 */
export const HUMAN_KEY_WHITELIST: string[] = [
  // 小件用料尺寸表的**工序名**（= 内容本身：`src/types/index.ts` 逐字「itemKey = 该小件对应的工序名」），
  // 文本位实测 2 处：`src/app/(dashboard)/production/remnants/page.tsx`（推荐行 + 未匹配行）
  'itemKey',
  // 省料镜头的组合口径常量（人话标签，非服务端机器键）
  'composition_key',
]

/** 末端标识符是不是「服务端机器键」（白名单优先）；是 ⇒ 返回命中的规则 id。 */
export function isMachineKeyName(name: string): string | null {
  if (HUMAN_KEY_WHITELIST.includes(name)) return null
  const hit = MACHINE_KEY_RULES.find((r) => r.test.test(`.${name}`))
  return hit ? hit.id : null
}

/** 一个表达式是不是**纯成员链**（`x` / `a.b` / `a?.b` / `a!.b` / `(a.key)`）；不是 ⇒ 交给子节点递归。 */
function isMemberChain(node: ts.Node): boolean {
  return (
    ts.isPropertyAccessExpression(node) ||
    ts.isIdentifier(node) ||
    ts.isNonNullExpression(node) ||
    (ts.isParenthesizedExpression(node) && isMemberChain(node.expression))
  )
}

/** 取成员链的**末端标识符**（`a.b.c` ⇒ `c`）；非纯成员链 ⇒ null。 */
export function chainTailName(text: string): string | null {
  const t = text.trim()
  if (!/^[A-Za-z_$][\w$]*(?:[?!]?\.[A-Za-z_$][\w$]*)*$/.test(t)) return null
  const parts = t.split('.')
  return parts[parts.length - 1].replace(/[?!]/g, '')
}

/** 一条命中：**文件相对路径 + 行号（供归因）+ 表达式文本 + 命中的规则 id**。 */
export interface MachineKeyFinding {
  file: string
  line: number
  expr: string
  rule: string
}

/**
 * 规则本体（纯函数、不含文件 IO）：扫一份 TSX 源码的 **JSX 文本位**里渲染的成员链。
 *
 * 面 = **元素子节点位置**的 `{expr}`（同行 / 独占一行 / 跨行都不影响 —— AST 决定，不看行首）；
 * 属性位（`key=` / `data-testid=` / …）**整支跳过**。
 * `rules` 可注入（判别力自证用「射程为空的规则表」证明规则真的在起决定作用）。
 */
export function scanJsxMachineKeys(
  fileName: string,
  source: string,
  rules: Array<{ id: string; test: RegExp }> = MACHINE_KEY_RULES,
): MachineKeyFinding[] {
  const sf = ts.createSourceFile(fileName, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
  const line0 = (pos: number) => sf.getLineAndCharacterOfPosition(pos).line + 1
  const out: MachineKeyFinding[] = []
  const visit = (node: ts.Node) => {
    if (ts.isJsxExpression(node) && node.expression && !ts.isJsxAttribute(node.parent)) {
      const expr = node.expression
      if (isMemberChain(expr)) {
        const text = source.slice(expr.getStart(sf), expr.getEnd())
        const name = chainTailName(text)
        if (name && !HUMAN_KEY_WHITELIST.includes(name)) {
          const hit = rules.find((r) => r.test.test(`.${name}`))
          if (hit) out.push({ file: fileName, line: line0(node.getStart(sf)), expr: text, rule: hit.id })
        }
      }
    }
    ts.forEachChild(node, visit)
  }
  visit(sf)
  return out
}

/**
 * 扫描面存活读数（**不被规则影响**，用来证明「扫描面是活的」而不是「规则恰好没命中」）：
 * 数这份源码里 JSX 文本位的表达式总数。
 */
export function countJsxTextExpressions(source: string, fileName = 'x.tsx'): number {
  const sf = ts.createSourceFile(fileName, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
  let n = 0
  const visit = (node: ts.Node) => {
    if (ts.isJsxExpression(node) && node.expression && !ts.isJsxAttribute(node.parent)) n += 1
    ts.forEachChild(node, visit)
  }
  visit(sf)
  return n
}

// ───────────────────────── 扫描面（`src/**/*.tsx`，每次都现取） ─────────────────────────

function walkTsx(dir: string): string[] {
  const out: string[] = []
  for (const name of readdirSync(dir)) {
    const full = join(dir, name)
    if (statSync(full).isDirectory()) out.push(...walkTsx(full))
    else if (name.endsWith('.tsx')) out.push(full)
  }
  return out
}

export interface Corpus {
  files: Array<{ path: string; source: string }>
  textExprs: number
  findings: MachineKeyFinding[]
}

/** 现取语料 + 现取违例（**每次调用都重新读盘**：注入式对照就靠这个）。 */
export function scanCorpus(srcDir: string = SRC_DIR): Corpus {
  const files = walkTsx(srcDir).map((full) => ({
    path: relative(ROOT, full).split(sep).join('/'),
    source: readFileSync(full, 'utf-8'),
  }))
  const findings = files.flatMap((f) => scanJsxMachineKeys(f.path, f.source))
  const textExprs = files.reduce((n, f) => n + countJsxTextExpressions(f.source, f.path), 0)
  return { files, textExprs, findings }
}

/** 台账键：`<文件相对路径>::<渲染的表达式>`（**不写行号** —— 行号会漂）。 */
export const findingKey = (f: MachineKeyFinding) => `${f.file}::${f.expr.trim()}`

/** 门禁口径（纯函数）：扫描面下限没到 ⇒ 报红（返回原因串）；否则返回未登记违例。 */
export function guardViolations(corpus: Corpus): string[] {
  const problems: string[] = []
  if (corpus.files.length < MIN_FILES) {
    problems.push(`扫描面只有 ${corpus.files.length} 个 tsx（下限 ${MIN_FILES}）⇒ 判据在扫空气`)
  }
  if (corpus.textExprs < MIN_TEXT_EXPRS) {
    problems.push(`JSX 文本位表达式只有 ${corpus.textExprs} 个（下限 ${MIN_TEXT_EXPRS}）⇒ 发现面已漂`)
  }
  problems.push(...corpus.findings.map(findingKey).sort())
  return problems
}

const CORPUS = scanCorpus()
const OFFENDERS = CORPUS.findings.map(findingKey).sort()

/** 扫描面下限（现取读数的保守七折；掉到线下 = 扫描面漂了 ⇒ 红，不许静默变绿） */
const MIN_FILES = 100
const MIN_TEXT_EXPRS = 1500

/** 机器键的两个现场页面（本判据的坐标系锚点）。 */
const MATERIAL_KEY_FILES = [
  'src/app/(dashboard)/production/pool/page.tsx',
  'src/app/(dashboard)/production/saving-board/page.tsx',
]

// ───────────────────────── 历史形态（#6523 / #6535 的**真实语料**） ─────────────────────────

/**
 * 两个现场修复前的**逐字源码行**（`git show <修复提交>^:<path>` 取回，即修复前形态）。
 * 注入式对照直接拿它当语料 —— 「这条守卫能不能抓住那两个形态」的答案必须来自**实跑**读数。
 */
const HISTORICAL_FORMS: Array<{ where: string; line: string; expr: string }> = [
  {
    where: 'issue #6523（智能派单料组标题，修复前形态）',
    line: '<span className="font-medium text-neutral-800">{group.materialKey}</span>',
    expr: 'group.materialKey',
  },
  {
    where: 'issue #6535（省料看板「物料」列，修复前形态）',
    line: '<td className="px-4 py-2.5 text-neutral-700">{g.materialKey}</td>',
    expr: 'g.materialKey',
  },
]

/** 注入文件路径（`src/` 下的临时语料；判据跑完即删，不留半成品） */
const INJECTED = join(SRC_DIR, '__machine-key-guard-injection__.tsx')

/** 把源码行**真写进** `src/` 再扫一遍（落盘版注入：证明「扫描面 + 规则 + 语料发现」整条链）。 */
function scanWithInjected(lines: string[]): MachineKeyFinding[] {
  writeFileSync(
    INJECTED,
    'export default function Injected() {\n  return (\n    <div>\n'
      + lines.map((l) => `      ${l}`).join('\n')
      + '\n    </div>\n  )\n}\n',
    'utf-8',
  )
  try {
    return scanCorpus().findings
  } finally {
    if (existsSync(INJECTED)) unlinkSync(INJECTED)
  }
}

describe('JSX 文本位的服务端机器键守卫（issue #6552 · #6523 / #6535 同族）', () => {
  it('扫描面非空且覆盖已知对象（目录搬了 / AST 口径坏了 ⇒ 本判据先红，而不是静默空跑）', () => {
    expect(CORPUS.files.length, '扫不到 tsx ⇒ 判据在扫空气').toBeGreaterThanOrEqual(MIN_FILES)
    expect(
      CORPUS.textExprs,
      'JSX 文本位表达式数掉到线下 ⇒ 发现面已漂（扫描面活着才有资格报「0 处违例」）',
    ).toBeGreaterThanOrEqual(MIN_TEXT_EXPRS)
    // 两个现场页面必须在场，且**仍然**在用 materialKey（只应出现在属性位）——
    // 证明坐标系里有被测对象，而不是「这个仓库里根本没有 materialKey」。
    for (const path of MATERIAL_KEY_FILES) {
      const f = CORPUS.files.find((x) => x.path === path)
      expect(f?.path, `${path} 不在扫描面里 ⇒ 本判据的坐标系已漂移`).toBe(path)
      expect(f!.source.includes('materialKey'), `${path} 不再出现 materialKey ⇒ 坐标系漂了`).toBe(true)
    }
  })

  it('规则表不许被悄悄删空（四条机器键形态一条都不许少）', () => {
    expect(MACHINE_KEY_RULES.map((r) => r.id)).toEqual(['MK-compound-key', 'MK-uuid', 'MK-hash', 'MK-token'])
    for (const r of MACHINE_KEY_RULES) expect(r.desc.length, `${r.id} 缺说明`).toBeGreaterThan(3)
  })

  it('JSX 文本位不得渲染服务端机器键（未登记即红；现取应为空集）', () => {
    expect(
      OFFENDERS,
      '这些地方把服务端机器键（复合键 / UUID / hash / token 形态）当展示文本渲染了 ——'
        + '商家会看到一长串十六进制或内部标识：\n'
        + OFFENDERS.join('\n')
        + '\n\n出口（照 #6523 / #6535 的既定修法）：**展示名与标识分家** ——'
        + '服务端下发人话展示字段（如 `materialLabel`），`materialKey` 继续承载 React `key` /'
        + '`data-testid` / 分组判据（属性位不判，见文件头）。前端**不切字符串**'
        + '（那是第二份会漂的口径）。\n'
        + `现取集合（供登记）= ${JSON.stringify(OFFENDERS)}`,
    ).toEqual([])
    // 空集必须**显式**断言，且扫描面读数同刻非空（否则「空集」是扫描面坏掉的假绿）
    expect(CORPUS.files.length).toBeGreaterThanOrEqual(MIN_FILES)
    expect(CORPUS.textExprs).toBeGreaterThanOrEqual(MIN_TEXT_EXPRS)
    expect(guardViolations(CORPUS), '门禁口径下的违例必须是空集').toEqual([])
  })

  it('台账（人话白名单）不得腐坏：每条必须仍出现在语料里（只许缩短）', () => {
    const corpusText = CORPUS.files.map((f) => f.source).join('\n')
    const dead = HUMAN_KEY_WHITELIST.filter((w) => !new RegExp(`\\b${w}\\b`).test(corpusText))
    expect(
      dead,
      `这些人话白名单条目已不在语料里出现 ⇒ 死条目，请从 HUMAN_KEY_WHITELIST 删除：${dead.join('、')}`,
    ).toEqual([])
    expect(HUMAN_KEY_WHITELIST.length, '白名单只许缩短：确认为人话的条目不要再加（不许留松弛量）')
      .toBeLessThanOrEqual(2)
  })

  it('判别力自证①：同行形态 / 独占一行形态都必红（假绿教训：按行首锚定会漏掉同行）', () => {
    // ① 同行形态（#6523 的真实形态）：`<span …>{group.materialKey}</span>`
    expect(scanJsxMachineKeys('x.tsx', 'const a = <span className="x">{group.materialKey}</span>')).toHaveLength(1)
    // ② 元素子节点独占一行
    expect(scanJsxMachineKeys('x.tsx', 'const a = <span className="x">\n  {group.materialKey}\n</span>')).toHaveLength(1)
    // ③ 三级链 / 可选链（都在文本位）
    expect(scanJsxMachineKeys('x.tsx', 'const a = <span>{a.b.materialKey}</span>')).toHaveLength(1)
    expect(scanJsxMachineKeys('x.tsx', 'const a = <span>{a?.materialKey}</span>')).toHaveLength(1)
    // ④ **边界（有意，不是漏判）**：机器键**嵌在三元 / 逻辑 / 调用里**（`{ok ? row.materialKey : '—'}`）
    //    不在面内 —— 本判据只收「文本位**整个表达式就是一条成员链**」的形态（#6523 / #6535 的真实形态）。
    //    两边都钉住：哪天有人把面扩到嵌套表达式，这两条会先红，必须显式改边界与文件头。
    expect(scanJsxMachineKeys('x.tsx', 'const a = <span>{ok ? row.materialKey : "—"}</span>')).toEqual([])
    expect(scanJsxMachineKeys('x.tsx', 'const a = <span>{ok && row.materialKey}</span>')).toEqual([])
    // ④ 接口里那版**按行首锚定**的坏正则对①给出的是**假绿**（本判据用 AST，不看行首）——
    //    这是 issue 里逐字的假绿教训，钉在这里：哪天有人把发现面换回行首锚定，这条对照先红。
    expect(
      /^\s*\{[^}]*\.materialKey\}/.test('const a = <span className="x">{group.materialKey}</span>'),
      '行首锚定对同行形态必须给假绿（这正是本判据不用它的原因）',
    ).toBe(false)
  })

  it('判别力自证②：属性位是合法承载面（key / data-testid / href / value / title 一律不判）', () => {
    const attrForms = [
      '<div key={g.materialKey} />',
      '<div data-testid={`saving-saved-group-${g.materialKey}`} />',
      '<a href={`/p/${g.materialKey}`} />',
      '<input value={p.materialKey} />',
      '<span title={g.materialKey} />',
      '<div key={u.itemKey} data-testid={`remnant-unmatched-${u.itemKey}`} />',
    ]
    for (const s of attrForms) expect(scanJsxMachineKeys('x.tsx', `const a = ${s}`), s).toEqual([])
  })

  it('判别力自证③：人话 / 正常业务字段不误伤（不是「什么变量都不能渲染」）', () => {
    const good = [
      '<span>{row.productName}</span>',
      '<span>{row.orderNo}</span>',
      '<span>{row.code}</span>',
      '<span>{row.id}</span>',
      '<span>{rec.itemKey}</span>',
      '<span>{OTHER_KEY}</span>',
      '<span>{p.key}</span>',
      '<span>{composition_key}</span>',
      '<span>{t("materialKey")}</span>',
      '<span>{"materialKey"}</span>',
      '<span>{items.map((i) => <b key={i.materialKey}>{i.name}</b>)}</span>',
    ]
    for (const s of good) expect(scanJsxMachineKeys('x.tsx', `const a = ${s}`), s).toEqual([])
    // 规则本身对机器键形态必须有判别力（否则上面全是「规则坏了也绿」）——
    // **逐条钉到具体规则 id**（不用 `not.toBeNull` 这种存在性断言：`growth_gate` 的 G4 会判它弱断言）
    const mustHit: Array<[string, string]> = [
      ['materialKey', 'MK-compound-key'],
      ['materialLabelKey', 'MK-compound-key'],
      ['sessionUuid', 'MK-uuid'],
      ['uuid', 'MK-uuid'],
      ['contentHash', 'MK-hash'],
      ['hash', 'MK-hash'],
      ['apiToken', 'MK-token'],
      ['token', 'MK-token'],
    ]
    for (const [name, rule] of mustHit) {
      expect(isMachineKeyName(name), `${name} 必须命中 ${rule}`).toBe(rule)
    }
    const mustMiss: Array<[string, string]> = [
      ['material_key', 'snake_case 是服务端口径/内容，不是机器键指纹'],
      ['composition_key', '已登记人话（工序组合口径标签）'],
      ['itemKey', '已登记人话（= 工序名，内容本身）'],
      ['materialLabel', '展示名（人话）'],
      ['OTHER_KEY', '全大写常量 = 内容本身'],
    ]
    for (const [name, why] of mustMiss) {
      expect(isMachineKeyName(name), `${name} 不该判红（${why}）`).toBe(null)
    }
  })

  // ⏱ 本用例真落盘再全量重扫（每次 ~2.8s、共 4 次）⇒ 显式放宽超时；**不用挂钟当判据**
  //   （`migao-dev-flow` §23 G8：这里钉的是「注入 ⇒ 命中 / 撤注 ⇒ 空集」这个与负载无关的工作量读数）。
  it('判别力自证④（注入式，落盘）：把历史形态写进 src/ ⇒ 必红；删掉 ⇒ 回到空集', { timeout: 60000 }, () => {
    // 反向对照：注入前是空集（两处都已修）
    expect(scanCorpus().findings, '注入前应无违例').toEqual([])
    for (const form of HISTORICAL_FORMS) {
      const findings = scanWithInjected([form.line])
      expect(findings, `${form.where} 的形态没被抓住 ⇒ 本守卫对那一族没有判别力`).toHaveLength(1)
      expect(findings[0].expr).toBe(form.expr)
      expect(findings[0].file).toContain('__machine-key-guard-injection__.tsx')
      expect(findings[0].rule).toBe('MK-compound-key')
    }
    // 一次注入两条（两种形态），各自具名
    const both = scanWithInjected(HISTORICAL_FORMS.map((f) => f.line))
    expect(both.map((f) => f.expr).sort()).toEqual(['g.materialKey', 'group.materialKey'])
    // 删掉注入 ⇒ 回到空集（证明「空集」是真实读数，不是注入残留）
    expect(scanCorpus().findings).toEqual([])
    expect(existsSync(INJECTED), '注入文件必须已被清理（不留半成品）').toBe(false)
  })

  it('判别力自证⑤：扫描面 / 规则被弄坏 ⇒ 门禁口径必红', () => {
    // ① 扫描面为空（真去扫一个空目录）⇒ guardViolations 报「判据在扫空气」
    //    （不是「恰好 0 处违例」，也不是恒真断言：下面紧接着一条真语料的对照）
    const emptyDir = join(ROOT, 'tests', '.tmp-empty-corpus')
    mkdirSync(emptyDir, { recursive: true })
    try {
      const empty = scanCorpus(emptyDir)
      expect(empty.files.length, '空目录里不该扫到 tsx').toBe(0)
      const emptyProblems = guardViolations(empty)
      expect(emptyProblems.length, '空语料必须至少报一条扫描面问题').toBeGreaterThan(0)
      expect(emptyProblems.join(' ')).toContain('扫空气')
    } finally {
      rmdirSync(emptyDir)
    }
    // 对照：真语料 + 空违例 ⇒ 门禁口径**不**报任何问题（否则上面那条是恒真断言）
    expect(guardViolations(CORPUS)).toEqual([])
    // ② 规则射程被改坏（正则永不命中）⇒ 注入历史形态也扫不出来 ⇒ 违例集为空 ⇒ 与①的
    //    「扫描面下限」一起构成双向夹逼：规则坏了 / 语料坏了都瞒不过去。
    const brokenRules = MACHINE_KEY_RULES.map((r) => ({ ...r, test: /$^/ }))
    expect(
      scanJsxMachineKeys('x.tsx', 'const a = <span>{group.materialKey}</span>', brokenRules),
      '射程为空的规则表不得命中（若命中 ⇒ 自证本身坏了）',
    ).toEqual([])
    // ③ 语料为空时「文本位表达式数」读数也为 0（扫描面自证就读这个数）
    expect(countJsxTextExpressions('const a = 1')).toBe(0)
  })
})
