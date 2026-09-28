'use client'

import { useCallback, useEffect, useState } from 'react'
import { Plus, Search } from 'lucide-react'
import { toast } from 'sonner'
import { workerApi } from '@/lib/api'
import { toastRequestError } from '@/lib/api-error'
import { Button, Input, Select, Modal, Table, Badge, Pagination } from '@/components/ui'
import type { TableColumn } from '@/components/ui'
import type { EmployeeStatus, WorkerProfile } from '@/types'

/**
 * 工人档案（issue #4869）—— **产品路径：第一个工人怎么建出来**。
 *
 * 改前形态：全仓没有任何入口能设 `users.worker_no`（无控制台 / 无接口 / 无种子）
 * ⇒ 工号 + PIN 登录（#4733，早已落码）在真实部署里**永远没有可登录的对象**。
 *
 * 与员工的关系（本组件存在的理由）：
 * - 工人**不是**员工：零菜单权限、无登录用户名、只能用工号 + PIN 进工人端扫码报工
 *   ⇒ 不能混进员工列表（那会「看起来像员工」，点编辑还能改岗位/权限，而那条路根本不成立）。
 *   本面板独立成 Tab；服务端也在 `UserService.getUserPage` 里排除 `role=worker`。
 * - 权限码**复用**员工域（`employee:create` / `employee:list`）—— 新增权限码要走迁移 + 全租户回填，
 *   而工人在产品上就是人事管理的一部分。
 * - 停用 / 启用**复用**既有 `PUT /api/admin/users/{id}/status`（`workerApi.setWorkerStatus`），不另造端点。
 */
interface WorkerProfilesPanelProps {
  /** 是否持有 `employee:create`（无此权限 ⇒ 只读） */
  canWrite: boolean
}

export default function WorkerProfilesPanel({ canWrite }: WorkerProfilesPanelProps) {
  const [workers, setWorkers] = useState<WorkerProfile[]>([])
  const [loading, setLoading] = useState(false)
  const [total, setTotal] = useState(0)
  const [current, setCurrent] = useState(1)
  const [pageSize, setPageSize] = useState(10)

  const [keyword, setKeyword] = useState('')
  const [searchKeyword, setSearchKeyword] = useState('')
  const [statusFilter, setStatusFilter] = useState<'' | EmployeeStatus>('')
  const [searchStatus, setSearchStatus] = useState<'' | EmployeeStatus>('')

  const [formOpen, setFormOpen] = useState(false)
  const [form, setForm] = useState({ workerNo: '', name: '', pin: '' })
  const [creating, setCreating] = useState(false)
  const [togglingId, setTogglingId] = useState<string | null>(null)

  const loadWorkers = useCallback(async () => {
    setLoading(true)
    try {
      const res = await workerApi.listWorkers({
        page: current,
        size: pageSize,
        keyword: searchKeyword || undefined,
        status: searchStatus || undefined,
      })
      const data = res.data.data
      setWorkers(data?.items || [])
      setTotal(data?.total || 0)
    } catch (e) {
      toastRequestError(e, '加载工人档案失败')
    } finally {
      setLoading(false)
    }
  }, [current, pageSize, searchKeyword, searchStatus])

  useEffect(() => {
    loadWorkers()
  }, [loadWorkers])

  const handleSearch = () => {
    setCurrent(1)
    setSearchKeyword(keyword)
    setSearchStatus(statusFilter)
  }

  const handleReset = () => {
    setKeyword('')
    setStatusFilter('')
    setCurrent(1)
    setSearchKeyword('')
    setSearchStatus('')
  }

  const handleOpenCreate = () => {
    setForm({ workerNo: '', name: '', pin: '' })
    setFormOpen(true)
  }

  /** 建号：工号（租户内唯一）+ 姓名 + PIN。冲突由服务端 409 明确拒绝，页面**不**替它改写文案。 */
  const handleCreate = async () => {
    if (!form.workerNo.trim()) { toast.error('请输入工号'); return }
    if (!form.name.trim()) { toast.error('请输入工人姓名'); return }
    // 与后端同一条形态判据：工人端 PIN 输入框是数字键盘（inputmode=numeric）⇒ 含字母的 PIN 打不出来
    if (!/^\d{4,12}$/.test(form.pin.trim())) { toast.error('PIN 必须是 4~12 位数字'); return }

    setCreating(true)
    try {
      await workerApi.createWorker({
        workerNo: form.workerNo.trim(),
        name: form.name.trim(),
        pin: form.pin.trim(),
      })
      toast.success('工人档案已创建，请把工号与 PIN 告知本人')
      setFormOpen(false)
      setForm({ workerNo: '', name: '', pin: '' })
      loadWorkers()
    } catch (e) {
      // 失败**不关弹窗**：工号冲突是可修正的错误；文案由拦截器统一展示服务端原文（UI-024 去重口径）
      toastRequestError(e, '创建工人档案失败')
    } finally {
      setCreating(false)
    }
  }

  const handleToggleStatus = async (worker: WorkerProfile) => {
    if (togglingId !== null) return
    const newStatus: EmployeeStatus = worker.status === 'active' ? 'disabled' : 'active'
    setTogglingId(worker.id)
    try {
      await workerApi.setWorkerStatus(worker.id, newStatus)
      toast.success(newStatus === 'active' ? '已启用' : '已停用（该工人不能再登录工人端）')
      loadWorkers()
    } catch (e) {
      toastRequestError(e, '操作失败')
    } finally {
      setTogglingId(null)
    }
  }

  const columns: TableColumn<WorkerProfile>[] = [
    {
      key: 'workerNo',
      title: '工号',
      width: '140px',
      render: (record) => (
        <span className="font-medium text-neutral-900">{record.workerNo}</span>
      ),
    },
    { key: 'name', title: '姓名', width: '140px', dataIndex: 'name' },
    {
      key: 'status',
      title: '状态',
      width: '100px',
      render: (record) => (
        <Badge variant={record.status === 'active' ? 'success' : 'info'}>
          {record.status === 'active' ? '启用' : '停用'}
        </Badge>
      ),
    },
    {
      key: 'actions',
      title: '操作',
      width: '120px',
      render: (record) => (
        <button
          type="button"
          onClick={() => handleToggleStatus(record)}
          disabled={!canWrite || togglingId === record.id}
          className="text-primary-600 hover:text-primary-700 hover:underline transition-colors text-sm disabled:text-neutral-400 disabled:no-underline disabled:cursor-not-allowed"
        >
          {record.status === 'active' ? '停用' : '启用'}
        </button>
      ),
    },
  ]

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <p className="text-sm text-neutral-500">
          工人用工号 + PIN 登录工人端扫码报工，不进入管理后台、没有菜单权限；与员工账号分开管理，不会出现在员工列表里。
        </p>
        {canWrite ? (
          <Button onClick={handleOpenCreate}>
            <Plus className="w-4 h-4 mr-1.5" />
            新建工人档案
          </Button>
        ) : (
          <span className="text-xs text-neutral-400">只读</span>
        )}
      </div>

      <div className="bg-neutral-50 p-4 rounded-lg mb-4" data-testid="worker-search-area">
        <div className="flex flex-wrap items-end gap-4">
          <div className="min-w-[200px]">
            <Input
              label="工号/姓名"
              placeholder="输入工号或姓名搜索"
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
            />
          </div>
          <div className="min-w-[140px]">
            <Select
              label="状态"
              options={[
                { value: '', label: '全部状态' },
                { value: 'active', label: '启用' },
                { value: 'disabled', label: '停用' },
              ]}
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value as EmployeeStatus | '')}
            />
          </div>
          <div className="flex items-center gap-2 ml-auto">
            <Button variant="secondary" size="sm" onClick={handleReset}>
              重置
            </Button>
            <Button size="sm" onClick={handleSearch}>
              <Search className="w-4 h-4 mr-1.5" />
              查询
            </Button>
          </div>
        </div>
      </div>

      <div className="bg-white rounded-lg border border-neutral-200">
        <Table<WorkerProfile>
          columns={columns}
          dataSource={workers}
          loading={loading}
          rowKey="id"
          emptyText="还没有工人档案：点右上角「新建工人档案」录入工号与 PIN 即可"
        />
        <Pagination
          current={current}
          pageSize={pageSize}
          total={total}
          onChange={setCurrent}
          onPageSizeChange={(size) => { setPageSize(size); setCurrent(1) }}
        />
      </div>

      <Modal
        open={formOpen}
        onClose={() => setFormOpen(false)}
        title="新建工人档案"
        width={520}
        footer={
          <>
            <Button variant="secondary" onClick={() => setFormOpen(false)} disabled={creating}>
              取消
            </Button>
            <Button onClick={handleCreate} loading={creating}>
              创建
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <Input
            label="工号 *"
            placeholder="工人工牌上的工号，如 W-1002"
            value={form.workerNo}
            onChange={(e) => setForm({ ...form, workerNo: e.target.value })}
          />
          <Input
            label="姓名 *"
            placeholder="工人姓名，如 李四"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />
          <Input
            label="PIN *"
            type="password"
            inputMode="numeric"
            placeholder="4~12 位数字，工人登录工人端时输入"
            value={form.pin}
            onChange={(e) => setForm({ ...form, pin: e.target.value })}
          />
          <p className="text-xs text-neutral-400">
            工号在您的企业内不能重复；PIN 请当面告知工人（工人端用「工号 + PIN」登录扫工牌报工）。
            工人不会进入管理后台，也拿不到任何菜单权限。
          </p>
        </div>
      </Modal>
    </div>
  )
}
