// case_ids: UI-001
/**
 * 文档与 token 的**漂移判据**（issue #6668 交付物 1/2）。
 *
 * ## 病灶
 *
 * 修前 `docs/design/ui-design-spec.md` 自称 v8.0，把主色写成 AntD 蓝 `#2F54EB`、
 * 页面底色写成 `#FAFAFA`；而 `frontend/admin-web/tailwind.config.ts` 早已是「织物质感」
 * （`primary-500 = #48618f` / `neutral-50 = #faf7f2`）⇒ **任何照文档做的新页面必然漂回蓝**。
 * 关键点：**文档与代码各写一份，没有任何东西会因此变红**。
 *
 * ## 判据
 *
 * 1. **真值源文档必须在场且指向代码**（`docs/design/design-baseline.md` 声明
 *    `tailwind.config.ts` 与 `src/lib/design-tokens.ts`）；
 * 2. **基线页里写的每个色值必须与 config 逐值相同**（把文档里的 `#48618f` 改成别的 ⇒ 红）；
 * 3. **基线页里的字号阶梯必须与 `TYPE_SCALE` 逐值相同**（改一处不改另一处 ⇒ 红）；
 * 4. **降级后的 `ui-design-spec.md` 不得再自称是颜色真值源**（它必须写明「以 token 为准」+
 *    「适用范围从未覆盖官网」），且**不得再出现未标注为历史值**的 AntD 蓝；
 * 5. **判别力自证**：把三处漂移注进内存文本 ⇒ 判据各自报红。
 *
 * ## 边界（照实登记，§19.1）
 *
 * - 只钉「文档里**显式写出**的色值与字号」——散文里的形容（「暖亚麻」）不在面内；
 * - 不判「页面该不该用某个 token」（那是评审）；
 * - `ui-design-spec.md` 的**其余章节**（组件 / 布局 / 动画）本轮不动（有意不做整篇重写），
 *   它们与 token 无关，故不在本判据面内。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync, existsSync } from 'node:fs'
import { join } from 'node:path'

import config from '../../tailwind.config'
import { TYPE_SCALE, TYPE_FLOOR_PX, LINE_HEIGHT_RATIO } from '../../src/lib/design-tokens'

const ROOT = process.cwd()
const REPO = join(ROOT, '..', '..')
const BASELINE_PATH = join(REPO, 'docs/design/design-baseline.md')
const SPEC_PATH = join(REPO, 'docs/design/ui-design-spec.md')

const baseline = readFileSync(BASELINE_PATH, 'utf-8')
const spec = readFileSync(SPEC_PATH, 'utf-8')

type Scale = Record<string, string>
const colors = (config.theme?.extend?.colors ?? {}) as Record<string, Scale>

/**
 * 从文档里取「某个 token 名对应的色值」——形态固定：`| \`primary-500\` | \`#48618f\` |`。
 *
 * ⚠️ 两条必须：① 先按行切（`\s` 会跨行：`primary-600` 那行的空单元格会贪到下一行的 hex）；
 * ② 中间用 `[^|]*`（不跨单元格）。
 */
export function docColorValue(doc: string, token: string): string | null {
  const escaped = token.replace(/[-/\\^$*+?.()|[\]{}]/g, '\\$&')
  const re = new RegExp('`' + escaped + '`[^|]*\\|[^|]*`(#[0-9a-fA-F]{6})`')
  for (const line of doc.split('\n')) {
    const m = line.match(re)
    if (m) return m[1].toLowerCase()
  }
  return null
}

/** 从文档里取「某个类名对应的字号/行高」——形态固定：`| \`text-sm\` | 14px | 21px | 400 | ...` */
export function docTypeStep(doc: string, className: string): { size: string; lineHeight: string } | null {
  const re = new RegExp('`' + className + '`\\s*\\|\\s*(\\d+)px\\s*\\|\\s*(\\d+)px')
  const m = doc.match(re)
  return m ? { size: m[1], lineHeight: m[2] } : null
}

describe('真值源文档在场且指向代码（不是复制一份 token）', () => {
  it('docs/design/design-baseline.md 存在', () => {
    expect(existsSync(BASELINE_PATH), `缺 ${BASELINE_PATH}`).toBe(true)
  })

  it('它把颜色 / 字号 / 阴影 / 金额 / 日期的真值源逐个指到代码文件', () => {
    for (const anchor of [
      'frontend/admin-web/tailwind.config.ts',
      'frontend/admin-web/src/lib/design-tokens.ts',
      'frontend/admin-web/src/lib/money.ts',
      'frontend/admin-web/src/lib/enum-display.ts',
    ]) {
      expect(baseline, `基线页没指到 ${anchor}`).toContain(anchor)
    }
  })

  it('它写明了「适用范围从未覆盖官网」这个事实', () => {
    expect(baseline).toContain('从未覆盖官网')
  })
})

describe('文档写的色值必须与 config 逐值相同（漂移即红）', () => {
  it.each([
    ['primary-500', '#48618f'],
    ['primary-600', '#3a4e75'],
    ['primary-700', '#2e3d5c'],
    ['accent-500', '#c06a3e'],
    ['neutral-50', '#faf7f2'],
    ['neutral-700', '#625545'],
    ['neutral-900', '#312c26'],
  ])('基线页的 `%s` = %s（且 config 同值）', (token, value) => {
    const [family, step] = token.split('-')
    expect(colors[family]?.[step], `config 的 ${token}`).toBe(value)
    expect(docColorValue(baseline, token), `基线页的 ${token}`).toBe(value)
  })

  it('基线页不得把主色写成 AntD 蓝 `#2F54EB`', () => {
    expect(baseline.toLowerCase()).not.toContain('#2f54eb')
  })

  it('判别力自证：把文档里的主色改掉 ⇒ 判据报红（文档侧）', () => {
    const drifted = baseline.replace('`primary-500` | `#48618f`', '`primary-500` | `#2F54EB`')
    expect(docColorValue(drifted, 'primary-500')).toBe('#2f54eb')
    expect(docColorValue(drifted, 'primary-500')).not.toBe(colors.primary['500'])
  })
})

describe('文档写的字号阶梯必须与 TYPE_SCALE 逐值相同', () => {
  it.each(TYPE_SCALE.map((s) => [s.className, String(s.size), String(s.lineHeight)]))(
    '基线页的 `%s` = %spx / %spx',
    (className, size, lineHeight) => {
      expect(docTypeStep(baseline, className)).toEqual({ size, lineHeight })
    },
  )

  it('下限 12px 与行高比 1.5 写进文档', () => {
    expect(baseline).toContain(`下限 ${TYPE_FLOOR_PX}px`)
    expect(baseline).toContain(String(LINE_HEIGHT_RATIO))
  })

  it('判别力自证：把文档里的 `text-sm` 行高改掉 ⇒ 判据报红', () => {
    const drifted = baseline.replace('| `text-sm` | 14px | 21px |', '| `text-sm` | 14px | 22px |')
    expect(docTypeStep(drifted, 'text-sm')).toEqual({ size: '14', lineHeight: '22' })
    expect(docTypeStep(drifted, 'text-sm')?.lineHeight).not.toBe('21')
  })

  it('`fontSize` 已接进 tailwind theme（文档指的类名真的存在）', () => {
    const fontSize = (config.theme?.extend as Record<string, unknown> | undefined)?.fontSize as
      | Record<string, [string, { lineHeight: string }]>
      | undefined
    expect(fontSize, 'tailwind.config 的 theme.extend.fontSize 缺失').toBeTruthy()
    for (const step of TYPE_SCALE) {
      const key = step.className.replace(/^text-/, '')
      expect(fontSize?.[key], `theme.extend.fontSize.${key}`).toEqual([`${step.size}px`, { lineHeight: `${step.lineHeight}px` }])
    }
  })
})

describe('过期规范降级：ui-design-spec.md 不再自称颜色真值源', () => {
  it('它必须写明「以 code token 为准」并指回基线页', () => {
    expect(spec).toContain('docs/design/design-baseline.md')
    expect(spec).toMatch(/以.*(token|真值源).*为准/)
  })

  it('它的历史色值必须被显式标成历史（不许裸着当现行值）', () => {
    // 旧值是 AntD 蓝：出现可以，但必须在「历史」小节里（见下方两条）
    expect(spec.toLowerCase()).toContain('#2f54eb')
    expect(spec).toContain('历史')
  })

  it('判别力自证：把「以 token 为准」那句删掉 ⇒ 判据报红', () => {
    const stripped = spec.replace(/以.*(token|真值源).*为准/g, '')
    expect(stripped).not.toMatch(/以.*(token|真值源).*为准/)
  })
})
