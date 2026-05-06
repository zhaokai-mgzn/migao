'use client'

import { useRouter } from 'next/navigation'
import { 
  User, 
  LogOut, 
  ChevronDown 
} from 'lucide-react'
import { useAuthStore } from '@/store/auth'
import { cn } from '@/lib/utils'
import NotificationBell from './NotificationBell'

interface HeaderProps {
  title?: string
  breadcrumbs?: { label: string; href?: string }[]
}

export default function Header({ title, breadcrumbs }: HeaderProps) {
  const router = useRouter()
  const { user, logout } = useAuthStore()

  const handleLogout = async () => {
    await logout()
    router.push('/login')
  }

  // 获取当前页面标题
  const pageTitle = title || '数据看板'

  return (
    <header className="h-14 bg-white border-b border-gray-200 flex items-center justify-between px-6 sticky top-0 z-40">
      {/* 左侧：面包屑 / 页面标题 */}
      <div className="flex items-center">
        {breadcrumbs ? (
          <nav className="flex items-center text-sm">
            {breadcrumbs.map((crumb, index) => (
              <div key={index} className="flex items-center">
                {index > 0 && (
                  <span className="mx-2 text-gray-400">/</span>
                )}
                {crumb.href ? (
                  <a 
                    href={crumb.href}
                    className="text-gray-500 hover:text-primary-600 transition-colors"
                  >
                    {crumb.label}
                  </a>
                ) : (
                  <span className="text-gray-900 font-medium">
                    {crumb.label}
                  </span>
                )}
              </div>
            ))}
          </nav>
        ) : (
          <h1 className="text-base font-medium text-gray-900">{pageTitle}</h1>
        )}
      </div>

      {/* 右侧：通知 + 用户信息 */}
      <div className="flex items-center gap-4">
        {/* 通知铃铛 */}
        <NotificationBell />

        {/* 用户下拉菜单 */}
        <div className="relative group">
          <button className="flex items-center gap-2 p-1.5 pr-3 rounded-lg hover:bg-gray-100 transition-colors">
            {/* 头像 */}
            <div className="w-8 h-8 bg-primary-100 rounded-full flex items-center justify-center">
              <User className="w-4 h-4 text-primary-600" />
            </div>
            {/* 昵称 */}
            <span className="text-sm text-gray-700 hidden sm:block">
              {user?.name || user?.nickname || user?.username || '管理员'}
            </span>
            <ChevronDown className="w-4 h-4 text-gray-400 hidden sm:block" />
          </button>

          {/* 下拉菜单 */}
          <div className={cn(
            'absolute right-0 top-full mt-1 w-48 py-1',
            'bg-white rounded-lg shadow-card border border-gray-100',
            'opacity-0 invisible group-hover:opacity-100 group-hover:visible',
            'transition-all duration-200'
          )}>
            <div className="px-4 py-2 border-b border-gray-100">
              <p className="text-sm font-medium text-gray-900">
                {user?.name || user?.nickname || user?.username || '管理员'}
              </p>
              <p className="text-xs text-gray-500">
                {user?.email || user?.username || ''}
              </p>
            </div>
            <button
              onClick={handleLogout}
              className="w-full flex items-center gap-2 px-4 py-2 text-sm text-red-600 hover:bg-red-50 transition-colors"
            >
              <LogOut className="w-4 h-4" />
              退出登录
            </button>
          </div>
        </div>
      </div>
    </header>
  )
}
