// case_ids: MC-226
/**
 * 工人端**精裁清单**页（issue #7813 P2b）—— 工人菜单页的一条行卡：`pages/worker/cut-plan/index`。
 *
 * ## 这一页回答什么
 *
 * 「这一套每一樘，**裁多长（米）× 几片**，用料多少，从哪一批裁」—— 数据**只**来自服务端扫码
 * 解析响应里的 `set_overview.cut_plan`（后端唯一实现 `ProcessingSetReadService`，与商家端
 * 加工单详情**同一份**）。端侧**不算法、不做单位换算**。
 *
 * ## 搬迁口径（`/w/` 的区块 → 小程序的一条入口）
 *
 * `/w/` 里它是报工屏上的一个区块（`render.mjs` 的 `cutPlanView`，issue #5693）；本页把它提成
 * **独立读面**（`/w/` 一字未动，P2c 才收口）。逐条搬过来的三条渲染纪律：
 *
 * 1. 🔴 **缺值不渲染假数据**：`panel_count` / `panel_length_m` 任一为 `null` ⇒ 该项 `—`
 *    （**不显示 0 / 1**）；`missing_reason` 只在真缺时出现一行小字。
 * 2. 🔴 `cut_plan` 缺失 / 非数组 / 为空 ⇒ **整块不出现**，改由**具名空态**说清为什么（不吞）。
 * 3. 🔴 派工指定批次（issue #6754）+ 从该批裁多少（issue #7722）：未指派 ⇒ 这一格**不渲染**
 *    （工人端不摆「批次 —」这种空占位）。
 *
 * ## `/w/` 四条硬约束在本页的落点
 *
 * - ① **旧码 ⇒ 进 select 态，绝不默认取第 1 套**：本页先经扫码解析，`granularity:'order'`
 *   ⇒ 只出「选套 / 选部位」两块，**一个裁片都不显示**；选完（两截齐全）才重新解析取这一套的清单。
 *   红证 = 把 `applyReadScan` 的 `mode` 分支改成恒 `ready` ⇒ 判据当场红。
 * - ② 工序未确定（`operation == null`）⇒ **不得出现报工按钮**：本页只有「去报工」这条**导航**
 *   （不是报工按钮），并在该情形下明说为什么没有动作（`operationNotReadyHint`）。
 * - ③ 未登录 ⇒ 不得出现报工按钮：未登录时连扫码块都不渲染。
 * - ④ 前端不猜：交给报工页的**只有码**（不顺手塞套 / 工序）。
 *
 * ## 边界（照实登记）
 *
 * - **只读**：本页没有写动作（不报工、不改批次）。P2b 的口径 =「一条入口 + 读面复用」。
 * - 入口显隐键 = `cut_calc`（工人档案里「裁高计算」那一项）：后端闭词表里**没有**独立的
 *   「精裁清单」键，而本单**零后端改动** ⇒ 两个裁床读面共用同一个开关。
 *   重启条件 = 后端 `WorkerPages` 出现独立键时拆分（PR body 已登记）。
 */
import { useCallback, useEffect, useState } from 'react'
import Taro from '@tarojs/taro'
import { Button, Text, View } from '@tarojs/components'
import { scanResolve, type ScanSelection } from '../../../services/productionService'
import { fetchCurrentWorker } from '../../../services/workerService'
import { clearWorkerSession, hasWorkerSession } from '../../../utils/workerSession'
import {
  CUT_PLAN_WORKER_LOGIN_REQUIRED,
  REPORT_PAGE_ROUTE,
  WORKER_LOGIN_ROUTE,
} from '../../../utils/inbound/gaps'
import { resolveScanLanding } from '../../../utils/scanInput'
// 🔴 h5 里没有原生扫码（Taro 侧只在微信内可用）⇒ 本文件必须有**显式平台分支**，
// 否则「点了没反应」是静默失败（守卫 tests/h5-platform-api-guard.test.ts）。
import { canUseNativeScan } from '../../../utils/platform'
import {
  CUT_PLAN_EMPTY_HINT,
  READ_ONLY_NOTICE,
  applyReadScan,
  cutPlanRows,
  operationNotReadyHint,
  operationText,
  pieceText,
  readFaceInitial,
  readPickPosition,
  readPickSet,
  reportHandoffUrl,
  textOr,
  type ReadFaceState,
  type ReadFaceWorker,
} from '../../../utils/workerReadFaces'
import { WorkerReadLegacyPicker, WorkerReadScanEntry } from '../../../components/WorkerReadEntry'
import { WorkerBackLink } from '../../../components/WorkerBackLink'
import './index.scss'

/** 页面标题（与商家端「精裁清单」同一件事，工人这里说的是同一句话）。 */
export const CUT_PLAN_TITLE = '精裁清单'

/** 读不到时的兜底（技术原文留在请求层）。 */
export const CUT_PLAN_READ_FAILED_HINT = '读取精裁清单失败，请重试'

export default function WorkerCutPlanPage() {
  const workerReady = hasWorkerSession()
  const [state, setState] = useState<ReadFaceState>(() => readFaceInitial(null))
  const [manual, setManual] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
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

  const resolve = useCallback(
    async (raw: string, selection: ScanSelection | null = null) => {
      const code = String(raw ?? '').trim()
      if (code === '') return
      setBusy(true)
      setMessage('')
      const res = await scanResolve(code, undefined, selection)
      setBusy(false)
      if (res.success && res.data) {
        setToken(code)
        setState((prev) => applyReadScan(prev, res.data!))
        return
      }
      if (res.statusCode === 401) {
        clearWorkerSession()
        setState({ ...readFaceInitial(null), mode: 'unauthorized' })
        return
      }
      setMessage(res.message || CUT_PLAN_READ_FAILED_HINT)
    },
    [],
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

  const rows = cutPlanRows(state.view)
  const operationHint = operationNotReadyHint(state.view)
  const unauthorized = state.mode === 'unauthorized'

  return (
    <View className='worker-cut-plan'>
      <View className='worker-cut-plan__header'>
        <WorkerBackLink />
        <Text className='worker-cut-plan__title'>{CUT_PLAN_TITLE}</Text>
        {state.worker ? (
          <Text className='worker-cut-plan__worker' data-testid='worker-cut-plan-worker'>
            当前工人：{textOr(state.worker.worker_name)}
          </Text>
        ) : null}
      </View>

      {unauthorized ? (
        <View className='worker-cut-plan__gate' data-testid='worker-cut-plan-login-required'>
          <Text className='worker-cut-plan__notice'>{CUT_PLAN_WORKER_LOGIN_REQUIRED}</Text>
          <Button
            className='worker-cut-plan__action'
            data-testid='worker-cut-plan-login'
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
          prefix='worker-cut-plan'
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

      {!unauthorized && message !== '' ? (
        <View className='worker-cut-plan__gate' data-testid='worker-cut-plan-read-failed'>
          <Text className='worker-cut-plan__notice'>{message}</Text>
          <Button
            className='worker-cut-plan__action'
            data-testid='worker-cut-plan-retry'
            onClick={() => {
              setState((prev) => ({ ...prev, view: null, mode: 'scan', notice: null }))
              setMessage('')
            }}
          >
            重新扫码
          </Button>
        </View>
      ) : null}

      {state.mode === 'select' ? (
        <WorkerReadLegacyPicker
          prefix='worker-cut-plan'
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
        <View className='worker-cut-plan__card' data-testid='worker-cut-plan-card'>
          <Text className='worker-cut-plan__piece' data-testid='worker-cut-plan-piece'>
            {pieceText(state.view)}
          </Text>
          <Text className='worker-cut-plan__line' data-testid='worker-cut-plan-operation'>
            本道工序：{operationText(state.view.operation)}
          </Text>
          {operationHint ? (
            <Text className='worker-cut-plan__notion' data-testid='worker-cut-plan-operation-hint'>
              {operationHint}
            </Text>
          ) : null}

          {rows.length > 0 ? (
            <View className='worker-cut-plan__rows' data-testid='worker-cut-plan-rows'>
              {rows.map((row) => (
                <View className='worker-cut-plan__row' key={row.key} data-testid='worker-cut-plan-row'>
                  <Text className='worker-cut-plan__size'>{row.size}</Text>
                  <Text className='worker-cut-plan__name'>{row.name}</Text>
                  <Text className='worker-cut-plan__meters'>{row.meters}</Text>
                  {row.batch ? (
                    <Text className='worker-cut-plan__batch' data-testid='worker-cut-plan-batch'>
                      {row.batch}
                    </Text>
                  ) : null}
                  {row.reason ? (
                    <Text className='worker-cut-plan__reason' data-testid='worker-cut-plan-reason'>
                      {row.reason}
                    </Text>
                  ) : null}
                </View>
              ))}
            </View>
          ) : (
            <Text className='worker-cut-plan__hint' data-testid='worker-cut-plan-empty'>
              {CUT_PLAN_EMPTY_HINT}
            </Text>
          )}

          <Text className='worker-cut-plan__hint'>{READ_ONLY_NOTICE}</Text>
          <Button
            className='worker-cut-plan__action'
            data-testid='worker-cut-plan-report'
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
