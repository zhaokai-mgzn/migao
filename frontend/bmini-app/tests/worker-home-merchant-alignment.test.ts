// case_ids: BM-034
/**
 * 类级守卫：**工人工作台必须和商家端用同一套视觉语言**（issue #7240）。
 *
 * ## 用户逐字（2026-10-18）
 * 「手机端工人登录后和商家登录后的两种风格，看起来很割裂」
 *
 * ## 病灶（读码，零成本复算）
 *
 * 商家端页面（`pages/auth/login` / `pages/profile` / `pages/dashboard`）统一 `@use
 * "../../../styles/variables.scss"`，页头是**品牌渐变带**（`$gradient-brand` / `$primary-color` →
 * `$primary-light`，下缘大圆角），卡片 `$radius-lg` + `$border-color` + `$shadow-card`。
 *
 * 工人工作台（`pages/worker/home`）却**自持一套字面量**：`#0a2540` / `#1a73e8` / `#f5f7fa` /
 * `#eaeef3` …（值恰好相同，但**没有一处走 token**），且整页是「白卡落在灰底上」——
 * 没有商家页头那一条品牌渐变带，卡片圆角/阴影也自成一套 ⇒ 同一个 App 里两个世界。
 *
 * ## 判据形态（会红）
 *
 * | # | 判据 | 怎么红 |
 * |---|---|---|
 * | 1 | 设计变量**单一源**：本页 `@use` `styles/variables.scss` | 删掉 `@use` ⇒ 红 |
 * | 2 | **零裸 hex**：规则体里不许再出现 `#rrggbb`（白色也走 `$bg-primary`） | 回填任意一个旧字面量 ⇒ 红（具名列出） |
 * | 3 | 身份条是**品牌渐变页头**（`linear-gradient` 且取自品牌 token），下缘大圆角 = 商家登录页同款 | 改回纯白卡 ⇒ 红 |
 * | 4 | 卡片圆角沿用商家卡片 token（`$radius-lg`），不自持 24px | 改回 `24px` ⇒ 红 |
 * | 5 | 判别力自证（内存变异 + 兄弟守卫的机制仍被引用） | 判据退化成恒真 ⇒ 红 |
 *
 * ## 边界（如实登记）
 *
 * - 本守卫判的是**同源**（同一份 token、同一族页头样式、同一套圆角），**判不了「好不好看」**；
 *   观感最终仍靠人读图（本机无浏览器二进制时，§15.7 多模态截图验收缺席 —— 会写进 PR 的未固化项）。
 * - 「零裸 hex」是**刻意**的：值相同但字面量各写一份，商家端改一阶工人端就不会跟着变 —— 这正是本单的成因。
 */
import fs from 'fs'
import path from 'path'

const ROOT = path.resolve(__dirname, '..')
const SCSS_REL = 'src/pages/worker/home/index.scss'
const SCSS = fs.readFileSync(path.join(ROOT, SCSS_REL), 'utf-8')

/** 剥块注释与行注释 —— 注释里引用的旧 hex 不算违规（与 `worker-card-contrast-guard` 同口径）。 */
function stripComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/[^\n]*/g, '')
}

/** 取某个选择器块（按 `{`/`}` 配对；找不到 ⇒ 返回空串，由断言具名报错）。 */
function blockOf(source: string, selector: string): string {
  const at = source.indexOf(selector)
  if (at < 0) return ''
  const open = source.indexOf('{', at)
  if (open < 0) return ''
  let depth = 0
  for (let i = open; i < source.length; i += 1) {
    if (source[i] === '{') depth += 1
    else if (source[i] === '}') {
      depth -= 1
      if (depth === 0) return source.slice(open + 1, i)
    }
  }
  return source.slice(open + 1)
}

const CSS = stripComments(SCSS)

describe('工人工作台与商家端同一套视觉语言（issue #7240）', () => {
  it('① 设计变量单一源：本页 `@use` `styles/variables.scss`', () => {
    expect(CSS).toMatch(/@use\s+["'][^"']*styles\/variables\.scss["']\s+as\s+\*/)
  })

  it('② 零裸 hex：规则体里不许再出现 `#rrggbb`（白色也走 `$bg-primary`）', () => {
    const literals = Array.from(new Set(CSS.match(/#[0-9a-fA-F]{3,8}\b/g) ?? [])).sort()
    expect(literals).toEqual([])
  })

  it('③ 身份条 = 品牌渐变页头（`$gradient-brand` + 下缘大圆角，与商家登录页同款）', () => {
    const card = blockOf(CSS, '&__card')
    expect(card).not.toBe('')
    expect(card).toMatch(/background:\s*\$gradient-brand/)
    expect(card).toMatch(/border-radius:\s*0 0 48px 48px/)
    // 可见边界仍在（兄弟守卫判据 4：卡片形态必须声明 border 或 box-shadow）
    expect(card).toMatch(/box-shadow:\s*\$shadow-card/)
  })

  it('④ 卡片圆角沿用商家卡片 token（`$radius-lg`），不自持 24px', () => {
    for (const selector of ['&__entry', '&__gate']) {
      const block = blockOf(CSS, selector)
      expect({ selector, found: block !== '' }).toEqual({ selector, found: true })
      expect({ selector, usesToken: /border-radius:\s*\$radius-lg/.test(block) }).toEqual({
        selector,
        usesToken: true,
      })
    }
    // 反向：整页不许再出现写死的 24px 圆角（那是本页自持的那一套）
    expect(CSS).not.toMatch(/border-radius:\s*24px/)
  })

  it('⑤ 判别力自证：本守卫的两条检测器都真的会响', () => {
    // 裸 hex：注入一个旧字面量 ⇒ ② 的检测器命中
    expect(stripComments('.x { color: #0a2540 }').match(/#[0-9a-fA-F]{3,8}\b/g)).toEqual(['#0a2540'])
    // 注释里的 hex 不算
    expect(stripComments('// #0a2540\n.x { color: $text-primary }').match(/#[0-9a-fA-F]{3,8}\b/g)).toBe(null)
    // 规则块取值：能取到 `&__card` 的块体、且取不到不存在的选择器
    expect(blockOf(CSS, '&__card')).not.toBe('')
    expect(blockOf(CSS, '&__not-exist')).toBe('')
  })
})
