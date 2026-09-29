/**
 * 工人**拍照补打入库标签**（issue #5640 功能②；设计 `docs/design/inbound-photo-and-label.md` §5.2 / §6 / §7.1 / §7.3）
 *
 * 一条链：**拍照（或手输短码）→ 码空间判定 → 读单据详情 → 补打一张新标签**。
 *
 * ## 为什么需要这一页（业务场景）
 *
 * 标签**贴丢了 / 磨花了 / 贴错了**是仓库高频事故，而今天补打必须回到电脑端管理后台找到那张单再点打印
 * ⇒ 工人（人就在货架旁、手里只有手机）**没有补打路径**。本页把那条路径补上，
 * 且**首次打印与补打走同一条链**（不新造第二条）。
 *
 * ## 页面上的六条「不许」
 *
 * 1. **不许**在码空间判定之前查入库详情（`/s/` 洗水码是**报工**的码，查入库只会 404 ⇒ 把人引向"是不是抄错了"）；
 * 2. **不许**在客户端把抄错的短码（`O`/`I`/`L`）按严格字母表拦下（归一化在服务端，拦下=工人抄对了也没用）；
 * 3. **不许**把 404 与 410 说成同一句话（撤销是业务动作、不存在多半是抄错码，处置完全不同）；
 * 4. **不许**绕过服务端直接打印（§7.3；送打印只有一个入口 `printInboundLabel`，它**先调留痕接口**）；
 * 5. **不许**展示端侧拼出来的字段（字段真值只从 `GET /api/worker/inbound/labels/{短码}` 来）；
 * 6. **不许**猜单 / 预填（解不出码 ⇒ 明确提示重拍 + 手输，本单的链路里**没有**识别模型这一支）。
 *
 * 打印能力缺口**动手前**说清楚（照 P3 范式）：本机能不能打印在**拍照之前**就上屏，
 * 而不是等工人拍完、查到单、点了打印才失败。
 *
 * 版面 / 渲染 / 打印三件**一件都不在本页**：`layoutInboundLabel` / `renderInboundLabel` /
 * `printInboundLabel` 全部从 `utils/inbound/**` 复用（含画布工厂与其他页面共用的 `labelPageKit`）
 * —— 同族页面各写一套必然分叉，判据见 `tests/inbound-reprint-code-space.test.ts` 的 G3。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Taro, { useDidShow } from '@tarojs/taro'
import { Image, Input, ScrollView, Text, View } from '@tarojs/components'
import { hasWorkerSession } from '../../../utils/workerSession'
import {
  decodeBarcodeFromPhoto,
  type PendingPhoto,
} from '../../../utils/inbound/barcodeDecode'
import { classifyManualCode, type LabelCodeReading } from '../../../utils/inbound/codeSpace'
import { layoutInboundLabel, inboundLabelPageSize, type InboundLabelView } from '../../../utils/inbound/labelLayout'
import { renderInboundLabel } from '../../../utils/inbound/labelCanvas'
import {
  SDK_UNAVAILABLE_HINT,
  createH5CanvasFactory,
  renderLabelPreview,
} from '../../../utils/inbound/labelPageKit'
import { printInboundLabel } from '../../../utils/inbound/labelPrint'
import { createLpapiTransport, loadLpapi } from '../../../utils/inbound/lpapiTransport'
import {
  PRINT_READY_HINT,
  printFailureText,
  probePrintCapability,
  type PrintCapability,
} from '../../../utils/inbound/printCapability'
import { printerLink, printerLinkText } from '../../../utils/inbound/printerLink'
import {
  MANUAL_CODE_PLACEHOLDER,
  type LabelCodeSpace,
} from '../../../utils/inbound/codeSpace'
import {
  loadReprintDetail,
  runReprintResolve,
  type ReprintDetailState,
} from '../../../utils/inbound/reprintFlow'
import {
  INBOUND_PHOTO_FAILED_HINT,
  REPRINT_WORKER_LOGIN_REQUIRED,
  WORKER_LOGIN_ROUTE,
} from '../../../utils/inbound/gaps'
import {
  classifyLandingCode,
  landingCodeFromParams,
  type LandingCode,
} from '../../../utils/inbound/deepLink'
import { getInboundLabel, recordInboundLabelPrint } from '../../../services/workerInboundService'
import '../../../styles/admin-surfaces.scss'
import './index.scss'

type Step = 'photo' | 'manual' | 'detail'

/** 非入库码的空间（页面据此显示「为什么不能补打」—— 每一种各有各的出路） */
const BLOCKED_TEST_IDS: Record<LabelCodeSpace, string> = {
  'inbound-label': '',
  'wash-code': 'reprint-wash-code',
  foreign: 'reprint-foreign',
  'invalid-input': 'reprint-manual-invalid',
  undecoded: 'reprint-undecoded',
}

export default function WorkerReprintPage() {
  const workerReady = hasWorkerSession()
  const [step, setStep] = useState<Step>('photo')
  const [photo, setPhoto] = useState<PendingPhoto | null>(null)
  const [manualCode, setManualCode] = useState('')
  const [notices, setNotices] = useState<string[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [reading, setReading] = useState<LabelCodeReading | null>(null)
  const [detailState, setDetailState] = useState<ReprintDetailState | null>(null)
  const [label, setLabel] = useState<InboundLabelView | null>(null)
  const [previewUrl, setPreviewUrl] = useState('')
  const [printState, setPrintState] = useState('')

  // 能力探测**在动手前**做（照 P3：iOS / 非 HTTPS / 无蓝牙 / 非 h5 各有各的文案）
  const capability: PrintCapability = useMemo(() => probePrintCapability(), [])
  // 连接状态是**运行期事实**（与能力探测**是两件事**）：订阅传输层每次真实交互写的状态仓
  const [link, setLink] = useState(printerLink.get())
  useEffect(() => printerLink.subscribe(setLink), [])

  const onPick = useCallback(async () => {
    setError('')
    try {
      const res: any = await Taro.chooseImage({
        count: 1,
        sizeType: ['compressed'],
        sourceType: ['camera', 'album'],
      })
      const path: string = (res?.tempFilePaths || [])[0] || ''
      // h5：`tempFiles[].originalFileObj` 是真 File（解码时优先用它，省一次 blob 拉取）
      const file = (res?.tempFiles || [])[0]?.originalFileObj || path
      if (!file) {
        setError(INBOUND_PHOTO_FAILED_HINT)
        return
      }
      setPhoto({ tempFilePath: path || null, file })
      setNotices([])
      setReading(null)
      setDetailState(null)
    } catch {
      setError(INBOUND_PHOTO_FAILED_HINT)
    }
  }, [])

  /**
   * 读详情（**唯一**入口）：码空间门禁在 `loadReprintDetail` 里 —— 洗水码 / 陌生码 / 形态不合法
   * 到这一步就停（一次请求都不发），`kind: 'blocked'` 由页面按空间显示各自的说明。
   */
  const lookup = useCallback(async (next: LabelCodeReading) => {
    setBusy(true)
    try {
      const state = await loadReprintDetail({ reading: next, lookup: (code) => getInboundLabel(code) })
      setDetailState(state)
      if (state.kind !== 'ready') return
      setLabel(state.view)
      // 预览与送打印**同一份**绘制计划（同族共用件；画不出来时它会给一句明说）
      const preview = renderLabelPreview(state.view)
      setPreviewUrl(preview.url)
      if (preview.notice) setNotices((prev) => [...prev, preview.notice])
      setStep('detail')
    } finally {
      setBusy(false)
    }
  }, [])

  // ── 落地页深链 / 小程序页面参数（issue #5052 实现 PR；设计 §5.4）──
  // `/b/?code=<短码>` 由 `src/app.tsx`（h5 落地）搬进来，或由**小程序页面参数**带进来 ——
  // 两侧都落在 `router.params.code`，**共用下面这一处判定**（不各写一套分流）。
  const landing = useMemo<LandingCode>(
    () => landingCodeFromParams((Taro.getCurrentInstance() as any)?.router?.params),
    [],
  )
  const landingConsumed = useRef(false)

  /**
   * 消费深链（**至多一次**）。
   *
   * 🔴 未登录 ⇒ **不消费**（码就地留着，登录回来再消费）：直接查会拿 401，
   * 而工人看到的是"读取失败"，与"码不存在 / 已撤销"混在一起 = 把身份问题说成业务问题。
   * 登录回来（`navigateBack` 重挂 / `useDidShow`）时 `hasWorkerSession()` 变真 ⇒ 自动接着消费。
   */
  const consumeLanding = useCallback(() => {
    if (landingConsumed.current || !landing.present) return
    if (!hasWorkerSession()) return
    landingConsumed.current = true
    const next = classifyLandingCode(landing.raw)
    setReading(next)
    void lookup(next)
  }, [landing, lookup])

  useEffect(() => {
    consumeLanding()
  }, [consumeLanding])
  // weapp 的页面栈返回时组件可能不重挂 ⇒ 再挂一次 `useDidShow`（h5 侧是 no-op 语义）
  useDidShow(() => {
    consumeLanding()
  })

  const onRecognize = useCallback(async () => {
    if (!photo) {
      setError(INBOUND_PHOTO_FAILED_HINT)
      return
    }
    setError('')
    setDetailState(null)
    setBusy(true)
    try {
      const result = await runReprintResolve({ photo, decode: decodeBarcodeFromPhoto })
      setNotices(result.notices.filter(Boolean))
      setReading(result.reading)
      await lookup(result.reading)
    } catch (e: any) {
      setError(e?.message || '照片处理失败，请重试')
    } finally {
      setBusy(false)
    }
  }, [photo, lookup])

  const onSubmitManual = useCallback(async () => {
    setError('')
    setNotices([])
    setDetailState(null)
    const next = classifyManualCode(manualCode)
    setReading(next)
    // 形态不合法时 `lookup` 内部也是 blocked（结构上不发请求），走同一条路免得两处分叉
    await lookup(next)
  }, [manualCode, lookup])

  const onPrint = useCallback(async () => {
    setError('')
    setPrintState('')
    const shortCode = String(label?.shortCode || '').trim()
    if (!shortCode) {
      setError('这张标签没有短码，不能打印（可回电脑端补打）。')
      return
    }
    setBusy(true)
    const lpapi = await loadLpapi()
    if (!lpapi) {
      setBusy(false)
      setPrintState(SDK_UNAVAILABLE_HINT)
      return
    }
    const result = await printInboundLabel({
      shortCode,
      capability,
      transport: createLpapiTransport({ lpapi }),
      // 先留痕（计数原子自增 + 审计），成功了才送数据给打印机
      recordPrint: async (code) => {
        const res = await recordInboundLabelPrint(code)
        if (!res.success || !res.data) throw new Error(res.message || '打印留痕失败')
        return res.data
      },
      render: () => renderInboundLabel(label as InboundLabelView, createH5CanvasFactory()),
    })
    setBusy(false)
    if (result.ok) {
      // 计数**原样转发**服务端回执（前端不 +1、不累加）
      setPrintState(`已送出打印（服务端记第 ${result.printCount} 次）`)
      const refreshed = await getInboundLabel(shortCode)
      if (refreshed.success && refreshed.data) setLabel(refreshed.data)
      return
    }
    // 同上（入库页）：失败文案 = 静态 hint + 运行期事实（本次是否已记一次）
    setPrintState(printFailureText(result.hint, result.printRecorded))
  }, [label, capability])

  /** 纸面版心（与送打印同一份绘制计划；页面不另算一套像素） */
  const labelPlan = useMemo(() => layoutInboundLabel(label || {}), [label])
  const blockedTestId = reading ? BLOCKED_TEST_IDS[reading.space] : ''

  if (!workerReady) {
    return (
      <View className='admin-surface' data-testid='worker-reprint-page'>
        <View className='admin-surface__header'>
          <Text className='admin-surface__title'>拍照补打标签</Text>
          <Text className='admin-surface__subtitle' data-testid='reprint-worker-login-required'>
            {REPRINT_WORKER_LOGIN_REQUIRED}
          </Text>
        </View>
        <View className='admin-surface__body'>
          <View
            className='admin-action admin-action--gold'
            data-testid='reprint-go-worker-login'
            onClick={() => Taro.navigateTo({ url: WORKER_LOGIN_ROUTE })}
          >
            <Text>去登录工人身份</Text>
          </View>
        </View>
      </View>
    )
  }

  return (
    <ScrollView scrollY className='admin-surface' data-testid='worker-reprint-page'>
      <View className='admin-surface__header'>
        <Text className='admin-surface__title'>拍照补打标签</Text>
        <Text className='admin-surface__subtitle'>
          拍米高入库标签（或手输 8 位短码）→ 看单据详情 → 补打一张新标签
        </Text>
      </View>

      <View className='admin-surface__body'>
        {error !== '' && (
          <View className='admin-notice' data-testid='reprint-error'>
            <Text className='admin-notice__text'>{error}</Text>
          </View>
        )}
        {notices.map((notice, index) => (
          <View className='admin-notice' key={`notice-${index}`} data-testid={`reprint-notice-${index}`}>
            <Text className='admin-notice__text'>{notice}</Text>
          </View>
        ))}

        {/* 🔴 打印能力缺口**动手前**就在屏上（不是打完才失败）：本机能不能打印，在拍照之前就说清 */}
        <Text className='admin-card__note' data-testid='reprint-print-capability'>
          {capability.ok ? PRINT_READY_HINT : capability.hint}
        </Text>

        {/* 连接状态（**运行期事实**）：能打 ≠ 已连上（机器可能没开机）—— 两件事分开显示 */}
        {capability.ok && (
          <Text className='admin-card__note' data-testid='reprint-printer-link'>
            {printerLinkText(link)}
          </Text>
        )}

        {step === 'photo' && (
          <View className='admin-card' data-testid='reprint-step-photo'>
            <View className='admin-action' data-testid='reprint-pick' onClick={onPick}>
              <Text>拍照（对着标签上的二维码）</Text>
            </View>
            <Text className='admin-card__meta'>
              照片清楚时本机直接解码（**不会**调用识别模型）；标签磨花解不出来也没关系 —— 可以手输短码
            </Text>
            <View
              className={`admin-action admin-action--gold${busy || !photo ? ' admin-action--disabled' : ''}`}
              data-testid='reprint-recognize'
              onClick={() => {
                if (busy || !photo) return
                onRecognize()
              }}
            >
              <Text>识别这张照片</Text>
            </View>
            <View className='admin-action' data-testid='reprint-to-manual' onClick={() => setStep('manual')}>
              <Text>标签磨花了？手输短码</Text>
            </View>
          </View>
        )}

        {step === 'manual' && (
          <View className='admin-card' data-testid='reprint-step-manual'>
            <Text className='admin-card__title'>手输标签上的 8 位短码</Text>
            <Input
              className='admin-input'
              data-testid='reprint-manual-code'
              placeholder={MANUAL_CODE_PLACEHOLDER}
              value={manualCode}
              onInput={(e: any) => setManualCode(e?.detail?.value ?? '')}
            />
            <Text className='admin-card__meta'>
              照抄纸面即可：抄成字母 O / I / L 也没关系（系统按 0 / 1 处理）
            </Text>
            <View
              className={`admin-action admin-action--gold${busy ? ' admin-action--disabled' : ''}`}
              data-testid='reprint-manual-submit'
              onClick={() => {
                if (!busy) onSubmitManual()
              }}
            >
              <Text>查询这张标签</Text>
            </View>
            <View className='admin-action' data-testid='reprint-to-photo' onClick={() => setStep('photo')}>
              <Text>回去拍照</Text>
            </View>
          </View>
        )}

        {/* 非入库码：每一种空间各自一句可行动的话（洗水码另给报工入口） */}
        {reading && blockedTestId !== '' && (
          <View className='admin-card' data-testid={blockedTestId}>
            <Text className='admin-card__note'>{reading.message}</Text>
            {reading.action && (
              <View
                className='admin-action admin-action--gold'
                data-testid='reprint-go-report'
                onClick={() => Taro.navigateTo({ url: (reading.action as { route: string }).route })}
              >
                <Text>{reading.action.label}</Text>
              </View>
            )}
          </View>
        )}

        {detailState?.kind === 'not-found' && (
          <View className='admin-card' data-testid='reprint-not-found'>
            <Text className='admin-card__note'>{detailState.message}</Text>
            <View className='admin-action' data-testid='reprint-back-to-manual' onClick={() => setStep('manual')}>
              <Text>重新输入短码</Text>
            </View>
          </View>
        )}

        {detailState?.kind === 'revoked' && (
          <View className='admin-card' data-testid='reprint-revoked'>
            <Text className='admin-card__note'>{detailState.message}</Text>
          </View>
        )}

        {detailState?.kind === 'error' && (
          <View className='admin-card' data-testid='reprint-detail-error'>
            <Text className='admin-card__note'>{detailState.message}</Text>
          </View>
        )}

        {step === 'detail' && label && (
          <View className='admin-card' data-testid='reprint-step-detail'>
            <Text className='admin-card__title'>入库标签 {inboundLabelPageSize()}</Text>
            <Text className='admin-card__meta'>
              短码 {label.shortCode || '（缺失）'} · 单号 {label.inboundNo || '-'} · 已打印{' '}
              {label.printCount ?? 0} 次
            </Text>
            <Text className='admin-card__meta' data-testid='reprint-detail-fields'>
              {label.productName || '未填品名'} · 色号 {label.colorName || '-'}
              {label.doorWidth ? ` / ${label.doorWidth}` : ''} · 米数 {label.quantity ?? '-'} · 货号{' '}
              {label.skuCode || '-'} · 缸号 {label.dyeLot || '-'}
            </Text>
            <Text className='admin-card__meta'>
              批次 {label.batchNo || '-'} · 供应商 {label.supplier || '-'} · 入库{' '}
              {label.inboundDate || '-'}
            </Text>
            {previewUrl !== '' && <Image className='admin-label-preview' src={previewUrl} mode='widthFix' />}
            <View
              className={`admin-action admin-action--gold${busy || !capability.ok ? ' admin-action--disabled' : ''}`}
              data-testid='reprint-print'
              onClick={() => {
                if (busy || !capability.ok) return
                onPrint()
              }}
            >
              <Text>打印新标签</Text>
            </View>
            {printState !== '' && (
              <Text className='admin-card__note' data-testid='reprint-print-state'>
                {printState}
              </Text>
            )}
            <Text className='admin-card__meta' data-testid='reprint-label-bound'>
              版心 {labelPlan.widthPx} × {labelPlan.heightPx} px（1:1 送打印）
            </Text>
          </View>
        )}
      </View>
    </ScrollView>
  )
}
