// case_ids: UI-100
/**
 * 类级元守卫（issue #7007）：**商家后台不得退回 Tailwind 默认冷色族**。
 *
 * ## 病灶
 *
 * 用户 2026-10-16 反馈「只有订单管理的设计精美，其它页面没有这种感觉」。诊断到的可归因差异之一：
 * 全仓共 **178 处**在用 Tailwind **默认调色板**（`gray-50` / `blue-50` / `indigo-100` …），
 * 而 `frontend/admin-web/tailwind.config.ts` **只定义了三族暖色**
 * （`primary` / `accent` / `neutral`，页面底色是暖亚麻 `neutral-50 = #faf7f2`）
 * ⇒ 这些类落回 Tailwind 内置值（`gray-50 = #f9fafb`、`blue-50 = #eff6ff`，都是**冷灰 / 冷蓝**），
 * 在同一屏里是一块**另一个产品的颜色**。
 *
 * 最典型的是共享件 `frontend/admin-web/src/components/ui/SearchBar.tsx` 的 `bg-gray-50`
 * —— 它被客户页与知识库页复用 ⇒ **一处漂移污染多页**。
 *
 * ## 🔴 射程（2026-10-16 当晚**一次收口**：从「分两档」改判为**全部硬禁**）
 *
 * 本判据第一版把冷色族分了两档：中性灰族（`gray`/`slate`/`zinc`/`stone`，本仓无对应 token）
 * **硬禁**；冷彩族（`blue`/`indigo`/`purple` 等，当时担心「有语义用途」）进**存量台账只许缩短**
 * （20 个文件 / 74 处）。**同一天内台账即清零** —— 用户当场裁定「**全部归到暖色 token**」，
 * 而逐处核过之后确认**没有一处真有语义**：它们服务的是同一组状态轮换
 * （`confirmed` / `producing` / `shipped`），三个色相纯粹是装饰性区分。
 *
 * ⇒ 台账与它的两条判据（双向相等 / 不许空转）**一并删除**，冷彩族升为**硬禁**。
 * 判据形态与理由（可复算）：
 *
 * | 族 | 映射 | 依据 |
 * |---|---|---|
 * | `blue` / `sky` / `cyan` | → `primary` | **仓里既有的语义约定**：`frontend/admin-web/src/lib/status-chip.ts` 开头逐字写着「替代默认蓝/灰/绿：**info→primary**」 |
 * | `indigo` / `purple` / `violet` | → `accent` | 这两族在本仓服务**同一组状态轮换**（如 `producing` 用 purple、`shipped` 用 indigo）⇒ 都归 accent，**颜色数从 3 降到 2**（更克制，不是更花） |
 *
 * ⚠️ **`gold` 不在可用集里**（如实登记）：`frontend/admin-web/src/lib/brand-palette.ts` 的
 * `gold` 只到 600 阶，实测 `text-gold-600` 在浅金底上对比度仅 **2.76:1**（WCAG AA 正文要 4.5:1）
 * ⇒ 金色是**点缀色**（官网 hero / 深色区块图标），**不用于文字与状态**。
 * ⇒ 暖色文字只有 `primary` / `accent` / `neutral` 三族可选。
 *
 * ⚠️ **本次**有意不扩网**的一族（观察项，非缺陷）**：`green-*`（`register` 页与
 * `CustomerPanel` 的「已完成」）—— 仓里的成功态约定是 `emerald`（`status-chip.ts` 的
 * `success: bg-emerald-50 …`），所以 `green-*` 同样属「第二个词说同一件事」；
 * 但它**不在本轮用户点名的冷色族里**，且 `green`/`emerald` 都是语义色（不是默认调色板兜底）
 * ⇒ 单列跟踪，不混进本条（重启条件 = 有单收口「成功态只有一个名字」时）。
 *
 * ## 判据（四条，全部会红）
 *
 * 1. **零默认调色板**：`src/app/**` + `src/components/**`（`.tsx`）里不得出现
 *    `gray`/`slate`/`zinc`/`stone`（中性灰族）与 `blue`/`indigo`/`sky`/`violet`/`purple`/`cyan`
 *    （冷彩族）的工具类；
 * 2. **暖色 token 仍在使用**（否则「全删干净」也能过，那等于把界面变成没配色的裸 Tailwind）；
 * 3. **判别力自证**：坏形态在内存里各自判红、好形态放行（同族先例 =
 *    `frontend/admin-web/tests/unit/auth-pages-warm-token-guard.test.ts` 的自证节）；
 * 4. **官网子树在射程之外**（`src/app/(corporate)/**` 有自己的对外口径）。
 *
 * ## 为什么「注释里提到」不算违规
 *
 * 本判据扫**源码文本**，而上面那段病灶说明与本仓多处修复注释**必然**要引用旧写法
 * （不然讲不清为什么改）⇒ 必须先去注释再扫，否则**守卫会被自己的说明喂红**
 * （本仓已多次踩）。`stripComments` 与 `auth-pages-warm-token-guard.test.ts` 同源口径。
 *
 * ## 边界（照实登记，§19.1）
 *
 * - 判的是**源码类名字面量**，不是渲染像素：「好不好看」仍由 `migao-dev-flow` §15.7 读图 + 人裁定；
 *   本判据只保证「**没退回另一个产品的配色**」这一件事；
 * - **射程不含** `frontend/admin-web/src/app/(corporate)/**`（官网有自己的一套对外口径，
 *   见 `docs/design/design-baseline.md` 的「官网是否纳入本基线」显式裁定）与 Taro 两个门面；
 * - 只认**命名空间**，不判具体色阶对错；
 * - 冷彩族台账**只许缩短**：本判据**不为存量背书**，只保证「不再增长 + 修一处少一处」；
 * - 不改任何门禁的通过条件、不新增 required check。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'

const ROOT = process.cwd()

/** 射程：商家后台的应用面与组件面 */
const SCAN_DIRS = ['src/app', 'src/components']

/**
 * 官网子树**有意排除**（`docs/design/design-baseline.md`：官网不纳入字号阶梯，只共用颜色 token；
 * 它有自己的对外口径，与本判据「商家后台统一暖色」不是同一条射程）。
 */
const EXCLUDED_PREFIXES = [join('src', 'app', '(corporate)')]

const UTILITY_PREFIX = 'bg|text|border|ring|from|via|to|divide|outline|shadow|decoration|accent|caret|fill|stroke'

/** ① 硬禁：中性灰族（本仓无对应 token ⇒ 出现即漂移） */
const NEUTRAL_GRAY_FAMILY = new RegExp(
  `\\b(?:${UTILITY_PREFIX})-(?:gray|slate|zinc|stone)-\\d{2,3}\\b`,
  'g'
)

/** ② 存量台账：冷彩族（有语义用途 ⇒ 逐包收口） */
const COOL_CHROMA_FAMILY = new RegExp(
  `\\b(?:${UTILITY_PREFIX})-(?:blue|indigo|sky|violet|purple|cyan)-\\d{2,3}\\b`,
  'g'
)

/** 暖色 token 命名空间（本仓真值源 = `frontend/admin-web/tailwind.config.ts` 的 colors） */
const WARM_TOKEN = /\b(?:bg|text|border|ring|from|via|to|divide|outline)-((?:primary|accent|neutral)-\d{2,3})\b/g

/**
 * 去掉注释（行注释 + 块注释）。
 *
 * 与 `frontend/admin-web/tests/unit/auth-pages-warm-token-guard.test.ts` 的 `stripComments`
 * **同一口径**：本判据扫源码文本，而病灶说明必须引用旧写法 ⇒ 不去注释就会「被自己的说明喂红」。
 */
export function stripComments(source: string): string {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, ' ')
    .replace(/(^|[^:])\/\/[^\n]*/g, '$1 ')
}

/** 递归收集 `.tsx`（跳过测试夹具与 node_modules —— 本判据射程是产品源码） */
function collectTsx(dir: string): string[] {
  const abs = join(ROOT, dir)
  const out: string[] = []
  const walk = (d: string) => {
    for (const entry of readdirSync(d)) {
      if (entry === 'node_modules' || entry === '__tests__' || entry.startsWith('.')) continue
      const p = join(d, entry)
      if (statSync(p).isDirectory()) walk(p)
      else if (p.endsWith('.tsx')) out.push(p)
    }
  }
  if (statSync(abs).isDirectory()) walk(abs)
  return out
}

const inExcluded = (abs: string) =>
  EXCLUDED_PREFIXES.some((prefix) => relative(ROOT, abs).startsWith(prefix))

function scan(re: RegExp): string[] {
  const hits: string[] = []
  for (const dir of SCAN_DIRS) {
    for (const abs of collectTsx(dir)) {
      if (inExcluded(abs)) continue
      const code = stripComments(readFileSync(abs, 'utf-8'))
      for (const m of code.matchAll(re)) hits.push(`${relative(ROOT, abs)}:${m[0]}`)
    }
  }
  return hits.sort()
}

/** 现取「中性灰族」违规点：`<仓库相对路径>:<命中串>` —— 判红必须可归因、可复算 */
export const findNeutralGrayHits = () => scan(NEUTRAL_GRAY_FAMILY)

/** 现取「冷彩族」命中点（与台账逐条比对） */
export const findCoolChromaHits = () => scan(COOL_CHROMA_FAMILY)

/** 现取「暖色 token 出现过的类名」集合（判据 2 用；空集 ⇒ 界面已无配色 ⇒ 红） */
export function findWarmTokens(): string[] {
  const found = new Set<string>()
  for (const dir of SCAN_DIRS) {
    for (const abs of collectTsx(dir)) {
      if (inExcluded(abs)) continue
      const code = stripComments(readFileSync(abs, 'utf-8'))
      for (const m of code.matchAll(WARM_TOKEN)) found.add(m[1])
    }
  }
  return [...found].sort()
}

describe('类级元守卫：商家后台一律暖色 token（不得退回 Tailwind 默认调色板）', () => {
  it('判据 1a：`src/app/**` + `src/components/**` 里零中性灰族（gray / slate / zinc / stone）', () => {
    const hits = findNeutralGrayHits()
    expect(
      hits,
      `发现 ${hits.length} 处中性灰族（本仓**没有** gray/slate/zinc/stone token，暖色族 = ` +
        `primary / accent / neutral；真值源 = frontend/admin-web/tailwind.config.ts）。` +
        `逐条改用对应的 neutral-*：\n` +
        hits.map((h) => `  - ${h}`).join('\n')
    ).toEqual([])
  })

  it('判据 1b：零冷彩族（blue / indigo / sky / violet / purple / cyan）—— 映射依据见文件头', () => {
    const hits = findCoolChromaHits()
    expect(
      hits,
      `发现 ${hits.length} 处冷彩族（映射：blue/sky/cyan → primary；indigo/purple/violet → accent。` +
        `依据 = 本仓 frontend/admin-web/src/lib/status-chip.ts 逐字写着「info→primary」，` +
        `且 indigo/purple 在本仓服务同一组状态轮换 ⇒ 都归 accent）：\n` +
        hits.map((h) => `  - ${h}`).join('\n')
    ).toEqual([])
  })

  it('判据 1c：`gold` 不得用于文字（对比度实测 2.76:1，未达 AA）', () => {
    // 如实登记的反面：`gold` 是**点缀色**（官网 hero / 深色区块图标），不是文字色。
    // 判据形态与 1a/1b 不同（这里没有 `gold` 的存量可清）⇒ 只钉「不许新增 text-*」。
    const src = collectTsx('src/components').concat(collectTsx('src/app'))
    const offenders: string[] = []
    for (const abs of src) {
      if (inExcluded(abs)) continue
      const code = stripComments(readFileSync(abs, 'utf-8'))
      for (const m of code.matchAll(/\btext-gold-\d{2,3}\b/g)) {
        offenders.push(`${relative(ROOT, abs)}:${m[0]}`)
      }
    }
    expect(
      offenders,
      `gold 不用于文字（frontend/admin-web/src/lib/brand-palette.ts 只到 600 阶，` +
        `text-gold-600 在浅金底上对比度实测 2.76:1 < AA 4.5:1）：\n` +
        offenders.map((h) => `  - ${h}`).join('\n')
    ).toEqual([])
  })

  it('判据 2：暖色 token 仍在使用（「全删干净」不算通过）', () => {
    const warm = findWarmTokens()
    expect(warm.length, '界面上一个暖色 token 都没有 ⇒ 等于没配色的裸 Tailwind').toBeGreaterThan(0)
  })

  it('判据 3a：自证 —— 中性灰族正则命中坏形态', () => {
    const bad = stripComments('<div className="bg-gray-50 text-gray-500 border-gray-200" />')
    expect([...bad.matchAll(NEUTRAL_GRAY_FAMILY)].map((m) => m[0]).sort()).toEqual([
      'bg-gray-50',
      'border-gray-200',
      'text-gray-500',
    ])
  })

  it('判据 3b：自证 —— 暖色 token 与语义色放行（不误伤）', () => {
    const good = stripComments(
      '<div className="bg-neutral-50 text-neutral-700 border-neutral-200 bg-primary-600 text-white bg-emerald-50 text-red-600 text-amber-700" />'
    )
    expect([...good.matchAll(NEUTRAL_GRAY_FAMILY)].map((m) => m[0])).toEqual([])
    expect([...good.matchAll(COOL_CHROMA_FAMILY)].map((m) => m[0])).toEqual([])
  })

  it('判据 3c：自证 —— 注释里的旧写法不算违规（否则守卫被自己的说明喂红）', () => {
    const commented = stripComments(
      '// 修前这里是 bg-gray-50（冷灰，与暖色 token 不同族）\nconst x = 1'
    )
    expect([...commented.matchAll(NEUTRAL_GRAY_FAMILY)].map((m) => m[0])).toEqual([])
  })

  it('判据 3d：自证 —— 官网子树在有意的射程之外', () => {
    expect(EXCLUDED_PREFIXES).toEqual([join('src', 'app', '(corporate)')])
    for (const dir of SCAN_DIRS) {
      for (const abs of collectTsx(dir)) {
        if (!inExcluded(abs)) continue
        expect(relative(ROOT, abs).startsWith(join('src', 'app', '(corporate)'))).toBe(true)
      }
    }
  })

})
