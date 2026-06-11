'use client'

import { useState, useEffect, useCallback } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import Link from 'next/link'
import { Eye, EyeOff, Loader2, ShieldCheck, Smartphone, Phone } from 'lucide-react'
import { toast } from 'sonner'
import { useAuthStore } from '@/store/auth'
import { authApi } from '@/lib/api'
import { cn } from '@/lib/utils'
import Logo from '@/components/ui/Logo'

type TabType = 'sms' | 'password'

export default function LoginPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const { login, smsLogin, isLoading } = useAuthStore()

  
  // 短信登录表单
  const [smsForm, setSmsForm] = useState({ phone: '', code: '' })
  const [smsErrors, setSmsErrors] = useState<Record<string, string>>({})
  const [smsLoginError, setSmsLoginError] = useState('')
  const [countdown, setCountdown] = useState(0)
  const [sendingCode, setSendingCode] = useState(false)

  // 密码登录表单
  const [passwordForm, setPasswordForm] = useState({ tenantCode: '', username: '', password: '' })
  const [showPassword, setShowPassword] = useState(false)
  const [rememberMe, setRememberMe] = useState(true)
  const [passwordErrors, setPasswordErrors] = useState<Record<string, string>>({})
  const [passwordLoginError, setPasswordLoginError] = useState('')

  // 倒计时
  useEffect(() => {
    if (countdown <= 0) return
    const timer = setTimeout(() => setCountdown(c => c - 1), 1000)
    return () => clearTimeout(timer)
  }, [countdown])

  // ========== 短信登录逻辑 ==========
  const validatePhone = (phone: string) => /^1[3-9]\d{9}$/.test(phone)

  const handleSendCode = useCallback(async () => {
    if (!smsForm.phone.trim()) {
      setSmsErrors({ phone: '请输入手机号' })
      return
    }
    if (!validatePhone(smsForm.phone)) {
      setSmsErrors({ phone: '请输入正确的11位手机号' })
      return
    }
    setSmsErrors({})
    setSendingCode(true)
    try {
      await authApi.sendSmsCode(smsForm.phone)
      toast.success('验证码已发送')
      setCountdown(60)
    } catch (error: any) {
      const msg = error?.response?.data?.message || error?.message || '发送验证码失败'
      toast.error(msg)
    } finally {
      setSendingCode(false)
    }
  }, [smsForm.phone])

  const validateSmsForm = () => {
    const errors: Record<string, string> = {}
    if (!smsForm.phone.trim()) {
      errors.phone = '请输入手机号'
    } else if (!validatePhone(smsForm.phone)) {
      errors.phone = '请输入正确的11位手机号'
    }
    if (!smsForm.code.trim()) {
      errors.code = '请输入验证码'
    } else if (smsForm.code.length !== 6) {
      errors.code = '验证码为6位数字'
    }
    setSmsErrors(errors)
    return Object.keys(errors).length === 0
  }

  const handleSmsSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSmsLoginError('')
    if (!validateSmsForm()) return
    try {
      await smsLogin(smsForm.phone, smsForm.code)
      const callbackUrl = searchParams.get('callbackUrl') || '/dashboard'
      router.push(callbackUrl)
    } catch (error: any) {
      const msg = error?.response?.data?.message || error?.message || '登录失败，请检查验证码'
      setSmsLoginError(msg)
    }
  }

  const handleSmsChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value } = e.target
    setSmsForm(prev => ({ ...prev, [name]: value }))
    if (smsErrors[name]) setSmsErrors(prev => ({ ...prev, [name]: '' }))
    if (smsLoginError) setSmsLoginError('')
  }

  // ========== 密码登录逻辑（保持原有不变）==========
  const validatePasswordForm = () => {
    const newErrors: Record<string, string> = {}
    // 企业编号可选：为空时后端使用默认租户；输入时需为数字
    if (passwordForm.tenantCode.trim() && !/^\d+$/.test(passwordForm.tenantCode.trim())) {
      newErrors.tenantCode = '企业编号需为数字'
    }
    if (!passwordForm.username.trim()) {
      newErrors.username = '请输入用户名/手机号/邮箱'
    }
    if (!passwordForm.password) {
      newErrors.password = '请输入密码'
    } else if (passwordForm.password.length < 6) {
      newErrors.password = '密码长度不能少于6位'
    }
    setPasswordErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }

  const handlePasswordSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setPasswordLoginError('')
    if (!validatePasswordForm()) return
    try {
      await login(passwordForm.username, passwordForm.password, rememberMe, passwordForm.tenantCode)
      const callbackUrl = searchParams.get('callbackUrl') || '/dashboard'
      router.push(callbackUrl)
    } catch (error: any) {
      const msg = error?.response?.data?.message || error?.message || '登录失败，请检查用户名和密码'
      setPasswordLoginError(msg)
    }
  }

  const handlePasswordChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value } = e.target
    setPasswordForm(prev => ({ ...prev, [name]: value }))
    if (passwordErrors[name]) setPasswordErrors(prev => ({ ...prev, [name]: '' }))
    if (passwordLoginError) setPasswordLoginError('')
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-blue-50 via-white to-indigo-50 px-4">
      {/* 背景装饰 */}
      <div className="fixed inset-0 overflow-hidden pointer-events-none">
        <div className="absolute -top-40 -right-40 w-80 h-80 bg-primary-100 rounded-full opacity-30 blur-3xl" />
        <div className="absolute -bottom-40 -left-40 w-80 h-80 bg-indigo-100 rounded-full opacity-30 blur-3xl" />
      </div>

      <div className="w-full max-w-[420px] relative z-10">
        {/* Logo 区域 */}
        <div className="flex flex-col items-center mb-8">
          <Logo size="large" className="mb-4" />
          <h1 className="text-2xl font-bold text-gray-900 tracking-tight">
            有客
          </h1>
          <p className="mt-1.5 text-sm text-gray-500">
            企业级AI电商管理解决方案
          </p>
        </div>

        {/* 登录卡片 */}
        <div className="bg-white/80 backdrop-blur-sm rounded-2xl shadow-xl shadow-gray-200/50 border border-gray-100 p-8">
          {/* 手机号验证码登录 */}
          <div className="flex items-center justify-center gap-2 mb-6">
            <Smartphone className="w-5 h-5 text-primary-600" />
            <h2 className="text-lg font-semibold text-gray-900">
              手机号登录
            </h2>
          </div>

          {smsLoginError && (
            <div className="mb-4 p-3 rounded-lg bg-red-50 border border-red-100">
              <p className="text-sm text-red-600">{smsLoginError}</p>
            </div>
          )}

          <form onSubmit={handleSmsSubmit} className="space-y-5">
                {/* 手机号 */}
                <div>
                  <label htmlFor="phone" className="block text-sm font-medium text-gray-700 mb-1.5">
                    手机号
                  </label>
                  <div className="relative">
                    <Phone className="absolute left-3 top-1/2 -translate-y-1/2 w-4.5 h-4.5 text-gray-400" />
                    <input
                      id="phone"
                      name="phone"
                      type="tel"
                      autoComplete="tel"
                      maxLength={11}
                      value={smsForm.phone}
                      onChange={handleSmsChange}
                      placeholder="请输入手机号"
                      className={cn(
                        'w-full h-11 pl-10 pr-3.5 rounded-lg border text-sm transition-all',
                        'focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15',
                        smsErrors.phone
                          ? 'border-red-400 focus:border-red-500 focus:ring-red-500/15'
                          : 'border-gray-300 hover:border-gray-400'
                      )}
                      disabled={isLoading}
                    />
                  </div>
                  {smsErrors.phone && (
                    <p className="mt-1.5 text-xs text-red-500">{smsErrors.phone}</p>
                  )}
                </div>

                {/* 验证码 */}
                <div>
                  <label htmlFor="code" className="block text-sm font-medium text-gray-700 mb-1.5">
                    验证码
                  </label>
                  <div className="flex gap-3">
                    <input
                      id="code"
                      name="code"
                      type="text"
                      inputMode="numeric"
                      maxLength={6}
                      autoComplete="one-time-code"
                      value={smsForm.code}
                      onChange={handleSmsChange}
                      placeholder="请输入6位验证码"
                      className={cn(
                        'flex-1 h-11 px-3.5 rounded-lg border text-sm transition-all',
                        'focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15',
                        smsErrors.code
                          ? 'border-red-400 focus:border-red-500 focus:ring-red-500/15'
                          : 'border-gray-300 hover:border-gray-400'
                      )}
                      disabled={isLoading}
                    />
                    <button
                      type="button"
                      onClick={handleSendCode}
                      disabled={countdown > 0 || sendingCode || isLoading}
                      className={cn(
                        'shrink-0 h-11 px-4 rounded-lg text-sm font-medium transition-all',
                        'border border-primary-300 text-primary-600',
                        'hover:bg-primary-50',
                        (countdown > 0 || sendingCode) && 'opacity-60 cursor-not-allowed text-gray-400 border-gray-300 hover:bg-transparent'
                      )}
                    >
                      {sendingCode ? (
                        <Loader2 className="w-4 h-4 animate-spin" />
                      ) : countdown > 0 ? (
                        `重新发送(${countdown}s)`
                      ) : (
                        '获取验证码'
                      )}
                    </button>
                  </div>
                  {smsErrors.code && (
                    <p className="mt-1.5 text-xs text-red-500">{smsErrors.code}</p>
                  )}
                </div>

                {/* 登录按钮 */}
                <button
                  type="submit"
                  disabled={isLoading}
                  className={cn(
                    'w-full h-11 rounded-lg text-sm font-semibold text-white transition-all',
                    'bg-gradient-to-r from-primary-600 to-primary-700',
                    'hover:from-primary-700 hover:to-primary-800 hover:shadow-lg hover:shadow-primary-500/25',
                    'focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:ring-offset-2',
                    'active:scale-[0.98]',
                    isLoading && 'opacity-70 cursor-not-allowed'
                  )}
                >
                  {isLoading ? (
                    <span className="flex items-center justify-center gap-2">
                      <Loader2 className="w-4 h-4 animate-spin" />
                      登录中...
                    </span>
                  ) : (
                    '登 录'
                  )}
                </button>
              </form>
            </>
          )}

                           )}
                >
                  {isLoading ? (
                    <span className="flex items-center justify-center gap-2">
                      <Loader2 className="w-4 h-4 animate-spin" />
                      登录中...
                    </span>
                  ) : (
                    '登 录'
                  )}
                </button>
              </form>


            </>
          )}

          {/* 企业入驻链接 */}
          <div className="mt-6 pt-5 border-t border-gray-100 text-center">
            <p className="text-sm text-gray-500">
              还没有企业账号？
              <Link
                href="/register"
                className="ml-1 text-primary-600 hover:text-primary-700 font-medium hover:underline"
              >
                企业入驻申请
              </Link>
            </p>
          </div>
        </div>

        {/* 底部版权 */}
        <p className="mt-8 text-center text-xs text-gray-400">
          © 2026 米高智能 · 有客
        </p>
      </div>
    </div>
  )
}
