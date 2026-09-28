// case_ids: BM-030
/**
 * B 端 H5 底部 tabBar 的**居中不变量**（issue #5754）
 *
 * ## 治的形态
 *
 * Taro h5 的 tabBar 把 iOS 安全区**算了两遍**（条 `margin-bottom: env(safe-area-inset-bottom)`
 * 把整条抬起 + item `padding-bottom: env(...)` 再垫一次）⇒ 线上实测：iPhone 上图标溢出条外、
 * 文字下方留 51px 空白；无安全区时 item 是「上 5 下 0」⇒ 文字贴着屏幕底边。两种都不居中。
 *
 * ## 判据的诚实边界（**这是文本级守卫，不是几何判据**）
 *
 * 本文件只保证「`src/styles/tabbar.scss` 的三条不变量在位 + 被 `src/app.scss` 真的引入」。
 * 「是否真的居中」需要浏览器几何复测（本仓 bmini 无 e2e 腿）—— 复测读数记在 issue #5754 与 PR 正文，
 * **不要**把本文件读成「布局已被机器验过」。
 *
 * 三条不变量：① 安全区只补一次（条不吃 margin-bottom、条高覆盖安全区）；
 * ② 图标 + 文字在可视区垂直居中（flex 纵列居中 + `padding-top: 0`）；
 * ③ item 的底部安全区衬垫保留（只清 top）。
 */
import fs from 'fs'
import path from 'path'

const SRC = path.resolve(__dirname, '..', 'src')
const APP_SCSS = path.join(SRC, 'app.scss')
const STYLES_DIR = path.join(SRC, 'styles')
const TABBAR_SCSS = path.join(STYLES_DIR, 'tabbar.scss')

/** 读文件；**缺文件 = 判红**（不是跳过 —— 缺了就没法区分「没违规」与「没检查」） */
function read(file: string): string {
  expect(fs.existsSync(file)).toBe(true)
  return fs.readFileSync(file, 'utf-8')
}

/** 去掉整行 `//` 注释后的**代码**（注释里提到某条规则不算落实） */
function code(scss: string): string {
  return scss
    .split('\n')
    .filter((line) => !line.trim().startsWith('//'))
    .join('\n')
}

const tabbarCode = () => code(read(TABBAR_SCSS))

describe('B 端 H5 tabBar 居中不变量（issue #5754）', () => {
  it('覆盖样式必须被 app.scss 真的引入（写在别处但没接线 ⇒ 红）', () => {
    expect(code(read(APP_SCSS))).toMatch(/@use\s+['"]\.\/styles\/tabbar\.scss['"]/)
  })

  it('① 安全区只补一次：条不再吃 margin-bottom，条高 = --taro-tabbar-height + 安全区', () => {
    const scss = tabbarCode()
    expect(scss).toMatch(/\.taro-tabbar__tabbar-bottom\s*\{[^}]*margin-bottom:\s*0\s*;/)
    expect(scss).toMatch(
      /\.taro-tabbar__tabbar\s*\{[^}]*height:\s*calc\(\s*var\(--taro-tabbar-height[^)]*\)\s*\+\s*env\(safe-area-inset-bottom\)\s*\)/,
    )
  })

  it('② 图标 + 文字在可视区垂直居中（flex 纵列居中，不靠「上 5 下 0」）', () => {
    const item = tabbarCode().match(/\.weui-tabbar__item\s*\{[^}]*\}/)?.[0] ?? ''
    expect(item).toContain('display: flex')
    expect(item).toContain('flex-direction: column')
    expect(item).toContain('align-items: center')
    expect(item).toContain('justify-content: center')
    expect(item).toMatch(/padding-top:\s*0\s*;/)
  })

  it('③ item 的底部安全区衬垫必须保留（与 ① 合起来才是「只补一次」）', () => {
    const item = tabbarCode().match(/\.weui-tabbar__item\s*\{[^}]*\}/)?.[0] ?? ''
    expect(item).toMatch(/padding-bottom:\s*env\(safe-area-inset-bottom\)\s*;/)
  })

  it('类级：tabbar 覆盖只有这一份（别处再写一套 ⇒ 第二份口径会漂）', () => {
    const others = fs
      .readdirSync(STYLES_DIR)
      .filter((file) => file.endsWith('.scss') && file !== 'tabbar.scss' && file !== 'variables.scss')
    const duplicated = others.filter((file) =>
      code(fs.readFileSync(path.join(STYLES_DIR, file), 'utf-8')).includes('taro-tabbar__'),
    )
    expect(duplicated).toEqual([])
  })
})
