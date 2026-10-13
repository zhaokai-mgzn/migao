// case_ids: UI-097
// 类级元守卫（issue #6799 ② 的接线面）：区间守卫必须真的**被装上** ——
// 「有一个好用的守卫」与「守卫被接线」是两件事（本仓已多次踩过：判据在、接线丢了，没有任何东西变红）。
//
// ## 机械面
// `src/app/layout.tsx` 必须在**模块顶层** import `@/lib/user-timing-guard`
// （root layout 的模块级 import 会随初始 bundle 在 React hydrate **之前**执行；放进某个组件的
// `useEffect` 就晚了 —— React 首次 commit 的埋点先跑）。同时守卫模块自己必须在模块顶层调用 `installUserTimingGuard()`。
//
// ## 红证
// 删掉 `layout.tsx` 的那行 import ⇒ 本判据红（具名报出"接线不见了"）；
// 删掉守卫模块末尾的 `installUserTimingGuard()` 调用 ⇒ 本判据红（具名报出"模块不自动装"）。

import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

const SRC = join(process.cwd(), 'src')
const LAYOUT = join(SRC, 'app', 'layout.tsx')
const GUARD = join(SRC, 'lib', 'user-timing-guard.ts')

describe('performance.measure 守卫的接线（issue #6799 ②）', () => {
  it('root layout 模块顶层 import 了守卫', () => {
    const src = readFileSync(LAYOUT, 'utf8')
    // 相对路径而非 `@/lib/…` 别名：实测 Turbopack 对**新增**文件的别名解析会在文件创建后
    // 一段时间内报 `Module not found: Can't resolve '@/lib/user-timing-guard'`（同目录同级，
    // 相对路径的解析路径不同、不受该缓存影响）—— 判据只钉"顶层静态 import 到本模块"。
    expect(
      /^import\s+'\.\.\/lib\/user-timing-guard'\s*$/m.test(src),
      'src/app/layout.tsx 缺少顶层 `import \'../lib/user-timing-guard\'` —— 守卫不会被装上（issue #6799 ②）',
    ).toBe(true)
  })

  it('守卫在模块顶层自装（不是只在被显式调用时才生效）', () => {
    const src = readFileSync(GUARD, 'utf8')
    expect(/^installUserTimingGuard\(\)\s*$/m.test(src), '守卫模块末尾缺少顶层 `installUserTimingGuard()` 调用').toBe(true)
  })

  it('负控/判别力自证：把接线改成注释后，判据的核对正则不再命中（同一条判据的对照读数）', () => {
    const src = readFileSync(LAYOUT, 'utf8')
    const commented = src.replace(/^import\s+'\.\.\/lib\/user-timing-guard'\s*$/m, "// import '../lib/user-timing-guard'")
    expect(commented).not.toBe(src)
    expect(/^import\s+'\.\.\/lib\/user-timing-guard'\s*$/m.test(commented), '去掉接线后判据必须不再命中').toBe(false)
  })
})
