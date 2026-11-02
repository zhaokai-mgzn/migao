/**
 * 工人**库存修正**（issue #8104；用户 2026-10-29 逐字
 * 「手机端还要增加一个库存修正的功能，apk程序也要同步增加这个功能，允许工人对某个批次的布匹进行修正」）。
 *
 * ## 这一页回答什么
 *
 * 「这一卷布实际只剩 42 米，系统说还有 45.5 米」—— 工人当场按批次改成实测米数，不必回电脑端找管理员盘点。
 * 一条链：**搜批次 → 看到系统余量 → 填实盘米数 + 选原因 → 二次确认 → 提交 → 回执四数**。
 *
 * ## 六条纪律（每条都有对应断言，见 `tests/worker-stock-page.test.tsx`）
 *
 * 1. 🔴 **身份只由会话解**：请求体里没有 `worker_id` / `worker_name`
 *    （构造式白名单 = `utils/workerStock.ts` 的 `buildCorrectionBody`）；页头显示的是**服务端**的当前工人；
 * 2. 🔴 **米数口径与库存链路同一把尺**：0.1 米、不接受负数、**不做静默取整**
 *    （`parseActualMeters` 先拦一道只为少一次往返；服务端仍是权威）；
 * 3. 🔴 **不替工人决定提交**：改库存是不可逆动作 ⇒ 提交前 `Taro.showModal` 二次确认，
 *    确认文案里带上「系统读数 → 实盘读数」让工人复核；
 * 4. 🔴 **幂等**：一次提交一把 `clientRequestId`（失败重试复用）；工人**改了任何输入** ⇒ 换新键
 *    （否则服务端会把「改了数字的重试」当成上一次的回放，静默不落账）；
 * 5. 🔴 **三态分开说**：`applied`（真的改了）/ `unchanged`（与系统一致，零写入）/
 *    `replayed`（这次提交此前已记过账）—— 混成一句「提交成功」会让工人以为改了两次；
 * 6. 🔴 **401 单独一态**：未登录 / 会话失效 ⇒ 引导去工人登录（不清商家态、不跳商家登录页）。
 *
 * ## 边界（照实登记）
 *
 * - **一个提交只改一个批次**：工人现场就是「这一卷」；批量盘点仍是商家面（`/api/admin/batch-stock/stocktake`）。
 * - **不做盘点单**：无单号 / 无审批 / 无打印（沿用 #5865 的「A 最小录入式」）。
 * - 台账来源仍是 `reason=stocktake` + `note` 写明「工人库存修正：谁 / 工号 / 原因」
 *   （要在台账上把「工人修正 / 商家盘点」分列 ⇒ 另开迁移单，见 issue #8104 的边界段）。
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import Taro from '@tarojs/taro'
import { Button, Input, Text, View } from '@tarojs/components'
import { fetchCurrentWorker } from '../../../services/workerService'
import { getInboundLabel, uploadInboundPhotoSmart } from '../../../services/workerInboundService'
import {
  recognizeBatchNo,
  searchStockBatches,
  submitBatchCorrection,
} from '../../../services/workerStockService'
import type { StockBatchPage } from '../../../services/workerStockService'
import { decodeBarcodeFromPhoto } from '../../../utils/inbound/barcodeDecode'
import { STOCK_WORKER_LOGIN_REQUIRED, WORKER_LOGIN_ROUTE } from '../../../utils/inbound/gaps'
import { clearWorkerSession, hasWorkerSession, type CurrentWorker } from '../../../utils/workerSession'
import {
  MAX_NOTE_LENGTH,
  buildCorrectionBody,
  describeCorrection,
  formatDelta,
  formatMeters,
  newCorrectionRequestId,
  parseActualMeters,
  rowSubtitle,
  type CorrectionReason,
  type CorrectionReceipt,
  type StockBatchRow,
} from '../../../utils/workerStock'
import {
  STOCK_RECOGNIZE_MANUAL_HINT,
  locateByBatchNo,
  normalizeBatchNo,
  runStockRecognize,
} from '../../../utils/workerStockRecognize'
import './index.scss'

/** 空态文案（说清「怎么才会有批次」——只说「没有」等于没说）。 */
export const EMPTY_HINT = '没有匹配的批次：换个关键词（批次号 / 货号 / 缸号 / 入库单号任一段），或清空后直接看最近入库的批次'

/** 读不到时的兜底文案（技术原文留在请求层）。 */
export const READ_FAILED_HINT = '读取失败，请重试'

/** 页面上的四种状态（互斥）。 */
export type StockPhase = 'loading' | 'error' | 'unauthorized' | 'ready'

/**
 * 二次确认文案：把「系统读数 → 工人填的读数」放在同一句里（工人据此复核，不靠记忆）。
 *
 * 抽成导出函数是为了让判据能逐字钉住它（文案里少一个数 = 工人少一次核对机会）。
 */
export function confirmText(row: StockBatchRow, actualMeters: number): string {
  return `批次 ${row.batch_no}：系统余量 ${formatMeters(row.remaining_meters)} → 实盘 ${formatMeters(
    actualMeters,
  )}。修正后库存台账会按实盘对齐，确认提交吗？`
}

export default function WorkerStockPage() {
  /** 本机有没有工人身份（本地判据，只决定「渲染功能」还是「先引导登录」） */
  const workerReady = hasWorkerSession()
  const [worker, setWorker] = useState<CurrentWorker | null>(null)
  const [phase, setPhase] = useState<StockPhase>(workerReady ? 'loading' : 'unauthorized')
  const [keyword, setKeyword] = useState('')
  const [rows, setRows] = useState<StockBatchRow[]>([])
  const [reasons, setReasons] = useState<CorrectionReason[]>([])
  const [searched, setSearched] = useState(false)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')

  const [selected, setSelected] = useState<StockBatchRow | null>(null)
  const [actual, setActual] = useState('')
  const [reasonCode, setReasonCode] = useState('')
  const [note, setNote] = useState('')
  const [receipt, setReceipt] = useState<CorrectionReceipt | null>(null)
  /**
   * 幂等键（**一次提交一把**）：只在「同一份输入的重试」上复用。
   * 工人改了批次 / 米数 / 原因 / 备注 ⇒ 置空 ⇒ 下一次提交换新键（否则服务端按回放处理，静默不落账）。
   */
  const requestIdRef = useRef('')

  const unauthorized = useCallback(() => {
    clearWorkerSession()
    setWorker(null)
    setPhase('unauthorized')
  }, [])

  const loadWorker = useCallback(async () => {
    const res = await fetchCurrentWorker()
    if (res.success && res.data) {
      setWorker(res.data)
      return
    }
    unauthorized()
  }, [unauthorized])

  const runSearch = useCallback(
    async (text: string) => {
      if (!workerReady) {
        setPhase('unauthorized')
        return
      }
      setBusy(true)
      setMessage('')
      const res = await searchStockBatches(text)
      setBusy(false)
      if (res.success && res.data) {
        const page: StockBatchPage = res.data
        setRows(Array.isArray(page.items) ? page.items : [])
        setReasons(Array.isArray(page.reasons) ? page.reasons : [])
        setSearched(true)
        setPhase('ready')
        return
      }
      // 🔴 401 = 未登录 / 会话失效 ⇒ 引导登录；**不**渲染成「读不到」或「没有批次」
      if (res.statusCode === 401) {
        unauthorized()
        return
      }
      setMessage(res.message || READ_FAILED_HINT)
      setPhase('error')
    },
    [unauthorized, workerReady],
  )

  useEffect(() => {
    if (!workerReady) {
      setPhase('unauthorized')
      return
    }
    void loadWorker()
    void runSearch('')
    // 只在挂载时对齐一次（后续由「搜索 / 提交」驱动）
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  /** 选中一个批次 ⇒ 打开修正面板（并清掉上一次的输入 / 回执 / 幂等键）。 */
  const selectRow = useCallback(
    (row: StockBatchRow, reasonList?: CorrectionReason[]) => {
      setSelected(row)
      setActual('')
      // 原因清单可能来自**本次**搜索（识别后的定位），不能只读 state 里上一次的那份
      setReasonCode((reasonList ?? reasons)[0]?.code ?? '')
      setNote('')
      setReceipt(null)
      setMessage('')
      requestIdRef.current = ''
    },
    [reasons],
  )

  /** 工人改了任何输入 ⇒ 这份输入是一次**新的**提交（幂等键必须换）。 */
  const touched = useCallback(() => {
    requestIdRef.current = ''
  }, [])

  /**
   * 按批次号**精确定位**（识别入口的唯一落点；复用既有搜索读面，不新造端点）。
   *
   * 三态分开说：命中 1 行 ⇒ 直接打开修正面板；同号多行 ⇒ 列出来让工人点；0 行 ⇒ 明说
   * 「没找到批次 X」（**不**退化成「没有批次」，那会让工人以为系统里全没了）。
   */
  const locateBatch = useCallback(
    async (rawBatchNo: string) => {
      const batchNo = normalizeBatchNo(rawBatchNo)
      if (batchNo === '') {
        setMessage(STOCK_RECOGNIZE_MANUAL_HINT)
        return
      }
      setKeyword(batchNo)
      setBusy(true)
      setMessage('')
      const res = await searchStockBatches(batchNo)
      setBusy(false)
      if (!res.success || !res.data) {
        if (res.statusCode === 401) {
          unauthorized()
          return
        }
        setMessage(res.message || READ_FAILED_HINT)
        setPhase('error')
        return
      }
      const page: StockBatchPage = res.data
      const found = Array.isArray(page.items) ? page.items : []
      const reasonList = Array.isArray(page.reasons) ? page.reasons : []
      setRows(found)
      setReasons(reasonList)
      setSearched(true)
      setPhase('ready')

      const location = locateByBatchNo(found, batchNo)
      if (location.kind === 'selected') {
        selectRow(location.row, reasonList)
        return
      }
      setSelected(null)
      if (location.kind === 'ambiguous') {
        setMessage(`找到 ${location.rows.length} 个批次都用这个批次号，请点一行确认要修正哪一批`)
        return
      }
      setMessage(
        `没找到批次 ${batchNo}：可能不是本企业的批次，或这张标签上印的是旧系统批次号 —— 请核对后手输`,
      )
    },
    [selectRow, unauthorized],
  )

  /**
   * 拍照识别批次号（issue #8210）。
   *
   * 顺序在 `runStockRecognize` 里钉死：**扫标签二维码（0 次 LLM）→ vision 兜底 → 手输**。
   * 页面只做接线：拿图 → 交纯函数 → 按结果定位。识别**不提交**（提交仍要工人填实盘数 + 二次确认）。
   */
  const runRecognize = useCallback(async () => {
    if (!workerReady) {
      setPhase('unauthorized')
      return
    }
    setMessage('')
    let photos: Array<{ tempFilePath: string }> = []
    try {
      const picked: any = await Taro.chooseImage({ count: 1, sourceType: ['camera', 'album'] })
      const paths: string[] = Array.isArray(picked?.tempFilePaths) ? picked.tempFilePaths : []
      photos = paths.filter((path) => String(path ?? '') !== '').map((path) => ({ tempFilePath: path }))
    } catch {
      // 取消拍照 / 没有相机权限 ⇒ 静默返回（不是错误，工人可以改手输）
      return
    }
    if (photos.length === 0) return

    setBusy(true)
    try {
      const outcome = await runStockRecognize({
        photos,
        decode: decodeBarcodeFromPhoto,
        lookupLabelBatchNo: async (shortCode: string) => {
          const res = await getInboundLabel(shortCode)
          if (!res.success || !res.data) return { batchNo: null, failed: true }
          return { batchNo: res.data.batchNo ?? null }
        },
        upload: async (photo) => {
          const path = String(photo.tempFilePath || photo.file || '')
          const res = await uploadInboundPhotoSmart({ tempFilePath: path })
          const url = res?.data?.url
          if (!res?.success || !url) throw new Error('upload failed')
          return String(url)
        },
        recognize: async ({ images }) => recognizeBatchNo(images),
      })
      setBusy(false)
      if (outcome.statusCode === 401) {
        unauthorized()
        return
      }
      if (outcome.notice) setMessage(outcome.notice)
      if (outcome.batchNo) await locateBatch(outcome.batchNo)
    } catch {
      setBusy(false)
      setMessage(STOCK_RECOGNIZE_MANUAL_HINT)
    }
  }, [locateBatch, unauthorized, workerReady])

  const submit = useCallback(async () => {
    if (!selected) return
    const parsed = parseActualMeters(actual)
    if (parsed.error) {
      setMessage(parsed.error)
      return
    }
    if (!reasonCode) {
      setMessage('请选择修正原因（方便以后查得到这批为什么变了）')
      return
    }
    const modal = await Taro.showModal({
      title: '确认修正库存',
      content: confirmText(selected, parsed.value as number),
      confirmText: '确认修正',
      cancelText: '再检查一下',
    })
    if (!modal?.confirm) return

    // 同一次提交的重试复用同一个键；换了输入 ⇒ 新键（见 touched）
    if (!requestIdRef.current) requestIdRef.current = newCorrectionRequestId()
    const body = buildCorrectionBody(selected, parsed.value as number, reasonCode, note,
      requestIdRef.current)

    setBusy(true)
    setMessage('')
    const res = await submitBatchCorrection(body)
    setBusy(false)
    if (res.success && res.data) {
      setReceipt(res.data)
      setMessage('')
      // 回执的盘后读数**回写列表**（工人接着做下一卷时看到的是新余量，不是旧读数）
      const after = Number(res.data.after_meters)
      const batchId = res.data.batch_id ?? selected.batch_id
      setRows((prev) =>
        prev.map((row) =>
          row.batch_id === batchId && Number.isFinite(after)
            ? { ...row, remaining_meters: after }
            : row,
        ),
      )
      setSelected((prev) =>
        prev && prev.batch_id === batchId && Number.isFinite(after)
          ? { ...prev, remaining_meters: after }
          : prev,
      )
      requestIdRef.current = ''
      return
    }
    if (res.statusCode === 401) {
      unauthorized()
      return
    }
    // 失败保留 requestIdRef：同一份输入的点「重试」必须是同一次提交（不双记）
    setMessage(res.message || '提交修正失败，请重试')
  }, [actual, note, reasonCode, selected, unauthorized])

  if (!workerReady || phase === 'unauthorized') {
    return (
      <View className='worker-stock'>
        <View className='worker-stock__gate' data-testid='worker-stock-gate'>
          <Text className='worker-stock__gate-text'>{STOCK_WORKER_LOGIN_REQUIRED}</Text>
          <Button
            className='worker-stock__login'
            onClick={() => Taro.navigateTo({ url: WORKER_LOGIN_ROUTE })}
          >
            去登录工人身份
          </Button>
        </View>
      </View>
    )
  }

  return (
    <View className='worker-stock'>
      <View className='worker-stock__header'>
        <View className='worker-stock__heading'>
          <Text className='worker-stock__title'>库存修正</Text>
          <Text className='worker-stock__worker' data-testid='worker-stock-worker'>
            当前工人：{worker ? worker.worker_name || '未署名' : '—'}
            {worker?.worker_no ? `（工号 ${worker.worker_no}）` : ''}
          </Text>
        </View>
      </View>

      {/* 搜索：批次号 / 货号 / 缸号 / 入库单号任一段；空关键词 = 最近入库的批次 */}
      <View className='worker-stock__search'>
        <Input
          className='worker-stock__input'
          data-testid='worker-stock-keyword'
          value={keyword}
          placeholder='批次号 / 货号 / 缸号 / 入库单号'
          confirmType='search'
          onInput={(e: any) => setKeyword(e?.detail?.value ?? '')}
          onConfirm={() => void runSearch(keyword)}
        />
        <Button
          className='worker-stock__search-button'
          data-testid='worker-stock-search'
          disabled={busy}
          onClick={() => void runSearch(keyword)}
        >
          查询
        </Button>
      </View>

      {/* 拍照识别批次号（issue #8210）：扫标签二维码优先（0 次 LLM）→ OCR 兜底 → 手输 */}
      <View className='worker-stock__recognize'>
        <Button
          className='worker-stock__recognize-button'
          data-testid='worker-stock-recognize'
          disabled={busy}
          onClick={() => void runRecognize()}
        >
          拍照识别批次号
        </Button>
        <Text className='worker-stock__recognize-hint'>
          拍标签上的二维码最快；没有码时自动按批次号文字识别
        </Text>
      </View>

      {message ? (
        <Text className='worker-stock__message' data-testid='worker-stock-message'>
          {message}
        </Text>
      ) : null}

      {phase === 'loading' ? (
        <View className='worker-stock__notice' data-testid='worker-stock-loading'>
          <Text className='worker-stock__notice-text'>正在读取批次…</Text>
        </View>
      ) : null}

      {phase === 'error' ? (
        <View className='worker-stock__notice' data-testid='worker-stock-error'>
          <Text className='worker-stock__notice-text'>{READ_FAILED_HINT}</Text>
          <Button className='worker-stock__retry' data-testid='worker-stock-retry' onClick={() => void runSearch(keyword)}>
            重试
          </Button>
        </View>
      ) : null}

      {phase === 'ready' && rows.length === 0 && searched ? (
        <View className='worker-stock__notice' data-testid='worker-stock-empty'>
          <Text className='worker-stock__notice-text'>{EMPTY_HINT}</Text>
        </View>
      ) : null}

      {phase === 'ready' && rows.length > 0 ? (
        <View className='worker-stock__list'>
          <Text className='worker-stock__list-hint'>选中要修正的批次（点这一行）：</Text>
          {rows.map((row, index) => (
            <View
              className={
                selected?.batch_id === row.batch_id
                  ? 'worker-stock__row worker-stock__row--active'
                  : 'worker-stock__row'
              }
              key={`batch-${row.batch_id}`}
              data-testid={`worker-stock-row-${index}`}
              onClick={() => selectRow(row)}
            >
              <Text className='worker-stock__row-no' data-testid={`worker-stock-batch-no-${index}`}>
                {row.batch_no}
              </Text>
              <Text className='worker-stock__row-meta' data-testid={`worker-stock-row-meta-${index}`}>
                {rowSubtitle(row)}
              </Text>
              <Text className='worker-stock__row-rest' data-testid={`worker-stock-remaining-${index}`}>
                系统余量：{formatMeters(row.remaining_meters)}
              </Text>
            </View>
          ))}
        </View>
      ) : null}

      {selected ? (
        <View className='worker-stock__panel' data-testid='worker-stock-panel'>
          <Text className='worker-stock__panel-title'>修正批次 {selected.batch_no}</Text>
          <Text className='worker-stock__panel-line' data-testid='worker-stock-before'>
            系统余量：{formatMeters(selected.remaining_meters)}
          </Text>

          <Text className='worker-stock__label'>实盘米数（这一批现在实际还剩多少米）</Text>
          <Input
            className='worker-stock__input'
            data-testid='worker-stock-meters'
            type='digit'
            value={actual}
            placeholder='例如 42 或 42.5'
            onInput={(e: any) => {
              setActual(e?.detail?.value ?? '')
              touched()
            }}
          />

          <Text className='worker-stock__label'>修正原因</Text>
          <View className='worker-stock__reasons'>
            {reasons.map((reason) => (
              <View
                className={
                  reasonCode === reason.code
                    ? 'worker-stock__reason worker-stock__reason--active'
                    : 'worker-stock__reason'
                }
                key={reason.code}
                data-testid={`worker-stock-reason-${reason.code}`}
                onClick={() => {
                  setReasonCode(reason.code)
                  touched()
                }}
              >
                <Text className='worker-stock__reason-text'>{reason.label}</Text>
              </View>
            ))}
          </View>

          <Text className='worker-stock__label'>备注（可不填，最多 {MAX_NOTE_LENGTH} 字）</Text>
          <Input
            className='worker-stock__input'
            data-testid='worker-stock-note'
            value={note}
            placeholder='例如：量过一遍，只剩半卷'
            maxlength={MAX_NOTE_LENGTH}
            onInput={(e: any) => {
              setNote(e?.detail?.value ?? '')
              touched()
            }}
          />

          <Button
            className='worker-stock__submit'
            data-testid='worker-stock-submit'
            disabled={busy}
            onClick={() => void submit()}
          >
            提交修正
          </Button>
        </View>
      ) : null}

      {receipt ? (
        <View className='worker-stock__receipt' data-testid='worker-stock-receipt'>
          <Text className='worker-stock__receipt-title'>{describeCorrection(receipt)}</Text>
          <Text className='worker-stock__receipt-line' data-testid='worker-stock-receipt-before'>
            盘前：{formatMeters(receipt.before_meters)}
          </Text>
          <Text className='worker-stock__receipt-line' data-testid='worker-stock-receipt-actual'>
            实盘：{formatMeters(receipt.actual_meters)}
          </Text>
          <Text className='worker-stock__receipt-line' data-testid='worker-stock-receipt-delta'>
            差异：{formatDelta(receipt.delta_meters)}
          </Text>
          <Text className='worker-stock__receipt-line' data-testid='worker-stock-receipt-after'>
            盘后：{formatMeters(receipt.after_meters)}
          </Text>
          <Text className='worker-stock__receipt-worker'>
            记录人：{receipt.worker_name || '—'}
            {receipt.worker_no ? `（工号 ${receipt.worker_no}）` : ''}
          </Text>
        </View>
      ) : null}
    </View>
  )
}
