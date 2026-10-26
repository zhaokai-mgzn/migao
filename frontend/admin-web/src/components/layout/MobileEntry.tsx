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
type TicketPhase = 'loading' | 'ready' | 'failed'

/**
 * 取票失败后的**自动重试**节奏（毫秒）：1.5s → 4s → 10s → 10s…
 *
 * 为什么必须有（issue #7834 现场）：发布滚动窗口内 admin-api 会短暂 502，前端原来**只试一次**
 * ⇒ 弹层被永久钉在「免登录码暂时生成失败」，用户只能扫到那张**没有票据**的码，
 * 于是「扫码后还是要登录」。有节奏的重试能把这种**瞬时**失败自动吃掉。
 */
const QR_TICKET_RETRY_DELAYS = [1500, 4000, 10000]

/** 自动重试封顶次数（约 1 分钟）：之后停下，避免后台无休止打后端；用户仍可点「重试」 */
const QR_TICKET_MAX_ATTEMPTS = 6

/** 取票 + 状态机（issue #7825 首版 / #7834 加固）。 */
function useMobileEntry() {
  const bminiH5Url = getBminiH5Url()
  const [ticket, setTicket] = useState('')
  const [remaining, setRemaining] = useState(0)
  // 🔴 三态而不是布尔（issue #7834）：`loading` 期间**不画码** —— 否则弹层刚出现的那 ~300ms 里
  //    画的是**裸入口**，手快的人扫到的正是「要登录」的那张（首版就踩了这个）。
  const [phase, setPhase] = useState<TicketPhase>('loading')
  const [attempts, setAttempts] = useState(0)
  /** 失败原因读数（`status=502` / `status=network` …）：只进 console 与 DOM 的 data-diag，不上屏 */
  const [diag, setDiag] = useState('')

  const issueTicket = useCallback(async () => {
    if (!bminiH5Url) {
      setPhase('failed')
      setDiag('unconfigured')
      return
    }
    setAttempts(value => value + 1)
    setPhase(prev => (prev === 'ready' ? prev : 'loading'))
    try {
      // 🔴 解包口径（issue #7837 事故）：请求实例的响应拦截器返回的是 **AxiosResponse**，
      //   不是后端信封本体 —— 本仓惯例是 `res.data.data`（见 store/auth.ts 的 refreshToken）。
      //   首版读成 `res.data.ticket`（漏了一层）⇒ 恒 undefined ⇒ 每次都判「生成失败」，
      //   而请求其实是 **200**（现场症状：弹层立刻显示失败、没有任何网络错误提示）。
      type QrTicketEnvelope = ApiResponse<{ ticket: string; expiresIn: number }>
      const response = await request.post<QrTicketEnvelope>(QR_TICKET_ENDPOINT)
      const payload = response?.data
      const value = payload?.data?.ticket || ''
      if (!value) throw Object.assign(new Error('empty ticket'), { status: 200 })
      const ttl = Math.max(1, Math.round(Number(payload?.data?.expiresIn) || QR_TICKET_TTL_FALLBACK))
      setTicket(value)
      setRemaining(ttl)
      setPhase('ready')
      setDiag('')
    } catch (error: unknown) {
      const err = error as { response?: { status?: number }; statusCode?: number; message?: string }
      const status = Number(err?.response?.status || err?.statusCode || 0)
      const reason = `status=${status || 'network'}`
      setTicket('')
      setRemaining(0)
      setPhase('failed')
      setDiag(reason)
      // 归因读数（不打扰用户）：线上排障从 console 或 fallback 节点的 data-diag 直接读
      // eslint-disable-next-line no-console
      console.warn('[qr-ticket] 免登录码签发失败', reason, err?.message || '')
    }
  }, [bminiH5Url])

  // 弹层打开（组件挂载）即签发
  useEffect(() => {
    void issueTicket()
  }, [issueTicket])

  // 失败自动重试（issue #7834）：按节奏退避，封顶 QR_TICKET_MAX_ATTEMPTS 次
  useEffect(() => {
    if (phase !== 'failed' || attempts >= QR_TICKET_MAX_ATTEMPTS) return
    const delay = QR_TICKET_RETRY_DELAYS[Math.min(attempts - 1, QR_TICKET_RETRY_DELAYS.length - 1)]
    const timer = setTimeout(() => {
      void issueTicket()
    }, delay)
    return () => clearTimeout(timer)
  }, [phase, attempts, issueTicket])

  // 票据到期自动换新（成功态才计时）
  useEffect(() => {
    if (phase !== 'ready') return
    if (remaining <= 0) {
      void issueTicket()
      return
    }
    const timer = setTimeout(() => setRemaining(value => value - 1), 1000)
    return () => clearTimeout(timer)
  }, [phase, remaining, issueTicket])

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(bminiH5Url)
      toast.success('链接已复制')
    } catch {
      toast.error('复制失败，请手动选择链接复制')
    }
  }

  return {
    bminiH5Url,
    entryUrl: buildMobileEntryUrl(bminiH5Url, ticket),
    ticket,
    remaining,
    phase,
    diag,
    copy,
    retry: issueTicket,
  }
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
  const { bminiH5Url, entryUrl, phase, remaining, diag, copy, retry } = useMobileEntry()
  return (
    <div
      className={cn(
        'w-[280px] rounded-lg border border-neutral-200 bg-white p-4 shadow-card-hover',
        className,
      )}
    >
      {bminiH5Url ? (
        <div>
          {phase === 'loading' ? (
            // 取票中**不画码**（issue #7834）：画裸码 = 让用户扫到一张「要登录」的码
            <div
              className="flex h-[156px] items-center justify-center rounded-lg border border-dashed border-neutral-200 text-xs text-neutral-400"
              data-testid="bmini-h5-qr-loading"
            >
              正在生成免登录码…
            </div>
          ) : (
            <div className="flex justify-center rounded-lg border border-neutral-200 p-2">
              {/* 二维码内容 = 裸地址 或 裸地址 + 一次性票据（派生点只有一个：`buildMobileEntryUrl`） */}
              <QRCodeSVG value={entryUrl} size={140} title={entryUrl} data-testid="bmini-h5-qr" />
            </div>
          )}
          <p className="mt-3 text-xs text-neutral-500">用手机相机或「扫一扫」打开：</p>
          <code className="mt-1 block break-all text-xs text-neutral-700" data-testid="bmini-h5-url">
            {bminiH5Url}
          </code>
          {phase === 'ready' ? (
            <p className="mt-1 text-xs text-neutral-400" data-testid="bmini-h5-qr-ttl">
              扫码免登录 · {formatTicketTtl(remaining)} 后自动换新码
            </p>
          ) : phase === 'failed' ? (
            <div className="mt-1 flex items-start gap-2" data-testid="bmini-h5-qr-fallback" data-diag={diag}>
              <p className="flex-1 text-xs text-neutral-400">
                免登录码暂时生成失败
                {/* 诊断码（issue #7836）：只给排障用（用户截图即可定位），不替代主文案 */}
                {diag ? <span className="ml-1 text-neutral-300">（{diag}）</span> : null}
                ，扫码后在手机上登录即可
              </p>
              <button
                type="button"
                className="shrink-0 text-xs text-amber-600 hover:underline"
                onClick={() => void retry()}
              >
                重试
              </button>
            </div>
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
