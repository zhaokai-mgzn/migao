import { useCallback, useState } from 'react'
import { View, Text, Button, Input } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { useAuthStore } from '../../../store/authStore'
import './index.scss'

/**
 * B 端员工登录页（米宝商家端）—— issue #5485 起统一为「账号密码」
 *
 * 1. 员工填「用户名@企业编码」+ 密码 → employeeLoginAction(identifier, password)
 * 2. 后端 `POST /api/auth/employee/login` 由标识里的企业编码解析租户
 *    （前端**不解析租户、不传 tenantId**）
 * 3. 成功 → switchTab 到「问米宝」（首页 Tab）
 *
 * 原「微信授权手机号 → 跨租户匹配员工 → 绑定 openid → 二次免密」整条退场：
 * 本页**没有** `getPhoneNumber` 授权按钮，`POST /api/auth/bmini/login` 已废弃。
 *
 * 格式与账号存在性的判定**单一真值在后端**（统一 401 同一文案，反枚举）——
 * 这里只挡「空输入」，不复制后端的企业编码 / 用户名格式规则（否则就是第二套真值）。
 */
export default function LoginPage() {
  const { isLoading, employeeLoginAction } = useAuthStore()
  const [identifier, setIdentifier] = useState('')
  const [password, setPassword] = useState('')

  /**
   * 提交登录。
   * 空输入在本地拦下（不白跑一次请求）；其余一律交后端判定，
   * 失败原因由 authStore 内部 showToast（不区分是哪个字段错）。
   */
  const handleLogin = useCallback(async () => {
    if (isLoading) return
    if (!identifier.trim() || !password) {
      Taro.showToast({ title: '请输入用户名@企业编码和密码', icon: 'none' })
      return
    }

    const success = await employeeLoginAction(identifier.trim(), password)
    if (success) {
      Taro.switchTab({ url: '/pages/chat/index/index' })
    }
  }, [identifier, password, isLoading, employeeLoginAction])

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
      content: '本应用仅使用您的员工账号信息完成登录校验，账号信息将严格保密。',
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
        <Text className='login-brand__title'>米宝 · 商家助手</Text>
        <Text className='login-brand__subtitle'>经营数据 · AI 客服 · 移动坐席</Text>
      </View>

      {/* 中间登录表单 */}
      <View className='login-form'>
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
            onConfirm={handleLogin}
          />
        </View>

        <Text className='login-form__hint'>账号由企业管理员在管理后台设置</Text>
      </View>

      {/* 底部操作区域 */}
      <View className='login-actions'>
        <Button
          className={`login-btn ${isLoading ? 'login-btn--loading' : ''}`}
          loading={isLoading}
          disabled={isLoading}
          onClick={handleLogin}
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