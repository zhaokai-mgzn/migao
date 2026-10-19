// case_ids: BM-051
/**
 * 手机端页面文案「纯文本」类级守卫（issue #7316）
 *
 * 治的病：**给工人 / 商家看的字，是给评审 / 研发看的写法**。
 * 两个真实形态（2026-10-19 用户逐字「markdown语法未正确渲染，显示成了**不会**」
 * 「不会调用识别模型这句文案应该改一下，改成工人能理解的文字」）：
 * ① Taro `<Text>` **不渲染 markdown** ⇒ 源里的 `**不会**` 把两个星号原样印在手机上；
 * ② 研发术语上屏（「本机直接解码」「调用识别模型」「服务端识别」）—— 工人看不懂，也不知道下一步做什么。
 *
 * 为什么是**类级**而不是再补一条实例断言：这两类文案缺陷都不挑页面 ——
 * 谁在 JSX 里写一句带 `**` 的话、谁把服务端视角的词抄进提示，就得有人重新发现一次。
 * 所以本守卫扫：
 *  - **全部页面与共享组件**（`src/pages/**` + `src/components/**`：JSX 文本 + 字面量）；
 *  - **页面直渲的文案源**（`COPY_SOURCES`，**登记制**）：`all` = 整文件所有中文字面量都上屏；
 *    `exported` = 只扫**顶层导出的字符串常量**（同文件里还混着研发台账，如 `gaps.ts` / `reprintFlow.ts`
 *    的 `why` / `audience` 字段 —— 那些从不上屏，且本来就用 markdown 写实现细节）。
 *
 * 规则（两条，都带判别力自证）：
 *  1. **零 markdown 标记**：`**` / `__`（强调）、`` `x` ``（行内代码）、行首 `#`（标题）——
 *     包括被拆到多个 JSX 子节点里的裸标记（`<Text>{'**'}{n}{'**'}</Text>`）；
 *  2. **零研发术语**：识别模型 / 大模型 / LLM / 服务端 / 后端 / 解码 / 接口 / 安全上下文 / 落库 / 幂等。
 *
 * 射程边界（照实登记）：判的是「**会不会被手机用户看到**」，不是「源码里有没有这个词」——
 * 注释 / JSDoc 不在射程；纯逻辑字符串（无中文、且不是裸标记）不在射程；
 * `productionOffline.ts` 的 `补传被服务端拒绝` 目前**无入队调用点**（本仓不可达），未登记；
 * admin-web 另有同口径机械面（`user-copy-scan.mjs` + `user-copy-jargon-guard.test.ts`）。
 */
import fs from 'fs'
import path from 'path'
import ts from 'typescript'

const ROOT = path.resolve(__dirname, '..')

/** 页面与共享组件（JSX 文本 + 字面量都会被扫） */
const SCAN_DIRS = ['src/pages', 'src/components']

/**
 * 页面直接渲染的文案源（**登记制**：新增一处「页面拿 utils 文案直接上屏」就登记进来）。
 * `all` = 文件里所有中文串都上屏（`notices` / hint / message）；
 * `exported` = 只扫顶层导出的字符串常量（文件里同时有研发台账，台账字段从不上屏）。
 */
const COPY_SOURCES: { file: string; mode: 'all' | 'exported' }[] = [
  { file: 'src/utils/inbound/recognizeFlow.ts', mode: 'all' },
  { file: 'src/utils/inbound/barcodeDecode.ts', mode: 'all' },
  { file: 'src/utils/inbound/recognizeGate.ts', mode: 'all' },
  { file: 'src/utils/inbound/printCapability.ts', mode: 'all' },
  { file: 'src/utils/inbound/gaps.ts', mode: 'exported' },
  { file: 'src/utils/inbound/reprintFlow.ts', mode: 'exported' },
]

/** markdown 强调 / 行内代码 / 标题（Taro 不渲染 ⇒ 原样上屏） */
const MARKDOWN = /\*\*|__|`[^`]+`|(^|\n)\s*#{1,6}\s/
/** 裸标记被拆到多个 JSX 子节点里的形态（`{'**'}{n}{'**'}`） */
const BARE_MARKER = /^(\*\*|__|`)$/
/** 研发术语 / 研发过程语（手机端文案应有的是「后果 + 该做什么」） */
const JARGON = /识别模型|大模型|LLM|服务端|后端|解码|接口|安全上下文|落库|幂等|裁定|判据|快照/
const CJK = /[\u4e00-\u9fa5]/

interface Hit {
  file: string
  line: number
  text: string
}

function listSourceFiles(dir: string): string[] {
  const out: string[] = []
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) out.push(...listSourceFiles(full))
    else if (/\.tsx?$/.test(entry.name)) out.push(full)
  }
  return out
}

/** 抽「手机用户可能看到的字」 */
function collectUserFacingText(): Hit[] {
  const files = [
    ...SCAN_DIRS.flatMap((dir) => listSourceFiles(path.join(ROOT, dir))),
    ...COPY_SOURCES.map(({ file }) => path.join(ROOT, file)),
  ]
  const exportedOnly = new Set(COPY_SOURCES.filter((s) => s.mode === 'exported').map((s) => s.file))
  const hits: Hit[] = []
  for (const file of files) {
    const source = fs.readFileSync(file, 'utf8')
    const rel = path.relative(ROOT, file)
    const sf = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true, file.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS)
    const push = (node: ts.Node, text: string) => {
      hits.push({
        file: rel,
        line: sf.getLineAndCharacterOfPosition(node.getStart(sf)).line + 1,
        text: text.trim(),
      })
    }
    const visit = (node: ts.Node) => {
      if (exportedOnly.has(rel)) {
        // 只认「export const X = '…'」这类**上屏常量**；台账（数组 / 对象字段）跳过
        if (ts.isVariableStatement(node) && node.modifiers?.some((m) => m.kind === ts.SyntaxKind.ExportKeyword)) {
          for (const decl of node.declarationList.declarations) {
            if (decl.initializer && (ts.isStringLiteral(decl.initializer) || ts.isNoSubstitutionTemplateLiteral(decl.initializer))) {
              push(decl.initializer, decl.initializer.text)
            }
          }
        }
      } else if (ts.isJsxText(node)) push(node, node.getText(sf))
      else if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) push(node, node.text)
      else if (ts.isTemplateExpression(node)) {
        push(node, node.head.text)
        node.templateSpans.forEach((span) => push(span.literal, span.literal.text))
      }
      ts.forEachChild(node, visit)
    }
    visit(sf)
  }
  return hits
}

const HITS = collectUserFacingText()
const format = (hit: Hit) => `${hit.file}:${hit.line} → ${hit.text.slice(0, 100)}`

describe('手机端页面文案：纯文本（无 markdown 标记、无研发术语）', () => {
  it('判别力自证：扫描器真读到了文案（路径写错 ⇒ 零命中会假装通过）', () => {
    expect(HITS.length).toBeGreaterThan(20)
    // 三个被用户点名的页面 + 每个登记在案的文案源都在射程内
    for (const file of [
      'src/pages/worker/inbound/index.tsx',
      'src/pages/worker/reprint/index.tsx',
      'src/pages/worker/shipment/index.tsx',
      ...COPY_SOURCES.map((s) => s.file),
    ]) {
      expect(HITS.some((hit) => hit.file === file)).toBe(true)
    }
  })

  it('判据 1：手机端页面上不出现 markdown 标记（`**` / `__` / 反引号 / 标题会原样上屏）', () => {
    const offenders = HITS.filter((hit) => CJK.test(hit.text)).filter((hit) => MARKDOWN.test(hit.text))
    // 裸标记可能被拆到独立 JSX 子节点（无中文）—— 单独按「整段就是一个标记」判
    const bare = HITS.filter((hit) => BARE_MARKER.test(hit.text))
    expect([...offenders, ...bare].map(format)).toEqual([])
  })

  it('判据 2：手机端页面上不出现研发术语（识别模型 / 服务端 / 解码 / 接口 …）', () => {
    const offenders = HITS.filter((hit) => CJK.test(hit.text)).filter((hit) => JARGON.test(hit.text))
    expect(offenders.map(format)).toEqual([])
  })
})
