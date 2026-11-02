# #4299 真库取值分布复核（2026-09-18，第 1 次独立复核）

> 复核对象：issue #4299 的证据链 ②「真库取值分布（决定性）」+ 其验收判据 1「必须覆盖真库里已观测到的每一个取值（含 `(无)`）」
> 环境：云 dev 库 `ai_customer_service`（阿里云 RDS，本地 admin-api 同源）。凭据从 `backend/admin-api/.env` 读取，**未写入任何产物**。
> 复跑：`./run.sh`（依次跑 `survey.sql` + `survey2.sql`；也可 `./run.sh survey2.sql` 单跑）。
> 原始输出：`survey-output.txt` / `survey2-output.txt`。
> 只读查询，无写操作。被测口径锚点：`main @ dd5c5c54`。
>
> **可复现性**：`./run.sh` 在 worktree 里复跑，逐值一致
> （`(无)`566 / 可达面 68 / A1=561 / A4=2 / `pricing_type` per_meter=93 + fixed=11）。
> 脚本从 `backend/admin-api/.env` 读凭据（worktree 无该文件 ⇒ 自动回落主工作区），**密钥不入产物**。

---

## 一句话结论

**issue #4299 的代码级诊断成立，但它的验收判据 1「覆盖 (无) 那 566 条」建立在一个错误推论上** ——
那 566 条里 **564 条结构上永远进不了 `calcInfo`**（连 `processing_info` 都没有），
真正可达的只有 **2 条**。而「改判据」的字段选择，实测**只有加工项 `pricingMethod` 成立**，
用户原选的 `products.pricing_type` 在可达面上会**漏掉 17/68 条**。

---

## 一、复核上一会话的读数（第 1 轮 [1]/[7]）

`order_items.processing_info->>'sellingMethod'`（`deleted=0`，共 784 行）：

| sellingMethod | n | 上一会话读数 |
|---|---|---|
| `(无)` | **566** | 566 ✅ |
| `bulk_cut` | **160** | 160 ✅ |
| `散剪` | **41** | 41 ✅ |
| `full_roll` | **6** | 6 ✅ |
| `整卷` | **3** | 3 ✅ |
| `散剪售卖` | **3** | 3 ✅ |
| `散剪按米` | 1 | 1 ✅ |
| `散剪·按米购买` | 1 | 1 ✅ |
| `散剪(bulk_cut)` | 1 | **上一会话未列** |
| `cut` | 1 | **上一会话未列** |
| `散剪（按米裁剪）` | 1 | **上一会话未列** |

`processing_orders.items_snapshot` → `bulk_cut × 31`：**逐值复核一致** ✅

⇒ **上一会话的读数基本准确，但漏了 3 个取值**（`散剪(bulk_cut)` / `cut` / `散剪（按米裁剪）`）。
按判据 1「必须覆盖每一个已观测取值」，这 3 个也必须在覆盖清单里。

---

## 二、决定性发现：那 566 条里 564 条**结构上不可达**

`buildSnapshot()`（`ProcessingOrderService` 第 762-770 行）对
`extractProcessingItems(processing_info)` 为空的订单行**直接 `continue`** ——
即：**没有 `processingItems` 的订单行永远进不了加工单快照，也就永远走不到 `calcInfo`**。

第 1 轮 [2] 的总量对照：

| 口径 | n |
|---|---|
| `order_items` 总数（`deleted=0`） | 784 |
| 带 `processing_info` | **223** |
| 带**非空** `processingItems`（= 可达面） | **68** |

第 2 轮 [A]：把 566 条按「能否进 calcInfo」拆开 ——

| 形状 | n |
|---|---|
| A1 `processing_info` 为 NULL（**永不进快照**） | **561** |
| A2 无 `processingItems` 数组（**永不进快照**） | 2 |
| A3 `processingItems` 空数组（**永不进快照**） | 1 |
| A4 可达 calcInfo，且有 `per_meter` 加工项 | **2** |
| A5 可达 calcInfo 但无 `per_meter` 加工项 | **0** |

⇒ **「(无) 的口径要显式定义」是一个伪需求**：564 条不可达，2 条可被下方判据自动覆盖，
**需要为 `(无)` 单独定义口径的条数 = 0**。
（上一轮扫描的 `[4]` 查询我写错了 —— `jsonb_typeof(NULL) <> 'array'` 求值为 NULL、分支穿透，
把 564 条 NULL 算进了「有 processingItems」；已在第 2 轮用 `IS DISTINCT FROM` 修正。
**这条也说明：一次写错的 SQL 能造出与事实相反的分布结论** —— 复核不是可选项。）

---

## 三、判据字段选择：实测只有「加工项 `pricingMethod`」成立

可达面 68 条订单行，两种候选判据的命中对照：

| 判据 | 命中 | 漏 |
|---|---|---|
| **加工项 `pricingMethod == 'per_meter'`** | **67 / 68** | 1 |
| 商品 `products.pricing_type == 'per_meter'` | 50 / 68 | **18** |

按 `products.pricing_type` 分组（第 2 轮 [D]）：

| 商品的 pricing_type | 订单行数 | 其中**也有** per_meter 加工项 |
|---|---|---|
| `per_meter` | 50 | 50 |
| **`(商品缺失/软删)`** | **12** | **11** ← 判据查不到商品 ⇒ 漏 11 条 |
| **`fixed`** | **6** | **6** ← 商品定价 `fixed` 但加工项按米 ⇒ 漏 6 条 |

⇒ 商品级 `pricing_type` 是**商品**的属性，而决定订单行数量口径的是**该单实际选的加工项**。
实测 6 条 `pricing_type=fixed` 的商品，其订单行的加工项仍是 `per_meter`、订单数量仍是米数 ——
**用商品字段判会把这 6 条判成非米数**（正是 #4299 要治的「拿 A 字段比 B 口径」同族）。

### 判据只当标志，取值必须用订单行 quantity

第 2 轮 [F] 的 4 条 `full_roll`（整卷）单，加工项 `per_meter` 的 quantity 与订单 quantity：

| 订单行 id | 订单 quantity | 加工项 pricing:qty |
|---|---|---|
| `e8c4c0e8…` | 3.00 | `per_meter:3` |
| `b863b991…` | 3.00 | `per_meter:3` |
| `372655a6…` | 3.00 | `per_meter:3` |
| **`7e6f2a1c…`** | **112.00** | **`per_meter:1`**,`per_piece:1` |

⇒ 第 4 条：订单数量 **112**，而那条 `per_meter` 加工项的 quantity 被写成了 **1**。
**若取值也用加工项 quantity ⇒ 112 米的单会得到「应做 1 米」⇒ 报工上限 1 ⇒ 假完工**（同族红线）。
⇒ **判据用加工项的 `pricingMethod`（标志），取值用 `OrderItem.quantity`（值）。**

另：4 条整卷单**全部**带 `per_meter` 加工项且订单数量是米量级 ⇒
「整卷的 quantity 是卷数、会被误映射」这个我在选型时提出的顾虑，**实测不成立**
（商家后台建单表单 `frontend/admin-web/src/app/(dashboard)/orders/new/page.tsx` 本就无条件把 `line.quantity` 当 `fabricMeters` 传入 —— 按 `fabricMeters` 符号检索，不写裸行号）。

---

## 四、对 #4299 验收判据的修正建议（实测级）

| 原判据 | 修正 |
|---|---|
| 1. 覆盖真库**每一个**取值，含 `(无)`（566 条） | 改为：**可达面 68 条**为对象。覆盖清单 = 已观测 11 个取值（含上一轮漏掉的 3 个）；`(无)` **不需要单列口径**（564 不可达 + 2 条被判据覆盖）。判据字段 = 加工项 `pricingMethod`；取值 = `OrderItem.quantity` |
| 2. 红证用 `bulk_cut` | 保留，且**必须同时覆盖**：`bulk_cut`(52 条，可达面最大类) / `散剪` / `full_roll`；负例 = 唯一不命中的 `per_sqm` 刺绣单（`286229cf…`，`selling_method=散剪`、无商品）⇒ 断言保持 `fallback` |
| 3. 口径写进注释 | 保留，并补一条：`products.pricing_type` 与加工项 `pricingMethod` **也是两个不同层级的字段**（实测 6 条 fixed 商品 + 11 条商品缺失会因此漏判） |
| 4. 端到端红证 | 保留（真栈建单）。**注意**：单测里 `productionOperationQtyClient` 是 mock 的，只能证 `calc_info` 是否带 `fabric_meters`，证不了「米类 qty == 订单米数」 |
| 5. 不回归 | 保留 |

## 五、给用例库的影响（§14）

`processing-order.yml` 的 **PG-022**（第 921 / 926 行）现在写着
「米类 12.3(`fabric_meters`)、折类 24(`pleat_count`)」+「`per_meter` 时映射为 `fabric_meters`」：
- 「`per_meter` ⇒ 映射」这半句**要改判据字段**；
- 「折类 24(`pleat_count`)」这半句与 #4208 更正后的口径（折/幅/套 = `fallback 1`）**直接矛盾**，**现在是错的**。
