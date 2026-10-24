// case_ids: UI-113
/**
 * 类级元守卫（issue #7116，`#7007` 根因③）：**筛选区不许手写成裸 div**。
 *
 * ## 病灶
 *
 * 用户 2026-10-16：「只有订单管理的设计非常精美，其它的页面没有这种感觉」。
 * `#7007` 诊断出的第三条根因：**「同一个『筛选区』在仓里有三种互不相同的形态」**，
 * 而共享件 `frontend/admin-web/src/components/ui/SearchPanel.tsx` 抽出来之后**落地只有 1 页**
 * （`customers`），`PageCard` 却被 9 页拿去做筛选外壳。
 *
 * ## 本判据锁什么（只判**机械可判定**的那部分）
 *
 * **射程 = 页面上自己声明了「这是筛选区」的地方** —— 即存在
 * `data-testid="search-area"`（原生属性）**或** `testId="search-area"`（`PageCard` 的透传 prop）。
 *
 * 这是**有意收窄**：本仓页面标「筛选区」的方式不统一（有的完全没有标记），
 * 靠「这页有没有查询按钮 / 搜索框」去猜**会把新建单据表单误判成筛选区**
 * （实测：`orders/new/page.tsx` 有搜索框 + 查询 + 重置，但它是**下单表单**，不是筛选区）。
 * ⇒ 判据只承认**页面自己声明的意图**，不猜。
 *
 * 判据：声明的筛选区**必须由一个组件承载**（`SearchPanel` / `SearchBar` / `PageCard`），
 * **不得**是裸 `<div>`。理由不是审美，而是**能力**：裸 div 拿不到原语里的
 * 单一响应式 grid（行行对齐）/ 标签左置 / 按钮独占一行 / `h-9` 控件下限，
 * 于是每页各自漂移 —— 这正是「三种形态」的成因。
 *
 * ## 未固化项（照实登记，§19.1）
 *
 * - **不判**「该用 `SearchPanel` 还是 `SearchBar`」的**选择**是否正确
 *   （那是「页面是否自持筛选 state」的判断，形态上两者都合规；选择理由写在各自文件头）；
 * - **不判**没有声明标记的页面里**藏着的**筛选区（本仓还有若干页把筛选塞在 `PageCard` 里、
 *   毫无标记）—— 那需要先把标记补齐，属后续面（重启条件：标记收口成页面级约定时）；
 * - **不判**视觉美观（§15.7 读图 + §31 评审面）。
 */

import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative, sep } from 'node:path'
import { describe, expect, it } from 'vitest'

const DASHBOARD = join('src', 'app', '(dashboard)')

/** 筛选区的**声明方式**（两种写法都算「页面自己说这是筛选区」）。 */
export const SEARCH_AREA_DECL = /(?:data-testid|testId)="search-area"/
/** 合法的筛选区承载组件（裸 `div` / `section` 都不在其中）。 */
export const FILTER_PRIMITIVES = ['SearchPanel', 'SearchBar', 'PageCard'] as const

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) walk(p, out)
    else if (p.endsWith('.tsx')) out.push(p)
  }
  return out
}

export function scopeFiles(): string[] {
  return walk(DASHBOARD)
    .map((p) => relative(process.cwd(), p).split(sep).join('/'))
    .sort()
}

/**
 * 该文件里，`search-area` 这个方法/属性名**出现在什么标签上**。
 *
 * 返回每处声明的「承载标签名」（`` 表示按标签名取不到 ⇒ 视为裸元素）。
 * 判法：取 `search-area` 前 400 字符里**最后一个**开标签。
 */
export function carrierOfDeclarations(text: string): string[] {
  const out: string[] = []
  const re = new RegExp(SEARCH_AREA_DECL.source, 'g')
  let m: RegExpExecArray | null
  while ((m = re.exec(text)) !== null) {
    const head = text.slice(Math.max(0, m.index - 400), m.index)
    const tags = [...head.matchAll(/<([A-Za-z][\w.]*)/g)]
    const tag = tags.length > 0 ? tags[tags.length - 1][1] : ''
    out.push(tag)
  }
  return out
}

/** 承载标签是否合法（原语组件之一）。 */
export function isPrimitiveCarrier(tag: string): boolean {
  return (FILTER_PRIMITIVES as readonly string[]).includes(tag)
}

/** → 声明的筛选区里，**不是**由原语承载的那些（`文件:标签` 形态，便于判红点名）。 */
export function bareFilterAreas(files: string[] = scopeFiles()): string[] {
  const bad: string[] = []
  for (const rel of files) {
    const text = readFileSync(rel, 'utf8')
    for (const tag of carrierOfDeclarations(text)) {
      if (!isPrimitiveCarrier(tag)) bad.push(`${rel}（承载标签：<${tag || '?'}>）`)
    }
  }
  return bad
}

describe('判据 1：页面声明的筛选区必须由原语承载（不得是裸 div）', () => {
  it('没有「声明为 search-area 却由裸元素承载」的筛选区', () => {
    const files = scopeFiles()
    expect(files.length).toBeGreaterThan(40) // 反空跑：射程塌了要出声
    const bad = bareFilterAreas(files)
    expect(
      bad,
      `这些页面把筛选区声明成 \`search-area\`，却用**裸元素**承载 ⇒ 拿不到原语的\n` +
        `单一响应式 grid / 标签左置 / 按钮独占一行 / h-9 控件下限，于是各页各自漂移：\n  ` +
        `${bad.join('\n  ')}\n改用 frontend/admin-web/src/components/ui/SearchPanel.tsx` +
        `（无状态，页面自持筛选 state）或 SearchBar.tsx（自带 state）。`,
    ).toEqual([])
  })
})

describe('判据 2：反作弊 —— 射程内确实有声明，且确实都在用原语', () => {
  it('射程里存在足量筛选区（否则判据 1 是空转）', () => {
    // 计两种：① **显式声明**了 `search-area` 的（判据 1 的直接对象）；
    // ② **用了 `SearchPanel`** 的页面 —— 该原语的 `testId` 默认就是 `search-area`
    //    ⇒ 调用方**不需要**再写一遍声明，这类页面同样贡献「射程里有筛选区」这一事实。
    const files = scopeFiles()
    let explicit = 0
    let viaPrimitive = 0
    for (const rel of files) {
      const text = readFileSync(rel, 'utf8')
      explicit += carrierOfDeclarations(text).length
      if (text.includes('<SearchPanel')) viaPrimitive += 1
    }
    // 现取：显式 2（employees / products）+ 用原语 3（customers / orders / after-sales）= 5
    expect(explicit + viaPrimitive).toBeGreaterThanOrEqual(5)
  })

  it('三个原语文件都真实存在（判据引用的对象不许是空名）', () => {
    for (const name of FILTER_PRIMITIVES) {
      const p = join('src', 'components', 'ui', `${name}.tsx`)
      expect(statSync(p).isFile(), `原语文件不存在：${p}`).toBe(true)
    }
  })
})

describe('判别力自证', () => {
  it('坏形态判红、好形态放行（纯函数级）', () => {
    expect(carrierOfDeclarations('<div className="x" data-testid="search-area">')).toEqual(['div'])
    expect(isPrimitiveCarrier('div')).toBe(false)
    expect(carrierOfDeclarations('<SearchPanel fields={f} testId="search-area" />')).toEqual(['SearchPanel'])
    expect(isPrimitiveCarrier('SearchPanel')).toBe(true)
    expect(carrierOfDeclarations('<PageCard testId="search-area">')).toEqual(['PageCard'])
    expect(isPrimitiveCarrier('PageCard')).toBe(true)
    // 没有声明 ⇒ 不产生任何判定（不猜）
    expect(carrierOfDeclarations('<div className="flex"><Input placeholder="搜索" /></div>')).toEqual([])
  })
})
