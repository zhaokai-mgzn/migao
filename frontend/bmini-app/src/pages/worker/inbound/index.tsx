/**
 * 工人**拍照入库**（issue #5052 **P3**；设计 `docs/design/inbound-photo-and-label.md` §4 / §6 / §7）
 *
 * 一条链：**拍照 → 本机解码优先（0 次 LLM）→ 识别兜底 → 工人确认 → 过账（不可逆，二次确认）
 * → 出 30×40mm 标签 → 送打印**。
 *
 * ## 为什么走 `/api/worker/**` 而不是 `/api/admin/**`
 *
 * 工人**零商家权限码**（#4727 红线）⇒ `/api/admin/**` 对工人是 401/403，而"给工人挂商家权限"
 * 这条出路是被明令禁止的。故本页与 `pages/production/index/index.tsx` 同款做**身份分流**：
 * **有工人 session ⇒ 走工人路径；没有 ⇒ 明说要去登录**（本页没有"商家面"这一支：
 * 手机上管理入库单是另一个页面 `pages/admin/inbound/index`，两者不互相顶替）。
 *
 * ## 页面上的四条"不许"
 *
 * 1. **不许**在本机解码成功时还去问模型（成本守卫，顺序钉在 `utils/inbound/recognizeFlow.ts`）；
 * 2. **不许**在不确定 / 零命中时预填（§6.4；`prefillFromRecognize` 返回空值 + 说明）；
 * 3. **不许**替工人决定过账（§6.5 + 不可逆 ⇒ `confirmAdminAction` 二次确认，且 `confirmed: true` 由工人勾选）；
 * 4. **不许**绕过服务端直接打印（§7.3；送打印只有一个入口 `printInboundLabel`，它**先调留痕**）。
 *
 * 能力缺口**动手前**说清楚：打印区在任何操作之前就先渲染 `probePrintCapability()` 的结论
 * （iOS / 非 HTTPS / 无蓝牙 / 非 h5 各有各的文案），而不是等点了打印才失败。
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import Taro from '@tarojs/taro'
import { Image, Input, ScrollView, Text, View } from '@tarojs/components'
import { confirmAdminAction } from '../../../utils/adminConfirm'
import { hasWorkerSession } from '../../../utils/workerSession'
import { decodeBarcodeFromPhoto, type PendingPhoto } from '../../../utils/inbound/barcodeDecode'
import { inboundLabelPageSize, layoutInboundLabel, type InboundLabelView } from '../../../utils/inbound/labelLayout'
import { renderInboundLabel } from '../../../utils/inbound/labelCanvas'
import {
  evaluateSkuGate,
  prefillFromRecognize,
  checkDraftInput,
  type PrefillResult,
  type SkuMatch,
} from '../../../utils/inbound/recognizeGate'
import { MAX_INBOUND_PHOTOS, runInboundRecognize } from '../../../utils/inbound/recognizeFlow'
import {
  PRINT_READY_HINT,
  printFailureText,
  probePrintCapability,
  type PrintCapability,
} from '../../../utils/inbound/printCapability'
import { printerLink, printerLinkText } from '../../../utils/inbound/printerLink'
import {
  SDK_UNAVAILABLE_HINT,
  createH5CanvasFactory,
  renderLabelPreview,
} from '../../../utils/inbound/labelPageKit'
import { printInboundLabel } from '../../../utils/inbound/labelPrint'
import { createLpapiTransport, loadLpapi } from '../../../utils/inbound/lpapiTransport'
import {
  INBOUND_PHOTO_FAILED_HINT,
  INBOUND_WORKER_LOGIN_REQUIRED,
  WORKER_LOGIN_ROUTE,
} from '../../../utils/inbound/gaps'
import {
  createInboundDraft,
  getInboundLabel,
  postInboundDraft,
  recognizeInbound,
  recordInboundLabelPrint,
  uploadInboundPhoto,
  newInboundRequestId,
} from '../../../services/workerInboundService'
import '../../../styles/admin-surfaces.scss'
import './index.scss'

/** 画布工厂 / 组件缺失文案 / 预览渲染 = **共用件**（`utils/inbound/labelPageKit`）。
 * 补打页（`pages/worker/reprint/index.tsx`）是**同族页面**，两页必须引用同一份 ——
 * 各写一份画布工厂的下场是「一边修了另一边没修」，而两边都不会报错
 * （守卫 `tests/inbound-reprint-code-space.test.ts` 的 G3）。 */

type Step = 'photo' | 'confirm' | 'label'

export default function WorkerInboundPage() {
  const workerReady = hasWorkerSession()
  const [step, setStep] = useState<Step>('photo')
  const [photos, setPhotos] = useState<PendingPhoto[]>([])
  const [notices, setNotices] = useState<string[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const [prefill, setPrefill] = useState<PrefillResult | null>(null)
  const [matches, setMatches] = useState<SkuMatch[]>([])
  const [chosenSku, setChosenSku] = useState<SkuMatch | null>(null)
  const [quantity, setQuantity] = useState('')
  const [dyeLot, setDyeLot] = useState('')
  const [supplier, setSupplier] = useState('')
  const [supplierDocNo, setSupplierDocNo] = useState('')
  const [remark, setRemark] = useState('')
  const [confirmed, setConfirmed] = useState(false)

  const [label, setLabel] = useState<InboundLabelView | null>(null)
  const [previewUrl, setPreviewUrl] = useState('')
  const [printState, setPrintState] = useState('')

  // 能力探测**在动手前**做（不是打完才失败）：h5 + 安全上下文 + 非 iOS + 有 Web Bluetooth
  const capability: PrintCapability = useMemo(() => probePrintCapability(), [])
  // 连接状态是**运行期事实**（与上面的能力探测**是两件事**）：订阅传输层每次真实交互写的状态仓。
  // 浏览器侧做不到持续真值（Web Bluetooth 权限模型不允许静默重连）⇒ 口径见 `printerLink.ts`。
  const [link, setLink] = useState(printerLink.get())
  useEffect(() => printerLink.subscribe(setLink), [])

  const onPick = useCallback(async () => {
    setError('')
    try {
      const res: any = await Taro.chooseImage({
        count: MAX_INBOUND_PHOTOS,
        sizeType: ['compressed'],
        sourceType: ['camera', 'album'],
      })
      const paths: string[] = res?.tempFilePaths || []
      const files: any[] = res?.tempFiles || []
      const picked: PendingPhoto[] = paths.map((path, index) => ({
        tempFilePath: path,
        // h5：`tempFiles[].originalFileObj` 是真 File（解码时优先用它，避免再走一次 blob URL 拉取）
        file: files[index]?.originalFileObj || path,
      }))
      if (picked.length === 0) {
        setError(INBOUND_PHOTO_FAILED_HINT)
        return
      }
      setPhotos(picked.slice(0, MAX_INBOUND_PHOTOS))
      setNotices([])
    } catch {
      setError(INBOUND_PHOTO_FAILED_HINT)
    }
  }, [])

  const onRecognize = useCallback(async () => {
    setError('')
    setBusy(true)
    try {
      const result = await runInboundRecognize({
        photos,
        decode: decodeBarcodeFromPhoto,
        upload: async (photo) => {
          const res = await uploadInboundPhoto(String(photo.tempFilePath || photo.file || ''))
          if (!res.success || !res.data?.url) throw new Error(res.message || '照片上传失败')
          return res.data.url
        },
        recognize: async (payload) => {
          const res = await recognizeInbound(payload)
          if (!res.success || !res.data) throw new Error(res.message || '识别失败')
          return res.data
        },
      })
      setNotices(result.notices.filter(Boolean))
      const next = prefillFromRecognize(result.response)
      setPrefill(next)
      setMatches(result.response.skuMatches || [])
      // 唯一命中时**预选**（仍要工人核对）；多命中/零命中都不替工人挑
      setChosenSku(next.gate.kind === 'matched' ? next.gate.match : null)
      setQuantity(next.quantity)
      setStep('confirm')
    } catch (e: any) {
      setError(e?.message || '识别失败，请重试')
    } finally {
      setBusy(false)
    }
  }, [photos])

  const onSubmit = useCallback(async () => {
    setError('')
    const input = {
      productId: chosenSku?.productId || null,
      skuId: chosenSku?.skuId ?? null,
      quantity,
      confirmed,
    }
    const check = checkDraftInput(input)
    if (!check.ok) {
      setError(check.message)
      return
    }
    // 过账**不可逆** ⇒ 二次确认（复用 #5654 的一步动作护栏；文案说清后果）
    const ok = await confirmAdminAction(
      '确认过账',
      `${prefill?.productName || chosenSku?.skuCode || '这批货'} ${quantity} 米过账后将立即加库存、生成批次号，且不可撤销`,
    )
    if (!ok) return
    setBusy(true)
    const draftRequestId = newInboundRequestId()
    try {
      const draft = await createInboundDraft(
        {
          productId: String(chosenSku?.productId || ''),
          // 🔴 雪花号 id **原样字符串**回传：Number() 会丢精度（> 2^53），服务端查不到该 SKU（issue #6340）
          skuId: String(chosenSku?.skuId),
          quantity,
          dyeLot: dyeLot || null,
          supplier: supplier || null,
          supplierDocNo: supplierDocNo || null,
          remark: remark || null,
        },
        draftRequestId,
      )
      if (!draft.success || !draft.data?.draftId) throw new Error(draft.message || '建单失败')
      const posted = await postInboundDraft(draft.data.draftId, `${draftRequestId}-post`)
      if (!posted.success || !posted.data) throw new Error(posted.message || '过账失败')
      const shortCode = posted.data.items?.[0]?.shortCode || ''
      const detail = await getInboundLabel(shortCode)
      if (!detail.success || !detail.data) throw new Error(detail.message || '读标签详情失败')
      setLabel(detail.data)
      setStep('label')
      // 出图（预览）：与送打印**同一份**绘制计划（不另写一份版面，也不各写一份画布工厂）
      const preview = renderLabelPreview(detail.data)
      setPreviewUrl(preview.url)
      if (preview.notice) setNotices((prev) => [...prev, preview.notice])
    } catch (e: any) {
      setError(e?.message || '过账失败，请重试')
    } finally {
      setBusy(false)
    }
  }, [chosenSku, quantity, confirmed, prefill, dyeLot, supplier, supplierDocNo, remark])

  const onPrint = useCallback(async () => {
    setError('')
    setPrintState('')
    const shortCode = String(label?.shortCode || '')
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
      recordPrint: async (code) => {
        const res = await recordInboundLabelPrint(code)
        if (!res.success || !res.data) throw new Error(res.message || '打印留痕失败')
        return res.data
      },
      render: () => renderInboundLabel(label as InboundLabelView, createH5CanvasFactory()),
    })
    setBusy(false)
    if (result.ok) {
      setPrintState(`已送出打印（服务端记第 ${result.printCount} 次）`)
      const refreshed = await getInboundLabel(shortCode)
      if (refreshed.success && refreshed.data) setLabel(refreshed.data)
      return
    }
    // 「记没记打印次数」是**运行期事实**（留痕在送数据之前）⇒ 由 printRecorded 决定要不要补一句，
    // 不靠静态文案对运行期下结论（issue #5052 验收 D6）
    setPrintState(printFailureText(result.hint, result.printRecorded))
  }, [label, capability])

  const gate = useMemo(() => evaluateSkuGate(matches), [matches])
  /** 纸面版心（与送打印同一份绘制计划；页面不另算一套像素） */
  const labelPlan = useMemo(() => layoutInboundLabel(label || {}), [label])

  if (!workerReady) {
    return (
      <View className='admin-surface' data-testid='worker-inbound-page'>
        <View className='admin-surface__header'>
          <Text className='admin-surface__title'>拍照入库</Text>
          <Text className='admin-surface__subtitle'>{INBOUND_WORKER_LOGIN_REQUIRED}</Text>
        </View>
        <View className='admin-surface__body'>
          <View
            className='admin-action admin-action--gold'
            data-testid='inbound-go-worker-login'
            onClick={() => Taro.navigateTo({ url: WORKER_LOGIN_ROUTE })}
          >
            <Text>去登录工人身份</Text>
          </View>
        </View>
      </View>
    )
  }

  return (
    <ScrollView scrollY className='admin-surface' data-testid='worker-inbound-page'>
      <View className='admin-surface__header'>
        <Text className='admin-surface__title'>拍照入库</Text>
        <Text className='admin-surface__subtitle'>
          拍上游标签 → 核对 → 过账（加库存）→ 打印 {inboundLabelPageSize()} 标签
        </Text>
      </View>

      <View className='admin-surface__body'>
        {error !== '' && (
          <View className='admin-notice' data-testid='inbound-error'>
            <Text className='admin-notice__text'>{error}</Text>
          </View>
        )}
        {notices.map((notice, index) => (
          <View className='admin-notice' key={`notice-${index}`} data-testid={`inbound-notice-${index}`}>
            <Text className='admin-notice__text'>{notice}</Text>
          </View>
        ))}

        {/* 🔴 打印能力缺口**动手前**就在屏上（不是打完才失败）：本机能不能打印，
            在拍照之前就说清 —— 否则工人白拍一遍、白过账一次，最后才发现这台手机打不了。 */}
        <Text className='admin-card__note' data-testid='inbound-print-capability'>
          {capability.ok ? PRINT_READY_HINT : capability.hint}
        </Text>

        {/* 连接状态（**运行期事实**）：能打 ≠ 已连上（机器可能没开机）—— 两件事分开显示 */}
        {capability.ok && (
          <Text className='admin-card__note' data-testid='inbound-printer-link'>
            {printerLinkText(link)}
          </Text>
        )}

        {step === 'photo' && (
          <View className='admin-card' data-testid='inbound-step-photo'>
            <View className='admin-action' data-testid='inbound-pick' onClick={onPick}>
              <Text>拍照 / 选图（最多 {MAX_INBOUND_PHOTOS} 张）</Text>
            </View>
            <Text className='admin-card__meta'>
              已选 {photos.length} 张 · 照片清楚、条码完整时本机直接解码，**不会**调用识别模型
            </Text>
            <View
              className={`admin-action admin-action--gold${busy || photos.length === 0 ? ' admin-action--disabled' : ''}`}
              data-testid='inbound-recognize'
              onClick={() => {
                if (busy || photos.length === 0) return
                onRecognize()
              }}
            >
              <Text>识别</Text>
            </View>
          </View>
        )}

        {step === 'confirm' && prefill && (
          <View className='admin-card' data-testid='inbound-step-confirm'>
            <Text className='admin-card__title'>
              {prefill.prefillUsed ? '识别完成，请核对' : '请手工录入（识别不确定）'}
            </Text>
            <Text className='admin-card__meta' data-testid='inbound-prefill-notice'>
              {prefill.notice}
            </Text>

            {gate.kind === 'none' && (
              <Text className='admin-card__note' data-testid='inbound-sku-gate-none'>
                {gate.message}
              </Text>
            )}
            {gate.kind === 'ambiguous' && (
              <View data-testid='inbound-sku-choices'>
                <Text className='admin-card__note'>{gate.message}</Text>
                {gate.matches.map((match) => (
                  <View
                    key={`sku-${match.skuId}`}
                    className={`admin-action${chosenSku?.skuId === match.skuId ? ' admin-action--gold' : ''}`}
                    data-testid={`inbound-sku-option-${match.skuId}`}
                    onClick={() => setChosenSku(match)}
                  >
                    <Text>
                      {match.skuCode || '未填货号'} · {match.colorName || '未填色号'}
                    </Text>
                  </View>
                ))}
              </View>
            )}

            <Text className='admin-card__meta' data-testid='inbound-chosen-sku'>
              已选货号：{chosenSku?.skuCode || '（未选，零命中时不能入库）'}
            </Text>
            <Input
              className='admin-input'
              data-testid='inbound-quantity'
              type='digit'
              placeholder='入库米数（大于 0，最多 1 位小数）'
              value={quantity}
              onInput={(e: any) => setQuantity(e?.detail?.value ?? '')}
            />
            <Input
              className='admin-input'
              data-testid='inbound-dyelot'
              placeholder='缸号（可空）'
              value={dyeLot}
              onInput={(e: any) => setDyeLot(e?.detail?.value ?? '')}
            />
            <Input
              className='admin-input'
              data-testid='inbound-supplier'
              placeholder='供应商（可空）'
              value={supplier}
              onInput={(e: any) => setSupplier(e?.detail?.value ?? '')}
            />
            <Input
              className='admin-input'
              data-testid='inbound-docno'
              placeholder='送货单号（可空）'
              value={supplierDocNo}
              onInput={(e: any) => setSupplierDocNo(e?.detail?.value ?? '')}
            />
            <Input
              className='admin-input'
              data-testid='inbound-remark'
              placeholder='备注（可空）'
              value={remark}
              onInput={(e: any) => setRemark(e?.detail?.value ?? '')}
            />
            <View
              className='admin-card__note'
              data-testid='inbound-confirm-toggle'
              onClick={() => setConfirmed(!confirmed)}
            >
              <Text>{confirmed ? '☑' : '☐'} 我确认：标签与实物一致（过账立即加库存，不可撤销）</Text>
            </View>
            <View
              className={`admin-action admin-action--gold${busy ? ' admin-action--disabled' : ''}`}
              data-testid='inbound-submit'
              onClick={() => {
                if (!busy) onSubmit()
              }}
            >
              <Text>提交过账</Text>
            </View>
          </View>
        )}

        {step === 'label' && label && (
          <View className='admin-card' data-testid='inbound-step-label'>
            <Text className='admin-card__title'>入库标签 {inboundLabelPageSize()}</Text>
            <Text className='admin-card__meta'>
              短码 {label.shortCode || '（缺失）'} · 单号 {label.inboundNo || '-'} · 已打印{' '}
              {label.printCount ?? 0} 次
            </Text>
            {previewUrl !== '' && <Image className='admin-label-preview' src={previewUrl} mode='widthFix' />}
            <View
              className={`admin-action admin-action--gold${busy || !capability.ok ? ' admin-action--disabled' : ''}`}
              data-testid='inbound-print'
              onClick={() => {
                if (busy || !capability.ok) return
                onPrint()
              }}
            >
              <Text>打印标签</Text>
            </View>
            {printState !== '' && (
              <Text className='admin-card__note' data-testid='inbound-print-state'>
                {printState}
              </Text>
            )}
            <Text className='admin-card__meta' data-testid='inbound-label-bound'>
              版心 {labelPlan.widthPx} × {labelPlan.heightPx} px（1:1 送打印）
            </Text>
          </View>
        )}
      </View>
    </ScrollView>
  )
}
