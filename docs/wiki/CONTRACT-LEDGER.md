# 并行开发契约清单（Contract Ledger）

> 目的：多任务（尤其多 Agent 并行）开发前，先锁定跨模块共享的**契约事实**，
> 避免各任务各写各的字段名/状态枚举/端点签名，改完再逐项核对。
> 用法：并行开工前填好本表 → 各任务读表并承诺遵守 → 交付时跑 `contract-check.sh` 验证。

---

## 一、状态枚举（单一事实源，三端必须一致）

| 业务对象 | 合法值 | 注释/来源 |
|---|---|---|
| 订单状态（DB） | `pending / confirmed / producing / shipped / completed / cancelled` | `OrderService.java` 状态机；**生产中是 producing 不是 processing** |
| 订单状态（前端展示） | `pending_payment / pending_shipment / shipped / completed / closed / refund` | `types/index.ts` `BackendToFrontendStatus` 映射 |
| 售后工单状态 | `pending / processing / rejected / resolved / closed` | `AfterSalesTicketService.java` |
| 商品状态 | `draft / on_sale / off_sale / under_review` | `ProductService.java` `STATUS_TRANSITIONS`（4 值状态机，已核实=后端真值）；前端 `types/index.ts ProductStatus` 同 4 值。**Agent 侧只放开 `on_sale / off_sale`（2 值）—— 有意的权限边界，非能力缺口、不扩枚举，见第九节 #3686** |
| 售后工单来源 | `customer / agent / merchant` | `AfterSalesTicketService.SOURCE_*`（`VALID_SOURCES` 白名单）。语义 = 工单**真实来源**：customer=顾客发起 / agent=AI 建单 / merchant=人工建单。写入路径见第八节（#3686） |
| 加工单状态 | `generated / issued / in_processing / completed / cancelled` | `ProcessingOrderService.java` 状态机（issue #3340，1 订单 1 加工单） |

## 二、关键字段名（前后端 + Agent 三端一致）

| 字段 | 后端 Java | 前端 TS | Agent Python | 备注 |
|---|---|---|---|---|
| 优惠金额 | `discountAmount`（Order/OrderCreateRequest/OrderDetailResponse） | `discountAmount` | — | V14 迁移 |
| 退款金额 | `refundAmount` + `refundAt` | `refundAmount`/`refundAt` | `refund_amount`（API 入参蛇形） | 退款 API body 用 `refund_reason`/`refund_amount` |
| 物流公司 | `logisticsCompany` | `logisticsCompany` | `logisticsCompany`（读响应） | 勿用 company |
| 运单号 | `trackingNo` | `trackingNo` | `trackingNumber` | Agent 发 update_logistics 用 trackingNumber |
| 下单用户ID | `userId`（Order/OrderCreateRequest/AgentOrderCreateRequest，来自 X-User-Id 透传） | — | `context.user_id`（customer_order_query 强制注入） | **C 端数据隔离字段**（V20260901）；B 端查询用 B 端 order_query，C 端用小布专用 customer_order_query |
| 加工单号 | `processingOrderNo` | `processingOrderNo` | `processingOrderNo`（读响应） | 生成格式 `JG-YYYYMMDD-XXXX`，DB 唯一（issue #3340） |
| 加工单状态 | `status`（generated/issued/in_processing/completed/cancelled） | `status`（同枚举） | `status`（同枚举） | 中文映射 `PO_STATUS_TEXT`（processing_order_query.py） |
| **路线来源**（issue #4308，V60；**`route_key` 语义见 2026-09-19 订正**） | `routeKey` / `routeRequestedKey` / `routeSource`（`ProcessingOrder` / `ProcessingOrderResponse`；DB 列 `route_key` / `route_requested_key` / `route_source`） | `route_key` / `route_requested_key` / `route_source`（加工单详情响应；前端 `lib/route-source.ts` 单点映射文案） | — | 🔴 **`route_key` = 实际使用的那条路线的身份 = 路线模板名**（如 `窗帘工序路线（默认）`）——**不再是** `部位×工艺`（issue #4459 = 母单 #4423 的 P2b 订正）。理由：新结构里路线 = **具名模板**（工艺已降为 `production_route_rules` 的触发键，不再参与选路），且验收判据 6 要求「默认路线改为另一条 ⇒ 无信号订单**实际使用键随之变**」——若 `route_key` 仍是派生键，改默认路线时它**不会变**，判据不成立。**`route_requested_key` 形态未变** = 派生出来想用的键（仍是 `部位×工艺`；两维全不命中时 null）⇒ `missing_route` 的提示语义不变。`route_source` **五态** `direct（订单直读）/ derived / partial（补信号）/ missing_route（建路线）/ default（补信号）`（`direct` 由 issue #4354 引入，本行原写「四态」已订正）；多部位订单取最需关注的一条（`default` > `missing_route` > `partial` > `derived`） |
| **订单明细数量** | `quantity` **`BigDecimal`**（OrderCreateRequest.OrderItemRequest / AgentOrderCreateRequest.AgentOrderItem / OrderItem / OrderDetailResponse / OrderListResponse）——DB `order_items.quantity DECIMAL(10,2)`（V45） | `quantity: number`（decimal 安全） | `items[].quantity` JSON Schema `"type": "number"`（可为小数） | **口径按计价方式**：per_meter=米数 / per_set=1 / per_area=宽×高（㎡）；**可为小数**（如 2.8×3=8.4 ㎡），三端一律**不得取整/截断**（issue #3666，原 Integer/INTEGER 会少收钱）。JSON 传整数 3 仍反序列化为 BigDecimal("3") |
| **下单行要素**（issue #4362，S1，V63） | `OrderItem` 的 11 个字段：`curtainType` / `craft` / `openCount` / `cuttingMode` / `isShaped` / `fullness` / `fullnessActual` / `pleatSpacing` / `pleatCount` / `hasPattern` / `corner`——DB 列 `curtain_type` / `craft` / `open_count` / `cutting_mode` / `is_shaped` / `fullness` / `fullness_actual` / `pleat_spacing` / `pleat_count` / `has_pattern` / `corner` | —（`OrderDetailResponse.OrderItemResponse` **未**透出，见下方「未交付」注） | 写入口 = `items[i].processing_info` 顶层键（camelCase；算料输出键 `pleat_count`/`fullness`/`fullness_actual` 保持 snake_case）。C 端小布按清单 id（snake_case：`curtain_type`/`open_count`/`is_shaped`/`pleat_spacing`/`has_pattern`/`window_type`）采集时由 `curtain_checklist.to_craft_spec` 归一 | **全部 nullable、不设必填校验**（用户裁定 2026-09-19「部位不是必填的」）⇒ 缺键就是缺，**不造值**。单一映射点 = Java `OrderLineCraftFields`（写面 `materialize` / 读面 `toSnapshotKeys`）+ Python `curtain_checklist.to_craft_spec`。⚠️ `craft` **单值**；「四爪钩/四叉钩」是**加工项（配件）不是工艺**（#4365 裁定）⇒ 信号映射层已指向主线工艺（V63） |
| **信号映射：四爪钩/四叉钩**（issue #4362 阶段 1 ②，V63；**迁移状态见 2026-09-19 P2b 订正**） | `production_route_signals` 的 `sig-v60-06/07` 两行 `craft`：`四爪钩` → `韩褶`（= `ProcessingOrderService.DEFAULT_CRAFT` 的**种子**取值；运行时缺 `craft` 取**该租户默认工艺** `production_crafts.is_default`，issue #4459 起） | — | — | **不再是独立路线键**。⚠️ 原注「`production_routings` 的 `布帘×四爪钩` 路线保留、阶段 3 才迁移」**已作废**：P2b（issue #4459）起消费路径读 `production_route_templates`，旧 `production_routings` 的活跃行由 **V73 软删**（表未 DROP，可回滚）。「穿钩-*」条件工序属阶段 2/3（工序名/单价待客户确认，见 #4261） |
| **客户默认收货信息**（issue #4419，V70） | `defaultReceiverName` / `defaultReceiverPhone` / `defaultReceiverAddress`（`CustomerProfile`；DB 列 `default_receiver_name` VARCHAR(100) / `default_receiver_phone` VARCHAR(20) / `default_receiver_address` TEXT） | `defaultReceiverName` / `defaultReceiverPhone` / `defaultReceiverAddress`（`types/index.ts` 的 `Customer` / `CustomerProfile`） | 同名字段（`customer_manage` 的 `WRITABLE_FIELDS`，与 `CustomerService.updateCustomer` 非空拷贝白名单同集合 —— 由 `test_tool_field_name_contract.py` 强制） | **单个**默认地址（用户 2026-09-19 裁定，不做多地址簿）；地址为**单字段文本**（与 `orders.customer_address` 同口径）。写路径 = `PUT /api/admin/customers/{id}` 非空拷贝（空白/缺省**不覆盖**，**无清空语义**）；消费 = 新增订单选客户**逐字带出**（优先于 `region*` 拼接）/ 发货页带出常用物流（反查按 `phone` **或** `defaultReceiverPhone` 精确命中，#4436）。⚠️ 客户列表 `keyword` 搜索覆盖**三列**：`wechat_nickname` / `phone` / `default_receiver_phone`（#4436 起） |
| **算料公式配置键**（issue #4528 = 包 E，V80） | 列名 = 配置键（逐字同名）：`per_fold_single` / `per_fold_mixed_times` / `margin_single` / `margin_multi` / `min_fullness` / `tiers` / `default_formula` / `side_margin` / `meters_rounding_step`（实体 `CraftCalcConfig`，表 `craft_calc_configs`） | `CraftCalcConfig`（`types/index.ts`；`GET|PUT /api/admin/production/craft-calc-config` 的 `data.config`） | 算料端点入参 `config`（`internal.py::CraftCalcRequest`；键集 = `curtain_calc.DEFAULT_CRAFT_CALC_CONFIG`） | 🔴 **单一真值 = 算料引擎**（`curtain_calc.py`）：Java/TS **不得**持有默认值 —— 无配置行时后端从 `GET /api/internal/production/craft-calc-config` 取引擎默认值 + `source='default'`。跨源逐键守卫 = `tests/unit_ci_workflows/test_craft_calc_config_contract.py`（引擎键集 ↔ V80 列 ↔ schema.sql 列 ↔ 实体字段 ↔ `CONFIG_KEYS`）。⚠️ 设计文档 §4.2 的提案键 `default_fabric_width` **实现里不存在**（以实现为准，登记差异） |
| **物流类型**（issue #3984 引入，issue #4419 补上 admin-web 写面） | `logisticsType`（`order_logistics.logistics_type`；客户常用值在 `customer_profiles.default_logistics_type`） | `logisticsType`（`LogisticsFormData` → `buildLogisticsPayload` → `PUT /orders/{id}/logistics`） | 读响应 `logistics_type`（`logistics_track.py`，缺省回退 `express`） | `express` 快递 / `logistics` 物流专线。⚠️ **修前 admin-web 从不下发该字段** ⇒ 商家端发货恒落列默认 `express`，V47 的区分形同虚设（#4419 补） |

## 三、端点签名（勿自造）

| 操作 | 端点 | Body 关键字段 |
|---|---|---|
| 订单退款 | `PUT /api/admin/orders/{id}/refund` | `refund_reason`、`refund_amount`（缺省=全额） |
| Agent 统一改单 | `PATCH /api/admin/agent/orders/{id}` | action ∈ {update_status, update_logistics, confirm_payment, cancel, refund} |
| Agent 单 SKU 改价 | `PATCH /api/admin/agent/products/{productId}/skus/{skuId}` | `price`（≥0） |
| Agent 创建商品 | `POST /api/admin/agent/products` | `basePrice`（前端适配层 price→basePrice） |
| **C 端我的订单** | `GET /api/admin/agent/orders/mine?page&size&status` | **强制按 X-User-Id 过滤 + 手机号兜底**：`user_id=本人 OR (user_id IS NULL AND customer_phone=本人已绑定手机号)`（商户代录/历史订单据此归属；未绑手机号则仅 user_id 直配） |
| **小程序绑定手机号** | `POST /api/auth/mini/bind-phone` body `{code}`（JWT 认证） | code = `open-type="getPhoneNumber"` 授权动态令牌；后端换号 → 写 `users.phone` → 回填名下 `user_id IS NULL AND customer_phone=该号` 的订单（V23 运行时化） |
| **B 端员工小程序登录** | `POST /api/auth/bmini/login` body `{code, phoneCode?}`（issue #2977） | code = wx.login() 凭证；phoneCode = `open-type="getPhoneNumber"` 授权动态令牌（**首次必传**）。语义与 C 端相反：openid 无绑定 → 换号跨租户匹配员工（role∉customer/agent）→ 绑定 `user_identities(bmini_app + appId=wechat.bmini.appid)` → 签发含 permissions 的员工 JWT；**匹配不到即拒绝、绝不自动建号**（BM-003） |
| **加工单生成** | `POST /api/admin/processing-orders/generate` body `{orderIds:[]}`（issue #3340） | 仅已确认且含加工项订单；幂等（已有活跃加工单拒绝）；联动订单 confirmed→producing；权限 `processing:update` |
| **加工单列表/详情** | `GET /api/admin/processing-orders?keyword&status` / `GET /api/admin/processing-orders/{id}` | id 可为加工单号/订单号/UUID；租户隔离 fail-closed；权限 `processing:view` |
| **加工单状态更新** | `PATCH /api/admin/processing-orders/{id}` body `{action, processor?, expectedDeliveryDate?, reason?}` | action ∈ {issue, start, complete, cancel}；cancel 必填 reason；issued+ 取消需人工确认；completed 冻结；权限 `processing:update` |
| **加工单-订单联动守卫** | 订单发货守卫 + 取消联动（`OrderService`） | 含加工项订单须有 completed 加工单才能 shipped；订单取消时加工单 generated→自动作废、issued+→拦截 |
| **工艺路线写面**（issue #4308；**body 形态见 2026-09-19 P2b 订正**） | `POST /api/admin/production/routings` body `{name, mainline?, positions?, is_default?, status?}`（`mainline` 可缺省 = 初版空主线；`positions` 缺省 = 适用三部位；`is_default` 缺省 = false） | 新建**具名路线模板**（落 `production_route_templates`，issue #4459 起；旧 `{curtain_type, craft, operations}` 形态已退场）；同租户活跃路线重名（含停用行）⇒ 409；`is_default=true` ⇒ 同事务把既有默认降级（恰一条默认的不变式）；响应与 `GET /routings` 单项同构 `{id, name, is_default, positions, mainline, status}`；权限 `processing:manage` |
| **工艺路线改主线 / 删路线**（issue #4308；**body 与端点见 2026-09-19 P2b 订正**） | `PUT /api/admin/production/routings/{id}` body `{name?, is_default?, mainline?, positions?, status?}`（**部分更新**：只写出现的字段）；`DELETE /api/admin/production/routings/{id}` | **改名只改 `name`**（不给 `mainline` 就不动序列）；`mainline` = **有序逻辑工序名数组**（与 `OPERATION_LOGICAL_NAMES` 值域一致；也接受库内变体名）；护栏：空主线 / 工序不在库 / **重复工序（判重键 = `normalizeOperationName` 归一后的逻辑名**，issue #4520 —— 故 `精裁` 与 `精裁-布` 视为**同一道工序**，各排一次即 422；按原始字符串判重会放行 ⇒ 实例化出两道 ⇒ **工人按两遍单价拿钱**）/ 无必完工序 / `is_default:false` ⇒ 422（零默认 ⇒ 建单全 fail-closed）/ 停用默认 ⇒ 422 / 删默认 ⇒ 422 / 删最后一条 ⇒ 422；失败 = **422 + `error.details:[{field,message}]` 逐条理由**；序列真实变更落 `production_routing_versions`；DELETE = 软删（`deleted=1`）；权限 `processing:manage` |
| **信号映射写面**（issue #4308） | `GET|POST /api/admin/production/route-signals` + `PUT|DELETE /route-signals/{id}` | GET 响应 `{total, signals:[{id, signal, curtain_type, craft, priority, status}]}`；POST/PUT body `{signal, curtain_type?, craft?, priority?, status?}`（两维至少给一个）；DELETE = 软删（`deleted=1`）；权限 `processing:manage` |
| **新增工序**（issue #4308） | `POST /api/admin/production/operations` body `{name, group_name?, unit?, unit_price, position?, is_must_finish?, is_start_marker?, sort_order?}` | 落 `production_operations` + **同事务写单价版本账首行**；同名（含停用行）⇒ 409；缺 name/缺 unit_price/负单价 ⇒ 422；权限 `processing:manage` |
| **路线缺口**（issue #4308） | `GET /api/admin/production/routing-gaps` | `{unrouted_operations:[{name, group_name, unit, unit_price, pending_confirmation, note}], unrouted_operation_total, pending_confirmation_total, signal_keys_without_route:[{curtain_type, craft, route_key, signal}]}`；`pending_confirmation=true` = **有意挂起等客户输入**（issue #4261 提问清单），不是系统漏了 |
| **部位价目矩阵**（issue #4500 = 母单 #4423 的 P2c，V71 新表） | `GET /api/admin/production/operation-positions`（**只读**） | `data = [{operation, position, unit_price, applicable}]` —— **30 逻辑工序 × 4 部位 = 120 格**（第 4 个部位 = `布料`，issue #4529）（`operation` = `production_operation_positions.logical_name`，**不是** `production_operations.name` 的旧名 `精裁-布`）。**顺序口径 `(operation, position)`**（Java 侧显式比较器，不依赖 DB collation）。`applicable=false` = 该部位**明确不做**（`unit_price` 可为 `null` = 不报价）—— 与「没定价」（`applicable=true` + `unit_price IS NULL`）**可区分**。过滤只有 租户 + `deleted=0` + `status='active'`（**无值过滤** ⇒ 120 格整份呈现）。权限 `processing:manage`；写面留 v1b |
| **统一规则区**（issue #4500 = 母单 #4423 的 P2c，V71 新表；issue #4567 追加 `customer_unit_price`；issue #4616 起 `trigger_kind` 扩到三档） | `GET /api/admin/production/route-rules`（**只读**） | `data = [{id, trigger_kind, trigger_value, position, action, operation, after_operation, priority, status, customer_unit_price}]` —— **26 条** = 工艺变体 10（`trigger_kind='craft'`）+ 特殊选项 16（`'option'`），与 `routing.py::ROUTE_RULES` 同源。**顺序口径 `(priority, id)`**（`priority` 升序 = 规则生效顺序；同档按 `id` 定序 ⇒ 可预测）。`customer_unit_price`（V77，**元/套**）只对 `trigger_kind='option'` 有意义（选项按**套**收费）；`null` = **未定价**（**≠ 0 元**，前端不得渲染成 `¥0.00`），非 `option` 行一律 `null`（服务层不取价、不回退）。**只含路线编排档**（`action ∈ {insert, remove}`）：V72 从旧 `production_option_factors` 搬来的 `action='factor'`（计件系数档）**不在本端点**（P3 规则区不呈现系数，形状里也没有 `factor` 键）。数据源 = `production_route_rules`（**新表**；旧 `production_option_routings` / `production_option_factors` 已由 P2b 软删，**绝不读**）。权限 `processing:manage`；写面留 v1b |
| **条件工序规则创建**（issue #4616；端点本体建立于 issue #4570） | `POST /api/admin/production/route-rules`（body `{trigger_kind?, trigger_value, action?, operation, after_operation?, position?, priority?, customer_unit_price?}`） | **通用化创建**（**不新增创建端点**）：`trigger_kind` ∈ **闭词表** `craft` / `option` / `processing_item`（与 V71 的 CHECK 同口径；**缺省 = `option`** = 老调用方/老 bundle 行为一字不变 —— 反向护栏；`shaped` 是表结构预留、无种子行 ⇒ **422**）。`trigger_value` **必须存在于对应词表**（`craft` ⇒ 活跃 `production_crafts`；`processing_item` ⇒ 活跃 `processing_items`，触发键 = 订单行 `processingInfo.processingItems[].name` **精确相等**；`option` ⇒ 可新建，**无词表**）⇒ 不存在/已停用 ⇒ **422 + `error.details:[{field,message}]` 逐条、一次报全**。`action` ∈ `insert` / `remove`（缺省 `insert`；`remove` 不接受锚点）。`customer_unit_price`（元/套）**只允许 `trigger_kind='option'`**（craft / 加工项行必须为空，否则 422）—— 「两套账不互读」的既有边界。`operation` / `after_operation` = **逻辑工序名**（必须在该租户工序库里存在，复用同一份 `logicalOperationExists`）。重复 = `kind + 触发值 + 动作 + 目标工序`（对齐 DB 唯一索引）⇒ **409**。权限 `processing:manage`。⚠️ 一句话摘要由「目标工序不在工序库里」改为「条件工序规则校验未通过」（**逐条理由一字未动**） |
| **规则触发值取值域**（issue #4616，新端点） | `GET /api/admin/production/route-rule-options`（**只读**） | `data = {crafts:[…], processing_items:[…]}`：`crafts` = 本租户活跃**工艺词表**（`production_crafts`，过滤 = 租户 + `deleted=0` + `status='active'`，**默认工艺优先、其余按名升序** —— 复用 `ProductionOperationQueryService.activeCrafts` 的既有口径，**不另写一份排序**；名字去重保序）；`processing_items` = 本租户活跃**加工项目录**（`processing_items`，同三条件 + 按 `name` 升序，名字去重保序）。**服务端已排好序 ⇒ 前端不重排**。存在的理由：工艺词表此前**没有任何读端点**，而规则创建弹窗要求「触发值**按类型从对应词表取、不手输**」—— 手输一个词表外的名字 = 建一条**永远不命中**的规则（商家以为配了、加工单上却没有）。**特殊选项名不在本端点**：它按现状**可新建**（没有第二份词表，后端也不校验）。**不含任何工序名**（无变体名/逻辑名泄漏）。权限 `processing:manage` |
| **算料公式配置读面**（issue #4528 = 包 E，V80 新表） | `GET /api/admin/production/craft-calc-config` | `data = {source, config}`：`source='stored'`（本租户有配置行）/ `'default'`（**无行** ⇒ `config` = **算料引擎默认值**，取自 ai-agent 内部端点）。`config` 键集 = 引擎 `DEFAULT_CRAFT_CALC_CONFIG`（9 键，逐字同名）。⚠️ 缺行时该端点**依赖 ai-agent 可达**（取不到默认值 ⇒ 422 fail-closed，**不凭空造一份默认值**）。权限 `processing:manage` |
| **算料公式配置写面**（issue #4528 = 包 E） | `PUT /api/admin/production/craft-calc-config` body = 配置键的**扁平**映射（与读面 `data.config` 同形、与算料端点 `config` 入参同形） | **upsert + 全量替换**（缺键/未知键 ⇒ 422 逐键报；护栏：数值 > 0 / `per_fold_mixed_times` 非空且键为正整数、值 > 0 / `tiers` 非空且每档 `fullness ≥ min_fullness` / `min_fullness ≥ 1.5`（行业红线，可配不可关）/ `default_formula ∈ {pleat, fullness}`）；失败 = **422 + `error.details:[{field,message}]` 逐条理由**，**绝不静默回退默认值**；权限 `processing:manage` |
| **特殊选项对客单价写面**（issue #4567） | `PUT /api/admin/production/route-rules/{id}/customer-unit-price`（body `{customer_unit_price}`，**元/套**） | **只写** `production_route_rules.customer_unit_price` 这一列（+`updated_at`），**不碰** `factor`（计件系数）—— 对客售价账与工人计件账**两套账不互读**（设计 §4.1）。护栏（**422 + `error.details:[{field,message}]` 逐条理由**）：行不存在 / 非本租户 / 已软删 ⇒ **404**；`trigger_kind != 'option'` ⇒ **422**（只有特殊选项按套计价，工艺变体不按套收费）；价非数值 / 负数 / 超过两位小数（`NUMERIC(12,2)`，**不静默四舍五入**）⇒ **422**；`null` / 空串 ⇒ **允许** = 显式改回**未定价**（语义是「还没定价」，**不是** 0 元）。响应 = 规则展示形态的单项。权限 `processing:manage` |
| **算料引擎默认配置**（issue #4528 = 包 E，内部） | `GET /api/internal/production/craft-calc-config`（ai-agent，Service Token） | `data = {config}`：键集 == `curtain_calc.DEFAULT_CRAFT_CALC_CONFIG`（**恰好**）。存在的理由：默认值唯一来源是引擎 —— Java 侧抄一份 = 第二份会漂的默认值。消费方 = `CraftCalcClient.defaultConfig()`（缺配置行的租户读面） |
| **C 端我的售后** | `GET /api/admin/agent/after-sales/mine?page&size` | **强制按 X-User-Id 反查用户订单 → 只返回这些订单上的工单**（数据隔离强制点；勿用 `GET /api/admin/after-sales?customerId=`——该参数不存在且工单 customer_id 存的是客户姓名） |
| **C 端我的物流** | `GET /api/admin/agent/orders/mine?status=shipped` → 逐单 `GET /api/admin/orders/{id}` 取 `logistics` | 小布专用 `customer_logistics_track`：只查本人**已发货(在途)**订单；**两端一律拒绝用户提供快递单号直查**（运单号仅由系统从订单详情读取） |
| **转人工建人工会话** | `POST /api/admin/agent-sessions`（ai-agent human_handoff 调用） | 字段 `aiSessionId/customerId/reason` + **GB-01 新增** `aiContextSummary`（≤500 字）+ `aiContextMessages`（≤20 条 `{role: user\|assistant, content, contentType?, createdAt?}`，每条 ≤500 字）；管理端详情 `GET /api/admin/agent-sessions/{id}` 响应含 `aiContextSummary`/`aiContext`；**顾客端** `GET /api/customer/agent-sessions/by-ai/{aiSessionId}` **不含** aiContext 且过滤 isInternal 消息（GB/T 47746-2026 对齐，issue #2776） |

## 四、跨模块联动约定（改一处必须检查另一处）

| 联动 | 规则 | 违反后果 |
|---|---|---|
| 售后工单完结 → 订单 | resolved + refund/return 类 → 订单累加 refundAmount、写退款流水 | 退款不入账 |
| 订单确认/取消 → 库存 | 确认支付扣库存；**仅订单取消（confirmed/producing → cancelled）恢复库存**（refundOrder 不恢复库存） | 超卖/库存虚增 |
| 售后工单完结 → 库存（issue #2991） | refund/return 工单 resolved：**按商品「退货回补库存」开关 `products.allow_return_restock`（默认 false）决定**——窗帘行业定制退货不可再售，默认不回补；订单**全部**商品开启才整单回补（复用 `OrderService.restoreStockForReturn`）；任一商品关闭则整单跳过（宁可少回补不过回补） | 定制退货误入可售库存 → 假可售/误导销售 |
| 订单 → 财务流水 | confirmPayment 记 income；cancel/refund 记 refund | 对账不平 |
| 下单 → 客户建档 | 老客户只刷新 lastActiveAt（不累计） | 画像失真（已知，勿重复实现） |
| C 端查物流 | `customer_logistics_track`（仅本人已发货订单，拒绝快递单号直查）↔ B 端 `logistics_track`（仅 order_id，拒绝 tracking_number） | 用户/LLM 传快递单号直查必须拒绝；快递单号只能由系统从订单详情读取后内部查询轨迹 |

## 五、验收前必跑

```bash
# 1. 本地 gate 预检（QA Growth Gate 同 CI 规则）
./verify-all.sh gate

# 2. 三端字段名 grep 对齐（改某字段时）
grep -rn "字段名" backend/admin-api/src frontend/admin-web/src backend/ai-agent-service/app | grep -v test

# 3. case_ids（新增/修改测试必带）
# 每个测试文件头部: # case_ids: OR-001, OR-002  （按域：OR 订单/AS 售后/PR 商品/FN 财务/CU 客户/DA 看板）
```

## 六、加工项计价方式契约（issue #3005 回滚 #2986，2026-09-07）

行业加工费按米计价、辅料（罗马圈/四爪钩等）含在按米单价中 → 加工项计价方式仅 `per_meter / per_set / fixed / per_area`，
**per_piece 与「每米数量」密度（per_meter_quantity / custom_per_meter_quantity）已全链路移除**（schema V34 回滚迁移 + DTO/TS/Python 删除）。

| 字段 | 后端 Java | 前端 TS | Agent Python | 备注 |
|---|---|---|---|---|
| 计价方式 | `pricingMethod`（ProcessingItem/Response/Create/Update，枚举 per_meter/per_set/fixed/per_area） | `PricingMethod` 同枚举 | `pricing_method`（tool 透传） | per_piece 创建/更新被 validatePricingMethod 拒绝 |
| 数量规则 | per_meter → 数量=面料米数；per_set/fixed → 1；per_area → 面积 | 同（deriveProcessingQty） | 同（order prompt） | B 端下单展示「名称+数量+金额」供对账，无数量输入框 |
| 价格计算入参 | `quantity`（PriceCalculateRequest，per_meter 传面料米数） | — | `quantity` | fabricMeters 字段已删除，无密度推导 |
| 数量类型（issue #3666） | `BigDecimal`（ProcessingItem/订单明细/订单列表/详情 DTO） | `number` | `number` | 全部为十进制、**禁止取整**；服务端 `OrderService.extractProcessingItems()` 走 `toBigDecimal()`（旧 `toInteger()` 把 per_area 8.4 截断成 8 → 列表/详情加工费与外层落库金额自相矛盾） |

## 七、LLM WIKI 知识板块契约（issue #3051，2026-09-08 起）

知识单元从 RAG chunk 升级为**知识卡片**（knowledge_cards）+ 提炼候选（knowledge_candidates）。
检索用结构化过滤 + 关键词匹配，**不引入向量库**（决策 D1 维持）。设计单一事实源：`docs/design/knowledge-wiki-design.md`。

| 业务对象 | 合法值 | 三端一致要求 |
|---|---|---|
| 知识卡片状态 | `draft / pending_review / published / archived` | Java `KnowledgeCard.status` = TS `KnowledgeCardStatus` = Agent 检索过滤条件（仅 published） |
| 候选状态 | `pending / adopted / edited / rejected` | Java `KnowledgeCandidate.status` = TS 同 |
| 知识卡片来源 | `template / conversation / document / manual` | Java `sourceType` = TS `sourceType` = Agent 展示徽标；商品派生（product）/加工项派生（config）已移除且存量数据已清理（#3083/#3085/#3087） |
| 候选来源 | `conversation / document / product / config` | 同上 |
| 知识卡片分类 | `faq / product / measure / aftersale / config` | 前后端同枚举 |
| 知识卡片检索端点 | `GET /api/admin/knowledge/cards/search?query=&productId=&category=` | 仅返回本租户 `published` 知识卡片（显式 eq tenant_id + status） |
| 会话提炼（自动触发） | 人工客服会话结束（status→ended）事务提交后异步触发（SessionEndedEvent + @Async AFTER_COMMIT，#3090） | 提炼源=已结束且 employeeId 非空（转人工标记）的会话；纯 AI 会话不提炼；防重复（该会话已有 conversation 候选跳过）；POST /api/admin/knowledge/distill/conversations?hours=24 保留为管理端对账入口；ai-agent 内部 POST /internal/knowledge/distill 负责 LLM 提炼 |
| 模板目录 | `GET /api/admin/knowledge/templates` | 平台预置模板（templateId/industry/name/version/entryCount，布艺 curtain 26 条（仅行业通用知识，商品级词条已移除 #3095）） |
| 模板套用 | `POST /api/admin/knowledge/templates/{templateId}/apply` | 复制为租户卡片（sourceType=template/sourceRef=templateId/status=published），按 (tenant_id,title) 去重，返回 {created,skipped} |
| 候选队列 | `GET /api/admin/knowledge/candidates` + `POST /{id}/adopt` / `adopt-edited` / `reject` | 待确认队列闭环：候选读+写路径齐全；采纳转卡片 published（来源继承），拒绝记 status_note |
| 待确认计数 | `GET /api/admin/knowledge/candidates/pending-count` | 前端红点 |

## 八、售后工单来源写入契约（issue #3686，2026-09-14）

`after_sales_tickets.source` = 工单**真实来源**（`customer` 顾客发起 / `agent` AI 建单 /
`merchant` 人工建单）。此前服务端在 `AfterSalesTicketService.createTicket` 内**无条件**
`setSource("agent")` ⇒ C 端小布顾客工单被误标 agent、DDL `DEFAULT 'customer'` 成死默认。

| 建单入口 | 端点 | 来源取值来源 | 落库值 |
|---|---|---|---|
| admin-web 后台表单 | `POST /api/admin/after-sales` | 该 URL 唯一调用方是 admin-web 工单页（`api.ts` ← `after-sales/page.tsx`）⇒ 绑定常量 | `merchant` |
| 小布（C 端）`aftersale_create` | `POST /api/admin/agent/after-sales` | ai-agent 侧 `ToolContext.ticket_source` = `customer`（role 折叠） | `customer` |
| 米宝（B 端）`after_sales_manage` | 同上 | 同上 = `agent` | `agent` |
| 转人工 `human_handoff` | 同上 | 同上；该工具 `check_permission` 只放 C 端角色 ⇒ 恒 `customer` | `customer` |
| 评测 seed SQL（`tests/agent_eval/fixtures/*.sql`） | 直插 | 显式列出 `source` 列 | 由 seed 指定 |

**服务端无法自行判定 Agent 侧来源**（3 个工具打同一 URL、同一组 header、均 Service Token
认证 ⇒ `getCurrentOperator()` 恒 `internal-service`、body 无 `source`）⇒ 由内部调用方经
**请求头 `X-Agent-Client`** 声明，服务端只接受白名单值，缺省/未知一律回退 `agent`
（= 既有行为，向后兼容）。**不放 body**：来源不由客户端 payload 决定（#3605 取舍，且避开
payload 契约门禁射程）。

DDL `source VARCHAR(32) DEFAULT 'customer'` 现状：服务端各路径均显式写值 ⇒ 该默认**不可达**
（死默认），保留作防御性兜底（原始 SQL 插单）并已加注释；`DROP DEFAULT` 会触发 Flyway
迁移，不划算 —— 如确需清理另开 issue。

## 九、有意的三端差异（登记真实意图，避免被当成缺口"补齐"）

| 差异 | 值域 | 裁定与理由 |
|---|---|---|
| 商品状态（agent `product_manage`） | 后端/前端 4 值 `draft/on_sale/off_sale/under_review`；**Agent 2 值 `on_sale/off_sale`** | **有意的权限边界（#3686 裁定，不扩枚举）**：Agent 只负责上下架；新建草稿、`draft→under_review→on_sale` 送审是 admin-web 后台的商品运营流程（需人工编辑资料并承担审核语义）。给 Agent 放开这两值 = 对话可跳过审核门禁（越权），违反最小权限。真值同时写在 `product_manage.py` 的 `status` 字段 description 内。**需要 Agent 送审时必须先补权限设计 + 审核责任归属，再改枚举** |

## 十、工具层权限码与失败映射契约（issue #4106）

`[ai-chat.permission-layers]` 契约（「角色检查 + 细粒度权限」）此前**只是声明**：
38 个工具类里只有 1 个声明了 `required_permissions`，其余 37 个纯靠手写
`allowed_roles` 角色码白名单 ⇒ 与 admin-api 权限目录漂移后**持有权限码的员工被工具判
「权限不足」**（假拒绝）。本单把实现改成契约说的样子，并把失败映射收成一个入口。

### 10.1 两层权限的真值（`app/tools/base.py::BaseTool.check_permission`）

| 层 | 何时生效 | 判据 | 单一真值源 |
|---|---|---|---|
| 细粒度层（**权威**） | 工具声明了 `required_permissions` | JWT `permissions` claim（`*` = 全权限；`admin` 恒为 `["*"]`） | admin-api 权限目录（18 码） |
| C 端硬闸（两端隔离不变式） | 同上 | `context.role ∈ CUSTOMER_ONLY_ROLES` ⇒ 一律拒绝（生产不可达，纵深防御） | `app/tools/base.py::CUSTOMER_ONLY_ROLES` |
| 角色层（粗筛） | 工具**未**声明权限码 | `allowed_roles` | 各工具类体（C 端工具 / 无目录码工具） |

**声明了权限码的工具不得再声明 `allowed_roles`**（它已不生效 = 假门禁），由
`tests/test_tool_permission_codes.py` 静态锁定。

工具 → 权限码映射（端点取各 controller 的 `@RequirePermission`；**写操作取写码**，
避免只读持有者拿到写权限）：

| 工具 | 权限码 | 出处 |
|---|---|---|
| `after_sales_manage` | `order:refund` | `AfterSalesController` / `AgentAfterSalesController` |
| `category_manage` | `product:category` | `CategoryController` |
| `customer_manage` | `customer:view` | `CustomerController` |
| `dashboard_stats` | `dashboard:view` | `DashboardController` |
| `employee_manage` | `employee:list` / `employee:create` | `AdminUserController`（写操作按 action 二次校验） |
| `finance_api` | `finance:view` | `FinanceController` |
| `order_manage` | `order:list` | `AgentOrderController` / `OrderController` |
| `piecework_query` | `order:list` | `AgentProductionController` / `ProductionController` |
| `processing_item_manage` | `processing:manage` | `ProcessingItemController` / `ProcessingCategoryController` |
| `processing_order_generate` | `processing:update` | `ProcessingOrderController` |
| `processing_order_query` | `processing:view` | 同上（**查看**码） |
| `processing_order_update` | `processing:update` | 同上（写取写码） |
| `product_manage` | `product:create` | `ProductController` 的 POST/PUT/DELETE |
| `product_processing_item_manage` | `processing:manage` | `ProcessingItemController` |
| `product_update` | `product:create` | 商品写取写码 |
| `role_manage` | `system:manage` | `AdminRoleController` |
| `session_manage` | `agent:session` | `AgentSessionController` |
| `settings_manage` | `system:manage` | `SettingsController` |
| `sku_update` | `product:create` | 商品写取写码 |

**仍由角色层把关**（目录里没有对应码）：`notification_manage`（`NotificationController`
全类无 `@RequirePermission`）。C 端双端工具（`product_search`/`order_query`/`product_detail`/
`inventory_manage`/`order_create`/`curtain_calc`/`interact`/`validate_input`/`knowledge_search` 等）
不加码 —— C 端 JWT 没有权限码，加码会让 C 端全量失效。

### 10.2 跨包契约（**名字不得改**）

```python
from app.tools.base import NON_RETRYABLE_ERROR_CODES  # frozenset，停重试的判据
# {"PERMISSION_DENIED", "FORBIDDEN", "AUTH_REQUIRED", "AUTH_FAILED", "UNAUTHORIZED"}
from app.tools.base import ToolResult  # ToolResult.error_code: Optional[str]
```

- `NON_RETRYABLE_ERROR_CODES` = admin-api 实际产出的授权/认证类码（逐个有出处：
  `GlobalExceptionHandler` 的 `PERMISSION_DENIED`/`AUTH_REQUIRED`、`SecurityConfig` 的
  `FORBIDDEN`/`UNAUTHORIZED`、`BusinessException` 的 `AUTH_FAILED`）。**刻意不含**
  `TENANT_INVALID`（租户配置问题，不是「当前账号缺权限」）。消费方式：`code in NON_RETRYABLE_ERROR_CODES`。
- `ToolResult.error_code` = 服务端 `error.code` 原值（拿不到则空，不臆造）。
- 失败映射单一入口：`app/tools/base.py::admin_api_failure(response, error=…, message=…, suggestion=…)`
  —— 授权类失败产出**可执行**建议（说明是权限限制、**不要重试**、指向管理后台授权路径，
  并保留服务端给的 `requiredPermission`）；其它失败**优先保留服务端 `suggestion`**，
  调用方文案仅作兜底。`app/tools/*.py` 里每个 admin-api 失败分支都必须走它
  （由 `tests/test_admin_api_failure_mapping.py` 的 L0 静态锁强制）。
