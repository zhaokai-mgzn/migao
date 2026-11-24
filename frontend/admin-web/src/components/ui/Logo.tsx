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
 * 生意管家品牌标 ——「管家铃」。
 *
 * 语义（不是字面画「管家」）：铃 = 随叫随到的服务；底座 = 经营台面；
 * 右上角星芒 = 词元 / AI 的底座。深靛方印承接企业级稳重感，织金铃身只在 token 里取色。
 * 16px 下保留铃身 + 底座 + 顶钮，去掉高光与星芒（见 public/favicon.svg）。
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
        <linearGradient id="logo-gold" x1="16" y1="17" x2="34" y2="35" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor={gold[300]} />
          <stop offset="100%" stopColor={gold[600]} />
        </linearGradient>
      </defs>
      <rect x="2" y="2" width="44" height="44" rx="13.5" fill="url(#logo-bg)" />
      <path
        d="M13.4 33.2 C13.4 25.4 16.9 19.8 24 19.8 C31.1 19.8 34.6 25.4 34.6 33.2 Z"
        fill="url(#logo-gold)"
      />
      <path
        d="M16.9 30.6 C17.3 24.6 19.8 21.4 23.2 20.4"
        stroke="#faf7f2"
        strokeOpacity="0.55"
        strokeWidth="1.2"
        strokeLinecap="round"
      />
      <circle cx="24" cy="17.2" r="2.3" fill={gold[300]} />
      <rect x="11" y="34" width="26" height="3.2" rx="1.6" fill="#faf7f2" />
      <path
        d="M36.2 11.4 C36.6 13.6 37.9 14.9 40.1 15.3 C37.9 15.7 36.6 17 36.2 19.2 C35.8 17 34.5 15.7 32.3 15.3 C34.5 14.9 35.8 13.6 36.2 11.4 Z"
        fill={gold[300]}
      />
    </svg>
  )
}
