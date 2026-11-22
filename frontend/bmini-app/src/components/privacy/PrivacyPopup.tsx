/**
 * 微信隐私授权弹窗（选中的照片或视频信息 / 摄像头 / 麦克风）
 *
 * 文案**逐字等于小程序后台申报的《用户隐私保护指引》**（不要改写）：改名/改口径 ⇒ 申报内容与
 * 代码不符，本身就是审核驳回理由。
 *
 * ## 挂载口径（见 `tests/privacy-authorization.test.tsx` 的挂载判据）
 *
 * 弹窗**不是**在 `app.tsx` 里渲染的：Taro 的小程序端 `App` 只负责把**页面**挂进各自的根节点，
 * 在 `App` 里多渲染的兄弟节点没有页面归属 ⇒ 界面**上看不到**（App 里只做 `setupPrivacyAuthorization()`
 * 的一次性注册）。因此弹窗挂在**每一个可能触发隐私接口的页面**里 —— 那一组页面由判据**现取**
 * （「页面 → 传递依赖 → `Taro.chooseImage` / `scanCode` / `getRecorderManager`」），不是手抄清单。
 *
 * ## 只留一个 `open-type` 按钮
 *
 * 「同意并继续」必须是 `<Button openType='agreePrivacyAuthorization' id='agree-btn'>`：微信在
 * `resolve({ event: 'agree', buttonId })` 时校验**该 id 的按钮确实被点击过**。「暂不同意」是普通按钮
 * （走 `resolvePrivacy(false)`），不得给 `open-type`，否则平台会把它也当成同意按钮。
 */
import { useEffect, useState } from 'react'
import { Button, Text, View } from '@tarojs/components'
import {
  AGREE_BUTTON_ID,
  openPrivacyContract,
  resolvePrivacy,
  subscribePrivacy,
} from '../../utils/privacy'
import './PrivacyPopup.scss'

export const PRIVACY_TITLE = '隐私保护提示'
export const PRIVACY_INTRO = '为了完成扫码、拍照与语音输入，我们需要在下列场景使用你的信息：'
/** 三条用途：与后台申报的三类信息**一一对应**（照片或视频 / 摄像头 / 麦克风） */
export const PRIVACY_ITEMS = [
  '选中的照片或视频信息：用于入库、出库、盘点、返修补打的现场照片记录，以及 AI 识图问答（仅在你主动选择时读取）',
  '摄像头：用于扫描产品与水洗唛上的二维码/条码，以及拍摄作业现场照片',
  '麦克风：用于语音输入转文字（按住说话时录音，松开即停止）',
]
export const PRIVACY_CONTRACT_LINK = '查看完整《隐私保护指引》'
export const PRIVACY_REFUSE_NOTE = '不同意不影响你浏览，但无法使用扫码、拍照与语音功能。'

export default function PrivacyPopup() {
  const [needAuthorization, setNeedAuthorization] = useState(false)

  // 订阅「需要授权」状态：**由 utils/privacy 的模块级状态驱动**（不是本组件自己判隐私接口）
  useEffect(() => subscribePrivacy(setNeedAuthorization), [])

  if (!needAuthorization) return null

  return (
    <View className='privacy-popup' data-testid='privacy-popup'>
      {/* 遮罩：**不可点穿 / 不可点关** —— 授权是显式选择，点空白处不表态 */}
      <View className='privacy-popup__mask' />
      <View className='privacy-popup__panel'>
        <Text className='privacy-popup__title'>{PRIVACY_TITLE}</Text>
        <Text className='privacy-popup__intro'>{PRIVACY_INTRO}</Text>
        {PRIVACY_ITEMS.map((item) => (
          <View className='privacy-popup__item' key={item}>
            <Text className='privacy-popup__item-text'>{item}</Text>
          </View>
        ))}
        <Text
          className='privacy-popup__contract'
          data-testid='privacy-contract-link'
          onClick={openPrivacyContract}
        >
          {PRIVACY_CONTRACT_LINK}
        </Text>
        <Text className='privacy-popup__refuse-note'>{PRIVACY_REFUSE_NOTE}</Text>
        <Button
          className='privacy-popup__agree'
          id={AGREE_BUTTON_ID}
          data-testid='privacy-agree'
          openType='agreePrivacyAuthorization'
          onAgreePrivacyAuthorization={() => resolvePrivacy(true)}
        >
          同意并继续
        </Button>
        <Button
          className='privacy-popup__disagree'
          data-testid='privacy-disagree'
          onClick={() => resolvePrivacy(false)}
        >
          暂不同意
        </Button>
      </View>
    </View>
  )
}
