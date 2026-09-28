/**
 * 管理面通用状态块（issue #5654）
 *
 * 🔴 存在的理由：4 个管理面都有同一组**必须互不混淆**的状态，而「无权限」被渲染成空白/转圈
 * 是本单明令要治的形态（管理员在车间看到一片空白，只能以为「店里没事」）。
 * 一个组件 + 一个测试锚点 ⇒ 四处的四态**长得一样、测得一样**。
 *
 * 四态与判据：
 * - `loading`：正在拉数据（**不许**与「没有数据」同形）；
 * - `forbidden`：403 ⇒ 逐字「无「XX」查看权限（需要权限码 …）」（可行动：知道找谁开什么）；
 * - `error`：失败 ⇒ 服务端文案或兜底文案（**不静默**）；
 * - `empty`：**真的有权限**且结果为空 ⇒ 才能说「没有」。
 */
import { View, Text } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { H5_WECHAT_LOGIN_UNAVAILABLE_HINT, isH5 } from '../../utils/platform'

export type SurfaceStateKind = 'loading' | 'forbidden' | 'error' | 'empty'

export interface SurfaceStateProps {
  kind: SurfaceStateKind
  /** 要显示的那句话（`forbidden` 必须是 `missingPermissionText()` 的产出） */
  message: string
}

export function SurfaceState({ kind, message }: SurfaceStateProps) {
  return (
    <View className={`surface-state surface-state--${kind}`} data-testid={`admin-surface-${kind}`}>
      <Text className='surface-state__text'>{message}</Text>
    </View>
  )
}

/**
 * **未登录**态（issue #5654 验收判据：平台能力缺口必须显式）。
 *
 * 🔴 这就是本单 4 个管理面唯一的**平台相关**差异：管理面要的是**商家会话**
 * （JWT 来自 `POST /api/auth/employee/login`），而 h5 下**没有微信登录这条腿**
 * （`Taro.login` 在 taro-h5 是 `temporarilyNotSupport('login')`，见 #5650 的 `platform.ts`）
 * ⇒ 浏览器里没会话时**必须说清「怎么才能进来」**（账号密码），
 * 而不是转圈 / 空白 / 拿一个永远不会成功的微信换码去试。
 */
export function SurfaceLoginRequired() {
  const message = isH5()
    ? H5_WECHAT_LOGIN_UNAVAILABLE_HINT
    : '请先登录后再使用管理功能'
  return (
    <View className='admin-surface'>
      <View className='surface-state surface-state--forbidden' data-testid='admin-surface-login-required'>
        <Text className='surface-state__text'>{message}</Text>
      </View>
      <View className='admin-surface__body'>
        <View
          className='admin-action'
          data-testid='admin-surface-go-login'
          onClick={() => Taro.redirectTo({ url: '/pages/auth/login/index' })}
        >
          <Text>去登录</Text>
        </View>
      </View>
    </View>
  )
}


export default SurfaceState
