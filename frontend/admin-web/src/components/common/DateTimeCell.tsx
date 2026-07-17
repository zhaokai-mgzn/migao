'use client'

import dayjs from 'dayjs'

interface DateTimeCellProps {
  value?: string | null
}

/**
 * DateTimeCell — 统一的日期时间展示组件。
 *
 * 业务要求（#1399）：所有列表页「创建时间」展示格式一致。
 * 默认 2 行展示：第一行 YYYY-MM-DD，第二行 HH:mm。
 *
 * 注意：验证使用原生 Date（而非 dayjs.isValid），
 * 避免测试中 dayjs mock 缺失 isValid 方法导致运行时错误。
 */
export default function DateTimeCell({ value }: DateTimeCellProps) {
  if (!value) {
    return <span className="text-gray-400 text-sm">-</span>
  }

  // 用原生 Date 做合法性检查，兼容测试 mock
  const native = new Date(value)
  if (isNaN(native.getTime())) {
    return <span className="text-gray-400 text-sm">{value}</span>
  }

  const d = dayjs(value)
  const date = d.format('YYYY-MM-DD')
  const time = d.format('HH:mm')

  return (
    <div className="text-sm text-gray-600 leading-snug whitespace-nowrap">
      <div>{date}</div>
      <div className="text-gray-400">{time}</div>
    </div>
  )
}
