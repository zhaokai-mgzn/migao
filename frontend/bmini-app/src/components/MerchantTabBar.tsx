/**
 * B 端底栏（**4 项一律可见**，用户 2026-10-18 裁定）
 *
 * ## 为什么自己画一条底栏
 *
 * 微信小程序 / Taro 的 `tabBar` 是**构建期静态配置**：`Taro.setTabBarItem` 只能改文字与图标。
 * 本组件自绘一条底栏 + 把原生条收起来（`Taro.hideTabBar`），在原生条占的那一条
 * （`50px + 安全区`）里画自己的内容 ⇒ 导航与高度模型都不动（`app.config.ts` 的 `tabBar` 保留：
 * `Taro.switchTab` 只能落 tabBar 页，h5 的页面高度算式也依赖它）。
 *
 * ## 可见性口径（用户 2026-10-18 逐字裁定）
 *
 * 「跟问黄金策那个菜单一样都可见，参考问黄金策那个菜单的做法即可」⇒ 底栏 4 项
 * （问黄金策 / 数据 / 坐席 / 我的）**一律可见**，不再按权限删格；旧口径
 * （issue #6574「1，按权限隐藏」）按本裁定退场。
 *
 * 🔴 这**不是授权放宽**：数据面仍由服务端 `@RequirePermission` 拦（如移动坐席要求 `agent:session`），
 * 页面自己给「无权限」引导；底栏只是**导航**，不替服务端判可见性。
 * 服务端下发的 `mobileTabs` 仍用来取**标题**（文案不端侧自造），顺序取静态表
 * （= `MobileSurfaces.TABS` = `app.config.ts` tabBar 的逐值镜像）。
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
  // 🔴 用户 2026-10-18 裁定：4 项**一律可见**（与「问黄金策」一致），不按权限删格。
  // 服务端清单只用来取**标题**；顺序取静态表（= 服务端 TABS 的逐值镜像）。
  // 改前按 `mobileTabs` 删格 ⇒ 加载中先画 4 格、答复回来再缩成 3 格（用户实测
  // 「没有坐席权限也能看到坐席，点进去后坐席又消失」）—— 那段三态兜底随本裁定一起退场：
  // 可见性不再依赖那次 fetch，也就不存在「先出现再消失」。
  const titleByKey = new Map(serverTabs.map((tab) => [tab.key, tab.title]))
  const tabs: MerchantTab[] = ALL_MERCHANT_TABS.map((tab) => {
    const title = titleByKey.get(tab.key)
    return title ? { ...tab, title } : tab
  })

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