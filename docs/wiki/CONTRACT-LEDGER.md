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
| 商品状态 | `draft / on_sale / off_sale / under_review` | `ProductService.java` |
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
