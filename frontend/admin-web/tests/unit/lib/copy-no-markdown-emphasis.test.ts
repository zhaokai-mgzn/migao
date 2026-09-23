// case_ids: PR-105
/**
 * 商家可见文案的 markdown 强调：**准写，但必须经 `@/lib/inline-markdown` 上屏**
 * （issue #5194 **改判** —— 用户 2026-09-23 裁定「渲染」，本文件原判据「源码零 `**`」= #5206 的
 * 「去掉标记」方案，同日被本条改判；`#5206` 只留其对菜单/余料台账那部分）。
 *
 * ## 为什么改判（不是口味问题）
 *
 * 去标记能让星号消失，但**强调本身也没了** —— 商家看到的是没有层级的长散文；
 * 而这些文案（算料口径 / 术语 / 余料口径）正是「哪几个字是重点」最需要被看见的地方。
 * ⇒ 保留标记 + 渲染层解析成 `<strong>` / `<code>`（`@/lib/inline-markdown`，只认这两种行内标记）。
 *
 * ## 判据分工（**DOM 面在别处**，本文件管**源码面**）
 *
 * - **DOM 面**：`tests/unit/components/CraftCalcGlossary.test.tsx` /
 *   `tests/unit/components/TenantParamsPanel.test.tsx` /
 *   `tests/unit/pages/production-routings.test.tsx` —— 渲染后整块 `textContent` 不含 `**` 与反引号，
 *   **且** `<strong>` / `<code>` 真的出现。🔴 两条必须同时有：只判「不含 `**`」的话，
 *   把标记删掉（= #5206 的形态）同样绿 ⇒ 那是个**看不见强调丢失**的空判据。
 * - **源码面（本文件）**：① 带标记的文件**必须登记**；② 登记项**必须接线**（消费它的渲染点 import
 *   了渲染器）；③ 两边**陈旧即红**。⇒ 「新写一处带 `**` 的文案却忘了接渲染器」不会静默溜过，
 *   而「把标记删回纯文本」会因 DOM 面的正控判红。
 *
 * ## 判据（各自能单独变红）
 *
 * ① **正控**：检测器对合成坏样本（成对 `**x**` / 未闭合 `**x` / JSX 文本 / 模板 head+tail）**必须报出**
 *    —— 没有这条，「零未登记」可能只是检测器瞎了（**空断言**）；
 * ② **负控**：手机号掩码 `'****'`、行/块/JSX 注释里的 `**` **不得**被判违规
 *    （面是 AST 而非全文 grep：本仓注释惯例就是 markdown 写法，全文 grep 在 `frontend/` 报 500+ 命中）；
 * ③ **未登记即红**：`frontend/admin-web/src` + `frontend/worker-h5/src` 里出现 `**` 的文件必须都在
 *    登记表内 —— 新文件命中 ⇒ 红，逼你**当场决定**（接渲染器 + 登记，或把标记删掉再登记说明）；
 * ④ **登记陈旧即红**：登记过的文件里若已无 `**` ⇒ 红（留着会让判据悄悄放宽）；
 * ⑤ **接线即红/绿**：每个渲染点必须 `import … from '@/lib/inline-markdown'`（漏接 ⇒ 标记原样上屏）；
 * ⑥ **掩码登记陈旧即红**（原 ④ 保留）。
 *
 * ## 红证（实测，非推理）
 *
 * - ③：往 `src/lib/inbound-orders`（**未登记**）的任一句文案塞 `**` ⇒ 判红并打印 `文件:行`；
 * - ④：把 `src/lib/tenant-params.ts` 的 `**每一项都直接改米数 = 改钱**` 标记删掉 ⇒ 判红（登记陈旧）；
 * - ⑤：从 `src/components/settings/RemnantItemSizesPanel.tsx` 删掉 `inline-markdown` 那行 import ⇒ 判红。
 *
 * ## 边界（如实登记）
 *
 * - 本守卫扫的是**源码字面量**，**不**判反射面：服务端下发的字符串（如余料 `notice`、
 *   后端错误 message）若含 `**` 仍会上屏 —— 那一面不在本单范围（issue #5194 的穷举面 = `frontend/`）；
 * - 检测面**不含** `frontend/mini-app`：C 端助手消息经 `frontend/mini-app/src/utils/richText.ts`
 *   的 `parseRichText` **真的解析** `**x**`（那是既有渲染约定，不是泄漏）；
 * - 检测面**不含**各包的 `tests/`：用例标题里写 `**强调**` 是**自述**，不上屏；
 * - **未实装**：不做「文案 source → 消费方」的静态映射（那要手写一张易腐的映射表）——
 *   端到端上屏由 DOM 面的三处判据覆盖（覆盖的是本单改到的「算料 / 余料 / 参数总览」面）。
 */
import { describe, expect, it } from 'vitest'
import { readdirSync, readFileSync } from 'node:fs'
import { join, relative } from 'node:path'
import ts from 'typescript'

/** 掩码字面量（**不是** markdown）：全星号串 —— 客户手机号脱敏用 */
const MASK_ONLY = /^\*+$/

/** 掩码登记表：允许出现的 `**`（**逐字相等**，不是模式）—— 每一项都必须仍在源码里（陈旧即红，见 ⑥） */
const REGISTERED = ['****'] as const

/**
 * **登记表**：允许在用户可见文案里写 markdown 标记的源文件（相对 `frontend/admin-web` 的路径）。
 * 新文件命中 ③ ⇒ 要么接渲染器并登记，要么把标记删掉（并在此说明为什么不渲染）。
 */
const REGISTERED_MARKER_FILES = [
  'src/lib/craft-calc-glossary.ts',
  'src/lib/tenant-params.ts',
  'src/components/production/CraftCalcGlossary.tsx',
  'src/components/settings/TenantParamsPanel.tsx',
  'src/components/settings/RemnantItemSizesPanel.tsx',
  'src/components/settings/OversizeThresholdPreview.tsx',
  'src/app/(dashboard)/production/remnants/page.tsx',
  'src/app/(dashboard)/production/routings/page.tsx',
] as const

/**
 * **接线表**：必须 import `@/lib/inline-markdown` 的渲染点（相对 `frontend/admin-web`）。
 *
 * 上面两个 `src/lib/*.ts` 是**数据模块**（没有 JSX），标记的渲染由消费它的这几个组件/页面负责
 * ⇒ 漏接线 = 标记原样上屏（正是本单要修的缺陷形态）。
 */
const WIRED_FILES = [
  'src/components/production/CraftCalcGlossary.tsx',
  'src/components/settings/TenantParamsPanel.tsx',
  'src/components/settings/RemnantItemSizesPanel.tsx',
  'src/components/settings/OversizeThresholdPreview.tsx',
  'src/app/(dashboard)/production/remnants/page.tsx',
  'src/app/(dashboard)/production/routings/page.tsx',
] as const

interface Leak {
  file: string
  line: number
  kind: string
  text: string
}

/**
 * AST 节点 → 稳定标签。
 *
 * 🔴 **必须用数值比较，不能用 `ts.SyntaxKind[node.kind]` 反查名字**（实测踩过一次）：
 * 无插值的模板字面量与 `NoSubstitutionTemplateLiteral` **共用同一个数值**，反查拿到的是
 * 枚举里排在前面的别名 **`FirstTemplateToken`** ⇒ 拿字符串 `=== 'NoSubstitutionTemplateLiteral'`
 * 判等**恒为假**，`const x = \`…**…\`` 这一类会**静默漏检**（本文件 ① 正控就是这么抓出来的）。
 */
function kindName(node: ts.Node): string | null {
  if (node.kind === ts.SyntaxKind.StringLiteral) return 'StringLiteral'
  if (node.kind === ts.SyntaxKind.NoSubstitutionTemplateLiteral) return 'TemplateLiteral'
  if (node.kind === ts.SyntaxKind.JsxText) return 'JsxText'
  if (node.kind === ts.SyntaxKind.TemplateExpression) return 'TemplateExpression'
  if (node.kind === ts.SyntaxKind.TemplateHead) return 'TemplateHead'
  if (node.kind === ts.SyntaxKind.TemplateMiddle) return 'TemplateMiddle'
  if (node.kind === ts.SyntaxKind.TemplateTail) return 'TemplateTail'
  return null
}

/** 纯函数检测器：AST 面 = 字符串字面量 / 模板静态段 / JSX 文本（注释不在面内） */
function findEmphasisLeaks(file: string, source: string): Leak[] {
  const kind = /\.(tsx|jsx)$/.test(file) ? ts.ScriptKind.TSX : ts.ScriptKind.TS
  const sf = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true, kind)
  const out: Leak[] = []
  const push = (node: ts.Node, astKind: string, text: string) => {
    if (!text.includes('**')) return
    if (MASK_ONLY.test(text.trim())) return
    if ((REGISTERED as readonly string[]).includes(text)) return
    const { line } = sf.getLineAndCharacterOfPosition(node.getStart(sf))
    out.push({ file, line: line + 1, kind: astKind, text: text.replace(/\n/g, '\\n') })
  }
  const rec = (node: ts.Node) => {
    const k = kindName(node)
    if (k === 'StringLiteral' || k === 'TemplateLiteral' || k === 'JsxText') {
      push(node, k, (node as ts.LiteralLikeNode | ts.JsxText).text)
    } else if (k === 'TemplateExpression') {
      // ⚠️ `**` 也可能落在 **head**（`` `**强调** ${x}` `` 的第一个静态段）。
      // 只扫 `templateSpans` 会漏掉 head —— 实测踩过一次（本文件 ① 正控抓出来的第二个盲点）。
      const tpl = node as ts.TemplateExpression
      if (kindName(tpl.head) === 'TemplateHead') push(tpl.head, 'TemplateHead', tpl.head.text)
      for (const span of tpl.templateSpans) {
        push(span.literal, kindName(span.literal) ?? 'TemplateSpan', span.literal.text)
      }
    }
    ts.forEachChild(node, rec)
  }
  rec(sf)
  return out
}

const SRC_DIRS = [
  join(process.cwd(), 'src'),
  join(process.cwd(), '..', 'worker-h5', 'src'),
]

function sourceFiles(dir: string): string[] {
  const out: string[] = []
  const walk = (d: string) => {
    for (const e of readdirSync(d, { withFileTypes: true })) {
      if (e.name === 'node_modules' || e.name === '.next' || e.name === 'dist') continue
      const p = join(d, e.name)
      if (e.isDirectory()) walk(p)
      else if (/\.(tsx?|jsx?|mjs|cjs)$/.test(e.name)) out.push(p)
    }
  }
  walk(dir)
  return out
}

describe('文案里的 markdown 强调必须经渲染器上屏（issue #5194 改判 / §22）', () => {
  it('① 正控：检测器对成对与未闭合的 `**` 都必须报出（否则「零未登记」是空断言）', () => {
    const src = [
      "const a = '有明细行未通过校验，**未建账**（一行都没写）'",
      "const b = '未闭合的 **星号也要报（商家照样看得见）'",
      'const c = <p>JSX 文本里的 **强调** 同样上屏</p>',
      'const d = `无插值模板里的 **强调** 也算`',
      'const e = `有插值模板里的 **强调** ${x} 也算**收尾**`',
    ].join('\n')
    const leaks = findEmphasisLeaks('positive-control.tsx', src)
    expect(leaks.map((l) => `${l.line}:${l.kind}`)).toEqual([
      '1:StringLiteral',
      '2:StringLiteral',
      '3:JsxText',
      // 无插值模板 = NoSubstitutionTemplateLiteral ⇒ 反查名字会拿到 FirstTemplateToken（见 kindName 注释）
      '4:TemplateLiteral',
      '5:TemplateHead',
      '5:TemplateTail',
    ])
  })

  it('② 负控：掩码 / 注释 / JSX 注释里的 `**` 不算违规（面是 AST，不是全文 grep）', () => {
    const src = [
      "const masked = p.slice(0, 3) + '****' + p.slice(-4)",
      '// 注释里的 **强调** 不上屏（本仓注释惯例就是 markdown 写法）',
      '/* 块注释里的 **强调** 同样不上屏 */',
      'const view = <div>{/* JSX 注释里的 **强调** 不上屏 */}ok</div>',
    ].join('\n')
    expect(findEmphasisLeaks('negative-control.tsx', src)).toEqual([])
  })

  it('③ 未登记即红：带 `**` 的源文件必须都在登记表里（新命中 ⇒ 当场决定接渲染器还是删标记）', () => {
    const files = scanFiles()
    const leaks = files.flatMap((f) => findEmphasisLeaks(relative(process.cwd(), f), readFileSync(f, 'utf-8')))
    const unregistered = Array.from(new Set(leaks.map((l) => l.file))).filter(
      (f) => !(REGISTERED_MARKER_FILES as readonly string[]).includes(f)
    )
    expect(
      unregistered,
      '这些文件的文案里出现了 markdown 标记 `**` 但**没有登记**：要么接 `@/lib/inline-markdown` 并登记，' +
        '要么把标记删掉（删标记会丢掉强调 ⇒ 须在文件里说明理由）',
    ).toEqual([])
    // 自证非空：面里**确实**有带标记的文件（否则本条在空集上恒真）
    expect(leaks.length).toBeGreaterThan(0)
  })

  it('④ 登记陈旧即红：登记过的文件里必须仍有 `**`（否则请删条目）', () => {
    const sources = scanFiles().map((f) => ({ file: relative(process.cwd(), f), src: readFileSync(f, 'utf-8') }))
    const stale = REGISTERED_MARKER_FILES.filter(
      (f) => findEmphasisLeaks(f, sources.find((s) => s.file === f)?.src ?? '').length === 0
    )
    expect(
      stale,
      '登记表里的文件已不含 `**` ⇒ 条目陈旧（留着会让判据悄悄放宽），请从 REGISTERED_MARKER_FILES 删掉',
    ).toEqual([])
  })

  it('⑤ 接线：每个渲染点都必须 import `@/lib/inline-markdown`（漏接 ⇒ 标记原样上屏）', () => {
    const missing = WIRED_FILES.filter((f) => {
      const src = readFileSync(join(process.cwd(), f), 'utf-8')
      // 位置性证据：只看 import 语句（正文注释里提到模块名不算接线 —— 免得判据被自己的文案喂绿）
      return !/^\s*import\s+\{[^}]*InlineMarkdown[^}]*\}\s+from\s+'@\/lib\/inline-markdown'/m.test(src)
    })
    expect(missing, '这些渲染点没接 `InlineMarkdown` ⇒ 文案里的标记会原样上屏').toEqual([])
  })

  it('⑥ 掩码登记表陈旧即红：登记过的掩码字面量必须仍在源码里（否则请删条目）', () => {
    const all = SRC_DIRS.flatMap((d) => sourceFiles(d).map((f) => readFileSync(f, 'utf-8'))).join('\n')
    const missing = REGISTERED.filter((m) => !all.includes(`'${m}'`))
    expect(
      missing,
      '登记表里的掩码字面量在源码里已不存在 ⇒ 条目陈旧，请从 REGISTERED 删掉（留着会让判据悄悄放宽）',
    ).toEqual([])
  })
})

/** 扫描面（含 fail-closed 自检：面消失时报绿等于判据失效） */
function scanFiles(): string[] {
  const files = SRC_DIRS.flatMap((d) => {
    expect(
      (() => {
        try {
          return readdirSync(d).length > 0
        } catch {
          return false
        }
      })(),
      `扫描面不存在或为空：${d} —— 面消失时报绿等于判据失效（fail-closed）`,
    ).toBe(true)
    return sourceFiles(d)
  })
  // 实测 191 个文件（admin-web/src 185 + worker-h5/src 6，2026-09-23）；写 150 留余量，
  // 但**不允许解析失灵 ⇒ 骤降**（面消失时报绿等于判据失效）。
  expect(files.length, '扫描面文件数异常 ⇒ 判据在空集上恒真').toBeGreaterThan(150)
  return files
}
