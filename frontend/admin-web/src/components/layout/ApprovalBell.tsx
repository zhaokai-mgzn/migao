'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import { Inbox, Stamp } from 'lucide-react'
import { approvalApi } from '@/lib/api'
import { usePermission } from '@/lib/permission'
import { APPROVAL_TYPE_LABEL } from '@/lib/approval-request'
import { displayEnum } from '@/lib/enum-display'
import { cn } from '@/lib/utils'
import type { ApprovalItem } from '@/types/approval'

/**
 * 顶栏「待审批」入口（issue #7593，用户 2026-10-24 裁定）。
 *
 * ## 它代替的是什么
 *
 * 审批中心（`/approvals`）原是侧边栏「交易管理」组下的**静态菜单项**。两处都不合适：
 *   ① 它不属于任何一个域 —— 五类业务闸门（改价 / 超授信 / 退款 / 采购超量 / 盘点差异）跨
 *      交易 / 供应链 / 仓储三域共用一块裁决屏，挂进「交易管理」让仓库的人找不到「盘点差异」；
 *   ② **静态菜单项没有信号** —— 待审 0 条和 12 条，那一行长得一模一样；审批的本质是
 *      「有人在等你」，必须带数徽标。
 *
 * ⇒ 侧边栏撤项（三源同批，`config/menu.ts` / `MenuController` / `AuthService`），改由这里承担：
 *   **图标 + 待审条数徽标 + 下拉面板（待审前 5 条 + 去审批中心）**。
 *
 * ## 边界（照实登记）
 *
 * - **面板不是裁决屏**：不在下拉里「通过 / 驳回」（裁决要看清对象与金额、写理由，那是页面的活）；
 *   面板只回答「有没有要我批的、是什么」，动手指向 `/approvals`。
 * - **徽标只数 `pending`**：「已通过但未使用」是申请人该补的动作，不是待办。
 * - **按 `finance:view` 门控**（= 页面读码 = 路由守卫码，零授权 delta）：没有该码的岗位
 *   顶栏根本不出现这个图标（常驻面克制）。
 * - 与通知铃铛**有意分成两条入口**：通知是「已读即消失」的 FYI，审批是「要动手」的待办 ——
 *   合进一个铃铛会造成「全部已读之后还有 3 条没批」。
 *
 * 交互壳（30s 轮询 + 徽标 + 下拉 + 点击外部收起）照 `NotificationBell.tsx` 的既有形态，
 * 不抽公共组件：两者面板内容与动作语义不同，抽出来的只有定位这几行 class。
 *
 * ## 已知边界（照实登记）
 *
 * 后端**没有**「待审条数」端点 ⇒ 这里复用列表接口（`GET /api/admin/approvals?status=pending`）拿全量再计数。
 * 审批条数是十位数级时这是最省的一步；**若单租户待审过百**，应改成 count 端点 + 面板按需拉前 5 条
 * （那时才会有「每 30 秒拉一次长列表」的代价）。重启条件写在这里，不靠人记得。
 */
const POLL_INTERVAL = 30_000

/** 面板只摆前 5 条（§31 P1 常驻面克制）；更多去页面。 */
const PANEL_LIMIT = 5

/** 金额上屏：`null` ⇒ 「无金额约束」（没有金额约束 ≠ 金额为零）。 */
function amountText(value: number | null | undefined): string {
  if (value === null || value === undefined) return '无金额约束'
  return `¥${Number(value).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

export default function ApprovalBell() {
  const router = useRouter()
  const { has } = usePermission()
  const canRead = has('finance:view')
  const [open, setOpen] = useState(false)
  const [pending, setPending] = useState<ApprovalItem[]>([])
  const [loaded, setLoaded] = useState(false)
  const panelRef = useRef<HTMLDivElement>(null)
  const buttonRef = useRef<HTMLButtonElement>(null)

  const fetchPending = useCallback(async () => {
    try {
      const res = await approvalApi.list({ status: 'pending' })
      setPending(res.data?.data ?? [])
    } catch {
      // 静默降级（与 `NotificationBell` 同口径）：顶栏入口不能因为一次网络抖动把整页拖垮
    } finally {
      setLoaded(true)
    }
  }, [])

  useEffect(() => {
    if (!canRead) return
    fetchPending()
    const timer = setInterval(fetchPending, POLL_INTERVAL)
    return () => clearInterval(timer)
  }, [canRead, fetchPending])

  // 点击外部收起 —— 与 `Header` 用户菜单 / `NotificationBell` 同一形态（不用全屏遮罩：
  // 顶栏带 `backdrop-blur`，遮罩的 `inset-0` 会相对顶栏盒子而不是视口，见 `Header.tsx` 的注释）
  useEffect(() => {
    if (!open) return
    function handleClickOutside(e: MouseEvent) {
      if (
        panelRef.current && !panelRef.current.contains(e.target as Node) &&
        buttonRef.current && !buttonRef.current.contains(e.target as Node)
      ) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [open])

  const goToCenter = useCallback(() => {
    setOpen(false)
    router.push('/approvals')
  }, [router])

  if (!canRead) return null

  const count = pending.length
  const shown = pending.slice(0, PANEL_LIMIT)

  return (
    <div className="relative">
      <button
        ref={buttonRef}
        type="button"
        data-testid="approval-bell"
        aria-label={count > 0 ? `待审批 ${count} 条` : '审批中心'}
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="relative rounded-lg p-2 text-neutral-500 transition-colors hover:bg-neutral-100 hover:text-neutral-700"
      >
        <Stamp className="h-5 w-5" />
        {count > 0 && (
          <span
            data-testid="approval-bell-badge"
            className="absolute -top-0.5 -right-0.5 flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-red-500 px-1 text-xs font-medium leading-none text-white"
          >
            {count > 99 ? '99+' : count}
          </span>
        )}
      </button>

      {open && (
        <div
          ref={panelRef}
          data-testid="approval-bell-panel"
          className={cn(
            'absolute right-0 top-full mt-2 w-[360px]',
            'rounded-lg border border-neutral-100 bg-white shadow-card',
            'z-50 overflow-hidden',
            'animate-in fade-in slide-in-from-top-2 duration-200',
          )}
        >
          <div className="flex items-center justify-between border-b border-neutral-100 px-4 py-3">
            <h3 className="text-sm font-semibold text-neutral-900">待审批</h3>
            {count > 0 && <span className="text-xs text-neutral-500">{count} 条</span>}
          </div>

          <div className="max-h-[320px] overflow-y-auto">
            {!loaded ? (
              <div className="flex items-center justify-center py-10">
                <div className="h-5 w-5 animate-spin rounded-full border-2 border-primary-200 border-t-primary-600" />
              </div>
            ) : shown.length === 0 ? (
              <div data-testid="approval-bell-empty" className="flex flex-col items-center justify-center py-10 text-neutral-400">
                <Inbox className="mb-2 h-10 w-10 stroke-[1.5]" />
                <p className="text-sm">没有待审批的单据</p>
              </div>
            ) : (
              shown.map(item => (
                <div
                  key={item.id}
                  data-testid="approval-bell-item"
                  className="border-b border-neutral-100 px-4 py-3 last:border-b-0"
                >
                  <p className="truncate text-sm font-medium text-neutral-900">
                    {displayEnum(APPROVAL_TYPE_LABEL, item.objectType)} · {item.objectLabel || item.objectRef}
                  </p>
                  <p className="mt-0.5 truncate text-xs text-neutral-500">
                    {amountText(item.amount)} · {item.requestedByName || '—'}
                  </p>
                </div>
              ))
            )}
          </div>

          <div className="flex items-center justify-end border-t border-neutral-100 bg-neutral-50/50 px-4 py-2.5">
            <button
              type="button"
              data-testid="approval-bell-viewall"
              onClick={goToCenter}
              className="text-xs font-medium text-primary-600 transition-colors hover:text-primary-700"
            >
              去审批中心 →
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
