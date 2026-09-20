// case_ids: PG-020, PG-034, PG-053, PP-014, OR-041, UI-048
// PG-020（issue #4203 / #4204）+ PP-014（issue #4307）**合并后**的单页用户面（issue #4416），
// 本单（issue #4433 = 母单 #4423 的 P3）把它适配到**新路线模型**（P1 #4427 / P2 #4432 / P2b #4459 / P2c #4500）。
//
// 新模型下的用户面判据（#4433）：
// ① **部位价目矩阵**（tab「工艺项」主区）：`GET /operation-positions` 的格数**整份**渲染（真实规模见 issue #4529：30 逻辑工序 × 4 部位 = 120 格；本文件用自己的夹具 28 × 3 判「不过滤」这一行为）
//    **整份呈现** —— 同一道工序三个部位各自真实价与适用性；`applicable=false` 的行**不得被过滤**；
//    服务端顺序（`(operation, position)`）**不得重排**；
// ② 「**不做**」（`applicable=false`）与「**没定价**」（`applicable=true` 但 `unit_price=null`）
//    在界面上**可区分**（同 `route_source` 的「静默 = 未知」纪律）；
// ③ **具名路线**：列表显示 `name` + **默认徽标** + 适用帘种 + 主线道数；**不再**出现「部位 × 工艺」标题；
// ④ 危险操作**护栏就地展示**：删默认 ⇒ 拦；删最后一条 ⇒ 拦（后端也会 422，前端不许把理由吞成一句）；
// ⑤ **改名只改 `name`**（对话框里**不出现**工序名/主线编辑）；
// ⑥ **删除二次确认** → `DELETE` → 刷新；失败**逐条**展示理由；
// ⑦ **设为默认** → `PUT {is_default:true}`；默认行不显示该入口；**绝不**提交 `is_default:false`（后端 422）；
// ⑧ **统一规则区**（tab「工艺路线」次区）：26 条规则**不截断**，触发键**逐字取自后端**（#4389 join key 纪律）；
// ⑨ **就绪度新增「默认路线」格**：无默认 ⇒ `data-state=todo` + 后果说明；
// ⑩ **零退化**：工序库半边（分组/搜索/改价/必完/作用域/新增工序）+ 路线半边 + 两个 tab + 切 tab 不丢状态；
// ⑪ 商家页**不得**出现「信号」（issue #4453 裁定：内部机制名不入商家面）。
// ⑫ **新建路线的部位勾选与部位价目矩阵同源**（issue #4556）：包 F（#4529 / V79）落库的第 4 个部位
//    `布料` 必须**可选**、能建出 `positions:['布料']` 的路线；矩阵读面 120 格**逐值不变**（回归）；
//    不动勾选仍提交**基线三部位**（既有行为逐字不变）。
// ⑬ **跨形态勾选就地提示**（#4556 产品裁定 (a)；后端机制跟单 #4563）：同勾「`布料` + 帘种部位」⇒
//    提示「会顶掉布料专用路线 / 可能丢工序」；**只**勾 `布料`（布料专线）或只勾基线三部位 ⇒ **不**提示。
// ⑭ **用户走查三条**（issue #4567）：
//    ① 条件工序规则表加「单价（元/套）」列 —— `option` 有价 ⇒ `money()`；`null` ⇒ 「**未定价**」
//       （**不得**是 `¥0.00`：未定价 ≠ 0 元）；真 0 元 ⇒ 照显示 `¥0.00`；非 `option` ⇒ `—` + `title`；
//    ② 工艺档位**显示名**中文化（`standard` ⇒ 标准档 / `economy` ⇒ 经济档，未知键回退原键），
//       而**键**（`data-testid` / 提交的 `tiers` 键 / `label` 初值）仍是英文键；
//    ③ 就绪度补第 4 步「算料配置」（`source='stored'` ⇒ done / `'default'` ⇒ todo /
//       **读面未回来 ⇒ 中性 unknown**，不把「没加载」误报成「没配」）。
// ⑮ **特殊选项单价可改**（issue #4567 追加，用户原文「特殊选项有单价，但数据不全，新增工序也无法
//    增加特殊选项配置单价」）：`option` 行的「单价（元/套）」列给**行内编辑**（铅笔 → 输入 → 保存/
//    取消，照「工序库明细」改计件单价的既有交互）⇒ `PUT /route-rules/{id}/customer-unit-price`
//    的 body **只带** `{customer_unit_price}`；清空 = 发 `null`（**改回未定价**，≠ 0 元）；
//    失败 ⇒ 后端理由**逐条就地**展示且**不**刷新、**不**改显示；非 `option` 行**没有**编辑入口。
//    ⚠️ 两套账不互读：这里写的是**对客元/套**（`production_route_rules`），
//    「工序库明细」里那栏是**给工人的计件单价**（`production_operations.unit_price`）。
// ⑯ **「新增」对话框的类型二选一**（issue #4570，用户裁定：「只要能新增工序项就行了，并可以设置为
//    特殊选项或者工序，也支持设置单价」）：顶部 `create-kind-operation`（默认）/ `create-kind-option`
//    二选一 + 一句话把**两本账**说清（计件元/件·米·折 vs 对客元/套，互不换算）；
//    - **工序**（默认）⇒ 既有表单**一字不改**，仍走 `POST /api/admin/production/operations`（回归）；
//    - **特殊选项** ⇒ 选项名 / 单价（元/套）/ 目标工序（必填）/ 锚点 / 优先级
//      ⇒ `POST /api/admin/production/route-rules`，body **恰为**
//      `{trigger_value, operation, after_operation?, priority?, customer_unit_price}` ——
//      **不得**混入「工序」那套字段（`name`/`group_name`/`unit`/`unit_price`）；
//      目标工序下拉取值域 = **逻辑工序名**（复用部位价目矩阵的行键，与
//      `production_route_rules.operation` 逐字同源；**不新造第二份工序名清单**）；
//    - 本地最小预检（名称 / 目标工序 / 单价 / 优先级）⇒ 就地理由 + **不发请求**；
//      后端 422 ⇒ `optionPriceGuardReasons()` 把 `error.details[].message` **逐条**就地展示，
//      **不刷新、不改页面数据**（成功才关框 + 重新拉取规则列表）。
// ⑰ **工艺项合并成一屏一张表**（issue #4588 = 母单 #4586 包 B；契约 #4587）：
//    - 一屏**只有一张表**：行 = 逻辑工序（`GET /operation-positions` 的 `operation`）、列 = 部位
//      （`POSITION_DOMAIN` 基线序 + 矩阵里出现的部位自动补齐）、行尾 = `分组 · 单位` + **必完标记**
//      （issue #4610 改判，见 ㉑）+「管理▸」抽屉；
//    - **原「工序库明细」折叠区取消**（`operations-catalog*` 一律不存在）⇒ 不再有两张平铺表；
//    - 格内三态（有价 / 不做 / 未定价）**可区分**，`¥0.00` 是真价（≠「未定价」）；格内就地改价
//      ⇒ `PUT /operation-positions/{id}` body **只带** `{unit_price}`；「不做 ⇄」⇒ 只带 `{applicable}`；
//    - **「作用域」不得出现在主表**（用户 2026-09-19 追加裁定）—— 收进抽屉并用商家话解释；
//      ⚠️ **同日改判（issue #4610）**：「必完标记还是得在这里展示」（完工门槛要一眼看得见）⇒
//      主表行尾加**只读**必完标记（三态见 ㉑），维护面与作用域仍在抽屉里；
//    - 抽屉：变体列表（按 `variant_operation_id` 去重）+ 分组/单位/作用域/必完/停用/删除
//      （`DELETE /operations/{id}`，二次确认，护栏理由**就地逐条**）；
//    - 条件工序规则表加「操作」列 + 删除（`DELETE /route-rules/{id}`，二次确认）；
//    - **文案口径**（用户裁定 A）：这一屏的价一律叫「计件单价（给工人）」（报工工资 = 数量 × 计件单价），
//      **不得**出现「加工费」「对客价」—— 收顾客的那笔钱在「加工项组合费用」/「条件工序规则」。
// ⑳ **「添加工序」下拉只列逻辑工序名**（issue #4609，P0 静默丢工序的前端半边）：
//    取值域 = 部位价目矩阵的行键（`GET /operation-positions` 的 `operation`，天然逻辑名、天然去重），
//    显示 = 逻辑名 + 该行分组的公共值；`加入` 写进草稿/请求体的值 = **逻辑名**。
//    **不得**再出现 `精裁-布` / `布三边` 这类**变体名**项（它们是**库口径** 35 行，同一道逻辑工序
//    按部位重复出现 ⇒ 商家看到「35 道」，且存进主线的变体名在实例化时按逻辑名查不到 ⇒ 静默丢工序）。
//    红证：改前 `value` 是变体名（`精裁-布`）⇒ 下拉项断言红、`PUT` body 断言红。
// 反 placeholder：断言落**真实数据行**与**请求体**，不断言「页面存在」。
// ㉑ **必完标记回主表 + 必完含义提示**（issue #4610，用户裁定「必完标记还是得在这里展示」）：
//    - 行尾在 `分组 · 单位` 之后加**必完标记**（数据 = 矩阵读面每行已有的 `is_must_finish`，
//      **不新造字段 / 不另拉接口**）：① 有变体的格全部必完 ⇒ `必完`；② **只有部分部位**必完 ⇒
//      `必完（部分部位）` + `title` 列出**具体哪些部位**（不静默取第一个）；③ 都没有 ⇒ **不显示**
//      （不得发明「非必完」这类新词）；
//    - 抽屉里**必完的解释**要能回答「多部位时判谁」：`必完 · 缺这道工序不能打包（部位级：每个部位
//      都要做完）`（顶部说明与勾选框旁小字**口径一致**）；
//    - **不加限制**（用户明确）：部位级的必完开关**仍可用**（不得 disabled / 隐藏），也不新增交互。
// ㉒ **条件工序规则移除折叠、常驻展开**（issue #4613，用户原话「条件工序默认不要折叠，打开，
//    移除可折叠功能」）：页面加载后**未点任何 toggle** 规则表与说明直接可见；标题 + `共 N 条` + hint
//    保留；`route-rules-toggle` **不存在**（移除的是折叠能力，不只是「默认打开」）。
//    ⚠️ **#4650 阶段 1 改判**：上面这一条说的是**独立规则表**的折叠 —— 那张表已整块移除
//    （见 ㉗）；「常驻可见」的口径随条件迁到**工序抽屉的「适用条件」**（无 toggle）。
// ㉓ **「新增工序」入口去重**（issue #4615，用户原话「这里还有个一样的按钮，可以移除掉，保留最上面的
//    「新增」，但是要改成**新增工序**」）：入口**只在页头**（`routings-new-operation`，文案 = `新增工序`）；
//    面板内重复的 `operations-new-operation` **不存在**；矩阵空态提示指向**右上**（入口换位置后
//    不得留下「点上方…」这种死引用）。⚠️ **不动弹窗内部**（类型二选一与字段由 #4614 在飞）。
// ㉔ **「新增」对话框加「适用部位」多选**（issue #4614，用户原话「这个新增按钮，无法新增工序」）：
//    病根 = `createOperation` 只 POST `{name, group_name, unit, unit_price}`（**不带部位**），
//    后端只写工序库 ⇒ 新工序没有矩阵行 ⇒「工艺项」表（只按 `GET /operation-positions` 渲染）
//    里看不到它、也没法定价（原「工序库明细」表已随 #4588 取消）。形态裁定 = **A**：
//    - 值域 = **矩阵里出现的部位 ∪ `POSITION_DOMAIN` 基线三部位** —— 复用「新建路线」的
//      `positionOptions`（#4556 已做成「从矩阵带出」）⇒ **不写死第二份**（第 4 个部位 `布料` 自动可选）；
//    - **默认勾基线三部位**（与「新建路线」默认一致）；
//    - 一个部位都不勾 ⇒ **本地预检拦下、不发请求**，就地逐条理由（照 `newOptionReasons` 形态）；
//    - 提交 body 带 `positions`；结果 toast 报**服务端返回的真实数字**（`created_positions` /
//      `skipped_positions`），**缺结果体时显式报错，不假装成功**（照 `applyTemplate` 既有纪律）；
//    - 新增成功后 `load()` 刷新 ⇒ 该工序**立刻出现在「工艺项」表里**。
//    ⚠️ #4609 之后「主线下拉只列矩阵里的逻辑工序名」⇒ 没有矩阵行的新工序**两边都看不到**（孤儿），
//    这正是本单要治的；存量孤儿见 ㉕。
// ㉕ **存量孤儿接入**（issue #4614 范围补口）：用户实测「工艺项里看不到 `测试22`，但**路线编辑的
//    下拉**能看到，是 bug」—— 用户此前建的工序只有工序库行、没有矩阵行 ⇒ 孤儿。顶部给孤儿提示
//    （判据 = 工序库 id **不在**任何矩阵格的 `variant_operation_id` 里）+ 接入弹窗（每道勾适用部位，
//    值域与新增工序同一份）；确认 ⇒ `PUT /operations/{id}` 带 `positions`（后端**只补缺失行**，
//    不删已有行、不覆盖已定价的格）；接入后立刻出现在「工艺项」表里、且下拉也能看到它。
// ㉖ **web 面只用一套工序名：矩阵行首与抽屉都不再出现变体名**（issue #4622 = goal「web 面工序命名
//    统一」阶段 3；**只换呈现，能力不减**）：
//    - 矩阵**行首**只显示**逻辑工序名**（`精裁` / `三边`）—— 该行「哪个部位做 / 不做」由**列与格**
//      表达 ⇒ 承载变体名的行首小字（`精裁-布 / 精裁-纱`、`布三边 / 纱三边`）**整块去掉**，
//      连 `matrix-variants-*` 这个 testid 一起消失（**testid 也是界面契约的一部分**）；
//      首列表头由「工序（工人看到的）」改回「工序」（这一列从来不是工人端展示名）；
//    - 「管理▸」抽屉：标题/说明改**商家语言**（`「精裁」在各部位的设置`），条目**以「部位」为主标识**
//      —— 一个变体可能服务多个部位（`帘头` 回落复用 `布帘` 的变体）⇒ 主标识 = **它服务的部位集合**
//      （`布帘 / 帘头`），`variant_name` **不上界面**（含 `aria-label` 与删除 toast）；
//      ⚠️ **接口层同口径**：`GET /operation-positions` 的响应**已不含** `variant_name`
//      （issue #4622 补口③；契约守卫 `tests/unit_ci_workflows/test_routing_read_endpoints.py` 同步改判）；
//    - **补口①**：主线「工序是否存在」只按**矩阵里的逻辑工序名**判（原「工序库 ∪ 矩阵」并集会把
//      残留的变体名误判为「存在」，而后端按逻辑名判 ⇒ 两边口径不一致）；
//    - **补口②**：主线 chip 的「必完」按**矩阵聚合**三态（原读按变体名索引的工序库 ⇒ 逻辑名查不到
//      ⇒ 那枚标记基本显示不出来）；`lacksMustFinish` 预检口径未动（它自带 `resolved` 门禁）；
//    - **能力零变化（反向护栏）**：改分组 / 单位 / 作用域 / 必完 / 停用 / 删除**六项逐条断言仍可用**，
//      接口与 body 口径一字未动（`PUT /operations/{id}` 部分更新、`DELETE /operations/{id}` 二次确认）；
//    - 「新增工序」对话框的「工序名称」placeholder 不再示范部位后缀（`罗马帘-穿杆` ⇒ `罗马帘穿杆`）
//      + 一句「工序名不要带部位 —— 部位在下面勾选」；**不加**阻断式校验（#4614 的预检不变）；
//    - 红证（修复前实测，窄跑）：9 failed / 115 passed；实现后 124/124 绿。
// ㉗ **「条件工序规则」概念从界面消失（issue #4650 阶段 1，用户原话「**我要求移除条件工序规则**，
//    这个概念我都难以理解，用户如何去理解？我们要做到**智能化的产品**，而不是旧时代配置化的产品」）**：
//    商家界面**不再有**那张要求他填「触发类型 / 触发值 / 部位限定 / 动作 / 目标工序 / 插入锚点 /
//    优先级」的独立规则表（`route-rules*` 一族 testid 与「新增规则」入口**一律不存在**），
//    术语也不得出现在页面文本里；条件改为**挂在工序身上** —— 「工艺项」tab 的 `管理▸` 抽屉里一节
//    **「适用条件」**，一句人话（`工艺 = 韩褶 时插入（在「三边」之后）` / `工艺 = 四爪钩 时不做` /
//    无锚点 ⇒ `插入（追加到末尾）`）；归属判据 = `production_route_rules.operation === 该工序`。
//    **零迁移 + 行为不变**：后端 `GET/POST/DELETE /route-rules` 端点**保留**（阶段 2 的 AI 入口与
//    阶段 4 的承载收敛还要用），写面**复用现有端点**（**严禁**新造第二套）；页面加载**零写请求**；
//    添加只问**两件事**（什么时候 / 做还是不做），取值**从词表选、不手输**，「插在哪道之后」给
//    可选项 + **默认值**（该工序现有条件的锚点 ⇒ 默认主线里它的前一道）；特殊选项的「元/套」
//    跟着条件一起搬进抽屉（写面一字未动）；「新增 → 特殊选项」对话框**去掉优先级**、
//    锚点改叫「插在哪道工序之后」并自动填默认值。
//    - 红证（改前实测，窄跑 `-t ㉗`）：10 failed（独立表/术语仍在、抽屉里没有「适用条件」一族）
//      ⇒ 实现后 10/10 绿；全文件 132/132 绿。
// ㉘ **删除工序卡死：一键「设为不做并删除」+ 让「做/不做」看得见**（issue #4665；用户原话
//    「**无法删除，而且没有地方设置做于不做**」）：
//    - **病根（两层）**：① 做/不做开关**存在但找不到** —— 它只藏在**主表格**每行的裸 `⇄` 图标里
//      （仅 `title`/`aria-label` 提示），而商家此刻在**抽屉**里（弹框让他「先去设为不做」）⇒ 死路；
//      ② 流程本身是坏设计 —— 删除的前置（把相关格设为不做）**系统完全可以自己做**，却拆成两步给商家；
//    - **A 一键**：删除弹框给「**设为不做并删除**」（`variant-detach-and-delete-{id}`）⇒ **一次**请求
//      `DELETE /operations/{id}?detach_positions=true`（后端**同一事务**先摘格再删 + 级联软删矩阵行）
//      ⇒ **没有**「第一步成功、第二步失败」的中间态；弹框**说清将发生什么**（哪几个格 + 历史报工不受影响）；
//    - **B 看得见**：抽屉里按**部位逐格**给 `做 / 不做` 控件（`drawer-applicable-{工序}-{部位}`，
//      价并排渲染在 `drawer-price-{工序}-{部位}`）；主表格的 `⇄` 换成**有可见文字**的 `做` / `不做`
//      （同一个 `ApplicableToggle`）—— 两处**共用一份**控件，不靠 hover 才知道它是什么；
//    - **反向护栏（不得放宽）**：主线 / 规则两条对一键按钮**照样拦**（主线涉及车间顺序，必须人工确认）
//      ⇒ 被拦时理由逐条就地展示、弹框不收摊、矩阵**不被动**（一格都不摘）；
//    - 三态语义**不变**（`不做` / `未定价`（≠ ¥0.00） / `¥x.xx`）；`DELETE /operations/{id}` 不带参数时
//      行为**一字不变**（矩阵格仍是硬护栏 —— 反向证明「护栏没被放宽」）。
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

const mockGetRoutings = vi.fn()
const mockUpdateRouting = vi.fn()
const mockCreateRouting = vi.fn()
const mockDeleteRouting = vi.fn()
const mockGetOperationsCatalog = vi.fn()
const mockCreateOperation = vi.fn()
// issue #4570：新增**特殊选项**（对客元/套）—— 与 `mockCreateOperation`（计件元）是两本账
const mockCreateOptionRule = vi.fn()
const mockUpdateOperation = vi.fn()
const mockGetSeedTemplates = vi.fn()
const mockGetOperationPositions = vi.fn()
const mockGetRouteRules = vi.fn()
// issue #4616：规则创建弹窗的触发值取值域（工艺词表 + 加工项目录）
const mockGetRouteRuleOptions = vi.fn()
// issue #4588：矩阵格写面（改价 / 改做不做）+ 工序与规则的软删（契约 #4587 ②③④）
const mockUpdateOperationPosition = vi.fn()
const mockDeleteOperation = vi.fn()
const mockDeleteRouteRule = vi.fn()
// issue #4567：特殊选项**对客单价**（元/套）写面 —— 与计件单价 `mockUpdateOperation` 是两套账
const mockUpdateRuleCustomerUnitPrice = vi.fn()
// issue #4453 探针：信号映射是**研发内部机制**，商家页**不得**消费 ⇒ 它必须恒不被调用
const mockGetRouteSignals = vi.fn()
const mockApplySeedTemplate = vi.fn()
// issue #4528 = 包 E：算料配置读写（tab「算料配置」）
const mockGetCraftCalcConfig = vi.fn()
const mockUpdateCraftCalcConfig = vi.fn()

vi.mock('@/lib/api', () => ({
  productionApi: {
    getRoutings: (...a: unknown[]) => mockGetRoutings(...a),
    updateRouting: (...a: unknown[]) => mockUpdateRouting(...a),
    createRouting: (...a: unknown[]) => mockCreateRouting(...a),
    deleteRouting: (...a: unknown[]) => mockDeleteRouting(...a),
    getOperationsCatalog: (...a: unknown[]) => mockGetOperationsCatalog(...a),
    createOperation: (...a: unknown[]) => mockCreateOperation(...a),
    createOptionRule: (...a: unknown[]) => mockCreateOptionRule(...a),
    updateOperation: (...a: unknown[]) => mockUpdateOperation(...a),
    getSeedTemplates: (...a: unknown[]) => mockGetSeedTemplates(...a),
    getOperationPositions: (...a: unknown[]) => mockGetOperationPositions(...a),
    getRouteRules: (...a: unknown[]) => mockGetRouteRules(...a),
    getRouteRuleOptions: (...a: unknown[]) => mockGetRouteRuleOptions(...a),
    updateOperationPosition: (...a: unknown[]) => mockUpdateOperationPosition(...a),
    deleteOperation: (...a: unknown[]) => mockDeleteOperation(...a),
    deleteRouteRule: (...a: unknown[]) => mockDeleteRouteRule(...a),
    updateRuleCustomerUnitPrice: (...a: unknown[]) => mockUpdateRuleCustomerUnitPrice(...a),
    getRouteSignals: (...a: unknown[]) => mockGetRouteSignals(...a),
    applySeedTemplate: (...a: unknown[]) => mockApplySeedTemplate(...a),
    getCraftCalcConfig: (...a: unknown[]) => mockGetCraftCalcConfig(...a),
    updateCraftCalcConfig: (...a: unknown[]) => mockUpdateCraftCalcConfig(...a),
  },
}))

import { toast } from 'sonner'
import ProcessConfigPage from '@/app/(dashboard)/production/routings/page'

const ok = (data: unknown) => ({ data: { success: true, data } })

/** 工序库（库口径）：含 作用域 / provenance / 必完 / 首工序 —— 工艺项 tab 的次区（明细） */
const CATALOG = {
  total: 4,
  groups: [
    {
      group: '裁剪',
      operations: [
        { id: 'op-v54-01', name: '精裁-布', group: '裁剪', position: '布帘', scope: 'position', unit: '套', unit_price: 8.5, is_must_finish: true, is_start_marker: true, source: '占位待确认' },
        { id: 'op-v54-02', name: '裁剪-布', group: '裁剪', position: '布帘', scope: 'position', unit: '套', unit_price: 7, is_must_finish: false, is_start_marker: true },
      ],
    },
    {
      group: '车位',
      operations: [
        { id: 'op-v54-03', name: '韩褶-布', group: '车位', position: '布帘', scope: 'position', unit: '米', unit_price: 1.2, is_must_finish: false, is_start_marker: false },
      ],
    },
    {
      group: '后道',
      operations: [
        { id: 'op-v54-04', name: '外帘装袋', group: '后道', position: '外帘', scope: 'set', unit: '件', unit_price: 0.4, is_must_finish: true, is_start_marker: false },
      ],
    },
  ],
}

/** 查不到变体 ⇒ 契约 #4587 ① 的 6 个新键**全 null**（不是空串、不是 0） */
const NO_VARIANT = {
  variant_operation_id: null,
  unit: null,
  group: null,
  scope: null,
  is_must_finish: null,
}

/**
 * 部位价目矩阵（issue #4588 起每行带行 `id` + 变体元数据；契约 #4587 ①）。
 * **服务端顺序** = `(operation, position)`（Java 自然序：三边 < 精裁 < 车被 < 韩褶）。
 * 四态齐备 —— ① 有价 ② **不做**（applicable=false ⇒ unit_price=null）
 * ③ **没定价**（applicable=true 但 unit_price=null）④ **真 0 元**（`车被`/`布帘` = 0 ⇒ 必须显示 `¥0.00`）。
 *
 * 变体元数据三种形态齐备（判据不是「能渲染」，而是「不许静默取第一个」）：
 * - `三边`：两格变体同为 `车位 · 米` ⇒ 行尾取**公共值**；
 * - `精裁`：两格变体分组**不同**（裁剪 / 车位）⇒ 行尾必须**两个都列出**；
 * - `车被`：一格有变体（`后道 · 件 · 套级 · 必完`）⇒ 抽屉可改作用域/必完；
 * - `韩褶`：矩阵里查不到变体（6 键全 null）⇒ 行尾不发明元数据、抽屉给「没有变体」提示。
 */
const POSITIONS = [
  { id: 'pos-三边-帘头', operation: '三边', position: '帘头', unit_price: null, applicable: false, ...NO_VARIANT },
  { id: 'pos-三边-布帘', operation: '三边', position: '布帘', unit_price: 1.2, applicable: true, variant_operation_id: 'op-三边-布', unit: '米', group: '车位', scope: 'position', is_must_finish: false },
  { id: 'pos-三边-纱帘', operation: '三边', position: '纱帘', unit_price: null, applicable: true, variant_operation_id: 'op-三边-纱', unit: '米', group: '车位', scope: 'position', is_must_finish: false },
  // `帘头` 回落复用 `布帘` 的变体（真值源 `variantNameOf` 的第 2 步）—— 夹具照真形态给
  // `variant_operation_id`，否则这一格在抽屉里**不出现**（抽屉按 `variant_operation_id` 去重）。
  { id: 'pos-精裁-帘头', operation: '精裁', position: '帘头', unit_price: null, applicable: false, variant_operation_id: 'op-精裁-布', unit: '套', group: '裁剪', scope: 'position', is_must_finish: true },
  { id: 'pos-精裁-布帘', operation: '精裁', position: '布帘', unit_price: 8.5, applicable: true, variant_operation_id: 'op-精裁-布', unit: '套', group: '裁剪', scope: 'position', is_must_finish: true },
  { id: 'pos-精裁-纱帘', operation: '精裁', position: '纱帘', unit_price: 6, applicable: true, variant_operation_id: 'op-精裁-纱', unit: '套', group: '车位', scope: 'position', is_must_finish: true },
  { id: 'pos-车被-帘头', operation: '车被', position: '帘头', unit_price: null, applicable: false, ...NO_VARIANT },
  { id: 'pos-车被-布帘', operation: '车被', position: '布帘', unit_price: 0, applicable: true, variant_operation_id: 'op-车被', unit: '件', group: '后道', scope: 'set', is_must_finish: true },
  { id: 'pos-车被-纱帘', operation: '车被', position: '纱帘', unit_price: null, applicable: false, ...NO_VARIANT },
  { id: 'pos-韩褶-布帘', operation: '韩褶', position: '布帘', unit_price: 2, applicable: true, ...NO_VARIANT },
  // 部位无关工序（`外帘打卷/装袋/发货`）**也是** 30 道逻辑工序之一（真值源
  // `routing.py::OPERATION_POSITION_PRICES`）⇒ 真数据里它有矩阵格。夹具里补上这一格是**必须**的：
  // issue #4622 补口① 起「主线里的工序是否存在」按**矩阵的逻辑工序名**判，夹具缺这格会让
  // `外帘装袋` 被误报「不存在」（真数据不会 —— 这正是夹具与真值的差异）。
  { id: 'pos-外帘装袋-布帘', operation: '外帘装袋', position: '布帘', unit_price: 1.0, applicable: true, variant_operation_id: 'op-v54-04', unit: '套', group: '后道', scope: 'set', is_must_finish: true },
]

/** 规则区：工艺触发 insert（带锚点）/ 工艺触发 remove（带部位限定）/ 特殊选项触发 insert */
const RULES = [
  { id: 1, trigger_kind: 'craft', trigger_value: '韩褶', position: null, action: 'insert', operation: '韩褶', after_operation: '三边', priority: 10, status: 'active' },
  { id: 2, trigger_kind: 'craft', trigger_value: '打孔', position: '布帘', action: 'remove', operation: '熨烫', after_operation: null, priority: 20, status: 'active' },
  { id: 3, trigger_kind: 'option', trigger_value: '拼2次', position: '纱帘', action: 'insert', operation: '拼缝', after_operation: null, priority: 30, status: 'active' },
]

/**
 * 规则区**单价**夹具（issue #4567 用户走查①：「特殊选项缺乏单价，通常按套收费」）。
 * 四态齐备，且 `¥0.00` 与「未定价」**同时在场**（0 元是真价、`null` 是未定价 —— 两者不得混）：
 * ① `option` 有价 `12.5` ⇒ `¥12.50`；② `option` **未定价** `null` ⇒ 「未定价」；
 * ③ `option` 定价恰为 `0` ⇒ `¥0.00`（真 0 元，**必须**照样显示成金额）；
 * ④ 工艺变体 ⇒ `—`（工艺变体不按套计价）。
 *
 * ⚠️ issue #4650 阶段 1：价随**条件**一起搬进工序抽屉 ⇒ 四条规则的目标工序都落在同一道
 * 可在矩阵里打开抽屉的工序（`韩褶`）上，测试才能一次看全四态。
 */
const RULES_WITH_PRICE = [
  { id: 21, trigger_kind: 'option', trigger_value: '拼2次', position: '纱帘', action: 'insert', operation: '韩褶', after_operation: null, priority: 210, status: 'active', customer_unit_price: 12.5 },
  { id: 22, trigger_kind: 'option', trigger_value: '防翘扣', position: null, action: 'insert', operation: '韩褶', after_operation: '三边', priority: 220, status: 'active', customer_unit_price: null },
  { id: 23, trigger_kind: 'option', trigger_value: '免熨', position: null, action: 'insert', operation: '韩褶', after_operation: null, priority: 230, status: 'active', customer_unit_price: 0 },
  { id: 24, trigger_kind: 'craft', trigger_value: '韩褶', position: null, action: 'insert', operation: '韩褶', after_operation: '三边', priority: 10, status: 'active' },
]

/**
 * 具名路线（新结构）：① 默认 + 三帘种 + 3 道主线 ② 纱帘专线（**空主线** ⇒ 空壳）。
 * ⚠️ 主线存的是**逻辑工序名**（`精裁`/`三边`，与 V71 种子同款书写）。
 * **issue #4642 起服务端读面已把 `production_operations.name` 归一后暴露**（catalog 的 `name` = 逻辑名，
 * 库口径原名走 `library_name` 且 web 不得渲染）⇒ 前端**有了**映射，`libraryByName` 按逻辑名建键能查到
 * （`resolved` 变好）。本文件上方那份 `CATALOG` 夹具仍保留**库口径旧名**（历史夹具形态，用于回归
 * 「下拉/矩阵不按库名成行」等判据）；**新真值形态**见 ㉕-①′ 的 `LOGICAL_CATALOG`。
 * 旧形态（`curtain_type` × `craft` 展开快照）已随 P2b 退场 ⇒ 前端不得再按那个键渲染。
 */
/**
 * 规则创建弹窗的**触发值取值域**（issue #4616）：活跃工艺词表 + 活跃加工项目录。
 * ⚠️ 判据是「**从词表取、不手输**」⇒ 弹窗里必须是**下拉**，且选项逐字来自这里。
 */
const RULE_TRIGGER_OPTIONS = {
  crafts: ['韩褶', '打孔', '罗马帘'],
  processing_items: ['花边', '扣环', '拼接'],
}

const ROUTINGS = {
  total: 2,
  routings: [
    { id: 11, name: '窗帘工序路线（默认）', is_default: true, positions: ['布帘', '纱帘', '帘头'], mainline: ['精裁', '三边', '外帘装袋'], status: 'active' },
    { id: 12, name: '纱帘专线', is_default: false, positions: ['纱帘'], mainline: [], status: 'active' },
  ],
}

const TEMPLATES = [
  { templateId: 'curtain', industry: 'curtain', name: '布艺窗帘行业模板', version: 1, description: '35 道工序 + 9 条路线' },
]

/**
 * 算料引擎**默认配置**（issue #4528）：本租户没有配置行时后端返回的那一份
 * （`GET /api/admin/production/craft-calc-config` ⇒ `{source:'default', config}`）。
 *
 * ⚠️ 逐值**写死**（真值源 §8 / 包 D 既有常量）：判据不得从实现推导 —— 否则「前端抄了一份默认值」
 * 这类缺陷不会红。前端**不持有**这份常量（它只在测试里当"后端会回什么"的替身）。
 */
const ENGINE_DEFAULT_CALC_CONFIG = {
  per_fold_single: 0.25,
  per_fold_mixed_times: { '1': 0.65, '2': 1.2 },
  margin_single: 0.2,
  margin_multi: 0.3,
  min_fullness: 1.5,
  tiers: {
    standard: { fullness: 2.0, label: '标准工艺' },
    economy: { fullness: 1.8, label: '经济工艺' },
  },
  default_formula: 'pleat',
  side_margin: 0.3,
  meters_rounding_step: 0.1,
}

/** 后端护栏失败信封（逐条理由；**不**含顶层 `error_messages` —— 那个字段后端不存在） */
const CALC_GUARD_REJECTION = {
  response: {
    data: {
      success: false,
      error: {
        code: 'VALIDATION_ERROR',
        message: '算料配置有 2 处不合法，已整份拒绝',
        details: [
          { field: 'min_fullness', message: '不得低于行业红线 1.5' },
          { field: 'default_formula', message: '必须是 [pleat, fullness] 之一' },
        ],
      },
    },
  },
}

/** 后端护栏失败响应体（**真实**信封：`error.details[].message` 逐条理由 —— issue #4308「冻结补遗 ②」） */
const guardError = (reasons: string[]) => ({
  response: {
    status: 422,
    data: {
      success: false,
      error: {
        code: 'VALIDATION_ERROR',
        message: `工艺路线校验未通过：${reasons.length} 项`,
        details: reasons.map((message, i) => ({ field: `mainline[${i}]`, message })),
      },
      suggestion: '请修正后重试',
    },
  },
  message: 'Request failed with status code 422',
})

/** 渲染并切到「工艺路线」tab（路线内容在第二个 tab，默认落在「工艺项」） */
const renderOnRoutes = async () => {
  render(<ProcessConfigPage />)
  await waitFor(() => expect(screen.getByTestId('process-config-tab-routes')).toBeInTheDocument())
  await userEvent.click(screen.getByTestId('process-config-tab-routes'))
}

/** 渲染并停在「工艺项」tab（默认 tab）；等到这一屏**唯一**的表就位 */
const renderOperations = async () => {
  render(<ProcessConfigPage />)
  await waitFor(() => expect(screen.getByTestId('craft-operations-panel')).toBeInTheDocument())
  await waitFor(() => expect(screen.getByTestId('operation-price-matrix')).toBeInTheDocument())
}

/** 打开某逻辑工序的「管理▸」抽屉（变体维护面） */
const openManage = async (operation: string) => {
  await renderOperations()
  await userEvent.click(screen.getByTestId(`matrix-manage-${operation}`))
  await waitFor(() => expect(screen.getByTestId('operations-manage-drawer')).toBeInTheDocument()
  )
}

/**
 * 打开某逻辑工序的抽屉并等「适用条件」一节就位（issue #4650 阶段 1：条件**挂在工序身上**）。
 * ⚠️ 一个测试里**只能调一次** `openManage`（它会 `render` 一个新的页面实例 ⇒ 同 testid 出现两份）。
 * 需要看第二道工序时：`userEvent.click(screen.getByTestId('matrix-manage-X'))`。
 */
const openConditions = async (operation: string) => {
  await openManage(operation)
  return screen.findByTestId('operation-conditions')
}

describe('工艺配置页 /production/routings（新路线模型，issue #4433 = 母单 #4423 的 P3）', () => {
  beforeEach(() => {
    mockGetOperationsCatalog.mockReset().mockResolvedValue(ok(CATALOG))
    mockGetRoutings.mockReset().mockResolvedValue(ok(ROUTINGS))
    mockGetSeedTemplates.mockReset().mockResolvedValue(ok(TEMPLATES))
    mockGetOperationPositions.mockReset().mockResolvedValue(ok(POSITIONS))
    mockGetRouteRules.mockReset().mockResolvedValue(ok(RULES))
    mockGetRouteRuleOptions.mockReset().mockResolvedValue(ok(RULE_TRIGGER_OPTIONS))
    mockUpdateRuleCustomerUnitPrice.mockReset().mockResolvedValue(ok({ id: 21, customer_unit_price: 6 }))
    mockGetRouteSignals.mockReset()
    mockApplySeedTemplate.mockReset().mockResolvedValue(ok({ created_operations: 35, created_routings: 9, skipped: 0 }))
    mockUpdateOperation.mockReset().mockResolvedValue(ok({ id: 'op-v54-03', name: '韩褶-布', unit_price: 2.5 }))
    // issue #4588：矩阵格写面 + 软删（默认成功；各用例按需 mockRejectedValueOnce）
    mockUpdateOperationPosition.mockReset().mockResolvedValue(ok({ id: 'pos-精裁-纱帘' }))
    mockDeleteOperation.mockReset().mockResolvedValue(ok({ id: 'op-精裁-布', deleted: true }))
    mockDeleteRouteRule.mockReset().mockResolvedValue(ok({ id: 1, deleted: true }))
    mockUpdateRouting.mockReset().mockResolvedValue(ok({ id: 12 }))
    mockCreateRouting.mockReset().mockResolvedValue(ok({ id: 13, name: '罗马帘专线', is_default: false, positions: ['布帘'], mainline: [], status: 'active' }))
    mockDeleteRouting.mockReset().mockResolvedValue(ok({ id: 12 }))
    mockCreateOperation
      .mockReset()
      .mockResolvedValue(ok({ id: 'op-new', created_positions: 3, skipped_positions: 0 }))
    mockCreateOptionRule.mockReset().mockResolvedValue(ok({ id: 31 }))
    mockGetCraftCalcConfig.mockReset().mockResolvedValue(ok({ source: 'default', config: ENGINE_DEFAULT_CALC_CONFIG }))
    mockUpdateCraftCalcConfig.mockReset().mockResolvedValue(ok({ source: 'stored', config: ENGINE_DEFAULT_CALC_CONFIG }))
    vi.mocked(toast.success).mockClear()
    vi.mocked(toast.error).mockClear()
  })

  // ══════════════════ ①② 部位价目矩阵（tab「工艺项」主区） ══════════════════

  it('部位价目矩阵：84 格**整份**渲染 —— applicable=false 的行不得被过滤', async () => {
    // 真实规模：28 逻辑工序 × 3 部位 = 84 格，其中约 1/3 是 applicable=false（「不做」）
    const positions = ['布帘', '纱帘', '帘头']
    const big = Array.from({ length: 28 }, (_, i) => `工序${i + 1}`).flatMap((operation, oi) =>
      positions.map((position, pi) => ({
        operation,
        position,
        unit_price: pi === 1 ? null : oi + pi,
        applicable: pi !== 1,
      })),
    )
    mockGetOperationPositions.mockReset().mockResolvedValue(ok(big))
    render(<ProcessConfigPage />)

    await waitFor(() => expect(screen.getByTestId('operation-price-matrix')).toBeInTheDocument())
    // 28 行 × 3 列 = 84 格（注入：过滤掉 applicable=false ⇒ 格数变 56，断言红）
    expect(screen.getByTestId('operation-price-matrix-total')).toHaveTextContent('28')
    expect(screen.getByTestId('operation-price-matrix-cells')).toHaveTextContent('84')
    expect(screen.getAllByTestId(/^matrix-row-/)).toHaveLength(28)
    expect(screen.getAllByTestId(/^matrix-cell-/)).toHaveLength(84)
    // 被「不做」的那一列仍然在（不是被整列/整行滤掉）
    expect(screen.getAllByTestId(/^matrix-cell-.*-纱帘$/)).toHaveLength(28)
    expect(screen.getByTestId('matrix-cell-工序1-纱帘')).toHaveTextContent('不做')
  })

  it('部位价目矩阵：同一道工序三个部位各自显示真实价/适用性，且**服务端顺序不重排**', async () => {
    render(<ProcessConfigPage />)
    await waitFor(() => expect(screen.getByTestId('operation-price-matrix')).toBeInTheDocument())

    // 行序 = 服务端顺序（`(operation, position)` ⇒ 三边 / 精裁 / 车被 / 韩褶 / 外帘装袋）；
    // 注入：前端按字母重排 ⇒ 红
    const rows = screen.getAllByTestId(/^matrix-row-/)
    expect(rows.map((r) => r.getAttribute('data-operation'))).toEqual([
      '三边', '精裁', '车被', '韩褶', '外帘装袋',
    ])

    // 同一道「精裁」：布帘 ¥8.50 / 纱帘 ¥6.00 / 帘头 不做 —— 三个部位三份数据（不是一行一个价）
    expect(screen.getByTestId('matrix-cell-精裁-布帘')).toHaveTextContent('¥8.50')
    expect(screen.getByTestId('matrix-cell-精裁-纱帘')).toHaveTextContent('¥6.00')
    expect(screen.getByTestId('matrix-cell-精裁-帘头')).toHaveTextContent('不做')
    expect(screen.getByTestId('matrix-cell-三边-布帘')).toHaveTextContent('¥1.20')
    // 列序 = 业务口径（布帘 / 纱帘 / 帘头），不是服务端格序；末列 = 行尾元数据 + 「管理▸」
    // 首列表头 = 「工序」（issue #4622：这一列是**逻辑工序名**，不再是「工人看到的名字」）
    expect(within(screen.getByTestId('operation-price-matrix')).getAllByRole('columnheader').map((c) => c.textContent)).toEqual([
      '工序',
      '布帘',
      '纱帘',
      '帘头',
      '元数据 / 操作',
    ])
  })

  it('「不做」与「没定价」在界面上**可区分**（同 route_source 的「静默 = 未知」纪律）', async () => {
    render(<ProcessConfigPage />)
    await waitFor(() => expect(screen.getByTestId('operation-price-matrix')).toBeInTheDocument())

    // applicable=false ⇒ 「不做」+ data-state=na（明确不做，不是漏配）
    const na = screen.getByTestId('matrix-cell-车被-纱帘')
    expect(na).toHaveAttribute('data-state', 'na')
    expect(na).toHaveTextContent('不做')
    expect(na).not.toHaveTextContent('未定价')

    // applicable=true 但没价 ⇒ 「未定价」+ data-state=unpriced（有定价动作但还没填）
    const unpriced = screen.getByTestId('matrix-cell-三边-纱帘')
    expect(unpriced).toHaveAttribute('data-state', 'unpriced')
    expect(unpriced).toHaveTextContent('未定价')
    expect(unpriced).not.toHaveTextContent('不做')

    // 有价的格不得被渲染成上面两态
    expect(screen.getByTestId('matrix-cell-三边-布帘')).toHaveAttribute('data-state', 'priced')
  })

  it('部位价目矩阵：端点失败只在该区给可读提示（不白屏、不影响其余区）', async () => {
    mockGetOperationPositions.mockReset().mockRejectedValueOnce(new Error('500'))
    render(<ProcessConfigPage />)

    await waitFor(() => expect(screen.getByTestId('operation-price-matrix-error')).toHaveTextContent('部位价目加载失败'))
    // 路线半边照常（切过去仍渲染真实数据）
    await userEvent.click(screen.getByTestId('process-config-tab-routes'))
    await waitFor(() => expect(screen.getByTestId('routings-total')).toHaveTextContent('2'))
  })

  // ══════════════════ ③ 具名路线（name + 默认徽标 + 适用帘种） ══════════════════

  it('路线列表显示 name + 默认徽标 + 适用帘种 + 主线道数；不再出现「部位 × 工艺」标题', async () => {
    await renderOnRoutes()
    await waitFor(() => expect(screen.getByTestId('routings-total')).toHaveTextContent('2'))

    const box = screen.getByTestId('routing-11')
    expect(within(box).getByTestId('routing-name-11')).toHaveTextContent('窗帘工序路线（默认）')
    expect(within(box).getByTestId('routing-default-11')).toHaveTextContent('默认')
    expect(within(box).getByTestId('routing-positions-11')).toHaveTextContent('布帘')
    expect(within(box).getByTestId('routing-positions-11')).toHaveTextContent('纱帘')
    expect(within(box).getByTestId('routing-positions-11')).toHaveTextContent('帘头')
    expect(within(box).getByTestId('routing-mainline-count-11')).toHaveTextContent('3')

    // 非默认路线**不得**带默认徽标（注入：徽标写死 ⇒ 红）
    expect(within(screen.getByTestId('routing-12')).queryByTestId('routing-default-12')).toBeNull()
    expect(within(screen.getByTestId('routing-12')).getByTestId('routing-positions-12')).toHaveTextContent('纱帘')

    // 旧形态退场：不再按 (部位 × 工艺) 渲染
    expect(document.body.textContent ?? '').not.toContain('×')
  })

  it('空壳口径：主线为空 ⇒ 「空壳 · 不可用」（正常路线不得被误标）', async () => {
    await renderOnRoutes()
    await waitFor(() => expect(screen.getByTestId('routing-12')).toBeInTheDocument())

    expect(screen.getByTestId('routing-empty-shell-12')).toHaveTextContent('空壳')
    expect(screen.getByTestId('routing-12')).toHaveTextContent('0 道')
    expect(within(screen.getByTestId('routing-11')).queryByTestId('routing-empty-shell-11')).toBeNull()
  })

  // ══════════════════ ④ 危险操作护栏（就地展示理由） ══════════════════

  it('删默认 ⇒ 删除按钮**禁用**且就地给出可读理由（不靠后端 422 才知道）', async () => {
    await renderOnRoutes()
    await waitFor(() => expect(screen.getByTestId('routing-delete-11')).toBeInTheDocument())

    expect(screen.getByTestId('routing-delete-11')).toBeDisabled()
    const reason = screen.getByTestId('routing-delete-blocked-11')
    expect(reason).toHaveTextContent('默认')
    expect(reason).toHaveTextContent('设为默认')
    // 非默认路线可删（不得把护栏套到所有行上）
    expect(screen.getByTestId('routing-delete-12')).toBeEnabled()
  })

  it('删最后一条 ⇒ 删除按钮**禁用**且就地说明后果', async () => {
    mockGetRoutings.mockReset().mockResolvedValue(
      ok({
        total: 1,
        routings: [{ id: 11, name: '唯一路线', is_default: true, positions: ['布帘'], mainline: ['精裁'], status: 'active' }],
      }),
    )
    await renderOnRoutes()
    await waitFor(() => expect(screen.getByTestId('routing-delete-11')).toBeInTheDocument())

    expect(screen.getByTestId('routing-delete-11')).toBeDisabled()
    expect(screen.getByTestId('routing-delete-blocked-11')).toHaveTextContent('最后一条')
  })

  it('恰一条默认：默认行**不显示**「设为默认」入口（后端 is_default:false ⇒ 422，前端不得发）', async () => {
    await renderOnRoutes()
    await waitFor(() => expect(screen.getByTestId('routing-11')).toBeInTheDocument())

    expect(screen.queryByTestId('routing-set-default-11')).toBeNull()
    expect(screen.getByTestId('routing-set-default-12')).toBeInTheDocument()
  })

  // ══════════════════ ⑤ 改名（只改 name） ══════════════════

  it('改名：对话框**只有路线名称**（不出现工序名/主线编辑），PUT 只提交 name', async () => {
    await renderOnRoutes()
    await waitFor(() => expect(screen.getByTestId('routing-rename-11')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('routing-rename-11'))
    const modal = await screen.findByTestId('routing-rename-modal')
    expect(within(modal).getByTestId('routing-rename-input')).toHaveValue('窗帘工序路线（默认）')
    // 用户裁定「只是更改工艺路线总名」：对话框里**不得**出现工序名/主线编辑入口
    expect(within(modal).queryByTestId('routing-rename-mainline')).toBeNull()
    expect(modal.textContent ?? '').not.toContain('工序名')

    await userEvent.clear(within(modal).getByTestId('routing-rename-input'))
    await userEvent.type(within(modal).getByTestId('routing-rename-input'), '窗帘主线（默认）')
    await userEvent.click(screen.getByTestId('routing-rename-submit'))

    // 只提交 name —— 改名不得顺带重写主线（那是计件工资的输入）
    await waitFor(() => expect(mockUpdateRouting).toHaveBeenCalledWith(11, { name: '窗帘主线（默认）' }))
    await waitFor(() => expect(mockGetRoutings).toHaveBeenCalledTimes(2))
  })

  it('改名失败（重名 409/422）：理由**逐条**就地展示，不吞成一句「保存失败」', async () => {
    mockUpdateRouting.mockReset().mockRejectedValueOnce(
      guardError(['工艺路线「纱帘专线」已存在']),
    )
    await renderOnRoutes()
    await waitFor(() => expect(screen.getByTestId('routing-rename-12')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('routing-rename-12'))
    await userEvent.clear(await screen.findByTestId('routing-rename-input'))
    await userEvent.type(screen.getByTestId('routing-rename-input'), '纱帘专线')
    await userEvent.click(screen.getByTestId('routing-rename-submit'))

    await waitFor(() => expect(screen.getByTestId('routing-op-error-item-0')).toHaveTextContent('已存在'))
    expect(screen.queryByText(/Request failed with status code/)).not.toBeInTheDocument()
    expect(mockGetRoutings).toHaveBeenCalledTimes(1)
  })

  // ══════════════════ ⑥ 删除（二次确认 + DELETE + 刷新） ══════════════════

  it('删除：**二次确认**后才发 DELETE，成功后刷新列表', async () => {
    await renderOnRoutes()
    await waitFor(() => expect(screen.getByTestId('routing-delete-12')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('routing-delete-12'))
    // 只打开确认框 ⇒ 不得发请求（注入：去掉确认直接删 ⇒ 红）
    expect(await screen.findByTestId('routing-confirm-modal')).toHaveAttribute('data-kind', 'delete')
    expect(mockDeleteRouting).not.toHaveBeenCalled()

    await userEvent.click(screen.getByTestId('routing-confirm-delete-12'))
    await waitFor(() => expect(mockDeleteRouting).toHaveBeenCalledWith(12))
    await waitFor(() => expect(mockGetRoutings).toHaveBeenCalledTimes(2))
  })

  it('删除：确认框可取消 —— 取消后不发 DELETE', async () => {
    await renderOnRoutes()
    await waitFor(() => expect(screen.getByTestId('routing-delete-12')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('routing-delete-12'))
    await userEvent.click(await screen.findByTestId('routing-confirm-cancel'))
    expect(mockDeleteRouting).not.toHaveBeenCalled()
    expect(screen.queryByTestId('routing-confirm-modal')).toBeNull()
  })

  it('删除被后端拒（护栏 422）：理由逐条就地展示，且商家面不出现内部机制名', async () => {
    mockDeleteRouting.mockReset().mockRejectedValueOnce(
      guardError([
        '默认路线不能删：删了该租户就没有默认路线 ⇒ 缺信号订单建单全部 fail-closed。请先把另一条设为默认，再删这条',
      ]),
    )
    await renderOnRoutes()
    await waitFor(() => expect(screen.getByTestId('routing-delete-12')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('routing-delete-12'))
    await userEvent.click(await screen.findByTestId('routing-confirm-delete-12'))

    await waitFor(() => expect(screen.getByTestId('routing-op-error-item-0')).toBeInTheDocument())
    expect(screen.getByTestId('routing-op-error-item-0')).toHaveTextContent('默认路线不能删')
    // issue #4453：内部机制名不入商家面（只换词，不删理由）
    expect(document.body.textContent ?? '').not.toContain('信号')
    expect(document.body.textContent ?? '').not.toContain('fail-closed')
    expect(mockGetRoutings).toHaveBeenCalledTimes(1)
  })

  // ══════════════════ ⑦ 设为默认（PUT is_default:true） ══════════════════

  it('设为默认：二次确认 → `PUT {is_default:true}` → 刷新', async () => {
    await renderOnRoutes()
    await waitFor(() => expect(screen.getByTestId('routing-set-default-12')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('routing-set-default-12'))
    expect(await screen.findByTestId('routing-confirm-modal')).toHaveAttribute('data-kind', 'default')
    expect(mockUpdateRouting).not.toHaveBeenCalled()

    await userEvent.click(screen.getByTestId('routing-confirm-default-12'))
    await waitFor(() => expect(mockUpdateRouting).toHaveBeenCalledWith(12, { is_default: true }))
    await waitFor(() => expect(mockGetRoutings).toHaveBeenCalledTimes(2))
  })

  it('页面**绝不**提交 `is_default:false`（后端 422：取消默认 ⇒ 零默认 ⇒ 建单全 fail-closed）', async () => {
    await renderOnRoutes()
    await waitFor(() => expect(screen.getByTestId('routing-set-default-12')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('routing-set-default-12'))
    await userEvent.click(await screen.findByTestId('routing-confirm-default-12'))
    await waitFor(() => expect(mockUpdateRouting).toHaveBeenCalled())

    const payloads = mockUpdateRouting.mock.calls.map((c) => c[1] as Record<string, unknown>)
    expect(payloads.every((p) => p.is_default !== false)).toBe(true)
  })

  // ══════════════════ ⑧ 适用条件（26 条不截断，取值逐字取自后端；issue #4650 阶段 1 起挂在工序上） ══════════════════

  it('⑳ 适用条件**常驻可见**：打开抽屉即见，没有折叠开关（issue #4613 口径随 #4650 迁到抽屉）', async () => {
    const section = await openConditions('韩褶')

    // 条件**直接可见** —— 改前默认收起（要再点一下才看得到，连带说明也被藏起来）⇒ 本断言红
    expect(within(section).getAllByTestId(/^operation-condition-\d+$/)).toHaveLength(1)
    expect(within(section).getByTestId('operation-condition-text-1')).toHaveTextContent('韩褶')
    expect(section).toHaveTextContent('适用条件')
    // 反向断言：折叠开关**不存在**（移除的是折叠**能力**，不只是「默认打开」）
    expect(screen.queryByTestId('operation-conditions-toggle')).toBeNull()
    expect(screen.queryByTestId('route-rules-toggle')).toBeNull()
  })

  it('适用条件：26 条**整份**渲染（不截断），取值**逐字**取自后端', async () => {
    const big = Array.from({ length: 26 }, (_, i) => ({
      id: 100 + i,
      trigger_kind: i % 2 === 0 ? 'craft' : 'option',
      trigger_value: `触发${i + 1}`,
      position: i % 3 === 0 ? null : '布帘',
      action: i % 4 === 0 ? 'remove' : 'insert',
      operation: '三边',
      after_operation: i % 4 === 0 ? null : '精裁',
      priority: (i + 1) * 10,
      status: 'active',
    }))
    mockGetRouteRules.mockReset().mockResolvedValue(ok(big))
    const section = await openConditions('三边')

    // 注入：把 26 条截断成前 20 条（.slice(0,20)）⇒ 断言红
    expect(within(section).getAllByTestId(/^operation-condition-\d+$/)).toHaveLength(26)
    expect(within(section).getByTestId('operation-condition-text-100')).toHaveTextContent('触发1')
  })

  it('适用条件：三种形态的**人话**都可读（带锚点 / 不做 / 追加到末尾）', async () => {
    mockGetRouteRules.mockReset().mockResolvedValue(
      ok([
        { id: 1, trigger_kind: 'craft', trigger_value: '韩褶', position: null, action: 'insert', operation: '韩褶', after_operation: '三边', priority: 10, status: 'active' },
        { id: 2, trigger_kind: 'craft', trigger_value: '打孔', position: '布帘', action: 'remove', operation: '车被', after_operation: null, priority: 20, status: 'active' },
        { id: 3, trigger_kind: 'option', trigger_value: '拼2次', position: '纱帘', action: 'insert', operation: '外帘装袋', after_operation: null, priority: 30, status: 'active' },
      ]),
    )
    await openConditions('韩褶')

    // ① 工艺触发 · 插入 after 锚点（取值**逐字**取自后端）
    expect(screen.getByTestId('operation-condition-text-1')).toHaveTextContent('工艺 = 韩褶 时插入（在「三边」之后）')

    await userEvent.click(screen.getByTestId('operations-manage-close'))
    await userEvent.click(screen.getByTestId('matrix-manage-车被'))
    // ② 工艺触发 · 不做
    expect(await screen.findByTestId('operation-condition-text-2')).toHaveTextContent('工艺 = 打孔 时不做')

    await userEvent.click(screen.getByTestId('operations-manage-close'))
    await userEvent.click(screen.getByTestId('matrix-manage-外帘装袋'))
    // ③ 特殊选项触发 · 无锚点 ⇒ 「追加到末尾」；取值**逐字**：拼2次（前端不得"纠正"成「拼两次」）
    expect(await screen.findByTestId('operation-condition-text-3')).toHaveTextContent(
      '特殊选项 = 拼2次 时插入（追加到末尾）',
    )
  })

  // ══════════════════ ⑨ 就绪度「默认路线」格 ══════════════════

  it('就绪度新增「默认路线」格：有默认 ⇒ done；无默认 ⇒ todo + 说明后果', async () => {
    await renderOnRoutes()
    await waitFor(() => expect(screen.getByTestId('readiness-step-default-route')).toBeInTheDocument())
    expect(screen.getByTestId('readiness-step-default-route')).toHaveAttribute('data-state', 'done')
  })

  it('就绪度「默认路线」格：零默认 ⇒ todo，并说明「没有指定工艺的订单一张加工单也生成不了」', async () => {
    mockGetRoutings.mockReset().mockResolvedValue(
      ok({
        total: 1,
        routings: [{ id: 11, name: '唯一路线', is_default: false, positions: ['布帘'], mainline: ['精裁'], status: 'active' }],
      }),
    )
    await renderOnRoutes()

    await waitFor(() => expect(screen.getByTestId('readiness-step-default-route')).toHaveAttribute('data-state', 'todo'))
    expect(screen.getByTestId('readiness-step-default-route')).toHaveTextContent('加工单')
    expect(screen.getByTestId('readiness-step-default-route')).toHaveTextContent('设为默认')
  })

  // ══════════════════ ⑨b 就绪度第 4 步「算料配置」（issue #4567 用户走查③） ══════════════════

  it('就绪度第 4 步「算料配置」：本租户有保存过的配置（source=stored）⇒ done', async () => {
    // 该判据必须**先**在「算料配置」tab 把配置读回来 —— 读面是懒加载的，首屏它还不在
    //（懒加载 → unknown 中性态见下一条；此处判的是「读到 stored 之后」）。
    mockGetCraftCalcConfig.mockReset().mockResolvedValue(ok({ source: 'stored', config: ENGINE_DEFAULT_CALC_CONFIG }))
    render(<ProcessConfigPage />)
    await waitFor(() => expect(screen.getByTestId('operation-price-matrix')).toBeInTheDocument())
    await userEvent.click(screen.getByTestId('process-config-tab-calc'))
    await waitFor(() => expect(screen.getByTestId('craft-calc-config-panel')).toBeInTheDocument())

    const step = screen.getByTestId('readiness-step-calc-config')
    // 注入：把第 4 步删掉（就绪度回到三步）⇒ getByTestId 直接抛错，断言红
    expect(step).toHaveAttribute('data-state', 'done')
    expect(step).toHaveTextContent('算料配置')
    expect(step).toHaveTextContent('已保存')
    // 已保存 ⇒ hint 留空（与既有三步 done 态一致）
    expect(step).not.toHaveTextContent('下一步')
  })

  it('就绪度第 4 步「算料配置」：本租户无配置行（source=default）⇒ todo + 指向「算料配置」tab', async () => {
    render(<ProcessConfigPage />)
    await waitFor(() => expect(screen.getByTestId('operation-price-matrix')).toBeInTheDocument())
    await userEvent.click(screen.getByTestId('process-config-tab-calc'))
    await waitFor(() => expect(screen.getByTestId('craft-calc-config-panel')).toBeInTheDocument())

    const step = screen.getByTestId('readiness-step-calc-config')
    // 注入：把 source==='stored' 之外一律判 done ⇒ 本断言红（把「系统默认」谎报成「配好了」）
    expect(step).toHaveAttribute('data-state', 'todo')
    expect(step).toHaveTextContent('系统默认')
    expect(step).toHaveTextContent('算料配置')
    expect(step).toHaveTextContent('每折吃布')
  })

  it('就绪度第 4 步「算料配置」：读面还没回来 ⇒ **中性**（不把「没加载」误报成「没配」）', async () => {
    // 挂起：GET 永不 resolve ⇒ calcConfig 停在 null（首屏真实形态）
    mockGetCraftCalcConfig.mockReset().mockReturnValue(new Promise(() => {}))
    render(<ProcessConfigPage />)
    await waitFor(() => expect(screen.getByTestId('operation-price-matrix')).toBeInTheDocument())
    await userEvent.click(screen.getByTestId('process-config-tab-calc'))

    const step = screen.getByTestId('readiness-step-calc-config')
    // 注入：把「未加载」并入 todo 分支 ⇒ 本断言红（未加载被误报成「没配」，正是本条的缺陷形态）
    expect(step).toHaveAttribute('data-state', 'unknown')
    expect(step).toHaveTextContent('读取中')
    expect(step).not.toHaveTextContent('待完成')
  })

  // ══════════════════ ⑨c 适用条件里的「单价（元/套）」（issue #4567 用户走查①；#4650 起随条件搬进抽屉） ══════════════════
  //
  // 独立规则表没了，但那笔**对客按套**的钱仍然只有一个载体 = **特殊选项触发的那条条件**
  // ⇒ 跟着条件一起搬进工序抽屉，写面（`PUT /route-rules/{id}/customer-unit-price`）一字未动。

  it('规则区单价：option 行有价渲染金额、**未定价渲染「未定价」且不含 ¥0.00**、真 0 元照显示 ¥0.00', async () => {
    mockGetRouteRules.mockReset().mockResolvedValue(ok(RULES_WITH_PRICE))
    await openConditions('韩褶')
    await waitFor(() => expect(screen.getByTestId('route-rule-price-21')).toBeInTheDocument())

    // ① 有价 ⇒ 用页面既有的 money() 渲染
    expect(screen.getByTestId('route-rule-price-21')).toHaveTextContent('¥12.50')
    expect(screen.getByTestId('route-rule-price-21')).toHaveAttribute('data-state', 'priced')

    // ② 未定价 ⇒ 「未定价」，**不得**是 ¥0.00（未定价 ≠ 0 元 —— 仓库硬纪律）
    const unpriced = screen.getByTestId('route-rule-price-22')
    expect(unpriced).toHaveTextContent('未定价')
    expect(unpriced).not.toHaveTextContent('¥0.00')
    expect(unpriced).toHaveAttribute('data-state', 'unpriced')

    // ③ 定价恰为 0 ⇒ 真价 0 元，照样显示金额（**不**被并进「未定价」）
    expect(screen.getByTestId('route-rule-price-23')).toHaveTextContent('¥0.00')
    expect(screen.getByTestId('route-rule-price-23')).toHaveAttribute('data-state', 'priced')
    // 未定价那一格**不**含 ¥ 符号（与真 0 元在文本上也可区分）
    expect(unpriced.textContent).not.toContain('¥')
  })

  it('规则区单价：非 option 行（craft 等工艺变体）⇒ **不出现**价格格（工艺变体不按套计价）', async () => {
    mockGetRouteRules.mockReset().mockResolvedValue(ok(RULES_WITH_PRICE))
    const section = await openConditions('韩褶')
    await waitFor(() => expect(screen.getByTestId('route-rule-price-21')).toBeInTheDocument())

    // 注入：给非 option 行也渲染价格格（`money(null)` 会出 ¥0.00 —— 未定价 ≠ 0 元）⇒ 断言红
    expect(screen.queryByTestId('route-rule-price-24')).toBeNull()
    // 那条条件本身仍在（只是它没有那笔对客的钱）—— 三态仍可区分：有价 / 未定价 / 不适用（无价格格）
    expect(screen.getByTestId('operation-condition-text-24')).toHaveTextContent('工艺 = 韩褶 时插入（在「三边」之后）')

    // 说明文案（特殊选项按**套**收费）就地写在「适用条件」一节里
    expect(section).toHaveTextContent('按套收费')
  })

  it('规则区单价行内编辑（成功）：铅笔 → 输入 → 保存 ⇒ PUT 只带 {customer_unit_price}，成功后刷新', async () => {
    mockGetRouteRules.mockReset().mockResolvedValue(ok(RULES_WITH_PRICE))
    mockUpdateRuleCustomerUnitPrice.mockReset().mockResolvedValue(ok({ id: 21, customer_unit_price: 6 }))
    await openConditions('韩褶')
    await waitFor(() => expect(screen.getByTestId('route-rule-price-21')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('route-rule-price-edit-21'))
    const input = screen.getByTestId('route-rule-price-input-21')
    // 初值 = 当前价（不是 0）
    expect(input).toHaveValue(12.5)
    await userEvent.clear(input)
    await userEvent.type(input, '6')
    await userEvent.click(screen.getByTestId('route-rule-price-save-21'))

    await waitFor(() => expect(mockUpdateRuleCustomerUnitPrice).toHaveBeenCalledTimes(1))
    // 注入：顺手带上 factor / 计件单价 ⇒ 两套账互读，断言红
    expect(mockUpdateRuleCustomerUnitPrice.mock.calls[0][0]).toBe(21)
    expect(mockUpdateRuleCustomerUnitPrice.mock.calls[0][1]).toEqual({ customer_unit_price: 6 })
    // 成功后重新拉取（结果可见，不靠本地乐观值假装成功）
    await waitFor(() => expect(mockGetRouteRules.mock.calls.length).toBeGreaterThan(1))
  })

  it('规则区单价行内编辑（成功·清空）：清空 ⇒ PUT `null` = 改回**未定价**（不是 0 元）', async () => {
    mockGetRouteRules.mockReset().mockResolvedValue(ok(RULES_WITH_PRICE))
    mockUpdateRuleCustomerUnitPrice.mockReset().mockResolvedValue(ok({ id: 21, customer_unit_price: null }))
    await openConditions('韩褶')
    await waitFor(() => expect(screen.getByTestId('route-rule-price-21')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('route-rule-price-edit-21'))
    await userEvent.clear(screen.getByTestId('route-rule-price-input-21'))
    await userEvent.click(screen.getByTestId('route-rule-price-save-21'))

    await waitFor(() => expect(mockUpdateRuleCustomerUnitPrice).toHaveBeenCalledTimes(1))
    // 注入：把空串当 0 发 ⇒ 断言红（未定价 ≠ 0 元）
    expect(mockUpdateRuleCustomerUnitPrice.mock.calls[0][1]).toEqual({ customer_unit_price: null })
  })

  it('规则区单价行内编辑（失败）：后端理由**逐条**就地展示，且不假装成功（不刷新、不改显示）', async () => {
    mockGetRouteRules.mockReset().mockResolvedValue(ok(RULES_WITH_PRICE))
    const callsBefore = mockGetRouteRules.mock.calls.length
    mockUpdateRuleCustomerUnitPrice.mockReset().mockRejectedValue({
      response: {
        status: 422,
        data: {
          success: false,
          error: {
            code: 'VALIDATION_ERROR',
            message: '只有特殊选项按套计价（工艺变体不按套收费）',
            details: [
              { field: 'trigger_kind', message: '这条规则的触发维是「craft」，不是特殊选项（option）' },
            ],
          },
        },
      },
    })
    await openConditions('韩褶')
    await waitFor(() => expect(screen.getByTestId('route-rule-price-21')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('route-rule-price-edit-21'))
    await userEvent.clear(screen.getByTestId('route-rule-price-input-21'))
    await userEvent.type(screen.getByTestId('route-rule-price-input-21'), '6')
    await userEvent.click(screen.getByTestId('route-rule-price-save-21'))

    // 注入：把理由吞成一句「保存失败」⇒ 断言红
    const reasons = await screen.findByTestId('route-rule-price-reasons-21')
    expect(reasons).toHaveTextContent('不是特殊选项')
    // 失败 ⇒ 留在编辑态、不刷新、原值不被改成新值（静默写回 = 商家以为改了、取价侧没改）
    expect(screen.getByTestId('route-rule-price-input-21')).toBeInTheDocument()
    expect(mockGetRouteRules.mock.calls.length).toBe(callsBefore + 1)
  })

  it('规则区单价行内编辑（本地预检）：负数 / 三位小数 ⇒ 不发请求，就地给理由', async () => {
    mockGetRouteRules.mockReset().mockResolvedValue(ok(RULES_WITH_PRICE))
    await openConditions('韩褶')
    await waitFor(() => expect(screen.getByTestId('route-rule-price-21')).toBeInTheDocument())

    for (const bad of ['-1', '6.005']) {
      await userEvent.click(screen.getByTestId('route-rule-price-edit-21'))
      const input = screen.getByTestId('route-rule-price-input-21')
      await userEvent.clear(input)
      await userEvent.type(input, bad)
      await userEvent.click(screen.getByTestId('route-rule-price-save-21'))
      // 注入：去掉本地预检 ⇒ 请求被发出，断言红
      expect(mockUpdateRuleCustomerUnitPrice).not.toHaveBeenCalled()
      expect(await screen.findByTestId('route-rule-price-reasons-21')).toHaveTextContent('两位小数')
      await userEvent.click(screen.getByTestId('route-rule-price-cancel-21'))
    }
  })

  it('规则区单价：**非 option 行没有编辑入口**（工艺变体不按套收费，服务端也会 422）', async () => {
    mockGetRouteRules.mockReset().mockResolvedValue(ok(RULES_WITH_PRICE))
    await openConditions('韩褶')
    await waitFor(() => expect(screen.getByTestId('route-rule-price-21')).toBeInTheDocument())

    expect(screen.queryByTestId('route-rule-price-24')).toBeNull()
    expect(screen.queryByTestId('route-rule-price-edit-24')).toBeNull()
    // option 行有入口（对照组：证明不是「全都没有」）
    expect(screen.getByTestId('route-rule-price-edit-21')).toBeInTheDocument()
  })

  // ══════════════════ ⑩ 零退化：工艺项单表 / 路线半边 / 两个 tab / 切 tab 不丢状态 ══════════════════

  it('⑰-① 工艺项**只有一张表**：「工序库明细」折叠区已取消；主表不出现「作用域」「必完」', async () => {
    await renderOperations()
    const panel = screen.getByTestId('craft-operations-panel')

    // 折叠区与它的 testid 一律不存在（注入：把次区加回来 ⇒ 红）
    for (const id of [
      'operations-catalog',
      'operations-catalog-toggle',
      'operations-catalog-body',
      'operations-catalog-total',
      'operations-catalog-error',
    ]) {
      expect(screen.queryByTestId(id)).toBeNull()
    }
    expect(within(panel).queryByText('工序库明细')).toBeNull()
    // 一屏只有**一张**表（两张平铺表正是本次要治的形态）
    expect(within(panel).getAllByRole('table')).toHaveLength(1)
    // 用户 2026-09-19 追加裁定：**作用域**收进抽屉 ⇒ 这个词不得出现在主表；
    // ⚠️ 同日**改判**（issue #4610）：「必完标记还是得在这里展示」⇒ 必完回到主表行尾，
    //    但它只是**只读标记**（维护面仍在抽屉里）—— 见 ⑳ 的三态断言。
    expect(within(panel).queryByText('作用域')).toBeNull()
  })

  it('⑰-② 行尾元数据 = `分组 · 单位`（公共值；不一致时**全部列出**，不静默取第一个）+ 必完标记', async () => {
    await renderOperations()

    // 三边：两格变体同为 车位 · 米 ⇒ 公共值
    const common = screen.getByTestId('matrix-meta-三边')
    expect(common).toHaveTextContent('车位')
    expect(common).toHaveTextContent('米')
    expect(common).not.toHaveAttribute('data-inconsistent')

    // 精裁：两格分组不同（裁剪 / 车位）⇒ **两个都列出**（注入：只取第一个 ⇒ 红）
    const mixed = screen.getByTestId('matrix-meta-精裁')
    expect(mixed).toHaveTextContent('裁剪')
    expect(mixed).toHaveTextContent('车位')
    expect(mixed).toHaveAttribute('data-inconsistent', 'true')

    // 韩褶：矩阵里查不到变体（6 键全 null）⇒ 不发明元数据
    expect(screen.getByTestId('matrix-meta-韩褶')).toHaveTextContent('—')

    // issue #4610：精裁两格变体都必完 ⇒ 行尾带 `必完`（三态见下一条用例）
    expect(screen.getByTestId('matrix-must-finish-精裁')).toHaveTextContent('必完')
  })

  it('⑳ 行尾必完标记三态：全必完 ⇒ `必完`；部分部位 ⇒ `必完（部分部位）` + title 列部位；无 ⇒ 不显示（issue #4610）', async () => {
    // 夹具刻意造出**部分部位**那一态（基座夹具里没有）：车被 布帘必完 / 纱帘**非**必完
    mockGetOperationPositions.mockReset().mockResolvedValue(
      ok([
        { id: 'p1', operation: '三边', position: '布帘', unit_price: 1.2, applicable: true, variant_operation_id: 'op-三边-布', unit: '米', group: '车位', scope: 'position', is_must_finish: false },
        { id: 'p2', operation: '三边', position: '纱帘', unit_price: 1.2, applicable: true, variant_operation_id: 'op-三边-纱', unit: '米', group: '车位', scope: 'position', is_must_finish: false },
        { id: 'p3', operation: '精裁', position: '布帘', unit_price: 8.5, applicable: true, variant_operation_id: 'op-精裁-布', unit: '套', group: '裁剪', scope: 'position', is_must_finish: true },
        { id: 'p4', operation: '精裁', position: '纱帘', unit_price: 6, applicable: true, variant_operation_id: 'op-精裁-纱', unit: '套', group: '车位', scope: 'position', is_must_finish: true },
        { id: 'p5', operation: '车被', position: '布帘', unit_price: 0, applicable: true, variant_operation_id: 'op-车被', unit: '件', group: '后道', scope: 'set', is_must_finish: true },
        { id: 'p6', operation: '车被', position: '纱帘', unit_price: null, applicable: true, variant_operation_id: 'op-车被-纱', unit: '件', group: '后道', scope: 'position', is_must_finish: false },
        { id: 'p7', operation: '韩褶', position: '布帘', unit_price: 2, applicable: true, ...NO_VARIANT },
      ]),
    )
    await renderOperations()

    // ① 有变体的格**全部**必完 ⇒ `必完`（不带「部分部位」）
    const all = screen.getByTestId('matrix-must-finish-精裁')
    expect(all).toHaveTextContent('必完')
    expect(all).not.toHaveTextContent('部分部位')

    // ② **只有部分部位**必完 ⇒ 注明 + `title` **列出具体哪些部位**（注入：静默取第一个 ⇒ 部位列错，断言红）
    const partial = screen.getByTestId('matrix-must-finish-车被')
    expect(partial).toHaveTextContent('必完（部分部位）')
    expect(partial.getAttribute('title')).toContain('布帘')
    expect(partial.getAttribute('title')).not.toContain('纱帘')

    // ③ 一道都不必完 / 读面没给该键 ⇒ **不显示**（不得发明「非必完」这类新词）
    expect(screen.queryByTestId('matrix-must-finish-三边')).toBeNull()
    expect(screen.queryByTestId('matrix-must-finish-韩褶')).toBeNull()
    expect(screen.getByTestId('matrix-meta-三边')).not.toHaveTextContent('必完')
    expect(screen.getByTestId('matrix-meta-韩褶')).not.toHaveTextContent('必完')
  })

  it('㉖-① 矩阵行首**不再显示变体名**（改判 ⑰-③）：该行「哪个部位做/不做」由列与格表达', async () => {
    await renderOperations()

    // 行首小字整块去掉 —— 承载变体名的节点与 testid 都不再存在（testid 也是界面契约的一部分）
    expect(screen.queryByTestId('matrix-variants-精裁')).toBeNull()
    expect(screen.queryByTestId(/^matrix-variants-/)).toBeNull()

    // 红证（改前必红）：改前这一屏的行首小字就是这些变体名（`精裁-布 / 精裁-纱`、`布三边 / 纱三边`）
    const panel = screen.getByTestId('craft-operations-panel')
    for (const variantName of ['精裁-布', '精裁-纱', '布三边', '纱三边', '车被-纱', '韩褶-布']) {
      expect(panel).not.toHaveTextContent(variantName)
    }

    // 信息不丢：逻辑工序名照旧；部位维度仍由**列与格**表达（价 / 不做 / 未定价三态俱在）
    expect(screen.getByTestId('matrix-row-精裁')).toHaveTextContent('精裁')
    expect(screen.getByTestId('matrix-cell-精裁-布帘')).toHaveTextContent('¥8.50')
    expect(screen.getByTestId('matrix-cell-精裁-帘头')).toHaveTextContent('不做')
    expect(screen.getByTestId('matrix-cell-三边-纱帘')).toHaveTextContent('未定价')
  })

  it('⑰-④ 三态可区分：`¥0.00` 是真价（≠「未定价」）；未定价计数 = 待办数', async () => {
    await renderOperations()

    const zero = screen.getByTestId('matrix-cell-车被-布帘')
    expect(zero).toHaveAttribute('data-state', 'priced')
    expect(zero).toHaveTextContent('¥0.00')
    expect(zero).not.toHaveTextContent('未定价')

    const unpriced = screen.getByTestId('matrix-cell-三边-纱帘')
    expect(unpriced).toHaveAttribute('data-state', 'unpriced')
    expect(unpriced).toHaveTextContent('未定价')
    // 未定价那一格**不含 ¥ 符号**（与真 0 元在文本上也可区分）
    expect(unpriced).not.toHaveTextContent('¥')

    expect(screen.getByTestId('matrix-unpriced-count')).toHaveTextContent('1')
  })

  it('⑰-⑤ 格内改价：body **只带** `{unit_price}`；清空 ⇒ `null`（改回未定价，≠ 0 元）', async () => {
    await renderOperations()

    await userEvent.click(screen.getByTestId('matrix-price-edit-精裁-纱帘'))
    const input = screen.getByTestId('matrix-price-input-精裁-纱帘')
    await userEvent.clear(input)
    await userEvent.type(input, '6.5')
    await userEvent.click(screen.getByTestId('matrix-price-save-精裁-纱帘'))

    await waitFor(() =>
      expect(mockUpdateOperationPosition).toHaveBeenCalledWith('pos-精裁-纱帘', { unit_price: 6.5 }),
    )
    expect(Object.keys(mockUpdateOperationPosition.mock.calls[0][1] as object)).toEqual(['unit_price'])

    // 清空 = 改回**未定价**（发 `null`；注入：把空串当 0 发 ⇒ 红）
    mockUpdateOperationPosition.mockClear()
    await userEvent.click(screen.getByTestId('matrix-price-edit-三边-布帘'))
    await userEvent.clear(screen.getByTestId('matrix-price-input-三边-布帘'))
    await userEvent.click(screen.getByTestId('matrix-price-save-三边-布帘'))
    await waitFor(() =>
      expect(mockUpdateOperationPosition).toHaveBeenCalledWith('pos-三边-布帘', { unit_price: null }),
    )
  })

  it('⑰-⑥ 「不做 ⇄」：切成不做 ⇒ 只带 `{applicable:false}`；切回做 ⇒ `{applicable:true}`', async () => {
    await renderOperations()

    await userEvent.click(screen.getByTestId('matrix-applicable-三边-布帘'))
    await waitFor(() =>
      expect(mockUpdateOperationPosition).toHaveBeenCalledWith('pos-三边-布帘', { applicable: false }),
    )
    expect(Object.keys(mockUpdateOperationPosition.mock.calls[0][1] as object)).toEqual(['applicable'])

    await userEvent.click(screen.getByTestId('matrix-applicable-三边-帘头'))
    await waitFor(() =>
      expect(mockUpdateOperationPosition).toHaveBeenCalledWith('pos-三边-帘头', { applicable: true }),
    )
  })

  /**
   * issue #4665 ③：主表格格子里的做/不做**不许只靠 hover/`title` 才知道它是什么**
   * （改前是一个光秃秃的 `⇄`）⇒ 控件必须有**可见文字**，且三态语义不变。
   */
  it('#4665-D 主表格格子：做/不做**有可见文字**（改前只有裸 `⇄`），三态不变', async () => {
    await renderOperations()

    // `applicable=true` 的格：控件文字 = `做`
    expect(screen.getByTestId('matrix-applicable-三边-布帘')).toHaveTextContent('做')
    // `applicable=false` 的格：控件文字 = `不做`
    expect(screen.getByTestId('matrix-applicable-三边-帘头')).toHaveTextContent('不做')
    // 三态不混：`未定价`（做但没价）**不得**渲染成 ¥0.00
    const cell = screen.getByTestId('matrix-cell-三边-纱帘')
    expect(cell).toHaveAttribute('data-state', 'unpriced')
    expect(cell).toHaveTextContent('未定价')
    expect(cell).not.toHaveTextContent('¥0.00')
  })

  it('⑰-⑦ 格内改价本地预检：负数 / 三位小数 ⇒ **不发请求**，就地给理由', async () => {
    await renderOperations()

    await userEvent.click(screen.getByTestId('matrix-price-edit-精裁-纱帘'))
    const input = screen.getByTestId('matrix-price-input-精裁-纱帘')
    await userEvent.clear(input)
    await userEvent.type(input, '5.555')
    await userEvent.click(screen.getByTestId('matrix-price-save-精裁-纱帘'))

    expect(mockUpdateOperationPosition).not.toHaveBeenCalled()
    expect(screen.getByTestId('matrix-price-reasons-精裁-纱帘')).toHaveTextContent('最多两位小数')
  })

  it('⑰-⑧ 格内改价被后端拒：理由**逐条**就地展示，且不静默收摊（仍在编辑态）', async () => {
    mockUpdateOperationPosition
      .mockReset()
      .mockRejectedValueOnce(guardError(['该部位已停用，不能改价', '请先处理引用它的主线']))
    await renderOperations()

    await userEvent.click(screen.getByTestId('matrix-price-edit-精裁-纱帘'))
    const input = screen.getByTestId('matrix-price-input-精裁-纱帘')
    await userEvent.clear(input)
    await userEvent.type(input, '6.5')
    await userEvent.click(screen.getByTestId('matrix-price-save-精裁-纱帘'))

    const reasons = await screen.findByTestId('matrix-price-reasons-精裁-纱帘')
    expect(reasons).toHaveTextContent('该部位已停用，不能改价')
    expect(reasons).toHaveTextContent('请先处理引用它的主线')
    expect(screen.getByTestId('matrix-price-input-精裁-纱帘')).toBeInTheDocument()
  })

  it('⑰-⑨ 搜索框过滤这一张表（行级过滤；不是两张表各滤一遍）', async () => {
    await renderOperations()
    await userEvent.type(screen.getByTestId('operations-search'), '精裁')
    await waitFor(() => expect(screen.queryByTestId('matrix-row-三边')).toBeNull())
    expect(screen.getByTestId('matrix-row-精裁')).toBeInTheDocument()
  })

  it('⑰-⑩ 「管理▸」抽屉：条目带 分组·单位·作用域·必完 + 商家话解释；改档各只带自己的字段', async () => {
    await openManage('车被')
    const row = screen.getByTestId('variant-row-op-车被')
    // issue #4622：条目主标识 = 部位（改前是变体名 `车被`）
    expect(row).toHaveTextContent('布帘')
    expect(row).not.toHaveTextContent('车被-布')
    expect(row).toHaveTextContent('后道')
    expect(row).toHaveTextContent('件')

    // 作用域：闭词表两档 + 一句商家看得懂的解释
    expect(screen.getByTestId('variant-scope-op-车被')).toHaveValue('set')
    expect(row).toHaveTextContent('每樘窗只做一次')
    // 必完：勾选态 + 一句解释（issue #4610 追加：解释要能回答「多部位时判谁」）
    expect(screen.getByTestId('variant-must-finish-op-车被')).toBeChecked()
    expect(row).toHaveTextContent('必完 · 缺这道工序不能打包（部位级：每个部位都要做完）')
    // 抽屉顶部说明与勾选框旁的小字**口径一致**（都含「每个部位」这一层）
    expect(screen.getByTestId('operations-manage-drawer')).toHaveTextContent('部位级工序要每个部位都做完')
    // 反向护栏（用户裁定「不加作用域限制」）：部位级的必完开关**仍可用**（不得 disabled/隐藏）
    expect(screen.getByTestId('variant-must-finish-op-车被')).not.toBeDisabled()

    await userEvent.selectOptions(screen.getByTestId('variant-scope-op-车被'), 'position')
    await waitFor(() => expect(mockUpdateOperation).toHaveBeenCalledWith('op-车被', { scope: 'position' }))

    await userEvent.click(screen.getByTestId('variant-must-finish-op-车被'))
    await waitFor(() => expect(mockUpdateOperation).toHaveBeenCalledWith('op-车被', { is_must_finish: false }))

    // 停用走既有写面（`PUT /operations/{id}` 的 `status`）
    await userEvent.click(screen.getByTestId('variant-disable-op-车被'))
    await waitFor(() => expect(mockUpdateOperation).toHaveBeenCalledWith('op-车被', { status: 'inactive' }))
  })

  it('㉖-② 抽屉条目以**部位**为主标识（改判 ⑰-⑪）：按 `variant_operation_id` 去重，且不显示变体名', async () => {
    await openManage('三边')
    expect(screen.getAllByTestId(/^variant-row-/)).toHaveLength(2)

    const cloth = screen.getByTestId('variant-row-op-三边-布')
    expect(cloth).toHaveTextContent('布帘')
    expect(cloth).not.toHaveTextContent('布三边')

    const yarn = screen.getByTestId('variant-row-op-三边-纱')
    expect(yarn).toHaveTextContent('纱帘')
    expect(yarn).not.toHaveTextContent('纱三边')

    // 抽屉整体（标题 / 说明 / 条目）都不得出现变体名（红证：改前条目主标识就是变体名）
    const drawer = screen.getByTestId('operations-manage-drawer')
    expect(drawer).not.toHaveTextContent('布三边')
    expect(drawer).not.toHaveTextContent('纱三边')
  })

  it('㉖-③ 抽屉条目主标识 = 它**服务的部位集合**（`帘头` 回落复用 `布帘` 的变体 ⇒ 一条条目列两个部位）', async () => {
    mockGetOperationPositions.mockReset().mockResolvedValue(
      ok([
        { id: 'p1', operation: '三边', position: '布帘', unit_price: 1.2, applicable: true, variant_operation_id: 'op-三边-布', unit: '米', group: '车位', scope: 'position', is_must_finish: false },
        { id: 'p2', operation: '三边', position: '帘头', unit_price: 1.2, applicable: true, variant_operation_id: 'op-三边-布', unit: '米', group: '车位', scope: 'position', is_must_finish: false },
      ]),
    )
    await openManage('三边')

    // 一个变体服务多个部位 ⇒ 仍只列一条（按 id 去重），主标识是**部位集合**而不是变体名
    expect(screen.getAllByTestId(/^variant-row-/)).toHaveLength(1)
    const row = screen.getByTestId('variant-row-op-三边-布')
    expect(row).toHaveTextContent('布帘')
    expect(row).toHaveTextContent('帘头')
    expect(row).not.toHaveTextContent('布三边')
  })

  it('㉖-④ 能力不减（反向护栏）：改分组 / 单位 / 作用域 / 必完 / 停用 / 删除 **六项逐条仍可用**', async () => {
    await openManage('车被')
    const id = 'op-车被'

    // ① 改分组 + ② 改单位：铅笔 → 输入 → 保存 ⇒ body 恰为 `{group_name, unit}`（部分更新，不夹带别的字段）
    await userEvent.click(screen.getByTestId(`variant-meta-edit-${id}`))
    const groupInput = screen.getByTestId(`variant-group-input-${id}`)
    await userEvent.clear(groupInput)
    await userEvent.type(groupInput, '后道2')
    const unitInput = screen.getByTestId(`variant-unit-input-${id}`)
    await userEvent.clear(unitInput)
    await userEvent.type(unitInput, '个')
    await userEvent.click(screen.getByTestId(`variant-meta-save-${id}`))
    await waitFor(() =>
      expect(mockUpdateOperation).toHaveBeenCalledWith(id, { group_name: '后道2', unit: '个' }),
    )
    expect(Object.keys(mockUpdateOperation.mock.calls[0][1] as object)).toEqual(['group_name', 'unit'])

    // ③ 改作用域 / ④ 改必完 / ⑤ 停用：各只带自己的字段（`PUT /operations/{id}`）
    await userEvent.selectOptions(screen.getByTestId(`variant-scope-${id}`), 'position')
    await waitFor(() => expect(mockUpdateOperation).toHaveBeenCalledWith(id, { scope: 'position' }))
    await userEvent.click(screen.getByTestId(`variant-must-finish-${id}`))
    await waitFor(() => expect(mockUpdateOperation).toHaveBeenCalledWith(id, { is_must_finish: false }))
    await userEvent.click(screen.getByTestId(`variant-disable-${id}`))
    await waitFor(() => expect(mockUpdateOperation).toHaveBeenCalledWith(id, { status: 'inactive' }))

    // ⑥ 删除：二次确认后才发 `DELETE /operations/{id}`（逐条护栏理由的就地展示见 ⑰-⑬）
    await userEvent.click(screen.getByTestId(`variant-delete-${id}`))
    expect(mockDeleteOperation).not.toHaveBeenCalled()
    await userEvent.click(screen.getByTestId(`variant-delete-confirm-${id}`))
    await waitFor(() => expect(mockDeleteOperation).toHaveBeenCalledWith(id))
  })

  it('㉖-⑤ 抽屉标题/说明改成商家语言：以「部位」为主标识，不再出现「变体 / 工人扫码时看到的工序」', async () => {
    await openManage('三边')

    // 标题 = 商家语言（含这道工序的名字，但不说「变体」）
    expect(screen.getByRole('dialog', { name: '「三边」在各部位的设置' })).toBeInTheDocument()

    const drawer = screen.getByTestId('operations-manage-drawer')
    expect(drawer).not.toHaveTextContent('变体')
    expect(drawer).not.toHaveTextContent('工人扫码')
    expect(drawer.textContent ?? '').not.toContain('布三边')

    // #4610 的「必完」解释**保留**（一字不动）
    expect(drawer).toHaveTextContent('必完：缺这道工序不能打包')
    expect(drawer).toHaveTextContent('部位级工序要每个部位都做完')
  })

  it('⑰-⑫ 抽屉：该逻辑工序查不到任何设置（6 键全 null）⇒ 可读提示，不空白、不发明数据', async () => {
    await openManage('韩褶')
    expect(screen.queryByTestId(/^variant-row-/)).toBeNull()
    const empty = screen.getByTestId('operations-manage-empty')
    expect(empty).toHaveTextContent('还没有设置')
    // issue #4622：提示也用商家语言（不得再写「变体 / 工人端」这类内部术语）
    expect(empty).not.toHaveTextContent('变体')
    expect(empty).not.toHaveTextContent('工人端')
  })

  it('⑰-⑬ 删除工序：**二次确认**后才发 `DELETE /operations/{id}`；护栏理由逐条就地展示', async () => {
    mockDeleteOperation
      .mockReset()
      .mockRejectedValueOnce(guardError(['被活跃路线「窗帘工序路线（默认）」引用，请先改主线', '该部位仍是「做」，请先设为不做']))
    await openManage('精裁')

    await userEvent.click(screen.getByTestId('variant-delete-op-精裁-布'))
    // 二次确认：只是展开确认，**未**发请求
    expect(mockDeleteOperation).not.toHaveBeenCalled()
    await userEvent.click(screen.getByTestId('variant-delete-confirm-op-精裁-布'))

    await waitFor(() => expect(mockDeleteOperation).toHaveBeenCalledWith('op-精裁-布'))
    const reasons = await screen.findByTestId('variant-delete-reasons')
    expect(reasons).toHaveTextContent('请先改主线')
    expect(reasons).toHaveTextContent('请先设为不做')
  })

  it('⑰-⑭ 删除工序（成功）：确认后 DELETE + 刷新（不静默）', async () => {
    await openManage('精裁')
    await userEvent.click(screen.getByTestId('variant-delete-op-精裁-纱'))
    await userEvent.click(screen.getByTestId('variant-delete-confirm-op-精裁-纱'))

    await waitFor(() => expect(mockDeleteOperation).toHaveBeenCalledWith('op-精裁-纱'))
    await waitFor(() => expect(mockGetOperationPositions).toHaveBeenCalledTimes(2))
  })

  it('⑰-⑮ 删除工序：确认框可取消 —— 取消后不发 DELETE', async () => {
    await openManage('精裁')
    await userEvent.click(screen.getByTestId('variant-delete-op-精裁-布'))
    await userEvent.click(screen.getByTestId('variant-delete-cancel-op-精裁-布'))

    expect(mockDeleteOperation).not.toHaveBeenCalled()
    expect(screen.queryByTestId('variant-delete-confirm-op-精裁-布')).toBeNull()
  })

  it('⑰-⑯ 适用条件：删除（二次确认后 `DELETE /route-rules/{id}`）', async () => {
    const section = await openConditions('韩褶')
    const r1 = within(section).getByTestId('operation-condition-1')
    expect(within(r1).getByTestId('operation-condition-delete-1')).toBeInTheDocument()

    await userEvent.click(screen.getByTestId('operation-condition-delete-1'))
    expect(mockDeleteRouteRule).not.toHaveBeenCalled()
    await userEvent.click(screen.getByTestId('route-rule-delete-confirm-1'))

    await waitFor(() => expect(mockDeleteRouteRule).toHaveBeenCalledWith(1))
    await waitFor(() => expect(mockGetRouteRules).toHaveBeenCalledTimes(2))
  })

  it('⑰-⑰ 适用条件：删除被拒 ⇒ 护栏理由逐条就地展示', async () => {
    mockDeleteRouteRule.mockReset().mockRejectedValueOnce(guardError(['规则已被订单引用', '请先停用该选项']))
    await openConditions('韩褶')

    await userEvent.click(screen.getByTestId('operation-condition-delete-1'))
    await userEvent.click(screen.getByTestId('route-rule-delete-confirm-1'))

    const reasons = await screen.findByTestId('route-rule-delete-reasons')
    expect(reasons).toHaveTextContent('规则已被订单引用')
    expect(reasons).toHaveTextContent('请先停用该选项')
  })

  // ══════════════════ ⑱ 「添加条件」入口（issue #4616 的入口，issue #4650 起挂在工序抽屉里）══════════════════
  //
  // 用户裁定：「现在的问题是**没有入口往条件工序规则中添加新的工艺和加工项**」——
  // 缺了入口 ⇒ 商家新增工艺/加工项后**无法**让它在订单里插/删工序 ⇒ 该订单**静默少工序**。
  // #4650 阶段 1：入口从独立规则表**搬到工序抽屉**，且只问**两件事**（什么时候 / 做还是不做）。

  it('⑱-① 「添加条件」入口 ⇒ 建**工艺**触发条件，body 带 trigger_kind/action/operation', async () => {
    await openConditions('三边')

    await userEvent.click(screen.getByTestId('operation-condition-add'))
    await waitFor(() => expect(screen.getByTestId('operation-condition-form')).toBeInTheDocument())
    // 默认「什么时候」= 工艺；取值**从工艺列表取**（下拉，不是手输）
    expect(screen.getByTestId('condition-kind-craft')).toHaveAttribute('aria-checked', 'true')
    await userEvent.selectOptions(screen.getByTestId('condition-value'), '罗马帘')
    await userEvent.selectOptions(screen.getByTestId('condition-anchor'), '精裁')
    await userEvent.click(screen.getByTestId('condition-add-submit'))

    await waitFor(() =>
      expect(mockCreateOptionRule).toHaveBeenCalledWith({
        trigger_kind: 'craft',
        trigger_value: '罗马帘',
        action: 'insert',
        operation: '三边',
        after_operation: '精裁',
      }),
    )
    // 建完 load() 刷新 ⇒ 新条件立刻出现在该工序的「适用条件」里
    await waitFor(() => expect(mockGetRouteRules).toHaveBeenCalledTimes(2))
  })

  it('⑱-② 建**加工项**触发条件：取值取自加工项目录（下拉）', async () => {
    await openConditions('三边')

    await userEvent.click(screen.getByTestId('operation-condition-add'))
    await userEvent.click(screen.getByTestId('condition-kind-processing_item'))
    await userEvent.selectOptions(screen.getByTestId('condition-value'), '拼接')
    await userEvent.click(screen.getByTestId('condition-add-submit'))

    await waitFor(() =>
      expect(mockCreateOptionRule).toHaveBeenCalledWith({
        trigger_kind: 'processing_item',
        trigger_value: '拼接',
        action: 'insert',
        operation: '三边',
        after_operation: '精裁',
      }),
    )
  })

  it('⑱-③ 「什么时候」切换 ⇒ 取值来源随之变（三档**都是下拉**，选项逐字来自对应来源）', async () => {
    await openConditions('韩褶')
    await userEvent.click(screen.getByTestId('operation-condition-add'))

    // 默认「工艺」⇒ 选项 = 活跃工艺词表
    expect(screen.getByTestId('condition-value').tagName).toBe('SELECT')
    expect(within(screen.getByTestId('condition-value')).getByRole('option', { name: '罗马帘' })).toBeInTheDocument()

    await userEvent.click(screen.getByTestId('condition-kind-processing_item'))
    expect(screen.getByTestId('condition-value').tagName).toBe('SELECT')
    expect(within(screen.getByTestId('condition-value')).getByRole('option', { name: '拼接' })).toBeInTheDocument()
    // 切换 ⇒ 已选取值被清空（不把上一档的值带过去）
    expect(screen.getByTestId('condition-value')).toHaveValue('')

    // 特殊选项档的取值 = 既有选项名（**不手输**；新建选项走「新增 → 特殊选项」）
    await userEvent.click(screen.getByTestId('condition-kind-option'))
    expect(screen.getByTestId('condition-value').tagName).toBe('SELECT')
    expect(within(screen.getByTestId('condition-value')).getByRole('option', { name: '拼2次' })).toBeInTheDocument()
  })

  it('⑱-④ 「做还是不做」切到「不做」⇒ 「插在哪道工序之后」整块消失（不做没有位置）', async () => {
    await openConditions('韩褶')
    await userEvent.click(screen.getByTestId('operation-condition-add'))

    expect(screen.getByTestId('condition-anchor')).toBeInTheDocument()
    await userEvent.selectOptions(screen.getByTestId('condition-action'), 'remove')
    expect(screen.queryByTestId('condition-anchor')).toBeNull()
  })

  it('⑱-⑤ 本地预检：未选取值 ⇒ 逐条就地理由 + **不发请求**', async () => {
    await openConditions('韩褶')
    await userEvent.click(screen.getByTestId('operation-condition-add'))
    await userEvent.click(screen.getByTestId('condition-add-submit'))

    const reasons = await screen.findByTestId('condition-add-reasons')
    expect(reasons).toHaveTextContent('请选择什么时候生效')
    expect(mockCreateOptionRule).not.toHaveBeenCalled()
  })

  it('⑱-⑥ 后端 422 ⇒ 理由**逐条**就地展示，且**不刷新**、不改页面数据', async () => {
    mockCreateOptionRule
      .mockReset()
      .mockRejectedValueOnce(guardError(['工艺词表里没有活跃的「罗马帘」', '对客单价只属于特殊选项']))
    await openConditions('三边')
    await userEvent.click(screen.getByTestId('operation-condition-add'))
    await userEvent.selectOptions(screen.getByTestId('condition-value'), '罗马帘')
    await userEvent.click(screen.getByTestId('condition-add-submit'))

    const reasons = await screen.findByTestId('condition-add-reasons')
    expect(reasons).toHaveTextContent('工艺词表里没有活跃的「罗马帘」')
    expect(reasons).toHaveTextContent('对客单价只属于特殊选项')
    // 失败 ⇒ **不**刷新（静默写回 = 商家以为加上了、订单侧其实没生效）
    expect(mockGetRouteRules).toHaveBeenCalledTimes(1)
    // 表单仍在（理由要看得见、草稿不丢）
    expect(screen.getByTestId('operation-condition-form')).toBeInTheDocument()
  })

  // ══════════════════ ⑲ 删除改弹框（issue #4617）══════════════════
  //
  // 用户裁定：「确认删除的交互为什么不是弹框选择，交互需要优化」——
  // 同页此前两套形态并存：路线删除用弹框，规则/工序删除是**就地展开**的确认按钮。

  it('⑲-① 点条件「删除」⇒ **出现弹框**（不再就地展开），弹框里能读出删的是哪条', async () => {
    await openConditions('韩褶')

    await userEvent.click(screen.getByTestId('operation-condition-delete-1'))

    const modal = await screen.findByTestId('route-rule-delete-modal', {}, { timeout: 1500 })
    // 弹框用**人话**写清删的是哪一条（不是「触发类型 + 触发值 + 动作」那套配置术语）
    expect(modal).toHaveTextContent('工艺 = 韩褶 时插入（在「三边」之后）')
    expect(modal).toHaveAttribute('data-rule', '1')
    // 红证：改前这一格是**就地展开**的「确认删除 / 取消」两个按钮，`route-rule-delete-modal` 不存在
    expect(mockDeleteRouteRule).not.toHaveBeenCalled()
  })

  it('⑲-② 弹框「取消」⇒ **不发请求**，弹框消失', async () => {
    await openConditions('韩褶')
    await userEvent.click(screen.getByTestId('operation-condition-delete-1'))
    await userEvent.click(await screen.findByTestId('route-rule-delete-cancel-1', {}, { timeout: 1500 }))

    expect(mockDeleteRouteRule).not.toHaveBeenCalled()
    await waitFor(() => expect(screen.queryByTestId('route-rule-delete-modal')).toBeNull())
  })

  it('⑲-③ 删除中按钮禁用（重复点击不会发两次）', async () => {
    let resolveDelete: (v: unknown) => void = () => {}
    mockDeleteRouteRule.mockReset().mockImplementation(
      () => new Promise((resolve) => {
        resolveDelete = resolve
      }),
    )
    await openConditions('韩褶')
    await userEvent.click(screen.getByTestId('operation-condition-delete-1'))
    const confirm = await screen.findByTestId('route-rule-delete-confirm-1', {}, { timeout: 1500 })
    await userEvent.click(confirm)

    await waitFor(() => expect(mockDeleteRouteRule).toHaveBeenCalledTimes(1))
    // 删除中：确认按钮禁用（loading 态）+ 取消也禁用（不能把在飞的请求丢在半路）
    expect(screen.getByTestId('route-rule-delete-confirm-1')).toBeDisabled()
    expect(screen.getByTestId('route-rule-delete-cancel-1')).toBeDisabled()
    // 再点一次不会发第二次请求（按钮已禁用 ⇒ userEvent 点不动）
    await userEvent.click(screen.getByTestId('route-rule-delete-confirm-1'))
    expect(mockDeleteRouteRule).toHaveBeenCalledTimes(1)

    resolveDelete(ok({ id: 1, deleted: true }))
  })

  it('⑲-④ 删除被拒 ⇒ 理由**逐条**在弹框里就地展示（不吞成一句「删除失败」）', async () => {
    mockDeleteRouteRule.mockReset().mockRejectedValueOnce(guardError(['规则已被订单引用', '请先停用该选项']))
    await openConditions('韩褶')
    await userEvent.click(screen.getByTestId('operation-condition-delete-1'))
    await userEvent.click(await screen.findByTestId('route-rule-delete-confirm-1', {}, { timeout: 1500 }))

    const reasons = await screen.findByTestId('route-rule-delete-reasons')
    expect(reasons).toHaveTextContent('规则已被订单引用')
    expect(reasons).toHaveTextContent('请先停用该选项')
    // 失败后弹框仍在（理由要看得见）
    expect(screen.getByTestId('route-rule-delete-modal')).toBeInTheDocument()
  })

  it('⑲-⑤ 工序删除（抽屉那处）**同一套弹框**：弹框写清删的是哪一道', async () => {
    await openManage('精裁')

    await userEvent.click(screen.getByTestId('variant-delete-op-精裁-布'))

    const modal = await screen.findByTestId('variant-delete-modal', {}, { timeout: 1500 })
    // 主标识 = **部位**（issue #4622：变体名不上界面 —— 改前这里断言的是 `精裁-布`）
    expect(modal).toHaveTextContent('布帘')
    expect(modal).not.toHaveTextContent('精裁-布')
    expect(modal).toHaveAttribute('data-variant', 'op-精裁-布')
    expect(mockDeleteOperation).not.toHaveBeenCalled()

    // 取消 ⇒ 不发请求
    await userEvent.click(screen.getByTestId('variant-delete-cancel-op-精裁-布'))
    expect(mockDeleteOperation).not.toHaveBeenCalled()
    await waitFor(() => expect(screen.queryByTestId('variant-delete-modal')).toBeNull())
  })

  /**
   * issue #4665 ①：**发现性失败** —— 做/不做开关只藏在主表格的 `⇄` 里，而商家此刻在抽屉里
   * （弹框让他「先去设为不做」）⇒ 抽屉必须**直接**能看到并改做/不做。
   *
   * 红证（改前）：抽屉里没有 `drawer-applicable-*` 控件 ⇒ 本用例红（找不到 testid）。
   */
  it('#4665-A 抽屉里能**直接**看到并改「做 / 不做」（不再只有主表格的 ⇄）', async () => {
    await openManage('精裁')
    const row = screen.getByTestId('variant-row-op-精裁-布')
    expect(row).toBeInTheDocument()

    // 每个部位一格，且**文字可见**（不靠 hover/title 才知道是什么）
    const cloth = screen.getByTestId('drawer-applicable-精裁-布帘')
    expect(cloth).toHaveTextContent('做')
    expect(cloth).toHaveAccessibleName('布帘 改成不做这道工序')

    // 点「做」⇒ 改成不做：同一端点，body **只带** `{applicable:false}`
    await userEvent.click(cloth)
    await waitFor(() =>
      expect(mockUpdateOperationPosition).toHaveBeenCalledWith('pos-精裁-布帘', { applicable: false }),
    )
    expect(Object.keys(mockUpdateOperationPosition.mock.calls[0][1] as object)).toEqual(['applicable'])

    // 点「不做」⇒ 切回做（`{applicable:true}`）
    mockUpdateOperationPosition.mockClear()
    await userEvent.click(screen.getByTestId('drawer-applicable-精裁-帘头'))
    await waitFor(() =>
      expect(mockUpdateOperationPosition).toHaveBeenCalledWith('pos-精裁-帘头', { applicable: true }),
    )
    expect(Object.keys(mockUpdateOperationPosition.mock.calls[0][1] as object)).toEqual(['applicable'])
  })

  it('#4665-A2 抽屉的做/不做是**三态**：不做 / 未定价（≠ ¥0.00）/ ¥x.xx 各自可见', async () => {
    await openManage('精裁')
    // 控件文字 = 做/不做；**价**并排渲染（三态**不同形**）
    expect(screen.getByTestId('drawer-applicable-精裁-帘头')).toHaveTextContent('不做')
    expect(screen.getByTestId('drawer-applicable-精裁-布帘')).toHaveTextContent('做')
    expect(screen.getByTestId('drawer-price-精裁-布帘')).toHaveTextContent('¥8.50')
    expect(screen.getByTestId('drawer-price-精裁-纱帘')).toHaveTextContent('¥6.00')
    // `不做` 的格**不报**一个价（不做 ≠ ¥0.00）
    expect(screen.getByTestId('drawer-price-精裁-帘头')).toHaveTextContent('')
  })

  it('#4665-A3 「未定价」（做但没价）**不得**渲染成 ¥0.00（与 `不做`、真价三态不同形）', async () => {
    await openManage('三边')
    // 三边 × 纱帘：applicable=true 且 unit_price=null ⇒ 「未定价」（≠ ¥0.00）
    const unpriced = screen.getByTestId('drawer-price-三边-纱帘')
    expect(unpriced).toHaveTextContent('未定价')
    expect(unpriced).not.toHaveTextContent('¥0.00')
    // 同一抽屉里「做 + 真价」也在（三边 × 布帘 ¥1.20）⇒ 两种态同屏可辨
    expect(screen.getByTestId('drawer-price-三边-布帘')).toHaveTextContent('¥1.20')
    expect(screen.getByTestId('drawer-applicable-三边-布帘')).toHaveTextContent('做')
  })

  /**
   * issue #4665 ②：删除的前置（把相关格设为不做）**系统自己做** —— 弹框给**一键**
   * 「设为不做并删除」，把受影响的格设为 `applicable=false` 然后删工序（后端**一次事务**）。
   *
   * 红证（改前）：弹框里没有 `variant-detach-and-delete-*` ⇒ 本用例红；且改前只能手工两步。
   */
  it('#4665-B 一键「设为不做并删除」：`DELETE` 带 `detach_positions=true`，工序真被删', async () => {
    await openManage('精裁')
    await userEvent.click(screen.getByTestId('variant-delete-op-精裁-布'))
    const modal = await screen.findByTestId('variant-delete-modal', {}, { timeout: 1500 })

    // 文案要说清**将发生什么**（设为不做 + 历史报工不受影响）
    expect(modal).toHaveTextContent('设为不做')
    expect(modal).toHaveTextContent('历史报工不受影响')

    // 一键按钮存在，且点击前**不发请求**
    const oneClick = screen.getByTestId('variant-detach-and-delete-op-精裁-布')
    expect(mockDeleteOperation).not.toHaveBeenCalled()
    await userEvent.click(oneClick)

    // 一次调用带上 `detach_positions`（原子：后端同一事务里先摘格再删）
    await waitFor(() =>
      expect(mockDeleteOperation).toHaveBeenCalledWith('op-精裁-布', { detachPositions: true }),
    )
    // 删除成功后弹框收摊（不静默留在半完成态）
    await waitFor(() => expect(screen.queryByTestId('variant-delete-modal')).toBeNull())
    await waitFor(() => expect(mockGetOperationPositions).toHaveBeenCalledTimes(2))
  })

  /**
   * 反向护栏（issue #4665 明确要求）：**主线那一条不得被一键按钮绕过**。
   *
   * 主线涉及车间顺序，必须人工确认 —— 后端护栏①（活跃路线主线）对 `detach_positions=true`
   * **照样拦**（本用例用真实后端语义的 422 打桩：理由里只有主线，没有矩阵格）。
   * 一键按钮不得让工序消失，且理由必须**逐条就地**展示。
   */
  it('#4665-C 反向护栏：主线命中 ⇒ 一键「设为不做并删除」**也被拦**（工序不被删）', async () => {
    mockDeleteOperation.mockReset().mockRejectedValueOnce(
      guardError(['工序「精裁」还在活跃路线「窗帘工序路线（默认）」的主线里 —— 先改主线（把它从该路线去掉），再删它']),
    )
    await openManage('精裁')
    await userEvent.click(screen.getByTestId('variant-delete-op-精裁-布'))
    await userEvent.click(screen.getByTestId('variant-detach-and-delete-op-精裁-布'))

    await waitFor(() =>
      expect(mockDeleteOperation).toHaveBeenCalledWith('op-精裁-布', { detachPositions: true }),
    )
    // 主线理由**就地**展示（不吞成一句「删除失败」）
    const reasons = await screen.findByTestId('variant-delete-reasons')
    expect(reasons).toHaveTextContent('先改主线')
    // 被拦 ⇒ 弹框仍在（不是静默半完成），且抽屉里的工序**还在**
    expect(screen.getByTestId('variant-delete-modal')).toBeInTheDocument()
    expect(screen.getByTestId('variant-row-op-精裁-布')).toBeInTheDocument()
    // 矩阵**没有被偷偷改成不做**（护栏拦下时不许发生副作用）
    expect(mockUpdateOperationPosition).not.toHaveBeenCalled()
  })

  /**
   * issue #4665 C（用户实测追加「**依然删不干净**」）：删除后**表格里那一行必须消失**。
   *
   * <p>根因在后端：工序软删了、**矩阵行还在** ⇒ 工艺项表格（按矩阵读面成行）照旧显示它。
   * 后端已在同一事务里级联软删矩阵行；本用例从**用户面**钉住结果 —— 删成功后重新拉矩阵，
   * 那一行**不在**了（红证：改前 `matrix-row-精裁` 仍在）。</p>
   */
  it('#4665-C 一键删除后**表格里那一行消失**（级联软删矩阵行；改前「删成功但行还在」）', async () => {
    // 读面序列：首次（渲染）返回全量；删除后的那次刷新 = 后端已级联软删 ⇒ **不含**「精裁」
    mockGetOperationPositions
      .mockReset()
      .mockResolvedValueOnce(ok(POSITIONS))
      .mockResolvedValue(ok(POSITIONS.filter((c) => c.operation !== '精裁')))
    await openManage('精裁')
    expect(screen.getByTestId('matrix-row-精裁')).toBeInTheDocument()

    await userEvent.click(screen.getByTestId('variant-delete-op-精裁-布'))
    await userEvent.click(screen.getByTestId('variant-detach-and-delete-op-精裁-布'))
    await waitFor(() =>
      expect(mockDeleteOperation).toHaveBeenCalledWith('op-精裁-布', { detachPositions: true }),
    )
    // 后端级联软删后，读面不再返回「精裁」的格 ⇒ 表格里那一行消失（红证：改前它还在）
    await waitFor(() => expect(screen.queryByTestId('matrix-row-精裁')).toBeNull())
    // 反向：别的行不受影响（不是「整张表被清空」）
    expect(screen.getByTestId('matrix-row-三边')).toBeInTheDocument()
  })

  it('⑰-⑱ 文案：这一屏的价叫「计件单价（给工人）」+ 两本账一句话；不出现「加工费」「对客价」', async () => {
    await renderOperations()
    const text = screen.getByTestId('craft-operations-panel').textContent ?? ''

    expect(text).toContain('计件单价（给工人）')
    expect(text).toContain('报工工资 = 数量 × 计件单价')
    expect(text).toContain('收顾客')
    expect(text).toContain('加工项组合费用')
    // issue #4650 阶段 1：对客的那笔钱指到**工序的「适用条件」**（独立规则表已从界面移除）
    expect(text).toContain('适用条件')
    expect(text).not.toContain('条件工序规则')
    // 用户裁定 A：这一屏的价是**给工人**的计件单价 —— 不得叫成「加工费 / 对客价」
    expect(text).not.toContain('加工费')
    expect(text).not.toContain('对客价')
  })

  it('⑰-⑲ 新增工序：入口**只在页头**（`POST /operations` 后刷新）—— 面板内重复入口已移除（issue #4615）', async () => {
    await renderOperations()

    // 入口 = 页头那个（`routings-new-operation`）；文案已按用户裁定改成「新增工序」
    const entry = screen.getByTestId('routings-new-operation')
    expect(entry).toHaveTextContent('新增工序')
    // 反向断言（issue #4615）：面板内那个**同功能的重复按钮已删除**（改前必红）
    expect(screen.queryByTestId('operations-new-operation')).toBeNull()

    await userEvent.click(entry)
    await waitFor(() => expect(screen.getByTestId('create-kind-operation')).toBeInTheDocument())
    await userEvent.type(screen.getByTestId('routings-create-op-name'), '罗马帘-穿杆')
    await userEvent.type(screen.getByTestId('routings-create-op-group_name'), '车位')
    await userEvent.type(screen.getByTestId('routings-create-op-unit'), '套')
    await userEvent.type(screen.getByTestId('routings-create-op-unit_price'), '4.5')
    await userEvent.click(screen.getByTestId('routings-create-operation-submit'))

    await waitFor(() =>
      expect(mockCreateOperation).toHaveBeenCalledWith({
        name: '罗马帘-穿杆',
        group_name: '车位',
        unit: '套',
        unit_price: 4.5,
        // issue #4614：不带部位 = 新工序没有矩阵行 ⇒「工艺项」表里看不到它（无处可见的孤儿）
        positions: ['布帘', '纱帘', '帘头'],
      }),
    )
    await waitFor(() => expect(mockGetOperationPositions).toHaveBeenCalledTimes(2))
  })

  it('㉖-⑥ 「新增工序」对话框不再示范「名字里带部位」的旧写法（issue #4622 范围补口）', async () => {
    await renderOperations()
    await userEvent.click(screen.getByTestId('routings-new-operation'))
    await waitFor(() => expect(screen.getByTestId('create-kind-operation')).toBeInTheDocument())

    // ① placeholder 不再示范部位后缀（改前是 `如 罗马帘-穿杆`）
    const ph = screen.getByTestId('routings-create-op-name').getAttribute('placeholder') ?? ''
    expect(ph).toBe('如 罗马帘穿杆')
    expect(ph).not.toMatch(/-布|-纱|布帘|纱帘|帘头/)

    // ② 工序名称旁有**商家语言的**提示：工序名不要带部位（部位在下面勾选）
    const hint = screen.getByTestId('routings-create-op-name-hint')
    expect(hint).toHaveTextContent('不要带部位')
    expect(hint).toHaveTextContent('部位在下面勾选')
    // 提示本身不得举变体名当例子（那会把变体名又带回这一屏）
    expect(hint.textContent ?? '').not.toContain('布三边')

    // ③ 只治文案误导：**不新增阻断式校验**（#4614 的「至少勾一个部位」预检与默认勾选不变）
    expect(screen.getByTestId('routings-create-op-position-布帘')).toBeChecked()
  })

  it('⑳ 矩阵空态指向**右上**入口（issue #4615：入口换位置后不得留下死引用）', async () => {
    mockGetOperationPositions.mockReset().mockResolvedValue(ok([]))
    await renderOperations()

    const empty = screen.getByTestId('operation-price-matrix-empty')
    expect(empty).toHaveTextContent('点右上「新增工序」建一道')
    expect(empty).not.toHaveTextContent('点上方')
  })

  it('路线半边：主线逐道渲染 —— 「必完」按**矩阵聚合**（issue #4622 补口②），不发明别的库口径元数据', async () => {
    await renderOnRoutes()
    await waitFor(() => expect(screen.getByTestId('routing-step-11-1')).toBeInTheDocument())

    // 逻辑工序名「精裁」：矩阵里两格都必完 ⇒ chip 显示「必完」
    // （改前读的是按**变体名**索引的工序库 ⇒ `精裁` 查不到 ⇒ 这枚标记基本显示不出来）
    const logical = screen.getByTestId('routing-step-11-1')
    expect(logical).toHaveTextContent('精裁')
    expect(logical).not.toHaveTextContent('¥')
    expect(logical).toHaveTextContent('必完')
    // 「三边」矩阵里都不必完 ⇒ 不显示（不得发明「非必完」这类新词）
    expect(screen.getByTestId('routing-step-11-2')).not.toHaveTextContent('必完')
    // 「外帘装袋」（部位无关工序）矩阵里**有**它的行且必完 ⇒ 也显示「必完」
    // （它与工序库同名，但**判据不是名字** —— issue #4622 补口② 起一律按矩阵聚合）
    expect(screen.getByTestId('routing-step-11-3')).toHaveTextContent('外帘装袋')
    expect(screen.getByTestId('routing-step-11-3')).toHaveTextContent('必完')
    expect(screen.getByTestId('routing-step-11-3')).not.toHaveTextContent('¥')
    // 空壳那条没有步骤可渲染
    expect(screen.queryByTestId('routing-step-12-1')).toBeNull()
  })

  it('㉖-⑦ 主线预检的存在性判定按**逻辑名域**（改前「工序库 ∪ 矩阵」并集 ⇒ 残留的变体名被误判为「存在」）', async () => {
    // 存量数据：主线里残留变体名 `精裁-布`，而它在**工序库**里有同名行（旧口径据此判「存在」）
    mockGetRoutings.mockReset().mockResolvedValue(
      ok({
        total: 1,
        routings: [
          { id: 11, name: '窗帘工序路线（默认）', is_default: true, positions: ['布帘'], mainline: ['精裁', '精裁-布'], status: 'active' },
        ],
      }),
    )
    await renderOnRoutes()
    await waitFor(() => expect(screen.getByTestId('routing-step-11-2')).toBeInTheDocument())

    // 只读 chip：变体名 ⇒ 标红并指名；合法逻辑名 ⇒ 不得误报
    expect(screen.getByTestId('routing-step-11-2')).toHaveTextContent('工序库中不存在或已停用')
    expect(screen.getByTestId('routing-step-11-1')).not.toHaveTextContent('工序库中不存在')

    // 编辑态草稿行同口径（同一份 `missing`）
    await userEvent.click(screen.getByTestId('routing-edit-11'))
    const missing = await screen.findByTestId('routing-draft-missing-11-2')
    expect(missing).toHaveTextContent('工序库中不存在')
    expect(screen.queryByTestId('routing-draft-missing-11-1')).toBeNull()
  })

  it('㉖-⑧ 主线 chip 的「必完」按**矩阵聚合**三态：全必完 / 部分部位（title 列部位）/ 无', async () => {
    // 矩阵：精裁 两格都必完；车被 **部分部位**必完（布帘必完 / 纱帘不必完）；三边 都不必完
    mockGetOperationPositions.mockReset().mockResolvedValue(
      ok([
        { id: 'p1', operation: '精裁', position: '布帘', unit_price: 8.5, applicable: true, variant_operation_id: 'op-精裁-布', unit: '套', group: '裁剪', scope: 'position', is_must_finish: true },
        { id: 'p2', operation: '精裁', position: '纱帘', unit_price: 6, applicable: true, variant_operation_id: 'op-精裁-纱', unit: '套', group: '车位', scope: 'position', is_must_finish: true },
        { id: 'p3', operation: '车被', position: '布帘', unit_price: 0, applicable: true, variant_operation_id: 'op-车被', unit: '件', group: '后道', scope: 'set', is_must_finish: true },
        { id: 'p4', operation: '车被', position: '纱帘', unit_price: 1, applicable: true, variant_operation_id: 'op-车被-纱', unit: '件', group: '后道', scope: 'position', is_must_finish: false },
        { id: 'p5', operation: '三边', position: '布帘', unit_price: 1.2, applicable: true, variant_operation_id: 'op-三边-布', unit: '米', group: '车位', scope: 'position', is_must_finish: false },
      ]),
    )
    mockGetRoutings.mockReset().mockResolvedValue(
      ok({
        total: 1,
        routings: [
          { id: 11, name: '窗帘工序路线（默认）', is_default: true, positions: ['布帘'], mainline: ['精裁', '车被', '三边'], status: 'active' },
        ],
      }),
    )
    await renderOnRoutes()
    await waitFor(() => expect(screen.getByTestId('routing-step-11-1')).toBeInTheDocument())

    // ① 有必完元数据的格**全部**必完 ⇒ `必完`（不带「部分部位」）
    const all = screen.getByTestId('routing-step-must-finish-11-1')
    expect(all).toHaveTextContent('必完')
    expect(all).not.toHaveTextContent('部分部位')

    // ② **只有部分部位**必完 ⇒ 注明 + `title` **列出具体哪些部位**（不静默取第一个）
    const partial = screen.getByTestId('routing-step-must-finish-11-2')
    expect(partial).toHaveTextContent('必完（部分部位）')
    expect(partial.getAttribute('title')).toContain('布帘')
    expect(partial.getAttribute('title')).not.toContain('纱帘')

    // ③ 一道都不必完 ⇒ **不显示**（不得发明「非必完」这类新词）
    expect(screen.queryByTestId('routing-step-must-finish-11-3')).toBeNull()
    expect(screen.getByTestId('routing-step-11-3')).not.toHaveTextContent('必完')
  })

  it('主线 chips 与抽屉行**统一不显示单价**（#4583）：库口径可见的那道也不出现 ¥；抽屉保留 分组 · 单位', async () => {
    await renderOnRoutes()
    await waitFor(() => expect(screen.getByTestId('routing-step-11-3')).toBeInTheDocument())

    // ① 部位无关工序（`外帘装袋`）⇒ 也不得出现 ¥；矩阵里没有它的行 ⇒ 「必完」判不了（静默 = 未知）
    const resolvedChip = screen.getByTestId('routing-step-11-3')
    expect(resolvedChip).toHaveTextContent('外帘装袋')
    expect(resolvedChip).not.toHaveTextContent('¥')
    // ② 逻辑名那道同样只有名字（与 ① 口径一致 —— 显示与否不再取决于「两套名字是否恰好一致」）
    const logicalChip = screen.getByTestId('routing-step-11-1')
    expect(logicalChip).toHaveTextContent('精裁')
    expect(logicalChip).not.toHaveTextContent('¥')

    await userEvent.click(screen.getByTestId('routing-edit-11'))
    const resolvedDraft = screen.getByTestId('routing-draft-step-11-3')
    expect(resolvedDraft).not.toHaveTextContent('¥')
    // 抽屉仍保留 分组 · 单位（去掉的**只有**单价）
    expect(resolvedDraft).toHaveTextContent('后道')
    expect(resolvedDraft).toHaveTextContent('件')
    // 逻辑名那行没有库口径 ⇒ 连 分组 · 单位 也没有（静默 = 未知，不得发明）
    expect(screen.getByTestId('routing-draft-step-11-1')).not.toHaveTextContent('¥')
  })

  it('序列编辑：添加工序 → 保存 ⇒ `PUT {mainline:[...]}` 顺序等于屏幕顺序（加进去的是**逻辑名**，#4609）', async () => {
    await renderOnRoutes()
    await waitFor(() => expect(screen.getByTestId('routing-edit-11')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('routing-edit-11'))
    expect(screen.getByTestId('routing-draft-step-11-1')).toHaveTextContent('精裁')

    await userEvent.selectOptions(screen.getByTestId('routing-add-select-11'), '车被')
    await userEvent.click(screen.getByTestId('routing-add-11'))
    await userEvent.click(screen.getByTestId('routing-save-11'))

    await waitFor(() =>
      expect(mockUpdateRouting).toHaveBeenCalledWith(11, { mainline: ['精裁', '三边', '外帘装袋', '车被'] }),
    )
    await waitFor(() => expect(mockGetRoutings).toHaveBeenCalledTimes(2))
    await waitFor(() => expect(screen.queryByTestId('routing-save-11')).not.toBeInTheDocument())
  })

  it('⑳ 下拉只列**逻辑工序名**（去重）：不出现 `精裁-布`/`布三边` 这类变体名（issue #4609）', async () => {
    await renderOnRoutes()
    await waitFor(() => expect(screen.getByTestId('routing-edit-11')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('routing-edit-11'))
    const select = screen.getByTestId('routing-add-select-11') as HTMLSelectElement
    const values = Array.from(select.options).map((o) => o.value)

    // 取值域 = 矩阵行键（**逻辑名**，服务端顺序）；`slice(1)` 去掉占位项（value=''）
    // 注入：数据源换回工序库 `catalog.groups[].operations`（35 条**变体名**）⇒ 本断言红
    expect(values.slice(1)).toEqual(['三边', '精裁', '车被', '韩褶', '外帘装袋'])
    // 同一逻辑工序**只出现一次**（`精裁` 在矩阵里有 3 格 ⇒ 选择器里仍只有 1 项）
    expect(values.filter((v) => v === '精裁')).toHaveLength(1)
    // 带部位后缀的变体名一律不出现
    expect(values.some((v) => v.includes('精裁-') || v === '布三边' || v === '纱三边')).toBe(false)
    // 显示形态 = 逻辑名 + 分组（分组取该行各格**公共值**，不一致时逐个列出 —— 不静默取第一个）
    expect(select.options[1].textContent).toBe('三边（车位）')
    expect(select.options[2].textContent).toBe('精裁（裁剪 / 车位）')
    // 库里查不到变体元数据的那道（`韩褶`）⇒ 只有名字，不发明分组
    expect(select.options[4].textContent).toBe('韩褶')
  })

  it('⑳ 选「精裁」加入 ⇒ 主线里存的是**逻辑名**（红证：改前下拉只有变体名，存的是 `精裁-布`）', async () => {
    await renderOnRoutes()
    // 空壳路线 12：加入一道即成为唯一一道 ⇒ 请求体一眼看出存的是哪把尺
    await waitFor(() => expect(screen.getByTestId('routing-edit-12')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('routing-edit-12'))
    const select = screen.getByTestId('routing-add-select-12') as HTMLSelectElement
    expect(
      Array.from(select.options).some((o) => o.value === '精裁'),
      '下拉里必须有逻辑工序名「精裁」这一项（改前只有变体名 精裁-布 / 精裁-纱）',
    ).toBe(true)

    await userEvent.selectOptions(select, '精裁')
    await userEvent.click(screen.getByTestId('routing-add-12'))
    expect(screen.getByTestId('routing-draft-step-12-1')).toHaveTextContent('精裁')
    await userEvent.click(screen.getByTestId('routing-save-12'))

    await waitFor(() => expect(mockUpdateRouting).toHaveBeenCalledWith(12, { mainline: ['精裁'] }))
  })

  it('序列编辑：下移/删除改变顺序后保存，请求体随之变化', async () => {
    await renderOnRoutes()
    await waitFor(() => expect(screen.getByTestId('routing-edit-11')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('routing-edit-11'))
    await userEvent.click(screen.getByTestId('routing-draft-down-11-1'))
    expect(screen.getByTestId('routing-draft-name-11-1')).toHaveTextContent('三边')
    await userEvent.click(screen.getByTestId('routing-draft-remove-11-3'))
    await userEvent.click(screen.getByTestId('routing-save-11'))

    await waitFor(() => expect(mockUpdateRouting).toHaveBeenCalledWith(11, { mainline: ['三边', '精裁'] }))
  })

  it('空主线：本地拦住不发请求，并说明为什么不能空', async () => {
    await renderOnRoutes()
    await waitFor(() => expect(screen.getByTestId('routing-edit-12')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('routing-edit-12'))
    await userEvent.click(screen.getByTestId('routing-save-12'))

    await waitFor(() => expect(screen.getByTestId('routing-error-12')).toBeInTheDocument())
    expect(screen.getByTestId('routing-error-item-0')).toHaveTextContent('不能为空')
    expect(mockUpdateRouting).not.toHaveBeenCalled()
  })

  it('保存被拒（主线护栏）：后端理由**逐条**展示，不合并成一句「保存失败」', async () => {
    mockUpdateRouting.mockReset().mockRejectedValueOnce(
      guardError([
        '工序「罗马帘-打孔」不在工序库中',
        '工序「精裁」在主线中重复出现 2 次',
        '路线至少要有一道必完工序（当前 0 道）',
      ]),
    )
    await renderOnRoutes()
    await waitFor(() => expect(screen.getByTestId('routing-edit-11')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('routing-edit-11'))
    await userEvent.click(screen.getByTestId('routing-save-11'))

    await waitFor(() => expect(screen.getByTestId('routing-error-11')).toBeInTheDocument())
    expect(within(screen.getByTestId('routing-error-11')).getAllByTestId(/^routing-error-item-/)).toHaveLength(3)
    expect(screen.getByTestId('routing-error-item-0')).toHaveTextContent('工序不存在')
    expect(screen.getByTestId('routing-error-item-1')).toHaveTextContent('工序重复')
    expect(screen.getByTestId('routing-error-item-2')).toHaveTextContent('缺少必完工序')
  })

  it('护栏就地预检：主线缺必完工序 ⇒ 黄条；但**判不了就不判**（逻辑名/库中缺失 ⇒ 静默 = 未知）', async () => {
    // 两道都能在工序库里查到、且都不是必完 ⇒ 判得动 ⇒ 黄条
    mockGetRoutings.mockReset().mockResolvedValue(
      ok({
        total: 1,
        routings: [
          { id: 11, name: '窗帘工序路线（默认）', is_default: true, positions: ['布帘'], mainline: ['韩褶-布', '裁剪-布'], status: 'active' },
        ],
      }),
    )
    await renderOnRoutes()
    await waitFor(() => expect(screen.getByTestId('routing-edit-11')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('routing-edit-11'))
    expect(screen.getByTestId('routing-precheck-11')).toHaveTextContent('必完')
    // 预检只是提示，不阻断保存（后端仍是唯一权威）
    expect(screen.getByTestId('routing-save-11')).toBeEnabled()
  })

  it('护栏就地预检：主线的逻辑工序名拿不到「必完」口径 ⇒ **不误报**黄条（未知 ≠ 违规）', async () => {
    await renderOnRoutes()
    await waitFor(() => expect(screen.getByTestId('routing-edit-11')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('routing-edit-11'))
    // 主线是逻辑名（精裁/三边）⇒ 工序库里查不到同名的 is_must_finish ⇒ 判不了就不判
    expect(screen.queryByTestId('routing-precheck-11')).toBeNull()
    expect(screen.queryByTestId('routing-precheck-missing-11')).toBeNull()
  })

  it('护栏就地预检：主线引用了矩阵里没有的工序 ⇒ 该行标红并指名（合法逻辑名**不误伤**）', async () => {
    mockGetRoutings.mockReset().mockResolvedValue(
      ok({
        total: 1,
        routings: [
          // ⚠️ issue #4622 补口① 起存在性按**矩阵的逻辑工序名**判 ⇒ 这里用**合法逻辑名** `精裁`
          // 作对照行（变体名 `韩褶-布` 现在**也会**被正确标红 —— 那由 ㉖-⑦ 专测）
          { id: 11, name: '窗帘工序路线（默认）', is_default: true, positions: ['布帘'], mainline: ['精裁', '罗马帘-打孔'], status: 'active' },
        ],
      }),
    )
    await renderOnRoutes()
    await waitFor(() => expect(screen.getByTestId('routing-edit-11')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('routing-edit-11'))
    await waitFor(() => expect(screen.getByTestId('routing-draft-missing-11-2')).toBeInTheDocument())
    expect(screen.getByTestId('routing-draft-missing-11-2')).toHaveTextContent('工序库中不存在')
    expect(screen.queryByTestId('routing-draft-missing-11-1')).toBeNull()
  })

  it('#4605 主线预检提示**不得**指向已取消的「工序库明细」，且要指向界面上真实存在的入口', async () => {
    // 病灶（#4588 漏改的死引用）：预检文案曾写「请先到「工艺项 · 工序库明细」补上」，
    // 而该折叠次区已随 #4588 取消 ⇒ 商家照着找**找不到入口**。
    mockGetRoutings.mockReset().mockResolvedValue(
      ok({
        total: 1,
        routings: [
          { id: 11, name: '窗帘工序路线（默认）', is_default: true, positions: ['布帘'], mainline: ['韩褶-布', '罗马帘-打孔'], status: 'active' },
        ],
      }),
    )
    await renderOnRoutes()
    await waitFor(() => expect(screen.getByTestId('routing-edit-11')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('routing-edit-11'))
    const precheck = await screen.findByTestId('routing-precheck-missing-11')
    // ① 不得再出现已取消的形态名（死引用）
    expect(precheck).not.toHaveTextContent('工序库明细')
    // ② 指向**真实存在**的入口：「工艺项」的「新增工序」按钮（同一页面另一 tab 的入口）
    expect(precheck).toHaveTextContent('新增工序')
  })

  it('新建路线：提交 `{name, positions, is_default}` 并自动进入主线编辑', async () => {
    mockGetRoutings
      .mockReset()
      .mockResolvedValueOnce(ok(ROUTINGS))
      .mockResolvedValue(
        ok({
          total: 3,
          routings: [...ROUTINGS.routings, { id: 13, name: '罗马帘专线', is_default: false, positions: ['布帘'], mainline: [], status: 'active' }],
        }),
      )
    await renderOnRoutes()
    await waitFor(() => expect(screen.getByTestId('routings-total')).toHaveTextContent('2'))

    await userEvent.click(screen.getByTestId('routings-new-route'))
    await userEvent.type(screen.getByTestId('routings-create-name'), '罗马帘专线')
    await userEvent.click(screen.getByTestId('routings-create-position-帘头')) // 取消勾选「帘头」
    await userEvent.click(screen.getByTestId('routings-create-route-submit'))

    await waitFor(() =>
      expect(mockCreateRouting).toHaveBeenCalledWith({ name: '罗马帘专线', positions: ['布帘', '纱帘'] }),
    )
    // 建壳后**自动进入主线编辑**（消灭「建了条空壳但没人知道」的静默态）
    await waitFor(() => expect(screen.getByTestId('routing-save-13')).toBeInTheDocument())
    expect(screen.getByTestId('routing-draft-empty-13')).toHaveTextContent('从工序库选择')
  })

  it('两个 tab 存在且默认落在「工艺项」；切换后内容互斥（不平铺）', async () => {
    render(<ProcessConfigPage />)
    await waitFor(() => expect(screen.getByTestId('process-config-tabs')).toBeInTheDocument())

    const opsTab = screen.getByTestId('process-config-tab-operations')
    const routesTab = screen.getByTestId('process-config-tab-routes')
    expect(opsTab).toHaveTextContent('工艺项')
    expect(routesTab).toHaveTextContent('工艺路线')
    expect(opsTab).toHaveAttribute('data-state', 'active')
    expect(screen.getByTestId('operation-price-matrix')).toBeInTheDocument()
    expect(screen.queryByTestId('routings-total')).not.toBeInTheDocument()

    await userEvent.click(routesTab)
    expect(routesTab).toHaveAttribute('data-state', 'active')
    expect(screen.queryByTestId('operation-price-matrix')).not.toBeInTheDocument()
    expect(screen.getByTestId('routings-total')).toBeInTheDocument()
  })

  it('切 tab **不丢状态**：在「工艺路线」编辑主线 → 切走 → 切回，draft 仍在', async () => {
    await renderOnRoutes()
    await waitFor(() => expect(screen.getByTestId('routing-edit-11')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('routing-edit-11'))
    await userEvent.selectOptions(screen.getByTestId('routing-add-select-11'), '车被')
    await userEvent.click(screen.getByTestId('routing-add-11'))
    expect(screen.getByTestId('routing-draft-step-11-4')).toHaveTextContent('车被')

    await userEvent.click(screen.getByTestId('process-config-tab-operations'))
    await userEvent.click(screen.getByTestId('process-config-tab-routes'))

    // 注入：把 draft 改成随 tab 重置 ⇒ 红
    expect(screen.getByTestId('routing-draft-step-11-4')).toHaveTextContent('车被')
    expect(screen.getByTestId('routing-save-11')).toBeInTheDocument()
  })

  it('只读端点失败不白屏：路线列表失败给提示 + 重试；工序库失败只在该区提示', async () => {
    mockGetRoutings.mockReset().mockRejectedValueOnce(new Error('500')).mockResolvedValue(ok(ROUTINGS))
    render(<ProcessConfigPage />)

    await waitFor(() => expect(screen.getByTestId('routings-error')).toHaveTextContent('工艺路线加载失败'))
    await userEvent.click(screen.getByTestId('routings-retry'))
    await userEvent.click(await screen.findByTestId('process-config-tab-routes'))
    await waitFor(() => expect(screen.getByTestId('routings-total')).toHaveTextContent('2'))
  })

  it('工序库加载失败不白屏：这一张表照常（表只依赖部位价目），抽屉不发明 provenance', async () => {
    mockGetOperationsCatalog.mockReset().mockRejectedValueOnce(new Error('500')).mockResolvedValue(ok(CATALOG))
    await renderOperations()

    // 表照常渲染真实价（工序库读面挂了不该把这一屏吞掉）
    expect(screen.getByTestId('matrix-cell-精裁-布帘')).toHaveTextContent('¥8.50')

    await userEvent.click(screen.getByTestId('matrix-manage-精裁'))
    await waitFor(() => expect(screen.getByTestId('operations-manage-drawer')).toBeInTheDocument())
    // 设置行来自矩阵（**部位**），不依赖工序库；provenance 查不到 ⇒ 不渲染徽标（静默 = 未知）
    const row = screen.getByTestId('variant-row-op-精裁-布')
    expect(row).toHaveTextContent('布帘')
    expect(row).not.toHaveTextContent('精裁-布')
    expect(screen.queryByTestId('variant-source-op-精裁-布')).toBeNull()
  })

  // ══════════════════ ⑪ 商家面不得出现内部机制名 ══════════════════

  it('工艺配置页不得出现「信号映射」这个概念：不渲染该区、不发起请求、页面文本无「信号」', async () => {
    render(<ProcessConfigPage />)
    await waitFor(() => expect(screen.getByTestId('operation-price-matrix')).toBeInTheDocument())

    for (const id of [
      'route-signals-section',
      'route-signals-toggle',
      'route-signals-body',
      'route-signals-error',
      'route-signals-empty',
      'route-signal-31',
      'route-signal-new',
      'routings-gap-signals',
    ]) {
      expect(screen.queryByTestId(id)).toBeNull()
    }
    expect(mockGetRouteSignals).not.toHaveBeenCalled()
    expect(document.body.textContent ?? '').not.toContain('信号')
  })

  // ══════════════════ ㉗ 「条件工序规则」概念从界面消失（issue #4650 阶段 1）══════════════════
  //
  // 用户裁定（逐字）：「**我要求移除条件工序规则**，这个概念我都难以理解，用户如何去理解？
  // 我们要做到**智能化的产品**，而不是旧时代配置化的产品」。
  //
  // 商家**不该**再看到一张要求他填「触发类型 / 触发值 / 部位限定 / 动作 / 目标工序 / 插入锚点 /
  // 优先级」的表；他只该看到 **工艺项（工序 + 部位 + 价）** 与 **每道工序「在什么情况下做」**（一句人话）。
  //
  // 阶段 1 是**零迁移 + 行为不变**的纯呈现改造：
  // - 后端 `GET/POST/DELETE /route-rules` **端点保留**（阶段 2 的 AI 入口与阶段 4 的承载收敛还要用）；
  // - `production_route_rules` **一行不动**（页面加载**零写请求**）；
  // - 条件的**呈现与编辑落点**从「独立规则表」搬到**工序抽屉**里的「适用条件」一节。

  it('㉗-① 工艺配置页**任何 tab** 都不再出现「条件工序规则」独立表（含标题/入口/表体）', async () => {
    await renderOnRoutes()

    // 红证：改前这一区是**常驻展开**的（`route-rules` / `route-rules-body` / `route-rules-total` /
    // 「新增规则」入口 `route-rules-new` 全都在）
    expect(screen.queryByTestId('route-rules')).toBeNull()
    expect(screen.queryByTestId('route-rules-body')).toBeNull()
    expect(screen.queryByTestId('route-rules-total')).toBeNull()
    expect(screen.queryByTestId('route-rules-new')).toBeNull()
    expect(screen.queryByTestId('route-rule-create-modal')).toBeNull()

    // 术语也不得出现（用户原话：「这个概念我都难以理解，用户如何去理解？」）
    const text = document.body.textContent ?? ''
    for (const banned of ['条件工序规则', '触发类型', '触发值', '部位限定', '插入锚点', '优先级', '新增规则']) {
      expect(text).not.toContain(banned)
    }
  })

  it('㉗-② 工序抽屉里**有**「适用条件」一节，且是**人话**（改前没有这一节）', async () => {
    await openManage('韩褶')

    const section = await screen.findByTestId('operation-conditions')
    expect(section).toHaveTextContent('适用条件')
    // 规则 1：craft 韩褶 → insert 韩褶，锚点 三边
    expect(screen.getByTestId('operation-condition-text-1')).toHaveTextContent('工艺 = 韩褶 时插入（在「三边」之后）')
    // 该工序**没有**的规则不得出现在它的抽屉里（按目标工序归属）
    expect(screen.queryByTestId('operation-condition-2')).toBeNull()
  })

  it('㉗-③ 人话三态：`不做` / `插入（在「X」之后）` / 无锚点 ⇒ 「追加到末尾」', async () => {
    mockGetRouteRules.mockReset().mockResolvedValue(
      ok([
        { id: 1, trigger_kind: 'craft', trigger_value: '韩褶', position: null, action: 'insert', operation: '韩褶', after_operation: '三边', priority: 10, status: 'active' },
        { id: 2, trigger_kind: 'craft', trigger_value: '打孔', position: '布帘', action: 'remove', operation: '车被', after_operation: null, priority: 20, status: 'active' },
        { id: 3, trigger_kind: 'option', trigger_value: '拼2次', position: '纱帘', action: 'insert', operation: '外帘装袋', after_operation: null, priority: 30, status: 'active' },
      ]),
    )
    await renderOperations()
    await userEvent.click(screen.getByTestId('matrix-manage-车被'))
    // 规则 2：craft 打孔 → remove 车被 ⇒ 「时不做」
    expect(await screen.findByTestId('operation-condition-text-2')).toHaveTextContent('工艺 = 打孔 时不做')

    await userEvent.click(screen.getByTestId('operations-manage-close'))
    await userEvent.click(screen.getByTestId('matrix-manage-外帘装袋'))
    // 规则 3：option 拼2次 → insert 外帘装袋，无锚点 ⇒ 「追加到末尾」（**不得**渲染成「在「末尾」之后」）
    const text = screen.getByTestId('operation-condition-text-3').textContent ?? ''
    expect(text).toContain('特殊选项 = 拼2次 时插入')
    expect(text).toContain('追加到末尾')
    expect(text).not.toContain('「末尾」')
  })

  it('㉗-④ 添加条件只问两件事（什么时候 / 做还是不做）⇒ 复用**现有**写面 `POST /route-rules`', async () => {
    await openManage('三边')
    await userEvent.click(screen.getByTestId('operation-condition-add'))

    // ① 「什么时候」= 种类（默认工艺）+ 取值（**从词表选，不手输** ⇒ SELECT）
    expect(screen.getByTestId('condition-kind-craft')).toHaveAttribute('aria-checked', 'true')
    expect(screen.getByTestId('condition-value').tagName).toBe('SELECT')
    await userEvent.selectOptions(screen.getByTestId('condition-value'), '罗马帘')
    // ② 「做还是不做」
    await userEvent.selectOptions(screen.getByTestId('condition-action'), 'insert')
    // ③ 插在哪道之后（可选项 + 默认值）
    await userEvent.selectOptions(screen.getByTestId('condition-anchor'), '精裁')
    await userEvent.click(screen.getByTestId('condition-add-submit'))

    await waitFor(() =>
      expect(mockCreateOptionRule).toHaveBeenCalledWith({
        trigger_kind: 'craft',
        trigger_value: '罗马帘',
        action: 'insert',
        operation: '三边',
        after_operation: '精裁',
      }),
    )
    // 成功 ⇒ load() 刷新（新条件立刻出现在该工序的「适用条件」里）
    await waitFor(() => expect(mockGetRouteRules).toHaveBeenCalledTimes(2))
  })

  it('㉗-⑤ 锚点默认值 = 该工序现有条件的锚点（**别让商家猜**），且「不做」时锚点整块不渲染', async () => {
    await openManage('韩褶')
    await userEvent.click(screen.getByTestId('operation-condition-add'))

    // 韩褶的现有插入条件锚点是「三边」（= 今天 routing.py 种子里该工序的锚点）⇒ 默认选中它
    expect(screen.getByTestId('condition-anchor')).toHaveValue('三边')

    await userEvent.selectOptions(screen.getByTestId('condition-action'), 'remove')
    expect(screen.queryByTestId('condition-anchor')).toBeNull()
  })

  it('㉗-⑥ 加工项触发：取值取自加工项目录（下拉）', async () => {
    await openManage('三边')
    await userEvent.click(screen.getByTestId('operation-condition-add'))
    await userEvent.click(screen.getByTestId('condition-kind-processing_item'))
    await userEvent.selectOptions(screen.getByTestId('condition-value'), '拼接')
    await userEvent.click(screen.getByTestId('condition-add-submit'))

    await waitFor(() =>
      expect(mockCreateOptionRule).toHaveBeenCalledWith({
        trigger_kind: 'processing_item',
        trigger_value: '拼接',
        action: 'insert',
        operation: '三边',
        after_operation: '精裁',
      }),
    )
  })

  it('㉗-⑦ 本地预检：未选取值 ⇒ 逐条就地理由 + **不发请求**（不改页面数据）', async () => {
    await openManage('三边')
    await userEvent.click(screen.getByTestId('operation-condition-add'))
    await userEvent.click(screen.getByTestId('condition-add-submit'))

    expect(await screen.findByTestId('condition-add-reasons')).toHaveTextContent('请选择')
    expect(mockCreateOptionRule).not.toHaveBeenCalled()
    expect(mockGetRouteRules).toHaveBeenCalledTimes(1)
  })

  it('㉗-⑧ 反向护栏（能力不减）：条件**删除**仍可用，且走**现有**端点 `DELETE /route-rules/{id}`', async () => {
    await openManage('韩褶')
    await userEvent.click(screen.getByTestId('operation-condition-delete-1'))

    const modal = await screen.findByTestId('route-rule-delete-modal', {}, { timeout: 1500 })
    // 弹框写清删的是**哪一条**（人话，不是「触发类型 + 动作」那套术语）
    expect(modal).toHaveTextContent('工艺 = 韩褶 时插入（在「三边」之后）')
    expect(modal).toHaveAttribute('data-rule', '1')
    expect(mockDeleteRouteRule).not.toHaveBeenCalled()

    await userEvent.click(screen.getByTestId('route-rule-delete-confirm-1'))
    await waitFor(() => expect(mockDeleteRouteRule).toHaveBeenCalledWith(1))
    await waitFor(() => expect(mockGetRouteRules).toHaveBeenCalledTimes(2))
  })

  it('㉗-⑨ 回归锁（零写面）：页面加载**不发任何写请求** —— `production_route_rules` 一行未动', async () => {
    await renderOnRoutes()

    expect(mockCreateOptionRule).not.toHaveBeenCalled()
    expect(mockDeleteRouteRule).not.toHaveBeenCalled()
    expect(mockUpdateRuleCustomerUnitPrice).not.toHaveBeenCalled()
    // 读面照旧（一次），且没有第二条规则读面端点被发明出来
    expect(mockGetRouteRules).toHaveBeenCalledTimes(1)
  })

  it('㉗-⑩ 回归锁（同一套规则配置逐项不变）：每条规则仍**逐条**出现在它目标工序的「适用条件」里', async () => {
    // 同一套规则配置（4 条：工艺 insert / 工艺 remove / 特殊选项 / 加工项）——
    // 搬走独立表**不得**丢规则、不得改归属、不得跨工序串味。
    mockGetRouteRules.mockReset().mockResolvedValue(
      ok([
        { id: 1, trigger_kind: 'craft', trigger_value: '韩褶', position: null, action: 'insert', operation: '韩褶', after_operation: '三边', priority: 10, status: 'active' },
        { id: 2, trigger_kind: 'craft', trigger_value: '打孔', position: '布帘', action: 'remove', operation: '韩褶', after_operation: null, priority: 20, status: 'active' },
        { id: 3, trigger_kind: 'option', trigger_value: '拼2次', position: '纱帘', action: 'insert', operation: '三边', after_operation: null, priority: 30, status: 'active' },
        { id: 4, trigger_kind: 'processing_item', trigger_value: '花边', position: null, action: 'insert', operation: '精裁', after_operation: '三边', priority: 40, status: 'active' },
      ]),
    )

    await renderOperations()
    // 逐工序：只列属于它自己的那几条，一条不多、一条不少
    const expected: Record<string, string[]> = {
      韩褶: ['工艺 = 韩褶 时插入（在「三边」之后）', '工艺 = 打孔 时不做'],
      三边: ['特殊选项 = 拼2次 时插入（追加到末尾）'],
      精裁: ['加工项 = 花边 时插入（在「三边」之后）'],
    }
    for (const [operation, texts] of Object.entries(expected)) {
      await userEvent.click(screen.getByTestId(`matrix-manage-${operation}`))
      const section = await screen.findByTestId('operation-conditions')
      expect(within(section).getAllByTestId(/^operation-condition-\d+$/)).toHaveLength(texts.length)
      for (const t of texts) expect(within(section).getByText(t)).toBeInTheDocument()
      await userEvent.click(screen.getByTestId('operations-manage-close'))
    }
  })

/**
 * ══════════════════ ⑫ 算料配置 tab（issue #4528 = 包 E） ══════════════════
 *
 * 判据（每条都能红）：
 * ① 切到本 tab ⇒ 发**一次** `GET`，渲染**引擎默认值**并标注「当前使用系统默认值」
 *    （把默认值伪装成商家配置 ⇒ 红；前端自带一份默认值 ⇒ 与后端逐值比对时红）；
 * ② 改一个参数 ⇒ `PUT` 带**全量 9 键**（缺键 = 让后端静默回默认值 ⇒ 红）；
 * ③ 非法值 ⇒ 后端 422 的**逐条**理由可见，且**不静默回退默认值**（草稿保持用户输入、不显示「已保存」⇒ 红）；
 * ④ 切 tab 不丢草稿（state 挂在本组件上）。
 */
describe('算料配置 tab（issue #4528）', () => {
  it('切到算料配置 tab ⇒ GET 一次 + 渲染引擎默认值 + 标注「当前使用系统默认值」', async () => {
    render(<ProcessConfigPage />)
    await waitFor(() => expect(screen.getByTestId('operation-price-matrix')).toBeInTheDocument())
    // 懒加载：没切过去之前**不**发请求
    expect(mockGetCraftCalcConfig).not.toHaveBeenCalled()

    await userEvent.click(screen.getByTestId('process-config-tab-calc'))

    await waitFor(() => expect(screen.getByTestId('craft-calc-config-panel')).toBeInTheDocument())
    expect(mockGetCraftCalcConfig).toHaveBeenCalledTimes(1)
    expect(screen.getByTestId('craft-calc-config-source')).toHaveTextContent('当前使用系统默认值')
    // 默认值来自**后端**（逐值渲染，前端不持有）
    expect(screen.getByTestId('craft-calc-config-scalar-per_fold_single')).toHaveValue(0.25)
    expect(screen.getByTestId('craft-calc-config-scalar-min_fullness')).toHaveValue(1.5)
    expect(screen.getByTestId('craft-calc-config-default_formula')).toHaveValue('pleat')
    expect(screen.getByTestId('craft-calc-config-tier-standard-fullness')).toHaveValue(2)
    expect(screen.getByTestId('craft-calc-config-mixed-1')).toHaveValue(0.65)
  })

  it('改「单色每折吃布」⇒ PUT 带全量 9 键（缺键会让后端静默回默认值）', async () => {
    render(<ProcessConfigPage />)
    await waitFor(() => expect(screen.getByTestId('operation-price-matrix')).toBeInTheDocument())
    await userEvent.click(screen.getByTestId('process-config-tab-calc'))
    await waitFor(() => expect(screen.getByTestId('craft-calc-config-panel')).toBeInTheDocument())

    const input = screen.getByTestId('craft-calc-config-scalar-per_fold_single')
    await userEvent.clear(input)
    await userEvent.type(input, '0.5')
    mockUpdateCraftCalcConfig.mockResolvedValueOnce(
      ok({ source: 'stored', config: { ...ENGINE_DEFAULT_CALC_CONFIG, per_fold_single: 0.5 } }),
    )
    await userEvent.click(screen.getByTestId('craft-calc-config-save'))

    await waitFor(() => expect(mockUpdateCraftCalcConfig).toHaveBeenCalledTimes(1))
    const body = mockUpdateCraftCalcConfig.mock.calls[0][0] as Record<string, unknown>
    expect(body.per_fold_single).toBe(0.5)
    expect(Object.keys(body).sort()).toEqual(
      [
        'per_fold_single',
        'per_fold_mixed_times',
        'margin_single',
        'margin_multi',
        'min_fullness',
        'tiers',
        'default_formula',
        'side_margin',
        'meters_rounding_step',
      ].sort(),
    )
    // 保存成功后口径来源如实变「已保存为您的配置」
    await waitFor(() =>
      expect(screen.getByTestId('craft-calc-config-source')).toHaveTextContent('已保存为您的配置'),
    )
  })

  it('非法值 ⇒ 422 逐条理由就地可见，且**不静默回退默认值**', async () => {
    render(<ProcessConfigPage />)
    await waitFor(() => expect(screen.getByTestId('operation-price-matrix')).toBeInTheDocument())
    await userEvent.click(screen.getByTestId('process-config-tab-calc'))
    await waitFor(() => expect(screen.getByTestId('craft-calc-config-panel')).toBeInTheDocument())

    const input = screen.getByTestId('craft-calc-config-scalar-min_fullness')
    await userEvent.clear(input)
    await userEvent.type(input, '1')
    mockUpdateCraftCalcConfig.mockRejectedValueOnce(CALC_GUARD_REJECTION)
    await userEvent.click(screen.getByTestId('craft-calc-config-save'))

    const reasons = await screen.findByTestId('craft-calc-config-reasons')
    expect(reasons).toHaveTextContent('不得低于行业红线 1.5')
    expect(reasons).toHaveTextContent('必须是 [pleat, fullness] 之一')
    // 不静默回退：用户输入**还在**（没有被悄悄写回默认 1.5），且来源仍标注「系统默认值」
    expect(screen.getByTestId('craft-calc-config-scalar-min_fullness')).toHaveValue(1)
    expect(screen.getByTestId('craft-calc-config-source')).toHaveTextContent('当前使用系统默认值')
  })

  it('切 tab 不丢草稿（编辑中的参数在切走再切回后仍在）', async () => {
    render(<ProcessConfigPage />)
    await waitFor(() => expect(screen.getByTestId('operation-price-matrix')).toBeInTheDocument())
    await userEvent.click(screen.getByTestId('process-config-tab-calc'))
    await waitFor(() => expect(screen.getByTestId('craft-calc-config-panel')).toBeInTheDocument())

    const input = screen.getByTestId('craft-calc-config-scalar-margin_multi')
    await userEvent.clear(input)
    await userEvent.type(input, '0.45')

    await userEvent.click(screen.getByTestId('process-config-tab-routes'))
    await waitFor(() => expect(screen.getByTestId('routings-list')).toBeInTheDocument())
    await userEvent.click(screen.getByTestId('process-config-tab-calc'))

    expect(screen.getByTestId('craft-calc-config-scalar-margin_multi')).toHaveValue(0.45)
  })

  it('工艺档位显示中文（标准档 / 经济档），但**键**仍是 standard / economy（testid + 提交体 + label 初值）', async () => {
    // 额外挂一个**未知档**：显示名回退原键（不得吞掉、不得猜中文）
    mockGetCraftCalcConfig.mockReset().mockResolvedValue(
      ok({
        source: 'default',
        config: {
          ...ENGINE_DEFAULT_CALC_CONFIG,
          tiers: {
            standard: { fullness: 2.0, label: '标准工艺' },
            economy: { fullness: 1.8, label: '经济工艺' },
            custom: { fullness: 2.4, label: '' },
          },
        },
      }),
    )
    render(<ProcessConfigPage />)
    await waitFor(() => expect(screen.getByTestId('operation-price-matrix')).toBeInTheDocument())
    await userEvent.click(screen.getByTestId('process-config-tab-calc'))
    await waitFor(() => expect(screen.getByTestId('craft-calc-config-panel')).toBeInTheDocument())

    // ① 显示名中文化：注入（去掉 TIER_DISPLAY_LABEL 映射）⇒ 断言红（界面回到英文键）
    const rowOf = (name: string) =>
      screen.getByTestId(`craft-calc-config-tier-${name}-label`).closest('tr') as HTMLElement
    expect(rowOf('standard')).toHaveTextContent('标准档')
    expect(rowOf('standard')).not.toHaveTextContent('standard')
    expect(rowOf('economy')).toHaveTextContent('经济档')
    expect(rowOf('economy')).not.toHaveTextContent('economy')
    // ② 未知档 ⇒ 回退原键（不吞掉未知档）
    expect(rowOf('custom')).toHaveTextContent('custom')

    // ③ 键**不许改**：data-testid 仍是英文键；label 输入框初值 = 后端逐字（不是中文显示名）
    expect(screen.getByTestId('craft-calc-config-tier-standard-fullness')).toHaveValue(2)
    expect(screen.getByTestId('craft-calc-config-tier-standard-label')).toHaveValue('标准工艺')

    // ④ 提交给 API 的 tiers 键仍是 standard / economy（中文只是显示名）
    await userEvent.click(screen.getByTestId('craft-calc-config-save'))
    await waitFor(() => expect(mockUpdateCraftCalcConfig).toHaveBeenCalledTimes(1))
    const body = mockUpdateCraftCalcConfig.mock.calls[0][0] as { tiers: Record<string, unknown> }
    expect(Object.keys(body.tiers).sort()).toEqual(['custom', 'economy', 'standard'])
    expect(body.tiers).not.toHaveProperty('标准档')
  })

  it('算料配置加载失败 ⇒ 就地报错 + 重试入口（不白屏、不拿默认值顶替）', async () => {
    mockGetCraftCalcConfig.mockReset().mockRejectedValueOnce(new Error('500')).mockResolvedValue(ok({
      source: 'default',
      config: ENGINE_DEFAULT_CALC_CONFIG,
    }))
    render(<ProcessConfigPage />)
    await waitFor(() => expect(screen.getByTestId('operation-price-matrix')).toBeInTheDocument())
    await userEvent.click(screen.getByTestId('process-config-tab-calc'))

    await waitFor(() => expect(screen.getByTestId('craft-calc-config-error')).toHaveTextContent('算料配置加载失败'))
    expect(screen.queryByTestId('craft-calc-config-scalar-per_fold_single')).toBeNull()

    await userEvent.click(screen.getByTestId('craft-calc-config-retry'))
    await waitFor(() => expect(screen.getByTestId('craft-calc-config-scalar-per_fold_single')).toHaveValue(0.25))
  })
})
})

/**
 * 部位价目矩阵的**真实规模**夹具（issue #4529 / V79：30 逻辑工序 × **4** 部位 = **120** 格）。
 * 第 4 个部位 = `布料` —— #4556 的不对称就长在这：**读面**（本夹具）本来就看得见它，
 * **写面**（新建路线的勾选项）却建不出来。
 * 服务端顺序 = `(operation, position)`；本夹具按 `工序1..30` × `布帘/纱帘/帘头/布料` 逐格铺开。
 * 三态齐备：纱帘列 `applicable=false`（不做）/ 布料列 `unit_price=null`（做但未定价）/ 其余有价。
 */
const MATRIX_120 = Array.from({ length: 30 }, (_, i) => `工序${i + 1}`).flatMap((operation, oi) =>
  ['布帘', '纱帘', '帘头', '布料'].map((position, pi) => ({
    operation,
    position,
    unit_price: pi === 3 ? null : oi + pi,
    applicable: pi !== 1,
  })),
)

describe('新建路线的部位选项（issue #4556：包 F 的第 4 个部位「布料」）', () => {
  beforeEach(() => {
    mockGetOperationPositions.mockReset().mockResolvedValue(ok(MATRIX_120))
  })

  it('判据③ 回归：矩阵列**逐值不变** —— 30 道 × 4 部位 = 120 格整份呈现，`布料` 列在（读面本来就看得见）', async () => {
    render(<ProcessConfigPage />)
    await waitFor(() => expect(screen.getByTestId('operation-price-matrix')).toBeInTheDocument())

    expect(screen.getByTestId('operation-price-matrix-total')).toHaveTextContent('30')
    expect(screen.getByTestId('operation-price-matrix-cells')).toHaveTextContent('120')
    expect(screen.getAllByTestId(/^matrix-row-/)).toHaveLength(30)
    expect(screen.getAllByTestId(/^matrix-cell-/)).toHaveLength(120)
    // 逐列 30 格 —— **四列一个不少**（改口径把 `布料` 列滤掉/重排 ⇒ 红）
    for (const p of ['布帘', '纱帘', '帘头', '布料']) {
      expect(screen.getAllByTestId(new RegExp(`^matrix-cell-.*-${p}$`))).toHaveLength(30)
    }
    // 列序 = 基线三部位在前、矩阵里的新部位**追加在后**（不重排、不丢列）
    expect(
      within(screen.getByTestId('operation-price-matrix'))
        .getAllByRole('columnheader')
        .map((th) => th.textContent),
    ).toEqual(['工序', '布帘', '纱帘', '帘头', '布料', '元数据 / 操作'])
  })

  it('判据① 「新建路线」的部位勾选**含 `布料`**（不含 ⇒ 红）', async () => {
    await renderOnRoutes()
    await userEvent.click(screen.getByTestId('routings-new-route'))
    await waitFor(() => expect(screen.getByTestId('routings-create-name')).toBeInTheDocument())

    for (const p of ['布帘', '纱帘', '帘头', '布料']) {
      expect(screen.getByTestId(`routings-create-position-${p}`)).toBeInTheDocument()
    }
    // 默认 = **基线三部位全适用**（与后端 `ProductionRoutingCommandService.DEFAULT_POSITIONS` 同口径）；
    // `布料` 是**按需勾选**的第 4 项（默认不勾：勾上会建出一条「也适用布料」的路线，
    // 而路线命中是 `(is_default DESC, id)` 首个命中 ⇒ 会**顶掉**种子自带的 `布料工序路线`）。
    expect(screen.getByTestId('routings-create-position-布帘')).toBeChecked()
    expect(screen.getByTestId('routings-create-position-布料')).not.toBeChecked()
  })

  it('判据② 能建出 `positions=[\'布料\']` 的路线（建不出 ⇒ 红）', async () => {
    await renderOnRoutes()
    await userEvent.click(screen.getByTestId('routings-new-route'))
    await userEvent.type(screen.getByTestId('routings-create-name'), '布料工序路线')
    // 取消基线三部位 → 勾上第 4 部位 `布料`
    for (const p of ['布帘', '纱帘', '帘头']) {
      await userEvent.click(screen.getByTestId(`routings-create-position-${p}`))
    }
    await userEvent.click(screen.getByTestId('routings-create-position-布料'))
    await userEvent.click(screen.getByTestId('routings-create-route-submit'))

    await waitFor(() =>
      expect(mockCreateRouting).toHaveBeenCalledWith({ name: '布料工序路线', positions: ['布料'] }),
    )
  })

  it('判据④ 回归：不动勾选 ⇒ 仍提交**基线三部位**（既有行为逐字不变）', async () => {
    await renderOnRoutes()
    await userEvent.click(screen.getByTestId('routings-new-route'))
    await userEvent.type(screen.getByTestId('routings-create-name'), '窗帘工序路线')
    await userEvent.click(screen.getByTestId('routings-create-route-submit'))

    await waitFor(() =>
      expect(mockCreateRouting).toHaveBeenCalledWith({
        name: '窗帘工序路线',
        positions: ['布帘', '纱帘', '帘头'],
      }),
    )
  })

  it('`positions` 是**开放多值集合**（后端不校验闭词表）⇒ 前端**不发明**互斥规则：勾「布料 + 三部位」四个都提交', async () => {
    // ⚠️ 照实登记（#4556 报告）：跨形态路线的**副作用**（顶掉 `布料工序路线`）已回报产品裁定，
    // 本测试只钉「前端不擅自新增校验」这一条既有后端语义，**不**主张跨形态是可取的。
    await renderOnRoutes()
    await userEvent.click(screen.getByTestId('routings-new-route'))
    await userEvent.type(screen.getByTestId('routings-create-name'), '跨形态路线')
    await userEvent.click(screen.getByTestId('routings-create-position-布料'))
    await userEvent.click(screen.getByTestId('routings-create-route-submit'))

    await waitFor(() =>
      expect(mockCreateRouting).toHaveBeenCalledWith({
        name: '跨形态路线',
        positions: ['布帘', '纱帘', '帘头', '布料'],
      }),
    )
  })

  it('兜底：部位价目读面失败 ⇒ 勾选项退回基线三部位（矩阵挂了也要能建路线，不得一个选项都没有）', async () => {
    mockGetOperationPositions.mockReset().mockRejectedValue(new Error('500'))
    await renderOnRoutes()
    await userEvent.click(screen.getByTestId('routings-new-route'))
    await waitFor(() => expect(screen.getByTestId('routings-create-name')).toBeInTheDocument())

    for (const p of ['布帘', '纱帘', '帘头']) {
      expect(screen.getByTestId(`routings-create-position-${p}`)).toBeInTheDocument()
    }
    await userEvent.type(screen.getByTestId('routings-create-name'), '窗帘工序路线')
    await userEvent.click(screen.getByTestId('routings-create-route-submit'))

    await waitFor(() =>
      expect(mockCreateRouting).toHaveBeenCalledWith({
        name: '窗帘工序路线',
        positions: ['布帘', '纱帘', '帘头'],
      }),
    )
  })

  // ── 跨形态提示（issue #4556 产品裁定 (a)；后端机制跟单 #4563）──

  it('裁定 (a) 文案**出现**形态：同勾「布料 + 帘种部位」⇒ 就地提示会顶掉布料专用路线 / 可能丢工序', async () => {
    await renderOnRoutes()
    await userEvent.click(screen.getByTestId('routings-new-route'))
    // 默认已勾基线三部位 ⇒ 再勾第 4 部位 `布料` = 跨形态
    await userEvent.click(screen.getByTestId('routings-create-position-布料'))

    const hint = screen.getByTestId('routings-create-position-mixed-hint')
    // 可行动：说清**机制**（顶掉）与**后果**（丢工序），并指名是哪两项
    expect(hint).toHaveTextContent('顶掉')
    expect(hint).toHaveTextContent('丢工序')
    expect(hint).toHaveTextContent('布料')
    expect(hint).toHaveTextContent('布帘')

    // 取消勾选 `布料` ⇒ 提示随之消失（不是常驻噪音）
    await userEvent.click(screen.getByTestId('routings-create-position-布料'))
    expect(screen.queryByTestId('routings-create-position-mixed-hint')).toBeNull()
  })

  it('裁定 (a) **不出现**形态一：**只**勾「布料」（布料专线）⇒ 不提示 —— 这条正是本单要支持的建法', async () => {
    await renderOnRoutes()
    await userEvent.click(screen.getByTestId('routings-new-route'))
    for (const p of ['布帘', '纱帘', '帘头']) {
      await userEvent.click(screen.getByTestId(`routings-create-position-${p}`))
    }
    await userEvent.click(screen.getByTestId('routings-create-position-布料'))

    expect(screen.getByTestId('routings-create-position-布料')).toBeChecked()
    expect(screen.queryByTestId('routings-create-position-mixed-hint')).toBeNull()
  })

  it('裁定 (a) **不出现**形态二：只勾基线三部位（默认）⇒ 不提示（既有行为逐字不变）', async () => {
    await renderOnRoutes()
    await userEvent.click(screen.getByTestId('routings-new-route'))

    expect(screen.getByTestId('routings-create-position-布帘')).toBeChecked()
    expect(screen.getByTestId('routings-create-position-布料')).not.toBeChecked()
    expect(screen.queryByTestId('routings-create-position-mixed-hint')).toBeNull()
  })

})

/**
 * ══════════════════ ⑯ 「新增」对话框的类型二选一（issue #4570） ══════════════════
 *
 * 单列一个 describe（**本组自己**的夹具与调用计数）：
 * ① 矩阵夹具要换回**基线**那份（逻辑工序名 = `精裁` / `三边` / `车被`）——
 *    上一组把它换成了 30 道 × 4 部位的 `MATRIX_120`；
 * ② mock 是**模块级共享**的（无全局 `clearMocks`）⇒ 要按本组自己的次数断言，
 *    必须在 `beforeEach` 里 `mockReset()` 清掉前面积累的调用历史。
 */
describe('「新增」对话框：工序 / 特殊选项 类型二选一（issue #4570）', () => {
  beforeEach(() => {
    mockGetRoutings.mockReset().mockResolvedValue(ok(ROUTINGS))
    mockGetOperationsCatalog.mockReset().mockResolvedValue(ok(CATALOG))
    mockGetOperationPositions.mockReset().mockResolvedValue(ok(POSITIONS))
    mockGetRouteRules.mockReset().mockResolvedValue(ok(RULES))
    mockCreateOperation
      .mockReset()
      .mockResolvedValue(ok({ id: 'op-new', created_positions: 3, skipped_positions: 0 }))
    mockCreateOptionRule.mockReset().mockResolvedValue(ok({ id: 31 }))
  })

  /** 打开「新增」对话框（工序项 tab 右上入口；类型默认「工序」） */
  const openCreateDialog = async () => {
    await renderOperations()
    await userEvent.click(screen.getByTestId('routings-new-operation'))
  }

  it('⑯-① 类型二选一：默认「工序」（既有表单在、特殊选项字段不在）；切「特殊选项」⇒ 元/套 + 落在哪道工序 + 插在哪道之后', async () => {
    await openCreateDialog()

    // 一句话把两本账说清（用户走查的核心困惑）
    const ledgers = screen.getByTestId('create-kind-two-ledgers')
    expect(ledgers).toHaveTextContent('计件')
    expect(ledgers).toHaveTextContent('元/套')
    expect(ledgers).toHaveTextContent('互不换算')

    // 默认 = 工序：既有表单在场，特殊选项字段**不在**
    expect(screen.getByTestId('create-kind-operation')).toHaveAttribute('aria-checked', 'true')
    expect(screen.getByTestId('create-kind-option')).toHaveAttribute('aria-checked', 'false')
    expect(screen.getByTestId('routings-create-op-unit_price')).toBeInTheDocument()
    expect(screen.queryByTestId('routings-create-option-customer_unit_price')).toBeNull()

    await userEvent.click(screen.getByTestId('create-kind-option'))
    expect(screen.getByTestId('create-kind-option')).toHaveAttribute('aria-checked', 'true')
    expect(screen.getByTestId('routings-create-option-customer_unit_price')).toBeInTheDocument()
    expect(screen.getByTestId('routings-create-option-operation')).toBeInTheDocument()
    expect(screen.getByTestId('routings-create-option-after_operation')).toBeInTheDocument()
    // issue #4650 阶段 1：**优先级整块去掉** —— 界面不再有这个概念（后端按默认顺序）
    expect(screen.queryByTestId('routings-create-option-priority')).toBeNull()
    // 切过去后「工序」那套字段退场（不是两套表单叠着）
    expect(screen.queryByTestId('routings-create-op-unit_price')).toBeNull()

    // 目标工序下拉 = **逻辑工序名**（与 `route_rules.operation` 同源），**不是**库口径的 `精裁-布`
    const opts = within(screen.getByTestId('routings-create-option-operation'))
      .getAllByRole('option')
      .map((o) => o.textContent)
    expect(opts).toContain('精裁')
    expect(opts).toContain('三边')
    expect(opts).not.toContain('精裁-布')
  })

  it('⑯-② 特殊选项提交 ⇒ POST /route-rules 的 body **恰为** {trigger_value, operation, customer_unit_price}（不混工序字段）', async () => {
    await openCreateDialog()
    await userEvent.click(screen.getByTestId('create-kind-option'))
    await userEvent.type(screen.getByTestId('routings-create-option-trigger_value'), '拼3次')
    await userEvent.type(screen.getByTestId('routings-create-option-customer_unit_price'), '15.5')
    await userEvent.selectOptions(screen.getByTestId('routings-create-option-operation'), '精裁')
    await userEvent.click(screen.getByTestId('routings-create-operation-submit'))

    await waitFor(() => expect(mockCreateOptionRule).toHaveBeenCalledTimes(1))
    const body = mockCreateOptionRule.mock.calls[0][0] as Record<string, unknown>
    // 逐键：可选键（锚点 / 优先级）留空 ⇒ **不发**（不拿 null 冒充「没填」）
    expect(Object.keys(body).sort()).toEqual(['customer_unit_price', 'operation', 'trigger_value'])
    expect(body).toEqual({ trigger_value: '拼3次', operation: '精裁', customer_unit_price: 15.5 })
    for (const k of ['name', 'group_name', 'unit', 'unit_price']) expect(body).not.toHaveProperty(k)
    expect(mockCreateOperation).not.toHaveBeenCalled()
    // 成功 ⇒ 关框 + 重新拉取规则列表
    await waitFor(() => expect(mockGetRouteRules).toHaveBeenCalledTimes(2))
    expect(screen.queryByTestId('routings-create-option-trigger_value')).toBeNull()
  })

  it('⑯-②b 特殊选项：选定工序 ⇒ 「插在哪道之后」**自动填默认值**（issue #4650：别让商家猜）', async () => {
    await openCreateDialog()
    await userEvent.click(screen.getByTestId('create-kind-option'))
    await userEvent.type(screen.getByTestId('routings-create-option-trigger_value'), '免熨')
    await userEvent.type(screen.getByTestId('routings-create-option-customer_unit_price'), '8')
    await userEvent.selectOptions(screen.getByTestId('routings-create-option-operation'), '三边')

    // 三边在默认主线里位于「精裁」之后 ⇒ 默认值 = 精裁（与今天种子里该工序的锚点同口径）
    expect(screen.getByTestId('routings-create-option-after_operation')).toHaveValue('精裁')

    await userEvent.click(screen.getByTestId('routings-create-operation-submit'))

    await waitFor(() => expect(mockCreateOptionRule).toHaveBeenCalledTimes(1))
    expect(mockCreateOptionRule.mock.calls[0][0]).toEqual({
      trigger_value: '免熨',
      operation: '三边',
      after_operation: '精裁',
      customer_unit_price: 8,
    })
  })

  it('⑯-③ 特殊选项：目标工序为空 ⇒ **不发请求** + 就地理由（对话框不关）', async () => {
    await openCreateDialog()
    await userEvent.click(screen.getByTestId('create-kind-option'))
    await userEvent.type(screen.getByTestId('routings-create-option-trigger_value'), '拼3次')
    await userEvent.type(screen.getByTestId('routings-create-option-customer_unit_price'), '15.5')
    // 目标工序**不选**
    await userEvent.click(screen.getByTestId('routings-create-operation-submit'))

    expect(mockCreateOptionRule).not.toHaveBeenCalled()
    expect(screen.getByTestId('routings-create-option-reasons')).toHaveTextContent('目标工序')
    expect(screen.getByTestId('routings-create-option-trigger_value')).toBeInTheDocument()
  })

  it('⑯-④ 特殊选项：单价非法（三位小数）⇒ **不发请求** + 就地理由', async () => {
    await openCreateDialog()
    await userEvent.click(screen.getByTestId('create-kind-option'))
    await userEvent.type(screen.getByTestId('routings-create-option-trigger_value'), '拼3次')
    await userEvent.type(screen.getByTestId('routings-create-option-customer_unit_price'), '12.345')
    await userEvent.selectOptions(screen.getByTestId('routings-create-option-operation'), '精裁')
    await userEvent.click(screen.getByTestId('routings-create-operation-submit'))

    expect(mockCreateOptionRule).not.toHaveBeenCalled()
    expect(screen.getByTestId('routings-create-option-reasons')).toHaveTextContent('两位小数')
  })

  it('⑯-⑤ 特殊选项：后端 422 ⇒ 理由**逐条**就地可见，且**不刷新**、不改页面数据', async () => {
    mockCreateOptionRule
      .mockReset()
      .mockRejectedValue(guardError(['选项名不能为空', '单价不得超过两位小数']))
    await openCreateDialog()
    await userEvent.click(screen.getByTestId('create-kind-option'))
    await userEvent.type(screen.getByTestId('routings-create-option-trigger_value'), '拼3次')
    await userEvent.type(screen.getByTestId('routings-create-option-customer_unit_price'), '15.5')
    await userEvent.selectOptions(screen.getByTestId('routings-create-option-operation'), '精裁')
    await userEvent.click(screen.getByTestId('routings-create-operation-submit'))

    await waitFor(() => expect(screen.getByTestId('routings-create-option-reasons')).toBeInTheDocument())
    const items = within(screen.getByTestId('routings-create-option-reasons')).getAllByRole('listitem')
    expect(items.map((li) => li.textContent)).toEqual(['选项名不能为空', '单价不得超过两位小数'])
    // 不刷新（规则列表只被首屏 load 拉过一次）、不改页面数据（对话框仍开着、草稿还在）
    expect(mockGetRouteRules).toHaveBeenCalledTimes(1)
    expect(screen.getByTestId('routings-create-option-trigger_value')).toHaveValue('拼3次')
  })

  it('⑯-⑥ 类型「工序」仍走 POST /operations（回归：切到特殊选项再切回，既有链路逐字不变）', async () => {
    await openCreateDialog()
    await userEvent.click(screen.getByTestId('create-kind-option'))
    await userEvent.click(screen.getByTestId('create-kind-operation'))

    await userEvent.type(screen.getByTestId('routings-create-op-name'), '罗马帘-穿杆')
    await userEvent.type(screen.getByTestId('routings-create-op-group_name'), '车位')
    await userEvent.type(screen.getByTestId('routings-create-op-unit'), '套')
    await userEvent.type(screen.getByTestId('routings-create-op-unit_price'), '4.5')
    await userEvent.click(screen.getByTestId('routings-create-operation-submit'))

    await waitFor(() =>
      expect(mockCreateOperation).toHaveBeenCalledWith({
        name: '罗马帘-穿杆',
        group_name: '车位',
        unit: '套',
        unit_price: 4.5,
        positions: ['布帘', '纱帘', '帘头'],
      }),
    )
    expect(mockCreateOptionRule).not.toHaveBeenCalled()
    await waitFor(() => expect(mockGetOperationsCatalog).toHaveBeenCalledTimes(2))
  })

  // ────────────────────────────────────────────────────────────────────────────
  // ㉔ 「新增」对话框加「适用部位」多选（issue #4614）—— 见文件头 ㉔ 的口径
  // ────────────────────────────────────────────────────────────────────────────

  /** 打开「新增」对话框并填完「工序」那一支的必填项（工序名 + 计件单价） */
  const fillOperationForm = async () => {
    await userEvent.type(screen.getByTestId('routings-create-op-name'), '罗马帘-穿杆')
    await userEvent.type(screen.getByTestId('routings-create-op-unit_price'), '4.5')
  }

  it('㉔-① 适用部位多选：默认勾**基线三部位**（与「新建路线」默认一致），提交 body 带 positions', async () => {
    await openCreateDialog()

    // 默认勾选 = 基线三部位（用户不必逐一点，但不勾就得被拦 —— 见 ⑳-②）
    expect(screen.getByTestId('routings-create-op-position-布帘')).toBeChecked()
    expect(screen.getByTestId('routings-create-op-position-纱帘')).toBeChecked()
    expect(screen.getByTestId('routings-create-op-position-帘头')).toBeChecked()

    await fillOperationForm()
    await userEvent.click(screen.getByTestId('routings-create-operation-submit'))

    await waitFor(() =>
      expect(mockCreateOperation).toHaveBeenCalledWith(
        expect.objectContaining({ positions: ['布帘', '纱帘', '帘头'] }),
      ),
    )
  })

  it('㉔-② 一个部位都不勾 ⇒ **不发请求** + 就地逐条理由（对话框不关、草稿不丢）', async () => {
    await openCreateDialog()
    await fillOperationForm()
    for (const p of ['布帘', '纱帘', '帘头']) {
      await userEvent.click(screen.getByTestId(`routings-create-op-position-${p}`))
    }

    await userEvent.click(screen.getByTestId('routings-create-operation-submit'))

    const reasons = await screen.findByTestId('routings-create-op-reasons')
    expect(reasons).toHaveTextContent('部位')
    expect(mockCreateOperation).not.toHaveBeenCalled()
    // 不刷新、不静默清空草稿（静默 = 商家以为建好了）
    expect(mockGetOperationPositions).toHaveBeenCalledTimes(1)
    expect(screen.getByTestId('routings-create-op-name')).toHaveValue('罗马帘-穿杆')
  })

  it('㉔-③ 值域与「新建路线」同源（复用 positionOptions）：矩阵里的第 4 个部位 `布料` 也可勾', async () => {
    mockGetOperationPositions.mockResolvedValue(
      ok([
        ...POSITIONS,
        { id: 'pos-配料-布料', operation: '配料', position: '布料', unit_price: 0.2, applicable: true, ...NO_VARIANT },
      ]),
    )
    await openCreateDialog()
    await fillOperationForm()

    const cloth = screen.getByTestId('routings-create-op-position-布料')
    expect(cloth).not.toBeChecked() // 默认仍只勾基线三部位（不把新增部位默认打开）
    await userEvent.click(cloth)
    await userEvent.click(screen.getByTestId('routings-create-operation-submit'))

    await waitFor(() =>
      expect(mockCreateOperation).toHaveBeenCalledWith(
        expect.objectContaining({ positions: ['布帘', '纱帘', '帘头', '布料'] }),
      ),
    )
  })

  it('㉔-④ 新增成功后**立刻出现在「工艺项」表里**（load() 刷新 ⇒ 可就地定价）', async () => {
    // 第一次读矩阵 = 旧快照（不含新工序）；新增后的第二次 = 含新工序的两个部位格
    mockGetOperationPositions
      .mockResolvedValueOnce(ok(POSITIONS))
      .mockResolvedValue(
        ok([
          ...POSITIONS,
          { id: 'pos-罗马帘-穿杆-布帘', operation: '罗马帘-穿杆', position: '布帘', unit_price: 4.5, applicable: true, ...NO_VARIANT },
          { id: 'pos-罗马帘-穿杆-纱帘', operation: '罗马帘-穿杆', position: '纱帘', unit_price: 4.5, applicable: true, ...NO_VARIANT },
        ]),
      )
    await renderOperations()
    // 基线：表里**没有**它（这正是用户实测「什么也没出现」的那一屏）
    expect(screen.queryByTestId('matrix-row-罗马帘-穿杆')).toBeNull()

    await userEvent.click(screen.getByTestId('routings-new-operation'))
    await waitFor(() => expect(screen.getByTestId('create-kind-operation')).toBeInTheDocument())
    await fillOperationForm()
    await userEvent.click(screen.getByTestId('routings-create-operation-submit'))

    await waitFor(() => expect(screen.getByTestId('matrix-row-罗马帘-穿杆')).toBeInTheDocument())
    expect(screen.getByTestId('matrix-cell-罗马帘-穿杆-布帘')).toHaveTextContent('4.5')
    expect(screen.getByTestId('matrix-cell-罗马帘-穿杆-纱帘')).toHaveTextContent('4.5')
  })

  it('㉔-⑤ 结果 toast 报**服务端返回的真实数字**（新增/跳过）；缺结果体 ⇒ 显式报错不假装成功', async () => {
    // 本组 describe 的 beforeEach 不清 toast spy（上面的用例会留下历史调用）⇒ 本用例自己清
    vi.mocked(toast.success).mockClear()
    vi.mocked(toast.error).mockClear()
    mockCreateOperation.mockResolvedValue(ok({ id: 'op-new', created_positions: 2, skipped_positions: 1 }))
    await openCreateDialog()
    await fillOperationForm()
    await userEvent.click(screen.getByTestId('routings-create-operation-submit'))

    await waitFor(() => expect(vi.mocked(toast.success)).toHaveBeenCalled())
    const message = vi.mocked(toast.success).mock.calls.at(-1)?.[0] as string
    expect(message).toContain('2')
    expect(message).toContain('1')
    expect(vi.mocked(toast.error)).not.toHaveBeenCalled()
  })

  it('㉔-⑥ 缺结果体（响应没有 data）⇒ 显式报错，**不**弹成功 toast（照 applyTemplate 既有纪律）', async () => {
    vi.mocked(toast.success).mockClear()
    vi.mocked(toast.error).mockClear()
    mockCreateOperation.mockResolvedValue({ data: { success: true } })
    await openCreateDialog()
    await fillOperationForm()
    await userEvent.click(screen.getByTestId('routings-create-operation-submit'))

    await waitFor(() => expect(vi.mocked(toast.error)).toHaveBeenCalled())
    expect(vi.mocked(toast.success)).not.toHaveBeenCalled()
  })

  // ────────────────────────────────────────────────────────────────────────────
  // ㉕ **存量孤儿接入**（issue #4614 范围补口）
  // 用户实测：「我现在在**工艺项**中看不到 测试22，但是在**路线编辑的下拉列表**能看到，是 bug」
  // —— 用户此前用「新增工序」建的工序只有 `production_operations` 行、没有矩阵行 ⇒ 孤儿：
  // 「工艺项」表按矩阵渲染 ⇒ 看不到；「路线编辑」下拉按工序库渲染 ⇒ 看得到（两边口径不一致）。
  // #4609 把下拉也改成读矩阵后孤儿**两边都看不到**（彻底不可达）⇒ 存量必须有接入路径。
  // 后端只有**一处**「按部位补建矩阵行」实现（新增路径 POST 与接入路径 PUT 共用）。
  // ────────────────────────────────────────────────────────────────────────────

  /** 只有工序库行、没有任何矩阵行的孤儿工序（用户实测的 `测试22`） */
  const ORPHAN_OP = {
    id: 'op-test22', name: '测试22', group: '其他', unit: '米',
    unit_price: 0.5, is_must_finish: false, is_start_marker: false,
  }
  const ORPHAN_CATALOG = { total: 1, groups: [{ group: '其他', operations: [ORPHAN_OP] }] }
  /** 已定价的非孤儿（矩阵里 `variant_operation_id = op-精裁-布` 指向它） */
  const PRICED_OP = {
    id: 'op-精裁-布', name: '精裁-布', group: '裁剪', unit: '套',
    unit_price: 8.5, is_must_finish: true, is_start_marker: true,
  }
  /** 接入后矩阵里多出来的那一格（`variant_operation_id` 指向孤儿 ⇒ 它不再是孤儿） */
  const ATTACHED_CELL = {
    id: 'pos-测试22-布帘', operation: '测试22', position: '布帘', unit_price: 0.5, applicable: true,
    variant_operation_id: 'op-test22', unit: '米', group: '其他',
    scope: 'position', is_must_finish: false,
  }

  it('㉕-① 存量孤儿提示：工序库里有、但没有任何部位价目行 ⇒ 顶部给出接入入口', async () => {
    mockGetOperationsCatalog.mockResolvedValue(ok(ORPHAN_CATALOG))
    await renderOperations()

    const hint = screen.getByTestId('matrix-orphan-hint')
    expect(hint).toHaveTextContent('1')
    expect(hint).toHaveTextContent('部位')
  })

  it('㉕-①′ 工序库目录的 `name` 已是**逻辑工序名**（issue #4642）：弹窗渲染逻辑名，变体名不上屏', async () => {
    // 夹具形态 = **读时归一后**的服务端响应（issue #4642）：库行 `精裁-布` 的 `name` 是 `精裁`，
    // 库口径原名另走 `library_name`（web 不得渲染）。`测试22` 不在归一表里 ⇒ 归一后等于自身。
    const LOGICAL_CATALOG = {
      total: 2,
      groups: [
        {
          group: '裁剪',
          operations: [
            {
              id: 'op-v54-01', name: '精裁', library_name: '精裁-布', group: '裁剪',
              unit: '套', unit_price: 8.5, is_must_finish: true, is_start_marker: true,
            },
          ],
        },
        {
          group: '其他',
          operations: [
            {
              id: 'op-test22', name: '测试22', library_name: '测试22', group: '其他',
              unit: '米', unit_price: 0.5, is_must_finish: false, is_start_marker: false,
            },
          ],
        },
      ],
    }
    mockGetOperationsCatalog.mockResolvedValue(ok(LOGICAL_CATALOG))
    await renderOperations()

    await userEvent.click(screen.getByTestId('matrix-orphan-hint'))
    await waitFor(() => expect(screen.getByTestId('orphan-attach-list')).toBeInTheDocument())

    // ① 弹窗按**逻辑名**渲染（改前这里是库口径变体名 `精裁-布`）
    //    ⚠️ id 用 `op-v54-01`（**不是** `op-精裁-布`）：后者被矩阵格的 `variant_operation_id` 指向
    //    ⇒ 它不算孤儿、不会出现在本弹窗里（那是另一条判据 ㉕-② 的事）。
    expect(screen.getByTestId('orphan-name-op-v54-01')).toHaveTextContent('精裁')
    expect(screen.getByTestId('orphan-name-op-v54-01')).not.toHaveTextContent('精裁-布')
    expect(screen.getByTestId('orphan-name-op-test22')).toHaveTextContent('测试22')

    // ② 反向护栏：**本弹窗列表子树**里不得出现变体名（`library_name` 是库口径键，web **不得渲染**）。
    //    ⚠️ issue #4647 / D6：本行注释改前写「**整屏**都不得出现变体名」而断言只查
    //    `orphan-attach-list` 的子树 ⇒ **注释漂移**（假绿来源）。两种改法二选一，这里取**注释与断言对齐**：
    //    本页其它区域（矩阵行键 / 主线 chip）的工序名来自**读面已归一**的 `operation` 值域，
    //    `library_name` 只作库口径元数据解析（见下 ③），故「不得渲染变体名」的机械判据落在
    //    **本弹窗子树** + 静态守卫 `tests/unit_ci_workflows/test_op_name_registry_guard.py`（①/②/③b）
    //    + 服务面 Java 断言上，而不是靠一条脆弱的整屏字符串扫描（`data-testid` / 其它区域的
    //    历史文案都可能含该形态，会把判据变成假红来源）。
    const orphanList = screen.getByTestId('orphan-attach-list')
    expect(orphanList.textContent ?? '').not.toContain('精裁-布')

    // ③ `libraryByName` 按 `name` 建键 ⇒ 归一后主线 chip 的库口径元数据解析**变好**
    //    （`libraryByName.get('精裁')` 现在查得到 ⇒ `resolved=true`）。本页 chip **不渲染**
    //    分组/单位（见 `StepView` 的注释：单价与库口径元数据不在 chip 上），故判据落在
    //    「chip 正常渲染 + 整页无变体名」上；`resolved` 的服务面真值由 Java 断言守住。
    await userEvent.click(screen.getByTestId('process-config-tab-routes'))
    await waitFor(() => expect(screen.getByTestId('routing-step-11-1')).toBeInTheDocument())
    expect(screen.getByTestId('routing-step-11-1')).toHaveTextContent('精裁')
    expect(screen.getByTestId('routing-step-11-1')).not.toHaveTextContent('精裁-布')
  })

  it('㉕-② 反向护栏：已被矩阵格指向的工序**不算**孤儿（不提示）', async () => {
    mockGetOperationsCatalog.mockResolvedValue(
      ok({ total: 1, groups: [{ group: '裁剪', operations: [PRICED_OP] }] }),
    )
    await renderOperations()

    expect(screen.queryByTestId('matrix-orphan-hint')).toBeNull()
  })

  it('㉕-③ 接入弹窗：列出孤儿（名/分组/单位）+ 默认勾基线三部位；**只**对孤儿发 PUT（已定价的格不被动）', async () => {
    mockUpdateOperation.mockClear()
    mockGetOperationsCatalog.mockResolvedValue(
      ok({ total: 2, groups: [{ group: '其他', operations: [ORPHAN_OP] }, { group: '裁剪', operations: [PRICED_OP] }] }),
    )
    mockUpdateOperation.mockResolvedValue(ok({ id: 'op-test22', created_positions: 3, skipped_positions: 0 }))
    await renderOperations()

    await userEvent.click(screen.getByTestId('matrix-orphan-hint'))
    await waitFor(() => expect(screen.getByTestId('orphan-attach-list')).toBeInTheDocument())
    // 名 + 分组 + 单位（商家据此认出是哪道工序）
    expect(screen.getByTestId('orphan-name-op-test22')).toHaveTextContent('测试22')
    expect(screen.getByTestId('orphan-row-op-test22')).toHaveTextContent('其他')
    expect(screen.getByTestId('orphan-row-op-test22')).toHaveTextContent('米')
    // 默认勾基线三部位（与新增工序同一份默认）
    expect(screen.getByTestId('orphan-position-op-test22-布帘')).toBeChecked()
    expect(screen.getByTestId('orphan-position-op-test22-纱帘')).toBeChecked()
    expect(screen.getByTestId('orphan-position-op-test22-帘头')).toBeChecked()
    // 已定价的非孤儿不在弹窗里（不被动）
    expect(screen.queryByTestId('orphan-row-op-精裁-布')).toBeNull()

    await userEvent.click(screen.getByTestId('orphan-attach-submit'))

    await waitFor(() =>
      expect(mockUpdateOperation).toHaveBeenCalledWith('op-test22', { positions: ['布帘', '纱帘', '帘头'] }),
    )
    expect(mockUpdateOperation).toHaveBeenCalledTimes(1)
  })

  it('㉕-④ 接入后**立刻出现在「工艺项」表里**，且「路线编辑」下拉也能看到它（两边口径一致）', async () => {
    mockGetOperationsCatalog.mockResolvedValue(ok(ORPHAN_CATALOG))
    mockUpdateOperation.mockResolvedValue(ok({ id: 'op-test22', created_positions: 3, skipped_positions: 0 }))
    mockGetOperationPositions
      .mockResolvedValueOnce(ok(POSITIONS))
      .mockResolvedValue(ok([...POSITIONS, ATTACHED_CELL]))
    await renderOperations()
    // 红证基线：改前「工艺项」表里没有它（用户实测的那一屏）
    expect(screen.queryByTestId('matrix-row-测试22')).toBeNull()

    await userEvent.click(screen.getByTestId('matrix-orphan-hint'))
    await waitFor(() => expect(screen.getByTestId('orphan-attach-submit')).toBeInTheDocument())
    await userEvent.click(screen.getByTestId('orphan-attach-submit'))

    await waitFor(() => expect(screen.getByTestId('matrix-row-测试22')).toBeInTheDocument())
    expect(screen.getByTestId('matrix-cell-测试22-布帘')).toHaveTextContent('0.5')
    // 接进来之后它不再是孤儿 ⇒ 提示消失
    expect(screen.queryByTestId('matrix-orphan-hint')).toBeNull()

    // 「路线编辑」下拉（读面与「工艺项」同一份矩阵行键）也能看到它
    await userEvent.click(screen.getByTestId('process-config-tab-routes'))
    await waitFor(() => expect(screen.getByTestId('routing-edit-11')).toBeInTheDocument())
    await userEvent.click(screen.getByTestId('routing-edit-11'))
    const options = within(screen.getByTestId('routing-add-select-11')).getAllByRole('option')
    expect(options.map((o) => o.textContent).join('|')).toContain('测试22')
  })

  it('㉕-⑤ 接入结果 toast 报服务端真实数字（新建/跳过）；缺结果体 ⇒ 显式报错不假装成功', async () => {
    vi.mocked(toast.success).mockClear()
    vi.mocked(toast.error).mockClear()
    mockGetOperationsCatalog.mockResolvedValue(ok(ORPHAN_CATALOG))
    mockUpdateOperation.mockResolvedValue(ok({ id: 'op-test22', created_positions: 2, skipped_positions: 1 }))
    await renderOperations()
    await userEvent.click(screen.getByTestId('matrix-orphan-hint'))
    await waitFor(() => expect(screen.getByTestId('orphan-attach-submit')).toBeInTheDocument())
    await userEvent.click(screen.getByTestId('orphan-attach-submit'))

    await waitFor(() => expect(vi.mocked(toast.success)).toHaveBeenCalled())
    const message = vi.mocked(toast.success).mock.calls.at(-1)?.[0] as string
    expect(message).toContain('2')
    expect(message).toContain('1')
    expect(vi.mocked(toast.error)).not.toHaveBeenCalled()
  })

  it('㉕-⑥ 一个部位都不勾 ⇒ 本地拦下、**不发请求** + 就地理由（弹窗不关、草稿不丢）', async () => {
    mockUpdateOperation.mockClear()
    mockGetOperationsCatalog.mockResolvedValue(ok(ORPHAN_CATALOG))
    await renderOperations()
    await userEvent.click(screen.getByTestId('matrix-orphan-hint'))
    await waitFor(() => expect(screen.getByTestId('orphan-attach-submit')).toBeInTheDocument())
    for (const p of ['布帘', '纱帘', '帘头']) {
      await userEvent.click(screen.getByTestId(`orphan-position-op-test22-${p}`))
    }

    await userEvent.click(screen.getByTestId('orphan-attach-submit'))

    expect(await screen.findByTestId('orphan-attach-reasons')).toHaveTextContent('部位')
    expect(mockUpdateOperation).not.toHaveBeenCalled()
    expect(screen.getByTestId('orphan-attach-list')).toBeInTheDocument()
  })

})
