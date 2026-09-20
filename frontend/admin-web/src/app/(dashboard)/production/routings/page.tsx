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
import { CRAFT_CALC_FORMULA_LABELS } from '@/lib/craft-calc-request'
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
  RouteRuleTriggerKind,
  RouteRuleTriggerOptions,
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
 * | **工序管理**（用户裁定 2026-09-21：原「工艺项」+「工艺路线」两 tab **合并为一屏**，标签定名「工序管理」） | 「每道工序给**工人**多少钱？」+「订单按哪条主线走、什么时候插/删工序？」 | **一张表**：行 = 一道逻辑工序、**一道工序一个单价**（就地可改）+ **必完标记**（issue #4610）；表**下同屏**是**具名路线**（默认徽标 + 主线 + 改名/设默认/删除） | 工序行尾 = `分组 · 单位` + 「管理▸」抽屉（分组 / 单位 / 作用域 / 必完 / 停用 / 删除，以及一节**适用条件**，人话；issue #4650 阶段 1 起**不再有**独立的「条件工序规则」表） |
 *
 * ## 为什么这一屏不再有「部位」（issue #4886，用户裁定）
 *
 * 用户裁定「新的工艺不应该配置部位」⇒ 这一层**彻底退场**：价目**塌缩成「一道工序一个价」**
 * （配套后端改动后 `GET /operation-positions` 每个逻辑工序名**只返回一行**，未定价保留 `NULL`）。
 * ⚠️ 只从**配置这一层**退场 —— 订单行 `curtain_type` 与加工单 `position_name` **保留**
 * （加工环节仍需区分布/纱）⇒ 订单页 / 加工单页 / 报工页**不动**。
 *
 * **工艺项为什么是一屏一张表**（issue #4588 = 母单 #4586 包 B；契约 #4587）：
 * 原形态是**两张平铺表** —— 主区只读矩阵 + 折叠次区「工序库明细」（能改计件单价但**改了不生效**）。
 * 同一个概念两个载体、改一处不生效、还没有任何提示 ⇒ 用户裁定**方案 A：合并成一屏一张表**
 * （用户原话：「工艺项我确实没看懂这样设计是要干啥」）。明细面收进**抽屉**（不是平铺）。
 *
 * **这一屏的价是「给工人的计件单价」**（用户裁定 2026-09-19）：
 * `production_operation_positions.unit_price` = 计件单价，**报工工资 = 数量 × 计件单价**。
 * 收顾客的那笔钱**不在这里** —— 基础工序在「加工项组合费用」，特殊选项在**工序抽屉的「适用条件」**里
 * （`production_route_rules.customer_unit_price`，元/套）。两本账**互不换算** ⇒ 这一屏
 * **不得**出现「加工费」「对客价」字样，也**不引入任何计件系数概念**。
 *
 * ## 与旧形态的关键差异（P2b #4459 / P2c #4500 之后）
 *
 * 1. **路线 = 一条具名主线**（`{id, name, is_default, mainline}`）—— 改名**只改 `name`**
 *    （不给 `mainline` 就不动序列：改一个名字不该顺带重写计件工资的输入）。
 * 2. **行键是逻辑工序名**（`精裁` / `三边`），**不是** `production_operations.name`
 *    （那边仍是旧名 `精裁-布` / `布三边`）。每行带的 5 个变体元数据键（`variant_operation_id` /
 *    `unit` / `group` / `scope` / `is_must_finish`）由后端 `variantNameOf` 推导，
 *    前端**直接取用、不另写一份推导**；5 键全 `null` = 查不到 ⇒ **不发明元数据**（静默 = 未知）。
 *    ⚠️ `variant_name`（`布三边` / `logo条-布` 这类**变体名**）**不出现在任何界面位置**
 *    （含 `data-testid`）—— 它只是后端 `production_operations.name` 的旧口径，读面也不返回它。
 *    `variant_operation_id` 仍要用：它是**寻址键**（抽屉条目按它去重、写面按它发 `PUT/DELETE`）。
 *    主线的「工序是否存在」判据 = **价目表里的逻辑工序名**（issue #4622 补口①：原口径是
 *    「工序库 ∪ 价目表」并集 —— 工序库键是**变体名**，会把残留的变体名误判成「存在」，
 *    而后端按逻辑名判 ⇒ 同一件事两边判得不一样）。
 * 3. **顺序口径**：`operation-positions` 按 `(operation, position)`、`route-rules` 按 `(priority, id)`
 *    —— **服务端已排好**，前端**不重排**（重排会与服务端口径分叉，同一张单两次生成会得到不同序列）。
 *
 * ## 护栏（后端仍是唯一权威；前端只把「保存失败」提前成「看得见」）
 *
 * - **删默认 ⇒ 拦**（默认路线是兜底终点，删了没有专属路线的订单一张加工单也生成不了）；
 * - **删最后一条 ⇒ 拦**（同因）；两条同时成立时**两条理由都给**（后端也一次报全）；
 * - **设为默认**只对非默认行开放（`is_default:false` 后端 422 ⇒ 前端**永不**提交 false）；
 * - 危险操作（删除 / 设为默认）**二次确认**；护栏理由**就地逐条**展示（复用 `lib/production-guard-reasons.ts`）；
 *   工艺项 tab 的两处删除同口径：删**工序**（`DELETE /operations/{id}`，三条护栏一次报全）与
 *   删**一条适用条件**（`DELETE /route-rules/{id}`，无硬护栏）—— 都先二次确认，被拒时逐条就地给理由。
 * - 商家面**不得**出现内部机制名（issue #4453：「信号映射」是研发内部机制）⇒ 后端理由过
 *   `merchantWording` 只换词、不删理由。
 *
 * ## 契约（冻结，**不得自行发明端点/字段名**）
 *   GET    /api/admin/production/routings                 POST /routings   body {name, mainline?, positions?, is_default?}
 *   PUT    /api/admin/production/routings/{id}            DELETE /routings/{id}      （部分更新 {name?, is_default?, mainline?, positions?, status?}）
 *   GET    /api/admin/production/operation-positions      GET  /route-rules
 *   PUT    /api/admin/production/operation-positions/{id}  （#4588 矩阵行写面；🔴 #4937/O1 起 body **只收** {unit_price?} —— `applicable` 已退场，收到即 422）
 *   POST   /api/admin/production/route-rules              （#4650 阶段 1：**条件的唯一创建写面**，被抽屉的「添加条件」复用）
 *   DELETE /api/admin/production/operations/{id}          （#4588 工序软删：三条护栏一次报全）
 *   DELETE /api/admin/production/route-rules/{id}         （#4588 规则软删：无硬护栏；#4650 起从抽屉里删一条条件）
 *   PUT    /api/admin/production/route-rules/{id}/customer-unit-price （#4567 特殊选项对客单价）
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
 * 逻辑工序名 —— **行键的唯一口径**（issue #4886）。
 *
 * ⚠️ 该值在接口里的字段名历史上叫 `operation`（后端 `ProductionRoutingReadService.positionView`
 * 逐字写的就是 `logical_name`）；配套后端可能改叫 `logical_name` ⇒ 这里做
 * `logical_name ?? operation` **兜底读取**，**两种命名都能渲染**（前端不猜、不发明第三份名字）。
 */
const logicalNameOf = (cell: OperationPosition): string =>
  (cell as OperationPosition & { logical_name?: string | null }).logical_name ?? cell.operation

/**
 * 同一逻辑名多行时的**收敛选择**（规则逐字见 {@link convergeByLogicalName}）：
 * 按 `position` 字典序 → `id` 升序取首个 —— 与后端
 * `ProductionOperationQueryService#collapseToLogical` 的**同一把尺**，保证两边选出**同一行**
 * （选错行 = `PUT /operation-positions/{id}` 改的是另一个价）。
 *
 * 🔴 **两条旧平局规则已退场**（issue #4937 / #4951 去部位化彻底版，如实登记为**判据面缩小**）：
 * ① 「优先 `applicable === true`」—— 存活行的 `applicable` **恒 `TRUE`**、该字段已从
 *    {@link OperationPosition} 退场（写面收到它即 422）⇒ 判据的输入不复存在；
 * ② 「其中优先 `布帘`」—— `position` 现在**恒 `通用`**（部位维物理退场）⇒ 没有可优先的列。
 * 留下这一条**不是放宽**：它仍是**完全确定**的（字典序 + `id`，不依赖 DB 返回序），且 #4951 之后
 * 同一逻辑名本就只有一行（收敛是过渡期兜底，选行结果唯一）。
 */
const pickConvergedCell = (group: OperationPosition[]): OperationPosition => {
  if (group.length === 1) return group[0]
  return [...group].sort(
    (a, b) =>
      (a.position ?? '').localeCompare(b.position ?? '') ||
      String(a.id ?? '').localeCompare(String(b.id ?? '')),
  )[0]
}

/**
 * **按逻辑工序名去重收敛为一行**（issue #4886 的**健壮性**要求）——
 * 这是「前后端可各自独立上线」的那道桥。
 *
 * 配套后端上线后 `GET /operation-positions` 每个逻辑工序名**只返回一行**；在它上线前
 * （或读面回退）接口**仍可能返回同一逻辑名的多行**。前端不得因此渲染出重复行
 * ⇒ 一律收敛成一行（规则见 {@link pickConvergedCell}）。
 * ⚠️ 收敛后**保留那一行的 `id`** —— 它就是 `PUT /operation-positions/{id}` 的寻址键。
 * 行序**保持服务端首次出现的顺序**（`Map` 插入序 = 服务端序，前端不重排）。
 */
const convergeByLogicalName = (cells: OperationPosition[]): OperationPosition[] => {
  const byName = new Map<string, OperationPosition[]>()
  cells.forEach((cell) => {
    const name = logicalNameOf(cell)
    byName.set(name, [...(byName.get(name) ?? []), cell])
  })
  return [...byName.values()].map(pickConvergedCell)
}

/**
 * 第一层「工序」的**车间分组**（issue #4677 = 设计 §4.1 元素②；**行业术语**，不是我们发明的词）。
 *
 * 取值来源 = 行尾元数据里的 `group`（已存在，`production_operations.group_name`），**不新造字段**；
 * 本表只做两件事：① 给出**行业正名**（设计 §1.2：《成品窗帘生产流程及工作规范》）——
 * `裁剪` ⇒ 裁剪（裁床）/ `车位` ⇒ 车位（缝制）/ `后道` ⇒ 后整（烫工及后整）；② 固定**折叠组的顺序**。
 *
 * ⚠️ 用**前缀匹配**认领（`裁剪*` 覆盖 `裁剪（裁床）` 这类已带括号的历史值，也覆盖将来
 * `裁剪组` 这类写法）；认不出的分组**照原样追加在后**（不丢组、不改名）—— 同 `metaText`
 * 「不许静默取第一个」的纪律。
 */
const WORKSHOP_LABEL: Array<{ prefix: string; label: string }> = [
  { prefix: '裁剪', label: '裁剪（裁床）' },
  { prefix: '车位', label: '车位（缝制）' },
  { prefix: '后整', label: '后整（烫工及后整）' },
  { prefix: '后道', label: '后整（烫工及后整）' },
  { prefix: '质检', label: '质检' },
  { prefix: '其他', label: '其他' },
]

/** 分组名 → 行业正名（认不出 ⇒ 原样返回，**不发明**名字） */
const workshopLabel = (group: string): string =>
  WORKSHOP_LABEL.find((w) => group.startsWith(w.prefix))?.label ?? group

/** 分组排序权重（认不出 ⇒ 排在最后，保持各自相对顺序） */
const workshopRank = (group: string): number => {
  const i = WORKSHOP_LABEL.findIndex((w) => group.startsWith(w.prefix))
  return i < 0 ? WORKSHOP_LABEL.length : i
}

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
 *
 * ⚠️ **取值（`position` / `set`）是后端契约，一字不动**；变的只是**展示名**（issue #4886：
 * 配置面不再出现部位概念 ⇒ 原「部位级 / 套级」改叫「按件 / 按套」，语义不变）。
 */
const SCOPE_META: Record<ProductionScope, { label: string; title: string }> = {
  position: { label: '按件', title: '每件各做一次（不按套去重）' },
  set: { label: '按套', title: '每套窗只做一次（一套「布 + 纱」只做一次）' },
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

/**
 * 一条条件的**人话**（issue #4650 阶段 1 —— 用户裁定「移除条件工序规则，这个概念我都难以理解」）。
 *
 * 商家看到的不是「触发类型 / 动作 / 目标工序 / 插入锚点」，而是**这道工序在什么情况下做**：
 * - `insert` + 锚点 ⇒ `工艺 = 韩褶 时插入（在「三边」之后）`；
 * - `insert` 无锚点 ⇒ `… 时插入（追加到末尾）`（**不**渲染成「在「末尾」之后」—— 那是把空值当工序名）；
 * - `remove` ⇒ `工艺 = 四爪钩 时不做`。
 *
 * 目标工序由**所在抽屉**表达（这一段只列 `operation === 该工序` 的条件）⇒ 话里不重复工序名。
 */
const conditionText = (rule: RouteRule) => {
  const kind = TRIGGER_KIND_LABEL[rule.trigger_kind ?? ''] ?? rule.trigger_kind ?? '—'
  const value = rule.trigger_value ?? '—'
  if (rule.action === 'remove') return `${kind} = ${value} 时不做`
  return rule.after_operation
    ? `${kind} = ${value} 时插入（在「${rule.after_operation}」之后）`
    : `${kind} = ${value} 时插入（追加到末尾）`
}

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
    <div
      className={cn('flex flex-col gap-0.5', state === 'unpriced' ? 'text-amber-600' : 'text-neutral-600')}
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
    </div>
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

/**
 * 兜底公式的可读文案（取值域由后端枚举给；这里只做展示映射）。
 *
 * ⚠️ **单一真值** = `@/lib/craft-calc-request` 的 `CRAFT_CALC_FORMULA_LABELS`（issue #4878 独立复核）：
 * 本页原来自带一份**逐字相同、但没有任何守卫**的副本（下单页另有一份）⇒ 改一处忘一处就**静默分叉**
 * （下单页显示「韩折公式（折数法）」、这里显示别的字）。⇒ 改为**直接复用同一张表**，不再各写一份。
 */
const CALC_FORMULA_LABEL: Record<string, string> = CRAFT_CALC_FORMULA_LABELS

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
 * ⚠️ `resolved` = 该工序能在**工序库**里查到（才有 分组/单位 这些库口径元数据）。
 * 主线存的是**逻辑工序名**（`精裁`），而 `production_operations.name` 仍是旧名（`精裁-布`）；
 * **issue #4642 起读面已把库名归一后暴露**（catalog 的 `name` = 逻辑名；库口径原名走 `library_name`
 * 且 web 不得渲染）⇒ `libraryByName` 按逻辑名建键**能查到**，`resolved` 因此**变好**
 * （改前库按变体名索引、主线存逻辑名 ⇒ 几乎恒为 `false`）。仍然**不猜**：查不到就只显示名字，不发明单位。
 *
* ⚠️ **「必完」的判定来源是价目表**（issue #4622 补口②；issue #4886 起收敛为**布尔**）：
* 原口径读的是 `libraryByName.get(name)?.is_must_finish` —— 库按**变体名**索引，而主线存的是
* **逻辑名** ⇒ 查不到 ⇒ 那枚「必完」标记对逻辑名几乎永远不显示。
 * `is_must_finish`（库口径）只剩一个用途：{@link ProcessConfigPage} 的「一道必完工序都没有」预检
 * （它自带 `resolved` 门禁，口径未动）。
 *
* ⚠️ **本口径不含单价**（issue #4583 用户裁定）：单价是**计件工资**口径，属「工艺项」那一屏的事；
* 而这里能拿到的只有**工序库单价**，真正生效的价是价目行上的价 ⇒ 显示它有误导性。
 * 且「显示与否」曾取决于「逻辑名与变体名是否恰好一致」（`外帘打卷`/`外帘装袋`/`外帘发货`
 * 只有那三处逻辑名与库口径名恰好同名时才显示，其余 6 道不显示）⇒ **统一不显示**。
 */
interface StepView {
  seq: number
  operation: string
  group?: string | null
  unit?: string | null
  /** 库口径必完（**只给「一道必完工序都没有」预检用**；chip 上的必完见 `must_finish`） */
  is_must_finish?: boolean
/** **价目表**口径的必完（issue #4622 补口② / #4886）：`null` = 查不到这道工序 ⇒ 不显示（未知） */
must_finish: boolean | null
  /** 工序库里有这条（有库口径元数据） */
  resolved: boolean
  /** 矩阵里没有它（停用/被删/名字是变体名）⇒ 保存必被后端拒，但页面要先让人看见 */
  missing: boolean
}

/**
 * 工序**单价格**（issue #4886）：一屏一张表里该工序的**唯一一个价** —— 就地可改。
 *
 * **两态**互斥且可区分（#4951 去部位化彻底版起由三态收敛为两态）：
 * - `priced` ⇒ `¥x.xx`（`0` 是**真价**，照显示 `¥0.00` —— ≠「未定价」）；
 * - `unpriced` ⇒ 「未定价」（`unit_price = null`，是**待办**、不是 0 元；**绝不**回落工序库单价）。
 *
 * 🔴 **第三态 `na`（「不做」）已退场**（issue #4937 / #4951）：V102/V104 之后存活价目行的
 * `applicable` **恒 `TRUE`** ⇒「不做」**不可达**，本组件不再有这一分支 —— `applicable` 也不再是
 * {@link OperationPosition} 的字段（写面收到它即 **422**）。「未定价 ≠ ¥0.00」这条**一字不放宽**。
 *
 * 写动作**一个端点、一个 body**：改价 ⇒ `PUT /operation-positions/{id}` `{unit_price}`
 * （清空 = `null` = 改回未定价）。失败理由**就地逐条**展示
 * （后端 `error.details[].message`，**不**吞成一句「保存失败」）。
 */
function OperationPriceCell({
  operation,
  cell,
  editing,
  draft,
  busy,
  reasons,
  onStartEdit,
  onDraftChange,
  onSave,
  onCancel,
}: {
  operation: string
  cell?: OperationPosition | null
  editing: boolean
  draft: string
  busy: boolean
  reasons: string[]
  onStartEdit: () => void
  onDraftChange: (v: string) => void
  onSave: () => void
  onCancel: () => void
}) {
  const state = cellState(cell)
  const hasPrice = state === 'priced'
  return (
    <div
      data-testid={`operation-price-${operation}`}
      data-state={state}
      title={
        state === 'unpriced'
          ? `「${operation}」还没定价（≠ ¥0.00）`
          : `「${operation}」计件单价（给工人） ${money(cell?.unit_price)}`
      }
      className={cn(state === 'unpriced' ? 'text-amber-700' : 'text-neutral-900')}
    >
      {editing ? (
        <span className="flex items-center gap-1.5">
          <input
            value={draft}
            inputMode="decimal"
            aria-label={`${operation} 计件单价（给工人）`}
            data-testid={`operation-price-input-${operation}`}
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
            data-testid={`operation-price-save-${operation}`}
            disabled={busy}
            onClick={onSave}
            className="rounded p-1 text-primary-600 hover:bg-neutral-100 disabled:opacity-50"
          >
            <Check className="w-4 h-4" />
          </button>
          <button
            type="button"
            aria-label="取消"
            data-testid={`operation-price-cancel-${operation}`}
            disabled={busy}
            onClick={onCancel}
            className="rounded p-1 text-neutral-400 hover:bg-neutral-100 disabled:opacity-50"
          >
            <X className="w-4 h-4" />
          </button>
        </span>
      ) : (
        <span className="flex items-center gap-1.5">
          <span>{state === 'unpriced' ? '未定价' : money(cell?.unit_price)}</span>
          <button
            type="button"
            aria-label={`编辑「${operation}」计件单价（给工人）`}
            data-testid={`operation-price-edit-${operation}`}
            onClick={onStartEdit}
            className="rounded p-1 text-neutral-400 hover:bg-neutral-100 hover:text-neutral-700"
          >
            <Pencil className="w-3.5 h-3.5" />
          </button>
        </span>
      )}
      {editing && reasons.length > 0 && (
        <ul className="mt-1 space-y-0.5 text-xs text-red-600" data-testid={`operation-price-reasons-${operation}`}>
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
    </div>
  )
}

/**
 * 行尾「管理▸」入口（issue #4677 = 设计 §7 第 7 条约束②：**移到行上**、与格无关）。
 *
 * 两个分区共用：工序层与打包发货层**同一份抽屉** —— 抽屉的判据是逻辑工序名（`manageOp`），
 * 与「在哪个分区」无关。
 */
function ManageButton({
  operation,
  onOpen,
  testIdPrefix = 'matrix-manage',
}: {
  operation: string
  onOpen: (operation: string) => void
  testIdPrefix?: string
}) {
  return (
    <button
      type="button"
      data-testid={`${testIdPrefix}-${operation}`}
      onClick={() => onOpen(operation)}
      title="管理这道工序的设置：分组 / 单位 / 作用域 / 必完 / 停用 / 删除"
      className="rounded px-1.5 py-0.5 text-xs text-primary-700 hover:bg-neutral-100"
    >
      管理▸
    </button>
  )
}


/**
 * 抽屉里的一行 = 该逻辑工序**落到工人端的那道工序**的设置（按 `variant_operation_id` 去重）。
 *
 * ⚠️ 条目主标识 = **逻辑工序名**（`manageOp`，issue #4886）—— 变体名（`布三边`）不上界面
 * （issue #4622：读面也不返回它）。元数据**逐字取自**读面的 5 个键（契约 #4587 ①）——
 * 前端**不推导**、不补默认值。
 */
interface VariantView {
  id: string
  group: string | null
  unit: string | null
  scope: ProductionScope
  is_must_finish: boolean
  /** 工序库里的 provenance；查不到 ⇒ `null` ⇒ **不渲染徽标**（静默 = 未知） */
  source: ProductionSource | null
  /**
   * 本条目是**按逻辑名回退**认出来的（issue #4674 C）：它的价目行 `variant_operation_id`
   * **未指向**该工序（NULL）⇒ 读面给不出变体 id，而**后端判据**（`variantNameOf` 按逻辑名反查）
   * 认得出它 ⇒ 两把尺不一致。
   * ⇒ 前端**照样认**（与后端同一份口径、不静默空）但**显式提示**「这些价目行未关联到本工序」。
   */
  unlinked: boolean
  /**
   * **指向别处**的价目行（issue #4674 C 的形态②）：行自带的 `variant_operation_id` 与
   * 「按逻辑名认出来的那道工序」**不是同一个** ⇒ 这一行属于**别的**工序。
   * 这种行**只如实报出、不给写面**（对它 PUT/DELETE 就是改另一道工序）。
   */
  foreign?: boolean
}

/**
 * 一道工序的**两态**：没定价 / 有价 —— 两态**不同形**（`null` 价**绝不**渲染成 `¥0.00`）。
 * 顶层函数（不闭包）⇒ 单价格组件也能用同一份判据。
 *
 * 🔴 原第三态 `na`（`applicable=false` ⇒「不做」）已随 **#4951 去部位化彻底版**退场：
 * 存活价目行的 `applicable` 恒 `TRUE`（V102/V104）⇒ 该态**不可达**，不再有 `na` 分支。
 * ⚠️ `unit_price=null ⇒ unpriced` 这条**一字不放宽**（未定价 ≠ ¥0.00；回落库行价会让工人白干）。
 */
const cellState = (cell?: OperationPosition | null): 'unpriced' | 'priced' => {
  if (!cell) return 'unpriced'
  return cell.unit_price == null ? 'unpriced' : 'priced'
}

/**
 * 必完口径（issue #4610，用户裁定「**必完标记还是得在这里展示**」—— 它是完工门槛，
 * 要一眼看得见；主表行尾与主线 chip **共用**这一份）。
 *
 * 数据来源 = 读面每行**已有**的 `is_must_finish`（契约 #4587 ① 的 5 键之一），
 * **不新造字段、不另拉接口**。
 * ⚠️ issue #4886：**一道工序一个价**之后，原「必完（部分子项）」那种多档聚合三态**不再存在**
 * ⇒ 判据**只看该工序自己那一行**的 `is_must_finish`（`null` = 读面没给 ⇒ **不显示**，
 * 不得发明「非必完」这类新词）。
 */
const mustFinishOf = (cell?: OperationPosition | null): boolean => cell?.is_must_finish === true

/** 必完标记的展示文案（主表行尾与主线 chip 共用一份 —— 各拼一份必然漂移） */
const mustFinishLabel = () => '必完'

/** 必完标记的 title（主表行尾与主线 chip 共用一份） */
const mustFinishTitle = () => '必完：缺这道工序不能打包'

/**
 * 价目表的一行 = **一道逻辑工序**（issue #4886）。
 *
 * `cells` 是**单元素** Map（键 = 该行原属的 `position`），只为「按行取元数据」的既有调用点保留
 * 同形；新代码请直接用 `cell`（`positions` 已不是这一层的概念）。
 */
interface MatrixRow {
  operation: string
  cell: OperationPosition
  cells: Map<string, OperationPosition>
}

export default function ProcessConfigPage() {
  // ── 只读面 ──
  const [catalog, setCatalog] = useState<OperationsCatalog | null>(null)
  const [catalogError, setCatalogError] = useState('')
  const [routings, setRoutings] = useState<RoutingsResponse | null>(null)
  const [templates, setTemplates] = useState<ProductionSeedTemplate[]>([])
  const [matrix, setMatrix] = useState<OperationPosition[]>([])
  const [matrixError, setMatrixError] = useState('')
  // ⚠️ issue #4886 用户裁定（附线上截图）后，原来的「【打包发货】独立区块」**整块删除** ⇒
  // 它的两个 state（服务端聚合 `deliveryAgg` + 读面失败面 `layersError`）与 `getOperationLayers`
  // 那次请求**一并退场**：那 5 道 `scope='set'` 工序本来就有矩阵行与 `id`，并回唯一那张表即可，
  // 再留一个「同一个概念的第二载体」就是第二份会漂的口径（同 #4650 阶段 1 的删法）。
  const [rules, setRules] = useState<RouteRule[]>([])
  const [rulesError, setRulesError] = useState('')
  const [loading, setLoading] = useState(true)
  /**
   * **两个 tab**：`process` 工序管理 / `calc` 算料配置。默认落在前者（依赖顺序上它在前）。
   *
   * <p>用户裁定（2026-09-21，附线上截图）：「【打包发货】这里的表单也直接删，把工艺路线的功能放置到
   * 这块区域，两个 tab 合并成一个」⇒ 原 `operations`（工艺项）与 `routes`（工艺路线）合为 `process`
   * 一屏：上面是**唯一**那张「一道工序一个价」表（原【打包发货】那 5 道 `scope='set'` 工序
   * **并回同一张表** —— 删掉那个独立区块**不减少任何定价入口**），原【打包发货】的位置改放
   * **工艺路线**。</p>
   */
  const [tab, setTab] = useState<'process' | 'calc'>('process')
  /** 「添加工序」选择器（路线 tab 内）—— 工序库在另一个 tab，编辑器必须自带入口 */
  const [picked, setPicked] = useState('')
  const [error, setError] = useState('')
  /** 工序名搜索（**一个控件管整个「工艺项」tab**：这一屏唯一的表按行过滤） */
  const [search, setSearch] = useState('')

  // ── 矩阵格写面（issue #4588；契约 #4587 ②）──
  /** 正在编辑的工序（键 = 逻辑工序名）；`null` = 没有行在编辑态 */
  const [cellEditing, setCellEditing] = useState<string | null>(null)
  const [cellDraft, setCellDraft] = useState('')
  const [cellBusy, setCellBusy] = useState(false)
  /** 保存被拒的**逐条**理由（按格就地展示，不吞成一句「保存失败」） */
  const [cellReasons, setCellReasons] = useState<{ key: string; items: string[] } | null>(null)

  // ── 「管理▸」抽屉（该工序的设置维护面：分组 / 单位 / 作用域 / 必完 / 停用 / 删除）──
  const [manageOp, setManageOp] = useState<string | null>(null)
  /**
   * 第一层【工序】的**车间折叠**状态（issue #4677 = 设计 §4.1 元素②）。
   *
   * ⚠️ 键 = **分组原值**（不是行业正名）—— 正名只用于显示，判据一律用数据里的原值。
   * 缺键 / 值不为 `false` ⇒ **展开**（默认展开：商家进来第一眼要看见工序，不是先点开四个抽屉）。
   */
  const [openWorkshops, setOpenWorkshops] = useState<Record<string, boolean>>({})
  const [editingVariantId, setEditingVariantId] = useState<string | null>(null)
  const [variantDraft, setVariantDraft] = useState({ group_name: '', unit: '' })
  const [variantBusy, setVariantBusy] = useState(false)
  /**
   * 逐行写面（分组 / 单位 / 作用域 / 必完）被拒的**逐条**理由 —— 渲染在抽屉顶部
   * （`data-testid="variant-reasons"`）。
   * ⚠️ issue #4947：改前它**唯一**的渲染点在逐行那一套删除弹框里（弹框不打开就看不见 = 静默）；
   * 那套弹框随去重退场后，这里成为它唯一的渲染点（写面失败**不得静默**）。
   * 与 footer 写面的 `opLevelReasons` **分开**：两处触发源不同。
   */
  const [variantReasons, setVariantReasons] = useState<{ id: string; items: string[] } | null>(null)
  /**
   * 抽屉**层**的删除二次确认（issue #4674 A）—— 目标是**抽屉当前展示的那一行**
   * （issue #4947 统一口径，见 `manageTargetOp`），**不依赖**矩阵格是否关联得上。
   * **只有这一条入口**（逐行那条已随 #4947 去重退场），写面仍是同一个 `DELETE /operations/{id}`。
   */
  const [confirmDeleteOpByName, setConfirmDeleteOpByName] = useState<string | null>(null)
  /**
   * 抽屉**层**写面（停用 / 删除）被拒时的理由 —— 与逐行写面的 `variantReasons` **分开**：
   * 两者的触发源不同（逐行 = `submitVariant` 的写面、抽屉层 = footer 的停用 / 删除），
   * 共用一份会让「逐行保存失败」在抽屉顶部多出一条**错位**的理由条。
   */
  const [opLevelReasons, setOpLevelReasons] = useState<string[] | null>(null)

  // ── 一条条件的删除（issue #4588；契约 #4587 ④；issue #4617 改弹框）──
  const [confirmDeleteRuleId, setConfirmDeleteRuleId] = useState<number | null>(null)
  const [ruleDeleteReasons, setRuleDeleteReasons] = useState<{ id: number; items: string[] } | null>(null)
  const [ruleBusy, setRuleBusy] = useState(false)

  // ── 抽屉里的「适用条件」（issue #4650 阶段 1：条件**挂在工序身上**，独立规则表从界面移除）──
  /**
   * 触发值**取值域**（`GET /route-rule-options`）：工艺词表 + 加工项目录。
   * 拿不到就退化成空列表 —— 下拉里没有可选项，**不静默给一份写死的词表**（那是第二份会漂的口径）。
   */
  const [ruleOptions, setRuleOptions] = useState<RouteRuleTriggerOptions>({ crafts: [], processing_items: [] })
  /** 「添加条件」表单是否展开（就地展开在该工序的抽屉里，**不是**弹窗、**不是**独立表） */
  const [conditionFormOpen, setConditionFormOpen] = useState(false)
  /**
   * 添加条件只问**两件事**（用户裁定：商家不该填「触发类型 / 触发值 / 限定范围 / 动作 / 目标工序 /
   * 插入锚点 / 优先级」七个字段）：**什么时候**（种类 + 取值）与**做还是不做**；
   * 「插在哪道之后」只在「做」时出现，且**带默认值**（见 {@link anchorDefaultFor}，别让商家猜）。
   * 目标工序 = 当前抽屉那道工序（不需要问）。`priority` 交给后端默认顺序（界面不再有这个概念）。
   */
  const [conditionDraft, setConditionDraft] = useState<{
    trigger_kind: RouteRuleTriggerKind
    trigger_value: string
    action: 'insert' | 'remove'
    after_operation: string
  }>({ trigger_kind: 'craft', trigger_value: '', action: 'insert', after_operation: '' })
  /** 添加条件的**就地**理由（本地预检 ∪ 后端 `error.details[].message` 逐条） */
  const [conditionReasons, setConditionReasons] = useState<string[]>([])

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
   * 新建路线：**只问名字**（issue #4886 —— 路线适用范围随旧配置面一起退场）。
   * 路线命中仍是 `(is_default DESC, id)` 首个命中，但不再由前端挑适用范围。
   */
  const [newRoute, setNewRoute] = useState<{ name: string }>({ name: '' })
  const [newOpOpen, setNewOpOpen] = useState(false)
  const [newOp, setNewOp] = useState({ name: '', group_name: '', unit: '', unit_price: '' })
  /** 新增**工序**的**就地**理由（本地预检；照 {@link newOptionReasons} 那套形态逐条展示） */
  const [newOpReasons, setNewOpReasons] = useState<string[]>([])
  /**
   * 「新增」对话框的**类型二选一**（issue #4570，用户裁定：「只要能新增工序项就行了，并可以设置为
   * 特殊选项或者工序，也支持设置单价」）。默认 `operation`（工序 —— 既有链路逐字不变）。
   */
  const [newKind, setNewKind] = useState<'operation' | 'option'>('operation')
  /**
   * 特殊选项草稿（`trigger_value` = 选项名；`customer_unit_price` = **对客**元/套）。
   *
   * issue #4650 阶段 1：**优先级整块去掉**（界面不再有这个概念，交给后端默认顺序 ——
   * 与今天留空同义）；「插入锚点」改叫**插在哪道工序之后**，且选定目标工序后**自动填默认值**
   * （{@link anchorDefaultFor}），商家不用猜。
   */
  const [newOption, setNewOption] = useState({
    trigger_value: '',
    customer_unit_price: '',
    operation: '',
    after_operation: '',
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
    const [routingsRes, catalogRes, templateRes, positionsRes, rulesRes, ruleOptionsRes] =
      await Promise.allSettled([
      productionApi.getRoutings(),
      productionApi.getOperationsCatalog(),
      productionApi.getSeedTemplates(),
      // ① 矩阵格（含 `id` ⇒ 抽屉写面寻址；`GET /operation-positions` 与分区读面的 `operations`
      //    段**同形**，本页只用它拿格 —— 分区与一列价由下面那条端点给，**不重算**）
      productionApi.getOperationPositions(),
      productionApi.getRouteRules(),
      productionApi.getRouteRuleOptions(),
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
    if (positionsRes.status === 'fulfilled') {
      // 价目行 = **全部**行（含 `scope='set'` 的交付环节行）—— 改价按行的 `id` 寻址，而两层分区
      // 读面的 `delivery` 段是**聚合行**（无 `id`）⇒ 写面必须靠这里。
      // ⚠️ issue #4886：`logical_name ?? operation` 兜底归一在**入口一处**做，
      // 下游一律按 `operation` = 逻辑工序名读（不把 fallback 散落到每个消费点）。
      setMatrix(
        (positionsRes.value.data?.data ?? []).map((c) => ({ ...c, operation: logicalNameOf(c) })),
      )
      setMatrixError('')
    } else {
      setMatrix([])
      setMatrixError('工序单价加载失败，请稍后重试')
    }
    if (rulesRes.status === 'fulfilled') {
      setRules(rulesRes.value.data?.data ?? [])
      setRulesError('')
    } else {
      setRules([])
      setRulesError('适用条件加载失败，请稍后重试')
    }
    // 触发值取值域（issue #4616）：**拿不到就空列表**（下拉无可选项），
    // 不回落任何写死的词表 —— 回落 = 第二份会漂的口径（新建的工艺永远进不了下拉）。
    if (ruleOptionsRes.status === 'fulfilled') {
      const opts = ruleOptionsRes.value.data?.data
      setRuleOptions({ crafts: opts?.crafts ?? [], processing_items: opts?.processing_items ?? [] })
    } else {
      setRuleOptions({ crafts: [], processing_items: [] })
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
  /**
   * 价目表里出现过的**逻辑工序名** —— 它同时是**主线取值域**与「工序是否存在」的**唯一权威**
   * （issue #4622 补口①）。⚠️ 原口径是「工序库 ∪ 矩阵」并集，而工序库键是**变体名**
   * （`精裁-布`）⇒ 主线里残留的变体名会被误判成「存在」而不报，后端（按逻辑名判）却会把它
   * 当未知名 ⇒ **同一件事两边判得不一样**。
   */
  const matrixOps = useMemo(() => new Set(matrix.map((c) => c.operation)), [matrix])

  /**
   * **孤儿工序**（issue #4614 范围补口）：工序库里有、但**没有任何价目行指向它**。
   *
   * <p>用户实测原话：「我现在在**工艺项**中看不到 测试22，但是在**路线编辑的下拉列表**能看到，是 bug」
   * —— 两边口径不一致（「工艺项」按价目行渲染、「路线编辑」下拉按工序库渲染）。</p>
   *
   * <p>判据用 **`variant_operation_id`**（读面按后端的 `variantNameOf` 反查出来的「该行落地变体」）
   * 而**不是**名字。⚠️ issue #4886：它的**出路**（接入弹窗）已随旧配置面退场 ⇒ 现在只作**只读提示**
   * （见渲染处的 `matrix-orphan-hint`）；配套后端「一道工序一行」落地后，新建工序即自带价目行，
   * 孤儿只剩存量数据。</p>
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

  // ────────────────────────── 工艺项：两层（【工序】/【打包发货】）──────────────────────────

  /**
   * 行 = **一道逻辑工序一个单价**（issue #4886）。
   *
   * ⚠️ 先按逻辑工序名**去重收敛**（{@link convergeByLogicalName}）—— 配套后端未上线时读面
   * 可能仍返回同一逻辑名的多行；收敛后每行恰好持有**那一行**（`cell`），`cells` 只为既有
   * 「按行取元数据」的调用点保留同形（单元素 Map）。
   * **保持服务端顺序**（`Map` 插入序 = 首次出现顺序），前端**不重排**。
   * ⚠️ 不再有「过滤掉不做的那一行」这件事（#4951：`applicable` 已退场且恒 `TRUE`）——
   * 价目读面给几行就收敛成几行，「不做」在这一屏**不是一种状态**。
   */
  const matrixRows = useMemo<MatrixRow[]>(
    () =>
      convergeByLogicalName(matrix).map((cell) => ({
        operation: cell.operation,
        cell,
        cells: new Map([[cell.position, cell]]),
      })),
    [matrix],
  )

  /**
   * 某道工序在价目读面里的**那一行**（issue #4886：一屏一行一道工序）。
   * `null` = 该工序没有价目行（「打包发货」层的必完回落服务端 `is_must_finish`）。
   */
  const matrixRowCell = useCallback(
    (operation: string) => matrixRows.find((r) => r.operation === operation)?.cell ?? null,
    [matrixRows],
  )

  /**
   * 「目标工序 / 插入锚点」下拉的取值域 = **逻辑工序名**（issue #4570）。
   *
   * ⚠️ 口径：`production_route_rules.operation` / `after_operation` 存的是**逻辑工序名**
   * （`精裁` / `三边`），而 `production_operations.name` 是**库口径**（旧名 `精裁-布`）
   * —— 两者不是同一把尺（本页 `stepView` 的 `resolved` 判据早已按此区分）。
   * ⇒ 本页唯一**已有**的逻辑名来源就是价目表的行键（`GET /operation-positions`，
   * 服务端顺序）⇒ 直接复用它，**不新造第二份工序名清单**、不重排、不拼写。
   */
  const logicalOps = useMemo(() => matrixRows.map((r) => r.operation), [matrixRows])

  /**
   * 既有规则里出现过的**特殊选项名**（issue #4616 弹窗的候选，不是白名单）。
   *
   * 特殊选项名按现状**可新建**（没有第二份词表，后端也不校验）⇒ 这里只把已用过的名字
   * 做成候选（防拼写漂移），**不**把输入限制成「只能选这些」（那会让新建选项无路可走）。
   */
  const optionNames = useMemo(
    () => [...new Set(rules.filter((r) => r.trigger_kind === 'option').map((r) => r.trigger_value ?? ''))]
      .filter((n) => n !== ''),
    [rules],
  )

  /**
   * **表的行 = 全部矩阵行**（用户裁定 2026-09-21：「【打包发货】这里的表单也直接删」）。
   *
   * ⚠️ 原来按 `scope` 分成「工序层」+「【打包发货】层」两处渲染（issue #4677 的两层分区）；
   * 用户裁定后**合并为一处** —— 那 5 道 `scope='set'` 工序（`打包` / `外帘打卷` / `外帘装袋` /
   * `外帘发货` / `裁剪`）本来就在 `matrixRows` 里（有矩阵行、有 `id`、可改价），
   * 独立区块只是同一批工序的**第二个视图** ⇒ 删掉它**不减少任何定价入口**，
   * 而且消灭了「同一个概念两个载体」这条漂移面（同 #4650 阶段 1 的删法）。
   */
  const operationsRows = matrixRows

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
   * 第一层**按车间分组**（issue #4677 = 设计 §4.1 元素②）：分组名取行尾元数据的 `group`
   * （各格不一致时**逐个列出**，同 {@link metaText} 口径 —— 不静默取第一个），
   * 顺序按 {@link WORKSHOP_LABEL}（裁剪 → 车位 → 后整 → 质检 → 其他），认不出的组**照原样追加在后**。
   */
  const workshopGroups = useMemo(() => {
    const byGroup = new Map<string, MatrixRow[]>()
    operationsRows.forEach((row) => {
      const groups = distinctMeta(row, (c) => c.group)
      const key = groups.length > 0 ? groups.join(' / ') : ''
      byGroup.set(key, [...(byGroup.get(key) ?? []), row])
    })
    return [...byGroup.entries()]
      .map(([group, rows]) => ({ group, rows }))
      .sort((a, b) => workshopRank(a.group) - workshopRank(b.group))
  }, [operationsRows])


  const visibleMatrixRows = useMemo(
    () => operationsRows.filter((r) => !q || r.operation.toLowerCase().includes(q)),
    [operationsRows, q],
  )

  /**
   * **搜索过滤后**的车间分组（issue #4677；零退化锁 ⑰-⑨）：过滤是**行级**的，而分组是行的外壳
   * ⇒ 必须在这里一起过滤，否则搜索框看着有字、行却一个不少（分组外壳把行"兜"住了）。
   * 一道都不剩的组**不渲染**（不给一个点了里面什么都没有的空壳）。
   */
  const visibleWorkshopGroups = useMemo(
    () =>
      workshopGroups
        .map((g) => ({
          group: g.group,
          rows: g.rows.filter((r) => !q || r.operation.toLowerCase().includes(q)),
        }))
        .filter((g) => g.rows.length > 0),
    [workshopGroups, q],
  )

  /** 分组标题的可见文字（组名 + 「N 道」）—— 商家一眼看出这一组有几道活 */
  const workshopTitle = (group: string, count: number) =>
    `${group === '' ? '未分组' : workshopLabel(group)} · ${count} 道`

  /**
   * 未定价工序数（**待办计数**：还没定价；真 0 元不算）。#4951 之后也不再有「不做」可排除
   * —— 那一态不可达（`applicable` 恒 `TRUE` 且已从类型退场）。
   * ⚠️ 按**收敛后的行**数（一屏一行一道工序）—— 直接数 `matrix` 会把同一道工序的多行重复计数。
   */
  const unpricedCount = useMemo(
    () => matrixRows.filter((r) => cellState(r.cell) === 'unpriced').length,
    [matrixRows],
  )

  /**
   * 行尾元数据 = 该行各格变体元数据的**公共值**；各格不一致时**逐个列出**（用 ` / ` 分隔）——
   * **不许静默取第一个**（取第一个会让「这道工序在两个分组里」这种事静默消失）。
   * 5 键全 `null`（查不到变体）⇒ 空数组 ⇒ 渲染 `—`（不发明元数据）。
   */
  const metaText = (values: string[]) => (values.length > 0 ? values.join(' / ') : '—')

  const metaInconsistent = (values: string[]) => values.length > 1

  /**
   * **矩阵口径的必完聚合**（逻辑工序名 → 三态；issue #4622 补口②）：主表行尾与**主线 chip**
   * 共用同一份口径（两处各写一份必然漂移）。
   */
  const matrixMustFinish = useMemo(() => {
    const m = new Map<string, boolean>()
    matrixRows.forEach((row) => {
      const v = mustFinishOf(row.cell)
      if (v) m.set(row.operation, v)
    })
    return m
  }, [matrixRows])

  /**
   * 「从工序库选择要添加的工序…」的取值域 = **逻辑工序名**（issue #4609）。
   *
   * ⚠️ 为什么不能再用 `catalog.groups[].operations`（{@link libraryOps}）：那是**库口径**，35 行里
   * 同一道逻辑工序在库里**重复出现**（`精裁-布` / `精裁-纱`），且 `value` 是变体名 ⇒
   * 加入主线的就是变体名（`精裁-布`），而实例化 `buildRoute` 的适用性矩阵按**逻辑名**建键
   * ⇒ `get("精裁-布")` = null ⇒ **该道工序被静默丢掉**（商家加了工序，加工单里没有）。
   * 取值域改由**价目读面的行键**给出（与 {@link logicalOps} 同源：天然是逻辑名、天然去重）；
   * 分组取该行各格的**公共值**（各格不一致时逐个列出 —— 同 {@link metaText} 口径，不静默取第一个）。
   *
   * ⚠️ `libraryByName`（主线 chips 解析**变体**元数据）仍按变体名索引，**不要**一起改。
   */
  const paletteOps = useMemo(
    () => matrixRows.map((row) => ({ name: row.operation, groups: distinctMeta(row, (c) => c.group) })),
    [matrixRows],
  )

  /**
   * **抽屉的设置行与表格成行的口径必须对齐**（issue #4674 C，治本）。
   *
   * <p>表格按**逻辑名**成行（`matrixRows` 的键 = `GET /operation-positions` 的 `operation`），
   * 而抽屉原先**只**按格的 `variant_operation_id` 找变体 ⇒ 该键为 NULL / 指向别处时抽屉**静默空**
   * （「行在 · 抽屉空 · 无处可删」，用户实测的**死路**）。</p>
   *
   * <p>回退判据 = **工序库按逻辑名查到的那一行**（`libraryByName` 的键 = 读时归一后的逻辑名，
   * 与矩阵行键同源）—— 与后端 `variantNameOf` 的裸名兜底同一份口径：读面查不到变体（5 键全 null）
   * 时，后端仍按逻辑名认得出这道工序（护栏③就是这么判的）⇒ 前端**不得**判得比后端严。</p>
   *
   * <p>⚠️ 同名多行（`精裁-布` / `精裁-纱` 归一后同名）**不静默取第一个**：取**排序稳定**的首行
   * （服务端顺序）并如实报出候选数，让「到底是哪条库行」可解释（与 `metaText` 同纪律）。</p>
   */
  const fallbackOpByName = useMemo(() => {
    const m = new Map<string, { op: CatalogOperation; candidates: number }>()
    libraryOps.forEach((op) => {
      const cur = m.get(op.name)
      if (cur) {
        cur.candidates += 1
        return
      }
      m.set(op.name, { op, candidates: 1 })
    })
    return m
  }, [libraryOps])

  /**
   * 同一**逻辑名**下的**全部**库行 id（issue #4674 C 的「属于本工序」判据）。
   *
   * <p>⚠️ **必须按集合判、不能只比首行**：同一道逻辑工序在库里有**多行**（`韩褶-布` / `韩褶-纱`
   * 归一后同名，价目表按逻辑名各自指到不同那行）⇒ 只比首行会把**合法的**行误判成
   * 「指向别处」而抽掉它的写面（那才是真的判错）。</p>
   */
  const idsByName = useMemo(() => {
    const m = new Map<string, Set<string>>()
    libraryOps.forEach((op) => {
      const set = m.get(op.name) ?? new Set<string>()
      set.add(String(op.id))
      m.set(op.name, set)
    })
    return m
  }, [libraryOps])

  /** 抽屉里那道工序对应的**工序库那一行**（issue #4674：抽屉层入口靠它寻址，不靠矩阵格） */
  const manageOpEntry = useMemo(
    () => (manageOp ? fallbackOpByName.get(manageOp) ?? null : null),
    [fallbackOpByName, manageOp],
  )

  /** 抽屉当前展示的设置行（按 `manageOp` 找到那一行） */
  const manageRow = useMemo(
    () => matrixRows.find((r) => r.operation === manageOp) ?? null,
    [matrixRows, manageOp],
  )

  /** 该逻辑工序在价目表里的**全部行**（与后端 `matchingCells` 同域：按行键取，不看关联键） */
  const manageOpCells = useMemo(
    () => (manageRow ? [...manageRow.cells.values()] : []),
    [manageRow],
  )

  /**
   * **删除路径的唯一判据 = 与后端护栏③同一把尺（按名字）**（issue #4692，治本）。
   *
   * <p>后端护栏③（{@code ProductionOperationCommandService.matchingCells} + {@code applicable}）
   * 按**名字**判「这道工序还挂不挂在价目表上」—— 它**从不看**行的
   * {@code variant_operation_id}。前端若拿 {@code variant_operation_id} 当「有没有行 / 能不能删 /
   * 走哪条删除路径」的判据，就会出现**前端说能删、后端 422 拦下**：用户第 3 次报的删除死路
   * （格按名字命中、关联键却是 {@code null}）就是这么来的。</p>
   *
   * <p>判据 = **本行（行键 = 逻辑工序名）里仍是「做」的行**。它与后端**同向**（按名字），且是后端
   * 命中集的**超集**（后端按 {@code variantNameOf} 解析出的变体，其逻辑名必然是行键；解析不出时
   * 后端也不命中）⇒ **fail-safe**：前端**绝不会**在后端会拦时选「普通删除」，最坏只是多走一次
   * 能过的 detach-and-delete（后端摘 0 格）。</p>
   *
   * <p>{@code variant_operation_id} 仍用于**展示**（「这些行未关联到本工序」是有价值的信息），
   * 但**不得**再作为「能否删 / 走哪条路」的判据（issue #4692 的硬要求）。</p>
   *
   * <p>⚠️ **2026-09-21（#4951 去部位化彻底版，判据面缩小、不放宽）**：`applicable` 已从
   * {@link OperationPosition} 退场且**恒 `TRUE`** ⇒「仍是『做』的行」= **本行的全部价目行**
   * （后端护栏③仍在，判据是 {@code matchingCells} × {@code applicable}）。前端口径随之从
   * 「过滤出做着的行」收敛为「有几行就有几个 blocker」—— 原先被排除的 {@code applicable=false}
   * 行在新形态下**不存在**；若真出现也一律走 detach（对后端护栏③而言是**安全方向**）。</p>
   */
  const opDeleteBlockerCells = useMemo(() => manageOpCells, [manageOpCells])

  /**
   * 该逻辑工序的设置行（issue #4674 C：`variant_operation_id` 关联不上时**回退按逻辑名**
   * 认同一道工序，并打上 `unlinked` 标记 ⇒ 界面**显式提示**，不再静默空）。
   *
   * <p>⚠️ 回退**只在读面没给 id 时**生效（`null` / 缺键）：行的 `variant_operation_id` **非空**就说明
   * 它指向**那道**工序 —— 指向别的工序的行**不属于**这一行，不得按名字硬拽进来
   * （那不是「对齐口径」，是**把别人那一行算到这道工序头上**）。</p>
   */
  const variantsOf = useCallback(
    (row: MatrixRow): VariantView[] => {
      const byId = new Map<string, VariantView>()
      // 「按逻辑名认出来的那道工序」—— 与后端 `variantNameOf` 的裸名兜底同一份口径
      const byName = fallbackOpByName.get(row.operation)?.op ?? null
      // 「属于本工序」的库行 id 集合（同名多行都算 —— 见 `idsByName`）
      const ownIds = idsByName.get(row.operation) ?? null
      row.cells.forEach((c) => {
        const explicit = c.variant_operation_id
        // 回退：读面给不出变体 id ⇒ 按**逻辑名**在工序库里认这道工序
        const fallback = explicit ? null : byName
        const id = explicit ?? (fallback ? String(fallback.id) : null)
        if (!id) return
        // 两把尺不一致的**两种形态**都算「未关联到本工序」：
        // ① 行没给 id（读面查不到变体）⇒ 靠逻辑名认出来；
        // ② 行给了 id 但它**不是**按逻辑名认出来的那道工序 ⇒ 该行指向别处（既有的悬空引用形态）。
        const entry = libraryById.get(id)
        // 形态②：行指向的那道工序**在库里查得到**，却**不属于**本逻辑名下的任何一行
        // ⇒ 这一行属于**别的**工序（只如实报出、不给写面：对它 PUT/DELETE 就是改另一道工序）。
        const foreign = !!explicit && entry != null && ownIds != null && !ownIds.has(String(explicit))
        // 「未关联到本工序」= 靠逻辑名认出来的（没给 id）+ 指向别处的
        const unlinked = !explicit || foreign
        if (byId.has(id)) return
        byId.set(id, {
          id,
          group: (fallback?.group ?? c.group) ?? null,
          unit: (fallback?.unit ?? c.unit) ?? null,
          scope: fallback?.scope === 'set' || c.scope === 'set' ? 'set' : 'position',
          is_must_finish: fallback ? !!fallback.is_must_finish : !!c.is_must_finish,
          source: entry?.source ?? fallback?.source ?? null,
          unlinked,
          foreign,
        })
      })
      return [...byId.values()]
    },
    [fallbackOpByName, idsByName, libraryById],
  )

  const manageVariants = useMemo(() => (manageRow ? variantsOf(manageRow) : []), [manageRow, variantsOf])
  /**
   * 抽屉里**有**设置行、但其中有格**没关联到本工序**（issue #4674 C）—— 两种形态都算：
   * ① 格没给 `variant_operation_id`（读面查不到变体）⇒ 按逻辑名认出来；
   * ② 格给了 id 但**指向别处**（`foreign`）。
   * 两把尺不一致时**显式提示**（改前是静默按变体 id 找不到 ⇒ 那几格在抽屉里根本不出现）。
   */
  const manageUnlinked = useMemo(() => manageVariants.filter((v) => v.unlinked), [manageVariants])
  /**
   * 抽屉层「停用 / 删除」**作用于哪一行**（issue #4947 统一口径）= **抽屉当前展示的那一行**。
   *
   * <p>判据 = 抽屉里**第一个非 `foreign` 变体**对应的工序库行（`libraryById.get(v.id)`）：
   * `foreign` 的行是「价目行指向别处」的形态（它的写面本就不该给 —— 对它 PUT/DELETE 就是改另一道工序），
   * 而**价目读面指到的那一行**才是用户在抽屉里看见、也以为自己在操作的那道工序。</p>
   *
   * <p>⚠️ 回退只在**读面没给 id / 库里查不到那一行**时生效：按**逻辑名取首行**（`manageOpEntry.op`）。
   * 同名多行（`布三边` / `纱三边` 归一后同名）时它与读面指到的行**不是同一行** —— 改前 footer
   * 就是拿那把尺寻址 ⇒ 「看见 A、动的是 B」（issue #4947 的实质修复）。</p>
   */
  const manageTargetOp = useMemo(() => {
    const v = manageVariants.find((x) => !x.foreign)
    return (v ? libraryById.get(v.id) ?? null : null) ?? manageOpEntry?.op ?? null
  }, [manageVariants, libraryById, manageOpEntry])
  /**
   * 删除二次确认弹框的目标（issue #4617）—— 弹框必须写清**删的是哪一条**：
   * 就地展开的确认在长表格里既易误点、又看不清删的是哪一行（用户裁定的病根）。
   * 目标从当前渲染的那份列表里取（取不到 ⇒ 弹框不渲染，**不猜**）。
   */
  const deleteRuleTarget = useMemo(
    () => rules.find((r) => r.id === confirmDeleteRuleId) ?? null,
    [rules, confirmDeleteRuleId],
  )
  /**
   * 抽屉**层**删除二次确认的目标（issue #4674 A；**issue #4947 统一口径**）：
   * 目标是**抽屉当前展示的那一行**（见 `manageTargetOp`），与矩阵格是否关联得上**无关**
   * ⇒ 「行在 · 抽屉空」时照样有删除入口（改前只有「关闭」）。
   *
   * <p>⚠️ issue #4947 改前这里按**逻辑名的首行**（`fallbackOpByName`）寻址 —— 同名多行
   * （`布三边` / `纱三边`）时会删掉**另一行**（footer 说 A、读面指 B）。
   * `candidates`（同名库行数）照旧如实报出，让「删的是哪一行」可解释。</p>
   */
  const deleteOpByNameTarget = useMemo(
    () =>
      confirmDeleteOpByName && manageTargetOp
        ? { op: manageTargetOp, candidates: manageOpEntry?.candidates ?? 1 }
        : null,
    [confirmDeleteOpByName, manageTargetOp, manageOpEntry],
  )
  /**
   * 抽屉层删除弹框要如实报出的行（issue #4674）：**按行键取全部行**（与后端 `matchingCells` 同域）
   * —— 关联不上的行**也在内**（后端护栏③照样拦它们）。`applicable=false` 的行单独标出，
   * 因为那几行**不拦**（#4665 C 的判据）。
   */
  const deleteOpByNameCells = useMemo(
    () => (deleteOpByNameTarget ? manageOpCells : []),
    [deleteOpByNameTarget, manageOpCells],
  )

  // ────────────────────────── 就绪度（先后依赖显性化） ──────────────────────────

  const operationsReady = (catalog?.total ?? 0) > 0
  const routeList = useMemo(() => routings?.routings ?? [], [routings])
  const emptyShells = useMemo(
    () => routeList.filter((r) => (r.mainline ?? []).length === 0),
    [routeList],
  )
  /**
   * **两条基础路线**（issue #4677 = 设计 §6 修法 B；源自 #4670 ②）：开租种子的**恰两条**基础路线
   * —— `窗帘工序路线（默认）`（`is_default=TRUE`）+ `布料工序路线`（`positions=['布料']`）。
   *
   * ⚠️ 名字与后端**逐字同源**（`ProductionSeedTemplateService` 的 `ROUTE_TEMPLATE_NAME_DEFAULT` /
   * `FABRIC_ROUTE_TEMPLATE_NAME_DEFAULT`）—— 判据是**「缺哪条」**，所以必须点名，不能只数条数
   * （数条数会把「窗帘路线 + 一条商家自建路线」判成齐 —— 用户实测踩到的形态）。
   */
  const BASE_ROUTE_NAMES = ['窗帘工序路线（默认）', '布料工序路线']
  const missingBaseRoutes = useMemo(
    () => BASE_ROUTE_NAMES.filter((n) => !routeList.some((r) => r.name === n)),
    [routeList],
  )
  /**
   * 就绪度②的判据（issue #4677）：**两条基础路线是否齐** ∧ **没有空壳路线**。
   * 改前 = `routeList.length > 0 && emptyShells.length === 0`（**只数条数** ⇒ 缺布料路线照样「已完成」）。
   */
  const routingsReady = missingBaseRoutes.length === 0 && emptyShells.length === 0
  const defaults = useMemo(() => routeList.filter((r) => r.is_default), [routeList])

  // ────────────────────────── 适用条件（挂在工序身上；issue #4650 阶段 1） ──────────────────────────

  /**
   * 当前抽屉那道工序的**适用条件** —— 归属判据 = `production_route_rules.operation`（**逻辑工序名**，
   * 与矩阵行键同源）。一条规则只属于**它目标的那道工序**：独立表搬走之后，「哪些条件属于谁」
   * 由这个过滤唯一决定（不再有第二处归属口径）。
   */
  const manageConditions = useMemo(
    () => (manageOp ? rules.filter((r) => r.operation === manageOp) : []),
    [rules, manageOp],
  )

  /**
   * 「插在哪道之后」的**默认值**（用户裁定：锚点要给默认值，**别让商家猜**）。
   *
   * 两段口径，先真值后常识：
   * ① 该工序**现有**插入条件用的锚点（= 今天 `routing.py` 种子里这道工序的锚点，
   *    如 `上车布` 在`韩褶`下插在`韩褶`后）—— 有就直接沿用，商家不用重新想一遍；
   * ② 没有现成条件 ⇒ 用**默认主线里它的前一道工序**（插在它前面那道之后 = 保持它现在的位置）；
   * ③ 都不成立（工序不在主线上）⇒ 空 = 追加到末尾（与后端 `after_operation` 缺省同义）。
   */
  const anchorDefaultFor = (operation: string) => {
    const seeded = rules.find(
      (r) => r.operation === operation && r.action !== 'remove' && (r.after_operation ?? '') !== '',
    )
    if (seeded) return seeded.after_operation as string
    const mainline = routeList.find((r) => r.is_default)?.mainline ?? []
    const idx = mainline.indexOf(operation)
    return idx > 0 ? mainline[idx - 1] : ''
  }

  const routingsHint =
    missingBaseRoutes.length > 0
      ? `缺 ${missingBaseRoutes.length} 条基础路线：${missingBaseRoutes.join(' / ')} —— ` +
        '这两条是窗帘单与布料单各自的主线，缺了对应形态的订单就没有工序可走。' +
        '用下方「补套行业模板」补齐（已存在的条目自动跳过）。'
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
        // 必完 = **矩阵**口径（issue #4622 补口②；与主表行尾同一份聚合）
        must_finish: matrixMustFinish.get(name) ?? null,
        resolved: !!lib,
        // 存在性 = **矩阵里的逻辑工序名**（issue #4622 补口①；不再并上按变体名索引的工序库键）
        missing: !matrixOps.has(name),
      }
    },
    [libraryByName, matrixMustFinish, matrixOps],
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

  /** 新建路线：只问名字 → 建壳后**立刻进入主线编辑**（消灭「建壳了但没排」的静默态） */
  const createRoute = async () => {
    const name = newRoute.name.trim()
    if (!name) {
      toast.error('请填写路线名称')
      return
    }
    setBusy(true)
    try {
      // issue #4886：**不再传 `positions`**（省略字段，而不是传空数组 —— 空数组会被读成
      // 「不适用任何范围」，语义不同）。路线的适用范围由配套后端决定。
      const res = await productionApi.createRouting({ name })
      const created = res.data?.data as Routing | undefined
      toast.success(`已新建路线「${name}」，请把工序排进主线`)
      setNewRouteOpen(false)
      setNewRoute({ name: '' })
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

  /** 打开「新增」对话框：每次都回到默认类型「工序」，并清掉上一次的失败理由 */
  const openCreateOperation = () => {
    setNewKind('operation')
    setNewOptionReasons([])
    setNewOpReasons([])
    setNewOpOpen(true)
  }

  /**
   * 新增**工序**（`POST /operations`）。
   *
   * <p>⚠️ issue #4886：请求体**不再带 `positions`**（「适用部位」已随旧配置面退场）——
   * 新工序如何进价目表由配套后端负责（本页这一批不再有这个概念）。
   * ⚠️ **跨包依赖（如实登记）**：配套后端未上线前，不带 `positions` ⇒ 后端只写工序库、
   * 不建价目行 ⇒ 新工序在「工艺项」表里看不到（#4614 那个病根会短期复发）。</p>
   *
   * <p>本地预检只拦「拦得住就不打扰后端」的那几条（名称/单价），**语义护栏一律以后端为准**
   * （前端不发明第二份口径）⇒ 失败理由**就地**逐条展示，**不刷新、不改页面数据**。</p>
   */
  const createOperation = async () => {
    const name = newOp.name.trim()
    const price = Number(newOp.unit_price)
    const reasons: string[] = []
    if (!name) reasons.push('请填写工序名称')
    if (newOp.unit_price.trim() === '' || Number.isNaN(price)) {
      reasons.push('请输入有效单价（元/件·米·折）')
    }
    if (reasons.length > 0) {
      setNewOpReasons(reasons)
      return
    }
    setNewOpReasons([])
    setBusy(true)
    try {
      await productionApi.createOperation({
        name,
        group_name: newOp.group_name.trim() || undefined,
        unit: newOp.unit.trim() || undefined,
        unit_price: price,
      })
      toast.success(`已新增工序「${name}」`)
      setNewOpOpen(false)
      setNewOp({ name: '', group_name: '', unit: '', unit_price: '' })
      await load()
    } catch (e) {
      console.error(e)
      if (!isErrorToastShown(e)) toast.error('新增工序失败')
    } finally {
      setBusy(false)
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
    if (reasons.length > 0) {
      setNewOptionReasons(reasons)
      return
    }
    // 可选键**留空就不发**（`after_operation?`）—— 不拿 `null` 冒充「没填」；
    // `priority` 不再由界面提供（issue #4650 阶段 1）⇒ 省略 = 后端默认顺序（与今天留空同义）。
    const payload: RouteRuleCreateParams = {
      trigger_value: trigger,
      operation: newOption.operation,
      customer_unit_price: Number(rawPrice),
    }
    if (newOption.after_operation) payload.after_operation = newOption.after_operation
    setBusy(true)
    setNewOptionReasons([])
    try {
      await productionApi.createOptionRule(payload)
      toast.success('特殊选项已新增')
      setNewOpOpen(false)
      setNewOption({ trigger_value: '', customer_unit_price: '', operation: '', after_operation: '' })
      await load()
    } catch (e) {
      console.error(e)
      setNewOptionReasons(optionPriceGuardReasons(e))
      if (!isErrorToastShown(e)) toast.error('新增特殊选项失败')
    } finally {
      setBusy(false)
    }
  }

  /**
   * 给**当前抽屉那道工序**加一条适用条件（issue #4650 阶段 1）。
   *
   * 用户裁定：「**我要求移除条件工序规则**，这个概念我都难以理解，用户如何去理解？」⇒ 商家只回答
   * **两件事**（{@link conditionDraft}）：什么时候 + 做还是不做；目标工序 = 抽屉那道工序，
   * 「插在哪道之后」在「做」时给**可选项 + 默认值**（{@link anchorDefaultFor}）。
   *
   * 落库**复用现有写面** `POST /route-rules`（**严禁**新造第二套写面；本阶段零迁移、行为不变）。
   * 本地只做「拦得住就不打扰后端」的最小预检；**语义护栏**一律以后端为准
   * （取值是否在词表里、锚点是否在工序库）⇒ 失败时逐条理由**就地**展示，
   * **不刷新、不改页面数据**（静默写回 = 商家以为加上了、订单侧其实没生效）。
   */
  const createCondition = async () => {
    if (!manageOp) return
    const reasons: string[] = []
    const trigger = conditionDraft.trigger_value.trim()
    if (!trigger) {
      reasons.push(
        conditionDraft.trigger_kind === 'craft'
          ? '请选择什么时候生效：工艺必须从列表里选（手输一个不在列表里的名字 = 这条条件永远不命中）'
          : conditionDraft.trigger_kind === 'processing_item'
            ? '请选择什么时候生效：加工项必须从列表里选（触发键 = 订单里的加工项名，精确相等）'
            : '请选择什么时候生效：特殊选项必须从列表里选（选项名是订单里的键，错一个字就查不到）',
      )
    }
    if (reasons.length > 0) {
      setConditionReasons(reasons)
      return
    }
    // 可选键**留空就不发**（`after_operation?`）—— 不拿 `null` 冒充「没填」；
    // `priority` 不再由界面提供 ⇒ 省略 = 后端默认顺序（与今天留空同义）。
    const payload: RouteRuleCreateParams = {
      trigger_kind: conditionDraft.trigger_kind,
      trigger_value: trigger,
      action: conditionDraft.action,
      operation: manageOp,
    }
    if (conditionDraft.action === 'insert' && conditionDraft.after_operation) {
      payload.after_operation = conditionDraft.after_operation
    }
    setBusy(true)
    setConditionReasons([])
    try {
      await productionApi.createOptionRule(payload)
      toast.success('条件已添加')
      setConditionFormOpen(false)
      await load()
    } catch (e) {
      console.error(e)
      setConditionReasons(optionPriceGuardReasons(e))
      if (!isErrorToastShown(e)) toast.error('添加条件失败')
    } finally {
      setBusy(false)
    }
  }

  /** 展开「添加条件」表单：每次回到默认（工艺 / 做 / 锚点取默认值），并清掉上一次的失败理由 */
  const openConditionForm = () => {
    setConditionDraft({
      trigger_kind: 'craft',
      trigger_value: '',
      action: 'insert',
      after_operation: manageOp ? anchorDefaultFor(manageOp) : '',
    })
    setConditionReasons([])
    setConditionFormOpen(true)
  }

  /** 「什么时候」的种类切换 ⇒ 取值换来源（工艺/加工项/特殊选项各自一份词表）+ 清空已选值 */
  const switchConditionKind = (kind: RouteRuleTriggerKind) => {
    setConditionDraft((d) => ({ ...d, trigger_kind: kind, trigger_value: '' }))
    setConditionReasons([])
  }

  /** 关闭抽屉 ⇒ 一并收摊「添加条件」表单（不把半截草稿留给下一道工序） */
  const closeManage = () => {
    if (variantBusy) return
    setManageOp(null)
    setConditionFormOpen(false)
    setConditionReasons([])
    setConfirmDeleteOpByName(null)
    setOpLevelReasons(null)
  }

  /**
   * 打开某道工序的「管理▸」抽屉（issue #4677：**两个分区共用**同一个入口 —— 工序层与打包发货层
   * 的行都调它）。抽摊上一轮的删除确认/理由，避免把上一道工序的中间态带进来。
   */
  const openManageFor = (operation: string) => {
    setManageOp(operation)
    setEditingVariantId(null)
    setConfirmDeleteOpByName(null)
    setVariantReasons(null)
    setOpLevelReasons(null)
  }

  // ────────────────────────── 矩阵格写面（issue #4588；契约 #4587 ②） ──────────────────────────

  /**
   * 就地改价的**编辑键** = 逻辑工序名（issue #4886：一道工序一个价 ⇒ 键里不再有第二维）。
   */
  const cellKeyOf = (operation: string) => operation

  /**
   * 价目写面统一出口（契约 #4587 ② 是**部分更新** ⇒ body 只带变了的那个键）。
   * 失败 ⇒ 理由**逐条**就地展示在该行，且**不**收摊、**不**刷新
   * （静默写回 = 商家以为改了、取价侧其实没改）。
   */
  const submitCell = async (
    key: string,
    id: string | null | undefined,
    payload: OperationPositionUpdateParams,
  ) => {
    if (!id) {
      // 契约保证每行都有 `id`；真缺了就说清楚，不静默失败
      setCellReasons({ key, items: ['这一行缺少行标识，无法保存 —— 请点右上「刷新」重试'] })
      return
    }
    setCellBusy(true)
    setCellReasons(null)
    try {
      await productionApi.updateOperationPosition(id, payload)
      toast.success(payload.unit_price == null ? '已改回未定价' : '计件单价已更新')
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
   * 保存**计件单价（给工人）**。空输入 = **改回未定价**（发 `null`，≠ 0 元）。
   * 本地只拦「送出去也必被拒」的形态（非数值 / 负数 / 三位小数）—— 语义护栏以后端为准
   * （后端一次报全 `error.details`，前端不发明第二份口径）。
   */
  const saveCellPrice = (cell: OperationPosition) => {
    const key = cellKeyOf(cell.operation)
    const raw = cellDraft.trim()
    if (raw !== '' && !/^\d+(\.\d{1,2})?$/.test(raw)) {
      setCellReasons({ key, items: ['计件单价必须是 ≥ 0 且最多两位小数的数字（要表示「还没定价」请清空）'] })
      return
    }
    void submitCell(key, cell.id, { unit_price: raw === '' ? null : Number(raw) })
  }

  const cancelCellEdit = () => {
    setCellEditing(null)
    setCellDraft('')
    setCellReasons(null)
  }

  // ────────────────────────── 「管理▸」抽屉：工序设置维护面（issue #4588；#4622 换主标识） ──────────────────────────

  /** 抽屉写面统一出口（既有 `PUT /operations/{id}`；部分更新 ⇒ 只带变了的字段） */
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

  // ────────────── 抽屉**层**的工序入口（issue #4674：与矩阵格是否关联得上无关） ──────────────

  /**
   * 打开抽屉层的删除二次确认。目标 = **抽屉当前展示的那一行**（issue #4947 统一口径：
   * `manageTargetOp`，即价目读面指到的那道变体所对应的库行；查不到才回落按逻辑名的首行）。
   * 查不到库行 ⇒ 就地报出**为什么**（不静默、不假装可删）—— 那种情况下没有可寻址的工序行，
   * 删除必然打不中对象（这正是「先看清楚再动手」）。
   */
  const openDeleteOpByName = () => {
    if (!manageOp) return
    if (!manageTargetOp) {
      setOpLevelReasons([
        `「${manageOp}」在工序库里查不到对应的工序行，无法删除 —— 请点右上「刷新」重试；` +
          '若仍查不到，它可能已被别的会话删除',
      ])
      return
    }
    setConfirmDeleteOpByName(manageOp)
    setOpLevelReasons(null)
  }

  /**
   * 删除工序（**抽屉层**入口：底部「删除」与正文「删除这道工序」**共用这一个函数**，issue #4674 A）。
   *
   * <p><b>路径判据 = {@link opDeleteBlockerCells}（与后端护栏③同一把尺：按名字，issue #4692）</b>：
   * 本行还有「做」的格 ⇒ 走 #4671 的 **detach-and-delete**（后端**同一事务**里先把这些格设为不做、
   * 级联软删矩阵行、再软删工序 —— 这条**能过**护栏③）；一格都没挂（或都已是「不做」）⇒ 才走普通软删。</p>
   *
   * <p>⚠️ 改前这里**一律**走普通删除，而「有没有格」是按 {@code variant_operation_id} 判的 ⇒ 用户那个
   * 形态（格按名字命中、关联键为 {@code null}）必然被后端护栏③ 422 拦下 = **第 3 次「仍然不能删除」**。
   * 路径选择从此**不再看** {@code variant_operation_id}。</p>
   *
   * <p>⚠️ **护栏①主线 / ②规则不放宽**：两条路都被后端照旧拦（主线涉及车间顺序，必须人工确认）⇒
   * 失败理由**逐条**就地展示、弹框不收摊、页面不刷新（不留半完成态）。</p>
   */
  const removeOpByName = async (op: CatalogOperation) => {
    setVariantBusy(true)
    setOpLevelReasons(null)
    try {
      if (opDeleteBlockerCells.length > 0) {
        // 走能过护栏③的那条路（#4671 的端点）：一次请求、后端一次事务
        await productionApi.deleteOperation(String(op.id), { detachPositions: true })
        toast.success(`已设为不做并删除工序「${op.name}」`)
      } else {
        await productionApi.deleteOperation(String(op.id))
        toast.success(`已删除工序「${op.name}」`)
      }
      setConfirmDeleteOpByName(null)
      await load()
    } catch (e) {
      setOpLevelReasons(routingAdminGuardReasons(e))
      if (!isErrorToastShown(e)) toast.error('删除失败')
    } finally {
      setVariantBusy(false)
    }
  }

  /**
   * 停用工序（既有 `PUT /operations/{id}` 的 `status`，与逐行「停用」同一写面）。
   * 与删除同样**不依赖**矩阵格 ⇒ 抽屉里任何形态下都有一条可走的路。
   */
  const disableOpByName = async (op: CatalogOperation) => {
    setVariantBusy(true)
    setOpLevelReasons(null)
    try {
      await productionApi.updateOperation(op.id, { status: 'inactive' })
      toast.success(`已停用工序「${op.name}」`)
      await load()
    } catch (e) {
      setOpLevelReasons(routingAdminGuardReasons(e))
      if (!isErrorToastShown(e)) toast.error('停用失败')
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
            工序（各自多少钱）→ 工艺路线（订单按哪条主线走）。路线是计件工资与完工判定的唯一输入
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
                /* issue #4677 = 设计 §6 修法 B：判据从「**数条数**」改成「**两条基础路线是否齐**」
                   并**点名**缺的是哪条（改前 `工艺路线 2 条` 就显示「已完成」——
                   缺 `布料工序路线` 时布料单一条工序都走不了，界面上却看不出来）。 */
                label={
                  missingBaseRoutes.length > 0
                    ? `基础路线 ${BASE_ROUTE_NAMES.length - missingBaseRoutes.length}/${BASE_ROUTE_NAMES.length} 条 · 缺 ${missingBaseRoutes.join(' / ')}`
                    : `基础路线 ${BASE_ROUTE_NAMES.length}/${BASE_ROUTE_NAMES.length} 条 · 齐`
                }
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

          {/* ── 行业模板（**缺失即显示**，issue #4677 = 设计 §6 修法 A；源自 #4670 ①）──
              改前判据 = `!operationsReady`（**只在工序库为空时**显示）⇒ 工序库非空但**缺基础路线**
              的租户看不到这个入口（「补套」是幂等的：已存在的条目自动跳过）⇒ 入口改成
              「**工序库为空 ∨ 两条基础路线不齐**」（缺失即显示，幂等）。
              ⚠️ **不并上「有空壳路线」**：空壳路线不是种子能补的（那是商家自建路线的半成品，
              补套不会碰它）⇒ 把它算进来会给出一个点了也没用的入口。 */}
          {(!operationsReady || missingBaseRoutes.length > 0) && (
            <div className="rounded-lg border border-amber-200 bg-amber-50/60 p-5" data-testid="seed-templates">
              <div className="mb-3 flex flex-wrap items-baseline gap-2">
                <h2 className="text-base font-medium text-neutral-900">
                  {operationsReady ? '缺基础路线 · 补套行业模板' : '工序库为空 · 补套行业模板'}
                </h2>
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

          {/* ── 两个 tab：工序管理 / 算料配置 ──
              issue #4886 用户裁定：原「工艺项」与「工艺路线」**合并为一屏**（路线就放在原【打包发货】的位置），
              选项卡从三项收敛为两项；合并仍是**一个菜单入口、一个页面**，tab 切换**不丢状态**。 */}
          <div className="flex items-center gap-1 border-b border-neutral-200" role="tablist" data-testid="process-config-tabs">
            {([
              { key: 'process', label: '工序管理' },
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
            {/* ══════════ tab「工艺项」：**一屏一张表**（行 = 逻辑工序 · 一道工序一个价） ══════════
                issue #4588 = 母单 #4586 包 B（契约 #4587）。原「主区只读矩阵 + 折叠次区工序库明细」两张
                平铺表已合并成这一张：明细面（分组 / 单位 / 作用域 / 必完 / 停用 / 删除）收进行尾
                「管理▸」抽屉 —— 同一个概念**只有一个载体**，改价只有一个入口（矩阵格）。
                例外（用户改判）：**必完** 是完工门槛，除抽屉里的维护面外，行尾还要有**只读标记**
                （issue #4610）；**作用域**仍只在抽屉里。 */}
            {tab === 'process' && (
              <div className="space-y-4" data-testid="craft-operations-panel">
                <section className="rounded-lg border border-neutral-200 bg-white p-5" data-testid="operation-price-matrix">
                  <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                    <div className="flex flex-wrap items-baseline gap-2">
                      <h2 className="text-base font-medium text-neutral-900">工艺项 · 计件单价（给工人）</h2>
                      <span className="text-sm text-neutral-500">
                        <span data-testid="operation-price-matrix-total">{operationsRows.length}</span> 道工序 ·
                        一道工序一个价
                      </span>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <span
                        className={cn(
                          'rounded px-2 py-0.5 text-xs',
                          unpricedCount > 0 ? 'bg-amber-50 text-amber-700' : 'bg-neutral-100 text-neutral-500',
                        )}
                        data-testid="matrix-unpriced-count"
                        title="这些工序还没定价 —— 报工按未定价处理，请补价"
                      >
                        未定价 {unpricedCount} 项
                      </span>
                      {/* 孤儿提示（issue #4614；issue #4886 起**只读**）：工序库里有、但没有任何价目行
                          ⇒ 下表看不到它、也没法定价。旧的「接入」弹窗已随旧配置面退场 ⇒
                          这里**不摆死路按钮**，只如实报数（出路见 title）。 */}
                      {orphanOps.length > 0 && (
                        <span
                          data-testid="matrix-orphan-hint"
                          className="rounded bg-amber-50 px-2 py-0.5 text-xs text-amber-700"
                          title="这些工序在工序库里有、但没有任何价目行 —— 下表看不到它们，也没法定价。点右上「刷新」重试；若仍缺失，用下方「补套行业模板」补齐，或用「新增工序」重建。"
                        >
                          有 {orphanOps.length} 道工序还没有价目行（下表看不到）
                        </span>
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
                    <strong>一道工序一个价</strong>（issue #4886）；
                    <span className="text-amber-700">未定价</span> = 还没定价（≠ ¥0.00；真 0 元照显示 ¥0.00）。
                    收顾客的那笔钱不在这里 —— 基础工序在「加工项组合费用」，特殊选项在每道工序的
                    <strong>「适用条件」</strong>里（按套计价）。
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
                       {operationsRows.length === 0
                         ? '暂无可定价的工序 —— 点右上「新增工序」建一道，再回这里定价'
                         : '没有匹配的工序，换个关键词试试'}
                     </p>
                   ) : (
                     <div className="overflow-x-auto">
                       <table className="w-full text-sm" data-testid="operation-workshop-table">
                         <thead>
                           <tr className="border-b border-neutral-200 text-left text-xs text-neutral-500">
                             <th className="py-2 pr-4 font-medium">工序</th>
                             <th className="py-2 pr-4 font-medium">单价</th>
                             <th className="py-2 pr-4 font-medium">分组 · 单位 · 必完 · 操作</th>
                           </tr>
                         </thead>
                         {/* **按车间分组可折叠**（issue #4677 = 设计 §4.1 元素②）：一个分组一个
                             `<tbody>`（不是嵌套表）—— 折叠只收起这一组的行，表头不动。
                             组名 = 行尾元数据的 `group` 经**行业正名**（`裁剪` ⇒ 裁剪（裁床）…）；
                             ⚠️ 界面上一律**不出现「槽位」**这类我们发明的词（用户裁定）。 */}
                         {visibleWorkshopGroups.map((g) => (
                           <tbody
                             key={g.group || '__ungrouped__'}
                             data-testid={`matrix-workshop-${g.group || '未分组'}`}
                           >
                             <tr className="border-b border-neutral-100 bg-neutral-50/60">
                               <td colSpan={3} className="py-1.5 pr-4">
                                 <button
                                   type="button"
                                   aria-expanded={openWorkshops[g.group || '__ungrouped__'] !== false}
                                   data-testid={`matrix-workshop-toggle-${g.group || '未分组'}`}
                                   onClick={() =>
                                     setOpenWorkshops((prev) => ({
                                       ...prev,
                                       [g.group || '__ungrouped__']: prev[g.group || '__ungrouped__'] === false,
                                     }))
                                   }
                                   className="flex items-center gap-1.5 text-xs font-medium text-neutral-700"
                                 >
                                   <span aria-hidden>
                                     {openWorkshops[g.group || '__ungrouped__'] === false ? '▸' : '▾'}
                                   </span>
                                   {workshopTitle(g.group, g.rows.length)}
                                 </button>
                               </td>
                             </tr>
                             {openWorkshops[g.group || '__ungrouped__'] !== false &&
                               g.rows.map((row) => {
                                 const groups = distinctMeta(row, (c) => c.group)
                                 const units = distinctMeta(row, (c) => c.unit)
                                 const inconsistent = metaInconsistent(groups) || metaInconsistent(units)
                                 const mustFinish = mustFinishOf(row.cell)
                                 const key = cellKeyOf(row.operation)
                                 return (
                                   <tr
                                     key={row.operation}
                                     className="border-b border-neutral-100 last:border-0"
                                     data-testid={`matrix-row-${row.operation}`}
                                     data-operation={row.operation}
                                   >
                                     <td className="py-2.5 pr-4 align-top">
                                       {/* 行首只显示**逻辑工序名**（issue #4622 / #4886）：行 = 一道工序，
                                           变体名（`布三边` / `logo条-布`）不出现在任何界面位置。 */}
                                       <div className="text-neutral-900">{row.operation}</div>
                                     </td>
                                     {/* **一道工序一个价**（issue #4886）：就地可改的**唯一**单价 —— 未定价照显示
                                         「未定价」，**绝不**回落 ¥0.00，也**绝不**回落工序库单价（历史 P0 #4696）。 */}
                                     <td className="py-2.5 pr-4 align-top">
                                       <OperationPriceCell
                                         operation={row.operation}
                                         cell={row.cell}
                                         editing={cellEditing === key}
                                         draft={cellDraft}
                                         busy={cellBusy}
                                         reasons={cellEditing === key && cellReasons?.key === key ? cellReasons.items : []}
                                         onStartEdit={() => {
                                           setCellEditing(key)
                                           setCellDraft(row.cell.unit_price == null ? '' : String(row.cell.unit_price))
                                           setCellReasons(null)
                                         }}
                                         onDraftChange={setCellDraft}
                                         onSave={() => saveCellPrice(row.cell)}
                                         onCancel={cancelCellEdit}
                                       />
                                     </td>
                                     {/* 行尾元数据 = `分组 · 单位`（作用域收进抽屉）+ **必完标记**（issue #4610：
                                         完工门槛要一眼看得见）+「管理▸」入口；不一致时逐个列出，**不静默取第一个** */}
                                     <td
                                       className="py-2.5 pr-4 align-top"
                                       data-testid={`matrix-meta-${row.operation}`}
                                       data-inconsistent={inconsistent ? 'true' : undefined}
                                       title={inconsistent ? '分组 / 单位不一致，已逐个列出' : undefined}
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
                                             title={mustFinishTitle()}
                                             >
                                             {mustFinishLabel()}
                                           </span>
                                         )}
                                         <ManageButton operation={row.operation} onOpen={openManageFor} />
                                       </div>
                                     </td>
                                   </tr>
                                 )
                               })}
                           </tbody>
                         ))}
                      </table>
                    </div>
                  )}
                </section>


              </div>
            )}

                {/* ══════════════ tab「工艺路线」：主区 = 具名路线 ══════════════
                    ⚠️ issue #4650 阶段 1（用户裁定「我要求移除条件工序规则，这个概念我都难以理解」）：
                    次区的**独立规则表**（26 条 + 「新增规则」入口 + 触发类型/动作/锚点/优先级那套术语）
                    **整块移除** —— 条件改为**挂在工序身上**（「工艺项」tab 的 `管理▸` 抽屉里一节
                    「适用条件」，人话）。后端 `GET/POST/DELETE /route-rules` 端点**保留**
                    （阶段 2 的 AI 入口与阶段 4 的承载收敛还要用），本阶段零迁移、实例化行为不变。 */}
            {tab === 'process' && (
              <div className="space-y-4">
                {/* 主区：具名路线（name + 默认徽标 + 主线 + 改名/设默认/删除） */}
                <section className="rounded-lg border border-neutral-200 bg-white p-5" data-testid="routings-list">
                  <div className="mb-3 flex items-baseline gap-2">
                    <h2 className="text-base font-medium text-neutral-900">工艺路线</h2>
                      <span className="text-sm text-neutral-500">
                        共 <span data-testid="routings-total">{routings?.total ?? 0}</span> 条 · 每条 = 一条有序主线
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
                      暂无工艺路线 —— 点右上「新建路线」建一条（一条路线 = 一条有序主线）
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
                                        {/* 必完：**矩阵**口径三态（issue #4622 补口② —— 原读工序库
                                            的 `is_must_finish`，而库按变体名索引 ⇒ 逻辑名查不到） */}
                                        {step.must_finish && (
                                          <span className="text-xs text-amber-600" title={mustFinishTitle()}>
                                            {mustFinishLabel()}
                                          </span>
                                        )}
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
                                      {/* 主线 chip 只留 序号 + 工序名 (+ 必完 / 矩阵里查不到)：
                                          **不显示任何库口径元数据**（#4583）—— 否则「显示与否」取决于
                                          逻辑名与变体名是否恰好一致，9 道 chip 两套口径（用户实测的现象）。
                                          ⚠️ 那枚「必完」本身**不是**库口径元数据：它按**矩阵聚合**
                                          （issue #4622 补口②，与主表行尾同一份三态口径）。 */}
                                      {step.must_finish && (
                                        <span
                                          className="ml-1.5 text-amber-600"
                                          data-testid={`routing-step-must-finish-${id}-${step.seq}`}
                                          title={mustFinishTitle()}
                                        >
                                          {mustFinishLabel()}
                                        </span>
                                      )}
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

      {/* 新建路线：**只问名字**（issue #4886 —— 路线适用范围已随旧配置面退场，
          `POST /routings` 不再传 `positions`） */}
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
              路线名称（如 窗帘工序路线 / 加急专线）
            </label>
            <input
              id="new-route-name"
              data-testid="routings-create-name"
              className={inputCls}
              value={newRoute.name}
              onChange={(e) => setNewRoute({ ...newRoute, name: e.target.value })}
            />
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

      {/* 「管理▸」抽屉（issue #4588）：该逻辑工序的设置维护面（issue #4622：条目主标识 = 逻辑工序名，
          变体名不上界面）。
          ⚠️ 作用域 / 必完的**维护面**在这里（用户 2026-09-19 追加裁定：「作用域 · 必完 完全不知道干嘛的，
          也可以移除」⇒ 从主表移除的是**显示**，不是语义）；**必完**的只读标记按用户 2026-09-19 改判
          回到主表行尾（issue #4610：它是完工门槛，要一眼看得见），作用域仍只在抽屉里。 */}
      <Modal
        open={manageOp !== null}
        onClose={closeManage}
        title={manageOp ? `「${manageOp}」的设置` : ''}
        width={760}
        footer={
          /* **抽屉层**的工序入口（issue #4674 A）：与**价目行是否关联得上无关** ——
           * 工序库那一行确实存在，就永远有「停用 / 删除」可走。
           * 改前这两件事**只**挂在设置**行内** ⇒ `manageVariants` 为空时只剩一句
           * 死路文案 + 一个「关闭」（正是用户截图的形态：「这条测试数据已经没有办法删除了，无删除入口」）。
           * 写面**复用既有端点**：停用 = `PUT /operations/{id}` 的 `status`；删除 = `DELETE /operations/{id}`（软删）。
           * ⚠️ 删除的**路径**由 {@link opDeleteBlockerCells} 定（与后端护栏③**同一把尺：按名字**，issue #4692）：
           * 本行还有「做」的行 ⇒ 走 #4671 的 `…/detach-and-delete`（设为不做 + 级联软删价目行 + 删除，一次事务）；
           * 一行都没挂 ⇒ 才走普通软删。**改前一律走普通删除**（按 `variant_operation_id` 判「没有行」）
           * ⇒ 用户那个形态（行按名字命中、关联键为 null）必然 422 = 第 3 次「仍然不能删除」；
           * 仍挂在主线/规则 ⇒ 后端照旧 422，理由逐条就地展示（**不放宽**）。
           * **issue #4947**：逐行那一对「停用 / 删除」与这里**逐字重复**（同一屏两个「删除」）⇒ 已整对退场，
           * 停用/删除**只**有这一处入口；这两颗按钮**作用于抽屉当前展示的那一行**（`manageTargetOp`，
           * 不是按逻辑名的首行 —— 同名多行时两者**不是同一行**）。 */
          <div className="flex w-full flex-wrap items-center gap-2">
            <Button
              size="sm"
              variant="secondary"
              data-testid="operations-manage-disable"
              disabled={variantBusy || !manageTargetOp}
              onClick={() => manageTargetOp && void disableOpByName(manageTargetOp)}
            >
              停用
            </Button>
            <Button
              size="sm"
              variant="secondary"
              data-testid="operations-manage-delete"
              disabled={variantBusy || !manageTargetOp}
              onClick={openDeleteOpByName}
            >
              删除
            </Button>
            {/* issue #4947：这句提示原本在**逐行**那一对旁边（随那一对退场）—— 信息不许丢 ⇒ 搬到「删除」旁 */}
            <span className="text-xs text-neutral-400">删除后历史报工不受影响</span>
            <Button
              variant="secondary"
              className="ml-auto"
              data-testid="operations-manage-close"
              onClick={closeManage}
            >
              关闭
            </Button>
          </div>
        }
      >
        <div className="space-y-3 text-sm" data-testid="operations-manage-drawer">
          <p className="text-neutral-600">
            这道工序的设置。分组与单位决定报工口径；<strong>作用域</strong>：按套 = 每套窗只做一次，
            按件 = 每件各做一次；<strong>必完</strong>：缺这道工序不能打包。
          </p>
          {/* 抽屉层写面被拒：逐条理由就地展示（不吞成一句「操作失败」） */}
          {opLevelReasons && (
            <ul className="space-y-0.5 text-xs text-red-600" data-testid="operations-manage-op-reasons">
              {opLevelReasons.map((r, i) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
          )}
          {/* **逐行**写面（分组 / 单位 / 作用域 / 必完）被拒：同样**逐条**就地展示（写面失败不得静默）。
              ⚠️ 与上面那条**分开**渲染 —— 触发源不同（这里是 `submitVariant`，上面是 footer 的停用 / 删除），
              合成一条会让商家误判「是谁失败了」。#4947 把逐行那一套删除弹框去重退场后，
              这里（`variant-reasons`）就是这份理由**唯一**的渲染点。 */}
          {variantReasons && (
            <ul className="space-y-0.5 text-xs text-red-600" data-testid="variant-reasons">
              {variantReasons.items.map((r, i) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
          )}
          {manageVariants.length === 0 ? (
            /* 空态**必须给出路**（issue #4674 B）：说清**为什么**空 + 给可点动作。
               改前只有一句「请核对适用性配置」—— 而页面上**没有地方**可核对（死路指引）。 */
            <div className="py-4 text-center" data-testid="operations-manage-empty">
              <p className="text-sm text-neutral-500">
                「{manageOp}」在<strong>工序库</strong>里有这一行，但它在价目表里
                {manageOpCells.length > 0 ? (
                  <>有 {manageOpCells.length} 行，而这些行<strong>都没有关联到它</strong></>
                ) : (
                  <><strong>还没有任何价目行</strong></>
                )}
                ⇒ 它现在不出现在加工单里，也没法定价。
              </p>
              <p className="mt-1 text-xs text-neutral-400">
                点下面的「删除这道工序」把它删掉；若只是读面没读全，请点右上「刷新」重试。
              </p>
              <div className="mt-3 flex flex-wrap items-center justify-center gap-2">
                <Button
                  size="sm"
                  variant="secondary"
                  data-testid="operations-manage-delete-empty"
                  disabled={variantBusy || !manageOpEntry}
                  onClick={openDeleteOpByName}
                >
                  删除这道工序
                </Button>
              </div>
            </div>
          ) : (
            <div className="divide-y divide-neutral-100">
              {/* 两把尺不一致时**显式提示**（issue #4674 C）：这些格没关联到本工序，
                  是按逻辑名认出来的 —— 不静默、不假装一致。 */}
              {manageUnlinked.length > 0 && (
                <p
                  className="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-relaxed text-amber-800"
                  data-testid="operations-manage-unlinked-hint"
                >
                  ⚠️ 这道工序有
                  <strong className="mx-1">{manageUnlinked.length}</strong>
                  条设置<strong>没有关联到它</strong>（价目行指向的不是这道工序）——
                  下面带「这些行指向的不是这道工序」标记的行**不提供设置**（改它们就是改另一道工序）；
                  点底部<strong className="mx-1">删除</strong>可直接删掉这道工序。
                </p>
              )}
              {manageVariants.map((v) => (
                <div key={v.id} className="py-3" data-testid={`variant-row-${v.id}`}>
                  <div className="flex flex-wrap items-center gap-2">
                    {/* 主标识 = **逻辑工序名**（issue #4622 / #4886）—— 变体名不上界面 */}
                    <span className="font-medium text-neutral-900">{manageOp}</span>
                    {v.source && <SourceBadge source={v.source} testId={`variant-source-${v.id}`} />}
                    {v.foreign && (
                      <span
                        className="rounded bg-amber-50 px-1.5 py-0.5 text-[11px] text-amber-700"
                        data-testid={`variant-foreign-${v.id}`}
                      >
                        这些行指向的不是这道工序
                      </span>
                    )}
                  </div>

                  {/* **指向别处**的格（issue #4674 C 的形态②）：只**如实报出**、**不给**写面 ——
                      对它 PUT/DELETE 就是改另一道工序（正是「两把尺不一致」要暴露、不是要掩盖的东西）。 */}
                  {v.foreign ? (
                    <p
                      className="mt-2 text-xs text-neutral-500"
                      data-testid={`variant-foreign-note-${v.id}`}
                    >
                      价目表里这几行关联到的是另一道工序 ⇒ 这里不提供设置；请到那道工序的抽屉里改，
                      或点底部「删除」把本工序删掉。
                    </p>
                  ) : (
                    <>
                    {/* issue #4886：「做 / 不做」开关随旧配置面一起退场（一道工序一个价 ⇒ 没有第二个维度）；
                        issue #4951 去部位化彻底版：`applicable` 已退场（恒 TRUE，写面收到即 422）
                        ⇒ 价只剩**两态**（有价 / 未定价），全部在主表的**单价格**里
                        （`operation-price-*` 的 `data-state`），这里只维护元数据。 */}

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
                          aria-label={`编辑「${manageOp}」的分组与单位`}
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
                      aria-label={`「${manageOp}」作用域`}
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
                    <span>按套 = 每套窗只做一次；按件 = 每件各做一次</span>
                  </div>

                  {/* 必完 + 一句解释 */}
                  <label className="mt-2 flex flex-wrap items-center gap-2 text-xs text-neutral-500">
                    <input
                      type="checkbox"
                      aria-label={`「${manageOp}」必完`}
                      data-testid={`variant-must-finish-${v.id}`}
                      checked={v.is_must_finish}
                      disabled={variantBusy}
                      onChange={(e) => void submitVariant(v.id, { is_must_finish: e.target.checked })}
                      className="h-4 w-4 accent-primary-600"
                    />
                    <span>必完 · 缺这道工序不能打包</span>
                  </label>

                  {/* issue #4947：逐行的「停用 / 删除」原本在这一行 —— 与抽屉 footer 那一对**逐字重复**
                      （同一屏两个「删除」就是用户报的形态）⇒ 整对退场，写面只剩 footer 那一处；
                      那句「删除后历史报工不受影响」搬到了 footer 的「删除」旁边（信息不丢）。 */}
                    </>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* ── 适用条件（issue #4650 阶段 1）：条件**挂在工序身上** —— 独立规则表已从界面移除 ──
              商家看到的只有**人话**（「工艺 = 韩褶 时插入（在「三边」之后）」），不再是
              「触发类型 / 触发值 / 限定范围 / 动作 / 目标工序 / 插入锚点 / 优先级」那七格。
              归属判据 = `production_route_rules.operation === 本工序`（逻辑工序名）。
              写面**复用现有端点**（`POST /route-rules` / `DELETE /route-rules/{id}`）—— 不新造第二套。 */}
          <div className="rounded border border-neutral-200 bg-neutral-50 p-3" data-testid="operation-conditions">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium text-neutral-900">适用条件</span>
              <span className="text-xs text-neutral-500">这道工序在什么情况下做</span>
              <Button
                size="sm"
                className="ml-auto"
                data-testid="operation-condition-add"
                onClick={openConditionForm}
              >
                <Plus className="w-3.5 h-3.5 mr-1.5" />
                添加条件
              </Button>
            </div>

            <p className="mt-1 text-xs text-neutral-400">
              条件里的名字<strong>逐字取自</strong>订单里的工艺 / 特殊选项 / 加工项（错一个字就不会命中）。
              特殊选项按<strong>套</strong>收费（元/套）；工艺与加工项不按套计价。
            </p>

            {rulesError ? (
              // 读面失败 ⇒ 就地报错：**不**把它渲染成「没有条件」（静默 = 商家以为没配过）
              <p
                className="mt-2 rounded border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-600"
                data-testid="operation-conditions-error"
              >
                {rulesError}
              </p>
            ) : manageConditions.length === 0 ? (
              <p className="mt-2 text-xs text-neutral-400" data-testid="operation-conditions-empty">
                没有额外条件 —— 无论订单选什么工艺、什么特殊选项，这道工序都按主线做。
              </p>
            ) : (
              <ul className="mt-2 divide-y divide-neutral-100">
                {manageConditions.map((rule) => (
                  <li
                    key={rule.id}
                    className="flex flex-wrap items-center gap-2 py-2"
                    data-testid={`operation-condition-${rule.id}`}
                  >
                    <span className="text-neutral-800" data-testid={`operation-condition-text-${rule.id}`}>
                      {conditionText(rule)}
                    </span>
                    {/* 特殊选项按**套**收费（元/套）：那笔对客的钱挂在**这条条件**上（issue #4567）——
                        独立表没了，但它仍是唯一载体，故跟着条件一起搬进抽屉，写面一字未动。 */}
                    {rule.trigger_kind === 'option' && (
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
                    )}
                    {/* 删除（issue #4588；契约 #4587 ④）：二次确认 → `DELETE /route-rules/{id}`；
                        失败理由**逐条**就地展示（不吞成一句「删除失败」）。 */}
                    <button
                      type="button"
                      data-testid={`operation-condition-delete-${rule.id}`}
                      onClick={() => {
                        setConfirmDeleteRuleId(rule.id)
                        setRuleDeleteReasons(null)
                      }}
                      className="ml-auto rounded px-1.5 py-1 text-xs text-neutral-500 hover:bg-neutral-100 hover:text-red-600"
                    >
                      删除
                    </button>
                  </li>
                ))}
              </ul>
            )}

            {/* 「添加条件」= **两件事**（什么时候 / 做还是不做）+ 「做」时给「插在哪道之后」的可选项与默认值 */}
            {conditionFormOpen && (
              <div className="mt-3 space-y-2 rounded border border-neutral-200 bg-white p-3" data-testid="operation-condition-form">
                <div>
                  <span className="mb-1 block text-xs text-neutral-600">什么时候</span>
                  <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="什么时候">
                    {([
                      { key: 'craft', label: '工艺' },
                      { key: 'option', label: '特殊选项' },
                      { key: 'processing_item', label: '加工项' },
                    ] as const).map((k) => (
                      <button
                        key={k.key}
                        type="button"
                        role="radio"
                        aria-checked={conditionDraft.trigger_kind === k.key}
                        data-testid={`condition-kind-${k.key}`}
                        onClick={() => switchConditionKind(k.key)}
                        className={cn(
                          'rounded-full border px-3 py-1 text-sm transition-colors',
                          conditionDraft.trigger_kind === k.key
                            ? 'border-primary-600 bg-neutral-50 font-medium text-primary-700'
                            : 'border-neutral-300 text-neutral-600 hover:bg-neutral-50',
                        )}
                      >
                        {k.label}
                      </button>
                    ))}
                  </div>
                  {/* 取值**从列表选、不手输**：手输一个词表里没有的名字 = 这条条件永远不命中 */}
                  <select
                    id="condition-value"
                    aria-label="什么时候生效"
                    data-testid="condition-value"
                    className={cn(inputCls, 'mt-2')}
                    value={conditionDraft.trigger_value}
                    onChange={(e) => setConditionDraft((d) => ({ ...d, trigger_value: e.target.value }))}
                  >
                    <option value="">
                      {conditionDraft.trigger_kind === 'craft'
                        ? '从工艺列表里选…'
                        : conditionDraft.trigger_kind === 'processing_item'
                          ? '从加工项列表里选…'
                          : '从特殊选项列表里选…'}
                    </option>
                    {(conditionDraft.trigger_kind === 'craft'
                      ? ruleOptions.crafts
                      : conditionDraft.trigger_kind === 'processing_item'
                        ? ruleOptions.processing_items
                        : optionNames
                    ).map((name) => (
                      <option key={name} value={name}>
                        {name}
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="mb-1 block text-xs text-neutral-600" htmlFor="condition-action">
                    做还是不做
                  </label>
                  <select
                    id="condition-action"
                    data-testid="condition-action"
                    className={inputCls}
                    value={conditionDraft.action}
                    onChange={(e) => {
                      const action = e.target.value as 'insert' | 'remove'
                      setConditionDraft((d) => ({ ...d, action, after_operation: '' }))
                    }}
                  >
                    <option value="insert">做（订单命中时加上这道工序）</option>
                    <option value="remove">不做（订单命中时去掉这道工序）</option>
                  </select>
                </div>

                {/* 「插在哪道之后」**只对「做」有意义**（不做没有位置）—— 切到不做时整块不渲染。
                    默认值 = 该工序现有条件的锚点，其次 = 默认主线里它的前一道（别让商家猜）。 */}
                {conditionDraft.action === 'insert' && (
                  <div>
                    <label className="mb-1 block text-xs text-neutral-600" htmlFor="condition-anchor">
                      插在哪道工序之后
                    </label>
                    <select
                      id="condition-anchor"
                      data-testid="condition-anchor"
                      className={inputCls}
                      value={conditionDraft.after_operation}
                      onChange={(e) => setConditionDraft((d) => ({ ...d, after_operation: e.target.value }))}
                    >
                      <option value="">放到最后（末尾）</option>
                      {logicalOps.map((op) => (
                        <option key={op} value={op}>
                          {op}
                        </option>
                      ))}
                    </select>
                  </div>
                )}

                {conditionReasons.length > 0 && (
                  <ul className="space-y-0.5 text-xs text-red-600" data-testid="condition-add-reasons">
                    {conditionReasons.map((r, i) => (
                      <li key={i}>{r}</li>
                    ))}
                  </ul>
                )}

                <div className="flex justify-end gap-2">
                  <Button
                    variant="secondary"
                    disabled={busy}
                    data-testid="condition-add-cancel"
                    onClick={() => setConditionFormOpen(false)}
                  >
                    取消
                  </Button>
                  <Button loading={busy} data-testid="condition-add-submit" onClick={createCondition}>
                    保存
                  </Button>
                </div>
              </div>
            )}
          </div>
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
              {([
                // ⚠️ issue #4622：placeholder 不得再示范「把前缀编进名字」的旧写法（`罗马帘-穿杆`）；
                // 工序名 = **逻辑工序名**，只写这道活本身（#4886：不再有任何前后缀勾选）。
                { key: 'name', label: '工序名称', ph: '如 罗马帘穿杆', hint: '工序名只写这道活本身（如「精裁」「三边」），不要带任何前缀或后缀' },
                { key: 'group_name', label: '分组', ph: '裁剪 / 车位 / 后道 / 其他' },
                { key: 'unit', label: '单位', ph: '米 / 套 / 件 / 个 / 折' },
              ] as { key: string; label: string; ph: string; hint?: string }[]).map((f) => (
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
                  {f.hint && (
                    <p className="mt-1 text-xs text-neutral-400" data-testid={`routings-create-op-${f.key}-hint`}>
                      {f.hint}
                    </p>
                  )}
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
                  这道选项落在哪道工序上
                </label>
                <select
                  id="new-option-operation"
                  data-testid="routings-create-option-operation"
                  className={inputCls}
                  value={newOption.operation}
                  onChange={(e) =>
                    // 选定工序 ⇒ **顺手填上**「插在哪道之后」的默认值（issue #4650：别让商家猜）
                    setNewOption({
                      ...newOption,
                      operation: e.target.value,
                      after_operation: e.target.value ? anchorDefaultFor(e.target.value) : '',
                    })
                  }
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
                  插在哪道工序之后（可选）
                </label>
                <select
                  id="new-option-after_operation"
                  data-testid="routings-create-option-after_operation"
                  className={inputCls}
                  value={newOption.after_operation}
                  onChange={(e) => setNewOption({ ...newOption, after_operation: e.target.value })}
                >
                  <option value="">放到最后（末尾）</option>
                  {logicalOps.map((op) => (
                    <option key={op} value={op}>
                      {op}
                    </option>
                  ))}
                </select>
                <p className="mt-1 text-xs text-neutral-400">
                  已按这道工序现有的位置填好默认值，通常不用改。
                </p>
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



      {/* 删除**一条适用条件**的二次确认（issue #4617 的弹框形态；issue #4650 起从工序抽屉里点）——
          内容写清「删的是哪一条」，用的是**人话**（`工艺 = 韩褶 时插入（在「三边」之后）`），
          不是「触发类型 + 触发值 + 动作 + 目标工序」那套配置术语。
          删除中禁用按钮（防重复提交）；失败理由**逐条**就地展示（不吞成一句「删除失败」）。 */}
      <Modal
        open={deleteRuleTarget !== null}
        onClose={() => !ruleBusy && setConfirmDeleteRuleId(null)}
        title="删除这条适用条件"
        footer={null}
      >
        {deleteRuleTarget && (
          <div data-testid="route-rule-delete-modal" data-rule={deleteRuleTarget.id} className="space-y-3 text-sm">
            <p className="text-neutral-600">
              将删除这条条件：<strong className="ml-1">{conditionText(deleteRuleTarget)}</strong>
            </p>
            <p className="text-neutral-500">
              删除后，订单命中这个条件时<strong>不再</strong>增删「{deleteRuleTarget.operation ?? '—'}」这道工序
              （加工单按当前主线生成）。历史加工单一字不变。
            </p>
            {ruleDeleteReasons && (
              <ul className="space-y-0.5 text-xs text-red-600" data-testid="route-rule-delete-reasons">
                {ruleDeleteReasons.items.map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ul>
            )}
            <div className="flex justify-end gap-2">
              <Button
                variant="secondary"
                disabled={ruleBusy}
                data-testid={`route-rule-delete-cancel-${deleteRuleTarget.id}`}
                onClick={() => setConfirmDeleteRuleId(null)}
              >
                取消
              </Button>
              <Button
                variant="danger"
                loading={ruleBusy}
                data-testid={`route-rule-delete-confirm-${deleteRuleTarget.id}`}
                onClick={() => void removeRule(deleteRuleTarget)}
              >
                确认删除
              </Button>
            </div>
          </div>
        )}
      </Modal>

      {/* 删除**工序**（抽屉层那处，issue #4674 A）的二次确认：目标 = **抽屉当前展示的那一行**
          （issue #4947 统一口径），**与价目行是否关联得上无关** —— 改前这里根本没有入口
          （`manageVariants` 为空 ⇒ 弹框不渲染）。
          形态与页面里其它删除弹框**同一套**（同一页面不留两套形态，issue #4617 的裁定照旧；
          #4947 起「工序删除」**只剩这一套**）；
          删的是**哪一道工序**写在第一句；价目行逐行如实报出（含**未关联**的行 —— 后端护栏③按名字照样算它们）；
          失败理由**逐条**就地展示，弹框**不收摊**（#4617 纪律）。 */}
      <Modal
        open={deleteOpByNameTarget !== null}
        onClose={() => !variantBusy && setConfirmDeleteOpByName(null)}
        title="删除工序"
        footer={null}
      >
        {deleteOpByNameTarget && (
          <div
            data-testid="operations-manage-delete-modal"
            data-operation={deleteOpByNameTarget.op.name}
            className="space-y-3 text-sm"
          >
            <p className="text-neutral-600">
              将删除工序<strong className="mx-1">「{deleteOpByNameTarget.op.name}」</strong>
              （{deleteOpByNameTarget.candidates > 1
                ? `工序库里有 ${deleteOpByNameTarget.candidates} 行同名，删除的是其中一行`
                : '工序库里的这一行'}）。
            </p>
            <p className="text-neutral-500">
              删除后它不再出现在工序库与工序单价表里，新加工单不会再生成这道工序；
              <strong>历史报工不受影响</strong>（报工按当时的工序快照）。
            </p>
            {deleteOpByNameCells.length === 0 ? (
              <p
                className="rounded border border-neutral-200 bg-neutral-50 px-3 py-2 text-neutral-600"
                data-testid="operations-manage-delete-nocells"
              >
                这道工序<strong>没有挂任何价目行</strong> ⇒ 删除不会有行需要摘。
              </p>
            ) : opDeleteBlockerCells.length > 0 ? (
              /* issue #4692：判据与后端护栏③**同一把尺（按名字）** —— 有「做」的行 ⇒ 走
               detach-and-delete（设为不做 + 级联软删价目行 + 删除，后端**一次事务**）。
               文案**说清将发生什么**（改前这里写「后端会拦下并告诉你先在哪一格设为不做」——
               而本入口**不会**被拦，那句话是改前那条走错路径留下的死路文案）。 */
              <p
                className="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-amber-800"
                data-testid="operations-manage-delete-cells"
              >
                它在价目表里共 {deleteOpByNameCells.length} 行，其中
                <strong className="mx-1">{opDeleteBlockerCells.length}</strong>
                行还是「做」。点「确认删除」：系统会把这几行<strong>设为不做</strong>，
                然后删除这道工序（一次完成，不留半成品）；
                <strong>历史报工不受影响</strong>（报工按当时的工序快照）。
              </p>
            ) : (
              <p
                className="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-amber-800"
                data-testid="operations-manage-delete-cells"
              >
                它在价目表里共 {deleteOpByNameCells.length} 行，且都已经是「不做」⇒ 删除时这些行会一起清掉；
                <strong>历史报工不受影响</strong>。
              </p>
            )}
            {opLevelReasons && (
              <ul className="space-y-0.5 text-xs text-red-600" data-testid="operations-manage-delete-reasons">
                {opLevelReasons.map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ul>
            )}
            <div className="flex justify-end gap-2">
              <Button
                variant="secondary"
                disabled={variantBusy}
                data-testid="operations-manage-delete-cancel"
                onClick={() => {
                  setConfirmDeleteOpByName(null)
                  setOpLevelReasons(null)
                }}
              >
                取消
              </Button>
              <Button
                variant="danger"
                loading={variantBusy}
                data-testid="operations-manage-delete-confirm"
                onClick={() => void removeOpByName(deleteOpByNameTarget.op)}
              >
                确认删除
              </Button>
            </div>
          </div>
        )}
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
