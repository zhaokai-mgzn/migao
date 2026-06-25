'use client'

import { useState } from 'react'
import { MapPin, Phone, Mail, Clock, Send, CheckCircle, Building2 } from 'lucide-react'

const contactInfo = [
  {
    icon: MapPin,
    label: '公司地址',
    value: '浙江省杭州市余杭区文一西路000号',
  },
  {
    icon: Phone,
    label: '联系电话',
    value: '400-888-8888',
  },
  {
    icon: Mail,
    label: '电子邮箱',
    value: 'contact@migao-ai.com',
  },
  {
    icon: Clock,
    label: '工作时间',
    value: '周一至周五 9:00-18:00',
  },
]

interface FormData {
  name: string
  phone: string
  email: string
  message: string
}

interface FormErrors {
  name?: string
  phone?: string
  email?: string
  message?: string
}

export default function ContactPage() {
  const [form, setForm] = useState<FormData>({
    name: '',
    phone: '',
    email: '',
    message: '',
  })
  const [errors, setErrors] = useState<FormErrors>({})
  const [submitted, setSubmitted] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  const validate = (): boolean => {
    const errs: FormErrors = {}
    if (!form.name.trim()) errs.name = '请输入您的姓名'
    if (!form.phone.trim()) {
      errs.phone = '请输入您的联系电话'
    } else if (!/^[\d\-+() ]{7,20}$/.test(form.phone.trim())) {
      errs.phone = '请输入有效的电话号码'
    }
    if (!form.email.trim()) {
      errs.email = '请输入您的电子邮箱'
    } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email.trim())) {
      errs.email = '请输入有效的邮箱地址'
    }
    if (!form.message.trim()) {
      errs.message = '请输入留言内容'
    } else if (form.message.trim().length < 10) {
      errs.message = '留言内容至少10个字符'
    }
    setErrors(errs)
    return Object.keys(errs).length === 0
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!validate()) return

    setSubmitting(true)
    // Simulate API submission with a short delay
    await new Promise((resolve) => setTimeout(resolve, 800))
    setSubmitting(false)

    // Show success and reset
    setSubmitted(true)
    setForm({ name: '', phone: '', email: '', message: '' })
    setErrors({})

    // Hide success message after 5 seconds
    setTimeout(() => setSubmitted(false), 5000)
  }

  const handleChange = (field: keyof FormData, value: string) => {
    setForm((prev) => ({ ...prev, [field]: value }))
    // Clear field error on change
    if (errors[field]) {
      setErrors((prev) => {
        const next = { ...prev }
        delete next[field]
        return next
      })
    }
  }

  const inputClasses = (field: keyof FormData) =>
    `w-full px-4 py-3 border rounded-xl text-sm transition-all duration-200 outline-none ${
      errors[field]
        ? 'border-red-300 focus:ring-2 focus:ring-red-200 focus:border-red-400 bg-red-50/30'
        : 'border-gray-200 focus:ring-2 focus:ring-blue-200 focus:border-blue-400 bg-white hover:border-gray-300'
    }`

  return (
    <>
      {/* Page Header */}
      <section className="relative bg-gradient-to-br from-blue-600 via-blue-700 to-indigo-800 text-white py-16 sm:py-20 overflow-hidden">
        <div
          className="absolute inset-0 opacity-10"
          style={{
            backgroundImage: 'radial-gradient(circle, rgba(255,255,255,0.8) 1px, transparent 1px)',
            backgroundSize: '24px 24px',
          }}
        />
        <div className="absolute -top-24 -right-24 w-80 h-80 bg-blue-400/15 rounded-full blur-3xl" />
        <div className="absolute -bottom-24 -left-24 w-64 h-64 bg-indigo-400/15 rounded-full blur-3xl" />

        <div className="relative mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 text-center">
          <h1 className="text-3xl sm:text-4xl lg:text-5xl font-extrabold tracking-tight">
            联系我们
          </h1>
          <p className="mt-4 text-lg sm:text-xl text-blue-100/90 max-w-2xl mx-auto leading-relaxed">
            无论您有任何疑问或合作意向，我们都期待与您取得联系
          </p>
        </div>
      </section>

      {/* Contact Content */}
      <section className="py-20 sm:py-28 bg-white">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-12 lg:gap-16">
            {/* Left: Contact Info */}
            <div>
              <span className="text-sm font-semibold text-blue-600 uppercase tracking-wider">
                联系信息
              </span>
              <h2 className="mt-2 text-2xl sm:text-3xl font-bold text-gray-900">
                期待与您沟通
              </h2>
              <p className="mt-3 text-gray-500 leading-relaxed">
                欢迎通过以下方式联系我们，我们的团队将在工作时间内尽快回复您。
              </p>

              <div className="mt-8 space-y-5">
                {contactInfo.map((item) => (
                  <div key={item.label} className="group flex items-start gap-4 p-4 rounded-xl hover:bg-slate-50 transition-colors duration-200">
                    <div className="w-11 h-11 bg-gradient-to-br from-blue-50 to-indigo-50 rounded-xl flex items-center justify-center shrink-0 group-hover:from-blue-100 group-hover:to-indigo-100 transition-all duration-300">
                      <item.icon className="w-5 h-5 text-blue-600" />
                    </div>
                    <div>
                      <p className="text-xs font-medium text-gray-400 uppercase tracking-wider">
                        {item.label}
                      </p>
                      <p className="text-base text-gray-900 mt-0.5 font-medium">
                        {item.value}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Right: Contact Form */}
            <div>
              <span className="text-sm font-semibold text-blue-600 uppercase tracking-wider">
                在线留言
              </span>
              <h2 className="mt-2 text-2xl sm:text-3xl font-bold text-gray-900">
                给我们留言
              </h2>
              <p className="mt-3 text-gray-500 leading-relaxed">
                填写以下表单，我们会尽快与您联系
              </p>

              {/* Success Message */}
              {submitted && (
                <div className="mt-6 p-4 bg-green-50 border border-green-200 rounded-xl flex items-center gap-3 animate-[fadeIn_0.3s_ease-out]">
                  <div className="w-10 h-10 bg-green-100 rounded-full flex items-center justify-center shrink-0">
                    <CheckCircle className="w-5 h-5 text-green-600" />
                  </div>
                  <div>
                    <p className="text-sm font-semibold text-green-800">留言提交成功！</p>
                    <p className="text-xs text-green-600 mt-0.5">感谢您的留言，我们将在 1-2 个工作日内回复您。</p>
                  </div>
                </div>
              )}

              <form className="mt-6 space-y-5" onSubmit={handleSubmit} noValidate>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
                  <div>
                    <label htmlFor="name" className="block text-sm font-medium text-gray-700 mb-1.5">
                      姓名 <span className="text-red-400">*</span>
                    </label>
                    <input
                      type="text"
                      id="name"
                      name="name"
                      value={form.name}
                      onChange={(e) => handleChange('name', e.target.value)}
                      placeholder="请输入您的姓名"
                      className={inputClasses('name')}
                    />
                    {errors.name && (
                      <p className="mt-1 text-xs text-red-500">{errors.name}</p>
                    )}
                  </div>
                  <div>
                    <label htmlFor="phone" className="block text-sm font-medium text-gray-700 mb-1.5">
                      电话 <span className="text-red-400">*</span>
                    </label>
                    <input
                      type="tel"
                      id="phone"
                      name="phone"
                      value={form.phone}
                      onChange={(e) => handleChange('phone', e.target.value)}
                      placeholder="请输入您的联系电话"
                      className={inputClasses('phone')}
                    />
                    {errors.phone && (
                      <p className="mt-1 text-xs text-red-500">{errors.phone}</p>
                    )}
                  </div>
                </div>
                <div>
                  <label htmlFor="email" className="block text-sm font-medium text-gray-700 mb-1.5">
                    邮箱 <span className="text-red-400">*</span>
                  </label>
                  <input
                    type="email"
                    id="email"
                    name="email"
                    value={form.email}
                    onChange={(e) => handleChange('email', e.target.value)}
                    placeholder="请输入您的电子邮箱"
                    className={inputClasses('email')}
                  />
                  {errors.email && (
                    <p className="mt-1 text-xs text-red-500">{errors.email}</p>
                  )}
                </div>
                <div>
                  <label htmlFor="message" className="block text-sm font-medium text-gray-700 mb-1.5">
                    留言内容 <span className="text-red-400">*</span>
                  </label>
                  <textarea
                    id="message"
                    name="message"
                    rows={5}
                    value={form.message}
                    onChange={(e) => handleChange('message', e.target.value)}
                    placeholder="请输入您想咨询的内容（至少10个字符）..."
                    className={inputClasses('message') + ' resize-none'}
                  />
                  {errors.message && (
                    <p className="mt-1 text-xs text-red-500">{errors.message}</p>
                  )}
                </div>
                <button
                  type="submit"
                  disabled={submitting}
                  className="group w-full sm:w-auto inline-flex items-center justify-center gap-2 px-8 py-3.5 text-sm font-semibold text-white bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed rounded-xl transition-all duration-300 shadow-sm hover:shadow-md"
                >
                  {submitting ? (
                    <>
                      <svg className="animate-spin w-4 h-4" viewBox="0 0 24 24" fill="none">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                      </svg>
                      提交中...
                    </>
                  ) : (
                    <>
                      提交留言
                      <Send className="w-4 h-4 group-hover:translate-x-0.5 transition-transform" />
                    </>
                  )}
                </button>
              </form>
            </div>
          </div>
        </div>
      </section>

      {/* Company Info Card (replaces map placeholder) */}
      <section className="py-16 sm:py-20 bg-slate-50">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="max-w-3xl mx-auto">
            <div className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden">
              <div className="grid grid-cols-1 sm:grid-cols-2 divide-y sm:divide-y-0 sm:divide-x divide-gray-100">
                {/* Address & Location */}
                <div className="p-6 sm:p-8">
                  <div className="flex items-center gap-3 mb-4">
                    <div className="w-10 h-10 bg-gradient-to-br from-blue-50 to-indigo-50 rounded-xl flex items-center justify-center">
                      <Building2 className="w-5 h-5 text-blue-600" />
                    </div>
                    <h3 className="text-lg font-semibold text-gray-900">公司地址</h3>
                  </div>
                  <p className="text-sm text-gray-600 leading-relaxed">
                    浙江省杭州市余杭区文一西路000号
                  </p>
                  <p className="text-xs text-gray-400 mt-2">
                    距地铁5号线创景路站步行10分钟
                  </p>
                </div>

                {/* Business Hours */}
                <div className="p-6 sm:p-8">
                  <div className="flex items-center gap-3 mb-4">
                    <div className="w-10 h-10 bg-gradient-to-br from-blue-50 to-indigo-50 rounded-xl flex items-center justify-center">
                      <Clock className="w-5 h-5 text-blue-600" />
                    </div>
                    <h3 className="text-lg font-semibold text-gray-900">工作时间</h3>
                  </div>
                  <div className="space-y-2 text-sm text-gray-600">
                    <div className="flex justify-between">
                      <span>周一至周五</span>
                      <span className="font-medium text-gray-900">9:00 - 18:00</span>
                    </div>
                    <div className="flex justify-between">
                      <span>周六</span>
                      <span className="font-medium text-gray-900">10:00 - 16:00</span>
                    </div>
                    <div className="flex justify-between">
                      <span>周日</span>
                      <span className="text-gray-400">休息</span>
                    </div>
                  </div>
                </div>
              </div>

              {/* Bottom bar */}
              <div className="border-t border-gray-100 px-6 sm:px-8 py-4 bg-slate-50/50 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2">
                <p className="text-xs text-gray-400">
                  法定节假日工作时间可能调整，请提前致电确认
                </p>
                <a
                  href="tel:400-888-8888"
                  className="inline-flex items-center gap-1.5 text-sm font-medium text-blue-600 hover:text-blue-700 transition-colors"
                >
                  <Phone className="w-3.5 h-3.5" />
                  400-888-8888
                </a>
              </div>
            </div>
          </div>
        </div>
      </section>
    </>
  )
}
