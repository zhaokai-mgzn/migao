// case_ids: UI-001
/**
 * 字号真值源 `frontend/admin-web/src/lib/design-tokens.ts` 的**实例判据**（issue #6668）。
 *
 * ## 为什么单独一条
 *
 * 这个文件是**设计基线的字号真值源**（阶梯 = `TYPE_SCALE`）—— 它的价值**只在「有人照它做」**时成立：
 * ① 它必须真的**接进** `tailwind.config.ts` 的 `theme.extend.fontSize`（否则页面写 `text-sm` 拿不到
 * 本仓口径的 14/21，文档指过来就是死指针）；② 它必须与基线页 `docs/design/design-baseline.md`
 * **逐值一致**（文档与真值源一漂移就红 —— 这正是修前 `ui-design-spec.md` 说 `#2F54EB` 而代码是
 * `#48618f` 却没有人变红的同族病）；③ 它必须与**过期规范**的旧口径**不同**（不许悄悄回退）。
 *
 * ⇒ 本文件判的是「**真值源成立**」而不是「文件存在」：三条里任一条漂移都会红，
 * 且每条都给了**注入式红证**（把坏形态注进内存 ⇒ 判据自己也判红）。
 *
 * ## 边界（照实登记，§19.1）
 *
 * - 不判「某个标题该用哪一级」（那是评审 + 读图，见 `docs/design/design-baseline.md` §10）；
 * - 不判视觉呈现（jsdom 不做布局）；
 * - 与 `frontend/admin-web/tests/unit/design-baseline-token-contract.test.ts` 的分工：
 *   **那条**判「文档 ↔ config ↔ TYPE_SCALE」三方一致（跨文件漂移）；
 *   **本条**判「真值源自身成立」—— 阶梯的**内部不变量**（下限 / 行高比 / 唯一性 / 消费面）。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'

import config from '../../../tailwind.config'
import { fontSize, LINE_HEIGHT_RATIO, TYPE_FLOOR_PX, TYPE_SCALE } from '@/lib/design-tokens'

const ROOT = process.cwd()
const REPO = join(ROOT, '..', '..')
const SRC = join(ROOT, 'src')

/**
 * 🔴 **冻结上界（只许缩短）**：`src/` 下用任意值字号（`text-[13px]` 一族）的**文件数**。
 * 现取读数 = 44（2026-10-10，`node_modules` 之外的全部非测试源文件）。
 * 它是**存量**（多为打印/纸面与小标签的历史写法），本单**不改业务文件** ⇒ 记上界而非清零；
 * 新增一处即红。下调 = 真的改掉了一处（或若干处），须同步改这个数。
 */
const FROZEN_ARBITRARY_FONT_SIZE_FILES = 44

const themeFontSize = (config.theme?.extend as Record<string, unknown> | undefined)?.fontSize as
  | Record<string, [string, { lineHeight: string }]>
  | undefined

/** 判据体裁（纯函数，可内存注入取证）：阶梯内部不变量 → 违规条目清单 */
export function scaleViolations(
  scale: ReadonlyArray<{ className: string; size: number; lineHeight: number }>,
  floor = TYPE_FLOOR_PX,
  ratio = LINE_HEIGHT_RATIO,
): string[] {
  const bad: string[] = []
  for (const s of scale) {
    if (s.size < floor) bad.push(`${s.className}: 字号 ${s.size} < 下限 ${floor}`)
    if (Math.abs(s.lineHeight / s.size - ratio) > 1e-9) {
      bad.push(`${s.className}: 行高比 ${s.lineHeight}/${s.size} ≠ ${ratio}`)
    }
    if (!/^text-(xs|sm|base|lg|xl|2xl|3xl)$/.test(s.className)) bad.push(`${s.className}: 不是标准 Tailwind 字号类名`)
  }
  const dup = scale.map((s) => s.className).filter((c, i, a) => a.indexOf(c) !== i)
  if (dup.length > 0) bad.push(`类名重复：${[...new Set(dup)].join(', ')}`)
  const sizes = scale.map((s) => s.size)
  if (new Set(sizes).size !== sizes.length) bad.push('字号值重复（同一级两个类名 ⇒ 两个口径）')
  if (scale.length > 0 && !scale.some((s) => s.size === floor)) bad.push(`阶梯里没有下限档 ${floor}px`)
  return bad
}

describe('字号真值源自身成立（实例判据，issue #6668）', () => {
  it('① 阶梯内部不变量：每档 ≥ 下限、行高比恒 1.5、类名标准、无重复', () => {
    expect(scaleViolations(TYPE_SCALE)).toEqual([])
  })

  it('② 真值源**真的被消费**：`theme.extend.fontSize` 与 `TYPE_SCALE` 逐项同值', () => {
    expect(themeFontSize, 'tailwind.config 的 theme.extend.fontSize 缺失 ⇒ 文档指的是死指针').toBeTruthy()
    for (const step of TYPE_SCALE) {
      const key = step.className.replace(/^text-/, '')
      expect(themeFontSize?.[key], `fontSize.${key}`).toEqual([
        `${step.size}px`,
        { lineHeight: `${step.lineHeight}px` },
      ])
    }
    // 反向：config 里不许有阶梯之外的档次（两处各写一份必然漂移）
    expect(Object.keys(themeFontSize ?? {}).sort()).toEqual(
      TYPE_SCALE.map((s) => s.className.replace(/^text-/, '')).sort(),
    )
  })

  it('③ 与基线页逐值一致（文档漂移 ⇒ 红）', () => {
    const baseline = readFileSync(join(REPO, 'docs/design/design-baseline.md'), 'utf-8')
    for (const step of TYPE_SCALE) {
      const re = new RegExp('`' + step.className + '`\\s*\\|\\s*(\\d+)px\\s*\\|\\s*(\\d+)px')
      const m = baseline.match(re)
      expect(m, `基线页缺 ${step.className} 那一行`).toBeTruthy()
      expect([m?.[1], m?.[2]], `${step.className} 在基线页里的值`).toEqual([String(step.size), String(step.lineHeight)])
    }
  })

  it('④ 与**过期规范**的旧口径不同（不许悄悄回退到 AntD 阶梯）', () => {
    const spec = readFileSync(join(REPO, 'docs/design/ui-design-spec.md'), 'utf-8')
    // 旧阶梯的 11px 角标（Caption-XS）已作废 ⇒ 真值源不得再有 11 这一档
    expect(TYPE_SCALE.some((s) => s.size === 11), '真值源里出现 11px 档 = 回退到旧阶梯').toBe(false)
    // 旧规范若仍写 11px，必须只出现在被显式标成历史的语境里（本判据只保证真值源侧不退回）
    expect(spec.includes('Caption-XS')).toBe(false)
  })

  it('⑤ 消费面：任意值字号（绕过真值源）只许缩短，且扫描面自证活着', () => {
    const files: string[] = []
    const walk = (dir: string): void => {
      for (const e of readdirSync(dir, { withFileTypes: true })) {
        if (['node_modules', '.next', 'dist', 'coverage'].includes(e.name)) continue
        const p = join(dir, e.name)
        if (e.isDirectory()) walk(p)
        else if (/\.(tsx?)$/.test(e.name) && !/\.(test|spec)\.tsx?$/.test(e.name)) files.push(p)
      }
    }
    walk(SRC)
    expect(files.length, 'src 下应有大量源文件').toBeGreaterThanOrEqual(150)
    // `text-[13px]` 一族绕过字号阶梯 —— 它是**存量**（现取读数，冻结上界），只许缩短；
    // 新增一处即红（要么用阶梯里的类名，要么下调本上界并在 PR body 说明）。
    const arbitrary = files.filter((f) => /text-\[\d+px\]/.test(readFileSync(f, 'utf-8')))
    expect(
      arbitrary.length,
      `任意值字号的文件数 ${arbitrary.length} > 冻结上界 ${FROZEN_ARBITRARY_FONT_SIZE_FILES}（新增即红）`,
    ).toBeLessThanOrEqual(FROZEN_ARBITRARY_FONT_SIZE_FILES)
  })
})

describe('判别力自证（注入式）：坏形态各自判红', () => {
  it('🔴 低于下限的字号 ⇒ 红', () => {
    expect(scaleViolations([{ className: 'text-xs', size: 11, lineHeight: 16.5 }])).toContain('text-xs: 字号 11 < 下限 12')
  })

  it('🔴 行高比不是 1.5 ⇒ 红', () => {
    expect(scaleViolations([{ className: 'text-sm', size: 14, lineHeight: 22 }])[0]).toContain('行高比 22/14 ≠ 1.5')
  })

  it('🔴 非标准类名（任意值绕道）⇒ 红', () => {
    expect(scaleViolations([{ className: 'text-[13px]', size: 13, lineHeight: 19.5 }])[0]).toContain('不是标准 Tailwind 字号类名')
  })

  it('🔴 同一级两个类名（口径分叉）⇒ 红', () => {
    const bad = [
      { className: 'text-sm', size: 14, lineHeight: 21 },
      { className: 'text-sm', size: 13, lineHeight: 19.5 },
    ]
    expect(scaleViolations(bad).join('\n')).toContain('类名重复')
  })

  it('🔴 阶梯里没有下限档 ⇒ 红', () => {
    expect(scaleViolations([{ className: 'text-sm', size: 14, lineHeight: 21 }])).toContain('阶梯里没有下限档 12px')
  })

  it('✅ 好形态（现行阶梯）⇒ 不红（对照读数）', () => {
    expect(scaleViolations(TYPE_SCALE)).toEqual([])
  })
})
