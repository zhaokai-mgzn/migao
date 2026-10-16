// @vitest-environment jsdom
// case_ids: UI-109
/**
 * `lucide-react` mock 的**闭集元守卫**（issue #7007）。
 *
 * ## 为什么要有这条（同一族缺陷已咬过两次）
 *
 * 一个测试文件用 `vi.mock('lucide-react', () => ({ A: stub(), B: stub() }))` 替身图标时，
 * 那个返回值是一个**闭合集合**。它本身没毛病 —— 直到**被测模块的依赖面变大**：
 *
 * - 第 1 次（本轮）：`@/components/ui` 的桶改成 `...actual`（摊开真原语）⇒ 真的加载 `EmptyState`
 *   ⇒ `EmptyState` 自己 `import { Package, Search, FileX, Inbox } from 'lucide-react'`
 *   ⇒ 7 个套件同时加载失败：`No "Package" export is defined on the "lucide-react" mock`。
 * - 第 2 次（同一轮内，换个宿主）：`@/components/ui` **桶**的 mock 本身也是闭集，症状一模一样。
 *
 * ⇒ 这是**类级**缺陷，不是某一处写错：**用闭合集合去替身一个会继续增长的模块**。
 * 单点修复只是把病灶挪到下一层（实测就是这么发生的）。
 *
 * ## 判据（会红）
 *
 * 扫 `tests/**` 下所有 TS/TSX，凡出现 `vi.mock('lucide-react', …)`：
 * - 若它是**本仓既有 helper** `tests/unit/helpers/lucide-mock.ts`（`lucideMock(...)`）
 *   ⇒ 放行（该 helper 自己 `...actual`）；
 * - 否则该 mock 的**工厂返回值里必须出现 `...actual`**，且工厂必须是 `async (importOriginal)`
 *   ⇒ 否则判红并**具名**列出文件。
 *
 * **红证**：把任一文件的 `...actual` 删掉（或把 `async (importOriginal)` 改回 `() =>`）⇒ 本判据当场红。
 *
 * ## 边界（照实登记）
 *
 * - 它管的是「**mock 的形状**」，不是「用了哪个图标」—— 不保证图标的 testid 对不对；
 * - 它只认**字面量**形态的 `vi.mock('lucide-react', …)`（动态名 / 变量名构造的 mock 不在此列，
 *   实测本仓为 0 处）；
 * - `tests/setup.ts` 的**全局**桩也在扫描面内并**同样要求 `...actual`**（它是所有文件的兜底，
 *   漏一个图标就是全仓红 —— 实测 `File` / `KeyRound` / `MailOpen` 三个图标就不在它的 163 个桩里）。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'

const TESTS_ROOT = join(__dirname, '..')
const REPO_TEST_HELPER = 'helpers/lucide-mock'

/** 递归收集 tests/ 下的 .ts / .tsx */
function collectTests(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) {
      collectTests(p, out)
    } else if (p.endsWith('.ts') || p.endsWith('.tsx')) {
      out.push(p)
    }
  }
  return out
}

/** 取出 `vi.mock('lucide-react', ...)` 这一次调用的源码片段（到下一个顶层 `vi.mock(` 为止） */
function lucideMockSegments(src: string): string[] {
  const out: string[] = []
  let i = src.indexOf("vi.mock('lucide-react'")
  while (i >= 0) {
    const next = src.indexOf('vi.mock(', i + 10)
    out.push(src.slice(i, next > 0 ? next : src.length))
    i = src.indexOf("vi.mock('lucide-react'", i + 10)
  }
  return out
}

describe('lucide-react mock 闭集元守卫（issue #7007）', () => {
  const files = collectTests(TESTS_ROOT)

  it('语料下限：真的扫到了本仓的测试文件（否则「零违规」是空转绿）', () => {
    // 红证：把 TESTS_ROOT 指错 ⇒ 本判据当场红（避免「扫了个空目录 ⇒ 全绿」）
    expect(files.length).toBeGreaterThan(200)
  })

  it('凡替身 lucide-react 的 mock，都必须是「摊开真值 + 显式桩」而不是闭合集合', () => {
    const offenders: string[] = []
    let checked = 0

    for (const f of files) {
      // 跳过本扫描器自己：源码里含被扫的字面量，否则它会扫到自己那几行模板字符串
      if (f.endsWith('lucide-mock-closure-guard.test.ts')) continue
      const src = readFileSync(f, 'utf-8')
      for (const seg of lucideMockSegments(src)) {
        // 仓内既有 helper：它自己 `...actual` ⇒ 放行
        if (seg.includes(REPO_TEST_HELPER) || seg.includes('lucideMock')) continue
        checked += 1
        const rel = relative(TESTS_ROOT, f)
        // ① 工厂必须是 async (importOriginal)
        if (!/vi\.mock\('lucide-react',\s*async\s*\(/.test(seg)) {
          offenders.push(`${rel}：工厂不是 async (importOriginal) ⇒ 没有任何途径拿到真值`)
          continue
        }
        // ② 两种**开放集**形态任一即可：
        //    (a) `return { ...actual, <显式桩> }`（本仓主流）
        //    (b) `new Proxy(actual, { get(...) { ... return target[prop] ?? stub } })`
        //        —— 未知键**透给真值**（`list-write-button-permission.test.tsx` 的写法）
        const isSpreadOpen = /return\s*\{[\s\S]{0,400}?\.\.\.actual/.test(seg)
        const isProxyOpen = /new\s+Proxy\(\s*actual/.test(seg)
        if (!isSpreadOpen && !isProxyOpen) {
          offenders.push(`${rel}：既没有 ...actual 也不是 Proxy(actual) ⇒ 是闭合集合（依赖面一变大就报 No "X" export）`)
        }
      }
    }

    // 红证：删掉任一文件的 `...actual`（或改成同步工厂）⇒ offenders 非空、本判据红
    expect(offenders).toEqual([])
    // 反向：真的检查了东西（本仓实测 14+ 处，取一个下界即可；改窄扫描面会让它红）
    expect(checked).toBeGreaterThanOrEqual(10)
  })

  it('全局 setup.ts 的兜底桩也必须摊开真值（它漏一个图标就是全仓红）', () => {
    // 红证：把 setup.ts 里 lucide 的 `...actual` 删掉 ⇒ 本判据当场红
    const setup = readFileSync(join(TESTS_ROOT, 'setup.ts'), 'utf-8')
    const segs = lucideMockSegments(setup)
    expect(segs.length).toBeGreaterThan(0)
    expect(segs[0]).toContain('...actual')
  })
})
