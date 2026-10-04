'use client'

import { useState } from 'react'
import Link from 'next/link'
import {
  ArrowRight,
  Building2,
  CheckCircle,
  MessagesSquare,
  Send,
  Sparkles,
  Users,
} from 'lucide-react'
import { PageHero, SectionHeading } from '@/components/corporate/CorporateSection'

export const helpItems = [
  {
    icon: Sparkles,
    title: '想看产品演示',
    description: '按你的业务场景走一遍：算料报价、下单、加工单与报工、入库批次、发货、售后与对账。',
  },
  {
    icon: MessagesSquare,
    title: '想聊 AI 客服边界',
    description:
      '哪些交给 AI、哪些留给人工、敏感事项怎么兜底 —— 我们按你的行业与客单价给具体建议，而不是给一张功能表。',
  },
  {
    icon: Users,
    title: '想评估落地成本',
    description: '说明门店数量、客服人数与现有流程，我们按你的口径算一遍能省下多少人力与时间。',
  },
  {
    icon: Building2,
    title: '想了解合作与代理',
    description: '区域合作、行业模板共建、渠道代理等合作事项，请在留言里写明合作形式与所在地区。',
  },
]

export const faqs = [
  {
    question: '开通需要多久？',
    answer:
      '提交企业信息并完成手机验证后，AI 自动核验企业信息与合规性并秒级返回结论，通过即自动开通账号，无需等待人工审核。',
  },
  {
    question: '需要我们自己准备服务器吗？',
    answer: '不需要。米高是多租户 SaaS，浏览器打开就能用；员工端 H5 扫码即开，工人不必安装 App。',
  },
  {
    question: 'AI 会替我做主退款、改价或取消订单吗？',
    answer:
      '不会。顾客侧 AI 不改价、不取消订单、不退款、不承诺优惠折扣，也不报库存数量；涉及价格、折扣、退款金额、赔偿与法律诉求，AI 只做规则解释与材料收集，申请类动作待商家或规范流程确认。',
  },
  {
    question: '价格在哪里看？',
    answer:
      '本页面不公示价格。请在留言中说明门店规模与希望开通的模块，我们的团队会按你的情况给出方案与报价。',
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
    <>
      <PageHero
        kicker="联系方式"
        title="联系我们"
        lead="想聊产品、想看演示、想评估成本或谈合作 —— 在下面留言说明你的情况，我们的团队会在工作时间内回复你。"
        chips={['按业务场景演示', '不公示价格 · 按需报价', 'AI 自动甄别 · 秒级开通']}
      />

      {/* ── 留言与说明 ───────────────────────────────────────── */}
      <section className="bg-white py-20 sm:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="grid grid-cols-1 gap-12 lg:grid-cols-2 lg:gap-16">
            {/* 左：我们能帮你什么 */}
            <div>
              <span className="text-[11px] font-semibold uppercase tracking-[0.18em] text-accent-600">
                先说说你的情况
              </span>
              <h2 className="mt-3 text-2xl font-bold text-neutral-900 sm:text-3xl">
                留言前，可以先对一下方向
              </h2>
              <p className="mt-3 leading-relaxed text-neutral-600">
                这四类问题我们最常见。留言时写清你的行业、门店规模与现在卡在哪一步，回复会更有针对性。
              </p>

              <div className="mt-8 space-y-4">
                {helpItems.map((item) => (
                  <div
                    key={item.title}
                    className="flex gap-4 rounded-2xl border border-neutral-200 bg-neutral-50/60 p-5"
                  >
                    <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-white ring-1 ring-neutral-200">
                      <item.icon className="h-5 w-5 text-primary-600" />
                    </div>
                    <div>
                      <p className="text-sm font-semibold text-neutral-900">{item.title}</p>
                      <p className="mt-1 text-sm leading-relaxed text-neutral-600">
                        {item.description}
                      </p>
                    </div>
                  </div>
                ))}
              </div>

              <div className="mt-8 rounded-2xl border border-primary-100 bg-primary-50/60 p-6">
                <p className="text-sm font-semibold text-neutral-900">
                  只想直接开通？不必等我们回信
                </p>
                <p className="mt-2 text-sm leading-relaxed text-neutral-600">
                  提交入驻申请并完成手机验证后，AI 会自动核验企业信息与合规性，通过即自动开通账号。
                </p>
                <Link
                  href="/register"
                  className="group mt-5 inline-flex items-center gap-2 rounded-xl bg-primary-600 px-6 py-3 text-sm font-semibold text-white transition-colors hover:bg-primary-700"
                >
                  去提交入驻申请
                  <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
                </Link>
              </div>
            </div>

            {/* 右：留言表单 */}
            <div>
              <span className="text-[11px] font-semibold uppercase tracking-[0.18em] text-accent-600">
                在线留言
              </span>
              <h2 className="mt-3 text-2xl font-bold text-neutral-900 sm:text-3xl">给我们留言</h2>
              <p className="mt-3 leading-relaxed text-neutral-600">
                填写以下信息，我们会按你留下的联系方式回复。
              </p>

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
                    <label
                      htmlFor="name"
                      className="mb-1.5 block text-sm font-medium text-neutral-700"
                    >
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
                    <label
                      htmlFor="phone"
                      className="mb-1.5 block text-sm font-medium text-neutral-700"
                    >
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
                  <label
                    htmlFor="message"
                    className="mb-1.5 block text-sm font-medium text-neutral-700"
                  >
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
          </div>
        </div>
      </section>

      {/* ── 常见问题 ─────────────────────────────────────────── */}
      <section className="bg-neutral-50 py-20 sm:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <SectionHeading kicker="常见问题" title="留言之前，这几个问题先答一遍" />
          <div className="mx-auto mt-14 grid max-w-4xl grid-cols-1 gap-5 md:grid-cols-2">
            {faqs.map((faq) => (
              <div key={faq.question} className="rounded-2xl border border-neutral-200 bg-white p-6">
                <h3 className="text-base font-semibold text-neutral-900">{faq.question}</h3>
                <p className="mt-2 text-sm leading-relaxed text-neutral-600">{faq.answer}</p>
              </div>
            ))}
          </div>
        </div>
      </section>
    </>
  )
}
