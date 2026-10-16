// case_ids: UI-111
/**
 * 类级元守卫（issue #7065 的根因②）：**内层白卡必须有 `shadow-card`**。
 *
 * ## 病灶（用户原话 → 可归因读数）
 *
 * 用户 2026-10-16：「只有订单管理的设计精美，其它页面没有这种感觉」。
 * `#7007` 诊断出的三条根因之一 = **层级不统一**：
 *
 * > 订单页的清透感来自「**整页卡片(阴影) → 内层卡片(边框)**」这套层级；
 * > 缺阴影的页退化成「**一圈边框套一圈边框**」。
 *
 * `app/(dashboard)/layout.tsx` 已把每页包进 `rounded-2xl border shadow-card`（外壳统一），
 * 差距全在**卡片内部**：内层容器写成 `bg-white rounded-lg border border-neutral-200`
 * 却**不带** `shadow-card` ⇒ 与外壳**视觉权重相同**，两层框线叠在一起。
 *
 * ## 判据
 *
 * 射程内（`src/app/(dashboard)/**` + `src/components/**`）凡形态为
 * `bg-white rounded-{lg,xl,2xl} border border-neutral-200` 的**内层白卡容器**，
 * 同一 `className` 里**必须**出现 `shadow-card`。
 *
 * ⚠️ **匹配的是 `className` 里的三件事同时成立**（白底 + 圆角 + 中性边框），
 * **不是**「凡是带 border 的都要加阴影」—— 表格内分隔线、输入框边框、Tab 栏下划线都**不是**白卡容器。
 *
 * ## 与「边框套边框」相反的方向（照实登记边界）
 *
 * 本判据**不**判「阴影是不是太多了」。反过来堆阴影（每层都加）同样会破坏层级 ——
 * 那属于评审面（§15.7 读图 + §31 产品设计原则），判不了形态。
 * 本判据只钉住**文档已明确的那一侧**：白卡容器不得缺 `shadow-card`。
 */

import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative, sep } from 'node:path'
import { describe, expect, it } from 'vitest'

const SRC = 'src'
const SCAN_DIRS = [join(SRC, 'app', '(dashboard)'), join(SRC, 'components')]

/** 内层白卡容器的形态指纹：白底 + 圆角 + 中性边框（三件事同时成立）。 */
export const INNER_CARD_RE = /bg-white rounded-(?:lg|xl|2xl) border border-neutral-200/
/** 该形态必须具备的层级信号。 */
export const LAYER_TOKEN = 'shadow-card'

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) walk(p, out)
    else if (p.endsWith('.tsx')) out.push(p)
  }
  return out
}

/** 射程内所有 `.tsx` 文件（相对仓库根的路径）。 */
export function scanFiles(): string[] {
  const found: string[] = []
  for (const d of SCAN_DIRS) {
    for (const p of walk(d)) found.push(relative(process.cwd(), p).split(sep).join('/'))
  }
  return found.sort()
}

/** → 缺 `shadow-card` 的内层白卡容器（`文件:行号` 形态，便于判红时直接点名）。 */
export function innerCardsMissingShadow(files: string[] = scanFiles()): string[] {
  const bad: string[] = []
  for (const rel of files) {
    const lines = readFileSync(rel, 'utf8').split('\n')
    lines.forEach((line, idx) => {
      if (INNER_CARD_RE.test(line) && !line.includes(LAYER_TOKEN)) {
        bad.push(`${rel}:${idx + 1}`)
      }
    })
  }
  return bad
}

describe('判据 1：内层白卡容器必须带 shadow-card（否则「边框套边框」）', () => {
  it('射程内没有「白底 + 圆角 + 中性边框」却缺 shadow-card 的容器', () => {
    const files = scanFiles()
    expect(files.length).toBeGreaterThan(40) // 反空跑：射程塌了要出声
    const bad = innerCardsMissingShadow(files)
    expect(
      bad,
      `这些内层白卡容器缺 shadow-card ⇒ 与整页外壳视觉权重相同（「一圈边框套一圈边框」，issue #7007 根因②）：\n  ` +
        `${bad.join('\n  ')}\n统一改用 frontend/admin-web/src/components/ui/PageCard.tsx（它自带 shadow-card），` +
        `或就地补上 shadow-card（token 定义在 tailwind.config.ts 的 boxShadow.card）。`,
    ).toEqual([])
  })
})

describe('判据 2：反作弊 —— 射程内确实有这种容器，且确实都在用该 token', () => {
  it('射程里存在足量白卡容器（否则判据 1 是空转）', () => {
    const files = scanFiles()
    let total = 0
    for (const rel of files) {
      for (const line of readFileSync(rel, 'utf8').split('\n')) {
        if (INNER_CARD_RE.test(line)) total += 1
      }
    }
    // 现取读数：22 处。给一个下界，防止「把 className 改写成别的形态」来绕过判据 1。
    expect(total).toBeGreaterThanOrEqual(15)
  })

  it('shadow-card 这个 token 真的被定义（不是写了个不存在的类）', () => {
    const cfg = readFileSync('tailwind.config.ts', 'utf8')
    expect(cfg).toContain('card:')
    expect(cfg.replace(/\s+/g, '')).toMatch(/card:'0/)
  })
})

describe('判别力自证', () => {
  it('坏形态判红、好形态放行（纯函数级）', () => {
    expect(INNER_CARD_RE.test('<div className="bg-white rounded-lg border border-neutral-200 p-5">')).toBe(true)
    expect(INNER_CARD_RE.test('<div className="bg-white rounded-lg border border-neutral-200 shadow-card p-5">')).toBe(true)
    // 好形态：有 shadow-card ⇒ 判据只筛「形态命中且缺 token」
    const good = '<div className="bg-white rounded-lg border border-neutral-200 shadow-card p-5">'
    expect(INNER_CARD_RE.test(good) && !good.includes(LAYER_TOKEN)).toBe(false)
    // 不是白卡容器的东西**不该**被命中
    expect(INNER_CARD_RE.test('<div className="divide-y divide-neutral-200">')).toBe(false)
    expect(INNER_CARD_RE.test('<input className="rounded-md border border-neutral-300" />')).toBe(false)
    expect(INNER_CARD_RE.test('<div className="border-b border-neutral-200" />')).toBe(false)
  })
})
