import { useCallback, useEffect, useState } from 'react'
import { View, Text, Button, Input } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { useAuthStore } from '../../../store/authStore'
import { sendSmsCode } from '../../../utils/auth'
import './index.scss'

/** 两个登录入口：员工（用户名@企业编码 + 密码）/ 管理员（手机号 + 短信验证码） */
type LoginTab = 'employee' | 'admin'

/** 「获取验证码」的本地冷却秒数（服务端另有频控：每号 1 次/60s + 每日上限） */
const CODE_COUNTDOWN_SECONDS = 60

/**
 * B 端登录页（米宝商家端）
 *
 * 1. **员工入口**（issue #5485）：填「用户名@企业编码」+ 密码 → `employeeLoginAction`
 *    → 后端 `POST /api/auth/employee/login` 由标识里的企业编码解析租户
 *    （前端**不解析租户、不传 tenantId**）。
 * 2. **管理员入口**（issue #5721）：手机号 + 短信验证码 → `smsLoginAction`
 *    → `POST /api/auth/sms/login`。为什么必须有：管理员身份在设计上是「手机号 + 短信」，
 *    而 #5485 之后 H5 只留了员工入口 ⇒ 管理员在**唯一可达的 H5** 上无路可走
 *    （存量账号 `users.username` 为 NULL，员工入口同样进不去）。
 * 3. 成功 → switchTab 到「问米宝」（首页 Tab）；首登强制改密 ⇒ 先去改密页。
 *
 * 原「微信授权手机号 → 跨租户匹配员工 → 绑定 openid → 二次免密」整条退场：
 * 本页**没有** `getPhoneNumber` 授权按钮，`POST /api/auth/bmini/login` 已废弃。
 *
 * 格式 / 账号是否存在 / 角色门禁的判定**单一真值都在后端**（同一文案反枚举）——
 * 这里只挡「空输入」，不复制后端的格式规则或角色判断（否则就是第二套真值）。
 */
export default function LoginPage() {
  const { isLoading, employeeLoginAction, smsLoginAction } = useAuthStore()

  const [tab, setTab] = useState<LoginTab>('employee')

  // 员工入口
  const [identifier, setIdentifier] = useState('')
  const [password, setPassword] = useState('')

  // 管理员入口（issue #5721）
  const [phone, setPhone] = useState('')
  const [code, setCode] = useState('')
  const [countdown, setCountdown] = useState(0)
  const [sendingCode, setSendingCode] = useState(false)

  // 冷却计时：到点自动解锁「获取验证码」
  useEffect(() => {
    if (countdown <= 0) return
    const timer = setTimeout(() => setCountdown(value => value - 1), 1000)
    return () => clearTimeout(timer)
  }, [countdown])

  /**
   * 登录成功后的去向（两个入口共用）。
   * 首登强制改密（`user.mustChangePassword`）：**不放进主界面**，直接送改密页 ——
   * 改密前后端只放行白名单接口，硬进主界面只会让每个功能都 403（用户读成「小程序坏了」）。
   *
   * 注意读的是动作之后的**最新**状态（钩子返回值在本闭包里是旧的）。
   */
  const afterLoginSuccess = useCallback(() => {
    const { user } = useAuthStore.getState()
    if (user?.mustChangePassword) {
      Taro.redirectTo({ url: '/pages/auth/change-password/index' })
      return
    }
    Taro.switchTab({ url: '/pages/chat/index/index' })
  }, [])

  /** 员工登录：空输入在本地拦下（不白跑一次请求），其余交后端判定 */
  const handleEmployeeLogin = useCallback(async () => {
    if (isLoading) return
    if (!identifier.trim() || !password) {
      Taro.showToast({ title: '请输入用户名@企业编码和密码', icon: 'none' })
      return
    }

    const success = await employeeLoginAction(identifier.trim(), password)
    if (!success) return
    afterLoginSuccess()
  }, [identifier, password, isLoading, employeeLoginAction, afterLoginSuccess])

  /** 管理员登录：手机号 + 验证码（角色门禁在服务端，非管理员由服务端回文案） */
  const handleAdminLogin = useCallback(async () => {
    if (isLoading) return
    if (!phone.trim() || !code.trim()) {
      Taro.showToast({ title: '请输入手机号和验证码', icon: 'none' })
      return
    }

    const success = await smsLoginAction(phone.trim(), code.trim())
    if (!success) return
    afterLoginSuccess()
  }, [phone, code, isLoading, smsLoginAction, afterLoginSuccess])

  /** 获取验证码：只挡空输入（格式/频控/是否注册由服务端判），成功后进入本地冷却 */
  const handleSendCode = useCallback(async () => {
    if (sendingCode || countdown > 0) return
    const value = phone.trim()
    if (!value) {
      Taro.showToast({ title: '请先输入手机号', icon: 'none' })
      return
    }

    setSendingCode(true)
    const result = await sendSmsCode(value)
    setSendingCode(false)

    if (!result.success) {
      Taro.showToast({ title: result.error || '验证码发送失败', icon: 'none' })
      return
    }
    setCountdown(CODE_COUNTDOWN_SECONDS)
    Taro.showToast({ title: '验证码已发送', icon: 'none' })
  }, [phone, sendingCode, countdown])

  const handleSubmit = tab === 'employee' ? handleEmployeeLogin : handleAdminLogin

  // 服务条款
  const handleTerms = useCallback(() => {
    Taro.showModal({
      title: '服务条款',
      content: '本应用面向米高平台商家员工，使用即表示同意平台服务条款。',
      showCancel: false,
      confirmText: '我知道了',
    })
  }, [])

  // 隐私协议
  const handlePrivacy = useCallback(() => {
    Taro.showModal({
      title: '隐私协议',
      content: '本应用仅使用您的账号信息完成登录校验，账号信息将严格保密。',
      showCancel: false,
      confirmText: '我知道了',
    })
  }, [])

  return (
    <View className='login-page'>
      {/* 顶部品牌区域 */}
      <View className='login-brand'>
        <View className='login-brand__icon'>
          <Text className='login-brand__icon-text'>米</Text>
        </View>
        {/* AI 角色标签口径见 frontend/admin-web/src/config/ai-roles.ts（issue #6330/#6333）；
            本 App 是独立工程，不跨 App 引共享模块（#6306 教训：落在发布集外 ⇒ 白屏）⇒ 本地字面量 + 测试钉值。 */}
        <Text className='login-brand__title'>米宝 · 企业智能生产管家</Text>
        <Text className='login-brand__subtitle'>经营数据 · AI 客服 · 移动坐席</Text>
      </View>

      {/* 中间登录表单 */}
      <View className='login-form'>
        {/* 两个入口并列（issue #5721）：员工与管理员是两条不同的身份链，不共用一个表单 */}
        <View className='login-tabs'>
          <View
            className={`login-tab ${tab === 'employee' ? 'login-tab--active' : ''}`}
            onClick={() => setTab('employee')}
          >
            <Text className='login-tab__text'>员工登录</Text>
          </View>
          <View
            className={`login-tab ${tab === 'admin' ? 'login-tab--active' : ''}`}
            onClick={() => setTab('admin')}
          >
            <Text className='login-tab__text'>管理员登录</Text>
          </View>
        </View>

        {tab === 'employee' ? (
          <>
            <View className='login-field'>
              <Text className='login-field__label'>用户名@企业编码</Text>
              <Input
                className='login-field__input'
                type='text'
                placeholder='如 zhangsan@acme'
                value={identifier}
                onInput={(e: any) => setIdentifier(e.detail.value)}
              />
            </View>

            <View className='login-field'>
              <Text className='login-field__label'>密码</Text>
              <Input
                className='login-field__input'
                password
                placeholder='请输入密码'
                value={password}
                onInput={(e: any) => setPassword(e.detail.value)}
                onConfirm={handleEmployeeLogin}
              />
            </View>

            <Text className='login-form__hint'>
              账号由企业管理员在管理后台「员工管理」中分配（用户名@企业编码）
            </Text>
          </>
        ) : (
          <>
            <View className='login-field'>
              <Text className='login-field__label'>手机号</Text>
              <Input
                className='login-field__input'
                type='number'
                placeholder='请输入管理员手机号'
                value={phone}
                onInput={(e: any) => setPhone(e.detail.value)}
              />
            </View>

            <View className='login-field'>
              <Text className='login-field__label'>验证码</Text>
              <View className='login-code-row'>
                <Input
                  className='login-field__input login-field__input--code'
                  type='number'
                  placeholder='请输入验证码'
                  value={code}
                  onInput={(e: any) => setCode(e.detail.value)}
                  onConfirm={handleAdminLogin}
                />
                <View
                  className={`login-code-btn ${countdown > 0 ? 'login-code-btn--disabled' : ''}`}
                  onClick={handleSendCode}
                >
                  <Text className='login-code-btn__text'>
                    {countdown > 0 ? `${countdown}s 后重发` : '获取验证码'}
                  </Text>
                </View>
              </View>
            </View>

            <Text className='login-form__hint'>
              企业管理员用手机号 + 短信验证码登录；员工请用「员工登录」
            </Text>
          </>
        )}
      </View>

      {/* 底部操作区域 */}
      <View className='login-actions'>
        <Button
          className={`login-btn ${isLoading ? 'login-btn--loading' : ''}`}
          loading={isLoading}
          disabled={isLoading}
          onClick={handleSubmit}
        >
          {isLoading ? '登录中...' : '登录'}
        </Button>

        <View className='login-agreement'>
          <Text className='login-agreement__text'>
            登录即表示您同意
          </Text>
          <Text className='login-agreement__link' onClick={handleTerms}>
            《服务条款》
          </Text>
          <Text className='login-agreement__text'>和</Text>
          <Text className='login-agreement__link' onClick={handlePrivacy}>
            《隐私协议》
          </Text>
        </View>
      </View>
    </View>
  )
}
