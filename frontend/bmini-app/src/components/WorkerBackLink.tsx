/**
 * 工人端子页的「返回」入口（issue #8657）。
 *
 * <p>病：工人端页面在**手机浏览器 / 微信 / 手持标签机的全屏 WebView** 里打开时没有系统返回键
 * （终端是 kiosk 全屏、小程序子页也没有可见的返回条），工人做完一件事想回工作台只能靠
 * 手势或杀掉重进 —— 车间现场反复踩。</p>
 *
 * <p>行为分两种，都**不许静默失败**：</p>
 * <ol>
 *   <li>有上一页（正常从工作台点进来）⇒ {@code navigateBack}，回到原来那屏（可能带着扫码上下文）；</li>
 *   <li>没有历史（扫码短链 / 直接打开子页 / 终端冷启动落到子页）⇒ {@code reLaunch} 到工人工作台 ——
 *       「返回」在这里的语义是「回上一层」，不是「假装点了但什么都没发生」。</li>
 * </ol>
 */
import { useCallback } from 'react'
import { View, Text } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { WORKER_HOME_ROUTE } from '../utils/inbound/gaps'
import './WorkerBackLink.scss'

interface Props {
  /** 供页面测试定位（缺省 `worker-back`）。 */
  testId?: string
}

export function WorkerBackLink({ testId = 'worker-back' }: Props) {
  const goBack = useCallback(() => {
    const pages = typeof Taro.getCurrentPages === 'function' ? Taro.getCurrentPages() : []
    if (Array.isArray(pages) && pages.length > 1) {
      void Taro.navigateBack({ delta: 1 })
      return
    }
    void Taro.reLaunch({ url: WORKER_HOME_ROUTE })
  }, [])

  return (
    <View className='worker-back' data-testid={testId} onClick={goBack}>
      <Text className='worker-back__chevron'>‹</Text>
      <Text className='worker-back__text'>返回</Text>
    </View>
  )
}
