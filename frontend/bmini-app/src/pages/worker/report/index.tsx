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
 * ③ 未登录 ⇒ **不出报工按钮**，**就地**给与终端 `/w/` 逐字一致的登录表单（issue #8194：
 *    不再跳三角色登录页 —— 手里那个码不绕路、扫码这一步不被别的页面打断）；
 * ④ 回执 ⇒ 只显示服务端给的「下一道 / 本套已完成」，**前端不猜下一道**。
 *
 * ## 微信 A 档「扫普通链接二维码打开小程序」（issue #8196）
 *
 * 纸上的码 `https://app.migaozn.com/s/<短码>` 永不变（已印出去不可重印）。H5 靠服务端 302 落到
 * `/b/?t=<token>`；小程序里微信把整条链接放进 `getEnterOptionsSync().query.q`，而**小程序不跟随
 * 302** ⇒ `/s/<短码>` 这一支先经短链 JSON 面（`GET /s/<短码>/json`）换 token，再走本页既有流程
 * （未登录 ⇒ 就地登录，登录后继续手里的码）。未知 / 已撤销的码**明确报错**、不重试；读不到时
 * 退回既有行为（短码原样交给工人扫码端点 —— `ProductionScanService` 本来就认短码）。
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
import { fetchCurrentWorker, workerLogin } from '../../../services/workerService'
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
import { WORKER_HOME_ROUTE } from '../../../utils/inbound/gaps'
// 🔴 入口参数的提取**不在本页判平台**（issue #7879）：h5 读 URL search、小程序读
// `getEnterOptionsSync()` / 页面参数，两条都收口到 `utils/scanInput.ts` 的同一个解析器
import {
  currentEntryLanding,
  rememberReportReturn,
  takeReportReturn,
} from '../../../utils/reportEntry'
// 🔴 未登录**就地**登录（issue #8194）：表单 = 与终端 `/w/` 逐字一致的共享组件
// （判据 tests/worker-login-parity.test.ts）。本页不再跳三角色登录页。
import WorkerLoginForm, {
  WORKER_LOGIN_FAILED_FALLBACK,
  type WorkerLoginSubmitResult,
  type WorkerLoginValues,
} from '../../../components/WorkerLoginForm'
import { resolveScanLanding } from '../../../utils/scanInput'
// 🔴 短链 JSON 面（issue #8196）：A 档「扫普通链接二维码打开小程序」里微信把整条链接放进 `q`，
// 而**小程序不跟随 302** ⇒ `/s/<短码>` 这一支要先换 token（服务端 `GET /s/{短码}/json`）。
// 只有这一份调用点（前端不许再拼第二份「短码 ⇒ token」的映射）。
import {
  WORKER_SHORT_LINK_INVALID_HINT,
  resolveWorkerShortLink,
} from '../../../services/workerShortLinkService'
// 🔴 小程序专有 API 的 h5 出路（守卫 tests/h5-platform-api-guard.test.ts）：h5 产物里没有
// 原生扫码 ⇒ 不摆「扫一扫」按钮，手输码这条降级路径仍然可用（不是把页面弄死）。
import { canUseNativeScan } from '../../../utils/platform'
import './index.scss'

/** 读面失败兜底（技术原文留在请求层）。 */
export const RESOLVE_FAILED_HINT = '扫码结果读取失败，请重试'

/** 手输提示。 */
export const MANUAL_HINT = '输码（短码 / 加工单号 / 订单号）'

/**
 * 没有码落地时先给的那句话（2026-10-27 用户裁定，issue #7920）：
 * 「把工人菜单页面的扫码报工菜单移除掉，直接用其他 app 的扫一扫功能替代」
 * ⇒ 本页是**扫码的落地面**（服务端 302 → `/b/?t=`），不再自己发起扫码；
 * 页面要先把「怎么到这一页」说清楚，手输只是标签磨花时的兜底（不是首屏主语）。
 *
 * 小程序端**不渲染**它：端内有原生「扫一扫」（`canUseNativeScan()`），没有"其他 app"这回事。
 */
export const SCAN_ENTRY_HINT = '请用微信「扫一扫」或手机相机扫一扫纸上的二维码'

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
  /**
   * 入口解码后的码（issue #8196）：A 档 `q=/s/<短码>` ⇒ **token**；其余入口形态原样。
   * 入口效果只写它，页面别的分支只读 —— 免得每处都自己再看一遍入口参数（两处推导必然漂）。
   */
  const [entryCode, setEntryCode] = useState('')
  /** 入口本身不可用（未知 / 已撤销的码）：明确上屏，不进报工流程、不重试 */
  const [entryError, setEntryError] = useState('')
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
   * 🔴 **入口解码**（issue #8196）：A 档「扫码」在小程序里拿到的是 `getEnterOptionsSync().query.q`
   * （整条链接 URL-encoded），而**小程序不跟随服务端 302** ⇒ `/s/<短码>` 这一支必须先用短链 JSON
   * 面换回 token（`GET /s/{短码}/json`）。
   *
   * 三种结局，都是**有界**的（`entryResolvedRef` 保证只读一次入口、只解析一次，错误态不重试）：
   * ① 换到 token ⇒ 走下面的既有报工流程（未登录则先就地登录，登录后继续）；
   * ② 未知 / 已撤销（404 / 410）⇒ 明确错误上屏（不必等工人填完 PIN 才说「码坏了」）；
   * ③ 读不到（离线 / 旧后端没有这条路径）⇒ 退回既有行为：短码原样交给工人扫码端点
   *    （`ProductionScanService` 本来就认短码）—— **已印出去的码不能因为新版前端而作废**。
   *
   * 其余入口形态（`…/b/report/?t=<token>`、页面参数 `t`、无码）**原样**，行为与改前逐字一致。
   */
  const entryResolvedRef = useRef(false)
  useEffect(() => {
    if (entryResolvedRef.current) return
    entryResolvedRef.current = true
    const landing = currentEntryLanding()
    if (landing.kind !== 'report' || landing.code === '') return
    if (landing.from !== 'link-qr-short') {
      setEntryCode(landing.code)
      return
    }
    void resolveWorkerShortLink(landing.code).then((res) => {
      if (res.success && res.data) {
        setEntryCode(res.data.token)
        return
      }
      if (res.statusCode === 404 || res.statusCode === 410) {
        setEntryError(WORKER_SHORT_LINK_INVALID_HINT)
        return
      }
      setEntryCode(landing.code)
    })
  }, [])

  /**
   * 🔴 **入口即解析**（issue #7879）：h5 启动器 `redirectTo` 带 `?t=<token>`、小程序冷启动的
   * `query.q`（A 档「扫普通链接二维码打开小程序」）/ `query.scene`（B 档小程序码）—— 三条都经
   * `currentEntryLanding()` 归一 ⇒ 工人扫码后**不必再手输一次**。
   *
   * 只消费返回值（页面里**不判平台**）；身份未就绪时先等（上面的身份 effect 会把它设成
   * `scan` / `unauthorized`）。未登录时**就地**登录（下面的 `signIn`），登录成功后由它接着解析。
   * 手里的码 = `entryCode`（A 档已换过 token；其余形态原样）。
   */
  const entryDoneRef = useRef(false)
  useEffect(() => {
    if (entryDoneRef.current) return
    if (entryCode === '') return
    if (state.mode === 'unauthorized' || !state.worker) return
    entryDoneRef.current = true
    void resolve(entryCode)
  }, [entryCode, state.mode, state.worker, resolve])

  /**
   * 🔴 **未登录 + 手里有码 ⇒ 先记下「登录后接着报这个码」**（issue #8194）：走
   * `utils/reportEntry.ts` 的**同一份**一次性记录（不是第二套待报码通道）——
   * 工人填 PIN 期间页面被系统回收 / 刷新，码不会丢；登录成功后由下面的 `signIn` 读回（读到即清）。
   *
   * issue #8196：记的是**入口解码后的码**（A 档 = token）—— 死码（404 / 410）不记，
   * 免得登录成功后白解析一次、再给一遍同样的错误。
   */
  useEffect(() => {
    if (state.mode !== 'unauthorized') return
    if (entryCode === '') return
    rememberReportReturn(entryCode)
  }, [state.mode, entryCode])

  /**
   * 未登录 ⇒ **就地**登录（issue #8194；不再跳三角色登录页）。
   *
   * 表单 = 共享组件 `WorkerLoginForm`（与终端 `/w/` 逐字一致，判据 `tests/worker-login-parity.test.ts`）。
   * 成功后**留在本页**继续手里的那个码；无码 ⇒ 回工人首页（不在报工页留一个空壳）。
   */
  const signIn = useCallback(
    async (values: WorkerLoginValues): Promise<WorkerLoginSubmitResult> => {
      // 设备标签不传：`/w/` 没有那一格
      const res = await workerLogin(
        values.workerNo,
        values.pin,
        undefined,
        values.enterpriseCode,
      )
      if (!res.success) {
        return { ok: false, message: res.message || WORKER_LOGIN_FAILED_FALLBACK }
      }
      // 登录已签发工人 session ⇒ 读回服务端认定的身份（页头的「当前工人」是计件凭证，不自己拼）
      const current = await fetchCurrentWorker()
      if (!current.success || !current.data) {
        clearWorkerSession()
        return { ok: false, message: '登录已成功，但没能读到工人身份，请再试一次' }
      }
      setState(initialState(current.data as CurrentWorker))
      // 一次性记录读回（读到即清）；存储写失败时退回入口解码后的码（码不能因为记不住就丢）
      const back = takeReportReturn()
      const code = back.code || entryCode
      // 上面那条入口 effect 不得再解析一次（同一个码只递一次服务端）
      entryDoneRef.current = true
      if (code) {
        await resolve(code)
      } else {
        Taro.redirectTo({ url: WORKER_HOME_ROUTE })
      }
      return { ok: true, workerName: res.data?.worker_name ?? null }
    },
    [entryCode, resolve],
  )

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
      {/* 🔴 未登录**不渲染页头**（2026-10-31 用户裁定，issue #8194）：终端 `/w/` 的登录屏只有
          一张卡片（`loginView()` = `.wh5-card`），页头是**登录后**的页面身份 —— 若这里照样印
          「扫码报工」，小程序扫码进入时就变成「扫码报工」+「工人报工」两层标题，与 APK / `/w/` 不一致。
          登录成功（`state.worker` 就绪）后页头出现。 */}
      {state.mode === 'unauthorized' ? null : (
        <View className='worker-report__header' data-testid='worker-report-header'>
          <Text className='worker-report__title'>扫码报工</Text>
          {state.worker ? (
            <Text className='worker-report__worker' data-testid='worker-report-worker'>
              当前工人：{state.worker.worker_name || MISSING}
            </Text>
          ) : null}
        </View>
      )}

      {/* 🔴 入口本身不可用（issue #8196：未知 / 已撤销的短码）⇒ **明确**说清「码没了、下一步怎么办」。
          未登录时它与登录表单同屏（回到工人登录，不白屏）；登录后它与手输码同在（还能手输别的单号）。
          错误态**不重试**（`entryResolvedRef` 保证入口只解析一次）。 */}
      {entryError ? (
        <View className='worker-report__notice' data-testid='worker-report-entry-error'>
          <Text className='worker-report__error'>{entryError}</Text>
        </View>
      ) : null}

      {state.mode === 'unauthorized' ? (
        <View className='worker-report__login' data-testid='worker-report-login-required'>
          <WorkerLoginForm onSubmit={signIn} />
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
          {canUseNativeScan() ? null : (
            <Text className='worker-report__hint' data-testid='worker-report-scan-entry-hint'>
              {SCAN_ENTRY_HINT}
            </Text>
          )}
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
