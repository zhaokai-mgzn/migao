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
import { toast } from 'sonner'
import { Button, Modal, NumberInput } from '@/components/ui'
import { isErrorToastShown, toastRequestError } from '@/lib/api-error'
import { cuttingHeightApi, productionApi } from '@/lib/api'
import { craftCalcConfigGuardReasons, optionPriceGuardReasons, routingAdminGuardReasons, routingGuardReasons } from '@/lib/production-guard-reasons'
import { CALC_PARAM_COPY, CALC_SCALAR_KEYS, glossaryAnchorOf, type CalcScalarKey } from '@/lib/craft-calc-glossary'
import { InlineMarkdown } from '@/lib/inline-markdown'
import { CraftCalcGlossary } from '@/components/production/CraftCalcGlossary'
import { CuttingHeightConfigPanel } from '@/components/production/CuttingHeightConfigPanel'
import { CRAFT_CALC_FORMULA_LABELS } from '@/lib/craft-calc-request'
import { cn } from '@/lib/utils'
import type {
  CatalogOperation,
  CraftCalcConfig,
  CraftCalcConfigResponse,
  OperationPosition,
  OperationPositionUpdateParams,
  OperationsCatalog,
  ProductionSource,
  ProductionOperationUpdateParams,
  RouteRule,
  RouteRuleCreateParams,
  RouteRuleTriggerKind,
  RouteRuleTriggerOptions,
  Routing,
  RoutingsResponse,
} from '@/types'
// 就绪度判据的**单一真值**（issue #6573）：本页的页内五步与跨页主线（`/settings/params` 的
// 配置主线）**都调这里** —— 同一个概念两个载体 = 同一屏两个互相矛盾的数（#5858 的实测形态）。
import {
  BASE_ROUTE_NAMES,
  judgeBaseRoutesStep,
  judgeConfigSourceStep,
  judgeDefaultRouteStep,
  judgeOperationsStep,
  missingBaseRoutesOf,
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

import ProcessConfigBoard from '@/components/production-config/ProcessConfigBoard'
/**
 * 本页 = **薄壳**：功能体已抽成 {@link ProcessConfigBoard}（企业基础设置合并页共用同一份）。
 * 路由 / URL 参数 / 行为一字未改。
 */
export default function ProcessConfigPage() {
  return (
    <Suspense fallback={null}>
      <ProcessConfigBoard />
    </Suspense>
  )
}
