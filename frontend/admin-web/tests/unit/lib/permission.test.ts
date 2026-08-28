// case_ids: HR-001, DF-007
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook } from '@testing-library/react'
import { usePermission } from '@/lib/permission'

// Mock useAuthStore — 支持 selector 调用
const mockUseAuthStore = vi.fn()
vi.mock('@/store/auth', () => ({
  useAuthStore: (selector: any) => (selector ? selector(mockUseAuthStore()) : mockUseAuthStore()),
}))

function mockUser(user: any) {
  mockUseAuthStore.mockReturnValue({ user })
}

/**
 * usePermission 权限判断 Hook 单元测试
 * 口径与后端一致：admin/super_admin/* → 全权限；其余按 permissions 权限码。
 */
describe('usePermission', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('admin 角色拥有全部权限（无需显式 permissions）', () => {
    mockUser({ id: '1', roles: ['admin'], permissions: [] })
    const { result } = renderHook(() => usePermission())
    expect(result.current.has('employee:create')).toBe(true)
    expect(result.current.has('order:list')).toBe(true)
    expect(result.current.isAdmin).toBe(true)
  })

  it('permissions 含 * 视为全部权限', () => {
    mockUser({ id: '1', roles: [], permissions: ['*'] })
    const { result } = renderHook(() => usePermission())
    expect(result.current.has('employee:create')).toBe(true)
  })

  it('普通员工按权限码判断', () => {
    mockUser({ id: '2', roles: ['operator'], permissions: ['employee:list', 'dashboard:view'] })
    const { result } = renderHook(() => usePermission())
    expect(result.current.has('employee:list')).toBe(true)
    expect(result.current.has('employee:create')).toBe(false)
    expect(result.current.has('order:list')).toBe(false)
    expect(result.current.isAdmin).toBe(false)
  })

  it('未登录/无权限码时全部拒绝', () => {
    mockUser(null)
    const { result } = renderHook(() => usePermission())
    expect(result.current.has('dashboard:view')).toBe(false)
    expect(result.current.has(undefined)).toBe(true) // 无权限码 = 所有人可见
  })
})
