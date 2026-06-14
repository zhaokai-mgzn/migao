'use client'

import { useState, useEffect, useCallback } from 'react'
import { Plus, Pencil, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { employeeApi, roleApi } from '@/lib/api'
import { Button, Input, Select, Modal, Table, Pagination, Badge } from '@/components/ui'
import type { TableColumn } from '@/components/ui'
import type { Employee, EmployeeStatus, Role } from '@/types'
import { EmployeeStatusLabels } from '@/types'
import dayjs from 'dayjs'

// 预定义岗位列表（可下拉选择，也支持手输）
const PRESET_POSITIONS = ['管理员', '客服', '运营', '销售', '财务']

// 角色颜色映射（按 code 区分颜色）
const ROLE_COLOR_MAP: Record<string, 'info' | 'success' | 'warning' | 'error'> = {
  admin: 'error',
  agent: 'info',
  operator: 'warning',
}

function getRoleBadgeVariant(code: string): 'info' | 'success' | 'warning' | 'error' {
  return ROLE_COLOR_MAP[code] || 'info'
}

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

  // 角色选项
  const [allRoles, setAllRoles] = useState<Role[]>([])

  // 新增/编辑对话框
  const [formOpen, setFormOpen] = useState(false)
  const [editingEmployee, setEditingEmployee] = useState<Employee | null>(null)
  const [formLoading, setFormLoading] = useState(false)
  const [formData, setFormData] = useState({
    username: '',
    password: '',
    name: '',
    phone: '',
    email: '',
    position: '',
    roleIds: [] as number[],
  })

  // 删除确认
  const [deleteTarget, setDeleteTarget] = useState<Employee | null>(null)
  const [deleting, setDeleting] = useState(false)

  // 内联状态切换 loading（按 ID 防止双击）
  const [togglingId, setTogglingId] = useState<number | null>(null)

  // 加载角色列表
  useEffect(() => {
    roleApi.getAllRoles().then((res) => {
      setAllRoles(res.data.data || [])
    }).catch(() => {})
  }, [])

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
    } catch {
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
    setFormData({ username: '', password: '', name: '', phone: '', email: '', position: '', roleIds: [] })
    setFormOpen(true)
  }

  // 打开编辑对话框
  const handleEdit = (employee: Employee) => {
    setEditingEmployee(employee)
    setFormData({
      username: employee.username,
      password: '',
      name: employee.name,
      phone: employee.phone || '',
      email: employee.email || '',
      position: employee.position || '',
      roleIds: employee.roles?.map(r => r.id) || [],
    })
    setFormOpen(true)
  }

  // 提交表单
  const handleSubmit = async () => {
    if (!formData.username.trim()) { toast.error('请输入用户名'); return }
    if (!formData.name.trim()) { toast.error('请输入姓名'); return }
    if (!editingEmployee && !formData.password.trim()) { toast.error('请输入密码'); return }

    setFormLoading(true)
    try {
      if (editingEmployee) {
        await employeeApi.updateEmployee(editingEmployee.id, {
          name: formData.name,
          phone: formData.phone || undefined,
          email: formData.email || undefined,
          password: formData.password || undefined,
          position: formData.position || undefined,
          roleIds: formData.roleIds,
        })
        toast.success('编辑成功')
      } else {
        await employeeApi.createEmployee({
          username: formData.username,
          password: formData.password,
          name: formData.name,
          phone: formData.phone || undefined,
          email: formData.email || undefined,
          position: formData.position || undefined,
          roleIds: formData.roleIds,
        })
        toast.success('创建成功')
      }
      setFormOpen(false)
      loadEmployees()
    } catch {
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
    } catch {
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
    } catch {
      toast.error(`操作失败`)
    } finally {
      setTogglingId(null)
    }
  }

  // 角色多选切换
  const toggleRole = (roleId: number) => {
    setFormData(prev => ({
      ...prev,
      roleIds: prev.roleIds.includes(roleId)
        ? prev.roleIds.filter(id => id !== roleId)
        : [...prev.roleIds, roleId],
    }))
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
      key: 'roles',
      title: '权限',
      width: '200px',
      render: (record) => (
        <div className="flex flex-wrap gap-1">
          {record.roles?.length > 0
            ? record.roles.map(r => (
              <Badge key={r.id} variant={getRoleBadgeVariant(r.code)}>{r.name}</Badge>
            ))
            : <span className="text-gray-400 text-sm">未分配</span>
          }
        </div>
      ),
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
      render: (record) => record.createdAt ? dayjs(record.createdAt).format('YYYY-MM-DD HH:mm') : '-',
    },
    {
      key: 'actions',
      title: '操作',
      width: '140px',
      render: (record) => (
        <div className="flex items-center gap-3">
          <button
            onClick={(e) => { e.stopPropagation(); handleEdit(record) }}
            className="text-primary-600 hover:text-primary-700 text-sm flex items-center gap-1"
          >
            <Pencil className="w-3.5 h-3.5" />
            编辑
          </button>
          <button
            onClick={(e) => { e.stopPropagation(); setDeleteTarget(record) }}
            className="text-red-600 hover:text-red-700 text-sm flex items-center gap-1"
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
      <div className="bg-gray-50 p-4 rounded-lg mb-4">
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
              label="岗位"
              options={[
                { value: '', label: '全部岗位' },
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
            label={editingEmployee ? '密码（留空则不修改）' : '密码'}
            placeholder={editingEmployee ? '留空则不修改密码' : '请输入密码'}
            type="password"
            value={formData.password}
            onChange={(e) => setFormData(prev => ({ ...prev, password: e.target.value }))}
          />
          <Input
            label="姓名"
            placeholder="请输入姓名"
            value={formData.name}
            onChange={(e) => setFormData(prev => ({ ...prev, name: e.target.value }))}
          />
          <Input
            label="手机号（选填）"
            placeholder="请输入手机号"
            value={formData.phone}
            onChange={(e) => setFormData(prev => ({ ...prev, phone: e.target.value }))}
          />
          <Input
            label="邮箱（选填）"
            placeholder="请输入邮箱"
            value={formData.email}
            onChange={(e) => setFormData(prev => ({ ...prev, email: e.target.value }))}
          />
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">岗位（选填，纯展示）</label>
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
            <p className="text-xs text-gray-400 mt-1">下拉选择或手动输入岗位名称</p>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">账号权限</label>
            <div className="flex flex-wrap gap-2">
              {allRoles.length > 0 ? allRoles.map(role => (
                <button
                  key={role.id}
                  type="button"
                  onClick={() => toggleRole(role.id)}
                  className={`px-3 py-1.5 rounded-md border text-sm font-medium transition-all ${
                    formData.roleIds.includes(role.id)
                      ? 'border-primary-500 bg-primary-50 text-primary-700'
                      : 'border-gray-200 hover:border-gray-300 text-gray-600'
                  }`}
                >
                  {role.name}
                </button>
              )) : (
                <span className="text-sm text-gray-400">暂无可选权限</span>
              )}
            </div>
            <p className="text-xs text-gray-400 mt-1">勾选该员工的菜单访问权限</p>
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
