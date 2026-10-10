// case_ids: BM-040
/**
 * 坐席会话详情页：页盒口径与输入区（issue #6666 判据 5）
 *
 * ## 实测读数（线上 `app.migaozn.com/b/`，390×844，API 全桩）——**审计的前提部分不成立**
 *
 * | 量 | 读数 | 判读 |
 * |---|---|---|
 * | `.detail-page` 盒 | top 0 / bottom **844** / height 844 | = 视口高，**不溢出** |
 * | 原生导航条 | **渲染不出**（`null`） | 该页没有导航条占位 ⇒ 不会把输入区顶出视口 |
 * | `.detail-input` | top 788.9 / bottom **844** | `inputBelowViewportPx = 0` ⇒ **没有落在视口之外** |
 *
 * ⇒ 「输入区没为键盘/安全区留位」里的**安全区那一半不成立**：输入区本来就补了
 * `calc(16px + env(safe-area-inset-bottom))`，且实测 bottom == 视口底边。
 * **键盘那一半本机判不了**（真机键盘 / visualViewport）—— 登记在 PR body 的「未固化项」+ §15.7 真机确认。
 *
 * ## 本文件守什么
 *
 * 与聊天页**同源**的页盒口径（`height: 100vh` + `box-sizing: border-box`）：聊天页正是因为没有
 * `border-box` 才让行内 `padding-top` 把那页顶到 **864px**（视口 844）——同一个页盒写法，
 * 详情页一旦加上任何根级 padding 就会以完全相同的方式把底部输入区挤出视口。
 * 安全区**只补一次**（输入区补，页面不再补）。
 */
import fs from 'fs'
import path from 'path'

const SCSS = path.resolve(__dirname, '../src/pages/sessions/detail/index.scss')

/** 剔除注释后的 SCSS **代码** */
function scssCode(file: string): string {
  return fs
    .readFileSync(file, 'utf-8')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .split('\n')
    .filter((line) => !line.trim().startsWith('//'))
    .join('\n')
}

/** 取 `.cls { … }` 整块（按花括号配平） */
function block(code: string, cls: string): string {
  const m = new RegExp(`\\.${cls}\\s*\\{`).exec(code)
  if (!m) return ''
  let depth = 0
  for (let i = m.index + m[0].length - 1; i < code.length; i += 1) {
    if (code[i] === '{') depth += 1
    else if (code[i] === '}') {
      depth -= 1
      if (depth === 0) return code.slice(m.index, i + 1)
    }
  }
  return ''
}

describe('坐席会话详情页 — 页盒与输入区（issue #6666 判据 5）', () => {
  const code = scssCode(SCSS)

  it('🔴 `.detail-page` 与聊天页同源：`height: 100vh` + `box-sizing: border-box`', () => {
    const page = block(code, 'detail-page')
    expect(page).not.toBe('')
    expect(page).toMatch(/height:\s*100vh\s*;/)
    // 少了 border-box：根级任何 padding 都会**加在** 100vh 之上 ⇒ 底部输入区出视口（聊天页实测 864/844）
    expect(page).toMatch(/box-sizing:\s*border-box\s*;/)
  })

  it('安全区只补一次：输入区补 `env(safe-area-inset-bottom)`，页面不补', () => {
    expect(block(code, 'detail-input')).toContain('env(safe-area-inset-bottom)')
    expect(block(code, 'detail-page')).not.toContain('safe-area-inset-bottom')
  })

  it('消息区与输入区都留在 flex 列里（滚动只发生在消息区）', () => {
    expect(block(code, 'detail-page')).toContain('flex-direction: column')
    expect(block(code, 'detail-messages')).toMatch(/flex:\s*1\s*;/)
  })
})
