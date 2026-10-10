'use client'

/**
 * 「算料口径」域的**读面 + 编辑面**（issue #6580）—— 从
 * `frontend/admin-web/src/components/settings/TenantParamsPanel.tsx` 抽出的那一域。
 *
 * ## 为什么抽出来
 *
 * 「企业基础设置 = 配置指挥台」按域分栏（设计真值源
 * `docs/design/enterprise-settings-redesign.md` §2），而算料口径是 **① 报价与计费** 的第一格：
 * 它由**新页面的域面板**与**原「参数总览」面板**两处渲染。若不抽出，两处各写一份 —— 那就是
 * 设计 §2「判死线」第 1 条（**同一份配置在两个域各挂一次**）的变体：同一个编辑面两份实现，
 * 改一处漂一处。
 *
 * ## 🔴 它不判口径、不算钱（同 `config-readiness.ts` / `tenant-params.ts` 的纪律）
 *
 * 值一律来自服务端读面（`props.calc`）**原样**展示；`source` / `defaults` 的三态解释只用
 * `@/lib/tenant-params` 的既有纯函数。本组件**不产出任何就绪度判断** —— 那是
 * `@/lib/config-readiness` 的 `judge*` 系列（**唯一真值源**，有类级守卫）。
 *
 * ## props 与 `TenantParamsPanelProps` 同款（`calc` / `calcError` / `loading`）
 *
 * 取数仍在**页面**里（`useEffect` 驱动的可执行面 = 该页第一屏读端点，
 * `tests/unit_ci_workflows/test_agent_permission_parity.py` 的 `MENU_READ_ENDPOINT_ANCHORS` 那一跳）：
 * 本组件是**受控**展示件，自己不请求任何东西。
 */
import { useState } from 'react'
import Link from 'next/link'
import { AlertCircle, ChevronDown, ChevronRight, ExternalLink } from 'lucide-react'
import { OversizeThresholdPreview } from '@/components/settings/OversizeThresholdPreview'
import { InlineMarkdown } from '@/lib/inline-markdown'
import {
  PARAM_DOMAINS,
  isUsingEngineDefault,
  type ParamDomain,
  type ScalarParam,
} from '@/lib/tenant-params'
import type { CraftCalcConfigResponse } from '@/types'

/**
 * 一行**标量参数**（三件套 + 右列值位）—— 算料域与其余标量域（AI 客服）**同一份渲染**，
 * 避免「同一件事两个载体」（`param-*` 的 testid 也只有一个定义处）。
 *
 * 默认值徽标（`unset` / 逐键「已改 / 默认」）由调用方按**它自己那份读面**决定要不要传 ——
 * 本行只渲染，不判定。
 */
export function ParamScalarRow({
  param,
  value,
  unset = false,
  changedFromDefault,
}: {
  param: ScalarParam
  /** 右列显示的值；**读面未落地时调用方传 `'…'`**（不谎报） */
  value: string
  /** 是否标「未配置（正在用引擎默认值）」 */
  unset?: boolean
  /**
   * 逐键「我改过没有」：`undefined` = 本次不可比（**一个徽标都不标**）；
   * `null` = 该键的引擎默认值没取到（同样不标）；`string` = 默认值 ⇒ 与 `value` 比对后标「已改 / 默认」。
   */
  changedFromDefault?: string | null
}) {
  return (
    <div
      data-testid={`param-${param.key}`}
      className="border border-neutral-200 rounded-lg p-4"
    >
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-medium text-neutral-900">
              <InlineMarkdown text={param.copy.label} />
            </span>
            {unset && (
              <span
                data-testid={`param-unset-${param.key}`}
                className="text-xs px-1.5 py-0.5 rounded bg-amber-50 text-amber-700 border border-amber-200"
              >
                未配置（正在用引擎默认值）
              </span>
            )}
            {changedFromDefault != null &&
              (value !== changedFromDefault ? (
                <span
                  data-testid={`param-changed-${param.key}`}
                  className="text-xs px-1.5 py-0.5 rounded bg-primary-50 text-primary-700 border border-primary-200"
                >
                  已改（默认 {changedFromDefault}）
                </span>
              ) : (
                <span
                  data-testid={`param-is-default-${param.key}`}
                  className="text-xs px-1.5 py-0.5 rounded bg-neutral-100 text-neutral-600 border border-neutral-200"
                >
                  默认
                </span>
              ))}
          </div>
          <p className="text-xs text-neutral-500 mt-1">
            <InlineMarkdown text={param.copy.hint} />
          </p>
        </div>
        <div className="text-right flex-shrink-0">
          <div data-testid={`param-value-${param.key}`} className="text-sm font-mono text-neutral-900">
            {value}
          </div>
          {/* 🔴 issue #6663（§31 P3「不摆内部标识」）：改前这里印的是**引擎键名**
              （`per_fold_single` / `oversize_width_threshold` …，`font-mono` 渲染）——
              那是引擎的实现细节，商家既读不懂也用不上。
              删掉即可；要说明「这个参数是什么」用**人话标签 + 口径说明**（本行上方已各有其一）。
              ⚠️ 有意**不**在前端切字符串冒充展示名：展示名与标识分离要在服务端（同 §31 P3）。 */}
        </div>
      </div>
      <p className="text-xs text-neutral-600 mt-2 pt-2 border-t border-neutral-100">
        改它会怎样：<InlineMarkdown text={param.copy.impact} />
      </p>
    </div>
  )
}

export interface CalcCaliberPanelProps {
  /** 算料域读面（**由页面取数**）；`null` = 没取到（不区分失败与空） */
  calc: CraftCalcConfigResponse | null
  /** 算料读面的错误话术（空 = 没出错）；页面负责区分「没配」与「没权限」 */
  calcError: string
  /** 算料读面是否仍在路上（**不谎报**：加载中不把任何参数画成「未配置」） */
  loading: boolean
  /**
   * 失败行的重试出口（由**页面**提供 —— 取数在页面，见头注释「取数仍在页面里」）。
   * 失败态必须给出口，否则商家只能刷整页（墙上那句「配置类页面要给下一步」）。
   */
  onRetry?: () => void
}

export function CalcCaliberPanel({ calc, calcError, loading, onRetry }: CalcCaliberPanelProps) {
  const [advancedOpen, setAdvancedOpen] = useState(false)

  /**
   * 读面失败 —— 本面板**只画一条失败行**，其余三处重复信号全部撤掉（issue #6663 / §31 P1·P2）。
   *
   * 真机截图实证（2026-10-10，1440×980）：同一次读面失败在**一屏之内渲染了四处** ——
   * ① 本面板顶部红条；② 标题行右侧「读不到」徽标；③ 每个参数数值位一个 `—`；
   * ④ 面板底部又一行「算料配置加载失败，请稍后重试 [重试]」（那句来自同域的
   * `production-config/CalcFormulaPanel`，由它那条**保存失败的**提示一并承载）。
   *
   * 本面板的处置：**留面板顶部这一条**（它是本域失败的第一现场），
   * ③ 数值位不再用 `—` 冒充读数（读不到就说读不到，不要摆一个看起来像值的占位符）。
   */
  const failed = Boolean(calcError)

  /** 本组件只管算料域（域定义取自单一真值模块，不在这里写第二份清单） */
  const domain: ParamDomain =
    PARAM_DOMAINS.find((d) => d.key === 'calc') ?? PARAM_DOMAINS[0]

  /**
   * 「未配置（正在用引擎默认值）」**只有在真知道答案时才许说**（issue #6573 收口）：
   * 读面还在路上（`loading`）或读失败（`calcError`）时 `calc === null`，而
   * `isUsingEngineDefault(undefined) === true` —— 不设栏就会在**首屏那一瞬**把「还不知道」
   * 说成「你没配」（`param-unset-*` 徽标 + 顶部那条横幅）。这与本仓的「不谎报」纪律相抵
   * （同族：`config-readiness.ts` 把读失败判成 `unknown` 而不是 `todo`）。
   */
  const usingDefault = !loading && !calcError && isUsingEngineDefault(calc?.source)

  /** 值一律来自服务端读面，**原样**展示（本组件不做任何换算） */
  const valueOf = (key: string): string => {
    const v = (calc?.config as Record<string, unknown> | null | undefined)?.[key]
    return v === undefined || v === null || v === '' ? '—' : String(v)
  }

  /**
   * 引擎默认值里该键的值（**只在 `defaults_source='engine'` 时有意义**；否则 `null`）。
   * 值一律**原样**来自服务端，本组件不做换算。
   */
  const defaultOf = (key: string): string | null => {
    const v = (calc?.defaults as Record<string, unknown> | undefined)?.[key]
    return v === undefined || v === null ? null : String(v)
  }

  /** 逐键「我改过没有」本次**可用吗**（§22 P3，issue #5131 增量 2）—— 只在引擎默认值真取到时才可比 */
  const perKeyComparable = calc?.defaults_source === 'engine' && !!calc?.defaults

  /** §22 P3 逐键「我改过没有」：只在**引擎默认值真取到**时才给比对值（拿不到就一条都不标） */
  const changedFromDefaultOf = (key: string): string | null | undefined =>
    perKeyComparable ? defaultOf(key) : undefined

  const renderScalar = (p: ScalarParam) => (
    <ParamScalarRow
      key={p.key}
      param={p}
      // 🔴 读失败 ⇒ **空位**（不是 `—`）：`—` 长得像「这个参数没有值」，而真相是**整个读面失败**。
      //    加载中仍给 `…`（那是「还在读」，与失败是两件事）。
      value={failed ? '' : loading ? '…' : valueOf(p.key)}
      unset={usingDefault}
      changedFromDefault={changedFromDefaultOf(p.key)}
    />
  )

  return (
    <div data-testid="calc-caliber-panel" className="space-y-4">
      {/* 🔴 读面失败 —— 本域**唯一**那条失败行（§31 P1 常驻面克制 / P2 信息不重复）。
          其余三处重复信号已撤：数值位的 `—`（见 renderScalar）、底部那行重复的「加载失败 + 重试」。 */}
      {failed && (
        <div
          data-testid="param-calc-error"
          className="flex items-start gap-3 text-xs text-red-700 bg-red-50 border border-red-200 rounded p-2"
        >
          <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
          <span className="flex-1">{calcError}</span>
          {onRetry && (
            <button
              type="button"
              data-testid="param-calc-retry"
              onClick={onRetry}
              className="flex-shrink-0 rounded border border-red-300 px-2 py-0.5 font-medium text-red-700 hover:bg-red-100"
            >
              重试
            </button>
          )}
        </div>
      )}

      {usingDefault && !calcError && (
        <div
          data-testid="param-calc-using-default"
          className="text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded p-2"
        >
          <InlineMarkdown text="本企业尚未保存过算料口径 —— 下表**全部**为算料引擎默认值。" />
        </div>
      )}

      {/* §22 P3 逐键：引擎默认值**本次取不到** ⇒ **显式**说明「判不了」，
          而不是把「拿不到」画成「就是默认值」（issue #5131 增量 2） */}
      {calc?.defaults_source === 'unavailable' && (
        <div
          data-testid="param-defaults-unavailable"
          className="text-xs text-neutral-600 bg-neutral-50 border border-neutral-200 rounded p-2"
        >
          <InlineMarkdown text="引擎默认值本次取不到 ⇒ **无法判断哪些参数被你改过**。这不等于「都是默认值」，也不影响你的配置本身（稍后重新打开本页即可再试）。" />
        </div>
      )}

      {/* 读面失败 ⇒ **不画参数卡**（画一排空值卡等于把「读不到」伪装成「这些参数是空的」）。
          保留一个锚点，让「失败态发生过」这件事在 DOM 里可断言。 */}
      {failed ? (
        <div data-testid="param-calc-read-failed" />
      ) : (
        <>
          {/* P2 三件套（常用 / 高级渐进披露） */}
          {domain.common && domain.common.length > 0 && (
            <div className="space-y-3">{domain.common.map((p) => renderScalar(p))}</div>
          )}

          {domain.advanced && domain.advanced.length > 0 && (
            <div>
              <button
                type="button"
                data-testid={`param-advanced-toggle-${domain.key}`}
                aria-expanded={advancedOpen}
                onClick={() => setAdvancedOpen((v) => !v)}
                className="flex items-center gap-1 text-xs font-medium text-neutral-600 hover:text-neutral-900"
              >
                {advancedOpen ? (
                  <ChevronDown className="w-4 h-4" />
                ) : (
                  <ChevronRight className="w-4 h-4" />
                )}
                高级（{domain.advanced.length}）—— 一般不常改
              </button>
              {advancedOpen && (
                <div data-testid={`param-advanced-${domain.key}`} className="mt-3 space-y-3">
                  {domain.advanced.map((p) => renderScalar(p))}
                </div>
              )}
            </div>
          )}
        </>
      )}

      {/* §22 P4：改钱的参数给预览（本域唯一能做**真预演**的两个阈值 —— 见 TenantParamsPanel 头注释） */}
      {!calcError && <OversizeThresholdPreview config={calc?.config ?? null} />}

      {domain.edit && (
        <div className="pt-4 border-t border-neutral-100">
          <Link
            href={domain.edit.href}
            data-testid={`param-edit-${domain.key}`}
            className="inline-flex items-center gap-1 text-sm font-medium text-primary-700 hover:underline"
          >
            <InlineMarkdown text={domain.edit.label} />
            <ExternalLink className="w-3.5 h-3.5" />
          </Link>
        </div>
      )}
    </div>
  )
}

export default CalcCaliberPanel
