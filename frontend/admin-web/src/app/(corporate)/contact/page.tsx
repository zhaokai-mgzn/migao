import Link from 'next/link'
import { ArrowRight, Building2, MessagesSquare, Sparkles, Users } from 'lucide-react'
import { PageHero, SectionHeading } from '@/components/corporate/CorporateSection'

// 本页必须是**服务端组件**（不要在这里加 'use client'，issue #6307）：
// 根 layout 里的门控对公开路由不渲染骨架，页面正文在服务端渲染进初始 HTML；
// 一旦整页声明 'use client'，SSR 阶段就不渲染正文 ⇒ SEO / 无 JS 环境读到空壳
// （浏览器里却完全正常，所以不会有任何用户可见异常提醒）。
// 类级判据 = frontend/admin-web/tests/unit/pages/corporate-pages-server-component-guard.test.ts
// 首屏实例判据 = frontend/admin-web/tests/unit/pages/anonymous-first-screen-pages.ssr.test.tsx
//
// ⚠️ **留言表单已按用户裁定隐藏**（本单的追加裁定，逐字：「先不放邮箱：表单直接隐藏，只留现有联系方式/FAQ」）。
// 原表单是**假成功**（本地 setTimeout 800ms 后渲染绿框「留言提交成功」，全仓无任何留言接口）
// ⇒ 本页不再挂载任何表单控件，也不再承诺「在线留言 / 留言受理」。
// 表单形态的重启条件 = 用户提供真实联系方式或留言后端接口。

export const helpItems = [
  {
    icon: Sparkles,
    title: '了解产品演示',
    description: '按您的业务场景演示完整链路：算料报价、下单、加工单与报工、入库批次、发货、售后与对账。',
  },
  {
    icon: MessagesSquare,
    title: '沟通 AI 客服边界',
    description:
      '哪些环节交给 AI、哪些保留人工、敏感事项如何处置，我们按您的行业与客单价给出具体建议，而非功能清单。',
  },
  {
    icon: Users,
    title: '评估落地成本',
    description: '提供企业规模、客服人数与现有流程，我们按您的口径测算可节省的人力与时间。',
  },
  {
    icon: Building2,
    title: '合作与代理',
    description:
      '区域合作、行业模板共建、渠道代理等合作事项，请说明合作形式与所在地区；提交入驻申请时一并说明即可。',
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
    answer: '不需要。观星台是多租户 SaaS，浏览器打开就能用；员工端 H5 扫码即开，工人不必安装 App。',
  },
  {
    question: 'AI 会替我做主退款、改价或取消订单吗？',
    answer:
      '不会。顾客侧 AI 不改价、不取消订单、不退款、不承诺优惠折扣，也不报库存数量；涉及价格、折扣、退款金额、赔偿与法律诉求，AI 只做规则解释与材料收集，申请类动作待商家或规范流程确认。',
  },
  {
    question: '价格在哪里查看？',
    answer: '观星台不公示价格。企业规模、开通模块与场景不同，报价随方案一并给出。',
  },
]

export default function ContactPage() {
  return (
    <>
      <PageHero
        kicker="联系方式"
        title="联系我们"
        lead="产品咨询、演示预约、成本评估或合作洽谈，按下面四类诉求说明您的情况即可；开通本身不需要等回复。"
        chips={['按业务场景演示', '不公示价格 · 按需报价', 'AI 自动甄别 · 秒级开通']}
      />

      {/* ── 常见诉求与常见问题 ───────────────────────────────── */}
      <section className="bg-white py-20 sm:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="grid grid-cols-1 gap-12 lg:grid-cols-2 lg:gap-16">
            {/* 左：四类常见诉求 */}            <div>
              <span className="corporate-kicker">常见诉求</span>
              <h2 className="mt-3 text-2xl font-bold text-neutral-900 sm:text-3xl">
                四类常见咨询
              </h2>
              <p className="mt-3 leading-relaxed text-neutral-600">
                说明所属行业、企业规模与当前面临的问题，我们按您的情况给出针对性回复。
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
            </div>

            {/* 右：常见问题 */}
            <div>
              <SectionHeading kicker="常见问题" title="常见问题解答" align="left" />
              <div className="mt-8 grid grid-cols-1 gap-5">
                {faqs.map((faq) => (
                  <div key={faq.question} className="rounded-2xl border border-neutral-200 bg-white p-6">
                    <h3 className="text-base font-semibold text-neutral-900">{faq.question}</h3>
                    <p className="mt-2 text-sm leading-relaxed text-neutral-600">{faq.answer}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* 入驻通道：本页唯一的行动号召（不重复页头已说过的内容） */}
          <div className="mx-auto mt-14 max-w-3xl rounded-2xl border border-primary-100 bg-primary-50/60 p-6 sm:flex sm:items-center sm:justify-between sm:gap-8">
            <div>
              <p className="text-sm font-semibold text-neutral-900">
                可直接开通，无需等待回复
              </p>
              <p className="mt-2 text-sm leading-relaxed text-neutral-600">
                提交入驻申请并完成手机验证后，AI 会自动核验企业信息与合规性，通过即自动开通账号。
              </p>
            </div>
            <Link
              href="/register"
              className="group mt-5 inline-flex shrink-0 items-center gap-2 rounded-xl bg-primary-600 px-6 py-3 text-sm font-semibold text-white transition-colors hover:bg-primary-700 sm:mt-0"
            >
              提交入驻申请
              <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
            </Link>
          </div>
        </div>
      </section>
    </>
  )
}
