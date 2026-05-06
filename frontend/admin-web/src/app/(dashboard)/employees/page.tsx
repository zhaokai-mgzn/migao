'use client'

import { useState, useEffect, useCallback } from 'react'
import { Plus, Pencil, RotateCcw, Trash2, ShieldOff, ShieldCheck, KeyRound } from 'lucide-react'
import { toast } from 'sonner'
import { employeeApi, roleApi } from '@/lib/api'
import { Button, Input, Select, Modal, Table, Pagination, Badge } from '@/components/ui'
import type { TableColumn } from '@/components/ui'
import type { Employee, EmployeeStatus, Role } from '@/types'
import { EmployeeStatusLabels } from '@/types'
import dayjs from 'dayjs'

export default function EmployeesPage() {
  // 列表状态
  const [employees, setEmployees] = useState<Employee[]>([])
  const [loading, setLoading] = useState(false)
  const [total, setTotal] = useState(0)
  const [current, setCurrent] = useState(1)
  const [pageSize, setPageSize] = useState(10)
  const [keyword, setKeyword] = useState('')
  const [statusFilter, setStatusFilter] = useState<EmployeeStatus | ''>('')
  const [searchKeyword, setSearchKeyword] = useState('')
  const [searchStatus, setSearchStatus] = useState<EmployeeStatus | ''>('')

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
    roleIds: [] as number[],
  })

  // 删除确认
  const [deleteTarget, setDeleteTarget] = useState<Employee | null>(null)
  const [deleting, setDeleting] = useState(false)

  // 重置密码对话框
  const [resetPwdTarget, setResetPwdTarget] = useState<Employee | null>(null)
  const [newPassword, setNewPassword] = useState('')
  const [resetPwdLoading, setResetPwdLoading] = useState(false)

  // 禁用/启用确认
  const [toggleTarget, setToggleTarget] = useState<Employee | null>(null)
  const [toggling, setToggling] = useState(false)

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
      const res = await employeeApi.getEmployees({
        page: current,
        size: pageSize,
        keyword: searchKeyword || undefined,
        status: searchStatus || undefined,
      })
      const data = res.data.data
      setEmployees(data?.items || [])
      setTotal(data?.total || 0)
    } catch {
      toast.error('加载员工列表失败')
    } finally {
      setLoading(false)
    }
  }, [current, pageSize, searchKeyword, searchStatus])

  useEffect(() => {
    loadEmployees()
  }, [loadEmployees])

  // 搜索
  const handleSearch = () => {
    setCurrent(1)
    setSearchKeyword(keyword)
    setSearchStatus(statusFilter)
  }

  // 重置
  const handleReset = () => {
    setKeyword('')
    setStatusFilter('')
    setCurrent(1)
    setSearchKeyword('')
    setSearchStatus('')
  }

  // 打开新增对话框
  const handleAdd = () => {
    setEditingEmployee(null)
    setFormData({ username: '', password: '', name: '', phone: '', email: '', roleIds: [] })
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

  // 重置密码
  const handleResetPassword = async () => {
    if (!resetPwdTarget) return
    if (!newPassword.trim()) { toast.error('请输入新密码'); return }
    setResetPwdLoading(true)
    try {
      await employeeApi.resetPassword(resetPwdTarget.id, { newPassword })
      toast.success('密码已重置')
      setResetPwdTarget(null)
      setNewPassword('')
    } catch {
      // Error handled by API layer
    } finally {
      setResetPwdLoading(false)
    }
  }

  // 启用/禁用
  const handleToggleStatus = async () => {
    if (!toggleTarget) return
    setToggling(true)
    const newStatus: EmployeeStatus = toggleTarget.status === 'active' ? 'disabled' : 'active'
    try {
      await employeeApi.toggleEmployeeStatus(toggleTarget.id, newStatus)
      toast.success(newStatus === 'active' ? '已启用' : '已禁用')
      setToggleTarget(null)
      loadEmployees()
    } catch {
      // Error handled by API layer
    } finally {
      setToggling(false)
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
    { key: 'username', title: '用户名', dataIndex: 'username', width: '120px' },
    { key: 'name', title: '姓名', dataIndex: 'name', width: '120px' },
    { key: 'phone', title: '手机号', dataIndex: 'phone', width: '140px' },
    {
      key: 'roles',
      title: '角色',
      width: '200px',
      render: (record) => (
        <div className="flex flex-wrap gap-1">
          {record.roles?.length > 0
            ? record.roles.map(r => (
              <Badge key={r.id} variant="info">{r.name}</Badge>
            ))
            : <span className="text-gray-400">未分配</span>
          }
        </div>
      ),
    },
    {
      key: 'status',
      title: '状态',
      width: '100px',
      render: (record) => (
        <Badge variant={record.status === 'active' ? 'success' : 'error'}>
          {EmployeeStatusLabels[record.status]}
        </Badge>
      ),
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
      width: '240px',
      render: (record) => (
        <div className="flex items-center gap-2">
          <button
            onClick={(e) => { e.stopPropagation(); handleEdit(record) }}
            className="text-primary-600 hover:text-primary-700 text-sm flex items-center gap-1"
          >
            <Pencil className="w-3.5 h-3.5" />
            编辑
          </button>
          <button
            onClick={(e) => { e.stopPropagation(); setResetPwdTarget(record); setNewPassword('') }}
            className="text-amber-600 hover:text-amber-700 text-sm flex items-center gap-1"
          >
            <KeyRound className="w-3.5 h-3.5" />
            重置密码
          </button>
          <button
            onClick={(e) => { e.stopPropagation(); setToggleTarget(record) }}
            className={`text-sm flex items-center gap-1 ${record.status === 'active' ? 'text-orange-600 hover:text-orange-700' : 'text-green-600 hover:text-green-700'}`}
          >
            {record.status === 'active' ? <ShieldOff className="w-3.5 h-3.5" /> : <ShieldCheck className="w-3.5 h-3.5" />}
            {record.status === 'active' ? '禁用' : '启用'}
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
          新增员工
        </Button>
      </div>

      {/* 搜索筛选栏 */}
      <div className="bg-gray-50 p-4 rounded-lg mb-4">
        <div className="flex flex-wrap items-end gap-4">
          <div className="min-w-[200px]">
            <Input
              label="关键词搜索"
              placeholder="姓名、用户名"
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
            <label className="block text-sm font-medium text-gray-700 mb-2">角色分配</label>
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
                <span className="text-sm text-gray-400">暂无可选角色</span>
              )}
            </div>
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

      {/* 重置密码对话框 */}
      <Modal
        open={!!resetPwdTarget}
        onClose={() => setResetPwdTarget(null)}
        title="重置密码"
        footer={
          <>
            <Button variant="secondary" onClick={() => setResetPwdTarget(null)} disabled={resetPwdLoading}>
              取消
            </Button>
            <Button onClick={handleResetPassword} loading={resetPwdLoading}>
              确认重置
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <p className="text-gray-600">
            为 <span className="font-medium text-gray-900">{resetPwdTarget?.name}</span> 重置密码
          </p>
          <Input
            label="新密码"
            type="password"
            placeholder="请输入新密码"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
          />
        </div>
      </Modal>

      {/* 启用/禁用确认对话框 */}
      <Modal
        open={!!toggleTarget}
        onClose={() => setToggleTarget(null)}
        title={toggleTarget?.status === 'active' ? '确认禁用' : '确认启用'}
        footer={
          <>
            <Button variant="secondary" onClick={() => setToggleTarget(null)} disabled={toggling}>
              取消
            </Button>
            <Button
              variant={toggleTarget?.status === 'active' ? 'danger' : 'primary'}
              onClick={handleToggleStatus}
              loading={toggling}
            >
              {toggleTarget?.status === 'active' ? '确认禁用' : '确认启用'}
            </Button>
          </>
        }
      >
        <p className="text-gray-600">
          确定要{toggleTarget?.status === 'active' ? '禁用' : '启用'}员工
          <span className="font-medium text-gray-900"> {toggleTarget?.name} </span>吗？
          {toggleTarget?.status === 'active' && '禁用后该员工将无法登录系统。'}
        </p>
      </Modal>
    </div>
  )
}
