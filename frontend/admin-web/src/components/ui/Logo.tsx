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

/** 米高品牌 Logo — 帘成 M：织金暖底 + 窗帘杆 + 垂帘 M + 波浪底摆 */
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
        <linearGradient id="logo-grad" x1="2" y1="2" x2="46" y2="46" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#FFC53D" />
          <stop offset="100%" stopColor="#D48806" />
        </linearGradient>
      </defs>
      {/* 织金暖底 */}
      <rect x="2" y="2" width="44" height="44" rx="13.5" fill="url(#logo-grad)" />
      {/* 窗帘杆 + 吊环 */}
      <rect x="11" y="8.6" width="26" height="2.4" rx="1.2" fill="white" fillOpacity="0.35" />
      <circle cx="12.8" cy="9.8" r="1.8" stroke="white" strokeOpacity="0.55" strokeWidth="1.1" fill="none" />
      <circle cx="35.2" cy="9.8" r="1.8" stroke="white" strokeOpacity="0.55" strokeWidth="1.1" fill="none" />
      {/* 垂帘 M — 波浪底摆如窗帘下缘 */}
      <path
        fill="white"
        d="M10.8 31.8 L10.8 15.8 Q10.8 13.6 13 13.6 L18.2 13.6 L21.6 27.2 L24 13.6 L26.4 27.2 L29.8 13.6 L35 13.6 Q37.2 13.6 37.2 15.8 L37.2 31.8 C35.2 33.4 32.8 29.8 30.2 30.4 C27.6 31 25.6 33.4 23 32.8 C20.4 32.2 18 29.8 15.2 30.4 C13 30.8 11.6 31.6 10.8 31.8 Z"
      />
    </svg>
  )
}
