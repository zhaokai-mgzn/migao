// case_ids: UI-083
/**
 * `fixed` × CSS 包含块守卫（issue #6339）—— 治「`fixed` 元素落在 `backdrop-filter` / `transform`
 * 祖先内 ⇒ `inset-0` 不再相对视口、只盖住**祖先盒子**」这一类缺陷。
 *
 * ## 病根（真实缺陷，2026-10-05 用户报告）
 *
 * 右上角用户卡片展开后**点页面其他区域收不回去**。承载实现是 `Header.tsx` 里一个
 * `<div className="fixed inset-0 z-40" onClick={...} />` 透明遮罩，而它所在的 `<header>` 带
 * `backdrop-blur-sm`。CSS 规范：`backdrop-filter` 非 `none` 的元素是 `position: fixed` 后代的
 * **包含块**（同族：`filter` / `transform` / `perspective` / `will-change` / `contain: paint`）
 * ⇒ 该遮罩的 `inset-0` 相对的是 **header 盒子（`h-14` = 56px 顶栏带）**、不是视口。
 * 两个可观察后果：① 内容区点击落不到遮罩上 ⇒ 卡片永不收起；② 顶栏那一带被遮罩吃掉点击（铃铛点不开）。
 *
 * ## 为什么此前没有东西会变红
 *
 * jsdom **不做布局** —— `fixed inset-0` 在单测里就是「一个盖满屏的 div」，行为面看不出差别。
 * 而 `UI-037` 的验收项写着「点击卡片外收起」，其判据是**在 jsdom 里点那个遮罩本身**
 * ⇒ 遮罩就算只盖住 56px，它也照样「绿」（`migao-dev-flow` §15.7 的「标记在 ≠ 渲染对」）。
 * 没有布局引擎能判这件事 ⇒ 判据只能是**静态的**：AST 上一次，此后任何文件再犯当场红。
 *
 * ## 判据（TypeScript AST，不做正则近似）
 *
 * 遍历 `src/` 下全部 `.tsx`，维护 **JSX 祖先栈**；元素 `className` 含 `fixed` 时，若任一**祖先**的
 * `className` 命中会生成包含块的类（`CONTAINING_BLOCK_EXACT` / `CONTAINING_BLOCK_PREFIX`），即判红，
 * 并具名报出「文件:行 ← 祖先行 + 命中类」。`className` 取字符串字面量与 `cn(...)` 之类的表达式实参。
 *
 * ## 红证（实测读数，非推理）
 *
 * - **修复前**（真语料全扫）：1 条 —— 命中文件 = 仓库相对路径 `frontend/admin-web/src/components/layout/Header.tsx`，
 *   命中祖先类 = `backdrop-blur-sm`（命中行就是修复前那个 `fixed inset-0` 遮罩）；
 * - **修复后**（同一命令）：0 条；
 * - **判别力自证**（本文件末尾的注入用例，不依赖真语料）：把修复前的形态喂进扫描器 ⇒ 必须红；
 *   对照组 `transition-transform`（含 `transform` 子串、但**不**生成包含块）⇒ 必须**不**红（防假红）。
 * - 复算命令（在 `frontend/admin-web` 下）：`npx vitest run tests/unit/lib/fixed-containing-block.test.ts`
 *
 * ## 边界（如实登记，不当成「通过」）
 *
 * - 只判**同一文件内**的 JSX 祖先：跨文件形态（子组件自渲染 `fixed`、带 `backdrop-blur` 的祖先在
 *   另一个文件）**判不了** —— 本仓当前不存在该形态（全扫 0 条），但不为将来背书；
 * - 只认 `fixed`：`absolute` 本就相对最近的定位祖先，属**有意行为**，不在判据内；
 * - 类名清单是 Tailwind 工具类，覆盖不到 `style={{ filter: ... }}` 内联样式与自定义 CSS。
 */
import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'
import ts from 'typescript'

const SRC_DIR = path.resolve(__dirname, '../../../src')

/** 生成包含块的**精确**类（子串相同但语义不同的类，如 `transition-transform`，**不在**此列） */
const CONTAINING_BLOCK_EXACT = new Set([
  'transform',
  'transform-gpu',
  'filter',
  'backdrop-filter',
  'invert',
  'grayscale',
  'sepia',
])

/** 生成包含块的**前缀**类（Tailwind 的 filter / transform / 包含块工具类；`container` 不在其中） */
const CONTAINING_BLOCK_PREFIX = [
  'backdrop-blur',
  'blur',
  'brightness-',
  'contrast-',
  'drop-shadow-',
  'hue-rotate-',
  'saturate-',
  'translate-',
  'scale-',
  'rotate-',
  'skew-',
  'will-change-',
  'perspective-',
  'contain-',
]

/** `className` 里命中「生成包含块」的类（变体前缀 `hover:` / `md:` 与负号 `-translate-x-1` 都已归一） */
export function containingBlockTokens(className: string): string[] {
  return className
    .split(/\s+/)
    .filter(Boolean)
    .map((c) => (c.replace(/^-/, '').split(':').pop() || '').trim())
    .filter((t) => t && (CONTAINING_BLOCK_EXACT.has(t) || CONTAINING_BLOCK_PREFIX.some((p) => t.startsWith(p))))
}

/** 取 JSX 元素的 `className` 文本（字符串字面量 / 模板 / 表达式实参拼接）；无该属性 ⇒ `null` */
function classNameOf(attributes: ts.JsxAttributes): string | null {
  for (const prop of attributes.properties) {
    if (!ts.isJsxAttribute(prop) || prop.name.getText() !== 'className') continue
    if (!prop.initializer) return ''
    if (ts.isStringLiteral(prop.initializer)) return prop.initializer.text
    if (ts.isJsxExpression(prop.initializer) && prop.initializer.expression) {
      const parts: string[] = []
      const collect = (n: ts.Node) => {
        if (ts.isStringLiteral(n) || ts.isNoSubstitutionTemplateLiteral(n)) parts.push(n.text)
        n.forEachChild(collect)
      }
      collect(prop.initializer.expression)
      return parts.join(' ')
    }
  }
  return null
}

export interface FixedUnderContainingBlock {
  file: string
  line: number
  ancestorLine: number
  ancestorTokens: string[]
}

/** 单文件扫描：`fixed` 元素 × 生成包含块的 JSX 祖先 */
export function findFixedUnderContainingBlock(fileName: string, source: string): FixedUnderContainingBlock[] {
  const sf = ts.createSourceFile(fileName, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
  const found: FixedUnderContainingBlock[] = []
  const ancestors: { className: string; line: number }[] = []
  const lineOf = (n: ts.Node) => sf.getLineAndCharacterOfPosition(n.getStart(sf)).line + 1

  const visit = (node: ts.Node) => {
    let attributes: ts.JsxAttributes | null = null
    if (ts.isJsxElement(node)) attributes = node.openingElement.attributes
    else if (ts.isJsxSelfClosingElement(node)) attributes = node.attributes

    let pushed = false
    if (attributes) {
      const className = classNameOf(attributes)
      if (className !== null && className.split(/\s+/).includes('fixed')) {
        const hit = [...ancestors].reverse().find((a) => containingBlockTokens(a.className).length > 0)
        if (hit) {
          found.push({
            file: fileName,
            line: lineOf(node),
            ancestorLine: hit.line,
            ancestorTokens: containingBlockTokens(hit.className),
          })
        }
      }
      ancestors.push({ className: className ?? '', line: lineOf(node) })
      pushed = true
    }

    node.forEachChild(visit)
    if (pushed) ancestors.pop()
  }

  visit(sf)
  return found
}

function tsxFiles(dir: string): string[] {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const p = path.join(dir, e.name)
    if (e.isDirectory()) return tsxFiles(p)
    return e.name.endsWith('.tsx') ? [p] : []
  })
}

const describeHit = (h: FixedUnderContainingBlock) =>
  `${path.relative(SRC_DIR, h.file)}:${h.line} ← 祖先 L${h.ancestorLine} ${h.ancestorTokens.join(',')}`

describe('`fixed` 元素不得落在生成包含块的祖先内（issue #6339 / UI-083）', () => {
  it('检出面非空 —— 解析/遍历失灵时不至于在空集上恒真', () => {
    const files = tsxFiles(SRC_DIR)
    // 实测 161 个 .tsx（2026-10-05）；写死下限只为拦住「遍历返回空集」这类退化
    expect(files.length).toBeGreaterThanOrEqual(100)
    expect(files.some((f) => f.endsWith('components/layout/Header.tsx'))).toBe(true)
  })

  it('🔴 真语料：`src/**/*.tsx` 里没有任何 `fixed` 元素落在包含块祖先内', () => {
    const hits = tsxFiles(SRC_DIR).flatMap((f) =>
      findFixedUnderContainingBlock(f, fs.readFileSync(f, 'utf8')),
    )
    // 修复前该断言的实际读数（具名）：1 条 —— 带 backdrop-blur-sm 的 <header> 之下的 fixed inset-0 遮罩行
    // （路径经 `git show origin/main:frontend/admin-web/src/components/layout/Header.tsx` 复核）
    expect(hits.map(describeHit)).toEqual([])
  })
})

describe('判别力自证（注入合成片段；真语料全绿时仍证明本扫描器抓得住）', () => {
  it('修复前的形态（header backdrop-blur 内放 fixed inset-0 遮罩）⇒ 必须红', () => {
    const hits = findFixedUnderContainingBlock(
      'injected.tsx',
      `<header className="sticky top-0 backdrop-blur-sm">\n  <div className="fixed inset-0 z-40" onClick={() => {}} />\n</header>`,
    )
    expect(hits.map((h) => h.line)).toEqual([2])
    expect(hits[0].ancestorTokens).toContain('backdrop-blur-sm')
    expect(hits[0].ancestorLine).toBe(1)
  })

  it('对照组：祖先不带包含块类 ⇒ 不红', () => {
    const hits = findFixedUnderContainingBlock(
      'clean.tsx',
      `<div className="relative">\n  <div className="fixed inset-0" />\n</div>`,
    )
    expect(hits).toEqual([])
  })

  it('对照组：`transition-transform` 只是子串、不生成包含块 ⇒ 不红（防假红）', () => {
    const hits = findFixedUnderContainingBlock(
      'substring.tsx',
      `<div className="transition-transform duration-200">\n  <div className="fixed inset-0" />\n</div>`,
    )
    expect(hits).toEqual([])
  })

  it('对照组：`translate-x-*` / `scale-*` / `will-change-*` 变体与负号形态 ⇒ 必须红', () => {
    for (const cls of ['md:translate-x-2', '-translate-y-1', 'hover:scale-105', 'will-change-transform', 'contain-paint']) {
      const hits = findFixedUnderContainingBlock(
        'variant.tsx',
        `<div className="${cls}">\n  <div className="fixed inset-0" />\n</div>`,
      )
      expect(hits, `${cls} 应当被判为包含块祖先`).toHaveLength(1)
    }
  })
})
