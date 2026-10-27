// case_ids: BM-034
/**
 * 工人**返工记录**页（issue #7921）—— 工人工作台的一条入口：`pages/worker/rework/index`。
 *
 * ## 这一页回答什么
 *
 * 「哪些加工单报过返工、返了几笔、返在哪道工序」。数据源 = `GET /api/worker/production/rework-orders`
 * （#7860 上线；`ProductionReworkService.reworkOrders`）—— 与 H5 `/w/rework.html` **同一个端点、
 * 同一份服务端聚合**：一行 = 一张加工单，行内给返工笔数 / 数量 / 最近返工 / 原因 / 涉及工序。
 *
 * ## 四条纪律（每条都能单独变红）
 *
 * 1. 🔴 **前端不聚合、不排序、不补算**：服务端给几行就渲染几行，`rework_count` / `operations`
 *    逐值照用（端侧自己再算一遍 = 第二份返工口径，与 H5 `/w/` 那一份迟早分叉）。
 * 2. 🔴 **五种状态互斥、各有稳定 testID**：读取中 / 读不到（可重试）/ 未登录（去登录）/
 *    **档案未开「返工记录」页**（403，可行动）/ 读到了（空态或列表）。
 *    「读不到」与「没有返工」是两个事实（前者可能只是网差，工人据此决定要不要等）。
 * 3. 🔴 **403 不当故障**：工人档案页面集里没有 `rework` 键 ⇒ 说清「找管理员勾选『返工记录』」，
 *    **不**冒充「没有返工」、**不**让工人反复点重试。
 * 4. 🔴 **缺值不编造**：`null` / 空串 ⇒ `—` 或整项不渲染；**不**印 `0 笔`（那是替服务端断言
 *    「一次都没返工」——与「服务端没给」是两件事）。
 *
 * ## 与工作台入口的关系（issue #7921）
 *
 * 显隐由工人档案的 `rework` 页面键决定（`utils/workerMenu.ts` 的 `REWORK_PAGE_KEY`，
 * 商家面名字「返工记录」，见 `WorkerPages.optionalPages()`）。入口显隐 ≠ 访问拦截：
 * 直接打开本页照旧可用，服务端仍按同一套页面集准入（403 由本页呈现）。
 */
import { useCallback, useEffect, useState } from 'react'
import Taro from '@tarojs/taro'
import { Button, Text, View } from '@tarojs/components'
import { fetchCurrentWorker } from '../../../services/workerService'
import {
  listWorkerReworkOrders,
  type WorkerReworkOperation,
  type WorkerReworkOrder,
  type WorkerReworkOrdersPage,
} from '../../../services/workerReworkService'
import { WORKER_TAB_LOGIN_ROUTE } from '../../../utils/inbound/gaps'
import { clearWorkerSession, hasWorkerSession, type CurrentWorker } from '../../../utils/workerSession'
import './index.scss'

/** 页面标题（与商家后台「返工记录」同名 —— 工人与商家说同一件事用同一个词）。 */
export const REWORK_TITLE = '返工记录'

/** 缺值占位符（与待发货单 / 发货纸面同口径：**不是** 0、不是空串、不是「未知」）。 */
export const MISSING = '—'

/** 空态（读了、真没有 —— **不是**错误态）。 */
export const EMPTY_HINT = '暂无返工记录：车间报过返工的加工单会出现在这里'

/** 读不到时的兜底文案（技术原文留在请求层，屏上只出现人话）。 */
export const READ_FAILED_HINT = '读取失败，请重试'

/** 401：未登录 / 会话失效 ⇒ 引导去工人登录（不清商家态、不跳商家登录页）。 */
export const LOGIN_REQUIRED = '请先用工号 + PIN 登录工人身份，再查看返工记录（商家账号不能走这条路径）。'

/**
 * 403：工人档案的页面集里没有 `rework`。**可行动**（找谁 / 做什么 / 之后怎么办），
 * 且与「读不到」分成两种现场（见文件头第 3 条）。
 */
export const FORBIDDEN_HINT =
  '本机未开「返工记录」页：请让管理员在工人档案的页面里勾选「返工记录」，回来刷新即可'

/** 页面的五种状态（互斥）。 */
export type ReworkPhase = 'loading' | 'error' | 'unauthorized' | 'forbidden' | 'ready'

/** 文本化：`null` / 空串 / 纯空白 ⇒ `—`（缺值不编造）。 */
export function textOrMissing(value: unknown): string {
  const text = value == null ? '' : String(value).trim()
  return text === '' ? MISSING : text
}

/** 数字 → 文本（`2.00` ⇒ `2`）；缺值 / 坏值 ⇒ `''`（整项不渲染，**不印 `NaN`**）。 */
export function formatQty(value: unknown): string {
  if (value == null) return ''
  if (typeof value === 'string' && value.trim() === '') return ''
  const num = Number(value)
  return Number.isFinite(num) ? String(num) : ''
}

/** 返工笔数：`3` ⇒ `3 笔`；缺值 / 坏值 ⇒ `''`（**不印 `0 笔` 冒充**）。 */
export function reworkCountText(value: unknown): string {
  const qty = formatQty(value)
  return qty === '' ? '' : `${qty} 笔`
}

/**
 * 最近返工时间：`2026-10-26T17:00:00+08:00` ⇒ `2026-10-26 17:00`。
 *
 * 🔴 **只切不改**（同 H5 `/w/rework.mjs` 口径）：服务端按业务时区给值（带偏移），
 * 再 `new Date()` 转一次就会在浏览器所在时区上漂。短到切不出分钟 ⇒ `''`（整项不渲染）。
 */
export function reworkAtText(value: unknown): string {
  const raw = value == null ? '' : String(value).trim()
  return raw.length < 16 ? '' : raw.slice(0, 16).replace('T', ' ')
}

/** 涉及工序：`工序名 ×数量`，缺数量只出名字，缺名字整项丢掉（工人认不出无名的那一行）。 */
export function operationsText(operations: WorkerReworkOperation[] | null | undefined): string {
  return (Array.isArray(operations) ? operations : [])
    .map((op) => ({ name: String(op?.operation_name ?? '').trim(), qty: formatQty(op?.qty) }))
    .filter((op) => op.name !== '')
    .map((op) => (op.qty === '' ? op.name : `${op.name} ×${op.qty}`))
    .join('、')
}

/** 一行的展示模型：**唯一**决定「哪些项出现」（渲染与测试都读它）。 */
export interface ReworkRowModel {
  heading: string
  cells: Array<{ key: string; label: string; text: string }>
}

export function reworkRowModel(order: WorkerReworkOrder | null | undefined): ReworkRowModel {
  const cells: ReworkRowModel['cells'] = []
  const orderNo = String(order?.order_no ?? '').trim()
  if (orderNo !== '') cells.push({ key: 'order_no', label: '订单号', text: orderNo })
  const count = reworkCountText(order?.rework_count)
  if (count !== '') cells.push({ key: 'rework_count', label: '返工', text: count })
  const at = reworkAtText(order?.latest_rework_at)
  if (at !== '') cells.push({ key: 'latest_rework_at', label: '最近返工', text: at })
  const reason = String(order?.latest_reason ?? '').trim()
  if (reason !== '') cells.push({ key: 'latest_reason', label: '原因', text: reason })
  const ops = operationsText(order?.operations)
  if (ops !== '') cells.push({ key: 'operations', label: '涉及工序', text: ops })
  return { heading: String(order?.processing_order_no ?? '').trim(), cells }
}

function ReworkRow({ order, index }: { order: WorkerReworkOrder; index: number }) {
  const row = reworkRowModel(order)
  return (
    <View className='worker-rework__row' data-testid={`worker-rework-row-${index}`}>
      <Text className='worker-rework__no' data-testid={`worker-rework-no-${index}`}>
        {row.heading === '' ? MISSING : row.heading}
      </Text>
      {row.cells.map((cell) => (
        <Text
          className='worker-rework__line'
          key={cell.key}
          data-testid={`worker-rework-${cell.key}-${index}`}
        >
          {cell.label}：{cell.text}
        </Text>
      ))}
    </View>
  )
}

export default function WorkerReworkPage() {
  const workerReady = hasWorkerSession()
  const [worker, setWorker] = useState<CurrentWorker | null>(null)
  const [phase, setPhase] = useState<ReworkPhase>(workerReady ? 'loading' : 'unauthorized')
  const [page, setPage] = useState<WorkerReworkOrdersPage | null>(null)
  const [message, setMessage] = useState('')

  const load = useCallback(async () => {
    if (!workerReady) {
      setPhase('unauthorized')
      return
    }
    setPhase('loading')
    setMessage('')
    const res = await listWorkerReworkOrders()
    if (res.success && res.data) {
      setPage(res.data)
      setPhase('ready')
      return
    }
    // 🔴 401 = 未登录 / 会话失效 ⇒ 只清本机工人身份并引导登录
    if (res.statusCode === 401) {
      clearWorkerSession()
      setWorker(null)
      setPhase('unauthorized')
      return
    }
    // 🔴 403 = 工人档案没开「返工记录」页 ⇒ 可行动提示（**不是**「没有返工」、**不是**网络故障）
    if (res.statusCode === 403) {
      setPhase('forbidden')
      return
    }
    setMessage(res.message || READ_FAILED_HINT)
    setPhase('error')
  }, [workerReady])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    if (!workerReady) return
    // 页头「当前工人」取自服务端（与工作台同源）；读不到不阻塞列表
    void fetchCurrentWorker().then((res) => {
      if (res.success && res.data) setWorker(res.data)
    })
  }, [workerReady])

  const goWorkerLogin = useCallback(() => {
    Taro.navigateTo({ url: WORKER_TAB_LOGIN_ROUTE })
  }, [])

  const orders = page?.orders ?? []
  const count = orders.length

  return (
    <View className='worker-rework'>
      <View className='worker-rework__header'>
        <View className='worker-rework__heading'>
          <Text className='worker-rework__title'>{REWORK_TITLE}</Text>
          {worker && phase !== 'unauthorized' ? (
            <Text className='worker-rework__worker' data-testid='worker-rework-worker'>
              当前工人：{textOrMissing(worker.worker_name)}
            </Text>
          ) : null}
        </View>
        <Button
          className='worker-rework__refresh'
          data-testid='worker-rework-refresh'
          onClick={() => {
            void load()
          }}
        >
          刷新
        </Button>
      </View>

      {phase === 'loading' ? (
        <View className='worker-rework__notice' data-testid='worker-rework-loading'>
          <Text className='worker-rework__notice-text'>正在读取返工记录…</Text>
        </View>
      ) : null}

      {phase === 'unauthorized' ? (
        <View className='worker-rework__gate' data-testid='worker-rework-login-required'>
          <Text className='worker-rework__gate-text'>{LOGIN_REQUIRED}</Text>
          <Button
            className='worker-rework__login'
            data-testid='worker-rework-login'
            onClick={goWorkerLogin}
          >
            去登录工人身份
          </Button>
        </View>
      ) : null}

      {phase === 'forbidden' ? (
        <View className='worker-rework__notice' data-testid='worker-rework-forbidden'>
          <Text className='worker-rework__notice-text'>{FORBIDDEN_HINT}</Text>
        </View>
      ) : null}

      {phase === 'error' ? (
        <View className='worker-rework__notice' data-testid='worker-rework-error'>
          <Text className='worker-rework__notice-text'>{message || READ_FAILED_HINT}</Text>
          <Button
            className='worker-rework__retry'
            data-testid='worker-rework-retry'
            onClick={() => {
              void load()
            }}
          >
            重试
          </Button>
        </View>
      ) : null}

      {phase === 'ready' ? (
        <View className='worker-rework__body'>
          <Text className='worker-rework__count' data-testid='worker-rework-count'>
            共 {count} 张加工单有返工报工
          </Text>
          {count === 0 ? (
            <View className='worker-rework__notice' data-testid='worker-rework-empty'>
              <Text className='worker-rework__notice-text'>{EMPTY_HINT}</Text>
            </View>
          ) : (
            <View className='worker-rework__list' data-testid='worker-rework-list'>
              {orders.map((order, index) => (
                <ReworkRow
                  key={order.processing_order_id || `row-${index}`}
                  order={order}
                  index={index}
                />
              ))}
            </View>
          )}
        </View>
      ) : null}
    </View>
  )
}
