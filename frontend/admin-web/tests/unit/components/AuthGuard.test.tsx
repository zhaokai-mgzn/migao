// case_ids: AU-006
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'

const mockReplace = vi.fn()
let mockPathname = '/dashboard'
vi.mock('next/navigation', () => ({
  usePathname: () => mockPathname,
  useRouter: () => ({ replace: mockReplace, push: vi.fn() }),
}))

// store 的 selector 调用形态：useAuthStore(s => s.xxx)
let mockState: { isAuthenticated: boolean; _hasHydrated: boolean; user: any } = {
  isAuthenticated: false,
  _hasHydrated: true,
  user: null,
}
vi.mock('@/store/auth', () => ({
  useAuthStore: (selector: any) => selector(mockState),
}))

import { AuthGuard } from '@/components/auth-guard'

/**
 * 路由层的强制改密兜底（issue #5485）。
 *
 * 权威拦截在服务端（403 PASSWORD_CHANGE_REQUIRED，axios 层已全局处理过），
 * 这里只保证用户不会先看到一屏业务页报错。
 */
describe('AuthGuard — 首登强制改密的路由兜底（issue #5485）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockPathname = '/dashboard'
    mockState = { isAuthenticated: true, _hasHydrated: true, user: { mustChangePassword: true } }
  })

  it('未改密的会话访问业务页 → 改到改密页', () => {
    render(<AuthGuard><div>业务内容</div></AuthGuard>)
    expect(mockReplace).toHaveBeenCalledWith('/change-password')
  })

  it('已在改密页 → 不再跳转（否则自己跳自己 = 死循环）', () => {
    mockPathname = '/change-password'
    render(<AuthGuard><div>改密表单</div></AuthGuard>)
    expect(mockReplace).not.toHaveBeenCalled()
    expect(screen.getByText('改密表单')).toBeInTheDocument()
  })

  it('改密完成（标记 false）→ 正常渲染业务页', () => {
    mockState = { isAuthenticated: true, _hasHydrated: true, user: { mustChangePassword: false } }
    render(<AuthGuard><div>业务内容</div></AuthGuard>)
    expect(screen.getByText('业务内容')).toBeInTheDocument()
    expect(mockReplace).not.toHaveBeenCalled()
  })

  it('未登录访问改密页 → 先去登录页（带 callbackUrl）', () => {
    mockPathname = '/change-password'
    mockState = { isAuthenticated: false, _hasHydrated: true, user: null }
    render(<AuthGuard><div>改密表单</div></AuthGuard>)
    expect(mockReplace).toHaveBeenCalledWith('/login?callbackUrl=%2Fchange-password')
  })

  it('未登录访问业务页 → 登录页（既有行为不回归）', () => {
    mockPathname = '/orders'
    mockState = { isAuthenticated: false, _hasHydrated: true, user: null }
    render(<AuthGuard><div>订单</div></AuthGuard>)
    expect(mockReplace).toHaveBeenCalledWith('/login?callbackUrl=%2Forders')
  })
})