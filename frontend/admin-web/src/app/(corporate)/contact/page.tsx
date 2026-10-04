import Link from 'next/link'
import { ArrowRight, Building2, MessagesSquare, Sparkles, Users } from 'lucide-react'
import { PageHero, SectionHeading } from '@/components/corporate/CorporateSection'
import ContactForm from './ContactForm'

// 本页必须是**服务端组件**（不要在这里加 'use client'，issue #6307）：
// 根 layout 的 AuthProvider 在 SSR 阶段只渲染 loading 骨架，页面正文只有走服务端渲染
// 才会进初始 HTML；而声明 'use client' 会让整页在 SSR 阶段不渲染
// ⇒ SEO / 无 JS 环境读到空壳（浏览器里却完全正常，所以不会有任何用户可见异常提醒你）。
// 交互态（表单 / 校验 / 提交反馈）收在同目录的 ContactForm 客户端组件里。
// 类级判据 = frontend/admin-web/tests/unit/pages/corporate-pages-server-component-guard.test.ts

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

export default function ContactPage() {
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

            {/* 右：留言表单（客户端组件 —— 交互态在这里，静态文案与结构留在本服务端组件） */}
            <ContactForm
              kicker="在线留言"
              title="给我们留言"
              lead="填写以下信息，我们会按你留下的联系方式回复。"
            />
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
