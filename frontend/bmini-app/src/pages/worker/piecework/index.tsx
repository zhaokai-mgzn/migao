// case_ids: BM-054
/**
 * 工人**我的计件**页（issue #7934）—— 工人菜单页的一条行卡：`pages/worker/piecework/index`。
 *
 * ## 这一页回答什么
 *
 * 「我这个月做了多少、这一笔怎么算的」。数据源 = `GET /api/worker/piecework?month=YYYY-MM`
 * （issue #6767 上线；实现 = `ProductionService.workerPieceworkLedger`）—— 与 H5
 * `/b/report/piecework.html` **同一个端点、同一份服务端聚合**。
 *
 * ## 六条纪律（口径 = docs/design/worker-home-menu.md §6.3，逐条在本文件的落点）
 *
 * 1. 🔴 **单一真值**：金额**只**取服务端 `amount_total`，本页**不求和**（把 `lines[].amount` 加起来
 *    = 第二份口径，涉钱面必然分叉且不会变红）⇒ 判据见 `tests/worker-piecework-page.test.tsx`。
 * 2. 🔴 **作用域只认会话**：请求只带 `month`（`readWorkerPiecework(month)`），页面**没有**任何入参能
 *    指定「看谁的计件」；`worker_id` 只由服务端从 `X-Worker-Session-Id` 解出。
 * 3. **期间**：默认本月（服务端按业务时区算），可切上月；`prev_period` / `can_prev` / `next_period` /
 *    `can_next` 全用服务端给的值 —— 端侧不推算月份边界（少一处会漂的真值）。
 * 4. 🔴 **未定价**：`unpriced` 原样显式列出「N 道未定价（未计入合计）」，**绝不**印 ¥0.00
 *    （未定价 ≠ 0 元，V90 / #4696）；一整月都是未定价时只出未定价块，**不**出「合计」。
 * 5. **只读**：本页没有任何写动作（不确认 / 不锁定 / 不结算 —— 用户 2026-09-19 裁定 2）。
 * 6. **口径风险同源**：已取消 / 返工 / 改价的扣减口径与商家端计件报表**同一份**聚合（不自行发明）。
 *
 * ## 五种状态互斥、各有稳定 testID
 *
 * 读取中 / 读不到（可重试）/ 未登录（去登录）/ 读到了（空态或读数）—— 「读不到」与「这一月没干活」
 * 是两个事实（前者可能只是网差，人据此决定要不要等）；读失败**不冒充**空态、不冒充 ¥0.00。
 */
import { useCallback, useEffect, useState } from 'react'
import Taro from '@tarojs/taro'
import { Button, Text, View } from '@tarojs/components'
import {
  readWorkerPiecework,
  type WorkerPieceworkLedger,
} from '../../../services/workerPieceworkService'
import { WORKER_TAB_LOGIN_ROUTE } from '../../../utils/inbound/gaps'
import { clearWorkerSession, hasWorkerSession } from '../../../utils/workerSession'
import './index.scss'

/** 页面标题（与商家后台「计件工资」同一件事，工人这里叫「我的计件」）。 */
export const PIECEWORK_TITLE = '我的计件'

/** 缺值占位符（与同族工人页同口径：**不是** 0、不是「未知」）。 */
export const MISSING = '—'

/** 空月文案（读到了、这一月确实没有计件 ⇒ 如实说，**不印 ¥0.00 充当读数**）。 */
export const EMPTY_HINT = '本月还没有计件：报工之后这里会出现每一道活的件数与金额'

/** 读不到时的兜底文案（技术原文留在请求层，屏上只出现人话）。 */
export const READ_FAILED_HINT = '读取失败，请重试'

/** 401：未登录 / 会话失效 ⇒ 引导去工人登录（不清商家态、不跳商家登录页）。 */
export const LOGIN_REQUIRED = '请先用工号 + PIN 登录工人身份，再查看计件（商家账号不能走这条路径）。'

/** 未定价那一条的显式说明（**绝不** ¥0.00）：几道 / 未计入合计。 */
export function unpricedNotice(count: number): string {
  return `${count} 道未定价（未计入合计）`
}

/**
 * 金额渲染：两位小数 + 千分位；`null` / 非数 ⇒ `—`（**绝不**回落成 ¥0.00）。
 *
 * 只做格式化 —— 数字本身从服务端来，本函数**不做**任何求和 / 取整口径。
 */
export function formatYuan(value: unknown): string {
  if (value === null || value === undefined || value === '') return MISSING
  const num = Number(value)
  if (!Number.isFinite(num)) return MISSING
  const sign = num < 0 ? '-' : ''
  const [int, frac] = Math.abs(num).toFixed(2).split('.')
  return `${sign}¥${int.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}.${frac}`
}

/** 件数渲染：缺值 / 坏值 ⇒ `—`（**不印 0**）。 */
export function formatQty(value: unknown): string {
  if (value === null || value === undefined || value === '') return MISSING
  const num = Number(value)
  return Number.isFinite(num) ? String(num) : MISSING
}

/** 逐笔工序显示名：逻辑名 · 部位（服务端读时派生）；缺逻辑名 ⇒ 用快照名原文。 */
function operationName(row: { logical_name?: string | null; operation?: string | null; position?: string | null }): string {
  const logical = String(row?.logical_name || row?.operation || '').trim()
  const position = String(row?.position || '').trim()
  if (logical === '' && position === '') return '未命名工序'
  return position === '' ? logical : `${logical} · ${position}`
}

/** 一行的展示模型（渲染与测试都读它）。 */
export interface PieceworkLineModel {
  key: string
  name: string
  qtyText: string
  amountText: string
}

/** 未定价工序的展示模型。 */
export interface PieceworkUnpricedModel {
  key: string
  name: string
  qtyText: string
}

/** 整页的展示模型（**唯一**决定「哪些块出现」；渲染不另算）。 */
export interface PieceworkModel {
  workerName: string
  period: string
  totalText: string
  qtyText: string
  lines: PieceworkLineModel[]
  /** 有定价行 ⇒ 才出「合计」块（一整月全未定价时**不**出，避免印成 ¥0.00） */
  hasPriced: boolean
  unpricedCount: number
  unpricedNoticeText: string
  unpricedRows: PieceworkUnpricedModel[]
  hasUnpriced: boolean
  /** 这一月一条活都没有（既无定价行、也无未定价行） */
  isEmpty: boolean
  canPrev: boolean
  prevMonth: string
  canNext: boolean
  nextMonth: string
}

/**
 * 读数 → 展示模型（**唯一**读取点）。
 *
 * 🔴 形状不对（不是对象 / 连 `amount_total` 都没有）⇒ 返回 `null`，由页面按「读不到」呈现。
 * 涉钱面上「静默当 0」会让人以为自己白干了 —— 宁可说「没读到」。
 */
export function pieceworkModel(data: WorkerPieceworkLedger | null | undefined): PieceworkModel | null {
  if (!data || typeof data !== 'object') return null
  if (data.amount_total === undefined || data.amount_total === null) return null

  const lines = (Array.isArray(data.lines) ? data.lines : []).map((line, index) => ({
    key: `line-${index}`,
    name: operationName(line ?? {}),
    qtyText: formatQty(line?.qty),
    amountText: formatYuan(line?.amount),
  }))
  const operations = Array.isArray(data.unpriced?.operations) ? data.unpriced!.operations : []
  const unpricedRows = operations.map((op, index) => ({
    key: `unpriced-${index}`,
    name: operationName(op ?? {}),
    qtyText: formatQty(op?.qty),
  }))
  const hasPriced = lines.length > 0
  const hasUnpriced = unpricedRows.length > 0 || Number(data.unpriced?.qty ?? 0) > 0

  return {
    workerName: typeof data.worker_name === 'string' ? data.worker_name : '',
    period: typeof data.period === 'string' ? data.period : '',
    totalText: formatYuan(data.amount_total),
    qtyText: formatQty(data.qty_total),
    lines,
    hasPriced,
    unpricedCount: unpricedRows.length,
    unpricedNoticeText: unpricedNotice(unpricedRows.length),
    unpricedRows,
    hasUnpriced,
    isEmpty: !hasPriced && !hasUnpriced,
    // 期间切换完全按服务端给的值（本页不写月份算术）
    canPrev: data.can_prev === true,
    prevMonth: typeof data.prev_period === 'string' ? data.prev_period : '',
    canNext: data.can_next === true,
    nextMonth: typeof data.next_period === 'string' ? data.next_period : '',
  }
}

/** 页面的四种状态（互斥）。 */
export type PieceworkPhase = 'loading' | 'error' | 'unauthorized' | 'ready'

export default function WorkerPieceworkPage() {
  const workerReady = hasWorkerSession()
  /** 当前请求的月份（`''` = 服务端按业务当前自然月）；切换月份只改它，请求由它带出 */
  const [month, setMonth] = useState('')
  const [phase, setPhase] = useState<PieceworkPhase>(workerReady ? 'loading' : 'unauthorized')
  const [model, setModel] = useState<PieceworkModel | null>(null)
  const [message, setMessage] = useState('')

  const load = useCallback(async () => {
    if (!workerReady) {
      setPhase('unauthorized')
      return
    }
    setPhase('loading')
    setMessage('')
    const res = await readWorkerPiecework(month || undefined)
    if (res.success) {
      const next = pieceworkModel(res.data)
      if (next) {
        setModel(next)
        setPhase('ready')
        return
      }
      // 读数形状不对 = 读不到（**不**把它当成 0 元 / 空月）
      setMessage(READ_FAILED_HINT)
      setPhase('error')
      return
    }
    // 🔴 401 = 未登录 / 会话失效 ⇒ 只清本机工人身份并引导登录
    if (res.statusCode === 401) {
      clearWorkerSession()
      setPhase('unauthorized')
      return
    }
    setMessage(res.message || READ_FAILED_HINT)
    setPhase('error')
  }, [month, workerReady])

  useEffect(() => {
    void load()
  }, [load])

  const goWorkerLogin = useCallback(() => {
    Taro.navigateTo({ url: WORKER_TAB_LOGIN_ROUTE })
  }, [])

  return (
    <View className='worker-piecework'>
      <View className='worker-piecework__header'>
        <View className='worker-piecework__heading'>
          <Text className='worker-piecework__title'>{PIECEWORK_TITLE}</Text>
          {phase === 'ready' && model && model.workerName !== '' ? (
            <Text className='worker-piecework__worker' data-testid='worker-piecework-worker'>
              当前工人：{model.workerName}
            </Text>
          ) : null}
          {phase === 'ready' && model && model.period !== '' ? (
            <Text className='worker-piecework__period' data-testid='worker-piecework-period'>
              {model.period}
            </Text>
          ) : null}
        </View>
        <Button
          className='worker-piecework__refresh'
          data-testid='worker-piecework-refresh'
          onClick={() => {
            void load()
          }}
        >
          刷新
        </Button>
      </View>

      {phase === 'loading' ? (
        <View className='worker-piecework__notice' data-testid='worker-piecework-loading'>
          <Text className='worker-piecework__notice-text'>正在读取计件…</Text>
        </View>
      ) : null}

      {phase === 'unauthorized' ? (
        <View className='worker-piecework__gate' data-testid='worker-piecework-login-required'>
          <Text className='worker-piecework__gate-text'>{LOGIN_REQUIRED}</Text>
          <Button
            className='worker-piecework__login'
            data-testid='worker-piecework-login'
            onClick={goWorkerLogin}
          >
            去登录工人身份
          </Button>
        </View>
      ) : null}

      {phase === 'error' ? (
        <View className='worker-piecework__notice' data-testid='worker-piecework-error'>
          <Text className='worker-piecework__notice-text'>{message || READ_FAILED_HINT}</Text>
          <Button
            className='worker-piecework__retry'
            data-testid='worker-piecework-retry'
            onClick={() => {
              void load()
            }}
          >
            重试
          </Button>
        </View>
      ) : null}

      {phase === 'ready' && model ? (
        <View className='worker-piecework__body'>
          {/* 合计：**只**印服务端给的 amount_total（本页不求和不补算） */}
          {model.hasPriced ? (
            <View className='worker-piecework__summary' data-testid='worker-piecework-summary'>
              <Text className='worker-piecework__total' data-testid='worker-piecework-total'>
                合计 {model.totalText}
              </Text>
              <Text className='worker-piecework__qty' data-testid='worker-piecework-qty'>
                共 {model.qtyText} 件
              </Text>
            </View>
          ) : null}

          {model.isEmpty ? (
            <View className='worker-piecework__notice' data-testid='worker-piecework-empty'>
              <Text className='worker-piecework__notice-text'>{EMPTY_HINT}</Text>
            </View>
          ) : null}

          {model.lines.length > 0 ? (
            <View className='worker-piecework__list' data-testid='worker-piecework-lines'>
              {model.lines.map((line, index) => (
                <View className='worker-piecework__row' key={line.key} data-testid={`worker-piecework-line-${index}`}>
                  <Text className='worker-piecework__row-name'>{line.name}</Text>
                  <Text className='worker-piecework__row-qty'>{line.qtyText} 件</Text>
                  <Text className='worker-piecework__row-amount'>{line.amountText}</Text>
                </View>
              ))}
            </View>
          ) : null}

          {/* 🔴 未定价：显式可见（几道 / 未计入合计）+ 逐条工序名；**绝不** ¥0.00 */}
          {model.hasUnpriced ? (
            <View className='worker-piecework__unpriced' data-testid='worker-piecework-unpriced'>
              <Text className='worker-piecework__unpriced-title' data-testid='worker-piecework-unpriced-count'>
                {model.unpricedNoticeText}
              </Text>
              <Text className='worker-piecework__unpriced-detail'>
                这几道活还没定价，所以没有算进上面的合计 —— 请联系管理员定价。
              </Text>
              {model.unpricedRows.map((row) => (
                <Text className='worker-piecework__unpriced-row' key={row.key}>
                  {row.name} · {row.qtyText} 件
                </Text>
              ))}
            </View>
          ) : null}

          {/* 期间切换：只按服务端给的 can_prev / can_next（端侧不推算月份边界） */}
          {model.canPrev || model.canNext ? (
            <View className='worker-piecework__months' data-testid='worker-piecework-months'>
              {model.canPrev ? (
                <Button
                  className='worker-piecework__month'
                  data-testid='worker-piecework-prev'
                  onClick={() => setMonth(model.prevMonth)}
                >
                  上月
                </Button>
              ) : null}
              {model.canNext ? (
                <Button
                  className='worker-piecework__month'
                  data-testid='worker-piecework-next'
                  onClick={() => setMonth(model.nextMonth)}
                >
                  下月
                </Button>
              ) : null}
            </View>
          ) : null}
        </View>
      ) : null}
    </View>
  )
}
