import { cn } from '@/lib/utils'

const sizeMap = {
  small: { size: 28 },
  medium: { size: 36 },
  large: { size: 56 },
} as const

interface LogoProps {
  size?: keyof typeof sizeMap
  className?: string
}

/** 米高品牌 Logo — "M" 几何字母标 */
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
    >
      <defs>
        <linearGradient id="logo-grad" x1="0" y1="0" x2="48" y2="48" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#4F6EF7" />
          <stop offset="100%" stopColor="#3B52CC" />
        </linearGradient>
      </defs>
      {/* 圆角底板 */}
      <rect x="2" y="2" width="44" height="44" rx="12" fill="url(#logo-grad)" />
      {/* M 字母 — 双斜线笔画 */}
      <path
        d="M12 34V20L20 28L24 20L28 28L36 20V34"
        stroke="white"
        strokeWidth="3.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />
      {/* 顶部高光点 */}
      <circle cx="24" cy="10" r="2" fill="white" fillOpacity="0.4" />
    </svg>
  )
}
