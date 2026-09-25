import { useCallback, useState } from 'react'
import { View, Text, Button, Input } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { useAuthStore } from '../../../store/authStore'
import './index.scss'

/**
 * 首登强制改密页（B 端商家小程序，issue #5485）
 *
 * 背景：管理员给员工设的**初始密码**必须首登后改掉。改密前后端只放行白名单
 * （`POST /api/auth/password/change` / `logout` / `GET /api/auth/me` / `refresh`），
 * 其余接口一律 403 `PASSWORD_CHANGE_REQUIRED` ⇒ 登录页见 `user.mustChangePassword === true`
 * 就把人送到本页，**不放进主界面**（否则用户看到的是「这小程序坏了」）。
 *
 * 出口就在本页：改密端点在白名单内，且成功后**直接换发**一份不带标记的新凭据
 * （`utils/auth.ts` 的 `changePassword` 会用新凭据覆盖本地存储）⇒
 * 商家员工（很多是手机-only）**不必去电脑端管理后台**。
 *
 * 文案口径：密码策略（长度 / 字符构成）与「原密码是否正确」都是**服务端判定**，
 * 前端只挡「空」与「两次输入不一致」，其余原样展示服务端 422 的 `message`（不造第二套规则）。
 */
export default function ChangePasswordPage() {
  const { isLoading, changePasswordAction, logout } = useAuthStore()
  const [oldPassword, setOldPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')

  const handleSubmit = useCallback(async () => {
    if (isLoading) return
    if (!oldPassword || !newPassword || !confirmPassword) {
      Taro.showToast({ title: '请填写原密码与新密码', icon: 'none' })
      return
    }
    if (newPassword !== confirmPassword) {
      Taro.showToast({ title: '两次输入的新密码不一致', icon: 'none' })
      return
    }

    const success = await changePasswordAction(oldPassword, newPassword)
    if (success) {
      Taro.showToast({ title: '密码修改成功', icon: 'success' })
      Taro.switchTab({ url: '/pages/chat/index/index' })
    }
    // 失败（原密码不正确 / 新密码不符合策略）由 authStore 展示服务端文案
  }, [oldPassword, newPassword, confirmPassword, isLoading, changePasswordAction])

  /**
   * 改不了密码时的出口：换账号重新登录。
   * 本页是 `redirectTo` 进来的（不是 tab 页、没有返回键）⇒ 不留出口就是死路。
   */
  const handleSwitchAccount = useCallback(() => {
    logout()
    Taro.redirectTo({ url: '/pages/auth/login/index' })
  }, [logout])

  return (
    <View className='cp-page'>
      <Text className='cp-title'>设置新密码</Text>
      <Text className='cp-desc'>
        首次登录需先修改密码，改完即可正常使用（原密码为管理员设置的初始密码）
      </Text>

      <View className='cp-field'>
        <Text className='cp-field__label'>原密码</Text>
        <Input
          className='cp-field__input'
          password
          placeholder='请输入初始密码'
          value={oldPassword}
          onInput={(e: any) => setOldPassword(e.detail.value)}
        />
      </View>

      <View className='cp-field'>
        <Text className='cp-field__label'>新密码</Text>
        <Input
          className='cp-field__input'
          password
          placeholder='请输入新密码'
          value={newPassword}
          onInput={(e: any) => setNewPassword(e.detail.value)}
        />
      </View>

      <View className='cp-field'>
        <Text className='cp-field__label'>确认新密码</Text>
        <Input
          className='cp-field__input'
          password
          placeholder='请再次输入新密码'
          value={confirmPassword}
          onInput={(e: any) => setConfirmPassword(e.detail.value)}
          onConfirm={handleSubmit}
        />
      </View>

      <Button
        className={`cp-btn ${isLoading ? 'cp-btn--loading' : ''}`}
        loading={isLoading}
        disabled={isLoading}
        onClick={handleSubmit}
      >
        {isLoading ? '提交中...' : '确认修改'}
      </Button>

      <View className='cp-switch'>
        <Text className='cp-switch__link' onClick={handleSwitchAccount}>
          使用其他账号登录
        </Text>
      </View>
    </View>
  )
}