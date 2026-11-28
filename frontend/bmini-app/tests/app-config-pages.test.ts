// case_ids: BM-070
/**
 * **`app.config.ts` 页面清单的解析判据**（issue #8979：管理面移入分包后，「在册」的口径变了）
 *
 * ## 治的形态
 *
 * 拆分包后，低频页不再以绝对路由字面量出现在 `pages` 里 —— 它们是 `subPackages[].pages`
 * 的**相对 root** 路径（`pool/index`），绝对路由 `root + '/' + page` 要**合成**。
 * 守卫若继续 `appConfig.includes("'pages/admin/pool/index'")` ⇒ 拆包后**假红**；
 * 若改成只读主包 `pages` ⇒ 分包页**逃出**「未登记即红」⇒ 判据空跑。两种都是本判据要拦的。
 *
 * ## 判据（唯一实现 = `tests/helpers/appConfigPages.ts`，两个守卫共用）
 *
 * | # | 判据 | 红证（怎么让它单独变红） |
 * |---|---|---|
 * | ① | 正跑：现取 **25 条**（21 主包 + 4 分包），4 个管理面合成后**逐字等于**拆分前的路由；无重复登记 | 从 `subPackages` 摘掉一条 ⇒ 该路由不在清单里 |
 * | ② | 🔴 分包声明**不能绕过**：摘掉整个 `subPackages` 段 ⇒ 清单只剩 21 条、4 个管理面全部消失（证明解析不是从别处「补」出来的） | 把解析改成只读主包 `pages` ⇒ 本条红 |
 * | ③ | 空 `pages` / 只有 `subPackages` 没有 `root` ⇒ **抛错**（判红，不静默返回空集） | 把分包 `pages: [...]` 改成 `pages: []` ⇒ 抛「pages 为空」 |
 * | ④ | 同一路由同时登记在主包与分包 ⇒ **抛错**（微信会认两份，归属靠猜 ⇒ 不许猜） | 往主包 `pages` 再加一条 `pages/admin/pool/index` ⇒ 抛「重复登记」 |
 * | ⑤ | 注释里的 `pages: [` 骗不过解析（先剥注释；`app.config.ts` 的注释里确实出现过方括号） | 把剥注释去掉 ⇒ 解析被注释里的 `]` 截断 ⇒ 抛「方括号没有配对」/条数漂移 |
 *
 * 边界：本判据只保证「app.config 声明了这些页面、且解析口径能读出来」；
 * **产物里真的有这些页**由 `deploy/scripts/bmini-assert-dist.sh` 判据 ①（结构）与
 * `tests/unit_ci_workflows/test_bmini_dist_assert.py` 负责；**主包字节**由同一个脚本判据 ③ 负责。
 */
import fs from 'fs'
import path from 'path'
import { parseAppConfigPages } from './helpers/appConfigPages'
import { BMINI_ROOT } from './helpers/h5PlatformLists'

const APP_CONFIG = path.join(BMINI_ROOT, 'src', 'app.config.ts')

const ADMIN_ROUTES = [
  '/pages/admin/pool/index',
  '/pages/admin/inbound/index',
  '/pages/admin/after-sales/index',
  '/pages/admin/piecework/index',
]

const readSource = (): string => fs.readFileSync(APP_CONFIG, 'utf8')

/** 变异生效自证：锚点失配时 `replace` 会静默返回原文 ⇒ 红证退化成空断言 */
function mutate(source: string, from: string, to: string): string {
  const mutated = source.replace(from, to)
  if (mutated === source) throw new Error(`变异锚点失配：${from}`)
  return mutated
}

describe('app.config 页面清单：主包 + 分包的唯一解析口径（issue #8979）', () => {
  it('① 正跑：25 条（21 主包 + 4 分包），管理面合成路由与拆分前逐字相同，且无重复', () => {
    const pages = parseAppConfigPages(readSource())
    expect(pages.length).toBe(25)
    for (const route of ADMIN_ROUTES) expect(pages).toContain(route)
    expect(new Set(pages).size).toBe(pages.length)
  })

  it('② 红证：摘掉整个 subPackages 段 ⇒ 4 个管理面从清单消失（不是「在册」）', () => {
    const source = readSource()
    const block = [
      '  subPackages: [',
      '    {',
      "      root: 'pages/admin',",
      "      pages: ['pool/index', 'inbound/index', 'after-sales/index', 'piecework/index'],",
      '    },',
      '  ],',
      '',
    ].join('\n')
    const mutated = mutate(source, block, '')
    const pages = parseAppConfigPages(mutated)
    expect(pages.length).toBe(21)
    for (const route of ADMIN_ROUTES) expect(pages).not.toContain(route)
  })

  it('③ 红证：分包 pages 为空 ⇒ 抛错（判红，不静默返回空集）', () => {
    const mutated = mutate(
      readSource(),
      "pages: ['pool/index', 'inbound/index', 'after-sales/index', 'piecework/index']",
      'pages: []',
    )
    expect(() => parseAppConfigPages(mutated)).toThrow(/pages 为空/)
  })

  it('③b 红证：有 subPackages 却没有 root ⇒ 抛错（口径漂移不许静默跳过）', () => {
    const mutated = mutate(readSource(), "root: 'pages/admin',\n", '')
    expect(() => parseAppConfigPages(mutated)).toThrow(/解析不出任何 root/)
  })

  it('④ 红证：同一路由同时登记在主包与分包 ⇒ 抛错（归属不许猜）', () => {
    const mutated = mutate(
      readSource(),
      "    'pages/worker/stock/index',\n",
      "    'pages/worker/stock/index',\n    'pages/admin/pool/index',\n",
    )
    expect(() => parseAppConfigPages(mutated)).toThrow(/重复登记/)
  })

  it('⑤ 红证：注释里的 `pages: [` 骗不过解析（先剥注释）', () => {
    const mutated = mutate(readSource(), '  pages: [\n', "  // pages: ['/fake/page/index']\n  pages: [\n")
    expect(parseAppConfigPages(mutated)).toEqual(parseAppConfigPages(readSource()))
  })
})
