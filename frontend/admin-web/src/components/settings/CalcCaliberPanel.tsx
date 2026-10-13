'use client'

/**
 * 「算料口径」域的**唯一写面**（读面 + 就地编辑，issue #6580 抽出；issue #6825 起可写）。
 *
 * ## 它是什么
 *
 * 「企业基础设置 = 配置指挥台」按域分栏（设计真值源
 * `docs/design/enterprise-settings-redesign.md` §2），算料口径是 **① 报价与计费** 的第一格。
 * issue #6825 之前本域**只有只读展示**（值都在、能看，一个输入框都没有），而真正的写面藏在
 * `frontend/admin-web/src/components/production-config/ProcessConfigBoard.tsx` 的「算料配置」tab 里
 * —— 那个 tab 的入口已随 #6580 从菜单撤掉 ⇒ **商家从任何导航都改不到这些参数**。
 *
 * 现在本域就是**算料配置的唯一写面**（设计判死线第 1 条：同一份配置不许两个入口）：
 * 8 个标量（`CALC_SCALAR_KEYS`）/ 档位表 `tiers` / 拼色每折吃布表 `per_fold_mixed_times` /
 * 备用公式 `default_formula` **全部就地可改**，全域**只有一个保存按钮**；
 * 术语说明（`CraftCalcGlossary`）与阈值预览（`OversizeThresholdPreview`）随参数同屏。
 *
 * ## 🔴 保存语义（与后端契约逐字一致）
 *
 * 读面 `GET /api/admin/production/craft-calc-config` 给**整份**配置（`CraftCalcConfigResponse`），
 * 写面 `PUT` 是**全量替换** ⇒ 保存时发**整份键**（缺键会被后端静默回默认值 —— 那正是
 * 「改了一处、另一处悄悄变回默认」的静默失效形态）。成功 ⇒ `source` 变 `stored` + 回执；
 * 被拒（422）⇒ 后端 `error.details[].message` **逐条**上屏
 * （`@/lib/production-guard-reasons` 的 `craftCalcConfigGuardReasons`）、**草稿不回滚**、
 * **不谎报已保存**。
 *
 * ## 🔴 它不判口径、不算钱（同 `config-readiness.ts` / `tenant-params.ts` 的纪律）
 *
 * 值一律来自服务端读面**原样**展示；三态解释只用 `@/lib/tenant-params` 的既有纯函数。
 * 本组件**不产出任何就绪度判断** —— 那是 `@/lib/config-readiness` 的 `judge*` 系列（唯一真值源）。
 * 默认值**不落前端**：本租户没配置行时后端回的就是引擎默认值（`source='default'`）。
 *
 * ## 两种挂载形态
 *
 * - **取数形态**（`/settings` 的算料域）：**不传** `calc` ⇒ 本组件自己读、**就地可写**；
 * - **受控只读形态**（`frontend/admin-web/src/components/settings/TenantParamsPanel.tsx`）：
 *   传 `calc` / `calcError` / `loading`、**不给** `onCalcChange` ⇒ 只渲染读数，**一个输入框都不渲染**
 *   （读面不由本组件取 ⇒ 它没有可写的东西；渲染一个「保存」在那里等于造第二个写面）。
 *
 * ## 数字输入一律用 `NumberInput`（issue #5198 / #5218）
 *
 * 旧 `type="number"` 会吞 `0.` 中间态、清空会把框渲染成字面量 `NaN` 且清不掉。
 */
import { useCallback, useEffect, useState } from 'react'
import { AlertCircle, ChevronDown, ChevronRight } from 'lucide-react'
import { toast } from 'sonner'
import { NumberInput } from '@/components/ui'
import { OversizeThresholdPreview } from '@/components/settings/OversizeThresholdPreview'
import { CraftCalcGlossary } from '@/components/production/CraftCalcGlossary'
import { productionApi } from '@/lib/api'
import { isErrorToastShown } from '@/lib/api-error'
import { InlineMarkdown } from '@/lib/inline-markdown'
import { CRAFT_CALC_FORMULA_LABELS } from '@/lib/craft-calc-request'
import { CALC_PARAM_COPY, CALC_SCALAR_KEYS, glossaryAnchorOf } from '@/lib/craft-calc-glossary'
import { craftCalcConfigGuardReasons } from '@/lib/production-guard-reasons'
import { inputCls } from '@/components/production-config/utils'
import {
  PARAM_DOMAINS,
  isUsingEngineDefault,
  type ParamDomain,
  type ScalarParam,
} from '@/lib/tenant-params'
import type { CraftCalcConfig, CraftCalcConfigResponse } from '@/types'

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
  docHref,
  hideValue = false,
  unset = false,
  changedFromDefault,
}: {
  param: ScalarParam
  /** 右列显示的值；**读面未落地时调用方传 `'…'`**（不谎报） */
  value: string
  /**
   * 「参数旁的**说明**」锚点目标（issue #4975）。
   * ⚠️ 只有**同屏真的渲染了术语区块**的调用方才能给（否则就是指向空处的死锚点）——
   * 算料口径域给 `glossaryAnchorOf(key)`；域面板（`TenantParamsPanel`）不给。
   */
  docHref?: string
  /**
   * 🔴 **不渲染右列值**（§31 P2「信息不重复」；2026-10-13 真机读图复核逼出来的返修）。
   *
   * 可写形态下右列值与输入框**同源**（都读同一份草稿）⇒ 同一行把同一个数印两遍，
   * 而两次都不可解释「谁是**要改的**那个」（是纯回声，**不是**「已保存 vs 正在改」的对照）。
   * ⇒ 可写形态的值只由**输入框**一处承载；右列值只在**只读形态**保留
   * （`TenantParamsPanel` 那条路上没有输入框，值只能靠它显示）。
   */
  hideValue?: boolean
  /** 是否标「未配置（正在用引擎默认值）」 */
  unset?: boolean
  /**
   * 逐键「我改过没有」：`undefined` = 本次不可比（**一个徽标都不标**）；
   * `null` = 该键的引擎默认值没取到（同样不标）；`string` = 默认值 ⇒ 与 `value` 比对后标「已改 / 默认」。
   */
  changedFromDefault?: string | null
}) {
  return (
    <div data-testid={`param-${param.key}`} className="border border-neutral-200 rounded-lg p-4">
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
        {!hideValue && (
          <div className="text-right flex-shrink-0">
            <div data-testid={`param-value-${param.key}`} className="text-sm font-mono text-neutral-900">
              {value}
            </div>
            {/* 🔴 issue #6663（§31 P3「不摆内部标识」）：改前这里印的是**引擎键名**
                （`per_fold_single` / `oversize_width_threshold` …）—— 那是引擎的实现细节，
                商家既读不懂也用不上。要说明「这个参数是什么」用**人话标签 + 口径说明**（上方已各有其一）。 */}
          </div>
        )}
      </div>
      <p className="text-xs text-neutral-600 mt-2 pt-2 border-t border-neutral-100">
        改它会怎样：<InlineMarkdown text={param.copy.impact} />
        {docHref !== undefined && (
          <a
            href={`#${docHref}`}
            data-testid={`param-doc-${param.key}`}
            className="ml-2 text-primary-600 hover:underline"
          >
            说明
          </a>
        )}
      </p>
    </div>
  )
}

export interface CalcCaliberPanelProps {
  /**
   * 算料域读数（**传了它**= 受控形态：读面归调用方）。
   * **不传** ⇒ 本面板自己读 + **就地可写**（`/settings` 的算料域是这一形态）。
   */
  calc?: CraftCalcConfigResponse | null
  /** 读数错误话术（受控形态用）；空 = 没出错 */
  calcError?: string
  /** 读数是否仍在路上（受控形态用；**不谎报**：加载中不把任何参数画成「未配置」） */
  loading?: boolean
  /**
   * 写面回调：**给了它**本面板才就地可写；`draft` 由**调用方**持有（取数在页面，
   * 见 `tests/unit_ci_workflows/test_agent_permission_parity.py` 的 `MENU_READ_ENDPOINT_ANCHORS`）。
   * 草稿一律是**整份**配置（写面是全量替换）。
   */
  onCalcDraftChange?: (next: CraftCalcConfig) => void
  /** 当前草稿（受控可写形态；不传 ⇒ 用读数里的 `config`） */
  calcDraft?: CraftCalcConfig | null
  /**
   * 保存（**调用方**发 `PUT` —— 写面的错误归因与 toast 口径在页面一处）。
   * 抛错 ⇒ 本面板把 `error.details[].message` 逐条上屏、**草稿不回滚**。
   */
  onCalcSave?: () => Promise<void>
  /** 失败行的重试出口（取数形态 = 重跑本面板那次读面；受控形态 = 调用方给） */
  onRetry?: () => void
}

/** 工艺档位的**显示名**（键仍是后端键；未知档回退原键，不吞掉、不猜中文） */
const TIER_DISPLAY_LABEL: Record<string, string> = {
  standard: '标准档',
  economy: '经济档',
}

/**
 * 档位**显示名**（未知档 ⇒ 人话兜底，**不**把服务端机器键印上屏）。
 *
 * 🔴 改判（issue #6825）：改前是 `TIER_DISPLAY_LABEL[name] ?? name` —— 服务端新增档位时
 * 会把 `economy` 这类标识直接显示给商家/顾客。守卫 `design-baseline-expression-fallback.test.ts`
 * （issue #6668 盲区①）的首选处置 = 换人话兜底（不是登记豁免）。
 */
const tierLabelOf = (name: string): string => TIER_DISPLAY_LABEL[name] ?? '未命名档位'

/** 草稿里某个数值键的当前值（**不在这里补默认值**）—— 非有限数（清空时落的 `NaN` 哨兵）一律 `null` */
function numberOf(config: CraftCalcConfig, key: string): number | null {
  const v = (config as unknown as Record<string, unknown>)[key]
  return typeof v === 'number' && Number.isFinite(v) ? v : null
}

export function CalcCaliberPanel({
  calc: calcProp,
  calcError: calcErrorProp,
  loading: loadingProp,
  calcDraft: draftProp,
  onCalcDraftChange,
  onCalcSave,
  onRetry,
}: CalcCaliberPanelProps) {
  const [advancedOpen, setAdvancedOpen] = useState(false)

  /**
   * **取数形态**（调用方没给 `calc`）⇒ 本面板自己读。
   *
   * ⚠️ 用 `calcProp === undefined` 判形态（不是 `== null`）：调用方显式传 `null` 是
   * **受控形态**（调用方说「没读到」），本面板必须**不**去抢读面 —— 否则同一次读面两个来源。
   */
  const own = calcProp === undefined
  const [ownCalc, setOwnCalc] = useState<CraftCalcConfigResponse | null>(null)
  const [ownDraft, setOwnDraft] = useState<CraftCalcConfig | null>(null)
  const [ownError, setOwnError] = useState('')
  const [busy, setBusy] = useState(false)
  /** 保存被拒的逐条理由（**不吞**成一句「保存失败」—— 后端一次列出每一处不合法） */
  const [reasons, setReasons] = useState<string[]>([])

  const loadCalcConfig = useCallback(async () => {
    try {
      const res = await productionApi.getCraftCalcConfig()
      const data = res.data?.data ?? null
      setOwnCalc(data)
      setOwnDraft(data?.config ?? null)
      setOwnError('')
    } catch {
      setOwnCalc(null)
      setOwnDraft(null)
      /**
       * 🔴 **只留这一处**失败信号（issue #6669 / §31 P1 常驻面克制 · P2 信息不重复）。
       *
       * `frontend/admin-web/src/lib/request.ts` 的响应拦截器对**所有**失败分支都已
       * `toast.error(...)` + `markErrorToastShown(error)` ⇒ 这里再播一次就是同一故障报两遍。
       * 撤掉的是**重复**，不是**可见性**：失败仍看得见（本行摘要）且有出口（「重试」）。
       */
      setOwnError('算料配置加载失败，请稍后重试')
    }
  }, [])

  useEffect(() => {
    if (own && ownCalc === null && ownError === '') void loadCalcConfig()
  }, [own, ownCalc, ownError, loadCalcConfig])

  const calc: CraftCalcConfigResponse | null = own ? ownCalc : (calcProp ?? null)
  const calcError = own ? ownError : (calcErrorProp ?? '')
  /** 读面是否仍在路上（**不谎报**：加载中不把任何参数画成「未配置」） */
  const loading = own ? ownCalc === null && ownError === '' : Boolean(loadingProp)
  /** 写面可用吗（调用方没给回调 ⇒ 只读退化，一个输入框都不渲染） */
  const writable = typeof onCalcDraftChange === 'function' || typeof onCalcSave === 'function'
  const draft: CraftCalcConfig | null = own ? ownDraft : (draftProp ?? calc?.config ?? null)
  /** 展示取值对象（草稿优先 —— 改完立刻看得见；否则读面原文） */
  const displayConfig = draft ?? calc?.config ?? null
  const patchDraft = (next: CraftCalcConfig) => onCalcDraftChange?.(next)

  async function save() {
    if (!onCalcSave) return
    setReasons([])
    setBusy(true)
    try {
      await onCalcSave()
      setReasons([])
      toast.success('算料配置已保存，之后的算料按当前配置计算')
    } catch (e) {
      setReasons(craftCalcConfigGuardReasons(e))
      if (!isErrorToastShown(e)) toast.error('算料配置保存失败')
    } finally {
      setBusy(false)
    }
  }

  /** 本组件只管算料域（域定义取自单一真值模块，不在这里写第二份清单） */
  const domain: ParamDomain = PARAM_DOMAINS.find((d) => d.key === 'calc') ?? PARAM_DOMAINS[0]

  /** 读面失败 —— 本面板**只画一条失败行**，其余重复信号全部撤掉（issue #6663 / §31 P1·P2） */
  const failed = Boolean(calcError)

  /**
   * 「未配置（正在用引擎默认值）」**只有在真知道答案时才许说**（issue #6573 收口）：
   * 读面还在路上（`loading`）或读失败（`calcError`）时 `calc === null`，而
   * `isUsingEngineDefault(undefined) === true` —— 不设栏就会在**首屏那一瞬**把「还不知道」
   * 说成「你没配」（这与本仓「不谎报」纪律相抵）。
   */
  const usingDefault = !loading && !calcError && isUsingEngineDefault(calc?.source)

  /** 值一律来自服务端（或当前草稿），**原样**展示（本组件不做任何换算） */
  const valueOf = (key: string): string => {
    const v = (displayConfig as unknown as Record<string, unknown> | null | undefined)?.[key]
    return v === undefined || v === null || v === '' ? '—' : String(v)
  }

  /** 引擎默认值里该键的值（**只在 `defaults_source='engine'` 时有意义**；否则 `null`） */
  const defaultOf = (key: string): string | null => {
    const v = (calc?.defaults as Record<string, unknown> | undefined)?.[key]
    return v === undefined || v === null ? null : String(v)
  }

  /** §22 P3 逐键「我改过没有」：只在**引擎默认值真取到**时才给比对值（拿不到就一条都不标） */
  const perKeyComparable = calc?.defaults_source === 'engine' && !!calc?.defaults
  const changedFromDefaultOf = (key: string): string | null | undefined =>
    perKeyComparable ? defaultOf(key) : undefined

  const renderScalar = (p: ScalarParam) => (
    <div key={p.key} className="space-y-1">
      <ParamScalarRow
        param={p}
        // 「说明」锚点指到**同页**的术语与口径区块条目（issue #4975：指路要指得着）
        docHref={displayConfig ? glossaryAnchorOf(p.key) : undefined}
        // 🔴 读失败 ⇒ **空位**（不是 `—`）：`—` 长得像「这个参数没有值」，而真相是**整个读面失败**。
        //    加载中仍给 `…`（那是「还在读」，与失败是两件事）。
        value={failed ? '' : loading && !displayConfig ? '…' : valueOf(p.key)}
        // 🔴 §31 P2（真机复核返修，2026-10-13）：**输入框在屏上时不渲染右列值** ——
        //    两者同源（都读 `displayConfig`）⇒ 同一行把同一个数印两遍，且分不清哪个是「要改的」。
        //    条件与下面那个 `NumberInput` 的渲染条件**逐字相同**（有输入框 ⇔ 没有右列值）。
        hideValue={writable && !!displayConfig}
        unset={usingDefault}
        changedFromDefault={changedFromDefaultOf(p.key)}
      />
      {/* 就地可改（写面）：`NumberInput`（issue #5198 —— `type="number"` 会吞 `0.` / 清空变 `NaN`） */}
      {writable && displayConfig && (
        <NumberInput
          className={inputCls}
          aria-label={`${p.copy.label}`}
          data-testid={`calc-caliber-scalar-${p.key}`}
          value={numberOf(displayConfig, p.key)}
          onChange={(v) =>
            patchDraft({ ...displayConfig, [p.key]: v === null ? Number.NaN : v } as CraftCalcConfig)
          }
        />
      )}
    </div>
  )

  const tiers = displayConfig?.tiers ?? {}
  const mixed = displayConfig?.per_fold_mixed_times ?? {}

  return (
    <div data-testid="calc-caliber-panel" className="space-y-4">
      {/* 🔴 读面失败 —— 本域**唯一**那条失败行（§31 P1 常驻面克制 / P2 信息不重复）。
          其余重复信号已撤：数值位的 `—`（见 renderScalar）、底部那行重复的「加载失败 + 重试」。 */}
      {failed && (
        <div
          data-testid="param-calc-error"
          className="flex items-start gap-3 text-xs text-red-700 bg-red-50 border border-red-200 rounded p-2"
        >
          <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
          <span className="flex-1">{calcError}</span>
          <button
            type="button"
            data-testid="param-calc-retry"
            onClick={() => (own ? void loadCalcConfig() : onRetry?.())}
            className="flex-shrink-0 rounded border border-red-300 px-2 py-0.5 font-medium text-red-700 hover:bg-red-100"
          >
            重试
          </button>
        </div>
      )}

      {/* 口径来源徽标：「系统默认值」≠「你的配置」（读失败时不画 —— 那是读成功才知道的事） */}
      {!failed && calc && (
        <span
          data-testid="calc-caliber-source"
          className={
            calc.source === 'stored'
              ? 'inline-block rounded bg-primary-50 px-2 py-0.5 text-xs text-primary-700'
              : 'inline-block rounded bg-neutral-100 px-2 py-0.5 text-xs text-neutral-600'
          }
        >
          {calc.source === 'stored' ? '已保存为您的配置' : '当前使用系统默认值'}
        </span>
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

      {/* 读面失败 ⇒ **不画参数卡、不画写面**（画一排空值卡 = 把「读不到」伪装成「这些参数是空的」；
          读不到就不许改 —— 改的是一份读不到的配置）。保留一个锚点，让失败态在 DOM 里可断言。 */}
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

          {/* ══════════ 以下三块原在板子的「算料配置」tab 里（issue #6825 并入本域） ══════════ */}
          {writable && displayConfig && (
            <>
              {/* 备用公式（工艺能推导时以工艺为准，这里只是推导表缺失时的兜底） */}
              <div className="pt-3 border-t border-neutral-100">
                <label className="mb-1 block text-sm text-neutral-700" htmlFor="calc-caliber-formula">
                  {CALC_PARAM_COPY.default_formula.label}
                </label>
                {/* 取值域与文案 = **单一真值** `CRAFT_CALC_FORMULA_LABELS`（不另写一份映射） */}
                <select
                  id="calc-caliber-formula"
                  className={inputCls}
                  data-testid="calc-caliber-default_formula"
                  value={displayConfig.default_formula}
                  onChange={(e) => patchDraft({ ...displayConfig, default_formula: e.target.value })}
                >
                  {Object.keys(CRAFT_CALC_FORMULA_LABELS).map((k) => (
                    <option key={k} value={k}>
                      {CRAFT_CALC_FORMULA_LABELS[k]}
                    </option>
                  ))}
                </select>
                <span className="mt-1 block text-xs text-neutral-500">
                  <InlineMarkdown text={CALC_PARAM_COPY.default_formula.hint} />
                </span>
              </div>

              {/* 次区：档位与拼色系数（表格，逐行可改） */}
              <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 pt-3 border-t border-neutral-100">
                <div>
                  <h3 className="mb-2 text-sm font-medium text-neutral-700">
                    {CALC_PARAM_COPY.tiers.label}
                  </h3>
                  <table className="w-full text-sm">
                    <tbody>
                      {Object.entries(tiers).map(([name, tier]) => (
                        <tr key={name} className="border-b border-neutral-100">
                          <td className="py-1.5 pr-3 text-neutral-600">
                            {tierLabelOf(name)}
                          </td>
                          <td className="py-1.5 pr-3">
                            <input
                              className={inputCls}
                              aria-label={`${tierLabelOf(name)} 显示名`}
                              data-testid={`calc-caliber-tier-${name}-label`}
                              value={tier.label ?? ''}
                              onChange={(e) =>
                                patchDraft({
                                  ...displayConfig,
                                  tiers: { ...tiers, [name]: { ...tier, label: e.target.value } },
                                })
                              }
                            />
                          </td>
                          <td className="py-1.5">
                            <NumberInput
                              className={inputCls}
                              aria-label={`${tierLabelOf(name)} 褶倍`}
                              data-testid={`calc-caliber-tier-${name}-fullness`}
                              value={
                                typeof tier.fullness === 'number' && Number.isFinite(tier.fullness)
                                  ? tier.fullness
                                  : null
                              }
                              onChange={(v) =>
                                patchDraft({
                                  ...displayConfig,
                                  tiers: {
                                    ...tiers,
                                    [name]: { ...tier, fullness: v === null ? Number.NaN : v },
                                  },
                                })
                              }
                            />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div>
                  <h3 className="mb-2 text-sm font-medium text-neutral-700">
                    {CALC_PARAM_COPY.per_fold_mixed_times.label}
                  </h3>
                  <table className="w-full text-sm">
                    <tbody>
                      {Object.entries(mixed).map(([times, perFold]) => (
                        <tr key={times} className="border-b border-neutral-100">
                          <td className="py-1.5 pr-3 text-neutral-600">拼{times}次</td>
                          <td className="py-1.5">
                            <NumberInput
                              className={inputCls}
                              aria-label={`拼${times}次 每折吃布`}
                              data-testid={`calc-caliber-mixed-${times}`}
                              value={
                                typeof perFold === 'number' && Number.isFinite(perFold)
                                  ? perFold
                                  : null
                              }
                              onChange={(v) =>
                                patchDraft({
                                  ...displayConfig,
                                  per_fold_mixed_times: {
                                    ...mixed,
                                    [times]: v === null ? Number.NaN : v,
                                  },
                                })
                              }
                            />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </>
          )}

          {/* §22 P4：改钱的参数给预览（本域唯一能做**真预演**的两个阈值） */}
          <OversizeThresholdPreview config={displayConfig} />

          {/* 全域**唯一**的保存按钮（受控只读形态 / 读失败 ⇒ 不渲染） */}
          {writable && displayConfig && (
            <div className="pt-3 border-t border-neutral-100">
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  data-testid="calc-caliber-save"
                  /* 域写面台账的「出口」标记（issue #6825）：类级守卫要求「可编辑控件 + 本域写出口」
                     成对出现 —— 只看「域内有 input」会被**阈值试算**那类工具输入框满足（假绿）。 */
                  data-write-exit="calc"
                  disabled={busy}
                  onClick={() => void save()}
                  className="rounded bg-primary-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-primary-700 disabled:opacity-50"
                >
                  {busy ? '保存中…' : '保存'}
                </button>
                <span className="text-xs text-neutral-500">
                  保存后按当前配置计算；非法值会被整份拒绝并逐条说明理由。
                </span>
              </div>
              {/* 护栏理由**逐条**展示（后端一次列出每一处不合法）—— 不吞成一句「保存失败」 */}
              {reasons.length > 0 && (
                <ul className="mt-2 space-y-1 text-sm text-red-600" data-testid="calc-caliber-reasons">
                  {reasons.map((r) => (
                    <li key={r}>{r}</li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </>
      )}

      {/* 口径与术语说明（issue #4975）：与参数**同屏** —— 参数回答「我这家的口径是多少」，
          说明回答「系统怎么判、拿哪些参数判」。区块里**不写死任何数字**（数值取自当前草稿）。 */}
      {!failed && displayConfig && <CraftCalcGlossary config={displayConfig} />}
    </div>
  )
}

export default CalcCaliberPanel
