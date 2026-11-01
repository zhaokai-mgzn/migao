/**
 * 工人**拍照入库**（issue #5052 **P3**；设计 `docs/design/inbound-photo-and-label.md` §4 / §6 / §7）
 *
 * 一条链：**拍照 → 本机解码优先（0 次 LLM）→ 识别兜底 → 工人确认 → 过账（不可逆，二次确认）
 * → 出 50×80mm 标签 → 送打印**。
 *
 * ## 为什么走 `/api/worker/**` 而不是 `/api/admin/**`
 *
 * 工人**零商家权限码**（#4727 红线）⇒ `/api/admin/**` 对工人是 401/403，而"给工人挂商家权限"
 * 这条出路是被明令禁止的。故本页做**身份分流**（同款形态的报工页 `pages/production/index/index.tsx`
 * 已于 2026-10-14 随 issue #6868 实现包 D1 下架；本页与工人首页是这套形态的现役载体）：
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
 * 5. **不许**让拦截/失败只出现在页面顶部（issue #7822）：端侧闸不通过 / 服务端拒绝 ⇒ 文案渲染在
 *    「提交过账」**正上方**（`inbound-submit-blocked`），顶部横幅只留拍照 / 识别 / 搜索这类与提交无关的
 *    失败 —— 长表单 / 小屏 / 软键盘弹起时顶部横幅在视口之外，工人读到的是**「点了没反应」**（线上实测：
 *    按钮 top=588 在屏内、横幅 top=-170 在屏外，且一个请求都没发）。
 *
 * ## 两格数字：**卷数** × **卷长**（issue #6812）
 *
 * 「数量」= **卷数**（默认 `1`）、「卷长」= **每卷米数**，入库米数 = 两者之乘 —— 这个乘法的
 * **真值在服务端**：端侧只把两格照原样提交（`quantity` + `rollLengthM`），**不换算、不校验数值口径**
 * （卷数正整数 / 卷长上限 / 米数粒度全由服务端判，400/422 文案原样上屏）。
 * 识别到的 `quantityMeters` 现在落在**卷长**那格（见 `utils/inbound/recognizeGate.ts`）。
 *
 * 能力缺口**动手前**说清楚：打印区在任何操作之前就先渲染 `probePrintCapability()` 的结论
 * （iOS / 非 HTTPS / 无蓝牙 / 非 h5 各有各的文案），而不是等点了打印才失败。
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import Taro from '@tarojs/taro'
import { Image, Input, ScrollView, Text, View } from '@tarojs/components'
import { confirmActionResult } from '../../../utils/adminConfirm'
import { hasWorkerSession } from '../../../utils/workerSession'
import { decodeBarcodeFromPhoto, type PendingPhoto } from '../../../utils/inbound/barcodeDecode'
import { inboundLabelPageSize, layoutInboundLabel, type InboundLabelView } from '../../../utils/inbound/labelLayout'
import { renderInboundLabel } from '../../../utils/inbound/labelCanvas'
import {
  evaluateSkuGate,
  prefillFromRecognize,
  recognizedFieldRows,
  checkDraftInput,
  type PrefillResult,
  type RecognizeLike,
  type SkuMatch,
} from '../../../utils/inbound/recognizeGate'
import { MAX_INBOUND_PHOTOS, runInboundRecognize } from '../../../utils/inbound/recognizeFlow'
import {
  INBOUND_DECODE_TIMEOUT_HINT,
  INBOUND_DECODE_TIMEOUT_MS,
  INBOUND_PROGRESS_DECODE,
  INBOUND_PROGRESS_RECOGNIZE,
  INBOUND_PROGRESS_UPLOAD,
  INBOUND_RECOGNIZE_TIMEOUT_HINT,
  INBOUND_RECOGNIZE_TIMEOUT_MS,
  INBOUND_UPLOAD_TIMEOUT_HINT,
  INBOUND_UPLOAD_TIMEOUT_MS,
  withTimeout,
} from '../../../utils/inbound/withTimeout'
import {
  SUGGEST_DEBOUNCE_MS,
  SUGGEST_SHOW_LIMIT,
  SUGGEST_TOO_SHORT_HINT,
  canSuggest,
  createSuggestRunner,
  suggestHint,
  suggestQueryOf,
} from '../../../utils/inbound/skuSuggest'
import {
  PRINT_READY_HINT,
  printFailureText,
  probePrintCapability,
  type PrintCapability,
} from '../../../utils/inbound/printCapability'
import { printerLink, printerLinkText } from '../../../utils/inbound/printerLink'
import { showsPrinterLinkHint } from '../../../utils/inbound/terminalTransport'
import {
  SDK_UNAVAILABLE_HINT,
  createH5CanvasFactory,
  renderLabelPreview,
} from '../../../utils/inbound/labelPageKit'
import { printInboundLabel } from '../../../utils/inbound/labelPrint'
import { createPrintTransport } from '../../../utils/inbound/terminalTransport'
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
  searchInboundSkus,
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

/**
 * 模糊搜索下拉的状态（issue #7892）。
 *
 * `q` = 这批候选**属于哪个查询** —— 输入框里的词变了，旧候选就不许再上屏（后发先至的端侧一刀）。
 * `hint` = 面板下面那句话（也兼作「搜索中…」的状态位，不再多一个 loading 开关）。
 */
interface SuggestView {
  q: string
  rows: SkuMatch[]
  hint: string
}

export default function WorkerInboundPage() {
  const workerReady = hasWorkerSession()
  const [step, setStep] = useState<Step>('photo')
  const [photos, setPhotos] = useState<PendingPhoto[]>([])
  const [notices, setNotices] = useState<string[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  /** 识别链的**分步进度**（issue #8307）：三步各自封顶后，屏上还得说清「现在在做哪一步」，
   *  否则慢的时候工人只看到一个灰按钮，无法判断是卡住还是在跑。 */
  const [progress, setProgress] = useState('')
  /** 提交链的失败/拦截文案 —— **就地**渲染在「提交过账」正上方（issue #7822：顶部横幅在长表单里
   * 会被折到视口外，工人看到的是「点了没反应」）。与 `busy` 分开：提交期间要单独给「提交中…」。 */
  const [submitError, setSubmitError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const [prefill, setPrefill] = useState<PrefillResult | null>(null)
  // 识别回执**原样**留一份：逐格结果（`fields`）由它派生，不在端侧重建字段表
  const [recognized, setRecognized] = useState<RecognizeLike | null>(null)
  const [matches, setMatches] = useState<SkuMatch[]>([])
  const [chosenSku, setChosenSku] = useState<SkuMatch | null>(null)
  // 零命中时的**只读**货号搜索（issue #7759：原来这里没有出口，文案却叫工人「从已有商品里选」）
  // issue #7892：不是「点按钮再在整宽列表里找」，而是**边输边出候选、点一条即选中**（用户裁定）
  const [searchQuery, setSearchQuery] = useState('')
  const [suggest, setSuggest] = useState<SuggestView>({ q: '', rows: [], hint: '' })
  const [quantity, setQuantity] = useState('1')
  const [rollLengthM, setRollLengthM] = useState('')
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
        decode: async (photo) => {
          setProgress(INBOUND_PROGRESS_DECODE)
          return withTimeout(decodeBarcodeFromPhoto(photo), INBOUND_DECODE_TIMEOUT_MS, INBOUND_DECODE_TIMEOUT_HINT)
        },
        upload: async (photo) => {
          setProgress(INBOUND_PROGRESS_UPLOAD)
          const res = await withTimeout(
            uploadInboundPhoto(String(photo.tempFilePath || photo.file || '')),
            INBOUND_UPLOAD_TIMEOUT_MS,
            INBOUND_UPLOAD_TIMEOUT_HINT,
          )
          if (!res.success || !res.data?.url) throw new Error(res.message || '照片上传失败')
          return res.data.url
        },
        recognize: async (payload) => {
          setProgress(INBOUND_PROGRESS_RECOGNIZE)
          const res = await withTimeout(recognizeInbound(payload), INBOUND_RECOGNIZE_TIMEOUT_MS, INBOUND_RECOGNIZE_TIMEOUT_HINT)
          if (!res.success || !res.data) throw new Error(res.message || '识别失败')
          return res.data
        },
      })
      // 🔴 识别链**不上屏过程叙述**（issue #7818）：解码没命中而服务端认回来了是正常路径。
      //    「要不要人工核对」由确认卡说清（`prefillFromRecognize().notice`），这里不接横幅。
      const next = prefillFromRecognize(result.response)
      setPrefill(next)
      setRecognized(result.response)
      setMatches(result.response.skuMatches || [])
      setSearchQuery('')
      setSuggest({ q: '', rows: [], hint: '' })
      // 唯一命中时**预选**（仍要工人核对）；多命中/零命中都不替工人挑
      setChosenSku(next.gate.kind === 'matched' ? next.gate.match : null)
      setQuantity(next.quantity)
      setRollLengthM(next.rollLengthM)
      setStep('confirm')
    } catch (e: any) {
      setError(e?.message || '识别失败，请重试')
    } finally {
      setBusy(false)
      setProgress('')
    }
  }, [photos])

  /**
   * 零命中时按**货号 / 色名**搜已有货号（issue #7759 的出口；**只读**，不改存货）。
   *
   * 用户 2026-10-27 裁定（issue #7892）：要能「通过输入模糊搜索下拉框来选中」—— 于是这里从
   * 「输入 + 点按钮」改成**边输边出候选**。搜索词仍由工人自己给（不拿识别结果替他去猜），
   * 三条端侧口径（最小长度 / 防抖 / 后发先至）的唯一实现 = `utils/inbound/skuSuggest`。
   */
  const runSuggest = useMemo(
    () =>
      createSuggestRunner(async (query) => {
        const res = await searchInboundSkus(query)
        if (!res.success) return { ok: false as const, message: res.message || '搜索没成功，请重试' }
        return { ok: true as const, matches: Array.isArray(res.data) ? res.data : [] }
      }),
    [],
  )

  /** 停手 300ms 才查（每敲一个字就查 = 一次输入 6 个请求）；`alive` = 这一次输入还有没有人要 */
  useEffect(() => {
    const query = suggestQueryOf(searchQuery)
    if (!canSuggest(query)) return
    let alive = true
    setSuggest({ q: query, rows: [], hint: '搜索中…' })
    const timer = setTimeout(() => {
      void runSuggest(query).then((answer) => {
        // 两道闸：`alive`（本次输入已被新输入取代）＋ `stale`（查询器侧的序号，双保险）
        if (!alive || answer.stale) return
        setSuggest({
          q: answer.query,
          rows: answer.outcome.ok ? answer.outcome.matches : [],
          hint: answer.outcome.ok ? suggestHint(answer.outcome.matches.length) : answer.outcome.message,
        })
      })
    }, SUGGEST_DEBOUNCE_MS)
    return () => {
      alive = false
      clearTimeout(timer)
    }
  }, [searchQuery, runSuggest])

  /** 点候选即选中（下拉收起：输入框清空 ⇒ 短查询；要换货号就再输几个字） */
  const onSuggestPick = useCallback((match: SkuMatch) => {
    setChosenSku(match)
    setSearchQuery('')
    setSuggest({ q: '', rows: [], hint: '' })
  }, [])

  const suggestQuery = suggestQueryOf(searchQuery)
  /** 只认**当前查询**的候选（旧查询的候选哪怕还在内存里也不上屏） */
  const suggestRows = suggest.q === suggestQuery ? suggest.rows : []
  const suggestText = suggest.q === suggestQuery ? suggest.hint : ''
  const suggestTooShort = suggestQuery !== '' && !canSuggest(suggestQuery)

  /**
   * 建单准入的**实时**结论（勾「我确认」/ 填卷长 / 选货号 三件事）。
   * 渲染在「提交过账」**正上方** ⇒ 缺什么当场看得见（issue #7822），不靠点完之后去页面顶部找横幅
   * （长表单 / 小屏 / 软键盘弹起时那面横幅在视口之外）。判据真值仍是 `checkDraftInput`。
   */
  const draftCheck = useMemo(
    () =>
      checkDraftInput({
        productId: chosenSku?.productId || null,
        skuId: chosenSku?.skuId ?? null,
        quantity,
        rollLengthM,
        confirmed,
      }),
    [chosenSku, quantity, rollLengthM, confirmed],
  )
  /** 按钮上方那一行：**提交失败的文案优先**，否则给端侧闸缺的那一项 */
  const submitHint = submitError !== '' ? submitError : draftCheck.ok ? '' : draftCheck.message

  const onSubmit = useCallback(async () => {
    setError('')
    setSubmitError('')
    // 🔴 拦截原因**就地**上屏（issue #7822）：顶部横幅在长表单 / 小屏 / 软键盘弹起时会被折到
    //    视口之外（线上实测：按钮 top=588 在屏内、横幅 top=-170 在屏外）⇒ 工人读到的是「点了没反应」。
    if (!draftCheck.ok) {
      setSubmitError(draftCheck.message)
      return
    }
    // 过账**不可逆** ⇒ 二次确认（复用 #5654 的一步动作护栏；文案把两格说清）
    // 🔴 端侧**不在这里算乘积**（issue #6812）：入库米数 = 卷数 × 卷长 的真值在服务端，
    //    端侧再算一份就是第二份会漂的口径（精度/粒度都可能有差）⇒ 只把两格原样念给工人听。
    const outcome = await confirmActionResult(
      '确认过账',
      `${prefill?.productName || chosenSku?.skuCode || '这批货'} ${quantity} 卷 × ${rollLengthM} 米/卷过账后将立即加库存、生成批次号，且不可撤销`,
    )
    // 取消 = 工人的选择（静默）；**弹窗失联**不是选择 ⇒ 必须说一句（issue #7822）
    if (outcome === 'cancelled') return
    if (outcome === 'failed') {
      setSubmitError('这张单没有提交：确认框没能弹出来。请再点一次「提交过账」。')
      return
    }
    setSubmitting(true)
    const draftRequestId = newInboundRequestId()
    try {
      const draft = await createInboundDraft(
        {
          productId: String(chosenSku?.productId || ''),
          // 🔴 雪花号 id **原样字符串**回传：Number() 会丢精度（> 2^53），服务端查不到该 SKU（issue #6340）
          skuId: String(chosenSku?.skuId),
          quantity,
          // 空字符串 ⇒ null（与 dyeLot / supplier 同款写法）
          rollLengthM: rollLengthM || null,
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
      // 服务端 400/422/409 的文案**原样**落到按钮上方（口径真值在服务端，端侧不重写第二份）
      setSubmitError(e?.message || '过账失败，请重试')
    } finally {
      setSubmitting(false)
    }
  }, [draftCheck, chosenSku, quantity, rollLengthM, prefill, dyeLot, supplier, supplierDocNo, remark])

  const onPrint = useCallback(async () => {
    setError('')
    setPrintState('')
    const shortCode = String(label?.shortCode || '')
    if (!shortCode) {
      setError('这张标签没有短码，不能打印（可回电脑端补打）。')
      return
    }
    setBusy(true)
    const transport = await createPrintTransport()
    if (!transport) {
      setBusy(false)
      setPrintState(SDK_UNAVAILABLE_HINT)
      return
    }
    const result = await printInboundLabel({
      shortCode,
      capability,
      transport,
      recordPrint: async (code) => {
        const res = await recordInboundLabelPrint(code)
        if (!res.success || !res.data) throw new Error(res.message || '打印留痕失败')
        return res.data
      },
      render: () => renderInboundLabel(label as InboundLabelView, createH5CanvasFactory()),
    })
    setBusy(false)
    if (result.ok) {
      setPrintState(`已送出打印（系统记第 ${result.printCount} 次）`)
      const refreshed = await getInboundLabel(shortCode)
      if (refreshed.success && refreshed.data) setLabel(refreshed.data)
      return
    }
    // 「记没记打印次数」是**运行期事实**（留痕在送数据之前）⇒ 由 printRecorded 决定要不要补一句，
    // 不靠静态文案对运行期下结论（issue #5052 验收 D6）
    setPrintState(printFailureText(result.hint, result.printRecorded))
  }, [label, capability])

  const gate = useMemo(() => evaluateSkuGate(matches), [matches])
  /** 逐格识别结果（服务端 `fields` 原样派生；空 = 这次没回字段表 ⇒ 不渲染这一段） */
  const fieldRows = useMemo(() => recognizedFieldRows(recognized), [recognized])
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
          拍上游标签 → 核对 → 过账入库 → 打印标签
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
          {capability.ok ? capability.readyHint || PRINT_READY_HINT : capability.hint}
        </Text>

        {/* 连接状态（**运行期事实**）：能打 ≠ 已连上（机器可能没开机）—— 两件事分开显示 */}
        {capability.ok && showsPrinterLinkHint() && (
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
              已选 {photos.length} 张 · 请把二维码拍清楚、拍完整
            </Text>
            {busy && progress !== '' && (
              <Text className='admin-card__meta' data-testid='inbound-progress'>
                {progress}
              </Text>
            )}
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

            {fieldRows.length > 0 && (
              <View data-testid='inbound-recognized-fields'>
                <Text className='admin-card__note'>系统读到的内容（核对一下；空着的格要自己填）</Text>
                {fieldRows.map((row) => (
                  <Text
                    key={`field-${row.key}`}
                    className='admin-card__meta'
                    data-testid={`inbound-field-${row.key}`}
                  >
                    {row.label}：{row.text}
                  </Text>
                ))}
              </View>
            )}

            {recognized?.doorWidthAssumed === true && (
              <Text className='admin-card__note' data-testid='inbound-door-width-assumed'>
                标签未印门幅，按行业标准 {recognized?.doorWidth} 米（如有其他门幅，标签上会写，请核对）
              </Text>
            )}

            {gate.kind === 'none' && (
              <View data-testid='inbound-sku-search'>
                <Text className='admin-card__note' data-testid='inbound-sku-gate-none'>
                  {gate.message}
                </Text>
                <Text className='admin-card__meta'>按货号或色名搜已有货号（只查不改，选中后才入库）</Text>
                <Input
                  className='admin-input'
                  data-testid='inbound-sku-search-input'
                  placeholder='输入货号或色名（至少 2 个字，边输边出候选）'
                  value={searchQuery}
                  onInput={(e: any) => setSearchQuery(e?.detail?.value ?? '')}
                />
                {/* 下拉候选（issue #7892）：点一条即选中，不再需要「搜货号」按钮 */}
                {suggestRows.length > 0 && (
                  <View className='admin-suggest' data-testid='inbound-sku-suggest'>
                    {suggestRows.slice(0, SUGGEST_SHOW_LIMIT).map((match) => (
                      <View
                        key={`found-${match.skuId}`}
                        className='admin-suggest__row'
                        data-testid={`inbound-sku-found-${match.skuId}`}
                        onClick={() => onSuggestPick(match)}
                      >
                        <Text>
                          {match.skuCode || '未填货号'} · {match.colorName || '未填色号'}
                          {match.doorWidth ? ` · 门幅 ${match.doorWidth}` : ''}
                        </Text>
                      </View>
                    ))}
                  </View>
                )}
                {(suggestTooShort || suggestText !== '') && (
                  <Text className='admin-card__note' data-testid='inbound-sku-suggest-hint'>
                    {suggestTooShort ? SUGGEST_TOO_SHORT_HINT : suggestText}
                  </Text>
                )}
              </View>
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
              placeholder='卷数（默认 1；正整数）'
              value={quantity}
              onInput={(e: any) => setQuantity(e?.detail?.value ?? '')}
            />
            <Input
              className='admin-input'
              data-testid='inbound-roll-length'
              type='digit'
              placeholder='卷长（米/卷，如 67.2）'
              value={rollLengthM}
              onInput={(e: any) => setRollLengthM(e?.detail?.value ?? '')}
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
            {/* 🔴 拦截/失败原因**贴着按钮**（issue #7822）：端侧闸缺哪一项、服务端拒绝了什么都落这一行；
                顶部横幅只留拍照 / 识别 / 搜索这类与提交无关的失败（同屏不重复说同一件事）。 */}
            {submitHint !== '' && (
              <Text className='admin-card__note' data-testid='inbound-submit-blocked'>
                {submitHint}
              </Text>
            )}
            <View
              className={`admin-action admin-action--gold${busy || submitting ? ' admin-action--disabled' : ''}`}
              data-testid='inbound-submit'
              onClick={() => {
                if (!busy && !submitting) onSubmit()
              }}
            >
              <Text>{submitting ? '提交中…' : '提交过账'}</Text>
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
