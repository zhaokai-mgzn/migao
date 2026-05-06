import Image from 'next/image'
import { cn } from '@/lib/utils'

const sizeMap = {
  small: { container: 'w-7 h-7', image: 28 },
  medium: { container: 'w-9 h-9', image: 36 },
  large: { container: 'w-14 h-14', image: 56 },
} as const

interface LogoProps {
  size?: keyof typeof sizeMap
  className?: string
}

export default function Logo({ size = 'medium', className }: LogoProps) {
  const s = sizeMap[size]
  return (
    <div className={cn(s.container, 'flex-shrink-0', className)}>
      <Image
        src="/logo.svg"
        alt="有客"
        width={s.image}
        height={s.image}
        className="w-full h-full"
        priority
      />
    </div>
  )
}
