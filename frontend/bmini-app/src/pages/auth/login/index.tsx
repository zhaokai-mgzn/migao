import { useCallback, useEffect, useState } from 'react'
import { View, Text, Button, Input } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { useAuthStore } from '../../../store/authStore'
import { sendSmsCode } from '../../../utils/auth'
import { workerLogin } from '../../../services/workerService'
import { WORKER_HOME_ROUTE } from '../../../utils/inbound/gaps'
import './index.scss'

/**
 * 三个登录入口：员工（用户名@企业编码 + 密码）/ 管理员（手机号 + 短信验证码）/
 * **工人**（工号 + PIN，issue #6467 切片 1）
 */
type LoginTab = 'employee' | 'admin' | 'worker'

/** 「获取验证码」的本地冷却秒数（服务端另有频控：每号 1 次/60s + 每日上限） */
const CODE_COUNTDOWN_SECONDS = 60

/**
 * 入口的**路由参数直达**（issue #6467）：`/pages/auth/login/index?tab=worker` 直接停在工人入口。
 *
 * <p>这是给「报工页 / 工人首页 / 入库页引导过来」用的入口 —— 工人在报工页点「去登录工人身份」
 * 时**不该**先落在商家员工表单上再自己找第二个 tab（现场实测：那台设备的人根本不知道
 * 「完成报工」需要的是工人身份）。</p>
 */
function initialTab(routeTab: unknown): LoginTab {
  return routeTab === 'worker' || routeTab === 'admin' ? routeTab : 'employee'
}

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
 * 4. **工人入口**（issue #6467 切片 1）：工号 + PIN（可选设备标签）→ `workerLogin`
 *    → `POST /api/worker/login`（**既有**端点，不新造登录服务）。工人**没有商家会话**
 *    ⇒ 成功只能 `redirectTo` 工人首页（`switchTab` 会落到商家 tabBar/问米宝）。
 *    报工页/工人首页的「去登录工人身份」用 `?tab=worker` 直达本入口。
 *
 * 原「微信授权手机号 → 跨租户匹配员工 → 绑定 openid → 二次免密」整条退场：
 * 本页**没有** `getPhoneNumber` 授权按钮，`POST /api/auth/bmini/login` 已废弃。
 *
 * 格式 / 账号是否存在 / 角色门禁的判定**单一真值都在后端**（同一文案反枚举）——
 * 这里只挡「空输入」，不复制后端的格式规则或角色判断（否则就是第二套真值）。
 */
export default function LoginPage() {
  const { isLoading, employeeLoginAction, smsLoginAction } = useAuthStore()

  // 初始入口按**路由参数**定（issue #6467：报工页/工人首页引导进来时直达工人入口）
  const [tab, setTab] = useState<LoginTab>(() =>
    initialTab((Taro.getCurrentInstance?.() as any)?.router?.params?.tab),
  )

  // 员工入口
  const [identifier, setIdentifier] = useState('')
  const [password, setPassword] = useState('')

  // 管理员入口（issue #5721）
  const [phone, setPhone] = useState('')
  const [code, setCode] = useState('')
  const [countdown, setCountdown] = useState(0)
  const [sendingCode, setSendingCode] = useState(false)

  // 工人入口（issue #6467）
  const [workerNo, setWorkerNo] = useState('')
  const [pin, setPin] = useState('')
  const [deviceLabel, setDeviceLabel] = useState('')
  const [workerSubmitting, setWorkerSubmitting] = useState(false)
  const [workerError, setWorkerError] = useState('')

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

  /**
   * 工人登录（issue #6467）：工号 + PIN（可选「设备标签」）→ **既有** `workerLogin`
   * （`POST /api/worker/login`，`skipAuth`：工人身份不走商家 JWT）。
   *
   * <p>🔴 成功**只能** `redirectTo` 工人首页：工人没有商家会话，`switchTab` 会落到商家 tabBar
   * （问米宝）—— 而工人零商家权限（`/api/admin/**` 拒绝集合含 `worker`）⇒ 落地即 403 / 空页。</p>
   *
   * <p>失败**原样展示服务端 message**：格式 / PIN 是否正确 / 角色门禁的单一真值都在服务端，
   * 前端只挡空输入（否则就是第二套口径）。</p>
   */
  const handleWorkerLoginSubmit = useCallback(async () => {
    if (workerSubmitting) return
    if (!workerNo.trim() || !pin.trim()) {
      Taro.showToast({ title: '请输入工号和 PIN', icon: 'none' })
      return
    }
    setWorkerSubmitting(true)
    setWorkerError('')
    try {
      const res = await workerLogin(workerNo.trim(), pin.trim(), deviceLabel.trim() || undefined)
      if (!res.success) {
        setWorkerError(res.message || '登录失败，请重试')
        return
      }
      Taro.redirectTo({ url: WORKER_HOME_ROUTE })
    } finally {
      setWorkerSubmitting(false)
    }
  }, [workerNo, pin, deviceLabel, workerSubmitting])

  /** 三个入口各自的提交：三条身份链，互不共用表单也不共用动作 */
  const handleSubmit =
    tab === 'employee' ? handleEmployeeLogin : tab === 'admin' ? handleAdminLogin : handleWorkerLoginSubmit

  /** 提交中（工人入口用本地 in-flight 标记；商家两个入口用 store 的 isLoading） */
  const submitting = tab === 'worker' ? workerSubmitting : isLoading

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
        {/* 三个入口并列（issue #5721 / #6467）：员工、管理员、工人是三条不同的身份链，不共用一个表单 */}
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
          <View
            className={`login-tab ${tab === 'worker' ? 'login-tab--active' : ''}`}
            onClick={() => setTab('worker')}
          >
            <Text className='login-tab__text'>工人登录</Text>
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
        ) : tab === 'admin' ? (
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
        ) : (
          <>
            <View className='login-field'>
              <Text className='login-field__label'>工号</Text>
              <Input
                className='login-field__input'
                type='text'
                placeholder='请输入工号'
                value={workerNo}
                onInput={(e: any) => setWorkerNo(e.detail.value)}
              />
            </View>

            <View className='login-field'>
              <Text className='login-field__label'>PIN</Text>
              <Input
                className='login-field__input'
                password
                placeholder='请输入 PIN'
                value={pin}
                onInput={(e: any) => setPin(e.detail.value)}
                onConfirm={handleWorkerLoginSubmit}
              />
            </View>

            <View className='login-field'>
              <Text className='login-field__label'>设备标签（可选）</Text>
              <Input
                className='login-field__input'
                type='text'
                placeholder='设备标签（可选）'
                value={deviceLabel}
                onInput={(e: any) => setDeviceLabel(e.detail.value)}
              />
            </View>

            {workerError ? (
              <Text className='login-form__error'>{workerError}</Text>
            ) : null}

            <Text className='login-form__hint'>
              车间工人用工号 + PIN 登录（共用 PAD 不必登录商家账号）；登录后进工人工作台
            </Text>
          </>
        )}
      </View>

      {/* 底部操作区域 */}
      <View className='login-actions'>
        <Button
          className={`login-btn ${submitting ? 'login-btn--loading' : ''}`}
          loading={submitting}
          disabled={submitting}
          onClick={handleSubmit}
        >
          {submitting ? '登录中...' : '登录'}
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
