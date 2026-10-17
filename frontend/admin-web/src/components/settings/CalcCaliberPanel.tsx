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
 * ## 版式（issue #7124，2026-10-17 用户裁定 —— 本文件最重要的一段注释）
 *
 * 用户逐字：「算料口径这里的样式还是太丑陋了」，并授权「**按你自己最优方案设计**」。
 * 病灶三条（真机截图归因，逐条对应下面的判据）：
 *
 * 1. **控件与名称同行**（#6857 的「行式紧凑」）⇒ 标签长短不一，每个输入框的**左边界逐行抖动**，
 *    两列之间也对不齐；
 * 2. **每行一条 `border-b`** ⇒ 8 行 8 条横线，像一张没有表头的表，与同页「阈值试算」那张圆角卡片
 *    不是同一套视觉语言；
 * 3. **没有区块标题** ⇒ 用料 / 档位 / 拼色 / 阈值 全靠 `border-t` 硬切，商家读不出哪几项是一组。
 *
 * ⇒ 改为**分组表单**：**标签在上、控件在下、一行口径提示收尾**（左边界恒定、两列对齐），
 * 分组靠**区块标题 + 区块间距**表达（不再画行内分隔线）；分组清单 =
 * `@/lib/craft-calc-glossary` 的 `CALC_FIELD_GROUPS`（单一真值，守卫判「分组 ∪ ≡ 键集」）。
 * 定宽输入（防整列拉满，#6857 的另一半）继续保留，宽度统一到 `w-36`。
 * 🔴 **本组判据不是审美**：「左边界对齐 / 区块存在 / 分组不漏键」都是可断言的形态；
 * 「好不好看」仍由 §15.7 读图 + 人裁定（§31.4）。
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
 * ## 挂载形态（**只有一个**：算料口径域）
 *
 * - **取数形态**（`/settings` 的算料域）：**不传** `calc` ⇒ 本组件自己读、**就地可写**；
 * - **受控形态**（`/settings` 的算料域带草稿/保存回调）：传 `calc` / `calcError` / `loading` +
 *   `calcDraft` / `onCalcDraftChange` / `onCalcSave`；**不给写回调** ⇒ 只读退化，**一个输入框都不渲染**
 *   （读面不由本组件取 ⇒ 它没有可写的东西；渲染一个「保存」在那里等于造第二个写面）。
 *
 * ## 数字输入一律用 `NumberInput`（issue #5198 / #5218）
 *
 * 旧 `type="number"` 会吞 `0.` 中间态、清空会把框渲染成字面量 `NaN` 且清不掉。
 */
import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { AlertCircle, ChevronDown, ChevronRight } from 'lucide-react'
import { toast } from 'sonner'
import { NumberInput } from '@/components/ui'
import { OversizeThresholdPreview } from '@/components/settings/OversizeThresholdPreview'
import { CraftCalcGlossary } from '@/components/production/CraftCalcGlossary'
import { productionApi } from '@/lib/api'
import { isErrorToastShown } from '@/lib/api-error'
import { InlineMarkdown } from '@/lib/inline-markdown'
import { CRAFT_CALC_FORMULA_LABELS } from '@/lib/craft-calc-request'
import { CALC_FIELD_GROUPS, CALC_PARAM_COPY } from '@/lib/craft-calc-glossary'
import { craftCalcConfigGuardReasons } from '@/lib/production-guard-reasons'
import { boundedInputCls } from '@/components/production-config/utils'
import {
  PARAM_DOMAINS,
  isUsingEngineDefault,
  type ParamDomain,
  type ScalarParam,
} from '@/lib/tenant-params'
import type { CraftCalcConfig, CraftCalcConfigResponse } from '@/types'

/** 数值输入框的**统一定宽**（定宽防「整列拉满」；统一宽度才有稳定的左边界 —— issue #6857 / #7124） */
const NUM_INPUT_WIDTH = 'w-36'

/**
 * 一个参数字段（**标签在上、控件在下、口径提示收尾**）。
 *
 * 🔴 为什么控件不跟标签同一行（#6857 曾是同行，本次改版推翻）：标签是「单色每折用料（米）」这种
 * 长短不一的句子，同行布局下每个输入框的起点都不同 —— 一屏 6 个框排不出一条竖线（用户判「丑陋」的
 * 主因）。竖排后左边界由**栅格**决定，与标签长短无关。
 *
 * 默认值徽标**不在行内标**：默认态由域级信号承担（顶部横幅 + 口径徽标，§31 P2「信息不重复」），
 * 改动与回退由「恢复为默认值」按钮兜住。
 */
export function ParamField({
  param,
  value,
  control,
}: {
  param: ScalarParam
  /** 只读值（`control` 缺省时印在标签下方）；**读面未落地时调用方传 `'…'`**（不谎报） */
  value: string
  /** 标签**下方**的控件（可编辑时给 `NumberInput`；不传 ⇒ 只读，同位置印值） */
  control?: ReactNode
}) {
  return (
    <div data-testid={`param-${param.key}`} className="min-w-0">
      <span className="block text-sm font-medium leading-5 text-neutral-800">
        <InlineMarkdown text={param.copy.label} />
      </span>
      <div className="mt-1.5">
        {control ?? (
          <div data-testid={`param-value-${param.key}`} className="text-sm text-neutral-900">
            {value}
          </div>
        )}
      </div>
      <p className="mt-1.5 text-xs leading-relaxed text-neutral-500">
        <InlineMarkdown text={param.copy.hint} />
      </p>
    </div>
  )
}

/**
 * 表单里的**一个区块**（标题 + 内容）—— 分组靠它表达，`divider` 给区块之间的一条细分隔线
 * （区块内的字段之间**不画线**：那是上一版「8 行 8 条线」的病灶）。
 */
function FormSection({
  title,
  testid,
  divider = true,
  children,
}: {
  title: string
  testid: string
  divider?: boolean
  children: ReactNode
}) {
  return (
    <section
      data-testid={testid}
      className={divider ? 'border-t border-neutral-100 pt-6' : undefined}
    >
      <h3 className="text-base font-semibold text-neutral-900">{title}</h3>
      <div className="mt-3">{children}</div>
    </section>
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

/** 工艺档位的**显示名**（键仍是后端键；未知档回退人话，不吞掉、不猜中文） */
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

  /**
   * 「恢复为默认值」（issue #6857，用户裁定）：把**整份**草稿写回引擎默认值。
   *
   * 后端 `defaults` = 引擎 `defaultConfig()` 的**整份配置**（含档位 / 拼色 / 备用公式，
   * 见 `CraftCalcConfigService` 的 `withDefaults` 分支）；`defaults_source !== 'engine'`
   * （本次取不到）⇒ **禁用并说明**，不拿一份猜的值冒充默认值。
   *
   * 🔴 **不自动保存**：本页的保存语义是显式点「保存」（整份替换 + 422 逐条理由），
   *    恢复默认只改草稿 ⇒ 商家还有反悔余地（这正是不把默认态逐行标出来的补偿）。
   */
  const engineDefaults = calc?.defaults_source === 'engine' ? (calc?.defaults ?? null) : null
  function restoreDefaults() {
    if (!engineDefaults || !displayConfig) return
    patchDraft({ ...displayConfig, ...engineDefaults })
    toast.success('已恢复为引擎默认值（还没保存 —— 点「保存」后生效）')
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

  const renderScalar = (p: ScalarParam) => (
    <ParamField
      key={p.key}
      param={p}
      // 🔴 读失败 ⇒ **空位**（不是 `—`）：`—` 长得像「这个参数没有值」，而真相是**整个读面失败**。
      //    加载中仍给 `…`（那是「还在读」，与失败是两件事）。
      value={failed ? '' : loading && !displayConfig ? '…' : valueOf(p.key)}
      // 可写形态：控件在标签**下方**（issue #7124）；不可写 ⇒ 同位置印只读值。
      control={
        writable && displayConfig ? (
          // `NumberInput`（issue #5198 —— `type="number"` 会吞 `0.` / 清空变 `NaN`）
          <NumberInput
            className={boundedInputCls(`${NUM_INPUT_WIDTH} text-right tabular-nums`)}
            aria-label={`${p.copy.label}`}
            data-testid={`calc-caliber-scalar-${p.key}`}
            value={numberOf(displayConfig, p.key)}
            onChange={(v) =>
              patchDraft({ ...displayConfig, [p.key]: v === null ? Number.NaN : v } as CraftCalcConfig)
            }
          />
        ) : undefined
      }
    />
  )

  /**
   * 字段分组（顺序与 `CALC_FIELD_GROUPS` 一致；组内顺序 = `domain.common` 的顺序 = 引擎键序）。
   *
   * 🔴 **兜底不为空即渲染**：分组清单万一漏了键（守卫会判红，但那是 CI 的事），
   * 运行时也必须**仍然可改** —— 参数在表单里隐身是比「排得难看」严重得多的故障。
   */
  function fieldGroups(): { key: string; title: string; params: ScalarParam[] }[] {
    const common = domain.common ?? []
    const used = new Set<string>()
    const groups = CALC_FIELD_GROUPS.map((g) => {
      const keys: readonly string[] = g.keys
      const params = common.filter((p) => keys.includes(p.key))
      params.forEach((p) => used.add(p.key))
      return { key: g.key as string, title: g.title as string, params }
    }).filter((g) => g.params.length > 0)
    const rest = common.filter((p) => !used.has(p.key))
    return rest.length > 0
      ? [...groups, { key: 'rest', title: '其余参数', params: rest }]
      : groups
  }

  const groups = fieldGroups()
  /** 阈值组**排在档位之后、且紧跟试算块**（改完立刻能试 —— 它们是同一件事的两半） */
  const thresholdGroup = groups.find((g) => g.key === 'thresholds')
  const leadingGroups = groups.filter((g) => g !== thresholdGroup)

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

      {/* 读面失败 ⇒ **不画参数、不画写面**（画一排空值 = 把「读不到」伪装成「这些参数是空的」；
          读不到就不许改 —— 改的是一份读不到的配置）。保留一个锚点，让失败态在 DOM 里可断言。 */}
      {failed ? (
        <div data-testid="param-calc-read-failed" />
      ) : (
        <div className="space-y-6">
          {/* ── 用布与余量（及其它非阈值分组） ── */}
          {leadingGroups.map((g, i) => (
            <FormSection
              key={g.key}
              testid={`calc-caliber-group-${g.key}`}
              title={g.title}
              divider={i > 0}
            >
              <div className="grid grid-cols-1 gap-x-10 gap-y-5 sm:grid-cols-2">
                {g.params.map(renderScalar)}
              </div>
            </FormSection>
          ))}

          {/* ══════════ 档位与拼色（原在板子的「算料配置」tab 里，issue #6825 并入本域） ══════════ */}
          {writable && displayConfig && (
            <FormSection testid="calc-caliber-group-rules" title="档位与拼色">
              {/* 🔴 两张表**上下排**（不是并排）：并排时每张只剩 ~370px，而「档位 + 显示名（w-40）+
                  褶倍（w-36）」这三列合计就 ~360px ⇒ 真机 1440 实测右列被裁掉（验收读图实证）。
                  定宽是 #6857 的成果、不能为了并排去缩它（缩了又回到「挤」），所以让容器让步。 */}
              {/* 🔴 两张表**贴合内容、放得下就并排、放不下就换行**（不是撑满整行）：
                  撑满整行时每张卡右侧会空出 357 / 535px（独立复核读图实测），
                  并排 + `w-full` 时又会在 1440 下裁掉「褶倍」列（本包第一轮读图实测）。
                  正解 = 卡宽贴合表格内容（`w-fit`）+ `flex-wrap`：1440 下两张并排且不裁切，
                  窄容器下自动换行；`max-w-full` 兜住极窄容器。 */}
              <div className="flex flex-wrap items-start gap-4">
                {/* 档位表：一行一个档位（顾客看到的名字 + 褶倍） */}
                <div className="w-fit max-w-full rounded-lg border border-neutral-200 bg-neutral-50/50 p-4">
                  <h4 className="text-sm font-medium text-neutral-800">
                    {CALC_PARAM_COPY.tiers.label}
                  </h4>
                  {/* 表格**不撑满**（无 `w-full`）：列宽贴合内容，同一行的「档位 / 显示名 / 褶倍」
                      挨在一起读；撑满会把定宽输入框之间的空白拉成一道鸿沟（验收读图实证）。 */}
                  <table className="mt-2 text-sm">
                    <tbody>
                      {/* 列头用 `td` 而不是 `th` **元素**：列头本来就短、这张表也不需要横向逃逸口，
                          而 `list-table-nowrap-guard` 的射程是「带表头标签元素的表格」——
                          不引它就不必造一个假的 overflow 容器（有意为之，不是漏了）。
                          ⚠️ 注释里也**不要写那个角括号标签名**：该守卫按源码文本判，注释同样命中。 */}
                      {/* 列头色 = `text-neutral-600`（对白底 6.2:1，过 AA）；**旧的 400 只有 2.28:1**，
                          12px 小字在真机上是「看着脏」的来源（独立复核读图实测）。 */}
                      <tr className="text-xs text-neutral-600">
                        <td className="pb-1">档位</td>
                        <td className="pb-1 pl-3">显示名</td>
                        <td className="pb-1 text-right">褶倍</td>
                      </tr>
                      {Object.entries(tiers).map(([name, tier]) => (
                        <tr key={name} className="border-t border-neutral-200/70">
                          <td className="py-2 pr-3 whitespace-nowrap text-neutral-700">
                            {tierLabelOf(name)}
                          </td>
                          <td className="py-2 pr-3">
                            <input
                              className={boundedInputCls('w-40')}
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
                          <td className="py-2">
                            <NumberInput
                              className={boundedInputCls(`${NUM_INPUT_WIDTH} text-right tabular-nums`)}
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

                {/* 拼色每折用料表：一行一个拼色次数 */}
                <div className="w-fit max-w-full rounded-lg border border-neutral-200 bg-neutral-50/50 p-4">
                  <h4 className="text-sm font-medium text-neutral-800">
                    {CALC_PARAM_COPY.per_fold_mixed_times.label}
                  </h4>
                  {/* 同档位表：不撑满，行内元素挨着读 */}
                  <table className="mt-2 text-sm">
                    <tbody>
                      <tr className="text-xs text-neutral-600">
                        <td className="pb-1">拼色方式</td>
                        <td className="pb-1 text-right">每折用料（米）</td>
                      </tr>
                      {Object.entries(mixed).map(([times, perFold]) => (
                        <tr key={times} className="border-t border-neutral-200/70">
                          <td className="py-2 pr-3 whitespace-nowrap text-neutral-700">
                            拼{times}次
                          </td>
                          <td className="py-2">
                            <NumberInput
                              className={boundedInputCls(`${NUM_INPUT_WIDTH} text-right tabular-nums`)}
                              aria-label={`拼${times}次 每折用料`}
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

              {/* 备用公式（工艺能推导时以工艺为准，这里只是推导表缺失时的兜底） */}
              <div className="mt-5">
                <label
                  className="block text-sm font-medium text-neutral-800"
                  htmlFor="calc-caliber-formula"
                >
                  {CALC_PARAM_COPY.default_formula.label}
                </label>
                {/* 取值域与文案 = **单一真值** `CRAFT_CALC_FORMULA_LABELS`（不另写一份映射） */}
                <select
                  id="calc-caliber-formula"
                  className={`${boundedInputCls('w-64')} mt-1.5`}
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
                <p className="mt-1.5 text-xs text-neutral-500">
                  <InlineMarkdown text={CALC_PARAM_COPY.default_formula.hint} />
                </p>
              </div>
            </FormSection>
          )}

          {/* ── 超高 / 超宽阈值 + 试算（同一件事的两半：上半个改阈值，下半个看它会不会变） ── */}
          {thresholdGroup && (
            <FormSection testid={`calc-caliber-group-${thresholdGroup.key}`} title={thresholdGroup.title}>
              <div className="grid grid-cols-1 gap-x-10 gap-y-5 sm:grid-cols-2">
                {thresholdGroup.params.map(renderScalar)}
              </div>
            </FormSection>
          )}

          {/* §22 P4：改钱的参数给预览（本域唯一能做**真预演**的两个阈值） */}
          <OversizeThresholdPreview config={displayConfig} />

          {/* 高级（渐进披露：默认收起，展开后与常用字段**同一形态**） */}
          {domain.advanced && domain.advanced.length > 0 && (
            <div className="border-t border-neutral-100 pt-6">
              <button
                type="button"
                data-testid={`param-advanced-toggle-${domain.key}`}
                aria-expanded={advancedOpen}
                onClick={() => setAdvancedOpen((v) => !v)}
                className="flex items-center gap-1.5 text-sm font-medium text-neutral-800 hover:text-neutral-900"
              >
                {advancedOpen ? (
                  <ChevronDown className="w-4 h-4 text-neutral-400" />
                ) : (
                  <ChevronRight className="w-4 h-4 text-neutral-400" />
                )}
                高级（{domain.advanced.length}）
                <span className="text-xs font-normal text-neutral-500">一般不常改</span>
              </button>
              {advancedOpen && (
                <div
                  data-testid={`param-advanced-${domain.key}`}
                  className="mt-4 grid grid-cols-1 gap-x-10 gap-y-5 sm:grid-cols-2"
                >
                  {domain.advanced.map(renderScalar)}
                </div>
              )}
            </div>
          )}

          {/* 全域**唯一**的保存出口（受控只读形态 / 读失败 ⇒ 不渲染）。
              🔴 形态 = **右下角常驻的小条**（`sticky` + 右对齐 + 白底微模糊），不是整条白底横幅：
              整条横幅在**静止首屏**会盖住内容（独立复核读图实测：盖住「备用用料公式」标签
              15708px² / 下拉框上部 5632px²）—— 而小条在静止态落在面板右下角的空白区，
              滚动时只压住一小角，且「保存」永远够得着（首屏不用滚 1.3 屏）。
              重启条件：若商家反馈「小条挡住右下角内容」，改成滚动过表单首屏后才吸底。 */}
          {writable && displayConfig && (
            <div className="sticky bottom-6 z-10 pt-2">
              {/* 护栏理由**逐条**展示（后端一次列出每一处不合法）—— 不吞成一句「保存失败」；
                  放在吸底容器里 ⇒ 保存被拒时理由不会滚出视口。 */}
              {reasons.length > 0 && (
                <ul
                  /* §31 P1：逐条明细**封顶滚动**（不随条数把常驻面撑高）—— 后端一次可能列出多处不合法 */
                  className="mb-2 max-h-40 space-y-1 overflow-y-auto rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-600"
                  data-testid="calc-caliber-reasons"
                >
                  {reasons.map((r) => (
                    <li key={r}>{r}</li>
                  ))}
                </ul>
              )}
              <div className="flex justify-end">
                <div className="flex flex-wrap items-center justify-end gap-3 rounded-lg border border-neutral-200 bg-white/95 px-3 py-2 shadow-sm backdrop-blur-sm">
                  {/* ⚠️ 小条里**不写说明文字**：那会把条撑到 ~556px 宽，静止首屏又压到
                      「备用用料公式」下拉框（右沿 818 > 754，独立复核实测）。说明改挂按钮 `title`，
                      真正需要时由 422 的逐条理由块承载。 */}
                  <button
                    type="button"
                    data-testid="calc-caliber-restore-defaults"
                    disabled={busy || !engineDefaults}
                    title={
                      engineDefaults
                        ? '把全部算料口径恢复成算料引擎默认值（改完还要点「保存」）'
                        : '本次没取到引擎默认值 ⇒ 无法恢复（重新打开本页可再试）'
                    }
                    onClick={restoreDefaults}
                    className="rounded border border-neutral-300 px-3 py-1.5 text-sm text-neutral-700 hover:bg-neutral-50 disabled:opacity-50"
                  >
                    恢复为默认值
                  </button>
                  <button
                    type="button"
                    data-testid="calc-caliber-save"
                    /* 域写面台账的「出口」标记（issue #6825）：类级守卫要求「可编辑控件 + 本域写出口」
                       成对出现 —— 只看「域内有 input」会被**阈值试算**那类工具输入框满足（假绿）。 */
                    data-write-exit="calc"
                    disabled={busy}
                    title="保存后按当前配置计算；非法值会被整份拒绝并逐条说明理由。"
                    onClick={() => void save()}
                    className="rounded bg-primary-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-primary-700 disabled:opacity-50"
                  >
                    {busy ? '保存中…' : '保存'}
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* 口径与术语说明（issue #4975）：与参数**同屏** —— 参数回答「我这家的口径是多少」，
          说明回答「系统怎么判、拿哪些参数判」。区块里**不写死任何数字**（数值取自当前草稿）。 */}
      {!failed && displayConfig && <CraftCalcGlossary config={displayConfig} />}
    </div>
  )
}

export default CalcCaliberPanel
