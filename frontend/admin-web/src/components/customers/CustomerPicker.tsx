'use client'

// ============================================================
// 客户选择器（公共件，issue #7622）
// ============================================================
// 用户 2026-10-24 逐字：「允许选择客户，有通用组件」—— 起因是价格本有两处让人**手打客户 id**：
// 「只看这个客户（可选）」筛选，与协议价的「客户 id」录入。客户 id 是内部标识（雪花号字符串），
// 拿它当人能填的东西交给商家，既不可能也不该发生（#5904 同族：内部标识只能选、不能抄）。
//
// 交互：**搜姓名 / 手机号 → 选中 → 收成一个可读结论**（展示名 + 手机号），可一键清除。
// 选中回传 `{ id, label, phone }`：调用方拿得到展示名，列表里不必再印内部 id；
// 展示名口径 = `customerDisplayName()`（与下单页「选择客户」弹窗同一套字段优先级，缺名给「未命名客户」）。
//
// 🔴 一条「失败 ≠ 空态」的纪律（#6691 同族）：搜索失败 ⇒ 说「没读到数据」+ 重试按钮，
// **不许**显示「没有匹配的客户」—— 后者是**数据事实**，拿读故障冒充它会让人去客户管理白找一遍。
//
// 判据：tests/unit/components/CustomerPicker.test.tsx（会红）
// 消费面：价格本（协议价 + 「只看这个客户」筛选）

import { useCallback, useEffect, useState } from 'react'
import { Search, X } from 'lucide-react'
import { customerApi } from '@/lib/api'
import { FIELD_CONTROL } from '@/components/ui/FormPanel'
import { cn } from '@/lib/utils'
import type { Customer } from '@/types'

/** 选中结果：id 给接口用，label/phone 给界面用（不回查、不当第二份口径） */
export interface CustomerChoice {
  id: string
  /** 展示名（**不**是内部 id） */
  label: string
  phone?: string
}

/** 派生：客户的展示名 —— 后端三种姓名字段都可能缺，缺名给「未命名客户」而不是空白。 */
export function customerDisplayName(
  customer: Pick<Customer, 'wechatNickname' | 'name' | 'nickname'>,
): string {
  return customer.wechatNickname || customer.name || customer.nickname || '未命名客户'
}

interface CustomerPickerProps {
  /** 已选客户（受控）：组件不存影子状态，值住在调用方 */
  value: CustomerChoice | null
  onChange: (choice: CustomerChoice | null) => void
  placeholder?: string
  /** testid 前缀：`<prefix>-input` / `-option-<id>` / `-selected` / `-clear` / `-error` / `-empty` */
  testIdPrefix?: string
  className?: string
}

export default function CustomerPicker({
  value,
  onChange,
  placeholder = '搜索客户姓名 / 手机号',
  testIdPrefix = 'customer-picker',
  className,
}: CustomerPickerProps) {
  const [keyword, setKeyword] = useState('')
  const [options, setOptions] = useState<Customer[]>([])
  const [loading, setLoading] = useState(false)
  /** 读故障：与「没有匹配的客户」空态**互斥**（#6691） */
  const [failed, setFailed] = useState(false)
  /** 展开态：聚焦 / 输入即展开；选中、Esc、失焦即收起 */
  const [open, setOpen] = useState(false)

  const search = useCallback(async (text: string) => {
    setLoading(true)
    try {
      const res = await customerApi.getCustomers({ keyword: text.trim() || undefined, page: 1, size: 20 })
      setOptions(res.data?.data?.items ?? [])
      setFailed(false)
    } catch {
      // 拦截器已 toast；这里只标失败态（列表保持不清零 —— 故障不冒充「搜不到」）
      setFailed(true)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (!open) return
    // 防抖只服务于「边打边搜」：停手 300ms 才打一次接口
    const timer = setTimeout(() => void search(keyword), 300)
    return () => clearTimeout(timer)
  }, [open, keyword, search])

  const pick = (customer: Customer) => {
    onChange({ id: customer.id, label: customerDisplayName(customer), phone: customer.phone || undefined })
    setKeyword('')
    setOptions([])
    setOpen(false)
  }

  // 已选：收成一个可读的结论（展示名 + 手机号），右侧一键清除
  if (value) {
    return (
      <div
        data-testid={`${testIdPrefix}-selected`}
        className={cn(
          'flex h-9 items-center gap-2 rounded-lg border border-neutral-200 bg-neutral-50 px-3 text-sm',
          className,
        )}
      >
        <span className="min-w-0 flex-1 truncate text-neutral-800">{value.label}</span>
        {value.phone ? (
          <span className="shrink-0 text-xs tabular-nums text-neutral-500">{value.phone}</span>
        ) : null}
        <button
          type="button"
          aria-label="清除所选客户"
          data-testid={`${testIdPrefix}-clear`}
          className="shrink-0 rounded p-0.5 text-neutral-400 transition-colors hover:text-neutral-700"
          onClick={() => onChange(null)}
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
    )
  }

  return (
    <div className={cn('relative', className)}>
      <Search
        className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-neutral-400"
        aria-hidden
      />
      <input
        data-testid={`${testIdPrefix}-input`}
        aria-label={placeholder}
        className={cn(FIELD_CONTROL, 'pl-9')}
        value={keyword}
        placeholder={placeholder}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onChange={(e) => {
          setKeyword(e.target.value)
          setOpen(true)
        }}
        onKeyDown={(e) => {
          if (e.key === 'Escape') setOpen(false)
        }}
      />
      {open ? (
        <div
          data-testid={`${testIdPrefix}-options`}
          // 🔴 点结果时**不能让输入框先失焦**（失焦即关列表 ⇒ 点击落空）
          onMouseDown={(e) => e.preventDefault()}
          className="absolute z-20 mt-1 max-h-56 w-full overflow-auto rounded-lg border border-neutral-200 bg-white shadow-card"
        >
          {failed ? (
            <div role="alert" data-testid={`${testIdPrefix}-error`} className="px-3 py-4 text-sm text-neutral-600">
              客户搜索失败 —— 没读到数据，请检查网络后重试
              <button
                type="button"
                data-testid={`${testIdPrefix}-retry`}
                className="ml-2 text-primary-600 underline"
                onClick={() => void search(keyword)}
              >
                重试
              </button>
            </div>
          ) : loading && options.length === 0 ? (
            <div className="px-3 py-4 text-sm text-neutral-400">加载中…</div>
          ) : options.length === 0 ? (
            <div data-testid={`${testIdPrefix}-empty`} className="px-3 py-4 text-sm text-neutral-400">
              {keyword.trim() ? '没有匹配的客户 —— 换个姓名或手机号试试' : '暂无可选客户'}
            </div>
          ) : (
            options.map((customer) => (
              <button
                key={customer.id}
                type="button"
                data-testid={`${testIdPrefix}-option-${customer.id}`}
                onClick={() => pick(customer)}
                className="flex w-full items-center gap-2 border-b border-neutral-100 px-3 py-2 text-left text-sm last:border-0 hover:bg-neutral-50"
              >
                <span className="min-w-0 flex-1 truncate text-neutral-800">{customerDisplayName(customer)}</span>
                {customer.phone ? (
                  <span className="shrink-0 text-xs tabular-nums text-neutral-500">{customer.phone}</span>
                ) : null}
              </button>
            ))
          )}
        </div>
      ) : null}
    </div>
  )
}
