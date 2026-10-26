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
import { buildMobileEntryUrl, getBminiH5Url } from '@/lib/bmini-h5-url'
import request from '@/lib/request'
import type { ApiResponse } from '@/types'
import { cn } from '@/lib/utils'

/** 票据端点（issue #7825）：需已登录；返回 120 秒、单次有效的二维码票据 */
const QR_TICKET_ENDPOINT = '/api/auth/qr/ticket'

/** 服务端没给有效期时的兜底秒数（与后端 `jwt.qr-login-ticket-expiration` 同量级） */
const QR_TICKET_TTL_FALLBACK = 120

/** 倒计时上屏形态：`m:ss`（票据是短窗口，秒级足够） */
function formatTicketTtl(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds))
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`
}

/**
 * 地址 + 票据 + 复制动作（只由顶栏使用）。
 *
 * 「扫码即登录」（issue #7825）：弹层打开时向服务端要一张**一次性**票据，二维码内容带 `?qr=`；
 * 手机 H5 兑换后直接拿到自己的 30 天会话（不必再输密码）。票据过期/签发失败 ⇒ 降级为**裸入口**
 * （扫码后照旧在手机上登录），不会出现「画了一张扫了没用的码」。
 *
 * 复制动作仍复制**裸地址**（不把短期凭证写进剪贴板）。
 */
function useMobileEntry() {
  const bminiH5Url = getBminiH5Url()
  const [ticket, setTicket] = useState('')
  const [remaining, setRemaining] = useState(0)
  const [ticketFailed, setTicketFailed] = useState(false)

  const issueTicket = useCallback(async () => {
    if (!bminiH5Url) return
    try {
      // ⚠️ 拦截器返回的是**后端信封本体**（`{success,data}`），而 axios 的泛型是 `AxiosResponse<T>`
      // ⇒ 这里显式转换（运行时形状由 request.ts 的 response 拦截器保证）
      type QrTicketEnvelope = ApiResponse<{ ticket: string; expiresIn: number }>
      const payload = (await request.post<QrTicketEnvelope>(
        QR_TICKET_ENDPOINT,
      )) as unknown as QrTicketEnvelope
      const value = payload?.data?.ticket || ''
      const ttl = Math.max(1, Math.round(Number(payload?.data?.expiresIn) || QR_TICKET_TTL_FALLBACK))
      setTicket(value)
      setRemaining(value ? ttl : 0)
      setTicketFailed(!value)
    } catch {
      setTicket('')
      setRemaining(0)
      setTicketFailed(true)
    }
  }, [bminiH5Url])

  // 弹层打开（组件挂载）即签发；过期自动换新，不要求用户点刷新
  useEffect(() => {
    void issueTicket()
  }, [issueTicket])

  useEffect(() => {
    if (remaining <= 0) {
      if (ticket) void issueTicket()
      return
    }
    const timer = setTimeout(() => setRemaining(value => value - 1), 1000)
    return () => clearTimeout(timer)
  }, [remaining, ticket, issueTicket])

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(bminiH5Url)
      toast.success('链接已复制')
    } catch {
      toast.error('复制失败，请手动选择链接复制')
    }
  }

  return { bminiH5Url, entryUrl: buildMobileEntryUrl(bminiH5Url, ticket), ticket, remaining, ticketFailed, copy }
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
  const { bminiH5Url, entryUrl, ticket, remaining, ticketFailed, copy } = useMobileEntry()
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
            {/* 二维码内容 = 裸地址 或 裸地址 + 一次性票据（派生点只有一个：`buildMobileEntryUrl`） */}
            <QRCodeSVG value={entryUrl} size={140} title={entryUrl} data-testid="bmini-h5-qr" />
          </div>
          <p className="mt-3 text-xs text-neutral-500">用手机相机或「扫一扫」打开：</p>
          <code className="mt-1 block break-all text-xs text-neutral-700" data-testid="bmini-h5-url">
            {bminiH5Url}
          </code>
          {ticket ? (
            <p className="mt-1 text-xs text-neutral-400" data-testid="bmini-h5-qr-ttl">
              扫码免登录 · {formatTicketTtl(remaining)} 后自动换新码
            </p>
          ) : ticketFailed ? (
            <p className="mt-1 text-xs text-neutral-400" data-testid="bmini-h5-qr-fallback">
              免登录码暂时生成失败，扫码后在手机上登录即可
            </p>
          ) : null}
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
