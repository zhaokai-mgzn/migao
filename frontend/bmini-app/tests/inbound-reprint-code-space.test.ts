// case_ids: BM-020, BM-021, BM-022
/**
 * 拍照**补打**：码空间判定 + 手输兜底 + 同族复用（issue #5640；设计 §7.1）
 *
 * 本文件是本单的**类级元守卫**所在（AGENTS.md 铁律 8 / `migao-dev-flow` §23）。本单最值得固化的两类：
 *
 * ### ① 「**两套码空间被当成一套用**」
 *
 * 入库标签 = `https://app.migaozn.com/i/<短码>`（承载 `inbound_labels`），洗水码 / 报工短链 =
 * `.../s/<短码>`（承载 `processing_set_part_tokens`，302 → `/w/?t=`）。两者**短码规格故意同款**
 * （8 位 Crockford Base32）——「规格同款」是为了**人可读可抄**，不是为了**可以互相串**。
 * 串了的下场：工人拍一张洗水码 ⇒ 去查入库单 ⇒ 404 ⇒ 界面说「查无此码」，而真相是**走错了门**。
 * 服务端那一侧已有静态守卫（`tests/unit_ci_workflows/test_public_code_spaces_are_disjoint.py`）；
 * 端侧这一半（码是**在手机上**被判定分流的地方）此前**没有任何判据**。
 *
 * ### ② 「**同族页面各写一套流程，第二套必然与第一套分叉**」
 *
 * 补打页与 P3 的入库页是**同族页面**：同一个版面（`layoutInboundLabel`）、同一个渲染器
 * （`renderInboundLabel`）、同一个送打印入口（`printInboundLabel`）、同一个画布工厂。
 * 「复制一份改改」在这里是**静默分叉**：改一处版面不会改另一处，而两边**都不会报错**
 * ⇒ 判据 = 射程内每个渲染标签的页面都必须**引用**这些共用件，且不得自带第二份
 * （`qrcode(` 版面、直连 `printImageData`、手写端点 URL、像素字面量）。
 *
 * | # | 判据 | 红证（怎么让它单独变红） |
 * |---|---|---|
 * | S1 | 扫到 `/i/<短码>` ⇒ 入库空间，短码取自 URL **原样**（客户端不归一化） | 把短码 `.toUpperCase()`/`.replace` ⇒ 红 |
 * | S2 | 🔴 扫到 `/s/<短码>` ⇒ **洗水码空间** + 报工入口（不是入库标签） | 不看码空间直接取路径段 ⇒ 红（S2 的 `treatAsInbound` 复刻） |
 * | S3 | 非米高二维码（别的域名 / 纯文本）⇒ **明确告知** | 靠「含 `/i/` 就当入库」⇒ 红（别的域名的 `/i/` 会命中） |
 * | S4 | 手输含 `O`/`I`/`L` 的 8 位 ⇒ 入库空间且**原样**交给服务端归一化 | 用严格字母表 `isValidShortCode` 当闸 ⇒ 红（本单指定的红证） |
 * | S5 | 手输形态不合法（非 8 位 / 含符号）⇒ 明说「8 位」**且一次请求都不发** | 放行任意字符串 ⇒ 红 |
 * | G1 | 两个码空间的**前缀**与后端逐值一致（`/s/` 与 `/i/` 各一处真值） | 客户端另抄一份前缀 ⇒ 红 |
 * | G2 | 🔴 「谁可以查入库详情」有台账：**调用点级**（文件 + 所在函数 + 出现次数），未登记即红、条目必须活着；受门禁的调用点**其所在函数**必须引用码空间判定 | 在**已登记页面**里加一处不经 `loadReprintDetail` 的 `getInboundLabel(...)` ⇒ 红 |
 * | G3 | 🔴 同族页面必须复用共用件、不得自带第二份（注入式红证） | 任一页面删掉 `printInboundLabel` 引用 ⇒ 判定函数点名判红 |
 */
import fs from 'fs'
import path from 'path'
import {
  FOREIGN_CODE_MESSAGE,
  MANUAL_CODE_INVALID_MESSAGE,
  REPORT_PAGE_ROUTE,
  UNDECODED_CODE_MESSAGE,
  WASH_CODE_ACTION,
  WASH_CODE_MESSAGE,
  WASH_CODE_PATH,
  classifyManualCode,
  classifyScannedCode,
} from '../src/utils/inbound/codeSpace'
import { LABEL_DETAIL_CALLERS } from '../src/utils/inbound/reprintFlow'
import { isValidShortCode } from '../src/utils/inbound/shortCode'
import { INBOUND_LABEL_CODE_PATH, inboundLabelGeometry } from '../src/utils/inbound/truth'
import { BMINI_ROOT, SRC_DIR, stripComments, walk } from './helpers/h5PlatformLists'
import { callSites } from './helpers/inboundCallSites'

const REPO_ROOT = path.join(BMINI_ROOT, '..', '..')

function readRepo(rel: string): string {
  const abs = path.join(REPO_ROOT, rel)
  if (!fs.existsSync(abs)) throw new Error(`找不到受管文件：${rel}（路径漂移不得静默跳过 ⇒ 红）`)
  return fs.readFileSync(abs, 'utf8')
}

function readSrc(relFromBmini: string): string {
  const abs = path.join(BMINI_ROOT, relFromBmini)
  if (!fs.existsSync(abs)) throw new Error(`找不到受管文件：${relFromBmini}（路径漂移不得静默跳过 ⇒ 红）`)
  return fs.readFileSync(abs, 'utf8')
}

/** `src/**` 里所有 `.ts` / `.tsx`（相对 bmini 根的路径） */
function srcFiles(): string[] {
  return walk(SRC_DIR, (name) => /\.tsx?$/.test(name)).map((abs) => path.relative(BMINI_ROOT, abs))
}

/**
 * 错误形态（本单要防的那件事）：不看码空间，直接把扫到的 URL 的最后一段当入库短码。
 *
 * 它**确实能**从一个 `/s/` 的码里取出一段像模像样的 8 位短码 ⇒ 后面的 404「查无此码」
 * 会把人引向「是不是抄错了」，而真相是**走错了门**。判据 S2 就是把它拦下来的那一步。
 */
function treatAsInboundShortCode(raw: string): string | null {
  const segment = String(raw).split('/').filter(Boolean).pop() || null
  return segment && segment.length === 8 ? segment : null
}

/**
 * 码空间门禁的判定（真判据与注入式红证**共用同一份**，见 `migao-dev-flow` §23.5）。
 * 坏形态 = 上面那个"裸取路径段"的替身；它**确实**能从 `/s/` 的码里取出一段像模像样的 8 位短码。
 */
function spaceGateProblems(take: (raw: string) => string | null): string[] {
  const washCode = 'https://app.migaozn.com/s/7K3M9QP2'
  if (take(washCode) === '7K3M9QP2') {
    return [
      `没有码空间门禁：洗水码 ${washCode} 被当成了入库短码 ⇒ 会去查一次入库详情，` +
        `然后报「查无此码」—— 把人引向"是不是抄错了"，而真相是走错了门`,
    ]
  }
  return []
}

/** 真实现：只有 `inbound-label` 空间谈得上"入库短码" */
function gatedShortCode(raw: string): string | null {
  const reading = classifyScannedCode(raw)
  return reading.space === 'inbound-label' ? reading.shortCode : null
}

/** 手输长度闸的判定（真判据与注入式红证共用同一份） */
function lengthGateProblems(classify: (raw: string) => { shortCode: string | null }): string[] {
  const leaked = ['ABCD2', 'ABCD23456', '短码'].filter((raw) => classify(raw).shortCode !== null)
  return leaked.length > 0
    ? [`非 8 位的手输也被放行：${leaked.join(' / ')} ⇒ 会白发一次请求（端侧应先明说"要 8 位"）`]
    : []
}

/** 「路径里有 `/i/` 就当入库」这条宽松口径的判定（真判据与注入式红证共用同一份） */
function loosePathProblems(classify: (raw: string) => { space: string }): string[] {
  const foreign = 'https://example.com/i/ABCD2345'
  return classify(foreign).space === 'inbound-label'
    ? [`别的域名里的 /i/ 被当成了米高标签：${foreign} ⇒ 会去查一次入库详情`]
    : []
}

/**
 * 「谁可以查入库详情」的**调用点级**判定（真判据与注入式红证共用同一份）。
 *
 * 历史缺陷（issue #5052 验收 D7-②）：旧口径只比对**文件集合** ⇒ 在**已登记文件**里
 * 新加一处绕过门禁的调用仍然全绿。现在按「文件 + 所在函数 + 出现次数」逐点核验。
 */
function detailCallSiteProblems(
  files: { file: string; code: string }[],
  ledger: typeof LABEL_DETAIL_CALLERS,
): string[] {
  const problems: string[] = []
  const actual = new Map<string, { count: number; span: string }>()
  for (const source of files) {
    const code = stripComments(source.code)
    for (const site of callSites(code, /getInboundLabel\s*\(/g)) {
      const key = `${source.file}::${site.fn || '<模块顶层>'}`
      const hit = actual.get(key) || { count: 0, span: site.span }
      hit.count += 1
      actual.set(key, hit)
    }
  }
  const declared = new Map(ledger.map((item) => [`${item.file}::${item.in}`, item]))
  for (const [key, hit] of actual) {
    const item = declared.get(key)
    if (!item) {
      problems.push(`${key}: 新增了一个查入库详情的**调用点**却没登记（未登记即红）`)
      continue
    }
    if (item.calls !== hit.count) {
      problems.push(
        `${key}: 这个函数里 getInboundLabel(…) 出现 ${hit.count} 次，台账登记 ${item.calls} 次 —— ` +
          `多一处 / 少一处都要同步台账（**调用点级**，不是文件级）`,
      )
    }
    if (item.gatedByCodeSpace && !/loadReprintDetail|classifyScannedCode|classifyManualCode/.test(hit.span)) {
      problems.push(
        `${key}: 这一处调用**所在的函数**没有引用码空间门禁（文件级引用不算）—— ` +
          `洗水码会在这里被当成入库码查一次`,
      )
    }
  }
  for (const [key, item] of declared) {
    if (!actual.has(key)) problems.push(`src 里已经没有这个调用点：${key}（台账只许缩短）`)
    if (item.why.trim().length <= 8) problems.push(`${key}: 没写清这一处为什么可以不经码空间门禁`)
  }
  return problems
}

/**
 * 像素口径探针 —— **从真值源派生**，不在这里复述数字：
 * `tests/inbound-print-geometry-single-source.test.ts` 的 C2 会扫全仓「同时写着那组像素口径」的文件，
 * 判据自己复述一遍就会被自己判红（`migao-dev-flow` §23.8 B1：判据语料必须排除判据自身）。
 */
const PIXEL_PROBE = new RegExp(
  `\\b(${[inboundLabelGeometry().effectiveWidthPx, inboundLabelGeometry().heightPx].join('|')})\\b`,
)

/**
 * 纸型字面量探针（**类级**，不写死具体毫米数）。
 *
 * 历史形态：这里原本是 `/50mm\s*30mm|50×30/` —— 标签改成 30×40 之后那条正则**静默失效**
 * （守卫还在、还会绿，只是再也抓不到任何东西）。⇒ 改成「任意 `宽mm × 高mm` / `宽mm 高mm` 形态」，
 * 换纸型时不需要人记得回来改这一行。
 */
const PAPER_SIZE_PROBE =
  /\d+(?:\.\d+)?\s*mm\s*[×xX]\s*\d+(?:\.\d+)?\s*mm|\d+(?:\.\d+)?\s*mm\s+\d+(?:\.\d+)?\s*mm/

/** 同族页面的判据函数（真判据 + 注入式红证**共用同一份**判定，见 migao-dev-flow §23.5） */
function labelPageProblems(pages: { file: string; code: string }[]): string[] {
  const problems: string[] = []
  for (const page of pages) {
    const code = stripComments(page.code)
    if (!/printInboundLabel/.test(code)) problems.push(`${page.file}: 未引用唯一送打印入口 printInboundLabel`)
    if (/qrcode\s*\(/.test(code)) problems.push(`${page.file}: 自带第二份二维码版面（qrcode(…)）`)
    if (/printImageData/.test(code)) problems.push(`${page.file}: 直连传输层（printImageData）绕过送打印入口`)
    if (/\/api\/worker\//.test(code)) problems.push(`${page.file}: 手写端点字面量（应用 INBOUND_ENDPOINTS）`)
    if (PIXEL_PROBE.test(code)) problems.push(`${page.file}: 自带像素口径字面量（应取 inboundLabelGeometry）`)
    if (PAPER_SIZE_PROBE.test(code)) problems.push(`${page.file}: 自带纸型字面量（应取 inboundLabelPageSize）`)
    if (!/createH5CanvasFactory/.test(code)) problems.push(`${page.file}: 未用共用画布工厂（第二份画布实现会分叉）`)
    // 「前端不自行计数」（验收判据 8）：页面里对 `printCount` 做算术 ⇒ 纸上与服务端两份数都不会报错
    if (/printCount\s*(\+\+|[+\-*/]=?)/.test(code) || /(\+\+|--)\s*\w*printCount/.test(code)) {
      problems.push(`${page.file}: 对 printCount 做了本地算术（前端不自行计数）`)
    }
  }
  return problems
}

/** 渲染入库标签的页面（发现形态：引用渲染器 = 这个页面在出标签） */
function labelRenderingPages(): { file: string; code: string }[] {
  return srcFiles()
    .filter((rel) => rel.startsWith('src/pages/') && /\.tsx$/.test(rel))
    .map((rel) => ({ file: rel, code: readSrc(rel) }))
    .filter((page) => /renderInboundLabel/.test(page.code))
}

/** `function createH5CanvasFactory` 的定义处（必须恰好一处 = 共用件本身） */
function canvasFactoryDefinitions(): string[] {
  return srcFiles().filter((rel) => /function createH5CanvasFactory/.test(readSrc(rel)))
}

/** 全仓（`src/**`）里写着洗水码前缀字面量的文件（真值只许在 `codeSpace.ts` 一处） */
function washPrefixLiteralFiles(): string[] {
  return srcFiles().filter((rel) => {
    const code = stripComments(readSrc(rel))
    return /'\/s\/'|"\/s\/"/.test(code)
  })
}

/** 后端公开短码前缀（唯一真值 = 两个 `@GetMapping("/x/{shortCode}")`） */
function backendPrefixes(): string[] {
  const controllers = [
    'backend/admin-api/src/main/java/com/migao/admin/controller/WorkerShortLinkController.java',
    'backend/admin-api/src/main/java/com/migao/admin/controller/InboundLabelShortLinkController.java',
  ]
  const prefixes: string[] = []
  for (const rel of controllers) {
    for (const match of readRepo(rel).matchAll(/@GetMapping\(\s*"(\/[a-z])\/\{/g)) prefixes.push(`${match[1]}/`)
  }
  return prefixes.sort()
}

describe('拍照补打：码空间判定与手输兜底（issue #5640）', () => {
  it('S1 扫到 /i/<短码> ⇒ 入库标签空间，短码取自 URL 原样（客户端不归一化）', () => {
    const reading = classifyScannedCode('https://app.migaozn.com/i/ABCD2345')
    expect(reading.space).toBe('inbound-label')
    expect(reading.shortCode).toBe('ABCD2345')
    expect(reading.action).toBeNull()
    expect(reading.message.trim().length).toBeGreaterThan(8)
    // 小写 / 带查询串 / 带尾斜杠：路径段原样取出（大小写与别名一律**留给服务端**归一化）
    expect(classifyScannedCode('https://app.migaozn.com/i/abcd2345?from=paper').shortCode).toBe('abcd2345')
    expect(classifyScannedCode('https://app.migaozn.com/i/7K3M9QP2/').shortCode).toBe('7K3M9QP2')
  })

  it('S2 🔴 扫到 /s/<短码> ⇒ **洗水码**空间 + 报工入口（绝不当作入库标签）', () => {
    const raw = 'https://app.migaozn.com/s/7K3M9QP2'
    const reading = classifyScannedCode(raw)
    expect(reading.space).toBe('wash-code')
    expect(reading.space).not.toBe('inbound-label')
    expect(reading.shortCode).toBe('7K3M9QP2')
    expect(reading.message).toBe(WASH_CODE_MESSAGE)
    expect(reading.message).toContain('水洗唛')
    expect(reading.message).toContain('报工')
    expect(reading.action).toEqual(WASH_CODE_ACTION)
    expect(reading.action?.route).toBe(REPORT_PAGE_ROUTE)
    // 🔴 红证（注入式）：把"**不看码空间**的那条路"喂给**同一判定** ⇒ 必须点名
    expect(spaceGateProblems(treatAsInboundShortCode).join('\n')).toContain('没有码空间门禁')
    // 对照：真实现下同一判定判绿 —— 这一半让本 case 真的**走被测函数**（把它整体禁用 ⇒ 本 case 必红）
    expect(gatedShortCode(raw)).toBeNull()
    expect(gatedShortCode('https://app.migaozn.com/i/7K3M9QP2')).toBe('7K3M9QP2')
    expect(spaceGateProblems(gatedShortCode)).toEqual([])
  })

  it('S3 非米高二维码 ⇒ 明确告知「这不是米高的标签」（别的域名 / 纯文本 / 空）', () => {
    for (const raw of ['https://example.com/i/ABCD2345', 'https://app.migaozn.com/x/ABCD2345', 'MG-1001']) {
      const reading = classifyScannedCode(raw)
      expect({ raw, space: reading.space }).toEqual({ raw, space: 'foreign' })
      expect(reading.message).toBe(FOREIGN_CODE_MESSAGE)
      expect(reading.message).toContain('不是米高的标签')
      expect(reading.shortCode).toBeNull()
    }
    // 红证（注入式）：靠「路径里有 /i/ 就当入库」的宽松口径会把**别人域名**的 /i/ 当成自家标签
    const loosePath = (code: string) => ({ space: /\/i\//.test(code) ? 'inbound-label' : 'foreign' })
    expect(loosePathProblems(loosePath).join('\n')).toContain('别的域名')
    expect(loosePathProblems(classifyScannedCode)).toEqual([])
    // 没解出码 ⇒ 明说（不静默、不猜单）
    expect(classifyScannedCode('').space).toBe('undecoded')
    expect(classifyScannedCode(null).message).toBe(UNDECODED_CODE_MESSAGE)
  })

  it('S4 🔴 手输含 O/I/L 的 8 位 ⇒ 入库空间且**原样**交给服务端归一化', () => {
    const mistyped = classifyManualCode('ABCDO234')
    expect(mistyped.space).toBe('inbound-label')
    expect(mistyped.shortCode).toBe('ABCDO234')
    expect(classifyManualCode('ABCDI234').shortCode).toBe('ABCDI234')
    expect(classifyManualCode('ABCDL234').shortCode).toBe('ABCDL234')
    // 抄写分隔符（空格 / 连字符）会被去掉；大小写与别名**不**在客户端改写
    expect(classifyManualCode(' ABCD O234 ').shortCode).toBe('ABCDO234')
    expect(classifyManualCode('abcd-2345').shortCode).toBe('abcd2345')
    // 整条 URL 粘进来也认（工人会从聊天记录里复制）
    expect(classifyManualCode('https://app.migaozn.com/i/ABCD2345').shortCode).toBe('ABCD2345')
    expect(classifyManualCode('https://app.migaozn.com/s/7K3M9QP2').space).toBe('wash-code')
    // 🔴 红证（本单指定）：把归一化做在客户端、只认严格字母表 ⇒ 这些码**永远送不到**服务端
    const strictOnlyAlphabet = (raw: string) => (isValidShortCode(raw) ? raw : null)
    expect(strictOnlyAlphabet('ABCDO234')).toBeNull()
    expect(isValidShortCode('ABCDI234')).toBe(false)
    expect({ space: mistyped.space, code: mistyped.shortCode }).toEqual({ space: 'inbound-label', code: 'ABCDO234' })
  })

  it('S5 手输形态不合法 ⇒ 明说「8 位」且**一次请求都不发**（不是发出去等 404）', () => {
    for (const raw of ['ABCD2', 'ABCD23456', 'ABCD 23', '短码', '']) {
      const reading = classifyManualCode(raw)
      expect({ raw, space: reading.space }).toEqual({ raw, space: 'invalid-input' })
      expect(reading.shortCode).toBeNull()
      expect(reading.message).toBe(MANUAL_CODE_INVALID_MESSAGE)
      expect(reading.message).toContain('8 位')
    }
    // 🔴 红证（注入式）：放行任意非空串（去掉长度闸）⇒ 同一判定必须点名；
    //    对照 = 真实现（classifyManualCode）下判绿 —— 这一半让本 case 真的走被测函数
    const withoutLengthGate = (raw: string) => ({ shortCode: String(raw).trim() || null })
    expect(lengthGateProblems(withoutLengthGate).join('\n')).toContain('非 8 位')
    expect(lengthGateProblems(classifyManualCode)).toEqual([])
  })

  it('G1 两个码空间各一处真值，且前缀与后端控制器逐值一致', () => {
    expect(WASH_CODE_PATH).toBe('/s/')
    expect(INBOUND_LABEL_CODE_PATH).toBe('/i/')
    expect(WASH_CODE_PATH).not.toBe(INBOUND_LABEL_CODE_PATH)
    const backend = backendPrefixes()
    expect(backend).toEqual(['/i/', '/s/'].sort())
    expect(backend).toContain(WASH_CODE_PATH)
    expect(backend).toContain(INBOUND_LABEL_CODE_PATH)
    // 洗水码前缀在端侧**只有一处**写着（复制第二份 = 两套码空间迟早被串起来）
    expect(washPrefixLiteralFiles()).toEqual(['src/utils/inbound/codeSpace.ts'])
  })

  it('G2 🔴 谁可以查入库详情：台账未登记即红、条目必须活着、受门禁的**调用点所在函数**必须引用码空间判定', () => {
    const files = srcFiles().map((rel) => ({ file: rel, code: readSrc(rel) }))
    // 反空跑：射程真的扫到了源码
    expect(files.length).toBeGreaterThanOrEqual(50)
    expect(detailCallSiteProblems(files, LABEL_DETAIL_CALLERS)).toEqual([])
    // 反空跑：确实存在**受门禁**的调用点（补打链路），否则这条判据只覆盖了服务层
    expect(LABEL_DETAIL_CALLERS.some((item) => item.gatedByCodeSpace)).toBe(true)

    // 🔴 注入 A（复核方给的 `page-direct-lookup`）：在**已登记页面**里、另一个函数里
    //    新加一处**不经 loadReprintDetail** 的 getInboundLabel(…) ⇒ 必须红
    const bypassed = files.map((source) =>
      source.file === 'src/pages/worker/reprint/index.tsx'
        ? {
            ...source,
            code:
              `${source.code}\nexport async function quickPeek(shortCode: string) {\n` +
              `  return getInboundLabel(shortCode)\n}\n`,
          }
        : source,
    )
    const bypassProblems = detailCallSiteProblems(bypassed, LABEL_DETAIL_CALLERS).join('\n')
    expect(bypassProblems).toContain('src/pages/worker/reprint/index.tsx::quickPeek')
    expect(bypassProblems).toContain('没登记')

    // 🔴 注入 B：在**同一个已登记函数**里再加一处（次数变了）⇒ 也必须红
    const duplicated = files.map((source) =>
      source.file === 'src/pages/worker/reprint/index.tsx'
        ? { ...source, code: source.code.replace('const refreshed = await getInboundLabel(shortCode)', 'const refreshed = await getInboundLabel(shortCode)\n      const extra = await getInboundLabel(shortCode)') }
        : source,
    )
    expect(detailCallSiteProblems(duplicated, LABEL_DETAIL_CALLERS).join('\n')).toContain('多一处 / 少一处都要同步台账')

    // 🔴 注入 C：把门禁从那个函数里摘掉（文件里别处仍有门禁 ⇒ 旧的文件级口径照样绿）⇒ 必须红
    const ungated = files.map((source) =>
      source.file === 'src/pages/worker/reprint/index.tsx'
        ? { ...source, code: source.code.replace(/loadReprintDetail\(/g, 'loadDetail(') }
        : source,
    )
    expect(detailCallSiteProblems(ungated, LABEL_DETAIL_CALLERS).join('\n')).toContain('没有引用码空间门禁')
  })

  it('G3 🔴 同族页面必须复用共用件（注入式红证：第二套实现会被点名判红）', () => {
    const pages = labelRenderingPages()
    // 反空跑：射程里确实有**同族**的两个页面（入库页 + 补打页）
    expect(pages.map((page) => page.file).sort()).toEqual([
      'src/pages/worker/inbound/index.tsx',
      'src/pages/worker/reprint/index.tsx',
    ])
    expect(labelPageProblems(pages)).toEqual([])
    // 画布工厂：共用件是唯一定义处（页面自带第二份 ⇒ 分叉）
    expect(canvasFactoryDefinitions()).toEqual(['src/utils/inbound/labelPageKit.ts'])

    // 注入 A：某页面不再引用唯一送打印入口 ⇒ 同一判定函数必须点名判红
    const stripped = pages.map((page) => ({ ...page, code: page.code.replace(/printInboundLabel/g, 'doPrint') }))
    expect(labelPageProblems(stripped).join('\n')).toContain('未引用唯一送打印入口')
    // 注入 B：页面自带第二份二维码版面
    const withQr = pages.map((page) => ({ ...page, code: `${page.code}\nconst qr = qrcode(0, 'M')\n` }))
    expect(labelPageProblems(withQr).join('\n')).toContain('第二份二维码版面')
    // 注入 C：页面直连传输层
    const withRaw = pages.map((page) => ({ ...page, code: `${page.code}\nawait api.printImageData({})\n` }))
    expect(labelPageProblems(withRaw).join('\n')).toContain('直连传输层')
    // 注入 D：页面自带像素 / 纸型字面量（改纸型不会跟着改 ⇒ 打废纸）
    const withPixels = pages.map((page) => ({
      ...page,
      code: `${page.code}\nconst w = ${inboundLabelGeometry().effectiveWidthPx}\nconst paper = '50mm 30mm'\n`,
    }))
    const pixelProblems = labelPageProblems(withPixels).join('\n')
    expect(pixelProblems).toContain('像素口径字面量')
    expect(pixelProblems).toContain('纸型字面量')
    // 注入 E：页面自己数打印次数（`printCount + 1`）⇒ 纸上第 4 次、服务端记第 3 次，两份数都不报错
    const withLocalCount = pages.map((page) => ({
      ...page,
      code: `${page.code}\nconst shown = ${'label'}.printCount + 1\n`,
    }))
    expect(labelPageProblems(withLocalCount).join('\n')).toContain('前端不自行计数')
  })
})
