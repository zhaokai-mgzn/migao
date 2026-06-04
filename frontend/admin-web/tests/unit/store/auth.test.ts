import { describe, it, expect, vi, beforeEach } from 'vitest'
import { act } from '@testing-library/react'

// Mock authApi
const mockLogin = vi.fn()
const mockLogout = vi.fn()
const mockRefreshToken = vi.fn()
const mockGetUserInfo = vi.fn()

vi.mock('@/lib/api', () => ({
  authApi: {
    login: (...args: any[]) => mockLogin(...args),
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
        refreshToken: null,
        isAuthenticated: false,
        isLoading: false,
        rememberMe: true,
        _hasHydrated: false,
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
      expect(state.refreshToken).toBeNull()
      expect(state.isAuthenticated).toBe(false)
      expect(state.isLoading).toBe(false)
      expect(state.rememberMe).toBe(true)
    })
  })

  describe('login', () => {
    it('should set tokens and isAuthenticated on successful login', async () => {
      mockLogin.mockResolvedValue({
        data: {
          data: {
            accessToken: 'access-123',
            refreshToken: 'refresh-456',
          },
        },
      })
      mockGetUserInfo.mockResolvedValue({
        data: {
          data: { id: 1, username: 'admin', role: 'admin' },
        },
      })

      await act(async () => {
        await useAuthStore.getState().login('admin', 'password')
      })

      const state = useAuthStore.getState()
      expect(state.accessToken).toBe('access-123')
      expect(state.refreshToken).toBe('refresh-456')
      expect(state.isAuthenticated).toBe(true)
      expect(state.isLoading).toBe(false)
    })

    it('should call authApi.login with correct params', async () => {
      mockLogin.mockResolvedValue({
        data: { data: { accessToken: 'at', refreshToken: 'rt' } },
      })
      mockGetUserInfo.mockResolvedValue({
        data: { data: { id: 1, username: 'admin' } },
      })

      await act(async () => {
        await useAuthStore.getState().login('admin', '123456')
      })

      expect(mockLogin).toHaveBeenCalledWith({
        username: 'admin',
        password: '123456',
        tenantId: 1,
      })
    })

    it('should set isLoading to true during login', async () => {
      let loadingDuringLogin = false
      mockLogin.mockImplementation(() => {
        loadingDuringLogin = useAuthStore.getState().isLoading
        return Promise.resolve({
          data: { data: { accessToken: 'at', refreshToken: 'rt' } },
        })
      })
      mockGetUserInfo.mockResolvedValue({
        data: { data: { id: 1 } },
      })

      await act(async () => {
        await useAuthStore.getState().login('admin', 'pass')
      })

      expect(loadingDuringLogin).toBe(true)
      expect(useAuthStore.getState().isLoading).toBe(false)
    })

    it('should reset isLoading on login failure', async () => {
      mockLogin.mockRejectedValue(new Error('Invalid credentials'))

      await act(async () => {
        try {
          await useAuthStore.getState().login('admin', 'wrong')
        } catch {
          // expected
        }
      })

      expect(useAuthStore.getState().isLoading).toBe(false)
    })

    it('should set rememberMe flag', async () => {
      mockLogin.mockResolvedValue({
        data: { data: { accessToken: 'at', refreshToken: 'rt' } },
      })
      mockGetUserInfo.mockResolvedValue({
        data: { data: { id: 1 } },
      })

      await act(async () => {
        await useAuthStore.getState().login('admin', 'pass', false)
      })

      expect(useAuthStore.getState().rememberMe).toBe(false)
    })

    it('should fetch user info after successful login', async () => {
      mockLogin.mockResolvedValue({
        data: { data: { accessToken: 'at', refreshToken: 'rt' } },
      })
      mockGetUserInfo.mockResolvedValue({
        data: { data: { id: 1, username: 'admin', role: 'admin' } },
      })

      await act(async () => {
        await useAuthStore.getState().login('admin', 'pass')
      })

      expect(mockGetUserInfo).toHaveBeenCalled()
      expect(useAuthStore.getState().user).toEqual({ id: 1, username: 'admin', role: 'admin' })
    })
  })

  describe('logout', () => {
    it('should clear auth state on logout', async () => {
      // Set up authenticated state
      act(() => {
        useAuthStore.setState({
          user: { id: 1, username: 'admin' } as any,
          accessToken: 'token',
          refreshToken: 'refresh',
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
      expect(state.refreshToken).toBeNull()
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
    it('should return new token on successful refresh', async () => {
      act(() => {
        useAuthStore.setState({
          refreshToken: 'old-refresh',
        })
      })

      mockRefreshToken.mockResolvedValue({
        data: {
          data: {
            accessToken: 'new-access-token',
            refreshToken: 'new-refresh-token',
          },
        },
      })

      let result: string | null = null
      await act(async () => {
        result = await useAuthStore.getState().refreshAccessToken()
      })

      expect(result).toBe('new-access-token')
      expect(useAuthStore.getState().accessToken).toBe('new-access-token')
      expect(useAuthStore.getState().refreshToken).toBe('new-refresh-token')
    })

    it('should return null and clear auth when no refresh token', async () => {
      act(() => {
        useAuthStore.setState({
          refreshToken: null,
        })
      })

      let result: string | null = 'something'
      await act(async () => {
        result = await useAuthStore.getState().refreshAccessToken()
      })

      expect(result).toBeNull()
    })

    it('should return null and clear auth on refresh failure', async () => {
      act(() => {
        useAuthStore.setState({
          refreshToken: 'old-refresh',
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

    it('should keep old refresh token if new one is not provided', async () => {
      act(() => {
        useAuthStore.setState({
          refreshToken: 'keep-this-refresh',
        })
      })

      mockRefreshToken.mockResolvedValue({
        data: {
          data: {
            accessToken: 'new-access',
            refreshToken: undefined,
          },
        },
      })

      await act(async () => {
        await useAuthStore.getState().refreshAccessToken()
      })

      expect(useAuthStore.getState().refreshToken).toBe('keep-this-refresh')
    })
  })

  describe('clearAuth', () => {
    it('should reset all auth fields', () => {
      act(() => {
        useAuthStore.setState({
          user: { id: 1, username: 'admin' } as any,
          accessToken: 'token',
          refreshToken: 'refresh',
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
      expect(state.refreshToken).toBeNull()
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

    it('should clear auth and throw on failure', async () => {
      act(() => {
        useAuthStore.setState({
          accessToken: 'token',
          isAuthenticated: true,
        })
      })

      mockGetUserInfo.mockRejectedValue(new Error('Unauthorized'))

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
  })
})
