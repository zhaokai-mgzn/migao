// case_ids: BM-051
/**
 * 工人可见文案「纯文本」类级守卫（issue #7316）
 *
 * 治的病：**给商家 / 工人看的字，是给评审 / 研发看的写法**。
 * 两个真实形态（2026-10-19 用户逐字「markdown语法未正确渲染，显示成了**不会**」
 * 「不会调用识别模型这句文案应该改一下，改成工人能理解的文字」）：
 * ① Taro `<Text>` **不渲染 markdown** ⇒ 源里的 `**不会**` 把两个星号原样印在工人手机上；
 * ② 研发术语上屏（「本机直接解码」「调用识别模型」「服务端识别」）—— 工人看不懂，也不知道下一步做什么。
 *
 * 为什么是**类级**而不是再补一条实例断言：这两类文案缺陷都不挑页面 ——
 * 谁在 JSX 里写一句带 `**` 的话、谁把服务端视角的词抄进提示，就得有人重新发现一次。
 * 所以本守卫扫**全部工人页面**（`src/pages/worker/**`）+ 页面直渲的文案源（`COPY_SOURCES`，登记制）。
 *
 * 射程边界（照实登记）：判的是「**会不会被工人看到**」，不是「源码里有没有这个词」——
 * 注释 / JSDoc / `src/utils/inbound/gaps.ts` 这类**研发台账**（从不上屏）不在射程内；
 * 纯逻辑字符串（无中文）也不在射程内。
 */
import fs from 'fs'
import path from 'path'
import ts from 'typescript'

const ROOT = path.resolve(__dirname, '..')

/** 工人可见页面目录（JSX 文本 + 中文字面量都会被扫） */
const PAGE_DIR = path.join(ROOT, 'src/pages/worker')

/**
 * 页面直接渲染的文案源（**登记制**：新增一处「页面拿 utils 文案直接上屏」就登记进来）。
 * 不登记 `reprintFlow.ts` / `gaps.ts` / `pageEntries.ts` —— 它们同时承载**研发登记表**
 * （`why` / `audience` 这类字段里的中文本来就用 markdown 写实现细节，且从不上屏），
 * 整文件扫描会把台账误报成工人文案；`reprintFlow.ts` 的唯一上屏文案
 * （`REPRINT_DETAIL_ERROR_MESSAGE`）由 `tests/inbound-reprint-flow.test.ts::F5b` 实例判据覆盖。
 */
const COPY_SOURCES = [
  'src/utils/inbound/recognizeFlow.ts',
  'src/utils/inbound/barcodeDecode.ts',
  'src/utils/inbound/recognizeGate.ts',
]

/** markdown 强调标记（Taro 不渲染 ⇒ 原样上屏） */
const BOLD_MARKERS = /\*\*|__/

/** 研发术语（工人视角应有的是「后果 + 该做什么」） */
const JARGON = /识别模型|大模型|LLM|服务端|解码/

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

/** 抽「工人可能看到的字」：JSX 文本 + 字符串 / 模板串字面量（只留含中文的） */
function collectUserFacingText(): Hit[] {
  const files = [...listSourceFiles(PAGE_DIR), ...COPY_SOURCES.map((rel) => path.join(ROOT, rel))]
  const hits: Hit[] = []
  for (const file of files) {
    const source = fs.readFileSync(file, 'utf8')
    const sf = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true, file.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS)
    const push = (node: ts.Node, text: string) => {
      if (!/[\u4e00-\u9fa5]/.test(text)) return
      hits.push({
        file: path.relative(ROOT, file),
        line: sf.getLineAndCharacterOfPosition(node.getStart(sf)).line + 1,
        text: text.trim(),
      })
    }
    const visit = (node: ts.Node) => {
      if (ts.isJsxText(node)) push(node, node.getText(sf))
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
const format = (hit: Hit) => `${hit.file}:${hit.line} → ${hit.text.slice(0, 80)}`

describe('工人可见文案：纯文本（无 markdown 标记、无研发术语）', () => {
  it('判别力自证：扫描器真读到了文案（路径写错 ⇒ 零命中会假装通过）', () => {
    expect(HITS.length).toBeGreaterThan(10)
    // 三个页面都在射程内（各自至少一条中文文案被抽到）
    for (const page of ['src/pages/worker/inbound/index.tsx', 'src/pages/worker/reprint/index.tsx', 'src/pages/worker/shipment/index.tsx']) {
      expect(HITS.some((hit) => hit.file === page)).toBe(true)
    }
    // 文案源也在射程内（改完后的正向锚点）
    expect(HITS.some((hit) => hit.text.includes('换一种方式再认一次'))).toBe(true)
  })

  it('判据 1：工人页面上不出现 markdown 强调标记（`**` / `__` 会原样印在手机上）', () => {
    expect(HITS.filter((hit) => BOLD_MARKERS.test(hit.text)).map(format)).toEqual([])
  })

  it('判据 2：工人页面上不出现研发术语（识别模型 / 服务端 / 解码 …）', () => {
    expect(HITS.filter((hit) => JARGON.test(hit.text)).map(format)).toEqual([])
  })
})
