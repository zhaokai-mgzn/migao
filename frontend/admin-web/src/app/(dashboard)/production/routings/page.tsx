'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  AlertCircle,
  ArrowDown,
  ArrowUp,
  Check,
  Pencil,
  Plus,
  RefreshCw,
  Star,
  Trash2,
  X,
} from 'lucide-react'
import { toast } from 'sonner'
import { Button, Modal } from '@/components/ui'
import { isErrorToastShown, toastRequestError } from '@/lib/api-error'
import { productionApi } from '@/lib/api'
import { craftCalcConfigGuardReasons, optionPriceGuardReasons, routingAdminGuardReasons, routingGuardReasons } from '@/lib/production-guard-reasons'
import { cn } from '@/lib/utils'
import type {
  CatalogOperation,
  CraftCalcConfig,
  CraftCalcConfigResponse,
  OperationPosition,
  OperationPositionUpdateParams,
  OperationsCatalog,
  ProductionScope,
  ProductionSeedTemplate,
  ProductionSource,
  ProductionOperationUpdateParams,
  RouteRule,
  RouteRuleCreateParams,
  Routing,
  RoutingsResponse,
} from '@/types'

/**
 * 工艺配置 /production/routings（issue #4416 合并单页；issue #4433 = 母单 #4423 的 **P3** 适配新模型）
 *
 * ## 新模型下这一页回答两个问题（**一屏一件事**，不做功能平铺）
 *
 * | tab | 它回答的问题 | 主区 | 维护面 |
 * |---|---|---|---|
 * | **工艺项** | 「每道工序在**哪个部位**做、给**工人**多少钱？」 | **一张表**：行 = 逻辑工序、列 = 部位、格 = 价 / 不做 / 未定价（**格内就地可改**） | 行尾 = `分组 · 单位` + **必完标记**（issue #4610：完工门槛要一眼看得见，部分部位必完时注明）+「管理▸」抽屉（变体：分组 / 单位 / 作用域 / 必完 / 停用 / 删除） |
 * | **工艺路线** | 「订单按哪条主线走、什么时候插/删工序？」 | 具名路线（默认徽标 + 适用帘种 + 主线 + 改名/设默认/删除） | 条件工序规则（26 条；**常驻展开**，issue #4613 起不可折叠） |
 *
 * **工艺项为什么不再分「主区 / 折叠次区」**（issue #4588 = 母单 #4586 包 B；契约 #4587）：
 * 原形态是**两张平铺表** —— 主区 84 格**只读**矩阵 + 折叠次区 35 行「工序库明细」（能改计件单价
 * 但**改了不生效**：真正生效的是矩阵格）。同一个概念两个载体、改一处不生效、还没有任何提示
 * ⇒ 用户裁定**方案 A：合并成一屏一张表**（用户原话：「工艺项我确实没看懂这样设计是要干啥」）。
 * 「一屏一件事」的纪律不变，只是这件事现在由**一张表**承载，明细面收进**抽屉**（不是平铺）。
 *
 * **这一屏的价是「给工人的计件单价」**（用户裁定 2026-09-19）：
 * `production_operation_positions.unit_price` = 计件单价，**报工工资 = 数量 × 计件单价**。
 * 收顾客的那笔钱**不在这里** —— 基础工序在「加工项组合费用」，特殊选项在「条件工序规则」
 * （`production_route_rules.customer_unit_price`，元/套）。两本账**互不换算** ⇒ 这一屏
 * **不得**出现「加工费」「对客价」字样，也**不引入任何计件系数概念**。
 *
 * ## 与旧形态的三处关键差异（P2b #4459 / P2c #4500 之后）
 *
 * 1. **路线 = 一条具名主线**（`{id, name, is_default, positions, mainline}`），不再是
 *    「部位 × 工艺」展开快照 ⇒ 列表显示**总名**+默认徽标+适用帘种，**不再**出现 `部位 × 工艺` 标题；
 *    改名**只改 `name`**（不给 `mainline` 就不动序列 —— 改一个名字不该顺带重写计件工资的输入）。
 * 2. **部位价目矩阵的行键是逻辑工序名**（`精裁` / `三边`），**不是** `production_operations.name`
 *    （那边仍是旧名 `精裁-布` / `布三边`）。issue #4588（契约 #4587 ①）起矩阵每格**多带** 6 个
 *    变体元数据键（`variant_operation_id` / `variant_name` / `unit` / `group` / `scope` /
 *    `is_must_finish`）—— 由后端 `variantNameOf` 推导，前端**直接渲染、不另写一份推导**；
 *    6 键全 `null` = 查不到 ⇒ **不发明元数据**（静默 = 未知）。
 *    主线的「工序是否存在」判据**不变**：按「工序库 ∪ 矩阵」两侧并集判定
 *    （只按工序库判会让每条种子路线都误报「工序库中不存在」）。
 * 3. **顺序口径**：`operation-positions` 按 `(operation, position)`、`route-rules` 按 `(priority, id)`
 *    —— **服务端已排好**，前端**不重排**（重排会与服务端口径分叉，同一张单两次生成会得到不同序列）。
 *
 * ## 护栏（后端仍是唯一权威；前端只把「保存失败」提前成「看得见」）
 *
 * - **删默认 ⇒ 拦**（默认路线是兜底终点，删了没有专属路线的订单一张加工单也生成不了）；
 * - **删最后一条 ⇒ 拦**（同因）；两条同时成立时**两条理由都给**（后端也一次报全）；
 * - **设为默认**只对非默认行开放（`is_default:false` 后端 422 ⇒ 前端**永不**提交 false）；
 * - 危险操作（删除 / 设为默认）**二次确认**；护栏理由**就地逐条**展示（复用 `lib/production-guard-reasons.ts`）；
 *   工艺项 tab 的两处删除同口径：删**工序变体**（`DELETE /operations/{id}`，三条护栏一次报全）与
 *   删**条件工序规则**（`DELETE /route-rules/{id}`，无硬护栏）—— 都先二次确认，被拒时逐条就地给理由。
 * - 商家面**不得**出现内部机制名（issue #4453：「信号映射」是研发内部机制）⇒ 后端理由过
 *   `merchantWording` 只换词、不删理由。
 *
 * ## 契约（冻结，**不得自行发明端点/字段名**）
 *   GET    /api/admin/production/routings                 POST /routings   body {name, mainline?, positions?, is_default?}
 *   PUT    /api/admin/production/routings/{id}            DELETE /routings/{id}      （部分更新 {name?, is_default?, mainline?, positions?, status?}）
 *   GET    /api/admin/production/operation-positions      GET  /route-rules
 *   PUT    /api/admin/production/operation-positions/{id}  （#4588 矩阵格写面：部分更新 {unit_price?} / {applicable?}）
 *   DELETE /api/admin/production/operations/{id}          （#4588 工序软删：三条护栏一次报全）
 *   DELETE /api/admin/production/route-rules/{id}         （#4588 规则软删：无硬护栏）
 *   GET    /api/admin/production/operations-catalog       POST /production/operations
 *   PUT    /api/admin/production/operations/{id}          （改分组 / 单位 / 必完 / 作用域 / status）
 *   GET|POST /api/admin/production/seed-templates[/{id}/apply]
 *   —— 写端点权限 processing:manage（以拦截器/后端为准，本页不做显隐分叉）。
 *
 * 真值源：docs/curtain-production-rules.md §2 工序库 / §3 工艺路线；
 * 领域模型与裁定：docs/design/position-instance-routing-model.md（R-c 作用域 / R-f 解绑加工项）。
 */

/**
 * 金额展示（`¥` + 两位小数）。
 * ⚠️ `null` 会渲染成 `¥0.00` —— 即「未定价」被显示成「0 元」。**未定价的字段不得直接喂进来**：
 * 先判 `null`（如 {@link RulePriceCell} 的「未定价」分支），再调本函数。
 */
const money = (v?: number | string | null) => `¥${Number(v ?? 0).toFixed(2)}`

/**
 * 部位（帘种）**列序基线 + 兜底** —— 它**不是**值域权威（issue #4556）。
 *
 * 取值域的真源 = `production_operation_positions.position`，而本页**已经在读**它
 * （`GET /operation-positions` 的部位价目矩阵）⇒ 可选部位由 {@link positionOptions} 从矩阵带出：
 * 矩阵里出现的部位**自动**进选项，**新增部位不需要改这一行**（改这一行就是「值域在页面里硬编码」
 * 的又一次漂移 —— 同族 #4440，也正是本条缺陷的成因：包 F / #4529 落库的第 4 个部位 `布料`
 * 读面看得见、写面却建不出来）。
 *
 * 它只剩两个用途：① 矩阵列 / 勾选项的**基线顺序**；② 矩阵**未加载或为空**时的兜底选项
 * （页面不至于连路线都建不出来）。
 * ⚠️ 后端**没有**部位枚举端点（#4556 实测）：`GET /operation-positions` 是**数据行**（按租户），
 * 不是词表。后端自己那份同形常量 `ProductionRoutingCommandService.DEFAULT_POSITIONS` 的语义是
 * **新路线的默认适用帘种**（见 `newRoute` 初值），**不是**可选范围。
 */
const POSITION_DOMAIN = ['布帘', '纱帘', '帘头']

const inputCls =
  'h-9 w-full rounded border border-neutral-300 bg-white px-3 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15 placeholder:text-neutral-400'

/**
 * provenance 三态 → 徽标（#4361 冻结取值）。未知/缺省（老实例未升级）**不渲染任何徽标** ——
 * 静默 = 未知，**不得**显示成「实证」（同 route-source 口径）。
 * 「占位待确认」文案要让商家看懂：它说的是**单价是初始占位值，需确认**，而不是工序本身有问题。
 */
const SOURCE_META: Record<ProductionSource, { label: string; className: string }> = {
  实证: { label: '实证', className: 'bg-emerald-50 text-emerald-700' },
  推算: { label: '推算', className: 'bg-neutral-100 text-neutral-500' },
  占位待确认: { label: '初始价·待确认', className: 'bg-amber-50 text-amber-700' },
}

/**
 * 工序作用域两档（V67，issue #4384 A1）——**闭词表**，与后端 `ProductionOperationCommandService`
 * 的校验、迁移 V67 的列注释同口径（前端不发明第三值）。
 */
const SCOPE_META: Record<ProductionScope, { label: string; title: string }> = {
  position: { label: '部位级', title: '每部位一次（如布帘一道、纱帘一道）' },
  set: { label: '套级', title: '每樘窗一次（一樘「布 + 纱」只做一次）' },
}
const SCOPE_ORDER: ProductionScope[] = ['position', 'set']

/**
 * 库口径 → 受控两档。**缺省按 `position`**（安全方向）：列是 `NOT NULL DEFAULT 'position'`，
 * 老实例未升级时键缺失 —— 默认成 `set` 会把每道工序都静默去重，默认成 `position` 最坏只是保持今天的行为。
 */
const scopeOf = (op: CatalogOperation): ProductionScope => (op.scope === 'set' ? 'set' : 'position')

/** 触发维（V71 列注释的闭词表；`shaped` / `processing_item` 是表结构预留，无种子行） */
const TRIGGER_KIND_LABEL: Record<string, string> = {
  craft: '工艺',
  option: '特殊选项',
  shaped: '是否定型',
  processing_item: '加工项',
}

/** 规则动作的可读文案：`insert` 带锚点（无锚点 = 追加末尾）/ `remove` 移除 */
const ruleActionText = (rule: RouteRule) =>
  rule.action === 'remove'
    ? `移除「${rule.operation ?? '—'}」`
    : `在「${rule.after_operation ?? '末尾'}」之后插入「${rule.operation ?? '—'}」`

/**
 * 条件工序规则的「单价（元/套）」格（issue #4567）。
 *
 * 三态**互斥**且可区分（同矩阵的「不做 / 没定价」纪律）：
 * - `option` + 有价 ⇒ `money()`；
 * - `option` + `null` ⇒ **「未定价」** —— ⚠️ **不是** `¥0.00`（未定价 ≠ 0 元，仓库硬纪律；
 *   `money(null)` 会算出 `¥0.00`，正是这里必须绕开的假值）；
 * - 非 `option`（`craft` 等）⇒ `—` + `title` 说明「只有特殊选项按套计价」。
 *
 * `option` 行带**行内编辑**（照「工序库明细」改计件单价的既有交互：铅笔 → 输入 → 保存/取消）；
 * 编辑态下失败理由**就地逐条**展示 —— 与计件单价那一栏同形态（同一页两套账，交互一致、
 * 但写的是**不同**端点、**不同**的列）。
 */
function RulePriceCell({
  rule,
  editing,
  draft,
  busy,
  reasons,
  onStartEdit,
  onDraftChange,
  onSave,
  onCancel,
}: {
  rule: RouteRule
  editing: boolean
  draft: string
  busy: boolean
  reasons: string[]
  onStartEdit: () => void
  onDraftChange: (v: string) => void
  onSave: () => void
  onCancel: () => void
}) {
  const isOption = rule.trigger_kind === 'option'
  const raw = rule.customer_unit_price
  const unpriced = raw === null || raw === undefined || raw === ''
  const state = !isOption ? 'na' : unpriced ? 'unpriced' : 'priced'
  const hasPrice = state === 'priced'
  return (
    <td
      className={cn('py-2.5 pr-4', state === 'unpriced' ? 'text-amber-600' : 'text-neutral-600')}
      data-testid={`route-rule-price-${rule.id}`}
      data-state={state}
      title={isOption ? '特殊选项按套收费（元/套）' : '只有特殊选项按套计价'}
    >
      {state === 'na' ? (
        '—'
      ) : editing ? (
        <span className="flex items-center gap-1.5">
          <input
            type="number"
            min="0"
            step="0.01"
            aria-label={`${rule.trigger_value ?? ''} 单价（元/套）`}
            data-testid={`route-rule-price-input-${rule.id}`}
            value={draft}
            disabled={busy}
            onChange={(e) => onDraftChange(e.target.value)}
            className={cn(
              'h-8 w-24 rounded border bg-white px-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500/15',
              reasons.length > 0
                ? 'border-red-300 focus:border-red-400'
                : 'border-neutral-300 focus:border-primary-500',
            )}
          />
          <button
            type="button"
            aria-label="保存单价"
            data-testid={`route-rule-price-save-${rule.id}`}
            disabled={busy}
            onClick={onSave}
            className="rounded p-1 text-primary-600 hover:bg-neutral-100 disabled:opacity-50"
          >
            <Check className="w-4 h-4" />
          </button>
          <button
            type="button"
            aria-label="取消"
            data-testid={`route-rule-price-cancel-${rule.id}`}
            disabled={busy}
            onClick={onCancel}
            className="rounded p-1 text-neutral-400 hover:bg-neutral-100 disabled:opacity-50"
          >
            <X className="w-4 h-4" />
          </button>
        </span>
      ) : (
        <span className="flex items-center gap-1.5">
          <span>{unpriced ? '未定价' : money(raw)}</span>
          <button
            type="button"
            aria-label={`编辑 ${rule.trigger_value ?? ''} 单价（元/套）`}
            data-testid={`route-rule-price-edit-${rule.id}`}
            onClick={onStartEdit}
            className="rounded p-1 text-neutral-400 hover:bg-neutral-100 hover:text-neutral-700"
          >
            <Pencil className="w-3.5 h-3.5" />
          </button>
        </span>
      )}
      {editing && reasons.length > 0 && (
        <ul
          className="mt-1 space-y-0.5 text-xs text-red-600"
          data-testid={`route-rule-price-reasons-${rule.id}`}
        >
          {reasons.map((r, i) => (
            <li key={i}>{r}</li>
          ))}
        </ul>
      )}
      {/* 编辑态下仍把「未定价 ≠ 0 元」写在旁边：清空输入框 = 改回未定价（不是 0 元） */}
      {editing && (
        <span className="mt-1 block text-[11px] text-neutral-400">
          {hasPrice ? '清空 = 改回未定价（≠ 0 元）' : '填 0 表示真 0 元；清空 = 未定价'}
        </span>
      )}
    </td>
  )
}

// ────────────────────────── 算料配置（tab「算料配置」，issue #4528 = 包 E） ──────────────────────────

/** 标量配置键（表单里逐个数字输入框；键名 = 后端列名 = 算料引擎配置键，**逐字同名**） */
type CalcScalarKey =
  | 'per_fold_single'
  | 'margin_single'
  | 'margin_multi'
  | 'min_fullness'
  | 'side_margin'
  | 'meters_rounding_step'

/** 六个标量键的展示元数据（**只有文案**：默认值/范围一律由后端给，前端不持有） */
const CALC_SCALAR_FIELDS: { key: CalcScalarKey; label: string; hint: string }[] = [
  { key: 'per_fold_single', label: '单色每折吃布（米）', hint: '折数法：用料 = 每折吃布 × 折数 + 余量' },
  { key: 'margin_single', label: '单开余量（米）', hint: '单开（一整幅）的包边余量' },
  { key: 'margin_multi', label: '多开余量（米）', hint: '双开/四开的包边 + 对缝余量' },
  { key: 'min_fullness', label: '褶倍下限', hint: '行业红线：不得低于系统默认值（低于它用料不足）' },
  { key: 'side_margin', label: '卷边（米）', hint: '定宽买高的上下卷边合计' },
  { key: 'meters_rounding_step', label: '进位步长（米）', hint: '用料只向上进位，不截断、不四舍五入' },
]

/** 兜底公式的可读文案（取值域由后端枚举给；这里只做展示映射） */
const CALC_FORMULA_LABEL: Record<string, string> = {
  pleat: '韩折公式（折数法）',
  fullness: '褶倍数公式（倍数法）',
}

/**
 * 工艺档位的**显示名**（issue #4567 用户走查②：「英文改中文」）。
 *
 * ⚠️ 这只是**显示名**，**不是**档位真值 —— 真值源 = 后端 `curtain_calc.py::DEFAULT_CRAFT_TIERS`
 * （前端不持有第二份档位定义，故这里**不**映射 `fullness`、**不**枚举全部档位）。
 * 键本身（`data-testid` 的 `${name}`、提交给 API 的 `tiers` 键、`label` 输入框初值）
 * **一律照旧用 `name`**：未知档**回退显示原键**（不吞掉、不猜中文）。
 */
const TIER_DISPLAY_LABEL: Record<string, string> = {
  standard: '标准档',
  economy: '经济档',
}

/** provenance 徽标；「占位待确认」是**可行动**引导：点它即进入该工序的改价入口（既有版本化写面） */
function SourceBadge({
  source,
  testId,
  onConfirmPrice,
}: {
  source?: ProductionSource | null
  testId: string
  onConfirmPrice?: () => void
}) {
  const meta = source ? SOURCE_META[source] : undefined
  if (!meta) return null
  const className = cn('ml-2 rounded px-1.5 py-0.5 text-[11px]', meta.className)
  if (source === '占位待确认' && onConfirmPrice) {
    return (
      <button
        type="button"
        data-testid={testId}
        onClick={onConfirmPrice}
        title="初始价（占位值），点此改成实际单价 —— 调价只影响新报工，历史报工按当时价"
        className={cn(className, 'underline decoration-dotted hover:brightness-95')}
      >
        {meta.label}
      </button>
    )
  }
  return <span data-testid={testId} className={className}>{meta.label}</span>
}

/** 就绪度一步（把「工序 → 路线 → 默认路线 → 算料」的先后关系变成看得见的步骤） */
function ReadinessStep({
  testId,
  index,
  label,
  state,
  hint,
}: {
  testId: string
  index: number
  label: string
  state: 'done' | 'todo' | 'unknown'
  hint?: string
}) {
  const done = state === 'done'
  /** 未知（如算料配置**还没加载完** / 加载失败）= **中性**呈现：把「没加载」显示成「没配」是误报 */
  const unknown = state === 'unknown'
  return (
    <div
      data-testid={testId}
      data-state={state}
      className={cn(
        'rounded border px-3 py-2',
        done
          ? 'border-emerald-200 bg-emerald-50/60'
          : unknown
            ? 'border-neutral-200 bg-neutral-50'
            : 'border-amber-200 bg-amber-50/60',
      )}
    >
      <div className="flex items-center gap-2 text-sm">
        <span
          className={cn(
            'font-medium',
            done ? 'text-emerald-800' : unknown ? 'text-neutral-700' : 'text-amber-900',
          )}
        >
          {index}. {label}
        </span>
        <span className={cn('text-xs', done ? 'text-emerald-700' : unknown ? 'text-neutral-500' : 'text-amber-800')}>
          {done ? '已完成' : unknown ? '读取中' : '待完成'}
        </span>
      </div>
      {!done && !unknown && hint && <p className="mt-1 text-xs text-amber-800">{hint}</p>}
    </div>
  )
}

/**
 * 主线上一步的展示口径（只读与草稿**共用一份** —— 两处各拼一份必然漂移）。
 *
 * ⚠️ `resolved` = 该工序能在**工序库**里查到（才有 分组/单位/必完 这些库口径元数据）。
 * 主线存的是**逻辑工序名**（`精裁`），而 `production_operations.name` 仍是旧名（`精裁-布`），
 * 两者之间**没有**暴露给前端的映射 ⇒ 前端**不猜**：查不到就只显示名字，不发明单位/必完。
 *
 * ⚠️ **本口径不含单价**（issue #4583 用户裁定）：单价是**计件工资**口径，属「工序项 / 部位价目」
 * 那一屏的事；而这里能拿到的只有**工序库单价**，真正生效的价是**部位价目矩阵**的格价
 * （`矩阵价 ?? 工序库价`，见 `ProcessingOrderService.buildRoute`）⇒ 显示它有误导性。
 * 且「显示与否」曾取决于「逻辑名与变体名是否恰好一致」（`外帘打卷`/`外帘装袋`/`外帘发货`
 * 三种部位同名才显示，其余 6 道不显示）⇒ **统一不显示**。
 */
interface StepView {
  seq: number
  operation: string
  group?: string | null
  unit?: string | null
  is_must_finish?: boolean
  /** 工序库里有这条（有库口径元数据） */
  resolved: boolean
  /** 工序库与部位价目表**都**没有它（停用/被删）⇒ 保存必被后端拒，但页面要先让人看见 */
  missing: boolean
}

/**
 * 部位价目**格**（issue #4588）：一屏一张表的单元格 —— 三态 + 格内就地改价 + 「不做 ⇄」。
 *
 * 三态**互斥**且可区分（既有判据，重做时不许丢）：
 * - `priced` ⇒ `¥x.xx`（`0` 是**真价**，照显示 `¥0.00` —— ≠「未定价」）；
 * - `unpriced` ⇒ 「未定价」（`applicable=true` 但 `unit_price=null`，是**待办**、不是 0 元）；
 * - `na` ⇒ 「不做」（`applicable=false`，**明确不做**，不是漏配）。
 *
 * 两个写动作**同一端点、不同 body**（契约 #4587 ② 是**部分更新** ⇒ body **只带**变了的键）：
 * 改价 ⇒ `{unit_price}`（清空 = `null` = 改回未定价）；「不做 ⇄」⇒ `{applicable}`。
 * 失败理由**就地逐条**展示（后端 `error.details[].message`，**不**吞成一句「保存失败」）。
 */
function PositionCell({
  cell,
  state,
  editing,
  draft,
  busy,
  reasons,
  onStartEdit,
  onDraftChange,
  onSave,
  onCancel,
  onToggleApplicable,
}: {
  cell: OperationPosition
  state: 'na' | 'unpriced' | 'priced'
  editing: boolean
  draft: string
  busy: boolean
  reasons: string[]
  onStartEdit: () => void
  onDraftChange: (v: string) => void
  onSave: () => void
  onCancel: () => void
  onToggleApplicable: () => void
}) {
  const key = `${cell.operation}-${cell.position}`
  const hasPrice = state === 'priced'
  return (
    <td
      data-testid={`matrix-cell-${key}`}
      data-state={state}
      title={
        state === 'na'
          ? `${cell.position}不做「${cell.operation}」这道工序`
          : state === 'unpriced'
            ? `${cell.position}做「${cell.operation}」，但还没定价（≠ ¥0.00）`
            : `${cell.position}「${cell.operation}」计件单价（给工人） ${money(cell.unit_price)}`
      }
      className={cn(
        'py-2.5 pr-4 align-top',
        state === 'na' ? 'text-neutral-400' : state === 'unpriced' ? 'text-amber-700' : 'text-neutral-900',
      )}
    >
      {state === 'na' ? (
        <span className="flex items-center gap-1.5">
          <span>不做</span>
          <button
            type="button"
            aria-label={`${key} 改成做这道工序`}
            data-testid={`matrix-applicable-${key}`}
            onClick={onToggleApplicable}
            className="rounded px-1 text-neutral-400 hover:bg-neutral-100 hover:text-neutral-700"
          >
            ⇄
          </button>
        </span>
      ) : editing ? (
        <span className="flex items-center gap-1.5">
          <input
            value={draft}
            inputMode="decimal"
            aria-label={`${key} 计件单价（给工人）`}
            data-testid={`matrix-price-input-${key}`}
            disabled={busy}
            onChange={(e) => onDraftChange(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && onSave()}
            className={cn(
              'h-8 w-24 rounded border bg-white px-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500/15',
              reasons.length > 0 ? 'border-red-300 focus:border-red-400' : 'border-neutral-300 focus:border-primary-500',
            )}
          />
          <button
            type="button"
            aria-label="保存计件单价"
            data-testid={`matrix-price-save-${key}`}
            disabled={busy}
            onClick={onSave}
            className="rounded p-1 text-primary-600 hover:bg-neutral-100 disabled:opacity-50"
          >
            <Check className="w-4 h-4" />
          </button>
          <button
            type="button"
            aria-label="取消"
            data-testid={`matrix-price-cancel-${key}`}
            disabled={busy}
            onClick={onCancel}
            className="rounded p-1 text-neutral-400 hover:bg-neutral-100 disabled:opacity-50"
          >
            <X className="w-4 h-4" />
          </button>
        </span>
      ) : (
        <span className="flex items-center gap-1.5">
          <span>{state === 'unpriced' ? '未定价' : money(cell.unit_price)}</span>
          <button
            type="button"
            aria-label={`编辑 ${key} 计件单价（给工人）`}
            data-testid={`matrix-price-edit-${key}`}
            onClick={onStartEdit}
            className="rounded p-1 text-neutral-400 hover:bg-neutral-100 hover:text-neutral-700"
          >
            <Pencil className="w-3.5 h-3.5" />
          </button>
          <button
            type="button"
            aria-label={`${key} 改成不做这道工序`}
            data-testid={`matrix-applicable-${key}`}
            title={`${cell.position}不做「${cell.operation}」—— 点一下改成不做`}
            onClick={onToggleApplicable}
            className="rounded px-1 text-neutral-400 hover:bg-neutral-100 hover:text-neutral-700"
          >
            ⇄
          </button>
        </span>
      )}
      {editing && reasons.length > 0 && (
        <ul className="mt-1 space-y-0.5 text-xs text-red-600" data-testid={`matrix-price-reasons-${key}`}>
          {reasons.map((r, i) => (
            <li key={i}>{r}</li>
          ))}
        </ul>
      )}
      {/* 编辑态下仍把「未定价 ≠ 0 元」写在旁边：清空输入框 = 改回未定价（不是 0 元） */}
      {editing && (
        <span className="mt-1 block text-[11px] text-neutral-400">
          {hasPrice ? '清空 = 改回未定价（≠ 0 元）' : '填 0 表示真 0 元；清空 = 未定价'}
        </span>
      )}
    </td>
  )
}

/**
 * 抽屉里的一行 = 该逻辑工序落到工人端的一道**变体工序**（按 `variant_operation_id` 去重）。
 * 元数据**逐字取自**矩阵行的 6 个新键（契约 #4587 ①）—— 前端**不推导**、不补默认值。
 */
interface VariantView {
  id: string
  name: string | null
  group: string | null
  unit: string | null
  scope: ProductionScope
  is_must_finish: boolean
  /** 该变体覆盖的部位（去重，矩阵列序） */
  positions: string[]
  /** 工序库里的 provenance；查不到 ⇒ `null` ⇒ **不渲染徽标**（静默 = 未知） */
  source: ProductionSource | null
}

export default function ProcessConfigPage() {
  // ── 只读面 ──
  const [catalog, setCatalog] = useState<OperationsCatalog | null>(null)
  const [catalogError, setCatalogError] = useState('')
  const [routings, setRoutings] = useState<RoutingsResponse | null>(null)
  const [templates, setTemplates] = useState<ProductionSeedTemplate[]>([])
  const [matrix, setMatrix] = useState<OperationPosition[]>([])
  const [matrixError, setMatrixError] = useState('')
  const [rules, setRules] = useState<RouteRule[]>([])
  const [rulesError, setRulesError] = useState('')
  const [loading, setLoading] = useState(true)
  /** 三个 tab：`operations` 工艺项 / `routes` 工艺路线 / `calc` 算料配置。默认落在「工艺项」—— 依赖顺序上它在前。 */
  const [tab, setTab] = useState<'operations' | 'routes' | 'calc'>('operations')
  /** 「添加工序」选择器（路线 tab 内）—— 工序库在另一个 tab，编辑器必须自带入口 */
  const [picked, setPicked] = useState('')
  const [error, setError] = useState('')
  /** 工序名搜索（**一个控件管整个「工艺项」tab**：这一屏唯一的表按行过滤） */
  const [search, setSearch] = useState('')

  // ── 矩阵格写面（issue #4588；契约 #4587 ②）──
  /** 正在编辑的格（键 = `工序-部位`）；`null` = 没有格在编辑态 */
  const [cellEditing, setCellEditing] = useState<string | null>(null)
  const [cellDraft, setCellDraft] = useState('')
  const [cellBusy, setCellBusy] = useState(false)
  /** 保存被拒的**逐条**理由（按格就地展示，不吞成一句「保存失败」） */
  const [cellReasons, setCellReasons] = useState<{ key: string; items: string[] } | null>(null)

  // ── 「管理▸」抽屉（变体维护面：分组 / 单位 / 作用域 / 必完 / 停用 / 删除）──
  const [manageOp, setManageOp] = useState<string | null>(null)
  const [editingVariantId, setEditingVariantId] = useState<string | null>(null)
  const [variantDraft, setVariantDraft] = useState({ group_name: '', unit: '' })
  const [variantBusy, setVariantBusy] = useState(false)
  /** 删除工序的二次确认目标（`null` = 没有行在确认态） */
  const [confirmDeleteOpId, setConfirmDeleteOpId] = useState<string | null>(null)
  const [variantReasons, setVariantReasons] = useState<{ id: string; items: string[] } | null>(null)

  // ── 条件工序规则删除（issue #4588；契约 #4587 ④）──
  const [confirmDeleteRuleId, setConfirmDeleteRuleId] = useState<number | null>(null)
  const [ruleDeleteReasons, setRuleDeleteReasons] = useState<{ id: number; items: string[] } | null>(null)
  const [ruleBusy, setRuleBusy] = useState(false)

  // ── 特殊选项对客单价行内编辑（元/套；issue #4567）──
  /** 正在编辑的行 id（null = 没有行在编辑态） */
  const [editingRulePriceId, setEditingRulePriceId] = useState<string | number | null>(null)
  const [rulePriceDraft, setRulePriceDraft] = useState('')
  /** 保存被拒的**逐条**理由（就地展示，不吞成一句「保存失败」） */
  const [rulePriceReasons, setRulePriceReasons] = useState<string[]>([])
  const [rulePriceBusy, setRulePriceBusy] = useState(false)

  // ── 主线编辑 ──
  const [editing, setEditing] = useState<Routing | null>(null)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [draft, setDraft] = useState<string[]>([])
  const [saving, setSaving] = useState(false)
  const [reasons, setReasons] = useState<string[]>([])
  /** 本地即时错误（如空主线），与后端理由同区展示，形态一致 */
  const [localReason, setLocalReason] = useState('')

  // ── 路线管理面（改名 / 删除 / 设为默认）──
  const [renameTarget, setRenameTarget] = useState<Routing | null>(null)
  const [renameDraft, setRenameDraft] = useState('')
  const [confirmAction, setConfirmAction] = useState<{ kind: 'delete' | 'default'; routing: Routing } | null>(null)
  /** 管理面被拒的逐条理由（就地展示，不吞成一句「操作失败」） */
  const [opReasons, setOpReasons] = useState<string[]>([])

  // ── 算料配置（tab「算料配置」，issue #4528 = 包 E）──
  /** 读面响应（含 `source`：`default` = 系统默认值 / `stored` = 已保存的商家配置） */
  const [calcConfig, setCalcConfig] = useState<CraftCalcConfigResponse | null>(null)
  /** 表单草稿（切 tab 不丢：state 挂在本组件上） */
  const [calcDraft, setCalcDraft] = useState<CraftCalcConfig | null>(null)
  const [calcError, setCalcError] = useState('')
  /** 保存被拒的逐条理由（**不吞**成一句「保存失败」—— 后端一次列出每一处不合法） */
  const [calcReasons, setCalcReasons] = useState<string[]>([])
  const [calcBusy, setCalcBusy] = useState(false)

  // ── 弹窗 ──
  const [newRouteOpen, setNewRouteOpen] = useState(false)
  /**
   * 新建路线：默认**基线三部位**全适用（收窄适用范围就取消勾选；至少留一个）。
   * ⚠️ 默认**不含** `布料`（与后端 `DEFAULT_POSITIONS` 同口径）：路线命中是
   * `(is_default DESC, id)` **首个命中**，而新路线的 id 是 UUID（恒小于种子 `rt-v79-01`）
   * ⇒ 勾上 `布料` 会**顶掉**种子自带的 `布料工序路线`，让布料单走窗帘主线（其工序对布料
   * `applicable=false` ⇒ 被适用性矩阵滤空 = 零/少工序加工单）。`布料` 因此是**按需勾选**的第 4 项。
   */
  const [newRoute, setNewRoute] = useState<{ name: string; positions: string[] }>({
    name: '',
    positions: POSITION_DOMAIN,
  })
  const [newOpOpen, setNewOpOpen] = useState(false)
  const [newOp, setNewOp] = useState({ name: '', group_name: '', unit: '', unit_price: '' })
  /**
   * 「新增」对话框里**工序**那一支的「适用部位」（issue #4614，形态裁定 A）。
   *
   * 默认 = **基线三部位**（与「新建路线」的适用帘种默认一致）；勾选项 = {@link positionOptions}
   * （矩阵带出的部位 ∪ 基线，**不写死第二份**）。一个都不勾 ⇒ 本地预检拦下（不发请求）——
   * 因为「没勾部位」= 建出来在「工艺项」表里看不到它、也没法定价（原病原地复发）。
   */
  const [newOpPositions, setNewOpPositions] = useState<string[]>(POSITION_DOMAIN)
  /** 新增**工序**的**就地**理由（本地预检；照 {@link newOptionReasons} 那套形态逐条展示） */
  const [newOpReasons, setNewOpReasons] = useState<string[]>([])
  // ── 存量孤儿接入（issue #4614 范围补口）──
  const [orphanOpen, setOrphanOpen] = useState(false)
  /** 每道孤儿工序勾的**适用部位**（初值 = 基线三部位，与新增工序同一份值域口径） */
  const [orphanPicks, setOrphanPicks] = useState<Record<string, string[]>>({})
  const [orphanReasons, setOrphanReasons] = useState<string[]>([])
  const [orphanBusy, setOrphanBusy] = useState(false)
  /**
   * 「新增」对话框的**类型二选一**（issue #4570，用户裁定：「只要能新增工序项就行了，并可以设置为
   * 特殊选项或者工序，也支持设置单价」）。默认 `operation`（工序 —— 既有链路逐字不变）。
   */
  const [newKind, setNewKind] = useState<'operation' | 'option'>('operation')
  /** 特殊选项草稿（`trigger_value` = 选项名；`customer_unit_price` = **对客**元/套） */
  const [newOption, setNewOption] = useState({
    trigger_value: '',
    customer_unit_price: '',
    operation: '',
    after_operation: '',
    priority: '',
  })
  /** 新增特殊选项的**就地**理由（本地预检 ∪ 后端 `error.details[].message` 逐条） */
  const [newOptionReasons, setNewOptionReasons] = useState<string[]>([])
  const [confirmTemplate, setConfirmTemplate] = useState<ProductionSeedTemplate | null>(null)
  const [applying, setApplying] = useState('')
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    // 五条只读端点互不依赖：任一条失败不得把整页吞掉（页面不白屏，失败处给可读提示）
    const [routingsRes, catalogRes, templateRes, matrixRes, rulesRes] = await Promise.allSettled([
      productionApi.getRoutings(),
      productionApi.getOperationsCatalog(),
      productionApi.getSeedTemplates(),
      productionApi.getOperationPositions(),
      productionApi.getRouteRules(),
    ])
    if (routingsRes.status === 'fulfilled') {
      setRoutings(routingsRes.value.data?.data ?? null)
    } else {
      setRoutings(null)
      setError('工艺路线加载失败，请稍后重试')
    }
    if (catalogRes.status === 'fulfilled') {
      setCatalog(catalogRes.value.data?.data ?? null)
      setCatalogError('')
    } else {
      setCatalog(null)
      setCatalogError('工序库加载失败，请稍后重试')
    }
    setTemplates(templateRes.status === 'fulfilled' ? templateRes.value.data?.data ?? [] : [])
    if (matrixRes.status === 'fulfilled') {
      setMatrix(matrixRes.value.data?.data ?? [])
      setMatrixError('')
    } else {
      setMatrix([])
      setMatrixError('部位价目加载失败，请稍后重试')
    }
    if (rulesRes.status === 'fulfilled') {
      setRules(rulesRes.value.data?.data ?? [])
      setRulesError('')
    } else {
      setRules([])
      setRulesError('条件工序规则加载失败，请稍后重试')
    }
    setLoading(false)
  }, [])

  useEffect(() => {
    load()
  }, [load])

  // ────────────────────────── 算料配置（tab「算料配置」，issue #4528） ──────────────────────────

  /**
   * 读本租户生效的算料配置。
   *
   * 页面**不持有任何默认值**：本租户没配置行时后端回的是**算料引擎默认值**
   * （`source='default'`）⇒ 直接渲染它（在 TS 侧抄一份默认值 = 第二份会漂的默认值）。
   */
  const loadCalcConfig = useCallback(async () => {
    try {
      const res = await productionApi.getCraftCalcConfig()
      const data = res.data?.data ?? null
      setCalcConfig(data)
      setCalcDraft(data?.config ?? null)
      setCalcError('')
    } catch (e) {
      setCalcConfig(null)
      setCalcDraft(null)
      setCalcError('算料配置加载失败，请稍后重试')
      if (!isErrorToastShown(e)) toast.error('算料配置加载失败')
    }
  }, [])

  // 懒加载：切到本 tab 才发请求（其余 tab 的加载面不受影响）
  useEffect(() => {
    if (tab === 'calc' && calcConfig === null && calcError === '') void loadCalcConfig()
  }, [tab, calcConfig, calcError, loadCalcConfig])

  /**
   * 保存（`PUT` = **全量替换**）。
   *
   * 失败 ⇒ **逐条**展示后端理由 + **不**改本地草稿（更不静默写回默认值 —— 静默 = 商家以为改了、
   * 系统按默认算 ⇒ 算错钱且无人知道）。
   */
  async function saveCalcConfig() {
    if (!calcDraft) return
    setCalcBusy(true)
    setCalcReasons([])
    try {
      const res = await productionApi.updateCraftCalcConfig(calcDraft)
      const data = res.data?.data ?? null
      setCalcConfig(data)
      setCalcDraft(data?.config ?? calcDraft)
      toast.success('算料配置已保存，之后的算料按当前配置计算')
    } catch (e) {
      setCalcReasons(craftCalcConfigGuardReasons(e))
      if (!isErrorToastShown(e)) toast.error('算料配置保存失败')
    } finally {
      setCalcBusy(false)
    }
  }

  /** 草稿里某个数值键的当前值（渲染用；不在这里补默认值） */
  const calcNumber = (key: CalcScalarKey): string => {
    const v = calcDraft?.[key]
    return v === undefined || v === null ? '' : String(v)
  }

  const setCalcNumber = (key: CalcScalarKey, raw: string) => {
    setCalcDraft((d) => (d ? { ...d, [key]: raw === '' ? Number.NaN : Number(raw) } : d))
  }

  const libraryOps = useMemo(() => (catalog?.groups ?? []).flatMap((g) => g.operations), [catalog])
  const libraryByName = useMemo(() => {
    const m = new Map<string, CatalogOperation>()
    libraryOps.forEach((op) => m.set(op.name, op))
    return m
  }, [libraryOps])
  /**
   * 工序库按 **id** 索引 —— 抽屉里某道变体的 provenance（`source`）只能这样查：
   * 变体名（`精裁-布`）与逻辑名（`精裁`）不是同一把尺，按名字查会查空或查错。
   * 查不到 ⇒ `source = null` ⇒ **不渲染徽标**（静默 = 未知，不得冒充已知）。
   */
  const libraryById = useMemo(() => {
    const m = new Map<string, CatalogOperation>()
    libraryOps.forEach((op) => m.set(String(op.id), op))
    return m
  }, [libraryOps])
  /** 部位价目表里出现过的逻辑工序名（主线可能用它书写 ⇒ 判「工序是否存在」必须并上这一侧） */
  const matrixOps = useMemo(() => new Set(matrix.map((c) => c.operation)), [matrix])
  const knownOps = useMemo(
    () => new Set<string>([...libraryByName.keys(), ...matrixOps]),
    [libraryByName, matrixOps],
  )

  /**
   * **孤儿工序**（issue #4614 范围补口）：工序库里有、但**没有任何矩阵格指向它**。
   *
   * <p>用户实测原话：「我现在在**工艺项**中看不到 测试22，但是在**路线编辑的下拉列表**能看到，是 bug」
   * —— 两边口径不一致（「工艺项」按矩阵渲染、「路线编辑」下拉按工序库渲染）。#4609 把下拉也改成读矩阵后
   * 孤儿**两边都看不到**（彻底不可达）⇒ 必须给存量孤儿一条**接入路径**。</p>
   *
   * <p>判据用 **`variant_operation_id`**（读面按后端的 `variantNameOf` 反查出来的「该格落地变体」）
   * 而**不是**名字 —— 变体名（`精裁-布`）与逻辑名（`精裁`）不是同一把尺，前端也没有归一表
   * （归一只在后端一份，见 `normalizeOperationName`）。</p>
   */
  const orphanOps = useMemo(() => {
    const referenced = new Set(
      matrix
        .map((c) => c.variant_operation_id)
        .filter((v): v is string => v != null)
        .map(String),
    )
    return libraryOps.filter((op) => !referenced.has(String(op.id)))
  }, [matrix, libraryOps])

  const q = search.trim().toLowerCase()

  // ────────────────────────── 工艺项：一屏一张表（issue #4588） ──────────────────────────

  /** 列 = 闭词表里**数据里真有**的部位 + 未知部位（追加在后；不丢数据） */
  const positionColumns = useMemo(() => {
    const present = new Set(matrix.map((c) => c.position))
    return [
      ...POSITION_DOMAIN.filter((p) => present.has(p)),
      ...[...present].filter((p) => !POSITION_DOMAIN.includes(p)),
    ]
  }, [matrix])

  /**
   * 「新建路线」的**部位勾选项** = {@link positionColumns}（与部位价目矩阵**同源**）
   * ⇒ `布料` 等新增部位**自动**可选（issue #4556：原来这里直接用 `POSITION_DOMAIN`，于是
   * 矩阵读面看得见 `布料`、写面却建不出它）；矩阵读面失败时退回基线三部位（**不是**空列表 ——
   * 否则读面一挂就连路线都建不出来）。
   */
  const positionOptions = useMemo(
    () => (positionColumns.length > 0 ? positionColumns : POSITION_DOMAIN),
    [positionColumns],
  )

  /**
   * **跨形态勾选**（issue #4556 产品裁定 (a)；后端机制跟单 #4563）：既勾了基线帘种部位、
   * 又勾了基线**之外**的部位（如 `布料`）。命中 ⇒ 就地提示。
   *
   * 为什么必须提示（读码实测的机制链）：路线命中是 `(is_default DESC, id ASC)` **首个命中**，
   * 而新路线的 id 是 UUID（十六进制字符恒小于种子 `rt-v79-01`）⇒ 这条跨形态路线会**顶掉**
   * 系统自带的布料专用路线 ⇒ 布料单改走窗帘主线，而窗帘各道工序对布料 `applicable=FALSE`
   * ⇒ 被适用性矩阵滤掉 ⇒ **丢工序**（V79 只留 `配料`/`打包` 对布料适用）。
   *
   * 判据**不写死 `布料`**：以 `POSITION_DOMAIN`（基线帘种）为参照 ⇒ 将来新增第 5 个部位自动落入本提示。
   */
  const mixedFormPick = useMemo(() => {
    const curtain = newRoute.positions.filter((p) => POSITION_DOMAIN.includes(p))
    const others = newRoute.positions.filter((p) => !POSITION_DOMAIN.includes(p))
    if (curtain.length === 0 || others.length === 0) return null
    return { curtainText: curtain.join(' / '), othersText: others.join(' / ') }
  }, [newRoute.positions])

  /**
   * 行 = 逻辑工序（**保持服务端顺序**：`Map` 的插入顺序即首次出现顺序）。
   * ⚠️ **不过滤** `applicable=false` 的格 —— 「明确不做」与「没定价」必须在界面上可区分。
   */
  const matrixRows = useMemo(() => {
    const byOp = new Map<string, Map<string, OperationPosition>>()
    matrix.forEach((cell) => {
      if (!byOp.has(cell.operation)) byOp.set(cell.operation, new Map())
      byOp.get(cell.operation)!.set(cell.position, cell)
    })
    return [...byOp.entries()].map(([operation, cells]) => ({ operation, cells }))
  }, [matrix])

  /**
   * 「目标工序 / 插入锚点」下拉的取值域 = **逻辑工序名**（issue #4570）。
   *
   * ⚠️ 口径：`production_route_rules.operation` / `after_operation` 存的是**逻辑工序名**
   * （`精裁` / `三边`），而 `production_operations.name` 是**库口径**（带部位后缀 `精裁-布`）
   * —— 两者不是同一把尺（本页 `stepView` 的 `resolved` 判据早已按此区分）。
   * ⇒ 本页唯一**已有**的逻辑名来源就是部位价目矩阵的行键（`GET /operation-positions`，
   * 服务端顺序）⇒ 直接复用它，**不新造第二份工序名清单**、不重排、不拼写。
   */
  const logicalOps = useMemo(() => matrixRows.map((r) => r.operation), [matrixRows])

  const visibleMatrixRows = useMemo(
    () => matrixRows.filter((r) => !q || r.operation.toLowerCase().includes(q)),
    [matrixRows, q],
  )

  /** 一格三态：明确不做（applicable=false）/ 没定价 / 有价 —— 三态**不同形** */
  const cellState = (cell?: OperationPosition): 'na' | 'unpriced' | 'priced' => {
    if (!cell) return 'unpriced'
    if (cell.applicable === false) return 'na'
    return cell.unit_price == null ? 'unpriced' : 'priced'
  }

  /** 未定价格数（**待办计数**：做但还没定价；「不做」不算、真 0 元不算） */
  const unpricedCount = useMemo(
    () => matrix.filter((c) => cellState(c) === 'unpriced').length,
    [matrix],
  )

  /** 一行里出现过的元数据值（去重、保序、剔除空值）—— 「不许静默取第一个」的公共值口径 */
  const distinctMeta = (
    row: { cells: Map<string, OperationPosition> },
    pick: (c: OperationPosition) => string | null | undefined,
  ) => {
    const out: string[] = []
    row.cells.forEach((c) => {
      const v = pick(c)
      if (v && !out.includes(v)) out.push(v)
    })
    return out
  }

  /**
   * 行尾元数据 = 该行各格变体元数据的**公共值**；各格不一致时**逐个列出**（用 ` / ` 分隔）——
   * **不许静默取第一个**（取第一个会让「这道工序在两个分组里」这种事静默消失）。
   * 6 键全 `null`（查不到变体）⇒ 空数组 ⇒ 渲染 `—`（不发明元数据）。
   */
  const metaText = (values: string[]) => (values.length > 0 ? values.join(' / ') : '—')

  const metaInconsistent = (values: string[]) => values.length > 1

  /**
   * 行尾「必完」标记的三态（issue #4610，用户裁定「**必完标记还是得在这里展示**」——
   * 它是完工门槛，要一眼看得见）。
   *
   * 数据来源 = 矩阵读面每行**已有**的 `is_must_finish`（契约 #4587 ① 的 6 键之一），
   * **不新造字段、不另拉接口**；口径沿用该格的「各格不一致时逐个列出、**不静默取第一个**」纪律：
   * ① 有变体元数据的格**全部**必完 ⇒ `必完`；
   * ② **只有部分部位**必完 ⇒ `必完（部分部位）`，`title` 列出**具体哪些部位**；
   * ③ 一道都没有（或读面没给该键）⇒ `null` ⇒ **不显示**（不得发明「非必完」这类新词）。
   */
  const mustFinishOf = (row: { cells: Map<string, OperationPosition> }) => {
    const yes: string[] = []
    const no: string[] = []
    row.cells.forEach((cell, position) => {
      if (cell.is_must_finish == null) return
      if (cell.is_must_finish) yes.push(position)
      else no.push(position)
    })
    return yes.length === 0 ? null : { partial: no.length > 0, positions: yes }
  }

  /**
   * 「从工序库选择要添加的工序…」的取值域 = **逻辑工序名**（issue #4609）。
   *
   * ⚠️ 为什么不能再用 `catalog.groups[].operations`（{@link libraryOps}）：那是**库口径**，35 行里
   * 同一道逻辑工序按部位**重复出现**（`精裁-布` / `精裁-纱`），且 `value` 是变体名 ⇒
   * 加入主线的就是变体名（`精裁-布`），而实例化 `buildRoute` 的适用性矩阵按**逻辑名**建键
   * ⇒ `get("精裁-布")` = null ⇒ **该道工序被静默丢掉**（商家加了工序，加工单里没有）。
   * 取值域改由**矩阵读面的行键**给出（与 {@link logicalOps} 同源：天然是逻辑名、天然去重）；
   * 分组取该行各格的**公共值**（各格不一致时逐个列出 —— 同 {@link metaText} 口径，不静默取第一个）。
   *
   * ⚠️ `libraryByName`（主线 chips 解析**变体**元数据）仍按变体名索引，**不要**一起改。
   */
  const paletteOps = useMemo(
    () => matrixRows.map((row) => ({ name: row.operation, groups: distinctMeta(row, (c) => c.group) })),
    [matrixRows],
  )

  /** 该逻辑工序的变体（按 `variant_operation_id` 去重；矩阵列序 = 部位顺序） */
  const variantsOf = useCallback(
    (row: { cells: Map<string, OperationPosition> }): VariantView[] => {
      const byId = new Map<string, VariantView>()
      row.cells.forEach((c) => {
        const id = c.variant_operation_id
        if (!id) return
        const existing = byId.get(id)
        if (existing) {
          if (!existing.positions.includes(c.position)) existing.positions.push(c.position)
          return
        }
        byId.set(id, {
          id,
          name: c.variant_name ?? null,
          group: c.group ?? null,
          unit: c.unit ?? null,
          scope: c.scope === 'set' ? 'set' : 'position',
          is_must_finish: !!c.is_must_finish,
          positions: [c.position],
          source: libraryById.get(id)?.source ?? null,
        })
      })
      return [...byId.values()]
    },
    [libraryById],
  )

  /** 抽屉当前展示的变体（按 `manageOp` 找到那一行） */
  const manageRow = useMemo(
    () => matrixRows.find((r) => r.operation === manageOp) ?? null,
    [matrixRows, manageOp],
  )
  const manageVariants = useMemo(() => (manageRow ? variantsOf(manageRow) : []), [manageRow, variantsOf])

  // ────────────────────────── 就绪度（先后依赖显性化） ──────────────────────────

  const operationsReady = (catalog?.total ?? 0) > 0
  const routeList = useMemo(() => routings?.routings ?? [], [routings])
  const emptyShells = useMemo(
    () => routeList.filter((r) => (r.mainline ?? []).length === 0),
    [routeList],
  )
  const routingsReady = routeList.length > 0 && emptyShells.length === 0
  const defaults = useMemo(() => routeList.filter((r) => r.is_default), [routeList])

  const routingsHint =
    routeList.length === 0
      ? '下一步：点右上「新建路线」建一条（一条路线 = 一条有序主线 + 适用帘种）。'
      : emptyShells.length > 0
        ? `有 ${emptyShells.length} 条「空壳」路线（主线为空）：该路线命中后一道工序都没有，请点「编辑主线」把工序排进去。`
        : ''
  const defaultRouteHint =
    defaults.length === 0
      ? '没有默认路线：匹配不到专属路线的订单，一张加工单也生成不了。请在下方路线列表点「设为默认」选一条。'
      : ''

  // ────────────────────────── 主线编辑 ──────────────────────────

  /** 主线一步的展示口径（只读与草稿共用 —— 见 {@link StepView}） */
  const stepView = useCallback(
    (name: string, i: number): StepView => {
      const lib = libraryByName.get(name)
      return {
        seq: i + 1,
        operation: name,
        group: lib?.group ?? null,
        unit: lib?.unit ?? null,
        is_must_finish: lib?.is_must_finish,
        resolved: !!lib,
        missing: !knownOps.has(name),
      }
    },
    [libraryByName, knownOps],
  )

  const openEditor = (routing: Routing) => {
    setEditing(routing)
    setEditingId(routing.id)
    setDraft(routing.mainline ?? [])
    setReasons([])
    setLocalReason('')
  }

  const closeEditor = () => {
    setEditing(null)
    setEditingId(null)
    setDraft([])
    setReasons([])
    setLocalReason('')
  }

  const draftSteps: StepView[] = useMemo(() => draft.map(stepView), [draft, stepView])

  const missingSteps = draftSteps.filter((s) => s.missing)
  /**
   * 就地预检：一道必完工序都没有 ⇒ 这张单**永远完不了工**。
   * ⚠️ 只在**每一步都能在工序库里查到**时判 —— 逻辑工序名（`精裁`）拿不到 `is_must_finish`
   * ⇒ 判不了就不判（**静默 = 未知**，不得当成违规，同 route_source 纪律）。
   */
  const lacksMustFinish =
    draftSteps.length > 0 &&
    draftSteps.every((s) => s.resolved) &&
    !draftSteps.some((s) => s.is_must_finish)

  const addFromPalette = (name: string) => {
    if (!editingId) return
    setDraft((d) => (d.includes(name) ? d : [...d, name]))
    setLocalReason('')
  }

  const move = (index: number, delta: -1 | 1) => {
    setDraft((d) => {
      const next = [...d]
      const target = index + delta
      if (target < 0 || target >= next.length) return d
      ;[next[index], next[target]] = [next[target], next[index]]
      return next
    })
  }

  const removeAt = (index: number) => setDraft((d) => d.filter((_, i) => i !== index))

  /** 保存主线：空主线本地拦（不发无效请求）；其余护栏理由由后端逐条返回 */
  const saveSequence = async () => {
    if (!editing) return
    if (draft.length === 0) {
      setLocalReason('主线不能为空：一条路线至少要有 1 道工序')
      setReasons([])
      return
    }
    setSaving(true)
    setReasons([])
    setLocalReason('')
    try {
      await productionApi.updateRouting(editing.id, { mainline: draft })
      toast.success('路线主线已保存')
      closeEditor()
      await load()
    } catch (e) {
      console.error(e)
      setReasons(routingGuardReasons(e))
      if (!isErrorToastShown(e)) toast.error('路线主线保存失败')
    } finally {
      setSaving(false)
    }
  }

  /** 新建路线：名字 + 适用帘种 → 建壳后**立刻进入主线编辑**（消灭「建壳了但没排」的静默态） */
  const createRoute = async () => {
    const name = newRoute.name.trim()
    if (!name) {
      toast.error('请填写路线名称')
      return
    }
    if (newRoute.positions.length === 0) {
      toast.error('请至少勾选一个适用帘种')
      return
    }
    setBusy(true)
    try {
      const res = await productionApi.createRouting({ name, positions: newRoute.positions })
      const created = res.data?.data as Routing | undefined
      toast.success(`已新建路线「${name}」，请把工序排进主线`)
      setNewRouteOpen(false)
      setNewRoute({ name: '', positions: POSITION_DOMAIN })
      await load()
      if (created?.id) {
        openEditor({ ...created, mainline: created.mainline ?? [] })
      }
    } catch (e) {
      console.error(e)
      toastRequestError(e, '新建路线失败')
    } finally {
      setBusy(false)
    }
  }

  // ────────────────────────── 路线管理面（改名 / 删除 / 设为默认） ──────────────────────────

  const openRename = (routing: Routing) => {
    setRenameTarget(routing)
    setRenameDraft(routing.name)
    setOpReasons([])
  }

  /** 改名：**只提交 `name`**（不给 mainline ⇒ 服务端不动序列） */
  const submitRename = async () => {
    const target = renameTarget
    if (!target) return
    const name = renameDraft.trim()
    if (!name) {
      setOpReasons(['路线名称不能为空'])
      return
    }
    setBusy(true)
    setOpReasons([])
    try {
      await productionApi.updateRouting(target.id, { name })
      toast.success('路线名称已更新')
      setRenameTarget(null)
      await load()
    } catch (e) {
      console.error(e)
      setOpReasons(routingAdminGuardReasons(e))
      if (!isErrorToastShown(e)) toast.error('改名失败')
    } finally {
      setBusy(false)
    }
  }

  /**
   * 删除 / 设为默认（二次确认后执行）。
   * ⚠️ `is_default` **只发 true** —— 发 false 会让该租户零默认（后端 422）。
   */
  const runConfirm = async () => {
    const action = confirmAction
    if (!action) return
    setBusy(true)
    setOpReasons([])
    try {
      if (action.kind === 'delete') {
        await productionApi.deleteRouting(action.routing.id)
        toast.success(`已删除路线「${action.routing.name}」`)
      } else {
        await productionApi.updateRouting(action.routing.id, { is_default: true })
        toast.success(`已把「${action.routing.name}」设为默认路线`)
      }
      setConfirmAction(null)
      await load()
    } catch (e) {
      console.error(e)
      setOpReasons(routingAdminGuardReasons(e))
      if (!isErrorToastShown(e)) toast.error(action.kind === 'delete' ? '删除失败' : '设为默认失败')
    } finally {
      setBusy(false)
    }
  }

  /** 删除护栏（**就地**给理由，不等后端 422）；两条同时成立时两条都给（后端也一次报全） */
  const deleteBlockReasons = (routing: Routing): string[] => {
    const out: string[] = []
    if (routeList.length <= 1) {
      out.push('这是最后一条工艺路线：删了就一条都不剩，任何订单都生成不了加工单。请先新建一条路线，再删这条。')
    }
    if (routing.is_default) {
      out.push(
        '默认路线是路线兜底的终点：删了之后匹配不到专属路线的订单，一张加工单也生成不了。请先把另一条设为默认，再删这条。',
      )
    }
    return out
  }

  // ────────────────────────── 工序库写面 ──────────────────────────

  /** 打开「新增」对话框：每次都回到默认类型「工序」+ 默认适用部位（基线三部位），并清掉上一次的失败理由 */
  const openCreateOperation = () => {
    setNewKind('operation')
    setNewOptionReasons([])
    setNewOpReasons([])
    setNewOpPositions(POSITION_DOMAIN)
    setNewOpOpen(true)
  }

  /**
   * 新增**工序**（issue #4614：**同时**为勾选的每个部位建一行矩阵行）。
   *
   * <p>为什么要带 `positions`：不带的话后端只写工序库，「工艺项」表（只按 `GET /operation-positions`
   * 渲染）里**看不到它** —— 用户实测原话「这个新增按钮，无法新增工序」。</p>
   *
   * <p>本地预检只拦「拦得住就不打扰后端」的那几条（名称/单价/部位），**语义护栏一律以后端为准**
   * （前端不发明第二份口径）⇒ 失败理由**就地**逐条展示，**不刷新、不改页面数据**。</p>
   *
   * <p>结果 toast 必须报**服务端返回的真实数字**（新建/跳过）—— 缺结果体时显式报错，
   * 不假装成功（照 {@link applyTemplate} 既有纪律）。</p>
   */
  const createOperation = async () => {
    const name = newOp.name.trim()
    const price = Number(newOp.unit_price)
    const reasons: string[] = []
    if (!name) reasons.push('请填写工序名称')
    if (newOp.unit_price.trim() === '' || Number.isNaN(price)) {
      reasons.push('请输入有效单价（元/件·米·折）')
    }
    if (newOpPositions.length === 0) {
      reasons.push(
        '请至少勾选一个适用部位：工序只在勾选的部位上出现 —— 一个都不勾，建出来在「工艺项」表里看不到它，也没法定价',
      )
    }
    if (reasons.length > 0) {
      setNewOpReasons(reasons)
      return
    }
    setNewOpReasons([])
    setBusy(true)
    try {
      const res = await productionApi.createOperation({
        name,
        group_name: newOp.group_name.trim() || undefined,
        unit: newOp.unit.trim() || undefined,
        unit_price: price,
        positions: newOpPositions,
      })
      const result = res.data?.data
      if (!result || result.created_positions === undefined || result.skipped_positions === undefined) {
        toast.error('新增结果缺失（服务端未返回部位写入数），请刷新页面核对「工艺项」表')
      } else {
        toast.success(
          `已新增工序「${name}」：新建 ${result.created_positions} 个部位的价目格、` +
            `跳过 ${result.skipped_positions} 个（已存在的部位保留原价）`,
        )
      }
      setNewOpOpen(false)
      setNewOp({ name: '', group_name: '', unit: '', unit_price: '' })
      setNewOpPositions(POSITION_DOMAIN)
      await load()
    } catch (e) {
      console.error(e)
      if (!isErrorToastShown(e)) toast.error('新增工序失败')
    } finally {
      setBusy(false)
    }
  }

  /**
   * 打开**存量孤儿接入**弹窗（issue #4614 范围补口）：每道孤儿默认勾**基线三部位**
   * （与新增工序的默认一致；不想接的那道把部位全取消勾即可）。
   */
  const openOrphanAttach = () => {
    const next: Record<string, string[]> = {}
    orphanOps.forEach((op) => {
      next[String(op.id)] = POSITION_DOMAIN
    })
    setOrphanPicks(next)
    setOrphanReasons([])
    setOrphanOpen(true)
  }

  /**
   * 把勾了部位的孤儿工序**接进**矩阵（`PUT /operations/{id}` 带 `positions`）。
   *
   * <p>后端**只补缺失行**：已存在的活跃行跳过（不覆盖已定价的格）、不删任何已有行；
   * 响应如实报数 ⇒ toast 报**服务端真实数字**（缺结果体时显式报错，不假装成功）。</p>
   *
   * <p>值域校验与新增路径**同一份**（后端一处实现）—— 前端不发明第二份口径，
   * 失败理由照 `routingAdminGuardReasons` **逐条**就地展示。</p>
   */
  const attachOrphans = async () => {
    const picks = orphanOps
      .map((op) => ({ op, positions: orphanPicks[String(op.id)] ?? [] }))
      .filter((x) => x.positions.length > 0)
    if (picks.length === 0) {
      setOrphanReasons([
        '请至少给一道工序勾一个适用部位：一个部位都不勾的工序接不进来（在「工艺项」表里看不到它，也没法定价）',
      ])
      return
    }
    setOrphanReasons([])
    setOrphanBusy(true)
    let created = 0
    let skipped = 0
    let done = 0
    try {
      for (const { op, positions } of picks) {
        const res = await productionApi.updateOperation(op.id, { positions })
        const result = res.data?.data
        if (!result || result.created_positions === undefined || result.skipped_positions === undefined) {
          toast.error(`「${op.name}」的接入结果缺失（服务端未返回部位写入数），请刷新页面核对「工艺项」表`)
          await load()
          return
        }
        created += result.created_positions
        skipped += result.skipped_positions
        done++
      }
      toast.success(
        `已接入 ${done} 道工序：新建 ${created} 个部位价目格、跳过 ${skipped} 个（已存在的格保留原价）`,
      )
      setOrphanOpen(false)
      await load()
    } catch (e) {
      console.error(e)
      setOrphanReasons(routingAdminGuardReasons(e))
      // 不假装成功：如实报出已经接进去几道（失败前完成的那些**已经落库**了）
      if (!isErrorToastShown(e)) toast.error(`接入失败（已接入 ${done} 道）`)
      await load()
    } finally {
      setOrphanBusy(false)
    }
  }

  /**
   * 新增**特殊选项**（对客按套计价，issue #4570）。
   *
   * 两本账**互不换算**：这里写 `production_route_rules`（**元/套**，对顾客），
   * 而 `createOperation` 写 `production_operations.unit_price`（**计件**，给工人）。
   *
   * 本地只做「拦得住就不打扰后端」的最小预检（照 `RulePriceCell` 行内编辑同口径）；
   * **语义护栏**一律以后端为准（前端**不发明**第二份口径）⇒ 失败时逐条理由**就地**展示，
   * **不刷新、不改页面数据**（静默写回 = 商家以为建好了、取价侧其实没建）。
   */
  const createOptionRule = async () => {
    const reasons: string[] = []
    const trigger = newOption.trigger_value.trim()
    if (!trigger) reasons.push('请填写选项名称')
    if (!newOption.operation) reasons.push('请选择目标工序：这条选项要在哪道工序上生效')
    const rawPrice = newOption.customer_unit_price.trim()
    if (rawPrice === '') {
      reasons.push('请填写单价（元/套）：对客按套计价，空着等于没有报价')
    } else if (!/^\d+(\.\d{1,2})?$/.test(rawPrice)) {
      reasons.push('单价必须是 ≥ 0 且最多两位小数的数字（元/套）')
    }
    const rawPriority = newOption.priority.trim()
    if (rawPriority !== '' && !/^\d+$/.test(rawPriority)) {
      reasons.push('优先级必须是不小于 0 的整数（留空 = 按后端默认顺序）')
    }
    if (reasons.length > 0) {
      setNewOptionReasons(reasons)
      return
    }
    // 可选键**留空就不发**（`after_operation?` / `priority?`）—— 不拿 `null` 冒充「没填」
    const payload: RouteRuleCreateParams = {
      trigger_value: trigger,
      operation: newOption.operation,
      customer_unit_price: Number(rawPrice),
    }
    if (newOption.after_operation) payload.after_operation = newOption.after_operation
    if (rawPriority !== '') payload.priority = Number(rawPriority)
    setBusy(true)
    setNewOptionReasons([])
    try {
      await productionApi.createOptionRule(payload)
      toast.success('特殊选项已新增')
      setNewOpOpen(false)
      setNewOption({ trigger_value: '', customer_unit_price: '', operation: '', after_operation: '', priority: '' })
      await load()
    } catch (e) {
      console.error(e)
      setNewOptionReasons(optionPriceGuardReasons(e))
      if (!isErrorToastShown(e)) toast.error('新增特殊选项失败')
    } finally {
      setBusy(false)
    }
  }

  // ────────────────────────── 矩阵格写面（issue #4588；契约 #4587 ②） ──────────────────────────

  const cellKeyOf = (operation: string, position: string) => `${operation}-${position}`

  /**
   * 矩阵格写面统一出口（契约 #4587 ② 是**部分更新** ⇒ body 只带变了的那个键）。
   * 失败 ⇒ 理由**逐条**就地展示在该格，且**不**收摊、**不**刷新
   * （静默写回 = 商家以为改了、取价侧其实没改）。
   */
  const submitCell = async (
    key: string,
    id: string | null | undefined,
    payload: OperationPositionUpdateParams,
  ) => {
    if (!id) {
      // 契约保证每行都有 `id`；真缺了就说清楚，不静默失败
      setCellReasons({ key, items: ['这一格缺少行标识，无法保存 —— 请点右上「刷新」重试'] })
      return
    }
    setCellBusy(true)
    setCellReasons(null)
    try {
      await productionApi.updateOperationPosition(id, payload)
      toast.success(
        payload.applicable === undefined ? '计件单价已更新' : payload.applicable ? '已设为做这道工序' : '已设为不做',
      )
      setCellEditing(null)
      await load()
    } catch (e) {
      setCellReasons({ key, items: routingAdminGuardReasons(e) })
      if (!isErrorToastShown(e)) toast.error('保存失败')
    } finally {
      setCellBusy(false)
    }
  }

  /**
   * 保存格内**计件单价（给工人）**。空输入 = **改回未定价**（发 `null`，≠ 0 元）。
   * 本地只拦「送出去也必被拒」的形态（非数值 / 负数 / 三位小数）—— 语义护栏以后端为准
   * （后端一次报全 `error.details`，前端不发明第二份口径）。
   */
  const saveCellPrice = (cell: OperationPosition) => {
    const key = cellKeyOf(cell.operation, cell.position)
    const raw = cellDraft.trim()
    if (raw !== '' && !/^\d+(\.\d{1,2})?$/.test(raw)) {
      setCellReasons({ key, items: ['计件单价必须是 ≥ 0 且最多两位小数的数字（要表示「还没定价」请清空）'] })
      return
    }
    void submitCell(key, cell.id, { unit_price: raw === '' ? null : Number(raw) })
  }

  /** 「不做 ⇄」：同一端点，body **只带** `applicable`（切回做 ⇒ `true`） */
  const toggleCellApplicable = (cell: OperationPosition) => {
    void submitCell(cellKeyOf(cell.operation, cell.position), cell.id, { applicable: cell.applicable === false })
  }

  const cancelCellEdit = () => {
    setCellEditing(null)
    setCellDraft('')
    setCellReasons(null)
  }

  // ────────────────────────── 「管理▸」抽屉：变体维护面（issue #4588） ──────────────────────────

  /** 变体写面统一出口（既有 `PUT /operations/{id}`；部分更新 ⇒ 只带变了的字段） */
  const submitVariant = async (id: string, payload: ProductionOperationUpdateParams) => {
    setVariantBusy(true)
    setVariantReasons(null)
    try {
      await productionApi.updateOperation(id, payload)
      toast.success('工序已更新')
      setEditingVariantId(null)
      await load()
    } catch (e) {
      setVariantReasons({ id, items: routingAdminGuardReasons(e) })
      if (!isErrorToastShown(e)) toast.error('工序更新失败')
    } finally {
      setVariantBusy(false)
    }
  }

  /**
   * 删除工序（**软删**，契约 #4587 ③）：二次确认后发 `DELETE /operations/{id}`。
   * 三条护栏（被活跃主线 / 活跃规则 / 矩阵格引用）由后端**一次报全** ⇒ 逐条就地展示。
   */
  const removeVariant = async (variant: VariantView) => {
    setVariantBusy(true)
    setVariantReasons(null)
    try {
      await productionApi.deleteOperation(variant.id)
      toast.success(`已删除工序「${variant.name ?? variant.id}」`)
      setConfirmDeleteOpId(null)
      await load()
    } catch (e) {
      setVariantReasons({ id: variant.id, items: routingAdminGuardReasons(e) })
      if (!isErrorToastShown(e)) toast.error('删除失败')
    } finally {
      setVariantBusy(false)
    }
  }

  // ────────────────────────── 条件工序规则删除（issue #4588；契约 #4587 ④） ──────────────────────────

  const removeRule = async (rule: RouteRule) => {
    setRuleBusy(true)
    setRuleDeleteReasons(null)
    try {
      await productionApi.deleteRouteRule(rule.id)
      toast.success('规则已删除')
      setConfirmDeleteRuleId(null)
      await load()
    } catch (e) {
      setRuleDeleteReasons({ id: rule.id, items: routingAdminGuardReasons(e) })
      if (!isErrorToastShown(e)) toast.error('删除失败')
    } finally {
      setRuleBusy(false)
    }
  }

  /**
   * 保存特殊选项的**对客单价**（元/套，issue #4567）。
   *
   * 本地只做「能拦住就没必要打扰后端」的最小预检（空/非数值/负数/三位小数）；
   * **语义护栏**（非 option 行等）一律以后端为准 —— 前端**不发明**第二份口径。
   * 失败 ⇒ 逐条理由**就地**展示（`rulePriceReasons`），且**不**改本地 `rules`
   * （静默写回会让商家以为改了、取价侧其实没改）。
   */
  const saveRulePrice = async (rule: RouteRule) => {
    const raw = rulePriceDraft.trim()
    const value = raw === '' ? null : Number(raw)
    if (value !== null && (Number.isNaN(value) || value < 0 || !/^\d+(\.\d{1,2})?$/.test(raw))) {
      setRulePriceReasons(['单价必须是 ≥ 0 且最多两位小数的数字（要表示「还没定价」请清空）'])
      return
    }
    setRulePriceBusy(true)
    setRulePriceReasons([])
    try {
      await productionApi.updateRuleCustomerUnitPrice(rule.id, { customer_unit_price: value })
      toast.success(value === null ? '已改回未定价' : '单价已更新')
      setEditingRulePriceId(null)
      await load()
    } catch (e) {
      const reasons = optionPriceGuardReasons(e)
      setRulePriceReasons(reasons)
      if (!isErrorToastShown(e)) toast.error('单价保存失败')
    } finally {
      setRulePriceBusy(false)
    }
  }

  /** 放弃编辑：清掉输入与**该次**失败理由（不把上一次的报错留给下一行） */
  const cancelRulePrice = () => {
    setEditingRulePriceId(null)
    setRulePriceDraft('')
    setRulePriceReasons([])
  }

  /**
   * 一键补套行业模板（**空态补救**，不是主路径）。
   * 结果 toast 必须报**服务端返回的真实数字**（新增/跳过）—— 缺结果体时显式报错，不假装成功。
   */
  const applyTemplate = async () => {
    const template = confirmTemplate
    if (!template) return
    setApplying(template.templateId)
    try {
      const res = await productionApi.applySeedTemplate(template.templateId)
      const result = res.data?.data
      if (!result) {
        toast.error('套用结果缺失，请刷新页面核对工序库')
      } else {
        toast.success(
          `已套用「${template.name}」：新增 ${result.created_operations} 道工序、` +
            `${result.created_routings} 条工艺路线、跳过 ${result.skipped} 条（初始价请在列表中确认后修改）`,
        )
      }
      setConfirmTemplate(null)
      await load()
    } catch (e) {
      toastRequestError(e, '套用行业模板失败')
    } finally {
      setApplying('')
    }
  }

  const total = catalog?.total ?? 0

  return (
    <div className="p-6 space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-neutral-900">工艺配置</h1>
          <p className="mt-0.5 text-sm text-neutral-500">
            工序（在哪些部位做、各自多少钱）→ 工艺路线（订单按哪条主线走）。路线是计件工资与完工判定的唯一输入
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="secondary" size="sm" onClick={load} disabled={loading}>
            <RefreshCw className={cn('w-4 h-4 mr-1.5', loading && 'animate-spin')} />
            刷新
          </Button>
          <Button
            variant="secondary"
            size="sm"
            data-testid="routings-new-operation"
            onClick={openCreateOperation}
          >
            <Plus className="w-4 h-4 mr-1.5" />
            新增工序
          </Button>
          <Button size="sm" data-testid="routings-new-route" onClick={() => setNewRouteOpen(true)}>
            <Plus className="w-4 h-4 mr-1.5" />
            新建路线
          </Button>
        </div>
      </div>

      {loading && (
        <div className="flex items-center gap-2 text-sm text-neutral-500" data-testid="routings-loading">
          <RefreshCw className="w-4 h-4 animate-spin" />
          加载中…
        </div>
      )}

      {!loading && error && (
        <div
          className="flex flex-col items-center gap-3 rounded-lg border border-neutral-200 bg-white py-10"
          data-testid="routings-error"
        >
          <AlertCircle className="w-6 h-6 text-red-500" />
          <p className="text-sm text-neutral-600">{error}</p>
          <Button size="sm" data-testid="routings-retry" onClick={load}>
            重试
          </Button>
        </div>
      )}

      {!loading && !error && (
        <>
          {/* ── 就绪度（四步）：① 工序库 → ② 工艺路线 → ③ 默认路线 → ④ 算料配置 ── */}
          <div className="rounded-lg border border-neutral-200 bg-white p-5" data-testid="process-readiness">
            <div className="mb-3 flex flex-wrap items-baseline gap-2">
              <h2 className="text-base font-medium text-neutral-900">配置就绪度</h2>
              <span className="text-sm text-neutral-500">
                按顺序配：先有工序，才能排路线；路线里要有一条默认的兜底；最后按你家口径核一遍算料
              </span>
            </div>
            <div className="grid gap-3 sm:grid-cols-2 md:grid-cols-4">
              <ReadinessStep
                testId="readiness-step-operations"
                index={1}
                label={catalogError ? '工序库 读取失败' : `工序库 ${total} 道`}
                state={operationsReady ? 'done' : 'todo'}
                hint={
                  catalogError
                    ? '工序库没读出来（≠ 没配）：点右上「刷新」重试。'
                    : '下一步：用下方「行业模板」补套，或点右上「新增」逐道建（工序 / 特殊选项）。'
                }
              />
              <ReadinessStep
                testId="readiness-step-routings"
                index={2}
                label={`工艺路线 ${routeList.length} 条`}
                state={routingsReady ? 'done' : 'todo'}
                hint={routingsHint}
              />
              <ReadinessStep
                testId="readiness-step-default-route"
                index={3}
                label={`默认路线 ${defaults.length} 条`}
                state={defaults.length === 1 ? 'done' : 'todo'}
                hint={defaultRouteHint}
              />
              {/* 第 4 步（issue #4567 用户走查③）：算料配置 —— `calcConfig` 是**懒加载**（切到
                  「算料配置」tab 才发请求，见 `loadCalcConfig` 的 useEffect）⇒ 本页首屏它通常还是
                  `null`，此时判 `unknown`（**中性**「读取中」），**不得**显示成 `todo`
                  （把「没加载」误报成「没配」）；加载失败同样不谎报 done。 */}
              <ReadinessStep
                testId="readiness-step-calc-config"
                index={4}
                label={calcConfig?.source === 'stored' ? '算料配置 已保存' : '算料配置 系统默认'}
                state={
                  calcConfig?.source === 'stored' ? 'done' : calcError !== '' || calcConfig === null ? 'unknown' : 'todo'
                }
                hint={calcConfig?.source === 'stored' ? '' : '下一步：切到「算料配置」tab 按你家口径改每折吃布 / 余量 / 档位倍数。'}
              />
            </div>
          </div>

          {/* ── 行业模板：**仅工序库为空时**出现（开租已自动套用；这里只是补套路径） ── */}
          {!operationsReady && (
            <div className="rounded-lg border border-amber-200 bg-amber-50/60 p-5" data-testid="seed-templates">
              <div className="mb-3 flex flex-wrap items-baseline gap-2">
                <h2 className="text-base font-medium text-neutral-900">工序库为空 · 补套行业模板</h2>
                <span className="text-sm text-neutral-600">
                  开租时系统会按行业自动套用；这里是套用失败或老租户的补救入口（已存在的条目自动跳过）
                </span>
              </div>
              {templates.length === 0 ? (
                <p className="py-4 text-sm text-neutral-500" data-testid="seed-templates-empty">
                  暂无可用模板
                </p>
              ) : (
                <div className="divide-y divide-amber-200">
                  {templates.map((t) => (
                    <div
                      key={t.templateId}
                      className="flex items-start justify-between gap-3 py-3"
                      data-testid={`seed-template-${t.templateId}`}
                    >
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="font-medium text-neutral-900">{t.name}</span>
                          <span className="rounded bg-white px-1.5 py-0.5 text-[11px] text-neutral-500">
                            v{t.version}
                          </span>
                        </div>
                        {t.description && <p className="mt-1 text-sm text-neutral-600">{t.description}</p>}
                      </div>
                      <Button
                        size="sm"
                        data-testid={`seed-template-apply-${t.templateId}`}
                        disabled={applying === t.templateId}
                        onClick={() => setConfirmTemplate(t)}
                        title="把该行业的预置工序与工艺路线复制到您的工序库（已存在条目自动跳过）"
                      >
                        {applying === t.templateId ? '套用中…' : '一键套用'}
                      </Button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* ── 两个 tab：工艺项 / 工艺路线 ──
              合并仍是**一个菜单入口、一个页面**；tab 切换**不丢状态**（编辑中的 draft 保留在 state 里）。 */}
          <div className="flex items-center gap-1 border-b border-neutral-200" role="tablist" data-testid="process-config-tabs">
            {([
              { key: 'operations', label: '工艺项' },
              { key: 'routes', label: '工艺路线' },
              { key: 'calc', label: '算料配置' },
            ] as const).map((t) => (
              <button
                key={t.key}
                type="button"
                role="tab"
                aria-selected={tab === t.key}
                data-testid={`process-config-tab-${t.key}`}
                data-state={tab === t.key ? 'active' : 'inactive'}
                onClick={() => setTab(t.key)}
                className={cn(
                  '-mb-px border-b-2 px-4 py-2 text-sm transition-colors',
                  tab === t.key
                    ? 'border-primary-600 font-medium text-primary-700'
                    : 'border-transparent text-neutral-500 hover:text-neutral-800',
                )}
              >
                {t.label}
              </button>
            ))}
          </div>

          <div>
            {/* ══════════ tab「工艺项」：**一屏一张表**（行 = 逻辑工序 / 列 = 部位 / 格可就地改） ══════════
                issue #4588 = 母单 #4586 包 B（契约 #4587）。原「主区只读矩阵 + 折叠次区工序库明细」两张
                平铺表已合并成这一张：明细面（分组 / 单位 / 作用域 / 必完 / 停用 / 删除）收进行尾
                「管理▸」抽屉 —— 同一个概念**只有一个载体**，改价只有一个入口（矩阵格）。
                例外（用户改判）：**必完** 是完工门槛，除抽屉里的维护面外，行尾还要有**只读标记**
                （issue #4610）；**作用域**仍只在抽屉里。 */}
            {tab === 'operations' && (
              <div className="space-y-4" data-testid="craft-operations-panel">
                <section className="rounded-lg border border-neutral-200 bg-white p-5" data-testid="operation-price-matrix">
                  <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                    <div className="flex flex-wrap items-baseline gap-2">
                      <h2 className="text-base font-medium text-neutral-900">工艺项 · 计件单价（给工人）</h2>
                      <span className="text-sm text-neutral-500">
                        <span data-testid="operation-price-matrix-total">{matrixRows.length}</span> 道工序 ×{' '}
                        {positionColumns.length} 个部位 ={' '}
                        <span data-testid="operation-price-matrix-cells">
                          {matrixRows.length * positionColumns.length}
                        </span>{' '}
                        格
                      </span>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <span
                        className={cn(
                          'rounded px-2 py-0.5 text-xs',
                          unpricedCount > 0 ? 'bg-amber-50 text-amber-700' : 'bg-neutral-100 text-neutral-500',
                        )}
                        data-testid="matrix-unpriced-count"
                        title="这些格「做这道工序但还没定价」—— 报工按未定价处理，请补价"
                      >
                        未定价 {unpricedCount} 项
                      </span>
                      {/* 孤儿提示（issue #4614 范围补口）：工序库里有、但没有任何部位价目行 ⇒
                          「工艺项」表里看不到它、也没法定价（存量工序没有接入路径 = 不可达）。 */}
                      {orphanOps.length > 0 && (
                        <button
                          type="button"
                          data-testid="matrix-orphan-hint"
                          onClick={openOrphanAttach}
                          className="rounded bg-amber-50 px-2 py-0.5 text-xs text-amber-700 underline decoration-dotted hover:bg-amber-100"
                          title="这些工序在工序库里有、但没有任何部位价目行 —— 接进来才能定价"
                        >
                          有 {orphanOps.length} 道工序还没接部位 ⇒ 接进来才能定价
                        </button>
                      )}
                      <input
                        value={search}
                        onChange={(e) => setSearch(e.target.value)}
                        placeholder="搜索工序名…"
                        aria-label="搜索工序"
                        data-testid="operations-search"
                        className="h-8 w-40 rounded border border-neutral-300 bg-white px-2 text-sm focus:outline-none focus:border-primary-500"
                      />
                    </div>
                  </div>
                  <p className="mb-3 text-xs text-neutral-500">
                    这一屏的价是<strong>计件单价（给工人）</strong>：报工工资 = 数量 × 计件单价。
                    <span className="text-neutral-400">不做</span> = 该部位明确不做这道工序（不是漏配）；
                    <span className="text-amber-700">未定价</span> = 做但还没定价（≠ ¥0.00；真 0 元照显示 ¥0.00）。
                    收顾客的那笔钱不在这里 —— 基础工序在「加工项组合费用」，特殊选项在「条件工序规则」。
                  </p>

                  {matrixError ? (
                    <p
                      className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-600"
                      data-testid="operation-price-matrix-error"
                    >
                      {matrixError}
                    </p>
                  ) : visibleMatrixRows.length === 0 ? (
                    <p className="py-8 text-center text-sm text-neutral-400" data-testid="operation-price-matrix-empty">
                      {matrixRows.length === 0
                        ? '暂无部位价目数据 —— 点右上「新增工序」建一道，再回这里给各部位定价'
                        : '没有匹配的工序，换个关键词试试'}
                    </p>
                  ) : (
                    <div className="overflow-x-auto">
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="border-b border-neutral-200 text-left text-xs text-neutral-500">
                            <th className="py-2 pr-4 font-medium">工序（工人看到的）</th>
                            {positionColumns.map((p) => (
                              <th key={p} className="py-2 pr-4 font-medium">
                                {p}
                              </th>
                            ))}
                            <th className="py-2 pr-4 font-medium">元数据 / 操作</th>
                          </tr>
                        </thead>
                        <tbody>
                          {visibleMatrixRows.map((row) => {
                            const groups = distinctMeta(row, (c) => c.group)
                            const units = distinctMeta(row, (c) => c.unit)
                            const names = distinctMeta(row, (c) => c.variant_name)
                            const inconsistent = metaInconsistent(groups) || metaInconsistent(units)
                            const mustFinish = mustFinishOf(row)
                            return (
                              <tr
                                key={row.operation}
                                className="border-b border-neutral-100 last:border-0"
                                data-testid={`matrix-row-${row.operation}`}
                                data-operation={row.operation}
                              >
                                <td className="py-2.5 pr-4 align-top">
                                  <div className="text-neutral-900">{row.operation}</div>
                                  {/* 该行落到工人端的**变体名**（`variant_name` 去重）—— 查不到就不编造 */}
                                  <div
                                    className="text-xs text-neutral-400"
                                    data-testid={`matrix-variants-${row.operation}`}
                                  >
                                    {names.length > 0 ? names.join(' / ') : '—'}
                                  </div>
                                </td>
                                {positionColumns.map((p) => {
                                  const cell = row.cells.get(p)
                                  // 矩阵里没有这一格：不假装有数据（也不给「不做 / 0 元」这两个假值）
                                  if (!cell) {
                                    return (
                                      <td
                                        key={p}
                                        data-testid={`matrix-cell-${row.operation}-${p}`}
                                        data-state="unpriced"
                                        className="py-2.5 pr-4 align-top text-amber-700"
                                        title={`${p}没有这一格的配置`}
                                      >
                                        未定价
                                      </td>
                                    )
                                  }
                                  const key = cellKeyOf(row.operation, p)
                                  return (
                                    <PositionCell
                                      key={p}
                                      cell={cell}
                                      state={cellState(cell)}
                                      editing={cellEditing === key}
                                      draft={cellDraft}
                                      busy={cellBusy}
                                      reasons={cellEditing === key && cellReasons?.key === key ? cellReasons.items : []}
                                      onStartEdit={() => {
                                        setCellEditing(key)
                                        setCellDraft(cell.unit_price == null ? '' : String(cell.unit_price))
                                        setCellReasons(null)
                                      }}
                                      onDraftChange={setCellDraft}
                                      onSave={() => saveCellPrice(cell)}
                                      onCancel={cancelCellEdit}
                                      onToggleApplicable={() => toggleCellApplicable(cell)}
                                    />
                                  )
                                })}
                                {/* 行尾元数据 = `分组 · 单位`（作用域收进抽屉）+ **必完标记**（issue #4610：
                                    完工门槛要一眼看得见）+「管理▸」入口；各格不一致时逐个列出，
                                    **不静默取第一个** */}
                                <td
                                  className="py-2.5 pr-4 align-top"
                                  data-testid={`matrix-meta-${row.operation}`}
                                  data-inconsistent={inconsistent ? 'true' : undefined}
                                  title={inconsistent ? '各部位的变体元数据不一致，已逐个列出' : undefined}
                                >
                                  <div className="flex flex-wrap items-center gap-2">
                                    <span className="text-xs text-neutral-500">
                                      {groups.length === 0 && units.length === 0
                                        ? '—'
                                        : `${metaText(groups)} · ${metaText(units)}`}
                                    </span>
                                    {mustFinish && (
                                      <span
                                        className="text-xs text-amber-600"
                                        data-testid={`matrix-must-finish-${row.operation}`}
                                        title={
                                          mustFinish.partial
                                            ? `必完的部位：${mustFinish.positions.join(' / ')}（其余部位不要求必完）`
                                            : '必完：缺这道工序不能打包（部位级：每个部位都要做完）'
                                        }
                                      >
                                        必完{mustFinish.partial ? '（部分部位）' : ''}
                                      </span>
                                    )}
                                    <button
                                      type="button"
                                      data-testid={`matrix-manage-${row.operation}`}
                                      onClick={() => {
                                        setManageOp(row.operation)
                                        setEditingVariantId(null)
                                        setConfirmDeleteOpId(null)
                                        setVariantReasons(null)
                                      }}
                                      title="管理这道工序的变体：分组 / 单位 / 作用域 / 必完 / 停用 / 删除"
                                      className="rounded px-1.5 py-0.5 text-xs text-primary-700 hover:bg-neutral-100"
                                    >
                                      管理▸
                                    </button>
                                  </div>
                                </td>
                              </tr>
                            )
                          })}
                        </tbody>
                      </table>
                    </div>
                  )}
                </section>
              </div>
            )}

            {/* ══════════════ tab「工艺路线」：主区 = 具名路线，次区 = 条件工序规则 ══════════════ */}
            {tab === 'routes' && (
              <div className="space-y-4">
                {/* 主区：具名路线（name + 默认徽标 + 适用帘种 + 主线 + 改名/设默认/删除） */}
                <section className="rounded-lg border border-neutral-200 bg-white p-5" data-testid="routings-list">
                  <div className="mb-3 flex items-baseline gap-2">
                    <h2 className="text-base font-medium text-neutral-900">工艺路线</h2>
                    <span className="text-sm text-neutral-500">
                      共 <span data-testid="routings-total">{routings?.total ?? 0}</span> 条 · 每条 = 一条有序主线 +
                      适用帘种
                    </span>
                  </div>

                  {/* 管理面被拒：逐条理由就地展示（不吞成一句「操作失败」） */}
                  {opReasons.length > 0 && (
                    <div
                      className="mb-3 rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-600"
                      data-testid="routing-op-error"
                    >
                      <p className="flex items-center gap-2 font-medium">
                        <AlertCircle className="w-4 h-4" />
                        操作被拒绝，请逐条处理：
                      </p>
                      <ul className="mt-1 list-disc space-y-0.5 pl-6">
                        {opReasons.map((r, i) => (
                          <li key={i} data-testid={`routing-op-error-item-${i}`}>
                            {r}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {routeList.length === 0 ? (
                    <p className="py-8 text-center text-sm text-neutral-400" data-testid="routings-empty">
                      暂无工艺路线 —— 点右上「新建路线」建一条（一条路线 = 一条有序主线 + 适用帘种）
                    </p>
                  ) : (
                    <div className="space-y-4">
                      {routeList.map((routing) => {
                        const id = routing.id
                        const isEditing = editingId === id
                        const mainline = routing.mainline ?? []
                        const isEmptyShell = mainline.length === 0
                        const blockReasons = deleteBlockReasons(routing)
                        return (
                          <div key={id} className="rounded-lg border border-neutral-200 p-4" data-testid={`routing-${id}`}>
                            <div className="flex flex-wrap items-center justify-between gap-2">
                              <div className="flex flex-wrap items-baseline gap-2">
                                <span className="text-sm font-medium text-neutral-900" data-testid={`routing-name-${id}`}>
                                  {routing.name}
                                </span>
                                {routing.is_default && (
                                  <span
                                    data-testid={`routing-default-${id}`}
                                    title="默认路线：匹配不到专属路线的订单走它（每租户恰一条）"
                                    className="rounded bg-primary-50 px-1.5 py-0.5 text-[11px] text-primary-700"
                                  >
                                    默认
                                  </span>
                                )}
                                <span className="text-xs text-neutral-400" data-testid={`routing-positions-${id}`}>
                                  适用：{(routing.positions ?? []).join(' / ') || '—'}
                                </span>
                                <span
                                  className="text-xs text-neutral-400"
                                  data-testid={`routing-mainline-count-${id}`}
                                >
                                  主线 {mainline.length} 道
                                </span>
                                {isEmptyShell && (
                                  <span
                                    data-testid={`routing-empty-shell-${id}`}
                                    title="主线为空：这条路线被命中后一道工序都没有 —— 既不报错也不拦，该订单会静默拿到 0 道工序"
                                    className="rounded bg-red-50 px-1.5 py-0.5 text-[11px] text-red-600"
                                  >
                                    空壳 · 不可用
                                  </span>
                                )}
                              </div>
                              {isEditing ? (
                                <div className="flex items-center gap-2">
                                  <Button
                                    variant="secondary"
                                    size="sm"
                                    data-testid={`routing-cancel-${id}`}
                                    disabled={saving}
                                    onClick={closeEditor}
                                  >
                                    取消
                                  </Button>
                                  <Button size="sm" data-testid={`routing-save-${id}`} loading={saving} onClick={saveSequence}>
                                    保存
                                  </Button>
                                </div>
                              ) : (
                                <div className="flex flex-wrap items-center gap-2">
                                  <Button
                                    variant="secondary"
                                    size="sm"
                                    data-testid={`routing-edit-${id}`}
                                    onClick={() => openEditor(routing)}
                                  >
                                    <Pencil className="w-3.5 h-3.5 mr-1.5" />
                                    编辑主线
                                  </Button>
                                  <Button
                                    variant="secondary"
                                    size="sm"
                                    data-testid={`routing-rename-${id}`}
                                    onClick={() => openRename(routing)}
                                    title="只改路线总名，不动主线工序"
                                  >
                                    改名
                                  </Button>
                                  {/* 设为默认：默认行**不显示**（后端 is_default:false ⇒ 422，前端不得发 false） */}
                                  {!routing.is_default && (
                                    <Button
                                      variant="secondary"
                                      size="sm"
                                      data-testid={`routing-set-default-${id}`}
                                      onClick={() => {
                                        setOpReasons([])
                                        setConfirmAction({ kind: 'default', routing })
                                      }}
                                    >
                                      <Star className="w-3.5 h-3.5 mr-1.5" />
                                      设为默认
                                    </Button>
                                  )}
                                  <Button
                                    variant="danger"
                                    size="sm"
                                    data-testid={`routing-delete-${id}`}
                                    disabled={blockReasons.length > 0 || busy}
                                    onClick={() => {
                                      setOpReasons([])
                                      setConfirmAction({ kind: 'delete', routing })
                                    }}
                                  >
                                    <Trash2 className="w-3.5 h-3.5 mr-1.5" />
                                    删除
                                  </Button>
                                </div>
                              )}
                            </div>

                            {/* 护栏理由**就地**展示（不等后端 422 才知道为什么点不动） */}
                            {blockReasons.length > 0 && (
                              <ul
                                className="mt-2 list-disc space-y-0.5 rounded border border-amber-200 bg-amber-50 px-3 py-2 pl-7 text-xs text-amber-800"
                                data-testid={`routing-delete-blocked-${id}`}
                              >
                                {blockReasons.map((r, i) => (
                                  <li key={i}>{r}</li>
                                ))}
                              </ul>
                            )}

                            {/* 主线保存被拒：逐条展示理由（空主线 / 工序不存在 / 重复 / 缺必完工序） */}
                            {isEditing && (localReason || reasons.length > 0) && (
                              <div
                                className="mt-3 rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-600"
                                data-testid={`routing-error-${id}`}
                              >
                                <p className="flex items-center gap-2 font-medium">
                                  <AlertCircle className="w-4 h-4" />
                                  保存被拒绝，请逐条修正：
                                </p>
                                <ul className="mt-1 list-disc space-y-0.5 pl-6">
                                  {(localReason ? [localReason] : reasons).map((r, i) => (
                                    <li key={i} data-testid={`routing-error-item-${i}`}>
                                      {r}
                                    </li>
                                  ))}
                                </ul>
                              </div>
                            )}

                            {isEditing ? (
                              <div className="mt-3 space-y-3">
                                {/* 就地预检（后端仍是唯一权威，这里只把「保存失败」提前成「看得见」） */}
                                {lacksMustFinish && (
                                  <p
                                    className="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800"
                                    data-testid={`routing-precheck-${id}`}
                                  >
                                    这条路线一道「必完」工序都没有 —— 必完工序全绿是完工判定的唯一依据，
                                    缺了这张单永远完不了工。请至少把一道关键工序标为「必完」。
                                  </p>
                                )}
                                {missingSteps.length > 0 && (
                                  <p
                                    className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-600"
                                    data-testid={`routing-precheck-missing-${id}`}
                                  >
                                    有 {missingSteps.length} 道工序在工序库中不存在或已停用（
                                    {missingSteps.map((s) => s.operation).join('、')}
                                    ）—— 保存会被拒，请先到「工艺项」点「新增工序」把它建出来，
                                    或把它从主线里移除。
                                  </p>
                                )}

                                {/* 添加工序：工序库在**另一个 tab** ⇒ 编辑器自带入口 */}
                                <div className="flex flex-wrap items-center gap-2">
                                  <select
                                    aria-label="从工序库添加工序"
                                    data-testid={`routing-add-select-${id}`}
                                    value={picked}
                                    onChange={(e) => setPicked(e.target.value)}
                                    className="h-9 min-w-56 flex-1 rounded border border-neutral-300 bg-white px-3 text-sm focus:outline-none focus:border-primary-500"
                                  >
                                    <option value="">从工序库选择要添加的工序…</option>
                                    {paletteOps.map((op) => (
                                      <option key={op.name} value={op.name}>
                                        {op.name}
                                        {op.groups.length > 0 ? `（${op.groups.join(' / ')}）` : ''}
                                      </option>
                                    ))}
                                  </select>
                                  <Button
                                    variant="secondary"
                                    size="sm"
                                    data-testid={`routing-add-${id}`}
                                    disabled={!picked}
                                    onClick={() => {
                                      if (picked) addFromPalette(picked)
                                      setPicked('')
                                    }}
                                  >
                                    <Plus className="w-3.5 h-3.5 mr-1.5" />
                                    加入
                                  </Button>
                                </div>

                                {draftSteps.length === 0 ? (
                                  <p className="text-sm text-neutral-400" data-testid={`routing-draft-empty-${id}`}>
                                    主线为空：从上方「从工序库选择要添加的工序…」选一道点「加入」（必完工序是完工门槛，缺了会阻止打包）
                                  </p>
                                ) : (
                                  <ol className="space-y-1.5">
                                    {draftSteps.map((step, i) => (
                                      <li
                                        key={`${step.operation}-${i}`}
                                        className={cn(
                                          'flex flex-wrap items-center gap-2 rounded border px-2 py-1.5 text-sm',
                                          step.missing ? 'border-red-200 bg-red-50' : 'border-neutral-200 bg-neutral-50',
                                        )}
                                        data-testid={`routing-draft-step-${id}-${step.seq}`}
                                      >
                                        <span className="w-6 text-neutral-400">{step.seq}.</span>
                                        <span
                                          className="font-medium text-neutral-900"
                                          data-testid={`routing-draft-name-${id}-${step.seq}`}
                                        >
                                          {step.operation}
                                        </span>
                                        {/* 分组 · 单位 —— **不含单价**（#4583：单价归「工序项」那一屏，见 {@link StepView}） */}
                                        {step.resolved && (
                                          <span className="text-xs text-neutral-500">
                                            {step.group ?? '—'} · {step.unit ?? '—'}
                                          </span>
                                        )}
                                        {step.is_must_finish && <span className="text-xs text-amber-600">必完</span>}
                                        {step.missing && (
                                          <span
                                            className="text-xs text-red-600"
                                            data-testid={`routing-draft-missing-${id}-${step.seq}`}
                                          >
                                            工序库中不存在或已停用
                                          </span>
                                        )}
                                        <span className="ml-auto flex items-center gap-1">
                                          <button
                                            type="button"
                                            aria-label={`上移 ${step.operation}`}
                                            data-testid={`routing-draft-up-${id}-${step.seq}`}
                                            disabled={i === 0}
                                            onClick={() => move(i, -1)}
                                            className="rounded p-1 text-neutral-500 hover:bg-neutral-200 disabled:opacity-30"
                                          >
                                            <ArrowUp className="w-3.5 h-3.5" />
                                          </button>
                                          <button
                                            type="button"
                                            aria-label={`下移 ${step.operation}`}
                                            data-testid={`routing-draft-down-${id}-${step.seq}`}
                                            disabled={i === draftSteps.length - 1}
                                            onClick={() => move(i, 1)}
                                            className="rounded p-1 text-neutral-500 hover:bg-neutral-200 disabled:opacity-30"
                                          >
                                            <ArrowDown className="w-3.5 h-3.5" />
                                          </button>
                                          <button
                                            type="button"
                                            aria-label={`删除 ${step.operation}`}
                                            data-testid={`routing-draft-remove-${id}-${step.seq}`}
                                            onClick={() => removeAt(i)}
                                            className="rounded p-1 text-neutral-500 hover:bg-red-50 hover:text-red-600"
                                          >
                                            <Trash2 className="w-3.5 h-3.5" />
                                          </button>
                                        </span>
                                      </li>
                                    ))}
                                  </ol>
                                )}

                                <p className="text-xs text-neutral-500">
                                  从上方「添加工序」选择器里选（v1 不做拖拽编排，用上移/下移调顺序）。
                                </p>
                              </div>
                            ) : (
                              <ol className="mt-3 flex flex-wrap gap-1.5">
                                {mainline.map((name, i) => {
                                  const step = stepView(name, i)
                                  return (
                                    <li
                                      key={step.seq}
                                      data-testid={`routing-step-${id}-${step.seq}`}
                                      className={cn(
                                        'rounded border px-2 py-1 text-xs',
                                        step.missing
                                          ? 'border-red-200 bg-red-50 text-red-700'
                                          : 'border-neutral-200 bg-neutral-50 text-neutral-700',
                                      )}
                                    >
                                      <span className="mr-1 text-neutral-400">{step.seq}.</span>
                                      {step.operation}
                                      {/* 主线 chip 只留 序号 + 工序名 (+ 必完 / 工序库中不存在或已停用)：
                                          **不显示任何库口径元数据**（#4583）—— 否则「显示与否」取决于
                                          逻辑名与变体名是否恰好一致，9 道 chip 两套口径（用户实测的现象）。 */}
                                      {step.is_must_finish && <span className="ml-1.5 text-amber-600">必完</span>}
                                      {step.missing && <span className="ml-1.5">工序库中不存在或已停用</span>}
                                    </li>
                                  )
                                })}
                              </ol>
                            )}
                          </div>
                        )
                      })}
                    </div>
                  )}
                </section>

                {/* 次区：统一规则区 —— 工艺变体 ∪ 特殊选项（26 条）。
                    **常驻展开**（issue #4613 用户裁定：「条件工序默认不要折叠，打开，移除可折叠功能」）
                    —— 折叠曾让商家要多点一下才看得到规则，连说明也被藏起来；现无展开/收起开关。 */}
                <section className="rounded-lg border border-neutral-200 bg-white" data-testid="route-rules">
                  <div className="flex flex-wrap items-center gap-2 px-5 py-3">
                    <span className="text-sm font-medium text-neutral-900">条件工序规则</span>
                    <span className="text-xs text-neutral-400" data-testid="route-rules-total">
                      共 {rules.length} 条
                    </span>
                    <span className="ml-auto hidden text-xs text-neutral-400 sm:inline">
                      工艺 / 特殊选项触发时，往主线里插一道或删一道
                    </span>
                  </div>
                  <div className="border-t border-neutral-100 p-5 pt-4" data-testid="route-rules-body">
                  <p className="mb-3 text-xs text-neutral-500">
                    触发键<strong>逐字取自后端</strong>（与订单里的工艺 / 选项名是同一个键）：错一个字就会查不到 ⇒
                    条件工序不加、计件系数退回 1.0。规则按优先级<strong>升序</strong>生效，顺序决定工序序列。
                    特殊选项按<strong>套</strong>收费（元/套）；工艺变体不按套计价。
                  </p>
                  {rulesError ? (
                    <p
                      className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-600"
                      data-testid="route-rules-error"
                    >
                      {rulesError}
                    </p>
                  ) : rules.length === 0 ? (
                    <p className="py-6 text-center text-sm text-neutral-400" data-testid="route-rules-empty">
                      暂无条件工序规则 —— 订单的工艺与特殊选项都不需要额外增删工序
                    </p>
                  ) : (
                    <div className="overflow-x-auto">
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="border-b border-neutral-200 text-left text-xs text-neutral-500">
                            <th className="py-2 pr-4 font-medium">触发</th>
                            <th className="py-2 pr-4 font-medium">部位限定</th>
                            <th className="py-2 pr-4 font-medium">动作</th>
                            <th className="py-2 pr-4 font-medium">目标工序</th>
                            <th className="py-2 pr-4 font-medium">单价（元/套）</th>
                            <th className="py-2 pr-4 font-medium">优先级</th>
                            <th className="py-2 pr-4 font-medium">操作</th>
                          </tr>
                        </thead>
                        <tbody>
                          {rules.map((rule) => (
                            <tr
                              key={rule.id}
                              className="border-b border-neutral-100 last:border-0"
                              data-testid={`route-rule-${rule.id}`}
                            >
                              <td className="py-2.5 pr-4 text-neutral-900" data-testid={`route-rule-trigger-${rule.id}`}>
                                <span className="mr-1.5 rounded bg-neutral-100 px-1.5 py-0.5 text-[11px] text-neutral-500">
                                  {TRIGGER_KIND_LABEL[rule.trigger_kind ?? ''] ?? rule.trigger_kind ?? '—'}
                                </span>
                                {rule.trigger_value ?? '—'}
                              </td>
                              <td className="py-2.5 pr-4 text-neutral-600" data-testid={`route-rule-position-${rule.id}`}>
                                {rule.position ?? '不限'}
                              </td>
                              <td className="py-2.5 pr-4 text-neutral-700" data-testid={`route-rule-action-${rule.id}`}>
                                {ruleActionText(rule)}
                              </td>
                              <td className="py-2.5 pr-4 text-neutral-900" data-testid={`route-rule-target-${rule.id}`}>
                                {rule.operation ?? '—'}
                              </td>
                              <RulePriceCell
                                rule={rule}
                                editing={editingRulePriceId === rule.id}
                                draft={rulePriceDraft}
                                busy={rulePriceBusy}
                                reasons={editingRulePriceId === rule.id ? rulePriceReasons : []}
                                onStartEdit={() => {
                                  setEditingRulePriceId(rule.id)
                                  setRulePriceDraft(rule.customer_unit_price == null ? '' : String(rule.customer_unit_price))
                                  setRulePriceReasons([])
                                }}
                                onDraftChange={setRulePriceDraft}
                                onSave={() => void saveRulePrice(rule)}
                                onCancel={cancelRulePrice}
                              />
                              <td className="py-2.5 pr-4 text-neutral-500" data-testid={`route-rule-priority-${rule.id}`}>
                                {rule.priority ?? '—'}
                              </td>
                              {/* 删除（issue #4588；契约 #4587 ④）：二次确认 → `DELETE /route-rules/{id}`；
                                  失败理由**逐条**就地展示（不吞成一句「删除失败」）。 */}
                              <td className="py-2.5 pr-4">
                                {confirmDeleteRuleId === rule.id ? (
                                  <span className="flex items-center gap-1.5">
                                    <Button
                                      size="sm"
                                      variant="danger"
                                      data-testid={`route-rule-delete-confirm-${rule.id}`}
                                      disabled={ruleBusy}
                                      onClick={() => void removeRule(rule)}
                                    >
                                      确认删除
                                    </Button>
                                    <Button
                                      size="sm"
                                      variant="secondary"
                                      data-testid={`route-rule-delete-cancel-${rule.id}`}
                                      onClick={() => setConfirmDeleteRuleId(null)}
                                    >
                                      取消
                                    </Button>
                                  </span>
                                ) : (
                                  <button
                                    type="button"
                                    data-testid={`route-rule-delete-${rule.id}`}
                                    onClick={() => {
                                      setConfirmDeleteRuleId(rule.id)
                                      setRuleDeleteReasons(null)
                                    }}
                                    className="rounded px-1.5 py-1 text-xs text-neutral-500 hover:bg-neutral-100 hover:text-red-600"
                                  >
                                    删除
                                  </button>
                                )}
                                {ruleDeleteReasons?.id === rule.id && (
                                  <ul className="mt-1 space-y-0.5 text-xs text-red-600" data-testid="route-rule-delete-reasons">
                                    {ruleDeleteReasons.items.map((r, i) => (
                                      <li key={i}>{r}</li>
                                    ))}
                                  </ul>
                                )}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                  </div>
                </section>
              </div>
            )}

            {/* ══════════════ tab「算料配置」：用料公式参数（issue #4528 = 包 E） ══════════════
                本 tab 只回答一个问题：「算料的公式参数，我这家的口径是多少？」
                ⚠️ 页面**不持有任何默认值**：本租户没配置行时，后端回的就是算料引擎默认值
                （`source='default'`）⇒ 直接渲染 + 明确标注「当前使用系统默认值」
                （把默认值伪装成商家配置 = 让商家以为改过、其实没改）。 */}
            {tab === 'calc' && (
              <div className="space-y-4" data-testid="craft-calc-config-panel">
                <section className="rounded-lg border border-neutral-200 bg-white p-5">
                  <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
                    <h2 className="text-base font-medium text-neutral-900">算料公式参数</h2>
                    <span
                      className={cn(
                        'rounded px-2 py-0.5 text-xs',
                        calcConfig?.source === 'stored'
                          ? 'bg-primary-50 text-primary-700'
                          : 'bg-neutral-100 text-neutral-600',
                      )}
                      data-testid="craft-calc-config-source"
                    >
                      {calcConfig?.source === 'stored' ? '已保存为您的配置' : '当前使用系统默认值'}
                    </span>
                  </div>
                  <p className="text-sm text-neutral-500">
                    这些参数决定用料米数（折数法：每折吃布 × 折数 + 余量）。保存后**新**的算料按当前配置计算，
                    已生成的单据不受影响。
                  </p>

                  {calcError !== '' && (
                    <div className="mt-3 flex items-center gap-3 text-sm text-danger-600" data-testid="craft-calc-config-error">
                      <AlertCircle className="h-4 w-4" />
                      <span>{calcError}</span>
                      <Button size="sm" variant="secondary" data-testid="craft-calc-config-retry" onClick={() => void loadCalcConfig()}>
                        重试
                      </Button>
                    </div>
                  )}

                  {calcError === '' && !calcDraft && (
                    <p className="mt-3 text-sm text-neutral-400" data-testid="craft-calc-config-loading">
                      正在读取算料配置…
                    </p>
                  )}

                  {calcDraft && (
                    <div className="mt-4 space-y-5 text-sm">
                      {/* 主区：六个标量参数 */}
                      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
                        {CALC_SCALAR_FIELDS.map((f) => (
                          <label key={f.key} className="block">
                            <span className="mb-1 block text-neutral-600">{f.label}</span>
                            <input
                              type="number"
                              step="0.01"
                              className={inputCls}
                              data-testid={`craft-calc-config-scalar-${f.key}`}
                              value={calcNumber(f.key)}
                              onChange={(e) => setCalcNumber(f.key, e.target.value)}
                            />
                            <span className="mt-1 block text-xs text-neutral-400">{f.hint}</span>
                          </label>
                        ))}
                      </div>

                      {/* 兜底公式（工艺能推导时以工艺为准，这里只是推导表缺失时的兜底） */}
                      <div>
                        <label className="mb-1 block text-neutral-600" htmlFor="craft-calc-config-formula">
                          兜底用料公式
                        </label>
                        <select
                          id="craft-calc-config-formula"
                          className={inputCls}
                          data-testid="craft-calc-config-default_formula"
                          value={calcDraft.default_formula}
                          onChange={(e) => setCalcDraft((d) => (d ? { ...d, default_formula: e.target.value } : d))}
                        >
                          {Object.keys(CALC_FORMULA_LABEL).map((k) => (
                            <option key={k} value={k}>
                              {CALC_FORMULA_LABEL[k]}
                            </option>
                          ))}
                        </select>
                        <span className="mt-1 block text-xs text-neutral-400">
                          韩褶 / 打孔按工艺自动推导公式，这里只在该推导不适用时兜底。
                        </span>
                      </div>

                      {/* 次区：档位与拼色系数（表格，逐行可改） */}
                      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                        <div>
                          <h3 className="mb-2 text-neutral-700">工艺档位</h3>
                          <table className="w-full text-sm">
                            <tbody>
                              {Object.entries(calcDraft.tiers ?? {}).map(([name, tier]) => (
                                <tr key={name} className="border-b border-neutral-100">
                                  <td className="py-1.5 pr-3 text-neutral-600" title={name}>
                                    {TIER_DISPLAY_LABEL[name] ?? name}
                                  </td>
                                  <td className="py-1.5 pr-3">
                                    <input
                                      className={inputCls}
                                      data-testid={`craft-calc-config-tier-${name}-label`}
                                      value={tier.label ?? ''}
                                      onChange={(e) =>
                                        setCalcDraft((d) =>
                                          d
                                            ? { ...d, tiers: { ...d.tiers, [name]: { ...d.tiers[name], label: e.target.value } } }
                                            : d,
                                        )
                                      }
                                    />
                                  </td>
                                  <td className="py-1.5">
                                    <input
                                      type="number"
                                      step="0.1"
                                      className={inputCls}
                                      data-testid={`craft-calc-config-tier-${name}-fullness`}
                                      value={String(tier.fullness ?? '')}
                                      onChange={(e) =>
                                        setCalcDraft((d) =>
                                          d
                                            ? {
                                                ...d,
                                                tiers: {
                                                  ...d.tiers,
                                                  [name]: {
                                                    ...d.tiers[name],
                                                    fullness: e.target.value === '' ? Number.NaN : Number(e.target.value),
                                                  },
                                                },
                                              }
                                            : d,
                                        )
                                      }
                                    />
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                        <div>
                          <h3 className="mb-2 text-neutral-700">拼色每折吃布（米）</h3>
                          <table className="w-full text-sm">
                            <tbody>
                              {Object.entries(calcDraft.per_fold_mixed_times ?? {}).map(([times, perFold]) => (
                                <tr key={times} className="border-b border-neutral-100">
                                  <td className="py-1.5 pr-3 text-neutral-600">拼{times}次</td>
                                  <td className="py-1.5">
                                    <input
                                      type="number"
                                      step="0.05"
                                      className={inputCls}
                                      data-testid={`craft-calc-config-mixed-${times}`}
                                      value={String(perFold ?? '')}
                                      onChange={(e) =>
                                        setCalcDraft((d) =>
                                          d
                                            ? {
                                                ...d,
                                                per_fold_mixed_times: {
                                                  ...d.per_fold_mixed_times,
                                                  [times]: e.target.value === '' ? Number.NaN : Number(e.target.value),
                                                },
                                              }
                                            : d,
                                        )
                                      }
                                    />
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </div>

                      <div className="flex items-center gap-3">
                        <Button loading={calcBusy} data-testid="craft-calc-config-save" onClick={saveCalcConfig}>
                          保存配置
                        </Button>
                        <span className="text-xs text-neutral-400">保存后按当前配置计算；非法值会被整份拒绝并逐条说明理由。</span>
                      </div>

                      {/* 护栏理由**逐条**展示（后端一次列出每一处不合法）—— 不吞成一句「保存失败」 */}
                      {calcReasons.length > 0 && (
                        <ul className="space-y-1 text-danger-600" data-testid="craft-calc-config-reasons">
                          {calcReasons.map((r) => (
                            <li key={r}>{r}</li>
                          ))}
                        </ul>
                      )}
                    </div>
                  )}
                </section>
              </div>
            )}
          </div>
        </>
      )}

      {/* 新建路线：名字 + 适用帘种（勾选项 = 部位价目矩阵里真有的部位，含第 4 个部位 `布料`；
          默认只勾**基线三部位** —— 见 `newRoute` 初值的理由） */}
      <Modal
        open={newRouteOpen}
        onClose={() => !busy && setNewRouteOpen(false)}
        title="新建路线"
        footer={
          <div className="flex justify-end gap-2">
            <Button variant="secondary" disabled={busy} onClick={() => setNewRouteOpen(false)}>
              取消
            </Button>
            <Button loading={busy} data-testid="routings-create-route-submit" onClick={createRoute}>
              创建
            </Button>
          </div>
        }
      >
        <div className="space-y-3 text-sm">
          <p className="text-neutral-600">
            创建后直接进入主线编辑，请把工序排进去 —— 主线为空的路线被命中后一道工序都没有。
          </p>
          <div>
            <label className="mb-1 block text-neutral-600" htmlFor="new-route-name">
              路线名称（如 窗帘工序路线 / 纱帘专线）
            </label>
            <input
              id="new-route-name"
              data-testid="routings-create-name"
              className={inputCls}
              value={newRoute.name}
              onChange={(e) => setNewRoute({ ...newRoute, name: e.target.value })}
            />
          </div>
          <div>
            <span className="mb-1 block text-neutral-600">适用帘种（至少勾一个）</span>
            <div className="flex flex-wrap gap-3">
              {positionOptions.map((p) => (
                <label key={p} className="flex items-center gap-1.5 text-neutral-700">
                  <input
                    type="checkbox"
                    data-testid={`routings-create-position-${p}`}
                    checked={newRoute.positions.includes(p)}
                    onChange={(e) =>
                      setNewRoute((prev) => ({
                        ...prev,
                        positions: e.target.checked
                          ? positionOptions.filter((x) => x === p || prev.positions.includes(x))
                          : prev.positions.filter((x) => x !== p),
                      }))
                    }
                    className="h-4 w-4 accent-primary-600"
                  />
                  {p}
                </label>
              ))}
            </div>
            {/* 跨形态就地提示（#4556 裁定 (a)）：只提示、**不拦** —— 互斥/优先级是后端语义，跟单 #4563 */}
            {mixedFormPick && (
              <p
                data-testid="routings-create-position-mixed-hint"
                className="mt-2 rounded border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-relaxed text-amber-800"
              >
                ⚠️ 同时勾了帘种部位（{mixedFormPick.curtainText}）与「{mixedFormPick.othersText}」：
                这条新路线会<strong>顶掉</strong>系统自带的「{mixedFormPick.othersText}」专用路线，
                「{mixedFormPick.othersText}」单将按这条路线的工序出单 ⇒ 可能<strong>丢工序</strong>。
                建议把「{mixedFormPick.othersText}」<strong>单独建一条路线</strong>（只勾它）。
              </p>
            )}
          </div>
        </div>
      </Modal>

      {/* 改名：**只改路线总名**（不给 mainline ⇒ 服务端不动序列） */}
      <Modal
        open={!!renameTarget}
        onClose={() => !busy && setRenameTarget(null)}
        title="更改路线名称"
        footer={null}
      >
        <div data-testid="routing-rename-modal" className="space-y-3 text-sm">
          <p className="text-neutral-600">
            只改这条路线的<strong>总名</strong>，主线工序与单价都不动（主线是计件工资与完工判定的输入）。
          </p>
          <input
            aria-label="路线名称"
            data-testid="routing-rename-input"
            className={inputCls}
            value={renameDraft}
            onChange={(e) => setRenameDraft(e.target.value)}
          />
          <div className="flex justify-end gap-2">
            <Button
              variant="secondary"
              disabled={busy}
              data-testid="routing-rename-cancel"
              onClick={() => setRenameTarget(null)}
            >
              取消
            </Button>
            <Button loading={busy} data-testid="routing-rename-submit" onClick={submitRename}>
              保存
            </Button>
          </div>
        </div>
      </Modal>

      {/* 危险操作二次确认（删除 / 设为默认） */}
      <Modal
        open={!!confirmAction}
        onClose={() => !busy && setConfirmAction(null)}
        title={confirmAction?.kind === 'delete' ? '删除工艺路线' : '设为默认路线'}
        footer={null}
      >
        {confirmAction && (
          <div
            data-testid="routing-confirm-modal"
            data-kind={confirmAction.kind}
            data-routing={confirmAction.routing.id}
            className="space-y-3 text-sm"
          >
            {confirmAction.kind === 'delete' ? (
              <p className="text-neutral-600">
                将删除路线「{confirmAction.routing.name}」。删除后它立刻不再参与选路，
                匹配不到专属路线的订单会回落到默认路线。
              </p>
            ) : (
              <p className="text-neutral-600">
                将把「{confirmAction.routing.name}」设为默认路线（每租户恰一条，原默认路线会自动降级）。
                匹配不到专属路线的订单都会走它。
              </p>
            )}
            <div className="flex justify-end gap-2">
              <Button variant="secondary" disabled={busy} data-testid="routing-confirm-cancel" onClick={() => setConfirmAction(null)}>
                取消
              </Button>
              <Button
                variant={confirmAction.kind === 'delete' ? 'danger' : 'primary'}
                loading={busy}
                data-testid={`routing-confirm-${confirmAction.kind}-${confirmAction.routing.id}`}
                onClick={runConfirm}
              >
                {confirmAction.kind === 'delete' ? '确认删除' : '设为默认'}
              </Button>
            </div>
          </div>
        )}
      </Modal>

      {/* 「管理▸」抽屉（issue #4588）：该逻辑工序的**变体**维护面。
          ⚠️ 作用域 / 必完的**维护面**在这里（用户 2026-09-19 追加裁定：「作用域 · 必完 完全不知道干嘛的，
          也可以移除」⇒ 从主表移除的是**显示**，不是语义）；**必完**的只读标记按用户 2026-09-19 改判
          回到主表行尾（issue #4610：它是完工门槛，要一眼看得见），作用域仍只在抽屉里。
          两处各配一句商家看得懂的解释（口径一致，含「部位级要每个部位都做完」那一层）。 */}
      <Modal
        open={manageOp !== null}
        onClose={() => !variantBusy && setManageOp(null)}
        title={manageOp ? `管理「${manageOp}」的工序变体` : ''}
        width={760}
        footer={
          <Button variant="secondary" data-testid="operations-manage-close" onClick={() => setManageOp(null)}>
            关闭
          </Button>
        }
      >
        <div className="space-y-3 text-sm" data-testid="operations-manage-drawer">
          <p className="text-neutral-600">
            这些是<strong>工人扫码时看到的工序</strong>（同一道逻辑工序在不同部位会落成不同变体）。
            分组与单位决定报工口径；<strong>作用域</strong>：套级 = 每樘窗只做一次；
            <strong>必完</strong>：缺这道工序不能打包；<strong>部位级工序要每个部位都做完</strong>才算完
            （套级每樘窗一次）。
          </p>
          {manageVariants.length === 0 ? (
            <p className="py-6 text-center text-sm text-neutral-400" data-testid="operations-manage-empty">
              这道工序还没有落到工人端的工序（矩阵里查不到它的变体）—— 请核对各部位的适用性配置。
            </p>
          ) : (
            <div className="divide-y divide-neutral-100">
              {manageVariants.map((v) => (
                <div key={v.id} className="py-3" data-testid={`variant-row-${v.id}`}>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium text-neutral-900">{v.name ?? '—'}</span>
                    {v.source && <SourceBadge source={v.source} testId={`variant-source-${v.id}`} />}
                    <span className="text-xs text-neutral-400">覆盖 {v.positions.join(' / ')}</span>
                  </div>

                  {/* 分组 · 单位：就地改（`PUT /operations/{id}` 部分更新） */}
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    {editingVariantId === v.id ? (
                      <>
                        <input
                          aria-label="分组"
                          data-testid={`variant-group-input-${v.id}`}
                          className={cn(inputCls, 'h-8 w-28')}
                          value={variantDraft.group_name}
                          onChange={(e) => setVariantDraft({ ...variantDraft, group_name: e.target.value })}
                        />
                        <input
                          aria-label="单位"
                          data-testid={`variant-unit-input-${v.id}`}
                          className={cn(inputCls, 'h-8 w-24')}
                          value={variantDraft.unit}
                          onChange={(e) => setVariantDraft({ ...variantDraft, unit: e.target.value })}
                        />
                        <Button
                          size="sm"
                          data-testid={`variant-meta-save-${v.id}`}
                          disabled={variantBusy}
                          onClick={() =>
                            void submitVariant(v.id, {
                              group_name: variantDraft.group_name,
                              unit: variantDraft.unit,
                            })
                          }
                        >
                          保存
                        </Button>
                        <Button
                          size="sm"
                          variant="secondary"
                          data-testid={`variant-meta-cancel-${v.id}`}
                          onClick={() => setEditingVariantId(null)}
                        >
                          取消
                        </Button>
                      </>
                    ) : (
                      <>
                        <span className="text-neutral-600">
                          {v.group ?? '—'} · {v.unit ?? '—'}
                        </span>
                        <button
                          type="button"
                          aria-label={`编辑 ${v.name ?? v.id} 的分组与单位`}
                          data-testid={`variant-meta-edit-${v.id}`}
                          onClick={() => {
                            setEditingVariantId(v.id)
                            setVariantDraft({ group_name: v.group ?? '', unit: v.unit ?? '' })
                          }}
                          className="rounded p-1 text-neutral-400 hover:bg-neutral-100 hover:text-neutral-700"
                        >
                          <Pencil className="w-3.5 h-3.5" />
                        </button>
                      </>
                    )}
                  </div>

                  {/* 作用域（V67 闭词表两档）+ 一句解释 */}
                  <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-neutral-500">
                    <span>作用域</span>
                    <select
                      aria-label={`${v.name ?? v.id} 作用域`}
                      data-testid={`variant-scope-${v.id}`}
                      value={v.scope}
                      disabled={variantBusy}
                      title={SCOPE_META[v.scope].title}
                      onChange={(e) => void submitVariant(v.id, { scope: e.target.value as ProductionScope })}
                      className="h-8 rounded border border-neutral-300 bg-white px-1.5 text-sm text-neutral-700 focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15 disabled:opacity-50"
                    >
                      {SCOPE_ORDER.map((s) => (
                        <option key={s} value={s}>
                          {SCOPE_META[s].label}
                        </option>
                      ))}
                    </select>
                    <span>套级 = 每樘窗只做一次（部位级 = 每个部位各做一次）</span>
                  </div>

                  {/* 必完 + 一句解释 */}
                  <label className="mt-2 flex flex-wrap items-center gap-2 text-xs text-neutral-500">
                    <input
                      type="checkbox"
                      aria-label={`${v.name ?? v.id} 必完`}
                      data-testid={`variant-must-finish-${v.id}`}
                      checked={v.is_must_finish}
                      disabled={variantBusy}
                      onChange={(e) => void submitVariant(v.id, { is_must_finish: e.target.checked })}
                      className="h-4 w-4 accent-primary-600"
                    />
                    <span>必完 · 缺这道工序不能打包（部位级：每个部位都要做完）</span>
                  </label>

                  {/* 停用（`PUT /operations/{id}` 的 status）/ 删除（`DELETE /operations/{id}`，二次确认） */}
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <Button
                      size="sm"
                      variant="secondary"
                      data-testid={`variant-disable-${v.id}`}
                      disabled={variantBusy}
                      onClick={() => void submitVariant(v.id, { status: 'inactive' })}
                    >
                      停用
                    </Button>
                    {confirmDeleteOpId === v.id ? (
                      <>
                        <Button
                          size="sm"
                          variant="danger"
                          data-testid={`variant-delete-confirm-${v.id}`}
                          disabled={variantBusy}
                          onClick={() => void removeVariant(v)}
                        >
                          确认删除
                        </Button>
                        <Button
                          size="sm"
                          variant="secondary"
                          data-testid={`variant-delete-cancel-${v.id}`}
                          onClick={() => setConfirmDeleteOpId(null)}
                        >
                          取消
                        </Button>
                      </>
                    ) : (
                      <Button
                        size="sm"
                        variant="secondary"
                        data-testid={`variant-delete-${v.id}`}
                        onClick={() => {
                          setConfirmDeleteOpId(v.id)
                          setVariantReasons(null)
                        }}
                      >
                        删除
                      </Button>
                    )}
                    <span className="text-xs text-neutral-400">删除后历史报工不受影响</span>
                  </div>

                  {/* 护栏理由**逐条**就地展示（后端一次报全：被活跃主线 / 活跃规则 / 矩阵格引用） */}
                  {variantReasons?.id === v.id && (
                    <ul className="mt-2 space-y-0.5 text-xs text-red-600" data-testid="variant-delete-reasons">
                      {variantReasons.items.map((r, i) => (
                        <li key={i}>{r}</li>
                      ))}
                    </ul>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </Modal>

      {/* 新增（**类型二选一**：工序 / 特殊选项；issue #4570） */}
      <Modal
        open={newOpOpen}
        onClose={() => !busy && setNewOpOpen(false)}
        title="新增"
        footer={
          <div className="flex justify-end gap-2">
            <Button variant="secondary" disabled={busy} onClick={() => setNewOpOpen(false)}>
              取消
            </Button>
            <Button
              loading={busy}
              data-testid="routings-create-operation-submit"
              onClick={newKind === 'option' ? createOptionRule : createOperation}
            >
              保存
            </Button>
          </div>
        }
      >
        <div className="space-y-3 text-sm">
          <div className="flex gap-2" role="radiogroup" aria-label="新增类型">
            {([
              { key: 'operation', label: '工序' },
              { key: 'option', label: '特殊选项' },
            ] as const).map((k) => (
              <button
                key={k.key}
                type="button"
                role="radio"
                aria-checked={newKind === k.key}
                data-testid={`create-kind-${k.key}`}
                onClick={() => {
                  setNewKind(k.key)
                  setNewOptionReasons([])
                }}
                className={cn(
                  'rounded-full border px-3 py-1 text-sm transition-colors',
                  newKind === k.key
                    ? 'border-primary-600 bg-neutral-50 font-medium text-primary-700'
                    : 'border-neutral-300 text-neutral-600 hover:bg-neutral-50',
                )}
              >
                {k.label}
              </button>
            ))}
          </div>
          {/* 两本账一句话（issue #4570 用户走查的核心困惑：工序价 vs 特殊选项价） */}
          <p className="text-neutral-600" data-testid="create-kind-two-ledgers">
            工序的价是<strong>给工人的计件</strong>（元/件·米·折）；特殊选项的价是
            <strong>对顾客的按套</strong>（元/套）。两者是两本账，互不换算。
          </p>

          {newKind === 'operation' ? (
            <>
              <p className="text-neutral-600">
                单价直接决定工人计件工资，请与车间核对后再填（调价只影响新报工，历史报工按当时价）。
              </p>
              {[
                { key: 'name', label: '工序名称', ph: '如 罗马帘-穿杆' },
                { key: 'group_name', label: '分组', ph: '裁剪 / 车位 / 后道 / 其他' },
                { key: 'unit', label: '单位', ph: '米 / 套 / 件 / 个 / 折' },
              ].map((f) => (
                <div key={f.key}>
                  <label className="mb-1 block text-neutral-600" htmlFor={`new-op-${f.key}`}>
                    {f.label}
                  </label>
                  <input
                    id={`new-op-${f.key}`}
                    data-testid={`routings-create-op-${f.key}`}
                    className={inputCls}
                    placeholder={f.ph}
                    value={(newOp as Record<string, string>)[f.key]}
                    onChange={(e) => setNewOp({ ...newOp, [f.key]: e.target.value })}
                  />
                </div>
              ))}
              <div>
                <label className="mb-1 block text-neutral-600" htmlFor="new-op-unit_price">
                  计件单价（元）
                </label>
                <input
                  id="new-op-unit_price"
                  inputMode="decimal"
                  data-testid="routings-create-op-unit_price"
                  className={inputCls}
                  value={newOp.unit_price}
                  onChange={(e) => setNewOp({ ...newOp, unit_price: e.target.value })}
                />
              </div>
              {/* 适用部位多选（issue #4614）：勾选项 = `positionOptions`（矩阵带出 ∪ 基线三部位，
                  与「新建路线」的适用帘种**同一份口径**）；默认勾基线三部位。 */}
              <div>
                <span className="mb-1 block text-neutral-600">适用部位（至少勾一个）</span>
                <div className="flex flex-wrap gap-3">
                  {positionOptions.map((p) => (
                    <label key={p} className="flex items-center gap-1.5 text-neutral-700">
                      <input
                        type="checkbox"
                        data-testid={`routings-create-op-position-${p}`}
                        checked={newOpPositions.includes(p)}
                        onChange={(e) =>
                          setNewOpPositions((prev) =>
                            e.target.checked
                              ? positionOptions.filter((x) => x === p || prev.includes(x))
                              : prev.filter((x) => x !== p),
                          )
                        }
                        className="h-4 w-4 accent-primary-600"
                      />
                      {p}
                    </label>
                  ))}
                </div>
                <p className="mt-1 text-xs text-neutral-400">
                  勾了哪些部位，这道工序就出现在「工艺项」表的哪些格上并可逐格定价；
                  一个都不勾 ⇒ 建出来在表里看不到它。
                </p>
              </div>
              {newOpReasons.length > 0 && (
                <ul className="space-y-0.5 text-xs text-red-600" data-testid="routings-create-op-reasons">
                  {newOpReasons.map((r, i) => (
                    <li key={i}>{r}</li>
                  ))}
                </ul>
              )}
            </>
          ) : (
            <>
              <div>
                <label className="mb-1 block text-neutral-600" htmlFor="new-option-trigger_value">
                  选项名称
                </label>
                <input
                  id="new-option-trigger_value"
                  data-testid="routings-create-option-trigger_value"
                  className={inputCls}
                  placeholder="如 拼3次 / 免熨 / 防翘扣"
                  value={newOption.trigger_value}
                  onChange={(e) => setNewOption({ ...newOption, trigger_value: e.target.value })}
                />
              </div>
              <div>
                <label className="mb-1 block text-neutral-600" htmlFor="new-option-customer_unit_price">
                  单价（元/套）
                </label>
                <input
                  id="new-option-customer_unit_price"
                  inputMode="decimal"
                  data-testid="routings-create-option-customer_unit_price"
                  className={inputCls}
                  placeholder="如 12.5"
                  value={newOption.customer_unit_price}
                  onChange={(e) => setNewOption({ ...newOption, customer_unit_price: e.target.value })}
                />
                <p className="mt-1 text-xs text-neutral-400">
                  这是对顾客的按套价（元/套），不进工人的计件工资。
                </p>
              </div>
              <div>
                <label className="mb-1 block text-neutral-600" htmlFor="new-option-operation">
                  目标工序
                </label>
                <select
                  id="new-option-operation"
                  data-testid="routings-create-option-operation"
                  className={inputCls}
                  value={newOption.operation}
                  onChange={(e) => setNewOption({ ...newOption, operation: e.target.value })}
                >
                  <option value="">选择这条选项落在哪道工序上…</option>
                  {logicalOps.map((op) => (
                    <option key={op} value={op}>
                      {op}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="mb-1 block text-neutral-600" htmlFor="new-option-after_operation">
                  插入锚点（可选）
                </label>
                <select
                  id="new-option-after_operation"
                  data-testid="routings-create-option-after_operation"
                  className={inputCls}
                  value={newOption.after_operation}
                  onChange={(e) => setNewOption({ ...newOption, after_operation: e.target.value })}
                >
                  <option value="">末尾追加</option>
                  {logicalOps.map((op) => (
                    <option key={op} value={op}>
                      {op}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="mb-1 block text-neutral-600" htmlFor="new-option-priority">
                  优先级（可选）
                </label>
                <input
                  id="new-option-priority"
                  inputMode="numeric"
                  data-testid="routings-create-option-priority"
                  className={inputCls}
                  placeholder="数字越小越先应用（留空 = 后端默认顺序）"
                  value={newOption.priority}
                  onChange={(e) => setNewOption({ ...newOption, priority: e.target.value })}
                />
              </div>
              {newOptionReasons.length > 0 && (
                <ul
                  className="space-y-0.5 text-xs text-red-600"
                  data-testid="routings-create-option-reasons"
                >
                  {newOptionReasons.map((r, i) => (
                    <li key={i}>{r}</li>
                  ))}
                </ul>
              )}
            </>
          )}
        </div>
      </Modal>

      {/* 存量孤儿接入（issue #4614 范围补口）：工序库里有、但没有任何部位价目行的工序
          ⇒ 勾适用部位后 `PUT /operations/{id}` 带 `positions` **只补缺失行**（不删、不覆盖）。 */}
      <Modal
        open={orphanOpen}
        onClose={() => !orphanBusy && setOrphanOpen(false)}
        title="接入部位价目"
        footer={
          <div className="flex justify-end gap-2">
            <Button variant="secondary" disabled={orphanBusy} onClick={() => setOrphanOpen(false)}>
              取消
            </Button>
            <Button loading={orphanBusy} data-testid="orphan-attach-submit" onClick={attachOrphans}>
              接入
            </Button>
          </div>
        }
      >
        <div className="space-y-3 text-sm">
          <p className="text-neutral-600">
            这些工序在<strong>工序库</strong>里有，但<strong>没有任何部位价目行</strong> ⇒
            「工艺项」表里看不到它们、也没法定价（路线编辑的下拉里能看到，是两边口径不一致）。
            勾上要做的部位并接入后，它们会立刻出现在「工艺项」表里，可就地定价。
          </p>
          <p className="text-xs text-neutral-400">
            已有部位价目行<strong>不会被改动</strong>（已定的价保留原价）；想跳过某道工序，把它的部位全部取消勾选即可。
          </p>
          <ul className="space-y-3" data-testid="orphan-attach-list">
            {orphanOps.map((op) => (
              <li
                key={String(op.id)}
                className="rounded border border-neutral-200 px-3 py-2"
                data-testid={`orphan-row-${op.id}`}
              >
                <div className="mb-1.5 flex flex-wrap items-baseline gap-2">
                  <span className="font-medium text-neutral-900" data-testid={`orphan-name-${op.id}`}>
                    {op.name}
                  </span>
                  <span className="text-xs text-neutral-500">
                    {op.group ?? '其他'} · {op.unit ?? '米'}
                  </span>
                </div>
                <div className="flex flex-wrap gap-3">
                  {positionOptions.map((p) => (
                    <label key={p} className="flex items-center gap-1.5 text-neutral-700">
                      <input
                        type="checkbox"
                        data-testid={`orphan-position-${op.id}-${p}`}
                        checked={(orphanPicks[String(op.id)] ?? []).includes(p)}
                        onChange={(e) =>
                          setOrphanPicks((prev) => {
                            const cur = prev[String(op.id)] ?? []
                            return {
                              ...prev,
                              [String(op.id)]: e.target.checked
                                ? positionOptions.filter((x) => x === p || cur.includes(x))
                                : cur.filter((x) => x !== p),
                            }
                          })
                        }
                        className="h-4 w-4 accent-primary-600"
                      />
                      {p}
                    </label>
                  ))}
                </div>
              </li>
            ))}
          </ul>
          {orphanReasons.length > 0 && (
            <ul className="space-y-0.5 text-xs text-red-600" data-testid="orphan-attach-reasons">
              {orphanReasons.map((r, i) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
          )}
        </div>
      </Modal>

      {/* 一键套用确认（批量写入工序/路线，防误触；照知识库页范式） */}
      <Modal open={!!confirmTemplate} onClose={() => setConfirmTemplate(null)} title="套用行业模板" footer={null}>
        <p className="text-sm">
          将把「{confirmTemplate?.name}」的预置工序与工艺路线复制到您的工序库；已存在的条目将自动跳过。
          套用出的单价是<strong>初始价（占位值）</strong>，请逐条确认后按实际工价修改 —— 改价只影响新报工，历史报工按当时价。
        </p>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setConfirmTemplate(null)}>取消</Button>
          <Button data-testid="seed-template-apply-confirm" onClick={applyTemplate} disabled={!!applying}>
            {applying ? '套用中…' : '确定套用'}
          </Button>
        </div>
      </Modal>
    </div>
  )
}
