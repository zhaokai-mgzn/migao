// case_ids: BM-016
/**
 * 拍照入库页的**类级元守卫**（issue #5052 P3；AGENTS.md 铁律 8「类级固化」/ `migao-dev-flow` §23）
 *
 * 本单最值得固化的两类缺陷，一类在这里：
 *
 * ### ① 「**声明了能力缺口却没接线**」（#5654 的 P9 形态）
 *
 * 台账里写一句「iOS 打不了蓝牙」很便宜，而**没有任何东西**保证它出现在用户眼前；
 * 于是用户看到的仍是「点了没反应」。判据把三件事绑在一起：
 * **登记**（台账有这条）→ **接线**（射程内文件真的引用它）→ **可见**（页面在**动手前**渲染探测结论）。
 *
 * ### ② 同族：「**新加一处平台调用而没人知道它在这个平台不可用**」
 *
 * 射程内实际用到的 `Taro.*` 必须**逐值等于**声明集（双向）⇒ 新增一处而未同步声明就被拦下。
 *
 * | # | 判据 | 红证（怎么让它单独变红） |
 * |---|---|---|
 * | G0 | 路由登记 == 单一真值，页面文件存在（没登记 = 死链） | 从 `app.config.ts` 删掉路由 ⇒ 红 |
 * | G1 | 声明集 == 射程内实测 `Taro.*` 集（双向） | 页面加一处 `Taro.showToast` ⇒ 红 |
 * | G2 | 命中 #5650 清单的 API 必须有缺口文案 + **被射程内文件引用** | 只登记不接线 ⇒ 红 |
 * | G3 | 台账只许缩短且条目必须活着 | 留着一条射程里已不存在的 ⇒ 红 |
 * | G4 | 文案非占位（≥10 字） | 写 "TODO" ⇒ 红 |
 * | G5 | 打印能力探测结论**在动手前**就上屏（含 iOS / 非 HTTPS / 无蓝牙各自的文案） | 只在失败后显示 ⇒ 红 |
 * | G6 | h5 下不调 `Taro.login`（照 #5650 判据） | 页面加 `Taro.login` ⇒ G1+G6 红 |
 */
import fs from 'fs'
import path from 'path'
import {
  INBOUND_PAGE_FILE,
  INBOUND_PAGE_PLATFORM_GAP_HINTS,
  INBOUND_PAGE_ROUTE,
  INBOUND_PAGE_SCOPE_FILES,
  INBOUND_PAGE_TARO_APIS,
  INBOUND_PRINT_GAP_WIRING,
  REPRINT_PAGE_FILE,
  REPRINT_PAGE_ROUTE,
  WORKER_LOGIN_ROUTE,
} from '../src/utils/inbound/gaps'
import { H5_API_OUTLET_LEDGER } from '../src/utils/platform'
import { BMINI_ROOT, jsSdkOnlyApis, stripComments, taroApisInFile, unsupportedApis } from './helpers/h5PlatformLists'

const REPO_ROOT = path.join(BMINI_ROOT, '..', '..')
const APP_CONFIG = 'src/app.config.ts'

function read(relFromBmini: string): string {
  const abs = path.join(BMINI_ROOT, relFromBmini)
  if (!fs.existsSync(abs)) throw new Error(`找不到受管文件：${relFromBmini}（路径漂移不得静默跳过 ⇒ 红）`)
  return fs.readFileSync(abs, 'utf8')
}

/** 射程内实测用到的 Taro API（去重排序；抽取实现与 #5650 守卫**同一份** helper） */
function measuredTaroApis(): string[] {
  const apis = new Set<string>()
  for (const rel of INBOUND_PAGE_SCOPE_FILES) {
    for (const api of taroApisInFile(path.join(BMINI_ROOT, rel))) apis.add(api)
  }
  return Array.from(apis).sort()
}

/**
 * 「声明集 == 实测集」的判定（真判据与注入式红证**共用同一份**，见 `migao-dev-flow` §23.5）。
 * 多一个（未声明就用）与少一个（声明了没用）**都要点名**。
 */
function declarationDriftProblems(measured: string[], declared: string[]): string[] {
  const problems: string[] = []
  const extra = measured.filter((api) => !declared.includes(api))
  const missing = declared.filter((api) => !measured.includes(api))
  if (extra.length > 0) problems.push(`射程内**未声明就用**：${extra.join(', ')}（新增平台调用必须先声明缺口）`)
  if (missing.length > 0) problems.push(`声明了却**没人用**：${missing.join(', ')}（声明集只许缩短）`)
  return problems
}

describe('拍照入库页：平台能力面（声明 == 实测 · 缺口必须接线）', () => {
  const unsupported = unsupportedApis()
  const jsSdkOnly = jsSdkOnlyApis()
  const measured = measuredTaroApis()

  it('G0 路由登记在 app.config.ts（没登记 = 死链），页面与页面配置都在', () => {
    expect(read(APP_CONFIG)).toContain(`'${INBOUND_PAGE_ROUTE.replace(/^\//, '')}'`)
    // 同族的**补打页**（issue #5640）也在，否则「同族共用一份台账」只覆盖了一半
    expect(read(APP_CONFIG)).toContain(`'${REPRINT_PAGE_ROUTE.replace(/^\//, '')}'`)
    // 工人登录页也在（未登录时跳它 —— 跳一个没登记的路由 = 点了没反应）
    expect(read(APP_CONFIG)).toContain(`'${WORKER_LOGIN_ROUTE.replace(/^\//, '')}'`)
    for (const rel of INBOUND_PAGE_SCOPE_FILES) {
      expect(fs.existsSync(path.join(BMINI_ROOT, rel))).toBe(true)
    }
    expect(fs.existsSync(path.join(BMINI_ROOT, 'src/pages/worker/inbound/index.config.ts'))).toBe(true)
    expect(fs.existsSync(path.join(BMINI_ROOT, 'src/pages/worker/reprint/index.config.ts'))).toBe(true)
    expect(INBOUND_PAGE_FILE).toBe('src/pages/worker/inbound/index.tsx')
    expect(REPRINT_PAGE_FILE).toBe('src/pages/worker/reprint/index.tsx')
  })

  it('G1 声明集 == 射程内实测集（多一个 / 少一个都红）', () => {
    const declared = [...INBOUND_PAGE_TARO_APIS].sort()
    expect(declarationDriftProblems(measured, declared)).toEqual([])
    // 反空跑：射程真的扫到了用法（否则两边都是空集，判据会空跑通过）
    expect(measured.length).toBeGreaterThanOrEqual(4)
  })

  it('G1 🔴 红证：往页面加一处未声明的 Taro 调用 ⇒ 实测集与声明集不再相等', () => {
    const declared = [...INBOUND_PAGE_TARO_APIS].sort()
    // ① 先跑**真**实测（读射程内的文件）⇒ 同一判定判绿。
    //    这一半让本 case 真的走被测对象：把 measuredTaroApis 换成"永远抛错"的实现 ⇒ 本 case 必红。
    expect(declarationDriftProblems(measuredTaroApis(), declared)).toEqual([])
    // ② 坏形态（页面加一处 Taro.showToast）作为**同一判定**的入参 ⇒ 必须点名
    const injected = Array.from(new Set([...measured, 'showToast'])).sort()
    expect(declarationDriftProblems(injected, declared).join('\n')).toContain('showToast')
  })

  it('G2 命中 #5650 清单的 API 必须**两处**登记，且文案被射程内文件引用', () => {
    const hazardous = measured.filter((api) => unsupported.has(api) || jsSdkOnly.has(api))
    // 反空跑：本页确实命中了一条（createOffscreenCanvas），否则这条判据会空转
    expect(hazardous).toContain('createOffscreenCanvas')
    for (const api of hazardous) {
      expect(api in INBOUND_PAGE_PLATFORM_GAP_HINTS).toBe(true)
      expect(api in H5_API_OUTLET_LEDGER).toBe(true)
      const hint = INBOUND_PAGE_PLATFORM_GAP_HINTS[api]
      // 「接线」的机械形态：射程内至少一个文件真的引用了这条文案（不是只写在台账里）
      const wired = INBOUND_PAGE_SCOPE_FILES.some((rel) => read(rel).includes(hint.slice(0, 24)))
      expect({ api, wired }).toEqual({ api, wired: true })
    }
  })

  it('G3 台账只许缩短且条目必须活着（射程里已不存在的 API ⇒ 红）', () => {
    const live = new Set(measured)
    const stale = Object.keys(INBOUND_PAGE_PLATFORM_GAP_HINTS).filter((api) => !live.has(api))
    expect(stale).toEqual([])
  })

  it('G4 缺口文案非占位（≥10 字，说清「用户看到什么」）', () => {
    const entries = Object.entries(INBOUND_PAGE_PLATFORM_GAP_HINTS)
    expect(entries.length).toBeGreaterThan(0)
    for (const [api, hint] of entries) {
      expect(`${api}:${hint}`.length).toBeGreaterThan(12)
      expect(hint.trim().length).toBeGreaterThanOrEqual(10)
    }
  })

  it('G5 打印能力探测结论**在动手前**就上屏（不是打完才失败）', () => {
    const page = read(INBOUND_PAGE_FILE)
    expect(page).toContain('probePrintCapability')
    expect(page).toContain('inbound-print-capability')
    expect(page).toContain('capability.hint')
    // 探测结论出现在**任何操作之前**的位置：它在 step 分支之外（页头顶部）
    const capabilityIndex = page.indexOf("data-testid='inbound-print-capability'")
    const firstStepIndex = page.indexOf("step === 'photo'")
    expect(capabilityIndex).toBeGreaterThan(-1)
    expect(capabilityIndex).toBeLessThan(firstStepIndex)
  })

  it('G5 每一种打印失败原因都被接线（键集与文案表一致，且有文件引用它）', () => {
    const wired = INBOUND_PRINT_GAP_WIRING.map((item) => item.reason).sort()
    expect(wired.length).toBeGreaterThanOrEqual(8)
    for (const item of INBOUND_PRINT_GAP_WIRING) {
      expect(read(item.wiredBy)).toContain(item.reason)
    }
  })

  it('G6 h5 下不调 Taro.login（工人身份走工号 + PIN，不走微信换码）', () => {
    expect(measured).not.toContain('login')
    const page = read(INBOUND_PAGE_FILE)
    expect(page).not.toMatch(/Taro\.login/)
    expect(page).not.toMatch(/miniAppLogin/)
  })

  it('G6 页面按工人 session 分流：有 ⇒ 走工人路径；没有 ⇒ 明说去登录（不静默）', () => {
    const page = read(INBOUND_PAGE_FILE)
    expect(page).toContain('hasWorkerSession')
    expect(page).toContain('INBOUND_WORKER_LOGIN_REQUIRED')
    // 不碰商家面：入库这条链只有 `/api/worker/inbound/**`
    // ⚠️ 按**去注释后的代码**判（页面文件头会解释「/api/admin/** 对工人是 401」——
    //    按原文判会把解释性注释判成违规，那是假红，见 migao-dev-flow §17.3 的「引用即实例」）
    const code = stripComments(page)
    expect(code).not.toContain('/api/admin/')
  })
})
