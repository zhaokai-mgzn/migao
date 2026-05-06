/**
 * 全局错误处理
 *
 * 捕获未处理的异常和 Promise 拒绝，统一日志输出
 */

import Taro from '@tarojs/taro'

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
    } else {
      Taro.showToast({
        title: '网络已恢复',
        icon: 'success',
        duration: 2000,
      })
    }
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
