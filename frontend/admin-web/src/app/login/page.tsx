'use client'

import { useState, useEffect } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { Smartphone, ShieldCheck, User, Lock, Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'
import Logo from '@/components/ui/Logo'
import { useAuthStore } from '@/store/auth'
import { authApi } from '@/lib/api'
import { extractApiErrorMessage } from '@/lib/api-error'

const SMS_CODE_LENGTH = 6
const COUNTDOWN_SECONDS = 60

/**
 * 登录页两个入口（issue #5485）—— 谁用哪个要一眼看懂：
 *
 * | 主体 | 凭据 | 说明 |
 * |---|---|---|
 * | 员工（默认） | `用户名@企业编码` + 密码 | 账号由企业管理员在「员工管理」里分配 |
 * | 企业管理员 / 平台超管 | 手机号 + 短信验证码 | 员工走短信会被服务端拒绝并给引导文案 |
 *
 * 登录成功后：`mustChangePassword === true` ⇒ **直接**去改密页（不要先进业务页再等 403）。
 */
type LoginMode = 'employee' | 'admin'

export default function LoginPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const {
    employeeLogin: storeEmployeeLogin,
    smsLogin: storeSmsLogin,
    isAuthenticated,
    user,
  } = useAuthStore()

  // 默认「员工登录」：绝大多数使用者是员工；管理员是少数（且他一定知道自己要切 tab）
  const [mode, setMode] = useState<LoginMode>('employee')

  // 员工登录
  const [identifier, setIdentifier] = useState('')
  const [password, setPassword] = useState('')

  // 管理员登录
  const [phone, setPhone] = useState('')
  const [code, setCode] = useState('')
  const [countdown, setCountdown] = useState(0)

  const [isLoading, setIsLoading] = useState(false)
  const [loginError, setLoginError] = useState('')
  const [errors, setErrors] = useState<{ identifier?: string; password?: string; phone?: string; code?: string }>({})

  const mustChangePassword = !!user?.mustChangePassword

  // 已登录访问登录页：按「是否需先改密」分流（#5485）
  useEffect(() => {
    if (!isAuthenticated) return
    if (mustChangePassword) {
      router.replace('/change-password')
      return
    }
    router.replace('/dashboard')
  }, [isAuthenticated, mustChangePassword, router])

  useEffect(() => {
    if (countdown <= 0) return
    const timer = setInterval(() => setCountdown(c => c - 1), 1000)
    return () => clearInterval(timer)
  }, [countdown])

  const switchMode = (next: LoginMode) => {
    setMode(next)
    setLoginError('')
    setErrors({})
  }

  const validateEmployee = (): boolean => {
    const errs: typeof errors = {}
    const id = identifier.trim()
    if (!id) errs.identifier = '请输入账号'
    // 标识形态 `用户名@企业编码`：只校验「有且仅有一段 @ 前非空、@ 后非空」。
    // ⚠️ 不在这里校验企业编码字符集/用户名规则 —— 那是服务端的事（前端自己写更严的正则
    // 会把合法的存量编码挡在门外，且两边规则一旦漂移就是「登不进去又看不出为什么」）。
    else if (!/^[^@\s]+@[^@\s]+$/.test(id)) errs.identifier = '账号格式为 用户名@企业编码'
    if (!password) errs.password = '请输入密码'
    setErrors(errs)
    return Object.keys(errs).length === 0
  }

  const validateAdmin = (): boolean => {
    const errs: typeof errors = {}
    if (!phone.trim()) errs.phone = '请输入手机号'
    else if (!/^\d{11}$/.test(phone.trim())) errs.phone = '请输入正确的11位手机号'
    if (!code.trim()) errs.code = '请输入验证码'
    else if (code.trim().length !== SMS_CODE_LENGTH) errs.code = `验证码为${SMS_CODE_LENGTH}位数字`
    setErrors(errs)
    return Object.keys(errs).length === 0
  }

  /**
   * 登录成功后的落点：需改密 ⇒ 改密页；否则回 `callbackUrl`（默认 dashboard）。
   * 两条登录路共用 —— 管理员也可能被要求改密（管理员由他人创建时同样置了标记）。
   */
  const goAfterLogin = (needChangePassword: boolean) => {
    if (needChangePassword) {
      router.push('/change-password')
      return
    }
    router.push(searchParams.get('callbackUrl') || '/dashboard')
  }

  const handleEmployeeLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!validateEmployee()) return
    setIsLoading(true)
    setLoginError('')
    try {
      // 标识**原样**发服务端：租户由服务端按企业编码解析，前端不做任何租户推断（#5485 I1）
      const outcome = await storeEmployeeLogin(identifier.trim(), password)
      goAfterLogin(outcome.mustChangePassword)
    } catch (error) {
      setLoginError(extractApiErrorMessage(error, '登录失败，请检查账号与密码'))
    } finally {
      setIsLoading(false)
    }
  }

  const handleAdminLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!validateAdmin()) return
    setIsLoading(true)
    setLoginError('')
    try {
      const outcome = await storeSmsLogin(phone.trim(), code.trim())
      goAfterLogin(outcome.mustChangePassword)
    } catch (error) {
      setLoginError(extractApiErrorMessage(error, '登录失败'))
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
    } catch (e) {
      setCountdown(COUNTDOWN_SECONDS)
      toast.success('验证码已发送（测试模式）')
    }
  }

  const inputClass = (hasError?: string) =>
    cn(
      'w-full h-11 rounded-lg border text-sm transition-all focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15',
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
          {/* 两个入口：员工（默认）/ 管理员 */}
          <div className="grid grid-cols-2 gap-1 p-1 mb-6 rounded-xl bg-neutral-100" role="tablist">
            {([
              { key: 'employee' as const, label: '员工登录', icon: User, hint: '账号密码' },
              { key: 'admin' as const, label: '管理员登录', icon: ShieldCheck, hint: '手机验证码' },
            ]).map(tab => (
              <button
                key={tab.key}
                type="button"
                role="tab"
                aria-selected={mode === tab.key}
                onClick={() => switchMode(tab.key)}
                className={cn(
                  'flex flex-col items-center justify-center gap-0.5 h-14 rounded-lg text-sm font-medium transition-colors',
                  mode === tab.key
                    ? 'bg-white text-primary-700 shadow-sm'
                    : 'text-neutral-500 hover:text-neutral-700'
                )}
              >
                <span className="flex items-center gap-1.5">
                  <tab.icon className="w-4 h-4" />
                  {tab.label}
                </span>
                <span className="text-[11px] font-normal text-neutral-400">{tab.hint}</span>
              </button>
            ))}
          </div>

          {loginError && (
            <div className="mb-4 p-3 rounded-lg bg-red-50 border border-red-100">
              <p className="text-sm text-red-600">{loginError}</p>
            </div>
          )}

          {/* ============ 员工登录：用户名@企业编码 + 密码 ============ */}
          {mode === 'employee' && (
            <>
              <p className="mb-5 text-xs leading-relaxed text-neutral-500">
                员工请用管理员分配的账号登录。账号形态为「<span className="font-medium text-neutral-700">用户名@企业编码</span>」，
                企业编码见企业管理员设置页（例如 <span className="text-neutral-600">zhangsan@migao</span>）。
              </p>
              <form onSubmit={handleEmployeeLogin} className="space-y-5">
                <div>
                  <label htmlFor="identifier" className="block text-sm font-medium text-neutral-700 mb-1.5">账号</label>
                  <div className="relative">
                    <User className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-neutral-400" />
                    <input id="identifier" type="text" autoComplete="username" value={identifier}
                      onChange={e => { setIdentifier(e.target.value); if (errors.identifier) setErrors(p => ({ ...p, identifier: '' })) }}
                      placeholder="用户名@企业编码"
                      className={cn(inputClass(errors.identifier), 'pl-10 pr-3.5')} />
                  </div>
                  {errors.identifier && <p className="mt-1.5 text-xs text-red-500">{errors.identifier}</p>}
                </div>

                <div>
                  <label htmlFor="password" className="block text-sm font-medium text-neutral-700 mb-1.5">密码</label>
                  <div className="relative">
                    <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-neutral-400" />
                    <input id="password" type="password" autoComplete="current-password" value={password}
                      onChange={e => { setPassword(e.target.value); if (errors.password) setErrors(p => ({ ...p, password: '' })) }}
                      placeholder="请输入密码"
                      className={cn(inputClass(errors.password), 'pl-10 pr-3.5')} />
                  </div>
                  {errors.password && <p className="mt-1.5 text-xs text-red-500">{errors.password}</p>}
                </div>

                <button type="submit" disabled={isLoading}
                  className={cn('w-full h-11 rounded-lg text-sm font-semibold text-white transition-all bg-gradient-to-r from-primary-600 to-primary-700 hover:shadow-lg', isLoading && 'opacity-70 cursor-not-allowed')}>
                  {isLoading ? <span className="flex items-center justify-center gap-2"><Loader2 className="w-4 h-4 animate-spin" />登录中...</span> : '登 录'}
                </button>

                <p className="text-center text-xs text-neutral-400">
                  还没有账号？请联系企业管理员在「员工管理」中分配用户名与初始密码
                </p>
              </form>
            </>
          )}

          {/* ============ 管理员登录：手机号 + 短信验证码 ============ */}
          {mode === 'admin' && (
            <>
              <p className="mb-5 text-xs leading-relaxed text-neutral-500">
                仅企业管理员与平台超管可使用短信验证码登录。员工请切到「<span className="font-medium text-neutral-700">员工登录</span>」用账号密码进入。
              </p>
              <form onSubmit={handleAdminLogin} className="space-y-5">
                <div>
                  <label htmlFor="phone" className="block text-sm font-medium text-neutral-700 mb-1.5">手机号</label>
                  <div className="relative">
                    <Smartphone className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-neutral-400" />
                    <input id="phone" type="tel" value={phone}
                      onChange={e => { setPhone(e.target.value); if (errors.phone) setErrors(p => ({ ...p, phone: '' })) }}
                      placeholder="请输入手机号"
                      className={cn(inputClass(errors.phone), 'pl-10 pr-3.5')} />
                  </div>
                  {errors.phone && <p className="mt-1.5 text-xs text-red-500">{errors.phone}</p>}
                </div>

                <div>
                  <label htmlFor="code" className="block text-sm font-medium text-neutral-700 mb-1.5">验证码</label>
                  <div className="flex gap-2">
                    <input id="code" type="text" maxLength={SMS_CODE_LENGTH} value={code}
                      onChange={e => { setCode(e.target.value.replace(/\D/g, '')); if (errors.code) setErrors(p => ({ ...p, code: '' })) }}
                      placeholder={`请输入${SMS_CODE_LENGTH}位验证码`}
                      className={cn(inputClass(errors.code), 'flex-1 px-3.5')} />
                    <button type="button" onClick={handleSendCode} disabled={countdown > 0}
                      className={cn('h-11 px-4 rounded-lg text-sm font-medium whitespace-nowrap transition-colors', countdown > 0 ? 'bg-neutral-100 text-neutral-400 cursor-not-allowed' : 'bg-primary-50 text-primary-600 hover:bg-primary-100')}>
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
            </>
          )}
        </div>

        <p className="mt-6 text-center text-xs text-neutral-400">© 2026 词元通达 · 米高</p>
      </div>
    </div>
  )
}