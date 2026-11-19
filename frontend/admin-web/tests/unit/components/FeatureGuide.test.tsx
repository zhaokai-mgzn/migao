// case_ids: UI-153
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

// 本组件只读 `useAuthStore(s => s.user)` —— 用最小替身，不触真实 store 的 API 调用。
const authState = vi.hoisted(() => ({
  current: { user: null as any },
}))
vi.mock('@/store/auth', () => ({
  useAuthStore: (selector?: (s: unknown) => unknown) =>
    typeof selector === 'function' ? selector(authState.current) : authState.current,
}))

import FeatureGuide from '@/components/onboarding/FeatureGuide'
import {
  featureGuideDismissedKey,
  hasFeatureGuideShown,
  markFeatureGuidePending,
  resetFeatureGuideSession,
  shouldShowFeatureGuide,
} from '@/lib/feature-guide'

const ADMIN_USER = {
  id: 'u-guide-1',
  username: 'zhangsan@migao',
  name: '张三',
  roles: ['admin'],
  permissions: ['*'],
  capabilities: { mibaoChat: true },
}

const CUSTOMER_SERVICE_USER = {
  id: 'u-guide-2',
  username: 'kefu@migao',
  name: '客服小王',
  roles: ['customer_service'],
  permissions: ['agent:session', 'knowledge:view', 'after_sales:view', 'customer:view'],
  capabilities: { mibaoChat: false },
}

describe('FeatureGuide 首次登录引导（issue #8925，UI-153）', () => {
  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
    authState.current = { user: ADMIN_USER }
  })

  it('登录后首次进入业务页弹出；两个操作按钮与「关闭仅本次」提示同屏', async () => {
    markFeatureGuidePending()
    render(<FeatureGuide />)

    const dialog = await screen.findByRole('dialog', { name: '功能使用引导' })
    expect(dialog).toBeVisible()
    expect(screen.getByRole('button', { name: '关闭' })).toBeVisible()
    expect(screen.getByRole('button', { name: '不再提醒' })).toBeVisible()
    expect(screen.getByText('「关闭」仅本次，下次登录仍会提示')).toBeVisible()
    expect(screen.getAllByTestId('feature-guide-step')).toHaveLength(4)
    expect(screen.getByTestId('feature-guide-module-customer-service')).toHaveTextContent('在线接待')

    // 展示即消费 pending + 记 shown
    expect(hasFeatureGuideShown()).toBe(true)
    expect(shouldShowFeatureGuide(ADMIN_USER.id)).toBe(false)
  })

  it('点「关闭」⇒ 本次会话不再弹；重新登录（清 session + 落 pending）⇒ 再次弹出', async () => {
    const user = userEvent.setup()
    markFeatureGuidePending()
    render(<FeatureGuide />)
    await screen.findByRole('dialog', { name: '功能使用引导' })

    await user.click(screen.getByTestId('feature-guide-close'))
    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: '功能使用引导' })).not.toBeInTheDocument()
    })
    // 没有写 localStorage —— 所以下次登录还能来
    expect(localStorage.getItem(featureGuideDismissedKey(ADMIN_USER.id))).toBeNull()

    cleanup()
    resetFeatureGuideSession() // 退出登录
    markFeatureGuidePending() // 下次登录成功
    render(<FeatureGuide />)
    expect(await screen.findByRole('dialog', { name: '功能使用引导' })).toBeVisible()
  })

  it('点「不再提醒」⇒ 写按用户持久化标记；重新登录也不再弹', async () => {
    const user = userEvent.setup()
    markFeatureGuidePending()
    render(<FeatureGuide />)
    await screen.findByRole('dialog', { name: '功能使用引导' })

    await user.click(screen.getByTestId('feature-guide-never'))
    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: '功能使用引导' })).not.toBeInTheDocument()
    })
    expect(localStorage.getItem(featureGuideDismissedKey(ADMIN_USER.id))).toBe('1')

    cleanup()
    resetFeatureGuideSession()
    markFeatureGuidePending()
    render(<FeatureGuide />)
    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: '功能使用引导' })).not.toBeInTheDocument()
    })
    expect(shouldShowFeatureGuide(ADMIN_USER.id)).toBe(false)
  })

  it('403 面（enabled=false）不弹；恢复后仍需「本次登录」标记才弹', async () => {
    markFeatureGuidePending()
    const { rerender } = render(<FeatureGuide enabled={false} />)
    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: '功能使用引导' })).not.toBeInTheDocument()
    })
    // 没有 enabled 时不该消费 pending
    expect(hasFeatureGuideShown()).toBe(false)

    rerender(<FeatureGuide enabled />)
    expect(await screen.findByRole('dialog', { name: '功能使用引导' })).toBeVisible()
  })

  it('未登录（无 user）不弹', async () => {
    authState.current = { user: null }
    markFeatureGuidePending()
    render(<FeatureGuide />)
    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: '功能使用引导' })).not.toBeInTheDocument()
    })
  })

  it('功能地图按岗位权限裁剪 + 无权限的提示卡也按能力位隐藏', async () => {
    authState.current = { user: CUSTOMER_SERVICE_USER }
    markFeatureGuidePending()
    render(<FeatureGuide />)
    await screen.findByRole('dialog', { name: '功能使用引导' })

    // 有权限的模块与子项在
    expect(screen.getByTestId('feature-guide-module-customer-service')).toHaveTextContent('在线接待')
    expect(screen.getByTestId('feature-guide-module-orders-products')).toHaveTextContent('客户列表')
    // 无权限的不在（不是灰显，是不渲染）
    expect(screen.queryByTestId('feature-guide-module-finance-center')).not.toBeInTheDocument()
    expect(screen.queryByText('销售订单')).not.toBeInTheDocument()
    // 无 dashboard:view ⇒ 不教用户先看经营报表；无 mibaoChat ⇒ 不承诺米宝
    expect(screen.queryByText('先看经营报表')).not.toBeInTheDocument()
    expect(screen.queryByText('不会操作就问米宝')).not.toBeInTheDocument()
    expect(screen.getByText('从左侧菜单进入业务')).toBeVisible()
  })

  it('空权限 ⇒ 可行动的空态（不渲染空模块列表）', async () => {
    authState.current = {
      user: { id: 'u-guide-3', username: 'new@migao', permissions: [], roles: [] },
    }
    markFeatureGuidePending()
    render(<FeatureGuide />)
    await screen.findByRole('dialog', { name: '功能使用引导' })
    expect(screen.getByTestId('feature-guide-no-modules')).toHaveTextContent('请联系企业管理员配置岗位权限')
    expect(screen.queryByTestId('feature-guide-modules')).not.toBeInTheDocument()
  })
})
