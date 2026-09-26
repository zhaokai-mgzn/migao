// case_ids: BM-006
/**
 * 类级元守卫：bmini 的**报工写面只许有一个入口**（issue #5647 G10 的固化面）。
 *
 * ## 为什么需要一条「类级」判据
 * 这处缺陷能长期存在，是因为「多长出一条写路径」**没有任何东西会红**：页面同时调
 * URL 定工序的 `.../operations/{id}/report` 与 `scan/complete`，两条路各自都跑得通，
 * 而防呆④（非本部位码）/ 防呆⑤（工序必须确定）/ 一次事务 / `done_at` 只在后者生效
 * ⇒ 同一租户两条报工路径迟早给出不同结果，且**只能靠人记得**别走错那条。
 * 本条把「写入口唯一」变成可执行判据：**新增第二条 ⇒ 红**（无豁免台账 ⇒ 不存在「登记一下就放行」）。
 *
 * ## 判据（全部取 `frontend/bmini-app/src/**` 的源码文本，不依赖运行时）
 * ① `reportOperation` 符号一处都不许有（URL 定工序那条路的客户端封装，issue #5647 已退场）；
 * ② `/operations/{...}/report` 形态一处都不许有（工序不得再由客户端定）；
 * ③ 唯一写入口端点 `/api/worker/production/scan/complete` 全 `src/**` **只有一处实现**；
 * ④ 生产服务里 `/api/worker/**` 的 POST 端点集合 = {`/api/worker/production/scan/complete`}。
 *
 * ## 红证（2026-09-26 实测）
 * 把 `reportOperation`（含其 URL）加回 `src/services/productionService.ts` ⇒ ①②③④ 四条**全红**；
 * 撤回后复跑全绿。
 */
import fs from 'fs'
import path from 'path'

const SRC_ROOT = path.join(__dirname, '..', 'src')
const PRODUCTION_SERVICE = path.join(SRC_ROOT, 'services', 'productionService.ts')
const SCAN_COMPLETE_ENDPOINT = '/api/worker/production/scan/complete'

/** 递归收集 `src/**` 下的源码文件（样式 / 资源不参与文本取判据）。 */
function sourceFiles(dir: string): string[] {
  const collected: string[] = []
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) {
      collected.push(...sourceFiles(full))
    } else if (/\.(ts|tsx|mjs|js)$/.test(entry.name)) {
      collected.push(full)
    }
  }
  return collected
}

const FILES = sourceFiles(SRC_ROOT)

/** 命中该正则的位置清单（`相对路径:行号` —— 判红时可归因到具体一行）。 */
function hits(pattern: RegExp): string[] {
  const found: string[] = []
  for (const file of FILES) {
    fs.readFileSync(file, 'utf8')
      .split('\n')
      .forEach((line, index) => {
        if (pattern.test(line)) found.push(`${path.relative(SRC_ROOT, file)}:${index + 1}`)
      })
  }
  return found
}

/** `productionService.ts` 里 `post<…>(…)` 的端点字面量（工人路径的写面集合）。 */
function workerPostEndpoints(): string[] {
  const text = fs.readFileSync(PRODUCTION_SERVICE, 'utf8')
  const endpoints: string[] = []
  for (const match of text.matchAll(/post(?:<[^(]*)?\(\s*(['"`])([^'"`]+)\1/g)) {
    if (match[2].startsWith('/api/worker/')) endpoints.push(match[2])
  }
  return endpoints
}

describe('bmini 报工写面唯一入口（issue #5647 G10 类级守卫）', () => {
  it('判据①：URL 定工序的客户端封装（reportOperation）一处都不许有', () => {
    expect(hits(/\breportOperation\b/)).toEqual([])
  })

  it('判据②：/operations/{id}/report 端点形态一处都不许有', () => {
    expect(hits(/operations\/\$\{[^}]*\}\/report/)).toEqual([])
  })

  it('判据③：唯一写入口 /api/worker/production/scan/complete 只有一处实现', () => {
    const files = hits(/\/api\/worker\/production\/scan\/complete/).map((loc) => loc.split(':')[0])
    expect(Array.from(new Set(files))).toEqual(['services/productionService.ts'])
  })

  it('判据④：生产服务里 /api/worker/** 的 POST 端点集合 = {scan/complete}', () => {
    expect(workerPostEndpoints()).toEqual([SCAN_COMPLETE_ENDPOINT])
  })
})
