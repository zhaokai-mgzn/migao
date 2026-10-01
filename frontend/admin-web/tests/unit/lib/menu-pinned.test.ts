// case_ids: UI-067
/**
 * 侧边栏「常用（收藏）」纯函数穷举（issue #5778）。
 *
 * ## 为什么这些判据必须存在（每条对应一个**真会发生的坏形态**）
 *
 * 「常用」= 用户自己钉的一组菜单项 key。它是**个性化偏好**，不是第四处菜单源
 * ⇒ 唯一的危险是「偏好被当成权限」或「偏好留下死引用」，所以本文件把三件事钉死：
 *
 *   ① **权限优先于偏好**：钉过的项若当前无权（或企业开关关了「每日简报」）⇒ **必须**从
 *      「常用」消失（`resolvePinnedItems`）。漏掉这条 = 「收藏可以绕过菜单权限」（安全缺口）；
 *   ② **不做死引用**：菜单项被删/改名（key 不再存在）⇒ 静默丢弃（侧边栏不出现死链、
 *      不抛错）；清单为空或钉住项**一项都不可见** ⇒ 整个「常用」区不渲染（`pinnedGroup` 返回 null）
 *      —— 空标题比没有标题更糟（用户会以为功能坏了）；
 *   ③ **上限与脏数据**：最多 `PINNED_MAX` 项；超出**拒绝**（原样返回，不静默顶掉别人的位置）；
 *      持久化值形状不对（非数组 / 非字符串 / 空串 / 重复）⇒ 一律按「读到什么算什么」清洗。
 *   ④ 🔴 **一级项不进「常用」**（#5877，用户 2026-10-01 裁定）：一级项已是一屏直达、且**没有星标**，
 *      再让它进「常用」只会在同一屏出现两条一模一样的入口 ⇒ 可收藏面**只含组内项 + 尾部独立项**；
 *      用户 localStorage 里残留的 `products` key **静默丢弃**（沿用既有「无效 key 静默丢弃」口径）。
 *
 * ## 边界（如实登记）
 *
 *   持久化在 `localStorage`（与既有的折叠态 / 浮窗位置同一模式）⇒ **换浏览器 / 换设备不同步**；
 *   服务端同步（偏好表 + 迁移 + 端点）**本轮有意不做**，不是漏做。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { menuGroups, standaloneTopItems, standaloneItems, type MenuItem } from '@/config/menu'
import {
  PINNED_MAX,
  PINNED_STORAGE_KEY,
  PINNED_GROUP_KEY,
  loadPinned,
  savePinned,
  togglePinned,
  isPinned,
  resolvePinnedItems,
  pinnedGroup,
  type MenuFilterOptions,
} from '@/lib/menu-nav'

const ADMIN: MenuFilterOptions = { permissions: ['*'], roles: ['admin'], briefingEnabled: true }

/** 全部可见项（权限过滤后）—— 与侧边栏 / 命令面板同一套纯函数 */
const visibleAll = (opts: MenuFilterOptions = ADMIN): MenuItem[] => [
  ...menuGroups.flatMap((g) => g.children.filter((i) => !i.permissionCode || opts.permissions.includes('*') || opts.permissions.includes(i.permissionCode))),
  ...standaloneTopItems,
  ...standaloneItems,
]

beforeEach(() => {
  window.localStorage.clear()
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('「常用（收藏）」：上限与纯函数三态（issue #5778 / UI-067）', () => {
  it('togglePinned 三态：未钉 ⇒ 追加到**末尾**（顺序 = 用户钉的顺序）；已钉 ⇒ 取消；满额 ⇒ **原样返回**（拒绝，不顶替）', () => {
    let pinned: string[] = []
    pinned = togglePinned(pinned, 'orders')
    pinned = togglePinned(pinned, 'customers')
    expect(pinned).toEqual(['orders', 'customers'])

    // 已钉 ⇒ 取消（保持其余顺序）
    expect(togglePinned(pinned, 'orders')).toEqual(['customers'])

    // 钉满 `PINNED_MAX` 项后再钉 ⇒ 原样返回（**不静默顶掉第一项**）
    const full = Array.from({ length: PINNED_MAX }, (_, i) => visibleAll()[i].key)
    expect(full).toHaveLength(PINNED_MAX)
    expect(togglePinned(full, 'notifications')).toEqual(full)
    // 自证：满额清单里的项都是**真实存在**的菜单项（否则上面那条断言是空跑）
    const realKeys = visibleAll().map((i) => i.key)
    for (const k of full) expect(realKeys).toContain(k)
  })

  it('isPinned：只认清单内的 key（大小写敏感、不做前缀匹配）', () => {
    const pinned = ['orders']
    expect(isPinned(pinned, 'orders')).toBe(true)
    expect(isPinned(pinned, 'Orders')).toBe(false)
    expect(isPinned(pinned, 'order')).toBe(false)
    expect(isPinned([], 'orders')).toBe(false)
  })
})

describe('「常用（收藏）」：持久化（SSR 安全 + 脏数据清洗）', () => {
  it('savePinned → loadPinned 往返一致（且写入的是 `PINNED_STORAGE_KEY`）', () => {
    savePinned(['orders', 'customers'])
    expect(window.localStorage.getItem(PINNED_STORAGE_KEY)).toBe(JSON.stringify(['orders', 'customers']))
    expect(loadPinned()).toEqual(['orders', 'customers'])
  })

  it('🔴 坏形状一律回空表（**不抛错**）：非 JSON / 非数组 / 元素非字符串 / 空串 / 重复 —— 逐个注入', () => {
    const cases: [string, string][] = [
      ['非 JSON', '{not json'],
      ['JSON 但不是数组', '{"a":1}'],
      ['数组里混了数字与 null', '["orders",1,null]'],
      ['数组里混了空串与空白', '["", "   ", "customers"]'],
      ['重复项', '["orders","orders","customers"]'],
      ['元素是数组（嵌套）', '[["orders"]]'],
    ]
    /** 每条坏形状的**精确**清洗结果（弱断言的反面：逐条点名读数） */
    const EXPECTED_SANITIZED: Record<string, string[]> = {
      '非 JSON': [],
      'JSON 但不是数组': [],
      '数组里混了数字与 null': ['orders'],
      '数组里混了空串与空白': ['customers'],
      '重复项': ['orders', 'customers'],
      '元素是数组（嵌套）': [],
    }
    for (const [name, raw] of cases) {
      window.localStorage.setItem(PINNED_STORAGE_KEY, raw)
      // 不抛错 + 只保留合法项（自证：下面每条都真的读了一次）
      const got = loadPinned()
      // 🔴 用**精确期望值**（不是"是个数组"这类弱断言）：每条坏形状各报它的清洗结果
      expect(got, name).toEqual(EXPECTED_SANITIZED[name])
      for (const k of got) {
        expect(k.trim(), name).toBe(k)
        expect(k, name).not.toBe('')
      }
      expect(new Set(got).size, name).toBe(got.length)
    }
    // 逐个点名读数（不是只看「没抛」）
    window.localStorage.setItem(PINNED_STORAGE_KEY, '{not json')
    expect(loadPinned()).toEqual([])
    window.localStorage.setItem(PINNED_STORAGE_KEY, '{"a":1}')
    expect(loadPinned()).toEqual([])
    window.localStorage.setItem(PINNED_STORAGE_KEY, '["orders",1,null]')
    expect(loadPinned()).toEqual(['orders'])
    window.localStorage.setItem(PINNED_STORAGE_KEY, '["", "   ", "customers"]')
    expect(loadPinned()).toEqual(['customers'])
    window.localStorage.setItem(PINNED_STORAGE_KEY, '["orders","orders","customers"]')
    expect(loadPinned()).toEqual(['orders', 'customers'])
  })

  it('读取**截断到上限**（历史上存过更长的清单 ⇒ 只取前 `PINNED_MAX` 项，不整表失效）', () => {
    const long = visibleAll().map((i) => i.key).slice(0, PINNED_MAX + 3)
    expect(long.length).toBeGreaterThan(PINNED_MAX)
    window.localStorage.setItem(PINNED_STORAGE_KEY, JSON.stringify(long))
    expect(loadPinned()).toEqual(long.slice(0, PINNED_MAX))
  })

  it('localStorage 抛错（隐私模式 / 配额满）⇒ 读回空表、写静默失败，**不影响功能**', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('SecurityError')
    })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('QuotaExceededError')
    })
    expect(() => loadPinned()).not.toThrow()
    expect(loadPinned()).toEqual([])
    expect(() => savePinned(['orders'])).not.toThrow()
  })
})

describe('「常用（收藏）」：权限与有效性过滤（🔴 不得成为绕过菜单权限的口子）', () => {
  it('🔴 钉过但**当前无权**的项 ⇒ 从「常用」消失（权限优先于偏好）', () => {
    const pinned = ['orders', 'customers', 'knowledge']
    // 只持 order:list：customers / knowledge 无权 ⇒ 只剩 orders
    const items = resolvePinnedItems(menuGroups, standaloneItems, pinned, {
      permissions: ['order:list'],
      roles: [],
    })
    expect(items.map((i) => i.key)).toEqual(['orders'])
    // 反向自证：全权时三项都在（否则上一条可能是「函数恒回空」的假绿）
    expect(
      resolvePinnedItems(menuGroups, standaloneItems, pinned, ADMIN).map((i) => i.key),
    ).toEqual(['orders', 'customers', 'knowledge'])
  })

  it('🔴 企业开关关掉「每日简报」⇒ 即使钉过也**不出现**（与侧边栏同一口径）', () => {
    const pinned = ['briefing']
    expect(
      resolvePinnedItems(menuGroups, standaloneItems, pinned, {
        permissions: ['*'],
        roles: ['admin'],
        briefingEnabled: false,
      }),
    ).toEqual([])
    expect(
      resolvePinnedItems(menuGroups, standaloneItems, pinned, ADMIN).map((i) => i.key),
    ).toEqual(['briefing'])
  })

  it('菜单项被删/改名（key 不存在）⇒ **静默丢弃**，不抛错、不留死引用', () => {
    const pinned = ['orders', 'processing-renamed-away', '', 'pinned']
    const items = resolvePinnedItems(menuGroups, standaloneItems, pinned, ADMIN)
    expect(items.map((i) => i.key)).toEqual(['orders'])
    // 「常用」合成组自己的 key 也不得被当成菜单项（合成 key 不是菜单源）
    expect(items.map((i) => i.key)).not.toContain(PINNED_GROUP_KEY)
  })

  it('保留**用户钉的顺序**（不是菜单自身顺序）：先钉 finance 再钉 orders ⇒ 常用区就是 finance 在前', () => {
    const items = resolvePinnedItems(menuGroups, standaloneItems, ['finance', 'orders'], ADMIN)
    expect(items.map((i) => i.key)).toEqual(['finance', 'orders'])
    // 反例自证：菜单自身顺序是 orders 在前 ⇒ 上面的结果**不可能**是「照抄菜单顺序」
    const menuOrder = visibleAll().map((i) => i.key)
    expect(menuOrder.indexOf('orders')).toBeLessThan(menuOrder.indexOf('finance'))
  })

  it('🔴 一级项**不进「常用」**（#5877）：钉过 `products` 也解析为空 ⇒ 不出现重复入口', () => {
    // 前提（面非空自证）：products 确实是一级项、且**不在**任何组内
    expect(standaloneTopItems.map((i) => i.key)).toContain('products')
    expect(menuGroups.flatMap((g) => g.children.map((c) => c.key))).not.toContain('products')
    // 一级项没星标、也不进「常用」⇒ 解析为空（**不是**「找不到就静默跳过」的假绿：见下一行对照）
    expect(resolvePinnedItems(menuGroups, standaloneItems, ['products'], ADMIN)).toEqual([])
    expect(pinnedGroup(menuGroups, standaloneItems, ['products'], ADMIN)).toBeNull()
    // 对照：同一次调用里，组内项照旧解析得出来（说明函数本身没坏）
    expect(resolvePinnedItems(menuGroups, standaloneItems, ['orders'], ADMIN).map((i) => i.key)).toEqual(['orders'])
    // 对照：尾部独立项（通知中心）**仍可**收藏（它仍是普通项、带星标）
    expect(resolvePinnedItems(menuGroups, standaloneItems, ['notifications'], ADMIN).map((i) => i.key)).toEqual(
      ['notifications'],
    )
  })

  it('🔴 localStorage 里残留的 `products`（旧版本用户数据）⇒ 静默丢弃，不抛错、不留死链', () => {
    window.localStorage.setItem('migao.sidebar.pinned.v1', JSON.stringify(['products', 'orders']))
    expect(() => loadPinned()).not.toThrow()
    expect(loadPinned()).toEqual(['products', 'orders'])
    expect(resolvePinnedItems(menuGroups, standaloneItems, loadPinned(), ADMIN).map((i) => i.key)).toEqual(['orders'])
  })
})

describe('「常用（收藏）」：合成分组（pinnedGroup）', () => {
  it('清单为空 ⇒ 返回 null（整区不渲染）', () => {
    expect(pinnedGroup(menuGroups, standaloneItems, [], ADMIN)).toBeNull()
  })

  it('🔴 钉住的项**一项都不可见** ⇒ 返回 null（不渲染空标题）', () => {
    const pinned = ['orders', 'finance']
    expect(
      pinnedGroup(menuGroups, standaloneItems, pinned, { permissions: [], roles: [] }),
    ).toBeNull()
    // 反向自证：有权限时同一份清单返回**精确内容**（不是「非 null」这种弱断言）
    expect(
      pinnedGroup(menuGroups, standaloneItems, pinned, ADMIN)!.items.map((i) => i.key),
    ).toEqual(['orders', 'finance'])
  })

  it('返回的合成组：key/名固定为「常用」、`items` 只含可见项且保持用户的钉序', () => {
    const g = pinnedGroup(menuGroups, standaloneItems, ['customers', 'orders'], ADMIN)
    expect(g!.key).toBe(PINNED_GROUP_KEY)
    expect(g!.name).toBe('常用')
    expect(g!.items.map((i) => i.key)).toEqual(['customers', 'orders'])
    // 🔴 合成 key **不得**与任何真实菜单组重名（否则侧边栏的 `data-group-key` 会撞车）
    expect(menuGroups.map((g2) => g2.key)).not.toContain(PINNED_GROUP_KEY)
  })
})
