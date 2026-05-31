import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'
import dayjs from 'dayjs'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/**
 * 解析后端返回的图片 URL 为可访问的绝对地址。
 *
 * 后端通常返回相对路径（如 `/api/files/static/products/xxx.png`），
 * 但前端是 Next.js 静态导出部署在 OSS / CDN 上，与后端 API 不同源，
 * 需要拼接 `NEXT_PUBLIC_API_BASE_URL` 才能访问到图片。
 *
 * 处理规则：
 * - 空值 / 非字符串：原样返回（由调用方处理空状态）
 * - data: / blob: / http(s): 协议：原样返回
 * - 以 `/` 开头的相对路径：拼接 API base URL
 * - 其他情况：原样返回
 */
export function resolveImageUrl(url?: string | null): string {
  if (!url || typeof url !== 'string') return ''
  const trimmed = url.trim()
  if (!trimmed) return ''
  // 完整 URL 直接返回
  if (/^(https?:|data:|blob:)/i.test(trimmed)) return trimmed
  // 协议相对 URL
  if (trimmed.startsWith('//')) return trimmed
  // 绝对路径（如 /api/files/static/xxx）拼接后端地址
  if (trimmed.startsWith('/')) {
    const base = (process.env.NEXT_PUBLIC_API_BASE_URL || '').replace(/\/$/, '')
    return base ? `${base}${trimmed}` : trimmed
  }
  // 裸 object key（如 products/xxx.png）拼接 OSS 域名
  const ossDomain = (process.env.NEXT_PUBLIC_OSS_DOMAIN || '').replace(/\/$/, '')
  if (ossDomain) {
    return `${ossDomain}/${trimmed}`
  }
  // 兜底：尝试用 API base URL 拼接
  const base = (process.env.NEXT_PUBLIC_API_BASE_URL || '').replace(/\/$/, '')
  return base ? `${base}/${trimmed}` : trimmed
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
