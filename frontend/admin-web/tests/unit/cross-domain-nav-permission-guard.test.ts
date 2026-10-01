// case_ids: UI-026
// 类级元守卫（issue #5913）：**跨权限域**的页内跳转入口，必须按目标域的守卫码显隐。
//
// 病（真实缺陷，issue #5913）：生产看板 `/production`（守卫 `production:view`）操作列的「查看」
// 跳 `/orders/{id}`（守卫 `order:list`），而默认岗位 `product_manager` **持前者、不持后者**
// （`backend/admin-api/.../RegistrationService.java` 的 productManagerRole 默认码表）
// ⇒ 按钮照渲染，点进去得「无权访问该页面」。**可见却 403** 是一类，不是一处：
// 任何「本页守卫码 ≠ 目标页守卫码」的 `router.push/replace` 都有同一形态。
//
// 判据（机械）：扫 `src/app` 下 `(dashboard)` 路由组内的源文件，取其中**字面量**跳转的目标；
// 若目标的守卫码 ≠ 源页守卫码，则源文件里必须出现 `has('<目标码>')` 形式的显隐判断，否则判红。
// 守卫码表**从 `layout.tsx` 现取**（不硬编码 —— 清单会漂移）。
//
// 边界（照实登记）：① 只认**字面量**（`router.push(someVar)` / 变量拼接不在射程）；
// ② 只判「源文件里出现了该码」，判不了它是否恰好包住那个按钮（语义面在实例判据里，
// 见 `frontend/admin-web/tests/unit/pages/production-board.test.tsx` 的「无 order:list ⇒ 不渲染」）。
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync } from 'fs'
import { join, relative, dirname, sep } from 'path'

const APP_DIR = join(process.cwd(), 'src/app')
const DASHBOARD_DIR = join(APP_DIR, '(dashboard)')
const LAYOUT = join(DASHBOARD_DIR, 'layout.tsx')

/**
 * 例外台账（**只许缩短**；登记值 = 相对 `src/app` 的路径）。
 * 当前为空 —— 命中规则但确有必要时，登记 + 写明理由（并检查是否该改守卫码表本身）。
 */
const EXEMPT: string[] = []

interface Guard {
  prefix: string
  code: string
}

/** 守卫码表：**现取** `layout.tsx` 的 `ROUTE_PERMISSION_MAP`（前缀 → 码） */
function parseGuards(layoutSource: string): Guard[] {
  return [...layoutSource.matchAll(/\{\s*prefix:\s*'([^']+)'\s*,\s*code:\s*'([^']+)'\s*\}/g)].map((m) => ({
    prefix: m[1],
    code: m[2],
  }))
}

/** 最长前缀命中（与 `layout.tsx` 的语义一致：更具体的子路径先命中） */
function guardCodeFor(url: string, guards: Guard[]): string | null {
  const hit = [...guards].filter((g) => url.startsWith(g.prefix)).sort((a, b) => b.prefix.length - a.prefix.length)[0]
  return hit ? hit.code : null
}

/** 源文件 → 它所在的路由（目录即路由；`(dashboard)` 路由组名不进 URL） */
function routeOf(file: string): string {
  const rel = relative(DASHBOARD_DIR, dirname(file)).split(sep).join('/')
  return rel === '' ? '/' : `/${rel}`
}

/** 字面量跳转（模板串取静态前缀：`router.push(\`/orders/${id}\`)` ⇒ `/orders/`） */
function pushedPaths(source: string): string[] {
  return [...source.matchAll(/router\.(?:push|replace)\(\s*[`'"]([^`'"$]*)/g)].map((m) => m[1])
}

/** 该文件是否按 `code` 显隐（`has('code')` / `hasPermission('code')`） */
function gatedBy(source: string, code: string): boolean {
  const escaped = code.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  return new RegExp(`has\\w*\\(\\s*['"]${escaped}['"]`).test(source)
}

/** 判定（纯函数：判别力自证直接喂合成样本给它，避免"判据本体没被验过"） */
function offenders(
  files: Array<{ file: string; route: string; source: string }>,
  guards: Guard[],
): string[] {
  const out: string[] = []
  for (const f of files) {
    if (EXEMPT.includes(f.file)) continue
    const srcCode = guardCodeFor(f.route, guards)
    // 源文件不在受守卫的路由组内（登录页 / 改密页等）⇒ 不在射程
    if (!srcCode) continue
    for (const target of pushedPaths(f.source)) {
      const tgtCode = guardCodeFor(target, guards)
      // 同域跳转（守卫码相同）⇒ 源页守卫已经覆盖，天然可达
      if (!tgtCode || tgtCode === srcCode) continue
      if (!gatedBy(f.source, tgtCode)) {
        out.push(`${f.file} · ${f.route} → ${target}（目标守卫码 ${tgtCode}，源页 ${srcCode}）`)
      }
    }
  }
  return [...new Set(out)]
}

function walk(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const p = join(dir, e.name)
    if (e.isDirectory()) return walk(p)
    return e.isFile() && e.name.endsWith('.tsx') ? [p] : []
  })
}

describe('跨权限域跳转入口守卫（issue #5913）', () => {
  const files = walk(DASHBOARD_DIR).map((file) => ({
    file: relative(APP_DIR, file).split(sep).join('/'),
    route: routeOf(file),
    source: readFileSync(file, 'utf-8'),
  }))
  const guards = parseGuards(readFileSync(LAYOUT, 'utf-8'))

  it('普查面非空且守卫码表解析成功（改名/搬走 ⇒ 本判据先红，而不是静默空跑）', () => {
    expect(files.length, '扫不到源文件 ⇒ 判据在扫空气').toBeGreaterThan(30)
    expect(guards.length, 'layout.tsx 的 ROUTE_PERMISSION_MAP 解析为空 ⇒ 判据已退化').toBeGreaterThanOrEqual(10)
    expect(guards.map((g) => g.code)).toContain('order:list')
    expect(files.map((f) => f.file)).toContain('(dashboard)/production/page.tsx')
  })

  it('判别力自证：合成样本上，未 gating 的跨域跳转必须被抓出（双向对照）', () => {
    const g: Guard[] = [
      { prefix: '/production', code: 'production:view' },
      { prefix: '/orders', code: 'order:list' },
    ]
    const sample = (source: string, route: string) => ({ file: 'sample.tsx', route, source })

    // 跨域 + 未 gating ⇒ 抓出（这正是 issue #5913 的形态）
    expect(offenders([sample("router.push('/orders/1')", '/production')], g)).toHaveLength(1)
    // 跨域 + gating ⇒ 放行
    expect(offenders([sample("has('order:list') && router.push('/orders/1')", '/production')], g)).toEqual([])
    // 同域（源 = 目标守卫码）⇒ 不在射程
    expect(offenders([sample("router.push('/orders/1')", '/orders/[id]')], g)).toEqual([])
    // 源文件不在受守卫路由组内 ⇒ 不在射程
    expect(offenders([sample("router.push('/orders/1')", '/login')], g)).toEqual([])
  })

  it('每个跨权限域跳转入口都按目标域守卫码显隐（本单实例 = 生产看板的「订单详情」）', () => {
    const bad = offenders(files, guards)
    expect(
      bad,
      '这些入口会渲染成「点进去 403」—— 源页守卫码不蕴含目标页守卫码，且入口未按目标码显隐：\n'
        + `${bad.join('\n')}\n`
        + "出口：按 `has('<目标码>')` 显隐该入口（生产看板「订单详情」即先例），"
        + '或把该文件登记进 EXEMPT 并写明理由。',
    ).toEqual([])
  })

  it('豁免台账不得腐坏（登记的文件必须仍然存在）', () => {
    const present = files.map((f) => f.file)
    for (const f of EXEMPT) {
      expect(present, `豁免条目 ${f} 已不存在 ⇒ 死条目，请删除`).toContain(f)
    }
  })
})
