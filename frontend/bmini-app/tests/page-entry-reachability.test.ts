// case_ids: BM-025
/**
 * **入口可达性元守卫**（issue #5052 实现 PR；验收协议 v1.11「交付物可达性」三问之②）
 *
 * ## 治的形态：「交付物做完了，却没有任何入口能走到它」
 *
 * 本仓的反面教材就在本单要接的那两条链路上：`src/utils/inbound/gaps.ts` 的
 * `INBOUND_PAGE_ROUTE` / `REPRINT_PAGE_ROUTE` **被声明了**、还被 `tests/inbound-page-platform-gaps.test.ts`
 * 的 G0 **比对过 `app.config.ts`** —— 却**没有任何一处跳转用它们**。⇒ 两页「在册、可编译、有单测」，
 * 而工人**一步也走不到**。**「声明存在」不等于「可达」**：一个只会断言"常量写着这个路由"的判据
 * 对这件事**恒绿**（空断言），所以本文件的判据是「**有一处真的在跳转**」。
 *
 * ## 判据表
 *
 * | # | 判据 | 红证（怎么让它单独变红） |
 * |---|---|---|
 * | L0 | 台账条目**活着**：每条 `route` 都在 `app.config.ts` 的 `pages` 里（只许缩短，条目必须活着） | 从 app.config 删掉该页 ⇒ 红 |
 * | L1 | 落地页参数名与后端**逐值同名**（`InboundLabelService.LANDING_CODE_PARAM`） | 后端改名而端侧没跟 ⇒ 红 |
 * | L2 | 🔴 **未登记即红**：每个**非 tabBar** 页面都必须在入口台账里具名（tabBar 页面机械豁免，且不许登记） | 加一个页面不登记 ⇒ 红 |
 * | L3 | 🔴 **登记了没人指向也红**：每条登记都必须能在 `from` 里找到**真导航形态** + 目标记号 | 把入口换回"只声明"（`from` 指向只写着常量的文件）⇒ 红 |
 * | L3b | 🔴 **形态在但没人调用也红**（调用点级）：导航语句**所在的函数**必须真的会被执行（组件 / hook / 文件内被引用过的具名函数） | 把 `Taro.redirectTo` 挪进一个**没人调用**的导出函数 ⇒ 红 |
 * | L3c | 🔴 **HTML 注释里的锚点不算入口**：判据先去掉 `<!-- … -->` 再判形态 | 把 `<a href>` 包成 `<!-- … -->` ⇒ 红 |
 * | L4 | `via` 不是路由字面量时，「记号 ⇒ 路由」的绑定必须被 `viaBinding` 钉住（那里出现路由字面量 / 路由常量名） | 把 viaBinding 指向无关文件 ⇒ 红 |
 * | L5 | 🔴 **跨应用入口已收敛**（2026-10-10，issue #6635）：`/w/` 报工页**不再**承载入库两页的 `<a>`（反向钉住：出现即红），可达性由**工人工作台**承担（`from` 逐值核） | 把 `/w/` 的那两条入口加回去 / 把工作台的入口删掉 ⇒ 红 |
 * | L6 | 平台缺口台账（Taro API 之外那一类）：缺口必须**由真的调用它的文件接线**（`wiredBy` 的**代码**里出现 `wiredToken`） | 只登记不接线 ⇒ 红 |
 *
 * ## 边界（明确的，不要把本守卫读成覆盖面更大的东西）
 *
 * ① 它**只**保证「源码里有一处导航形态指向这个页面」。**线上/真机是否走得通**
 *    （发布腿跑没跑、nginx 面在不在、工人 session 登没登）**不在**本判据里 ——
 *    那是 `deploy/scripts/*-verify-served.sh`（发布后身份断言）与各页面自己的身份分流判据的事；
 * ② `via` 是**动态记号**时（`surface.route`），本守卫只能核「跳转语句里带着它」+
 *    「`viaBinding` 那个文件里绑着这条路由」；「运行期它到底解析成哪个路由」由
 *    管理面自己的守卫（`tests/admin-surfaces-guard.test.ts`）负责 —— 两条判据合起来才闭合；
 * ③ tabBar 四页**机械豁免**（依据 = `app.config.ts` 的 `tabBar.list`，不是手写白名单）；
 * ④ L3b 的"会被执行"是**近似判定**（`tests/helpers/inboundCallSites.ts` 的 `reachableFromSpan`）：
 *    跨文件调用看不见 ⇒ 台账可用 `reachableBy` **显式登记**触发机制（登记优先于猜，
 *    见 `src/utils/pageEntries.ts` 的字段注释）。它治的是「**定义但从未被调用**」这一形态，
 *    **不是**"运行期真的到达了"（那仍是真机档 U6）；两种变体本判据都能独立抓住：
 *    `render.mjs` 侧（`workerEntriesBar(state)` 定义但调用被摘掉）与 `app.tsx` 侧（挪进没人调用的函数）；
 * ⑤ 本守卫**不改任何既有门禁的通过条件、不新增豁免**。
 */
import fs from 'fs'
import path from 'path'
import {
  INBOUND_PAGE_ROUTE,
  REPRINT_PAGE_ROUTE,
  WORKER_LOGIN_ROUTE,
  WORKER_SURFACE_PLATFORM_GAPS,
} from '../src/utils/inbound/gaps'
import { LANDING_CODE_PARAM } from '../src/utils/inbound/deepLink'
import { PAGE_ENTRY_LEDGER, type EntryNav, type PageEntry } from '../src/utils/pageEntries'
import { BMINI_ROOT, stripComments, stripHtmlComments } from './helpers/h5PlatformLists'
import { callSites, reachableFromSpan } from './helpers/inboundCallSites'

const REPO_ROOT = path.join(BMINI_ROOT, '..', '..')
const APP_CONFIG = 'src/app.config.ts'
/** 工人工作台 —— 入库两页现在**唯一**的入口承载面（2026-10-10 起，issue #6635）。 */
const WORKER_HOME = 'src/pages/worker/home/index.tsx'
const BACKEND_LANDING_PARAM =
  'backend/admin-api/src/main/java/com/migao/admin/service/InboundLabelService.java'

/** bmini 内文件写 bmini 相对路径，跨应用文件写仓库相对路径 —— 两处都找（找不到 ⇒ 抛，不静默跳过） */
type Reader = (rel: string) => string

const readReal: Reader = (rel) => {
  for (const base of [REPO_ROOT, BMINI_ROOT]) {
    const abs = path.join(base, rel)
    if (fs.existsSync(abs) && fs.statSync(abs).isFile()) return fs.readFileSync(abs, 'utf8')
  }
  throw new Error(`找不到受管文件：${rel}（路径漂移不得静默跳过 ⇒ 红）`)
}

/**
 * **变异生效自证**（issue #5778 会话）：红证夹具靠字符串/正则替换构造变异体，
 * 锚点一旦失配，`replace` 会**静默返回原文** ⇒ 该红证退化成**空断言**，
 * 且失败时抛的是**下游无关断言**（实测踩过：`render.mjs` 版本漂移时，报错是
 * `Expected substring: "function workerEntriesBar(state)"` —— 读日志的人会以为「函数定义丢了」，
 * 实际是**读到的对象不对**）。
 *
 * ⇒ 每个变异体构造后，用它**就地自证**「我想要的形态真的出现了」，否则当场红并指名锚点。
 */
function expectMutationApplied(mutated: string, tokens: string[], label: string): void {
  for (const token of tokens) {
    if (!mutated.includes(token)) {
      throw new Error(
        `[${label}] 变异未生效：变异体里找不到「${token}」⇒ 红证会退化成空断言。` +
          `锚点与被读文件版本不匹配（先核对该文件在 origin/main 上的形态），不要靠下游断言反推。`,
      )
    }
  }
}

function normalise(route: string): string {
  return route.startsWith('/') ? route : `/${route}`
}

function appConfigPages(read: Reader): string[] {
  // ⚠️ 先**去注释**再解析：`app.config.ts` 的注释里出现过 `ADMIN_SURFACES[].route` ——
  // 按原文解析会在那个 `]` 上截断（"判据把原文当代码读"那一族，见 `migao-dev-flow` §17.3）
  const block = /pages:\s*\[([\s\S]*?)\]/.exec(stripComments(read(APP_CONFIG)))
  if (!block) throw new Error(`${APP_CONFIG} 里读不出 pages 数组 ⇒ 判红而不是判绿（解析口径漂移了）`)
  const pages = Array.from(block[1].matchAll(/'([^']+)'/g)).map((m) => normalise(m[1]))
  if (pages.length < 8) throw new Error(`${APP_CONFIG} 的 pages 只解析出 ${pages.length} 条 ⇒ 解析口径已漂移`)
  return pages
}

function tabBarPages(read: Reader): string[] {
  return Array.from(stripComments(read(APP_CONFIG)).matchAll(/pagePath:\s*'([^']+)'/g)).map((m) =>
    normalise(m[1]),
  )
}

/** 路由常量别名（`via` 写成常量名时，"它解析成哪条路由"由这些导出值背书） */
const ROUTE_ALIASES: Record<string, string> = {
  [INBOUND_PAGE_ROUTE]: 'INBOUND_PAGE_ROUTE',
  [REPRINT_PAGE_ROUTE]: 'REPRINT_PAGE_ROUTE',
  [WORKER_LOGIN_ROUTE]: 'WORKER_LOGIN_ROUTE',
}

function escapeRe(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

/**
 * 导航形态的正则 —— **格式容忍**（不当"原文逐字"读：换行 / 重排 / 加空格都不该判红，
 * 见 `migao-dev-flow` §23 的「判据把原文当代码读」那一族）。
 */
function navPattern(nav: EntryNav, via: string): RegExp {
  const q = escapeRe(via)
  if (nav === 'href') return new RegExp(`href=["'][^"']*${q}`)
  return new RegExp(`\\bTaro\\.${nav}\\(\\s*\\{[\\s\\S]{0,200}?${q}`)
}

export interface EntryGuardInput {
  pages: string[]
  tabBar: string[]
  entries: PageEntry[]
  read: Reader
}

/** 核心判定（真判据与注入式红证**共用同一份** —— 红证必须走真判据，见 `migao-dev-flow` §23.5） */
export function entryProblems(input: EntryGuardInput): string[] {
  const problems: string[] = []
  const registered = new Set(input.entries.map((entry) => entry.route))

  // L2 未登记即红（tabBar 页机械豁免，且不许躺在台账里当"假入口"）
  for (const page of input.pages) {
    if (input.tabBar.includes(page)) {
      if (registered.has(page)) {
        problems.push(
          `${page}: tabBar 页面不该在入口台账里（可达性由系统 tabBar 提供；登记它 = 台账里躺着一条假入口）`,
        )
      }
      continue
    }
    if (!registered.has(page)) {
      problems.push(
        `${page}: 面向用户的页面**没有任何入口登记**（去 src/utils/pageEntries.ts 的 PAGE_ENTRY_LEDGER 写清「谁发射」，或给它补一个真入口）`,
      )
    }
  }

  for (const entry of input.entries) {
    // L0 条目必须活着
    if (!input.pages.includes(entry.route)) {
      problems.push(`${entry.route}: 台账条目已死（app.config.ts 的 pages 里没有这个页面）—— 台账只许缩短`)
    }
    if (String(entry.audience ?? '').trim().length < 8) {
      problems.push(`${entry.route}: 没写清「从哪个身份出发 / 登录态怎么衔接」`)
    }
    // L3 真导航形态 + 目标记号（"只声明"在这里红）
    // 🔴 先去掉 **HTML 注释**再判（D2：锚点被包进 `<!-- … -->` 时，"字符串还在"依旧成立，
    //    而工人看不到 ⇒ 按原文判 = 守卫与事实相反）
    const content = stripHtmlComments(stripComments(input.read(entry.from)))
    const pattern = navPattern(entry.nav, entry.via)
    if (!pattern.test(content)) {
      problems.push(
        `${entry.route}: ${entry.from} 里找不到「${entry.nav} + ${entry.via}」的真跳转 —— **声明存在 ≠ 可达**`,
      )
    } else {
      // L3b 形态在，但它**所在的那个函数会不会被执行**？（D3：把调用挪进没人调用的函数 ⇒ 字面量还在）
      const site = callSites(content, new RegExp(pattern.source, 'g'), { skipDefinitions: true })[0]
      if (site && !reachableFromSpan(content, site) && !entry.reachableBy) {
        problems.push(
          `${entry.route}: ${entry.from} 里的「${entry.nav} + ${entry.via}」落在函数 ` +
            `${site.fn}() 里，而它在文件内**没有任何调用** —— **写了 ≠ 会被执行**` +
            `（跨文件调用看不见时，请在台账里显式登记 reachableBy）`,
        )
      }
    }
    // L4 记号 ⇒ 路由 的绑定
    if (entry.via !== entry.route) {
      const alias = ROUTE_ALIASES[entry.route]
      const binding = entry.viaBinding ? stripComments(input.read(entry.viaBinding)) : ''
      const bound = binding.includes(entry.route) || (!!alias && binding.includes(alias))
      if (!bound) {
        problems.push(
          `${entry.route}: via「${entry.via}」与路由的绑定没被钉住（viaBinding=${entry.viaBinding ?? '（缺）'} 里既没有路由字面量，也没有路由常量名 ${alias ?? '（无别名）'}）`,
        )
      }
    }
    // L5 跨应用 href：`/b/#<路由>` 去掉前缀后必须逐值等于登记路由
    if (entry.nav === 'href') {
      const hrefs = Array.from(content.matchAll(/href=["']([^"']+)["']/g)).map((m) => m[1])
      const hit = hrefs.filter((href) => href.includes(entry.via))
      if (hit.length === 0) {
        problems.push(`${entry.route}: ${entry.from} 的 ` + `href 里没有含「${entry.via}」的链接`)
      }
      for (const href of hit) {
        const routePart = normalise(href.replace(/^\/b\/#/, '').replace(/^.*#/, ''))
        if (routePart !== entry.route) {
          problems.push(`${entry.route}: ${entry.from} 的 href「${href}」去掉跨应用前缀后 = ${routePart} ≠ ${entry.route}`)
        }
      }
    }
  }
  return problems
}

/** 真实输入（守卫的正跑） */
function realInput(): EntryGuardInput {
  return {
    pages: appConfigPages(readReal),
    tabBar: tabBarPages(readReal),
    entries: PAGE_ENTRY_LEDGER,
    read: readReal,
  }
}

describe('入口可达性：交付物可达性三问之② —— 每个面向用户的页面都必须「有入口」', () => {
  it('L2/L3/L4 正跑：全量页面已登记，且每条登记都能找到真跳转（红证走同一份判定）', () => {
    const input = realInput()
    // 反空跑：真的解析到了页面与登记（否则两边都是空集，判据会空转通过）
    expect(input.pages.length).toBeGreaterThanOrEqual(12)
    expect(input.entries.length).toBeGreaterThanOrEqual(10)
    expect(entryProblems(input)).toEqual([])
    // 🔴 2026-10-10（issue #6635，用户逐字「移除拍照入库和补打入库标签」）后：`/w/` 页头那两条
    // 跨应用 `href` 条目**已撤** ⇒ 台账里**不再有** `href` 条目（`href` 判定分支由 L5 的合成样本自证）。
    expect(input.entries.filter((entry) => entry.nav === 'href').length).toBe(0)
    expect(
      input.entries.filter((entry) => entry.nav === 'redirectTo' || entry.nav === 'navigateTo').length,
    ).toBeGreaterThanOrEqual(6)
  })

  it('L1 落地页参数名与后端逐值同名（`LANDING_CODE_PARAM`）', () => {
    const backend = readReal(BACKEND_LANDING_PARAM)
    const declared = /LANDING_CODE_PARAM\s*=\s*"([^"]+)"/.exec(backend)
    expect(declared?.[1]).toBe(LANDING_CODE_PARAM)
    expect(LANDING_CODE_PARAM).toBe('code')
  })

  it('L5 🔴 `/w/` 不再承载入库两页入口（反向钉住），可达性由工人工作台承担', () => {
    // 🔴 去 JS 注释**且**去 HTML 注释：注释里的锚点不是入口（D2）
    const workerH5 = stripHtmlComments(stripComments(readReal('frontend/worker-h5/src/render.mjs')))
    for (const route of [INBOUND_PAGE_ROUTE, REPRINT_PAGE_ROUTE]) {
      expect({ route, carriedByW: workerH5.includes(`/b/#${route}`) }).toEqual({ route, carriedByW: false })
    }
    // 反向：bmini 侧的路由常量不许被 worker-h5 抄第二份（前缀 `/b/#` 是 Taro h5 的 hash 路由形态）
    expect(workerH5.includes("INBOUND_PAGE_ROUTE")).toBe(false)
    // 正向：可达性没丢 —— 两条登记都能在**工人工作台**找到真导航（`from` 逐值 + nav 形态）
    for (const route of [INBOUND_PAGE_ROUTE, REPRINT_PAGE_ROUTE]) {
      const carriers = PAGE_ENTRY_LEDGER.filter((entry) => entry.route === route && entry.from === WORKER_HOME)
      expect({ route, carriers: carriers.length }).toEqual({ route, carriers: 1 })
      expect(carriers[0].nav).toBe('navigateTo')
    }
    // 形态覆盖自证：`href` 分支的判定函数没退化（台账里已无 href 条目 ⇒ 用合成样本钉住它）
    expect(navPattern('href', '/pages/worker/inbound/index').test('<a href="/b/#/pages/worker/inbound/index">x</a>')).toBe(true)
  })

  it('L6 平台缺口必须有登记，且由真的调用它的文件接线（Taro API 之外那一类）', () => {
    expect(WORKER_SURFACE_PLATFORM_GAPS.length).toBeGreaterThanOrEqual(1)
    for (const gap of WORKER_SURFACE_PLATFORM_GAPS) {
      expect({ key: gap.key, missingOn: gap.missingOn }).toEqual({ key: 'url-query-deeplink', missingOn: 'weapp' })
      expect(gap.fallback.trim().length).toBeGreaterThan(20)
      const wired = stripComments(readReal(gap.wiredBy))
      expect({ key: gap.key, wired: wired.includes(gap.wiredToken) }).toEqual({ key: gap.key, wired: true })
    }
  })

  it('L0 🔴 红证：台账条目对应的页面从 app.config 消失 ⇒ 判红（条目必须活着）', () => {
    const input = realInput()
    const withoutReprint = { ...input, pages: input.pages.filter((page) => page !== REPRINT_PAGE_ROUTE) }
    const problems = entryProblems(withoutReprint)
    expect(problems.join('\n')).toContain('台账条目已死')
    expect(problems.join('\n')).toContain(REPRINT_PAGE_ROUTE)
  })

  it('L2 🔴 红证：新加一个面向用户的页面而不登记入口 ⇒ 判红（未登记即红）', () => {
    const input = realInput()
    const withNewPage = { ...input, pages: [...input.pages, '/pages/worker/brand-new/index'] }
    const problems = entryProblems(withNewPage)
    expect(problems.join('\n')).toContain('/pages/worker/brand-new/index')
    expect(problems.join('\n')).toContain('没有任何入口登记')
  })

  it('L3 🔴 红证：把入口换回「只声明」⇒ 判红（本单要治的正是这个形态）', () => {
    const input = realInput()
    // 形态复刻：`from` 指向**只写着路由常量**的文件（`gaps.ts` 声明了 REPRINT_PAGE_ROUTE，却从不跳转）
    const declarationOnly = input.entries.map((entry) =>
      entry.from === 'src/app.tsx'
        ? { ...entry, from: 'src/utils/inbound/gaps.ts', via: 'REPRINT_PAGE_ROUTE', viaBinding: 'src/utils/inbound/gaps.ts' }
        : entry,
    )
    const problems = entryProblems({ ...input, entries: declarationOnly })
    expect(problems.join('\n')).toContain('声明存在 ≠ 可达')
    // 反证：被替换掉的那份文件里**确实**写着这个路由（所以"只声明"在别的判据下会绿）
    expect(readReal('src/utils/inbound/gaps.ts')).toContain('REPRINT_PAGE_ROUTE')
  })

  it('L3 🔴 红证：把**工人工作台**上的入库入口删掉 ⇒ 判红（声明存在 ≠ 可达）', () => {
    const input = realInput()
    const stripped: Reader = (rel) =>
      rel === WORKER_HOME
        ? readReal(rel).replace(
            /Taro\.navigateTo\(\{ url: (INBOUND_PAGE_ROUTE|REPRINT_PAGE_ROUTE) \}\)/g,
            "Taro.navigateTo({ url: '/pages/nonexistent/index' })",
          )
        : readReal(rel)
    const mutated = stripped(WORKER_HOME)
    // 变异生效自证（锚点失配会静默返回原文 ⇒ 红证退化成空断言）
    expectMutationApplied(mutated, ["Taro.navigateTo({ url: '/pages/nonexistent/index' })"], 'L3 摘掉工人工作台入口')
    expect(mutated.includes('Taro.navigateTo({ url: INBOUND_PAGE_ROUTE })')).toBe(false)
    const problems = entryProblems({ ...input, read: stripped })
    expect(problems.join('\n')).toContain('声明存在 ≠ 可达')
    expect(problems.join('\n')).toContain(INBOUND_PAGE_ROUTE)
  })

  it('L3b 🔴 红证：把 `Taro.redirectTo` 挪进**没人调用**的导出函数 ⇒ 判红（写了 ≠ 会被执行）', () => {
    const input = realInput()
    // 变异形态（复核方给的 `redirect-never-called`）：字面量都在，只是**没有一个调用者**
    const orphaned: Reader = (rel) =>
      rel === 'src/app.tsx'
        ? readReal(rel)
            .replace(/\s*Taro\.redirectTo\(\{ url: reprintLandingUrl\(landing\.raw\) \}\)/, '')
            .concat(
              '\nexport function handleLandingNav(landing: { raw: string }) {\n' +
                '  Taro.redirectTo({ url: reprintLandingUrl(landing.raw) })\n}\n',
            )
        : readReal(rel)
    const mutated = orphaned('src/app.tsx')
    // 「变异真的被读到」的自证：跳转语句**还在**文件里（只是没人调用它）
    expect(mutated).toContain('Taro.redirectTo({ url: reprintLandingUrl(landing.raw) })')
    expect(mutated).toContain('function handleLandingNav')
    expect(entryProblems(input)).toEqual([])
    {
      // ⚠️ 不能用「变异体里还有没有这句」判变异生效 —— 追加的**孤儿函数体内本来就有**同一句调用
      //（第一次就是这么误报的）。正确的自证 = **出现在函数体外的那一处真的没了**：
      // 计数从 1 降到 1（原文 1 处 → 变异后 1 处，从函数体挪进了孤儿函数）。
      const CALLEE = 'Taro.redirectTo({ url: reprintLandingUrl(landing.raw) })'
      const mutatedApp = orphaned('src/app.tsx')
      expectMutationApplied(mutatedApp, ['export function handleLandingNav'], 'L4 挪进孤儿函数')
      const before = (readReal('src/app.tsx').match(new RegExp(CALLEE.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'g')) ?? []).length
      const after = (mutatedApp.match(new RegExp(CALLEE.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'g')) ?? []).length
      if (after !== before) {
        throw new Error(
          `[L4] 变异形态不符预期：调用句出现次数 before=${before} / after=${after}` +
            `（预期相等 —— 只是把**函数体外那一处**挪进了孤儿函数体）`,
        )
      }
      if (!mutatedApp.includes('export function handleLandingNav')) {
        throw new Error('[L4] 变异未生效：孤儿函数没被追加 ⇒ 红证会退化成空断言')
      }
    }
    const problems = entryProblems({ ...input, read: orphaned })
    expect(problems.join('\n')).toContain('写了 ≠ 会被执行')
    expect(problems.join('\n')).toContain(REPRINT_PAGE_ROUTE)
  })

  it('L3b 🔴 红证：工人工作台的 `Taro.navigateTo` 挪进**没人调用**的导出函数 ⇒ 判红（写了 ≠ 会被执行）', () => {
    // ⚠️ 2026-10-10（issue #6635）后这条红证的注入点从 `/w/` 的 `render.mjs` 换成了**工人工作台** ——
    //    台账里已没有 `from: render.mjs` 的条目，再拿它做注入点就与判定对象脱钩（红证会变空断言）。
    const input = realInput()
    const orphaned: Reader = (rel) =>
      rel === WORKER_HOME
        ? readReal(rel)
            .replace(/\s*Taro\.navigateTo\(\{ url: INBOUND_PAGE_ROUTE \}\)/, '')
            .concat(
              '\nexport function handleInboundNav() {\n  Taro.navigateTo({ url: INBOUND_PAGE_ROUTE })\n}\n',
            )
        : readReal(rel)
    const mutated = orphaned(WORKER_HOME)
    expectMutationApplied(mutated, ['export function handleInboundNav'], 'L3b 挪进孤儿函数')
    {
      // 自证：**函数体外那一处**真的没了（计数不变：原文 1 处 → 变异后 1 处，从函数体挪进孤儿函数）
      const CALLEE = 'Taro.navigateTo({ url: INBOUND_PAGE_ROUTE })'
      const count = (text: string) => (text.match(new RegExp(CALLEE.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'g')) ?? []).length
      if (count(mutated) !== count(readReal(WORKER_HOME))) {
        throw new Error(`[L3b] 变异形态不符预期：调用句出现次数 before=${count(readReal(WORKER_HOME))} / after=${count(mutated)}`)
      }
    }
    const problems = entryProblems({ ...input, read: orphaned })
    expect(problems.join('\n')).toContain('写了 ≠ 会被执行')
    expect(problems.join('\n')).toContain(INBOUND_PAGE_ROUTE)
  })

  it('L4 🔴 红证：viaBinding 指向无关文件 ⇒ 判红（动态记号必须被钉住）', () => {
    const input = realInput()
    const broken = input.entries.map((entry) =>
      entry.viaBinding ? { ...entry, viaBinding: 'src/pages/sessions/index/index.tsx' } : entry,
    )
    const problems = entryProblems({ ...input, entries: broken })
    expect(problems.join('\n')).toContain('绑定没被钉住')
  })

  it('L5 🔴 红证：把已撤的 `/w/` 入口重新登记回台账 ⇒ 判红（台账不许给不存在的入口盖章）', () => {
    const input = realInput()
    const restored = [
      ...input.entries,
      {
        route: INBOUND_PAGE_ROUTE,
        from: 'frontend/worker-h5/src/render.mjs',
        nav: 'href' as const,
        via: '/pages/worker/inbound/index',
        audience: '工人身份（合成：把 2026-10-10 已撤的 /w/ 入口重新登记）',
      },
    ]
    // 对照：真台账下判绿（否则下面那条"红"可能只是读错了文件）
    expect(entryProblems(input)).toEqual([])
    const problems = entryProblems({ ...input, entries: restored })
    expect(problems.join('\n')).toContain('声明存在 ≠ 可达')
    expect(problems.join('\n')).toContain(INBOUND_PAGE_ROUTE)
  })

  it('L6 🔴 红证：平台缺口只登记不接线 ⇒ 判红', () => {
    const input = realInput()
    const unwired: Reader = (rel) =>
      rel === 'src/pages/worker/reprint/index.tsx'
        ? readReal(rel).replace(/landingCodeFromParams\(/g, 'loadParams(')
        : readReal(rel)
    const gap = WORKER_SURFACE_PLATFORM_GAPS[0]
    expect(stripComments(unwired(gap.wiredBy)).includes(gap.wiredToken)).toBe(false)
    // 同一份输入下，真读法必须接线（否则上面那条"红"可能只是读错了文件）
    expect(stripComments(input.read(gap.wiredBy)).includes(gap.wiredToken)).toBe(true)
  })
})
