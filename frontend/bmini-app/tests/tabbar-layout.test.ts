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
 *
 * ## issue #6574 起：**自绘底栏**也守同一族不变量
 *
 * 底栏改为按岗位权限裁剪（服务端下发 `mobileTabs`，端侧自绘 + 收起原生条）⇒ 用户看到的是
 * `src/components/MerchantTabBar.scss` 的那一条。它必须满足同一族不变量（安全区只补一次 / 条高 =
 * Taro 注入的 `--taro-tabbar-height` / 图标文字居中 / 每格等宽），否则 #5754 的病灶会以新形态复发。
 * 本文件两块判据：上面 = 原生条（仍留在 `app.config.ts` 里，`switchTab` 与页面高度算式依赖它），
 * 下面 = 自绘底栏（用户实际看到的）。
 */
import fs from 'fs'
import path from 'path'

const SRC = path.resolve(__dirname, '..', 'src')
const APP_SCSS = path.join(SRC, 'app.scss')
const STYLES_DIR = path.join(SRC, 'styles')
const TABBAR_SCSS = path.join(STYLES_DIR, 'tabbar.scss')
// 自绘底栏（issue #6574）：用户实际看到的那一条
const MERCHANT_TABBAR_COMPONENT = path.join(SRC, 'components', 'MerchantTabBar.tsx')
const MERCHANT_TABBAR_SCSS = path.join(SRC, 'components', 'MerchantTabBar.scss')

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

/** 遍历 `src/**` 的 scss，逐行回调（类级陷阱判据用） */
function walkScss(dir: string, visit: (file: string, line: string) => void): void {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) walkScss(full, visit)
    else if (entry.name.endsWith('.scss')) {
      for (const line of code(fs.readFileSync(full, 'utf-8')).split('\n')) visit(full, line)
    }
  }
}

/**
 * `--taro-tabbar-height` 的**运行时取值**（从装好的 Taro 实现包现取，**不写死**）。
 *
 * 为什么要现取：本仓那一格只能用 **CSS 尺度字面量**（见 ①b：引用变量名会被构建改坏），
 * 于是它与 Taro 之间只剩「数值相等」这一条联系 ⇒ 必须有一条判据盯着它（Taro 升级改了值 ⇒ 判红）。
 * fail-closed：找不到就抛错判红（口径漂移不许静默变成「没检查」）。
 */
function taroTabbarHeightPx(): number {
  const packages = ['components', 'router']
  const pattern = /--taro-tabbar-height:\s*(\d+)px/
  for (const pkg of packages) {
    const root = path.resolve(__dirname, '..', 'node_modules', '@tarojs', pkg, 'dist')
    if (!fs.existsSync(root)) continue
    const stack = [root]
    while (stack.length) {
      const dir = stack.pop() as string
      for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        const full = path.join(dir, entry.name)
        if (entry.isDirectory()) stack.push(full)
        else if (/\.(css|js)$/.test(entry.name)) {
          const hit = fs.readFileSync(full, 'utf-8').match(pattern)
          if (hit) return Number(hit[1])
        }
      }
    }
  }
  throw new Error(
    '在 @tarojs/{components,router} 的 dist 里找不到 `--taro-tabbar-height:<n>px` —— 口径漂移，判红（去核对 Taro 的 tabBar 实现，别猜一个数补上）',
  )
}

describe('B 端 H5 tabBar 居中不变量（issue #5754）', () => {
  it('覆盖样式必须被 app.scss 真的引入（写在别处但没接线 ⇒ 红）', () => {
    expect(code(read(APP_SCSS))).toMatch(/@use\s+['"]\.\/styles\/tabbar\.scss['"]/)
  })

  it('① 安全区只补一次：条不再吃 margin-bottom，条高 = Taro 的 tabBar 高 + 安全区', () => {
    const scss = tabbarCode()
    expect(scss).toMatch(/\.taro-tabbar__tabbar-bottom\s*\{[^}]*margin-bottom:\s*0\s*;/)
    expect(scss).toMatch(
      /\.taro-tabbar__tabbar\s*\{[^}]*height:\s*calc\(\s*\d+PX\s*\+\s*env\(safe-area-inset-bottom\)\s*\)/,
    )
  })

  it('①b 🔴 构建陷阱：**不许**引用 `var(--taro-tabbar-height)`（构建会改成 `var(--50PX)` ⇒ 规则失效）', () => {
    // 实证（PR #5755 发布后线上 + 探针实验）：
    //   `.x{width:var(--taro-tabbar-height)}` 编译成 `var(--50PX)` —— 变量名解析不到 ⇒
    //   该声明**在计算值阶段失效**（`unset` → `auto`）⇒ 线上条高塌成 26px、标签被挤出视口（实测超出 9.5px）。
    //   对照组：`var(--my-thing)` / `var(--foo-height)` **原样保留** ⇒ 被特殊处理的是**这个名字**。
    //   ⇒ 本仓 scss 里一律不得出现它；要那个高度就用 CSS 尺度字面量（大写 PX，见 ①c）。
    const offenders: string[] = []
    walkScss(SRC, (file, line) => {
      if (line.includes('var(--taro-tabbar-height')) offenders.push(`${path.relative(SRC, file)}: ${line.trim()}`)
    })
    expect(offenders).toEqual([])
  })

  it('①c 字面量必须与 Taro 运行时注入值**逐值相等**（Taro 升级把 50px 改成别的值 ⇒ 判红）', () => {
    const ours = Number(tabbarCode().match(/calc\(\s*(\d+)PX/)?.[1])
    expect(Number.isFinite(ours)).toBe(true)
    expect(ours).toBe(taroTabbarHeightPx())
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

// ══════════════════════════════════════════════════════════════════════════
// 自绘底栏（issue #6574）：用户实际看到的那一条
// ══════════════════════════════════════════════════════════════════════════

describe('B 端 H5 自绘底栏的几何不变量（issue #6574）', () => {
  const scss = code(read(MERCHANT_TABBAR_SCSS))

  it('覆盖样式被组件真的引入（写在别处但没接线 ⇒ 红）', () => {
    expect(code(read(MERCHANT_TABBAR_COMPONENT))).toContain("import './MerchantTabBar.scss'")
  })

  it('① 安全区只补一次：条高 = Taro 的 tabBar 高 + 安全区，且条**不吃** margin-bottom', () => {
    const bar = scss.match(/\.merchant-tabbar\s*\{[^}]*\}/)?.[0] ?? ''
    expect(bar).toMatch(/height:\s*calc\(\s*\d+PX\s*\+\s*env\(safe-area-inset-bottom\)\s*\)/)
    expect(bar).toMatch(/padding-bottom:\s*env\(safe-area-inset-bottom\)\s*;/)
    expect(bar).not.toContain('margin-bottom')
  })

  it('①b 🔴 构建陷阱：不许引用 `var(--taro-tabbar-height)`（全局扫描已覆盖，这里再显式钉一次）', () => {
    expect(scss).not.toContain('var(--taro-tabbar-height')
  })

  it('①c 字面量必须与 Taro 运行时注入值**逐值相等**（Taro 升级改了值 ⇒ 判红）', () => {
    const ours = Number(scss.match(/calc\(\s*(\d+)PX/)?.[1])
    expect(Number.isFinite(ours)).toBe(true)
    expect(ours).toBe(taroTabbarHeightPx())
  })

  it('② 图标 + 文字在可视区垂直居中（flex 纵列居中，不靠固定留白）', () => {
    const item = scss.match(/\.merchant-tabbar__item\s*\{[^}]*\}/)?.[0] ?? ''
    expect(item).toContain('display: flex')
    expect(item).toContain('flex-direction: column')
    expect(item).toContain('align-items: center')
    expect(item).toContain('justify-content: center')
  })

  it('③ 每格等宽（某格被按岗位隐藏后，其余自动等分整条）', () => {
    const item = scss.match(/\.merchant-tabbar__item\s*\{[^}]*\}/)?.[0] ?? ''
    expect(item).toMatch(/flex:\s*1\s*;/)
  })
})
