# 加工单（Processing Order）设计

> 状态：**已定稿** ｜ 日期：2026-09-12 ｜ 范围：POC 客户含加工环节，订单履约缺加工单
> 关联：订单状态机 `OrderService.STATUS_TRANSITIONS` · `CONTRACT-LEDGER.md` 订单状态枚举 · issue 见关联 PR

## 一、背景与目标

POC 客户存在真实加工环节（窗帘定制：客户下单 → 加工方按尺寸生产 → 送货）。
当前订单链路 `confirmed → producing → shipped` 中 **producing 无人驱动**（空转），
加工信息只能靠微信发截图/手抄，尺寸错、加工项漏、交期无人管。

**目标**：新增「加工单」单据类型——它是订单履约链中 producing 阶段的**子进度**，
不是平行单据；由米宝 Agent 驱动，与订单状态在服务端事务内联动。

**已确认决策（2026-09-12，客户拍板）**：

| # | 问题 | 决定 |
|---|---|---|
| 1 | 加工完成后是否入成品库存 | **不需要**，MVP 只履约不计量，不动库存逻辑 |
| 2 | 加工单价格显示口径 | **默认**：给加工方看加工费明细（其收入依据），**不显示销售价**（防暴露加价） |
| 3 | 交期来源 | **手工填写**（`expected_delivery_date`），不做 `processing_days` 预填/推算 |
| 4 | 客户数据给加工方的合规流程 | **当前不涉及**（不开产品内授权流程）；技术安全措施（链接租户隔离+有效期）照做 |

**验收后决策（2026-09-12，验收边界 #3352）：**

| # | 问题 | 决定 | 落地 |
|---|---|---|---|
| 5 | 加工单 `completed` 后订单取消被硬拦截（无人工出口） | **暂不处理，保持现状**（记为已知风险：需线下处理；若后续出现真实阻塞，再评估「管理员强制取消 + 原因留痕」或「订单作废状态」） | 无代码改动 |
| 6 | 加工单生成后订单加工项若被改动 → 快照漂移、漏做加工仍可发货 | **选项 C 源头约束**：加工项**仅创建订单时可写**，创建后无任何修改通道 | ✅ 已满足（明细唯一写入点为创建时 `orderItemMapper.insert`；整单删除仅限 `pending`，此时不可能有加工单）→ tripwire 测试 `OrderItemImmutabilityTest`（PG-014）锁住不变量 |

> **升级触发点**：若将来引入「订单明细编辑」入口，PG-014 必失败 → 必须同步启用**选项 B**（发货守卫从「存在 completed 加工单」升级为「快照覆盖订单当前全部加工项」）并补齐「加工单更新」能力。该触发点已写入测试断言消息与 PG-014 用例 data_checks。

## 二、现状核查（有据）

| 事实 | 位置 |
|---|---|
| 订单 6 态显式状态机 `pending/confirmed/producing/shipped/completed/cancelled` | `CONTRACT-LEDGER.md:13`；`OrderService.java:76-79`（`STATUS_TRANSITIONS`）、`:505-515`（非法迁移拒绝） |
| `confirmed→shipped` 直跳当前合法（有加工项订单需禁止） | `OrderService.java:78` |
| 加工项已结构化：`processing_info` = `{processingFee, processingItems:[{id,name,unitPrice,quantity,unit}]}`，typed DTO `ProcessingItemBrief` + 解析方法 | `OrderService.java:714`、`:718`；`OrderDetailResponse.java:181` |
| **加工项 options（打孔:纳米圈/四爪钩…）未随订单落库** | grep 无命中 → 加工单生成时必须从 `processing_items.options` 补快照 |
| `processing_rules`（互斥/必选/堆叠）下单流程未校验 | grep 无命中 → 生成时**提示级**校验，不硬拦 |
| 工具级角色权限现成（`ToolContext.role` + `allowed_roles`） | `app/tools/base.py:21,96,137` |
| 全仓无打印/PDF/导出代码；无 `order:print` 权限码 | 已核查 |
| 前端无截图/PDF 库；已有 `interact` 卡片体系（choice/confirm/form） | `interact.py` |

## 三、数据模型（`processing_orders` 表，新迁移 Vxx）

```
id VARCHAR(64) PK
tenant_id BIGINT NOT NULL REFERENCES tenants(id)
order_id VARCHAR(36) NOT NULL REFERENCES orders(id)
processing_order_no VARCHAR(32) NOT NULL UNIQUE   -- JG-YYYYMMDD-序号（DB 唯一约束防重号）
processor VARCHAR(128)                             -- 加工方（文本，MVP 不建主数据）
expected_delivery_date DATE                        -- 交期（手工填）
status VARCHAR(32) NOT NULL                        -- generated/issued/in_processing/completed/cancelled
items_snapshot JSONB NOT NULL                      -- 生成时快照（见下），订单后续改价/改项不影响已发加工单
remark TEXT
template_version INT DEFAULT 1                     -- 单据模板版本（防历史单据样式漂移）
generated_by VARCHAR(64) / generated_at TIMESTAMPTZ
issued_at / in_processing_at / completed_at / cancelled_at TIMESTAMPTZ
cancelled_reason TEXT
print_count INT DEFAULT 0
deleted INT DEFAULT 0
```

`items_snapshot` 结构（快照=发给加工方的准信）：

```json
[{
  "productName": "布艺遮光帘A", "sku": "0012",
  "colorName": "米白", "sellingMethod": "散剪", "doorWidth": "2.8米",
  "width": 2.5, "height": 2.8, "quantity": 12.5, "unit": "米",
  "processingItems": [{"id": "p1", "name": "打孔", "unitPrice": 3.0, "quantity": 12.5, "unit": "米", "options": ["四爪钩"]}],
  "remark": "客户备注"
}]
```

要点：
- **options 必须补快照**：下单时未落库，生成加工单时从 `processing_items.options` 取出写入
- **销售价不进入快照**（决策 2）；加工费明细进入（`unitPrice*quantity`，加工方收入依据）
- 软删统一 `deleted` 标志；订单取消后加工单仍可查（快照保真）

## 四、状态机与联动规则

### 4.1 加工单状态机（服务端单一写入者，照 `OrderService.STATUS_TRANSITIONS` Map 模式）

```
generated → issued → in_processing → completed   （主链）
generated → cancelled                             （未发加工可直取消，reason 必填）
issued → cancelled                                （需人工确认，可能已有加工费损失）
in_processing → cancelled                         （需人工确认）
completed                                        （冻结：不可取消/改状态）
```

### 4.2 加工单 ↔ 订单联动规则（服务端事务内原子执行，agent 不参与判断）

| 触发 | 加工单 | 订单 |
|---|---|---|
| 生成加工单（订单有加工项；幂等：无 active 加工单） | `generated` | `confirmed → producing` |
| 发加工（填加工方+交期，写操作 confirm） | `issued` | 保持 producing |
| 开始加工 / 加工完成 | `in_processing` / `completed` | producing（**不自动 shipped**，发货需物流单号，仅提示"可发货"） |
| 订单取消（加工单 `generated`） | **自动** `cancelled` | → `cancelled`（顺延现有库存恢复规则） |
| 订单取消（加工单 `issued` 及以上） | **拦截，需人工确认** | 保持（加工费损失风险） |
| 加工单取消（`generated`） | `cancelled` | `producing → confirmed` 回退（订单未发货前提下） |
| 加工单 `completed` 后订单取消 | **拦截，需人工确认** | 保持 |

### 4.3 必须补的订单守卫（防联动被绕过）

`OrderService.STATUS_TRANSITIONS` 增加条件守卫：**订单含加工项
（`order_items.processing_info` 非空）时，进入 `shipped` 前必须存在
`processing_orders.status=completed`**。否则加工环节被绕过，加工方根本没收到单。

### 4.4 条件化联动（不是所有订单都要加工单）

- 有加工项 → 必须走加工单，订单停在 producing
- 无加工项（现货成品）→ 维持现状 `confirmed → shipped` 直跳

## 五、权限与安全

| # | 项 | 决定 |
|---|---|---|
| 1 | 权限码 | 新增 `processing:view` / `processing:update`，按 V29/V32 岗位补齐幂等模式 |
| 2 | 角色矩阵 | 生成=有 order 权限员工；**发加工/取消=admin/tenant_admin**（`allowed_roles` 声明）；查询=全员 |
| 3 | 租户隔离 | 全部走 MyBatis 租户拦截器 fail-closed；快照不含跨租户数据 |
| 4 | PII | 加工单含客户姓名/电话/地址（对加工方必要）→ **分享/下载链接租户隔离 + 有效期** |
| 5 | 留痕 | 状态变更/打印全进 `audit_logs`，`resource_type` 加 `processing_order` |

## 六、米宝 Agent 集成（order skill 扩展，不新建 skill）

| 工具 | 场景 | 写守卫 |
|---|---|---|
| `processing_order_generate(order_ids[])` | 「把这几单生成加工单」「今天确认的订单都生成」 | confirm（批量先列清单）；幂等拒绝重复生成 |
| `processing_order_query(no/order_no)` | 「JG-xxx 到哪了」 | 只读 |
| `processing_order_update(no, action)` | 「发加工」「开始加工」「加工好了」「取消加工单」 | confirm；action ∈ {issue, start, complete, cancel}；服务端校验状态机 |

- `order_skill.py` intents 加 `processing_order_generate/query/update`；prompt（`references/prompts/order.md`）加场景与展示规则
- **主动提醒**（挂 `follow_up.py`，事件驱动，MVP 不做定时扫描）：订单确认且含加工项未生成加工单 → 建议「生成加工单」；查询时顺带提示超期（基准 `expected_delivery_date`）
- 批量：`processing_order_generate` 支持批量（上限 100 单/批，同步返回）
- 参数校验：`validate_input` 加 `processing_order_update` 的 action 枚举
- intent 路由测试：`processing_order_*` 必须路由 order skill（进契约测试）
- 前端展示走 `interact` 卡片：加工单卡（document 形态）+「复制全部」纯文本按钮（加工方可直接贴 Excel，一行一加工项）

## 七、前端交付

1. **admin-web 订单详情**：加工单区块（状态时间线 generated→…→completed + 快照查看 + 生成/发加工/开始/完成按钮 + 打印入口）
2. **加工单卡（interact document 形态）**：手机长按截图发微信；PC `@media print` 打印 A4（注意多明细分页）
3. **「复制全部」纯文本模板**：规范成一行一加工项（商品/颜色/门幅/宽×高/数量/加工项+options/备注）
4. **不做 PDF/后端图片**：前端卡片渲染 + 截图/打印为 MVP 交付通道；PDF 等出现批量/归档/凭证需求再加（数据已是结构化 JSON，届时只是换渲染器）

## 八、明确不做（防范围蔓延）

1:N 拆单给多个加工方（P2）· 加工方主数据（先文本）· 报工/排产/工位（不做）· 库存计量（决策 1）· 电子面单 · 定时扫描任务 · 拖拽模板设计器 · 套打/联次 · 加工费对账（P1 与 finance 衔接）· 售后换货新加工单（P1）。

## 九、工程落地顺序（每步测试同行，三把工具提交前跑）

```
① processing_orders 表迁移 + ProcessingOrderService 状态机/联动事务（Red 先行）
② 订单守卫：有加工项禁 confirmed→shipped 直跳
③ Python 3 工具 + intents + prompt + validate_input 规则
④ 前端订单详情加工单区块 + interact 加工单卡 + 复制全部 + print CSS
⑤ follow_up 主动提醒
```

- 提交：`./verify-all.sh gate` + `./check-ui-regression.sh` + **`./contract-check.sh`**（跨模块）
- 契约：加工单状态枚举进 `CONTRACT-LEDGER.md` + `ontology/schema.yaml`（`contract-check` 词表）
- 新测试文件头 `# case_ids:`；用例进 `.github/cases/`（新建 `processing.yml`，改后必跑 `render_cases.py` 提交生成物）
- 行为改动后按 `migao-dev-flow` §13 跑体检用例；验收按 `migao-acceptance`（L1/L2/UA + 证据链）

## 十、验收用例清单（`processing.yml`，一次到位）

| 用例 | 断言 |
|---|---|
| 生成加工单（有加工项） | 订单 confirmed→producing；加工单 generated；快照五要素齐全（含 options） |
| 幂等 | 同一订单已有 active 加工单 → 重复生成拒绝 |
| 无加工项订单 | 不生成加工单；confirmed→shipped 直跳合法 |
| 有加工项订单 | 禁 confirmed→shipped 直跳（无 completed 加工单时） |
| 订单取消（generated） | 加工单自动 cancelled + 订单 cancelled |
| 订单取消（issued+） | 拦截，需人工 |
| 加工单取消（generated） | 订单 producing→confirmed 回退 |
| completed 冻结 | 取消/改状态被拒；completed 后订单取消需人工 |
| 权限 | 无 `processing:update` 角色调用被拒（fail-closed） |
| 租户隔离 | A 租户加工单在 B 租户不可查 |
| PII | 分享链接带租户隔离 + 有效期 |
| 快照保真 | 生成后订单改价不影响已发加工单快照 |
| 加工费/销售价 | 快照含加工费明细、不含销售价 |
