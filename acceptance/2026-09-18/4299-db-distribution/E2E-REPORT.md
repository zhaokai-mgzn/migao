# #4299 端到端验证报告（真库 + 真栈，受控 A/B）

> 判据来源：issue #4299 验收判据 4 + 判据修正章节；判据字段选型的实测依据见 `FINDINGS.md`。
> 复跑入口：`./run-e2e.sh`（起分支栈 + 跑 A/B）；原始产物：`e2e-*.json` / `e2e-ab-output.txt`。
> 被测代码锚点：**RED** = `main @ 79e54c0f`（未修，本机常驻 admin-api :8080）；**GREEN** = 分支 `fix/4299-qty-meter-mapping`。
> 环境：云 dev 库 `ai_customer_service`（阿里云 RDS）+ 本机 ai-agent :8001（**本单不改 ai-agent ⇒ 两侧共用，不构成变量**）。
> 结论：**GREEN 达成，RED 复现，非回归项保持** —— 但如实登记两处形态边界（见文末「局限」）。

---

## 一、受控 A/B（唯一变量 = 代码版本）

两张单**同租户、同加工单路线、工序集合逐道相同、订单数量同为 3.00**，
唯一差别是生成时的代码版本：

| | 代码版本 | 加工单号 | 订单行数量 | 加工项 | 米类工序 | 折/幅/套 |
|---|---|---|---|---|---|---|
| **RED** | `main` 未修 | `JG-20260918-3967` | 3.00 | `锁边` / `per_meter` | **1.00 / `fallback`** ❌ | 1.00 / `fallback` |
| **GREEN** | 分支已修 | `JG-20260918-3104` | 3.00 | `锁边` / `per_meter` | **3.00 / `fabric_meters`** ✅ | 1.00 / `fallback` |

两侧工序逐道对照（RED 取自 `recon-output.txt`，GREEN 取自 `e2e-green-operations.json`；
两侧工序名与 seq **逐道相同**，唯一差别是 qty / qty_source）：

```
RED   （JG-20260918-3967，12 道，全部 qty=1.00 / fallback）
   1 精裁-布   米 1.00  fallback       7 定型-布   米 1.00  fallback
   2 布三边    米 1.00  fallback       8 复烫-布   米 1.00  fallback
   3 拼1次-布  幅 1.00  fallback       9 布帘车被 米 1.00  fallback
   4 韩褶-布   折 1.00  fallback      10 外帘打卷 套 1.00  fallback
   5 上车布-布 米 1.00  fallback      11 外帘装袋 套 1.00  fallback
   6 熨烫-布   米 1.00  fallback      12 外帘发货 套 1.00  fallback

GREEN （JG-20260918-3104，12 道）
   1 精裁-布   米 3.00  fabric_meters  7 定型-布   米 3.00  fabric_meters
   2 布三边    米 3.00  fabric_meters  8 复烫-布   米 3.00  fabric_meters
   3 拼1次-布  幅 1.00  fallback       9 布帘车被 米 3.00  fabric_meters
   4 韩褶-布   折 1.00  fallback      10 外帘打卷 套 1.00  fallback
   5 上车布-布 米 3.00  fabric_meters 11 外帘装袋 套 1.00  fallback
   6 熨烫-布   米 3.00  fabric_meters 12 外帘发货 套 1.00  fallback
```

**逐条判据**：

| # | 判据（issue #4299） | 结果 |
|---|---|---|
| 1 | 米类 `qty` == 订单米数 | ✅ 3.00（修复前 1.00） |
| 2 | 米类 `qty_source != "fallback"` | ✅ `fabric_meters` |
| 3 | 折/幅/套 保持 `qty=1` + `qty_source=fallback`（#4208 更正口径，**不得回归**） | ✅ 逐道保持 |
| 4 | 条件工序 `拼1次-布` 仍在（#4230 已验通过面，不得回归） | ✅ seq=3，位置未变 |
| 5 | `factor=1.70` 仍作用于该部位全部工序 | ✅ 逐道 1.70 |

## 二、本轮另取的一次独立 RED（第二观察，非复用上一会话读数）

用**未修的 main 代码**（:8080）对另一张真库订单 `78d207ac…`（订单数量 **2.00**、`bulk_cut`、
加工项 `锁边/per_meter`）生成 `JG-20260918-3968` ⇒ `GET /operations` **11 道全 `qty=1.00 / qty_source=fallback`**，
其中 **8 道米类本应为 2.00**（`e2e-red-operations.json`）。

⇒ RED 有两个独立观察（本轮的 qty=2 单 + 上一会话的 qty=3 单），均在同一真库上复现同一形态。

## 三、独立 oracle（把「Java 送对 calc_info」与「端点答得对」拆开）

直调 ai-agent 端点、**绕过 Java**，喂 `calc_info={"fabric_meters":3}`
（`POST http://localhost:8001/api/internal/production/operation-qty`；复跑 `./oracle.sh 3`）：

```json
{"精裁-布": [3.0, "fabric_meters"], "布三边": [3.0, "fabric_meters"],
 "韩褶-布": [1.0, "fallback"],      "外帘装袋": [1.0, "fallback"]}
```

⇒ **ai-agent 半边是对的**；缺陷 100% 在 Java 侧 `calc_info` 是否送出 `fabric_meters`。
这也独立钉死了 GREEN 的期望值（与 §一 实测逐值一致）。

## 三·补、产物脱敏（Secret Scan 实测触发，已修）

`e2e-*-operations.json` 是真栈响应的原样落盘，其中含加工单的 **`qr_token`**（32 位 hex，工人扫码报工用）。
首轮 CI 的 **Secret Scan (gitleaks) 判红**（`generic-api-key`，命中 `acceptance/.../e2e-red-operations.json`）
—— 该值属**凭据类**、与本单断言无关（断言只用 `qty` / `qty_source` / `unit`），故**就地脱敏**：
`"qr_token": "<redacted:32hex-dev-token>"`（键名保留以说明响应形态，值置占位）。

⚠️ 因 gitleaks-action 以 `fetch-depth: 0` **扫描 PR 的提交区间**（报告里带 `commitSha`），
「补一个脱敏 commit」**清不掉已入库提交里的命中** ⇒ 本分支已**重写提交历史**（脱敏发生在被扫的提交内），
`verdict*.jq` 的判定在脱敏前后**逐值一致**（已复跑：GREEN `米类[3.00/fabric_meters]`、RED `米类[1.00/fallback]`）。

## 四、局限（如实登记，勿读成已覆盖）

1. **不是同一张单的前后对比**：加工单按订单幂等（`generateOne` 的「已有加工单请勿重复生成」+
   `status=confirmed` 门禁）⇒ 同一订单无法既跑 RED 又跑 GREEN。故用**两张同形订单**
   （同工序集合、同订单数量 3.00）作配对；工序集合与数量已逐道核对相同，代码版本是唯一有意变量。
   附带的**无意为变量**：两张单的门幅/颜色等订单字段可能不同，但它们不进入 `calc_info` 的米数判据
   （判据只看加工项 `pricingMethod` + 订单行 `quantity`）。
2. **负例（`per_sqm` 刺绣单）无法在真栈跑**：唯一不命中新判据的订单行 `286229cf…` 属于订单
   `e495c2d5…`，其 `status=pending` ⇒ 被 `generateOne` 的状态门禁拒绝（须 `confirmed`）。
   故负例**只在单测层覆盖**（`nonPerMeterProcessingItemDoesNotMapOrderQuantity` +
   `processingItemsWithoutPricingMethodKeyDoNotMap`），**真栈负例未做**。
3. **`折/幅/套` 的 `fallback` 在真栈是「事实」而非「断言」**：本轮只读到了它们确为 `1.00/fallback`，
   但没有任何单测能证端点在该情形下的行为（单测里客户端是 mock，且共用桩的折轴是平行真值）——
   这是 #4273 的领地，本单不改。
4. 本轮 E2E **在共享云 dev 库上写入**了 2 张加工单（`JG-20260918-3968` / `JG-20260918-3104`）
   并消耗了 2 张 `confirmed` 订单（`78d207ac…` / `8614224ecd…`）—— 已在 `recon3.sql` 留痕可查。
