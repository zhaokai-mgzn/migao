// case_ids: OPS-001
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

/**
 * 供应链两个页面的**页面级留白**（issue #7373 复盘）。
 *
 * <h3>要治的形态</h3>
 * <p>布局的 `<main>` 只给外层留白，里面那层白色圆角卡片**自身没有 padding**（padding 由各页面自己给）。
 * 于是漏写页面留白的页面：标题、按钮、卡片全都贴边，视觉上「整页是歪的」—— 云上「采购单」页就是这样
 * （用户逐字：「采购单的页面布局是歪的」）。它不报错、不白屏，只是看起来廉价，且**没有任何判据会红**。</p>
 *
 * <h3>为什么只钉这两页（而不是全仓 45 页）</h3>
 * <p>实测：全仓 45 个 dashboard 页面里只有 25 个用 `className="p-6"`，其余 18 个（对话 / 画布 / 全高布局 /
 * 详情页）各有自己的留白方案。写一条「全仓都要 p-6」的守卫需要 18 条例外 —— 那种守卫半年后没人敢动。
 * 所以这里只钉**本特性新增的两个页面**（供应商 / 采购单），并在注释里写清取舍：新页面跟同族页面
 * （`orders` / `products` / `inbound-orders` 都是 `p-6`）对齐。</p>
 *
 * <p>红证方向：删掉 `purchase-orders/page.tsx` 的 `className="p-6"` ⇒ 本判据当场红。</p>
 */
const SUPPLY_CHAIN_PAGES = [
  'src/app/(dashboard)/suppliers/page.tsx',
  'src/app/(dashboard)/purchase-orders/page.tsx',
]

describe('供应链页面留白（与同族页面同款 p-6）', () => {
  it.each(SUPPLY_CHAIN_PAGES)('%s 根元素带页面级 p-6', (relPath) => {
    const source = readFileSync(join(process.cwd(), relPath), 'utf-8')
    // 只取**页面组件本体**的 `return (`（顶格两空格缩进）；文件里还有 map 回调 / 子组件的 `return (`，
    // 取最后一个会把内部 `<tr>` 当成根元素（实测踩过）
    const start = source.search(/\n {2}return \(/)
    // 弱断言守卫（issue #5477）不许 `not.toBeNull()` 这类存在性断言：这里直接对**根元素标记**取值，
    // 取不到就是空串 ⇒ 下面的 `toContain('p-6')` 立刻红（既断言存在，也断言内容）
    expect(start).toBeGreaterThan(-1)
    const rootTag = source.slice(start).split('\n').slice(1, 4).join('\n')

    expect(rootTag).toContain('p-6')
  })
})
