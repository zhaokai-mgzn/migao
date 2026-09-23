'use client'

/**
 * 阈值**试算**（§22 **P4「改钱的参数给护栏 + 预览」**，issue #5131）—— 改完先看，**不保存**。
 *
 * ## 为什么这一块是硬需求（不是锦上添花）
 *
 * 超高 / 超宽是**进加工费组合键**的特征名（命中不到组合 ⇒ 该行加工费收不到价）。
 * 而商家**没有能力**心算「把超宽阈值从 6 改成 5，我那些窗会怎样」——
 * ⇒ 「**改完能预演**」是**防错钱的必要条件**。
 *
 * ## 纪律
 *
 * 🔴 **判定一律走服务端真值**：`autoFeaturesApi.preview`（`POST /api/admin/orders/auto-features`）
 * —— 它接受 `config` 透传，所以能拿**改过的阈值**试算。本组件**不本地判、不本地算**。
 * 🔴 **本组件不写任何东西**：没有保存按钮、不发 PUT（改口径仍走「去算料配置」那条既有路径，
 * 那里有护栏与 422 逐条理由）。
 * ⚠️ **为什么只有这两个阈值能真预演**：算料试算端点（`craftCalcApi`）**不收 `config`**
 * （它用库里的租户配置）⇒ 其余算料参数今天**做不到**「改前预演」，已登记在设计文档 §6。
 */
import { useEffect, useState } from 'react'
import { AlertCircle } from 'lucide-react'
import { autoFeaturesApi } from '@/lib/api'
import { InlineMarkdown } from '@/lib/inline-markdown'
import type { CraftCalcConfig } from '@/types'

/** 一个示例窗（默认值只是**举例**，商家可改；它是值、不是文案） */
const EXAMPLE = { width: 5.5, height: 3.2 } as const

const WIDTH_KEY = 'oversize_width_threshold'
const HEIGHT_KEY = 'oversize_height_threshold'

interface Props {
  /** 该租户**当前**的算料配置（读面原文）；`null` = 还没读到 ⇒ 不试算 */
  config: CraftCalcConfig | null
}

interface Row {
  name: string
  reason: string
}

/** 把「配置 + 覆盖的阈值」拼成服务端要的那一份（**不改原对象**；入参已收窄为非空） */
function configWith(config: CraftCalcConfig, width: number, height: number): CraftCalcConfig {
  const bag = config as unknown as Record<string, unknown>
  return {
    ...bag,
    [WIDTH_KEY]: width,
    [HEIGHT_KEY]: height,
  } as unknown as CraftCalcConfig
}

export function OversizeThresholdPreview({ config }: Props) {
  const [width, setWidth] = useState<number>(EXAMPLE.width)
  const [height, setHeight] = useState<number>(EXAMPLE.height)
  const [widthThreshold, setWidthThreshold] = useState<number | ''>('')
  const [heightThreshold, setHeightThreshold] = useState<number | ''>('')
  const [current, setCurrent] = useState<Row[] | null>(null)
  const [adjusted, setAdjusted] = useState<Row[] | null>(null)
  const [error, setError] = useState('')

  // 草案初值 = 该租户**当前**的阈值（读面原文；不写死数字）
  useEffect(() => {
    if (!config) return
    const bag = config as unknown as Record<string, unknown>
    if (typeof bag[WIDTH_KEY] === 'number') setWidthThreshold(bag[WIDTH_KEY] as number)
    if (typeof bag[HEIGHT_KEY] === 'number') setHeightThreshold(bag[HEIGHT_KEY] as number)
  }, [config])

  useEffect(() => {
    if (!config || widthThreshold === '' || heightThreshold === '') return
    // 显式收窄：闭包里 TS **不保留** `config` 的非空收窄（否则报 `CraftCalcConfig | null` 不可赋给 `config?`）
    const cfg: CraftCalcConfig = config
    let alive = true
    const run = async () => {
      setError('')
      const [nowRes, adjRes] = await Promise.allSettled([
        autoFeaturesApi.preview({ width, height, config: cfg }),
        autoFeaturesApi.preview({
          width,
          height,
          config: configWith(cfg, Number(widthThreshold), Number(heightThreshold)),
        }),
      ])
      if (!alive) return
      const pick = (r: PromiseSettledResult<{ data?: { data?: { auto_features?: Row[] } } }>) =>
        r.status === 'fulfilled' ? (r.value.data?.data?.auto_features ?? []) : null
      const now = pick(nowRes)
      const adj = pick(adjRes)
      if (now === null || adj === null) {
        setError('试算失败（服务端判定不可用）—— 请稍后重试；**这不影响已下的单**')
        setCurrent(null)
        setAdjusted(null)
        return
      }
      setCurrent(now)
      setAdjusted(adj)
    }
    void run()
    return () => {
      alive = false
    }
  }, [config, width, height, widthThreshold, heightThreshold])

  const renderRows = (rows: Row[] | null, testid: string) => (
    <div data-testid={testid} className="text-xs">
      {rows === null ? (
        <span className="text-neutral-400">—</span>
      ) : rows.length === 0 ? (
        <span className="text-neutral-500">不判任何特征</span>
      ) : (
        <ul className="space-y-1">
          {rows.map((r) => (
            <li key={r.name}>
              <span className="font-medium text-neutral-900">{r.name}</span>
              <span className="text-neutral-500"> —— {r.reason}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )

  return (
    <div
      data-testid="threshold-preview"
      className="mt-4 border border-neutral-200 rounded-lg p-4 bg-neutral-50/50"
    >
      <h4 className="text-sm font-semibold text-neutral-900">阈值试算 —— 改完先看，不保存</h4>
      <p className="text-xs text-neutral-500 mt-1">
        <InlineMarkdown text="超高 / 超宽会进加工费组合键（命中不到组合就收不到价）。改阈值前先在这里试一扇窗，看看判定会不会变。判定由服务端给，本页**不保存任何改动**。" />
      </p>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-3">
        {(
          [
            ['试算窗宽（米）', 'preview-width', width, setWidth],
            ['试算窗高（米）', 'preview-height', height, setHeight],
            ['超宽阈值（米）', 'preview-threshold-width', widthThreshold, setWidthThreshold],
            ['超高阈值（米）', 'preview-threshold-height', heightThreshold, setHeightThreshold],
          ] as const
        ).map(([label, testid, value, setter]) => (
          <label key={testid} className="block">
            <span className="block text-xs text-neutral-600 mb-1">{label}</span>
            <input
              type="number"
              step="0.1"
              data-testid={testid}
              value={value}
              onChange={(e) => (setter as (v: number | '') => void)(e.target.value === '' ? '' : Number(e.target.value))}
              className="w-full h-8 px-2 rounded border border-neutral-300 text-sm focus:outline-none focus:border-primary-500"
            />
          </label>
        ))}
      </div>

      {error && (
        <div
          data-testid="preview-error"
          className="mt-3 flex items-start gap-2 text-xs text-red-700 bg-red-50 border border-red-200 rounded p-2"
        >
          <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
          <span>
            <InlineMarkdown text={error} />
          </span>
        </div>
      )}

      <div className="grid sm:grid-cols-2 gap-3 mt-3">
        <div className="bg-white border border-neutral-200 rounded p-3">
          <div className="text-xs font-medium text-neutral-700 mb-2">
            按<InlineMarkdown text="**当前**" />口径
          </div>
          {renderRows(current, 'preview-current')}
        </div>
        <div className="bg-white border border-neutral-200 rounded p-3">
          <div className="text-xs font-medium text-neutral-700 mb-2">
            按<InlineMarkdown text="**你改的**" />阈值
          </div>
          {renderRows(adjusted, 'preview-adjusted')}
        </div>
      </div>
    </div>
  )
}

export default OversizeThresholdPreview
