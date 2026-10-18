// @vitest-environment jsdom
// case_ids: UI-061
/**
 * 企业名称读取口（issue #7219）—— 四张纸面表头共用。
 *
 * 判据：
 * ① **登录态优先**：`useAuthStore.user.tenantName` 已随 `/api/auth/me` 下发 ⇒ 普通员工（无
 *    `system:manage`）打印时也能印企业名；
 * ② 登录态为空 ⇒ 回落 `GET /api/admin/settings` 的 `companyName`；
 * ③ 读失败 ⇒ 空串（调用方整行不渲染，不印「未设置」）；
 * ④ **登录态有 tenantName ⇒ 一次设置读面都不发**（issue #7285：该请求要 `system:manage`，
 *    而四张纸面在订单详情页常驻挂载 ⇒ 无该码的岗位每进页面弹一条 403）；
 * ⑤ 对照：登录态为空 ⇒ 仍然回落（防 ④ 用「永远不发」作弊）。
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
    mockGetSettings.mockClear() // ④/⑤ 断言的是**调用次数** ⇒ 每条用例从零起算
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

  it('④ 登录态有 tenantName ⇒ **一次设置读面都不发**（issue #7285：无 system:manage 的岗位不得被纸面钩子打出 403 弹窗）', async () => {
    currentUser = { tenantName: '米高布艺' }
    const { result } = renderHook(() => useCompanyName())
    await waitFor(() => expect(result.current).toBe('米高布艺'))
    // 判别力：修前这条必红 —— 旧实现**无条件**回落读 `GET /api/admin/settings`（system:manage）
    // ⇒ 客服/销售/财务一进订单详情页就弹一条「没有权限执行此操作」。
    expect(mockGetSettings).not.toHaveBeenCalled()
  })

  it('⑤ 对照：登录态**没有** tenantName ⇒ 仍然回落（否则 ④ 可以靠「永远不发」作弊）', async () => {
    currentUser = {}
    const { result } = renderHook(() => useCompanyName())
    await waitFor(() => expect(result.current).toBe('设置里的企业'))
    expect(mockGetSettings).toHaveBeenCalledTimes(1)
  })
})
