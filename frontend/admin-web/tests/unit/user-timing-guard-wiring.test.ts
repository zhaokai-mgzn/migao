// case_ids: UI-097
// 类级元守卫（issue #6799 ② 的接线面；判据本身经 issue #6946 订正）：
// 区间守卫必须真的**装进浏览器** —— 「有一个好用的守卫」≠「守卫被装上」。
//
// ## 旧判据为什么是假绿（#6946 实测）
// 旧版只断言 `src/app/layout.tsx` 里有一行 `import '../lib/user-timing-guard'`。
// 但 **`layout.tsx` 没有 `'use client'` ⇒ 它是 Server Component ⇒ 那句 import 只在 Node 侧执行**，
// 守卫入口的 `typeof window === 'undefined'` 短路 ⇒ 浏览器里 `performance.measure` 始终是原生的。
// 真栈读数（2026-10-15，Playwright，`acceptance/2026-10-14/tools/probe-timing-guard.mjs`）：
//   `installed=false`（`__userTimingGuardInstalled` 未置） · `String(performance.measure).includes('[native code]') === true`
// —— 而当时的接线判据**照样绿**。⇒ 判据必须钉住「**客户端能真装上**」这条链，而不是"仓库里有一行字"。
//
// ## 机械面（本判据钉的三件事）
// ① 装它的模块必须是 **`'use client'` 模块**（否则 Server Component 的短路会重演）；
// ② `layout.tsx` 必须**渲染**那个客户端组件（只 `import` 不够 —— 不渲染就不进初始 chunk）；
// ③ 守卫模块自己必须在模块顶层调用 `installUserTimingGuard()`（不是只在被显式调用时才生效）。
//
// ## 红证
// 删掉客户端模块的 `'use client'` ⇒ ① 红；`layout.tsx` 去掉 `<UserTimingGuard />` ⇒ ② 红；
// 去掉守卫模块末尾的 `installUserTimingGuard()` ⇒ ③ 红。三条各带同类判据内的对照读数（下方 negative control）。

import { describe, it, expect } from 'vitest'
import { readFileSync, existsSync } from 'node:fs'
import { join } from 'node:path'

const SRC = join(process.cwd(), 'src')
const LAYOUT = join(SRC, 'app', 'layout.tsx')
const GUARD = join(SRC, 'lib', 'user-timing-guard.ts')
const CLIENT_INSTALLER = join(SRC, 'components', 'UserTimingGuard.tsx')

describe('performance.measure 守卫的接线（issue #6799 ② / #6946 订正）', () => {
  it('① 装它的模块是 client 模块（否则 Server Component 的 import 进不了客户端 bundle）', () => {
    expect(existsSync(CLIENT_INSTALLER), `缺少客户端接线模块 ${CLIENT_INSTALLER}`).toBe(true)
    const src = readFileSync(CLIENT_INSTALLER, 'utf8')
    expect(
      /^\s*['"]use client['"]\s*$/m.test(src),
      "src/components/UserTimingGuard.tsx 缺少 'use client' —— 守卫会退化成「只在 Node 侧 import」（issue #6946 的病灶）",
    ).toBe(true)
    expect(
      /installUserTimingGuard\s*\(/.test(src),
      'src/components/UserTimingGuard.tsx 必须在模块顶层调用 installUserTimingGuard()',
    ).toBe(true)
  })

  it('② `layout.tsx` 渲染了该客户端组件（只 import 不够）', () => {
    const src = readFileSync(LAYOUT, 'utf8')
    expect(
      /import\s+UserTimingGuard\s+from\s+['"]@\/components\/UserTimingGuard['"]/.test(src),
      'src/app/layout.tsx 必须 import UserTimingGuard',
    ).toBe(true)
    expect(
      /<UserTimingGuard\s*\/>/.test(src),
      'src/app/layout.tsx 必须**渲染** <UserTimingGuard />（否则不随初始 chunk 加载）',
    ).toBe(true)
    expect(
      /^import\s+'\.\.\/lib\/user-timing-guard'\s*$/m.test(src),
      'src/app/layout.tsx 不得再直接副作用 import 守卫模块（Server Component 里那行是空操作，会误导后来人）',
    ).toBe(false)
  })

  it('③ 守卫在模块顶层自装（不是只在被显式调用时才生效）', () => {
    const src = readFileSync(GUARD, 'utf8')
    expect(/^installUserTimingGuard\(\)\s*$/m.test(src), '守卫模块末尾缺少顶层 `installUserTimingGuard()` 调用').toBe(true)
  })

  it('负控/判别力自证：去掉 use client 与渲染后，判据必须不再命中', () => {
    const client = readFileSync(CLIENT_INSTALLER, 'utf8')
    const clientNoDirective = client.replace(/^\s*['"]use client['"]\s*$/m, "// 'use client'")
    expect(clientNoDirective).not.toBe(client)
    expect(/^\s*['"]use client['"]\s*$/m.test(clientNoDirective), '去掉 use client 后 ① 必须不再命中').toBe(false)

    const layout = readFileSync(LAYOUT, 'utf8')
    // 替换文本里**不得**再出现该 JSX（放在注释里也算命中 ⇒ 负控会自相矛盾）
    const layoutNoRender = layout.replace(/<UserTimingGuard\s*\/>/, '{/* 已移除 */}')
    expect(layoutNoRender).not.toBe(layout)
    expect(/<UserTimingGuard\s*\/>/.test(layoutNoRender), '去掉渲染后 ② 必须不再命中').toBe(false)
  })
})
