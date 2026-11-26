'use client'

import { useState, useEffect } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { Menu, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import Logo from '@/components/ui/Logo'
import { merchantLoginUrl } from '@/lib/site-domain'
// 内测期隐藏自助入驻入口（issue #9066）：开关单一来源见 @/config/onboarding
import { SELF_SERVICE_ONBOARDING_OPEN } from '@/config/onboarding'

const navItems = [
  { name: '首页', href: '/' },
  { name: '产品能力', href: '/services' },
  // 终端下载页（issue #8195）：终端安装包是商家真正要拿到手的东西，必须有常驻入口
  { name: '下载中心', href: '/download' },
  { name: '关于我们', href: '/about' },
  { name: '联系方式', href: '/contact' },
]

export default function CorporateNav() {
  const pathname = usePathname()
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const [scrolled, setScrolled] = useState(false)
  // 「商家登录」落点跟着站点域名走（issue #8941）：写死 merchant.migaozn.com 会把
  // 生产环境的商家送去**测试域**登录（桌面 + 移动两处共用这一个值）。
  const merchantLogin = merchantLoginUrl()

  useEffect(() => {
    const handleScroll = () => {
      setScrolled(window.scrollY > 10)
    }
    handleScroll()
    window.addEventListener('scroll', handleScroll, { passive: true })
    return () => window.removeEventListener('scroll', handleScroll)
  }, [])

  const isActive = (href: string) => {
    if (href === '/') return pathname === '/'
    return pathname.startsWith(href)
  }

  return (
    <header
      className={cn(
        'sticky top-0 z-50 transition-all duration-300',
        scrolled
          ? 'border-b border-neutral-200 bg-neutral-50/95 shadow-sm backdrop-blur-md'
          : 'border-b border-transparent bg-neutral-50/80 backdrop-blur-sm'
      )}
    >
      {/* 顶部织金细线：把品牌色带进导航 */}
      <div className="h-0.5 bg-gradient-to-r from-gold-600 via-accent-500 to-primary-600" />

      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="flex h-16 items-center justify-between">
          {/* Logo */}
          <Link href="/" className="flex shrink-0 items-center gap-2.5">
            <Logo size="small" />
            <span className="text-lg font-semibold tracking-tight text-neutral-900">
              生意管家
            </span>
          </Link>

          {/* Desktop Navigation */}
          <nav className="hidden items-center gap-1 md:flex">
            {navItems.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  'rounded-lg px-4 py-2 text-sm font-medium transition-colors',
                  isActive(item.href)
                    ? 'bg-primary-50 text-primary-600'
                    : 'text-neutral-600 hover:bg-neutral-100 hover:text-neutral-900'
                )}
              >
                {item.name}
              </Link>
            ))}
          </nav>

          {/* Desktop CTA Buttons */}
          <div className="hidden items-center gap-3 md:flex">
            <a
              href={merchantLogin}
              className="px-4 py-2 text-sm font-medium text-neutral-700 transition-colors hover:text-neutral-900"
            >
              商家登录
            </a>
            <Link
              href="/contact"
              className="rounded-lg bg-primary-600 px-5 py-2 text-sm font-medium text-white shadow-sm transition-colors hover:bg-primary-700"
            >
              预约演示
            </Link>
            {SELF_SERVICE_ONBOARDING_OPEN && (
              <Link
                href="/register"
                className="rounded-lg border border-primary-200 px-5 py-2 text-sm font-medium text-primary-700 transition-colors hover:bg-primary-50"
              >
                商家入驻
              </Link>
            )}
          </div>

          {/* Mobile Menu Toggle */}
          <button
            type="button"
            className="rounded-lg p-2 text-neutral-600 transition-colors hover:bg-neutral-100 md:hidden"
            onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
            aria-label={mobileMenuOpen ? '关闭菜单' : '打开菜单'}
          >
            {mobileMenuOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </button>
        </div>
      </div>

      {/* Mobile Menu */}
      {mobileMenuOpen && (
        <div className="border-t border-neutral-200 bg-neutral-50 md:hidden">
          <div className="space-y-1 px-4 py-3">
            {navItems.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                onClick={() => setMobileMenuOpen(false)}
                className={cn(
                  'block rounded-lg px-4 py-2.5 text-sm font-medium transition-colors',
                  isActive(item.href)
                    ? 'bg-primary-50 text-primary-600'
                    : 'text-neutral-600 hover:bg-neutral-100 hover:text-neutral-900'
                )}
              >
                {item.name}
              </Link>
            ))}
            <div className="mt-3 space-y-2 border-t border-neutral-200 pt-3">
              <Link
                href="/contact"
                onClick={() => setMobileMenuOpen(false)}
                className="block rounded-lg bg-primary-600 px-4 py-2.5 text-center text-sm font-medium text-white transition-colors hover:bg-primary-700"
              >
                预约演示
              </Link>
              <a
                href={merchantLogin}
                onClick={() => setMobileMenuOpen(false)}
                className="block rounded-lg px-4 py-2.5 text-center text-sm font-medium text-neutral-700 transition-colors hover:bg-neutral-100"
              >
                商家登录
              </a>
              {SELF_SERVICE_ONBOARDING_OPEN && (
                <Link
                  href="/register"
                  onClick={() => setMobileMenuOpen(false)}
                  className="block rounded-lg bg-primary-600 px-4 py-2.5 text-center text-sm font-medium text-white transition-colors hover:bg-primary-700"
                >
                  商家入驻
                </Link>
              )}
            </div>
          </div>
        </div>
      )}
    </header>
  )
}
