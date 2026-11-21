// case_ids: MC-341
/**
 * 登录页「验证码行」布局守卫（issue #8983，真机实测缺陷）
 *
 * ## 治的形态
 *
 * 生产体验版 1.0.0 在 iPhone 上实测：验证码输入框右侧的「获取验证码」按钮**左边框不可见、
 * 左侧被输入框压住**（用户逐字「获取验证码的按钮有点问题吧，被遮住了」）。
 *
 * 机制：`.login-field__input` 带 `width: 100%`，而 `.login-field__input--code` 只补了
 * `flex: 1; min-width: 0`，**没有覆盖宽度**。weapp 的原生 `<input>` 是原生组件，宽度按 CSS
 * `width` 铺开 ⇒ 输入框占满整行、压在按钮上方。H5 下 flex 生效顺序不同，通常看不出来，
 * 所以这个缺陷**只在真机暴露**。
 *
 * 同理按钮缺 `box-sizing: border-box`（输入框有）⇒ 按钮总高 96 + 2rpx，比输入框高一条。
 *
 * ## 判据（每条都能单独变红）
 *
 * | # | 判什么 | 红证（注入式，实跑） |
 * |---|---|---|
 * | ① | `&__input--code` 里出现 `width: auto`（覆盖父级 100%） | 删掉该行 ⇒ 红 |
 * | ② | `.login-code-btn` 有 `box-sizing: border-box` | 删掉该行 ⇒ 红 |
 * | ③ | 父级 `&__input` 仍保留 `width: 100%`（防「为修 ① 而删父级」，污染其它输入面） | 删掉父级 ⇒ 红 |
 *
 * 判的是**源码结构**（不是渲染像素）：渲染像素要真机/Chromium 才有判据，这里只钉住「修法必须留在位」。
 */
import * as fs from 'fs'
import * as path from 'path'

const SCSS_PATH = path.join(__dirname, '..', 'src', 'pages', 'auth', 'login', 'index.scss')

/** 取某选择器后面第一个 `{ ... }` 块的内容（做花括号配平，SCSS 里嵌套块也能正确切）。 */
function ruleBlock(source: string, selector: string): string {
  const at = source.indexOf(selector)
  if (at < 0) return ''
  const open = source.indexOf('{', at + selector.length)
  if (open < 0) return ''
  let depth = 0
  for (let i = open; i < source.length; i += 1) {
    const ch = source[i]
    if (ch === '{') depth += 1
    else if (ch === '}') {
      depth -= 1
      if (depth === 0) return source.slice(open + 1, i)
    }
  }
  return ''
}

describe('登录页验证码行布局（issue #8983）', () => {
  const source = fs.readFileSync(SCSS_PATH, 'utf8')

  it('① 验证码输入框必须覆盖父级的 width:100%（否则 weapp 下压住按钮）', () => {
    const block = ruleBlock(source, '&__input--code')
    expect(block).not.toBe('')
    expect(block).toMatch(/width:\s*auto/)
  })

  it('② 「获取验证码」按钮必须是 border-box（与输入框同盒模型）', () => {
    const block = ruleBlock(source, '.login-code-btn')
    expect(block).not.toBe('')
    expect(block).toMatch(/box-sizing:\s*border-box/)
  })

  it('③ 父级输入框的 width:100% 必须保留（别的输入面靠它铺满）', () => {
    const block = ruleBlock(source, '&__input')
    expect(block).toMatch(/width:\s*100%/)
  })
})
