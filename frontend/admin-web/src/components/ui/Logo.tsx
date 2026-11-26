import { cn } from '@/lib/utils'
import { gold } from '@/lib/brand-palette'

const sizeMap = {
  small: { size: 28 },
  medium: { size: 36 },
  large: { size: 56 },
} as const

interface LogoProps {
  size?: keyof typeof sizeMap
  className?: string
}

/**
 * 生意管家品牌标 ——「旦」字方印。
 *
 * 为什么是「旦」：日（金圆）出地平线（金线），是「天明 / 日复一日 / 生意如日初升」。
 * 日 = 词元与每一天的经营数据；一 = 经营的地平线、管家的基座、一以贯之；
 * 方印 = 可托付。两笔，缩到 28px 仍能读，16px 下是「一点一线」。
 *
 * 视觉：深靛方印 + 织金两笔（金只从 brand-palette 取色）。
 * 旧「帘成 M」「管家铃」与五笔「生」都不再使用（用户 2026-11-24 要求简洁 / 有设计感 / 立意深远）。
 */
export default function Logo({ size = 'medium', className }: LogoProps) {
  const s = sizeMap[size]
  return (
    <svg
      width={s.size}
      height={s.size}
      viewBox="0 0 48 48"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={cn('flex-shrink-0', className)}
      aria-hidden="true"
    >
      <defs>
        <linearGradient id="logo-bg" x1="3" y1="3" x2="45" y2="45" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#48618f" />
          <stop offset="1" stopColor="#2e3d5c" />
        </linearGradient>
        <linearGradient id="logo-gold" x1="12" y1="10" x2="36" y2="38" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor={gold[300]} />
          <stop offset="100%" stopColor={gold[600]} />
        </linearGradient>
      </defs>
      <rect x="2" y="2" width="44" height="44" rx="13.5" fill="url(#logo-bg)" />
      <circle cx="24" cy="20.5" r="7.6" fill="url(#logo-gold)" />
      <path d="M10 34.5 H38" stroke="url(#logo-gold)" strokeWidth="4.2" strokeLinecap="round" />
    </svg>
  )
}
