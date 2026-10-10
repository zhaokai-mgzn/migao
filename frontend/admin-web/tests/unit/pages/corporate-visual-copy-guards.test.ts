// case_ids: UI-082
//
// 类级判据：**官网对外面的设计口径与称谓必须单一真值源**（issue #6665 第 5 / 6 / 7 条）。
//
// 病根（2026-10-10 审计现取）：
//   ① **中文小标签套 `uppercase`**：`uppercase tracking-[0.18em]` 作用在中文上完全无效
//      （`uppercase` 只改拉丁字母），只把汉字段落**拉宽**；同仓 `globals.css` 已有 `.section-kicker` 可复用。
//   ② **金色四处硬编码**：三份官网页面 + 组件里散着 `#f6d27a` / `#e8b04b` / `#d48806` / `#FFC53D`，
//      而 `tailwind.config.ts` 另有 `chart.gold` —— 四个金各写各的，改一处必然漂移。
//   ③ **敬语你/您混用**：官网对外统一「您」（产品内文案口径不受影响）。
//
// 三条都做成**扫源码**的类级判据（新增页面自动进面），并各带判别力自证。
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync, existsSync } from 'fs'
import { join, relative } from 'path'

/** 官网对外面（首页/关于/服务/联系 + 官网共用组件 + Logo）。 */
const SURFACE_DIRS = [
  join(process.cwd(), 'src/app/(corporate)'),
  join(process.cwd(), 'src/components/corporate'),
]
const LOGO = join(process.cwd(), 'src/components/ui/Logo.tsx')
const CONFIG = join(process.cwd(), 'tailwind.config.ts')

/** 递归收集对外面的 `.tsx` / `.ts` 源文件（相对包根）。 */
function surfaceFiles(dir: string, acc: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name)
    if (statSync(full).isDirectory()) surfaceFiles(full, acc)
    else if (/\.tsx?$/.test(name)) acc.push(relative(process.cwd(), full))
  }
  return acc.sort()
}

function read(rel: string): string {
  return readFileSync(join(process.cwd(), rel), 'utf-8')
}

/** 判据源：只扫「真实代码行」（注释行不算 —— 本文件自己的说明里必然出现这些串）。 */
function codeLines(src: string): string[] {
  return src
    .split(/\r?\n/)
    .filter((l) => !/^\s*(\/\/|\/\*|\*)/.test(l))
}

const SURFACE = surfaceFiles(SURFACE_DIRS[0]).concat(surfaceFiles(SURFACE_DIRS[1]))

describe('官网对外面：金色单一源 / 中文小标签 / 敬语（issue #6665）', () => {
  it('面自证：官网对外面的源码文件都在面内（空集或漏项会让下面三条变成空跑）', () => {
    expect(SURFACE.length, `对外面只找到 ${SURFACE.length} 个源文件 —— 判据坐标失效`).toBeGreaterThanOrEqual(5)
    for (const expected of [
      'src/app/(corporate)/page.tsx',
      'src/app/(corporate)/contact/page.tsx',
      'src/components/corporate/CorporateSection.tsx',
    ]) {
      expect(SURFACE, `面内缺 ${expected}`).toContain(expected)
    }
  })

  it('金色只在一处定义（tailwind.config.ts 的 gold 调色板读 brand-palette 真值源），对外面不得再写死', () => {
    // 判据源 = brand-palette 的金色值（本判据不另立第二份真值）
    const paletteSrc = readFileSync(join(process.cwd(), 'src/lib/brand-palette.ts'), 'utf-8')
    const importedGold = [...paletteSrc.matchAll(/'(#[0-9a-fA-F]{6})'/g)].map((m) => m[1].toLowerCase())
    expect(
      importedGold.sort(),
      `brand-palette 漏了金色阶（现取 ${importedGold.join(', ')}）`,
    ).toEqual(['#d48806', '#e8b04b', '#f6d27a', '#ffc53d'].sort())

    // tailwind.config.ts 只接调色板，不再抄第二份 hex
    const configSrc = readFileSync(CONFIG, 'utf-8')
    expect(configSrc, 'tailwind.config.ts 未接入 brand-palette 的 gold').toMatch(
      /import\s*\{\s*gold\s*\}\s*from\s*['"]\.\/src\/lib\/brand-palette['"]/,
    )
    expect(
      [...configSrc.matchAll(/'(#(?:f6d27a|e8b04b|d48806|ffc53d))'/gi)].map((m) => m[1]),
      'tailwind.config.ts 里又抄了一份金色 hex（应由 brand-palette 提供）',
    ).toEqual([])

    const offenders: string[] = []
    for (const rel of SURFACE) {
      const src = read(rel)
      for (const line of codeLines(src)) {
        const hit = line.match(/#(?:f6d27a|e8b04b|d48806|ffc53d|b8933d)\b/i)
        if (hit) offenders.push(`${rel}: ${hit[0]}`)
      }
    }
    expect(
      offenders,
      `官网对外面写死了金色 hex（改一处必然漂移）：${offenders.join(' ｜ ')}。` +
        `修法：金色只留在 src/lib/brand-palette.ts，页面用 token 类（bg-gold-600 / text-gold-500 等）。`,
    ).toEqual([])
  })

  it('Logo 的金色渐变也取自同一 token（不再是第四个金）', () => {
    const src = codeLines(read(relative(process.cwd(), LOGO))).join('\n')
    const hardcoded = [...src.matchAll(/#(?:f6d27a|e8b04b|d48806|ffc53d|b8933d)\b/gi)].map((m) => m[0])
    expect(
      hardcoded,
      `Logo.tsx 仍写死金色 hex：${hardcoded.join(', ')}（应 import tailwind.config.ts 的同一 token）`,
    ).toEqual([])
  })

  it('中文小标签不得套 uppercase（只拉宽汉字，不产生任何字形效果）', () => {
    const offenders: string[] = []
    for (const rel of SURFACE) {
      for (const line of codeLines(read(rel))) {
        if (/uppercase/.test(line) && /tracking-\[/.test(line)) offenders.push(rel)
      }
    }
    expect(
      offenders,
      `这些文件的中文小标签套了 uppercase + 自定义字距：${[...new Set(offenders)].join(', ')}。` +
        `\`uppercase\` 对汉字零作用，只把段落拉宽 —— 官网小标签复用已有的 .corporate-kicker（同 globals.css 的 .section-kicker 口径）。`,
    ).toEqual([])
  })

  it('官网对外统一敬语「您」（不得出现「你」）', () => {
    const offenders: string[] = []
    for (const rel of SURFACE) {
      for (const line of codeLines(read(rel))) {
        if (/[你妳祢]/.test(line)) offenders.push(`${rel}: ${line.trim().slice(0, 60)}`)
      }
    }
    expect(
      offenders,
      `官网对外面出现「你」：\n${offenders.join('\n')}\n` +
        `用户裁定：官网对外统一「您」（产品内界面（dashboard 等）不在本判据射程内）。`,
    ).toEqual([])
  })

  it('判别力自证：三条检测器对注入样本各自判红、对合规样本不报（否则是空断言）', () => {
    expect(codeLines('const c = "text-[#e8b04b]"').some((l) => /#(?:f6d27a|e8b04b|d48806|ffc53d|b8933d)\b/i.test(l))).toBe(true)
    expect(codeLines('// 注释里提到 #e8b04b 不算').some((l) => l.includes('#e8b04b'))).toBe(false)
    expect(codeLines('<span className="text-[11px] font-semibold uppercase tracking-[0.18em]">你好</span>').some((l) => /uppercase/.test(l) && /tracking-\[/.test(l))).toBe(true)
    expect(codeLines('<span className="text-[11px] font-semibold tracking-[0.14em]">你好</span>').some((l) => /uppercase/.test(l) && /tracking-\[/.test(l))).toBe(false)
    expect(codeLines('请在留言中说明您的情况').some((l) => /[你妳祢]/.test(l))).toBe(false)
    expect(codeLines('我们会在工作时间内回复你').some((l) => /[你妳祢]/.test(l))).toBe(true)
  })

  it('前提自证：globals.css 确实提供了官网小标签可复用的类比（不是凭空的"复用"）', () => {
    const css = readFileSync(join(process.cwd(), 'src/app/globals.css'), 'utf-8')
    expect(css, 'globals.css 里没有 .section-kicker —— 复用的前提不成立').toContain('.section-kicker')
    expect(existsSync(CONFIG), 'tailwind.config.ts 不在预期位置').toBe(true)
  })
})
