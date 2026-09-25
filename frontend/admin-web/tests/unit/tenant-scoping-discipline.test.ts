// case_ids: AU-002, AU-006
/**
 * 类级元守卫：前端**不为登录推导租户**（issue #5485 的 I1 / I3 前端半边）。
 *
 * ## 为什么要有这条（而不是只留实例判据）
 * 被删掉的 `store/auth.ts` legacy `login()` 是本仓**真实存在过**的病根形态：
 * 它把企业编码 `Number(tenantCode)` 解析成 `tenantId`，解析不出正整数时
 * **静默回落默认租户 1** ⇒ A 企业的员工拿别的（甚至非法）编码也进得去，且**没有任何东西会变红**。
 * 只删这一处 = 没修：下一个人写「兼容旧签名」时可以把同一形态原样加回来。
 * 本守卫让**这一类**进不来 —— 命中即给出 `文件:行号` 与出口。
 *
 * ## 判据口径（两条，都有红证）
 * ① 源码里不得出现「按企业编码/字符串推导 tenantId」的写法；
 * ② 也不得出现「tenant 相关值非法就回落某个默认租户」的形态。
 * 出口（唯一正确形态）：员工登录标识 `用户名@企业编码` **原样发服务端**
 * （`authApi.employeeLogin(identifier, password)`），租户由服务端按企业编码解析。
 *
 * ## 两条实测陷阱（本守卫自己踩过，已按此设计）
 * - **注释不算代码**：本仓的说明性注释里就写着 `Number(tenantCode)` / 回落租户 1 这些字面量
 *   （api.ts / auth.ts / types/index.ts 各一处）—— 若不做注释剥离，守卫会被**自己的文案**喂红
 *   （同 `migao-dev-flow` §23.4 T2 / §23.8 B1）。故先剥离注释再匹配。
 * - **只扫 `src/**`**：`tests/**` 里有专门用于红证的坏形态**夹具字符串**；
 *   把测试目录纳入扫描等于让夹具把守卫喂红（判据语料必须排除判据自身）。
 */
import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const ADMIN_WEB_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')

/** 禁止形态（标签 / 正则 / 出口文案） */
const FORBIDDEN: { name: string; re: RegExp; exit: string }[] = [
  {
    name: 'tenantId-由-Number/parseInt-推导',
    re: /tenantId\s*[:=][^\n]*\b(?:Number|parseInt|parseFloat)\s*\(/,
    exit: '租户由服务端按企业编码解析；前端只把 `用户名@企业编码` 原样发出去',
  },
  {
    name: 'Number/parseInt(<xxxCode>)',
    re: /\b(?:Number|parseInt)\s*\(\s*[A-Za-z_$][A-Za-z0-9_$]*[Cc]ode/,
    exit: '企业编码是**字符串标识**（基线含下划线，如 tenant_7478359537），不是数字',
  },
  {
    name: 'tenant-非法回落默认租户',
    re: /tenant[A-Za-z]*\s*[^,\n]{0,40}(?:\?\?|\|\|)\s*1\b/,
    exit: '解析不出租户时必须**显式拒绝**（服务端 401），不得静默落入任何默认租户',
  },
]

/** 剥离行注释与块注释（避免「判据被自己的说明文案喂红」）；仅需够用于本仓 TS/TSX 源码 */
export function stripComments(code: string): string {
  return code
    .replace(/\/\*[\s\S]*?\*\//g, '') // 块注释（含 JSDoc）
    .replace(/(^|[^:])\/\/[^\n]*/g, '$1') // 行注释（`[^:]` 避开 http:// 这类）
}

/** 检出禁止形态；返回 `文件:行号 形态` 列表（空 = 合规） */
export function detectTenantDerivation(code: string, file = 'snippet'): string[] {
  const stripped = stripComments(code).split('\n')
  const hits: string[] = []
  stripped.forEach((line, i) => {
    FORBIDDEN.forEach(({ name, re, exit }) => {
      if (re.test(line)) hits.push(`${file}:${i + 1} [${name}] 出口：${exit}`)
    })
  })
  return hits
}

function collectSourceFiles(dir: string): string[] {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) return collectSourceFiles(full)
    return /\.tsx?$/.test(entry.name) ? [full] : []
  })
}

describe('租户定位纪律（#5485 类级元守卫 · 前端不推导租户）', () => {
  it('src/ 全域零「按企业编码推导 tenantId / 非法回落默认租户」写法', () => {
    const files = collectSourceFiles(path.join(ADMIN_WEB_ROOT, 'src'))
    const violations = files.flatMap((f) =>
      detectTenantDerivation(fs.readFileSync(f, 'utf-8'), path.relative(ADMIN_WEB_ROOT, f)),
    )

    expect(files.length).toBeGreaterThan(50) // 守卫真的扫到了东西（不是空跑）
    expect(violations).toEqual([])
  })

  it('守卫自身有判别力（红证）：历史坏形态必被检出，且注释里的同形态不误伤', () => {
    // ① 历史坏形态（#5485 之前的 store/auth.ts 逐字形态）⇒ 必须检出
    const historical = [
      'const parsed = Number(tenantCode.trim())',
      'const tenantId = Number.isFinite(parsed) && parsed > 0 ? parsed : 1',
      'const params = { username, password, tenantId: Number(tenantCode.trim()) }',
    ].join('\n')
    const hits = detectTenantDerivation(historical)
    expect(hits.length).toBeGreaterThanOrEqual(2)
    // 点名坏形态 —— 锚点是**形态名**，不是「文件:行号」：后者会被 Case Trust Gate 的规则 G
    // 当成「对真实文件的陈旧行引用」判红（本断言测的是**合成夹具**，不指向任何真实文件的行）。
    expect(hits.some((h) => h.includes('tenantId-由-Number/parseInt-推导'))).toBe(true)
    expect(hits.some((h) => h.includes('Number/parseInt(<xxxCode>)'))).toBe(true)
    // 行号仍必须报到（夹具第 3 行是 `tenantId: Number(tenantCode.trim())`）：只断「带了位号」这一格式
    expect(hits.every((h) => /[0-9]+ \[/.test(h))).toBe(true)

    // ② 同样的字面量出现在**注释**里（本仓现状）⇒ 一条都不许命中
    //    （否则说明性注释会把守卫喂红 —— §23.4 T2 实测形态）
    const asComment = [
      '// 旧写法：把企业编码 Number(tenantCode) 解析、非法时回落默认租户 1',
      '/**',
      ' * 不要写 tenantId: Number(tenantCode) —— A 企业员工会被送进 B 企业',
      ' */',
      'export const ok = 1',
    ].join('\n')
    expect(detectTenantDerivation(asComment, 'doc-only.ts')).toEqual([])
  })
})