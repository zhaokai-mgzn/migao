import Link from 'next/link'
import Logo from '@/components/ui/Logo'

const quickLinks = [
  { name: '首页', href: '/' },
  { name: '产品服务', href: '/services' },
  { name: '关于我们', href: '/about' },
  { name: '联系方式', href: '/contact' },
  { name: '商家入驻', href: '/register' },
]

export default function CorporateFooter() {
  return (
    <footer className="bg-slate-900 text-slate-300">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        {/* Main Footer Content */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-10 py-12 border-b border-slate-800">
          {/* Company Info */}
          <div className="space-y-4">
            <div className="flex items-center gap-2.5">
              <Logo size="small" />
              <span className="text-lg font-semibold text-white tracking-tight">
                米高
              </span>
            </div>
            <p className="text-sm text-slate-400 leading-relaxed max-w-xs">
              米高致力于为企业提供一站式AI电商管理解决方案，
              助力商家提升服务效率与客户体验。
            </p>
          </div>

          {/* Quick Links */}
          <div>
            <h3 className="text-sm font-semibold text-white uppercase tracking-wider mb-4">
              快速链接
            </h3>
            <ul className="space-y-2.5">
              {quickLinks.map((link) => (
                <li key={link.href}>
                  <Link
                    href={link.href}
                    className="text-sm text-slate-400 hover:text-white transition-colors"
                  >
                    {link.name}
                  </Link>
                </li>
              ))}
            </ul>
          </div>

          {/* Contact Info */}
          <div>
            <h3 className="text-sm font-semibold text-white uppercase tracking-wider mb-4">
              联系我们
            </h3>
            <ul className="space-y-3 text-sm text-slate-400">
              <li className="flex items-start gap-2">
                <span className="shrink-0">电话：</span>
                <span>400-888-8888</span>
              </li>
              <li className="flex items-start gap-2">
                <span className="shrink-0">邮箱：</span>
                <span>contact@migao-ai.com</span>
              </li>
              <li className="flex items-start gap-2">
                <span className="shrink-0">地址：</span>
                <span>浙江省杭州市余杭区文一西路000号</span>
              </li>
            </ul>
          </div>
        </div>

        {/* Copyright */}
        <div className="py-6 text-center text-sm text-slate-500">
          © 2026 词元通达 · 米高 版权所有
        </div>
      </div>
    </footer>
  )
}
