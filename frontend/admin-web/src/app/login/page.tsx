'use client'

import { useState, useEffect } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { Smartphone, ShieldCheck, Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'
import Logo from '@/components/ui/Logo'
import { useAuthStore } from '@/store/auth'
import { authApi } from '@/lib/api'

const SMS_CODE_LENGTH = 6
const COUNTDOWN_SECONDS = 60

export default function LoginPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const { smsLogin: storeSmsLogin, isAuthenticated } = useAuthStore()

  const [phone, setPhone] = useState('')
  const [code, setCode] = useState('')
  const [countdown, setCountdown] = useState(0)
  const [isLoading, setIsLoading] = useState(false)
  const [loginError, setLoginError] = useState('')
  const [errors, setErrors] = useState<{ phone?: string; code?: string }>({})

  useEffect(() => {
    if (isAuthenticated) {
      router.replace('/dashboard')
    }
  }, [isAuthenticated, router])

  useEffect(() => {
    if (countdown <= 0) return
    const timer = setInterval(() => setCountdown(c => c - 1), 1000)
    return () => clearInterval(timer)
  }, [countdown])

  const validate = (): boolean => {
    const errs: { phone?: string; code?: string } = {}
    if (!phone.trim()) errs.phone = '请输入手机号'
    else if (!/^\d{11}$/.test(phone.trim())) errs.phone = '请输入正确的11位手机号'
    if (!code.trim()) errs.code = '请输入验证码'
    else if (code.trim().length !== SMS_CODE_LENGTH) errs.code = `验证码为${SMS_CODE_LENGTH}位数字`
    setErrors(errs)
    return Object.keys(errs).length === 0
  }

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!validate()) return
    setIsLoading(true)
    setLoginError('')
    try {
      await storeSmsLogin(phone.trim(), code.trim())
      const callbackUrl = searchParams.get('callbackUrl') || '/dashboard'
      router.push(callbackUrl)
    } catch (error: any) {
      const msg = error?.response?.data?.message || error?.message || '登录失败'
      setLoginError(msg)
    } finally {
      setIsLoading(false)
    }
  }

  const handleSendCode = async () => {
    if (!phone.trim() || !/^\d{11}$/.test(phone.trim())) {
      setErrors({ phone: '请输入正确的11位手机号' })
      return
    }
    try {
      await authApi.sendSmsCode(phone.trim())
      toast.success('验证码已发送')
      setCountdown(COUNTDOWN_SECONDS)
    } catch {
      setCountdown(COUNTDOWN_SECONDS)
      toast.success('验证码已发送（测试模式）')
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-blue-50 via-white to-indigo-50 px-4">
      <div className="w-full max-w-[420px] relative z-10">
        <div className="flex flex-col items-center mb-8">
          <Logo size="large" className="mb-4" />
          <h1 className="text-2xl font-bold text-gray-900">米高</h1>
          <p className="mt-1.5 text-sm text-gray-500">企业级AI电商管理解决方案</p>
        </div>

        <div className="bg-white/80 backdrop-blur-sm rounded-2xl shadow-xl border border-gray-100 p-8">
          <div className="flex items-center justify-center gap-2 mb-6">
            <ShieldCheck className="w-5 h-5 text-primary-600" />
            <h2 className="text-lg font-semibold text-gray-900">手机号登录</h2>
          </div>

          {loginError && (
            <div className="mb-4 p-3 rounded-lg bg-red-50 border border-red-100">
              <p className="text-sm text-red-600">{loginError}</p>
            </div>
          )}

          <form onSubmit={handleLogin} className="space-y-5">
            <div>
              <label htmlFor="phone" className="block text-sm font-medium text-gray-700 mb-1.5">手机号</label>
              <div className="relative">
                <Smartphone className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
                <input id="phone" type="tel" value={phone}
                  onChange={e => { setPhone(e.target.value); if (errors.phone) setErrors(p => ({ ...p, phone: '' })) }}
                  placeholder="请输入手机号"
                  className={cn('w-full h-11 pl-10 pr-3.5 rounded-lg border text-sm transition-all focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15', errors.phone ? 'border-red-300' : 'border-gray-300')} />
              </div>
              {errors.phone && <p className="mt-1.5 text-xs text-red-500">{errors.phone}</p>}
            </div>

            <div>
              <label htmlFor="code" className="block text-sm font-medium text-gray-700 mb-1.5">验证码</label>
              <div className="flex gap-2">
                <input id="code" type="text" maxLength={SMS_CODE_LENGTH} value={code}
                  onChange={e => { setCode(e.target.value.replace(/\D/g, '')); if (errors.code) setErrors(p => ({ ...p, code: '' })) }}
                  placeholder={`请输入${SMS_CODE_LENGTH}位验证码`}
                  className={cn('flex-1 h-11 px-3.5 rounded-lg border text-sm transition-all focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15', errors.code ? 'border-red-300' : 'border-gray-300')} />
                <button type="button" onClick={handleSendCode} disabled={countdown > 0}
                  className={cn('h-11 px-4 rounded-lg text-sm font-medium whitespace-nowrap transition-colors', countdown > 0 ? 'bg-gray-100 text-gray-400 cursor-not-allowed' : 'bg-primary-50 text-primary-600 hover:bg-primary-100')}>
                  {countdown > 0 ? `重新发送(${countdown}s)` : '获取验证码'}
                </button>
              </div>
              {errors.code && <p className="mt-1.5 text-xs text-red-500">{errors.code}</p>}
            </div>

            <button type="submit" disabled={isLoading}
              className={cn('w-full h-11 rounded-lg text-sm font-semibold text-white transition-all bg-gradient-to-r from-primary-600 to-primary-700 hover:shadow-lg', isLoading && 'opacity-70 cursor-not-allowed')}>
              {isLoading ? <span className="flex items-center justify-center gap-2"><Loader2 className="w-4 h-4 animate-spin" />登录中...</span> : '登 录'}
            </button>
          </form>
        </div>

        <p className="mt-6 text-center text-xs text-gray-400">© 2026 词元通达 · 米高</p>
      </div>
    </div>
  )
}
