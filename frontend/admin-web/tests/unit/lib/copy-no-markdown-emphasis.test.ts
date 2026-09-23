// case_ids: PR-105
/**
 * 商家可见文案**不得漏出 markdown 强调标记 `**`**（issue #5194，承 issue #5033）。
 *
 * ## 病根（这类缺陷为什么以前没有任何东西会变红）
 *
 * 这些文案的渲染层是**纯文本插值、零 markdown 解析**（`{term.definition}` / `{p.copy.hint}` /
 * JSX 文本 / `toast.error('…')`）⇒ 文案里的 `**想加粗**` 会被**原样**印成字面星号，
 * 商家看到的是 `本域**每一项都直接改米数 = 改钱**` 这种噪声。
 * 而**静态测试发现不了**：DOM 里确实「含该串」，任何「含某文案」的断言照样绿
 * —— 属「判据看不见的用户可见缺陷」。
 *
 * 更早的实证（issue #5033）：只在**一处**面板顺手修掉、其余存量留在注释里（「断言整块
 * `textContent` 不含 `**` 会因那些存量而红（假红）」就是这个形态的**自我豁免**）。
 * 本守卫把「不变量」落到**全量源码面**上，替代那份口头登记。
 *
 * ## 判据（三条，各自能单独变红）
 *
 * ① **正控**：检测器对合成的坏样本（成对 `**x**` / 未闭合 `**x`）**必须报出** ——
 *    没有这条，「零违规」可能只是检测器瞎了（**空断言**）；
 * ② **负控**：手机号掩码 `'****'`、注释 / JSX 注释里的 `**` **不得**被判违规 ——
 *    面**不是**全文 grep 而是 AST（字符串字面量 / 模板静态段 / JSX 文本），注释天然在面外；
 * ③ **零违规**：`frontend/admin-web/src` + `frontend/worker-h5/src` 的真实源码零命中；
 *    另有一张**登记表**（掩码字面量），且**陈旧即红**（登记项在源码里消失 ⇒ 红，要求删条目）。
 *
 * ## 红证（实测，非推理）
 *
 * 往 `src/lib/craft-calc-glossary.ts` 的一句 `impact` 里塞回 `**` ⇒ ③ 判红并打印
 * `文件:行` + 原文；删掉登记表里那一项所对应的掩码用法 ⇒ ④ 判红。见 PR body。
 *
 * ## 边界（如实登记）
 *
 * - 本守卫扫的是**源码字面量**，**不**判反射面：服务端下发的字符串（如余料 `notice`）
 *   若含 `**` 仍会上屏 —— 那一面不在本单范围（issue #5194 的穷举面就是 `frontend/`）；
 * - 检测面**不含** `frontend/mini-app`：C 端助手消息经 `frontend/mini-app/src/utils/richText.ts`
 *   的 `parseRichText` **真的解析** `**x**`（那是既有渲染约定，不是泄漏），
 *   一律禁 `**` 会误伤它的掩码与正则字面量。
 * - 检测面**不含**各包的 `tests/`：用例标题里写 `**强调**` 是**自述**，不上屏。
 */
import { describe, expect, it } from 'vitest'
import { readdirSync, readFileSync } from 'node:fs'
import { join, relative } from 'node:path'
import ts from 'typescript'

/** 掩码字面量（**不是** markdown）：全星号串 —— 客户手机号脱敏用 */
const MASK_ONLY = /^\*+$/

/** 登记表：允许出现的 `**`（**逐字相等**，不是模式）—— 每一项都必须仍在源码里（陈旧即红，见 ④） */
const REGISTERED = ['****'] as const

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

describe('商家可见文案不得漏出 markdown 强调标记（issue #5194 / §22）', () => {
  it('① 正控：检测器对成对与未闭合的 `**` 都必须报出（否则「零违规」是空断言）', () => {
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

  it('③ 真实源码面：零违规（红证 = 塞回一处 `**` ⇒ 本条判红并打印文件:行）', () => {
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

    const leaks = files.flatMap((f) => findEmphasisLeaks(relative(process.cwd(), f), readFileSync(f, 'utf-8')))
    expect(
      leaks.map((l) => `${l.file}:${l.line} [${l.kind}] ${l.text}`),
      '商家可见文案里仍有 markdown 强调标记 `**`（纯文本插值 ⇒ 原样上屏成字面星号）',
    ).toEqual([])
  })

  it('④ 登记表陈旧即红：登记过的掩码字面量必须仍在源码里（否则请删条目）', () => {
    const all = SRC_DIRS.flatMap((d) => sourceFiles(d).map((f) => readFileSync(f, 'utf-8'))).join('\n')
    const missing = REGISTERED.filter((m) => !all.includes(`'${m}'`))
    expect(
      missing,
      '登记表里的掩码字面量在源码里已不存在 ⇒ 条目陈旧，请从 REGISTERED 删掉（留着会让判据悄悄放宽）',
    ).toEqual([])
  })
})
