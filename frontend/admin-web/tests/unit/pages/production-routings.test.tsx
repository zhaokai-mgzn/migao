// case_ids: PG-020, PG-034, PG-053, PP-014, OR-041, UI-048, UI-049, UI-050, UI-051, UI-052
// ⚠️ issue #4962（「什么时候」加回**部位**维 / `production_route_rules.position`）：本文件新增的 **⑱′ 组**
// 由上面**已声明**的 `PG-053` 承载（该用例钉的就是这个「添加条件」表单 ——
// `.github/cases/processing-order.yml` 的 PG-053 注释块与判据 9，触发维闭词表本次加第 4 档 `position`）。
// 不新增 case_id：用例库侧的口径改判（第 4 档 + `route-rule-options` 新增 `positions` 键）由 #4962 的用例库同步一并落。
// PG-020（issue #4203 / #4204）+ PP-014（issue #4307）**合并后**的单页用户面（issue #4416），
// 本单（issue #4433 = 母单 #4423 的 P3）把它适配到**新路线模型**（P1 #4427 / P2 #4432 / P2b #4459 / P2c #4500）。
//
// 新模型下的用户面判据（#4433）：
// ① **工序单价表**（tab「工序管理」主区）：价目读面的行**整份**渲染（真实规模见 issue #4529：
//    30 逻辑工序 × 4 部位 = 120 格；issue #4886 起后端已收敛为**一道逻辑工序一行**，本文件仍用
//    多行夹具（28 × 3 / 30 × 4）判「按逻辑名去重收敛」这一行为）；服务端顺序**不得重排**；
// ② 价的两态「**有价**」（`¥x.xx`，真 0 元照显示）与「**未定价**」（`unit_price=null`；**绝不**
//    回落工序库行价 ⇒ 不得成 `¥0.00`）在界面上**可区分**（同 `route_source` 的「静默 = 未知」纪律）。
//    🔴 **2026-09-21 改判（配套 #4937 / #4951 去部位化彻底版）**：原第三态「**不做**」
//    （`applicable=false`）**已退场** —— 存活价目行的 `applicable` 恒 `TRUE`，该字段也已从
//    `OperationPosition` 类型退场（读面恒 true、写面收到即 **422**）⇒ 单价格 `data-state`
//    收敛为 `priced` / `unpriced` **两态**，第三态 `na` **永不可达**。判据面缩小、**不放宽**
//    （「未定价 ≠ ¥0.00」与「真 0 元照显示」一字未动，并补了「`na` / 「不做」不得出现」的反向断言）；
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
//    - 单价格**两态**（有价 / 未定价）**可区分**，`¥0.00` 是真价（≠「未定价」）；就地改价
//      ⇒ `PUT /operation-positions/{id}` body **只带** `{unit_price}`（#4937/O1 起**只收**这一个键）；
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
//      `DELETE /operations/{id}/detach-and-delete`（**独立端点**；后端**同一事务**先摘格再删
//      + 级联软删矩阵行）⇒ **没有**「第一步成功、第二步失败」的中间态；弹框**说清将发生什么**
//      （哪几个格 + 历史报工不受影响）。
//      ⚠️ **为什么是独立端点而不是给 `DELETE /{id}` 加查询参数**：`DELETE /{id}` 那条路径下另有
//      一个既有软删写面（`tests/unit_ci_workflows/test_logic_delete_write_shape.py` 的锚点按
//      **第一个名为 `delete` 的方法**取体，issue #4608 的显式写列守卫）—— 塞进同一方法会让护栏
//      判据与守卫锚点纠缠（CI 实测红）；独立端点让两条路径各自可 grep、各自可单测；
//    - **B 看得见**：抽屉里按**部位逐格**给 `做 / 不做` 控件（`drawer-applicable-{工序}-{部位}`，
//      价并排渲染在 `drawer-price-{工序}-{部位}`）；主表格的 `⇄` 换成**有可见文字**的 `做` / `不做`
//      （同一个 `ApplicableToggle`）—— 两处**共用一份**控件，不靠 hover 才知道它是什么；
//    - **反向护栏（不得放宽）**：主线 / 规则两条对一键按钮**照样拦**（主线涉及车间顺序，必须人工确认）
//      ⇒ 被拦时理由逐条就地展示、弹框不收摊、矩阵**不被动**（一格都不摘）；
//    - 三态语义**不变**（`不做` / `未定价`（≠ ¥0.00） / `¥x.xx`）；`DELETE /operations/{id}` 不带参数时
//      行为**一字不变**（矩阵格仍是硬护栏 —— 反向证明「护栏没被放宽」）。
// ㉙ **抽屉死路：矩阵格关联不上时也必须能停用/删除**（issue #4674；用户原话
//    「**这条测试数据已经没有办法删除了，无删除入口**」+ 截图：抽屉只有一句死路文案 + 一个「关闭」，
//    而主表格里 `测试22` 那一行**还在**）：
//    - **病根（三条）**：① 停用/删除**挂在「各部位的设置」行内**（`manageVariants` 为空 ⇒ 没有入口）；
//      ② **两把尺**：表格按**逻辑名**成行、抽屉按 `variant_operation_id` 找格（该键 NULL / 指向别处
//      ⇒ 抽屉静默空，而后端护栏③按 `variantNameOf` 照样认得出这道工序）；③ 空态文案
//      「请核对各部位的适用性配置」是**死路指引**（页面上没有地方可核对）；
//    - **A 抽屉层入口**（`operations-manage-disable` / `operations-manage-delete`）：渲染在**抽屉层**、
//      **不依赖** `manageVariants` 是否为空（工序库那一行确实存在）⇒ 永远有路可走；
//      ~~删除走**既有** `DELETE /operations/{id}`（软删；#4671 的一键端点 `…/detach-and-delete`
//      是**另一条**路径，本入口不用它）~~ —— **已被 ㉚ / issue #4692 改判**：删除**路径**改由
//      「与护栏③同一把尺（按名字）」定（有「做」的格 ⇒ 走 `…/detach-and-delete`）；
//      旧口径（一律普通删除）正是用户第 3 次「仍然不能删除」的成因，**勿再照抄**；
//    - **B 空态给出路**（`operations-manage-empty` 里）：说清**为什么**空 + **两个可点动作**
//      （「接入部位…」复用 #4614 的孤儿接入流程、「删除这道工序」）—— 不再写「请核对配置」；
//    - **C 两把尺对齐**：`variant_operation_id` 关联不上时**回退按逻辑名**认这道工序（与后端
//      `variantNameOf` 同一口径），并**显式提示** `operations-manage-unlinked-hint`
//      「这些格没有关联到它」；指向**别处**的格只如实报出（`variant-foreign-*`）、**不给写面**
//      （对它 PUT/DELETE 就是改另一道工序）—— **不许只改文案掩盖不一致**；
//    - **反向护栏（不得放宽）**：主线 / 规则两条对抽屉层删除**照样拦**（422 ⇒ 理由逐条就地展示、
//      弹框不收摊、矩阵**一格都不动**）；无主线/规则引用 ⇒ 删除**成功**；
//    - **红证（修复前实测，窄跑 `-t ㉙`）**：7 failed（`Unable to find an element by:
//      [data-testid="operations-manage-disable"]` / `…-delete` / `…-unlinked-hint`）⇒ 实现后全文件 147/147 绿。
// ㉚ **删除死路（第 3 次）：前后端判据必须同一把尺（按名字）**（issue #4692；用户原话
//    「**仍然不能删除**」+ 截图：#4674 已部署后的新抽屉说「它在部位价目矩阵里有 2 个格，而这些格
//    **都没有关联到它**」⇒ 点删除**仍然失败**）：
//    - **病根 = 两把尺**：前端按格的 `variant_operation_id` 判「有没有格关联到它」（关联键为 null
//      ⇒ 判「没有」⇒ 选**普通删除**）；后端护栏③（`ProductionOperationCommandService.matchingCells`
//      + `variantNameOf`）按**名字**判（格 `logical_name = 测试22` ⇒ 命中 + `applicable=true` ⇒ 422）
//      ⇒ 前端说能删、后端拒绝 ⇒ **必然失败**；
//    - **修法（治本）**：删除**路径的选择不再看 `variant_operation_id`** —— 判据 `opDeleteBlockerCells`
//      = 「本行（行键 = 逻辑工序名）里仍是「做」的格」：有 ⇒ `detachPositions: true`（#4671 的
//      `…/detach-and-delete`，后端**同一事务**先设为不做 + 级联软删矩阵行 + 删除）；没有 ⇒ 才用普通软删。
//      它与后端**同向**（按名字）且是后端命中集的**超集** ⇒ **fail-safe**（绝不会在后端会拦时选普通删除）；
//      `variant_operation_id` 只留作**展示**（「这些格未关联到本工序」仍是有价值的信息）；
//    - **A~E**：A 用户形态走 detach 且真删掉（**红证**：改前普通删除 ⇒ 护栏③ 422）；B 两把尺一致
//      （注入「FE 按 id 判、BE 按名判」⇒ 必红：每一次删除都只能是 detach 那条路）；C 正文
//      「删除这道工序」入口也走通（**没有**按名字命中的格 ⇒ 才用普通软删）；D 抽屉里**变体行**的删除
//      入口不再死路（普通删除不渲染 —— 它只会 422）；E **护栏不放宽**（主线/规则对新路径照样拦、
//      理由逐条、弹框不收摊、矩阵一格不动）。
//    - **红证（修复前实测）**：把删除的路径判据临时改回「一律普通删除」（+ 变体弹框改回只看按 id 那把尺）
//      后窄跑 `-t 4692` ⇒ **5 failed**（㉙-③ / A / B / D / E）—— B 的判词是
//      `expected undefined to deeply equal { detachPositions: true }`（发出去的正是**不带参数**的普通删除，
//      被护栏③打桩 422）；D 的判词是 `Unable to find an element by:
//      [data-testid="variant-detach-and-delete-op-test22"]`（改前那条路根本没给出来）。
//      C 是「**没有**按名字命中的格 ⇒ 才用普通软删」的回归锁（改前改后都绿，**不是**红证）。
// ㉛ **工艺项两层改造**（issue #4677 = 设计 `docs/design/public-operations-and-craft-ui.md` §4 / §6 / §7；
//    用户裁定「把 UI 改造作为 #4673 的一部分」；后端 #4676 已合并）：
//    - **两层**：`【工序】`（按**车间分组可折叠** —— 裁剪（裁床）/ 车位（缝制）/ 后整（烫工及后整）/ 质检，
//      **行业术语**，界面**不得**出现「槽位」这类我们发明的词）+ `【打包发货】`（**一列价**：单价 元/套 + 必完）；
//    - **分区判据 = 既有 `scope`**（`scope='set'` ⇒ 交付环节；其余含 `null` ⇒ 工序）—— **不新造概念**，
//      也**不是**「有没有矩阵格」（判据换成格 ⇒ 交付工序在某部位没格时整行消失 = #4674 形态）；
//    - **列收窄到部位词表**（`布帘 / 纱帘 / 帘头`）：`布料` 是**销售形态**不是窗帘部位 ⇒ 不再当第 4 列；
//      ⚠️ **只收窄列、不动数据** —— `布料` 的格仍在读面里（`variant_operation_id` 的载体、V88 的保命格），
//      孤儿判据（#4614）与「新建路线 / 新增工序」的勾选项（`positionOptions`，含 `布料`，#4556）**逐字不变**；
//    - 🔴 **硬要求**（#4677 评论逐字）：「商家必须能在一个明确、可见的位置给布料单的 `裁剪` 与 `打包` 定价，
//      **且不依赖矩阵里存在「布料」列**」⇒ 新增 `【布料单】` 小区（`fabric-sheet-section`）：`裁剪` + `打包`
//      各一行、一列价，**读写 `× 布料` 那一格本身**（走既有 `PUT /operation-positions/{id}`）；
//      **取舍**：不用「工序库行价」（`buildRoute` 的回落条件 = 「格存在 + 做 + 价 NULL」且回落值是
//      `NOT NULL DEFAULT 0` ⇒ 标「布料单按此价」会把**未定价显示成真 0 元**，且格不存在时它根本不参与实例化）；
//    - **#4674 从根上避免（四条约束）**：① 第二层的行**不依赖矩阵格**（判据是 `scope`）⇒ 一格都没有也有行 + `管理▸`；
//      ② `管理▸` **在行上**（`ManageButton`，两个分区共用）；③ 停用/删除渲染在 `manageVariants.map(...)`
//      **循环体外**（既有形态，本单**回归**锁住）；④ 空态**给出路**（两个可点动作，不写页面里没有的指引）；
//    - **种子自愈（§6，与模型无关）**：① 「补套行业模板」入口从「只在工序库为空时显示」改成
//      「**缺失即显示**」（工序库为空 ∨ 两条基础路线不齐；幂等）；② **就绪度②** 从「数条数」改成
//      「**两条基础路线是否齐**」并**点名**（`窗帘工序路线（默认）` / `布料工序路线`，与后端常量逐字同名）；
//    - **端点接入（验收协议 v1.11 三问）**：页面**真的调** `GET /operation-layers`（改前**零前端调用点**
//      ⇒ 文件在 main ≠ 被触发）；入口 = 「工艺项」tab（**默认 tab**，首屏即触发）；
//      `GET /operation-positions` 仍调（拿格的 `id` ⇒ 抽屉写面寻址）——两条读面**同一份数据**；
//    - **红证（修复前实测）**：把 `page.tsx` 换回 `origin/main` 版本后窄跑本组 ⇒ **17 failed**
//      （`delivery-section` / `matrix-workshop-toggle-裁剪` / `fabric-sheet-section` / `seed-templates`
//      均 `Unable to find an element`；就绪度② `data-state` 仍是 `done`；`getOperationLayers` 恒未被调用）
//      ⇒ 实现后全文件 170/170 绿。
// ㉜ **抽屉去重：逐行那一对「停用 / 删除」退场 + footer 目标行统一**（issue #4947；用户裁定
//    「抽屉里每行的停用/删除按钮和底部的重复了」）：
//    - **删什么**：抽屉正文每一行里那一对 `variant-disable-{id}` / `variant-delete-{id}` **整对退场**
//      （连同 `variant-delete-modal` 那一套弹框与 `variant-delete-reasons`）—— 同一屏两个「删除」
//      正是用户报的形态；**保留** footer 的 `operations-manage-disable` / `operations-manage-delete`
//      与空态的 `operations-manage-delete-empty`（#4674 B 要求空态给两个出路，本单不动它）；
//    - **信息不许丢**：行内那句「删除后历史报工不受影响」**搬到 footer 的「删除」旁边**；
//    - **目标行统一**（本单的实质修复）：footer 的停用/删除按**抽屉当前展示的那一行**
//      （`manageTargetOp` = 第一个非 `foreign` 变体对应的库行；查不到才回落 `manageOpEntry.op`）
//      寻址 —— 改前按**逻辑名的首行**（`fallbackOpByName`）寻址，同名多行（`布三边` / `纱三边`）
//      时会「看见 A、动的是 B」；判据见 #4947-②（读面指 `op-b` ⇒ 必须动 `op-b`、不得动首行 `op-a`）；
//    - **写面失败不得静默（本单收口）**：改前 `variantReasons`（逐行写面被拒的理由）**唯一**的渲染点
//      就在那套被删的弹框里 ⇒ 删除会让它变成**只写不读**。现在它在抽屉顶部有一个渲染点
//      `variant-reasons`（与 footer 写面的 `operations-manage-op-reasons` **分开**：两处触发源不同），
//      判据 = **#4947-③**（`PUT /operations/{id}` 被拒 ⇒ 理由逐条上屏，且不得渲染成 footer 那条）；
//    - **用例迁移（不留指向已删 testid 的死判据）**：驱动逐行路径的用例全部改走 footer
//      （⑰-⑩ / ㉖-④ / ⑰-⑬ / ⑰-⑮ / ⑲-⑤ / #4665-C ×2）；**删除**三条与 footer 用例逐字重复的：
//      ⑰-⑭（⇒ ㉙-③ 同场景：detach 删除 + 刷新）、#4665-B（⇒ ㉙-③ + #4692-A：一次请求 + 弹框说清后果）、
//      #4692-D（⇒ #4692-A 同夹具同形态、断言更强）；㉙-⑧ 改判为 **#4947-①**（逐行入口**已退场**，
//      不再断言「一个都没少」—— 那条断言随本单**反转**）。
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
const mockGetOperationLayers = vi.fn()
/**
 * `getOperationPositions` 的替身（issue #4677）：**自带一份当前夹具**，并在夹具被换掉时
 * **同步**给两层分区读面（`getOperationLayers` ⇒ `buildLayers(夹具)`）。
 *
 * <p>为什么需要同步：页面读**两个**端点 —— ① `GET /operation-positions`（拿格的 `id` ⇒ 抽屉
 * 写面寻址）与 ② `GET /operation-layers`（分区 + 一列价聚合）。两者必须是**同一份**数据
 * （否则「工序层」与「打包发货层」会对不上）。而各用例历来只换 ① 的夹具
 * ⇒ 用 `setDefault` 一处换、两处同步，**既有写法逐字不变**。</p>
 *
 * <p>⚠️ 不用「② 直接调 ①」的委托写法：`mockResolvedValueOnce` 的**一次性队列**会被调两次，
 * 让那些「首次 X、之后 Y」的用例（抽屉开着时读面变空那一族）静默错位。</p>
 */
const makePositionsSpy = () => {
  let current: unknown = []
  const spy: any = vi.fn(() => Promise.resolve(current))
  /** 换夹具（等价于原来的 `mockReset().mockResolvedValue(ok(v))`），并同步分区读面 */
  spy.setDefault = (v: unknown) => {
    current = ok(v)
    // ⚠️ **不要** `mockReset()` 分区读面：那会连**实现**一起清掉 ⇒ 页面 await 到 `undefined`
    // ⇒ `templateRes.value.data` 抛未处理拒绝（假红）。`mockResolvedValue` 是替换而非清除实现。
    // 🔴 issue #4729：交付行来自**工序库**（`scope='set'` 的行），不是矩阵格 ⇒ 打桩必须同源
    // （否则零矩阵格的交付工序在这份替身里**不存在**，掩盖真后端的缺口）。
    mockGetOperationLayers.mockResolvedValue(ok(buildLayers(v as any[], LAYER_DELIVERY_OPS)))
    spy.mockClear()
    return spy
  }
  /** 「首次 v、之后沿用当前夹具」—— 一次性队列只由**页面那一次**读面消费 */
  spy.setDefaultOnce = (v: unknown) => {
    spy.mockImplementationOnce(() => Promise.resolve(ok(v)))
    return spy
  }
  /** 读面失败（端点挂了）：分区读面同样跟着失败（两处口径一致） */
  spy.setDefaultRejected = (e: unknown) => {
    mockGetOperationLayers.mockRejectedValue(e)
    spy.mockClear()
    return spy
  }
  spy.setDefaultRejectedOnce = (e: unknown) => {
    spy.mockImplementationOnce(() => Promise.reject(e))
    return spy
  }
  return spy
}
const mockGetOperationPositions = makePositionsSpy()
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
    getOperationLayers: (...a: unknown[]) => mockGetOperationLayers(...a),
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
  // 算料口径说明区块的**算例**自 #5036 包 2a 起由服务端给 ⇒ 本页挂载即发两次判定请求。
  // 本替身逐值复刻引擎 `detect_auto_features` 的判据（示例几何：宽 2 / 高 2.6 / 门幅 2.8）。
  autoFeaturesApi: {
    preview: (p: { width: number; height: number; fabric_width?: number; cutting_mode?: string }) => {
      const side = 0.3
      const hem = 0.3
      const fullness = 2.0
      const round = (v: number) => Number(v.toFixed(3))
      const door = p.fabric_width ?? 0
      const features: Array<{ name: string; source: string; reason: string }> = []
      if (p.cutting_mode === '定宽买高') {
        const product = (p.width + side) * fullness
        if (product > door) {
          features.push({
            name: '超宽',
            source: '推算',
            reason: `成品宽 ${p.width} + 左右余量 ${side} = ${round(p.width + side)} 米 × 褶倍 ${fullness} = ${round(product)} 米 > 门幅 ${door} 米`,
          })
        }
        features.push({ name: '倒幅', source: '推算', reason: '加工类型 = 定宽买高' })
      } else if (p.height + hem > door) {
        features.push({
          name: '超高',
          source: '推算',
          reason: `成品高 ${p.height} + 上下卷边 ${hem} = ${round(p.height + hem)} 米 > 门幅 ${door} 米`,
        })
      }
      return Promise.resolve({
        data: { data: { auto_features: features, notices: [], door_width: door, fullness_used: fullness, notice: '' } },
      })
    },
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

/**
 * **工序库的交付环节行**（`production_operations` 里 `scope='set'` 的四道）—— issue #4729。
 *
 * <p>🔴 这是 `delivery` 段的**行来源**（真后端 `ProductionRoutingReadService.operationLayers`
 * 按工序库行分区，**不看矩阵格**）⇒ 替身必须带上它，否则「零矩阵格仍有行」这条判据在测试里
 * **不可能被构造**（原打桩只按格造行，掩盖了真后端的缺口 = 独立验收 #4677 的 P1-2）。</p>
 *
 * <p>`unit` / `group` / `is_must_finish` 与矩阵格夹具（{@link LAYER_CELLS}）逐字一致
 * —— 真数据里它们是**同一行工序**的元数据，格上的值就是从这行带出来的。</p>
 */
const LAYER_DELIVERY_OPS = [
  { id: 'lop-打包', name: '打包', group: '后道', unit: '套', scope: 'set', is_must_finish: true },
  { id: 'lop-外帘打卷', name: '外帘打卷', group: '后道', unit: '套', scope: 'set', is_must_finish: false },
  { id: 'lop-外帘装袋', name: '外帘装袋', group: '后道', unit: '套', scope: 'set', is_must_finish: true },
  { id: 'lop-外帘发货', name: '外帘发货', group: '后道', unit: '套', scope: 'set', is_must_finish: true },
]

/** 查不到变体 ⇒ 契约 #4587 ① 的 6 个新键**全 null**（不是空串、不是 0） */
const NO_VARIANT = {  variant_operation_id: null,
  unit: null,
  group: null,
  scope: null,
  is_must_finish: null,
}

/**
 * 价目读面夹具（issue #4588 起每行带行 `id` + 变体元数据；契约 #4587 ①）。
 * **服务端顺序** = `(operation, position)`（Java 自然序：三边 < 精裁 < 车被 < 韩褶）。
 * 价态齐备 —— ① 有价 ② **未定价**（`unit_price=null`）③ **真 0 元**（`车被`/`布帘` = 0 ⇒
 * 必须显示 `¥0.00`，≠「未定价」）。
 * ⚠️ **2026-09-21（#4937 / #4951）**：原「**不做**（`applicable=false`）」那一态**已退场** ——
 * 本夹具随之不再带 `applicable`（该字段在 `OperationPosition` 类型里已不存在）。多行形态仍保留：
 * 它同时是「按逻辑名去重收敛」的夹具（真读面在 #4951 后每逻辑工序**只有一行**、`position` 恒 `通用`）。
 *
 * 变体元数据三种形态齐备（判据不是「能渲染」，而是「不许静默取第一个」）：
 * - `三边`：两格变体同为 `车位 · 米` ⇒ 行尾取**公共值**；
 * - `精裁`：两格变体分组**不同**（裁剪 / 车位）⇒ 行尾必须**两个都列出**；
 * - `车被`：一格有变体（`后道 · 件 · 套级 · 必完`）⇒ 抽屉可改作用域/必完；
 * - `韩褶`：矩阵里查不到变体（6 键全 null）⇒ 行尾不发明元数据、抽屉给「没有变体」提示。
 */
const POSITIONS = [
  { id: 'pos-三边-帘头', operation: '三边', position: '帘头', unit_price: null, ...NO_VARIANT },
  { id: 'pos-三边-布帘', operation: '三边', position: '布帘', unit_price: 1.2, variant_operation_id: 'op-三边-布', unit: '米', group: '车位', scope: 'position', is_must_finish: false },
  { id: 'pos-三边-纱帘', operation: '三边', position: '纱帘', unit_price: null, variant_operation_id: 'op-三边-纱', unit: '米', group: '车位', scope: 'position', is_must_finish: false },
  // ⚠️ 真数据里一道工序**只属一个车间**（`group` 是库行元数据）。夹具里 `精裁` 两格分组不同
  // （裁剪 / 车位）是**故意**造的「不一致 ⇒ 逐个列出」形态（见 ⑰-②）；`三边` 两格同组 ⇒ 不冲突。
  // `帘头` 回落复用 `布帘` 的变体（真值源 `variantNameOf` 的第 2 步）—— 夹具照真形态给
  // `variant_operation_id`，否则这一格在抽屉里**不出现**（抽屉按 `variant_operation_id` 去重）。
  { id: 'pos-精裁-帘头', operation: '精裁', position: '帘头', unit_price: null, variant_operation_id: 'op-精裁-布', unit: '套', group: '裁剪', scope: 'position', is_must_finish: true },
  { id: 'pos-精裁-布帘', operation: '精裁', position: '布帘', unit_price: 8.5, variant_operation_id: 'op-精裁-布', unit: '套', group: '裁剪', scope: 'position', is_must_finish: true },
  { id: 'pos-精裁-纱帘', operation: '精裁', position: '纱帘', unit_price: 6, variant_operation_id: 'op-精裁-纱', unit: '套', group: '车位', scope: 'position', is_must_finish: true },
  { id: 'pos-车被-帘头', operation: '车被', position: '帘头', unit_price: null, ...NO_VARIANT },
  { id: 'pos-车被-布帘', operation: '车被', position: '布帘', unit_price: 0, variant_operation_id: 'op-车被', unit: '件', group: '后道', scope: 'position', is_must_finish: true },
  { id: 'pos-车被-纱帘', operation: '车被', position: '纱帘', unit_price: null, ...NO_VARIANT },
  { id: 'pos-韩褶-布帘', operation: '韩褶', position: '布帘', unit_price: 2, ...NO_VARIANT },
  // 部位无关工序（`外帘打卷/装袋/发货`）**也是** 30 道逻辑工序之一（真值源
  // `routing.py::OPERATION_POSITION_PRICES`）⇒ 真数据里它有矩阵格。夹具里补上这一格是**必须**的：
  // issue #4622 补口① 起「主线里的工序是否存在」按**矩阵的逻辑工序名**判，夹具缺这格会让
  // `外帘装袋` 被误报「不存在」（真数据不会 —— 这正是夹具与真值的差异）。
  { id: 'pos-外帘装袋-布帘', operation: '外帘装袋', position: '布帘', unit_price: 1.0, variant_operation_id: 'op-v54-04', unit: '套', group: '后道', scope: 'set', is_must_finish: true },
]

/**
 * **两层分区读面的等价打桩**（issue #4677；契约 #4676；**行来源修正 = issue #4729**）：
 * 复现**真后端**的两段 —— `operations` = 矩阵行里不属于交付工序集合的那些；
 * `delivery` = **工序库**里 `scope='set'` 的行（**不是**矩阵行！）各一行、聚合成一列价。
 *
 * <p>🔴 **为什么必须按工序库给行**（issue #4729 = 独立验收 #4677 的 P1-2）：原打桩只按矩阵格
 * 造 `delivery` 行 ⇒ 它**掩盖**了真后端的缺口（`ProductionRoutingReadService.operationLayers`
 * 当时遍历 `operationPositions()` = 只读矩阵表 ⇒ 零矩阵格的套级工序在 `delivery` 段一行都没有）。
 * 现在的形态与真后端同源：交付行的**存在**只取决于工序库行的 `scope`，格只决定**价态**。</p>
 *
 * <p>⚠️ 聚合口径**逐条照抄后端** `ProductionRoutingReadService.deliveryView`（判据是**行为等价**）：
 * ① 有 `NULL` ⇒ `unpriced`（**未定价 ≠ ¥0.00**，且**不回落工序库行价**）；② 价全同 ⇒ `priced`；
 * ③ 不同 ⇒ `multiple_prices` + `different_price_count`（**不静默取第一个**）。
 * 🔴 **2026-09-21（#4951 去部位化彻底版）**：第 4 态 `no_applicable_position` **已退场**
 * （存活行 `applicable` 恒 `TRUE` ⇒「一格『做』都没有」不再可达）⇒ **零格判 `unpriced`**；
 * `applicable_positions` **键保留但恒 `[]`**（9 键契约不变 —— 部位维已退场）。
 * 行尾元数据缺格时回落工序库行（与后端 `firstNonNull(cells, key, library, key)` 同一顺序）。</p>
 *
 * <p>夹具里 `车被` 是**部位级**工序（真值源 `routing.py` 的 `布帘车被`，`scope='position'`），
 * `外帘装袋` / `打包` 是**套级**（V79 的 `SET scope='set'`）⇒ 分区后：工序层 = 三边 / 精裁 / 车被 /
 * 韩褶，交付层 = 工序库里 `scope='set'` 的那几道。</p>
 *
 * @param cells 矩阵格（`GET /operation-positions` 的响应）
 * @param libraryOps 工序库行（`scope` 是**行**上的属性；缺省 = 从 `cells` 里取 `scope='set'`
 *                   的那些工序名 —— 只为兼容不关心交付层的旧用例）
 */
const buildLayers = (cells: any[], libraryOps: any[] = []) => {
  // 交付工序集合 = 工序库的 `scope='set'` 行（**不看格**）；缺省兜底见上
  const catalog = libraryOps.length > 0
    ? libraryOps
    : cells.filter((c) => c.scope === 'set').map((c) => ({ name: c.operation, scope: 'set' }))
  const deliveryOps = catalog.filter((o) => o.scope === 'set').map((o) => String(o.name))
  const cellsByOp = new Map<string, any[]>()
  const operations: any[] = []
  for (const c of cells) {
    if (deliveryOps.includes(c.operation)) {
      cellsByOp.set(c.operation, [...(cellsByOp.get(c.operation) ?? []), c])
    } else {
      operations.push(c)
    }
  }
  const delivery = deliveryOps.map((operation) => {
    const group = cellsByOp.get(operation) ?? []
    const library = catalog.find((o) => String(o.name) === operation)
    const prices = [...new Set(group.filter((c) => c.unit_price != null).map((c) => c.unit_price))]
    const unpriced = group.some((c) => c.unit_price == null)
    // 🔴 #4951：第四态 `no_applicable_position` 退场 ⇒ **零格判 `unpriced`**（不再有「没有适用部位」）
    const price_state =
      unpriced || group.length === 0
        ? 'unpriced'
        : prices.length === 1
          ? 'priced'
          : 'multiple_prices'
    const first = (k: string) => group.find((c) => c[k] != null)?.[k] ?? library?.[k] ?? null
    return {
      operation,
      scope: 'set',
      unit: first('unit'),
      group: first('group'),
      is_must_finish: first('is_must_finish'),
      price: price_state === 'priced' ? prices[0] : null,
      price_state,
      different_price_count: price_state === 'multiple_prices' ? prices.length : 0,
      // 键保留（9 键契约不变）但**恒 `[]`**（部位维已退场，见函数头注）
      applicable_positions: [],
    }
  })
  return { operations, delivery }
}

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
 *
 * issue #4962：后端 `GET /route-rule-options` **新增 `positions` 键** = **部位闭词表**
 * （基线三部位 ∪ 第 4 个部位 `布料`）—— 部位维的取值同样**只能从这里取**（前端不硬编码字面量）。
 */
const RULE_TRIGGER_OPTIONS = {
  crafts: ['韩褶', '打孔', '罗马帘'],
  processing_items: ['花边', '扣环', '拼接'],
  positions: ['布帘', '纱帘', '帘头', '布料'],
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
  // 🔴 #5030：宽方向的 `side_margin` 已整体退场（用户 2026-09-21 裁定）⇒ 换回**仍在场**的高方向卷边键
  hem_margin: 0.3,
  meters_rounding_step: 0.1,
  // 🔴 #5130：两个**企业阈值**（超宽 / 超高判据）；默认 6 / 4，与引擎常量逐值一致
  oversize_width_threshold: 6,
  oversize_height_threshold: 4,
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

/**
 * **后端护栏③ 的等价打桩**（issue #4692）：判据 = **按名字** —— `测试22` 这一行里还有「做」的格
 * ⇒ **普通删除必然 422**（`DELETE /operations/{id}`）；`detachPositions` 那条路（#4671 的
 * `…/detach-and-delete`，后端同一事务里先设为不做再删）**能过**。
 *
 * <p>它就是「两把尺」里的**后端那把尺**（真实语义见 `ProductionOperationCommandService.matchingCells`
 * —— 按 `variantNameOf` 解析，**从不看**格的 `variant_operation_id`）。前端改不动它 ⇒ 前端只能改自己的
 * 路径选择；用它打桩，「前端按 id 判 ⇒ 必然 422」这件事在单测里才**真的会红**（不是纸面断言）。</p>
 */
const beGuardByName = () =>
  mockDeleteOperation.mockImplementation(
    async (_id: unknown, opts?: { detachPositions?: boolean }) => {
      if (opts?.detachPositions) return ok({ id: 'op-test22', deleted: true, detached_positions: 1 })
      throw guardError([
        '工序「测试22」还挂在部位价目矩阵的「测试22 × 布帘」格上且该格是「做」—— 先在该部位设为「不做」，再删它',
      ])
    },
  )

/** 渲染并切到「工艺路线」tab（路线内容在第二个 tab，默认落在「工艺项」） */
const renderOnRoutes = async () => {
  render(<ProcessConfigPage />)
  await waitFor(() => expect(screen.getByTestId('process-config-tab-process')).toBeInTheDocument())
  await userEvent.click(screen.getByTestId('process-config-tab-process'))
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

/**
 * **用户实测的死路夹具**（issue #4674；用户原话「**这条测试数据已经没有办法删除了，无删除入口**」）：
 * 表格里**有** `测试22` 这一行（矩阵里有逻辑名 = `测试22` 的格），而抽屉里**空** ——
 * 因为格的 `variant_operation_id` **未指向**该工序（NULL）。
 * ⇒ 「行在 · 抽屉空 · 无处可删」：抽屉层原先只有「关闭」（正是截图形态）。
 *
 * 这是**真形态**、不是人造边界：`variant_operation_id` 由后端 `variantNameOf` 按
 * `(逻辑名, 部位)` 反查**当前**工序库得出 —— 查不到（如库里没有该变体）⇒ 5 键**全 null**
 * （见契约 #4587 ① 的 `NO_VARIANT`）。
 */
const CATALOG_WITH_TEST22 = {
  total: 6,
  groups: [
    ...CATALOG.groups,
    {
      group: '其他',
      operations: [
        { id: 'op-test22', name: '测试22', group: '其他', position: '布帘', scope: 'position', unit: '件', unit_price: 1, is_must_finish: false, is_start_marker: false },
        // 形态② 的对手方：`测试22` 的格**指向**它（指向别处）—— 它必须在库里，`foreign` 才成立
        { id: 'op-别的工序', name: '别的工序', group: '其他', position: '布帘', scope: 'position', unit: '件', unit_price: 1, is_must_finish: false, is_start_marker: false },
      ],
    },
  ],
}

/** 同上 + `测试22 × 布帘` 这一格：**格在、行在，但格没关联到这道工序**（`variant_operation_id = null`） */
const POSITIONS_WITH_TEST22 = [
  ...POSITIONS,
  { id: 'pos-测试22-布帘', operation: '测试22', position: '布帘', unit_price: 1, ...NO_VARIANT },
]

/**
 * **两把尺不一致**的形态（issue #4674 C）：`测试22` 的格里**有** `variant_operation_id`，
 * 但它指向**别的**工序（`op-别的工序`）⇒ 原先那几格在抽屉里**根本不出现**（静默空）。
 * 抽屉必须**显式提示**「这些格未关联到本工序」，而不是假装没有。
 */
const POSITIONS_TEST22_MISLINKED = [
  ...POSITIONS,
  { id: 'pos-测试22-布帘', operation: '测试22', position: '布帘', unit_price: 1, variant_operation_id: 'op-别的工序', unit: '件', group: '其他', scope: 'position', is_must_finish: false },
]

/**
 * **真形态**工序库夹具（issue #4642 读面归一：`name` = **逻辑工序名**，库口径原名走 `library_name`）
 * —— issue #4947 的「抽屉层目标行」口径必须在真形态下驱动。
 *
 * <p>为什么不能沿用上面那份 `CATALOG`（库口径旧名 `精裁-布` / `韩褶-布`）：抽屉层「停用 / 删除」
 * 按**逻辑名**寻址（`fallbackOpByName`）⇒ 在旧名夹具下这些工序的 footer 入口**恒禁用**
 * （`!manageOpEntry`），根本驱动不了写面。旧名那份留着给不关心写面的用例（如 ⑰-⑫ 的空态）。</p>
 *
 * <p>🔴 `三边` 是**同名两行**的形态（`布三边` = `op-a` / `纱三边` = `op-b`）：按逻辑名取到的
 * **首行**与价目读面**指到的那一行**不是同一行 —— 这正是 issue #4947 要治的「两把尺」。</p>
 */
const LOGICAL_CATALOG = {
  total: 4,
  groups: [
    {
      group: '裁剪',
      operations: [
        { id: 'op-精裁-布', library_name: '精裁-布', name: '精裁', group: '裁剪', position: '布帘', scope: 'position', unit: '套', unit_price: 8.5, is_must_finish: true, is_start_marker: true, source: '占位待确认' },
      ],
    },
    {
      group: '车位',
      operations: [
        { id: 'op-a', library_name: '布三边', name: '三边', group: '车位', position: '布帘', scope: 'position', unit: '米', unit_price: 1.2, is_must_finish: false, is_start_marker: false },
        { id: 'op-b', library_name: '纱三边', name: '三边', group: '车位', position: '纱帘', scope: 'position', unit: '米', unit_price: 1.2, is_must_finish: false, is_start_marker: false },
      ],
    },
    {
      group: '后道',
      operations: [
        { id: 'op-车被', library_name: '车被-布', name: '车被', group: '后道', position: '布帘', scope: 'position', unit: '件', unit_price: 0, is_must_finish: true, is_start_marker: false },
      ],
    },
  ],
}

/**
 * issue #4947 的**口径夹具**：逻辑名 `三边` 在工序库里有**两行**（`布三边` = `op-a` /
 * `纱三边` = `op-b`），而**价目读面**（`GET /operation-positions`；#4886 起一道工序一行）
 * 指到的是**第二行** `op-b` ⇒ 「按逻辑名的首行」与「抽屉当前展示的那一行」**不是同一行**。
 */
const POSITIONS_READFACE_OP_B = [
  { id: 'pos-三边-布帘', operation: '三边', position: '布帘', unit_price: 1.2, applicable: true, variant_operation_id: 'op-b', unit: '米', group: '车位', scope: 'position', is_must_finish: false },
]

describe('工艺配置页 /production/routings（新路线模型，issue #4433 = 母单 #4423 的 P3）', () => {
  beforeEach(() => {
    mockGetOperationsCatalog.mockReset().mockResolvedValue(ok(CATALOG))
    mockGetRoutings.mockReset().mockResolvedValue(ok(ROUTINGS))
    mockGetSeedTemplates.mockReset().mockResolvedValue(ok(TEMPLATES))
    mockGetOperationPositions.setDefault(POSITIONS)
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




  it('部位价目矩阵：端点失败只在该区给可读提示（不白屏、不影响其余区）', async () => {
    mockGetOperationPositions.setDefaultRejectedOnce(new Error('500'))
    render(<ProcessConfigPage />)

    await waitFor(() => expect(screen.getByTestId('operation-price-matrix-error')).toHaveTextContent('工序单价加载失败'))
    // 路线半边照常（切过去仍渲染真实数据）
    await userEvent.click(screen.getByTestId('process-config-tab-process'))
    await waitFor(() => expect(screen.getByTestId('routings-total')).toHaveTextContent('2'))
  })

  // ══════════════════ ③ 具名路线（name + 默认徽标 + 主线道数） ══════════════════

  it('路线列表显示 name + 默认徽标 + 主线道数；不再出现「部位 × 工艺」标题与「适用帘种」', async () => {
    await renderOnRoutes()
    await waitFor(() => expect(screen.getByTestId('routings-total')).toHaveTextContent('2'))

    const box = screen.getByTestId('routing-11')
    expect(within(box).getByTestId('routing-name-11')).toHaveTextContent('窗帘工序路线（默认）')
    expect(within(box).getByTestId('routing-default-11')).toHaveTextContent('默认')

    expect(within(box).getByTestId('routing-mainline-count-11')).toHaveTextContent('3')

    // 非默认路线**不得**带默认徽标（注入：徽标写死 ⇒ 红）
    expect(within(screen.getByTestId('routing-12')).queryByTestId('routing-default-12')).toBeNull()


    // 旧形态退场：**路线区**不再按 (部位 × 工艺) 渲染、也不出现「适用帘种」。
    // ⚠️ 判据收敛到路线区（`routings-list`）：合并成同屏之后，工序表的说明文案里有
    // 「报工工资 = 数量 × 计件单价」这个乘号 ⇒ 整页 `not.toContain('×')` 已不是本判据的表达。
    const routesPanel = screen.getByTestId('routings-list')
    expect(routesPanel.textContent ?? '').not.toContain('×')
    expect(routesPanel.textContent ?? '').not.toContain('适用帘种')
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

  it('算料配置面板的说明文案**不得漏出 markdown 星号**（issue #5033 顺手修）', async () => {
    // 红证：把 `保存后<strong>新</strong>的算料` 改回 `保存后**新**的算料` ⇒ 下面两条断言红
    //（用户截图实证：JSX 纯文本里的 `**` 会**原样渲染**成字面星号，不是加粗）。
    mockGetCraftCalcConfig.mockReset().mockResolvedValue(ok({ source: 'stored', config: ENGINE_DEFAULT_CALC_CONFIG }))
    render(<ProcessConfigPage />)
    await waitFor(() => expect(screen.getByTestId('operation-price-matrix')).toBeInTheDocument())
    await userEvent.click(screen.getByTestId('process-config-tab-calc'))
    await waitFor(() => expect(screen.getByTestId('craft-calc-config-panel')).toBeInTheDocument())

    const panel = screen.getByTestId('craft-calc-config-panel')
    // ⚠️ 只钉**这一句**：面板里其它区（术语说明）的散文仍带 markdown `**`（**已知的更大问题**，
    // 见 issue #5033 的登记）⇒ 断言整块 textContent 不含 `**` 会因那些存量而红（**假红**）。
    expect(panel.textContent).not.toContain('保存后**新**')
    expect(within(panel).getByText('新', { selector: 'strong' })).toBeInTheDocument()
    expect(panel).toHaveTextContent('保存后新的算料按当前配置计算')
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

  // ══════════════════ ⑨d 算料口径与术语说明（issue #4975） ══════════════════
  //
  // 判据的**取值域写死在测试里**（不从实现推导）：六个标量键 / 三个自动推算特征 / 两个手选特征。
  // 跨源守卫（文案 vs 引擎源）在 `tests/unit/lib/craft-calc-glossary.test.ts`；本段只判**页面渲染**。

  it('⑨d-① 参数旁「说明」锚点指到同 tab 的说明条目（六个标量键各一条，不指空）', async () => {
    mockGetCraftCalcConfig.mockReset().mockResolvedValue(ok({ source: 'default', config: ENGINE_DEFAULT_CALC_CONFIG }))
    render(<ProcessConfigPage />)
    await waitFor(() => expect(screen.getByTestId('operation-price-matrix')).toBeInTheDocument())
    await userEvent.click(screen.getByTestId('process-config-tab-calc'))
    await waitFor(() => expect(screen.getByTestId('craft-calc-config-panel')).toBeInTheDocument())

    for (const key of ['per_fold_single', 'margin_single', 'margin_multi', 'min_fullness', 'hem_margin', 'meters_rounding_step']) {
      const href = screen.getByTestId(`craft-calc-config-doc-${key}`).getAttribute('href') ?? ''
      // 注入：把锚点写死成别的 id（或漏渲染该条目）⇒ getElementById 返回 null ⇒ 红
      expect(document.getElementById(href.replace('#', ''))).not.toBeNull()
    }
  })

  // 🔴 issue #5030 改判：原判据「`side_margin` 的口径是『左右覆盖余量』」的前提**已消失** ——
  // 用户 2026-09-21 裁定订单宽高 = 窗户宽高 ⇒ 「左右覆盖余量」**整体退场**（常量与配置键一并删除）。
  // ⇒ 改成**同强度的反向守卫**：这一项**已不在页面上**（加回该参数 ⇒ 下面三条红）。
  it('⑨d-② `side_margin` **已不在页面上**（宽方向无余量；旧文案不得复活）（issue #5030）', async () => {
    mockGetCraftCalcConfig.mockReset().mockResolvedValue(ok({ source: 'default', config: ENGINE_DEFAULT_CALC_CONFIG }))
    render(<ProcessConfigPage />)
    await waitFor(() => expect(screen.getByTestId('operation-price-matrix')).toBeInTheDocument())
    await userEvent.click(screen.getByTestId('process-config-tab-calc'))
    await waitFor(() => expect(screen.getByTestId('craft-calc-config-panel')).toBeInTheDocument())

    // 注入：把 `side_margin` 加回键集（或把旧文案抄回页面）⇒ 下面三条同时红
    expect(screen.queryByTestId('craft-calc-config-scalar-side_margin')).toBeNull()
    expect(screen.queryByTestId('craft-calc-config-doc-side_margin')).toBeNull()
    expect(screen.queryByText(/左右覆盖余量/)).toBeNull()
    // 反向自证：同一张表单里**仍在场**的高方向参数必须能被看见（否则上面三条是空断言）
    expect(screen.getByTestId('craft-calc-config-scalar-hem_margin')).toBeInTheDocument()
    expect(screen.queryByText(/定宽买高的上下卷边合计/)).toBeNull()
  })

  it('⑨d-③ 说明区块与参数同屏：三个自动推算算例带真实数字 + 手选两项的边界可见', async () => {
    mockGetCraftCalcConfig.mockReset().mockResolvedValue(ok({ source: 'default', config: ENGINE_DEFAULT_CALC_CONFIG }))
    render(<ProcessConfigPage />)
    await waitFor(() => expect(screen.getByTestId('operation-price-matrix')).toBeInTheDocument())
    await userEvent.click(screen.getByTestId('process-config-tab-calc'))
    await waitFor(() => expect(screen.getByTestId('craft-calc-config-panel')).toBeInTheDocument())

    // 注入：删掉说明区块 ⇒ 第一条红（区块没跟参数同屏 = 用户还得去别处找）
    expect(screen.getByTestId('craft-calc-glossary')).toBeInTheDocument()
    for (const name of ['超高', '超宽']) {
      // 算例自 #5036 包 2a 起由**服务端**给 ⇒ 异步取，必须 await
      // 🔴 #5130 改判：依据文案由「> 门幅 … 米」改为「> 超宽/超高阈值 … 米」（旧式依据复活 ⇒ 红）
      expect(await screen.findByTestId(`glossary-example-${name}`)).toHaveTextContent('阈值')
    }
    // `倒幅` 的算例依据 = 加工类型（与阈值 / 门幅无关）
    expect(await screen.findByTestId('glossary-example-倒幅')).toHaveTextContent('定宽买高')
    // 死亡条件绑 #4569：加工项特征**当前**只计价、不触发工序
    expect(screen.getByTestId('glossary-term-拼接')).toHaveTextContent('不触发工序')
    expect(screen.getByTestId('glossary-term-接高')).toHaveTextContent('待查明')
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
    // 工序层只有**一张**「车间矩阵」表（两张平铺表正是本次要治的形态）。
    // ⚠️ issue #4677：一屏现在是**两层**（【工序】+【打包发货】）外加一个【布料单】定价小区
    // ⇒ 这条断言按**新设计**改判成「工序层只有一张表」；
    // 判据本身（不得再出现第二张平铺的工序明细表）**一字不放宽**。
    expect(within(panel).getAllByTestId('operation-workshop-table')).toHaveLength(1)
    // 用户 2026-09-19 追加裁定：**作用域**收进抽屉 ⇒ 这个词不得出现在主表；
    // ⚠️ 同日**改判**（issue #4610）：「必完标记还是得在这里展示」⇒ 必完回到主表行尾，
    //    但它只是**只读标记**（维护面仍在抽屉里）—— 见 ⑳ 的三态断言。
    expect(within(panel).queryByText('作用域')).toBeNull()
  })


  // ══════════════════ #4960 / #4961：作用域写面与「必完」整体退场 ══════════════════
  // ⚠️ 这一组是**移除**类判据 ⇒ 红证形态 = 「改前**存在**，断言它**不存在**」
  // （`expected <select …> to be null`），而不是「找不到元素」那种反向表述。

  it('#4960-① 商家写面不再有「作用域」：抽屉里没有 `variant-scope-*`，且这一屏的写请求**不带** `scope` 键', async () => {
    // issue #4947：抽屉层写面按**逻辑名**寻址（真形态）⇒ 用真形态夹具驱动（本文件同族 10 处的既有惯例）
    mockGetOperationsCatalog.mockReset().mockResolvedValue(ok(LOGICAL_CATALOG))
    await openManage('车被')

    // ① 控件**退场**（不是禁用、不是隐藏）：改前这里是 `<select data-testid="variant-scope-op-车被">`
    expect(document.body.querySelector('[data-testid^="variant-scope-"]')).toBeNull()
    const drawer = screen.getByTestId('operations-manage-drawer')
    expect(drawer).not.toHaveTextContent('作用域')
    // 商家看不懂的那对词随之退场 —— 说明句不再解释这个维度
    // ⚠️ 只断言**作用域专属**的措辞：抽屉的「适用条件」一节里「特殊选项按**套**收费（元/套）」
    // 说的是**计价**（另一本账），与本项无关 ⇒ 不能拿光秃秃的「按套」当判据。
    expect(drawer).not.toHaveTextContent('每套窗只做一次')
    expect(drawer).not.toHaveTextContent('按件')

    // ② 维护面**其余各项一个都没少**（移除的是作用域这一项，不是整块写面）
    await userEvent.click(screen.getByTestId('variant-meta-edit-op-车被'))
    await userEvent.click(screen.getByTestId('variant-meta-save-op-车被'))
    await waitFor(() =>
      expect(mockUpdateOperation).toHaveBeenCalledWith('op-车被', { group_name: '后道', unit: '件' }),
    )
    // 停用：入口在抽屉 footer（issue #4947：逐行那一对与 footer 逐字重复 ⇒ 退场，写面只剩这一处）
    await userEvent.click(screen.getByTestId('operations-manage-disable'))
    await waitFor(() => expect(mockUpdateOperation).toHaveBeenCalledWith('op-车被', { status: 'inactive' }))

    // ③ 这一屏**没有任何**写请求带 `scope` 键（退场的是**用户动作**，不是请求契约）
    expect(mockUpdateOperation.mock.calls.length).toBeGreaterThan(0)
    for (const call of mockUpdateOperation.mock.calls) {
      expect(Object.keys(call[1] as object)).not.toContain('scope')
    }
  })

  it('#4961-① 主表行尾的「必完」标记与列头里的「必完」一起退场（完工口径改为「全部工序实例全绿」）', async () => {
    await renderOperations()

    // 夹具里 `精裁` 必完（改前 ⇒ `matrix-must-finish-精裁` 那枚琥珀色标记在场）
    expect(document.body.querySelector('[data-testid^="matrix-must-finish-"]')).toBeNull()
    expect(screen.getByTestId('matrix-meta-精裁')).not.toHaveTextContent('必完')
    // 列头 = `分组 · 单位 · 操作`（改前是 `分组 · 单位 · 必完 · 操作`）
    expect(screen.getByTestId('operation-workshop-table')).not.toHaveTextContent('必完')
    // 移除的是「必完」，**不是**行尾元数据本身（`分组 · 单位` 逐字仍在）
    expect(screen.getByTestId('matrix-meta-精裁')).toHaveTextContent('裁剪')
    expect(screen.getByTestId('matrix-meta-精裁')).toHaveTextContent('套')
  })

  it('#4961-② 抽屉里的「必完」勾选框退场（不是禁用、不是隐藏）', async () => {
    await openManage('车被')

    // 改前这里是 `<input type="checkbox" data-testid="variant-must-finish-op-车被" checked>`
    expect(document.body.querySelector('[data-testid^="variant-must-finish-"]')).toBeNull()
    expect(screen.getByTestId('operations-manage-drawer')).not.toHaveTextContent('必完')
  })

  it('#4961-③ 主线 chip 上的「必完」标记退场', async () => {
    await renderOnRoutes()
    await waitFor(() => expect(screen.getByTestId('routing-step-11-1')).toBeInTheDocument())

    // 改前：`精裁` 矩阵行必完 ⇒ chip 1 带 `routing-step-must-finish-11-1`；`外帘装袋` ⇒ chip 3
    expect(document.body.querySelector('[data-testid^="routing-step-must-finish-"]')).toBeNull()
    expect(screen.getByTestId('routing-step-11-1')).not.toHaveTextContent('必完')
    expect(screen.getByTestId('routing-step-11-3')).not.toHaveTextContent('必完')
  })

  it('#4961-④ 「一道必完工序都没有」预检黄条（`routing-precheck-*`）整体退场', async () => {
    // 两道都能在工序库里查到、且都**不是**必完 ⇒ 改前 `lacksMustFinish` 成立、黄条就在这里
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

    expect(screen.queryByTestId('routing-precheck-11')).toBeNull()
    // 删的是「必完」这**一条**预检，不是整个预检面：主线编辑器照旧可用
    expect(screen.getByTestId('routing-add-select-11')).toBeInTheDocument()
    expect(screen.getByTestId('routing-save-11')).toBeEnabled()
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

    // 信息不丢：逻辑工序名 + **一个单价**照旧渲染（issue #4886：一道工序一行一个价）
    expect(screen.getByTestId('matrix-row-精裁')).toHaveTextContent('精裁')
    expect(screen.getByTestId('operation-price-精裁')).toHaveTextContent('¥8.50')
    expect(screen.getByTestId('operation-price-车被')).toHaveTextContent('¥0.00')
  })

  it('⑰-④ 两态可区分：`¥0.00` 是真价（≠「未定价」）、`未定价`；第三态「不做」已随 #4951 退场（反向护栏）', async () => {
  mockGetOperationPositions.setDefault([
  { id: 'p1', operation: '车被', position: '通用', unit_price: 0, ...NO_VARIANT },
  { id: 'p2', operation: '韩褶', position: '通用', unit_price: null, ...NO_VARIANT },
  ])
  await renderOperations()

  // ① 真 0 元 = **有价**（必须显示成金额，不得与「未定价」混同）
  const zero = screen.getByTestId('operation-price-车被')
  expect(zero).toHaveAttribute('data-state', 'priced')
  expect(zero).toHaveTextContent('¥0.00')
  expect(zero).not.toHaveTextContent('未定价')

  // ② 未定价：`unit_price=null` ⇒ 显示「未定价」，且文本里**不含 ¥ 符号**
  const unpriced = screen.getByTestId('operation-price-韩褶')
  expect(unpriced).toHaveAttribute('data-state', 'unpriced')
  expect(unpriced).toHaveTextContent('未定价')
  expect(unpriced).not.toHaveTextContent('¥')

  // ③ 🔴 反向护栏（2026-09-21 改判，配套 #4937 / #4951 去部位化彻底版）：存活价目行的
  //    `applicable` **恒 `TRUE`** 且该字段已退场 ⇒ `na`（「不做」）永不可达。判据从
  //    「三态可区分」收敛为「**恰两态** + 『不做』不得出现在任何单价格里」—— 判据面缩小
  //    （旧第三态失去对象）、**不放宽**（`未定价 ≠ ¥0.00` 与「真 0 元照显示」两条一字未动）。
  // ⚠️ 排除容器 `operation-price-matrix`（它没有 `data-state`）：只遍历**单价格**节点
    for (const el of screen.getAllByTestId(/^operation-price-(?!matrix$)[^-]+$/)) {
    expect(['priced', 'unpriced']).toContain(el.getAttribute('data-state'))
    expect(el).not.toHaveTextContent('不做')
  }
  expect(screen.queryByTestId('operation-price-三边')).toBeNull()

  // 待办计数只数「未定价」（真 0 元不算；「不做」已不成态）
  expect(screen.getByTestId('matrix-unpriced-count')).toHaveTextContent('1')
  })

  it('⑰-⑤ 格内改价：body **只带** `{unit_price}`；清空 ⇒ `null`（改回未定价，≠ 0 元）', async () => {
    await renderOperations()

    await userEvent.click(screen.getByTestId('operation-price-edit-精裁'))
    const input = screen.getByTestId('operation-price-input-精裁')
    await userEvent.clear(input)
    await userEvent.type(input, '6.5')
    await userEvent.click(screen.getByTestId('operation-price-save-精裁'))

    await waitFor(() =>
      expect(mockUpdateOperationPosition).toHaveBeenCalledWith('pos-精裁-布帘', { unit_price: 6.5 }),
    )
    expect(Object.keys(mockUpdateOperationPosition.mock.calls[0][1] as object)).toEqual(['unit_price'])

    // 清空 = 改回**未定价**（发 `null`；注入：把空串当 0 发 ⇒ 红）
    mockUpdateOperationPosition.mockClear()
    await userEvent.click(screen.getByTestId('operation-price-edit-三边'))
    await userEvent.clear(screen.getByTestId('operation-price-input-三边'))
    await userEvent.click(screen.getByTestId('operation-price-save-三边'))
    await waitFor(() =>
      expect(mockUpdateOperationPosition).toHaveBeenCalledWith('pos-三边-布帘', { unit_price: null }),
    )
  })


  /**
   * issue #4665 ③：主表格格子里的做/不做**不许只靠 hover/`title` 才知道它是什么**
   * （改前是一个光秃秃的 `⇄`）⇒ 控件必须有**可见文字**，且三态语义不变。
   */

  it('⑰-⑦ 格内改价本地预检：负数 / 三位小数 ⇒ **不发请求**，就地给理由', async () => {
    await renderOperations()

    await userEvent.click(screen.getByTestId('operation-price-edit-精裁'))
    const input = screen.getByTestId('operation-price-input-精裁')
    await userEvent.clear(input)
    await userEvent.type(input, '5.555')
    await userEvent.click(screen.getByTestId('operation-price-save-精裁'))

    expect(mockUpdateOperationPosition).not.toHaveBeenCalled()
    expect(screen.getByTestId('operation-price-reasons-精裁')).toHaveTextContent('最多两位小数')
  })

  it('⑰-⑧ 格内改价被后端拒：理由**逐条**就地展示，且不静默收摊（仍在编辑态）', async () => {
    mockUpdateOperationPosition
      .mockReset()
      .mockRejectedValueOnce(guardError(['该部位已停用，不能改价', '请先处理引用它的主线']))
    await renderOperations()

    await userEvent.click(screen.getByTestId('operation-price-edit-精裁'))
    const input = screen.getByTestId('operation-price-input-精裁')
    await userEvent.clear(input)
    await userEvent.type(input, '6.5')
    await userEvent.click(screen.getByTestId('operation-price-save-精裁'))

    const reasons = await screen.findByTestId('operation-price-reasons-精裁')
    expect(reasons).toHaveTextContent('该部位已停用，不能改价')
    expect(reasons).toHaveTextContent('请先处理引用它的主线')
    expect(screen.getByTestId('operation-price-input-精裁')).toBeInTheDocument()
  })

  it('⑰-⑨ 搜索框过滤这一张表（行级过滤；不是两张表各滤一遍）', async () => {
    await renderOperations()
    await userEvent.type(screen.getByTestId('operations-search'), '精裁')
    await waitFor(() => expect(screen.queryByTestId('matrix-row-三边')).toBeNull())
    expect(screen.getByTestId('matrix-row-精裁')).toBeInTheDocument()
  })

  it('⑰-⑩ 「管理▸」抽屉：条目带 分组 · 单位；「作用域 / 必完」已整体退场（issue #4960 / #4961）', async () => {
    // issue #4947：抽屉层写面按**逻辑名**寻址（真形态）⇒ 用真形态夹具驱动
    mockGetOperationsCatalog.mockReset().mockResolvedValue(ok(LOGICAL_CATALOG))
    await openManage('车被')
    const row = screen.getByTestId('variant-row-op-车被')
    // issue #4622 / #4886：条目主标识 = **逻辑工序名**（不是变体名，也不再是部位）
    expect(row).toHaveTextContent('车被')
    expect(row).not.toHaveTextContent('车被-布')
    expect(row).toHaveTextContent('后道')
    expect(row).toHaveTextContent('件')

    // 两个配置项**都不在**（移除类判据 ⇒ 断言「不存在」，控件级红证见 #4960-① / #4961-②）
    expect(document.body.querySelector('[data-testid^="variant-scope-"]')).toBeNull()
    expect(document.body.querySelector('[data-testid^="variant-must-finish-"]')).toBeNull()
    expect(row).not.toHaveTextContent('每套窗只做一次')
    expect(row).not.toHaveTextContent('必完')

    // 停用走既有写面（`PUT /operations/{id}` 的 `status`）—— issue #4947：入口已**统一到抽屉 footer**
    // （逐行那一对与 footer 重复 ⇒ 去重退场；判据见 #4947-①）
    await userEvent.click(screen.getByTestId('operations-manage-disable'))
    await waitFor(() => expect(mockUpdateOperation).toHaveBeenCalledWith('op-车被', { status: 'inactive' }))
  })



  it('㉖-④ 能力不减（反向护栏）：改分组 / 单位 / 停用 / 删除 **四项逐条仍可用**（作用域 / 必完已退场）', async () => {
    // issue #4947：停用/删除的入口统一到 footer ⇒ 用**真形态**夹具（footer 按逻辑名寻址）
    mockGetOperationsCatalog.mockReset().mockResolvedValue(ok(LOGICAL_CATALOG))
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

    // ③ 停用 / ④ 删除：入口已**统一到抽屉 footer**（issue #4947：逐行那一对与 footer 逐字重复 ⇒ 退场）
    await userEvent.click(screen.getByTestId('operations-manage-disable'))
    await waitFor(() => expect(mockUpdateOperation).toHaveBeenCalledWith(id, { status: 'inactive' }))

    // ④ 删除：二次确认后才发 `DELETE /operations/{id}`（逐条护栏理由的就地展示见 ⑰-⑬）
    await userEvent.click(screen.getByTestId('operations-manage-delete'))
    expect(mockDeleteOperation).not.toHaveBeenCalled()
    await userEvent.click(await screen.findByTestId('operations-manage-delete-confirm'))
    // ⚠️ 本行还有「做」的价目行 ⇒ 走 #4692 的 detach 那条路（与后端护栏③同一把尺）
    await waitFor(() =>
      expect(mockDeleteOperation).toHaveBeenCalledWith(id, { detachPositions: true }),
    )
  })

  it('㉖-⑤ 抽屉标题/说明改成商家语言：以**逻辑工序名**为主标识，不出现「变体 / 工人扫码时看到的工序」', async () => {
    await openManage('三边')

    // 标题 = 商家语言（含这道工序的名字，但不说「变体」）
    expect(screen.getByRole('dialog', { name: '「三边」的设置' })).toBeInTheDocument()

    const drawer = screen.getByTestId('operations-manage-drawer')
    expect(drawer).not.toHaveTextContent('变体')
    expect(drawer).not.toHaveTextContent('工人扫码')
    expect(drawer.textContent ?? '').not.toContain('布三边')

    // ⚠️ issue #4961：原「#4610 的必完解释保留」已**反向** —— 配置项退场，解释句一并退场
    expect(drawer).not.toHaveTextContent('必完')
  })

  it('⑰-⑫ 抽屉：该逻辑工序查不到任何设置（6 键全 null 且库里查不到）⇒ 可读提示 + 删除出路，不空白、不发明数据', async () => {
    await openManage('韩褶')
    expect(screen.queryByTestId(/^variant-row-/)).toBeNull()
    const empty = screen.getByTestId('operations-manage-empty')
    // issue #4674 B：空态不再是一句死路文案 —— 说清**为什么**空 + 给**两个可点动作**
    expect(empty).toHaveTextContent('都没有关联到它')
    expect(empty).not.toHaveTextContent('请核对各部位的适用性配置')
    // issue #4886：「接入部位…」已随部位退场 ⇒ **不得**再摆这条死路按钮，删除入口才是出路
    expect(screen.queryByTestId('operations-manage-attach')).toBeNull()
    expect(screen.getByTestId('operations-manage-delete-empty')).toBeInTheDocument()
    // issue #4622：提示也用商家语言（不得再写「变体 / 工人端」这类内部术语）
    expect(empty).not.toHaveTextContent('变体')
    expect(empty).not.toHaveTextContent('工人端')
  })

  // ══════════════ ㉙ 抽屉死路：矩阵格关联不上时也必须有「停用 / 删除」入口（issue #4674） ══════════════
  // 用户实测（截图 + 原话）：「这条测试数据已经没有办法删除了，无删除入口」——
  // 抽屉「『测试22』在各部位的设置」只有一句死路文案 + 一个「关闭」，而主表格里那一行**还在**。
  // 病根三条：① 停用/删除**挂在「各部位的设置」行内** ⇒ `manageVariants` 为空就没有入口；
  // ② 表格按**逻辑名**成行、抽屉按 `variant_operation_id` 找格（**两把尺**）；
  // ③ 空态文案「请核对各部位的适用性配置」是**死路指引**（页面上没有地方可核对）。

  it('㉙-① 抽屉层「停用 / 删除」**不依赖**矩阵格：格关联不上时照样有入口（**红证**：改前只有「关闭」）', async () => {
    mockGetOperationsCatalog.mockReset().mockResolvedValue(ok(CATALOG_WITH_TEST22))
    mockGetOperationPositions.setDefault(POSITIONS_WITH_TEST22)
    await openManage('测试22')

    // 抽屉层入口**与矩阵格无关** —— 库里那一行在，入口就在
    expect(screen.getByTestId('operations-manage-disable')).toBeInTheDocument()
    expect(screen.getByTestId('operations-manage-delete')).toBeInTheDocument()
    // 「关闭」仍在，但不再是**唯一**（改前 footer 里只有它 —— 正是用户截图的形态）
    expect(screen.getByTestId('operations-manage-close')).toBeInTheDocument()
    // 该格是按**逻辑名**回退认出来的 ⇒ 提示在（不静默）
    expect(screen.getByTestId('operations-manage-unlinked-hint')).toBeInTheDocument()
  })

  it('㉙-② 空态给可点动作（删除这道工序）且说清**为什么空**（**红证**：改前只有死路文案）', async () => {
    // 空态的**真形态**（用户截图那一屏）= 表格里**有**这一行、抽屉里**一行设置都没有**。
    // 复现路径 = 抽屉开着时读面变空（`load()` 后这一行的格没了）—— 这正是「行在 · 抽屉空」。
    mockGetOperationsCatalog.mockReset().mockResolvedValue(ok(CATALOG_WITH_TEST22))
    mockGetOperationPositions
      .setDefault(POSITIONS) // 之后：这一行的格没了 ⇒ 抽屉空
      .setDefaultOnce(POSITIONS_WITH_TEST22) // 首次：这一行有格 ⇒ 抽屉能开
    await openManage('测试22')
    // 抽屉层的「停用」走既有写面 + `load()` ⇒ 用它把读面刷成「这一行的格没了」
    await userEvent.click(screen.getByTestId('operations-manage-disable'))
    await waitFor(() => expect(mockGetOperationPositions).toHaveBeenCalledTimes(2))

    const empty = await screen.findByTestId('operations-manage-empty')
    // 说清**为什么**空（不再是「请核对各部位的适用性配置」这种死路指引）
    expect(empty).toHaveTextContent('测试22')
    expect(empty).toHaveTextContent('工序库')
    expect(empty).toHaveTextContent('还没有任何价目行')
    expect(empty).not.toHaveTextContent('请核对适用性配置')
    // 出路 = 删除这道工序（**可点** —— 库里那一行在，就有事可做）
    expect(screen.getByTestId('operations-manage-delete-empty')).not.toBeDisabled()
    // issue #4886：「接入部位…」已随部位退场 ⇒ 不得再摆这条死路按钮
    expect(screen.queryByTestId('operations-manage-attach')).toBeNull()
    // 抽屉层「停用 / 删除」在空态下**也**在（不依赖有没有行）
    expect(screen.getByTestId('operations-manage-disable')).toBeInTheDocument()
    expect(screen.getByTestId('operations-manage-delete')).toBeInTheDocument()


  })

  it('㉙-③ 删除**成功**：按名字命中的格仍在「做」⇒ 走 detach-and-delete（**能过护栏③**那条路；#4692 改判）', async () => {
    mockGetOperationsCatalog.mockReset().mockResolvedValue(ok(CATALOG_WITH_TEST22))
    mockGetOperationPositions.setDefault(POSITIONS_WITH_TEST22)
    await openManage('测试22')

    await userEvent.click(screen.getByTestId('operations-manage-delete'))
    // 二次确认：弹框先出现、**未**发请求
    expect(await screen.findByTestId('operations-manage-delete-modal')).toBeInTheDocument()
    expect(mockDeleteOperation).not.toHaveBeenCalled()
    await userEvent.click(screen.getByTestId('operations-manage-delete-confirm'))

    // ⚠️ **#4692 改判**：本夹具的格 `variant_operation_id = null`（读面查不到变体）却**按名字**
    // 命中 `测试22` 这一行且 `applicable=true` ⇒ 后端护栏③（按名字）**会拦普通删除**。
    // 故本入口必须走 `detachPositions: true`（#4671 的 `…/detach-and-delete`，后端同一事务）。
    // （改前这里断言的是**不带参数**的普通删除 —— 那条断言**编码了 bug**，是用户第 3 次「仍然不能删除」的成因；
    //   它**不是**被放宽，而是被**改成对的那条路** + 新增 ㉚-A 的「护栏③等价打桩」红证。）
    await waitFor(() =>
      expect(mockDeleteOperation).toHaveBeenCalledWith('op-test22', { detachPositions: true }),
    )
    // 刷新（不静默）
    await waitFor(() => expect(mockGetOperationPositions).toHaveBeenCalledTimes(2))
  })

  it('㉙-④ 反向护栏**不放宽**：仍挂在主线/规则 ⇒ 删除被拦，理由**逐条**就地展示', async () => {
    mockGetOperationsCatalog.mockReset().mockResolvedValue(ok(CATALOG_WITH_TEST22))
    mockGetOperationPositions.setDefault(POSITIONS_WITH_TEST22)
    mockDeleteOperation
      .mockReset()
      .mockRejectedValueOnce(
        guardError([
          '被活跃路线「窗帘工序路线（默认）」引用，请先改主线',
          '被活跃规则「工艺 韩褶」引用，请先删改那条规则',
        ]),
      )
    await openManage('测试22')

    await userEvent.click(screen.getByTestId('operations-manage-delete'))
    await userEvent.click(await screen.findByTestId('operations-manage-delete-confirm'))

    const reasons = await screen.findByTestId('operations-manage-delete-reasons')
    expect(reasons).toHaveTextContent('请先改主线')
    expect(reasons).toHaveTextContent('请先删改那条规则')
    // 被拦 ⇒ 弹框**不收摊**（理由要看得见）
    expect(screen.getByTestId('operations-manage-delete-modal')).toBeInTheDocument()
    // 且**没有**任何「摘格」发生（前端不自己去动矩阵 —— 一格都没写）
    expect(mockUpdateOperationPosition).not.toHaveBeenCalled()
  })

  it('㉙-⑤ 口径对齐：`variant_operation_id` 关联不上 ⇒ 抽屉**显式提示**「未关联到本工序」（**红证**：改前静默空）', async () => {
    mockGetOperationsCatalog.mockReset().mockResolvedValue(ok(CATALOG_WITH_TEST22))
    mockGetOperationPositions.setDefault(POSITIONS_TEST22_MISLINKED)
    await openManage('测试22')

    // 提示在（改前**静默空** —— 那几格在抽屉里根本不出现）
    const hint = screen.getByTestId('operations-manage-unlinked-hint')
    expect(hint).toHaveTextContent('没有关联到它')
    expect(hint).toHaveTextContent('1')
    // 行自带 `variant_operation_id` 且指向**别的**工序 ⇒ 只如实报出、**不给写面**
    // （对它 PUT/DELETE 就是改另一道工序 —— 那正是「两把尺不一致」要暴露的东西）
    // ⚠️ issue #4886：条目主标识 = **逻辑工序名**（抽屉当前那道），不再是部位集合
    expect(screen.getByTestId('variant-row-op-别的工序')).toHaveTextContent('测试22')
    expect(screen.getByTestId('variant-foreign-op-别的工序')).toBeInTheDocument()
    // issue #4947：逐行那一对「停用 / 删除」**整对退场** ⇒ 任何一行都不会再有它；
    // 判据换成「这条 foreign 行**一个写面都没有**」（去重不得顺手把 foreign 的护栏也删掉）
    expect(screen.queryByTestId('variant-delete-op-别的工序')).toBeNull()
    expect(screen.queryByTestId('variant-disable-op-别的工序')).toBeNull()
    expect(screen.queryByTestId('variant-meta-edit-op-别的工序')).toBeNull()
  })

  it('㉙-⑥ 抽屉层「停用」走既有 `PUT /operations/{id}` 的 `status`（与逐行停用同一写面）', async () => {
    mockGetOperationsCatalog.mockReset().mockResolvedValue(ok(CATALOG_WITH_TEST22))
    mockGetOperationPositions.setDefault(POSITIONS_WITH_TEST22)
    await openManage('测试22')

    await userEvent.click(screen.getByTestId('operations-manage-disable'))
    await waitFor(() => expect(mockUpdateOperation).toHaveBeenCalledWith('op-test22', { status: 'inactive' }))
  })

  it('㉙-⑦ 抽屉层写面被拒：理由**逐条**就地展示（不吞成一句「操作失败」）', async () => {
    mockGetOperationsCatalog.mockReset().mockResolvedValue(ok(CATALOG_WITH_TEST22))
    mockGetOperationPositions.setDefault(POSITIONS_WITH_TEST22)
    mockUpdateOperation
      .mockReset()
      .mockRejectedValueOnce(guardError(['被活跃路线「窗帘工序路线（默认）」引用，不能停用']))
    await openManage('测试22')

    await userEvent.click(screen.getByTestId('operations-manage-disable'))
    const reasons = await screen.findByTestId('operations-manage-op-reasons')
    expect(reasons).toHaveTextContent('不能停用')
  })

  it('#4947-① 抽屉层「停用 / 删除」**只剩 footer 那一对**：逐行那一对已按 #4947 去重退场（重复入口不许回来）', async () => {
    mockGetOperationsCatalog.mockReset().mockResolvedValue(ok(LOGICAL_CATALOG))
    await openManage('精裁')

    // 抽屉层入口**仍在**（能力不减：入口只是从「行内」统一到 footer）
    expect(screen.getByTestId('operations-manage-disable')).toBeInTheDocument()
    expect(screen.getByTestId('operations-manage-delete')).toBeInTheDocument()
    // 行还在（去重不得把正文那一行一起删掉）
    expect(screen.getByTestId('variant-row-op-精裁-布')).toBeInTheDocument()
    // 🔴 逐行那一对**已退场**（与 footer 逐字重复：同一屏两个「删除」正是用户报的形态）
    expect(screen.queryByTestId('variant-disable-op-精裁-布')).toBeNull()
    expect(screen.queryByTestId('variant-delete-op-精裁-布')).toBeNull()
    // 信息**不许丢**：那句提示搬到了 footer 的「删除」旁边
    expect(screen.getByTestId('operations-manage-delete').parentElement).toHaveTextContent(
      '删除后历史报工不受影响',
    )
    // 有关联 ⇒ **不**提示「未关联」（不得无差别刷提示）
    expect(screen.queryByTestId('operations-manage-unlinked-hint')).toBeNull()
  })

  it('#4947-② footer 的「停用 / 删除」作用于**抽屉当前展示的那一行**：读面指 `op-b` ⇒ 动的就是 `op-b`（不是按逻辑名取的首行 `op-a`）', async () => {
    mockGetOperationsCatalog.mockReset().mockResolvedValue(ok(LOGICAL_CATALOG))
    mockGetOperationPositions.setDefault(POSITIONS_READFACE_OP_B)

    // 前提自证（不是空跑）：同名两行里**首行**是 `op-a`（按名字取的那把尺），而**读面**指到的是 `op-b`
    const rows = LOGICAL_CATALOG.groups
      .flatMap((g) => g.operations)
      .filter((o) => o.name === '三边')
    expect(rows.map((o) => o.id)).toEqual(['op-a', 'op-b'])
    expect(rows[0].library_name).toBe('布三边')
    expect(POSITIONS_READFACE_OP_B[0].variant_operation_id).toBe('op-b')

    await openManage('三边')
    // 抽屉展示的正是读面指到的那一行
    expect(screen.getByTestId('variant-row-op-b')).toBeInTheDocument()

    await userEvent.click(screen.getByTestId('operations-manage-disable'))
    await waitFor(() => expect(mockUpdateOperation).toHaveBeenCalledWith('op-b', { status: 'inactive' }))
    // 反向：**不得**动按逻辑名取的首行（改前那条「两把尺」：footer 说 A、读面指 B）
    expect(mockUpdateOperation).not.toHaveBeenCalledWith('op-a', expect.anything())

    // 删除也按**读面那一行**寻址（弹框与请求落在同一行上）
    await userEvent.click(screen.getByTestId('operations-manage-delete'))
    expect(await screen.findByTestId('operations-manage-delete-modal')).toHaveAttribute(
      'data-operation',
      '三边',
    )
    await userEvent.click(screen.getByTestId('operations-manage-delete-confirm'))
    await waitFor(() =>
      expect(mockDeleteOperation).toHaveBeenCalledWith('op-b', { detachPositions: true }),
    )
    expect(mockDeleteOperation).not.toHaveBeenCalledWith('op-a', expect.anything())
  })

  it('#4947-③ 逐行写面（分组 / 单位）被拒 ⇒ 理由**逐条**在抽屉里上屏（`variant-reasons`），且**不是** footer 那条 `operations-manage-op-reasons`', async () => {
    mockGetOperationsCatalog.mockReset().mockResolvedValue(ok(LOGICAL_CATALOG))
    mockUpdateOperation
      .mockReset()
      .mockRejectedValueOnce(guardError(['分组名称最长 8 个字', '单位必须是 米/套/件/个/折 之一']))
    await openManage('精裁')

    await userEvent.click(screen.getByTestId('variant-meta-edit-op-精裁-布'))
    const groupInput = screen.getByTestId('variant-group-input-op-精裁-布')
    await userEvent.clear(groupInput)
    await userEvent.type(groupInput, '后道后道后道')
    await userEvent.click(screen.getByTestId('variant-meta-save-op-精裁-布'))

    // 写面失败**不得静默**（红证：改前逐行那一套弹框退场后，这份状态**没有渲染点**）
    const reasons = await screen.findByTestId('variant-reasons')
    expect(reasons).toHaveTextContent('分组名称最长 8 个字')
    expect(reasons).toHaveTextContent('单位必须是')
    // 两处触发源**不同**（逐行写面 vs footer 的停用/删除）⇒ 不得合成同一条理由条（错位会让商家误判是谁失败）
    expect(screen.queryByTestId('operations-manage-op-reasons')).toBeNull()
  })

  // ══════════ ㉚ 删除死路（**第 3 次**）：前后端判据必须**同一把尺（按名字）**（issue #4692） ══════════
  // 用户实测（2026-09-20，逐字）：「**仍然不能删除**」（#4674 已部署后的新抽屉）。
  // 病根 = **两把尺**：
  //   前端按格的 `variant_operation_id` 判「有没有格关联到它」（那 2 个格的关联键是 null ⇒ 判「没有」
  //   ⇒ 选**普通删除**）；后端护栏③（`ProductionOperationCommandService.matchingCells` + `variantNameOf`）
  //   按**名字**判（那 2 个格 `logical_name = 测试22` ⇒ 命中 + `applicable=true` ⇒ **422 拦下**）
  //   ⇒ 前端说能删、后端拒绝 ⇒ 点「删除」/「删除这道工序」**必然失败**。
  // 修法（治本）：**删除路径的选择不再看 `variant_operation_id`** —— 判据与护栏③同一把尺
  // （`opDeleteBlockerCells` = 本行仍是「做」的格）：有 ⇒ detach-and-delete（**能过**护栏③那条路），
  // 没有 ⇒ 才用普通软删。`variant_operation_id` 只留作**展示**（「这些格未关联到本工序」）。

  it('#4692-A 用户那个形态（格**按名字**命中、`variant_operation_id` 为 null）⇒ 走 `detachPositions: true` 且**真删掉**（**红证**：改前普通删除 ⇒ 护栏③ 422）', async () => {
    mockGetOperationsCatalog.mockReset().mockResolvedValue(ok(CATALOG_WITH_TEST22))
    mockGetOperationPositions.setDefault(POSITIONS_WITH_TEST22)
    // 后端那把尺（按名字）：普通删除 422、detach 能过
    beGuardByName()
    await openManage('测试22')

    await userEvent.click(screen.getByTestId('operations-manage-delete'))
    const modal = await screen.findByTestId('operations-manage-delete-modal')
    // 弹框**说清将发生什么**（设为不做 + 历史报工不受影响）—— 不再写「后端会拦下…」（那是走错路径的文案）
    expect(modal).toHaveTextContent('设为不做')
    expect(modal).toHaveTextContent('历史报工不受影响')
    expect(modal).not.toHaveTextContent('后端会拦下')

    await userEvent.click(screen.getByTestId('operations-manage-delete-confirm'))
    // ① 走的是**能过护栏③**的那条路（断言请求参数）
    await waitFor(() =>
      expect(mockDeleteOperation).toHaveBeenCalledWith('op-test22', { detachPositions: true }),
    )
    // ② 工序**真被删**（弹框收摊 + 刷新）—— 不是「提示成功但还在」
    await waitFor(() => expect(screen.queryByTestId('operations-manage-delete-modal')).toBeNull())
    await waitFor(() => expect(mockGetOperationPositions).toHaveBeenCalledTimes(2))
    // ③ **一次事务**：前端**不**自己逐个 PUT 矩阵格（那是两步、会留下「第一步成功第二步失败」的中间态）
    expect(mockUpdateOperationPosition).not.toHaveBeenCalled()
  })

  it('#4692-B 两把尺一致：**前端不再按 `variant_operation_id` 选删除路径**（注入「FE 按 id 判、BE 按名判」⇒ 必红）', async () => {
    mockGetOperationsCatalog.mockReset().mockResolvedValue(ok(CATALOG_WITH_TEST22))
    mockGetOperationPositions.setDefault(POSITIONS_WITH_TEST22)
    // 前提自证（不是空跑）：这一格的关联键确实是 null（id 那把尺判「没有格」），而行键（名字）是 `测试22`
    const cell = POSITIONS_WITH_TEST22.find((c) => c.operation === '测试22')!
    expect(cell.variant_operation_id).toBeNull()
    // ⚠️ issue #4937/#4951：原来这里还断言 `cell.applicable === true` —— `applicable` 已退场
    // （读面恒 true、写面收到即 422、类型里已无该字段）⇒ 该断言**失去对象**，删除（不是放宽：
    // 它守的「这一行是『做』的」在新形态下由「行存在」本身表达）。
    // 后端那把尺（按名字）：普通删除 422
    beGuardByName()
    await openManage('测试22')

    await userEvent.click(screen.getByTestId('operations-manage-delete'))
    await userEvent.click(await screen.findByTestId('operations-manage-delete-confirm'))
    await waitFor(() => expect(mockDeleteOperation).toHaveBeenCalled())

    // **判据 = 后端那把（按名字）**：发出去的**每一次**删除都只能是 detach 那条路
    // （前端若仍按 id 尺判「没有格」⇒ 普通删除 ⇒ 上面那个打桩 422 ⇒ 本断言必红）
    for (const call of mockDeleteOperation.mock.calls) {
      expect(call[1]).toEqual({ detachPositions: true })
    }
  })

  it('#4692-C 正文「删除这道工序」入口也走通：**没有任何按名字命中的格** ⇒ 才用普通软删（spec A 第 2 款）', async () => {
    mockGetOperationsCatalog.mockReset().mockResolvedValue(ok(CATALOG_WITH_TEST22))
    mockGetOperationPositions
      .setDefault(POSITIONS) // 之后：这一行的格没了 ⇒ 抽屉空
      .setDefaultOnce(POSITIONS_WITH_TEST22) // 首次：这一行有格 ⇒ 抽屉能开（正文入口出现）
    await openManage('测试22')
    // 用抽屉层「停用」把读面刷成「这一行的格没了」（与 ㉙-② 同一手法）
    await userEvent.click(screen.getByTestId('operations-manage-disable'))
    await waitFor(() => expect(mockGetOperationPositions).toHaveBeenCalledTimes(2))

    await screen.findByTestId('operations-manage-empty')
    const entry = screen.getByTestId('operations-manage-delete-empty')
    expect(entry).not.toBeDisabled()
    await userEvent.click(entry)
    expect(await screen.findByTestId('operations-manage-delete-modal')).toBeInTheDocument()
    // 一格都没有 ⇒ **不**走 detach（护栏③天然满足）；这正是 spec A 的第 2 款
    expect(screen.getByTestId('operations-manage-delete-nocells')).toBeInTheDocument()
    await userEvent.click(screen.getByTestId('operations-manage-delete-confirm'))
    await waitFor(() => expect(mockDeleteOperation).toHaveBeenCalledWith('op-test22'))
    await waitFor(() => expect(mockGetOperationPositions).toHaveBeenCalledTimes(3))
  })

  it('#4692-E 护栏**不放宽**：仍挂在主线/规则 ⇒ 新路径（detach）**照样被拦**，理由逐条就地展示、矩阵一格不动', async () => {
    mockGetOperationsCatalog.mockReset().mockResolvedValue(ok(CATALOG_WITH_TEST22))
    mockGetOperationPositions.setDefault(POSITIONS_WITH_TEST22)
    mockDeleteOperation
      .mockReset()
      .mockRejectedValueOnce(
        guardError([
          '工序「测试22」还在活跃路线「窗帘工序路线（默认）」的主线里 —— 先改主线（把它从该路线去掉），再删它',
          '工序「测试22」被活跃规则「工艺 韩褶 → 测试22」引用（目标工序或锚点）—— 先删或改那条规则，再删它',
        ]),
      )
    await openManage('测试22')

    await userEvent.click(screen.getByTestId('operations-manage-delete'))
    await userEvent.click(await screen.findByTestId('operations-manage-delete-confirm'))

    // 走的仍是 detach 那条路（路径判据变了），但**护栏①/②一字未放宽** ⇒ 一样 422
    await waitFor(() =>
      expect(mockDeleteOperation).toHaveBeenCalledWith('op-test22', { detachPositions: true }),
    )
    const reasons = await screen.findByTestId('operations-manage-delete-reasons')
    expect(reasons).toHaveTextContent('先改主线')
    expect(reasons).toHaveTextContent('先删或改那条规则')
    // 被拦 ⇒ 弹框**不收摊**（理由要看得见），且**没有**任何「摘格」发生（前端不自己去动矩阵）
    expect(screen.getByTestId('operations-manage-delete-modal')).toBeInTheDocument()
    expect(mockUpdateOperationPosition).not.toHaveBeenCalled()
  })

  it('⑰-⑬ 删除工序：**二次确认**后才发 `DELETE /operations/{id}`；护栏理由逐条就地展示（入口 = 抽屉 footer，#4947）', async () => {
    mockGetOperationsCatalog.mockReset().mockResolvedValue(ok(LOGICAL_CATALOG))
    mockDeleteOperation
      .mockReset()
      .mockRejectedValueOnce(guardError(['被活跃路线「窗帘工序路线（默认）」引用，请先改主线', '该部位仍是「做」，请先设为不做']))
    await openManage('精裁')

    await userEvent.click(screen.getByTestId('operations-manage-delete'))
    // 二次确认：弹框先出现，**未**发请求
    expect(mockDeleteOperation).not.toHaveBeenCalled()
    await userEvent.click(await screen.findByTestId('operations-manage-delete-confirm'))

    // 本行还有「做」的价目行 ⇒ 走 #4692 的 detach 那条路（能过护栏③）
    await waitFor(() =>
      expect(mockDeleteOperation).toHaveBeenCalledWith('op-精裁-布', { detachPositions: true }),
    )
    const reasons = await screen.findByTestId('operations-manage-delete-reasons')
    expect(reasons).toHaveTextContent('请先改主线')
    expect(reasons).toHaveTextContent('请先设为不做')
  })

  it('⑰-⑮ 删除工序：确认框可取消 —— 取消后不发 DELETE', async () => {
    mockGetOperationsCatalog.mockReset().mockResolvedValue(ok(LOGICAL_CATALOG))
    await openManage('精裁')
    await userEvent.click(screen.getByTestId('operations-manage-delete'))
    await userEvent.click(await screen.findByTestId('operations-manage-delete-cancel'))

    expect(mockDeleteOperation).not.toHaveBeenCalled()
    await waitFor(() => expect(screen.queryByTestId('operations-manage-delete-modal')).toBeNull())
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

  // ══════════════════ ⑱′ 「什么时候」第 4 维 = **部位**（issue #4962 加回）══════════════════
  //
  // 用户裁定（2026-09-21）：「如果有一些工序只能布帘有或者纱帘有，可以在适用条件上设置」⇒
  // `production_route_rules.position`（部位限定；`NULL` = 不限部位）**加回**：
  //   · 写面新增第 4 档 `trigger_kind='position'`（`trigger_value` = 部位名），并把值镜像进 `position` 列；
  //   · 取值域 = `GET /route-rule-options` 新增的 `positions` 键（**部位闭词表**，前端不硬编码）；
  //   · 读面「人话」渲染成 `部位 = 布帘 时插入（在「三边」之后）`。
  // 历史沿革：#4937 曾让规则级部位退场（该键恒 `NULL`、前端不得据它渲染），#4962 加回。

  it('⑱′-① 「部位」档：取值**逐字来自** `route-rule-options.positions`（含第 4 个 `布料`）⇒ 提交 body 带 `position`', async () => {
    // 刻意用**非规范顺序**的返回值（含第 4 个部位 `布料`）—— 页面若硬编码第二份三值/四值字面量，
    // 下面「选项逐字、逐序 = 后端返回值」这条断言**必红**（注入法：把 `ruleOptions.positions` 换成
    // 字面量 `['布帘','纱帘','帘头']` ⇒ 少一个 `布料` ⇒ 红）。
    mockGetRouteRuleOptions
      .mockReset()
      .mockResolvedValue(ok({ crafts: ['韩褶'], processing_items: ['拼接'], positions: ['纱帘', '布料', '布帘', '帘头'] }))
    await openConditions('三边')
    await userEvent.click(screen.getByTestId('operation-condition-add'))
    await waitFor(() => expect(screen.getByTestId('operation-condition-form')).toBeInTheDocument())

    // 先在默认档（工艺）选一个值：切档必须把它清掉（不把上一档的值带过去）
    await userEvent.selectOptions(screen.getByTestId('condition-value'), '韩褶')

    // 第 4 个按钮**在「什么时候」这个 radiogroup 里**（与既有三档同构：role=radio / aria-checked）
    const positionKind = screen.getByRole('radio', { name: '部位' })
    expect(positionKind).toBe(screen.getByTestId('condition-kind-position'))
    await userEvent.click(positionKind)
    expect(positionKind).toHaveAttribute('aria-checked', 'true')

    const select = screen.getByTestId('condition-value')
    expect(select.tagName).toBe('SELECT')
    expect(within(select).getByRole('option', { name: '从部位列表里选…' })).toBeInTheDocument()
    // 取值 = **后端给的部位闭词表**（逐字 + 逐序；含第 4 个 `布料`）—— 不是页面自带的第二份
    expect(Array.from(select.querySelectorAll('option')).map((o) => (o as HTMLOptionElement).value)).toEqual([
      '',
      '纱帘',
      '布料',
      '布帘',
      '帘头',
    ])
    // 切档 ⇒ 已选取值被清空
    expect(select).toHaveValue('')

    await userEvent.selectOptions(select, '布帘')
    await userEvent.selectOptions(screen.getByTestId('condition-anchor'), '精裁')
    await userEvent.click(screen.getByTestId('condition-add-submit'))

    // 提交 body：`trigger_kind='position'` + `trigger_value` = 选中的部位 + `position` 镜像同值
    await waitFor(() =>
      expect(mockCreateOptionRule).toHaveBeenCalledWith({
        trigger_kind: 'position',
        trigger_value: '布帘',
        position: '布帘',
        action: 'insert',
        operation: '三边',
        after_operation: '精裁',
      }),
    )
  })

  it('⑱′-② 反向护栏：其它档**不带** `position` 键（留空 = 不限部位，不拿 `null` 冒充「没填」）', async () => {
    await openConditions('三边')
    await userEvent.click(screen.getByTestId('operation-condition-add'))
    await userEvent.selectOptions(screen.getByTestId('condition-value'), '罗马帘')
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
    // 注入法：把 `payload.position = null` 无条件带上 ⇒ 本条红（`position: null` 会被读成「显式不限」，
    // 而「没填」的语义是**省略该键**）。
    expect(Object.keys(mockCreateOptionRule.mock.calls[0][0] as object)).not.toContain('position')
  })

  it('⑱′-③ 「部位」档本地预检：未选取值 ⇒ **部位专属**可行动理由 + 不发请求', async () => {
    await openConditions('三边')
    await userEvent.click(screen.getByTestId('operation-condition-add'))
    await userEvent.click(screen.getByTestId('condition-kind-position'))
    await userEvent.click(screen.getByTestId('condition-add-submit'))

    const reasons = await screen.findByTestId('condition-add-reasons')
    expect(reasons).toHaveTextContent(
      '请选择什么时候生效：部位必须从列表里选（部位 = 布帘/纱帘/帘头/布料，空 = 不限部位）',
    )
    expect(mockCreateOptionRule).not.toHaveBeenCalled()
  })

  it('⑱′-④ 人话：`position` 档渲染成「部位 = X 时…」（insert 带锚点 / remove 不带）', async () => {
    mockGetRouteRules.mockReset().mockResolvedValue(
      ok([
        { id: 41, trigger_kind: 'position', trigger_value: '布帘', position: '布帘', action: 'insert', operation: '韩褶', after_operation: '三边', priority: 5, status: 'active' },
        { id: 42, trigger_kind: 'position', trigger_value: '纱帘', position: '纱帘', action: 'remove', operation: '车被', after_operation: null, priority: 6, status: 'active' },
      ]),
    )
    await openManage('韩褶')
    // 注入法：把 `TRIGGER_KIND_LABEL` 的 `position` 映射去掉 ⇒ 这里渲染成 `position = 布帘 …` ⇒ 红
    expect(await screen.findByTestId('operation-condition-text-41')).toHaveTextContent(
      '部位 = 布帘 时插入（在「三边」之后）',
    )

    await userEvent.click(screen.getByTestId('operations-manage-close'))
    await userEvent.click(screen.getByTestId('matrix-manage-车被'))
    expect(await screen.findByTestId('operation-condition-text-42')).toHaveTextContent('部位 = 纱帘 时不做')
  })

  it('⑱′-⑤ 反向护栏：`craft` 档带部位列 **必须说出来**（不静默藏）；空 `position` 不渲染任何部位文案', async () => {
    mockGetRouteRules.mockReset().mockResolvedValue(
      ok([
        // ① 触发维是 `craft`、`position` 列**有值**（迁移 V108 写回的存量行 / 直写 API 的行）
        //    ⇒ 🔴 issue #4962 起**必须**把部位这一维说进人话 —— 藏起来 = 商家看不见
        //    「这条条件只对布帘生效」（静默信息缺口）。注入法：只渲染 `kind`/`value`、
        //    丢掉 `rule.position` ⇒ 本断言红（`工艺 = 打孔 时不做` ≠ `部位 = 布帘、工艺 = 打孔 时不做`）。
        { id: 51, trigger_kind: 'craft', trigger_value: '打孔', position: '布帘', action: 'remove', operation: '车被', after_operation: null, priority: 7, status: 'active' },
        // ② `position` 为空 = **不限部位** ⇒ 不得渲染「部位 = —」这类假值（注入法：无脑拼一段部位文案 ⇒ 红）
        { id: 52, trigger_kind: 'craft', trigger_value: '韩褶', position: null, action: 'insert', operation: '韩褶', after_operation: '三边', priority: 8, status: 'active' },
      ]),
    )
    await openManage('韩褶')
    const noPosition = await screen.findByTestId('operation-condition-text-52')
    expect(noPosition).toHaveTextContent('工艺 = 韩褶 时插入（在「三边」之后）')
    expect(noPosition.textContent ?? '').not.toContain('部位')

    await userEvent.click(screen.getByTestId('operations-manage-close'))
    await userEvent.click(screen.getByTestId('matrix-manage-车被'))
    const craftWithPositionColumn = await screen.findByTestId('operation-condition-text-51')
    // `trigger_kind ≠ 'position'` ⇒ **两个子句都要在**（部位在前、触发维在后，`、` 连接）
    expect(craftWithPositionColumn).toHaveTextContent('部位 = 布帘、工艺 = 打孔 时不做')
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
    mockGetOperationsCatalog.mockReset().mockResolvedValue(ok(LOGICAL_CATALOG))
    await openManage('精裁')

    await userEvent.click(screen.getByTestId('operations-manage-delete'))

    const modal = await screen.findByTestId('operations-manage-delete-modal', {}, { timeout: 1500 })
    // 主标识 = **逻辑工序名**（issue #4622 / #4886 —— 变体名不上界面）
    expect(modal).toHaveTextContent('「精裁」')
    expect(modal).not.toHaveTextContent('精裁-布')
    expect(modal).toHaveAttribute('data-operation', '精裁')
    expect(mockDeleteOperation).not.toHaveBeenCalled()

    // 取消 ⇒ 不发请求
    await userEvent.click(screen.getByTestId('operations-manage-delete-cancel'))
    expect(mockDeleteOperation).not.toHaveBeenCalled()
    await waitFor(() => expect(screen.queryByTestId('operations-manage-delete-modal')).toBeNull())
  })

  /**
   * issue #4665 ①：**发现性失败** —— 做/不做开关只藏在主表格的 `⇄` 里，而商家此刻在抽屉里
   * （弹框让他「先去设为不做」）⇒ 抽屉必须**直接**能看到并改做/不做。
   *
   * 红证（改前）：抽屉里没有 `drawer-applicable-*` 控件 ⇒ 本用例红（找不到 testid）。
   */



  /**
   * issue #4665 ②（**issue #4947 去重**）：原本这里还有一条 `#4665-B`「一键『设为不做并删除』」
   * 用例 —— 它驱动的是**逐行**的 `variant-detach-and-delete-*`，而那一整条路径已随 #4947 退场。
   * 该场景**未被丢弃**：`㉙-③`（同夹具：二次确认 → `{detachPositions:true}` → 刷新）与
   * `#4692-A`（弹框说清后果「设为不做」「历史报工不受影响」+ 关弹框 + 一次事务、不逐个 PUT 矩阵）
   * 逐条覆盖了它。
   */

  /**
   * 反向护栏（issue #4665 明确要求）：**主线那一条不得被一键按钮绕过**。
   *
   * 主线涉及车间顺序，必须人工确认 —— 后端护栏①（活跃路线主线）对 `detach_positions=true`
   * **照样拦**（本用例用真实后端语义的 422 打桩：理由里只有主线，没有矩阵格）。
   * 一键按钮不得让工序消失，且理由必须**逐条就地**展示。
   *
   * ⚠️ issue #4947：入口 = 抽屉 footer 的「删除」（**确认删除** 在背后选 detach 那条路）；
   * `data-testid` 随之从 `variant-detach-and-delete-*` 换成 `operations-manage-delete-*`。
   */
  it('#4665-C 反向护栏：主线命中 ⇒ 一键「设为不做并删除」**也被拦**（工序不被删）', async () => {
    mockGetOperationsCatalog.mockReset().mockResolvedValue(ok(LOGICAL_CATALOG))
    mockDeleteOperation.mockReset().mockRejectedValueOnce(
      guardError(['工序「精裁」还在活跃路线「窗帘工序路线（默认）」的主线里 —— 先改主线（把它从该路线去掉），再删它']),
    )
    await openManage('精裁')
    await userEvent.click(screen.getByTestId('operations-manage-delete'))
    await userEvent.click(await screen.findByTestId('operations-manage-delete-confirm'))

    await waitFor(() =>
      expect(mockDeleteOperation).toHaveBeenCalledWith('op-精裁-布', { detachPositions: true }),
    )
    // 主线理由**就地**展示（不吞成一句「删除失败」）
    const reasons = await screen.findByTestId('operations-manage-delete-reasons')
    expect(reasons).toHaveTextContent('先改主线')
    // 被拦 ⇒ 弹框仍在（不是静默半完成），且抽屉里的工序**还在**
    expect(screen.getByTestId('operations-manage-delete-modal')).toBeInTheDocument()
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
    mockGetOperationsCatalog.mockReset().mockResolvedValue(ok(LOGICAL_CATALOG))
    // 读面序列：首次（渲染）返回全量；删除后的那次刷新 = 后端已级联软删 ⇒ **不含**「精裁」
    mockGetOperationPositions
      .setDefault(POSITIONS.filter((c) => c.operation !== '精裁'))
      .setDefaultOnce(POSITIONS)
    await openManage('精裁')
    expect(screen.getByTestId('matrix-row-精裁')).toBeInTheDocument()

    await userEvent.click(screen.getByTestId('operations-manage-delete'))
    await userEvent.click(await screen.findByTestId('operations-manage-delete-confirm'))
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
        // issue #4886：请求体**不再带 `positions`**（「适用部位」已随部位从配置面退场）
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

    // ② 工序名称旁有**商家语言的**提示：只写这道活本身
    const hint = screen.getByTestId('routings-create-op-name-hint')
    expect(hint).toHaveTextContent('只写这道活本身')
    expect(hint).toHaveTextContent('不要带任何前缀或后缀')
    // 提示本身不得举变体名当例子（那会把变体名又带回这一屏）
    expect(hint.textContent ?? '').not.toContain('布三边')

    // ③ issue #4886：「适用部位」多选已整块退场（配置面不再有部位概念）
    expect(screen.queryByTestId(/^routings-create-op-position-/)).toBeNull()
  })

  it('⑳ 矩阵空态指向**右上**入口（issue #4615：入口换位置后不得留下死引用）', async () => {
    mockGetOperationPositions.setDefault([])
    await renderOperations()

    const empty = screen.getByTestId('operation-price-matrix-empty')
    expect(empty).toHaveTextContent('点右上「新增工序」建一道')
    expect(empty).not.toHaveTextContent('点上方')
  })

  it('路线半边：主线逐道渲染 —— 只显示 序号 + 工序名（不发明任何库口径元数据）', async () => {
    await renderOnRoutes()
    await waitFor(() => expect(screen.getByTestId('routing-step-11-1')).toBeInTheDocument())

    const logical = screen.getByTestId('routing-step-11-1')
    expect(logical).toHaveTextContent('精裁')
    expect(logical).not.toHaveTextContent('¥')
    // ⚠️ issue #4961 改判：原「精裁」chip 上那枚按矩阵聚合出来的「必完」标记**已退场**
    // （完工口径改为「全部工序实例全绿」）⇒ 三条 chip 一律不得再出现该词
    expect(logical).not.toHaveTextContent('必完')
    expect(screen.getByTestId('routing-step-11-2')).not.toHaveTextContent('必完')
    expect(screen.getByTestId('routing-step-11-3')).toHaveTextContent('外帘装袋')
    expect(screen.getByTestId('routing-step-11-3')).not.toHaveTextContent('必完')
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

  // ⚠️ issue #4961：原「㉖-⑧ 主线 chip 的「必完」按**价目行**判」那条用例的**被测对象已整体删除**
  // （`routing-step-must-finish-*`）⇒ 判据换成 #4961-③ 的反向断言（chip 上不再有任何必完标记），
  // 「主线 chip 不显示库口径元数据 / 不显示单价」两条由相邻用例继续守着，**不放宽**。

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
    // 显示形态 = 逻辑名 + 分组（分组取**收敛后那一行**的值；一道工序一行 ⇒ 不再有「逐个列出」）
    expect(select.options[1].textContent).toBe('三边（车位）')
    expect(select.options[2].textContent).toBe('精裁（裁剪）')
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
        '当前账号没有工艺路线管理权限',
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
    // 🔴 改判（issue #4961 集成收口）：「至少一道必完工序」那条**后端护栏已退场**（五条 ⇒ 四条），
    // 前端 `describeRoutingGuard` 的「缺少必完工序」前缀分支也随之一并删除（该文件自述的死亡条件已满足）
    // ⇒ 本用例的第三条改用**仍在**的护栏（权限），判据一格不放宽：逐条独立成条 + 可读归因 + **原文逐字不吞**
    expect(screen.getByTestId('routing-error-item-2')).toHaveTextContent('没有工艺路线管理权限')
    expect(screen.getByTestId('routing-error-item-2')).toHaveTextContent('当前账号没有工艺路线管理权限')
  })

  // ⚠️ issue #4961：原「护栏就地预检：主线缺必完工序 ⇒ 黄条」那条用例的**被测对象已整体删除**
  // （`lacksMustFinish` + `routing-precheck-*`）⇒ 判据换成 #4961-④ 的反向断言；
  // 另一半预检（工序不存在 / 已停用）由 ㉖-⑦ / #4605 继续守着，**不放宽**。

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

  it('新建路线：提交 `{name}`（不再传 positions）并自动进入主线编辑', async () => {
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
    // issue #4886：弹窗里**不再有任何**部位勾选项（「适用帘种」随部位退场）
    expect(screen.queryByTestId(/^routings-create-position-/)).toBeNull()
    await userEvent.type(screen.getByTestId('routings-create-name'), '罗马帘专线')
    await userEvent.click(screen.getByTestId('routings-create-route-submit'))

    // issue #4886：**不再传 `positions`**（「适用帘种」随部位从配置面退场 ——
    // 省略字段而不是传空数组：空数组会被读成「不适用任何范围」，语义不同）
    await waitFor(() => expect(mockCreateRouting).toHaveBeenCalledWith({ name: '罗马帘专线' }))
    // 建壳后**自动进入主线编辑**（消灭「建了条空壳但没人知道」的静默态）
    await waitFor(() => expect(screen.getByTestId('routing-save-13')).toBeInTheDocument())
    expect(screen.getByTestId('routing-draft-empty-13')).toHaveTextContent('从工序库选择')
  })

  it('**两个 tab**（工序管理 / 算料配置）且默认落前者；工序表与路线列表**同屏**（用户裁定合并后的形态）', async () => {
    render(<ProcessConfigPage />)
    await waitFor(() => expect(screen.getByTestId('process-config-tabs')).toBeInTheDocument())

    const tabs = screen.getByTestId('process-config-tabs')
    expect(within(tabs).getAllByRole('tab')).toHaveLength(2)
    const processTab = screen.getByTestId('process-config-tab-process')
    const calcTab = screen.getByTestId('process-config-tab-calc')
    expect(processTab).toHaveTextContent('工序管理')
    expect(calcTab).toHaveTextContent('算料配置')
    expect(processTab).toHaveAttribute('data-state', 'active')

    // 合并后的判据：**同一屏里两张都在**（改前是「切换互斥」）
    expect(screen.getByTestId('operation-price-matrix')).toBeInTheDocument()
    expect(screen.getByTestId('routings-total')).toBeInTheDocument()
    // 旧的独立区块与旧 tab 一律不存在
    expect(screen.queryByTestId('delivery-section')).toBeNull()
    expect(screen.queryByTestId('process-config-tab-operations')).toBeNull()
    expect(screen.queryByTestId('process-config-tab-routes')).toBeNull()
    // 工艺路线**就在原【打包发货】的位置**：文档序在工序表**之后**
    const rel = screen.getByTestId('craft-operations-panel').compareDocumentPosition(
      screen.getByTestId('routings-list'),
    )
    expect(rel & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()

    // 切到「算料配置」⇒ 两者都不在（真正互斥的是这一对）
    await userEvent.click(calcTab)
    expect(screen.queryByTestId('operation-price-matrix')).not.toBeInTheDocument()
    expect(screen.queryByTestId('routings-total')).not.toBeInTheDocument()
  })

  it('切 tab **不丢状态**：在「工艺路线」编辑主线 → 切走 → 切回，draft 仍在', async () => {
    await renderOnRoutes()
    await waitFor(() => expect(screen.getByTestId('routing-edit-11')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('routing-edit-11'))
    await userEvent.selectOptions(screen.getByTestId('routing-add-select-11'), '车被')
    await userEvent.click(screen.getByTestId('routing-add-11'))
    expect(screen.getByTestId('routing-draft-step-11-4')).toHaveTextContent('车被')

    await userEvent.click(screen.getByTestId('process-config-tab-process'))
    await userEvent.click(screen.getByTestId('process-config-tab-process'))

    // 注入：把 draft 改成随 tab 重置 ⇒ 红
    expect(screen.getByTestId('routing-draft-step-11-4')).toHaveTextContent('车被')
    expect(screen.getByTestId('routing-save-11')).toBeInTheDocument()
  })

  it('只读端点失败不白屏：路线列表失败给提示 + 重试；工序库失败只在该区提示', async () => {
    mockGetRoutings.mockReset().mockRejectedValueOnce(new Error('500')).mockResolvedValue(ok(ROUTINGS))
    render(<ProcessConfigPage />)

    await waitFor(() => expect(screen.getByTestId('routings-error')).toHaveTextContent('工艺路线加载失败'))
    await userEvent.click(screen.getByTestId('routings-retry'))
    await userEvent.click(await screen.findByTestId('process-config-tab-process'))
    await waitFor(() => expect(screen.getByTestId('routings-total')).toHaveTextContent('2'))
  })

  it('工序库加载失败不白屏：这一张表照常（表只依赖价目读面），抽屉不发明 provenance', async () => {
    mockGetOperationsCatalog.mockReset().mockRejectedValueOnce(new Error('500')).mockResolvedValue(ok(CATALOG))
    await renderOperations()

    // 表照常渲染真实价（工序库读面挂了不该把这一屏吞掉）
    expect(screen.getByTestId('operation-price-精裁')).toHaveTextContent('¥8.50')

    await userEvent.click(screen.getByTestId('matrix-manage-精裁'))
    await waitFor(() => expect(screen.getByTestId('operations-manage-drawer')).toBeInTheDocument())
    // 设置行来自价目读面，不依赖工序库；provenance 查不到 ⇒ 不渲染徽标（静默 = 未知）
    const row = screen.getByTestId('variant-row-op-精裁-布')
    expect(row).toHaveTextContent('精裁')
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
    // 🔴 **2026-09-21 改判（issue #4962，加回「适用条件」的部位维）**：`position` 非空的规则
    // 现在**必须**把部位说进人话（`conditionText` 加 `部位 = <值>` 子句；`trigger_kind='position'`
    // 时它就是唯一子句）。本用例的 2/3 号规则带 `position` ⇒ 期望文案随之改判
    // （**只改与实现不符的文案，判据一格不放宽**：条数 / 归属 / 逐字文本三条判据全在，且**新增**
    // 了对部位子句的覆盖；注入法：把 `conditionText` 的 `positionClause` 去掉 ⇒ 下面两条当场红）。
    const expected: Record<string, string[]> = {
      韩褶: ['工艺 = 韩褶 时插入（在「三边」之后）', '部位 = 布帘、工艺 = 打孔 时不做'],
      三边: ['部位 = 纱帘、特殊选项 = 拼2次 时插入（追加到末尾）'],
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
 * ② 改一个参数 ⇒ `PUT` 带**全量键**（**11 键**，issue #5130 起；缺键 = 让后端静默回默认值 ⇒ 红）；
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
    // issue #5198：算料参数改用 NumberInput（`type="text"` + 字符串草稿，否则清空时框里会变字面量 `NaN`）
    // ⇒ jest-dom 的 `toHaveValue` 对 text 控件按**字符串**比对，逐值钉住的强度不变。
    expect(screen.getByTestId('craft-calc-config-scalar-per_fold_single')).toHaveValue('0.25')
    expect(screen.getByTestId('craft-calc-config-scalar-min_fullness')).toHaveValue('1.5')
    expect(screen.getByTestId('craft-calc-config-default_formula')).toHaveValue('pleat')
    expect(screen.getByTestId('craft-calc-config-tier-standard-fullness')).toHaveValue('2')
    expect(screen.getByTestId('craft-calc-config-mixed-1')).toHaveValue('0.65')
  })

  it('改「单色每折吃布」⇒ PUT 带全量键（缺键会让后端静默回默认值）', async () => {
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
        'hem_margin',
        'meters_rounding_step',
        // 🔴 issue #5130：两个**企业阈值**（超宽 / 超高判据）也是配置键 ⇒ 必须在全量 PUT 里
        //（少了它们 = 后端按缺键 422，或静默回默认值 ⇒ 商家改的阈值丢失 = 静默失效的形态）
        'oversize_width_threshold',
        'oversize_height_threshold',
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
    expect(screen.getByTestId('craft-calc-config-scalar-min_fullness')).toHaveValue('1')
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

    await userEvent.click(screen.getByTestId('process-config-tab-process'))
    await waitFor(() => expect(screen.getByTestId('routings-list')).toBeInTheDocument())
    await userEvent.click(screen.getByTestId('process-config-tab-calc'))

    expect(screen.getByTestId('craft-calc-config-scalar-margin_multi')).toHaveValue('0.45')
  })

  // issue #5198：算料参数原形态 `type="number"` + `value={String(v ?? '')}` + 清空落 NaN 哨兵
  // ⇒ 用户一清空，输入框里就渲染出**字面量 `NaN`**（`String(NaN)`），而且清都清不掉。
  // 红证：把这几格换回旧形态，本条必红（实测 `toHaveValue('')` 收到 'NaN'）。
  it('清空算料参数 ⇒ 空框（不许变成字面量 `NaN`），且 0.x 小数能正常录入', async () => {
    render(<ProcessConfigPage />)
    await waitFor(() => expect(screen.getByTestId('operation-price-matrix')).toBeInTheDocument())
    await userEvent.click(screen.getByTestId('process-config-tab-calc'))
    await waitFor(() => expect(screen.getByTestId('craft-calc-config-panel')).toBeInTheDocument())

    const scalar = screen.getByTestId('craft-calc-config-scalar-per_fold_single')
    const fullness = screen.getByTestId('craft-calc-config-tier-standard-fullness')
    const mixed = screen.getByTestId('craft-calc-config-mixed-1')

    // ① 0.x 中间态逐键录得进去（0 → 0. → 0.5，不吞小数点、不把 0 当空）
    await userEvent.clear(scalar)
    await userEvent.type(scalar, '0.5')
    expect(scalar).toHaveValue('0.5')

    // ② 清空 ⇒ 空框（不是 `NaN`）
    await userEvent.clear(scalar)
    expect(scalar).toHaveValue('')
    await userEvent.clear(fullness)
    expect(fullness).toHaveValue('')
    await userEvent.clear(mixed)
    expect(mixed).toHaveValue('')

    // ③ 兜底：面板里任何输入框都不得以 `NaN` 为值
    const inputs = Array.from(document.querySelectorAll('input')) as HTMLInputElement[]
    expect(inputs.filter((el) => el.value === 'NaN')).toEqual([])
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
    expect(screen.getByTestId('craft-calc-config-tier-standard-fullness')).toHaveValue('2')
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
    await waitFor(() => expect(screen.getByTestId('craft-calc-config-scalar-per_fold_single')).toHaveValue('0.25'))
  })
})
})

/**
 * 部位价目矩阵的**历史规模**夹具（issue #4529 / V79：30 逻辑工序 × **4** 部位 = **120** 格）。
 *
 * ⚠️ issue #4886 / **#4951**：真读面已被后端 `collapseToLogical` 收敛为「一道逻辑工序**一行**」
 * （部位维物理退场、幸存行 `position` 恒 `通用`）；本夹具**故意保留多行形态**
 * ⇒ 它同时是「前端能按逻辑工序名去重收敛」的**红证夹具**（收敛规则见 `pickConvergedCell`）。
 * 服务端顺序 = `(operation, position)`；**两态齐备**：布料列 `unit_price=null`（**未定价**）/ 其余有价。
 * ⚠️ **不再有 `applicable`**（#4937 / O1 起该字段退场且恒 `TRUE`）—— 纱帘列不再是「不做」。
 */
const MATRIX_120 = Array.from({ length: 30 }, (_, i) => `工序${i + 1}`).flatMap((operation, oi) =>
  ['布帘', '纱帘', '帘头', '布料'].map((position, pi) => ({
    id: `mp-${operation}-${position}`,
    operation,
    position,
    unit_price: pi === 3 ? null : oi + pi,
  })),
)

describe('工序单价表：一道工序一行（issue #4886 去部位化）', () => {
  beforeEach(() => {
    mockGetOperationPositions.setDefault(MATRIX_120)
  })

  it('同一逻辑名的多行**收敛为一行**：30 行（不是 120 行），列头只有「一个单价」', async () => {
    await renderOperations()

    // ① 行数 = 逻辑工序数（不是格数）
    expect(screen.getByTestId('operation-price-matrix-total')).toHaveTextContent('30')
    expect(screen.getByTestId('matrix-row-工序1')).toBeInTheDocument()
    // ② 同一道工序只有**一个**价（不是 4 个格）
    expect(screen.getAllByTestId('operation-price-工序1')).toHaveLength(1)
    // ③ **没有任何**部位列 / 格 / 适用性开关的 testid 残留（testid 也是界面契约的一部分）
    expect(screen.queryByTestId(/^matrix-cell-/)).toBeNull()
    expect(screen.queryByTestId(/^matrix-applicable-/)).toBeNull()
    expect(screen.queryByTestId(/^drawer-applicable-/)).toBeNull()
    // ④ 列头 = 工序 / 单价 / 分组 · 单位 · 操作（⚠️ #4961 起「必完」从列头退场）
    const table = screen.getByTestId('operation-workshop-table')
    const heads = within(table).getAllByRole('columnheader').map((th) => th.textContent)
    expect(heads).toEqual(['工序', '单价', '分组 · 单位 · 操作'])
  })

  it('收敛规则：按 `position` 字典序 → `id` 升序（与后端 `collapseToLogical` 同口径）⇒ 保留其 id 作改价寻址', async () => {
    await renderOperations()

    // 工序1 的四行：布帘（价 0）/ 纱帘（价 1）/ 帘头（价 2）/ 布料（价 null）
    // ⇒ 字典序取 `布帘` ⇒ 真 0 元（`¥0.00`，**不是**「未定价」）
    // ⚠️ 2026-09-21 改判（配套 #4937 / #4951）：原平局规则「优先 `applicable=true` → 其中优先
    // `布帘`」已退场（`applicable` 恒 `TRUE` 且字段退场；真数据里 `position` 恒 `通用`）——
    // 判据面（选中哪一行 + 该行的 `id` 就是改价寻址键）**一字不放宽**，只是规则换成仍可判定的两条。
    const cell = screen.getByTestId('operation-price-工序1')
    expect(cell).toHaveAttribute('data-state', 'priced')
    expect(cell).toHaveTextContent('¥0.00')

    // 改价寻址 = **收敛后那一行**的 id（选错行就等于改另一个价）
    await userEvent.click(screen.getByTestId('operation-price-edit-工序1'))
    await userEvent.clear(screen.getByTestId('operation-price-input-工序1'))
    await userEvent.type(screen.getByTestId('operation-price-input-工序1'), '3.5')
    await userEvent.click(screen.getByTestId('operation-price-save-工序1'))

    await waitFor(() =>
      expect(mockUpdateOperationPosition).toHaveBeenCalledWith('mp-工序1-布帘', { unit_price: 3.5 }),
    )
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
    mockGetOperationPositions.setDefault(POSITIONS)
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
    id: 'pos-测试22-布帘', operation: '测试22', position: '布帘', unit_price: 0.5,
    variant_operation_id: 'op-test22', unit: '米', group: '其他',
    scope: 'position', is_must_finish: false,
  }



  it('㉕-② 反向护栏：已被矩阵格指向的工序**不算**孤儿（不提示）', async () => {
    mockGetOperationsCatalog.mockResolvedValue(
      ok({ total: 1, groups: [{ group: '裁剪', operations: [PRICED_OP] }] }),
    )
    await renderOperations()

    expect(screen.queryByTestId('matrix-orphan-hint')).toBeNull()
  })





})

/**
 * ══════════════════ #4677：工艺项**两层改造**（设计 `docs/design/public-operations-and-craft-ui.md`
 * §4 界面改造 / §6 种子自愈 / §7 第 7 条）══════════════════
 *
 * 本组用自己的**真形态**夹具（`LAYER_CELLS`）：一道工序只属一个车间（真数据如此）、
 * 交付环节（`scope='set'`）四道齐（打包 / 外帘打卷 / 外帘装袋 / 外帘发货）、
 * **`裁剪 × 布料` 保命格**在场（V88 逐字保留的那一格）。
 *
 * 红证（改前必红，逐条实测见 PR 描述）：
 * ① 交付环节**按部位 4 格**渲染（改后 = **一列价**）⇒ `matrix-row-*` / `operation-price-*` 不存在；
 * ② 工序层**没有**车间分组、不可折叠 ⇒ `matrix-workshop-*` 不存在；
 * ③ `布料` 当第 4 个部位列出来 ⇒ 列头含 `布料`、工序层 4 列；
 * ④ **布料单的 `裁剪` / `打包` 没有可见定价位置** ⇒ `fabric-sheet-*` 不存在（#4677 评论逐字的硬要求）；
 * ⑤ 补套入口在工序库非空时**隐藏** ⇒ `seed-templates` 不存在；
 * ⑥ 就绪度②**只数条数** ⇒ 缺 `布料工序路线` 时仍显示「已完成」。
 */
const LAYER_CELLS = [
  // ── 工序层（`scope='position'`）：裁剪（裁床）/ 车位（缝制）/ 后整（烫工及后整）/ 质检 ──
  { id: 'lc-1', operation: '精裁', position: '布帘', unit_price: 0.4, variant_operation_id: 'lop-精裁', unit: '米', group: '裁剪', scope: 'position', is_must_finish: true },
  { id: 'lc-2', operation: '精裁', position: '纱帘', unit_price: 0.4, variant_operation_id: 'lop-精裁-纱', unit: '米', group: '裁剪', scope: 'position', is_must_finish: true },
  { id: 'lc-3', operation: '精裁', position: '帘头', unit_price: 0.4, variant_operation_id: 'lop-精裁', unit: '米', group: '裁剪', scope: 'position', is_must_finish: true },
  { id: 'lc-4', operation: '三边', position: '布帘', unit_price: 0.4, variant_operation_id: 'lop-三边', unit: '米', group: '车位', scope: 'position', is_must_finish: true },
  { id: 'lc-5', operation: '三边', position: '纱帘', unit_price: 0.4, variant_operation_id: 'lop-三边-纱', unit: '米', group: '车位', scope: 'position', is_must_finish: true },
  { id: 'lc-6', operation: '熨烫', position: '布帘', unit_price: 0.6, variant_operation_id: 'lop-熨烫', unit: '米', group: '后整', scope: 'position', is_must_finish: false },
  { id: 'lc-7', operation: '质检', position: '布帘', unit_price: null, variant_operation_id: 'lop-质检', unit: '件', group: '质检', scope: 'position', is_must_finish: false },
  // ── 🔴 `裁剪 × 布料` **保命格**（V88 逐字保留：存量未实例化布料单补生成需要它）──
  { id: 'lc-8', operation: '裁剪', position: '布料', unit_price: 7, variant_operation_id: 'lop-裁剪-布', unit: '套', group: '裁剪', scope: 'position', is_must_finish: true },
  // ── 交付层（`scope='set'`）：四道齐，一列价四态各一 ──
  // `打包`：4 个部位价全同 1.5 ⇒ `priced`
  { id: 'lc-9', operation: '打包', position: '布帘', unit_price: 1.5, variant_operation_id: 'lop-打包', unit: '套', group: '后道', scope: 'set', is_must_finish: true },
  { id: 'lc-10', operation: '打包', position: '纱帘', unit_price: 1.5, variant_operation_id: 'lop-打包', unit: '套', group: '后道', scope: 'set', is_must_finish: true },
  { id: 'lc-11', operation: '打包', position: '帘头', unit_price: 1.5, variant_operation_id: 'lop-打包', unit: '套', group: '后道', scope: 'set', is_must_finish: true },
  { id: 'lc-12', operation: '打包', position: '布料', unit_price: 1.5, variant_operation_id: 'lop-打包', unit: '套', group: '后道', scope: 'set', is_must_finish: true },
  // `外帘打卷`：4 格价全空 ⇒ 收敛后判 `unpriced`（#4951：第四态 `no_applicable_position` 已退场）
  { id: 'lc-13', operation: '外帘打卷', position: '布帘', unit_price: null, variant_operation_id: 'lop-外帘打卷', unit: '套', group: '后道', scope: 'set', is_must_finish: false },
  { id: 'lc-14', operation: '外帘打卷', position: '纱帘', unit_price: null, variant_operation_id: 'lop-外帘打卷', unit: '套', group: '后道', scope: 'set', is_must_finish: false },
  // `外帘装袋`：**未定价**（价 `null`）⇒ `unpriced`（**≠ ¥0.00**）
  { id: 'lc-15', operation: '外帘装袋', position: '布帘', unit_price: null, variant_operation_id: 'lop-外帘装袋', unit: '套', group: '后道', scope: 'set', is_must_finish: true },
  { id: 'lc-15b', operation: '外帘装袋', position: '纱帘', unit_price: null, variant_operation_id: 'lop-外帘装袋', unit: '套', group: '后道', scope: 'set', is_must_finish: true },
  // `外帘发货`：各部位不同价（1 / 2）⇒ `multiple_prices` + 计数（**不静默取第一个**）
  { id: 'lc-16', operation: '外帘发货', position: '布帘', unit_price: 1, variant_operation_id: 'lop-外帘发货', unit: '套', group: '后道', scope: 'set', is_must_finish: true },
  { id: 'lc-17', operation: '外帘发货', position: '纱帘', unit_price: 2, variant_operation_id: 'lop-外帘发货', unit: '套', group: '后道', scope: 'set', is_must_finish: true },
]

/** 缺 `布料工序路线`（工序库**非空**）—— §6 修法 A/B 的**红证形态** */
const ROUTINGS_WITHOUT_FABRIC = {
  total: 1,
  routings: [
    { id: 11, name: '窗帘工序路线（默认）', is_default: true, positions: ['布帘', '纱帘', '帘头'], mainline: ['精裁', '三边'], status: 'active' },
  ],
}

/** 两条基础路线**齐**（与后端 `ProductionSeedTemplateService` 的两个常量逐字同名） */
const ROUTINGS_WITH_BASE = {
  total: 2,
  routings: [
    { id: 11, name: '窗帘工序路线（默认）', is_default: true, positions: ['布帘', '纱帘', '帘头'], mainline: ['精裁', '三边'], status: 'active' },
    { id: 13, name: '布料工序路线', is_default: false, positions: ['布料'], mainline: ['裁剪', '打包'], status: 'active' },
  ],
}

describe('#4677 工艺项两层改造（【工序】按车间分组 + 【打包发货】一列价 + 【布料单】定价入口）', () => {
  beforeEach(() => {
    // 本组**自带全部**夹具（模块级 mock 无全局 clearMocks，别的 describe 的 beforeEach
    // 只 reset 自己关心的那几个 ⇒ 不能指望它们）—— 少一个就会 await 到 `undefined`。
    mockGetOperationPositions.setDefault(LAYER_CELLS)
    mockGetOperationLayers.mockClear()
    mockGetRoutings.mockReset().mockResolvedValue(ok(ROUTINGS_WITH_BASE))
    mockGetOperationsCatalog.mockReset().mockResolvedValue(ok(CATALOG))
    mockGetSeedTemplates.mockReset().mockResolvedValue(ok(TEMPLATES))
    mockGetRouteRules.mockReset().mockResolvedValue(ok(RULES))
    mockGetRouteRuleOptions.mockReset().mockResolvedValue(ok(RULE_TRIGGER_OPTIONS))
    mockUpdateOperationPosition.mockReset().mockResolvedValue(ok({ id: 'lc-8' }))
    mockUpdateOperation.mockReset().mockResolvedValue(ok({ id: 'lop-打包' }))
    mockDeleteOperation.mockReset().mockResolvedValue(ok({ id: 'lop-打包', deleted: true }))
  })

  // ────────────────────── 两层布局（B1 / B2 / B3 / B4） ──────────────────────

  it('B1 一张表装**全部**工序（用户裁定 2026-09-21：删【打包发货】独立区块 + 两个 tab 合并）', async () => {
    await renderOperations()

    // 【工序】：`scope='position'` 的四道（含**布料单**的 `裁剪`）
    const workshop = screen.getByTestId('operation-price-matrix')
    for (const op of ['精裁', '三边', '熨烫', '质检', '裁剪', '打包', '外帘打卷', '外帘装袋', '外帘发货']) {
      expect(within(workshop).getByTestId(`matrix-row-${op}`)).toBeInTheDocument()
    }
    // 用户裁定 2026-09-21：原【打包发货】独立区块**整块删除**、两个 tab 合并为一屏 ⇒
    // 判据换成「**所有工序都在这一张表里**」，且不再存在任何 `delivery-*` 节点（同一概念不再有第二个载体）
    for (const op of ['打包', '外帘打卷', '外帘装袋', '外帘发货']) {
      expect(within(workshop).getByTestId(`operation-price-${op}`)).toBeInTheDocument()
    }
    expect(screen.queryByTestId('delivery-section')).toBeNull()
    expect(screen.queryAllByTestId(/^delivery-/)).toHaveLength(0)
  })

  it('B2 「工序」区**按车间分组可折叠**（行业术语：裁剪（裁床）/ 车位（缝制）/ 后整（烫工及后整）/ 质检）；界面**不出现「槽位」**', async () => {
    await renderOperations()

    // 四个车间组各一个可折叠容器（默认展开 —— 商家进来第一眼要看见工序）
    const expected = [
      ['裁剪', '裁剪（裁床）'],
      ['车位', '车位（缝制）'],
      ['后整', '后整（烫工及后整）'],
      ['质检', '质检'],
    ] as const
    for (const [group, label] of expected) {
      const toggle = screen.getByTestId(`matrix-workshop-toggle-${group}`)
      expect(toggle).toHaveAttribute('aria-expanded', 'true')
      expect(toggle).toHaveTextContent(label)
    }
    // 折叠：收起「裁剪（裁床）」⇒ 这一组的行不再渲染（表头/其他组不受影响）
    await userEvent.click(screen.getByTestId('matrix-workshop-toggle-裁剪'))
    expect(screen.queryByTestId('matrix-row-精裁')).toBeNull()
    expect(screen.getByTestId('matrix-row-三边')).toBeInTheDocument()
    expect(screen.getByTestId('matrix-workshop-toggle-裁剪')).toHaveAttribute('aria-expanded', 'false')
    // 再点开 ⇒ 回来
    await userEvent.click(screen.getByTestId('matrix-workshop-toggle-裁剪'))
    expect(screen.getByTestId('matrix-row-精裁')).toBeInTheDocument()

    // 用户裁定：**不许**用「槽位」这类我们发明的词（`docs/design/operation-slot-model.md` 的
    // 「槽位」是**打褶那一道**的内部口径，不是商家语言）
    expect(screen.getByTestId('craft-operations-panel')).not.toHaveTextContent('槽位')
  })

  it('B3 这张表 = **一道工序一个价**（列头恰三列 + 行尾单位逐字取后端）', async () => {
    await renderOperations()
    const delivery = screen.getByTestId('operation-price-matrix')

    // 列头**恰三列**（工序 / 单价 / 分组·单位·操作）—— 不是「工序 + 4 个部位」；
    // ⚠️ #4961：第三列文案里的「必完」已退场
    expect(within(delivery).getAllByRole('columnheader').map((c) => c.textContent)).toEqual([
      '工序',
      '单价',
      '分组 · 单位 · 操作',
    ])
    // 一道工序**恰好一个**价节点（改前是「一个部位一个格」）
    expect(within(delivery).getAllByTestId(/^matrix-row-/).length)
      .toBe(within(delivery).getAllByTestId(/^operation-price-[^-]+$/).length)
    expect(within(delivery).queryAllByTestId(/^matrix-cell-/)).toHaveLength(0)

    expect(within(delivery).getByTestId('operation-price-打包')).toHaveTextContent('¥1.50')
    // ⚠️ #4961 改判：原 `matrix-must-finish-打包` 那枚标记已退场 ⇒ 改为反向断言
    expect(within(delivery).queryByTestId('matrix-must-finish-打包')).toBeNull()
    expect(within(delivery).getByTestId('matrix-row-打包')).not.toHaveTextContent('必完')
    // 单位（套）在**行尾元数据**列（改前那一列独立区块把 `/套` 拼进价格里；合并后归位到行尾）
    expect(within(delivery).getByTestId('matrix-row-打包')).toHaveTextContent('套')
    expect(within(delivery).getByTestId('matrix-row-打包')).toHaveTextContent('后道')
    expect(within(delivery).getByTestId('matrix-row-打包')).toHaveTextContent('套')
  })


  // ────────────────────── 反向护栏（三态语义不变 / 不静默取第一个） ──────────────────────

  it('反向护栏 B5：两态语义**不变** —— `未定价` ≠ `¥0.00`；`applicable` 退场后**恰两态**（`na` 不可达）', async () => {
    await renderOperations()

    // `质检` 布帘：价 null ⇒ 未定价（且**不含 ¥**）
    const unpriced = screen.getByTestId('operation-price-质检')
    expect(unpriced).toHaveAttribute('data-state', 'unpriced')
    expect(unpriced).toHaveTextContent('未定价')
    expect(unpriced).not.toHaveTextContent('¥')

    // `精裁` 布帘：真价 ¥0.40（真 0 元也必须显示成金额 —— 这里用非 0 真价钉住「有价」态）
    const priced = screen.getByTestId('operation-price-精裁')
    expect(priced).toHaveAttribute('data-state', 'priced')
    expect(priced).toHaveTextContent('¥0.40')

    // issue #4886：适用性**开关**已随部位退场；issue #4937 / #4951：`applicable` **字段**本身也退场
    // （读面恒 true、写面收到即 422）⇒ 页面不得再有任何适用性开关，且单价格**恰两态**
    expect(screen.queryByTestId(/^matrix-applicable-/)).toBeNull()
    expect(screen.queryByTestId(/^drawer-applicable-/)).toBeNull()
    // ⚠️ 排除容器 `operation-price-matrix`（它没有 `data-state`）：只遍历**单价格**节点
    for (const el of screen.getAllByTestId(/^operation-price-(?!matrix$)[^-]+$/)) {
      expect(['priced', 'unpriced']).toContain(el.getAttribute('data-state'))
    }
  })


  // ────────────────────── 🔴 硬要求：布料单定价入口 ──────────────────────




  // ────────────────────── §6 种子自愈（与模型无关） ──────────────────────

  it('§6-① 补套入口改成「**缺失即显示**」（幂等）：工序库**非空**但缺 `布料工序路线` ⇒ 入口仍可见（**红证**：改前 `!operationsReady` 才显示）', async () => {
    // 工序库**非空**（`CATALOG.total = 4`）∧ 缺 `布料工序路线`
    mockGetRoutings.mockReset().mockResolvedValue(ok(ROUTINGS_WITHOUT_FABRIC))
    await renderOperations()

    expect(screen.getByTestId('seed-templates')).toBeInTheDocument()
    // 标题要说清**为什么**出现（不是「工序库为空」）
    expect(screen.getByTestId('seed-templates')).toHaveTextContent('缺基础路线')
    expect(screen.getByTestId('seed-template-apply-curtain')).toBeInTheDocument()
  })

  it('§6-① 反向护栏：两条基础路线**齐**且工序库非空 ⇒ 补套入口**不显示**（不是常驻噪音）', async () => {
    mockGetRoutings.mockReset().mockResolvedValue(ok(ROUTINGS_WITH_BASE))
    await renderOperations()

    expect(screen.queryByTestId('seed-templates')).toBeNull()
  })


  it('B6-① **行为变更（如实登记）**：零价目行的工序**不再出现在这张表**；孤儿提示必须在场且报数（不许静默消失）', async () => {
    // 表的行**只来自价目读面**（用户裁定删掉【打包发货】那道「行不依赖矩阵格」的兜底区块）。
    // ⚠️ 这是**行为变更**：一格价目行都没有的工序**没有行、也没有定价入口** —— 如实登记，不粉饰。
    // 判据的承重点是「**不许静默**」：孤儿提示必须在场并报出数量（改前该提示只在缺失态被断言过）。
    const withoutCells = LAYER_CELLS.filter((c) => c.operation !== '外帘装袋')
    mockGetOperationPositions.setDefault(withoutCells)
    await renderOperations()

    expect(screen.queryByTestId('matrix-row-外帘装袋')).toBeNull()
    expect(screen.queryByTestId('operation-price-外帘装袋')).toBeNull()
    const hint = screen.getByTestId('matrix-orphan-hint')
    expect(hint).toHaveTextContent(/有 \d+ 道工序还没有价目行/)
    expect(hint).toHaveTextContent('下表看不到')
    // 其余工序**照旧**（撤掉一道不得让别行消失）
    for (const op of ['打包', '外帘打卷', '外帘发货', '精裁']) {
      expect(screen.getByTestId(`matrix-row-${op}`)).toBeInTheDocument()
    }
  })

  it('反向护栏 B7-①：**未定价 ≠ ¥0.00**（改前回落工序库行价会把「未定价」变成真 0 元 ⇒ 工人白干）', async () => {
    await renderOperations()
    const cell = screen.getByTestId('operation-price-外帘装袋')

    expect(cell).toHaveAttribute('data-state', 'unpriced')
    expect(cell).toHaveTextContent('未定价')
    expect(cell).not.toHaveTextContent('¥0.00')
    expect(cell).not.toHaveTextContent('¥')
  })

  it('反向护栏 B7-③：幸存行价为空 ⇒ 如实显示**未定价**；「不做」这一态已随 #4937/#4951 退场（不得回归）', async () => {
    await renderOperations()
    const cell = screen.getByTestId('operation-price-外帘打卷')

    // 2026-09-21 改判（配套 #4937 / #4951）：原第四态 `no_applicable_position` 与单价格第三态
    // `na`（「一格『做』都没有 ⇒ 不做」）的**输入已不存在**（`applicable` 恒 TRUE 且已退场）
    // ⇒ 判据改判为「零价 ⇒ **未定价**」，并用**反向**断言钉住「不做」不得出现 ——
    // 「未定价 ≠ ¥0.00」这条一字不放宽（`不做` 与 `¥` 都不得出现）。
    expect(cell).toHaveAttribute('data-state', 'unpriced')
    expect(cell).toHaveTextContent('未定价')
    expect(cell).not.toHaveTextContent('不做')
    expect(cell).not.toHaveTextContent('¥')
  })

  it('B6-② `管理▸` **在行上**（不是格上）；抽屉层「停用 / 删除」在 `manageVariants` 循环体**外**', async () => {
    await renderOperations()

    // 行上的入口（不是「格上的入口」）
    await userEvent.click(screen.getByTestId('matrix-manage-外帘装袋'))
    await waitFor(() => expect(screen.getByTestId('operations-manage-drawer')).toBeInTheDocument())

    // 抽屉空态（`manageVariants.length === 0`）⇒ 停用 / 删除**照样在**（**红证**：改前只有「关闭」）
    const disableBtn = screen.getByTestId('operations-manage-disable')
    const deleteBtn = screen.getByTestId('operations-manage-delete')
    expect(disableBtn).toBeInTheDocument()
    expect(deleteBtn).toBeInTheDocument()
    expect(screen.getByTestId('operations-manage-close')).toBeInTheDocument()
    // 空态**给出路**（不是一句死路文案）
    expect(screen.getByTestId('operations-manage-drawer')).not.toHaveTextContent('请核对各部位的适用性配置')

    // ⚠️ 「**在**」≠「**可点**」（issue #4721 P2-2）：两处按钮都带
    // `disabled={variantBusy || !manageOpEntry}` ⇒ 工序库读面查不到该逻辑名时它们**恒禁用**，
    // 而改前只断言 `toBeInTheDocument()` ⇒ 按钮变成装饰也全绿。判据 = **disabled 为假 + 点击真的发请求**。
    // 红证：把 `disabled` 改回 `true`（或让 `manageOpEntry` 为 null）⇒ 下面必红（实测见 PR 描述）。
    expect(disableBtn).not.toBeDisabled()
    expect(deleteBtn).not.toBeDisabled()
    await userEvent.click(disableBtn)
    await waitFor(() =>
      expect(mockUpdateOperation).toHaveBeenCalledWith('op-v54-04', { status: 'inactive' }),
    )
    // 删除：二次确认弹框里点确认 ⇒ **真的**走删除。
    // 🔴 #4913 合并后本行**有价目行**（改前该夹具把它摘空了）⇒ 走的是 #4692 的
    // **`detach-and-delete`** 路径（`{detachPositions: true}`，先摘格再软删）——
    // 这是**更强**的判据：它证明「有格」这条分支真的接到了按钮上（改前那条断言的是零格的普通软删分支）。
    await userEvent.click(deleteBtn)
    await waitFor(() => expect(screen.getByTestId('operations-manage-delete-modal')).toBeInTheDocument())
    await userEvent.click(screen.getByTestId('operations-manage-delete-confirm'))
    await waitFor(() =>
      expect(mockDeleteOperation).toHaveBeenCalledWith('op-v54-04', { detachPositions: true }),
    )
  })

  it('🔴 B6-③ **行为变更的锋利边界（如实登记）**：零价目行的工序在本页**连停用/删除入口都没有**', async () => {
    // 用户裁定删掉【打包发货】那道「行不依赖矩阵格」的兜底区块后，本页进抽屉的唯一入口 = 表行上的
    // `管理▸`；而表的行**只来自价目读面** ⇒ 零价目行的工序**在这张表里既不能定价、也不能停用/删除**
    // （改前它在【打包发货】层还有一行 + `管理▸`）。唯一出路 = 「新增工序」重建 / 补套行业模板。
    // ⚠️ 本断言把这条**边界**钉住，避免它退化成「没人知道为什么某道工序消失了」。
    const withoutCells = LAYER_CELLS.filter((c) => c.operation !== '外帘装袋')
    mockGetOperationPositions.setDefault(withoutCells)
    await renderOperations()

    expect(screen.queryByTestId('matrix-row-外帘装袋')).toBeNull()
    expect(screen.queryByTestId('matrix-manage-外帘装袋')).toBeNull()
    // 不静默：孤儿提示如实报数（这是这条边界**唯一**的可见面）
    expect(screen.getByTestId('matrix-orphan-hint')).toBeInTheDocument()
  })


  it('§6-② 就绪度②从「**数条数**」改成「**两条基础路线是否齐**」并**点名**（**红证**：改前 `工艺路线 2 条` 就显示「已完成」）', async () => {
    // 改前：`routeList.length = 1 > 0` 且无空壳 ⇒ **只数条数** ⇒ `data-state="done"`
    mockGetRoutings.mockReset().mockResolvedValue(ok(ROUTINGS_WITHOUT_FABRIC))
    await renderOperations()

    const step = screen.getByTestId('readiness-step-routings')
    // 改前：`工艺路线 2 条` + `data-state="done"`（只数条数 ⇒ 缺布料路线照样「已完成」）
    expect(step).toHaveAttribute('data-state', 'todo')
    expect(step).toHaveTextContent('基础路线 1/2 条')
    expect(step).toHaveTextContent('缺 布料工序路线')
    // 后果要说清（点名 + 为什么）
    expect(step).toHaveTextContent('窗帘单与布料单各自的主线')
  })


  it('§6-② 反向护栏：两条基础路线齐 ⇒ 就绪度② `done`（不误报）', async () => {
    mockGetRoutings.mockReset().mockResolvedValue(ok(ROUTINGS_WITH_BASE))
    await renderOperations()

    const step = screen.getByTestId('readiness-step-routings')
    expect(step).toHaveAttribute('data-state', 'done')
    expect(step).toHaveTextContent('基础路线 2/2 条')
    expect(step).not.toHaveTextContent('缺 ')
  })
})
