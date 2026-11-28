/**
 * `src/app.config.ts` 的**页面清单唯一解析口径**（issue #8979；拆分包时抽出的共用实现）。
 *
 * 治的形态：有了 `subPackages` 之后，「页面在册」不再等于「路由字面量出现在 `pages` 里」——
 * `subPackages[].pages` 是**相对 root** 的路径（`pool/index`），绝对路由要合成：
 * `root='pages/admin'` + `pages[0]='pool/index'` ⇒ `/pages/admin/pool/index`。
 * 守卫若各自 `appConfig.includes("'pages/admin/pool/index'")`，拆包后会**假红**；
 * 若改成只读主包 `pages`，分包页就**逃出**「未登记即红」——两种都是判据空跑。
 * ⇒ 解析只有这一份实现，`tests/page-entry-reachability.test.ts` 与
 * `tests/admin-surfaces-guard.test.ts` 共用。
 *
 * 解析口径漂移（读不出 pages / root 没 pages / 同一路由两处登记）一律**抛错**：
 * 解析失败必须判红，不许静默返回空集 —— 空集上「每一页都登记了」恒真。
 */
import { stripComments } from './h5PlatformLists'

const READ_FAIL = 'app.config.ts 里读不出 pages 数组 ⇒ 判红而不是判绿（解析口径漂移了）'

/** 取 `key: [ … ]` 的方括号**配对**区间（页路由 / root 里没有方括号，按层级扫即可） */
function findArray(
  source: string,
  key: string,
): { body: string; start: number } | null {
  const head = new RegExp(`(?:^|[^A-Za-z0-9_$])\\s*${key}\\s*:\\s*\\[`)
  const match = head.exec(source)
  if (!match) return null
  const open = match.index + match[0].length - 1
  let depth = 0
  for (let i = open; i < source.length; i += 1) {
    if (source[i] === '[') depth += 1
    else if (source[i] === ']') {
      depth -= 1
      if (depth === 0) return { body: source.slice(open + 1, i), start: open }
    }
  }
  throw new Error(`${key} 的方括号没有配对 ⇒ 解析口径漂移`)
}

function stringLiterals(body: string): string[] {
  return Array.from(body.matchAll(/'([^']+)'/g)).map((m) => m[1])
}

function normaliseRoute(page: string): string {
  return `/${page}`.replace(/\/+/g, '/')
}

/**
 * 现取 app.config 的**全部页面路由**（主包 + 各分包，统一成带前导 `/` 的绝对路由）。
 * 与拆分前的口径逐值相同（拆包只改归属，不改路由）。
 */
export function parseAppConfigPages(rawSource: string): string[] {
  const source = stripComments(rawSource)

  const main = findArray(source, 'pages')
  if (!main) throw new Error(READ_FAIL)
  const routes = stringLiterals(main.body).map(normaliseRoute)
  if (routes.length < 8) {
    throw new Error(`app.config.ts 的 pages 只解析出 ${routes.length} 条 ⇒ 解析口径已漂移`)
  }

  const sub = findArray(source, 'subPackages')
  if (sub) {
    const roots = Array.from(sub.body.matchAll(/root\s*:\s*'([^']+)'/g))
    if (roots.length === 0) throw new Error('subPackages 声明了却解析不出任何 root ⇒ 解析口径已漂移')
    for (const rootMatch of roots) {
      const root = rootMatch[1].replace(/^\/+|\/+$/g, '')
      if (!root) throw new Error('subPackages 的 root 为空')
      const afterRoot = sub.body.slice(rootMatch.index! + rootMatch[0].length)
      const pagesArray = findArray(afterRoot, 'pages')
      if (!pagesArray) throw new Error(`分包 ${root} 没有 pages 数组`)
      // root 与它的 pages 之间若又出现一个 root ⇒ 归属不能猜（否则会把下一个分包算到这一个头上）
      if (/root\s*:\s*'/.test(afterRoot.slice(0, pagesArray.start))) {
        throw new Error(`分包 ${root} 的 pages 之前出现了下一个 root ⇒ 解析口径漂移（不许猜归属）`)
      }
      const relative = stringLiterals(pagesArray.body)
      if (relative.length === 0) throw new Error(`分包 ${root} 的 pages 为空（微信上传会报错）`)
      for (const page of relative) routes.push(normaliseRoute(`${root}/${page}`))
    }
  }

  const seen = new Set<string>()
  const duplicates = routes.filter((route) => {
    if (seen.has(route)) return true
    seen.add(route)
    return false
  })
  if (duplicates.length > 0) {
    throw new Error(`页面被重复登记（主包 / 分包之间）：${[...new Set(duplicates)].join(', ')}`)
  }

  return routes
}
