/**
 * 商家面身份护栏（issue #6567）—— **工人设备不进商家页**
 *
 * ## 治的形态
 * 工人用「工号 + PIN」登录后落在工人工作台（`pages/worker/home/index`，issue #6467）。但那是
 * **登录后的落点**：工人设备仍可以用网址 / 二维码 / 收藏打开任何一个**商家页**
 * （`pages/dashboard`、`pages/profile`、`pages/admin/**` …）—— 机器上只有工人 session、
 * 没有商家凭据，那些页只会一路 403 / 空页，工人看到的是一堆「无权限」。
 *
 * ## 判据（三个记号缺一不可，别只用其中一个）
 * ① `hasWorkerSession()` = 本机有工人 session（`worker_session_id`）；
 * ② **没有**商家凭据（`auth_token` + `auth_user` 都为空）—— 有商家凭据时**不跳**（负控：
 *    共用 PAD 上「先工人登录、再商家登录」是正常动线，把商家踢走是这台机器上最贵的 bug）；
 * ③ 只在**商家面**页面上挂（本 hook）；工人页（`pages/production/**` 双身份页、`pages/worker/**`）
 *    **不许**挂 —— 否则工人打开自己的页面会被弹回工作台。
 *
 * 判据：`frontend/bmini-app/tests/role-guard.test.tsx`（实例 + 商家页清单的类级守卫）。
 */
import { useEffect } from 'react'
import Taro from '@tarojs/taro'
import { getToken, getUser } from './auth'
import { WORKER_HOME_ROUTE } from './inbound/gaps'
import { hasWorkerSession } from './workerSession'

/**
 * 本机是不是**纯工人设备**：有工人 session、且没有任何商家凭据。
 *
 * 读的是**同步落盘**的凭据（`utils/auth.ts` 的 `getToken` / `getUser`），不是 store 里的
 * `isLoggedIn` —— 后者要等 `app.tsx` 的 `initialize()` 跑完才为真，页面挂载那一刻读它会把
 * 「商家刚登录」误判成「没有商家会话」（同一次启动内的竞态）。
 */
export function isWorkerOnlyDevice(): boolean {
  return hasWorkerSession() && !(getToken() && getUser())
}

/** 商家面页面挂上它：纯工人设备打开 ⇒ 送回工人工作台（`redirectTo`，工作台不是 tabBar 页） */
export function useMerchantSurfaceGuard(): void {
  useEffect(() => {
    if (isWorkerOnlyDevice()) {
      Taro.redirectTo({ url: WORKER_HOME_ROUTE })
    }
  }, [])
}

export default { isWorkerOnlyDevice, useMerchantSurfaceGuard }
