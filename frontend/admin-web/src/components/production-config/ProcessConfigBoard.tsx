'use client'

import { Suspense, useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'next/navigation'
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
import { isErrorToastShown, toastRequestError } from '@/lib/api-error'
import { toast } from 'sonner'
import { Button, Modal, NumberInput } from '@/components/ui'
import { productionApi } from '@/lib/api'
import { craftCalcConfigGuardReasons } from '@/lib/production-guard-reasons'
import { CALC_PARAM_COPY, CALC_SCALAR_KEYS, glossaryAnchorOf, type CalcScalarKey } from '@/lib/craft-calc-glossary'
import { InlineMarkdown } from '@/lib/inline-markdown'
import { CraftCalcGlossary } from '@/components/production/CraftCalcGlossary'
import { CRAFT_CALC_FORMULA_LABELS } from '@/lib/craft-calc-request'
import { cn } from '@/lib/utils'
// 共享工具与展示常量（issue #6585 P1）：定义处从本文件挪到模块外**一份**，四个面板同源 import。
import {
  inputCls,
  logicalNameOf,
  money,
  SOURCE_META,
  TRIGGER_KIND_LABEL,
} from '@/components/production-config/utils'
// 功能体与三个可独立挂载的面板（issue #6585）—— 板子只传 `store`，面板只渲染
import { useCutFeature, useOperationFeature, useRoutingsFeature } from '@/components/production-config/features'
import { OperationPricePanel } from '@/components/production-config/OperationPricePanel'
import { RoutingsPanel } from '@/components/production-config/RoutingsPanel'
import { CuttingHeightPanel } from '@/components/production-config/CuttingHeightPanel'
import type {
  CatalogOperation,
  CraftCalcConfig,
  CraftCalcConfigResponse,
  OperationPosition,
  ProductionSource,
  ProductionOperationUpdateParams,
  RouteRule,
} from '@/types'
// 就绪度判据的**单一真值**（issue #6573）：本页的页内五步与跨页主线（`/settings/params` 的
// 配置主线）**都调这里** —— 同一个概念两个载体 = 同一屏两个互相矛盾的数（#5858 的实测形态）。
import {
  BASE_ROUTE_NAMES,
  judgeBaseRoutesStep,
  judgeConfigSourceStep,
  judgeDefaultRouteStep,
  judgeOperationsStep,
  type ReadinessState,
} from '@/lib/config-readiness'

/**
 * 工艺配置 /production/routings（issue #4416 合并单页；issue #4433 = 母单 #4423 的 **P3** 适配新模型）
 *
 * ## 新模型下这一页回答两个问题（**一屏一件事**，不做功能平铺）
 *
 * | tab | 它回答的问题 | 主区 | 维护面 |
 * |---|---|---|---|
 * | **工序管理**（用户裁定 2026-09-21：原「工艺项」+「工艺路线」两 tab **合并为一屏**，标签定名「工序管理」） | 「每道工序给**工人**多少钱？」+「订单按哪条主线走、什么时候插/删工序？」 | **一张表**：行 = 一道逻辑工序、**一道工序一个单价**（就地可改）；表**下同屏**是**具名路线**（默认徽标 + 主线 + 改名/设默认/删除） | 工序行尾 = `分组 · 单位` + 「管理▸」抽屉（分组 / 单位 / 停用 / 删除，以及一节**适用条件**，人话；issue #4650 阶段 1 起**不再有**独立的「条件工序规则」表） |
 *
 * ## 这一屏**没有**的两个配置项（2026-09-21 两项退场，别再按旧口径读）
 *
 * - **「作用域」（issue #4960）**：商家面不再有 `variant-scope-*` 控件，说明句也不再解释
 *   「按套 / 按件」（用户原话「作用域…现在很难理解」）。⚠️ **只删商家写面** ——
 *   DB 取值 `position` / `set` 与后端实例化口径**一字不动**（本页不读也不写这个键）。
 * - **「必完」（issue #4961）**：完工口径改为「**全部工序实例全绿**」⇒ 主表行尾标记、
 *   主线 chip 标记、抽屉勾选框、以及 `lacksMustFinish` 黄条预检**一并退场**
 *   （列头随之从 `分组 · 单位 · 必完 · 操作` 回到 `分组 · 单位 · 操作`）。
 *
 * ## 为什么这一屏不再有「部位」（issue #4886，用户裁定）
 *
 * 用户裁定「新的工艺不应该配置部位」⇒ 这一层**彻底退场**：价目**塌缩成「一道工序一个价」**
 * （配套后端改动后 `GET /operation-positions` 每个逻辑工序名**只返回一行**，未定价保留 `NULL`）。
 * ⚠️ 只从**配置这一层**退场 —— 订单行 `curtain_type` 与加工单 `position_name` **保留**
 * （加工环节仍需区分布/纱）⇒ 订单页 / 加工单页 / 报工页**不动**。
 *
 * ⚠️ **2026-09-21 / issue #4962（用户裁定「如果有一些工序只能布帘有或者纱帘有，可以在适用条件上设置」）**：
 * 上面退场的是**价目这一层**的部位（工艺不再配部位）；**「适用条件」那一层随 #4962 加回了部位维** ——
 * `production_route_rules.position`（规则级部位限定；`NULL` = 不限部位）重新参与渲染与筛选，
 * 它是「什么时候」的**第 4 档**（`trigger_kind='position'`，取值 = **部位闭词表**）。
 * 沿革（**不得删**）：#4937 曾让规则级部位一并退场（该键恒 `NULL`、前端不得据它渲染），#4962 加回。
 * ⇒ 别把本节读成「整页没有『部位』二字」。
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
 * ## 顶部「配置就绪度」= **五步体检表**（issue #5858；2026-10-01 用户附截图逐字「这个页面的向导式
 * 已经和实际功能不匹配了，重构这个向导」）
 *
 * | 步 | 名字 | 判据（与它所指的区块**同源**） | 去处 |
 * |---|---|---|---|
 * | ① | 工序与单价 | 表里有工序 ∧ **无未定价** ∧ **无孤儿工序**（`unpricedCount` / `orphanOps`） | tab 工序管理 · `operation-price-matrix` |
 * | ② | 工艺路线 | 两条基础路线齐 ∧ 无空壳（#4677） | tab 工序管理 · `routings-list` |
 * | ③ | 默认路线 | 恰一条默认（兜底终点） | tab 工序管理 · `routings-list` |
 * | ④ | 算料配置 | `source='stored'` ⇒ done / `'default'` ⇒ todo / 读失败 ⇒ unknown + 「读取失败」 | tab 算料配置 |
 * | ⑤ | 裁高配置 | 同上（#5161 的第 5 个配置域；改前四步向导**不知道它存在**） | tab 裁高配置 |
 *
 * 三条纪律：① **计数与所在区块同源**（第 ① 步用 `operationsRows`，与表头 `operation-price-matrix-total`
 * 是**同一个数** —— 改前用工序库行数，同一屏会同时出现「工序库 40 道 · 已完成」与「29 道工序」）；
 * ② **每步一个可点的 `readiness-goto-<key>`**（切 tab + 滚到锚点）—— 改前只有「下方…」「切到…tab」
 * 这类在别的 tab 上**指不着**的文案；③ 算料 / 裁高读面**首屏就发**（用户裁定），不必先点 tab 才知道
 * 配没配；读失败**不谎报**「已配」。
 *
 * ## 2026-10-01 两处收口（issue #5874 / #5875）
 *
 * **① 「补套行业模板」商家面入口整体退场**（#5874，用户逐字「我建议移除这个功能」⇒ 追问后选
 * 「商家面入口 + 后端端点一起退场，但新租户入驻时要根据模板自动开租套用」）：
 * 本页不再读 `GET /seed-templates`、不再发 `POST /seed-templates/{id}/apply`
 * （后端 `ProductionSeedTemplateController` 同批删除）⇒ 卡片、`一键套用` 按钮、二次确认弹窗、
 * `templates` 状态与两个 api 方法**全部删除**。**开租自动套用保留**
 * （`RegistrationService` → `ProductionSeedTemplateService.applyTemplate`）——
 * 新租户开箱即有工序与路线；种子异常时补救动作**落回运营**（人工重跑）。
 * ⚠️ 连带：就绪度里的指路文案不再指向该入口（缺基础路线 ⇒ 联系运营 / 手工新建路线）。
 *
 * **② 无价目行的库行「进表」**（#5875，用户附截图「界面上就只展示了 29 道，是不是页面功能 bug，
 * 根本没有 41 道展示」⇒ 选 A）：
 * 表 = **价目行 ∪ 无价目行的库行**（`matrixRows ∪ orphanRows`）⇒ 「工序库里有、价目行没有」的工序
 * **有行**（单价格 `data-state=no_row` + 「无价目行」），行尾照旧有 `管理▸`（抽屉里可停用 / 删除，
 * 复用既有写面、**不新增端点**）；`matrix-orphan-hint` 黄标**退场**（信息进表，不留第二载体）。
 * ⚠️ 三条纪律：同一逻辑名**只出一行**；**已有价目行的逻辑名不补行**（那只是未被使用的库行）；
 * `no_row` **不得**与「未定价」（`unpriced`）混用（同仓纪律「未定价 ≠ ¥0.00」）。
 * ⚠️ **定价仍不可达**（后端没有「建价目行」写面）⇒ 出路 = 停用 / 删除后用「新增工序」重建。
 *
 * ## 与旧形态的关键差异（P2b #4459 / P2c #4500 之后）
 *
 * 1. **路线 = 一条具名主线**（`{id, name, is_default, mainline}`）—— 改名**只改 `name`**
 *    （不给 `mainline` 就不动序列：改一个名字不该顺带重写计件工资的输入）。
 * 2. **行键是逻辑工序名**（`精裁` / `三边`），**不是** `production_operations.name`
 *    （那边仍是旧名 `精裁-布` / `布三边`）。本页消费每行的 3 个变体元数据键
 *    （`variant_operation_id` / `unit` / `group`）——它们由后端 `variantNameOf` 推导，
 *    前端**直接取用、不另写一份推导**；3 键全 `null` = 查不到 ⇒ **不发明元数据**（静默 = 未知）。
 *    ⚠️ issue #4960/#4961：读面**仍会**返回 `scope`（后端契约一字未动，
 *    {@link OperationPosition} 类型保留该键）、而 `is_must_finish` 已随「必完退场」从读面类型移除
 *    —— 两者在商家面都**不再是配置项**（见上节）。
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
 *   POST   /api/admin/production/route-rules              （#4650 阶段 1：**条件的唯一创建写面**，被抽屉的「添加条件」复用；#4962 起 body 可带 `position`）
 *   GET    /api/admin/production/route-rule-options        （#4616 触发值取值域：`{crafts, processing_items}`；#4962 起**新增 `positions`** = 部位闭词表）
 *   DELETE /api/admin/production/operations/{id}          （#4588 工序软删：三条护栏一次报全）
 *   DELETE /api/admin/production/route-rules/{id}         （#4588 规则软删：无硬护栏；#4650 起从抽屉里删一条条件）
 *   PUT    /api/admin/production/route-rules/{id}/customer-unit-price （#4567 特殊选项对客单价）
 *   GET    /api/admin/production/operations-catalog       POST /production/operations
 *   PUT    /api/admin/production/operations/{id}          （改分组 / 单位 / status；#4960/#4961 起本页不再发 scope / is_must_finish）
 *   —— 写端点权限 processing:manage（以拦截器/后端为准，本页不做显隐分叉）。
 *
 * 真值源：docs/curtain-production-rules.md §2 工序库 / §3 工艺路线；
 * 领域模型与裁定：docs/design/position-instance-routing-model.md（R-c 作用域 / R-f 解绑加工项）。
 */

/**
 * 工序作用域（V67，issue #4384 A1）——**取值 `position` / `set` 是后端契约，一字不动**，
 * 它与后端 `ProductionOperationCommandService` 的校验、迁移 V67 的列注释同口径。
 *
 * ⚠️ **2026-09-21 / issue #4960（用户裁定）**：商家面**不再有**这个配置项 ——
 * 原抽屉里的 `variant-scope-*` 两档控件与那句解释一并退场（用户原话
 * 「作用域…现在很难理解」＋「要么还是移除作用域，生成工序实例时，显示为 工序名+布/纱？」）。
 * ⇒ 本页**不读也不写**这个键（原 `SCOPE_META` / `SCOPE_ORDER` / `scopeOf` 随之删除）；
 * 「每樘窗只做一次」这类语义**仍是后端按 DB 值实例化时判的**，不是商家在界面上配的。
 */

/**
 * 一条条件的**人话**（issue #4650 阶段 1 —— 用户裁定「移除条件工序规则，这个概念我都难以理解」）。
 *
 * 商家看到的不是「触发类型 / 动作 / 目标工序 / 插入锚点」，而是**这道工序在什么情况下做**：
 * - `insert` + 锚点 ⇒ `工艺 = 韩褶 时插入（在「三边」之后）`；
 * - `insert` 无锚点 ⇒ `… 时插入（追加到末尾）`（**不**渲染成「在「末尾」之后」—— 那是把空值当工序名）；
 * - `remove` ⇒ `工艺 = 穿杆 时不做`（#4365 起 `四爪钩` 不再是工艺 ⇒ 例子换成仍存在的 `穿杆`，
 *   它自带两条 `remove` 规则：定型 / 复烫）；
 * - `position`（#4962 加回的部位维）⇒ `部位 = 布帘 时插入（在「三边」之后）` / `部位 = 布帘 时不做`
 *   —— 同一套形态，**只有触发维的名词不同**（既有三档的文案形态一字未动）。
 *
 * 目标工序由**所在抽屉**表达（这一段只列 `operation === 该工序` 的条件）⇒ 话里不重复工序名。
 *
 * 🔴 **部位限定要说出来（issue #4962）**：**任何**带 `position` 的规则都要把这一维说进人话 ——
 * 包括 `trigger_kind ≠ 'position'` 的行（迁移 `V108` 写回的 `craft=韩褶 + position='布帘'`、
 * 直写 API 的存量行）。**不得**因为「今天表单只给 `position` 档写这一列」就把它藏起来：
 * 藏起来 = 商家看不见「这条条件只对布帘生效」（静默信息缺口，与「规则永不生效」同族）。
 * - `trigger_kind === 'position'` ⇒ `部位 = 布帘 时插入（在「三边」之后）`（`trigger_value`
 *   与 `position` 是同一把值 ⇒ **不重复渲染两遍**）；
 * - `trigger_kind === 'craft'` 且带部位 ⇒ `部位 = 布帘、工艺 = 韩褶 时插入（…）`；
 * - `position` 为空 / `null`（= **不限部位**）⇒ **不渲染**任何部位文案（不得出现「部位 = —」假值）。
 */
const conditionText = (rule: RouteRule) => {
  const kind = TRIGGER_KIND_LABEL[rule.trigger_kind ?? ''] ?? rule.trigger_kind ?? '—'
  const value = rule.trigger_value ?? '—'
  const positionClause = rule.position ? `${TRIGGER_KIND_LABEL.position} = ${rule.position}` : ''
  // `position` 档的「什么时候」**就是**部位（`trigger_value` = `position`）⇒ 只说一遍
  const triggerClause = rule.trigger_kind === 'position' ? '' : `${kind} = ${value}`
  const when = [positionClause, triggerClause].filter(Boolean).join('、') || `${kind} = ${value}`
  if (rule.action === 'remove') return `${when} 时不做`
  return rule.after_operation
    ? `${when} 时插入（在「${rule.after_operation}」之后）`
    : `${when} 时插入（追加到末尾）`
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
          {/* issue #5218 #6：本页其余 5 处已迁 `NumberInput`，此格漏网仍是 `type="number"`
              ⇒ "0." / "6.005" 这类中间态在浏览器层就被吃掉（提示自己写着「填 0 表示真 0 元」，
              0 必须打得出来）。这里**故意不用 `NumberInput`** 而用「等效的保留原始文本」实现
              （issue #5218 要求里明确允许）——因为本格的本地预检要**拒绝**三位小数并给理由，
              而 `NumberInput` 失焦会按 `decimals` 归一化（`6.005` ⇒ `6.01`），
              正好把该拒绝的输入**静默改成合法值**（实测：改成 NumberInput 后
              「三位小数 ⇒ 不发请求」那条判据直接红）。父组件的字符串草稿本就是原文。 */}
          <input
            type="text"
            inputMode="decimal"
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

/**
 * 标量键的展示元数据 —— **单一真值** = `@/lib/craft-calc-glossary` 的 `CALC_PARAM_COPY`
 * （issue #4975）。默认值/范围一律由后端给，前端**不持有**。
 *
 * 本页原来自带一份文案，其中 `side_margin` 的 label/hint 与算料引擎**口径相反**（页面说它是
 * 「定宽买高的上下卷边合计」，引擎里它是宽方向余量）⇒ 页面成了第二份口径（issue #4940）。
 * ⇒ 改为**引用同一份**（`tests/unit/lib/craft-calc-glossary.test.ts` 逐条读源守卫）。
 * ⚠️ 用户 2026-09-21 裁定（issue #5030）后该键**整体退场** ⇒ 这一项已从键集里删除，
 * 「左右覆盖余量」不再是可配参数（宽方向没有余量）。
 */
const CALC_SCALAR_FIELDS: { key: CalcScalarKey; label: string; hint: string; impact: string; anchor: string }[] =
  CALC_SCALAR_KEYS.map((key) => ({ key, ...CALC_PARAM_COPY[key], anchor: glossaryAnchorOf(key) }))

/**
 * 兜底公式的可读文案（取值域由后端枚举给；这里只做展示映射）。
 *
 * ⚠️ **单一真值** = `@/lib/craft-calc-request` 的 `CRAFT_CALC_FORMULA_LABELS`（issue #4878 独立复核）：
 * 本页原来自带一份**逐字相同、但没有任何守卫**的副本（下单页另有一份）⇒ 改一处忘一处就**静默分叉**
 * （下单页显示「韩褶公式（褶数法）」、这里显示别的字）。⇒ 改为**直接复用同一张表**，不再各写一份。
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

/**
 * 数量口径缺口的**读面文案**（issue #6117 / #6128）。
 *
 * 🔴 **逐字取自后端** `ProductionOperationQueryService.QTY_RULE_MISSING_HINT`（写面 `qty_rule_hint`
 * 用的就是它）。为什么前端要持有一份**副本**：读面只给布尔 `qty_rule_missing`
 * （`operationView` **不带**文案键），而「不在算料目录内 ⇒ 派工应做数量按 1 计」这件事**必须写清楚**
 * （只说「缺口径」等于没说后果）。⇒ 唯一一处字面量，**只**用于读面徽标的 `title`；
 * 写面一律用**响应体里的 `qty_rule_hint`**（后端说了算），不再抄第二遍。
 * 待后端把该文案也放进读面时，本常量应随之删除（改为读面直取）。
 */
const QTY_RULE_MISSING_HINT = '该工序不在算料目录内，派工应做数量将按 1 计'

/**
 * **读面标记**：这道工序不在算料目录内（`qty_rule_missing === true`）⇒ 派工应做数量走**兜底 1**。
 *
 * 视觉语言**沿用本页既有徽标形态**（同 {@link SourceBadge}：`rounded px-1.5 py-0.5 text-[11px]`），
 * 但换 amber —— 它是**后果提示**（计件工资按 1 计），不是 provenance 那种中性标注。
 * 缺省（键缺失 / 非 `true`）⇒ **不渲染**：静默 = 未知，不得冒充已知。
 */
function QtyFallbackBadge({ testId }: { testId: string }) {
  return (
    <span
      data-testid={testId}
      title={QTY_RULE_MISSING_HINT}
      className="ml-2 rounded bg-amber-50 px-1.5 py-0.5 text-[11px] text-amber-700"
    >
      数量按 1 计
    </span>
  )
}

 // 三态类型已收敛到 `@/lib/config-readiness`（issue #6573），本页不再自带一份

/**
 * 就绪度一步（把「工序与单价 → 工艺路线 → 默认路线 → 算料 / 裁高」的先后依赖变成看得见的步骤）。
 *
 * ⚠️ `action` = **可点的去处**（issue #5858）：改前每一步只有一句 hint，写的是「下方…」「切到…tab」——
 * 路线列表在另一个 tab 时「下方」根本不是它；算料 / 裁高在别的 tab 时**没有任何可点的动作**
 * （用户原话「这个页面的向导式已经和实际功能不匹配了」）。
 */
function ReadinessStep({
  testId,
  index,
  label,
  state,
  statusText,
  hint,
  action,
}: {
  testId: string
  index: number
  label: string
  state: ReadinessState
  /** 覆盖状态词（如读面失败）—— 缺省按 state 取「已完成 / 待完成 / 读取中」 */
  statusText?: string
  hint?: string
  action?: { testId: string; onClick: () => void }
}) {
  const done = state === 'done'
  /** 未知（读面**还没回来** / 读失败）= **中性**呈现：把「没加载」显示成「没配」是误报 */
  const unknown = state === 'unknown'
  return (
    <div
      data-testid={testId}
      data-state={state}
      className={cn(
        'flex flex-col rounded border px-3 py-2',
        done
          ? 'border-emerald-200 bg-emerald-50/60'
          : unknown
            ? 'border-neutral-200 bg-neutral-50'
            : 'border-amber-200 bg-amber-50/60',
      )}
    >
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span
          className={cn(
            'font-medium',
            done ? 'text-emerald-800' : unknown ? 'text-neutral-700' : 'text-amber-900',
          )}
        >
          {index}. {label}
        </span>
        <span className={cn('text-xs', done ? 'text-emerald-700' : unknown ? 'text-neutral-500' : 'text-amber-800')}>
          {statusText ?? (done ? '已完成' : unknown ? '读取中' : '待完成')}
        </span>
      </div>
      {!done && hint && (
        <p className={cn('mt-1 text-xs', unknown ? 'text-neutral-500' : 'text-amber-800')}>{hint}</p>
      )}
      {action && (
        <button
          type="button"
          data-testid={action.testId}
          onClick={action.onClick}
          className={cn(
            'mt-2 self-start rounded border px-2 py-0.5 text-xs transition-colors',
            done
              ? 'border-emerald-300 text-emerald-800 hover:bg-emerald-50'
              : unknown
                ? 'border-neutral-300 text-neutral-600 hover:bg-neutral-100'
                : 'border-amber-300 text-amber-900 hover:bg-amber-50',
          )}
        >
          {done ? '去查看' : '去处理'}
        </button>
      )}
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
 * ⚠️ **本口径不含单价**（issue #4583 用户裁定）：单价是**计件工资**口径，属「工艺项」那一屏的事；
 * 而这里能拿到的只有**工序库单价**，真正生效的价是价目行上的价 ⇒ 显示它有误导性。
 * 且「显示与否」曾取决于「逻辑名与变体名是否恰好一致」（`外帘打卷`/`外帘装袋`/`外帘发货`
 * 只有那三处逻辑名与库口径名恰好同名时才显示，其余 6 道不显示）⇒ **统一不显示**。
 *
 * ⚠️ **「必完」标记与它的就地预检已退场**（issue #4961，用户裁定）：完工口径改为
 * 「**全部工序实例全绿**」⇒ chip 上不再有那枚琥珀色标记，{@link ProcessConfigPage} 的
 * 「一道必完工序都没有」黄条（`lacksMustFinish`）也一并删除。
 */
interface StepView {
  seq: number
  operation: string
  group?: string | null
  unit?: string | null
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
  noPriceRow,
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
  /** issue #5875：这一行在工序库里有、但**没有任何价目行** ⇒ 没有可写的 `id`，**不可定价** */
  noPriceRow?: boolean
  editing: boolean
  draft: string
  busy: boolean
  reasons: string[]
  onStartEdit: () => void
  onDraftChange: (v: string) => void
  onSave: () => void
  onCancel: () => void
}) {
  // 「无价目行」是**独立状态**（≠「未定价」）：只如实说明，**不摆一个点了会失败的改价入口**
  if (noPriceRow) {
    return (
      <span
        data-testid={`operation-price-${operation}`}
        data-state="no_row"
        title={`「${operation}」在工序库里有，但没有任何价目行（也就没法定价）。点行尾「管理▸」可停用或删除它；需要它干活请删除后用右上「新增工序」重建（新建工序会自动带上价目行）。`}
        className="text-neutral-500"
      >
        无价目行
      </span>
    )
  }
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
      title="管理这道工序的设置：分组 / 单位 / 停用 / 删除"
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
 * （issue #4622：读面也不返回它）。字段**逐字取自**读面（契约 #4587 ①）——
 * 前端**不推导**、不补默认值。
 *
 * ⚠️ **issue #4960 / #4961：`scope` 与 `is_must_finish` 不再是本抽屉的配置项** ⇒ 不进这个 view model
 * （读面上的取值仍在，只是本页不消费；口径见文件头「这一屏**没有**的两个配置项」）。
 */
interface VariantView {
  id: string
  group: string | null
  unit: string | null
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
 * 价目表的一行 = **一道逻辑工序**（issue #4886）。
 *
 * `cells` 是**单元素** Map（键 = 该行原属的 `position`），只为「按行取元数据」的既有调用点保留
 * 同形；新代码请直接用 `cell`（`positions` 已不是这一层的概念）。
 */
interface MatrixRow {
  operation: string
  /**
   * 该行的价目行；`null` = **工序库里有、价目行没有**（issue #5875 的「无价目行」行）——
   * 这类行没有可写的 `id` ⇒ **不可定价**（出路见 `OperationPriceCell` 的 `noPriceRow` 分支）。
   * ⚠️ 别把它当「未定价」：`cellState(null)` 虽然也回 `unpriced`，但两者语义不同
   * （「未定价」= 有行、`unit_price` 为空；「无价目行」= 连行都没有 —— 同仓纪律「未定价 ≠ ¥0.00」）。
   */
  cell: OperationPosition | null
  cells: Map<string, OperationPosition>
  /** 无价目行时，元数据（分组 / 单位）只能从**工序库那一行**取（读面已把 `name` 归一为逻辑名） */
  library?: CatalogOperation | null
}

/**
 * `useSearchParams` 必须包在 Suspense 里（Next 的静态预渲染期读 searchParams 要求边界；
 * 形态照 `app/(dashboard)/production/processing/page.tsx` 与 `chat/page.tsx`）——
 * 页面本体是纯客户组件，fallback 留空即可。
 *
 * 为什么需要它（2026-09-29）：下单页「参数说明」把「工艺配置 → 算料配置」做成**可点深链**
 * （`/production/routings?tab=calc`，入口常量 = `frontend/admin-web/src/lib/meters-formula-legend.ts::CRAFT_CALC_ENTRY`）
 * ⇒ 本页必须**认这个参数**，否则点进去停在第一个 tab（用户口径「点击直接跳转过去」）。
 */
/**
 * 挂载形态（issue #6580）：
 * `embedded` = 被**配置指挥台**（`/settings` 的「工艺与路线」域）挂载 —— 那种形态下：
 * ① 页头标题/副标题**不渲染**（域面板已经给了「工艺与路线」+ 一句话，重复即设计 §2 判死线第 2 条）；
 * ② 自带的「配置就绪度」卡**不渲染** —— 指挥台顶部**已有一条配置主线**，同屏两个就绪面正是
 *    用户抱怨的「散乱」（判死线第 2 条）。
 * 独立路由 `/production/routings`（薄壳）仍按 `embedded=false` 渲染**原样**，行为一字不变。
 */
export default function ProcessConfigBoard({ embedded = false }: { embedded?: boolean } = {}) {
  const searchParams = useSearchParams()
  /**
   * **两个 tab**：`process` 工序管理 / `calc` 算料配置。默认落在前者（依赖顺序上它在前）。
   *
   * <p>用户裁定（2026-09-21，附线上截图）：「【打包发货】这里的表单也直接删，把工艺路线的功能放置到
   * 这块区域，两个 tab 合并成一个」⇒ 原 `operations`（工艺项）与 `routes`（工艺路线）合为 `process`
   * 一屏：上面是**唯一**那张「一道工序一个价」表（原【打包发货】那 5 道 `scope='set'` 工序
   * **并回同一张表** —— 删掉那个独立区块**不减少任何定价入口**），原【打包发货】的位置改放
   * **工艺路线**。</p>
   */
  const [tab, setTab] = useState<'process' | 'calc' | 'cut'>(() =>
    searchParams?.get('tab') === 'calc'
      ? 'calc'
      : searchParams?.get('tab') === 'cut'
        ? 'cut'
        : 'process'
  )

  // ── 算料配置（tab「算料配置」，issue #4528 = 包 E）──
  /** 读面响应（含 `source`：`default` = 系统默认值 / `stored` = 已保存的商家配置） */
  const [calcConfig, setCalcConfig] = useState<CraftCalcConfigResponse | null>(null)
  /** 表单草稿（切 tab 不丢：state 挂在本组件上） */
  const [calcDraft, setCalcDraft] = useState<CraftCalcConfig | null>(null)
  const [calcError, setCalcError] = useState('')
  /** 保存被拒的逐条理由（**不吞**成一句「保存失败」—— 后端一次列出每一处不合法） */
  const [calcReasons, setCalcReasons] = useState<string[]>([])
  const [calcBusy, setCalcBusy] = useState(false)

  // ── 功能体（工序 / 路线 / 裁高）的**唯一一份**状态与派生视图（issue #6585）──
  // 全在 `features.ts` 里：板子用它算就绪度卡与页头按钮，区块 JSX 由三个面板渲染
  // （板子传 `store`、面板只渲染）—— 🔴 **同一块 JSX 不留两份**。
  const opFeature = useOperationFeature()
  // ⚠️ **只读面只有一份来源**（issue #6585，2026-10-09 实测修正）：`useOperationFeature()` 已经取过
  // `getRoutings` / `getOperationsCatalog` / `getOperationPositions` / `getRouteRules` /
  // `getRouteRuleOptions` 五个端点；`useRoutingsFeature` 若再自取一遍，**每个端点会发两次请求**
  // ⇒ `production-routings.test.tsx` 的 `toHaveBeenCalledTimes(1)` 当场红、且
  // `mockResolvedValueOnce` 队列被第二次请求吃掉导致后续断言超时。
  // ⇒ 传 `seed`（读它的数据、**一条请求都不发**）+ `onReload`（刷新走提供方那份稳定 `load`）。
  const rtFeature = useRoutingsFeature({ seed: opFeature, onReload: opFeature.load })
  const cutFeature = useCutFeature()
  /**
   * 整页加载 / 失败面 = 三个功能体读面的**或**（改前是板子自己那一份 `loading` / `error`）：
   * 三条读面都落地才算加载完、任一失败就算失败 —— 与搬运前的单次 `load()` 同口径。
   */
  const loading = opFeature.loading || rtFeature.loading
  const error = opFeature.error || rtFeature.error
  const load = async () => {
    // `rtFeature.load` 已委托给 `opFeature.load`（见上面的 `onReload`）⇒ 这里不再单列，避免双发
    await Promise.all([opFeature.load(), cutFeature.load()])
  }

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

  /**
   * **首屏**就读（issue #5858 用户裁定）：就绪度第 ④ 步要在一屏之内回答「算料配没配」——
   * 改前是懒加载（`tab === 'calc'` 才发请求）⇒ 首屏恒为 `unknown`「读取中」，
   * 而向导恰恰要用户**不用点进去**就知道该不该点进去。代价 = 首屏多一次轻量 GET。
   */
  useEffect(() => {
    if (calcConfig === null && calcError === '') void loadCalcConfig()
  }, [calcConfig, calcError, loadCalcConfig])


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

  /** 草稿里某个数值键的当前值（渲染用；不在这里补默认值）——
   *  issue #5198：非有限数（清空时落的是 NaN 哨兵）一律返回 null，
   *  否则 `String(NaN)` 会把输入框渲染成字面量 `NaN`，用户清都清不掉。 */
  const calcNumber = (key: CalcScalarKey): number | null => {
    const v = calcDraft?.[key]
    return typeof v === 'number' && Number.isFinite(v) ? v : null
  }

  const setCalcNumber = (key: CalcScalarKey, next: number | null) => {
    setCalcDraft((d) => (d ? { ...d, [key]: next === null ? Number.NaN : next } : d))
  }

  // ────────────────────────── 就绪度（先后依赖显性化；数据全部来自功能体） ──────────────────────────

  const { catalogError, matrixError, operationsReady, operationsRows, unpricedCount, orphanRows } = opFeature
  const { emptyShells, missingBaseRoutes, defaults } = rtFeature

  /**
   * 第 ① 步「工序与单价」——**计数与判据都与它所指的那张表同源**（同一份 `operationsRows`）。
   * 三态：读面失败 ⇒ `unknown`（**不静默降级成「0 道工序」**）；否则
   * 「表里有工序 ∧ **无未定价** ∧ **无孤儿工序**」才算 `done`。
   */
  const opsStepState: ReadinessState = judgeOperationsStep({
    readFailed: catalogError !== '' || matrixError !== '',
    total: operationsReady ? operationsRows.length : 0,
    unpriced: unpricedCount,
    orphans: orphanRows.length,
  })
  const opsStepStatus = catalogError !== '' || matrixError !== '' ? '读取失败' : undefined
  const opsStepHint =
    catalogError !== ''
      ? '工序库没读出来（≠ 没配）：点右上「刷新」重试。'
      : matrixError !== ''
        ? '价目表没读出来（≠ 没定价）：点右上「刷新」重试。'
        : !operationsReady
          ? '工序库是空的：点右上「新增工序」逐道建（新建一道会自动带上它的价目行）。'
          : operationsRows.length === 0
            ? '表里还没有工序：点右上「新增工序」建一道，再回这里定价。'
            : unpricedCount > 0
              ? `有 ${unpricedCount} 道工序还没定价：未定价 ≠ ¥0.00 —— 报工按未定价处理（等于白干），点「去处理」逐道补价。`
              : orphanRows.length > 0
                ? `有 ${orphanRows.length} 道工序没有价目行（已在表里以「无价目行」标出）：点「去处理」逐道处理 —— 停用或删除后重建（删除不影响历史报工）。`
                : ''

  /**
   * 第 ④ / ⑤ 步（算料 / 裁高）：读面在**首屏**就发起（issue #5858 用户裁定）。
   * 三态与既有纪律同口径：读失败 ⇒ `unknown` + 如实说「读取失败」（**不谎报「已配」**）；
   * `source='stored'` ⇒ `done`；`source='default'` ⇒ `todo`（缺行用系统默认，界面必须显式说出来）。
   */
  const calcStepState: ReadinessState =
    calcError !== '' || calcConfig === null ? 'unknown' : judgeConfigSourceStep(calcConfig.source)
  const calcStepStatus = calcError !== '' ? '读取失败' : calcConfig === null ? '读取中' : undefined
  const calcStepHint = calcError !== ''
    ? '算料配置没读出来（≠ 没配）：点「去处理」重试。'
    : calcConfig === null
      ? ''
      : calcConfig.source === 'stored'
        ? ''
        : '现在用的是系统默认值：「每折吃布 / 余量 / 档位倍数」直接决定用料米数（改它 = 改钱），点「去处理」按你家口径核一遍。'

  const cutStepState: ReadinessState =
    cutFeature.error !== '' || cutFeature.source === null ? 'unknown' : judgeConfigSourceStep(cutFeature.source)
  const cutStepStatus = cutFeature.error !== '' ? '读取失败' : cutFeature.source === null ? '读取中' : undefined
  const cutStepHint = cutFeature.error !== ''
    ? '裁高配置没读出来（≠ 没配）：点「去处理」重试。'
    : cutFeature.source === null
      ? ''
      : cutFeature.source === 'stored'
        ? ''
        : '现在用的是系统默认值：裁剪高度 = 成品高 + 命中的增量项（如定型 / 打孔）—— 点「去处理」按你家口径核一遍。'

  /** 第 ② 步（基础路线）的文案：点名缺哪条 + 空壳路线的后果（与 `routings-list` 同源） */
  const routingsHint =
    missingBaseRoutes.length > 0
      ? `缺 ${missingBaseRoutes.length} 条基础路线：${missingBaseRoutes.join(' / ')} —— ` +
        '这两条是窗帘单与布料单各自的主线，缺了对应形态的订单就没有工序可走。' +
        '这两条是**开租时自动生成**的种子路线（这里是异常形态）—— 请联系我们核实补齐；也可先用右上「新建路线」手工建一条顶上。'
      : emptyShells.length > 0
        ? `有 ${emptyShells.length} 条「空壳」路线（主线为空）：该路线命中后一道工序都没有，请点「编辑主线」把工序排进去。`
        : ''
  /** 第 ③ 步（默认路线）的文案：没有默认 ⇒ 兜底终点缺失（订单一张加工单也生成不了） */
  const defaultRouteHint =
    defaults.length === 0
      ? '没有默认路线：匹配不到专属路线的订单，一张加工单也生成不了。点「去处理」在路线列表里「设为默认」选一条。'
      : ''

  /**
   * 每一步的**去处**（tab + 区块锚点）：hint 里的「下方…」「切到…tab」改成**可点的按钮**
   * （issue #5858 ④）—— 指路只有在**指得着**的时候才算指路。
   */
  const READINESS_TARGETS: Record<string, { tab: 'process' | 'calc' | 'cut'; anchor: string }> = {
    operations: { tab: 'process', anchor: 'operation-price-matrix' },
    routings: { tab: 'process', anchor: 'routings-list' },
    'default-route': { tab: 'process', anchor: 'routings-list' },
    calc: { tab: 'calc', anchor: 'craft-calc-config-panel' },
    cut: { tab: 'cut', anchor: 'cutting-height-panel' },
  }
  /** 待滚动到的锚点：`setTab` 要**下一帧**才渲染出目标区块 ⇒ 用 effect 在渲染后滚（jsdom 无此 API，可选调用） */
  const [pendingAnchor, setPendingAnchor] = useState('')
  const gotoReadinessStep = (key: string) => {
    const target = READINESS_TARGETS[key]
    if (!target) return
    setTab(target.tab)
    setPendingAnchor(target.anchor)
  }
  useEffect(() => {
    if (!pendingAnchor) return
    const el = document.querySelector(`[data-testid="${pendingAnchor}"]`)
    ;(el as HTMLElement | null)?.scrollIntoView?.({ block: 'start', behavior: 'smooth' })
    setPendingAnchor('')
  }, [pendingAnchor, tab])

  return (
    <div className="p-6 space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        {!embedded && (
          <div>
            <h1 className="text-xl font-semibold text-neutral-900">工艺配置</h1>
            <p className="mt-0.5 text-sm text-neutral-500">管理工序与计件单价、工艺路线和算料口径 —— <strong>路线决定订单按哪条主线走</strong></p>
          </div>
        )}
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="secondary" size="sm" onClick={() => void load()} disabled={loading}>
            <RefreshCw className={cn('w-4 h-4 mr-1.5', loading && 'animate-spin')} />
            刷新
          </Button>
          <Button
            variant="secondary"
            size="sm"
            data-testid="routings-new-operation"
            onClick={() => opFeature.openCreateOperation()}
          >
            <Plus className="w-4 h-4 mr-1.5" />
            新增工序
          </Button>
          <Button size="sm" data-testid="routings-new-route" onClick={() => rtFeature.setNewRouteOpen(true)}>
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
          <Button size="sm" data-testid="routings-retry" onClick={() => void load()}>
            重试
          </Button>
        </div>
      )}

      {!loading && !error && (
        <>
          {/* ── 就绪度（**五步**，与实际界面一一对应；issue #5858）：
              ① 工序与单价 → ② 工艺路线 → ③ 默认路线（兜底）→ ④ 算料配置 → ⑤ 裁高配置。
              每一步的**计数与它所指的区块同源**、状态覆盖该区块的真实缺口，并给一个可点的
              「去处理」（切 tab + 滚到区块）—— 改前只有 4 步、且 hint 里的「下方…」「切到…tab」
              在别的 tab 上就是假指路（用户原话「这个页面的向导式已经和实际功能不匹配了」）。 ── */}
          {!embedded && (
          <div className="rounded-lg border border-neutral-200 bg-white p-5" data-testid="process-readiness">
            <div className="mb-3 flex flex-wrap items-baseline gap-2">
              <h2 className="text-base font-medium text-neutral-900">配置就绪度</h2>
              <span className="text-sm text-neutral-500">
                按顺序配：先有工序与单价，才能排路线；路线里要留一条默认路线（没匹配到的订单走它）；最后按你家口径核一遍算料与裁高
              </span>
            </div>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
              <ReadinessStep
                testId="readiness-step-operations"
                index={1}
                /* 计数 = 与表头 `operation-price-matrix-total` **同一份数据**（改前用工序库行数 ⇒ 同屏两个数） */
                label={`工序与单价 ${operationsRows.length} 道`}
                state={opsStepState}
                statusText={opsStepStatus}
                hint={opsStepHint}
                action={{ testId: 'readiness-goto-operations', onClick: () => gotoReadinessStep('operations') }}
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
                state={judgeBaseRoutesStep(missingBaseRoutes, emptyShells.length)}
                hint={routingsHint}
                action={{ testId: 'readiness-goto-routings', onClick: () => gotoReadinessStep('routings') }}
              />
              <ReadinessStep
                testId="readiness-step-default-route"
                index={3}
                label={`默认路线 ${defaults.length} 条`}
                state={judgeDefaultRouteStep(defaults.length)}
                hint={defaultRouteHint}
                action={{ testId: 'readiness-goto-default-route', onClick: () => gotoReadinessStep('default-route') }}
              />
              {/* 第 4 步（issue #4567 用户走查③）：算料配置 —— 读面**首屏**就发（issue #5858），
                  读到之前是 `unknown`（**中性**「读取中」），**不得**显示成 `todo`
                  （把「没加载」误报成「没配」）；读失败同样不谎报 done（`statusText` = 读取失败）。 */}
              <ReadinessStep
                testId="readiness-step-calc-config"
                index={4}
                label={calcConfig?.source === 'stored' ? '算料配置 已保存' : '算料配置 系统默认'}
                state={calcStepState}
                statusText={calcStepStatus}
                hint={calcStepHint}
                action={{ testId: 'readiness-goto-calc', onClick: () => gotoReadinessStep('calc') }}
              />
              {/* 第 5 步（issue #5858）：**裁高配置** —— #5161/#5777 新增的第 5 个配置域，
                  改前的四步向导**完全不知道它存在**（tab 里已经有了，向导里没有）。 */}
              <ReadinessStep
                testId="readiness-step-cut-config"
                index={5}
                label={cutFeature.source === 'stored' ? '裁高配置 已保存' : '裁高配置 系统默认'}
                state={cutStepState}
                statusText={cutStepStatus}
                hint={cutStepHint}
                action={{ testId: 'readiness-goto-cut', onClick: () => gotoReadinessStep('cut') }}
              />
            </div>
          </div>
          )}

                    {/* ── 两个 tab：工序管理 / 算料配置 ──
              issue #4886 用户裁定：原「工艺项」与「工艺路线」**合并为一屏**（路线就放在原【打包发货】的位置），
              选项卡从三项收敛为两项；合并仍是**一个菜单入口、一个页面**，tab 切换**不丢状态**。 */}
          <div className="flex items-center gap-1 border-b border-neutral-200" role="tablist" data-testid="process-config-tabs">
            {([
              { key: 'process', label: '工序管理' },
              { key: 'calc', label: '算料配置' },
              { key: 'cut', label: '裁高配置' },
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
                平铺表已合并成这一张：明细面（分组 / 单位 / 停用 / 删除）收进行尾「管理▸」抽屉 ——
                同一个概念**只有一个载体**，改价只有一个入口（矩阵格）。
                ⚠️ issue #4960/#4961：**作用域**与**必完**都已**整体退场**（含抽屉里的维护面）
                ⇒ 行尾只剩 `分组 · 单位` + 单价 + 「管理▸」。 */}
            {tab === 'process' && <OperationPricePanel store={opFeature} embedded hideActions />}

            {tab === 'process' && <RoutingsPanel store={rtFeature} embedded hideActions />}

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
                    这些参数决定用料米数（褶数法：每折吃布 × 褶数 + 余量）。保存后<strong>新</strong>的算料按当前配置计算，
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
                            <span className="mb-1 block text-neutral-600">
                              <InlineMarkdown text={f.label} />
                            </span>
                            {/* issue #5198：改用 NumberInput（旧形态 `value={String(v ?? '')}` 在清空时
                                渲染成字面量 `NaN`；`type="number"` 还会把 "0." 中间态吞掉） */}
                            <NumberInput
                              className={inputCls}
                              data-testid={`craft-calc-config-scalar-${f.key}`}
                              value={calcNumber(f.key)}
                              onChange={(v) => setCalcNumber(f.key, v)}
                            />
                            <span className="mt-1 block text-xs text-neutral-400">
                              <InlineMarkdown text={f.hint} />{' '}
                              {/* 参数旁锚点（issue #4975）：跳到同 tab 的「术语与口径说明」对应条目 */}
                              <a
                                href={`#${f.anchor}`}
                                className="text-primary-600 underline"
                                data-testid={`craft-calc-config-doc-${f.key}`}
                              >
                                说明
                              </a>
                            </span>
                          </label>
                        ))}
                      </div>

                      {/* 兜底公式（工艺能推导时以工艺为准，这里只是推导表缺失时的兜底） */}
                      <div>
                        <label className="mb-1 block text-neutral-600" htmlFor="craft-calc-config-formula">
                          {CALC_PARAM_COPY.default_formula.label}
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
                          韩褶 / 打孔按工艺自动推导公式；推导不适用时，用这条备用公式。
                        </span>
                      </div>

                      {/* 次区：档位与拼色系数（表格，逐行可改） */}
                      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                        <div>
                          <h3 className="mb-2 text-neutral-700">{CALC_PARAM_COPY.tiers.label}</h3>
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
                                    <NumberInput
                                      className={inputCls}
                                      data-testid={`craft-calc-config-tier-${name}-fullness`}
                                      value={
                                        typeof tier.fullness === 'number' && Number.isFinite(tier.fullness)
                                          ? tier.fullness
                                          : null
                                      }
                                      onChange={(v) =>
                                        setCalcDraft((d) =>
                                          d
                                            ? {
                                                ...d,
                                                tiers: {
                                                  ...d.tiers,
                                                  [name]: {
                                                    ...d.tiers[name],
                                                    fullness: v === null ? Number.NaN : v,
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
                          <h3 className="mb-2 text-neutral-700">{CALC_PARAM_COPY.per_fold_mixed_times.label}</h3>
                          <table className="w-full text-sm">
                            <tbody>
                              {Object.entries(calcDraft.per_fold_mixed_times ?? {}).map(([times, perFold]) => (
                                <tr key={times} className="border-b border-neutral-100">
                                  <td className="py-1.5 pr-3 text-neutral-600">拼{times}次</td>
                                  <td className="py-1.5">
                                    <NumberInput
                                      className={inputCls}
                                      data-testid={`craft-calc-config-mixed-${times}`}
                                      value={
                                        typeof perFold === 'number' && Number.isFinite(perFold)
                                          ? perFold
                                          : null
                                      }
                                      onChange={(v) =>
                                        setCalcDraft((d) =>
                                          d
                                            ? {
                                                ...d,
                                                per_fold_mixed_times: {
                                                  ...d.per_fold_mixed_times,
                                                  [times]: v === null ? Number.NaN : v,
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

                {/* 口径与术语说明（issue #4975）：与参数**同屏** —— 参数回答「我这家的口径是多少」，
                    说明回答「系统怎么判、拿哪些参数判」。区块里**不写死任何数字**（数值取自本页配置）。 */}
                {calcDraft && <CraftCalcGlossary config={calcDraft} />}
              </div>
            )}

            {/* ══════════════ tab「裁高配置」：裁剪高度口径（母单 #5161） ══════════════
                本 tab 只回答一个问题：「这一刀该多高」——`裁剪高度 = 成品高 + 命中增量项`。
                命中口径由**服务端**判（`POST …/preview`）；本版**不算不写机器**（下发归上游设计单）。 */}
            {/* ══════════════ tab「裁高配置」：裁剪高度口径（母单 #5161） ══════════════
                ⚠️ 外层包一个带 `data-testid` 的容器：就绪度第 ⑤ 步的「去处理」要滚到它
                （issue #5858）—— 面板本身是自足的，这里**不改**它的内部结构。 */}
            {tab === 'cut' && <CuttingHeightPanel store={cutFeature} embedded />}
          </div>
        </>
      )}

      {/* 【已随面板迁出 board 的弹窗】（issue #6585）：新建路线 / 改名 / 删除·设默认 / 管理抽屉 /
          新建（工序 · 特殊选项）/ 删除规则 / 删除工序 —— 全部由 `RoutingsPanel` /
          `OperationPricePanel` 自持渲染（板子只传 `store`，不再持有第二份）。 */}
    </div>
  )
}
