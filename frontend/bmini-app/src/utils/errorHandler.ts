/**
 * 全局错误处理
 *
 * 捕获未处理的异常和 Promise 拒绝，统一日志输出
 */

import Taro from '@tarojs/taro'
import { flushPendingReports, type FlushResult } from './productionOffline'

/**
 * 初始化全局错误处理器
 * 在 App 启动时调用一次
 */
export function setupErrorHandler(): void {
  // 监听小程序全局错误
  Taro.onError?.((error) => {
    console.error('【全局错误】', error)
  })

  // 监听未处理的 Promise 拒绝
  Taro.onUnhandledRejection?.((res) => {
    console.error('【未处理的 Promise 拒绝】', res.reason)
  })
}

/**
 * 补传结果一句话（issue #4206）：工人必须知道「补上了几条 / 哪条被拒 / 还剩几条」——
 * 静默丢弃 = 丢单，而丢单的报工是**计件工资的凭证**（真值源 §4/§5）。
 */
function flushSummary(result: FlushResult): string {
  const parts: string[] = []
  if (result.sent.length > 0) parts.push(`已补传 ${result.sent.length} 条报工`)
  if (result.rejected.length > 0) {
    parts.push(`补传被拒：${result.rejected[0].operationName}（${result.rejected[0].message}）`)
  }
  if (result.remaining > 0) parts.push(`仍有 ${result.remaining} 条待补传`)
  return parts.join('；')
}

/**
 * 初始化网络状态监听
 * 断网时弹 toast 提醒，恢复时也提示
 */
export function setupNetworkListener(): void {
  // 监听网络状态变化
  Taro.onNetworkStatusChange((res) => {
    if (!res.isConnected) {
      Taro.showToast({
        title: '网络连接已断开',
        icon: 'none',
        duration: 3000,
      })
      return
    }
    Taro.showToast({
      title: '网络已恢复',
      icon: 'success',
      duration: 2000,
    })
    // 弱网降级（issue #4206）：网络恢复 ⇒ 自动补传离线报工。
    // 复用入队时的幂等键 ⇒ 服务端只落一次（不会重复计件）。
    void flushPendingReports()
      .then((result) => {
        if (result.sent.length > 0 || result.rejected.length > 0 || result.remaining > 0) {
          Taro.showToast({ title: flushSummary(result), icon: 'none', duration: 3000 })
        }
      })
      .catch((error) => {
        console.error('【离线报工补传】失败', error)
      })
  })

  // 获取初始网络状态
  Taro.getNetworkType({
    success: (res) => {
      if (res.networkType === 'none') {
        Taro.showToast({
          title: '当前无网络连接',
          icon: 'none',
          duration: 3000,
        })
      }
    },
  })
}
