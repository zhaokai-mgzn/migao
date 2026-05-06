import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'
import dayjs from 'dayjs'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

const WEEKDAY_NAMES = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']

/**
 * 智能时间格式化（用于会话列表等场景）
 * - 今天：HH:mm
 * - 昨天：昨天 HH:mm
 * - 本周内（7天内）：周X HH:mm
 * - 今年内：M月D日 HH:mm
 * - 跨年：YYYY年M月D日 HH:mm
 */
export function formatChatTime(dateStr: string | undefined | null): string {
  if (!dateStr) return '暂无'
  const normalized = dateStr.replace('+00:00Z', 'Z')
  const d = dayjs(normalized)
  if (!d.isValid()) return '暂无'

  const now = dayjs()
  const time = d.format('HH:mm')

  if (d.isSame(now, 'day')) {
    return time
  }
  if (d.isSame(now.subtract(1, 'day'), 'day')) {
    return `昨天 ${time}`
  }
  // 7天内
  const diffDays = now.startOf('day').diff(d.startOf('day'), 'day')
  if (diffDays < 7) {
    return `${WEEKDAY_NAMES[d.day()]} ${time}`
  }
  if (d.isSame(now, 'year')) {
    return `${d.month() + 1}月${d.date()}日 ${time}`
  }
  return `${d.year()}年${d.month() + 1}月${d.date()}日 ${time}`
}

/**
 * 完整日期时间格式化（用于详情面板）
 * 始终显示：YYYY年M月D日 HH:mm
 */
export function formatFullDateTime(dateStr: string | undefined | null): string {
  if (!dateStr) return '暂无'
  const normalized = dateStr.replace('+00:00Z', 'Z')
  const d = dayjs(normalized)
  if (!d.isValid()) return '暂无'
  return `${d.year()}年${d.month() + 1}月${d.date()}日 ${d.format('HH:mm')}`
}
