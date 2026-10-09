// case_ids: BM-047
/**
 * B 端底栏**按岗位权限裁剪**（issue #6574；用户 2026-10-08 逐字「**1，按权限隐藏**」）
 *
 * ## 治的形态
 *
 * `app.config.ts` 的 `tabBar` 是**构建期静态**的 4 项（问黄金策 / 数据 / 坐席 / 我的）：
 * `Taro.setTabBarItem` 只能改文字/图标、`hideTabBar` 只能整条收起 ⇒ 没有 `agent:session` 的岗位
 * （实测：商品管理员 8 码 / 财务 9 码）照样看到「坐席」。修法 = 服务端下发 `mobileTabs`
 * （`MobileSurfaces.visibleTabsFor`），端侧**自绘底栏** + 把原生条收起。
 *
 * ## 判据
 *
 * | # | 判据 | 红证（怎么让它单独变红） |
 * |---|---|---|
 * | 1 | 服务端给 3 项（无 `sessions`）⇒ 底栏**只有 3 格**，`坐席` 那一格不存在 | 端侧仍按静态 4 项渲染 ⇒ 红 |
 * | 2 | 服务端给 4 项 ⇒ 4 格，顺序与标题取服务端 | 端侧自造顺序/标题 ⇒ 红 |
 * | 3 | 🔴 拿不到菜单 ⇒ **照显 4 格**（tab 是功能入口：藏掉用户有的功能更糟） | 把 error 当「一个都没有」⇒ 红 |
 * | 4 | 空清单（服务端答复异常）⇒ 同 3（照显 4 格） | 空清单渲染 0 格 ⇒ 红 |
 * | 5 | 挂载即**收起原生条**（`Taro.hideTabBar({animation:false})`） | 忘了收起 ⇒ 两条底栏叠着 ⇒ 红 |
 * | 6 | 点未选中格 ⇒ `Taro.switchTab({url})`；点当前页 ⇒ 一次都不调 | 点当前页也跳 ⇒ 红 |
 * | 7 | 当前页那一格高亮（`--active`） | 不看当前路由 ⇒ 红 |
 * | 8 | **类级守卫**：服务端 `MobileSurfaces.TABS` ⇄ 端侧镜像 ⇄ `app.config.ts` 的 tabBar 三处逐值 | 改一处不改另一处 ⇒ 红 |
 * | 9 | **类级守卫**：4 个 tab 页都必须接线 `<MerchantTabBar />` | 新加一个 tab 页不接线 ⇒ 红 |
 * | 10 | **类级守卫**：每个 tab 都有**两张不同**的图标文件（选中/未选中） | 两格共用一张图 ⇒ 红（同 BM-031 判据 6） |
 */
import React from 'react'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import * as fs from 'fs'
import * as path from 'path'
import Taro from '@tarojs/taro'

jest.mock('../src/utils/request', () => ({
  get: jest.fn(),
  post: jest.fn(),
  put: jest.fn(),
  patch: jest.fn(),
  del: jest.fn(),
}))

import { get } from '../src/utils/request'
import MerchantTabBar from '../src/components/MerchantTabBar'
import { ALL_MERCHANT_TABS, TAB_ICONS } from '../src/components/merchantTabs'

const mockGet = get as jest.MockedFunction<typeof get>
const mockTaro = Taro as unknown as {
  hideTabBar: jest.Mock
  switchTab: jest.Mock
  getCurrentInstance: jest.Mock
}

/** 服务端 4 项（`key`/`title`/`route` 逐字 = `UserInfoResponse.MobileSurface`） */
const SERVER_ALL = [
  { key: 'chat', title: '问黄金策', route: '/pages/chat/index/index' },
  { key: 'dashboard', title: '数据', route: '/pages/dashboard/index/index' },
  { key: 'sessions', title: '坐席', route: '/pages/sessions/index/index' },
  { key: 'profile', title: '我的', route: '/pages/profile/index/index' },
]

/** 服务端 3 项（无 `agent:session` 的岗位：商品管理员 / 财务的实测形态） */
const SERVER_NO_SESSIONS = SERVER_ALL.filter((tab) => tab.key !== 'sessions')

/** 网络层桩：`/me` 给底栏；`null` = 拉不到 */
function stubNetwork(tabs: typeof SERVER_ALL | null) {
  mockGet.mockImplementation(async (url: string) => {
    if (url === '/api/auth/me') {
      if (tabs === null) throw Object.assign(new Error('Request failed with status 500'), { statusCode: 500 })
      return { success: true, data: { permissions: ['*'], mobileSurfaces: [], mobileTabs: tabs } } as any
    }
    return { success: true, data: [] } as any
  })
}

const keys = () =>
  screen.queryAllByTestId(/^merchant-tab-/, { exact: false }).map((el) => el.getAttribute('data-testid'))

beforeEach(() => {
  jest.clearAllMocks()
  stubNetwork(SERVER_ALL)
})

describe('底栏渲染 = 服务端下发的 mobileTabs', () => {
  it('🔴 服务端给 3 项（无 session 码的岗位）⇒ 底栏只有 3 格，「坐席」那一格不存在', async () => {
    stubNetwork(SERVER_NO_SESSIONS)
    render(<MerchantTabBar />)

    await waitFor(() => expect(screen.getByTestId('merchant-tab-chat')).toBeTruthy())
    await waitFor(() => expect(screen.queryByTestId('merchant-tab-sessions')).toBeNull())

    expect(keys()).toEqual([
      'merchant-tab-chat',
      'merchant-tab-dashboard',
      'merchant-tab-profile',
    ])
  })

  it('服务端给 4 项 ⇒ 4 格，标题与顺序都取服务端', async () => {
    render(<MerchantTabBar />)

    await waitFor(() => expect(screen.getByTestId('merchant-tab-profile')).toBeTruthy())
    expect(keys()).toEqual([
      'merchant-tab-chat',
      'merchant-tab-dashboard',
      'merchant-tab-sessions',
      'merchant-tab-profile',
    ])
    expect(screen.getByText('坐席')).toBeTruthy()
  })

  it('🔴 拿不到菜单 ⇒ **照显 4 格**（tab 是功能入口，不静默藏掉用户有的功能）', async () => {
    stubNetwork(null)
    render(<MerchantTabBar />)

    await waitFor(() => expect(mockGet).toHaveBeenCalledWith('/api/auth/me', expect.anything()))
    await waitFor(() => expect(keys()).toHaveLength(4))
    expect(screen.getByTestId('merchant-tab-sessions')).toBeTruthy()
  })

  it('空清单（服务端答复异常）⇒ 同「拿不到」：照显 4 格', async () => {
    stubNetwork([])
    render(<MerchantTabBar />)

    await waitFor(() => expect(mockGet).toHaveBeenCalledWith('/api/auth/me', expect.anything()))
    await waitFor(() => expect(keys()).toHaveLength(4))
  })

  it('挂载即**收起原生条**（否则两条底栏叠在一起）', async () => {
    render(<MerchantTabBar />)
    await waitFor(() => expect(mockTaro.hideTabBar).toHaveBeenCalledWith({ animation: false }))
  })

  it('点未选中的那一格 ⇒ switchTab 到服务端给的路由；点当前页 ⇒ 一次都不调', async () => {
    render(<MerchantTabBar current='chat' />)
    await waitFor(() => expect(screen.getByTestId('merchant-tab-dashboard')).toBeTruthy())

    fireEvent.click(screen.getByTestId('merchant-tab-dashboard'))
    await waitFor(() =>
      expect(mockTaro.switchTab).toHaveBeenCalledWith({ url: '/pages/dashboard/index/index' }),
    )

    // 当前页（chat）那一格点了不动 —— 避免无意义的重载
    mockTaro.switchTab.mockClear()
    fireEvent.click(screen.getByTestId('merchant-tab-chat'))
    expect(mockTaro.switchTab).not.toHaveBeenCalled()
  })

  it('当前页那一格高亮（`--active`）', async () => {
    render(<MerchantTabBar current='dashboard' />)

    await waitFor(() => expect(screen.getByTestId('merchant-tab-dashboard')).toBeTruthy())
    expect(screen.getByTestId('merchant-tab-dashboard').className).toContain('merchant-tabbar__item--active')
    expect(screen.getByTestId('merchant-tab-chat').className).not.toContain('merchant-tabbar__item--active')
  })
})

// ══════════════════════════════════════════════════════════════════════════
// 类级守卫（issue #6574 铁律 8：一条缺陷只修一处 = 没修）
// ══════════════════════════════════════════════════════════════════════════

const BMINI_ROOT = path.resolve(__dirname, '..')
const REPO_ROOT = path.resolve(BMINI_ROOT, '..', '..')
const MOBILE_SURFACES_JAVA =
  'backend/admin-api/src/main/java/com/migao/admin/service/MobileSurfaces.java'

/** 现取服务端**底栏**清单（`TABS = List.of(…)` 段，**不是** `ALL` 段） */
function serverTabs(): { key: string; title: string; route: string | null; code: string | null }[] {
  const text = fs.readFileSync(path.join(REPO_ROOT, MOBILE_SURFACES_JAVA), 'utf8')
  const block = text.split('public static final List<Surface> TABS = List.of(')[1]
  if (!block) throw new Error('拿不到 `TABS` 段（改结构了？判据不许静默跳过）')
  const body = block.split(');')[0]
  const rows: { key: string; title: string; route: string | null; code: string | null }[] = []
  const re = /new Surface\("([^"]+)",\s*"([^"]+)",\s*(null|"[^"]*"),\s*(null|"[^"]*")\)/g
  let match: RegExpExecArray | null
  while ((match = re.exec(body))) {
    rows.push({
      key: match[1],
      title: match[2],
      route: match[3] === 'null' ? null : match[3].slice(1, -1),
      code: match[4] === 'null' ? null : match[4].slice(1, -1),
    })
  }
  return rows
}

/** 现取 `app.config.ts` 的 tabBar 列表（`pagePath` + `text`） */
function appConfigTabBar(): { route: string; title: string }[] {
  const text = fs.readFileSync(path.join(BMINI_ROOT, 'src/app.config.ts'), 'utf8')
  const block = text.split('tabBar: {')[1]?.split('\n  },')[0]
  if (!block) throw new Error('拿不到 `app.config.ts` 的 tabBar 段')
  const rows: { route: string; title: string }[] = []
  const re = /pagePath: '([^']+)',\s*\n\s*text: '([^']+)'/g
  let match: RegExpExecArray | null
  while ((match = re.exec(block))) rows.push({ route: `/${match[1]}`, title: match[2] })
  return rows
}

describe('类级守卫：底栏清单三处同源（服务端 ⇄ 端侧镜像 ⇄ 静态配置）', () => {
  it('反空跑：服务端 TABS 与 app.config 的 tabBar 都现取到了 4 项', () => {
    expect(serverTabs()).toHaveLength(4)
    expect(appConfigTabBar()).toHaveLength(4)
  })

  it('服务端 TABS ⇄ 端侧 ALL_MERCHANT_TABS（key/title/route 逐值）', () => {
    expect(serverTabs().map((t) => ({ key: t.key, title: t.title, route: t.route }))).toEqual(
      ALL_MERCHANT_TABS.map((t) => ({ key: t.key, title: t.title, route: t.route })),
    )
  })

  it('服务端 TABS ⇄ app.config.ts 的 tabBar（route/title 逐值）', () => {
    expect(serverTabs().map((t) => ({ route: t.route, title: t.title }))).toEqual(appConfigTabBar())
  })

  it("🔴 4 个 tab 页都必须接线 `<MerchantTabBar current='<自己的 key>' />`（不接线 / 传错 key ⇒ 红）", () => {
    const wrong = serverTabs().filter((tab) => {
      if (!tab.route) return true
      const file = path.join(BMINI_ROOT, `src/${tab.route.slice(1)}.tsx`)
      if (!fs.existsSync(file)) return true
      // 选中态由**页面自己**传 key（不读路由：首帧可能拿不到 ⇒ 选中态永不亮，几何腿实测过这一形态）
      return !fs.readFileSync(file, 'utf8').includes(`<MerchantTabBar current='${tab.key}' />`)
    })
    expect(wrong).toEqual([])
  })

  it('每个 tab 都有两张图标（选中 / 未选中），且声明里是 8 个互不相同的 png', () => {
    ALL_MERCHANT_TABS.forEach((tab) => {
      const icon = TAB_ICONS[tab.key]
      // jest 把 png mock 成同一个模块 ⇒ 这里只能判**声明**（有没有两张）；
      // 「四张图标渲染出来两两不同」由几何腿核验（tests/e2e/specs/bmini/bmini-tabbar.spec.ts 判据 6）
      expect({ key: tab.key, hasTwo: !!icon?.normal && !!icon?.active }).toEqual({
        key: tab.key,
        hasTwo: true,
      })
    })
    const sources = fs.readFileSync(path.join(BMINI_ROOT, 'src/components/merchantTabs.ts'), 'utf8')
    const imported = Array.from(sources.matchAll(/from '\.\.\/assets\/tabbar\/([^']+)'/g)).map((m) => m[1])
    expect(imported).toHaveLength(8)
    expect(new Set(imported).size).toBe(8)
    expect(imported.filter((file) => file.includes('-active'))).toHaveLength(4)
  })
})
