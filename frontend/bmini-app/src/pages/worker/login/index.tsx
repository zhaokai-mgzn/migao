import { useCallback, useState } from 'react'
import { View, Text, Button, Input } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { workerLogin } from '../../../services/workerService'
import './index.scss'

/**
 * 工人登录页（issue #4733）：**工号 + PIN**。
 *
 * <p>主路径**不依赖微信**（设计 §2.1 裁定③）：车间 PAD 是普通浏览器/普通设备，没有微信授权；
 * 微信网页授权今天还是 501 占位（`AuthService.buildWechatH5AuthorizeUrl`），且**不得**成为唯一路径。</p>
 *
 * <p>与商家登录页（`pages/auth/login`）是**两条完全不同的链路**：那边走微信授权手机号 + 员工 JWT，
 * 这边走工号 + PIN + 工人 session；工人拿不到商家权限（服务端把 `worker` 放进
 * `/api/admin/**` 的拒绝集合）。</p>
 */
export default function WorkerLoginPage() {
  const [workerNo, setWorkerNo] = useState('')
  const [pin, setPin] = useState('')
  const [deviceLabel, setDeviceLabel] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  const submit = useCallback(async () => {
    if (!workerNo.trim() || !pin.trim()) {
      setError('请输入工号与 PIN')
      return
    }
    if (submitting) return
    setSubmitting(true)
    setError('')
    try {
      const res = await workerLogin(workerNo.trim(), pin.trim(), deviceLabel.trim() || undefined)
      if (!res.success) {
        setError(res.message || '登录失败，请重试')
        return
      }
      Taro.showToast({ title: `已登录：${res.data?.worker_name || workerNo}`, icon: 'success' })
      Taro.navigateBack({ delta: 1 })
    } finally {
      setSubmitting(false)
    }
  }, [workerNo, pin, deviceLabel, submitting])

  return (
    <View className='worker-login'>
      <Text className='worker-login__title'>工人登录</Text>
      <Text className='worker-login__subtitle'>
        用工号 + PIN 登录，登录后每笔报工都记到这个人头上
      </Text>

      <Input
        className='worker-login__input'
        type='text'
        placeholder='工号'
        value={workerNo}
        onInput={(event) => setWorkerNo(event.detail.value)}
      />
      <Input
        className='worker-login__input'
        password
        placeholder='PIN'
        value={pin}
        onInput={(event) => setPin(event.detail.value)}
      />
      <Input
        className='worker-login__input'
        type='text'
        placeholder='设备标签（可选，如 PAD-车间-01）'
        value={deviceLabel}
        onInput={(event) => setDeviceLabel(event.detail.value)}
      />

      {error ? <Text className='worker-login__error'>{error}</Text> : null}

      <Button className='worker-login__submit' loading={submitting} onClick={submit}>
        登录
      </Button>

      <Text className='worker-login__hint'>
        共用 PAD：干完活请点「切换工人」或用完登出；闲置会自动登出
      </Text>
    </View>
  )
}
