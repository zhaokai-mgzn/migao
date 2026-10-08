'use client'

import { useState, useEffect } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { Menu, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import Logo from '@/components/ui/Logo'

const navItems = [
  { name: '首页', href: '/' },
  { name: '产品服务', href: '/services' },
  { name: '关于我们', href: '/about' },
  { name: '联系方式', href: '/contact' },
]

export default function CorporateNav() {
  const pathname = usePathname()
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const [scrolled, setScrolled] = useState(false)

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
      <div className="h-0.5 bg-gradient-to-r from-[#d48806] via-accent-500 to-primary-600" />

      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="flex h-16 items-center justify-between">
          {/* Logo */}
          <Link href="/" className="flex shrink-0 items-center gap-2.5">
            <Logo size="small" />
            <span className="text-lg font-semibold tracking-tight text-neutral-900">
              观星台
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
              href="https://merchant.migaozn.com/login"
              className="px-4 py-2 text-sm font-medium text-neutral-700 transition-colors hover:text-neutral-900"
            >
              商家登录
            </a>
            <Link
              href="/register"
              className="rounded-lg bg-primary-600 px-5 py-2 text-sm font-medium text-white shadow-sm transition-colors hover:bg-primary-700"
            >
              商家入驻
            </Link>
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
              <a
                href="https://merchant.migaozn.com/login"
                onClick={() => setMobileMenuOpen(false)}
                className="block rounded-lg px-4 py-2.5 text-center text-sm font-medium text-neutral-700 transition-colors hover:bg-neutral-100"
              >
                商家登录
              </a>
              <Link
                href="/register"
                onClick={() => setMobileMenuOpen(false)}
                className="block rounded-lg bg-primary-600 px-4 py-2.5 text-center text-sm font-medium text-white transition-colors hover:bg-primary-700"
              >
                商家入驻
              </Link>
            </div>
          </div>
        </div>
      )}
    </header>
  )
}
