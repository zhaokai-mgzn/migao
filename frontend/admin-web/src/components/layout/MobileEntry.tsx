'use client'

/**
 * 手机端入口（issue #7198；原落位 issue #5668）—— B 端 h5 的扫码入口。
 *
 * ## 为什么在**顶栏**（不是一个配置域里的一个区块）
 *
 * 扫码是**跨设备交接的工具**：人坐在 PC 前，想把系统搬到手机上。它不回答
 * 「这家店长什么样、谁能进来」（那是「企业信息」域的问题，见
 * `docs/design/enterprise-settings-redesign.md` §2），所以不该埋在配置域里 ——
 * 改前要「企业基础设置 → 企业信息域 → 滚过名称/Logo」3~4 步才见得到，而扫码是个 30 秒的动作。
 *
 * ## 形态（§31 P1 常驻面克制）
 *
 * 顶栏常驻面只多**一个图标**（`< lg` 不显示 —— 手机自己扫自己没意义）；二维码**点开才画**，
 * 弹层要点外部才收起。**全站只有这一处入口**（issue #7212：设置页「企业信息」域里那一行也移除 ——
 * 用户逐字「这块直接移除吧，已经迁移到右上角了」）。
 *
 * ## 判据（别把这里读成"文档承诺"）
 *
 * - 单一真值：地址仍只经 `@/lib/bmini-h5-url` 的 `getBminiH5Url()` 取（组件里不硬编码域名）；
 * - 缺配置不画假码：`bminiH5Url` 为空 ⇒ 真分支里没有 `QRCodeSVG`，只给一句「未配置」；
 * - 守卫：`tests/unit_ci_workflows/test_frontend_bmini_entry_single_source.py`（判据 3/4 的判据对象已随本单指向本文件）。
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { Smartphone } from 'lucide-react'
import { QRCodeSVG } from 'qrcode.react'
import { toast } from 'sonner'
import { Button } from '@/components/ui'
import { getBminiH5Url } from '@/lib/bmini-h5-url'
import { cn } from '@/lib/utils'

/** 地址 + 复制动作（只由顶栏使用；复制失败不抛未捕获异常 —— jsdom / 非安全上下文没有 clipboard）。 */
function useMobileEntry() {
  const bminiH5Url = getBminiH5Url()
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(bminiH5Url)
      toast.success('链接已复制')
    } catch {
      toast.error('复制失败，请手动选择链接复制')
    }
  }
  return { bminiH5Url, copy }
}

/** 点击外部收起（与 `NotificationBell` / `Header` 用户菜单同一形态；`backdrop-filter` 下不能用全屏遮罩）。 */
function useClickOutside(open: boolean, close: () => void) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    function onMouseDown(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) close()
    }
    document.addEventListener('mousedown', onMouseDown)
    return () => document.removeEventListener('mousedown', onMouseDown)
  }, [open, close])
  return ref
}

/**
 * 二维码面板 —— **全站唯一的渲染处**（只由顶栏弹层使用）。
 * 结构层判据（单源守卫）读的就是这段三元：有值才画码，无值只说「未配置」。
 */
export function MobileEntryPanel({ className }: { className?: string }) {
  const { bminiH5Url, copy } = useMobileEntry()
  return (
    <div
      className={cn(
        'w-[280px] rounded-lg border border-neutral-200 bg-white p-4 shadow-card-hover',
        className,
      )}
    >
      {bminiH5Url ? (
        <div>
          <div className="flex justify-center rounded-lg border border-neutral-200 p-2">
            <QRCodeSVG value={bminiH5Url} size={140} title={bminiH5Url} data-testid="bmini-h5-qr" />
          </div>
          <p className="mt-3 text-xs text-neutral-500">用手机相机或「扫一扫」打开：</p>
          <code className="mt-1 block break-all text-xs text-neutral-700" data-testid="bmini-h5-url">
            {bminiH5Url}
          </code>
          <Button variant="secondary" size="sm" className="mt-3 w-full" onClick={copy}>
            复制链接
          </Button>
        </div>
      ) : (
        <p className="text-sm text-neutral-500" data-testid="bmini-h5-unconfigured">
          手机端入口未配置 —— 尚未开通手机版，需要开通时请联系服务方；开通后这里会出现扫码入口。
        </p>
      )}
    </div>
  )
}

/** 顶栏主入口：一个图标按钮 + 按需弹层（`< lg` 隐藏：手机扫自己的码没有意义）。 */
export default function MobileEntryHeader() {
  const [open, setOpen] = useState(false)
  const close = useCallback(() => setOpen(false), [])
  const ref = useClickOutside(open, close)
  return (
    <div className="relative hidden lg:block" ref={ref}>
      <button
        type="button"
        aria-label="手机端入口"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 rounded-lg p-2 text-neutral-500 transition-colors hover:bg-neutral-100 hover:text-neutral-700"
      >
        <Smartphone className="h-5 w-5" />
        <span className="hidden text-sm xl:block">手机端</span>
      </button>
      {open && <MobileEntryPanel className="absolute right-0 top-full z-50 mt-2" />}
    </div>
  )
}
