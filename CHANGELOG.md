# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 格式，并采用语义化版本（[Semantic Versioning](https://semver.org/lang/zh-CN/)）。

> 当前处于 POC 阶段（v0.x），尚未发布首个公开版本。以下变更记录自 2026-08 起维护。

## [Unreleased]

### 商品 + SKU 可以批量导入了：一个 Excel 建一批货，重复导入不产生重复、每一行错在哪都写着（2026-09-22，issue #5154）

- **为什么补这条通路**：它是**迁移/期初批次建账的前置** —— SKU 不存在 ⇒ 入库批次挂不上 ⇒
  闭环断在这里（用户裁定逐字：「**无法闭环就补功能**」）。此前后端只有「导出商品」是完整的，
  导入侧是一段**没有入口、没有调用方**的 POI 半成品（连 SKU 都不建）。
- **改后的形态**：商品管理页工具栏新增「**下载导入模板**」+「**导入商品**」（照「批量导出」的对偶形态）；
  一个 Excel 里**一个数据行 = 一个 SKU 行**，同一货号多行 = 一个商品的多 SKU。
  表头：商品名称\*、货号\*、分类ID、价格\*、库存、描述、**颜色、门幅**、SKU编码
  （与导出表头**逐字同名**的 5 列就是导出面；SKU 组合仍是**颜色 × 门幅**，售卖方式不参与）。
- **重复导入不会建重**：幂等键 = **货号**（租户内）。同一文件导入第二遍 ⇒ 商品与 SKU 都**原地更新**
  （主键不变 ⇒ 订单/批次里存的旧引用不断链），报告里写「新建 0 个、更新 N 个」。
  导入**只新增/更新，不删除**既有 SKU —— 商家在导入页看不到库里已有的 SKU，
  按「文件里没有」删会静默断掉批次引用。
- **每一行错在哪都写着（不静默跳过）**：报告弹窗同时给出「成功 N 行 / 失败 N 行 / **空白行** N 行」
  与「新建 N 个商品 / 更新 N 个商品」；失败明细逐行给**行号 + 货号 + 可行动原因**
  （例：`第 3 行库存 最多支持 1 位小数…当前值 2.755 有 3 位小数 —— 请改为 1 位小数后重试`）。
  非法行**零落库副作用**，同一文件里的合法行照常导入（行级原子，不是整包回滚）。
- **库存按 1 位小数**（沿用 #5063 口径）：`60.5` 原样落库、`2.755` 显式拒绝（**不静默取整**）；
  留空 = 不改既有库存（不是清零）。
- **不损失客户**：对客价 = 文件原值，不经任何折算；商品一律以**草稿**状态导入（上架仍是商家的显式动作）。
- **不做（显式边界）**：不做客户 / 订单 / 工艺配置导入（各自另议，见 #5149 的缺口清单）；
  导入**不改**状态与上架、**不删**任何既有数据。

### 入库单不再「双击过账就把库存加两次」：过账并发闸 + 单号重试 + 同一次导入重跑只建一张单（2026-09-24，issue #5148）

- **症状（三个真实可达的坏形态）**：
  ① **过账没有并发闸**：`post` 是「读 status → 判 draft → 写」，两个并发请求（双击 / 客户端重试 /
  多副本）**都**会通过判断 ⇒ 各加一遍库存、台账两条 —— 库存是资金级数据，虚增不响不报；
  ② **撞号即建单失败**：`RK-yyyyMMdd-NNNN` 的序号是**进程内**计数器，服务重启 / 换副本后从 `0001`
  重走 ⇒ 当天首个建单撞上已用的号、**直接失败**；而 `uk_inbound_orders_no` 当时是**全局**唯一，
  连别的租户用过的号都会把本租户挡下 —— 与建表注释逐字写的「**租户内**唯一」自相矛盾；
  ③ **重跑导入建出第二张单**：`create` 没有幂等键 ⇒ 同一份期初 / 迁移导入重跑会新建第二张草稿单，
  两张都过账 ⇒ **库存加两次**。
- **改后**：① 过账改为**条件更新原子闸**（`UPDATE … WHERE status='draft' AND deleted=0`，按**影响行数**
  判是否抢到过账权；PG 行锁持有到事务结束）⇒ 并发过账**只有一个成功**、库存只加一次、台账只落一条；
  ② 取单号前**查库内占用并重试**（上限 20 次，同批次号范式），单号唯一索引统一为**租户内**
  （`(tenant_id, inbound_no) WHERE deleted = 0`，与注释口径一致）；
  ③ 建单支持**运行级幂等键** `import_run_id` + 部分唯一索引 ⇒ 同一 `(租户, 运行标识)` 重跑
  **返回同一张单**；另新增 `source ∈ {purchase, opening}`（期初导入与正常采购可区分，供下游
  「批次建账」单做基线冻结点）。
- **不损失客户**：整数 / 1 位小数的入库量、单行与多行过账、移动加权均价、台账 `ref_no` = 入库单号、
  成本快照**逐值不变**；**不带** `import_run_id` 的建单行为与改前逐字一致（幂等键是可选的）。
- **真库判据**（Mockito 测不出来，见 #5141 的教训）：`tests/unit_ci_workflows/test_inbound_order_idempotency.py`
  起临时 PG 集群、**两个会话真并发**跑过账 —— CAS 形态读数：`claimed=1` / `claimed=0`、库存 5 → 35、
  台账 1 条、单据 posted；换成改前形态（注入式红证）⇒ 两会话都读到 `draft`、库存 5 → 65、台账 2 条。
- **边界（如实登记）**：取号的「查占用 → 插入」之间仍有窗口 ⇒ 两个**同时**建单的进程理论上可选中同号，
  此时由唯一索引挡下（后到者收到明确失败，**不会静默重号**）；进程内计数器单调递增，该窗口只在
  多副本 / 重启瞬间存在。`import_run_id` 冲突时后到者收到 409（不静默建第二张），重查即命中幂等分支。
- **顺带订正**：`InboundOrderCreateRequest` 的类 javadoc 仍写「数量必须 ≥1 的整数」（V115/#5063 之后已过期）
  ⇒ 改为现状口径（≥1 米且最多 1 位小数）；用例库 PR-032 的同款陈旧表述一并订正。

### AI 建品/改品的库存入参放宽为**1 位小数**：60.5 米不再被拒或被静默截成 60（2026-09-22，issue #5150）

- **症状**：#5063 把库存全链路小数化后，AI 侧还剩一处**同族残留** —— `product_manage` 的
  `stock_quantity` 仍是 `integer` schema + `int(...)` 强转 ⇒ 用户说「库存 60.5 米」时，
  AI 要么传不出去（schema 只认整数），要么被**静默截成 60**（半米凭空消失，且全程无告警）。
- **改后**：入参声明为 `number`，**最多 1 位小数**（0.1 米粒度，与 #5063 同一口径）并**原值**下发；
  **超过 1 位小数（如 2.755）⇒ 显式拒绝**：文案说明「库存按 0.1 米粒度记录、请改成 1 位小数后重试」，
  **不做**四舍五入、**不做**截断，且**一个字节都不下发**（零 API 调用，不会先打后端再报错）。
- **整数场景逐值不变**：库存 `30` 下发的仍是 `30`（不是 `30.0`）。
- **最少代码**：精度判定 / Decimal 归一**复用** #5063 落在 `inventory_manage` 的同一套助手
  （`_one_decimal_or_none` / `_stock_number` / `STOCK_QUANTUM`），未新造第二套判据或常量。
- **边界（如实登记）**：只改 AI 侧入参口径 —— 库存落库链路（#5063/#5147）、入库单、前端、迁移均未动。
### 派加工单时指定批次并扣批次库存：批次余量、剩余量分布、批次账对账三个读面（2026-09-22，issue #5145）

- **用户裁定（2026-09-22）**：逐字「应该订单用智能化**派加工单后就直接减少批次库存**」＋
  「**按你建议来 A**」（两本账）＋「生成加工单时由文员指定批次（系统给候选 + 建议值，人工确认、可改）」。
- **改后的形态**：生成加工单时，文员**逐面料行**选「这批布从哪个批次裁」（界面给候选批次 + 建议值，
  可改；建议值阶段 1 = **入库日期先进先出**，不是智能指派）；确认后**该批次余量当场减掉这行的米数**，
  与加工单生成**同一事务**。加工单作废（含订单取消自动作废）⇒ **同事务把余量还回去**，逐值对称
  （扣 2.7 米就回 2.7 米）。
- **不指定批次 = 行为与今天完全一样**：该 SKU 还没有入库批次、或文员不选 ⇒ 不扣、不记账、
  不多一个报错分支（这是本阶段的定义特征：**只记录、不改指派行为**，基线要能前后对比）。
- **缺料不再静默**：指定的批次余量不够 ⇒ **当场拒绝**并给出可行动建议（该行需要多少米、
  同货号还有哪些批次各剩多少、可换批次或先入库补料），**不会**「有多少扣多少」、
  **不会**留下「有加工单、没扣账」的半成品。
- **三个新读面**（后台）：① **批次余量**（入库量 − 已派工消耗，逐批次）；② **剩余量分布**
  （`≤0.2 米 / 0.2~0.5 米 / 0.5~1 米 / >1 米` 四档的批次数与占比 —— 这是「批次是否被用尽」的效果读数）；
  ③ **批次账对账**（`Σ批次余量` 与商品库存的**差额**及其分解：已售未派 / 退货回补 / 台账外存量）。
  工人扫码端每一行直接显示「**批次 PC-… 裁 2.7 米**」，即「去哪个批次裁多少米」。
- **不动客户面**：销售账（支付时按公式米数扣库存）**一字未动**，订单金额、售价、成品尺寸、加工费
  全部不受影响；批次账是新增的**实物账**，两账差额在对账读面里**读得出、可解释**，不会静默漂移。
- **不做（显式边界）**：不做智能指派（best-fit 属阶段 2）、不做余料台账/回收（用户裁定「废布不算企业资产」，
  归 #5146）、不做期初批次导入（归 #5149）；批次行本身**不原地改**（V111 裁定：冲销走新单据）。
- 迁移 `V116`：新表 `stock_batch_consumptions`（一行 = 一次批次余量变更；**余量派生** = 入库量 + Σ变化量；
  幂等闸 `uk_batch_consumption_line` 保证「同一加工单同一行同一批次」只扣一次；按**批次 / 加工单 / 订单**
  三个维度都能查回来）。

### 修复：**多行入库单过账必然失败**（整单共用一个批次号撞唯一索引，整单回滚）（2026-09-22，issue #5141）

- **症状**：一张 **≥2 行**明细的入库单点「过账」⇒ 第 2 行写批次台账时撞
  `uk_stock_batches_no`（= `UNIQUE (tenant_id, batch_no)`）⇒ **整个事务回滚**，库存一点没加、
  单据停在草稿；商家只看到「过账失败」，看不出是批次号重复。
- **改后**：批次号**逐行生成**（`PC-yyyyMMdd-NNNN` 每行各取一个），与 V111 的裁定
  「**一个 SKU 行 = 一个批次**」一致；每行 `inbound_order_items.batch_no` 回写**自己那一个**号，
  `product_skus.latest_batch_no` 也逐行各记各的。
- **单行过账逐值不变**：批次号格式、移动加权均价、台账成本快照、`ref_no` = 入库单号全不变。
- 边界（未在本单内）：真实 DB 上的过账尚无集成测试，本单判别力来自「两个批次号必须不同」
  这条断言（DB 唯一索引由它间接保证）；入库单号 `generateInboundNo()` 的重试与过账并发闸仍未实装。
### 库存米数支持**小数**（1 位小数 = 0.1 米粒度）：60.5 米能入库、2.7 米按真实米数扣库存（2026-09-22，issue #5063）

- **用户裁定（2026-09-22）**：逐字「**库存米数是小数，1 位小数，必须改造**」＋「**不能损失客户**」
  ⇒ 存量精度取 **1 位小数**（与用料口径 `meters_rounding_step` 进位到 0.1 一致）。
- **改后的形态**：入库单可以录 **60.5 米**（此前服务端**显式拒绝**「必须是 ≥1 的整数」）；
  顾客买 **2.7 米**时库存**真的减 2.7**（改前只减 2，**0.7 米凭空消失**，且全程无告警）；
  库存台账（`stock_ledger_entries`）的 `delta` / `before_qty` / `after_qty` 与实物同粒度，
  「某 SKU 的库存为什么从 X 变成 Y」在小数下依然能对账（相邻两行首尾相接）。
- **禁止静默取整**：库存类**输入**（入库数量 / 库存调整量 / 建品改品的库存）超过 1 位小数
  （如 **2.755**）⇒ **显式拒绝**并给出可行动提示（「库存按 0.1 米粒度记账，请改为 1 位小数后重试」），
  **不会**四舍五入成 2.8、也**不会**截断成 2.7。
- **对客口径一字未动**：订单金额、报价、加工费、成品尺寸**都不受影响**；既有**整数场景逐值不变**
  （买 10 米、入库 30 米、盘点 +3 的分配结果与改前**完全相同**，包含返回的 JSON 数字形态）。
- **边界（如实登记）**：顾客侧数量（`order_items.quantity`，最多 2 位小数）**不拒绝**
  —— 顾客已下单，在下单点拒绝 = 损失客户 ⇒ 按用料口径
  （`docs/curtain-fabric-quote-rules.md` §8「用料米数一律向上进位到 0.1」）**显式**进位到 0.1 后落库存，
  且扣减与回补**同一函数**（同一笔单净变化恒为 0）。「销量」与库存同源，一并小数化
  （否则会出现「库存 -2.7、销量 +2」这种单笔单据内部自相矛盾的账）。
- 迁移 `V115`：`product_skus.stock` / `products.stock` / `stock_ledger_entries.{delta,before_qty,after_qty}` /
  `inbound_order_items.quantity` / `stock_batches.quantity` / 两处 `sales_count` 由 `INTEGER` 改 `NUMERIC(12,1)`；
  **存量整数无损**（`60 :: numeric(12,1)` = `60.0`），幂等可重复执行，文末终态对账。

### 参数总览新增**逐键**「已改 / 默认」标记：一眼看出哪几个算料参数被你改过（2026-09-22，issue #5131）

- 算料参数里**每个键**旁标出是「**默认**」还是「**已改（默认 X）**」—— 商家不必再猜
  「这个数是我改过的还是系统给的」（§22 P3 的**逐键**形态；原先只有「本企业从没配过」时的整体提示）。
- 读面**按需**附引擎默认值（`GET /api/admin/production/craft-calc-config?with_defaults=true`）：
  🔴 **默认不带** —— 既有调用方（算料配置页）响应**逐字节不变**，也**不新增**
  「读配置要依赖引擎可达性」这条依赖（有配置行的读，值来自库）。
- 引擎默认值**取不到**时页面**显式**显示「无法判断哪些参数被你改过」——
  **不会**把「拿不到」画成「就是默认值」。
- 边界：只覆盖**算料域标量键**；AI 客服域的名称 / 欢迎语没有「引擎默认值」这个概念，不标记。

### 超高 / 超宽改为**企业阈值参数**判定（默认 6 / 4 米，与门幅无关）—— 涉钱：加工费组合键会变（2026-09-22，issue #5130）

- **用户裁定（2026-09-22）**：`6 / 4` 米（**净窗宽 / 净窗高**）是**客户给的口径** ⇒ 做成**企业参数**；
  判据**替换**（不再与门幅比）；默认 `6 / 4`、**对所有租户立即生效**（用户已知会改存量租户的加工费组合键，明确接受）。
- **改后的形态**：自动特征「超高 / 超宽」的判据 = `净窗宽 > oversize_width_threshold` ⇒ `超宽`、
  `净窗高 > oversize_height_threshold` ⇒ `超高`；`倒幅` **不变**（加工类型 = `定宽买高`）。输出顺序恒为
  `超宽 → 超高 → 倒幅`，`source` 恒为「推算」。两个新键进算料配置（`craft_calc_configs`，迁移 `V114`），
  **下单页随判定请求下发**（不下发会让商家改的阈值静默不生效）。
- **改判留档（三条判定面裁定一并退役）**：**#4661**「按加工类型分流」——
  绝对阈值与加工类型无关，且 `超宽` / `超高` **可同时为真**（缺省 / 表外加工类型 ⇒ 两者照判，只有 `倒幅` 缺席）；
  **#4662**「超宽须含褶倍」—— 新判据不含褶倍；**#4877**（**判定面**）「缺门幅 ⇒ 不判」——
  新判据不读门幅（门幅仍是**几何层**输入：用料 / 加工类型 / 门幅规则面）。
  三处留档：引擎 `detect_auto_features` 的 docstring、前端 `craft-calc-glossary.ts` 的术语文案、
  用例库 `.github/cases/order.yml` 的「下单页系统识别」用例。
- **改钱形态（用户裁定 D9 明确接受）**：「超高 / 超宽」由**高频特征**变成**只在大窗出现的罕见特征** ⇒
  家用常见窗（如 3.0 × 2.7）**不再**判超高/超宽 ⇒ 若商家给含它们的组合配了更高的价，
  这些单会落到**更便宜**的档（或 `unpriced`）。方向与「超宽 / 超高 = 更贵一档」的直觉相反 ——
  这是客户口径（绝对阈值）的必然结果，不是缺陷。
- **几何层一字未动**：用料米数、加工类型、分幅、门幅规则**都不受本变更影响**
  （`resolve_fabric_plan` / `calculate_fabric_meters` 走几何判据，与特征名无关）。
- **提示（notices）退役两条**：`missing-door-width`（旧文案「未维护门幅 ⇒ 超高/超宽都判不了」）与
  `missing-fullness`（「缺褶倍 ⇒ 未判超宽」）在新判据下是**假话** ⇒ 删除；`cutting-mode-conflict`
  （几何层，仍为真）**保留**。判定端点响应里失去消费者的 `fullness_used` / `notice` 两个字段一并删除。
- 新增配置键（六处同源，守卫 `tests/unit_ci_workflows/test_craft_calc_config_contract.py`）：
  `oversize_width_threshold`（超宽阈值，净窗宽，米；默认 6）/ `oversize_height_threshold`
  （超高阈值，净窗高，米；默认 4）。迁移 `V114__add_craft_calc_oversize_thresholds.sql`（**不播种**：
  缺行 = 用引擎默认值）。
### 企业基础信息新增「参数总览」：一处查看本企业可配参数与口径（2026-09-22，issue #5131）

- 用户 2026-09-22 逐字强调「**我们的配置类页面务必要考虑配置复杂度和用户体验**」，
  并裁定「整合」落在**页面 / 信息架构**这一层（存储保持结构化列，不动既有 6 处同源契约）。
- 新增 tab「**参数总览**」（`/settings?tab=params`）：按域分组（算料 / AI 客服 / 加工费 / 工艺），
  每个参数给 `label` + 一行口径 + 「改它会怎样」**三件套**；算料域再分「常用（默认展开）/ 高级（默认收起）」。
- **默认值可见**：算料口径读面 `source` 不是 `stored` 时，逐键标出「未配置（正在用引擎默认值）」
  —— 商家不必猜「这个值是我改过的还是系统默认的」。
- **行式配置只给入口**（加工费组合 / 特殊选项价 / 工序库 / 工序管理 / 计件）：它们是**列表编辑**，
  与标量参数不是一类，塞进参数表格会让页面变成两套交互的杂糅。
- 参数文案**单一真值模块** `frontend/admin-web/src/lib/tenant-params.ts`：算料域文案**直接读**
  `craft-calc-glossary.ts`（不抄第二份），并有守卫钉住两条基线 ——「文案里**不出现数字**」
  与「算料域必须覆盖引擎**全部**配置键」（双向）。
- 算料口径读面失败（如岗位缺「工艺配置」权限）给**可行动话术**并当**终态**处理，不再让商家反复重试。
- **改阈值前先试算**（§22 P4「改钱的参数给护栏 + 预览」）：算料域给「**阈值试算**」块 ——
  双列对照「按**当前**口径」vs「按**你改的**阈值」，判定走服务端真值
  （`POST /api/admin/orders/auto-features` 的 `config` 透传）⇒ **只读预演、不保存**
  （改口径仍走有护栏与逐条理由的「去算料配置」）。
  ⚠️ 只覆盖超高 / 超宽两个阈值键 —— 其余算料参数的服务端试算**不收 `config`**，今天做不到「改前预演」（已登记）。
- ⚠️ **未闭环（照实登记）**：**配置变更留痕**（谁在何时改了哪个参数）不在本增量内，
  已登记为 issue #5131 的后续增量。

### 用料进位收敛到 `build_quote` 唯一出口：展示米数与计费金额同源（2026-09-21，issue #5084）

- 声明口径（真值源 `docs/curtain-fabric-quote-rules.md` §8）：用料米数一览**向上进位到 0.1**（`ceil(x*10)/10`）
  —— 截断 / 四舍五入即违约；且**进位只在总用料上做一次**。
- 实测违约：实现里只有「褶数法」与显式 `formula='fullness'` 两支各自进位，其余三支
  （倍数法回落 / 定宽买高 / 门幅规则回落式）都不过它，出口只做 `round(meters, 2)`
  ⇒ **同一份报价内部不自洽**：明细「3.83 米 × ¥100/米」vs 金额 `383.4`。
- 治法：在 `build_quote` 返回前统一 `ceil_to_step(meters, cfg['meters_rounding_step'])`，
  位置在**算价之前** ⇒ `fabric_cost` / `processing_cost` / 拼色加价 / 孔带与 `fabric_meters` **同源同一变量**。
- 改前 → 改后（实测读数）：`3.83 → 3.9`（金额 `383.4 → 390.0`）；`8.79 → 8.8`；
  已各自进位的两支在唯一出口下**幂等**（值级锚点 12.3 / 13.3 / 11.0 米，11.0 = ERP 锚点）。
- 罗马帘路径按 #5084 明确剔除（用户裁定「无实际业务」）⇒ **逐值不变**（值级守卫保留）。

### 商品加「1 卷 = 多少米」+ 售卖方式降级为商品基础属性（SKU = 颜色 × 门幅）+ 订单体现优先整卷发货（2026-09-21，PR #5058）

- **用户裁定（逐字）**：「商品需要增加 1 卷=多少米，作为商品货号的基础参数，商品的售卖方式整卷/散件
  不能作为 SKU 的组合项，只能作为基础属性，商品的 SKU 由颜色+门幅组成即可，在订单中再体现
  客户要求优先整卷发货，例子：客户买 100 米布，一卷=60 米，那就发 1 整卷 60 + 散剪出的 40 米」。
- 数据模型（迁移 `V112`）：`products` 增 `selling_methods`（JSONB，商品级基础属性）与 `roll_length_m`
  （**1 卷 = 多少米**，可空、**不设默认值** ⇒ NULL = 未配置，订单侧禁止推算）；`product_skus` **删** `selling_method`，
  唯一键收窄为 `(product_id, color_id, door_width)`（存量同色同门幅多行按「价格最低、同价取 id 最小」去重，
  中文字面归一化为枚举）；`order_items` 增 `selling_method` / `roll_count` / `roll_length_m`（偏好 + 分配 + 卷长快照）。
- 整卷分配（纯函数 `ProductRollAllocation`）：`rollCount = floor(quantity / rollLength)`，余量散剪；
  闸门 = **货号有没有配卷长**（与售卖方式**解耦** —— 用户举的例子就是按米买布，顾客没说「我要整卷」）；
  卷长未知 / 非正 / 溢出 ⇒ 未分配（全 null，**不落 0、不 500**）。
- 三端同步：SKU 笛卡尔积收窄为 颜色 × 门幅（SKU 编码去售卖方式段）；`product_detail` 商品级透出；
  下单页 SKU 矩阵只剩 颜色 × 门幅；订单明细渲染「整卷 N + 散剪 M 米」；入库单页面的 SKU 级售卖方式展示删除。
- 用例新增：`PR-042` / `PR-043` / `PR-044`（SKU 组合只有 颜色 × 门幅 / 售卖方式 = 商品级基础属性 /
  卷长 = 货号级基础参数）+ `OR-046`（订单整卷分配，含用户原话那组数）。
- **独立对抗式复核抓到并已修（1 P0 / 2 P1 / 5 P2）**：**P0** = 迁移回填引用了**不存在的列** `product_skus.deleted`
  ⇒ 真库整份迁移回滚且被 MigrationRunner **静默跳过**（部署 success、三列永不建；是本单的测试夹具把它挡掉的）；
  **P1** = 评测栈种子仍写已删除的 `selling_method`（整个 persona 种子注入失败）、分配闸门原写成
  「只有明说 `full_roll` 才算」⇒ 用户举的例子恒不落分配（已解耦 + 补测试）；P2 = 溢出建单 500（改为未分配）等。

### 门幅（door-width）规则口径切源：服务端唯一实现，前端不再持有算料口径常量副本（2026-09-21，issue #5043）

- **用户裁定（2026-09-21）**：「四爪钩 / 穿杆 / 平幔 这三个工艺不影响用料和门幅」
  ⇒ 规则面按**引擎的正常用料口径**算，不为这三类另立口径、也不降级成「只判可行性」。
- 治的缺陷形态：前端门幅规则与引擎 `resolve_fabric_plan` **不是同一条规则** —— 定宽买高的幅数，
  引擎 = `ceil(T / g_eff)`（`T` = 定高用料，按**选定公式**算），前端 = `ceil((成品宽 + SIDE_MARGIN) × 褶倍 / g_eff)`
  （**恒按倍数法**）。实测（`per_fold_single=0.25` / 褶倍 2.0 / 韩褶）：门幅 3.2 时引擎 **1 幅** / 前端 **2 幅**，
  `T` 比前端分子小 0.65 米 ⇒ 搬过去必须采用**引擎口径**。
- 落点：`build_quote` 加性回传 `panels`（**幅数无定义时键必须缺席** —— 既不补 0、也不补 1 冒充「1 幅」）；
  新增引擎侧唯一实现 `judge_door_width_choice`（四态 `optimal` / `suboptimal` / `infeasible` / `unknown` + 可执行建议）；
  新增**只读**端点 `POST /api/internal/production/door-width-plan`（复用 `build_quote` 取自算料解，**不自算 `T`、
  不复刻公式选择、不回传任何金额字段**）+ Java 侧 `DoorWidthPlanController`（权限 `order:list`）。
- **终态**（前端不再持有任何算料口径常量副本）：删规则模块 `frontend/admin-web/src/lib/door-width-plan.ts`
  与 `HEM_MARGIN` 前端副本，页面三处消费者（`cuttingModeOf` / `pickAutoSkuForColor` / `doorWidthChoice`）
  全部改读服务端。
- 守卫**改判而非放宽**：前端「副本逐值相等 / 注释引文 / 副本被消费」三条前提全部消失 ⇒ 合并升级为**死亡条件**
  （前端任何源文件不得再定义该常量）+ **引擎侧存活**（防「两边都没有」的假绿）；用例 `OR-040` 的真值来源
  由前端文件改判为服务端腿（原真值指向的文件已退场）。

### Agent 能力可见面扩宽：只读工具按 persona 家族跨域共享 + 系统提示「能力索引」（2026-09-21，issue #4125）

- 只读工具（`read_only=True`）按 **persona 家族**共享：家族由 `SkillConfig.system_prompts` 键 derive，
  家族不唯一 ⇒ **fail-closed 不放宽**；**写工具仍按域收紧**（非对称切分）。
- 系统提示加「能力索引」层：内容为 `SkillConfig.tool_names` × 注册表 `read_only` 的**机械投影**
  （不写死任何 skill 名 / persona 字面量），**仅进模型提示，不进用户可见路径**。
- 提示预算按**逐域实测 +200、上取整到百位**只上调真正触顶的档位 —— 未触顶的档位**不动**
  （给没触顶的档位加余量等于**悄悄放宽棘轮**，与「只简化实现、不降门禁」相悖）；硬上限 14000 → 14800。

### 菜单「三处同构」：服务端两处同步到前端 IA + 新增跨源守卫（2026-09-21，issue #4440）

- 病根：菜单号称「三处同构」，实则**三份各自维护**且**改一处不红** —— 前端 `config/menu.ts`（**真实侧边栏**）、
  服务端 `MenuController.MENU_TREE`（`GET /api/admin/menus` 读面）、服务端 `AuthService.buildMenusByPermissions`（登录下发）。
- 实例（实测）：前端已在 #4416 把「工序库」+「工艺路线」**合并为单入口「工艺配置」**，而服务端两处仍是合并前的
  两个节点 ⇒ 前端「岗位权限」页（**确实消费** `GET /api/admin/menus`）显示的菜单项与**真实侧边栏对不上**。
- 落点：服务端两处同步为单节点（id / 名称 / 图标 / 路径与前端逐字一致）+ 新增**跨源守卫** ——
  断言生产管理组的节点名列表在三处**逐值相等**，并**反恒真**（任一解析为空 ⇒ 红）。
- 边界（如实登记）：根因「前端不消费服务端菜单」（`Sidebar.tsx` 只读 `menu.ts`）**不在本单** ——
  本次只把三处拉齐并把漂移**变红**，而不是让它静默腐烂。

### 路线匹配 tie-break 改「先建者优先」：新建路线不再静默顶掉种子路线（2026-09-21，issue #4563）

- 病根：路线模板排序曾为 `is_default DESC, id ASC`，多命中时「取第一条」＝ **id 最小者**；而新建路线 id 是 UUID、
  种子 id 形如 `rt-v79-01` ⇒ UUID 十六进制首字符恒小于 `r` ⇒ **任何新建的、`positions` 含同一部位的路线都会排到种子前面**。
- 叠加伤害（#4529 新增第 4 部位 `布料` 后暴露）：布料单走新路线后**只剩「打包」（丢掉「配料」）**；
  若新路线还是空壳 ⇒ **零工序加工单**（工人扫不了码，且**没有任何东西会变红**）。
  **涉钱**：工序 = 计件工资的输入（`Σ(报工数量 × 工序单价)`）⇒ 拿到错的工序序列 = 工人按错的单价拿钱。
- 修法：排序加第二键 `created_at ASC`（`is_default DESC, created_at ASC, id ASC`）—— **先建者优先**，
  默认路线仍恒排第一（既有语义不动），`id` 保留为第三键（同刻创建时仍确定）。
  判据含**反向自证**（证明「只按 id 排时新建的在前」这个机制**真实存在**，不是空断言）。

### 面包屑覆盖修复：「入库单」「每日简报」不再落兜底（2026-09-21，issue #5071）

- 现象：面包屑匹配表缺 `/inbound-orders` ⇒ 商家在「入库单」页**只看到「工作台」一项**（落兜底分支），
  违反「面包屑与侧边栏菜单名一致」（同表里 `/production/*`、`/products`、`/orders` 等每一组都逐条对齐）。
- 按「每个带 `path` 的菜单项 → 喂给匹配表」机械对账，实测 **2 处落兜底** —— 除 `/inbound-orders`
  （#5034 新增菜单项时漏配）外，还抓出同类第二例 **`/briefing`（每日简报）** ⇒ 两处一并补上。
- 补「防复发守卫」：对**每一个**带 `path` 的菜单项**渲染真实的 `Header`**，断言 ① 面包屑**不止一项**
  （兜底只有一项 ⇒ 一项即漏改）、② **末项 label == 该菜单项的 `name`** —— 把规范变成**可执行的定义**，
  并自动覆盖**将来**新增的菜单项（这类漏改**已发生两次**，此前无任何东西会变红）。
- 边界（如实登记）：只判**正向**（菜单项 ⇒ 有面包屑）；**反向不判** —— 面包屑表合法地覆盖**非菜单**路由
  （`/processing-orders/{id}/production`「生产明细」、`/agent-workspace/sessions` 等），
  要求「每个面包屑条目都有菜单项」会造**假红**。

### 算料口径：订单宽高 = 窗户宽高 —— 用料 = 窗宽 × 褶倍，「左右覆盖余量」整体退场（2026-09-21，issue #5030）

- **用户裁定（2026-09-21，逐字）**：「订单这里的宽和高是**窗户的宽高**」；宽度用料 = **窗宽 × 褶倍**
  （不再另加左右覆盖）；**成品高 = 净窗高**（不做换算）；「不用考虑左右余量，根据公式算出来的用料就已经包含了，
  我们是否需要移除左右余量这个概念」⇒ **移除**（常量 + 配置键 + DB 列一起删干净，留着就是「改了不生效」的静默失效）。
- `backend/ai-agent-service`：`curtain_calc.py` 删常量 `SIDE_MARGIN` 与配置键 `side_margin`；
  `calculate_fabric_meters` 定高用料 `(W+0.3)×N → W×N`、定宽分幅 `ceil((W+0.3)×N/G) → ceil(W×N/G)`；
  `detect_auto_features` 的「超宽」判据 `→ 窗宽 × 褶倍 > 门幅`（reason 文案同步）。
- 配置面**五处同源**同步删键：引擎键集 / 新迁移 `V112__drop_craft_calc_side_margin.sql`（`DROP COLUMN IF EXISTS`，幂等）/
  `docs/sql/schema.sql` / Java `CraftCalcConfig` / `CraftCalcConfigService`（`CONFIG_KEYS` + `NUMERIC_KEYS`）。
- `frontend/admin-web`：`lib/craft-auto-features.ts` 删导出常量 `SIDE_MARGIN`；`lib/door-width-plan.ts` 分幅与依据去余量；
  `lib/craft-calc-glossary.ts` / `types/index.ts` / 算料配置页去该键；下单页标签改 **「窗宽 (米) / 窗高 (米)」**，
  ①区块提示句改为「按**窗户净尺寸**填（成品宽 = 窗宽、成品高 = 窗高）」。
- **改钱面（实测读数）**：`calculate_fabric_meters` 通路 3.0/2.5/2.0/2.8 ⇒ **6.60 → 6.00 米**；6.6/2.6/2.0/3.2 ⇒
  **13.80 → 13.20 米**；6.6/2.6/2.0/2.8（定宽 5 幅）不变。B 端下单页两条通路（`pleat` / `fullness`）本就不含余量 ⇒ 金额不变。
- 判据改判：`tests/unit_ci_workflows/test_panels_formula_split_audit.py`（#4760 的「A 含 / B1 不含、恰差 1 幅」形态随本裁定消失）
  改为**四方同式** `ceil(窗宽 × 褶倍 ÷ 门幅)` + 反向守卫；`test_craft_calc_config_contract.py` 的 #4940 文案漂移守卫
  改为「全仓不再出现该键（迁移历史注释除外）」。
- 一并关闭：**#4760**（两条通路分幅公式不一致 —— 本裁定即其要求的业务裁定：`side_margin` **不该算**）、
  **#4940**（配置页文案与引擎口径相反 —— 其 A/B 两条路都被「该键整体退场」取代）。
- 真值源：`docs/curtain-fabric-quote-rules.md` 的常量清单 / 公式 / 分幅对照表 / 完整算例按新口径同步
  （3m 窗算例由 `M = 3.3 × 2 = 6.6 米` 改为 `M = 3 × 2 = 6.0 米`；该文已不再写「左右覆盖余量」）。

### 加工单打印任务卡改「洗水码」形态：按商品行（部位）出码（2026-09-21，issue #4946）

- **用户裁定（三条，2026-09-21）**：① 洗水码固定 **60mm × 30mm**；② 粒度 = **商品行（部位）**，一个商品一张纸；
  ③ 洗水码**取代** A4 任务卡。理由（用户逐字）：「当前生产环节都是按单个商品工序去生产……
  那得打印三张纸，每个商品一张纸，二维码也得生成三张分别对应三套工序」。
- `backend/admin-api`：`GET /production/orders/{orderId}/operations` 的 `positions[]` **只加不改**地补三个键
  —— `part_token` / `part_short_code` / `scan_url`（= `https://<稳定域名>/s/<短码>`，印刷品上二维码的内容）；
  既有键与顶层 `qr_token` 一字未动。扫码读面 `GET /production/scan` 新增**短码 / 整条 URL** 归一
  （设计 §1.4 逐字要求；`/s/<短码>` → 短码 → token），既有四形态路径一字未动，跨租户短码 fail-closed。
- `frontend/admin-web`：`TaskCardPrint` 由「一单一卡的 A4 版式」改为 **N 张 60mm×30mm 洗水码**
  （N = 部位数，每张自带该部位的二维码 + 人可读短码 + 加工单公共属性 + 工序摘要）；
  「生成二维码（测试用）」弹层由「一单一码」改为**按商品数量出码**。
- 用例库：`PP-011` 的 3 条既有 `data_checks` 按新真值**改判**（旧口径「任务卡二维码 = `qr_token`（加工单级）」
  「A4 逐道工序表 + 手工勾选位」「测试弹层 = 加工单号纯文本一码」均已作废）。
- 真值源：`docs/curtain-production-rules.md` §1 补录本次裁定（形态 / 粒度 / 公共属性 / 摘要边界 / 码的内容）。

### 评测完成判定收紧：`unstable`（两次皆败但成因不同）不再按波动放行（2026-09-14）

- `tests/agent_eval/local_runner.py`：`_COMPLETION_RELEASED_CLASSES` 由 `{llm-noise, unstable}`
  收为 **`{llm-noise}`** —— 放行档只保留「首次失败、新 session 重试通过」；两次都没通过的
  用例（含 `unstable`）一律进阻塞桶。理由：`unstable` 只证明"两次失败不是同一件事"，
  **没有**证明"其中有一次是对的"；实证 OR-014（run 34841029062）一次"下单成功但金额错
  168≠198"、一次"`order_create` 从未被调用"，2/2 都真失败
- **分类新增「指纹子集」规则**：两次指纹有**真子集**关系（共有部分非空）⇒ `reproducible`
  （纯结构判据，集合包含）。实证 AS-004（run 34849029334）：首败 = 两条**实质**落库断言
  （`落库 closeReason 为空` + `closeReason 不含期望值`），次败 = 这两条 + 一条
  `after_sales_manage … unmatched expectation` —— 机械按"指纹不同"判发散 ⇒ 真回归被洗成
  波动、`deterministic_failures` 漏计。注意：**指纹不同 ≠ 必然 `unstable`**
- 台账条目新增 `released` 字段（与 `_COMPLETION_RELEASED_CLASSES` 同源）—— 口径变更后
  "分类名"已读不出处置，台账自证放行与否
- 影响面（离线重放 6 个真实 run、**43 条去重台账条目**）：放行条目 29 → **21**（全部 21 条
  `llm-noise` 保留放行，8 条 `unstable` 改判阻塞）；分类变化 3 条（`unstable → reproducible`：
  PG-016 / AS-004 / PR-005）；**run×persona 结论翻转 2 处** ——
  `34846098440` mibao（PG-016 假绿，`ok` true→false）与 `34849029334` xiaobu
  （OR-026，`ok` true→false）
- 单测：`test_completion_verdict.py` 新增契约守卫（分类枚举封闭 + buckets 三方一致 +
  台账 `released` 同源），`test_unstable_released` → `test_unstable_blocks`；
  `test_failure_signature_root_cause.py` 增加 OR-014 / AS-004 / OR-026 三个**真实**指纹夹具
  （两次皆败 / 指纹子集 / 成因不同三形态）；`test_eval_summary_attribution.py` 的
  `completion_verdict` 语义冻结锚点同步显式更新（并加上 `unstable` 阻塞锚点）
- ⚠️ 门禁口径变更，属**待裁定**项（决策请求见对应 PR）；`.agent-presets/**` 里的技能副本
  仍写「llm-noise / unstable 放行」，需由该文件的负责方同步（本 PR 按避让约定未改）

### 米宝主推理模型迁移 DeepSeek-V4.1-Flash（模型名 canonical = `deepseek-flash`）（2026-09-11，#3319）

- `ai-agent-service`：DeepSeek 于 2026-09-10 发布 **DeepSeek-V4.1-Flash**，官方 API 将模型名改为 **`deepseek-flash`**（原生多模态），旧名 `deepseek-v4-flash` / `deepseek-v4-flash-vision-exp` 对应模型已下线、仅作**临时兼容路由**指向 V4.1-Flash。本次把仓库内模型名统一到 canonical 名（`config.py` 的 `LLM_MODEL_PRIMARY`/`LLM_MODEL_FAST`/`INTENT_MODEL`/`VISION_MODEL` 默认值、`.env.example`、4 个 CI workflow、`deploy/docker-compose.yml`、README、wiki 模型表）
- 视觉链路：V4.1-Flash **原生多模态**，`VISION_MODEL` 从已下线的 `deepseek-v4-flash-vision-exp` 一并切到 `deepseek-flash`（新旧名指向同一模型，纯命名迁移，行为无变化）
- 实测（本 PR 取证）：`deepseek-v4.1-flash` **不是合法模型名**——API 报 `The supported API model names are deepseek-flash, deepseek-v4-pro`；`deepseek-v4-flash` 与 `deepseek-v4-flash-vision-exp` 响应体 `model` 字段均回落为 `deepseek-flash`，实证兼容路由存在
- 背景：B 端（米宝）生产就绪性验收遗留 P1×2（LLM 长序列波动、PP-006 模型能力认知）均判为**模型层**，本次换模型后按 `migao-dev-flow` §13 复跑遗留用例（结论与证据见 `docs/design/agent-production-gap-analysis.md` 对应章节）
- 单测：`tests/test_config.py` 默认值断言 + `test_llm_pipeline.py` / `test_vision_integration.py` 模型名断言同步 canonical 化（case_ids: MC-007、MC-008、CH-021）

### /chat 工作台会话简报默认右侧展开、可向右缩回；FAB 浮窗保持原样（2026-09-08，#3018）

- `admin-web`：修复从侧边栏「米宝 · 在线对话」进入 /chat 工作台页右侧大片空白——会话简报改为**右侧常驻列（docked 变体，无遮罩）**：进入即默认在右侧展开，点击顶部「会话简报」按钮可像抽屉一样向右缩回、再点重新展开；`ChatArea` 新增 `insightDefaultOpen`/`insightVariant` props（`chat/page.tsx` 传 `insightDefaultOpen insightVariant="docked"`）
- `admin-web`：右下角 FAB 浮窗入口保持现有设计不变——overlay 覆盖式抽屉（带遮罩）默认收起、按需展开（`FloatingAssistant.tsx` 不传新 props 即行为不变）
- `admin-web`：WelcomePanel 引导文案同步——「点击顶部会话简报按钮」改为「右侧的会话简报会自动汇总」；行为用例 UI-019 更新 + 生成物重渲染（case_ids: UI-019）

### 企业基础信息页隐藏「登录日志」「修改密码」入口（2026-09-07，#3006）

- `admin-web`：企业基础信息页改为单区块（品牌设置 + 通知设置），移除 tab 切换栏；「登录日志」（无记录）与「修改密码」（未来统一短信码登录）两个 tab 及区块不再渲染，页面副标题不再提「账号安全与登录审计」；后端/Agent 接口保留，待短信码登录落地后再评估移除（行为用例 ST-010，case_ids: ST-010）

### 企业基础设置「启用系统通知」从死开关接线为租户级自动站内信总开关（2026-09-07，#3003）

- `admin-api`：`NotificationService.triggerByEvent`（order_created / after_sales_created / order_status_changed / after_sales_status_changed）与 `triggerForTenantAdmins` 新增租户级开关校验——`tenants.notification_enabled=false` 时自动站内信直接跳过（不解析规则/不查管理员/不落库），历史通知保留；`null`（存量租户）默认视为开启，行为不变（此前开关只落库、不影响任何通知发送，属死开关）
- `admin-web`：企业基础设置「启用系统通知」描述与实际一致——「控制订单、客服等重要事件站内通知的发送；关闭后不再产生新的站内通知（历史通知保留）」，删除「（当前为站内通知开关）」含糊文案（行为用例 ST-009，case_ids: ST-009）

### 岗位权限弹窗「权限分配」与真实侧边栏菜单同构化（2026-09-07，#3002）

- `admin-web`：新增侧边栏菜单配置单一来源 `@/config/menu`（menuGroups/standaloneItems 从 Sidebar.tsx 抽出，Sidebar 与岗位权限弹窗共用），**权限分配弹窗改按真实菜单渲染**——分组=菜单组（智能客服/商品管理/订单管理/客户管理/组织管理），勾选项=菜单项名（米宝 · 在线对话 / AI 客服配置 / 人工客服 / 知识库 / 商品列表 / 加工项管理 / 订单列表 / 售后工单 / 客户列表 / 财务对账 / 员工管理 / 岗位权限 / 企业基础信息），勾选即授予对应权限码（roles 保存权限 ID，前端做码→ID 映射）
- `admin-web`：非菜单操作权限（仪表板查看 / 新增商品 / 商品分类 / 订单详情 / 新增员工 / 商品管理旧码）单独一节「操作权限（不直接对应菜单入口）」；修复弹窗组头双击切换（checkbox 点击不再冒泡到行点击双向触发）
- 修复口径漂移：弹窗原先按后端 resourceType 英文原始码分组 + 展示旧权限名（会话监控/快捷回复/订单退款/系统管理…），与真实菜单完全对不上（行为用例 UI-028，case_ids: UI-028）；E2E roles 用例同步补齐（用例 mock 权限目录从杜撰码改为真实 catalog）

### 经营看板商品销量排行「环比」口径说明可见化（2026-09-07，#3000）

- `admin-web`：商品销量排行「环比」列口径说明**可见化**——表头 title 由含糊的「较上一统计周期(近7天)销量涨跌幅」改为「环比：本期(近7天)销量较上一统计周期(前7天)的涨跌幅」，并在排行表下方新增可见文字「环比 = 本期销量（近7天）对比上一期（前7天）的涨跌幅」；说明不再依赖 hover 提示，用户无需理解「环比」术语即可知道具体与哪个时间段比较（此前大部分用户不理解环比概念、不知道和哪个时间比；行为用例 UI-004，case_ids: UI-004）

### Vision 弱分析守卫误杀 DeepSeek 简洁回答 + MiniMax 配置清理（2026-09-05，#2914 次生）

- `ai-agent-service`：修复弱分析守卫 `len(text) < 20 → 判弱` 的**次生回归**——DeepSeek vision（deepseek-v4-flash-vision-exp）风格简洁，纯色/实体回答（「这张图片是红色的。」「红色」「这是窗帘」）被原判据误杀丢弃，导致含图消息一直走「抱歉，图片分析暂时无法完成」兜底（线上实测 sess_feec97def7124127）。改为仅在**空/无信息碎片/推诿话术**（分辨率限制/看不清/不敢编造等）时判弱，简洁有效回答直通不重试
- `ai-agent-service`：**清理 MiniMax 配置残留**——`MINIMAX_API_KEY/BASE_URL/MODEL` 兼容别名统一改名 `LLM_API_KEY/BASE_URL/MODEL`（PRIMARY 优先 VISION 兜底语义不变），删除已无业务意义的 `MINIMAX_VISION_MODEL/ENABLED` 纯别名；生产 `.env.ai-agent` 的 `VISION_MODEL` 误配 `MiniMax-M3` 已改为 DeepSeek vision（部署切换）
- `ai-agent-service`：回归单测更新（test_config/test_llm_factory/test_vision_integration/test_ontology_vision_grounding，case_ids: MC-007/MC-008/CH-021/ON-002/ON-004）

### 财务对账「本期」时间口径可见化（2026-09-05，#2910）

- `admin-web`：财务对账页「本期收入/本期退款」统计口径可见——打开页面默认把本期（自然月：本月1号~今天）填充到开始/结束日期并生效查询，资金流水/收支汇总/应收对账三个 tab 默认均按本期范围统计；「重置」恢复本期默认视图（此前未选日期时统计全部历史，与「本期」字面不符且口径不可见；行为用例 FN-004，case_ids: FN-001~004）

### 部署触发定时对账 — 防连续快速合并吞掉部署（2026-09-05，#2935）

- `deploy-ai-agent-service`：新增 `schedule`（每 20 分钟）触发的**部署对账**——构建前检查 ACR 中 main HEAD 对应的 `sha-<head7>` 镜像是否已存在；缺失说明该 commit 的 push 触发被 GitHub 吞掉（#2924→#2926 实测 #2926 未触发任何构建），自动补一次完整构建部署；已存在则跳过本轮（含冒烟）
- `deploy-ai-agent-service`：对账复用已有 ACR 登录步骤与凭据（无新增 secrets 引用），仅在 schedule 触发时生效，push / workflow_dispatch 路径不变

### 会话自动关闭加固 — 启动宽限期 + 单次扫描上限（2026-09-05，#2915）

- `ai-agent-service`：会话自动关闭循环增加**启动宽限期**（SESSION_STARTUP_GRACE_S=600s）——进程刚启动（部署/重启）时不立即扫描关闭，防部署过渡期把积压/时间戳未修正的会话一次性批量误杀（#2904 部署后首次扫描 89 会话被一批关闭的实证教训）
- `ai-agent-service`：`close_idle_sessions` 增加**单次扫描上限**（AUTO_CLOSE_SCAN_LIMIT=25）——积压分多轮消化（SQL LIMIT + 客户端截断 + UPDATE 按 ANY(ids) 只动限额内会话），不再出现"一批 89 全关"突袭
- `ai-agent-service`：`SessionService.expire_idle` 透传 limit；回归单测 5 例（case_ids: MC-009/API-001/CH-005/CH-006/DA-004）

### 图片识别修复 — 视觉路由不受文本路由开关影响（2026-09-05，#2914）

- `ai-agent-service`：修复 `LLM_ENABLE_MODEL_ROUTING=False` 时视觉请求误路由到纯文本主模型（deepseek-v4-flash 无法看图）导致图片颜色识别失效——`select_model` 的 `has_vision` 判定移到路由开关短路之前，含图消息恒走 `VISION_MODEL`（deepseek-v4-flash-vision-exp）；线上实证 sess_c40f60ffcae94f2b 色卡图原本只能识别"17 个颜色"概要
- `ai-agent-service`：Vision 弱分析守卫——空/过短/"分辨率限制/看不清/不敢编造"等弱分析重试一次，重试后仍弱则清空不缓存（防一次弱结果经 set_vision_analysis 毒化会话后续轮次）
- `ai-agent-service`：回归单测 20 例（test_llm_pipeline/test_ontology_vision_grounding/test_vision_integration，case_ids: MC-008/CH-021/ON-002/ON-004）

### 米宝「洞察」重构为「会话简报」（2026-09-05，#2897）

- `admin-web`：米宝工作台会话页「洞察」抽屉重构为「会话简报」——从工具台账转业务简报（商家用户不关心 agent 调用了哪些工具）：会话结论（业务语言确定性推导：查询聚合「查询了 N 笔订单」/ 写操作完成 / 失败原因 / 待确认）/ 需要你处理（待确认安全闸 + 失败操作业务化原因）/ 办理结果（明细行带状态徽标/金额/客户，有详情页点击跳转、无则点击追问，跨来源去重）/ 接下来可以问（复用 agent 已生成的后续建议，点击即发送）；删除工具时间线、业务域 ×N 计数、裸编号便签；会话标识弱化保留；入口文案「洞察」→「会话简报」并同步 WelcomePanel 引导（行为用例 UI-019）

### Agent Eval 波动根治（2026-09-05，#2890）

- `agent-eval`：失败波动分类——首次失败后新 session 重试并按指纹判定：`llm-noise`（重试通过→自动放行+记 flake 台账）/ `reproducible`（两次同指纹→确定性回归，禁止 rerun 掩盖）/ `unstable`（两次不同指纹→LLM 发散标注）/ `infra`（传输/超时/5xx→运行级）；替代「失败→人工 gh run rerun 拼人品」的 SOP
- `agent-eval`：flake 台账落盘（`AGENT_EVAL_FLAKE_LOG`，默认 agent-eval-flakes.json）——记录每次噪声放行/复现失败的签名，驱动断言收敛与高波动用例治理；pr-check 上传台账 artifact
- `agent-eval`：`--no-classify` 兼容开关；pr-check 整跑重试语义收敛为「仅兜底运行级故障」，复现型失败直接按签名排查
- `ai-agent-service`：回归单测补分类逻辑 10 例（test_agent_eval_runner.py，case_ids: CH-021/CH-026/OR-001/PR-001）

### Agent Eval 真实验收收口（2026-09-05，#2887）

- `agent-eval`：最后一轮报错即判用例失败——expectations 此前是「任意一轮命中即过」，图片轮崩溃会被前面轮次（success=true 等）掩盖成 100% 通过（假验收，线上 sess_806703a2dcca4059 崩溃漏过多轮验收）；显式预期错误（error.code=/suggestion）的用例豁免
- `agent-eval`：新增行为用例 CH-026「澄清卡后发图不崩溃」（tier normal，图片用云 dev OSS 资产，vision 模型可抓取）；本机真实链路实证 pre-fix 逐字复现 AttributeError / 修复后 vision 识别「彩色渐变条纹」+ 接地搜索
- `ai-agent-service`：新增 tests/manual/accept_drive.py（澄清卡→发图 真实验收驱动器）与 oss_upload_test_image.py（凭证经 .env 读取，无硬编码）；回归单测 test_agent_eval_runner.py（case_ids: CH-021/CH-026）

### 图片消息崩溃修复（2026-09-05，#2884）

- `ai-agent-service`：C 端小布 pending_skill 存在时发图崩溃——`intent_router_node` 对多模态 list content 调 `.strip()` 抛 `AttributeError`（会话 sess_806703a2dcca4059 真实报错），改用 `_get_last_human_text` 提取纯文本后再判消息长度；回归测试锁定（case_ids: CH-021，#2884）

### C 端小布长期记忆系统（2026-09-04，#2815/#2818）

- `ai-agent-service`：C 端用户画像记忆 + 会话末聚合——agent_type 分流（xiaobu/mibao），受控词表 + PII 过滤（手机号/地址/邮箱类记忆不落库），提取提示词禁止 PII
- `ai-agent-service`：记忆注入接线（context_builder/context_manager），合规 API（/memories 查询/删除），会话状态持久化
- `ai-agent-service`：下单地址自动填充——customer_address_query 查历史收货信息预填表单（issue #2815）
- `admin-api`：customerAddress 相关接口；迁移/清理脚本（scripts/cleanup_user_memories.py，默认 dry-run 幂等）；docs/sql/migrations/V20260904__add_agent_type_to_user_memories.sql
- 行为用例 CH-024/CH-025/MC-013~015 与 C 端长期记忆测试补全（case_ids 全声明）

### 澄清轮护栏与图片澄清（2026-09-03，#2790/#2795/#2797/#2800/#2816/#2817）

- `ai-agent-service`：澄清轮次护栏真实生效——连续模糊意图 ≥2 轮转示例兜底（防低学历用户被无限追问，#2797/#2816/#2817）
- `ai-agent-service`：Phase 2 澄清卡承载——B 端 general 澄清卡 + C 端图片候选意图（低学历随手发图，#2790）
- `ai-agent-service`：Phase 2c 图片澄清候选 grounded——关键词检索命中真实商品，不编造（#2800）
- `tests/agent_eval`：agent-eval 图片消息支持——澄清用例可发真图（Phase 3 前置，#2795）

### GB/T 47746-2026 合规（2026-09-01~04，#2779/#2785/#2781/#2788/#2805/#2806/#2808/#2809）

- `docs`：合规差距分析与落地路线（四路审计结论，#2779）；差距矩阵收尾——GB-01~04 全部闭合（3.5/3.6 🟢，#2805）
- `ai-agent-service`：承诺边界工具层收口 M1/M2——确认闸/报价默认价/权限/教学语料（#2782→#2785）
- `xiaobu`：消息级 AI 助手/人工客服来源标识——转人工后人机可区分（#2780→#2781）
- `handoff`：转人工携带 AI 对话上下文快照——人工客服无需顾客复述（#2776→#2778）
- `admin-web`：官网主页 GB/T 47746-2026 遵循国家标准宣称区块（#2787→#2788）
- `admin-api`：M3 服务端取价校验——agent 下单 unitPrice 与 SKU 权威价严格一致（#2806→#2813）
- `admin-web`：B 端 agent 命名统一——米高=平台、agent=米宝（GB-05-B，#2807→#2809）
- `admin-web`：宣传真实性——移除「AI 自动学习/越用越懂/基于知识库精准应答」夸大表述（#2807→#2808）

### 全栈时区统一 UTC+8（2026-09-04，#2810/#2814）

- `ai-agent-service`：营业时间按租户时区判断 + 全栈统一 UTC+8（is_after_hours 时区缺陷，#2810）
- `deploy`：nginx 容器统一时区 UTC+8（补齐全栈时区合规，#2814）

### 财务/看板/RBAC 修复（2026-09-03，#2802/#2803/#2804）

- `admin-api`：operator 内置权限移除 system:manage——角色管理/系统设置归 admin 专属（越权修复，#2802）
- `admin-api`：应收对账差额文案区分应退/少收——已完成退款订单不再误导为少收（P2-1，#2803）
- `admin-web`：今日/昨日销售额舍入口径统一 HALF_UP（P2-3 看板金额舍入不一致，#2804）

### 小布 C 端功能增强（2026-08-31~09-03，#2684/#2686/#2689/#2692/#2729/#2730/#2731/#2733/#2738/#2741/#2746/#2747/#2753/#2756/#2760/#2801/#2812）

- `mini-app`：小布 C 端全量功能合入主干（xiaobu 验收/深蓝金 UI/语音/wechat 修复，#2689）
- `mini-app`：语音输入——默认按住说话、松开发送，可切键盘模式（UI-007，#2686）；会话列表折叠（UI-008，#2692）；会话管理回归纯单列表（UI-006 修订，#2684）
- `mini-app`：C 端表单化交互——FormCard 组件 + __FORM__ 注入协议（CH-009，#2729）；多轮场景用例 + 手机号脱敏（CH-010~012，#2730）；E2E 多轮场景改「选品→下单」贴近真实路径（#2731）
- `mini-app`：C 端 agent 交互改版参考瑞幸——商品卡去下单/预计到手/规格 + 订单确认自提外送/支付方式（#2733）
- `xiaobu`：快捷入口转人工→查物流、退换货→售后咨询 + 物流查询两端收紧（禁物流号直查，#2738）
- `xiaobu`：微信授权手机号绑定——关联名下商户代录历史订单（#2741）
- `xiaobu`：下单流程价格铁律——单价/金额取商品与算料数据，严禁向顾客索要（#2747）；售后创建闭环 aftersale_create 订单号 404 修复（#2746）
- `xiaobu`：已发货订单售后被误转人工——few-shot/skill 补状态门禁认知（#2756）；售后 skill 误走 human_handoff 修复（#2753）
- `xiaobu`：AI 自动引导转人工——结构化信号判定 + 建议卡片 + 用户确认后转（#2760）
- `mini-app`：新增售后链路 E2E（售后咨询→真实后端 SSE 回复，#2801）；新增转人工链路 E2E（我要转人工→SSE human_handoff→C 端横幅，#2812）

### 商家入驻 AI 甄别与主页（2026-08-30，onboarding）

- `ai-agent-service`：商家入驻 AI 自动甄别 + 主页文案重设计（米高×小布）；甄别提示词明确「营业执照/选填字段缺失不构成驳回理由」；测试改用 settings.SERVICE_TOKEN 修复 CI 401
- `admin-api`：Tenant IdTypeAUTO 兼容 PG18 ALWAYS identity（#2658）
- `docs/deployment`：归档商家入驻 AI 自动甄别云验收脚本（20/20 场景可复用，#2660/#2667）

### 生产安全加固（2026-08-30，审计 07 遗留）

- `deploy`：生产安全加固——屏蔽敏感端点/端口绑 loopback/资源限制/readiness（#2662→#2663）
- `admin-api`：审计 07 遗留 P1 修复——登录租户校验/跨租户歧义/会话归属/refresh token 入 HttpOnly cookie（#2668）
- `admin-api`：入驻 IP 限流可被 X-Forwarded-For 伪造绕过修复（#2661→#2664）
- `test(smoke)`：适配审计 07 新契约——refresh token cookie + nginx 屏蔽 health（#2669）；修复 case_ids 注释语法（#2671）

### GitHub 安全基线（2026-08-30，#2659）

- `ci`：workflow 最小权限 + Danger Scan 破坏性变更门禁（#2659）
- `ci`：CI 失败报告去重守卫——6 个自动建 issue 的 workflow 加同标题查重（#2744）
- `ci`：冒烟前等待服务就绪，消除滚动重启瞬态 502 误报（greenlet 部署教训，#2701）
- `ci`：恢复 xiaobu H5 视觉回归 job（#2699）；pr-check E2E/admin-web 超时放宽（慢 runner 误报修复，#2811）

### 看板/数据（2026-08-31，#2677/#2768）

- `admin-web`：PD 精简改版——洞察条一句话经营解读 + 客单价卡 + 绿涨红跌语义色 + 修复 23.8 假数据（#2677）
- `ai-agent-service`：dashboard_stats 商品销量排行 action——米宝可答「哪个商品卖得最好」（DA-006，#2768）

### 下单链路修复（2026-08-29，#2611/#2613/#2615/#2607/#2608）

- `admin-api`：订单/商品/工单/跟进状态报错文案中文化（面向企业客户，#2611）
- `ai-agent-service`：下单漏加工费——order prompt 补强加工项数据来源/结构/金额计算（#2613）
- `admin-api`：订单列表含加工项筛选恒返回空——子查询投影补 processing_info（#2615）
- `admin-api`+`frontend`：SKU/颜色 Long id 精度丢失——序列化为字符串防 JS 失真（#2613）
- `ai-agent-service`：agent 回复中的售后工单英文枚举改为中文业务术语（#2607）；order 卡片载荷归一化，修复「订单」空盒子并支持点击跳转订单详情（#2608）
- `ai-agent-service`：补充 enum_labels 模块专属单测（QA Growth Gate G1 要求）

### 人工客服工作台（2026-08-29，POC xiaobu 增强）

- `admin-api`：转人工创建人工会话 + 消息收发 + 用户端查询
- `admin-web`：人工客服工作台页面（会话列表 + 对话 + 发消息）
- `mini-app`：用户端转人工支持——状态提示 + 人工会话消息 + 发消息分流
- `ai-agent-service`：customer_order 挂载 human_handoff（下单后转人工真正生效）

### H5 入口与部署（2026-08-29~30）

- `deploy`：app.migaozn.com C 端 H5 入口（nginx + compose）；mini-app 添加 H5 构建依赖（plugin-platform-h5/router/taro-h5，#2604）
- `deploy`：frontend 探测域名改 merchant.migaozn.com（#2672）

### 主模型切换（2026-09-01，#2678）

- `ai-agent-service`：主推理模型 deepseek-v4-pro → deepseek-v4-flash（成本/延迟优化）

### 依赖与工程（2026-08-30~09-02）

- `mini-app`：Taro 全家桶 3.6.40 → 4.2.1 整组升级工程级迁移（#2704）
- `ci`：actions/checkout 4→7、setup-java 4→6、setup-python 5→7、setup-node 4→7、upload-artifact 4→7、docker/setup-buildx-action 3→4、actions/github-script 7→9、gitleaks-action 2→3
- `admin-web`：axios 1.15→1.20、sonner 1.7.4→2.0.8、tailwind-merge、msw 2.13.6→2.15.0、@testing-library/*、@types/node 升级
- `ai-agent-service`：pydantic、pydantic-settings、uvicorn、greenlet、pyjwt、pytest-mock、python-dotenv 升级
- `admin-api`：jacoco、lombok、poi-ooxml、dysmsapi20170525、jjwt、mapstruct、maven-enforcer-plugin 升级
- `tests`：@playwright/test 1.60.0→1.62.1
- `gitignore`：Taro 本地私有配置 project.private.config.json（防真实 AppID 入库，#2698）
- `chore`：去除 junshi/军师/二郎神 内部代号命名（#2648）；仓库精简——删除 AI 标识/历史遗留/一次性产物（#2646→#2647）
- `scripts`：新增 git worktree 多分支工作区脚本 + 分支治理规范（#2725）；dev-flow 同步 Agent Eval 重试命令 + 部署验证端点修正（#2702）；Troubleshooting 增补 CI/本地环境差异（Taro dotenv 白屏 + Playwright 平台基线，#2700）

### 安全加固（POC 显式化）

- `admin-api`：SmsService 增加 `@PostConstruct` 启动警告——`sms.bypass-code` 非空时打印醒目 WARN（POC 模式万能验证码显式化，技术债 Issue #2616）
- `admin-api`：`verifyCode` 命中万能验证码的日志由 INFO 升级为 WARN（含 Issue #2616 指引）
- `ai-agent-service`：`.env.example` 的 `DEBUG` 默认值改为 `false`，并注释说明生产禁用与本地开发用法
- `ai-agent-service`：`[tool-exec]` 错误日志的 `tool_args` 经 `LogSanitizer.sanitize_tree` 递归脱敏（手机号/邮箱/敏感 key 打码）
- `ai-agent-service`：记忆提取增加 PII 过滤（`_filter_pii`）——手机号/地址/邮箱类记忆不落库，提取提示词禁止 PII

### 发布体系（2026-08-30）

- 镜像 tag 从时间戳改为 **git SHA 前 7 位**（不可变、可追溯）；`latest` 仅测试环境
- 新增 `release.yml`：手动触发打 semver tag（patch/minor/major）+ GitHub Release notes；tag 触发版本镜像构建（vX.Y.Z）
- deploy-* workflow 双模式：push/tag 自动部署**测试环境**（当前 SWAS）；workflow_dispatch 支持填 `image_tag` **回滚/指定版本**（跳过构建）
- 新增 `deploy-prod.yml`：未来**生产受控发布**入口（GitHub Environment 审批 + 指定版本），当前未启用
- 新增 `docs/deployment/production-deployment.md`（生产部署方案设计）与 `docs/deployment/rollback.md`（回滚 Runbook）
- deploy-frontend 补 concurrency group + 部署后域名 200 探测
- swas-deploy-ci.sh 支持传 IMAGE_TAG

### 开源治理

- 新增 `SECURITY.md`（安全漏洞报告政策与响应承诺）
- 新增 `CODE_OF_CONDUCT.md`（贡献者公约 2.1）
- 新增 `CHANGELOG.md`（本文件）
- 新增 `.github/dependabot.yml`（Maven / pip / npm / GitHub Actions 依赖自动更新）
- 新增 `.github/FUNDING.yml`（赞助入口占位）
- 新增 `CONTRIBUTING.md`（外部贡献者指南：Issue 先行 / 分支 / TDD / PR 门禁）
- `README.md` 全面修订：修正文档矛盾（工具 31、Controller 27、Service 23、Entity/Mapper 44、Boot 3.3.9、表 41 等）、RAG 按决策 D1 标注暂不开放、新增 CI/License badges
- `pr-check` 新增 Secret Scan (gitleaks) job
