// case_ids: BM-040
/**
 * 商家面身份护栏（issue #6567）—— **纯工人设备不进商家页**
 *
 * ## 为什么要有
 * 工人用「工号 + PIN」登录后落在工人工作台，但那是**登录后的落点**：工人设备仍可以用
 * 网址 / 二维码 / 收藏打开任何**商家页**（数据 / 我的 / 坐席 / 管理面 4 项）—— 那台机器上
 * 没有商家凭据，商家页只会一路 403 / 空页。用户 2026-10-08：「得按职责完全隔离干净」。
 *
 * ## 判据
 * | # | 判据 | 红证 |
 * |---|---|---|
 * | 1 | 有工人 session、**无**商家凭据 ⇒ 打开商家页 `redirectTo(WORKER_HOME_ROUTE)` | 去掉 hook ⇒ 用例判红 |
 * | 2 | 负控：**有**商家凭据（哪怕同时有工人 session）⇒ **不跳**（共用 PAD 的正常动线） | 只看工人 session 就跳 ⇒ 判红 |
 * | 3 | 负控：只有商家凭据、没有工人 session ⇒ 不跳 | 同上 |
 * | 4 | 类级：**商家页清单**（tabBar 四页 + 管理面 4 项 + 坐席会话详情，现取）每页都挂了护栏 | 新增一个商家页不挂 ⇒ 判红 |
 * | 5 | 类级：工人页 / 公开登录页**不许**挂护栏（挂了工人会被自己的页面弹走） | 给报工页挂上 ⇒ 判红 |
 */
import React from 'react'
import { View } from '@tarojs/components'
import { render } from '@testing-library/react'
import * as fs from 'fs'
import * as path from 'path'

jest.mock('../src/utils/request', () => ({
  get: jest.fn(),
  post: jest.fn(),
  put: jest.fn(),
  del: jest.fn(),
}))

import Taro from '@tarojs/taro'
import { STORAGE_KEYS } from '../src/utils/constants'
import { useMerchantSurfaceGuard } from '../src/utils/roleGuard'
import { WORKER_HOME_ROUTE } from '../src/utils/inbound/gaps'
import { ADMIN_SURFACES } from '../src/utils/adminPermission'

const BMINI_ROOT = path.join(__dirname, '..')

/** 探针：只挂护栏、不渲染别的东西 —— 测的就是 hook 本身（不是某一页的副作用） */
function Probe() {
  useMerchantSurfaceGuard()
  return <View />
}

function clearCredentials(): void {
  ;[STORAGE_KEYS.WORKER_SESSION, STORAGE_KEYS.TOKEN, STORAGE_KEYS.USER, STORAGE_KEYS.TENANT_ID].forEach(
    (key) => Taro.removeStorageSync(key),
  )
}

describe('商家面身份护栏（行为）', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    clearCredentials()
  })

  it('🔴 纯工人设备（有工人 session、无商家凭据）⇒ 送回工人工作台', () => {
    Taro.setStorageSync(STORAGE_KEYS.WORKER_SESSION, 'ws-1')

    render(<Probe />)

    expect(Taro.redirectTo).toHaveBeenCalledWith({ url: WORKER_HOME_ROUTE })
  })

  it('负控：有商家凭据（且同时有工人 session）⇒ **不跳**（共用 PAD 的正常动线）', () => {
    Taro.setStorageSync(STORAGE_KEYS.WORKER_SESSION, 'ws-1')
    Taro.setStorageSync(STORAGE_KEYS.TOKEN, 'aaa.bbb.ccc')
    Taro.setStorageSync(STORAGE_KEYS.USER, { id: 'u1', nickname: '王老板' })

    render(<Probe />)

    expect(Taro.redirectTo).not.toHaveBeenCalled()
  })

  it('负控：只有商家凭据、没有工人 session ⇒ 不跳', () => {
    Taro.setStorageSync(STORAGE_KEYS.TOKEN, 'aaa.bbb.ccc')
    Taro.setStorageSync(STORAGE_KEYS.USER, { id: 'u1', nickname: '王老板' })

    render(<Probe />)

    expect(Taro.redirectTo).not.toHaveBeenCalled()
  })
})

// ── 类级守卫：清单**现取**（tabBar 页来自 app.config，管理面来自 ADMIN_SURFACES），
//    新增一个商家页而没挂护栏 ⇒ 自动进不了清单也不行（清单是现取的，它一进 tabBar / 管理面就在射程内）。
/** 「坐席」列表点进去的详情页（既不是 tabBar 页、也不在 ADMIN_SURFACES 里） */
const EXTRA_MERCHANT_PAGES = ['src/pages/sessions/detail/index.tsx']

function tabBarPageFiles(): string[] {
  const text = fs.readFileSync(path.join(BMINI_ROOT, 'src/app.config.ts'), 'utf8')
  return Array.from(text.matchAll(/pagePath:\s*'([^']+)'/g)).map((m) => `src/${m[1]}.tsx`)
}

function adminSurfaceFiles(): string[] {
  return ADMIN_SURFACES.map((surface) => `src${surface.route}.tsx`)
}

/** 🔴 认**调用形态**（`useMerchantSurfaceGuard()`），不是「文件里提过这个名字」——
 *  只 import 不调（或在注释里提一句）不算挂上（§28.2：写了 ≠ 会被执行）。 */
function guarded(file: string): boolean {
  return fs.readFileSync(path.join(BMINI_ROOT, file), 'utf8').includes('useMerchantSurfaceGuard()')
}

describe('商家页清单（类级：新增商家页必须挂护栏）', () => {
  it('tabBar 四页 + 管理面 4 项 + 坐席详情 ⇒ 每页都挂了护栏', () => {
    const merchantPages = [...tabBarPageFiles(), ...adminSurfaceFiles(), ...EXTRA_MERCHANT_PAGES]
    // 反空跑：清单真的现取到了（否则「每页都挂」在空集上恒真）
    expect(tabBarPageFiles().length).toBeGreaterThanOrEqual(4)
    expect(adminSurfaceFiles().length).toBeGreaterThanOrEqual(4)

    merchantPages.forEach((file) => {
      expect({ file, guarded: guarded(file) }).toEqual({ file, guarded: true })
    })
  })

  it('🔴 工人页 / 公开登录页**不许**挂护栏（挂了工人被自己的页面弹走、登录都进不去）', () => {
    const notGuarded = [
      'src/pages/production/index/index.tsx',
      'src/pages/worker/home/index.tsx',
      'src/pages/worker/inbound/index.tsx',
      'src/pages/worker/reprint/index.tsx',
      'src/pages/worker/login/index.tsx',
      'src/pages/auth/login/index.tsx',
    ]
    notGuarded.forEach((file) => {
      expect({ file, guarded: guarded(file) }).toEqual({ file, guarded: false })
    })
  })
})
