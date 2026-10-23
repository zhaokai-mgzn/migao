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
 * 备用公式 `default_formula` **全部就地可改**，**改完即保存**（issue #7183：没有保存按钮，见下节）；
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
 * ## 🔴 变更即保存（issue #7183，2026-10-18 用户裁定）
 *
 * 用户逐字：「这里的两个按钮应该移除，一是不需要恢复默认功能，而是应该让用户在输入框变更后即保存，
 * 这样增加界面简洁程度提高了用户体验」。⇒ 底部保存条（「恢复为默认值」+「保存」）**整体退场**，
 * 改为草稿变更后**防抖 0.6 秒**自动 `PUT` 整份配置。四条不变量：
 *
 * 1. **首屏 / 读面刷新不写**：基线 = 读面给的整份配置，草稿与基线**深相等** ⇒ 一个请求都不发
 *    （否则「打开设置页」就等于「拿这份配置覆盖一次」，而写面是整份替换）；
 * 2. **防抖合并**：窗口内连续改多处 ⇒ 只发一次，正文是最后一次的**整份**草稿；
 * 3. **在飞闸**：一次保存没回来时不并发第二个；期间又有变更 ⇒ 只留「最新一次」在飞结束后补发
 *    （不排队 —— 队列长度会随敲键数增长）；
 * 4. **失败不设基线**：422 ⇒ 理由逐条上屏、草稿**不回滚**，商家改对后下一次变更自动重试。
 *
 * 保存态（保存中 / 已保存 · 时间 / 保存失败 · N 条理由）在面板里**一处**小字说清（§31 P2）；
 * 成功**不弹 toast**（每次变更弹一次会把商家淹掉），失败仍播一次（既有 `isErrorToastShown` 去重）。
 *
 * 🔴 「恢复为默认值」**随按钮一起去掉**（用户明确不要这个功能，不要再给它找替代入口）：
 * 引擎默认值仍是**信息**（`source` 徽标 + 「本企业尚未保存过算料口径」横幅），不再是**动作**。
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
 *
 * 🔴 小数位统一取 `CALC_INPUT_DECIMALS`（3 位 = 毫米，与各列 `NUMERIC(6,3)` 同口径；
 * issue #7548 —— 用户 2026-10-23：「算料口径的输入框都允许设置3位小数」）。**不传 `decimals`**
 * 就是组件默认的 2 位 ⇒ 失焦把 `0.125` 归一成 `0.13`（输入被静默改值）。
 * 判据：`frontend/admin-web/tests/unit/components/CalcCaliberPanel.test.tsx` 判据 10（含类级）。
 */
import { Fragment, useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { AlertCircle, ChevronDown, ChevronRight } from 'lucide-react'
import { toast } from 'sonner'
import { NumberInput, SELECT_CONTROL, SELECT_CONTROL_FIELD } from '@/components/ui'
// issue #7176：配置面表单的**唯一版式原语**（浅底面板 + 栅格 + 标签在上 + 单位入框）。
// 🔴 本文件**不再自己拼 label + input 的版式** —— 那是「同一产品三种字段语言」的来源。
import FormPanel, { FIELD_CONTROL, Field, FormGrid, fieldControl } from '@/components/ui/FormPanel'
import { OversizeThresholdPreview } from '@/components/settings/OversizeThresholdPreview'
import { CraftCalcGlossary } from '@/components/production/CraftCalcGlossary'
import { productionApi } from '@/lib/api'
import { isErrorToastShown } from '@/lib/api-error'
import { InlineMarkdown } from '@/lib/inline-markdown'
import { CRAFT_CALC_FORMULA_LABELS } from '@/lib/craft-calc-request'
import { CALC_FIELD_GROUPS, CALC_INPUT_DECIMALS, CALC_PARAM_COPY } from '@/lib/craft-calc-glossary'
import { craftCalcConfigGuardReasons } from '@/lib/production-guard-reasons'
import {
  PARAM_DOMAINS,
  isUsingEngineDefault,
  type ParamDomain,
  type ScalarParam,
} from '@/lib/tenant-params'
import type { CraftCalcConfig, CraftCalcConfigResponse } from '@/types'
import { cn } from '@/lib/utils'

/**
 * 控件的「铬」已上收到 `frontend/admin-web/src/components/ui/FormPanel.tsx` 的 `FIELD_CONTROL`
 * （issue #7176：同一产品只留一种字段形态 —— 浅底面板 + 栅格 + 标签在上 + 单位入框）。
 *
 * 🔴 这里**不再**定义第二份控件样式、也不再给控件定宽：宽度由 `FormGrid` 的列宽决定
 * （定宽 `w-40` 曾在「标签在上」的版式里留出一排空白，见 issue #7176 的截图读数）。
 */

/**
 * 一个参数字段（**标签在上、控件在下、口径提示收尾**）。
 *
 * 🔴 为什么控件不跟标签同一行（#6857 曾是同行，本次改版推翻）：标签是「单色每折用料（米）」这种
 * 长短不一的句子，同行布局下每个输入框的起点都不同 —— 一屏 6 个框排不出一条竖线（用户判「丑陋」的
 * 主因）。竖排后左边界由**栅格**决定，与标签长短无关。
 *
 * 默认值徽标**不在行内标**：默认态由域级信号承担（顶部横幅 + 口径徽标，§31 P2「信息不重复」）。
 * 🔴 「恢复为默认值」按钮已随 issue #7183 退场（用户裁定不需要该功能）：引擎默认值仍是**信息**
 * （由 `source` 徽标承担），不再是**动作** —— 不要按「缺了回退入口」把它加回来。
 */
export function ParamField({
  param,
  value,
  control,
}: {
  param: ScalarParam
  /** 只读值（`control` 缺省时印在控件位）；**读面未落地时调用方传 `'…'`**（不谎报） */
  value: string
  /** 控件（可编辑时给 `NumberInput`；不传 ⇒ 只读，同位置印值） */
  control?: ReactNode
}) {
  const { text, unit } = splitUnit(param.copy.label)
  return (
    /* 版式 = **标准字段**（issue #7176）：标签在上（`text-xs`）+ 控件在下 + 口径提示收尾。
       与「属性行」的区别：控件不在标签右边，而是**占满所在栅格列** —— 全站配置面只有这一种字段形态。 */
    <Field
      testid={`param-${param.key}`}
      label={<InlineMarkdown text={text} />}
      /* 单位由 `Field` 画成**框内后缀**（只在有控件时）：只读值自己带单位，不需要叠一层 */
      unit={control ? unit : null}
      hint={<InlineMarkdown text={param.copy.hint} />}
    >
      {control ?? (
        <span
          data-testid={`param-value-${param.key}`}
          className="block text-sm leading-9 text-neutral-900"
        >
          {value}
          {unit !== null && <span className="ml-1 text-xs text-neutral-500">{unit}</span>}
        </span>
      )}
    </Field>
  )
}

/**
 * 把标签末尾的「（单位）」拆出来（`单色每折用料（米）` ⇒ `单色每折用料` + `米`）。
 *
 * ⚠️ **文案仍是单一真值**：`CALC_PARAM_COPY[...].label` 一字不动，这里只做**展示拆分**
 * （决定单位在表单里出现的位置 = 框内后缀）。没有括号单位 ⇒ 原样返回，不编造。
 */
export function splitUnit(label: string): { text: string; unit: string | null } {
  const m = /^(.+?)（([^（）]+)）$/.exec(label)
  return m ? { text: m[1], unit: m[2] } : { text: label, unit: null }
}

/**
 * 表单里的**一个区块** = `FormPanel`（issue #7176）—— 分组靠它表达，区块之间**不画分隔线**：
 * 浅底面板本身就是「一组」的边界，行内细线是上一版「8 行 8 条线」的病灶。
 */

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
   *
   * 🔴 **给了它才**变更即保存（issue #7183）：草稿变更 → 防抖 0.6 秒 → 调它；
   * 不给 ⇒ 只读退化形态，**一个写请求都不发**（本组件不自己造写面）。
   * 抛错 ⇒ 本面板把 `error.details[].message` 逐条上屏、**草稿不回滚**（下一次变更自动重试）。
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

/**
 * 变更即保存的防抖窗口（issue #7183）。
 *
 * 为什么是 0.6 秒：同一个框里敲 `0.2` 会连着产生多次变更，逐个发 `PUT` 就是多次**整份替换**；
 * 窗口要短到「敲完就觉得已经存了」，又要长到能合并这些中间态（用户裁定里的「输入框变更后即保存」）。
 */
const AUTOSAVE_DEBOUNCE_MS = 600

/** 保存态（取代旧保存按钮的文案；§31 P2：同一个状态只在**一处**说） */
type CalcSaveState =
  | { kind: 'idle' }
  | { kind: 'saving' }
  | { kind: 'saved'; at: Date }
  | { kind: 'failed'; count: number }

/** 本地时间 `HH:mm`（保存态用；不做时区换算，也不为一行时间引格式化库） */
function formatClock(at: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(at.getHours())}:${pad(at.getMinutes())}`
}

/**
 * 整份配置的**深相等**（基线判据：「草稿 == 上次成功保存的那一份」⇒ 没有要保存的东西）。
 *
 * 🔴 为什么不用 `JSON.stringify` 比字符串：键序不同会把同一份配置判成「变了」⇒ 读面回写一次
 * 就白发一次 `PUT`，而写面是**整份替换** —— 白发不是空操作（会把正在改的中间态盖回基线）。
 * 比的是纯 JSON 结构（数字 / 字符串 / 布尔 / 对象 / 数组 / `NaN` 哨兵），不引第三方依赖。
 */
function calcConfigEqual(a: unknown, b: unknown): boolean {
  if (a === b) return true
  // `NaN`（数字框被清空时落的哨兵）与自身不相等 —— 但「清空后再清空」是同一状态，不该判成变更
  if (typeof a === 'number' && typeof b === 'number') return Number.isNaN(a) && Number.isNaN(b)
  if (typeof a !== 'object' || typeof b !== 'object' || a === null || b === null) return false
  const left = a as Record<string, unknown>
  const right = b as Record<string, unknown>
  const keys = Object.keys(left)
  if (keys.length !== Object.keys(right).length) return false
  return keys.every(
    (k) => Object.prototype.hasOwnProperty.call(right, k) && calcConfigEqual(left[k], right[k]),
  )
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
  /** 保存态（取代旧保存按钮的文案：保存中 / 已保存 · 时间 / 保存失败 · N 条理由） */
  const [saveState, setSaveState] = useState<CalcSaveState>({ kind: 'idle' })
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

  /**
   * 🔴 **变更即保存**（issue #7183，2026-10-18 用户裁定）—— 底部保存条与「恢复为默认值」已整体退场。
   *
   * 四条不变量（对应 `frontend/admin-web/tests/unit/components/CalcCaliberPanel.test.tsx` 判据 9）：
   * 1. **首屏 / 读面刷新不写**：基线 = 读面给的整份配置，草稿与它深相等 ⇒ 一个请求都不发；
   * 2. **防抖合并**：窗口内连续改多处 ⇒ 只发一次（正文是最后一次的整份草稿）；
   * 3. **在飞闸**：一次 `PUT` 没回来时不并发第二个；期间又有变更 ⇒ 只留「最新一次」，
   *    回来后按**最新草稿**补发（不排队 —— 队列长度会随敲键数增长）；
   * 4. **失败不设基线**：422 ⇒ 理由逐条上屏、草稿**不回滚**，商家改对后下一次变更自然重试。
   *
   * ⚠️ 只在 `typeof onCalcSave === 'function'` 时工作：只读退化形态一个请求都不发。
   */
  const saveWritable = typeof onCalcSave === 'function'
  /** 基线：上次**成功保存**（或读面落地）时那份整份配置 */
  const baselineRef = useRef<CraftCalcConfig | null>(null)
  const baselineReadyRef = useRef(false)
  /** 最新草稿 / 最新保存回调（防抖回调若读渲染期闭包，补发的会是**旧草稿** = 静默丢最后一次输入） */
  const draftRef = useRef<CraftCalcConfig | null>(null)
  const saveRef = useRef(onCalcSave)
  /** 防抖计时器 / 在飞闸 / 「在飞期间又改过」标记（**布尔**不是队列：多次变更坍缩成一次补发） */
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const inFlightRef = useRef(false)
  const pendingRef = useRef(false)

  /**
   * 基线 = **读面给的整份配置**（首屏与读面刷新都据此判「没有变更」，不写库）。
   *
   * 依赖用 `calc` 的**对象标识**（每次读面落地都是新对象）—— 与页面里同步草稿的那条 effect 同源，
   * 这样「保存成功 → 页面回填服务端新对象」也不会被当成一次新变更。
   */
  useEffect(() => {
    baselineRef.current = calc?.config ?? null
    baselineReadyRef.current = true
  }, [calc])

  // 防抖回调必须读**最新**草稿与回调（每次渲染同步一次，比 useCallback 依赖链简单且不会漏）
  useEffect(() => {
    draftRef.current = draft
    saveRef.current = onCalcSave
  })

  const flushSave = useCallback<() => Promise<void>>(async () => {
    const save = saveRef.current
    if (typeof save !== 'function') return
    // 在飞闸：不发第二个；标记「回来后按最新草稿补发一次」（多次变更在这里坍缩成一次）
    if (inFlightRef.current) {
      pendingRef.current = true
      return
    }
    const target = draftRef.current
    if (target === null || calcConfigEqual(target, baselineRef.current)) return
    inFlightRef.current = true
    pendingRef.current = false
    setSaveState({ kind: 'saving' })
    try {
      await save()
      // 基线 = **刚提交成功的那一份**（不是「当前草稿」—— 期间可能又有新变更等着补发）
      baselineRef.current = target
      setSaveState({ kind: 'saved', at: new Date() })
      setReasons([])
    } catch (e) {
      const nextReasons = craftCalcConfigGuardReasons(e)
      setReasons(nextReasons)
      setSaveState({ kind: 'failed', count: nextReasons.length })
      // 失败仍播一次（既有 `isErrorToastShown` 去重）；**成功不播** —— 每次变更弹一次会把商家淹掉
      if (!isErrorToastShown(e)) toast.error('算料配置保存失败')
    } finally {
      inFlightRef.current = false
      if (pendingRef.current) {
        pendingRef.current = false
        void flushSave()
      }
    }
  }, [])

  useEffect(() => {
    if (!saveWritable || draft === null) return
    // 首次挂载：基线 = 当前草稿（调用方已把它初始化为读面配置）⇒ 打开页面不写库
    if (!baselineReadyRef.current) {
      baselineRef.current = draft
      baselineReadyRef.current = true
      return
    }
    // 草稿回到基线（读面回写 / 商家改回原值）⇒ 没有可保存的东西，撤掉待发的那次
    if (calcConfigEqual(draft, baselineRef.current)) {
      if (timerRef.current !== null) {
        clearTimeout(timerRef.current)
        timerRef.current = null
      }
      return
    }
    // 防抖：窗口内再改 ⇒ 只留最后一次
    if (timerRef.current !== null) clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => {
      timerRef.current = null
      void flushSave()
    }, AUTOSAVE_DEBOUNCE_MS)
  }, [draft, saveWritable, flushSave])

  /**
   * 卸载（切到别的域 / 离开本页）时把**待发的那一次**发出去。
   *
   * 不这么做，「敲完立刻切域」会静默丢掉最后一次输入 —— 而防抖窗口里还没有任何保存态可看。
   */
  useEffect(
    () => () => {
      if (timerRef.current === null) return
      clearTimeout(timerRef.current)
      timerRef.current = null
      void flushSave()
    },
    [flushSave],
  )

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
            className={`${fieldControl(splitUnit(p.copy.label).unit)} tabular-nums`}
            aria-label={`${p.copy.label}`}
            data-testid={`calc-caliber-scalar-${p.key}`}
            value={numberOf(displayConfig, p.key)}
            decimals={CALC_INPUT_DECIMALS}
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
  /** 拼色每折用料的**单位**与**无单位标题**（从标签尾部拆出来做框内后缀；文案本身仍是单一真值） */
  const mixedUnit = splitUnit(CALC_PARAM_COPY.per_fold_mixed_times.label).unit
  const mixedTitle = splitUnit(CALC_PARAM_COPY.per_fold_mixed_times.label).text

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

      {/* 口径来源：「系统默认值」≠「你的配置」（读失败时不画 —— 那是读成功才知道的事）。
          形态 = **小圆点 + 一行灰字**，不是浅色药丸（药丸看着像调试标记）。 */}
      {!failed && calc && (
        <span
          data-testid="calc-caliber-source"
          className="inline-flex items-center gap-1.5 text-xs text-neutral-500"
        >
          <span
            aria-hidden
            className={`inline-block h-1.5 w-1.5 flex-shrink-0 rounded-full ${
              calc.source === 'stored' ? 'bg-emerald-500' : 'bg-neutral-400'
            }`}
          />
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
        <div className="space-y-4">
          {/* 🔴 「没有保存按钮」这件事必须**说出来**（同 #5899 企业信息域的做法）—— 否则商家会去找它。
              静态说明 + 动态保存态同一行：§31 P2，同一个状态只在一处说，不另起第二条常驻横幅。 */}
          {/* 只有**真能保存**时才说这句话（只给草稿回调、不给保存回调的形态下，「自动保存」是假话） */}
          {saveWritable && displayConfig && (
            <div className="flex flex-wrap items-baseline gap-x-2">
              <span className="text-xs text-neutral-500">
                修改后自动保存（约 0.6 秒），无需手动提交
              </span>
              <span
                data-testid="calc-caliber-save-state"
                /* 域写面台账的「出口」标记（issue #6825）：改前挂在保存按钮上，按钮随 #7183 退场 ——
                   自动保存本身就是写出口，标记随「保存态」这处可见证据走。 */
                data-write-exit="calc"
                role="status"
                aria-live="polite"
                className="text-xs text-neutral-500"
              >
                {saveState.kind === 'saving' && '保存中…'}
                {saveState.kind === 'saved' && `已保存 · ${formatClock(saveState.at)}`}
                {saveState.kind === 'failed' && `保存失败 · ${saveState.count} 条理由`}
              </span>
            </div>
          )}

          {/* ── 用布与余量（及其它非阈值分组） ── */}
          {leadingGroups.map((g) => (
            <FormPanel key={g.key} testid={`calc-caliber-group-${g.key}`} title={g.title}>
              <FormGrid>{g.params.map(renderScalar)}</FormGrid>
            </FormPanel>
          ))}

          {/* ══════════ 档位与拼色（原在板子的「算料配置」tab 里，issue #6825 并入本域） ══════════
              🔴 issue #7176：**不再是小表**。两张 `w-fit` 小表贴内容不撑行 ⇒ 真机右侧空出 78px
              （读数：内容宽 764 时左卡 423 / 右卡 245 / 右侧空白 79）。
              现在与「阈值试算」**同一套字段面板**（`FormPanel` + `FormGrid` + `Field`）：两组各占一半、
              栅格撑满 ⇒ 右侧空白归零；单位仍做框内后缀（`米`），标签仍是文案单一真值。 */}
          {writable && displayConfig && (
            <div data-testid="calc-caliber-group-rules" className="space-y-4">
              <div className="grid items-start gap-4 sm:grid-cols-2">
                {/* 档位表：每档两个字段（顾客看到的名字 + 褶倍） */}
                <FormPanel
                  testid="calc-caliber-group-tiers"
                  title={CALC_PARAM_COPY.tiers.label}
                  hint={<InlineMarkdown text={CALC_PARAM_COPY.tiers.hint} />}
                >
                  <FormGrid cols={2}>
                    {Object.entries(tiers).map(([name, tier]) => (
                      <Fragment key={name}>
                        <Field
                          label={`${tierLabelOf(name)} 显示名`}
                          htmlFor={`calc-caliber-tier-${name}-label`}
                        >
                          <input
                            id={`calc-caliber-tier-${name}-label`}
                            className={FIELD_CONTROL}
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
                        </Field>
                        <Field
                          label={`${tierLabelOf(name)} 褶倍`}
                          htmlFor={`calc-caliber-tier-${name}-fullness`}
                        >
                          <NumberInput
                            id={`calc-caliber-tier-${name}-fullness`}
                            className={`${FIELD_CONTROL} tabular-nums`}
                            aria-label={`${tierLabelOf(name)} 褶倍`}
                            data-testid={`calc-caliber-tier-${name}-fullness`}
                            decimals={CALC_INPUT_DECIMALS}
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
                        </Field>
                      </Fragment>
                    ))}
                  </FormGrid>
                </FormPanel>

                {/* 拼色每折用料：一行一个拼色次数（单位做框内后缀） */}
                <FormPanel
                  testid="calc-caliber-group-mixed"
                  title={mixedTitle}
                  hint={<InlineMarkdown text={CALC_PARAM_COPY.per_fold_mixed_times.hint} />}
                >
                  <FormGrid cols={2}>
                    {Object.entries(mixed).map(([times, perFold]) => (
                      <Field
                        key={times}
                        label={`拼${times}次`}
                        unit={mixedUnit}
                        htmlFor={`calc-caliber-mixed-${times}`}
                      >
                        <NumberInput
                          id={`calc-caliber-mixed-${times}`}
                          className={`${fieldControl(mixedUnit)} tabular-nums`}
                          aria-label={`拼${times}次 每折用料`}
                          data-testid={`calc-caliber-mixed-${times}`}
                          decimals={CALC_INPUT_DECIMALS}
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
                      </Field>
                    ))}
                  </FormGrid>
                </FormPanel>
              </div>

              {/* 备用公式（工艺能推导时以工艺为准，这里只是推导表缺失时的兜底）。
                  标题即字段名（面板标题 = 视觉标签）+ 说明收口；控件与其余字段同一铬、同一条左沿。 */}
              <FormPanel
                testid="calc-caliber-group-formula"
                title={CALC_PARAM_COPY.default_formula.label}
                hint={<InlineMarkdown text={CALC_PARAM_COPY.default_formula.hint} />}
              >
                <div className="mt-3 max-w-xs">
                  {/* 取值域与文案 = **单一真值** `CRAFT_CALC_FORMULA_LABELS`（不另写一份映射） */}
                  <select
                    id="calc-caliber-formula"
                    className={cn(SELECT_CONTROL_FIELD, 'w-full')}
                    aria-label={CALC_PARAM_COPY.default_formula.label}
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
                </div>
              </FormPanel>
            </div>
          )}

          {/* ── 超高 / 超宽阈值 + 试算（同一件事的两半：上半个改阈值，下半个看它会不会变） ── */}
          {thresholdGroup && (
            <FormPanel testid={`calc-caliber-group-${thresholdGroup.key}`} title={thresholdGroup.title}>
              <FormGrid>{thresholdGroup.params.map(renderScalar)}</FormGrid>
            </FormPanel>
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
                <FormPanel className="mt-4">
                  <FormGrid testid={`param-advanced-${domain.key}`}>
                    {domain.advanced.map(renderScalar)}
                  </FormGrid>
                </FormPanel>
              )}
            </div>
          )}

          {/* 护栏理由**逐条**展示（后端一次列出每一处不合法）—— 不吞成一句「保存失败」。
              🔴 issue #7183：保存条已退场，但理由**位置沿用现状**（面板底部、字段下方，不另开弹窗）——
              商家刚在哪个字段上出错，理由就在它附近；改对之后**下一次变更自动重试**（不需要按钮）。 */}
          {saveWritable && reasons.length > 0 && (
            <ul
              /* §31 P1：逐条明细**封顶滚动**（不随条数把常驻面撑高）—— 后端一次可能列出多处不合法 */
              className="max-h-40 space-y-1 overflow-y-auto rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-600"
              data-testid="calc-caliber-reasons"
            >
              {reasons.map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
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
