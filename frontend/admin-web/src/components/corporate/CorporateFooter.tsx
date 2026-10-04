import Link from 'next/link'
import Logo from '@/components/ui/Logo'

const quickLinks = [
  { name: '首页', href: '/' },
  { name: '产品服务', href: '/services' },
  { name: '关于我们', href: '/about' },
  { name: '联系方式', href: '/contact' },
  { name: '商家入驻', href: '/register' },
]

/** 能力域入口（都落在「产品服务」页的能力清单上） */
const capabilityLinks = [
  '经营看板与每日简报',
  '商品、订单与售后工单',
  '生产工序与计件工资',
  '入库批次与余料台账',
  '客户档案与岗位权限',
]

export default function CorporateFooter() {
  return (
    <footer className="bg-neutral-900 text-neutral-300">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="grid grid-cols-1 gap-10 border-b border-neutral-800 py-12 md:grid-cols-2 lg:grid-cols-4">
          {/* 品牌与主体 */}
          <div className="space-y-4">
            <div className="flex items-center gap-2.5">
              <Logo size="small" />
              <span className="text-lg font-semibold tracking-tight text-white">米高</span>
            </div>
            <p className="max-w-xs text-sm leading-relaxed text-neutral-400">
              杭州词元通达科技有限公司出品的米高平台：面向布艺 / 窗帘商家的多租户 AI
              经营平台，顾客侧小布、经营侧米宝，共用同一套业务数据。
            </p>
          </div>

          {/* 快速链接 */}
          <div>
            <h3 className="mb-4 text-sm font-semibold tracking-wider text-white">快速链接</h3>
            <ul className="space-y-2.5">
              {quickLinks.map((link) => (
                <li key={link.href}>
                  <Link href={link.href} className="text-sm text-neutral-400 transition-colors hover:text-white">
                    {link.name}
                  </Link>
                </li>
              ))}
            </ul>
          </div>

          {/* 产品能力 */}
          <div>
            <h3 className="mb-4 text-sm font-semibold tracking-wider text-white">产品能力</h3>
            <ul className="space-y-2.5">
              {capabilityLinks.map((name) => (
                <li key={name}>
                  <Link href="/services" className="text-sm text-neutral-400 transition-colors hover:text-white">
                    {name}
                  </Link>
                </li>
              ))}
            </ul>
          </div>

          {/* 开始使用 */}
          <div>
            <h3 className="mb-4 text-sm font-semibold tracking-wider text-white">开始使用</h3>
            <ul className="space-y-2.5 text-sm text-neutral-400">
              <li>提交入驻申请并完成手机验证</li>
              <li>AI 自动核验企业信息与合规性</li>
              <li>通过后即刻开通管理后台与两位 AI</li>
            </ul>
            <Link
              href="/register"
              className="mt-5 inline-flex rounded-lg bg-white px-5 py-2.5 text-sm font-semibold text-neutral-900 transition-colors hover:bg-neutral-100"
            >
              商家入驻
            </Link>
          </div>
        </div>

        <div className="space-y-3 py-6 text-center text-xs leading-relaxed text-neutral-500">
          <p>
            「遵循 / 对标 GB/T 47746-2026」指小布智能客服的人机协同机制功能设计参考该推荐性国家标准；该标准为推荐性标准、无认证或备案机制，本页面不构成任何认证、检测或备案结论。
          </p>
          <p>本页面展示的功能以实际开通版本为准；报价与交付内容由双方另行确认。</p>
          <p>© 2026 杭州词元通达科技有限公司 · 米高 版权所有</p>
        </div>
      </div>
    </footer>
  )
}
