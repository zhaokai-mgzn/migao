// case_ids: AU-001, AU-002, AU-006, API-010, UI-037
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { act } from '@testing-library/react'

// Mock authApi
const mockEmployeeLogin = vi.fn()
const mockSmsLogin = vi.fn()
const mockChangePassword = vi.fn()
const mockLogout = vi.fn()
const mockRefreshToken = vi.fn()
const mockGetUserInfo = vi.fn()

vi.mock('@/lib/api', () => ({
  authApi: {
    employeeLogin: (...args: any[]) => mockEmployeeLogin(...args),
    smsLogin: (...args: any[]) => mockSmsLogin(...args),
    changePassword: (...args: any[]) => mockChangePassword(...args),
    logout: (...args: any[]) => mockLogout(...args),
    refreshToken: (...args: any[]) => mockRefreshToken(...args),
    getUserInfo: (...args: any[]) => mockGetUserInfo(...args),
  },
}))

// Need to import after mocks
import { useAuthStore } from '@/store/auth'

describe('useAuthStore (Zustand auth store)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // Reset store state
    act(() => {
      useAuthStore.setState({
        user: null,
        accessToken: null,
        isAuthenticated: false,
        isLoading: false,
        rememberMe: true,
        _hasHydrated: true,
      })
    })
    // Mock document.cookie
    Object.defineProperty(document, 'cookie', {
      writable: true,
      value: '',
    })
  })

  describe('initial state', () => {
    it('should have correct initial state', () => {
      const state = useAuthStore.getState()
      expect(state.user).toBeNull()
      expect(state.accessToken).toBeNull()
      expect(state.isAuthenticated).toBe(false)
      expect(state.isLoading).toBe(false)
      expect(state.rememberMe).toBe(true)
    })

    it('legacy login() 必须不存在 —— 它会 Number(tenantCode) 解析并在非法时回落租户 1（#5485）', () => {
      // 这是本议题的核心回归面：那个方法正是「A 企业员工进到 B 企业」的形态，
      // 一旦有人把它加回来（哪怕「兼容签名」），这条用例必须红。
      expect((useAuthStore.getState() as any).login).toBeUndefined()
    })
  })

  // ==================== 员工登录（#5485 AU-001 / AU-002）====================

  describe('employeeLogin', () => {
    it('把标识原样交给 authApi.employeeLogin（**不**解析企业编码、**不**拼 tenantId）', async () => {
      mockEmployeeLogin.mockResolvedValue({
        data: { data: { accessToken: 'emp-token', user: { id: 'u1', mustChangePassword: false } } },
      })
      mockGetUserInfo.mockResolvedValue({
        data: { data: { user: { id: 'u1', username: 'zhangsan', mustChangePassword: false }, roles: ['operator'] } },
      })

      await act(async () => {
        await useAuthStore.getState().employeeLogin('zhangsan@tenant_7478359537', 'Init#12345')
      })

      // 逐字断言：带下划线的存量编码形态必须原样透传
      expect(mockEmployeeLogin).toHaveBeenCalledWith('zhangsan@tenant_7478359537', 'Init#12345')
      // 只有两个参数 —— 出现第三个（tenantId/tenantCode）就是前端自行解析租户的回归
      expect(mockEmployeeLogin.mock.calls[0]).toHaveLength(2)
    })

    it('登录成功：落会话（内存 token + 响应内 user）', async () => {
      mockEmployeeLogin.mockResolvedValue({
        data: {
          data: {
            accessToken: 'emp-access',
            user: { id: 'u1', nickname: '张三', tenantId: 20, tenantName: 'A 布艺', mustChangePassword: false },
          },
        },
      })
      // /api/auth/me 失败（网络/后端抖动）：登录本身不能因此失败
      mockGetUserInfo.mockRejectedValue(new Error('connect ECONNREFUSED 127.0.0.1:8080'))

      let outcome: { mustChangePassword: boolean } | undefined
      await act(async () => {
        outcome = await useAuthStore.getState().employeeLogin('zhangsan@migao', 'Init#12345')
      })

      const state = useAuthStore.getState()
      expect(state.accessToken).toBe('emp-access')
      expect(state.isAuthenticated).toBe(true)
      expect(state.isLoading).toBe(false)
      expect(outcome).toEqual({ mustChangePassword: false })
      // 登录响应里的身份信息仍在（/me 失败时右上角/侧边栏也有企业名可显示）
      expect((state.user as any).tenantName).toBe('A 布艺')
    })

    it('登录成功后 /api/auth/me 可用时：以 /me 的完整信息为准（含角色/权限/菜单）', async () => {
      mockEmployeeLogin.mockResolvedValue({
        data: { data: { accessToken: 'emp-access', user: { id: 'u1', mustChangePassword: false } } },
      })
      mockGetUserInfo.mockResolvedValue({
        data: {
          data: {
            user: { id: 'u1', username: 'zhangsan', nickname: '张三', mustChangePassword: false },
            roles: ['operator'],
            permissions: ['order:list'],
          },
        },
      })

      await act(async () => {
        await useAuthStore.getState().employeeLogin('zhangsan@migao', 'Init#12345')
      })

      const user = useAuthStore.getState().user as any
      expect(user.username).toBe('zhangsan')
      expect(user.roles).toEqual(['operator'])
      expect(user.permissions).toEqual(['order:list'])
    })

    it('mustChangePassword=true：返回值带标记（页面据此**直接**跳改密页）', async () => {
      mockEmployeeLogin.mockResolvedValue({
        data: { data: { accessToken: 'emp-access', user: { id: 'u1', mustChangePassword: true } } },
      })
      mockGetUserInfo.mockResolvedValue({
        data: { data: { user: { id: 'u1', username: 'zhangsan', mustChangePassword: true } } },
      })

      let outcome: { mustChangePassword: boolean } | undefined
      await act(async () => {
        outcome = await useAuthStore.getState().employeeLogin('zhangsan@migao', 'Init#12345')
      })

      expect(outcome).toEqual({ mustChangePassword: true })
      // 刷新页面后仍拿得到这个标记（/api/auth/me 也在白名单里下发它）
      expect((useAuthStore.getState().user as any).mustChangePassword).toBe(true)
    })

    it('登录失败：isLoading 复位、状态不置为已认证、异常继续抛出（给页面展示服务端原文）', async () => {
      const err = { response: { status: 401, data: { error: { message: '账号或密码错误' } } } }
      mockEmployeeLogin.mockRejectedValue(err)

      await act(async () => {
        await expect(
          useAuthStore.getState().employeeLogin('zhangsan@migao', 'wrong')
        ).rejects.toBe(err)
      })

      const state = useAuthStore.getState()
      expect(state.isLoading).toBe(false)
      expect(state.isAuthenticated).toBe(false)
      expect(state.accessToken).toBeNull()
    })

    it('isLoading 在请求期间为 true', async () => {
      let loadingDuringLogin = false
      mockEmployeeLogin.mockImplementation(() => {
        loadingDuringLogin = useAuthStore.getState().isLoading
        return Promise.resolve({
          data: { data: { accessToken: 'at', user: { id: 'u1' } } },
        })
      })
      mockGetUserInfo.mockResolvedValue({ data: { data: { user: { id: 'u1' } } } })

      await act(async () => {
        await useAuthStore.getState().employeeLogin('zhangsan@migao', 'pwd')
      })

      expect(loadingDuringLogin).toBe(true)
      expect(useAuthStore.getState().isLoading).toBe(false)
    })

    it('AU-002（前端半边）：A/B 两企业的同名员工，标识各自原样送达、互不改写', async () => {
      mockEmployeeLogin.mockResolvedValue({
        data: { data: { accessToken: 'token', user: { id: 'u1', mustChangePassword: false } } },
      })
      mockGetUserInfo.mockResolvedValue({
        data: { data: { user: { id: 'u1', username: 'zhangsan', mustChangePassword: false } } },
      })

      await act(async () => {
        await useAuthStore.getState().employeeLogin('zhangsan@tenant_7478359537', 'pwd')
      })
      await act(async () => {
        await useAuthStore.getState().employeeLogin('zhangsan@tenant_5321056468', 'pwd')
      })

      // 租户定位完全在服务端（前端只搬标识）—— 两次调用逐字不同、各自送到服务端
      expect(mockEmployeeLogin).toHaveBeenNthCalledWith(1, 'zhangsan@tenant_7478359537', 'pwd')
      expect(mockEmployeeLogin).toHaveBeenNthCalledWith(2, 'zhangsan@tenant_5321056468', 'pwd')
    })
  })

  // ==================== 自助改密（#5485 AU-006）====================

  describe('changePassword', () => {
    it('调用 /api/auth/password/change 并**直接采用响应里的新凭据**（不再手动刷一次 token）', async () => {
      act(() => {
        useAuthStore.setState({
          accessToken: 'old-must-change-token',
          isAuthenticated: true,
          user: { id: 'u1', username: 'zhangsan', mustChangePassword: true } as any,
        })
      })
      mockChangePassword.mockResolvedValue({
        data: {
          data: {
            accessToken: 'new-after-change',
            user: { id: 'u1', nickname: '张三', mustChangePassword: false },
          },
        },
      })
      mockGetUserInfo.mockResolvedValue({
        data: { data: { user: { id: 'u1', username: 'zhangsan', mustChangePassword: false }, roles: ['operator'] } },
      })

      await act(async () => {
        await useAuthStore.getState().changePassword('Init#12345', 'MyOwn#67890')
      })

      expect(mockChangePassword).toHaveBeenCalledWith({ oldPassword: 'Init#12345', newPassword: 'MyOwn#67890' })
      // 旧 token 仍带 claim ⇒ 必须换成响应里的新凭据
      expect(useAuthStore.getState().accessToken).toBe('new-after-change')
      // 绝不额外调 refresh（契约：改密响应直接带新凭据）
      expect(mockRefreshToken).not.toHaveBeenCalled()
      expect((useAuthStore.getState().user as any).mustChangePassword).toBe(false)
    })

    it('改密失败（旧密码错/弱密码 422）：isLoading 复位、不落新凭据、异常抛出给页面展示 message', async () => {
      act(() => {
        useAuthStore.setState({ accessToken: 'old-token', isAuthenticated: true })
      })
      const err = { response: { status: 422, data: { error: { code: 'VALIDATION_ERROR', message: '新密码强度不足' } } } }
      mockChangePassword.mockRejectedValue(err)

      await act(async () => {
        await expect(
          useAuthStore.getState().changePassword('wrong-old', '123')
        ).rejects.toBe(err)
      })

      expect(useAuthStore.getState().isLoading).toBe(false)
      expect(useAuthStore.getState().accessToken).toBe('old-token')
    })
  })

  describe('logout', () => {
    it('should clear auth state on logout', async () => {
      // Set up authenticated state
      act(() => {
        useAuthStore.setState({
          user: { id: 1, username: 'admin' } as any,
          accessToken: 'token',
          isAuthenticated: true,
        })
      })

      mockLogout.mockResolvedValue({})

      await act(async () => {
        await useAuthStore.getState().logout()
      })

      const state = useAuthStore.getState()
      expect(state.user).toBeNull()
      expect(state.accessToken).toBeNull()
      expect(state.isAuthenticated).toBe(false)
    })

    it('should clear auth even if logout API fails', async () => {
      act(() => {
        useAuthStore.setState({
          accessToken: 'token',
          isAuthenticated: true,
        })
      })

      mockLogout.mockRejectedValue(new Error('Network error'))

      await act(async () => {
        await useAuthStore.getState().logout()
      })

      expect(useAuthStore.getState().accessToken).toBeNull()
      expect(useAuthStore.getState().isAuthenticated).toBe(false)
    })
  })

  describe('refreshAccessToken', () => {
    it('should call refresh endpoint (cookie-based) and update access token', async () => {
      act(() => {
        useAuthStore.setState({ accessToken: 'old-access', isAuthenticated: true })
      })

      mockRefreshToken.mockResolvedValue({
        data: { data: { accessToken: 'new-access-token' } },
      })

      let result: string | null = null
      await act(async () => {
        result = await useAuthStore.getState().refreshAccessToken()
      })

      expect(mockRefreshToken).toHaveBeenCalledWith()  // 审计 07 P1-5: 无参（cookie 承载）
      expect(result).toBe('new-access-token')
      expect(useAuthStore.getState().accessToken).toBe('new-access-token')
    })

    it('should return null and clear auth on refresh failure', async () => {
      act(() => {
        useAuthStore.setState({
          accessToken: 'old-access',
          isAuthenticated: true,
        })
      })

      mockRefreshToken.mockRejectedValue(new Error('Refresh failed'))

      let result: string | null = 'something'
      await act(async () => {
        result = await useAuthStore.getState().refreshAccessToken()
      })

      expect(result).toBeNull()
      expect(useAuthStore.getState().accessToken).toBeNull()
      expect(useAuthStore.getState().isAuthenticated).toBe(false)
    })
  })

  describe('clearAuth', () => {
    it('should reset all auth fields', () => {
      act(() => {
        useAuthStore.setState({
          user: { id: 1, username: 'admin' } as any,
          accessToken: 'token',
          isAuthenticated: true,
          isLoading: true,
        })
      })

      act(() => {
        useAuthStore.getState().clearAuth()
      })

      const state = useAuthStore.getState()
      expect(state.user).toBeNull()
      expect(state.accessToken).toBeNull()
      expect(state.isAuthenticated).toBe(false)
      expect(state.isLoading).toBe(false)
    })
  })

  describe('setHasHydrated', () => {
    it('should set _hasHydrated flag', () => {
      act(() => {
        useAuthStore.getState().setHasHydrated(true)
      })

      expect(useAuthStore.getState()._hasHydrated).toBe(true)
    })
  })

  describe('fetchUserInfo', () => {
    it('应解包 /api/auth/me 的 { user, roles, permissions, menus } 包装结构（#3099）', async () => {
      mockGetUserInfo.mockResolvedValue({
        data: {
          data: {
            user: {
              id: 'u1',
              username: '13800138000',
              nickname: '张老板',
              position: '运营',
              avatar: 'https://oss.example.com/avatar.png',
              tenantId: 1,
              tenantName: '米高布艺',
              tenantLogo: 'https://oss.example.com/logo.png',
              status: 'active',
            },
            roles: ['admin'],
            permissions: ['*'],
            menus: [{ key: 'dashboard', name: '经营看板', path: '/dashboard' }],
          },
        },
      })

      await act(async () => {
        await useAuthStore.getState().fetchUserInfo()
      })

      const user = useAuthStore.getState().user as any
      // 顶层可读：昵称/用户名(手机号)/岗位/企业名/Logo（解包后，右上角与侧边栏才能正常展示）
      expect(user.nickname).toBe('张老板')
      expect(user.username).toBe('13800138000')
      expect(user.position).toBe('运营')
      expect(user.tenantName).toBe('米高布艺')
      expect(user.tenantLogo).toBe('https://oss.example.com/logo.png')
      // 角色/权限/菜单保留（侧边栏过滤等依赖）
      expect(user.roles).toEqual(['admin'])
      expect(user.permissions).toEqual(['*'])
      expect(user.menus).toEqual([{ key: 'dashboard', name: '经营看板', path: '/dashboard' }])
    })

    it('员工的 /api/auth/me：username 是账号用户名，且带 mustChangePassword（页面刷新后仍能判强制改密）', async () => {
      mockGetUserInfo.mockResolvedValue({
        data: {
          data: {
            user: {
              id: 'u2',
              username: 'zhangsan',
              nickname: '张三',
              employeeUsername: 'zhangsan',
              mustChangePassword: true,
              identityType: 'employee',
              tenantId: 20,
            },
            roles: ['operator'],
          },
        },
      })

      await act(async () => {
        await useAuthStore.getState().fetchUserInfo()
      })

      const user = useAuthStore.getState().user as any
      expect(user.username).toBe('zhangsan')
      expect(user.mustChangePassword).toBe(true)
      expect(user.identityType).toBe('employee')
    })

    it('should set user and isAuthenticated on success', async () => {
      mockGetUserInfo.mockResolvedValue({
        data: {
          data: { id: 1, username: 'admin', email: 'admin@test.com' },
        },
      })

      await act(async () => {
        await useAuthStore.getState().fetchUserInfo()
      })

      expect(useAuthStore.getState().user).toEqual({ id: 1, username: 'admin', email: 'admin@test.com' })
      expect(useAuthStore.getState().isAuthenticated).toBe(true)
    })

    it('should clear auth and throw on 401', async () => {
      act(() => {
        useAuthStore.setState({
          accessToken: 'token',
          isAuthenticated: true,
        })
      })

      // Simulate axios 401 error (has response.status)
      const authError = new Error('Unauthorized') as any
      authError.response = { status: 401 }
      mockGetUserInfo.mockRejectedValue(authError)

      await act(async () => {
        try {
          await useAuthStore.getState().fetchUserInfo()
        } catch {
          // expected
        }
      })

      expect(useAuthStore.getState().accessToken).toBeNull()
      expect(useAuthStore.getState().isAuthenticated).toBe(false)
    })

    it('should clear auth and throw on 403', async () => {
      act(() => {
        useAuthStore.setState({
          accessToken: 'token',
          isAuthenticated: true,
        })
      })

      const authError = new Error('Forbidden') as any
      authError.response = { status: 403 }
      mockGetUserInfo.mockRejectedValue(authError)

      await act(async () => {
        try {
          await useAuthStore.getState().fetchUserInfo()
        } catch {
          // expected
        }
      })

      expect(useAuthStore.getState().accessToken).toBeNull()
      expect(useAuthStore.getState().isAuthenticated).toBe(false)
    })

    it('should NOT clear auth on network error (ECONNREFUSED)', async () => {
      act(() => {
        useAuthStore.setState({
          user: { id: '1', username: 'admin' } as any,
          accessToken: 'token',
          isAuthenticated: true,
        })
      })

      // Network error: no response property (e.g. ECONNREFUSED, ETIMEDOUT)
      mockGetUserInfo.mockRejectedValue(new Error('connect ECONNREFUSED 127.0.0.1:8080'))

      await act(async () => {
        try {
          await useAuthStore.getState().fetchUserInfo()
        } catch {
          // expected
        }
      })

      // Auth state must be preserved on network error
      expect(useAuthStore.getState().accessToken).toBe('token')
      expect(useAuthStore.getState().isAuthenticated).toBe(true)
      expect(useAuthStore.getState().user).toBeDefined()
    })
  })

  describe('smsLogin', () => {
    it('should set tokens and isAuthenticated on successful SMS login', async () => {
      const phone = '13800138000'
      const code = '123456'
      mockSmsLogin.mockResolvedValue({
        data: {
          data: {
            accessToken: 'sms-access-token',
            refreshToken: 'sms-refresh-token',
            user: { id: '1', nickname: '管理员', mustChangePassword: false },
          },
        },
      })
      mockGetUserInfo.mockResolvedValue({
        data: {
          data: { id: '1', username: 'admin', name: '管理员', roles: ['admin'] },
        },
      })

      let outcome: { mustChangePassword: boolean } | undefined
      await act(async () => {
        outcome = await useAuthStore.getState().smsLogin(phone, code)
      })

      expect(useAuthStore.getState().accessToken).toBe('sms-access-token')
      expect(useAuthStore.getState().isAuthenticated).toBe(true)
      expect(mockSmsLogin).toHaveBeenCalledWith(phone, code)
      expect(outcome).toEqual({ mustChangePassword: false })
    })

    it('should set isLoading=true during smsLogin', async () => {
      const deferred = { resolve: null as any }
      const p = new Promise((r) => { deferred.resolve = r })
      mockSmsLogin.mockReturnValue(p)

      const promise = act(async () => {
        useAuthStore.getState().smsLogin('13800138000', '123456').catch(() => {})
      })

      expect(useAuthStore.getState().isLoading).toBe(true)
      deferred.resolve({ data: { data: { accessToken: 't', refreshToken: 'r' } } })
      await promise
    })

    it('should throw on failed SMS login and not set auth', async () => {
      mockSmsLogin.mockRejectedValue(new Error('验证码错误'))

      await expect(
        act(async () => {
          await useAuthStore.getState().smsLogin('13800138000', '000000')
        })
      ).rejects.toThrow()

      expect(useAuthStore.getState().isAuthenticated).toBe(false)
      expect(useAuthStore.getState().accessToken).toBeNull()
    })
  })

  describe('cross-tenant re-login', () => {
    it('should fully replace state when logging in as different tenant', async () => {
      // Initial login as tenant A
      act(() => {
        useAuthStore.setState({
          user: { id: '1', username: 'adminA', tenantId: 'tenant_A' } as any,
          accessToken: 'tenant-A-token',
          isAuthenticated: true,
        })
      })

      // Clear auth (simulates logout)
      act(() => {
        useAuthStore.getState().clearAuth()
      })

      // Login as tenant B
      mockSmsLogin.mockResolvedValue({
        data: {
          data: {
            accessToken: 'tenant-B-token',
            refreshToken: 'tenant-B-refresh',
          },
        },
      })
      mockGetUserInfo.mockResolvedValue({
        data: {
          data: { id: '2', username: 'adminB', roles: ['admin'] },
        },
      })

      await act(async () => {
        await useAuthStore.getState().smsLogin('13900000001', '123456')
      })

      const state = useAuthStore.getState()
      expect(state.accessToken).toBe('tenant-B-token')
      expect(state.accessToken).not.toBe('tenant-A-token')
    })
  })
})