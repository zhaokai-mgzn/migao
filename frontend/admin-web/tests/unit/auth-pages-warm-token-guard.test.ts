// case_ids: UI-057, UI-058
/**
 * 类级元守卫（issue #6663）：**登录 / 注册 / 改密三页必须是全站暖色 token**。
 *
 * ## 病灶
 *
 * 这三页是**客户第一眼**（试用客户拿到的第一条链接就是登录页），而它们一直用 Tailwind
 * **默认蓝**渐变（`from-blue-50 via-white to-indigo-50`）—— 与「织物质感」的暖色 token
 * （`primary #48618f` / `neutral #faf7f2`，见 `tailwind.config.ts`）**不同族**：
 * 打开像是另一个产品，商务感直接掉一档。
 *
 * 为什么不是「只改这三行」：同族页面会**各自重新长回**默认蓝（本仓已多次实证：
 * `check-ui-regression.sh` 就是为「旧 UI 覆盖验收版」立的）。⇒ 判据锚在**页面文件**上，
 * 新增第四张同族页面（比如找回密码）时，它会当场被要求站进暖色 token。
 *
 * ## 判据（三条，全部会红）
 *
 * 1. **不得出现 Tailwind 默认冷色族**（`blue-*` / `indigo-*` / `sky-*` / `violet-*`）——
 *    冷色族是「另一个产品」的来源；全站的暖色是 `primary` / `accent` / `neutral`；
 * 2. **必须有暖色 token**（`primary-*` 或 `accent-*` 或 `neutral-*`）—— 否则「删干净」也能过，
 *    那等于把页面变成没配色的裸 Tailwind；
 * 3. **渐变链不得用 `via-` 中间站**（issue #6663 的第二半）：`via-*` 依赖 Tailwind base 层注入的
 *    `--tw-gradient-via-position`；该变量缺失时整条 `background-image` 会成为**无效值**而
 *    被丢弃 ⇒ **渐变静默不生效**（页面看起来「没上色」，而没有任何东西会报）。
 *    实测（tailwindcss 3.4.19）：`via-white` 只产出 `--tw-gradient-stops`，
 *    `--tw-gradient-from-position` / `--tw-gradient-via-position` 只由 `@tailwind base` 的
 *    preflight 注入 ⇒ 两停渐变不依赖它，**是安全形态**。
 *
 * ## 边界（照实登记，§19.1）
 *
 * - 只判**这三页**（`login` / `register` / `change-password`）—— 官网（`(corporate)`）与
 *   小程序各有自己的一套对外口径，不在本判据射程；
 * - 判的是**源码里的类名字面量**，不是真实渲染像素：「好不好看」仍由 §15.7 读图 + 人裁定；
 *   本判据只保证「**没退回另一个产品的配色**」这一件事；
 * - 「暖色 token」只认**命名空间**（`primary`/`accent`/`neutral`），不判具体色阶对错。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

const ROOT = process.cwd()

/** 这三页 = 客户第一眼（新增同族页面请往这里加 —— 判据会当场要求它站进暖色 token） */
export const AUTH_PAGES = [
  'src/app/login/page.tsx',
  'src/app/register/page.tsx',
  'src/app/change-password/page.tsx',
]

/** Tailwind **默认冷色族**：出现即「另一个产品」（全站暖色是 primary / accent / neutral） */
const COOL_FAMILY = /\b(?:from|via|to|bg|text|border|ring|shadow)-(?:blue|indigo|sky|violet|purple|cyan)-\d{2,3}\b/g
/** 暖色 token 命名空间 */
const WARM_TOKEN = /\b(?:from|via|to|bg|text|border|ring|shadow)-(?:primary|accent|neutral)-\d{2,3}\b/
/** 渐变链里的 `via-*` 中间站（依赖 base 层变量；缺它就整条静默失效） */
const VIA_STOP = /\bvia-(?!transparent\b)[a-z0-9-]+\b/g

const sourceOf = (file: string) => readFileSync(join(ROOT, file), 'utf-8')

/**
 * 去掉注释（行注释 + 块注释）。
 *
 * 🔴 为什么必须去：本判据扫的是**源码文本**，而这三页的头注释**必然**要引用旧形态
 * （`from-blue-50 via-white to-indigo-50`）来解释「为什么改」—— 不去注释就会**被自己的说明喂红**
 * （本仓已多次踩：守卫的文案把守卫判红）。共用同一份口径，判别力自证与真扫描才不会两套。
 */
export function stripComments(source: string): string {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, ' ')
    .replace(/(^|[^:])\/\/[^\n]*/g, '$1 ')
}

/** 判据本体（只吃一段源码）—— 抽出来是为了让判别力自证跑**同一个**判定，不抄第二份正则 */
export function paletteOffenses(source: string): string[] {
  const code = stripComments(source)
  const out: string[] = []
  for (const cls of code.match(COOL_FAMILY) ?? []) out.push(`冷色族类名：${cls}`)
  for (const cls of code.match(VIA_STOP) ?? []) out.push(`渐变里用了 via 中间站：${cls}`)
  if (!WARM_TOKEN.test(code)) out.push('整页没有任何暖色 token（primary / accent / neutral）')
  return out
}

describe('登录 / 注册 / 改密三页 = 全站暖色 token（类级元守卫，issue #6663）', () => {
  it('普查面非空（三个文件都读得到 ⇒ 判据不在扫空气）', () => {
    expect(AUTH_PAGES.length).toBeGreaterThanOrEqual(3)
    for (const page of AUTH_PAGES) {
      expect(sourceOf(page).length, `${page} 应是一份有内容的页面`).toBeGreaterThan(200)
    }
  })

  for (const page of AUTH_PAGES) {
    it(`${page} 不得退回 Tailwind 默认冷色族，且必须有暖色 token`, () => {
      expect(
        paletteOffenses(sourceOf(page)),
        `${page} 与全站暖色 token 不同族（客户第一眼就会看出「不是一个产品」）。\n`
          + '出口：冷色族换成 `primary-*` / `accent-*` / `neutral-*`（见 tailwind.config.ts 的'
          + '「织物质感」token）；渐变用**两停**（`from-primary-50 to-neutral-100`），不要用 `via-*`'
          + '（它依赖 base 层变量，缺了就整条静默失效）。',
      ).toEqual([])
    })
  }

  it('负控：三页的功能锚点逐条仍在（换配色不许把功能换没）', () => {
    const anchors: Record<string, string[]> = {
      'src/app/login/page.tsx': ['员工登录', '管理员登录', '获取验证码', 'min-h-screen'],
      'src/app/register/page.tsx': ['min-h-screen'],
      'src/app/change-password/page.tsx': ['min-h-screen'],
    }
    for (const [page, list] of Object.entries(anchors)) {
      const source = sourceOf(page)
      for (const anchor of list) {
        expect(source.includes(anchor), `${page} 丢了功能锚点「${anchor}」`).toBe(true)
      }
    }
  })

  it('判别力自证：坏形态判红、好形态不红（守卫退化成绿 ⇒ 这里先红）', () => {
    // ① 改前的病灶形态（默认冷色 + via 中间站）
    expect(paletteOffenses(
      '<div className="min-h-screen bg-gradient-to-br from-blue-50 via-white to-indigo-50 px-4">',
    ).length).toBeGreaterThan(0)
    // ② 只删干净、不换暖色（页面变成没配色的裸 Tailwind）⇒ 仍判红
    expect(paletteOffenses('<div className="min-h-screen px-4">')).toContain(
      '整页没有任何暖色 token（primary / accent / neutral）',
    )
    // ③ 暖色但用了 via 中间站 ⇒ 判红（渐变可能静默失效）
    expect(paletteOffenses('<div className="bg-gradient-to-br from-primary-50 via-neutral-50 to-neutral-100">'))
      .toContain('渐变里用了 via 中间站：via-neutral-50')
    // ④ 好形态（本包改后的真实形态）⇒ 一条不红
    expect(paletteOffenses(
      '<div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-primary-50 to-neutral-100 px-4">',
    )).toEqual([])
    // ⑤ `via-transparent` 是**功能性**用法（不靠 base 变量取色）⇒ 不判
    expect(paletteOffenses('<div className="bg-gradient-to-r from-primary-500 via-transparent to-accent-500" />'))
      .toEqual([])
  })

  it('只改注释不红（对照读数：守卫不得被自己的说明文案喂红）', () => {
    // 三页的头注释**必然**要引用旧形态来解释「为什么改」—— 注释里的类名不是上屏配色
    const commented = [
      '// 旧形态 `from-blue-50 via-white to-indigo-50` 已删（issue #6663）',
      '/* 也别写 via-white —— 见本文件头注释 */',
      'const cls = "bg-gradient-to-br from-primary-50 to-neutral-100"',
    ].join('\n')
    expect(paletteOffenses(commented)).toEqual([])
    // 反向对照：同一句**去掉注释标记**就是真类名 ⇒ 判红（证明不是把整段文本一刀放过）
    expect(paletteOffenses('const cls = "from-blue-50 via-white to-indigo-50"').length).toBeGreaterThan(0)
  })
})
