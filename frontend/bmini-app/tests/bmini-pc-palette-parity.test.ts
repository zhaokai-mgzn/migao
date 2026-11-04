// case_ids: BM-034
/**
 * 类级守卫：**bmini 小程序的配色必须来自 PC 端 admin-web 的同一份调色板**（issue #8600）。
 *
 * ## 用户逐字（2026-11-04）
 *
 * 「我们当前移动端的整体样式没有和 pc 端的 UI 风格统一，需要统一」
 *
 * ## 病灶
 *
 * PC 端是「织物质感」（primary 靛蓝 / neutral 米白 / accent 陶土 / 暖阴影），
 * 而 bmini 自持一套「深蓝金」：`#0A2540` navy + `#1A73E8` 亮蓝 + `#C8A24B` 金铜 + 冷灰
 * `#F5F7FA` / `#EAEEF3` / `#9CA3AF`。同一个产品在电脑上和在手机上是两张脸。
 *
 * ## 判据（每条都能红）
 *
 * | # | 判据 | 怎么红 |
 * |---|---|---|
 * | 1 | `variables.scss` 每个语义 token 逐值等于 PC 调色板对应阶 | PC 改一阶这里没跟上 / 这里自创近似色 ⇒ 红 |
 * | 2 | 全部 `src/**\/*.{scss,ts,tsx}`（跳过注释）里的 hex **只能是 PC 调色板/语义色白名单** | 回填任一冷灰/深蓝金/一次性近似色 ⇒ 红并具名 |
 * | 3 | 冷色阴影 `rgba(10,37,64,…)` / `rgba(26,115,232,…)` 一个不留 | 回填冷色阴影 ⇒ 红 |
 * | 4 | 判别力自证（内存变异）：改一阶 / 塞回旧 hex ⇒ 各自判红 | 守卫退化成恒真 ⇒ 红 |
 *
 * 边界：判据只管「取的色是不是同一份」，判不了好不好看（观感靠截图读图）。
 */
import fs from 'fs'
import path from 'path'

const ROOT = path.resolve(__dirname, '..')
const VARS_REL = 'src/styles/variables.scss'
const TAILWIND_REL = '../admin-web/tailwind.config.ts'

const stripComments = (s: string) =>
  s.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/[^\n]*/g, '')

/** 从 admin-web tailwind.config.ts 取一组色阶（`primary: { 50: '#…', … }`）。取不到 ⇒ 抛错。 */
export function scaleOf(tailwindSrc: string, name: string): Record<string, string> {
  const body = new RegExp(`\\b${name}:\\s*\\{([\\s\\S]*?)\\}`).exec(tailwindSrc)
  if (!body) throw new Error(`admin-web tailwind 取不到色阶 ${name}（真值源变了，先修取值）`)
  const scale: Record<string, string> = {}
  for (const m of body[1].matchAll(/(\d+):\s*'(#[0-9a-fA-F]{6})'/g)) scale[m[1]] = m[2].toLowerCase()
  if (Object.keys(scale).length < 5) throw new Error(`色阶 ${name} 解析失败`)
  return scale
}

/** variables.scss 的 `$name: value;` → map。 */
export function scssVars(src: string): Record<string, string> {
  const out: Record<string, string> = {}
  for (const m of stripComments(src).matchAll(/\$([a-z0-9-]+)\s*:\s*([^;]+);/g)) {
    out[m[1]] = m[2].trim().toLowerCase()
  }
  return out
}

function allFiles(dir: string, exts: string[], acc: string[] = []): string[] {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, entry.name)
    if (entry.isDirectory()) allFiles(p, exts, acc)
    else if (exts.some((e) => entry.name.endsWith(e))) acc.push(p)
  }
  return acc
}

const VARS_SRC = fs.readFileSync(path.join(ROOT, VARS_REL), 'utf-8')
const TAILWIND_SRC = fs.readFileSync(path.join(ROOT, TAILWIND_REL), 'utf-8')
const VARS = scssVars(VARS_SRC)
const PRIMARY = scaleOf(TAILWIND_SRC, 'primary')
const NEUTRAL = scaleOf(TAILWIND_SRC, 'neutral')
const ACCENT = scaleOf(TAILWIND_SRC, 'accent')

/** 语义 token → PC 对应阶（唯一映射表；新增 token 先想清楚它对应 PC 哪一阶）。 */
const PARITY: Record<string, string> = {
  'brand-navy': PRIMARY[900],
  'brand-blue': PRIMARY[600],
  'brand-blue-light': PRIMARY[400],
  'brand-gold': ACCENT[500],
  'brand-gold-light': ACCENT[200],
  'primary-light': PRIMARY[50],
  'text-primary': NEUTRAL[900],
  'text-secondary': NEUTRAL[600],
  'text-tertiary': NEUTRAL[400],
  'bg-secondary': NEUTRAL[50],
  'border-color': NEUTRAL[200],
}

/** hex 白名单 = PC 三组色阶 + 语义色（Tailwind 默认 emerald/red/amber 族）+ 黑白。 */
const ALLOWED = new Set<string>([
  ...Object.values(PRIMARY),
  ...Object.values(NEUTRAL),
  ...Object.values(ACCENT),
  '#ffffff',
  '#000000',
  // 语义状态（PC status-chip 同族）：emerald / red / amber
  '#ecfdf5', '#d1fae5', '#a7f3d0', '#059669', '#047857',
  '#fef2f2', '#fee2e2', '#fecaca', '#dc2626', '#b91c1c',
  '#fffbeb', '#fef3c7', '#fde68a', '#d97706', '#b45309',
])

/** 冷色阴影（旧 navy / 亮蓝的 rgba）—— 一个都不许留。 */
const COLD_SHADOWS = [
  /rgba\(\s*10\s*,\s*37\s*,\s*64/i,
  /rgba\(\s*26\s*,\s*115\s*,\s*232/i,
  /rgba\(\s*47\s*,\s*84\s*,\s*235/i,
]

describe('bmini 配色 = PC 端同一份调色板（issue #8600）', () => {
  it('① 每个语义 token 逐值等于 PC 调色板对应阶', () => {
    const wrong: string[] = []
    for (const [token, expected] of Object.entries(PARITY)) {
      if (!expected) wrong.push(`$ ${token} 映射缺失（判据自身写错）`)
      const actual = VARS[token]
      if (!actual) wrong.push(`$${token} 缺失（应为 ${expected}）`)
      else if (actual !== expected.toLowerCase()) wrong.push(`$${token} = ${actual}，PC = ${expected}`)
    }
    expect(wrong).toEqual([])
  })

  it('② 全部 SCSS 的 hex 只能来自 PC 调色板白名单', () => {
    const offenders: string[] = []
    for (const file of allFiles(path.join(ROOT, 'src'), ['.scss', '.ts', '.tsx'])) {
      const code = stripComments(fs.readFileSync(file, 'utf-8'))
      for (const m of code.matchAll(/#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3})(?![0-9a-fA-F])/g)) {
        const hex = m[0].toLowerCase()
        if (!ALLOWED.has(hex)) offenders.push(`${path.relative(ROOT, file)}: ${hex}`)
      }
    }
    expect(offenders).toEqual([])
  })

  it('③ 冷色阴影一个不留', () => {
    const offenders: string[] = []
    for (const file of allFiles(path.join(ROOT, 'src'), ['.scss', '.ts', '.tsx'])) {
      const code = stripComments(fs.readFileSync(file, 'utf-8'))
      for (const re of COLD_SHADOWS) if (re.test(code)) offenders.push(`${path.relative(ROOT, file)}: ${re}`)
    }
    expect(offenders).toEqual([])
  })

  it('④ 判别力自证：改一阶 / 塞回旧 hex ⇒ 各自判红', () => {
    // 改一阶：把 $brand-blue 换成近似色 ⇒ ① 的检测器必须命中
    const mutated = VARS_SRC.replace(/\$brand-blue:\s*#[0-9a-fA-F]{6}/, '$brand-blue: #3a4e76')
    expect(scssVars(mutated)['brand-blue']).not.toBe(PRIMARY[600])
    // 塞回旧 hex ⇒ ② 的检测器必须命中
    const injected = '.x { color: #0a2540 }'
    expect(Array.from(stripComments(injected).matchAll(/#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3})(?![0-9a-fA-F])/g)).map((m) => m[0])).toEqual(['#0a2540'])
    // 注释里的旧 hex 不算
    expect(stripComments('// #0a2540\n.x { color: #faf7f2 }').includes('#0a2540')).toBe(false)
  })
})
