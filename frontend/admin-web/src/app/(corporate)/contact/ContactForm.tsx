'use client'

import { useState } from 'react'
import { CheckCircle, Send } from 'lucide-react'

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

interface ContactFormProps {
  kicker: string
  title: string
  lead: string
}

/**
 * 联系页的**在线留言表单**（唯一需要客户端状态的部分，issue #6307）。
 *
 * 为什么单独成一个文件：上一级 `page.tsx` 必须是**服务端组件** —— 一旦整个页面声明 `'use client'`，
 * SSR 阶段就整段不渲染，正文进不了初始 HTML（SEO / 无 JS 环境读到空壳）。
 * 把交互态收在这一个客户端组件里，静态文案与结构留在服务端组件中。
 *
 * 校验规则、提交成功反馈与按钮三态（提交留言 / 提交中... / 成功）与拆分前**逐字一致**，
 * 用户可见行为零变化。
 */
export default function ContactForm({ kicker, title, lead }: ContactFormProps) {
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
    // 当前为前端演示提交：接入留言接口后改为真实请求（issue #6291 登记）
    await new Promise((resolve) => setTimeout(resolve, 800))
    setSubmitting(false)

    setSubmitted(true)
    setForm({ name: '', phone: '', email: '', message: '' })
    setErrors({})
  }

  const handleChange = (field: keyof FormData, value: string) => {
    setForm((prev) => ({ ...prev, [field]: value }))
    if (errors[field]) {
      setErrors((prev) => {
        const next = { ...prev }
        delete next[field]
        return next
      })
    }
  }

  const inputClasses = (field: keyof FormData) =>
    `w-full rounded-xl border px-4 py-3 text-sm outline-none transition-all duration-200 ${
      errors[field]
        ? 'border-red-300 bg-red-50/30 focus:border-red-400 focus:ring-2 focus:ring-red-200'
        : 'border-neutral-200 bg-white hover:border-neutral-300 focus:border-primary-400 focus:ring-2 focus:ring-primary-100'
    }`

  return (
    <div>
      <span className="text-[11px] font-semibold uppercase tracking-[0.18em] text-accent-600">
        {kicker}
      </span>
      <h2 className="mt-3 text-2xl font-bold text-neutral-900 sm:text-3xl">{title}</h2>
      <p className="mt-3 leading-relaxed text-neutral-600">{lead}</p>

      {submitted && (
        <div
          role="status"
          className="mt-6 flex items-center gap-3 rounded-xl border border-emerald-200 bg-emerald-50 p-4"
        >
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-emerald-100">
            <CheckCircle className="h-5 w-5 text-emerald-600" />
          </div>
          <div>
            <p className="text-sm font-semibold text-emerald-900">留言提交成功</p>
            <p className="mt-0.5 text-xs text-emerald-700">
              感谢你的留言，我们会在工作时间内回复你留下的联系方式。
            </p>
          </div>
        </div>
      )}

      <form className="mt-6 space-y-5" onSubmit={handleSubmit} noValidate>
        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
          <div>
            <label htmlFor="name" className="mb-1.5 block text-sm font-medium text-neutral-700">
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
            {errors.name && <p className="mt-1 text-xs text-red-500">{errors.name}</p>}
          </div>
          <div>
            <label htmlFor="phone" className="mb-1.5 block text-sm font-medium text-neutral-700">
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
            {errors.phone && <p className="mt-1 text-xs text-red-500">{errors.phone}</p>}
          </div>
        </div>
        <div>
          <label htmlFor="email" className="mb-1.5 block text-sm font-medium text-neutral-700">
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
          {errors.email && <p className="mt-1 text-xs text-red-500">{errors.email}</p>}
        </div>
        <div>
          <label htmlFor="message" className="mb-1.5 block text-sm font-medium text-neutral-700">
            留言内容 <span className="text-red-400">*</span>
          </label>
          <textarea
            id="message"
            name="message"
            rows={5}
            value={form.message}
            onChange={(e) => handleChange('message', e.target.value)}
            placeholder="行业、门店规模、现在卡在哪一步（至少10个字符）..."
            className={`${inputClasses('message')} resize-none`}
          />
          {errors.message && <p className="mt-1 text-xs text-red-500">{errors.message}</p>}
        </div>
        <button
          type="submit"
          disabled={submitting}
          className="group inline-flex w-full items-center justify-center gap-2 rounded-xl bg-primary-600 px-8 py-3.5 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-primary-700 disabled:cursor-not-allowed disabled:opacity-50 sm:w-auto"
        >
          {submitting ? (
            <>
              <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none">
                <circle
                  className="opacity-25"
                  cx="12"
                  cy="12"
                  r="10"
                  stroke="currentColor"
                  strokeWidth="4"
                />
                <path
                  className="opacity-75"
                  fill="currentColor"
                  d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                />
              </svg>
              提交中...
            </>
          ) : (
            <>
              提交留言
              <Send className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
            </>
          )}
        </button>
        <p className="text-xs leading-relaxed text-neutral-400">
          提交留言即表示你同意我们通过所留联系方式与你联系；我们仅将这些信息用于本次沟通。
        </p>
      </form>
    </div>
  )
}
