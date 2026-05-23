'use client'

import { useState, useEffect, useCallback } from 'react'
import Link from 'next/link'
import { Phone, Loader2, Building2, ArrowLeft, ArrowRight, CheckCircle2, Upload, Bot, MessageCircle, LayoutDashboard } from 'lucide-react'
import { toast } from 'sonner'
import { authApi } from '@/lib/api'
import { fileApi } from '@/lib/api'
import { cn } from '@/lib/utils'
import Logo from '@/components/ui/Logo'
import type { RegistrationData } from '@/types'

type Step = 1 | 2 | 3 // 1: 手机验证, 2: 企业信息, 3: 提交成功

export default function RegisterPage() {
  const [step, setStep] = useState<Step>(1)

  // 步骤一：手机验证
  const [phone, setPhone] = useState('')
  const [smsCode, setSmsCode] = useState('')
  const [countdown, setCountdown] = useState(0)
  const [sendingCode, setSendingCode] = useState(false)
  const [phoneErrors, setPhoneErrors] = useState<Record<string, string>>({})

  // 步骤二：企业信息
  const [companyForm, setCompanyForm] = useState({
    companyName: '',
    contactName: '',
    industry: '',
    address: '',
    description: '',
  })
  const [businessLicenseUrl, setBusinessLicenseUrl] = useState('')
  const [companyErrors, setCompanyErrors] = useState<Record<string, string>>({})
  const [submitting, setSubmitting] = useState(false)
  const [uploading, setUploading] = useState(false)

  // 倒计时
  useEffect(() => {
    if (countdown <= 0) return
    const timer = setTimeout(() => setCountdown(c => c - 1), 1000)
    return () => clearTimeout(timer)
  }, [countdown])

  const validatePhone = (val: string) => /^1[3-9]\d{9}$/.test(val)

  // 发送验证码
  const handleSendCode = useCallback(async () => {
    if (!phone.trim()) {
      setPhoneErrors({ phone: '请输入手机号' })
      return
    }
    if (!validatePhone(phone)) {
      setPhoneErrors({ phone: '请输入正确的11位手机号' })
      return
    }
    setPhoneErrors({})
    setSendingCode(true)
    try {
      await authApi.sendSmsCode(phone)
      toast.success('验证码已发送')
      setCountdown(60)
    } catch (error: any) {
      const msg = error?.response?.data?.message || error?.message || '发送验证码失败'
      toast.error(msg)
    } finally {
      setSendingCode(false)
    }
  }, [phone])

  // 步骤一：验证手机号和验证码格式，进入步骤二
  const handleStepOneNext = (e: React.FormEvent) => {
    e.preventDefault()
    const errors: Record<string, string> = {}
    if (!phone.trim()) {
      errors.phone = '请输入手机号'
    } else if (!validatePhone(phone)) {
      errors.phone = '请输入正确的11位手机号'
    }
    if (!smsCode.trim()) {
      errors.code = '请输入验证码'
    } else if (smsCode.length !== 6) {
      errors.code = '验证码为6位数字'
    }
    setPhoneErrors(errors)
    if (Object.keys(errors).length === 0) {
      setStep(2)
    }
  }

  // 步骤二：企业信息表单变更
  const handleCompanyChange = (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    const { name, value } = e.target
    setCompanyForm(prev => ({ ...prev, [name]: value }))
    if (companyErrors[name]) setCompanyErrors(prev => ({ ...prev, [name]: '' }))
  }

  // 营业执照上传
  const handleLicenseUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    if (file.size > 10 * 1024 * 1024) {
      toast.error('文件大小不能超过10MB')
      return
    }
    setUploading(true)
    try {
      const response = await fileApi.uploadFile(file, 'license')
      setBusinessLicenseUrl(response.data.data.url)
      toast.success('上传成功')
    } catch {
      toast.error('上传失败，请重试')
    } finally {
      setUploading(false)
    }
  }

  // 提交申请
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    const errors: Record<string, string> = {}
    if (!companyForm.companyName.trim()) errors.companyName = '请输入企业名称'
    if (!companyForm.contactName.trim()) errors.contactName = '请输入联系人姓名'
    setCompanyErrors(errors)
    if (Object.keys(errors).length > 0) return

    setSubmitting(true)
    try {
      const data: RegistrationData = {
        companyName: companyForm.companyName.trim(),
        contactName: companyForm.contactName.trim(),
        phone,
        smsCode,
        businessLicenseUrl: businessLicenseUrl || undefined,
        industry: companyForm.industry.trim() || undefined,
        address: companyForm.address.trim() || undefined,
        description: companyForm.description.trim() || undefined,
      }
      await authApi.submitRegistration(data)
      toast.success('申请提交成功')
      setStep(3)
    } catch (error: any) {
      const msg = error?.response?.data?.message || error?.message || '提交失败，请重试'
      toast.error(msg)
    } finally {
      setSubmitting(false)
    }
  }

  const inputClassName = (hasError: boolean) =>
    cn(
      'w-full h-11 px-3.5 rounded-lg border text-sm transition-all',
      'focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15',
      hasError
        ? 'border-red-400 focus:border-red-500 focus:ring-red-500/15'
        : 'border-gray-300 hover:border-gray-400'
    )

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-blue-50 via-white to-indigo-50 px-4">
      {/* 背景装饰 */}
      <div className="fixed inset-0 overflow-hidden pointer-events-none">
        <div className="absolute -top-40 -right-40 w-80 h-80 bg-primary-100 rounded-full opacity-30 blur-3xl" />
        <div className="absolute -bottom-40 -left-40 w-80 h-80 bg-indigo-100 rounded-full opacity-30 blur-3xl" />
      </div>

      <div className="w-full max-w-[480px] relative z-10">
        {/* Logo 区域 */}
        <div className="flex flex-col items-center mb-8">
          <Logo size="large" className="mb-4" />
          <h1 className="text-2xl font-bold text-gray-900 tracking-tight">
            企业入驻申请
          </h1>
          <p className="mt-1.5 text-sm text-gray-500">
            有客 · AI智能管理平台
          </p>
        </div>

        {/* 步骤指示器 */}
        {step < 3 && (
          <div className="flex items-center justify-center gap-3 mb-6">
            <div className={cn(
              'flex items-center gap-2 text-sm font-medium',
              step >= 1 ? 'text-primary-600' : 'text-gray-400'
            )}>
              <div className={cn(
                'w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold',
                step >= 1 ? 'bg-primary-600 text-white' : 'bg-gray-200 text-gray-500'
              )}>1</div>
              手机验证
            </div>
            <div className={cn('w-8 h-0.5', step >= 2 ? 'bg-primary-400' : 'bg-gray-200')} />
            <div className={cn(
              'flex items-center gap-2 text-sm font-medium',
              step >= 2 ? 'text-primary-600' : 'text-gray-400'
            )}>
              <div className={cn(
                'w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold',
                step >= 2 ? 'bg-primary-600 text-white' : 'bg-gray-200 text-gray-500'
              )}>2</div>
              企业信息
            </div>
          </div>
        )}

        {/* 主卡片 */}
        <div className="bg-white/80 backdrop-blur-sm rounded-2xl shadow-xl shadow-gray-200/50 border border-gray-100 p-8">

          {/* ========== 步骤一：手机验证 ========== */}
          {step === 1 && (
            <form onSubmit={handleStepOneNext} className="space-y-5">
              <div className="flex items-center justify-center gap-2 mb-2">
                <Phone className="w-5 h-5 text-primary-600" />
                <h2 className="text-lg font-semibold text-gray-900">手机号验证</h2>
              </div>
              <p className="text-sm text-gray-500 text-center mb-4">
                请先验证您的手机号码
              </p>

              {/* 手机号 */}
              <div>
                <label htmlFor="reg-phone" className="block text-sm font-medium text-gray-700 mb-1.5">
                  手机号
                </label>
                <input
                  id="reg-phone"
                  type="tel"
                  maxLength={11}
                  value={phone}
                  onChange={(e) => {
                    setPhone(e.target.value)
                    if (phoneErrors.phone) setPhoneErrors(prev => ({ ...prev, phone: '' }))
                  }}
                  placeholder="请输入手机号"
                  className={inputClassName(!!phoneErrors.phone)}
                />
                {phoneErrors.phone && (
                  <p className="mt-1.5 text-xs text-red-500">{phoneErrors.phone}</p>
                )}
              </div>

              {/* 验证码 */}
              <div>
                <label htmlFor="reg-code" className="block text-sm font-medium text-gray-700 mb-1.5">
                  验证码
                </label>
                <div className="flex gap-3">
                  <input
                    id="reg-code"
                    type="text"
                    inputMode="numeric"
                    maxLength={6}
                    value={smsCode}
                    onChange={(e) => {
                      setSmsCode(e.target.value)
                      if (phoneErrors.code) setPhoneErrors(prev => ({ ...prev, code: '' }))
                    }}
                    placeholder="测试环境验证码: 123456"
                    className={cn(
                      'flex-1 h-11 px-3.5 rounded-lg border text-sm transition-all',
                      'focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15',
                      phoneErrors.code
                        ? 'border-red-400 focus:border-red-500 focus:ring-red-500/15'
                        : 'border-gray-300 hover:border-gray-400'
                    )}
                  />
                  <button
                    type="button"
                    onClick={handleSendCode}
                    disabled={countdown > 0 || sendingCode}
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
                {phoneErrors.code && (
                  <p className="mt-1.5 text-xs text-red-500">{phoneErrors.code}</p>
                )}
              </div>

              <button
                type="submit"
                className={cn(
                  'w-full h-11 rounded-lg text-sm font-semibold text-white transition-all',
                  'bg-gradient-to-r from-primary-600 to-primary-700',
                  'hover:from-primary-700 hover:to-primary-800 hover:shadow-lg hover:shadow-primary-500/25',
                  'focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:ring-offset-2',
                  'active:scale-[0.98]'
                )}
              >
                <span className="flex items-center justify-center gap-2">
                  下一步
                  <ArrowRight className="w-4 h-4" />
                </span>
              </button>
            </form>
          )}

          {/* ========== 步骤二：企业信息填写 ========== */}
          {step === 2 && (
            <form onSubmit={handleSubmit} className="space-y-4">
              <div className="flex items-center justify-center gap-2 mb-2">
                <Building2 className="w-5 h-5 text-primary-600" />
                <h2 className="text-lg font-semibold text-gray-900">企业信息</h2>
              </div>
              <p className="text-sm text-gray-500 text-center mb-4">
                请填写企业基本信息，完成入驻即可获得米宝AI助手
              </p>

              {/* 企业名称 */}
              <div>
                <label htmlFor="companyName" className="block text-sm font-medium text-gray-700 mb-1.5">
                  企业名称 <span className="text-red-500">*</span>
                </label>
                <input
                  id="companyName"
                  name="companyName"
                  type="text"
                  value={companyForm.companyName}
                  onChange={handleCompanyChange}
                  placeholder="请输入企业名称"
                  className={inputClassName(!!companyErrors.companyName)}
                />
                {companyErrors.companyName && (
                  <p className="mt-1.5 text-xs text-red-500">{companyErrors.companyName}</p>
                )}
              </div>

              {/* 联系人姓名 */}
              <div>
                <label htmlFor="contactName" className="block text-sm font-medium text-gray-700 mb-1.5">
                  联系人姓名 <span className="text-red-500">*</span>
                </label>
                <input
                  id="contactName"
                  name="contactName"
                  type="text"
                  value={companyForm.contactName}
                  onChange={handleCompanyChange}
                  placeholder="请输入联系人姓名"
                  className={inputClassName(!!companyErrors.contactName)}
                />
                {companyErrors.contactName && (
                  <p className="mt-1.5 text-xs text-red-500">{companyErrors.contactName}</p>
                )}
              </div>

              {/* 行业 */}
              <div>
                <label htmlFor="industry" className="block text-sm font-medium text-gray-700 mb-1.5">
                  行业 <span className="text-gray-400 text-xs font-normal">（选填）</span>
                </label>
                <input
                  id="industry"
                  name="industry"
                  type="text"
                  value={companyForm.industry}
                  onChange={handleCompanyChange}
                  placeholder="如：家居建材、电子商务等"
                  className={inputClassName(false)}
                />
              </div>

              {/* 企业地址 */}
              <div>
                <label htmlFor="address" className="block text-sm font-medium text-gray-700 mb-1.5">
                  企业地址 <span className="text-gray-400 text-xs font-normal">（选填）</span>
                </label>
                <input
                  id="address"
                  name="address"
                  type="text"
                  value={companyForm.address}
                  onChange={handleCompanyChange}
                  placeholder="请输入企业地址"
                  className={inputClassName(false)}
                />
              </div>

              {/* 企业简介 */}
              <div>
                <label htmlFor="description" className="block text-sm font-medium text-gray-700 mb-1.5">
                  企业简介 <span className="text-gray-400 text-xs font-normal">（选填）</span>
                </label>
                <textarea
                  id="description"
                  name="description"
                  rows={3}
                  value={companyForm.description}
                  onChange={handleCompanyChange}
                  placeholder="请简要描述您的企业"
                  className={cn(
                    'w-full px-3.5 py-2.5 rounded-lg border text-sm transition-all resize-none',
                    'focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15',
                    'border-gray-300 hover:border-gray-400'
                  )}
                />
              </div>

              {/* 营业执照上传 */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1.5">
                  营业执照 <span className="text-gray-400 text-xs font-normal">（选填，可跳过）</span>
                </label>
                {businessLicenseUrl ? (
                  <div className="flex items-center gap-2 p-3 rounded-lg bg-green-50 border border-green-200">
                    <CheckCircle2 className="w-4 h-4 text-green-600 shrink-0" />
                    <span className="text-sm text-green-700 truncate flex-1">已上传营业执照</span>
                    <button
                      type="button"
                      onClick={() => setBusinessLicenseUrl('')}
                      className="text-xs text-gray-500 hover:text-red-500"
                    >
                      移除
                    </button>
                  </div>
                ) : (
                  <label className={cn(
                    'flex items-center justify-center gap-2 h-11 rounded-lg border border-dashed cursor-pointer transition-all',
                    'border-gray-300 hover:border-primary-400 hover:bg-primary-50/50',
                    uploading && 'opacity-60 cursor-not-allowed'
                  )}>
                    <input
                      type="file"
                      accept="image/*,.pdf"
                      className="hidden"
                      onChange={handleLicenseUpload}
                      disabled={uploading}
                    />
                    {uploading ? (
                      <Loader2 className="w-4 h-4 animate-spin text-gray-400" />
                    ) : (
                      <Upload className="w-4 h-4 text-gray-400" />
                    )}
                    <span className="text-sm text-gray-500">
                      {uploading ? '上传中...' : '点击上传营业执照'}
                    </span>
                  </label>
                )}
              </div>

              {/* 按钮 */}
              <div className="flex gap-3 pt-2">
                <button
                  type="button"
                  onClick={() => setStep(1)}
                  className={cn(
                    'flex-1 h-11 rounded-lg text-sm font-medium transition-all',
                    'border border-gray-300 text-gray-700 hover:bg-gray-50',
                    'focus:outline-none focus:ring-2 focus:ring-gray-300/40 focus:ring-offset-2',
                    'active:scale-[0.98]'
                  )}
                >
                  <span className="flex items-center justify-center gap-2">
                    <ArrowLeft className="w-4 h-4" />
                    上一步
                  </span>
                </button>
                <button
                  type="submit"
                  disabled={submitting}
                  className={cn(
                    'flex-1 h-11 rounded-lg text-sm font-semibold text-white transition-all',
                    'bg-gradient-to-r from-primary-600 to-primary-700',
                    'hover:from-primary-700 hover:to-primary-800 hover:shadow-lg hover:shadow-primary-500/25',
                    'focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:ring-offset-2',
                    'active:scale-[0.98]',
                    submitting && 'opacity-70 cursor-not-allowed'
                  )}
                >
                  {submitting ? (
                    <span className="flex items-center justify-center gap-2">
                      <Loader2 className="w-4 h-4 animate-spin" />
                      提交中...
                    </span>
                  ) : (
                    '提交申请'
                  )}
                </button>
              </div>
            </form>
          )}

          {/* ========== 步骤三：提交成功 ========== */}
          {step === 3 && (
            <div className="text-center py-6">
              <div className="w-16 h-16 bg-green-100 rounded-full flex items-center justify-center mx-auto mb-4">
                <CheckCircle2 className="w-8 h-8 text-green-600" />
              </div>
              <h2 className="text-lg font-semibold text-gray-900 mb-2">
                申请已提交
              </h2>
              <p className="text-sm text-gray-500 mb-6 leading-relaxed">
                我们将在 1-3 个工作日内完成审核，<br />
                审核通过后将短信通知您。
              </p>

              {/* 入驻后可获得的能力展示 */}
              <div className="mb-8 w-full max-w-md mx-auto">
                <p className="text-sm text-gray-500 text-center mb-4">入驻审核通过后，您将获得</p>
                <div className="grid grid-cols-1 gap-3">
                  <div className="flex items-center gap-3 p-3 bg-blue-50 rounded-lg">
                    <div className="w-8 h-8 bg-blue-100 rounded-full flex items-center justify-center flex-shrink-0">
                      <Bot className="w-4 h-4 text-blue-600" />
                    </div>
                    <div className="text-left">
                      <p className="text-sm font-medium text-gray-900">米宝 · 智能工作助手</p>
                      <p className="text-xs text-gray-500">AI驱动的商品、订单、售后智能管理</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-3 p-3 bg-green-50 rounded-lg">
                    <div className="w-8 h-8 bg-green-100 rounded-full flex items-center justify-center flex-shrink-0">
                      <MessageCircle className="w-4 h-4 text-green-600" />
                    </div>
                    <div className="text-left">
                      <p className="text-sm font-medium text-gray-900">小布 · 智能客服</p>
                      <p className="text-xs text-gray-500">7×24小时AI客服，精准服务您的客户</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-3 p-3 bg-purple-50 rounded-lg">
                    <div className="w-8 h-8 bg-purple-100 rounded-full flex items-center justify-center flex-shrink-0">
                      <LayoutDashboard className="w-4 h-4 text-purple-600" />
                    </div>
                    <div className="text-left">
                      <p className="text-sm font-medium text-gray-900">全功能管理后台</p>
                      <p className="text-xs text-gray-500">商品、订单、客户、数据一站式管理</p>
                    </div>
                  </div>
                </div>
              </div>

              <Link
                href="/login"
                className={cn(
                  'inline-flex items-center justify-center gap-2 h-11 px-8 rounded-lg text-sm font-semibold text-white transition-all',
                  'bg-gradient-to-r from-primary-600 to-primary-700',
                  'hover:from-primary-700 hover:to-primary-800 hover:shadow-lg hover:shadow-primary-500/25',
                  'focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:ring-offset-2',
                  'active:scale-[0.98]'
                )}
              >
                <ArrowLeft className="w-4 h-4" />
                返回登录
              </Link>
            </div>
          )}
        </div>

        {/* 底部 */}
        {step < 3 && (
          <div className="mt-6 text-center">
            <Link
              href="/login"
              className="text-sm text-gray-500 hover:text-primary-600 transition-colors"
            >
              ← 返回登录
            </Link>
          </div>
        )}

        <p className="mt-8 text-center text-xs text-gray-400">
          © 2026 米高智能 · 有客
        </p>
      </div>
    </div>
  )
}
