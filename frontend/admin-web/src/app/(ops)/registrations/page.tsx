'use client'

import { useEffect, useState, useCallback } from 'react'
import { Eye } from 'lucide-react'
import { toast } from 'sonner'
import { registrationApi } from '@/lib/api'
import { Pagination, Modal, Button, Badge } from '@/components/ui'
import type { Registration, RegistrationStatus } from '@/types'
import { RegistrationStatusLabels, RegistrationStatusColors } from '@/types'
import dayjs from 'dayjs'
import { cn, resolveImageUrl } from '@/lib/utils'
import DateTimeCell from '@/components/common/DateTimeCell'

// 状态 Tab 配置
const statusTabs: { key: RegistrationStatus | ''; label: string }[] = [
  { key: '', label: '全部' },
  { key: 'pending', label: '待审核' },
  { key: 'approved', label: '已通过' },
  { key: 'rejected', label: '已驳回' },
]

export default function RegistrationsPage() {
  const [registrations, setRegistrations] = useState<Registration[]>([])
  const [loading, setLoading] = useState(false)
  const [total, setTotal] = useState(0)
  const [current, setCurrent] = useState(1)
  const [pageSize, setPageSize] = useState(20)

  // 筛选
  const [statusFilter, setStatusFilter] = useState<RegistrationStatus | ''>('')

  // 审批通过确认弹窗
  const [approveModalOpen, setApproveModalOpen] = useState(false)
  const [approvingItem, setApprovingItem] = useState<Registration | null>(null)
  const [approving, setApproving] = useState(false)

  // 驳回弹窗
  const [rejectModalOpen, setRejectModalOpen] = useState(false)
  const [rejectingItem, setRejectingItem] = useState<Registration | null>(null)
  const [rejectReason, setRejectReason] = useState('')
  const [rejecting, setRejecting] = useState(false)

  // 详情弹窗
  const [detailModalOpen, setDetailModalOpen] = useState(false)
  const [detailItem, setDetailItem] = useState<Registration | null>(null)

  // 加载列表
  const loadRegistrations = useCallback(async () => {
    setLoading(true)
    try {
      const params: Record<string, unknown> = {
        page: current,
        size: pageSize,
      }
      if (statusFilter) params.status = statusFilter

      const res = await registrationApi.getRegistrations(params as any)
      const pageData = res.data?.data
      setRegistrations(pageData?.items || [])
      setTotal(pageData?.total || 0)
    } catch (error) {
      console.error('加载申请列表失败:', error)
      toast.error('加载申请列表失败')
    } finally {
      setLoading(false)
    }
  }, [current, pageSize, statusFilter])

  useEffect(() => {
    loadRegistrations()
  }, [loadRegistrations])

  // Tab 切换
  const handleTabChange = (status: RegistrationStatus | '') => {
    setStatusFilter(status)
    setCurrent(1)
  }

  // 审批通过
  const handleApprove = (item: Registration) => {
    setApprovingItem(item)
    setApproveModalOpen(true)
  }

  const confirmApprove = async () => {
    if (!approvingItem) return
    setApproving(true)
    try {
      await registrationApi.approveRegistration(approvingItem.id)
      toast.success('审批通过成功')
      loadRegistrations()
    } catch (e) {
      toast.error('审批操作失败')
    } finally {
      setApproving(false)
      setApproveModalOpen(false)
      setApprovingItem(null)
    }
  }

  // 驳回
  const handleReject = (item: Registration) => {
    setRejectingItem(item)
    setRejectReason('')
    setRejectModalOpen(true)
  }

  const confirmReject = async () => {
    if (!rejectingItem) return
    if (!rejectReason.trim()) {
      toast.error('请填写驳回原因')
      return
    }
    setRejecting(true)
    try {
      await registrationApi.rejectRegistration(rejectingItem.id, rejectReason.trim())
      toast.success('已驳回该申请')
      loadRegistrations()
    } catch (e) {
      toast.error('驳回操作失败')
    } finally {
      setRejecting(false)
      setRejectModalOpen(false)
      setRejectingItem(null)
      setRejectReason('')
    }
  }

  // 查看详情
  const handleViewDetail = async (item: Registration) => {
    try {
      const res = await registrationApi.getRegistrationDetail(item.id)
      setDetailItem(res.data?.data || item)
    } catch (e) {
      setDetailItem(item)
    }
    setDetailModalOpen(true)
  }

  return (
    <div>
      {/* 页面标题 */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">企业入驻审批</h1>
          <p className="text-sm text-gray-500 mt-1">审核企业入驻申请，管理平台租户</p>
        </div>
      </div>

      {/* 状态 Tab 栏 */}
      <div className="flex items-center gap-0 bg-white border border-gray-200 rounded-t-lg overflow-x-auto">
        {statusTabs.map((tab) => (
          <button
            key={tab.key}
            onClick={() => handleTabChange(tab.key as RegistrationStatus | '')}
            className={cn(
              'relative px-4 py-3 text-sm font-medium whitespace-nowrap transition-colors border-b-2',
              statusFilter === tab.key
                ? 'text-blue-600 border-blue-600 bg-blue-50/50'
                : 'text-gray-500 border-transparent hover:text-gray-700 hover:bg-gray-50'
            )}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* 数据表格 */}
      <div className="bg-white rounded-b-lg border border-t-0 border-gray-200">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-200 bg-gray-50/80">
                <th className="text-left px-4 py-3 font-medium text-gray-600">企业名称</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">联系人</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">手机号</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">行业</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">状态</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">申请时间</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">操作</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={7} className="text-center py-12 text-gray-400">
                    加载中...
                  </td>
                </tr>
              ) : registrations.length === 0 ? (
                <tr>
                  <td colSpan={7} className="text-center py-12 text-gray-400">
                    暂无数据
                  </td>
                </tr>
              ) : (
                registrations.map((item) => (
                  <tr key={item.id} className="border-b border-gray-100 hover:bg-gray-50/50">
                    <td className="px-4 py-3 font-medium text-gray-900">{item.companyName}</td>
                    <td className="px-4 py-3 text-gray-700">{item.contactName}</td>
                    <td className="px-4 py-3 text-gray-700">{item.phone}</td>
                    <td className="px-4 py-3 text-gray-700">{item.industry || '-'}</td>
                    <td className="px-4 py-3">
                      <Badge variant={RegistrationStatusColors[item.status]}>
                        {RegistrationStatusLabels[item.status]}
                      </Badge>
                    </td>
                    <td className="px-4 py-3 text-gray-500">
                      <DateTimeCell value={item.createdAt} />
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        {item.status === 'pending' ? (
                          <>
                            <button
                              onClick={() => handleApprove(item)}
                              className="text-xs px-2.5 py-1 rounded bg-green-50 text-green-700 hover:bg-green-100 transition-colors font-medium"
                            >
                              审批通过
                            </button>
                            <button
                              onClick={() => handleReject(item)}
                              className="text-xs px-2.5 py-1 rounded bg-red-50 text-red-700 hover:bg-red-100 transition-colors font-medium"
                            >
                              驳回
                            </button>
                          </>
                        ) : (
                          <button
                            onClick={() => handleViewDetail(item)}
                            className="text-xs px-2.5 py-1 rounded bg-gray-50 text-gray-700 hover:bg-gray-100 transition-colors font-medium inline-flex items-center gap-1"
                          >
                            <Eye className="w-3.5 h-3.5" />
                            查看详情
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* 分页 */}
        <Pagination
          current={current}
          pageSize={pageSize}
          total={total}
          onChange={setCurrent}
          onPageSizeChange={(size) => { setPageSize(size); setCurrent(1) }}
        />
      </div>

      {/* 审批通过确认弹窗 */}
      <Modal
        open={approveModalOpen}
        onClose={() => setApproveModalOpen(false)}
        title="确认审批通过"
        footer={
          <>
            <Button variant="secondary" onClick={() => setApproveModalOpen(false)}>取消</Button>
            <Button onClick={confirmApprove} loading={approving}>确认通过</Button>
          </>
        }
      >
        <p className="text-gray-600">
          确定要通过企业 <span className="font-medium text-gray-900">{approvingItem?.companyName}</span> 的入驻申请吗？
          通过后系统将自动创建租户和管理员账号。
        </p>
      </Modal>

      {/* 驳回弹窗 */}
      <Modal
        open={rejectModalOpen}
        onClose={() => setRejectModalOpen(false)}
        title="驳回申请"
        footer={
          <>
            <Button variant="secondary" onClick={() => setRejectModalOpen(false)}>取消</Button>
            <Button variant="danger" onClick={confirmReject} loading={rejecting}>确认驳回</Button>
          </>
        }
      >
        <div className="space-y-4">
          <p className="text-gray-600">
            驳回企业 <span className="font-medium text-gray-900">{rejectingItem?.companyName}</span> 的入驻申请
          </p>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">驳回原因</label>
            <textarea
              value={rejectReason}
              onChange={(e) => setRejectReason(e.target.value)}
              placeholder="请填写驳回原因..."
              rows={3}
              className="w-full px-3 py-2 rounded border border-gray-300 bg-white text-sm focus:outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-500/15 resize-none"
            />
          </div>
        </div>
      </Modal>

      {/* 详情 Modal */}
      <Modal
        open={detailModalOpen}
        onClose={() => setDetailModalOpen(false)}
        title="申请详情"
        width={600}
        footer={
          <Button variant="secondary" onClick={() => setDetailModalOpen(false)}>关闭</Button>
        }
      >
        {detailItem && (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <DetailField label="企业名称" value={detailItem.companyName} />
              <DetailField label="联系人" value={detailItem.contactName} />
              <DetailField label="手机号" value={detailItem.phone} />
              <DetailField label="行业" value={detailItem.industry} />
              <DetailField label="地址" value={detailItem.address} span={2} />
              <DetailField label="企业描述" value={detailItem.description} span={2} />
              <DetailField
                label="状态"
                value={
                  <Badge variant={RegistrationStatusColors[detailItem.status]}>
                    {RegistrationStatusLabels[detailItem.status]}
                  </Badge>
                }
              />
              <DetailField
                label="申请时间"
                value={detailItem.createdAt ? dayjs(detailItem.createdAt).format('YYYY-MM-DD HH:mm:ss') : '-'}
              />
              {detailItem.status === 'rejected' && (
                <DetailField label="驳回原因" value={detailItem.rejectReason} span={2} />
              )}
              {detailItem.reviewedAt && (
                <DetailField
                  label="审核时间"
                  value={dayjs(detailItem.reviewedAt).format('YYYY-MM-DD HH:mm:ss')}
                />
              )}
            </div>
            {detailItem.businessLicenseUrl && (
              <div>
                <label className="block text-sm font-medium text-gray-500 mb-2">营业执照</label>
                <img
                  src={resolveImageUrl(detailItem.businessLicenseUrl)}
                  alt="营业执照"
                  className="max-w-full max-h-64 rounded-lg border border-gray-200 object-contain"
                />
              </div>
            )}
          </div>
        )}
      </Modal>
    </div>
  )
}

// 详情字段组件
function DetailField({
  label,
  value,
  span = 1,
}: {
  label: string
  value?: React.ReactNode
  span?: number
}) {
  return (
    <div className={span === 2 ? 'col-span-2' : ''}>
      <label className="block text-xs font-medium text-gray-500 mb-1">{label}</label>
      <div className="text-sm text-gray-900">{value || '-'}</div>
    </div>
  )
}
