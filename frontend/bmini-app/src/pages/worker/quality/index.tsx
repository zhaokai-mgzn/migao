// case_ids: MC-222
/**
 * 工人端**质检**页（issue #7813 P2b）—— 工人菜单页的一条行卡：`pages/worker/quality/index`。
 *
 * ## 这一页回答什么
 *
 * 「这一件（套号 × 部位）现在是什么状态、之前记过什么」—— 数据源 =
 * `GET /api/worker/quality/latest?order_item_id=…&set_no=…`（与 H5 `/w/` 报工页的
 * 「质检记录（做工）」块**同一个端点、同一份服务端口径**）。
 *
 * ## 搬迁口径（`/w/` 的质检区块 → 小程序的一条入口）
 *
 * | `/w/` 的形态 | 本页 |
 * |---|---|
 * | 报工屏里的一个区块（只在 `inspect` ∈ 页面集 + 已扫到一件时出现） | 工人菜单页的**一条入口**（`inspect` 键门控） |
 * | 状态词（读取中 / 未读到 / 正常 / 待复检 / 已判报废）+ 记录列表 | **逐条搬**（同一份词表、同一句空态） |
 * | 【记返工 / 复检通过 / 复检仍有问题】三个写动作 | **不搬**：本页只读（P2b =「一条入口 + 读面复用」）；录判定仍在 `/w/`，是否搬进小程序 = P2c 之后另裁 |
 * | 「未开通质检页」 | 403 ⇒ 可行动提示（找管理员开「质检」），**不**说成「没有记录」 |
 *
 * ## `/w/` 四条硬约束在本页的落点
 *
 * - ① **旧码 ⇒ 进 select 态，绝不默认取第 1 套**：多套同部位时猜错套 = 把**别的套**的质检结论
 *   摆给质检员看。⇒ 旧码只出选套 / 选部位，选完才取。
 * - ② 工序未确定 ⇒ **不得出现报工按钮**：本页没有报工按钮，只明说「这道工序还没定」。
 * - ③ 未登录 ⇒ 不得出现报工按钮：未登录只给去登录。
 * - ④ **屏上只认服务端**：状态词只由 `qualityStateText` 给 —— 读失败说「未读到」，
 *    **绝不**回落成「正常」（那是在替服务端断言「这一件没问题」）。
 *
 * ## 边界（照实登记）
 *
 * - **只读**：不录判定（写面 `POST /api/worker/quality/inspections` 仍只在 `/w/`）。
 * - 准入在服务端：工人档案页面集没有 `inspect` ⇒ 403；本页据此给可行动提示。
 */
import { useCallback, useEffect, useState } from 'react'
import Taro from '@tarojs/taro'
import { Button, Text, View } from '@tarojs/components'
import { scanResolve, type ScanSelection } from '../../../services/productionService'
import { fetchQualityLatest } from '../../../services/workerQualityService'
import { fetchCurrentWorker } from '../../../services/workerService'
import { clearWorkerSession, hasWorkerSession } from '../../../utils/workerSession'
import {
  QUALITY_WORKER_LOGIN_REQUIRED,
  REPORT_PAGE_ROUTE,
  WORKER_LOGIN_ROUTE,
} from '../../../utils/inbound/gaps'
import { resolveScanLanding } from '../../../utils/scanInput'
// 🔴 h5 里没有原生扫码（Taro 侧只在微信内可用）⇒ 本文件必须有**显式平台分支**，
// 否则「点了没反应」是静默失败（守卫 tests/h5-platform-api-guard.test.ts）。
import { canUseNativeScan } from '../../../utils/platform'
import {
  QUALITY_EMPTY_HINT,
  QUALITY_NOT_ENABLED_HINT,
  READ_ONLY_NOTICE,
  applyReadScan,
  operationNotReadyHint,
  operationText,
  pieceText,
  qualityRecordRows,
  qualityStateText,
  readFaceInitial,
  readPickPosition,
  readPickSet,
  reportHandoffUrl,
  textOr,
  type QualityRead,
  type ReadFaceState,
  type ReadFaceWorker,
} from '../../../utils/workerReadFaces'
import { WorkerReadLegacyPicker, WorkerReadScanEntry } from '../../../components/WorkerReadEntry'
import { WorkerBackLink } from '../../../components/WorkerBackLink'
import './index.scss'

/** 页面标题（工人这里说的是「质检记录」：这一件做过什么，不是「质量判定」这个研发词）。 */
export const QUALITY_TITLE = '质检记录'

/** 读不到时的兜底（技术原文留在请求层）。 */
export const QUALITY_READ_FAILED_HINT = '读取质检记录失败，请重试'

/** 页面级提示（未开通 / 读失败：两者互斥，都**不**冒充「没有记录」）。 */
export type QualityNotice = { kind: 'notEnabled' | 'failed'; text: string } | null

export default function WorkerQualityPage() {
  const workerReady = hasWorkerSession()
  const [state, setState] = useState<ReadFaceState>(() => readFaceInitial(null))
  const [manual, setManual] = useState('')
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<QualityNotice>(null)
  const [quality, setQuality] = useState<QualityRead | null>(null)
  const [token, setToken] = useState('')

  useEffect(() => {
    if (!workerReady) {
      setState({ ...readFaceInitial(null), mode: 'unauthorized' })
      return
    }
    void (async () => {
      const res = await fetchCurrentWorker()
      if (res.success && res.data) {
        setState(readFaceInitial(res.data as ReadFaceWorker))
        return
      }
      // 身份读不到（401 / 闲置超时）⇒ 清本机并回未登录（绝不按上一个人看待这一屏）
      clearWorkerSession()
      setState({ ...readFaceInitial(null), mode: 'unauthorized' })
    })()
  }, [workerReady])

  /** 读到一件之后取它的质检状态（顺序：先解析定位，再读记录 —— 两件事不合并）。 */
  const loadQuality = useCallback(async (orderItemId: string, setNo?: string | null) => {
    setNotice(null)
    setQuality({ loading: true, latest: null, records: [], error: null })
    const res = await fetchQualityLatest(orderItemId, setNo)
    if (res.statusCode === 401) {
      clearWorkerSession()
      setState({ ...readFaceInitial(null), mode: 'unauthorized' })
      setQuality(null)
      return
    }
    if (res.statusCode === 403) {
      // 🔴 403 ≠「没有记录」：状态词必须是「未读到」（读到「没有记录」才敢说正常/空态），
      // 另给一条**可行动**的提示（找管理员开「质检」）。
      setQuality({ loading: false, latest: null, records: [], error: QUALITY_NOT_ENABLED_HINT })
      setNotice({ kind: 'notEnabled', text: QUALITY_NOT_ENABLED_HINT })
      return
    }
    if (!res.success || !res.data) {
      setQuality({ loading: false, latest: null, records: [], error: res.message || QUALITY_READ_FAILED_HINT })
      setNotice({ kind: 'failed', text: res.message || QUALITY_READ_FAILED_HINT })
      return
    }
    setQuality({
      loading: false,
      latest: res.data.latest ?? null,
      records: Array.isArray(res.data.records) ? res.data.records : [],
      error: null,
    })
  }, [])

  const resolve = useCallback(
    async (raw: string, selection: ScanSelection | null = null) => {
      const code = String(raw ?? '').trim()
      if (code === '') return
      setBusy(true)
      setNotice(null)
      const res = await scanResolve(code, undefined, selection)
      setBusy(false)
      if (res.success && res.data) {
        setToken(code)
        setState((prev) => applyReadScan(prev, res.data!))
        const itemId = res.data.position?.order_item_id
        if (itemId) {
          void loadQuality(itemId, res.data.set_no === null ? null : String(res.data.set_no ?? ''))
        } else if (res.data.granularity !== 'order') {
          // 新码却没有部位 ⇒ 说明这一张码指不到具体一件（不猜，也不去读一个空的件）
          const text = '这次扫码没有指到具体的一件：请重新扫码'
          setQuality({ loading: false, latest: null, records: [], error: text })
          setNotice({ kind: 'failed', text })
        }
        return
      }
      if (res.statusCode === 401) {
        clearWorkerSession()
        setState({ ...readFaceInitial(null), mode: 'unauthorized' })
        return
      }
      setNotice({ kind: 'failed', text: res.message || QUALITY_READ_FAILED_HINT })
    },
    [loadQuality],
  )

  const scan = useCallback(async () => {
    // 没有原生扫码能力的端（h5 非微信浏览器）不发起调用：屏上早已只留手输码这一条路
    // （按钮本身也不渲染，见 WorkerReadScanEntry），这里是第二道（fail-closed）。
    if (!canUseNativeScan()) return
    try {
      const result = await Taro.scanCode({ scanType: ['qrCode', 'barCode'] })
      const code = resolveScanLanding({ text: (result as any)?.result }).code
      if (code) await resolve(code)
    } catch {
      // 用户取消扫码不是错误（小程序会 reject）—— 什么都不做，别弹红字
    }
  }, [resolve])

  const unauthorized = state.mode === 'unauthorized'
  const records = qualityRecordRows(quality?.records)
  const stateText = qualityStateText(quality)
  const operationHint = operationNotReadyHint(state.view)

  return (
    <View className='worker-quality'>
      <View className='worker-quality__header'>
        <WorkerBackLink />
        <Text className='worker-quality__title'>{QUALITY_TITLE}</Text>
        {state.worker ? (
          <Text className='worker-quality__worker' data-testid='worker-quality-worker'>
            当前工人：{textOr(state.worker.worker_name)}
          </Text>
        ) : null}
      </View>

      {unauthorized ? (
        <View className='worker-quality__gate' data-testid='worker-quality-login-required'>
          <Text className='worker-quality__notice'>{QUALITY_WORKER_LOGIN_REQUIRED}</Text>
          <Button
            className='worker-quality__action'
            data-testid='worker-quality-login'
            onClick={() => {
              void Taro.navigateTo({ url: WORKER_LOGIN_ROUTE })
            }}
          >
            去登录工人身份
          </Button>
        </View>
      ) : null}

      {!unauthorized && !state.view ? (
        <WorkerReadScanEntry
          prefix='worker-quality'
          manual={manual}
          onManualChange={setManual}
          onScan={() => {
            void scan()
          }}
          onResolve={() => {
            void resolve(manual)
          }}
          busy={busy}
        />
      ) : null}

      {!unauthorized && notice ? (
        <View className='worker-quality__gate' data-testid={`worker-quality-${notice.kind}`}>
          <Text className='worker-quality__notice'>{notice.text}</Text>
          {notice.kind === 'failed' ? (
            <Button
              className='worker-quality__action'
              data-testid='worker-quality-retry'
              onClick={() => {
                setNotice(null)
                setState((prev) => ({ ...prev, view: null, mode: 'scan', notice: null }))
              }}
            >
              重新扫码
            </Button>
          ) : null}
        </View>
      ) : null}

      {state.mode === 'select' ? (
        <WorkerReadLegacyPicker
          prefix='worker-quality'
          state={state}
          onPickSet={(setId, setNo) => setState((prev) => readPickSet(prev, setId, setNo))}
          onPickPosition={(orderItemId, positionName) => {
            const next = readPickPosition(state, orderItemId, positionName)
            setState(next)
            if (next.selection.setId && next.selection.orderItemId) {
              void resolve(token, { setId: next.selection.setId, orderItemId: next.selection.orderItemId })
            }
          }}
        />
      ) : null}

      {state.mode === 'ready' && state.view ? (
        <View className='worker-quality__card' data-testid='worker-quality-card'>
          <View className='worker-quality__head'>
            <Text className='worker-quality__piece' data-testid='worker-quality-piece'>
              {pieceText(state.view)}
            </Text>
            <Text className='worker-quality__state' data-testid='worker-quality-state'>
              {stateText}
            </Text>
          </View>
          <Text className='worker-quality__line' data-testid='worker-quality-operation'>
            本道工序：{operationText(state.view.operation)}
          </Text>
          {operationHint ? (
            <Text className='worker-quality__notion' data-testid='worker-quality-operation-hint'>
              {operationHint}
            </Text>
          ) : null}

          {records.length > 0 ? (
            <View className='worker-quality__records' data-testid='worker-quality-records'>
              {records.map((record) => (
                <View className='worker-quality__record' key={record.key}>
                  <View className='worker-quality__record-top'>
                    {record.label !== stateText ? (
                      <Text className='worker-quality__label'>{record.label}</Text>
                    ) : null}
                    {record.time !== '' ? (
                      <Text className='worker-quality__time'>{record.time}</Text>
                    ) : null}
                  </View>
                  {record.reason ? (
                    <Text className='worker-quality__reason' data-testid='worker-quality-reason'>
                      {record.reason}
                    </Text>
                  ) : null}
                  {record.inspector ? (
                    <Text className='worker-quality__meta'>检验人 {record.inspector}</Text>
                  ) : null}
                </View>
              ))}
            </View>
          ) : quality?.error ? null : quality?.loading ? (
            <Text className='worker-quality__hint' data-testid='worker-quality-loading'>
              质检记录读取中…
            </Text>
          ) : (
            <Text className='worker-quality__hint' data-testid='worker-quality-empty'>
              {QUALITY_EMPTY_HINT}
            </Text>
          )}

          <Text className='worker-quality__hint'>{READ_ONLY_NOTICE}</Text>
          <Button
            className='worker-quality__action'
            data-testid='worker-quality-report'
            onClick={() => {
              void Taro.navigateTo({ url: reportHandoffUrl(REPORT_PAGE_ROUTE, token) })
            }}
          >
            去报工
          </Button>
        </View>
      ) : null}
    </View>
  )
}
