// 首次登录功能使用引导：展示时机与「不再提醒」偏好（issue #8925）。
//
// ## 为什么用 sessionStorage 记录「本次登录已展示」
//
// 产品口径只有两条：
//   ① 点「关闭」= 本次关闭，**下次登录仍然弹出**；
//   ② 点「不再提醒」= 之后不再自动弹出。
//
// 若把 ① 也写 localStorage（或只写一个「已关闭」标记），登录后的刷新 / 站内跳转都会再次弹，
// 与「关闭」的语义不符。这里拆成三枚标记：
//   · pending（sessionStorage）—— **登录成功**那一刻写入；引导真正展示时消费掉；
//   · shown（sessionStorage）—— 本次浏览器会话已展示过；刷新 / 站内跳转不再重复；
//   · dismissed:<userId>（localStorage）—— 用户点了「不再提醒」，跨会话、跨刷新持久。
//
// 退出登录（`clearAuth`）会清掉前两枚 session 标记，于是「关闭后重新登录」能再次看到引导；
// dismissed 按用户 id 隔离，同一浏览器换账号登录不会被别人的「不再提醒」影响。
//
// ## 边界（有意为之，不是遗漏）
//
// dismissed 存在本机 localStorage（与侧边栏「常用」等既有偏好同一模式）⇒ **换浏览器 / 换设备
// 不同步**。要跨端同步需要服务端偏好表 + 迁移 + 端点；本轮不做，PR 里如实登记。

import type { User } from '@/types'
import { menuGroups } from '@/config/menu'
import { visibleMenuGroups } from '@/lib/menu-nav'

/** 引导内容版本：改版后想让老用户重新看到，升版本即可自然换新键。 */
export const FEATURE_GUIDE_VERSION = 1

/** 登录成功 ⇒ 写入（sessionStorage）；引导展示时消费。 */
export const FEATURE_GUIDE_PENDING_KEY = `migao.feature-guide.pending.v${FEATURE_GUIDE_VERSION}`

/** 本次浏览器会话已展示 ⇒ 刷新 / 站内跳转不再弹（sessionStorage）。 */
export const FEATURE_GUIDE_SHOWN_KEY = `migao.feature-guide.shown.v${FEATURE_GUIDE_VERSION}`

/** 「不再提醒」按用户隔离（localStorage，前缀 + 用户 key）。 */
export const FEATURE_GUIDE_DISMISSED_PREFIX = `migao.feature-guide.dismissed.v${FEATURE_GUIDE_VERSION}.`

/** 引导里展示的一个菜单分组（名称 / 子项全部来自 `config/menu.ts`，不在本文件另抄一份）。 */
export interface FeatureGuideModule {
  key: string
  name: string
  items: string[]
}

function sessionStorageSafe(): Storage | null {
  if (typeof window === 'undefined') return null
  try {
    return window.sessionStorage
  } catch {
    return null
  }
}

function localStorageSafe(): Storage | null {
  if (typeof window === 'undefined') return null
  try {
    return window.localStorage
  } catch {
    return null
  }
}

/**
 * 偏好键的用户标识：优先 `id`（稳定），历史 / 测试数据缺 id 时退回 `username`。
 * 两者都没有 ⇒ `null`（此时既不展示也不写偏好，避免把不同人混成同一条「不再提醒」）。
 */
export function featureGuideUserKey(
  user: Pick<User, 'id' | 'username'> | null | undefined,
): string | null {
  const id = typeof user?.id === 'string' ? user.id.trim() : ''
  if (id) return id
  const username = typeof user?.username === 'string' ? user.username.trim() : ''
  return username || null
}

/** 「不再提醒」的完整 localStorage 键（导出让测试可精确断言 / 清理）。 */
export function featureGuideDismissedKey(userKey: string): string {
  return `${FEATURE_GUIDE_DISMISSED_PREFIX}${userKey}`
}

/** 登录成功后调用：标记「本次登录尚待展示」。存储不可用时静默降级（引导下次登录还会来）。 */
export function markFeatureGuidePending(): void {
  try {
    sessionStorageSafe()?.setItem(FEATURE_GUIDE_PENDING_KEY, '1')
  } catch {
    /* 隐私模式 / 配额满：本次不展示，不阻塞登录 */
  }
}

/** 本次浏览器会话是否已经展示过（含已经关闭）。 */
export function hasFeatureGuideShown(): boolean {
  try {
    return sessionStorageSafe()?.getItem(FEATURE_GUIDE_SHOWN_KEY) === '1'
  } catch {
    return false
  }
}

/** 用户是否点过「不再提醒」。 */
export function isFeatureGuideDismissed(userKey: string | null | undefined): boolean {
  if (!userKey) return false
  try {
    return localStorageSafe()?.getItem(featureGuideDismissedKey(userKey)) === '1'
  } catch {
    return false
  }
}

/**
 * 是否该自动弹出：有「本次登录待展示」标记 + 本会话没展示过 + 该用户没点过「不再提醒」。
 * 三个条件缺一不可；任何存储异常都按「不弹」处理，避免把引导变成登录阻断。
 */
export function shouldShowFeatureGuide(userKey: string | null | undefined): boolean {
  if (!userKey) return false
  try {
    if (sessionStorageSafe()?.getItem(FEATURE_GUIDE_PENDING_KEY) !== '1') return false
  } catch {
    return false
  }
  if (hasFeatureGuideShown()) return false
  return !isFeatureGuideDismissed(userKey)
}

/** 引导真正展示时调用：消费 pending，并记下「本会话已展示」。 */
export function markFeatureGuideShown(): void {
  const storage = sessionStorageSafe()
  try {
    storage?.setItem(FEATURE_GUIDE_SHOWN_KEY, '1')
    storage?.removeItem(FEATURE_GUIDE_PENDING_KEY)
  } catch {
    /* 静默：写不进去最多下次再弹，不影响用户操作 */
  }
}

/** 点「不再提醒」：按用户持久化，并消费本次 pending。 */
export function dismissFeatureGuide(userKey: string): void {
  try {
    localStorageSafe()?.setItem(featureGuideDismissedKey(userKey), '1')
  } catch {
    /* 静默：写不进去最多下次再弹 */
  }
  try {
    sessionStorageSafe()?.removeItem(FEATURE_GUIDE_PENDING_KEY)
  } catch {
    /* ignore */
  }
}

/**
 * 清理本次会话标记（退出登录 / 会话失效时调用）。
 * **不能**清 dismissed —— 那正是「不再提醒」跨会话生效的载体。
 */
export function resetFeatureGuideSession(): void {
  const storage = sessionStorageSafe()
  if (!storage) return
  try {
    storage.removeItem(FEATURE_GUIDE_PENDING_KEY)
    storage.removeItem(FEATURE_GUIDE_SHOWN_KEY)
  } catch {
    /* ignore */
  }
}

/**
 * 按当前账号权限派生引导里的功能地图。
 *
 * 名称 / 子项 / 顺序全部走 `menuGroups` + `visibleMenuGroups`（与侧边栏同一套权限过滤），
 * 不在引导里另抄一份菜单 —— 菜单改名 / 调权限后引导不会漂移。
 */
export function buildFeatureGuideModules(
  permissions: string[] = [],
  roles: string[] = [],
): FeatureGuideModule[] {
  return visibleMenuGroups(menuGroups, { permissions, roles }).map((group) => ({
    key: group.key,
    name: group.name,
    items: group.children.map((item) => item.name),
  }))
}
