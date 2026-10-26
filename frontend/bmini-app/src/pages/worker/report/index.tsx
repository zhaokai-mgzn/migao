// case_ids: BM-014, BM-015, BM-025
/**
 * 工人**扫码报工**页（issue #7812 P2a）—— 小程序原生页（也随 `/b/` H5 一起编译）。
 *
 * ## 这一页回答什么
 *
 * 「我这一件该报哪道工序、报了多少」。流程 = **扫一扫（或手输码）→ 一屏 → 报工 → 回执**，
 * 记账/工序推断/完工判定**全在服务端**（`/api/worker/production/scan[/complete]`），端侧只做三件事：
 * 把码递上去、把服务端说的一屏摆出来、把工人点的这一下递回去。
 *
 * ## 四条硬约束（判据在 `src/utils/reportState.ts`，本页只按它渲染）
 *
 * ① 旧码（`granularity:'order'`）⇒ 进选套/选部位态，**绝不默认取第 1 套**；
 * ② 工序未确定（`operation == null`）⇒ **不出报工按钮**；
 * ③ 未登录 ⇒ **不出报工按钮**（本页直接给登录引导）；
 * ④ 回执 ⇒ 只显示服务端给的「下一道 / 本套已完成」，**前端不猜下一道**。
 *
 * ## 与 H5 `/w/` 的关系（收口方向 = #7806）
 *
 * 本页是纸上的码的**落地面**（issue #7879：`/s/` `/o/` 302 → `/b/?t=<token>` ⇒ h5 启动器把 token
 * 交给本页），语义与 H5 `/w/` 逐条对齐；`/w/` 转入兼容期（静态面可直连，但不再是任何 302 的目标，
 * 退役属 #7806 P3）。**记账口径一字未动**（扫码 = 开工/领活、单价在报工那刻固化）。
 *
 * ## 不做（照实登记）
 *
 * 机台/裁高、精裁清单、质检区块、成品标签打印属于 `/w/` 的其它面（P2b），本页不渲染；
 * 发货/入库走工作台的其它入口。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Button, Input, Text, View } from '@tarojs/components'
import Taro, { useDidShow } from '@tarojs/taro'
import { fetchCurrentWorker } from '../../../services/workerService'
import { completeByScan, scanResolve } from '../../../services/productionService'
import {
  clearWorkerSession,
  hasWorkerSession,
  type CurrentWorker,
} from '../../../utils/workerSession'
import {
  MISSING,
  WORK_TYPE_LABELS,
  WORK_TYPES,
  applyReceipt,
  applyScan,
  canReport,
  initialState,
  kindText,
  legacySelection,
  operationName,
  pickPosition,
  pickSet,
  progressText,
  qtyText,
  titleText,
  tokensFromScanResult,
  type ReportState,
  type ReportView,
  type WorkType,
} from '../../../utils/reportState'
import { WORKER_TAB_LOGIN_ROUTE } from '../../../utils/inbound/gaps'
// 🔴 入口参数的提取**不在本页判平台**（issue #7879）：h5 读 URL search、小程序读
// `getEnterOptionsSync()` / 页面参数，两条都收口到 `utils/scanInput.ts` 的同一个解析器
import { currentEntryLanding, rememberReportReturn } from '../../../utils/reportEntry'
import { resolveScanLanding } from '../../../utils/scanInput'
// 🔴 小程序专有 API 的 h5 出路（守卫 tests/h5-platform-api-guard.test.ts）：h5 产物里没有
// 原生扫码 ⇒ 不摆「扫一扫」按钮，手输码这条降级路径仍然可用（不是把页面弄死）。
import { canUseNativeScan } from '../../../utils/platform'
import './index.scss'

/** 未登录（本机没有工人身份）时的一句话。 */
export const REPORT_LOGIN_REQUIRED = '请先用工号 + PIN 登录工人身份，再扫码报工。'

/** 读面失败兜底（技术原文留在请求层）。 */
export const RESOLVE_FAILED_HINT = '扫码结果读取失败，请重试'

/** 手输提示。 */
export const MANUAL_HINT = '输码（短码 / 加工单号 / 订单号）'

/** 报工按钮文案（issue #6868 用户裁定「工人屏全部统一到『报』」）。 */
export const REPORT_BUTTON_TEXT = '报工'

/** 提交中（涉计件正确性：置真期间按钮 disabled + 改文案，防连点记两笔）。 */
export const REPORTING_TEXT = '提交中…'

let requestSeq = 0

/** 一次提交一个幂等键（重试同一次提交时**复用**它 —— 否则重试会记成两笔）。 */
export function newRequestId(): string {
  requestSeq += 1
  return `wr-${Date.now().toString(36)}-${requestSeq}`
}

export default function WorkerReportPage() {
  const workerReady = hasWorkerSession()
  const [state, setState] = useState<ReportState>(() =>
    initialState(null),
  )
  const [manual, setManual] = useState('')
  const [token, setToken] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  /** 页内错误（只用于「读不到 / 失败」这类非状态机的临时提示） */
  const [phaseError, setPhaseError] = useState('')
  const requestIdRef = useRef('')

  // ① 身份：本机没有工人身份 ⇒ 直接给登录引导（不出任何报工按钮）
  useEffect(() => {
    if (!workerReady) {
      setState({ ...initialState(null), mode: 'unauthorized' })
      return
    }
    void fetchCurrentWorker().then((res) => {
      if (res.success && res.data) {
        const worker = res.data as CurrentWorker
        setState((prev) => ({ ...prev, worker, mode: prev.view ? prev.mode : 'scan' }))
        return
      }
      // 身份读不到（401 / 闲置超时）⇒ 清本机并回到未登录（绝不按上一个人的身份报工）
      clearWorkerSession()
      setState({ ...initialState(null), mode: 'unauthorized' })
    })
  }, [workerReady])

  useDidShow(
    useCallback(() => {
      // 从登录页回来 ⇒ 本机已有身份时补一次读取（登录后直接能扫）
      if (hasWorkerSession() && !state.worker) {
        void fetchCurrentWorker().then((res) => {
          if (res.success && res.data) {
            setState((prev) => ({ ...prev, worker: res.data as CurrentWorker, mode: 'scan' }))
          }
        })
      }
    }, [state.worker]),
  )

  const goLogin = useCallback(() => {
    // 🔴 登录后**回跳本页继续报工**（issue #7879；新手机首次扫码时本机还没有工人 session）：
    // 把「要接着报的那个码」临时记在本机，登录成功后由 `pages/auth/login/index.tsx` 读它
    // `redirectTo` 回本页（不是停在登录页、也不是落到工人首页就把手里的活丢了）。存的是**码**，
    // 不是身份（PIN 绝不落盘，与 `rememberAccount` 的既有口径一致）。
    rememberReportReturn(token || manual.trim())
    Taro.navigateTo({ url: WORKER_TAB_LOGIN_ROUTE })
  }, [token, manual])

  /** 解析：token（+ 可选工序 / 旧码选择）→ 一屏。 */
  const resolve = useCallback(
    async (value: string, options: { operationId?: string | null; selection?: any } = {}) => {
      const code = String(value ?? '').trim()
      if (code === '') return
      setBusy(true)
      setPhaseError('')
      setMessage('')
      const res = await scanResolve(code, options.operationId ?? undefined, options.selection ?? null)
      setBusy(false)
      if (res.success && res.data) {
        setToken(code)
        setState((prev) => applyScan(prev, res.data as unknown as ReportView))
        return
      }
      if (res.statusCode === 401) {
        clearWorkerSession()
        setState({ ...initialState(null), mode: 'unauthorized' })
        return
      }
      setPhaseError(res.message || RESOLVE_FAILED_HINT)
      setState((prev) => ({ ...prev, error: res.message || RESOLVE_FAILED_HINT }))
    },
    [],
  )

  /**
   * 🔴 **入口即解析**（issue #7879）：h5 启动器 `redirectTo` 带 `?t=<token>`、小程序冷启动的
   * `query.q`（A 档「扫普通链接二维码打开小程序」）/ `query.scene`（B 档小程序码）—— 三条都经
   * `currentEntryLanding()` 归一 ⇒ 工人扫码后**不必再手输一次**。
   *
   * 只消费返回值（页面里**不判平台**）；身份未就绪时先等（下面的身份 effect 会把它设成
   * `scan` / `unauthorized`），未登录则先记下码再引导登录（`goLogin` 的 `rememberReportReturn`）。
   */
  const entryDoneRef = useRef(false)
  useEffect(() => {
    if (entryDoneRef.current) return
    if (state.mode === 'unauthorized' || !state.worker) return
    const landing = currentEntryLanding()
    if (landing.kind !== 'report' || landing.code === '') {
      entryDoneRef.current = true
      return
    }
    entryDoneRef.current = true
    void resolve(landing.code)
  }, [state.mode, state.worker, resolve])

  /** 扫一扫（小程序原生；扫码结果可能是短链 / 带 t 参数 / 裸码）。 */
  const scan = useCallback(async () => {
    try {
      const result = await Taro.scanCode({ scanType: ['qrCode', 'barCode'] })
      const code = resolveScanLanding({ text: (result as any)?.result }).code
      if (code) await resolve(code)
    } catch {
      // 用户取消扫码不是错误（小程序会 reject）—— 什么都不做，别弹红字
    }
  }, [resolve])

  const submit = useCallback(async () => {
    const view = state.view
    if (!canReport(state, view) || !view) return
    // 🔴 同一次提交复用同一个幂等键（首次生成；成功/失败后由调用方决定是否换新）
    if (!requestIdRef.current) requestIdRef.current = newRequestId()
    const operation = view.operation!
    const selection = legacySelection(state)
    const qtyRaw = operation.qty
    const qty = qtyRaw === null || qtyRaw === undefined ? null : Number(qtyRaw)
    setState((prev) => ({ ...prev, submitting: true, error: null }))
    // 🔴 单写入口复用：`completeByScan` 是 bmini 报工写面的**唯一实现**
    // （守卫 tests/production-single-write-entry.test.ts）；本页只补「旧码选择」与三态两件事。
    const res = await completeByScan(
      token,
      operation.operation_id,
      requestIdRef.current,
      {
        ...(Number.isFinite(qty as number) ? { qty: qty as number } : {}),
        // 非「正常」一律显式 0 合格（服务端缺省 = qty，会把报废记成满额合格）
        ...(state.workType === 'normal' ? {} : { qualified_qty: 0, work_type: state.workType }),
        ...(state.batchNo && state.batchNo.trim() !== '' ? { batch_no: state.batchNo.trim() } : {}),
      } as any,
      selection,
    )
    if (res.success && res.data) {
      requestIdRef.current = ''
      setState((prev) =>
        applyReceipt(prev, {
          nextOperation: (res.data?.next_operation as any) ?? null,
          setCompleted: res.data?.set_completed ?? null,
          setProgress: res.data?.set_progress ?? null,
        }),
      )
      setMessage('')
      Taro.showToast({ title: '已报工', icon: 'success' })
      return
    }
    if (res.statusCode === 401) {
      clearWorkerSession()
      setState({ ...initialState(null), mode: 'unauthorized' })
      return
    }
    // 失败：保留幂等键（重试同一笔不重复计件）
    setState((prev) => ({ ...prev, submitting: false, error: res.message || '报工失败，请重试' }))
  }, [state, token])

  const rescan = useCallback(() => {
    setToken('')
    setManual('')
    requestIdRef.current = ''
    setState((prev) => ({ ...initialState(prev.worker), mode: prev.worker ? 'scan' : 'unauthorized' }))
  }, [])

  const candidates = useMemo(() => {
    const op = state.view?.operation
    const list = [op, ...(state.view?.alternatives ?? [])].filter((c) => c && c.operation_id)
    return list as NonNullable<ReportView['operation']>[]
  }, [state.view])

  const showPicker = !state.view?.worker_operation && !state.view?.completed && candidates.length > 1
  const legacy = state.mode === 'select'
  const currentSet = (state.view?.needs_selection ?? []).find((s) => s.set_id === state.selection.setId)

  return (
    <View className='worker-report'>
      <View className='worker-report__header'>
        <Text className='worker-report__title'>扫码报工</Text>
        {state.worker ? (
          <Text className='worker-report__worker' data-testid='worker-report-worker'>
            当前工人：{state.worker.worker_name || MISSING}
          </Text>
        ) : null}
      </View>

      {state.mode === 'unauthorized' ? (
        <View className='worker-report__gate' data-testid='worker-report-login-required'>
          <Text className='worker-report__gate-text'>{REPORT_LOGIN_REQUIRED}</Text>
          <Button className='worker-report__primary' data-testid='worker-report-login' onClick={goLogin}>
            去登录工人身份
          </Button>
        </View>
      ) : null}

      {state.mode !== 'unauthorized' && !state.view ? (
        <View className='worker-report__scan' data-testid='worker-report-scan'>
          {canUseNativeScan() ? (
            <Button
              className='worker-report__primary'
              data-testid='worker-report-scan-button'
              disabled={busy}
              onClick={() => {
                void scan()
              }}
            >
              {busy ? '读取中…' : '扫一扫'}
            </Button>
          ) : null}
          <Text className='worker-report__hint'>{MANUAL_HINT}</Text>
          <Input
            className='worker-report__input'
            data-testid='worker-report-manual'
            value={manual}
            placeholder={MANUAL_HINT}
            onInput={(event) => setManual((event as any)?.detail?.value ?? '')}
          />
          <Button
            className='worker-report__ghost'
            data-testid='worker-report-manual-submit'
            disabled={busy || manual.trim() === ''}
            onClick={() => {
              void resolve(manual)
            }}
          >
            确定
          </Button>
        </View>
      ) : null}

      {legacy ? (
        <View className='worker-report__legacy' data-testid='worker-report-legacy'>
          <Text className='worker-report__notice' data-testid='worker-report-legacy-notice'>
            {state.notice || '这是一张旧码：请先选择套号与部位'}
          </Text>
          {!state.selection.setId ? (
            <View className='worker-report__sets' data-testid='worker-report-sets'>
              {(state.view?.needs_selection ?? []).map((set, index) => (
                <Button
                  key={set.set_id}
                  className='worker-report__set'
                  data-testid={`worker-report-set-${index}`}
                  onClick={() => setState((prev) => pickSet(prev, set.set_id, set.set_no))}
                >
                  第 {set.set_no ?? index + 1} 套
                </Button>
              ))}
            </View>
          ) : (
            <View className='worker-report__positions' data-testid='worker-report-positions'>
              {(currentSet?.positions ?? []).map((position, index) => (
                <Button
                  key={position.order_item_id}
                  className='worker-report__position'
                  data-testid={`worker-report-position-${index}`}
                  onClick={() => {
                    const next = pickPosition(state, position.order_item_id, position.position_name)
                    setState(next)
                    const selection = legacySelection(next)
                    if (selection) void resolve(token, { selection })
                  }}
                >
                  {position.position_name || position.position_kind || MISSING}
                </Button>
              ))}
            </View>
          )}
        </View>
      ) : null}

      {state.mode === 'main' && state.view ? (
        <View className='worker-report__card' data-testid='worker-report-card'>
          <Text className='worker-report__set' data-testid='worker-report-title'>
            {titleText(state.view)}
          </Text>
          <Text className='worker-report__line' data-testid='worker-report-kind'>
            帘种：{kindText(state.view)}
          </Text>
          <Text className='worker-report__line' data-testid='worker-report-progress'>
            {progressText(state.view)}
          </Text>

          {state.view.operation ? (
            <>
              <Text className='worker-report__op' data-testid='worker-report-operation'>
                {operationName(state.view.operation)}
              </Text>
              <Text className='worker-report__line' data-testid='worker-report-qty'>
                应做 {qtyText(state.view.operation.qty)} {state.view.operation.unit || ''}
              </Text>
            </>
          ) : (
            <Text className='worker-report__notice' data-testid='worker-report-no-operation'>
              {state.view.completed
                ? '本套工序都已报工'
                : state.view.worker_operation
                  ? `你的工序是「${state.view.worker_operation}」：本件没有可报的这道工序`
                  : '本部位推断不出待报工序（工序未确定 ⇒ 不得记账）'}
            </Text>
          )}

          {state.receipt ? (
            <Text className='worker-report__receipt' data-testid='worker-report-receipt'>
              {state.receipt}
            </Text>
          ) : null}

          {showPicker ? (
            <View className='worker-report__picker' data-testid='worker-report-picker'>
              <Text className='worker-report__hint'>选工序（点哪道就报哪道）</Text>
              {candidates.map((candidate, index) => (
                <Button
                  key={candidate!.operation_id}
                  className={
                    candidate!.operation_id === state.view?.operation?.operation_id
                      ? 'worker-report__choice is-on'
                      : 'worker-report__choice'
                  }
                  data-testid={`worker-report-choice-${index}`}
                  onClick={() => {
                    if (candidate!.operation_id === state.view?.operation?.operation_id) return
                    void resolve(token, { operationId: candidate!.operation_id })
                  }}
                >
                  {operationName(candidate!)}
                </Button>
              ))}
            </View>
          ) : null}

          {state.view.batch_required ? (
            <View className='worker-report__batch' data-testid='worker-report-batch'>
              <Text className='worker-report__hint'>裁剪批次（按派工批次填，必须能对上库存）</Text>
              <Input
                className='worker-report__input'
                data-testid='worker-report-batch-input'
                value={state.batchNo ?? state.view.batch_no ?? ''}
                onInput={(event) => {
                  const value = (event as any)?.detail?.value ?? ''
                  setState((prev) => ({ ...prev, batchNo: String(value) }))
                }}
              />
            </View>
          ) : null}

          {canReport(state) ? (
            <View className='worker-report__worktype' data-testid='worker-report-worktype'>
              <Text className='worker-report__hint'>这一笔</Text>
              {WORK_TYPES.map((type) => (
                <Button
                  key={type}
                  className={
                    state.workType === type
                      ? 'worker-report__choice is-on'
                      : 'worker-report__choice'
                  }
                  data-testid={`worker-report-worktype-${type}`}
                  onClick={() => setState((prev) => ({ ...prev, workType: type as WorkType }))}
                >
                  {WORK_TYPE_LABELS[type]}
                </Button>
              ))}
            </View>
          ) : null}

          {state.error ? (
            <Text className='worker-report__error' data-testid='worker-report-error'>
              {state.error}
            </Text>
          ) : null}

          {canReport(state) ? (
            <Button
              className='worker-report__primary'
              data-testid='worker-report-submit'
              disabled={state.submitting}
              onClick={() => {
                void submit()
              }}
            >
              {state.submitting ? REPORTING_TEXT : REPORT_BUTTON_TEXT}
            </Button>
          ) : null}

          <Button className='worker-report__ghost' data-testid='worker-report-rescan' onClick={rescan}>
            再扫一张
          </Button>
        </View>
      ) : null}

      {phaseError && state.mode === 'scan' ? (
        <View className='worker-report__notice' data-testid='worker-report-phase-error'>
          <Text className='worker-report__error'>{phaseError}</Text>
        </View>
      ) : null}
      {message ? <Text className='worker-report__line'>{message}</Text> : null}
    </View>
  )
}
