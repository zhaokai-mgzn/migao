// case_ids: PR-120
/**
 * 类级元守卫：「拍照 / 上传识别」入口的**落点**（issue #5918，铁律 8 的类级固化）。
 *
 * 病（不是一处）：**同一个组件**在两页被放成两种版式 —— 商品页悬在表单卡片**外面**
 * （页面底色上的独立容器），建单页在区块标题行**里面**。只把商品页挪一次不解决复发：
 * 下一个人照样能把它塞进任何一个裸容器里，而且**没有任何东西会红**。
 *
 * 本判据把「新增一个渲染点」变成**必须显式登记**的动作（未登记即红），并对每条登记项机械核三件事：
 *   ① 声明的**容器文件**存在、容器**锚**在该文件里逐字出现（= 容器真的在那儿）；
 *   ② 声明的**运行期证据**（哪个测试文件、哪条用例断言「按钮在卡片里」）存在且标题逐字对得上
 *      —— 台账不许空口声称「有人守着」；
 *   ③ 台账条目与源码里的渲染点**双向相等**（少了 = 死条目；多了 = 未登记）。
 *
 * 扫描规则（机械、窄口径）：`src/**` 里出现 JSX 用法 `<ImageRecognizeButton` 的文件。
 * `import` 行、`RecognizedBadge` 徽标不在面内（它们不是入口的落点）。
 *
 * 边界（如实登记，§19.1）：本判据**不跑**被引用的那份运行期证据（否则等于把全量套件再跑一遍），
 * 也不做 JSX 嵌套的静态解析 —— 它保证的是「落点已登记 + 容器锚与运行期证据都真实存在」，
 * 「按钮此刻真的在卡片里」由台账指名的用例承担（商品页 = 新建的
 * `products-new-recognize-entry.test.tsx` 判据 1；建单页 = 既有的 `orders-new-layout.test.tsx` 判据 2）。
 */
import { describe, it, expect } from 'vitest'
import { existsSync, readFileSync, readdirSync, statSync } from 'fs'
import { join, relative } from 'path'

/** 包根（vitest 的 cwd = `frontend/admin-web`） */
const ROOT = process.cwd()
/** 仓库根 —— 台账里的路径一律写成**仓库相对路径**，便于人复核（§16.7 引用纪律） */
const REPO = join(ROOT, '..', '..')
const SRC = join(ROOT, 'src')
const SKIP_DIRS = new Set(['node_modules', '.next', 'dist', 'coverage'])

/** 渲染点判定：JSX 用法的 `<ImageRecognizeButton`（非全局正则 ⇒ `test` 无状态、可重复调用） */
export const SITE_RE = /<ImageRecognizeButton[\s/>]/

interface Entry {
  /** 渲染点所在文件（仓库相对） */
  file: string
  /** 承载「卡片标题行」的文件（仓库相对） */
  containerFile: string
  /** 该文件里逐字可查的容器锚 */
  containerMarker: string
  /** 运行期证据：断言「按钮真在卡片里」的那条用例 */
  runtimeProof: { file: string; test: string }
}

const LEDGER: Entry[] = [
  {
    // 商品页：按钮由 `ProductForm` 的标题行动作槽承载 ⇒ 容器在**另一个文件**里
    file: 'frontend/admin-web/src/app/(dashboard)/products/new/page.tsx',
    containerFile: 'frontend/admin-web/src/components/products/ProductForm.tsx',
    containerMarker: 'data-testid="pf-title-card"',
    runtimeProof: {
      file: 'frontend/admin-web/tests/unit/pages/products-new-recognize-entry.test.tsx',
      test: '判据 1：识别入口在「新增商品」标题卡片内',
    },
  },
  {
    // 建单页：入口挂在「商品信息」卡（`<Card>`）的标题行右侧，容器就在本文件里
    file: 'frontend/admin-web/src/app/(dashboard)/orders/new/page.tsx',
    containerFile: 'frontend/admin-web/src/app/(dashboard)/orders/new/page.tsx',
    containerMarker: '<Card>',
    runtimeProof: {
      file: 'frontend/admin-web/tests/unit/pages/orders-new-layout.test.tsx',
      test: '识别入口挂在**商品信息**卡标题行',
    },
  },
]

/**
 * 豁免台账（**只许缩短**，当前为空）：登记「命中规则但确有必要」的渲染点。
 * 空台账也要有腐坏检查 —— 登记的条目必须仍然命中规则，否则就是死条目。
 */
const EXEMPT: string[] = []

function sourceFiles(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    if (SKIP_DIRS.has(entry)) continue
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) sourceFiles(full, out)
    else if (/\.(tsx|ts)$/.test(entry)) out.push(full)
  }
  return out
}

/** 源码里的渲染点（仓库相对路径，posix 分隔符） */
function renderSites(): string[] {
  return sourceFiles(SRC)
    .filter((f) => SITE_RE.test(readFileSync(f, 'utf-8')))
    .map((f) => relative(REPO, f).split('\\').join('/'))
}

// ── 纯判据（可在内存里自证判别力，见「判别力自证」那一节）────────────────────
/** 未登记的渲染点 */
const unregisteredSites = (sites: string[], ledger: Entry[], exempt: string[]): string[] =>
  sites.filter((f) => !ledger.some((e) => e.file === f) && !exempt.includes(f))
/** 台账里的死条目（声称的渲染点已不存在） */
const deadEntries = (sites: string[], ledger: Entry[]): string[] =>
  ledger.filter((e) => !sites.includes(e.file)).map((e) => e.file)
/** 容器锚 / 运行期证据是否**逐字**可查 */
const missingText = (text: string, needle: string): boolean => !text.includes(needle)

describe('识别入口落点元守卫（issue #5918）', () => {
  const sites = renderSites()

  it('普查面自证：扫得到渲染点，且两处已知落点都在册（改名 / 改写法 ⇒ 本判据先红，而不是空跑）', () => {
    expect(sites.length, '扫不到任何渲染点 ⇒ 判据在扫空气').toBeGreaterThanOrEqual(2)
    for (const known of LEDGER.map((e) => e.file)) {
      expect(sites, `${known} 应命中渲染点规则（JSX 写法变了 ⇒ 请同步本判据的 SITE_RE）`).toContain(known)
    }
  })

  it('未登记即红：每个渲染点都必须登记（新增落点必须显式说明它落在哪个卡片里）', () => {
    const offenders = unregisteredSites(sites, LEDGER, EXEMPT)
    expect(
      offenders,
      `这些文件渲染了「拍照 / 上传识别」却未登记落点：${offenders.join('、')}。`
        + '出口：在 LEDGER 里登记 {file, containerFile, containerMarker, runtimeProof}'
        + '（容器必须是**卡片标题行**，并为它补一条断言「按钮在卡片内」的用例）。',
    ).toEqual([])
  })

  it('台账不得腐坏：登记的渲染点必须仍然渲染（搬走 / 删除 ⇒ 删条目，不是留着）', () => {
    expect(deadEntries(sites, LEDGER), '台账里有死条目').toEqual([])
  })

  it('容器锚必须真实：声明的容器文件存在，且锚在该文件里逐字出现', () => {
    for (const e of LEDGER) {
      const p = join(REPO, e.containerFile)
      expect(existsSync(p), `${e.file} 声明了不存在的容器文件 ${e.containerFile}`).toBe(true)
      const text = readFileSync(p, 'utf-8')
      expect(
        missingText(text, e.containerMarker),
        `${e.containerFile} 里找不到容器锚 ${e.containerMarker} ⇒ 容器被改名 / 搬走（改前形态 = 悬在卡片外）`,
      ).toBe(false)
    }
  })

  it('运行期证据必须真实：声明的测试文件存在，且用例标题逐字出现', () => {
    for (const e of LEDGER) {
      const p = join(REPO, e.runtimeProof.file)
      expect(
        existsSync(p),
        `${e.file} 声明的运行期证据文件不存在：${e.runtimeProof.file}`,
      ).toBe(true)
      const text = readFileSync(p, 'utf-8')
      expect(
        missingText(text, e.runtimeProof.test),
        `${e.runtimeProof.file} 里找不到用例「${e.runtimeProof.test}」⇒ 台账在给一条不存在的证据盖章`,
      ).toBe(false)
    }
  })

  it('判别力自证：四种坏形态（未登记 / 死条目 / 容器锚缺失 / 证据缺失）各自判红', () => {
    // ① 未登记：两个渲染点、台账只登记一个 ⇒ 报出另一个
    expect(unregisteredSites([LEDGER[0].file, 'b.tsx'], [LEDGER[0]], [])).toEqual(['b.tsx'])
    // ①b 豁免命中 ⇒ 不报（豁免台账是出口，不是漏报）
    expect(unregisteredSites([LEDGER[0].file], [], [LEDGER[0].file])).toEqual([])
    // ② 死条目：台账声称的渲染点已不在源码里 ⇒ 报出该条
    expect(deadEntries(['b.tsx'], [LEDGER[0]])).toEqual([LEDGER[0].file])
    // ③ 容器锚缺失 / 在 ⇒ 一红一绿
    expect(missingText('<div className="pt-4" />', 'data-testid="pf-title-card"')).toBe(true)
    expect(missingText('<div data-testid="pf-title-card" />', 'data-testid="pf-title-card"')).toBe(false)
    // ④ 运行期证据缺失 / 在 ⇒ 一红一绿
    expect(missingText("it('别的用例')", '判据 1：识别入口在「新增商品」标题卡片内')).toBe(true)
    expect(missingText('判据 1：识别入口在「新增商品」标题卡片内、与「重置」同排', '判据 1：识别入口在「新增商品」标题卡片内')).toBe(false)
    // ⑤ 扫描规则本身不是空正则（含 `\b` 语义的判别：`<ImageRecognizeButtonX` 不算渲染点）
    expect(SITE_RE.test('<ImageRecognizeButton\n')).toBe(true)
    expect(SITE_RE.test('import ImageRecognizeButton from x')).toBe(false)
  })
})
