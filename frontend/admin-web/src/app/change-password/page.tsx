'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { KeyRound, Loader2, LogOut } from 'lucide-react'
import { cn } from '@/lib/utils'
import Logo from '@/components/ui/Logo'
import { useAuthStore } from '@/store/auth'
import { extractApiErrorMessage } from '@/lib/api-error'

/**
 * 首登强制改密页（issue #5485 I4）。
 *
 * 员工首次登录（或密码被管理员重置）后，在改密成功前访问**任何**业务 API 都会被
 * 服务端拒绝（403 `PASSWORD_CHANGE_REQUIRED`，白名单只有 改密/登出/`GET /api/auth/me`）。
 * 所以登录成功若 `mustChangePassword === true` 就直接落到这里，不进业务页。
 *
 * 成功响应**直接带新凭据**（新 accessToken + `mustChangePassword=false`）——
 * store 用它落会话即可，**不要**再手动刷一次 token（旧 token 仍带 claim）。
 *
 * 路由守卫：本页在 `auth-guard.tsx` 的受保护前缀里 ⇒ 未登录访问会先去登录页。
 */
export default function ChangePasswordPage() {
  const router = useRouter()
  const { changePassword, logout, isLoading } = useAuthStore()

  const [oldPassword, setOldPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState('')
  const [errors, setErrors] = useState<{ oldPassword?: string; newPassword?: string; confirmPassword?: string }>({})

  const validate = (): boolean => {
    const errs: typeof errors = {}
    if (!oldPassword) errs.oldPassword = '请输入当前密码（初始密码）'
    if (!newPassword) errs.newPassword = '请输入新密码'
    // 只做「纯前端可判」的校验：两遍输入一致。
    // 密码强度规则（长度/字符集）**由服务端判**，422 的 message 直接展示 ——
    // 前端再写一套必然会与服务端漂移（更严 ⇒ 用户被本地拦住却不知为何；更松 ⇒ 白填一次）。
    if (!confirmPassword) errs.confirmPassword = '请再次输入新密码'
    else if (newPassword && confirmPassword !== newPassword) errs.confirmPassword = '两次输入的新密码不一致'
    setErrors(errs)
    return Object.keys(errs).length === 0
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!validate()) return
    setError('')
    try {
      await changePassword(oldPassword, newPassword)
      // 响应里的新凭据已在 store 生效（含 mustChangePassword=false）⇒ 直接进业务
      router.push('/dashboard')
    } catch (err) {
      // 旧密码错 / 弱密码 ⇒ 422，服务端 message 可直接展示
      setError(extractApiErrorMessage(err, '修改密码失败，请稍后重试'))
    }
  }

  const inputClass = (hasError?: string) =>
    cn(
      'w-full h-11 pl-10 pr-3.5 rounded-lg border text-sm transition-all focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15',
      hasError ? 'border-red-300' : 'border-neutral-300'
    )

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-blue-50 via-white to-indigo-50 px-4">
      <div className="w-full max-w-[420px] relative z-10">
        <div className="flex flex-col items-center mb-8">
          <Logo size="large" className="mb-4" />
          <h1 className="text-2xl font-bold text-neutral-900">米高</h1>
          <p className="mt-1.5 text-sm text-neutral-500">企业级AI电商管理解决方案</p>
        </div>

        <div className="bg-white/80 backdrop-blur-sm rounded-2xl shadow-xl border border-neutral-100 p-8">
          <div className="flex items-center justify-center gap-2 mb-2">
            <KeyRound className="w-5 h-5 text-primary-600" />
            <h2 className="text-lg font-semibold text-neutral-900">首次登录，请先修改密码</h2>
          </div>
          <p className="mb-6 text-center text-xs leading-relaxed text-neutral-500">
            为了账号安全，使用初始密码首次登录后必须设置自己的新密码；<br />
            改密完成前，其他功能暂不可用。
          </p>

          {error && (
            <div className="mb-4 p-3 rounded-lg bg-red-50 border border-red-100">
              <p className="text-sm text-red-600">{error}</p>
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-5">
            <div>
              <label htmlFor="oldPassword" className="block text-sm font-medium text-neutral-700 mb-1.5">当前密码</label>
              <div className="relative">
                <KeyRound className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-neutral-400" />
                <input id="oldPassword" type="password" autoComplete="current-password" value={oldPassword}
                  onChange={e => { setOldPassword(e.target.value); if (errors.oldPassword) setErrors(p => ({ ...p, oldPassword: '' })) }}
                  placeholder="请输入管理员给你的初始密码"
                  className={inputClass(errors.oldPassword)} />
              </div>
              {errors.oldPassword && <p className="mt-1.5 text-xs text-red-500">{errors.oldPassword}</p>}
            </div>

            <div>
              <label htmlFor="newPassword" className="block text-sm font-medium text-neutral-700 mb-1.5">新密码</label>
              <div className="relative">
                <KeyRound className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-neutral-400" />
                <input id="newPassword" type="password" autoComplete="new-password" value={newPassword}
                  onChange={e => { setNewPassword(e.target.value); if (errors.newPassword) setErrors(p => ({ ...p, newPassword: '' })) }}
                  placeholder="请输入新密码"
                  className={inputClass(errors.newPassword)} />
              </div>
              {errors.newPassword && <p className="mt-1.5 text-xs text-red-500">{errors.newPassword}</p>}
            </div>

            <div>
              <label htmlFor="confirmPassword" className="block text-sm font-medium text-neutral-700 mb-1.5">确认新密码</label>
              <div className="relative">
                <KeyRound className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-neutral-400" />
                <input id="confirmPassword" type="password" autoComplete="new-password" value={confirmPassword}
                  onChange={e => { setConfirmPassword(e.target.value); if (errors.confirmPassword) setErrors(p => ({ ...p, confirmPassword: '' })) }}
                  placeholder="请再次输入新密码"
                  className={inputClass(errors.confirmPassword)} />
              </div>
              {errors.confirmPassword && <p className="mt-1.5 text-xs text-red-500">{errors.confirmPassword}</p>}
            </div>

            <button type="submit" disabled={isLoading}
              className={cn('w-full h-11 rounded-lg text-sm font-semibold text-white transition-all bg-gradient-to-r from-primary-600 to-primary-700 hover:shadow-lg', isLoading && 'opacity-70 cursor-not-allowed')}>
              {isLoading ? <span className="flex items-center justify-center gap-2"><Loader2 className="w-4 h-4 animate-spin" />提交中...</span> : '修改密码并进入系统'}
            </button>
          </form>

          {/* 改不了密码时的出口：登出是强制改密白名单内的端点，换账号不被拦 */}
          <button type="button" onClick={() => logout()}
            className="mt-4 w-full h-9 flex items-center justify-center gap-1.5 rounded-lg text-xs text-neutral-500 hover:text-neutral-700 hover:bg-neutral-50 transition-colors">
            <LogOut className="w-3.5 h-3.5" />
            退出登录
          </button>
        </div>

        <p className="mt-6 text-center text-xs text-neutral-400">
          忘记初始密码？请联系企业管理员在「员工管理」中重置
        </p>
      </div>
    </div>
  )
}