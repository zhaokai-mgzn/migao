'use client'

import { cn } from '@/lib/utils'
import { Loader2 } from 'lucide-react'
import { ButtonHTMLAttributes, ReactNode, forwardRef } from 'react'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'danger' | 'ghost'
  size?: 'sm' | 'md' | 'lg'
  loading?: boolean
  /**
   * 前置图标（**统一入口**，issue #7184）。
   *
   * 🔴 为什么必须有这个 slot：改前图标靠调用方手写 `<Icon className="mr-1.5" />` 塞进 children ——
   * 于是同一层级的按钮各自长出自己的间距（`mr-1` / `mr-1.5` / `mr-2` / 没有），
   * 用户 2026-10-18 四张截图里「同一动作层级三种形态」有一半来自这里。
   *
   * 🔴 语义：`loading` 时 spinner **顶替** icon（**不是并排**）。并排 = 双图标 —— 真机被读成
   * 「图标重叠」（issue #7180 同族观感）。
   *
   * 图标本身按 **16px** 传（`w-4 h-4`）；slot 给 `mr-1.5` 与 `shrink-0`，图标不参与收缩。
   */
  icon?: ReactNode
}

const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = 'primary', size = 'md', loading, icon, children, disabled, ...props }, ref) => {
    // 🔴 `whitespace-nowrap`（issue #5558）：按钮在 flex 行里是**可收缩项**，没有它时 min-content
    // = **一个汉字** ⇒ 空间紧张时（长说明段 / `w-full` 的 Input·Select 同一行）会被压到 ~1 字宽，
    // 标签在固定 `h-9` 的盒子里换行 —— 用户实测「入库单页按钮样式不对」（查询/重置竖排）。
    // 同批把基类拉齐：`Badge` / `StatusBadge` 早就有这一条，只有 Button 漏了（三个原语里的异类）。
    const baseStyles = 'inline-flex items-center justify-center whitespace-nowrap rounded-lg font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed'

    const variants = {
      primary: 'bg-primary-600 text-white shadow-sm hover:bg-primary-700 active:bg-primary-800',
      secondary: 'bg-white text-neutral-700 border border-neutral-300 hover:bg-neutral-50 active:bg-neutral-100',      danger: 'bg-white text-red-600 border border-red-600 hover:bg-red-50 active:bg-red-100',
      ghost: 'bg-transparent text-neutral-600 hover:bg-neutral-100 hover:text-neutral-900',
    }

    const sizes = {
      sm: 'h-8 px-3 text-sm',
      md: 'h-9 px-4 text-sm',
      lg: 'h-10 px-6 text-base',
    }

    return (
      <button
        ref={ref}
        className={cn(baseStyles, variants[variant], sizes[size], className)}
        disabled={disabled || loading}
        aria-busy={loading || undefined}
        {...props}
      >
        {/* loading ⇒ spinner **顶替** icon（不并排，issue #7184）；无 loading ⇒ 走 icon slot */}
        {loading ? (
          <Loader2 className="w-4 h-4 mr-2 animate-spin" aria-hidden />
        ) : (
          icon && (
            <span className="mr-1.5 inline-flex shrink-0 items-center" aria-hidden>
              {icon}
            </span>
          )
        )}
        {children}
      </button>
    )
  }
)

Button.displayName = 'Button'

export default Button
