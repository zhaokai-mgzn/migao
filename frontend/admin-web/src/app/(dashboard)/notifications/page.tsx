'use client'

import { useEffect, useState, useCallback } from 'react'
import { Bell, CheckCheck, Trash2, Mail, MailOpen, Inbox } from 'lucide-react'
import { toast } from 'sonner'
import { notificationApi } from '@/lib/api'
import { Pagination, Modal, Button } from '@/components/ui'
import type { Notification, NotificationStatus, NotificationChannel } from '@/types'
import { cn } from '@/lib/utils'

// 相对时间格式化（与 NotificationBell 一致）
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

// 渠道标签映射
const ChannelLabels: Record<NotificationChannel, string> = {
  internal: '站内信',
  sms: '短信',
  wechat: '微信',
  email: '邮件',
}

// 状态筛选 Tab 配置
const statusTabs: { key: NotificationStatus | ''; label: string; emptyText: string }[] = [
  { key: '', label: '全部', emptyText: '暂无通知' },
  { key: 'sent', label: '未读', emptyText: '暂无未读通知' },
  { key: 'read', label: '已读', emptyText: '暂无已读通知' },
]

export default function NotificationsPage() {
  const [notifications, setNotifications] = useState<Notification[]>([])
  const [loading, setLoading] = useState(false)
  const [total, setTotal] = useState(0)
  const [current, setCurrent] = useState(1)
  const [pageSize, setPageSize] = useState(20)

  // 筛选
  const [statusFilter, setStatusFilter] = useState<NotificationStatus | ''>('')

  // 删除确认
  const [deleteModalOpen, setDeleteModalOpen] = useState(false)
  const [deletingNotification, setDeletingNotification] = useState<Notification | null>(null)

  // 加载通知列表
  const loadNotifications = useCallback(async () => {
    setLoading(true)
    try {
      const params: Record<string, unknown> = {
        page: current,
        size: pageSize,
      }
      if (statusFilter) params.status = statusFilter

      const res = await notificationApi.getNotifications(params as any)
      const pageData = res.data?.data
      setNotifications(pageData?.items || [])
      setTotal(pageData?.total || 0)
    } catch (error) {
      console.error('加载通知失败:', error)
      toast.error('加载通知失败')
    } finally {
      setLoading(false)
    }
  }, [current, pageSize, statusFilter])

  useEffect(() => {
    loadNotifications()
  }, [loadNotifications])

  // Tab 切换
  const handleTabChange = (status: NotificationStatus | '') => {
    setStatusFilter(status)
    setCurrent(1)
  }

  // 全部标记已读
  const handleMarkAllAsRead = async () => {
    try {
      await notificationApi.markAllAsRead()
      toast.success('已全部标记为已读')
      loadNotifications()
    } catch (e) {
      toast.error('操作失败')
    }
  }

  // 标记单条已读
  const handleMarkAsRead = async (notification: Notification) => {
    if (notification.status === 'read') return
    try {
      await notificationApi.markAsRead(notification.id)
      setNotifications(prev =>
        prev.map(n => n.id === notification.id ? { ...n, status: 'read' as const, readAt: new Date().toISOString() } : n)
      )
      toast.success('已标记为已读')
    } catch (e) {
      toast.error('操作失败')
    }
  }

  // 删除通知
  const handleDelete = (notification: Notification) => {
    setDeletingNotification(notification)
    setDeleteModalOpen(true)
  }

  const confirmDelete = async () => {
    if (!deletingNotification) return
    try {
      await notificationApi.deleteNotification(deletingNotification.id)
      toast.success('删除成功')
      loadNotifications()
    } catch (e) {
      toast.error('删除失败')
    } finally {
      setDeleteModalOpen(false)
      setDeletingNotification(null)
    }
  }

  // 获取当前筛选的空状态文案
  const getEmptyText = () => {
    const tab = statusTabs.find(t => t.key === statusFilter)
    return tab?.emptyText || '暂无通知'
  }

  return (
    <div className="p-6">
      {/* 页面标题 */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">通知中心</h1>
          <p className="text-sm text-gray-500 mt-1">管理和查看系统通知</p>
        </div>
        <Button onClick={handleMarkAllAsRead}>
          <CheckCheck className="w-4 h-4 mr-1.5" />
          全部标记已读
        </Button>
      </div>

      {/* 状态 Tab 栏 */}
      <div className="flex items-center gap-0 bg-white border border-gray-200 rounded-t-lg overflow-x-auto">
        {statusTabs.map((tab) => (
          <button
            key={tab.key}
            onClick={() => handleTabChange(tab.key as NotificationStatus | '')}
            className={cn(
              'relative px-4 py-3 text-sm font-medium whitespace-nowrap transition-colors border-b-2',
              statusFilter === tab.key
                ? 'text-primary-600 border-primary-600 bg-primary-50/50'
                : 'text-gray-500 border-transparent hover:text-gray-700 hover:bg-gray-50'
            )}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* 通知列表 */}
      <div className="bg-white rounded-b-lg border border-t-0 border-gray-200">
        {loading ? (
          <div className="flex items-center justify-center py-20">
            <div className="w-6 h-6 border-2 border-primary-200 border-t-primary-600 rounded-full animate-spin" />
          </div>
        ) : notifications.length === 0 ? (
          /* 空状态 */
          <div className="flex flex-col items-center justify-center py-20 text-gray-400">
            <Inbox className="w-12 h-12 mb-3 stroke-[1.5]" />
            <p className="text-sm">{getEmptyText()}</p>
          </div>
        ) : (
          <div className="divide-y divide-gray-100">
            {notifications.map((notification) => (
              <div
                key={notification.id}
                className={cn(
                  'px-5 py-4 transition-colors hover:bg-gray-50',
                  notification.status !== 'read' && 'bg-blue-50/30'
                )}
              >
                <div className="flex gap-3">
                  {/* 未读蓝色圆点 */}
                  <div className="flex-shrink-0 pt-1.5">
                    <div
                      className={cn(
                        'w-2.5 h-2.5 rounded-full',
                        notification.status !== 'read' ? 'bg-blue-500' : 'bg-transparent'
                      )}
                    />
                  </div>

                  {/* 内容区 */}
                  <div className="flex-1 min-w-0">
                    <p className={cn(
                      'text-sm leading-5',
                      notification.status !== 'read' ? 'font-semibold text-gray-900' : 'font-medium text-gray-700'
                    )}>
                      {notification.title}
                    </p>
                    <p className="text-sm text-gray-500 mt-1 line-clamp-2 leading-5">
                      {notification.content}
                    </p>

                    {/* 底部：渠道标签 + 时间 + 操作 */}
                    <div className="flex items-center gap-3 mt-2">
                      <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-gray-100 text-gray-600">
                        {ChannelLabels[notification.channel] || notification.channel}
                      </span>
                      <span className="text-xs text-gray-400">
                        {formatRelativeTime(notification.createdAt)}
                      </span>
                      <div className="flex items-center gap-1 ml-auto">
                        {notification.status !== 'read' ? (
                          <button
                            onClick={() => handleMarkAsRead(notification)}
                            className="flex items-center gap-1 px-2 py-1 text-xs text-gray-500 hover:text-primary-600 hover:bg-primary-50 rounded transition-colors"
                            title="标记已读"
                          >
                            <MailOpen className="w-3.5 h-3.5" />
                            标记已读
                          </button>
                        ) : (
                          <span className="flex items-center gap-1 px-2 py-1 text-xs text-gray-400">
                            <Mail className="w-3.5 h-3.5" />
                            已读
                          </span>
                        )}
                        <button
                          onClick={() => handleDelete(notification)}
                          className="flex items-center gap-1 px-2 py-1 text-xs text-gray-500 hover:text-red-600 hover:bg-red-50 rounded transition-colors"
                          title="删除"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                          删除
                        </button>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* 分页 */}
        {notifications.length > 0 && (
          <Pagination
            current={current}
            pageSize={pageSize}
            total={total}
            onChange={setCurrent}
            onPageSizeChange={(size) => { setPageSize(size); setCurrent(1) }}
          />
        )}
      </div>

      {/* 删除确认弹窗 */}
      <Modal
        open={deleteModalOpen}
        onClose={() => setDeleteModalOpen(false)}
        title="确认删除"
        footer={
          <>
            <Button variant="secondary" onClick={() => setDeleteModalOpen(false)}>取消</Button>
            <Button variant="danger" onClick={confirmDelete}>确认删除</Button>
          </>
        }
      >
        <p className="text-gray-600">
          确定要删除通知 <span className="font-medium text-gray-900">&ldquo;{deletingNotification?.title}&rdquo;</span> 吗？此操作不可恢复。
        </p>
      </Modal>
    </div>
  )
}
