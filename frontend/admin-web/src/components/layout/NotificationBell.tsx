'use client'

import { useState, useEffect, useRef, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { Bell, Check, CheckCheck, Inbox } from 'lucide-react'
import { notificationApi } from '@/lib/api'
import { cn } from '@/lib/utils'
import type { Notification } from '@/types'

// 相对时间格式化
function formatRelativeTime(dateStr: string): string {
  const now = Date.now()
  const date = new Date(dateStr).getTime()
  const diff = now - date

  const seconds = Math.floor(diff / 1000)
  if (seconds < 60) return '刚刚'

  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}分钟前`

  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}小时前`

  const days = Math.floor(hours / 24)
  if (days < 30) return `${days}天前`

  const months = Math.floor(days / 30)
  return `${months}个月前`
}

const POLL_INTERVAL = 30_000

export default function NotificationBell() {
  const router = useRouter()
  const [open, setOpen] = useState(false)
  const [unreadCount, setUnreadCount] = useState(0)
  const [notifications, setNotifications] = useState<Notification[]>([])
  const [loading, setLoading] = useState(false)
  const panelRef = useRef<HTMLDivElement>(null)
  const buttonRef = useRef<HTMLButtonElement>(null)

  // 获取未读数
  const fetchUnreadCount = useCallback(async () => {
    try {
      const res = await notificationApi.getUnreadCount()
      setUnreadCount(res.data?.data?.count ?? 0)
    } catch {
      // 静默降级
    }
  }, [])

  // 获取最近通知列表
  const fetchNotifications = useCallback(async () => {
    setLoading(true)
    try {
      const res = await notificationApi.getNotifications({ page: 1, size: 5 })
      setNotifications(res.data?.data?.items ?? [])
    } catch {
      // 静默降级
    } finally {
      setLoading(false)
    }
  }, [])

  // 挂载时立即获取 + 轮询
  useEffect(() => {
    fetchUnreadCount()
    const timer = setInterval(fetchUnreadCount, POLL_INTERVAL)
    return () => clearInterval(timer)
  }, [fetchUnreadCount])

  // 打开面板时拉取列表
  useEffect(() => {
    if (open) {
      fetchNotifications()
    }
  }, [open, fetchNotifications])

  // 点击外部关闭面板
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (
        panelRef.current &&
        !panelRef.current.contains(e.target as Node) &&
        buttonRef.current &&
        !buttonRef.current.contains(e.target as Node)
      ) {
        setOpen(false)
      }
    }
    if (open) {
      document.addEventListener('mousedown', handleClickOutside)
    }
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [open])

  // 标记单条已读
  const handleMarkAsRead = useCallback(async (notification: Notification) => {
    if (notification.status === 'read') return
    try {
      await notificationApi.markAsRead(notification.id)
      setNotifications(prev =>
        prev.map(n => n.id === notification.id ? { ...n, status: 'read', readAt: new Date().toISOString() } : n)
      )
      setUnreadCount(prev => Math.max(0, prev - 1))
    } catch {
      // 静默降级
    }
  }, [])

  // 全部标记已读
  const handleMarkAllAsRead = useCallback(async () => {
    try {
      await notificationApi.markAllAsRead()
      setNotifications(prev => prev.map(n => ({ ...n, status: 'read' as const, readAt: new Date().toISOString() })))
      setUnreadCount(0)
    } catch {
      // 静默降级
    }
  }, [])

  // 查看全部
  const handleViewAll = useCallback(() => {
    setOpen(false)
    router.push('/notifications')
  }, [router])

  const togglePanel = useCallback(() => {
    setOpen(prev => !prev)
  }, [])

  return (
    <div className="relative">
      {/* 铃铛按钮 */}
      <button
        ref={buttonRef}
        onClick={togglePanel}
        className="relative p-2 text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded-lg transition-colors"
      >
        <Bell className="w-5 h-5" />
        {unreadCount > 0 && (
          <span className="absolute -top-0.5 -right-0.5 min-w-[18px] h-[18px] px-1 flex items-center justify-center text-[10px] font-medium text-white bg-red-500 rounded-full leading-none">
            {unreadCount > 99 ? '99+' : unreadCount}
          </span>
        )}
      </button>

      {/* 下拉通知面板 */}
      {open && (
        <div
          ref={panelRef}
          className={cn(
            'absolute right-0 top-full mt-2 w-[360px]',
            'bg-white rounded-lg shadow-card border border-gray-100',
            'z-50 overflow-hidden',
            'animate-in fade-in slide-in-from-top-2 duration-200'
          )}
        >
          {/* 面板头部 */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100">
            <h3 className="text-sm font-semibold text-gray-900">通知</h3>
            {unreadCount > 0 && (
              <button
                onClick={handleMarkAllAsRead}
                className="flex items-center gap-1 text-xs text-primary-600 hover:text-primary-700 transition-colors"
              >
                <CheckCheck className="w-3.5 h-3.5" />
                全部已读
              </button>
            )}
          </div>

          {/* 通知列表 */}
          <div className="max-h-[320px] overflow-y-auto">
            {loading ? (
              <div className="flex items-center justify-center py-10">
                <div className="w-5 h-5 border-2 border-primary-200 border-t-primary-600 rounded-full animate-spin" />
              </div>
            ) : notifications.length === 0 ? (
              /* 空状态 */
              <div className="flex flex-col items-center justify-center py-10 text-gray-400">
                <Inbox className="w-10 h-10 mb-2 stroke-[1.5]" />
                <p className="text-sm">暂无通知</p>
              </div>
            ) : (
              notifications.map(notification => (
                <button
                  key={notification.id}
                  onClick={() => handleMarkAsRead(notification)}
                  className={cn(
                    'w-full text-left px-4 py-3 border-b border-gray-50 last:border-b-0',
                    'hover:bg-gray-50 transition-colors',
                    notification.status !== 'read' && 'bg-blue-50/30'
                  )}
                >
                  <div className="flex gap-3">
                    {/* 未读蓝色圆点 */}
                    <div className="flex-shrink-0 pt-1.5">
                      <div
                        className={cn(
                          'w-2 h-2 rounded-full',
                          notification.status !== 'read' ? 'bg-blue-500' : 'bg-transparent'
                        )}
                      />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className={cn(
                        'text-sm leading-5 truncate',
                        notification.status !== 'read' ? 'font-medium text-gray-900' : 'text-gray-700'
                      )}>
                        {notification.title}
                      </p>
                      <p className="text-xs text-gray-500 mt-0.5 line-clamp-2 leading-4">
                        {notification.content}
                      </p>
                      <p className="text-[11px] text-gray-400 mt-1">
                        {formatRelativeTime(notification.createdAt)}
                      </p>
                    </div>
                  </div>
                </button>
              ))
            )}
          </div>

          {/* 底部操作栏 */}
          <div className="flex items-center justify-between px-4 py-2.5 border-t border-gray-100 bg-gray-50/50">
            <button
              onClick={handleMarkAllAsRead}
              className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-700 transition-colors"
            >
              <Check className="w-3.5 h-3.5" />
              全部标记已读
            </button>
            <button
              onClick={handleViewAll}
              className="text-xs text-primary-600 hover:text-primary-700 font-medium transition-colors"
            >
              查看全部 →
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
