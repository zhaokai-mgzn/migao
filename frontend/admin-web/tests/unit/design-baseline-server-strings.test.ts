// case_ids: UI-057
/**
 * 类级元守卫（issue #6668 盲区②）：**服务端下发的字符串，展示名与标识分离**。
 *
 * ## 病灶（今天是怎么漏的）
 *
 * 本仓已有的上屏类守卫各管一段，**两段都不管服务端文案**：
 * - `frontend/admin-web/tests/unit/user-copy-jargon-guard.test.ts`（UI-093）只扫**前端字面量**；
 * - `frontend/admin-web/tests/unit/jsx-machine-key-guard.test.ts`（UI-094）只判**文本位的纯成员链**；
 * - `frontend/admin-web/scripts/read-failure-empty-state-scan.mjs` 的注释里逐字写着
 *   「服务端下发的 `message` 里带字段名」**不在本条射程**（那是展示字段分离，另单）。
 *
 * ⇒ 于是有三条**没人管**的形态：
 * ① 前端**自己切**服务端下发的复合串（`.split('|')` 一族）；
 * ② 服务端把**标识**塞进**展示位**（`error.details[{"field":"requiredPermission","message":"<权限码>"}]`
 *    —— 那个 `message` 里装的是 `product:read` 这类**机读权限码**，不是人话）；
 * ③ 服务端只下发机器键、**没有展示名字段**（`materialKey` 只有 `productId|skuCode`）。
 *
 * ## 判据
 *
 * | # | 判什么 | 怎么红 |
 * |---|---|---|
 * | ① | **前端不切服务端字符串**：源码里出现 `.split('\|')` / `.split("\|")` | 新增一处切串 ⇒ 红（未登记） |
 * | ② | **`requiredPermission` 的 `message` 不得直出**：`src/**` 里不得出现把 `requiredPermission` 的结果当文案的值 | 把它 `setState` 成提示语 ⇒ 红 |
 * | ③ | **台账只许缩短 + 每条非空理由**：不再命中的条目 ⇒ 红 | 修完后忘删 ⇒ 红 |
 * | ④ | **各类不少于 1 条**（fail-closed） | 清空台账 ⇒ 红 |
 * | ⑤ | **判别力自证（注入式）**：切串 / 权限码直出 / 前端自拼 `materialKey` 三种坏形态各自判红 | 见下 |
 * | ⑥ | **「只改展示」负控**：`materialKey` 的**机器消费者**（React key / 分组判据 / 接口名）逐值不变 | 见下 |
 *
 * ## 与 UI-094 的分工（不重复造网）
 *
 * 「`{group.materialKey}` 直接渲染成文本」**已由 UI-094 守**（它会红）—— 本文件**不重判**那一条，
 * 只在判别力自证里把它当**对照读数**引用（证明本文件与 UI-094 合起来才盖满这一族）。
 *
 * ## 边界（照实登记，§19.1）
 *
 * - 服务端**新增展示名字段**（`materialLabel` / `permissionLabel` 一类）不在本包射程
 *   （那是 admin-api / ai-agent-service 的改动）⇒ 判据只保证**前端这一侧**不把标识当展示；
 *   服务端那一侧登记为**未固化项**，出口写在 `docs/design/design-baseline.md` 的「未固化项」。
 * - 只认源码文本形态；模板串拼接（`` `${a}|${b}` ``）与其它分隔符（`:` / `#`）**不在面内**。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative, sep } from 'node:path'

const ROOT = process.cwd()
const SRC = join(ROOT, 'src')
const LEDGER_PATH = join(ROOT, 'tests/unit/server-string-display-ledger.json')

interface Ledger {
  why: string
  ledger: Record<string, { rule: string; kind: 'risk' | 'benign'; reason: string }>
  boundary: string
}
const ledger = JSON.parse(readFileSync(LEDGER_PATH, 'utf-8')) as Ledger

/** 台账不可清空的下界（现取 = 2 条；只许缩短） */
const FROZEN_ENTRY_MAX = 2

const SKIP_DIRS = new Set(['node_modules', '.next', 'dist', 'coverage', '__pycache__'])

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir).sort()) {
    if (SKIP_DIRS.has(name)) continue
    const full = join(dir, name)
    if (statSync(full).isDirectory()) walk(full, out)
    else if (/\.(ts|tsx)$/.test(name) && !/\.(test|spec)\.(ts|tsx)$/.test(name)) {
      out.push(relative(ROOT, full).split(sep).join('/'))
    }
  }
  return out
}

/** 注释剔除法（保行号）：注释里**引用**坏形态不该判红（同 UI-094 的对照读数）。 */
function stripComments(src: string): string {
  return src.replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, ' ')).replace(/^\s*\/\/.*$/gm, '')
}

/** 判据①：前端切服务端复合串（`|` 是本仓服务端复合键的实测分隔符：`productId|skuCode`） */
export function findDelimiterSplits(src: string): string[] {
  return [...stripComments(src).matchAll(/\.split\(\s*['"]\|['"]/g)].map((m) => m[0])
}

/**
 * 判据②：机读权限码被当**文案**。
 *
 * 只判「拿它当**给人看的内容**」的形态（枚举得太宽会把「用它做权限判断」的正常代码判红，
 * 那是假红、会掩盖真缺陷 —— 判别力自证逐条钉住两边）：
 * - **进提示语**：`toast.error(requiredPermission)` / `setError(…, requiredPermission)` 一族；
 * - **进 JSX 文本**：`>{requiredPermission}<` / `>{x.requiredPermission}<`。
 *
 * **不判**：`const requiredPermission = …find(…)`（本地变量）、`hasPermission(requiredPermission)`
 * （判定入参）、`field === 'requiredPermission'`（字段名判定）—— 它们都不产生展示文案。
 */
export function findPermissionCodeAsCopy(src: string): string[] {
  const out: string[] = []
  for (const line of stripComments(src).split('\n')) {
    if (!/\brequiredPermission\b/.test(line)) continue
    const intoToast = /\b(?:toast\s*\.\s*\w+|set[A-Z]\w*)\s*\([^()]*requiredPermission/.test(line)
    const inJsx = />\s*\{[^}]*requiredPermission[^}]*\}\s*</.test(line)
    if (intoToast || inJsx) out.push(line.trim())
  }
  return out
}

const files = walk(SRC)
const fileText = new Map(files.map((f) => [f, readFileSync(join(ROOT, f), 'utf-8')]))

const hits: Array<{ file: string; rule: string }> = []
for (const [file, text] of fileText) {
  if (findDelimiterSplits(text).length > 0) hits.push({ file, rule: 'SS-delimiter-split' })
  if (findPermissionCodeAsCopy(text).length > 0) hits.push({ file, rule: 'SS-permission-code-as-copy' })
}
const hitKeys = [...new Set(hits.map((h) => `${h.file}::${h.rule}`))].sort()

describe('服务端下发字符串：展示名与标识分离（类级元守卫，issue #6668 盲区②）', () => {
  it('扫描面活着（文件数下限 + 每条规则的判据函数都能在坏形态上命中）', () => {
    expect(files.length, 'src 下应有大量源文件').toBeGreaterThanOrEqual(150)
    expect(findDelimiterSplits("content.split('|', 3)").length).toBe(1)
    expect(findPermissionCodeAsCopy("const hint = error.details[0].message").length).toBe(0) // 判定式不算
    expect(findPermissionCodeAsCopy("setHint(requiredPermission)").length).toBe(1)
  })

  it('① 未登记即红：每一处命中都必须进台账', () => {
    const unregistered = hitKeys.filter((k) => !(k in ledger.ledger))
    expect(
      unregistered,
      '这些位置在「切服务端字符串 / 把机读权限码当文案」——服务端展示名与标识没有分离。\n'
        + '出口：① 需要展示名 ⇒ 请服务端新增展示字段（如 `materialLabel` / `permissionLabel`），前端不切串；'
        + '② 前端自有协议（生产者与消费者都在本仓）⇒ 登记进 frontend/admin-web/tests/unit/server-string-display-ledger.json 并逐字写理由。',
    ).toEqual([])
  })

  it('② 台账只许缩短：不再命中的条目当场红', () => {
    const stale = Object.keys(ledger.ledger).filter((k) => !hitKeys.includes(k))
    expect(stale, '台账里这些条目已不再命中 ⇒ 删掉（台账只许缩短）：' + stale.join(', ')).toEqual([])
  })

  it('③ 每条必须有非空理由（reason < 10 字即红）', () => {
    const bad = Object.entries(ledger.ledger)
      .filter(([, v]) => typeof v.reason !== 'string' || v.reason.trim().length < 10)
      .map(([k]) => k)
    expect(bad, '这些条目缺理由（理由必须能被人复核）').toEqual([])
  })

  it('④ 台账不许被清空（fail-closed）', () => {
    expect(Object.keys(ledger.ledger).length, '台账为空 ⇒ 要么真修完（下调冻结基线并说明），要么被清空骗绿').toBeGreaterThan(0)
    expect(Object.keys(ledger.ledger).length).toBeLessThanOrEqual(FROZEN_ENTRY_MAX)
  })
})

describe('判别力自证：坏形态各自判红、好形态不红（注入式）', () => {
  it('🔴 前端自切服务端复合串 ⇒ 判红', () => {
    expect(findDelimiterSplits("const [productId, skuCode] = group.materialKey.split('|')").length).toBe(1)
    expect(findDelimiterSplits('const [a, b] = group.materialKey.split("|")').length).toBe(1)
  })

  it('🔴 把机读权限码当文案 ⇒ 判红', () => {
    expect(findPermissionCodeAsCopy('toast.error(requiredPermission)').length).toBe(1)
    expect(findPermissionCodeAsCopy('setHint(\u0060当前账号缺少权限：${requiredPermission}\u0060)').length).toBe(1)
    expect(findPermissionCodeAsCopy('setError(requiredPermission)').length).toBe(1)
  })

  it('✅ 用服务端下发的展示名 ⇒ 不红', () => {
    expect(findDelimiterSplits('<span>{group.materialLabel}</span>')).toEqual([])
    expect(findPermissionCodeAsCopy('setError("当前账号没有这项权限，请联系管理员开通")')).toEqual([])
  })

  it('✅ 判定式（`field === "requiredPermission"`）不算「当文案」', () => {
    expect(findPermissionCodeAsCopy("if (item.field === 'requiredPermission') return item.message")).toEqual([])
    expect(findPermissionCodeAsCopy('const requiredPermission = ROUTE_PERMISSION_MAP.find((r) => pathname.startsWith(r.prefix))?.code')).toEqual([])
    expect(findPermissionCodeAsCopy('hasPermission(requiredPermission)')).toEqual([])
  })

  it('✅ 前端自有协议（生产者与消费者都在本仓）⇒ 不红（登记为 benign，见台账理由）', () => {
    const own = "if (!content.startsWith('__PAGE__|')) return content\nconst [, , paramsStr] = content.split('|', 3)"
    expect(findDelimiterSplits(own).length).toBe(1) // 判据确实命中它…
    expect(ledger.ledger['src/components/chat/MessageList.tsx::SS-delimiter-split']?.kind).toBe('benign') // …但台账已登记理由
  })

  it('✅ 注释里的坏形态不判红（对照读数，防守卫被自己的文案喂红）', () => {
    expect(findDelimiterSplits("// materialKey.split('|') 是坏形态\nconst a = 1")).toEqual([])
  })
})

describe('「只改展示」负控：机器消费者逐值不变（issue #6668 盲区②）', () => {
  const pool = readFileSync(join(SRC, 'app/(dashboard)/production/pool/page.tsx'), 'utf-8')

  it('`materialKey` 仍是 React `key` 的承载面（展示分离不得动它）', () => {
    expect(pool).toContain('key={group.materialKey}')
  })

  it('展示文本走服务端下发的 `materialLabel`，不退回 `materialKey`', () => {
    expect(pool).toMatch(/\{group\.materialLabel\}/)
    expect(pool, '展示位退回机器键 ⇒ 内部标识上屏（#6523 复发）').not.toMatch(/>\s*\{group\.materialKey\}\s*</)
  })

  it('服务端 DTO 仍同时下发标识与展示名（分离的契约面不退化）', () => {
    const types = readFileSync(join(SRC, 'types/index.ts'), 'utf-8')
    const block = types.slice(types.indexOf('export interface PoolGroup'), types.indexOf('export interface PoolGroup') + 1400)
    expect(block, 'PoolGroup 缺 materialKey（机器键）').toMatch(/materialKey:\s*string/)
    expect(block, 'PoolGroup 缺 materialLabel（展示名）⇒ 展示名与标识没有分离（#6523 复发）').toMatch(/materialLabel:\s*string/)
  })

  it('负控自身有判别力：把展示位换回 `materialKey` ⇒ 上面两条判红（内存注入）', () => {
    const injected = pool.replace('{group.materialLabel}', '{group.materialKey}')
    expect(injected).not.toMatch(/\{group\.materialLabel\}/)
    expect(injected).toMatch(/>\s*\{group\.materialKey\}\s*</)
  })
})
