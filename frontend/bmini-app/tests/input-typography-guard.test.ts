// case_ids: MC-159
/**
 * 「H5 输入面字体族继承 + 占位符收口」的守卫（issue #6480；AGENTS.md 铁律 8 / `migao-dev-flow` §23）
 *
 * ## 治的形态（issue #6480 实测读数，真栈 + 真 Chromium，2026-10-07）
 *
 * Taro H5 把组件的 `className` 挂在**包裹元素**上（`taro-input-core` / `taro-textarea-core`），
 * 真正绘字的是**内层原生控件**（`input.weui-input` / `textarea.taro-textarea`）。
 * 浏览器给这两个控件**自己的 UA 默认样式**且**不继承**父级 ⇒ 只要样式只写在外层 class 上：
 *
 * | 面 | 内层元素 | `font-family` | `::placeholder` |
 * |---|---|---|---|
 * | 登录页 | `input.weui-input` | **`Arial`**（浏览器默认） | **`rgb(117,117,117)`**（默认灰） |
 * | 问米宝输入条（#6476 修前） | `textarea.taro-textarea` | **`monospace`** + 13.33px | 默认灰 |
 *
 * 而且 `placeholderClass` **只在 weapp 生效** ⇒ H5 那行小字必须给**真规则**，
 * 否则每个输入面各写一份、改了这页忘那页。
 *
 * ## 修法（一处收口）
 *
 * 唯一落点 = 共享样式层 `frontend/bmini-app/src/styles/input-center.scss`（由 `src/app.scss` 引入）：
 * ① 内层 `.weui-input` / `.taro-textarea` `font-family: inherit`（跟随各页正文）；
 * ② `.taro-textarea` 另加 `font-size: inherit`（UA 默认 13.33px monospace，外层字号到不了内层）；
 * ③ `::placeholder` 的**唯一**来源（色值 `$text-secondary`，与 #6476 输入条同 token，字号继承控件自身）。
 *
 * ## 判据（每条都能单独变红；红证见下面的用例）
 *
 * | # | 判什么 | 红证（注入式，实跑） |
 * |---|---|---|
 * | 1 | 共享层在位、被 `src/app.scss` 真的引入，且给**两个**内层控件都写了 `font-family: inherit` | 删掉任一条 `font-family: inherit` ⇒ 红并具名 |
 * | 2 | 共享层**不许**给内层写具体字体族 / 字号（会改变现有视觉） | 把 `inherit` 改成 `Arial` ⇒ 红 |
 * | 3 | **裸的** `font-family: <具体字体>` 全 app **只许**出现在字体定义处（`src/app.scss` 的 `page, body`），其余必须进台账 | 往任一页面 scss 加 `font-family: Arial` ⇒ 红并具名 |
 * | 4 | 台账**只许缩短**且条数**现取**：登记的例外必须仍能被扫到；空台账 ⇒ 红（fail-closed） | 删掉登录页那处等宽字体 ⇒ 台账条目已死 ⇒ 红 |
 * | 5 | `::placeholder` 只许出现在共享层，且两个内层选择器都有 `color: $text-secondary`、**不写** `font-size` | 往页面 scss 加 `&::placeholder{color:#999}` ⇒ 红并具名 |
 * | 6 | **射程完整**：`src` 的 `.tsx` 里不许出现原生 `<input>` / `<textarea>` 标签（它们绕过内层 class ⇒ 静默落回默认字体） | 注入一个 `<input className='x'/>` ⇒ 红 |
 *
 * ## 边界（照实登记，§19.1）
 * ① 它判的是**静态形态**（规则在不在、收口有没有破），**不是**运行期 `getComputedStyle` 读数；
 *    真机读数由 issue #6480 的验收记录承担，本单按派单口径**不跑**浏览器腿；
 * ② 射程 = `frontend/bmini-app/src/**` 的 `.scss` + `.tsx`；`weapp` 产物里没有这两个内层元素 ⇒
 *    这族规则对小程序端**零影响**（判据不覆盖小程序端，也不需要对它断言）；
 * ③ 它**不改任何门禁的通过条件、不新增豁免**。
 */
import fs from 'fs'
import path from 'path'
import { stripComments } from './helpers/h5PlatformLists'

const BMINI_ROOT = path.join(__dirname, '..')
const SRC_DIR = path.join(BMINI_ROOT, 'src')
const APP_SCSS = 'src/app.scss'
const SHARED_LAYER = 'src/styles/input-center.scss'
const SHARED_STYLE_PREFIX = 'src/styles/'
/** 全 app 唯一允许命名**具体字体族**的位置（全局正文口径 = 平台默认；本单**有意不动**它） */
const FONT_DEFINITION_FILE = 'src/app.scss'
const FONT_DEFINITION_SELECTOR = 'page, body'
/** 继承类取值：它们不指定具体字体，不会改变现有视觉 */
const INHERIT_VALUES = new Set(['inherit', 'unset', 'revert', 'revert-layer', 'initial'])
/** 占位符色唯一来源（与 issue #6476 的输入条同一 token） */
const PLACEHOLDER_COLOR = '$text-secondary'
const PLACEHOLDER_SELECTORS = ['.weui-input', '.taro-textarea']

export interface Declaration {
  file: string
  selector: string
  property: string
  value: string
}

export interface LedgerEntry {
  file: string
  /** `font-family: Menlo, Consolas, monospace` 形态（比较时忽略空白与大小写） */
  declaration: string
  /** 现取条数：同一文件里出现几次就必须登记几次 */
  count: number
  label: string
  case_ids: string[]
}

export interface Ledger {
  exceptions: LedgerEntry[]
}

/** 共享层判据的输入（真语料与注入式红证**共用同一份**判定） */
export interface CorpusInput {
  appScss: string
  sharedLayerExists: boolean
  sharedLayer: string
  /** `src` 下全部 scss：bmini 相对 posix 路径 → 原文 */
  scssFiles: Record<string, string>
  ledger: Ledger
}

// ── 解析（朴素但够用：bmini 的 scss 只有规则块与声明，没有 @media / 字符串里的括号）──────────

/** 去掉 `//` 行注释（本仓 scss 无 `url(…//…)` 形态；与 `input-center-guard.test.ts` 同口径） */
function stripScssComments(text: string): string {
  return text
    .split('\n')
    .map((line) => line.split('//')[0])
    .join('\n')
}

function normalizeSelector(selector: string): string {
  return selector.replace(/\s+/g, ' ').trim()
}

/** 逐字节扫一遍，给每条声明配上**解析后的选择器**（`&` 按父级展开，scss 嵌套可读） */
export function declarationsOf(files: Record<string, string>): Declaration[] {
  const out: Declaration[] = []
  for (const [file, raw] of Object.entries(files)) {
    const text = stripScssComments(raw)
    const stack: string[] = []
    let buf = ''
    const flush = (chunk: string): void => {
      const line = chunk.trim()
      if (!line) return
      const match = /^([\w-]+)\s*:\s*([\s\S]+)$/.exec(line)
      if (!match) return
      out.push({
        file,
        selector: stack.length > 0 ? stack[stack.length - 1] : '',
        property: match[1].toLowerCase(),
        value: match[2].replace(/\s+/g, ' ').trim(),
      })
    }
    for (const ch of text) {
      if (ch === '{') {
        const raw = normalizeSelector(buf)
        const parent = stack.length > 0 ? stack[stack.length - 1] : ''
        const resolved = raw.includes('&')
          ? raw.split('&').join(parent)
          : parent && raw
            ? `${parent} ${raw}`
            : raw
        stack.push(normalizeSelector(resolved))
        buf = ''
      } else if (ch === '}') {
        flush(buf)
        buf = ''
        stack.pop()
      } else if (ch === ';') {
        flush(buf)
        buf = ''
      } else {
        buf += ch
      }
    }
  }
  return out
}

function selectorsOf(declaration: Declaration): string[] {
  return declaration.selector.split(',').map((part) => part.trim())
}

/** 真语料 + **注入的**共享层文本：红证必须走同一份判定，否则改的是别处的副本 */
function scssWithShared(input: CorpusInput): Record<string, string> {
  return { ...input.scssFiles, [SHARED_LAYER]: input.sharedLayer }
}

function normDeclaration(text: string): string {
  return text.replace(/\s+/g, '').toLowerCase()
}

/** 判据 1 + 2：共享层在位、被引入、两个内层控件都 `font-family: inherit`，且不写具体字体 */
export function inheritProblems(input: CorpusInput): string[] {
  const problems: string[] = []

  if (!input.appScss.includes('./styles/input-center.scss')) {
    problems.push(
      `共享层没被引入：${APP_SCSS} 里找不到 \`@use './styles/input-center.scss'\` —— ` +
        `规则写在文件里但没接线 ⇒ 内层控件照旧跑浏览器默认字体（判据会空转）`,
    )
  }
  if (!input.sharedLayerExists) {
    problems.push(`共享层文件不存在：${SHARED_LAYER}（输入面字体族的唯一落点）`)
    return problems
  }

  const declarations = declarationsOf({ [SHARED_LAYER]: input.sharedLayer })
  const fontFamily = declarations.filter((decl) => decl.property === 'font-family')
  const withInherit = fontFamily.filter((decl) => INHERIT_VALUES.has(decl.value.toLowerCase()))

  for (const inner of PLACEHOLDER_SELECTORS) {
    const covered = withInherit.some((decl) => selectorsOf(decl).includes(inner))
    if (!covered) {
      problems.push(
        `共享层缺 \`${inner} { font-family: inherit }\` —— 这个内层原生控件不继承父级字体族，` +
          `输入框会落回浏览器默认（\`.weui-input\` 实测 Arial / \`.taro-textarea\` 实测 monospace）`,
      )
    }
  }

  // 判据 2：共享层只许写 inherit —— 写具体值就是「在这里改了全站输入面的视觉」
  for (const decl of declarations) {
    if (decl.property !== 'font-family' && decl.property !== 'font-size') continue
    if (INHERIT_VALUES.has(decl.value.toLowerCase())) continue
    problems.push(
      `共享层给内层写了具体 \`${decl.property}: ${decl.value}\`（${decl.selector}）—— ` +
        `这一族规则只许 \`inherit\`：具体字体族的位置是 ${FONT_DEFINITION_FILE} 的 \`${FONT_DEFINITION_SELECTOR}\`，` +
        `在共享层写死会改变全站输入面的现有视觉`,
    )
  }

  const textareaSize = declarations.filter(
    (decl) => decl.property === 'font-size' && selectorsOf(decl).includes('.taro-textarea'),
  )
  if (!textareaSize.some((decl) => decl.value.toLowerCase() === 'inherit')) {
    problems.push(
      `共享层缺 \`.taro-textarea { font-size: inherit }\` —— textarea 的 UA 默认是 **13.33px monospace**，` +
        `外层包裹元素（\`&__input\` 上的 26 / 28px）到不了内层`,
    )
  }
  return problems
}

/** 判据 3 + 4：裸的 `font-family: <具体字体>` 只许在字体定义处；例外进台账（只许缩短、条数现取） */
export function bareFontFamilyProblems(input: CorpusInput): string[] {
  const problems: string[] = []
  const declarations = declarationsOf(scssWithShared(input))
  const bare = declarations.filter(
    (decl) => decl.property === 'font-family' && !INHERIT_VALUES.has(decl.value.toLowerCase()),
  )

  const ledgerCounts = new Map<string, number>()
  for (const entry of input.ledger.exceptions) {
    const key = `${entry.file}::${normDeclaration(entry.declaration)}`
    ledgerCounts.set(key, (ledgerCounts.get(key) ?? 0) + 1)
  }

  if (input.ledger.exceptions.length === 0) {
    problems.push('台账为空：字体族例外台账被清空 ⇒ fail-closed 判红（「空」不等于「全部合规」）')
  }
  if (bare.length === 0) {
    problems.push('射程为空：`src` 下一条具体 `font-family` 都没扫到 ⇒ 扫描口径已漂移（fail-closed）')
  }

  for (const decl of bare) {
    const inDefinitionSite =
      decl.file === FONT_DEFINITION_FILE && decl.selector === FONT_DEFINITION_SELECTOR
    if (inDefinitionSite) continue
    const key = `${decl.file}::${normDeclaration(`${decl.property}: ${decl.value}`)}`
    if (ledgerCounts.has(key)) continue
    problems.push(
      `未登记即红：${decl.file} 的 \`${decl.selector}\` 里写了具体字体族 \`${decl.property}: ${decl.value}\` —— ` +
        `全 app 的字体族只许在 ${FONT_DEFINITION_FILE} 的 \`${FONT_DEFINITION_SELECTOR}\` 定义一处` +
        `（逐页各写一份 = 收口破，改一处全站不跟），确有例外须登记进` +
        ` frontend/bmini-app/tests/input-font-ledger.json（台账只许缩短）`,
    )
  }

  // 判据 4：台账条目必须**活着**（只许缩短），且条数与现取一致
  for (const entry of input.ledger.exceptions) {
    const key = `${entry.file}::${normDeclaration(entry.declaration)}`
    const actual = bare.filter(
      (decl) => `${decl.file}::${normDeclaration(`${decl.property}: ${decl.value}`)}` === key,
    ).length
    if (actual === 0) {
      problems.push(`台账条目已死：${entry.file} 的 \`${entry.declaration}\` 已不存在 ⇒ 同批删掉这一条（台账只许缩短）`)
    } else if (actual !== entry.count) {
      problems.push(
        `台账条数不符：${entry.file} 的 \`${entry.declaration}\` 现取 ${actual} 处，台账写 ${entry.count} 处 —— ` +
          `条数必须现取（多一处 = 又开了一个口子）`,
      )
    }
    if (!entry.label) problems.push(`${entry.file}：例外缺 label（不写「为什么故意这样」⇒ 下一个人不知道能不能删）`)
    if (!Array.isArray(entry.case_ids) || entry.case_ids.length === 0) {
      problems.push(`${entry.file}：例外没声明 case_ids（登记而不关联用例 ⇒ 没人知道它靠哪条判据活着）`)
    }
  }
  return problems
}

/** 判据 5：`::placeholder` 只许共享层一处，两个内层选择器同色、不写字号 */
export function placeholderProblems(input: CorpusInput): string[] {
  const problems: string[] = []
  const declarations = declarationsOf(scssWithShared(input)).filter((decl) =>
    selectorsOf(decl).some((selector) => selector.includes('::placeholder')),
  )

  for (const decl of declarations) {
    if (!decl.file.startsWith(SHARED_STYLE_PREFIX)) {
      problems.push(
        `逐页写占位符：${decl.file} 的 \`${decl.selector}\` 里出现 \`::placeholder\` —— ` +
          `占位符样式只许落在 ${SHARED_STYLE_PREFIX}** 的共享层（第二份口径会漂：改了共享层、逐页那份不动 ⇒ ` +
          `那一面照旧是浏览器默认灰，而没有任何东西会红）`,
      )
    }
  }

  const shared = declarations.filter((decl) => decl.file === SHARED_LAYER)
  for (const inner of PLACEHOLDER_SELECTORS) {
    const rule = shared.find(
      (decl) => decl.property === 'color' && selectorsOf(decl).includes(`${inner}::placeholder`),
    )
    if (!rule) {
      problems.push(
        `共享层缺 \`${inner}::placeholder { color: ${PLACEHOLDER_COLOR} }\` —— ` +
          `这行小字会落回浏览器默认灰（\`placeholderClass\` 只在 weapp 生效，H5 不认）`,
      )
    } else if (rule.value !== PLACEHOLDER_COLOR) {
      problems.push(
        `共享层 \`${inner}::placeholder\` 的颜色是 \`${rule.value}\`，应为 \`${PLACEHOLDER_COLOR}\` —— ` +
          `色值是全 app 唯一来源（与 issue #6476 的输入条同 token），改了会与已验收的输入条不一致`,
      )
    }
  }
  const sized = shared.filter(
    (decl) => decl.property === 'font-size' && selectorsOf(decl).some((s) => s.includes('::placeholder')),
  )
  if (sized.length > 0) {
    problems.push(
      `共享层给 \`::placeholder\` 写了字号（${sized.map((decl) => decl.selector).join(' / ')}）—— ` +
        `占位符应继承控件自身字号：写死就是第二个口径`,
    )
  }
  return problems
}

/** 判据 6：射程完整 —— 原生 `<input>` / `<textarea>` 标签会绕过内层 class ⇒ fail-closed */
export function rawControlProblems(files: string[], read: (rel: string) => string): string[] {
  const problems: string[] = []
  let textareas = 0
  for (const rel of files) {
    const text = read(rel)
    const raw = /<(input|textarea)\b/g
    const hits = [...text.matchAll(raw)].map((match) => match[1])
    if (hits.length > 0) {
      problems.push(
        `原生控件裸写：${rel} 里出现 \`<${hits[0]}>\` —— H5 下它拿不到 \`.weui-input\` / \`.taro-textarea\` 这两个内层 class，` +
          `共享层的字体族 / 占位符规则一条都不生效（静默落回浏览器默认）`,
      )
    }
    textareas += (text.match(/<Textarea\b/g) ?? []).length
  }
  // 反空跑：现取确实扫到了 textarea 面（否则「没有原生标签」在空射程上恒真）
  if (textareas === 0) {
    problems.push('射程为空：`src` 的 `.tsx` 里一处 `<Textarea>` 都没扫到 ⇒ 扫描口径已漂移（fail-closed）')
  }
  return problems
}

// ── 真语料读取（只读；坐标自证：路径漂移一律抛，不静默跳过）────────────────────────────

function walk(dir: string, keep: (name: string) => boolean, out: string[] = []): string[] {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) walk(full, keep, out)
    else if (keep(entry.name)) out.push(full)
  }
  return out
}

function relative(abs: string): string {
  return path.relative(BMINI_ROOT, abs).split(path.sep).join('/')
}

function scssFiles(): Record<string, string> {
  const out: Record<string, string> = {}
  for (const abs of walk(SRC_DIR, (name) => name.endsWith('.scss'))) out[relative(abs)] = fs.readFileSync(abs, 'utf8')
  return out
}

function tsxFiles(): string[] {
  return walk(SRC_DIR, (name) => name.endsWith('.tsx')).map(relative).sort()
}

const LEDGER = JSON.parse(
  fs.readFileSync(path.join(__dirname, 'input-font-ledger.json'), 'utf8'),
) as Ledger

function realInput(): CorpusInput {
  const layerAbs = path.join(BMINI_ROOT, SHARED_LAYER)
  return {
    appScss: fs.readFileSync(path.join(BMINI_ROOT, APP_SCSS), 'utf8'),
    sharedLayerExists: fs.existsSync(layerAbs),
    sharedLayer: fs.existsSync(layerAbs) ? fs.readFileSync(layerAbs, 'utf8') : '',
    scssFiles: scssFiles(),
    ledger: LEDGER,
  }
}

function realRead(rel: string): string {
  const abs = path.join(BMINI_ROOT, rel)
  if (!fs.existsSync(abs)) throw new Error(`找不到受管文件：${rel}（路径漂移不得静默跳过 ⇒ 红）`)
  return stripComments(fs.readFileSync(abs, 'utf8'))
}

/** 变异生效自证：锚点失配会让 `replace` 静默返回原文 ⇒ 红证退化成空断言（§23.4 陷阱 T1）。 */
function expectMutationApplied(mutated: string, token: string, label: string): void {
  if (!mutated.includes(token)) {
    throw new Error(
      `[${label}] 变异未生效：变异体里找不到「${token}」⇒ 红证会退化成空断言。` +
        `锚点与被读文件版本不匹配，不要靠下游断言反推。`,
    )
  }
}

describe('B. 输入面字体族继承：共享层判据（issue #6480）', () => {
  it('正跑：共享层被引入、两个内层控件都继承字体族、textarea 继承字号、不写具体字体', () => {
    const input = realInput()
    // 反空跑：真的读到了共享层与 src 下的 scss
    expect(Object.keys(input.scssFiles).length).toBeGreaterThanOrEqual(5)
    expect(input.sharedLayer.length).toBeGreaterThan(200)
    expect(inheritProblems(input)).toEqual([])
  })

  it('🔴 判据 1 红证：删掉 `.weui-input` 的 `font-family: inherit` ⇒ 必红并具名', () => {
    const input = realInput()
    const mutated = input.sharedLayer.replace('  font-family: inherit;\n', '')
    // 变异自证：文件头注释里也有这个 token ⇒ 必须锚到**声明行**，否则红证退化成空断言
    expect(mutated.includes('\n  font-family: inherit;')).toBe(false)
    expectMutationApplied(mutated, '.taro-textarea {', '判据 1 摘掉内层 inherit（其它块须留着）')
    const problems = inheritProblems({ ...input, sharedLayer: mutated }).join('\n')
    expect(problems).toContain('.weui-input')
    expect(problems).toContain('font-family: inherit')
  })

  it('🔴 判据 1b 红证：删掉 `.taro-textarea` 的 `font-size: inherit` ⇒ 必红（textarea 字号落回 13.33px）', () => {
    const input = realInput()
    const mutated = input.sharedLayer.replace('  font-size: inherit;\n', '')
    // 同上：头注释里也有 `font-size: inherit` ⇒ 锚到声明行
    expect(mutated.includes('\n  font-size: inherit;')).toBe(false)
    expectMutationApplied(mutated, '13.33px', '判据 1b 摘掉字号继承（头注释的成因说明须留着）')
    expect(inheritProblems({ ...input, sharedLayer: mutated }).join('\n')).toContain('13.33px')
  })

  it('🔴 判据 2 红证：把 `inherit` 改成具体字体 ⇒ 必红（会改变全站输入面现有视觉）', () => {
    const input = realInput()
    const mutated = input.sharedLayer.replace(
      '  font-family: inherit;',
      '  font-family: -apple-system, BlinkMacSystemFont, sans-serif;',
    )
    expectMutationApplied(mutated, 'BlinkMacSystemFont', '判据 2 把 inherit 换成具体字体栈')
    const problems = inheritProblems({ ...input, sharedLayer: mutated }).join('\n')
    expect(problems).toContain('具体')
    expect(problems).toContain('page, body')
  })

  it('🔴 判据 1c 红证：共享层没被 app.scss 引入 ⇒ 必红（写在文件里但没接线）', () => {
    const input = realInput()
    const mutated = input.appScss.replace("@use './styles/input-center.scss';", '')
    expectMutationApplied(mutated, './styles/tabbar.scss', '判据 1c 摘掉共享层引入')
    expect(mutated.includes('./styles/input-center.scss')).toBe(false)
    expect(inheritProblems({ ...input, appScss: mutated }).join('\n')).toContain('共享层没被引入')
  })
})

describe('B. 字体族收口：裸 font-family 只许在字体定义处（issue #6480）', () => {
  it('正跑：全 app 只剩「定义处 + 已登记例外」，台账条目活着且条数现取', () => {
    const input = realInput()
    const bare = declarationsOf(input.scssFiles).filter(
      (decl) => decl.property === 'font-family' && decl.value.toLowerCase() !== 'inherit',
    )
    // 反空跑：真的扫到了那处已登记的等宽例外（否则「收口」在空射程上恒真）
    expect(bare.length).toBeGreaterThanOrEqual(1)
    expect(bare.map((decl) => decl.file)).toContain('src/pages/auth/login/index.scss')
    expect(bareFontFamilyProblems(input)).toEqual([])
  })

  it('🔴 判据 3 红证：往某个页面 scss 加一句裸 `font-family: Arial` ⇒ 必红并具名', () => {
    const input = realInput()
    const injected = 'src/pages/sessions/detail/index.scss'
    const mutated = `${input.scssFiles[injected]}\n.admin-input { font-family: Arial; }\n`
    expectMutationApplied(mutated, 'font-family: Arial', '判据 3 注入裸字体族')
    const problems = bareFontFamilyProblems({
      ...input,
      scssFiles: { ...input.scssFiles, [injected]: mutated },
    }).join('\n')
    expect(problems).toContain('未登记即红')
    expect(problems).toContain(injected)
    expect(problems).toContain('font-family: Arial')
  })

  it('🔴 判据 4 红证：删掉已登记的等宽例外而台账不动 ⇒ 必红（条目已死，只许缩短）', () => {
    const input = realInput()
    const target = 'src/pages/auth/login/index.scss'
    const mutated = input.scssFiles[target].replace('font-family: Menlo, Consolas, monospace;', '')
    expectMutationApplied(mutated, '&__row', '判据 4 摘掉等宽例外')
    expect(mutated.includes('Menlo')).toBe(false)
    const problems = bareFontFamilyProblems({
      ...input,
      scssFiles: { ...input.scssFiles, [target]: mutated },
    }).join('\n')
    expect(problems).toContain('台账条目已死')
    expect(problems).toContain(target)
  })

  it('🔴 判据 4b 红证：台账被清空 ⇒ 必红（空台账不是「全部合规」）', () => {
    const input = realInput()
    const problems = bareFontFamilyProblems({ ...input, ledger: { exceptions: [] } }).join('\n')
    expect(problems).toContain('台账为空')
    expect(problems).toContain('未登记即红')
  })

  it('🔴 判据 4c 红证：同一文件里再加一处同值的等宽字体 ⇒ 条数不符必红（又开一个口子）', () => {
    const input = realInput()
    const target = 'src/pages/auth/login/index.scss'
    const mutated = `${input.scssFiles[target]}\n.another-row { font-family: Menlo, Consolas, monospace; }\n`
    expectMutationApplied(mutated, 'font-family: Menlo, Consolas, monospace', '判据 4c 追加同值例外')
    const problems = bareFontFamilyProblems({
      ...input,
      scssFiles: { ...input.scssFiles, [target]: mutated },
    }).join('\n')
    expect(problems).toContain('台账条数不符')
    expect(problems).toContain('现取 2 处')
  })
})

describe('B. 占位符收口 + 射程完整性（issue #6480）', () => {
  it('正跑：`::placeholder` 只在共享层，两个内层选择器同色、不写字号', () => {
    const input = realInput()
    const placeholders = declarationsOf(input.scssFiles)
      .flatMap(selectorsOf)
      .filter((selector) => selector.includes('::placeholder'))
    // 反空跑：两个内层（input / textarea）都真扫到了占位符规则
    expect(placeholders).toContain('.weui-input::placeholder')
    expect(placeholders).toContain('.taro-textarea::placeholder')
    expect(placeholderProblems(input)).toEqual([])
  })

  it('🔴 判据 5 红证：往页面 scss 加 `&::placeholder{color:#999}` ⇒ 必红并具名', () => {
    const input = realInput()
    const injected = 'src/pages/worker/stock/index.scss'
    const mutated = `${input.scssFiles[injected]}\n.stock-input { &::placeholder { color: #999; } }\n`
    expectMutationApplied(mutated, '::placeholder', '判据 5 注入逐页占位符')
    const problems = placeholderProblems({
      ...input,
      scssFiles: { ...input.scssFiles, [injected]: mutated },
    }).join('\n')
    expect(problems).toContain('逐页写占位符')
    expect(problems).toContain(injected)
  })

  it('🔴 判据 5b 红证：共享层占位符色被改（或给占位符写字号）⇒ 必红', () => {
    const input = realInput()
    const recolored = input.sharedLayer.replace(
      `  color: ${PLACEHOLDER_COLOR};\n}`,
      '  color: #999;\n}',
    )
    expectMutationApplied(recolored, 'color: #999', '判据 5b 改共享层占位符色')
    expect(placeholderProblems({ ...input, sharedLayer: recolored }).join('\n')).toContain('色值是全 app 唯一来源')

    const sized = input.sharedLayer.replace(
      `  color: ${PLACEHOLDER_COLOR};\n}`,
      `  color: ${PLACEHOLDER_COLOR};\n  font-size: 24px;\n}`,
    )
    expectMutationApplied(sized, 'font-size: 24px', '判据 5b 给占位符加字号')
    expect(placeholderProblems({ ...input, sharedLayer: sized }).join('\n')).toContain('第二个口径')
  })

  it('正跑：`.tsx` 里没有原生 `<input>` / `<textarea>`，且真的扫到了 Textarea 面', () => {
    const files = tsxFiles()
    expect(files.length).toBeGreaterThanOrEqual(12)
    expect(rawControlProblems(files, realRead)).toEqual([])
  })

  it('🔴 判据 6 红证：注入一个原生 `<input>` ⇒ 必红并具名（它绕过内层 class）', () => {
    const files = tsxFiles()
    const injected = 'src/pages/brand-new/index.tsx'
    const read = (rel: string): string =>
      rel === injected ? "export default () => <input className='brand-new__input' />" : realRead(rel)
    const problems = rawControlProblems([...files, injected], read).join('\n')
    expect(problems).toContain('原生控件裸写')
    expect(problems).toContain(`${injected}`)
  })
})
