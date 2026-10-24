'use client'

import { useEffect, useState, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { AlertCircle, Bell, Check, Trash2, Mail, MailOpen, Inbox } from 'lucide-react'
import { toast } from 'sonner'
import { notificationApi } from '@/lib/api'
import { Pagination, Modal, Button, PageCard, PageHeader, Select } from '@/components/ui'
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

// 业务类型筛选（#7524）：订单/售后/入库单混在一个列表里，商家要找的是「哪一类」
const bizTypeOptions = [
  { value: '', label: '全部类型' },
  { value: 'order', label: '订单' },
  { value: 'after_sales', label: '售后' },
  { value: 'inbound_order', label: '入库单' },
]

/** 严重级圆点（#7524）：urgent 红 / warn 琥珀 / info 主色；老数据为空按 info */
const SEVERITY_DOT: Record<string, string> = {
  info: 'bg-primary-500',
  warn: 'bg-amber-500',
  urgent: 'bg-red-500',
}

// 状态筛选 Tab 配置
const statusTabs: { key: NotificationStatus | ''; label: string; emptyText: string }[] = [
  { key: '', label: '全部', emptyText: '暂无通知' },
  { key: 'sent', label: '未读', emptyText: '暂无未读通知' },
  { key: 'read', label: '已读', emptyText: '暂无已读通知' },
]

export default function NotificationsPage() {
  const router = useRouter()
  const [notifications, setNotifications] = useState<Notification[]>([])
  const [loading, setLoading] = useState(false)
  const [total, setTotal] = useState(0)
  const [current, setCurrent] = useState(1)
  const [pageSize, setPageSize] = useState(20)

  // 筛选
  const [statusFilter, setStatusFilter] = useState<NotificationStatus | ''>('')
  const [bizTypeFilter, setBizTypeFilter] = useState('')

  // 删除确认
  const [deleteModalOpen, setDeleteModalOpen] = useState(false)
  const [deletingNotification, setDeletingNotification] = useState<Notification | null>(null)
  /** 列表读失败（与「暂无通知」互斥，issue #6714）：故障不是业务事实 */
  const [loadFailed, setLoadFailed] = useState(false)

  // 加载通知列表
  const loadNotifications = useCallback(async () => {
    setLoading(true)
    try {
      const params: Record<string, unknown> = {
        page: current,
        size: pageSize,
      }
      if (statusFilter) params.status = statusFilter
      if (bizTypeFilter) params.bizType = bizTypeFilter

      const res = await notificationApi.getNotifications(params as any)
      const pageData = res.data?.data
      setNotifications(pageData?.items || [])
      setTotal(pageData?.total || 0)
      setLoadFailed(false)
    } catch (error) {
      // 读面失败**不清零**（保留上次成功值）、只标失败态 —— 故障 ≠「没有通知」（issue #6714）
      console.error('加载通知失败:', error)
      setLoadFailed(true)
    } finally {
      setLoading(false)
    }
  }, [current, pageSize, statusFilter, bizTypeFilter])

  useEffect(() => {
    loadNotifications()
  }, [loadNotifications])

  // Tab 切换
  const handleTabChange = (status: NotificationStatus | '') => {
    setStatusFilter(status)
    setCurrent(1)
  }

  // 类型切换（#7524）：换类型回到第 1 页，否则会停在一个空页上
  const handleBizTypeChange = (bizType: string) => {
    setBizTypeFilter(bizType)
    setCurrent(1)
  }

  // 点开通知（#7524）：有落地页 ⇒ 标已读后跳转；没有 ⇒ 只标已读（与改前一致）
  const handleOpenNotification = async (notification: Notification) => {
    if (notification.status !== 'read') {
      try {
        await notificationApi.markAsRead(notification.id)
        setNotifications(prev =>
          prev.map(n => n.id === notification.id ? { ...n, status: 'read' as const, readAt: new Date().toISOString() } : n)
        )
      } catch (e) {
        // 跳转优先：标已读失败不阻塞打开单据
      }
    }
    if (notification.targetPath) {
      router.push(notification.targetPath)
    }
  }

  // 全部标记已读：在飞行态 + 禁用（issue #6669 第 5 条）。
  // 修前没有 in-flight 闸 —— 连点两次就发两次请求，商家看到的是随机成功/失败。
  const [markingAll, setMarkingAll] = useState(false)
  const unreadCount = notifications.filter((n) => n.status !== 'read').length

  // 全部标记已读
  const handleMarkAllAsRead = async () => {
    if (markingAll) return
    setMarkingAll(true)
    try {
      await notificationApi.markAllAsRead()
      toast.success('已全部标记为已读')
      loadNotifications()
    } catch (e) {
      toast.error('操作失败')
    } finally {
      setMarkingAll(false)
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
      <div className="mb-6">
        <PageHeader
          title="通知中心"
          subtitle="管理和查看系统通知"
          actions={unreadCount > 0 && (
            /* 🔴 issue #6669 第 5 条：一条未读都没有时这个动作无意义 ⇒ **不出入口**（不是留个点了没反应的按钮）；
                有未读时 in-flight 期间 disabled + loading（连点不发第二次请求）。 */
            <Button
              data-testid="mark-all-read"
              onClick={handleMarkAllAsRead}
              disabled={markingAll}
              loading={markingAll}
            >
              {/* issue #7180：「全部标记已读」用**单勾**（`Check`）。改前是 lucide 的 `CheckCheck`
                  （两条 path 的叠置双勾）—— 16px 下两个勾叠在一起，真机读成「两个图标重叠」
                  （用户报障截图红框）。语义不变：这里只有一个动作 = 标记已读。 */}
              <Check className="w-4 h-4 mr-1.5" aria-hidden />
              全部标记已读
            </Button>
          )}
        />
      </div>

      {/* 状态 Tab 栏 + 列表（与订单/知识库页同构：整宽 Tab 卡 + 整宽列表，故 padded={false}） */}
      <PageCard padded={false}>
      <div className="flex items-center gap-0 border-b border-neutral-200 overflow-x-auto">
        {statusTabs.map((tab) => (
          <button
            key={tab.key}
            onClick={() => handleTabChange(tab.key as NotificationStatus | '')}
            className={cn(
              'relative px-4 py-3 text-sm font-medium whitespace-nowrap transition-colors',
              statusFilter === tab.key
                ? 'text-primary-600'
                : 'text-neutral-500 hover:text-neutral-700'
            )}
          >
            {tab.label}
            {statusFilter === tab.key && (
              <span className="absolute left-0 right-0 -bottom-px h-0.5 bg-primary-600 rounded-full" />
            )}
          </button>
        ))}
        <div className="ml-auto px-3 py-2">
          <Select
            aria-label="按业务类型筛选"
            value={bizTypeFilter}
            onChange={(e) => handleBizTypeChange(e.target.value)}
            options={bizTypeOptions}
            className="w-[132px]"
          />
        </div>
      </div>

      {/* 🔴 issue #6714：读失败 ⇒ 常驻失败面 + 真重发（与下面的空态**互斥**）。
          修前失败只 toast（≈4s 消失），屏上留着「暂无通知」——一句事实性断言。 */}
      {!loading && loadFailed && (
        <div
          data-testid="notifications-load-failed"
          role="alert"
          className="flex items-start gap-3 rounded-lg border border-red-200 bg-red-50 px-4 py-3 mb-4 text-sm text-red-700"
        >
          <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
          <span className="flex-1">通知加载失败 —— 不是没有通知，是没读到。请检查网络后重试</span>
          <button
            type="button"
            data-testid="notifications-load-failed-retry"
            onClick={() => void loadNotifications()}
            className="flex-shrink-0 rounded border border-red-300 px-2 py-1 text-xs font-medium text-red-700 hover:bg-red-100"
          >
            重试
          </button>
        </div>
      )}

      {/* 通知列表 */}
      <div className="border-neutral-200">
        {loading ? (
          <div className="flex items-center justify-center py-20">
            <div className="w-6 h-6 border-2 border-primary-200 border-t-primary-600 rounded-full animate-spin" />
          </div>
        ) : !loadFailed && notifications.length === 0 ? (
          /* 空状态（**真为空**时才出现） */
          <div data-testid="notifications-empty" className="flex flex-col items-center justify-center py-20 text-neutral-400">
            <Inbox className="w-12 h-12 mb-3 stroke-[1.5]" />
            <p className="text-sm">{getEmptyText()}</p>
          </div>
        ) : (
          <div className="divide-y divide-neutral-100">
            {notifications.map((notification) => (
              <div
                key={notification.id}
                data-testid={`notification-item-${notification.id}`}
                onClick={() => void handleOpenNotification(notification)}
                className={cn(
                  'px-5 py-4 transition-colors hover:bg-neutral-50',
                  notification.status !== 'read' && 'bg-primary-50/30',
                  // 有落地页才给可点反馈；无 targetPath 的行不假装可点（#7524）
                  notification.targetPath && 'cursor-pointer'
                )}
              >
                <div className="flex gap-3">
                  {/* 未读蓝色圆点 */}
                  <div className="flex-shrink-0 pt-1.5">
                    <div
                      className={cn(
                        'w-2.5 h-2.5 rounded-full',
                        notification.status !== 'read'
                          ? (SEVERITY_DOT[notification.severity || 'info'] || 'bg-primary-500')
                          : 'bg-transparent'
                      )}
                    />
                  </div>

                  {/* 内容区 */}
                  <div className="flex-1 min-w-0">
                    <p className={cn(
                      'text-sm leading-5',
                      notification.status !== 'read' ? 'font-semibold text-neutral-900' : 'font-medium text-neutral-700'
                    )}>
                      {notification.title}
                    </p>
                    <p className="text-sm text-neutral-500 mt-1 line-clamp-2 leading-5">
                      {notification.content}
                    </p>

                    {/* 底部：渠道标签 + 时间 + 操作 */}
                    <div className="flex items-center gap-3 mt-2">
                      <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-neutral-100 text-neutral-600">
                        {ChannelLabels[notification.channel] || notification.channel}
                      </span>
                      <span className="text-xs text-neutral-400">
                        {formatRelativeTime(notification.createdAt)}
                      </span>
                      <div className="flex items-center gap-1 ml-auto">
                        {notification.status !== 'read' ? (
                          <button
                            onClick={(e) => { e.stopPropagation(); void handleMarkAsRead(notification) }}
                            className="flex items-center gap-1 px-2 py-1 text-xs text-neutral-500 hover:text-primary-600 hover:bg-primary-50 rounded transition-colors"
                            title="标记已读"
                          >
                            <MailOpen className="w-3.5 h-3.5" />
                            标记已读
                          </button>
                        ) : (
                          <span className="flex items-center gap-1 px-2 py-1 text-xs text-neutral-400">
                            <Mail className="w-3.5 h-3.5" />
                            已读
                          </span>
                        )}
                        <button
                          onClick={(e) => { e.stopPropagation(); handleDelete(notification) }}
                          className="flex items-center gap-1 px-2 py-1 text-xs text-neutral-500 hover:text-red-600 hover:bg-red-50 rounded transition-colors"
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
      </PageCard>

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
        <p className="text-neutral-600">
          确定要删除通知 <span className="font-medium text-neutral-900">&ldquo;{deletingNotification?.title}&rdquo;</span> 吗？此操作不可恢复。
        </p>
      </Modal>
    </div>
  )
}
