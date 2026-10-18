// @vitest-environment jsdom
// case_ids: UI-061
/**
 * 企业名称读取口（issue #7219）—— 四张纸面表头共用。
 *
 * 判据：
 * ① **登录态优先**：`useAuthStore.user.tenantName` 已随 `/api/auth/me` 下发 ⇒ 普通员工（无
 *    `system:manage`）打印时也能印企业名；
 * ② 登录态为空 ⇒ 回落 `GET /api/admin/settings` 的 `companyName`；
 * ③ 读失败 ⇒ 空串（调用方整行不渲染，不印「未设置」）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'

const mockGetSettings = vi.fn()
let currentUser: { tenantName?: string } | null = null

vi.mock('@/lib/api', () => ({
  settingsApi: { getSettings: () => mockGetSettings() },
}))
vi.mock('@/store/auth', () => ({
  useAuthStore: (selector: (state: { user: unknown }) => unknown) => selector({ user: currentUser }),
}))

import { useCompanyName, __resetCompanyNameCache } from '@/lib/use-company-name'

describe('useCompanyName（issue #7219）', () => {
  beforeEach(() => {
    __resetCompanyNameCache()
    currentUser = null
    mockGetSettings.mockResolvedValue({ data: { data: { companyName: '设置里的企业' } } })
  })

  it('① 登录态 tenantName 优先（普通员工也能印企业名）', async () => {
    currentUser = { tenantName: '米高布艺' }
    const { result } = renderHook(() => useCompanyName())
    await waitFor(() => expect(result.current).toBe('米高布艺'))
  })

  it('② 登录态为空 ⇒ 回落设置读面 companyName', async () => {
    const { result } = renderHook(() => useCompanyName())
    await waitFor(() => expect(result.current).toBe('设置里的企业'))
  })

  it('③ 读失败 ⇒ 空串（不印「未设置」，也不抛错）', async () => {
    mockGetSettings.mockRejectedValue(new Error('403'))
    const { result } = renderHook(() => useCompanyName())
    await waitFor(() => expect(result.current).toBe(''))
  })
})
