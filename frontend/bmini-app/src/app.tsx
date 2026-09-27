import { useEffect, useRef, PropsWithChildren } from 'react'
import Taro from '@tarojs/taro'
import { useAuthStore } from './store/authStore'
import { setupErrorHandler, setupNetworkListener } from './utils/errorHandler'
import { currentLandingCode, reprintLandingUrl } from './utils/inbound/deepLink'
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

    // 初始化认证状态
    useAuthStore.getState().initialize()

    // 🔴 **落地页深链**（issue #5052 实现 PR；设计 §5.4）：纸上的码
    // `https://app.migaozn.com/i/<短码>` 由服务端 302 到 `/b/?code=<短码>&tenant_id=…`，
    // 而修复前**没有任何人读那个 `code`** ⇒ 工人扫了自家标签、停在商家首页，
    // 而且没有任何东西会变红（码是好的、302 是好的、页面也不报错）。
    // 这里只做**搬运**：把码原样交给补打页 —— 码空间判定（入库 / 洗水码 / 陌生码）、
    // 「这不是米高的标签」、以及"一次都不查入库详情"都在页面与 `utils/inbound/deepLink.ts` 里。
    // `tenant_id` **刻意不用**：租户判定权威始终在服务端（跨租户 ⇒ 404，`requirePrintableLabel`），
    // 前端拿它去"决定看哪张单"就是把授权判据搬到客户端。
    const landing = currentLandingCode()
    if (landing.present) {
      Taro.redirectTo({ url: reprintLandingUrl(landing.raw) })
    }
  }, [])

  return children
}

export default App
