// case_ids: UI-099
// 客户端接线组件本身的判据（issue #6946）：它存在的**唯一理由**就是"模块顶层装上守卫"。
// 判据分三层：① import 即装（不是等 useEffect —— React 首次 commit 的埋点在效果之前）；
// ② 组件自身不上屏（渲染 null）；③ 接线**时机**由源码形态钉住（调用必须在 `export default` 之前，
// 即模块作用域），防止有人把调用挪进组件体里（那样第一次 commit 就漏掉了）。

import { describe, it, expect, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

const { installSpy } = vi.hoisted(() => ({ installSpy: vi.fn(() => true) }))

vi.mock('@/lib/user-timing-guard', () => ({ installUserTimingGuard: installSpy }))

describe('UserTimingGuard —— measure 守卫的客户端接线（issue #6946）', () => {
  it('① import 该模块即装上守卫（模块顶层调用，不需要任何人显式调用它）', async () => {
    vi.resetModules()
    installSpy.mockClear()
    await import('@/components/UserTimingGuard')
    expect(installSpy, 'import 该模块必须已经调用过 installUserTimingGuard()').toHaveBeenCalledTimes(1)
  })

  it('② 模块只执行一次：重复 import 不会重复安装（ESM 缓存 + 守卫自身幂等）', async () => {
    vi.resetModules()
    installSpy.mockClear()
    await import('@/components/UserTimingGuard')
    await import('@/components/UserTimingGuard')
    expect(installSpy).toHaveBeenCalledTimes(1)
  })

  it('③ 组件自身渲染 null（它只是接线点，不上屏）', async () => {
    vi.resetModules()
    const mod = await import('@/components/UserTimingGuard')
    // 该组件**不接受 props**（`export default function UserTimingGuard()`）⇒ 直接无参调用；
    // 传 `{}` 会被 `tsc --noEmit` 判红（TS2554，CI 的 admin-web typecheck 腿实测抓过）。
    expect(mod.default()).toBeNull()
  })

  it('④ 接线时机：调用必须写在模块作用域（`export default` 之前），不得挪进组件体', () => {
    const src = readFileSync(join(process.cwd(), 'src', 'components', 'UserTimingGuard.tsx'), 'utf8')
    // ⚠️ 必须钉「独占一行的模块级调用」，不能用 `indexOf('installUserTimingGuard()')`：
    // 本文件的**文档注释**里也写了这个符号（实测被喂中过 —— 与仓内「按原文扫会被注释喂中」同坑）。
    const CALL = /^installUserTimingGuard\(\)\s*$/m
    const callAt = src.search(CALL)
    expect(callAt, '模块作用域必须有一行 `installUserTimingGuard()`（模块顶层调用）').toBeGreaterThan(-1)
    expect(callAt, '安装调用必须在 `export default` **之前**（模块顶层，早于 React 首次 commit 埋点）').toBeLessThan(
      src.search(/export default/),
    )
    // 判别力自证：把它挪进组件体（模拟错误改法）⇒ 同一条判据必须不再成立
    const moved = src.replace(CALL, '').replace('return null', 'installUserTimingGuard()\n    return null')
    expect(moved, '负控：源码确实被改动了').not.toBe(src)
    expect(CALL.test(moved), '负控：挪进组件体后，模块级调用不再存在 ⇒ 判据必须不再命中').toBe(false)
  })
})
