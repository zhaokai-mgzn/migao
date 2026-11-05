// case_ids: MC-222
/**
 * 工人端**裁高计算**页（issue #7813 P2b）—— 工人菜单页的一条行卡：`pages/worker/cut-calc/index`。
 *
 * ## 这一页回答什么
 *
 * 「这一樘帘的成品高，机器屏上该输多少」—— 数据源 = `GET /api/worker/production/cutting-height`
 * （与 H5 机台屏 `/w/machine.html` **同一个端点、同一份服务端计算**：复用商家端
 * `CuttingHeightConfigService#preview`，端侧**不重算命中**）。
 *
 * ## 搬迁口径（`/w/` → 小程序，**只搬读面**）
 *
 * | `/w/` 的形态 | 本页 |
 * |---|---|
 * | 一体机常驻屏 + 有线扫码枪（`createScanBuffer`，全页无文本输入） | 手机上的**一条入口**：扫一扫 / 手输码（`WorkerReadScanEntry`） |
 * | 大字「请在机器屏输入 X.XXX 米」+ 命中项 + 未配置取值 + 缺值说明 | **逐条搬**（同一句口径、同一份格式化） |
 * | 【完成】= 报工（`POST .../scan/complete`） | **不搬**：本页只读，「去报工」只把**码**交给报工页 |
 * | 裁高计算器的手改（勾选命中项，只改本次显示） | **不搬**（如实登记：本页只显示系统值；手改不落库、不影响记账，P2c 另议） |
 * | 未登录只显示「请先用工号 + PIN 登录」 | 给**可点的**去登录入口（`WORKER_LOGIN_ROUTE`），登录回来接着扫 |
 *
 * ## `/w/` 四条硬约束在本页的落点（判据见 `tests/worker-read-faces.test.ts` 与
 * `tests/worker-cut-calc-page.test.tsx`）
 *
 * - ② 工序未确定 ⇒ 不得出现报工按钮：本页**一个报工按钮都没有**（读面自带这句话）；
 * - ③ 未登录 ⇒ 不得出现报工按钮：未登录时**连扫码按钮都没有**（只有去登录），红证 = 把扫码块
 *   渲染条件改成恒真 ⇒ 红；
 * - ④ 前端不猜：给报工页只交**这次扫到的码**（`reportHandoffUrl`），不交部位 / 工序。
 *
 * ## 边界（照实登记）
 *
 * - 不写机器（2026-09-29 用户裁定①）：本页终点是「给人一个可核对的数」，下发在机器屏上由人完成。
 * - 不记报工：报工仍只在报工页（写入口单一实现，见 `production-single-write-entry`）。
 */
import { useCallback, useEffect, useState } from 'react'
import Taro from '@tarojs/taro'
import { Button, Text, View } from '@tarojs/components'
import { fetchCuttingHeight } from '../../../services/workerCutService'
import { fetchCurrentWorker } from '../../../services/workerService'
import { clearWorkerSession, hasWorkerSession } from '../../../utils/workerSession'
import {
  CUT_CALC_WORKER_LOGIN_REQUIRED,
  REPORT_PAGE_ROUTE,
  WORKER_LOGIN_ROUTE,
} from '../../../utils/inbound/gaps'
import { resolveScanLanding } from '../../../utils/scanInput'
// 🔴 h5 里没有原生扫码（Taro 侧只在微信内可用）⇒ 本文件必须有**显式平台分支**，
// 否则「点了没反应」是静默失败（守卫 tests/h5-platform-api-guard.test.ts）。
import { canUseNativeScan } from '../../../utils/platform'
import {
  READ_ONLY_NOTICE,
  cutBatchBlockedText,
  cutHeightDetailRows,
  cutHeightPosition,
  cutHeightPositions,
  cutHeightText,
  cutHitRows,
  reportHandoffUrl,
  scannedPositionIndex,
  textOr,
  unresolvedRows,
  type CutHeightData,
  type ReadFaceWorker,
} from '../../../utils/workerReadFaces'
import { WorkerReadScanEntry } from '../../../components/WorkerReadEntry'
import { WorkerBackLink } from '../../../components/WorkerBackLink'
import './index.scss'

/** 页面标题（与 `/w/` 机台屏同一句话：2026-10-10 用户裁定「屏上/入口一律叫『裁高计算』」）。 */
export const CUT_CALC_TITLE = '裁高计算'

/** 读不到时的兜底（技术原文留在请求层）。 */
export const CUT_CALC_READ_FAILED_HINT = '读取裁高失败，请重试'

/** 页面的四种状态（互斥）。 */
export type CutCalcPhase = 'unauthorized' | 'scan' | 'loading' | 'error' | 'ready'

export default function WorkerCutCalcPage() {
  const workerReady = hasWorkerSession()
  const [worker, setWorker] = useState<ReadFaceWorker | null>(null)
  const [phase, setPhase] = useState<CutCalcPhase>('unauthorized')
  const [manual, setManual] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [data, setData] = useState<CutHeightData | null>(null)
  const [positionIndex, setPositionIndex] = useState(0)
  /** 这次读的码（「去报工」只交它 —— 前端不猜套 / 工序） */
  const [token, setToken] = useState('')

  useEffect(() => {
    if (!workerReady) {
      setPhase('unauthorized')
      return
    }
    void (async () => {
      const res = await fetchCurrentWorker()
      if (res.success && res.data) {
        setWorker(res.data as ReadFaceWorker)
        setPhase('scan')
        return
      }
      // 身份读不到（401 / 闲置超时）⇒ 清本机并回未登录（绝不按上一个人看待这一屏）
      clearWorkerSession()
      setWorker(null)
      setPhase('unauthorized')
    })()
  }, [workerReady])

  const load = useCallback(async (raw: string) => {
    const code = String(raw ?? '').trim()
    if (code === '') return
    setBusy(true)
    setMessage('')
    setPhase('loading')
    const res = await fetchCuttingHeight(code)
    setBusy(false)
    if (res.success && res.data) {
      setToken(code)
      setData(res.data)
      setPositionIndex(scannedPositionIndex(res.data))
      setPhase('ready')
      return
    }
    if (res.statusCode === 401) {
      clearWorkerSession()
      setWorker(null)
      setPhase('unauthorized')
      return
    }
    setData(null)
    setMessage(res.message || CUT_CALC_READ_FAILED_HINT)
    setPhase('error')
  }, [])

  const scan = useCallback(async () => {
    // 没有原生扫码能力的端（h5 非微信浏览器）不发起调用：屏上早已只留手输码这一条路
    // （按钮本身也不渲染，见 WorkerReadScanEntry），这里是第二道（fail-closed）。
    if (!canUseNativeScan()) return
    try {
      const result = await Taro.scanCode({ scanType: ['qrCode', 'barCode'] })
      const code = resolveScanLanding({ text: (result as any)?.result }).code
      if (code) await load(code)
    } catch {
      // 用户取消扫码不是错误（小程序会 reject）—— 什么都不做，别弹红字
    }
  }, [load])

  const position = cutHeightPosition(data, positionIndex)
  const positions = cutHeightPositions(data)
  const batchBlocked = cutBatchBlockedText(data)
  const unresolved = unresolvedRows(position)
  const details = cutHeightDetailRows(position)
  const hits = cutHitRows(position)

  return (
    <View className='worker-cut-calc'>
      <View className='worker-cut-calc__header'>
        <WorkerBackLink />
        <Text className='worker-cut-calc__title'>{CUT_CALC_TITLE}</Text>
        {worker ? (
          <Text className='worker-cut-calc__worker' data-testid='worker-cut-calc-worker'>
            当前工人：{textOr(worker.worker_name)}
          </Text>
        ) : null}
      </View>

      {phase === 'unauthorized' ? (
        <View className='worker-cut-calc__gate' data-testid='worker-cut-calc-login-required'>
          <Text className='worker-cut-calc__notice'>{CUT_CALC_WORKER_LOGIN_REQUIRED}</Text>
          <Button
            className='worker-cut-calc__action'
            data-testid='worker-cut-calc-login'
            onClick={() => {
              void Taro.navigateTo({ url: WORKER_LOGIN_ROUTE })
            }}
          >
            去登录工人身份
          </Button>
        </View>
      ) : null}

      {phase === 'scan' || phase === 'loading' ? (
        <WorkerReadScanEntry
          prefix='worker-cut-calc'
          manual={manual}
          onManualChange={setManual}
          onScan={() => {
            void scan()
          }}
          onResolve={() => {
            void load(manual)
          }}
          busy={busy}
        />
      ) : null}

      {phase === 'error' ? (
        <View className='worker-cut-calc__gate' data-testid='worker-cut-calc-read-failed'>
          <Text className='worker-cut-calc__notice'>{message || CUT_CALC_READ_FAILED_HINT}</Text>
          <Button
            className='worker-cut-calc__action'
            data-testid='worker-cut-calc-retry'
            onClick={() => {
              setPhase('scan')
              setMessage('')
            }}
          >
            重新扫码
          </Button>
        </View>
      ) : null}

      {phase === 'ready' ? (
        <View className='worker-cut-calc__card' data-testid='worker-cut-calc-card'>
          <Text className='worker-cut-calc__order' data-testid='worker-cut-calc-order'>
            {textOr(data?.order?.processing_order_no ?? data?.order?.order_no)}
            {data?.order?.set_no === null || data?.order?.set_no === undefined
              ? ''
              : ` · 第 ${data.order.set_no} 套`}
          </Text>

          {positions.length > 1 ? (
            <View className='worker-cut-calc__tabs' data-testid='worker-cut-calc-tabs'>
              {positions.map((item, index) => (
                <Button
                  key={String(item.order_item_id ?? index)}
                  className='worker-cut-calc__tab'
                  data-testid={`worker-cut-calc-tab-${index}`}
                  onClick={() => setPositionIndex(index)}
                >
                  {textOr(item.position_name ?? item.position_kind)}
                </Button>
              ))}
            </View>
          ) : null}

          <Text className='worker-cut-calc__big' data-testid='worker-cut-calc-height'>
            {cutHeightText(position)}
          </Text>

          {details.map((row) => (
            <View className='worker-cut-calc__row' key={row.label}>
              <Text className='worker-cut-calc__label'>{row.label}</Text>
              <Text className='worker-cut-calc__value'>{row.value}</Text>
            </View>
          ))}

          {hits.length > 0 ? (
            <View className='worker-cut-calc__hits' data-testid='worker-cut-calc-hits'>
              <Text className='worker-cut-calc__section'>命中项（{hits.length}）</Text>
              {hits.map((hit) => (
                <View className='worker-cut-calc__row' key={hit.key}>
                  <Text className='worker-cut-calc__label'>{hit.name}</Text>
                  <Text className='worker-cut-calc__value'>
                    {hit.direction}
                    {hit.value}
                  </Text>
                </View>
              ))}
            </View>
          ) : (
            <Text className='worker-cut-calc__hint' data-testid='worker-cut-calc-hits-empty'>
              本部位没有命中的增量项：裁高就是成品高
            </Text>
          )}

          {unresolved.length > 0 ? (
            <Text className='worker-cut-calc__warn' data-testid='worker-cut-calc-unresolved'>
              {unresolved.join(' / ')}：未配置取值，不计入、也不算 0
            </Text>
          ) : null}

          {batchBlocked ? (
            <Text className='worker-cut-calc__warn' data-testid='worker-cut-calc-batch'>
              {batchBlocked}
            </Text>
          ) : null}

          <Text className='worker-cut-calc__hint'>{READ_ONLY_NOTICE}</Text>
          <Button
            className='worker-cut-calc__action'
            data-testid='worker-cut-calc-report'
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
