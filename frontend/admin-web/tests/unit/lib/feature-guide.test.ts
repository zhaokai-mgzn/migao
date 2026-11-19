// case_ids: UI-153
import { describe, it, expect, beforeEach, vi } from 'vitest'
import {
  FEATURE_GUIDE_DISMISSED_PREFIX,
  FEATURE_GUIDE_PENDING_KEY,
  FEATURE_GUIDE_SHOWN_KEY,
  buildFeatureGuideModules,
  dismissFeatureGuide,
  featureGuideDismissedKey,
  featureGuideUserKey,
  hasFeatureGuideShown,
  isFeatureGuideDismissed,
  markFeatureGuidePending,
  markFeatureGuideShown,
  resetFeatureGuideSession,
  shouldShowFeatureGuide,
} from '@/lib/feature-guide'

/**
 * 首次登录功能使用引导的**存储语义**（issue #8925，用例 UI-153）。
 *
 * 产品口径（用户 2026-11-19）：
 *   · 点「关闭」= 本次关闭，下次登录继续弹出；
 *   · 点「不再提醒」= 之后不再自动弹出。
 *
 * 本文件把两句口径逐字翻成状态机：pending（登录落）→ shown（本次已展示）→ dismissed（按用户持久）。
 */
describe('feature-guide：登录 / 关闭 / 不再提醒的存储语义', () => {
  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
  })

  it('没有「本次登录待展示」标记时，不自动弹（刷新 / 深链不打扰）', () => {
    expect(shouldShowFeatureGuide('u1')).toBe(false)
    // 即便本会话从未展示、用户也没点过不再提醒
    expect(hasFeatureGuideShown()).toBe(false)
    expect(isFeatureGuideDismissed('u1')).toBe(false)
  })

  it('登录成功落 pending ⇒ 首次进入业务页应弹；展示后消费 pending 并记 shown', () => {
    markFeatureGuidePending()
    expect(sessionStorage.getItem(FEATURE_GUIDE_PENDING_KEY)).toBe('1')
    expect(shouldShowFeatureGuide('u1')).toBe(true)

    markFeatureGuideShown()
    expect(sessionStorage.getItem(FEATURE_GUIDE_PENDING_KEY)).toBeNull()
    expect(sessionStorage.getItem(FEATURE_GUIDE_SHOWN_KEY)).toBe('1')
    // 本次会话刷新 / 站内跳转不再弹（「关闭」语义）
    expect(shouldShowFeatureGuide('u1')).toBe(false)
  })

  it('「关闭」后重新登录（清 session 标记 + 登录再落 pending）⇒ 再次弹出', () => {
    markFeatureGuidePending()
    markFeatureGuideShown()
    expect(shouldShowFeatureGuide('u1')).toBe(false)

    // 退出登录：只清 session，不碰按用户持久化的 dismissed
    resetFeatureGuideSession()
    expect(hasFeatureGuideShown()).toBe(false)
    expect(isFeatureGuideDismissed('u1')).toBe(false)

    // 下次登录成功
    markFeatureGuidePending()
    expect(shouldShowFeatureGuide('u1')).toBe(true)
  })

  it('「不再提醒」⇒ 重登 / 刷新都不再弹（dismissed 持久化）', () => {
    markFeatureGuidePending()
    markFeatureGuideShown()
    dismissFeatureGuide('u1')

    expect(localStorage.getItem(featureGuideDismissedKey('u1'))).toBe('1')
    resetFeatureGuideSession()
    markFeatureGuidePending()
    expect(shouldShowFeatureGuide('u1')).toBe(false)
  })

  it('「不再提醒」按用户隔离：A 关掉不影响 B 首次登录', () => {
    markFeatureGuidePending()
    dismissFeatureGuide('user-a')
    resetFeatureGuideSession()

    markFeatureGuidePending()
    expect(shouldShowFeatureGuide('user-a')).toBe(false)
    expect(shouldShowFeatureGuide('user-b')).toBe(true)
  })

  it('用户键优先 id、缺失时退回 username；两者都没有 ⇒ null（不展示、不写偏好）', () => {
    expect(featureGuideUserKey({ id: 'u1', username: 'zhangsan' })).toBe('u1')
    expect(featureGuideUserKey({ id: '  ', username: ' zhangsan ' })).toBe('zhangsan')
    expect(featureGuideUserKey({ id: '', username: '' })).toBeNull()
    expect(featureGuideUserKey(null)).toBeNull()
    expect(shouldShowFeatureGuide(null)).toBe(false)
    expect(featureGuideDismissedKey('u1')).toBe(`${FEATURE_GUIDE_DISMISSED_PREFIX}u1`)
  })

  it('存储写失败时静默降级（不抛错、不把引导变成登录阻断）', () => {
    const sessionSet = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('QuotaExceededError')
    })
    try {
      expect(() => markFeatureGuidePending()).not.toThrow()
      expect(() => markFeatureGuideShown()).not.toThrow()
      expect(() => dismissFeatureGuide('u1')).not.toThrow()
    } finally {
      sessionSet.mockRestore()
    }
  })
})

/**
 * 功能地图必须与侧边栏同源（`config/menu.ts` + 同一权限过滤），只展示当前账号有权限的模块。
 * 反例：手抄一份菜单 ⇒ 菜单改名 / 权限收回后引导教用户点不存在的入口。
 */
describe('feature-guide：功能地图按权限派生', () => {
  it('管理员（*）看到全部菜单分组', () => {
    const modules = buildFeatureGuideModules(['*'], ['admin'])
    expect(modules.map((m) => m.key)).toEqual([
      'customer-service',
      'orders-products',
      'production-center',
      'quality',
      'inventory-center',
      'finance-center',
      'supply-chain',
      'org-center',
    ])
    expect(modules.find((m) => m.key === 'finance-center')?.items).toEqual(['财务对账', '计件工资'])
  })

  it('客服岗位只看到有权限的菜单项，不出现无权模块的子项', () => {
    const modules = buildFeatureGuideModules(
      ['agent:session', 'knowledge:view', 'after_sales:view', 'customer:view'],
      ['customer_service'],
    )
    const names = modules.map((m) => m.name)
    expect(names).toContain('客户服务')
    expect(names).toContain('订单/商品')
    // 客户服务组内三项都有权限
    expect(modules.find((m) => m.key === 'customer-service')?.items).toEqual([
      '在线接待',
      '售后工单',
      '知识库',
    ])
    // 订单/商品组只保留 customer:view 的「客户列表」，不出现销售订单 / 商品管理
    expect(modules.find((m) => m.key === 'orders-products')?.items).toEqual(['客户列表'])
    // 无 finance:view ⇒ 财务组整组不出现
    expect(names).not.toContain('财务')
  })

  it('空权限 ⇒ 空地图（页面显示可行动的空态，而不是假装有功能）', () => {
    expect(buildFeatureGuideModules([], [])).toEqual([])
  })
})
