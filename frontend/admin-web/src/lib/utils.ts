import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'
import dayjs from 'dayjs'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/**
 * 解析后端返回的图片 URL 为可访问的绝对地址。
 *
 * 历史上 OSS_URL_PREFIX 在不同环境使用了不同的域名（CDN / 旧 bucket），
 * 导致 DB 中存储的图片 URL 域名可能与当前实际 OSS 域名不一致。
 *
 * 处理规则（NEXT_PUBLIC_OSS_DOMAIN 为唯一基准域名）：
 * - 空值 / 非字符串：返回空字符串
 * - data: / blob: 协议：原样返回
 * - http(s) URL：域名不匹配 OSS 域名时，提取 path 用 OSS 域名重建
 * - 以 `/` 开头的绝对路径：拼接 API base URL
 * - 裸 object key（如 products/xxx.png）：拼接 OSS 域名
 */
export function resolveImageUrl(url?: string | null): string {
  if (!url || typeof url !== 'string') return ''
  const trimmed = url.trim()
  if (!trimmed) return ''

  const ossDomain = (process.env.NEXT_PUBLIC_OSS_DOMAIN || '').replace(/\/$/, '')

  // data: / blob: 协议原样返回
  if (/^(data:|blob:)/i.test(trimmed)) return trimmed

  // http(s) URL：规范化到当前 OSS 域名（处理历史遗留的各种域名）
  if (/^https?:/i.test(trimmed)) {
    if (ossDomain && !trimmed.startsWith(ossDomain + '/')) {
      try {
        const parsed = new URL(trimmed)
        const path = parsed.pathname.replace(/^\//, '')
        if (path) return `${ossDomain}/${path}${parsed.search}`
      } catch (e) { /* URL 解析失败则原样返回 */ }
    }
    return trimmed
  }

  // 协议相对 URL
  if (trimmed.startsWith('//')) return trimmed
  // 绝对路径（如 /api/files/static/xxx）拼接后端地址
  if (trimmed.startsWith('/')) {
    const base = (process.env.NEXT_PUBLIC_API_BASE_URL || '').replace(/\/$/, '')
    return base ? `${base}${trimmed}` : trimmed
  }
  // 裸 object key（如 products/xxx.png）拼接 OSS 域名
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
