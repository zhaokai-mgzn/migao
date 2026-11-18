'use client'

import dayjs from 'dayjs'

interface DateTimeCellProps {
  value?: string | null
  /**
   * 单行模式（2026-11-11 用户口径，issue #8897）：`YYYY-MM-DD HH:mm` 放在同一个行内元素里、
   * `whitespace-nowrap` 不换行。**只给明确要求单行的面用**（如订单详情「商品信息」的时间）；
   * 默认仍是列表页的两行版式（第一行日期、第二行时分）。
   */
  inline?: boolean
}

/**
 * DateTimeCell — 统一的日期时间展示组件。
 *
 * 业务要求（#1399）：所有列表页「创建时间」展示格式一致。
 * 默认 2 行展示：第一行 YYYY-MM-DD，第二行 HH:mm。
 * 2026-11-11（issue #8897）：可选 `inline` 单行模式（订单详情「商品信息」的时间一行展示不换行）。
 *
 * 注意：验证使用原生 Date（而非 dayjs.isValid），
 * 避免测试中 dayjs mock 缺失 isValid 方法导致运行时错误。
 */
export default function DateTimeCell({ value, inline = false }: DateTimeCellProps) {
  if (!value) {
    return <span className="text-neutral-400 text-sm">-</span>
  }

  // 用原生 Date 做合法性检查，兼容测试 mock
  const native = new Date(value)
  if (isNaN(native.getTime())) {
    return <span className="text-neutral-400 text-sm">{value}</span>
  }

  const d = dayjs(value)
  const date = d.format('YYYY-MM-DD')
  const time = d.format('HH:mm')

  if (inline) {
    return (
      <span className="whitespace-nowrap text-sm text-neutral-600">
        {date} {time}
      </span>
    )
  }

  return (
    <div className="text-sm text-neutral-600 leading-snug whitespace-nowrap">
      <div>{date}</div>
      <div className="text-neutral-400">{time}</div>
    </div>
  )
}
