/**
 * B 端底栏（**按岗位权限裁剪**）—— issue #6574（用户 2026-10-08 逐字「**1，按权限隐藏**」）
 *
 * ## 为什么自己画一条底栏
 *
 * 微信小程序 / Taro 的 `tabBar` 是**构建期静态配置**：`Taro.setTabBarItem` 只能改文字与图标，
 * **不能按角色删掉某一格**（`hideTabBar` 只能整条收起）。⇒ 要「无 `agent:session` 的岗位不出现坐席」
 * 就得自己渲染底栏。
 *
 * ## 与既有架构契约的关系（不砍）
 *
 * `app.config.ts` 的 `tabBar` **保留不动**：① `Taro.switchTab` 只能落 tabBar 页；
 * ② Taro h5 的 `.taro_page.taro_tabbar_page{max-height: calc(100vh - var(--taro-tabbar-height) - env(safe-area-inset-bottom))}`
 * 页面高度算式依赖它。本组件的做法 = **把原生条收起来**（`Taro.hideTabBar`）+ 在原生条占的那一条
 * （`50px + 安全区`）里画自己的内容 ⇒ 导航与高度模型都不动。
 *
 * ## 可见性口径（服务端说了算）
 *
 * 渲染 `GET /api/auth/me` 的 `mobileTabs`（服务端 `MobileSurfaces.visibleTabsFor`）。端侧不判权限码。
 * 🔴 **拿不到菜单 / 服务端给了空清单 ⇒ 照显全部 4 项**：tab 是功能入口，藏掉用户有的功能比露出一个
 * 点进去 403 的入口更糟（与「数据」页待办块 `error ⇒ 照渲染` 同一条规则；显式错误行 + 重试在「我的」页）。
 */
import { useEffect } from 'react'
import { View, Text, Image } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { useMobileMenu } from './admin/useMobileMenu'
import { ALL_MERCHANT_TABS, TAB_ICONS, type MerchantTab } from './merchantTabs'
import './MerchantTabBar.scss'

/**
 * @param current 本页对应的 tab key（**由页面自己传**，见下）
 */
export default function MerchantTabBar({ current = '' }: { current?: string } = {}) {
  const menu = useMobileMenu()

  // 服务端下发的 tab（`route` 缺键的项画不成底栏格 ⇒ 滤掉；当前清单里 4 项都带 route）
  const serverTabs: MerchantTab[] = menu.tabs
    .filter((tab) => !!tab.route)
    .map((tab) => ({ key: tab.key, title: tab.title, route: tab.route as string }))
  const tabs: MerchantTab[] =
    menu.state === 'ok' && serverTabs.length > 0 ? serverTabs : ALL_MERCHANT_TABS

  // 原生条收起来（内容由本组件决定）。**只用 useEffect**（不是 `useDidShow`）：
  // ① h5 侧原生条是启动时建一次、常驻的 DOM ⇒ 挂载时收一次就够；
  // ② `useDidShow` 在**子组件**里的语义不保证（它是页面级 hook）⇒ 不拿它当唯一保险。
  useEffect(() => {
    Taro.hideTabBar({ animation: false }).catch(() => {})
  }, [])

  // 选中态：**由页面自己传 `current`**（`<MerchantTabBar current='sessions' />`），不读路由 ——
  // Taro 的 `useRouter()` / `Taro.getCurrentInstance().router` 在**首帧**都可能还没挂上 ⇒ 选中态永不亮
  // （几何腿实测过这一形态：`.merchant-tabbar__item` 上从来没有 `--active`）。页面传自己的 key 更稳，
  // 且「页面 ≠ 自己的 key」由类级守卫钉住（tests/merchant-tabbar.test.tsx 判据 7）。

  const go = (tab: MerchantTab, active: boolean) => {
    if (active) return
    // 切页后再收一次：小程序侧原生条可能在切 tab 时被重新显出来
    Taro.switchTab({ url: tab.route })
      .then(() => Taro.hideTabBar({ animation: false }))
      .catch(() => {})
  }

  return (
    <View className='merchant-tabbar' data-testid='merchant-tabbar'>
      {tabs.map((tab) => {
        const active = current !== '' && tab.key === current
        const icon = TAB_ICONS[tab.key]
        return (
          <View
            key={tab.key}
            className={
              'merchant-tabbar__item' + (active ? ' merchant-tabbar__item--active' : '')
            }
            data-testid={`merchant-tab-${tab.key}`}
            onClick={() => go(tab, active)}
          >
            <Image
              className='merchant-tabbar__icon'
              src={active ? icon?.active : icon?.normal}
            />
            <Text className='merchant-tabbar__label'>{tab.title}</Text>
          </View>
        )
      })}
    </View>
  )
}