import { useEffect, useRef, PropsWithChildren } from 'react'
import Taro from '@tarojs/taro'
import { useAuthStore } from './store/authStore'
import { setupErrorHandler, setupNetworkListener } from './utils/errorHandler'
import { reprintLandingUrl, reportLandingUrl } from './utils/inbound/deepLink'
import { currentEntryLanding } from './utils/reportEntry'
import './app.scss'

function App({ children }: PropsWithChildren) {
  const initialized = useRef(false)

  useEffect(() => {
    if (initialized.current) return
    initialized.current = true

    // 初始化全局错误处理
    setupErrorHandler()

    // 初始化网络状态监听
    setupNetworkListener()

    // 初始化认证状态（异步：exp 过期时先续期，issue #7249）
    void useAuthStore.getState().initialize()

    // 🔴 **落地页深链**（issue #5052 实现 PR；设计 §5.4）：纸上的码
    // `https://app.migaozn.com/i/<短码>` 由服务端 302 到 `/b/?code=<短码>&tenant_id=…`，
    // 而修复前**没有任何人读那个 `code`** ⇒ 工人扫了自家标签、停在商家首页，
    // 而且没有任何东西会变红（码是好的、302 是好的、页面也不报错）。
    // 这里只做**搬运**：把码原样交给补打页 —— 码空间判定（入库 / 洗水码 / 陌生码）、
    // 「这不是观星台的标签」、以及"一次都不查入库详情"都在页面与 `utils/inbound/deepLink.ts` 里。
    // `tenant_id` **刻意不用**：租户判定权威始终在服务端（跨租户 ⇒ 404，`requirePrintableLabel`），
    // 前端拿它去"决定看哪张单"就是把授权判据搬到客户端。
    //
    // 🔴 **扫码/报工落地**（issue #7879；用户 2026-10-27 逐字「把跳转链接 /w 改成 /b，统一进手机端页面，
    // 不要再出现 /w 路径」+「扫码报工页面也要进入小程序，和手机端都应该一套」）：纸上的码
    // `…/s/<短码>`（加工单级 `/o/<短码>`）由服务端 302 到 `/b/?t=<token>&tenant_id=…&tenant_code=…`；
    // 小程序侧则由微信把整条链接放进 `getEnterOptionsSync().query.q`（A 档「扫普通链接二维码打开小程序」）。
    // 改前 `/b/` 上**没有任何人读那个 `t`** ⇒ 工人扫开自家纸上的码只会停在商家首页
    // （与上面 `?code=` 同一种静默失败，且不会有任何东西变红）。
    // 这里只做**分流 + 搬运**：两种入口（h5 URL / 小程序进入参数）**都**走
    // `utils/scanInput.ts` 的同一个 `resolveScanLanding`（入口模块 = `utils/reportEntry.ts`，
    // 平台分支只住在那儿）；一屏 / 报工 / 回执全在报工页与服务端。
    // `t`（报工）与 `code`（入库标签补打）按**参数名**分流、互不串道；两者同时出现时以 `t` 为准
    // （`t` 只由报工的 302 产出，指向一个部位；`code` 只由入库标签的 302 产出）。
    const landing = currentEntryLanding()
    if (landing.kind === 'report') {
      Taro.redirectTo({ url: reportLandingUrl(landing.code) })
    } else if (landing.kind === 'reprint') {
      Taro.redirectTo({ url: reprintLandingUrl(landing.code) })
    }
  }, [])

  return children
}

export default App
