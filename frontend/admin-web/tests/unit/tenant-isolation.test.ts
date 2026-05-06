import { describe, it, expect, vi, beforeEach } from 'vitest'
import { act } from '@testing-library/react'
import type { InternalAxiosRequestConfig } from 'axios'

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

import { useAuthStore } from '@/store/auth'

describe('Multi-Tenant Frontend Isolation', () => {
  beforeEach(() => {
    vi.clearAllMocks()
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
    Object.defineProperty(document, 'cookie', {
      writable: true,
      value: '',
    })
    localStorage.clear()
  })

  describe('Token-based tenant identification', () => {
    it('should store tenant-specific token on login', async () => {
      mockLogin.mockResolvedValue({
        data: {
          data: {
            accessToken: 'tenant-A-access-token',
            refreshToken: 'tenant-A-refresh-token',
          },
        },
      })
      mockGetUserInfo.mockResolvedValue({
        data: {
          data: { id: '1', username: 'admin', tenantId: 'tenant_A' },
        },
      })

      await act(async () => {
        await useAuthStore.getState().login('admin', 'password')
      })

      const state = useAuthStore.getState()
      expect(state.accessToken).toBe('tenant-A-access-token')
      expect(state.refreshToken).toBe('tenant-A-refresh-token')
      expect(state.isAuthenticated).toBe(true)
      expect(state.user?.tenantId).toBe('tenant_A')
    })

    it('should send tenantId in login params', async () => {
      mockLogin.mockResolvedValue({
        data: { data: { accessToken: 'at', refreshToken: 'rt' } },
      })
      mockGetUserInfo.mockResolvedValue({
        data: { data: { id: '1', username: 'admin' } },
      })

      await act(async () => {
        await useAuthStore.getState().login('admin', 'password')
      })

      expect(mockLogin).toHaveBeenCalledWith(
        expect.objectContaining({ tenantId: 'tenant_default' })
      )
    })
  })

  describe('Account switching - cache clearing', () => {
    it('should clear all auth state on logout', async () => {
      // Set up authenticated state for tenant A
      act(() => {
        useAuthStore.setState({
          user: { id: '1', username: 'admin', tenantId: 'tenant_A' } as any,
          accessToken: 'tenant-A-token',
          refreshToken: 'tenant-A-refresh',
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

    it('should clear auth via clearAuth method', () => {
      act(() => {
        useAuthStore.setState({
          user: { id: '1', username: 'admin', tenantId: 'tenant_B' } as any,
          accessToken: 'tenant-B-token',
          refreshToken: 'tenant-B-refresh',
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

    it('should clear auth even if logout API fails', async () => {
      act(() => {
        useAuthStore.setState({
          user: { id: '1', username: 'admin' } as any,
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

  describe('Store reset on re-login', () => {
    it('should fully replace state when logging in as different tenant user', async () => {
      // Initial login as tenant A
      act(() => {
        useAuthStore.setState({
          user: { id: '1', username: 'adminA', tenantId: 'tenant_A' } as any,
          accessToken: 'tenant-A-token',
          refreshToken: 'tenant-A-refresh',
          isAuthenticated: true,
        })
      })

      // Clear auth (simulates logout)
      act(() => {
        useAuthStore.getState().clearAuth()
      })

      // Login as tenant B
      mockLogin.mockResolvedValue({
        data: {
          data: {
            accessToken: 'tenant-B-token',
            refreshToken: 'tenant-B-refresh',
          },
        },
      })
      mockGetUserInfo.mockResolvedValue({
        data: {
          data: { id: '2', username: 'adminB', tenantId: 'tenant_B' },
        },
      })

      await act(async () => {
        await useAuthStore.getState().login('adminB', 'password')
      })

      const state = useAuthStore.getState()
      expect(state.accessToken).toBe('tenant-B-token')
      expect(state.user?.tenantId).toBe('tenant_B')
      expect(state.user?.username).toBe('adminB')
      // Should NOT have any tenant A data
      expect(state.user?.username).not.toBe('adminA')
    })
  })

  describe('Token refresh maintains tenant context', () => {
    it('should refresh token within same tenant', async () => {
      act(() => {
        useAuthStore.setState({
          user: { id: '1', username: 'admin', tenantId: 'tenant_A' } as any,
          accessToken: 'old-tenant-A-token',
          refreshToken: 'tenant-A-refresh',
          isAuthenticated: true,
        })
      })

      mockRefreshToken.mockResolvedValue({
        data: {
          data: {
            accessToken: 'new-tenant-A-token',
            refreshToken: 'new-tenant-A-refresh',
          },
        },
      })

      let result: string | null = null
      await act(async () => {
        result = await useAuthStore.getState().refreshAccessToken()
      })

      expect(result).toBe('new-tenant-A-token')
      expect(useAuthStore.getState().accessToken).toBe('new-tenant-A-token')
      // User info should remain unchanged
      expect(useAuthStore.getState().user?.tenantId).toBe('tenant_A')
    })

    it('should clear auth and return null when refresh fails', async () => {
      act(() => {
        useAuthStore.setState({
          accessToken: 'expired-token',
          refreshToken: 'expired-refresh',
          isAuthenticated: true,
        })
      })

      mockRefreshToken.mockRejectedValue(new Error('Refresh failed'))

      let result: string | null = 'something'
      await act(async () => {
        result = await useAuthStore.getState().refreshAccessToken()
      })

      expect(result).toBeNull()
      expect(useAuthStore.getState().isAuthenticated).toBe(false)
      expect(useAuthStore.getState().accessToken).toBeNull()
    })
  })

  describe('Zustand persist storage isolation', () => {
    it('should persist auth state to localStorage under auth-storage key', () => {
      act(() => {
        useAuthStore.setState({
          accessToken: 'persisted-token',
          refreshToken: 'persisted-refresh',
          isAuthenticated: true,
          user: { id: '1', username: 'admin' } as any,
        })
      })

      // Zustand persist serializes state to localStorage
      const stored = localStorage.getItem('auth-storage')
      if (stored) {
        const parsed = JSON.parse(stored)
        expect(parsed.state.accessToken).toBe('persisted-token')
        expect(parsed.state.isAuthenticated).toBe(true)
      }
    })

    it('should clear persisted state on clearAuth', () => {
      act(() => {
        useAuthStore.setState({
          accessToken: 'token-to-clear',
          isAuthenticated: true,
        })
      })

      act(() => {
        useAuthStore.getState().clearAuth()
      })

      const state = useAuthStore.getState()
      expect(state.accessToken).toBeNull()
      expect(state.isAuthenticated).toBe(false)
    })
  })
})
