'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import { Search } from 'lucide-react'
import { useAuthStore } from '@/store/auth'
import { cn } from '@/lib/utils'
import { menuGroups, standaloneItems } from '@/config/menu'
import { resolveMenuIcon } from '@/config/menu-icons'
import {
  filterMenuItems,
  visibleMenuGroups,
  flattenMenu,
  searchMenu,
  type FlatMenuItem,
} from '@/lib/menu-nav'
import { briefingApi } from '@/lib/api'

interface CommandPaletteProps {
  open: boolean
  onClose: () => void
}

/**
 * 菜单命令面板（⌘K / Ctrl+K，issue #5271）。
 *
 * ## 为什么需要它
 *
 * 重设计前侧边栏 21 项**全部平铺**、没有任何检索入口 ⇒ 找菜单只能靠眼扫 + 滚动
 * （`nav` 还带 `maxHeight: calc(100vh - 7rem)`）。本面板把「找入口」变成一次键入。
 *
 * ## 口径
 *
 *   · 命中面 = 菜单名 ∪ 组名 ∪ `menu.ts` 的 `keywords`（拼音首字母 / 常见叫法），
 *     排序规则见 `@/lib/menu-nav` 的 `searchMenu`（纯函数，有穷举判据）；
 *   · **只列当前用户有权访问的项**（复用侧边栏同一套过滤纯函数）—— 搜索不是绕过权限的口子；
 *   · 空查询时**列出全部可访问项**（不是空白页）：移动端抽屉收起时它就是一份完整菜单索引；
 *   · 键盘：↑/↓ 选择、Enter 跳转、Esc 关闭；点击遮罩关闭。
 *
 * ## 边界（如实登记）
 *
 *   不做模糊匹配 / 拼音全拼切分（无依赖可用，且 `keywords` 已覆盖常用别名）；
 *   不做「最近访问」排序（需要持久化，本轮不做）。
 */
export default function CommandPalette({ open, onClose }: CommandPaletteProps) {
  const router = useRouter()
  const { user } = useAuthStore()
  const [query, setQuery] = useState('')
  const [highlight, setHighlight] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)

  // 简报开关与侧边栏同一口径（开关关了就不该在搜索结果里冒出来）
  const [briefingEnabled, setBriefingEnabled] = useState(false)
  useEffect(() => {
    if (!open) return
    briefingApi.getConfig()
      .then((res) => setBriefingEnabled(!!res.data.data?.enabled))
      .catch(() => setBriefingEnabled(false))
  }, [open])

  const items = useMemo<FlatMenuItem[]>(() => {
    const opts = { permissions: user?.permissions || [], roles: user?.roles, briefingEnabled }
    return flattenMenu(
      visibleMenuGroups(menuGroups, opts),
      filterMenuItems(standaloneItems, opts),
    )
  }, [user?.permissions, user?.roles, briefingEnabled])

  // 空查询 = 全量索引（移动端就是靠这个当菜单用）
  const results = useMemo(
    () => (query.trim() ? searchMenu(items, query) : items),
    [items, query],
  )

  // 查询变化 ⇒ 高亮归零（否则会停在越界/错位的下标上）
  useEffect(() => {
    setHighlight(0)
  }, [query])

  // 打开时聚焦输入框、清空上次查询
  useEffect(() => {
    if (!open) return
    setQuery('')
    setHighlight(0)
    // 打开后立刻聚焦（jsdom 下 autoFocus 不总生效，显式调一次；失败也不影响功能）
    const t = setTimeout(() => inputRef.current?.focus(), 0)
    return () => clearTimeout(t)
  }, [open])

  if (!open) return null

  const go = (path: string) => {
    onClose()
    router.push(path)
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setHighlight((h) => (results.length === 0 ? 0 : (h + 1) % results.length))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setHighlight((h) => (results.length === 0 ? 0 : (h - 1 + results.length) % results.length))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      const target = results[highlight]
      if (target) go(target.path)
    } else if (e.key === 'Escape') {
      e.preventDefault()
      onClose()
    }
  }

  return (
    <div className="fixed inset-0 z-[60]" role="dialog" aria-modal="true" aria-label="搜索菜单">
      {/* 遮罩 */}
      <div
        data-testid="command-palette-mask"
        className="absolute inset-0 bg-black/45"
        onClick={onClose}
      />

      <div
        data-testid="command-palette"
        className="absolute left-1/2 top-24 w-[92vw] max-w-lg -translate-x-1/2 overflow-hidden rounded-2xl bg-white shadow-modal"
      >
        {/* 输入区 */}
        <div className="flex items-center gap-2 border-b border-neutral-200 px-4 py-3">
          <Search className="h-4 w-4 flex-shrink-0 text-neutral-400" />
          <input
            ref={inputRef}
            aria-label="搜索菜单"
            data-testid="command-palette-input"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="搜索菜单 / 功能…"
            className="flex-1 bg-transparent text-sm text-neutral-900 outline-none placeholder:text-neutral-400"
          />
          <kbd className="rounded border border-neutral-200 px-1.5 py-0.5 text-[10px] text-neutral-400">ESC</kbd>
        </div>

        {/* 结果区 */}
        <ul className="max-h-80 overflow-y-auto py-1">
          {results.map((item, i) => {
            const Icon = resolveMenuIcon(item.icon)
            const active = i === highlight
            return (
              <li key={item.key}>
                <button
                  type="button"
                  data-testid={`command-palette-item-${item.key}`}
                  onMouseEnter={() => setHighlight(i)}
                  onClick={() => go(item.path)}
                  className={cn(
                    'flex w-full items-center gap-3 px-4 py-2 text-left text-sm transition-colors',
                    active ? 'bg-primary-50 text-primary-700' : 'text-neutral-700 hover:bg-neutral-50',
                  )}
                >
                  <Icon className="h-4 w-4 flex-shrink-0 text-neutral-400" />
                  <span className="flex-1 truncate">{item.name}</span>
                  {item.groupName && (
                    <span className="flex-shrink-0 text-xs text-neutral-400">{item.groupName}</span>
                  )}
                </button>
              </li>
            )
          })}
          {results.length === 0 && (
            <li className="px-4 py-6 text-center text-sm text-neutral-400">
              没有匹配的菜单
            </li>
          )}
        </ul>
      </div>
    </div>
  )
}