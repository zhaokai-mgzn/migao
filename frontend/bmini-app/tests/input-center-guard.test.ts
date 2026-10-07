// case_ids: BM-042, BM-043
/**
 * 「H5 输入框文字竖向居中」的**共享层 + 输入面台账**元守卫（issue #6478；AGENTS.md 铁律 8 / `migao-dev-flow` §23）
 *
 * ## 治的形态
 *
 * 生产实测（2026-10-07，`https://app.migaozn.com/b/#/pages/auth/login/index`，viewport 390×844）：
 * Taro h5 的 `<Input>` 渲染成**两层** —— 外层自定义元素 `taro-input-core` 拿 `className`
 * （用户看到的圆角框，49.9px），内层是它渲染的原生 `<input class="weui-input">`
 * （Taro 自带样式 `height:1.47059em` ⇒ 只有 26px）⇒ 内层行盒**贴在框顶**：
 * 实测 **上留白 0.5px / 下留白 23.4px**，占位文字与已输入文字都落在框内偏上。
 * 小程序端是单层原生 input ⇒ 这是 **h5 特有**形态。
 *
 * 修法落在**共享样式层** `frontend/bmini-app/src/styles/input-center.scss`（由 `src/app.scss` 引入）：
 * ① 外框 `display:flex` + `align-items:center`；② 内层 `input` `height:100%`。
 * **只改竖向对齐**，不动任何尺寸 / 圆角 / 字号。
 *
 * ## 判据（每条都能单独变红）
 *
 * | # | 判据 | 红证（in-memory 注入，见下面的用例） |
 * |---|---|---|
 * | 1 | 共享层文件在位，且被 `frontend/bmini-app/src/app.scss` **真的引入** | 删掉 `@use './styles/input-center.scss'` ⇒ 红 |
 * | 2 | 共享层里三条居中声明都在（外框 flex / 外框 align-items:center / 内层 input height:100%） | 摘掉任一条 ⇒ 红 |
 * | 3 | **不许逐页打补丁**：`taro-input-core` 只许出现在 `frontend/bmini-app/src/styles/**` 的 scss 里 | 往某个页面的 scss 里加一条 `taro-input-core{…}` ⇒ 红 |
 * | 4 | **未登记即红**：`src` 下的 `.tsx` 里现取的 `(文件, className)` 输入面必须在台账里 | 造一个用 `<Input className='brand-new__input'>` 的页面 ⇒ 红并具名 |
 * | 5 | **台账只许缩短**：每条登记都必须仍能被扫到（面没了 ⇒ 该条已死 ⇒ 红） | 内存里摘掉某页的 `<Input>` 而不删登记 ⇒ 红 |
 * | 6 | **抽取必须完整**（fail-closed）：`<Input>` 出现次数 == 抽到的 className 数 | 把 `<Input>` 的 className 挪成第二个属性 ⇒ 红 |
 * | 7 | **台账不许空转**：条数 0 ⇒ 红；每条必须声明 `label` 与 `case_ids` | 清空台账「消红」⇒ 红 |
 *
 * ## 边界（照实登记，§19.1）
 * ① 它判的是**静态形态**（规则在不在 / 面登记没有），**不是**运行期真的居中 ——
 *    运行期那一条由真几何判据 `tests/e2e/specs/bmini/bmini-input-center.spec.ts` 承担（bmini 的
 *    Playwright 腿，`tests/playwright.bmini.config.ts`；CI = `.github/workflows/bmini-app.yml` 的
 *    `bmini H5 tabBar geometry (e2e)` job）；
 * ② 射程 = `frontend/bmini-app/src/**`：`Textarea` / 原生 `<input>` 直接写法的面**不在**台账内；
 * ③ 它**不改任何门禁的通过条件、不新增豁免**；
 * ④ 台账条数**现取**（本文件按 src 现算，双向相等才算过）、**文档里不写死条数**，
 *    复算命令见 `frontend/bmini-app/tests/input-surface-ledger.json` 的 `_recompute` 字段。
 */
import fs from 'fs'
import path from 'path'
import { stripComments } from './helpers/h5PlatformLists'

const BMINI_ROOT = path.join(__dirname, '..')
const SRC_DIR = path.join(BMINI_ROOT, 'src')
const APP_SCSS = 'src/app.scss'
/** 共享样式层目录（这一族规则的唯一合法落点） */
const SHARED_STYLE_PREFIX = 'src/styles/'
const SHARED_LAYER = 'src/styles/input-center.scss'

export interface LedgerEntry {
  file: string
  className: string
  label: string
  case_ids: string[]
}

/** 共享层判据的输入（真语料与注入式红证**共用同一份**判定） */
export interface SharedLayerInput {
  appScss: string
  sharedLayerExists: boolean
  sharedLayer: string
  /** `src` 下全部 scss：bmini 相对 posix 路径 → 原文 */
  scssFiles: Record<string, string>
}

/** 台账判据的输入 */
export interface LedgerInput {
  /** `src` 下全部 `.tsx`（bmini 相对 posix 路径） */
  files: string[]
  /** 读**剥注释后**的文本 */
  read: (rel: string) => string
  entries: LedgerEntry[]
}

/** 去掉 `//` 行注释（本仓 scss 无 `url(…//…)` 形态；与 `test_bmini_mobile_typography_floor.py` 同口径） */
function stripScssComments(text: string): string {
  return text
    .split('\n')
    .map((line) => line.split('//')[0])
    .join('\n')
}

/** 抽出 `selector { body }` 块（朴素配对：射程内只有顶层规则，无 scss 嵌套） */
function ruleBlocks(text: string): { selector: string; body: string }[] {
  const blocks: { selector: string; body: string }[] = []
  const re = /([^{}]+)\{([^{}]*)\}/g
  let match: RegExpExecArray | null
  while ((match = re.exec(text)) !== null) {
    blocks.push({ selector: match[1].trim().replace(/\s+/g, ' '), body: match[2] })
  }
  return blocks
}

function hasDeclaration(body: string, declaration: string): boolean {
  const norm = (value: string): string => value.replace(/\s+/g, '').toLowerCase()
  return body.split(';').map(norm).includes(norm(declaration))
}

/** 判据 1~3：共享层在位 / 被引入 / 三条居中声明都在 / 不许逐页打补丁 */
export function sharedLayerProblems(input: SharedLayerInput): string[] {
  const problems: string[] = []

  if (!input.appScss.includes('./styles/input-center.scss')) {
    problems.push(
      `共享层没被引入：${APP_SCSS} 里找不到 \`@use './styles/input-center.scss'\` —— ` +
        `规则写在文件里但没接线 ⇒ 页面上不生效（判据会空转）`,
    )
  }
  if (!input.sharedLayerExists) {
    problems.push(`共享层文件不存在：${SHARED_LAYER}（输入框竖向居中的唯一落点）`)
    return problems
  }

  const layer = stripScssComments(input.sharedLayer)
  const blocks = ruleBlocks(layer)
  const outer = blocks.filter((block) => block.selector === 'taro-input-core')
  if (outer.length === 0) {
    problems.push(`共享层里没有 \`taro-input-core { … }\`（外框居中规则）`)
  }
  if (!outer.some((block) => hasDeclaration(block.body, 'display: flex'))) {
    problems.push(`共享层的外框规则缺 \`display: flex\`（内层行盒会重新贴顶）`)
  }
  if (!outer.some((block) => hasDeclaration(block.body, 'align-items: center'))) {
    problems.push(`共享层的外框规则缺 \`align-items: center\``)
  }
  const inner = blocks.filter((block) => block.selector === 'taro-input-core .weui-input')
  if (!inner.some((block) => hasDeclaration(block.body, 'height: 100%'))) {
    problems.push(`共享层的 \`taro-input-core .weui-input\` 缺 \`height: 100%\`（内层没撑满外框 ⇒ 文字仍贴顶）`)
  }

  for (const [rel, text] of Object.entries(input.scssFiles)) {
    if (!stripScssComments(text).includes('taro-input-core')) continue
    if (rel.startsWith(SHARED_STYLE_PREFIX)) continue
    problems.push(
      `逐页打补丁：${rel} 里出现 \`taro-input-core\` —— 这一族规则只许落在 ${SHARED_STYLE_PREFIX}** 的共享层` +
        `（第二份口径会漂：改了共享层、逐页那份不动 ⇒ 那一面照旧贴顶，而没有任何东西会红）`,
    )
  }
  return problems
}

const INPUT_ANY_RE = /<Input\b/g
const INPUT_CLASS_RE = /<Input\s+className='([^']+)'/g

function surfaceKey(file: string, className: string): string {
  return `${file}::${className}`
}

/** 判据 4~7：现取的输入面 ⇄ 台账双向相等、抽取完整、台账不许空转 */
export function ledgerProblems(input: LedgerInput): string[] {
  const problems: string[] = []

  const detected = new Set<string>()
  let occurrences = 0
  for (const rel of input.files) {
    const text = input.read(rel)
    const count = (text.match(INPUT_ANY_RE) ?? []).length
    if (count === 0) continue
    occurrences += count
    const matched = [...text.matchAll(INPUT_CLASS_RE)].map((match) => match[1])
    if (matched.length !== count) {
      problems.push(
        `抽取不完整：${rel} 里有 ${count} 处 \`<Input>\`，只抽到 ${matched.length} 个 className —— ` +
          `形态可能变了（className 不再是 \`<Input>\` 的首个属性）⇒ 更新抽取实现与台账，**不许**静默跳过`,
      )
    }
    for (const className of matched) detected.add(surfaceKey(rel, className))
  }

  const declared = new Set(input.entries.map((entry) => surfaceKey(entry.file, entry.className)))

  // 判据 7：台账不许空转（fail-closed）—— 空台账不是「全部合规」
  if (input.entries.length === 0) {
    problems.push('台账为空：输入面台账被清空 ⇒ fail-closed 判红（「空」不等于「全部合规」）')
  }
  if (occurrences === 0) {
    problems.push('射程为空：`src` 下的 `.tsx` 里一处 `<Input>` 都没扫到 ⇒ 扫描口径已漂移（fail-closed）')
  }

  // 判据 4：未登记即红
  for (const key of detected) {
    if (!declared.has(key)) {
      problems.push(
        `未登记即红：${key} —— 这个输入面还没登记进 frontend/bmini-app/tests/input-surface-ledger.json` +
          `（新增输入面必须同批确认它也走共享层）`,
      )
    }
  }
  // 判据 5：台账只许缩短（条目必须活着）
  for (const key of declared) {
    if (!detected.has(key)) {
      problems.push(`台账条目已死：${key} —— 这个输入面已不存在 ⇒ 同批删掉这一条（台账只许缩短）`)
    }
  }

  for (const entry of input.entries) {
    const key = surfaceKey(entry.file, entry.className)
    if (!entry.label) {
      problems.push(`${key}：缺 label（登记而不写「这是哪个面」⇒ 没人能判断它该不该在）`)
    }
    if (!Array.isArray(entry.case_ids) || entry.case_ids.length === 0) {
      problems.push(`${key}：没有声明 case_ids（登记而不关联用例 ⇒ 没人知道它靠哪条判据活着）`)
    }
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

function realSharedInput(): SharedLayerInput {
  const layerAbs = path.join(BMINI_ROOT, SHARED_LAYER)
  return {
    appScss: fs.readFileSync(path.join(BMINI_ROOT, APP_SCSS), 'utf8'),
    sharedLayerExists: fs.existsSync(layerAbs),
    sharedLayer: fs.existsSync(layerAbs) ? fs.readFileSync(layerAbs, 'utf8') : '',
    scssFiles: scssFiles(),
  }
}

function realLedgerInput(): LedgerInput {
  return {
    files: tsxFiles(),
    read: (rel) => {
      const abs = path.join(BMINI_ROOT, rel)
      if (!fs.existsSync(abs)) throw new Error(`找不到受管文件：${rel}（路径漂移不得静默跳过 ⇒ 红）`)
      return stripComments(fs.readFileSync(abs, 'utf8'))
    },
    entries: LEDGER.entries,
  }
}

const LEDGER = JSON.parse(
  fs.readFileSync(path.join(__dirname, 'input-surface-ledger.json'), 'utf8'),
) as { entries: LedgerEntry[] }

/** 变异生效自证：锚点失配会让 `replace` 静默返回原文 ⇒ 红证退化成空断言（§23.4 陷阱 T1）。 */
function expectMutationApplied(mutated: string, tokens: string[], label: string): void {
  for (const token of tokens) {
    if (!mutated.includes(token)) {
      throw new Error(
        `[${label}] 变异未生效：变异体里找不到「${token}」⇒ 红证会退化成空断言。` +
          `锚点与被读文件版本不匹配，不要靠下游断言反推。`,
      )
    }
  }
}

describe('B. H5 输入框竖向居中：共享层判据（issue #6478）', () => {
  it('正跑：共享层在位、被 app.scss 引入、三条居中声明都在、没有逐页打补丁', () => {
    const input = realSharedInput()
    // 反空跑：真的读到了共享层与 src 下的 scss（否则两边都是空集 ⇒ 判据空转通过）
    expect(Object.keys(input.scssFiles).length).toBeGreaterThanOrEqual(5)
    expect(input.sharedLayer.length).toBeGreaterThan(200)
    expect(sharedLayerProblems(input)).toEqual([])
  })

  it('🔴 判据 1 红证：app.scss 不再引入共享层 ⇒ 判红（写在文件里但没接线）', () => {
    const input = realSharedInput()
    const mutated = input.appScss.replace("@use './styles/input-center.scss';", '')
    expectMutationApplied(mutated, ['@use', './styles/tabbar.scss'], '判据 1 摘掉共享层引入')
    expect(mutated.includes('./styles/input-center.scss')).toBe(false)
    expect(sharedLayerProblems({ ...input, appScss: mutated }).join('\n')).toContain('共享层没被引入')
  })

  it('🔴 判据 2 红证：共享层被清空 / 摘掉任一条居中声明 ⇒ 判红', () => {
    const input = realSharedInput()
    const emptied = sharedLayerProblems({ ...input, sharedLayer: '' })
    expect(emptied.join('\n')).toContain('没有 `taro-input-core { … }`')

    const noFlex = input.sharedLayer.replace('display: flex;', 'display: block;')
    expectMutationApplied(noFlex, ['display: block;'], '判据 2 把外框改回 block')
    expect(sharedLayerProblems({ ...input, sharedLayer: noFlex }).join('\n')).toContain('display: flex')

    const noCenter = input.sharedLayer.replace('align-items: center;', '')
    expectMutationApplied(noCenter, ['height: 100%;'], '判据 2 摘掉 align-items: center')
    expect(sharedLayerProblems({ ...input, sharedLayer: noCenter }).join('\n')).toContain('align-items: center')

    const noHeight = input.sharedLayer.replace('height: 100%;', 'height: 1.47059em;')
    expectMutationApplied(noHeight, ['height: 1.47059em;'], '判据 2 把内层改回 Taro 的 1.47059em')
    expect(sharedLayerProblems({ ...input, sharedLayer: noHeight }).join('\n')).toContain('height: 100%')
  })

  it('🔴 判据 3 红证：把居中规则抄进某个页面的 scss（逐页打补丁）⇒ 判红并具名', () => {
    const input = realSharedInput()
    const injected = 'src/pages/auth/login/index.scss'
    const mutated = `${input.scssFiles[injected]}\ntaro-input-core { display: flex; align-items: center; }\n`
    expectMutationApplied(mutated, ['taro-input-core'], '判据 3 注入逐页补丁')
    const problems = sharedLayerProblems({
      ...input,
      scssFiles: { ...input.scssFiles, [injected]: mutated },
    })
    expect(problems.join('\n')).toContain(injected)
    expect(problems.join('\n')).toContain('逐页打补丁')
  })

  it('🔴 判据 1 红证（缺文件）：共享层被删掉 ⇒ 判红（fail-closed）', () => {
    const input = realSharedInput()
    expect(sharedLayerProblems({ ...input, sharedLayerExists: false }).join('\n')).toContain('共享层文件不存在')
  })
})

describe('B. 输入框面台账元守卫（issue #6478）', () => {
  it('正跑：现取的 (文件, className) 输入面与台账双向相等，且每条都声明了 label / case_ids', () => {
    const input = realLedgerInput()
    // 反空跑：射程非空、台账非空（否则「双向相等」在空集上恒真）
    expect(input.files.length).toBeGreaterThanOrEqual(12)
    expect(LEDGER.entries.length).toBeGreaterThanOrEqual(12)
    expect(ledgerProblems(input)).toEqual([])
  })

  it('🔴 判据 4 红证：新页面里出现 `<Input>` 而没登记 ⇒ 判红并具名', () => {
    const input = realLedgerInput()
    const injected = 'src/pages/brand-new/index.tsx'
    const read = (rel: string): string =>
      rel === injected ? "export default () => <Input className='brand-new__input' />" : input.read(rel)
    const problems = ledgerProblems({ ...input, files: [...input.files, injected], read })
    expect(problems.join('\n')).toContain(`${injected}::brand-new__input`)
    expect(problems.join('\n')).toContain('未登记即红')
  })

  it('🔴 判据 5 红证：摘掉某页的 `<Input>` 而不删登记 ⇒ 判红（条目必须活着，只许缩短）', () => {
    const input = realLedgerInput()
    const target = 'src/pages/worker/reprint/index.tsx'
    const read = (rel: string): string =>
      rel === target ? input.read(rel).replace(/<Input\b/g, '<TextInput') : input.read(rel)
    expectMutationApplied(read(target), ['<TextInput'], '判据 5 摘掉补打页的 <Input>')
    expect(read(target).includes('<Input')).toBe(false)
    const problems = ledgerProblems({ ...input, read })
    expect(problems.join('\n')).toContain(`${target}::admin-input`)
    expect(problems.join('\n')).toContain('台账条目已死')
  })

  it('🔴 判据 6 红证：`<Input>` 的 className 不再是首个属性（抽取口径漂移）⇒ 判红（fail-closed）', () => {
    const input = realLedgerInput()
    const target = 'src/pages/sessions/detail/index.tsx'
    const read = (rel: string): string =>
      rel === target
        ? input.read(rel).replace(/<Input\s+className='([^']+)'/, "<Input\n            value={replyText}\n            className='$1'")
        : input.read(rel)
    expectMutationApplied(read(target), ['className='], '判据 6 把 className 挪成第二个属性')
    const problems = ledgerProblems({ ...input, read })
    expect(problems.join('\n')).toContain('抽取不完整')
    expect(problems.join('\n')).toContain(target)
  })

  it('🔴 判据 7 红证：台账被清空 ⇒ 判红（空台账不是「全部合规」，是 fail-closed）', () => {
    const empty = ledgerProblems({ ...realLedgerInput(), entries: [] })
    expect(empty.join('\n')).toContain('台账为空')
    expect(empty.join('\n')).toContain('未登记即红')
  })

  it('🔴 判据 7b 红证：射程扫描口径漂移（一处 `<Input>` 都扫不到）⇒ 判红', () => {
    const input = realLedgerInput()
    const problems = ledgerProblems({ ...input, files: [], read: () => '' })
    expect(problems.join('\n')).toContain('射程为空')
  })

  it('🔴 判据 7c 红证：登记缺 label / 缺 case_ids ⇒ 判红', () => {
    const input = realLedgerInput()
    const target = input.entries[0]
    const problems = ledgerProblems({
      ...input,
      entries: [
        { ...target, label: '' },
        { ...target, file: 'src/components/WorkerBar.tsx', label: 'x', case_ids: [] },
      ],
    })
    expect(problems.join('\n')).toContain('缺 label')
    expect(problems.join('\n')).toContain('没有声明 case_ids')
  })
})
