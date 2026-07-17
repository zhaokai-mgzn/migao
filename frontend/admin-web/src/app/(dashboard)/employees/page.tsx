'use client'

import { useState, useEffect, useCallback, useMemo } from 'react'
import { Plus, Pencil, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { employeeApi, roleApi } from '@/lib/api'
import request from '@/lib/request'
import { Button, Input, Select, Modal, Table, Pagination, Badge } from '@/components/ui'
import type { TableColumn } from '@/components/ui'
import type { Employee, EmployeeStatus, Role } from '@/types'
import { TreeCheckbox, type TreeNode } from '@/components/ui/TreeCheckbox'
import DateTimeCell from '@/components/common/DateTimeCell'

// 预定义岗位列表（可下拉选择，也支持手输）
const PRESET_POSITIONS = ['管理员', '客服', '运营', '销售', '财务']


export default function EmployeesPage() {
  // 列表状态
  const [employees, setEmployees] = useState<Employee[]>([])
  const [loading, setLoading] = useState(false)
  const [total, setTotal] = useState(0)
  const [current, setCurrent] = useState(1)
  const [pageSize, setPageSize] = useState(10)
  const [keyword, setKeyword] = useState('')
  const [statusFilter, setStatusFilter] = useState<EmployeeStatus | ''>('')
  const [roleFilter, setRoleFilter] = useState<string>('')
  const [searchKeyword, setSearchKeyword] = useState('')
  const [searchStatus, setSearchStatus] = useState<EmployeeStatus | ''>('')
  const [searchRole, setSearchRole] = useState<string>('')

  // 菜单权限树
  const [menuTree, setMenuTree] = useState<TreeNode[]>([])

  // 角色列表（用于搜索筛选）
  const [allRoles, setAllRoles] = useState<Role[]>([])

  // 新增/编辑对话框
  const [formOpen, setFormOpen] = useState(false)
  const [editingEmployee, setEditingEmployee] = useState<Employee | null>(null)
  const [formLoading, setFormLoading] = useState(false)
  const [formData, setFormData] = useState({
    username: '',
    name: '',
    phone: '',
    position: '',
    permissions: [] as string[],
  })

  // 删除确认
  const [deleteTarget, setDeleteTarget] = useState<Employee | null>(null)
  const [deleting, setDeleting] = useState(false)

  // 内联状态切换 loading（按 ID 防止双击）
  const [togglingId, setTogglingId] = useState<number | null>(null)

  // 加载菜单权限树 + 角色列表
  useEffect(() => {
    request.get('/api/admin/menus').then((res: any) => {
      const data = res.data?.data || res.data || []
      setMenuTree(Array.isArray(data) ? data : [])
    }).catch(() => {
      toast.error('加载菜单权限失败，请刷新重试')
    })
    roleApi.getAllRoles().then((res) => {
      setAllRoles(res.data.data || [])
    }).catch(() => {})
  }, [])

  // 从 menuTree 中提取 code → 中文 label 的映射 + 叶子节点总数
  const { permissionLabelMap, totalLeafCount } = useMemo(() => {
    const map: Record<string, string> = {}
    let count = 0
    menuTree.forEach(p => {
      p.children?.forEach(c => { map[c.code] = c.label; count++ })
    })
    return { permissionLabelMap: map, totalLeafCount: count }
  }, [menuTree])

  // 加载员工列表
  const loadEmployees = useCallback(async () => {
    setLoading(true)
    try {
      const params: Record<string, unknown> = {
        page: current,
        size: pageSize,
        keyword: searchKeyword || undefined,
        status: searchStatus || undefined,
      }
      if (searchRole) params.role = searchRole

      const res = await employeeApi.getEmployees(params as Parameters<typeof employeeApi.getEmployees>[0])
      const data = res.data.data
      setEmployees(data?.items || [])
      setTotal(data?.total || 0)
    } catch (e) {
      toast.error('加载员工列表失败')
    } finally {
      setLoading(false)
    }
  }, [current, pageSize, searchKeyword, searchStatus, searchRole])

  useEffect(() => {
    loadEmployees()
  }, [loadEmployees])

  // 搜索
  const handleSearch = () => {
    setCurrent(1)
    setSearchKeyword(keyword)
    setSearchStatus(statusFilter)
    setSearchRole(roleFilter)
  }

  // 重置
  const handleReset = () => {
    setKeyword('')
    setStatusFilter('')
    setRoleFilter('')
    setCurrent(1)
    setSearchKeyword('')
    setSearchStatus('')
    setSearchRole('')
  }

  // 打开新增对话框
  const handleAdd = () => {
    setEditingEmployee(null)
    setFormData({ username: '', name: '', phone: '', position: '', permissions: [] })
    setFormOpen(true)
  }

  // 打开编辑对话框
  const handleEdit = (employee: Employee) => {
    setEditingEmployee(employee)
    setFormData({
      username: employee.username,
      name: employee.name,
      phone: employee.phone || '',
      position: employee.position || '',
      permissions: employee.permissions || [],
    })
    setFormOpen(true)
  }

  // 提交表单
  const handleSubmit = async () => {
    if (!formData.username.trim()) { toast.error('请输入用户名'); return }
    if (!formData.name.trim()) { toast.error('请输入姓名'); return }
    if (!formData.phone.trim()) { toast.error('请输入手机号'); return }
    if (!formData.position.trim()) { toast.error('请选择岗位'); return }

    setFormLoading(true)
    try {
      if (editingEmployee) {
        await employeeApi.updateEmployee(editingEmployee.id, {
          name: formData.name,
          phone: formData.phone || undefined,
          position: formData.position || undefined,
          permissions: formData.permissions,
        })
        toast.success('编辑成功')
      } else {
        await employeeApi.createEmployee({
          username: formData.username,
          name: formData.name,
          phone: formData.phone,
          position: formData.position,
          permissions: formData.permissions,
        })
        toast.success('创建成功')
      }
      setFormOpen(false)
      loadEmployees()
    } catch (e) {
      // Error handled by API layer
    } finally {
      setFormLoading(false)
    }
  }

  // 删除
  const handleDelete = async () => {
    if (!deleteTarget) return
    setDeleting(true)
    try {
      await employeeApi.deleteEmployee(deleteTarget.id)
      toast.success('删除成功')
      setDeleteTarget(null)
      loadEmployees()
    } catch (e) {
      // Error handled by API layer
    } finally {
      setDeleting(false)
    }
  }

  // 内联状态切换（直接调 API，无弹窗）
  const handleToggleStatus = async (employee: Employee) => {
    if (togglingId !== null) return // 防止双击
    const newStatus: EmployeeStatus = employee.status === 'active' ? 'disabled' : 'active'
    const actionLabel = newStatus === 'active' ? '启用' : '禁用'
    setTogglingId(employee.id)
    try {
      await employeeApi.toggleEmployeeStatus(employee.id, newStatus)
      toast.success(`已${actionLabel}`)
      loadEmployees()
    } catch (e) {
      toast.error(`操作失败`)
    } finally {
      setTogglingId(null)
    }
  }

  // 表格列定义
  const columns: TableColumn<Employee>[] = [
    {
      key: 'index',
      title: '序号',
      width: '70px',
      render: (_record, index) => (
        <span className="text-gray-500">{(current - 1) * pageSize + index + 1}</span>
      ),
    },
    {
      key: 'name',
      title: '姓名',
      width: '120px',
      render: (record) => (
        <button
          onClick={() => handleEdit(record)}
          className="text-primary-600 hover:text-primary-700 hover:underline text-sm font-medium"
        >
          {record.name}
        </button>
      ),
    },
    { key: 'phone', title: '手机号', dataIndex: 'phone', width: '140px' },
    {
      key: 'position',
      title: '岗位',
      width: '100px',
      render: (record) => (
        <span className="text-sm text-gray-700">{record.position || '-'}</span>
      ),
    },
    {
      key: 'permissions',
      title: '权限',
      width: '200px',
      render: (record) => {
        const codes: string[] = record.permissions || []
        if (codes.length === 0) return <span className="text-gray-400 text-sm">未分配</span>
        // 拥有全部权限时折叠为单个标签
        if (totalLeafCount > 0 && codes.length >= totalLeafCount) {
          return <Badge variant="success">全部权限</Badge>
        }
        const labels = codes.map(c => permissionLabelMap[c] || c).slice(0, 3)
        return (
          <div className="flex flex-wrap gap-1">
            {labels.map((l, i) => <Badge key={i} variant="info">{l}</Badge>)}
            {codes.length > 3 && <span className="text-xs text-gray-400">+{codes.length - 3}</span>}
          </div>
        )
      },
    },
    {
      key: 'status',
      title: '状态',
      width: '90px',
      render: (record) => {
        const isToggling = togglingId === record.id
        return (
        <button
          type="button"
          onClick={() => handleToggleStatus(record)}
          disabled={isToggling}
          className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-1 disabled:opacity-50 disabled:cursor-not-allowed ${
            record.status === 'active' ? 'bg-primary-600' : 'bg-gray-300'
          }`}
          title={isToggling ? '处理中...' : record.status === 'active' ? '点击禁用' : '点击启用'}
        >
          <span
            className={`inline-block h-4 w-4 rounded-full bg-white shadow-sm transition-transform ${
              record.status === 'active' ? 'translate-x-6' : 'translate-x-1'
            }`}
          />
        </button>
        )
      },
    },
    {
      key: 'createdAt',
      title: '创建时间',
      width: '180px',
      render: (record) => <DateTimeCell value={record.createdAt} />,
    },
    {
      key: 'actions',
      title: '操作',
      width: '140px',
      render: (record) => (
        <div className="flex items-center gap-3 whitespace-nowrap">
          <button
            onClick={(e) => { e.stopPropagation(); handleEdit(record) }}
            className="text-primary-600 hover:text-primary-700 hover:underline transition-colors text-sm flex items-center gap-1"
          >
            <Pencil className="w-3.5 h-3.5" />
            编辑
          </button>
          <button
            onClick={(e) => { e.stopPropagation(); setDeleteTarget(record) }}
            className="text-red-500 hover:text-red-600 hover:underline transition-colors text-sm flex items-center gap-1"
          >
            <Trash2 className="w-3.5 h-3.5" />
            删除
          </button>
        </div>
      ),
    },
  ]

  return (
    <div className="p-6">
      {/* 页面标题 */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">员工管理</h1>
          <p className="text-sm text-gray-500 mt-1">管理系统用户和员工账号</p>
        </div>
        <Button onClick={handleAdd}>
          <Plus className="w-4 h-4 mr-1.5" />
          添加员工
        </Button>
      </div>

      {/* 搜索筛选栏 */}
      <div className="bg-gray-50 p-4 rounded-lg mb-4" data-testid="search-area">
        <div className="flex flex-wrap items-end gap-4">
          <div className="min-w-[200px]">
            <Input
              label="姓名/手机号"
              placeholder="输入姓名或手机号搜索"
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
                { value: 'disabled', label: '禁用' },
              ]}
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value as EmployeeStatus | '')}
            />
          </div>
          <div className="min-w-[140px]">
            <Select
              label="角色"
              options={[
                { value: '', label: '全部角色' },
                ...allRoles.map(r => ({ value: r.code, label: r.name })),
              ]}
              value={roleFilter}
              onChange={(e) => setRoleFilter(e.target.value)}
            />
          </div>
          <div className="flex items-center gap-2 ml-auto">
            <Button variant="secondary" size="sm" onClick={handleReset}>
              重置
            </Button>
            <Button size="sm" onClick={handleSearch}>
              搜索
            </Button>
          </div>
        </div>
      </div>

      {/* 表格 */}
      <div className="bg-white rounded-lg border border-gray-200">
        <Table<Employee>
          columns={columns}
          dataSource={employees}
          loading={loading}
          rowKey="id"
        />
        <Pagination
          current={current}
          pageSize={pageSize}
          total={total}
          onChange={setCurrent}
          onPageSizeChange={(size) => { setPageSize(size); setCurrent(1) }}
        />
      </div>

      {/* 新增/编辑对话框 */}
      <Modal
        open={formOpen}
        onClose={() => setFormOpen(false)}
        title={editingEmployee ? '编辑员工' : '新增员工'}
        width={520}
        footer={
          <>
            <Button variant="secondary" onClick={() => setFormOpen(false)} disabled={formLoading}>
              取消
            </Button>
            <Button onClick={handleSubmit} loading={formLoading}>
              {editingEmployee ? '保存' : '创建'}
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <Input
            label="用户名"
            placeholder="请输入用户名"
            value={formData.username}
            onChange={(e) => setFormData(prev => ({ ...prev, username: e.target.value }))}
            disabled={!!editingEmployee}
          />
          <Input
            label="姓名 *"
            placeholder="请输入姓名"
            value={formData.name}
            onChange={(e) => setFormData(prev => ({ ...prev, name: e.target.value }))}
          />
          <Input
            label="手机号 *"
            placeholder="请输入手机号"
            value={formData.phone}
            onChange={(e) => setFormData(prev => ({ ...prev, phone: e.target.value }))}
          />
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">岗位 *</label>
            <input
              list="position-list"
              placeholder="选择或输入岗位，如：客服"
              value={formData.position}
              onChange={(e) => setFormData(prev => ({ ...prev, position: e.target.value }))}
              className="w-full h-10 px-3 rounded-lg border border-gray-300 bg-white text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15 placeholder:text-gray-400"
            />
            <datalist id="position-list">
              {PRESET_POSITIONS.map(p => <option key={p} value={p} />)}
            </datalist>
            <p className="text-xs text-gray-400 mt-1">选择或输入员工岗位（必填）</p>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">账号权限 *</label>
            {menuTree.length > 0 ? (
              <div className="max-h-[360px] overflow-y-auto border border-gray-200 rounded-lg p-3">
                <TreeCheckbox
                  tree={menuTree}
                  selected={formData.permissions}
                  onChange={(codes) => setFormData(prev => ({ ...prev, permissions: codes }))}
                />
              </div>
            ) : (
              <span className="text-sm text-gray-400">加载菜单权限中...</span>
            )}
          </div>
        </div>
      </Modal>

      {/* 删除确认对话框 */}
      <Modal
        open={!!deleteTarget}
        onClose={() => setDeleteTarget(null)}
        title="确认删除"
        footer={
          <>
            <Button variant="secondary" onClick={() => setDeleteTarget(null)} disabled={deleting}>
              取消
            </Button>
            <Button variant="danger" onClick={handleDelete} loading={deleting}>
              确认删除
            </Button>
          </>
        }
      >
        <p className="text-gray-600">
          确定要删除员工 <span className="font-medium text-gray-900">{deleteTarget?.name}</span> 吗？此操作不可撤销。
        </p>
      </Modal>
    </div>
  )
}
