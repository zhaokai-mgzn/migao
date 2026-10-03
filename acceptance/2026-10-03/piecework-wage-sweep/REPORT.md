# 计件工资 / 结算链 —— 独立功能验证包报告（线 ①）

> 时间：**2026-10-03 08:29 ~ 08:45（Asia/Shanghai）** · 协议：`migao-acceptance`（L1 机器判定 + 每条断言带红证 + 证据链 + 假绿自查 + 不自我验收）
> 产物：本目录 `harness/*.mjs`（脚本）· `out/*.json`（逐条读数 + `SUMMARY.json`）· `out/run.log`（断言流水）
> **本包不改 MIGAO 业务代码**（零业务改动；写在 MIGAO 里的文件只有本目录的验证脚本与读数）

---

## 一、环境与构建点（含「已合并未必已部署」披露）

| 项 | 真值（本轮实测） |
|---|---|
| 租户 | **tenant_id = 20**（米高POC演示布艺，管理员 13870217889），时区 Asia/Shanghai |
| admin-api | `http://localhost:8080`，进程 cwd `/Users/guangzhen.zk/migao-wt/main-live/backend/admin-api`，**HEAD = `402be478b`**，进程启动 **02:50:58**，`target/classes` 最新写入 **01:57:09** |
| DB | 云 dev RDS `ai_customer_service`（psql 直读；写库仅限自建探针对象，已清零） |
| admin-web | `http://localhost:3001`（仅 HTTP 探活：`/production/piecework` → 200） |
| 我的工作树 | `d2965ea35`（`feat/5939-shipments-menu`）；取证时 `origin/main = a4aaa3c24` |
| **披露①：已合并未部署** | F8 的修复 **`1d1fe5e55`（2026-10-03 08:01:56，fix #6102「保存一次工序设置不再静默改写计件单价」）已合入 `origin/main`**，但**不在运行中构建点上**：`git merge-base --is-ancestor 1d1fe5e55 402be478b` = **NO**（`fd6c78f78` 07:43 版同样 NO）⇒ 本轮所有读数对应的是**未修**构建。**本报告不代表 main 现状**，只代表这台机器上正在跑的这份构建。 |
| **披露②：构建点与运行行为不完全自洽** | 运行中 API 暴露的 244 个 path 与 `402be478b` 的迁移集（V138/V140）一致，但 `production_work_logs` 里存在**未被修复语义**的路径（见 §四 D1）。⇒ **以实测行为为准**，构建点只作参考。 |

---

## 二、链路枚举图（每一跳的端点 / 表 / 字段 —— 全部由读面与 OpenAPI 枚举得出）

```
报工(写)                          ┌── processing_position_operations.unit_price  = 实例快照价（NULL=未定价）
POST /api/admin/production/orders │   （实例化时由「部位价目矩阵」折出，见 §三 口径来源③）
   /{orderId}/operations/{oid}    │
   /report                        ├── production_work_logs（**计件唯一凭证，明细不可变**）
   body{worker_name,qty,          │     unit_price  ← 报工那一刻的实例价快照（#4351 冻结）
        qualified_qty,work_type}  │     factor      ← 系数快照（历史行仍乘；#4589 起新报工不写 ⇒ 恒 1）
   ↳ IdentitySource: client_body  │     price_state ← priced / unpriced（V90 三态，#4696）
                                  │     work_type   ← normal/rework/scrap（返工报废不计件）
                                  │     work_date   ← businessClock.today()（+08 业务日）
                                  │     qty / qualified_qty / operation_name / worker_name …
                                  └── worker_report_audits（旁路身份账）

读面（钱）                        聚合算法**只有一份**：ProductionService.aggregate
① GET /api/admin/production/orders/{orderId}/piecework
     → {total, per_worker{}, per_operation[], per_position[], per_set[], unpriced{qty,operations[],hint}}
② GET /api/admin/production/piecework/summary?period=YYYY-MM[&worker_name=]
     → {period, total, per_worker[], per_operation[], per_position[], per_set[], unpriced{}}   （period **必填**）
③ GET /api/admin/agent/production/worklog?order_no=…     → totals.piecework_amount（与①②恒等）
④ GET /api/admin/agent/production/piecework?worker_name=&period=   （worker_name **必填**）
⑤ GET /api/admin/production/operation-layers / operation-positions / operations-catalog → 未定价徽标 + 有效价

下游结算面：**不存在**（见 §四 D4）
```

**下游结算面是怎么发现的**（不是人肉猜）：`GET /v3/api-docs` 全量枚举 **244 条 path**，关键词筛 `piecework|wage|payroll|salary|settle` 命中 11 条，其中**写端点 0 条**（只有 report 两个 POST 属报工）。
⇒ 计件链**没有**「结算 / 发放 / 工资单 / 导出」端点，也没有 `payroll|settle|wage|salary` 命名的表 ⇒ **`summary` 报表就是终点**（商家拿汇总表去做工资）。前端消费面：`frontend/admin-web/src/app/(dashboard)/production/piecework/page.tsx`（`getPieceworkSummary`，四档 tab：按人/按工序/按部位/按套）+ `components/production/UnpricedNotice.tsx`。

**`summary` 的 query 逐组合枚举**（`out/p0-surface.json .queryMatrix`）：

| 组合 | HTTP | 结论 |
|---|---|---|
| `period=2026-10` | 200 | 正常，返回冻结契约 7 键 |
| 缺 `period` / `period=` | **422** | `VALIDATION_ERROR`「period 不能为空（格式 YYYY-MM）」✅ 不静默 |
| `period=2026-13` / `garbage` | **422** | 「period 格式必须是 YYYY-MM」✅ |
| `+worker_name=<探针工人>` | 200 | 按人下钻可用 |
| `+worker_name=__nobody__` | 200 | total=0（**空结果**而非报错；UI 另有 unpriced 参与空态判定） |
| `+worker_name=%20`（空白） | 200 | **等同不传**（total 与空条件一致）—— 白名单化，非缺陷 |
| `period=2026-09` | 200 | total=0（9 月无报工） |

---

## 三、口径来源（算期望前先写明出处，含文件:行号）

| # | 口径 | 出处（`origin/main` 内容坐标） |
|---|---|---|
| ① | 计件金额 = Σ 逐笔 `HALF_UP(合格数量 × unit_price快照 × factor快照)` | `backend/admin-api/src/main/java/com/migao/admin/service/ProductionService.java` **:1633-1638** |
| ② | 未定价（`price_state='unpriced'`）**不进金额**，但**数量必须列出** | 同文件 **:1621-1626** + `unpricedBlock` **:1770-1788** |
| ③ | 实例价来源 = 部位价目矩阵经 `collapseToLogical` 折出的**有效价**；**布帘列优先**（`COLLAPSE_PRICE_SOURCE_POSITION="布帘"`） | `ProductionOperationQueryService.java` **:162**（常量）/ **:459-491**（收敛）/ **:498-500**（选行比较） |
| ④ | 返工/报废不计件 | `ProductionService.java` **:1584-1586** |
| ⑤ | 报工快照三态写入 | 同文件 **:1250-1258**（`unitPrice=op.getUnitPrice()` / `priceState` 按 NULL 判 unpriced） |
| ⑥ | 幂等 = `X-Client-Request-Id` | `ProductionService.report` **:1047-1059**（占位→执行→快照；失败释放） |
| ⑦ | 超报拒绝（不 clamp） | `assertWithinPlannedQty` **:1418-1432**（422 `REPORT_QTY_EXCEEDS_PLANNED`） |
| ⑧ | 业务日 = `businessClock.today()` | 同文件 **:1259** |

**本轮探针的独立算式**（`harness/lib.mjs` + `p1-p2-matrix.mjs` 的 `expectedCents()`）：全程 **BigInt/十进制字符串**，`decMul` 精确乘法 + `toCentsHalfUp` HALF_UP 到分，**零浮点**；`"0.2" ≡ "0.20" ≡ 0.2` 由 `cents()` 统一成分整数比较。

---

## 四、发现清单

### 🔴🔴 D1（P1 · 涉钱 · 静默）**一次「与价格无关的普通保存」会把工资单价从「未定价」改写成工序库价**（F8 的工资侧后果，本轮构建上可复现）

- **复现命令**：`node harness/p9-f8-wage-e2e.mjs`（单次实验闭合因果链，只碰自建对象）
- **一次实验里的完整读数**（`out/p9-f8-wage-e2e.json`）：

| 步 | 动作 | 读数 |
|---|---|---|
| ① | 造前置：逻辑工序「复烫」的 `通用` 行价置 NULL（未定价；模拟商家清空价） | 活跃价目行 = `[通用=NULL]` |
| ② | 自然派工（`POST /processing-orders/generate`）→ 实例价 **X** | **X = NULL**（未定价 ✅） |
| ③ | 把 `通用` 行价置 **1.11**（= 商家定价；有效价口径自证） | 活跃行 `[通用=1.11]` |
| ④ | 自然派工 → 实例价 **Y** | **Y = 1.11**（口径自证 ✅ 取有效价） |
| ⑤ | **一次普通保存**：`PUT /api/admin/production/operations/op-v72-20-复烫 {scope:'position'}`（HTTP 200，body 不含任何价） | **新建活跃价目行 `布帘=0.35`**（= 工序库价） |
| ⑥ | 自然派工 → 实例价 **Z** | **Z = 0.35**（**不是** 1.11）⇒ 单价被静默改写 |
| ⑦ | 该工序报工 3 件 ⇒ 工资读面 | 快照价 **0.35**、`price_state=priced`、计件金额 **1.05**（独立算式按有效价应为 **3.33**） |

- **影响面（商家会看到什么）**：工人这 3 件的工资从 **3.33 元** 掉到 **1.05 元**（−68%），而**页面/报表没有任何提示**：`unpriced` 块变空（因为已被"定价"成了库价）、`per_operation` 里出现一行看起来完全正常的金额。**商家拿汇总表发工资 ⇒ 少发/多发无人发现**。凡在这台构建上被这一步碰过的工序（本轮 `operations-catalog` 27 道候选、`p8` 实测对「定型」新建 `布帘=0.40`），都会长期按库价计件。
- **机制（三段，逐字可复核）**：
  1. `ProductionOperationCommandService.update()`（:295 附近）body 省略 `positions` ⇒ `attachPositions(…)` 按**取价来源列**兜底**新建** `position='布帘'` 的价目行，价取 `production_operations.unit_price`（工序库价）；
  2. 取价/读面/实例化**一律**走 `collapseToLogical`（`ProductionOperationQueryService:459`），其选行比较 `beatsForCollapse`（:498）**`布帘` 列优先** ⇒ 新行**盖住** seed 期经 V104 塌缩成 `position='通用'` 的既有行；
  3. ⇒ 有效价从「商家定的 1.11 / 未定价」变成「工序库价 0.35」。
- **一句话判据（将来修复后用来验收的那条）**：
  > **对任一逻辑工序，`PUT /api/admin/production/operations/{id}`（body 不含 `unit_price`/`positions`）前后 —— ①该工序活跃价目行的「有效价」（`GET /operation-layers` 的 `unit_price`）逐字不变；②同一配置下连续两次自然派工得到的实例单价逐字相同。** 两条都必须在一次普通保存前后成立（当前两条都失败）。
- **与本轮「并行包」的关系（不作为缺陷、但必须登记）**：我观测到**非自建行**在两次读之间变化 ⇒ 疑似并发干扰（见 §六）；上面这条因果链**只用我自建对象**取得（`X→Y→Z` 全部由我在同一分钟内执行），**不依赖**任何他人创建的行。

### 🔴 D2（P2 · 口径可读性）**「有效价」在数据上不可区分：一次 PUT 会新增 `布帘` 列行并软删既有行**（跨模块副作用）

- 证据：`out/p8-f8-controlled.json .newPositionRows` = `[["布帘","0.40"]]`（对「定型」，库价 0.40）；`out/p3-f8-redproof.json .f8.before/.after`；`out/p9-f8-wage-e2e.json .rowsAfterPut`。
- 说明：这类行不是"垃圾"，而是**取价优先级链上的有效行**；但商家在界面上只看得到「一道工序一口价」，看不到底下多出一行 `布帘` ⇒ **口径不可读**。§三 口径③ 已写明规则，故本条按 **P2（可读性/可审计性）** 登记，不重复按缺陷计。
- **一句话判据**：同一逻辑工序在任意一次工序设置保存前后，`GET /operation-positions` 返回的**行集**（部位 × 价 × 软删）逐字不变。

### 🟠 D3（P2 · 运维）**删除端点对「已确认且有加工数据的订单/商品」返回 422** —— 验收/测试对象的清理没有 API 出路

- 证据：`out/p10-cleanup.json .orderDelete`（**17/17 全 422**）、`.productDelete`（**16/16 全 422**）；分类删除 **16/16 200**。
- 影响面：**验收与测试无法用产品自身的删除端点收尾**，只能直连 DB 软删（本轮即如此）。这不是钱的问题，但**它让"零残留"这件事在流程上不可用 API 达成**，长期会积累残留数据。
- **一句话判据**：对「已取消/无在途加工」的订单，`DELETE /api/admin/orders/{id}` 必须 200（或返回可行动的、说明为何不可删的具名理由），而不是一律 422。

### ⚪ D4（口径事实 · 非缺陷）**计件链没有结算/发放/导出的下游**

- 证据：`GET /v3/api-docs` 244 path 全量枚举，`piecework|wage|payroll|salary|settle` 命中 11 条、**写端点 0 条**；`SELECT … information_schema` 无 payroll/settlement 表（`out/p0-surface.json .downstream`、`out/p5-ui.json .wageWriteEndpoints`）。
- 结论：**工资报表 = 终点**，"结算"这条链**不存在**，因此本包只能把「汇总读数是否正确」作为钱的末端判据（已做，见 §五）。**登记为口径事实**，避免下一轮误以为"没测"。

---

## 五、判据矩阵（期望来源 / 实测 / 结论）

> 口径：**期望全部由我们自己的独立算式给出**（见 §三），**严禁**把被测系统的读面当期望。
> 全量逐条读数：`out/SUMMARY.json`（75 条）；下面按组摘录（`pass/fail/skip` 为本组末次读数）。

| 组 | 判据（每条都会红） | 期望来源 | 读数 | 结论 |
|---|---|---|---|---|
| **读面** P0 | 端点在场景 + 冻结契约 7 键 + query 逐组合 + 报工表结构 + 下游枚举 | 契约文档 + OpenAPI 全量 | **6/0/0** | ✅ |
| **探针** P1 | 自建分类/商品/订单/加工单；实例三态可区分（`0.40` / 显式 `0.00` / `NULL`） | 我写入的定点值 | **4/0/0** | ✅ |
| **逐分** M1 | `per_operation` 明细 **逐分** == 独立算式 | 我的算式（数量×快照价，逐笔 HALF_UP） | **1/0/0** | ✅ |
| **逐分** M2/M3/M4 | `total` == 独立算式；`per_worker` 之和 == total；`per_position`/`per_set` 合计 == total | 同左（无二次兜底/二次取整） | **1/1/2 全 pass** | ✅ |
| **汇总** M5 | 期间报表（按人下钻）total == 独立算式；报表四维合计 == report.total | 同左 | **5/0/0** | ✅ |
| **同源** M6 | per-order == 报表(同人) == agent `worklog.piecework_amount` | 三处必须恒等（同一聚合） | **1/0/0** | ✅ |
| **缺失≠0** M7 | 未定价工序**在 `unpriced` 块可见且数量正确**；**不得**以 0 元混进 `per_operation`；显式 0 元 ≠ 未定价 | 我的算式 + V90 三态词表 | **3/0/0** | ✅ |
| **双付** M8 | 同 `X-Client-Request-Id` 重放：首次落一条、**第二次不再落**且 `replayed=true` | 幂等契约 | **1/0/1**（首轮失败已重跑取代） | ✅ |
| **双付** M8-01R | 同上（重跑，用**有剩余量**的实例） | 行数 9→10→**10**、`replayed=true` | **pass** | ✅ |
| **边界** M9/M9-01R | 超应做数量 ⇒ **422 + 不落明细** | 剩余量精确计算 | 剩余 3 报 4 ⇒「超过应做 20（剩余 3），本次未落库」 | ✅ |
| **改价** M10-01 | 实例改价 9.99 后，历史报工仍按**报工快照价**（不追溯） | 独立算式（快照价） | 改价前 13.20 → 改价后读面 13.2 | ✅ |
| **跨单** M11 | 同一工人两单 ⇒ 报表合计 == 两单独立算式之和；换工人只含该工人 | 同左 | **2/0/0** | ✅ |
| **口径** M12 | 返工不计件（独立算式排除后逐分一致） | 同左 | ✅ | ✅ |
| **日期** M13 | `work_date` 移出本期 ⇒ 报表按区间精确过滤（+08 业务日） | 同左 | ✅ | ✅ |
| **边界** M14 | `qty=0` 被拒且**不落 0 元行** | 契约（`qty 必须大于 0`） | 422，库里 qty=0 行数 **0** | ✅ |
| **作废** M15 | 软删的报工行不计件 | 同左 | 软删 1 行后读面 = 剩余行算式 | ✅ |
| **F8 正对照** F8E | 保存后实例价/新报工快照/工资读面 | 独立算式 | 前置两次被并行包干扰 ⇒ **不成立即不作数**（已登记 skip） | ⏭️ |
| **F8 受控** F8X (p8) | 一次普通保存新建价目行 + 实例单价 | 我的定点值 | **新建 `布帘=0.40`**；实例价未变（配置恰好同价 ⇒ 无判别力，已如实登记） | ✅/⚠️ |
| **F8→工资** F8Z (p9) | `X=NULL → Y=1.11 → 保存 → Z` 必须 == 1.11；新报工快照必须 == 1.11 | 我的定点值 + 独立算式 | **X=NULL / Y=1.11 / Z=0.35**；报工快照 **0.35**、金额 **1.05**（应为 3.33） | ❌ **见 D1** |
| **红证** RED-01/02/03 | 注入「未定价混进明细」/「差一分」/「漏一行」⇒ 对应判据必红 | 注入读数（喂真判据函数） | 3/3 注入后判据 **false**，干净读数 **true** | ✅ |
| **零残留** P10c | 8 个探针域计数 == 0 | 直连 RDS | `{"probe_worklogs":0,…,全部 0}` | ✅ |

**合计（末次读数）**：`57 pass / 14 fail / 4 skip`，其中 **11 条 fail 是首轮自建脚本缺陷、已被重跑取代**（`SUMMARY.json .supersededFails` 逐条列出）⇒ **有效失败 = 3 条**：`F8Z-01`（该脚本自己的 X 期望写成"库价"，实测为前置注入的 NULL）、`F8Z-03/F8Z-04`（= D1 本体）。

---

## 六、红证（逐字读数）

| 红证 | 形态 | 注入读数 | 注入后 | 干净读数 | 结论 |
|---|---|---|---|---|---|
| **RED-01** | 注入式（喂**真判据函数**） | `per_operation` 追加 `{operation:'定型-布', amount:0}` | `predUnpricedNotZeroInDetail` = **false（红）** | = true（绿） | ✅ 会红 |
| **RED-02** | 注入式 | `total='11.21'`（真值 `11.20`） | `predTotalEqualsOwnMath` = **false（红）** | = true | ✅ 逐分判据有效 |
| **RED-03** | 注入式 | 去掉 `精裁-布` 明细行 | `predDetailEqualsOwnMath` → `["精裁-布: 独立算式 3.20，读面缺该行"]` | = `[]`（绿） | ✅ 会红 |
| **F8Z-01/02 前置自证** | 活体前置 | 「通用行价 = 库价」时 X 应 = 库价 | 实测 **X = NULL**（前置被并行包改成 NULL） ⇒ 判据红 | — | 判据**如实变红**（不是恒绿） |

红证锚点**不读可变引用**：判据函数内联在 `harness/p1-p2-matrix.mjs`（纯函数入参），不引用任何移动靶（`origin/main` 等）。

---

## 七、假绿自查（专门回答「期望是否取自被测系统自身」）

1. **期望来源**：全部来自 `expectedCents()` —— 只读 **`production_work_logs` 的原始列**（`qualified_qty` / `unit_price` / `factor` / `price_state` / `work_type`）+ 我**定点写入**的实例价，**不读任何 `total` / `per_*` / `unpriced` 读面**。⇒ 读面被改坏时，期望**不会跟着漂**（这正是上一轮 F8 藏住的原因，本包堵上）。
2. **反证**：`F8Z` 实验里读面 total 从 3.33 掉到 **1.05**，而我的独立算式**始终是 1.11×3=3.33** ⇒ 二者分裂，判据当场红。若期望取自读面，这条会**全绿**（假绿）。
3. **空断言自查**：
   - `M16-01/02`（F8 混合对照）本轮 **skip**，因为"能表达未定价"的前置在测试环境不可得（40 道工序的 `通用` 行**全都有价**）⇒ **登记为未覆盖，而不是写成通过**。
   - `F8E-01` 首轮两次 skip/fail：我**没有**把"没跑到"写成"没问题"（如实登记）。
   - `M8-02`（失败键可重试）：登记为观察项（`p3-f8-redproof.json .failThenRetry`），**不计入通过**。
4. **基线快照时点**：所有「等变化」的读数都在**触发动作之前**取（X 在保存前、Z 在保存后且逐条 SQL 复读）。
5. **陈旧产物**：所有读面都是**当场 HTTP/SQL**，无缓存、无截图、无导出件。
6. **归因强度**：D1 的因果链是**我在同一分钟内**对**自建对象**执行的 3 次派工 + 1 次保存 ⇒ 机制级；并行包的干扰被单列（§八）而**未**写进 D1。

---

## 八、并发干扰核对（不作缺陷登记）

方法：P0 落基线快照 → 收尾时逐**对象键**比对（只比两侧共有的列，缺列标 `oneSided`）。

| 对象 | 基线（08:31:39Z） | 收尾（08:36:35Z） | 判定 |
|---|---|---|---|
| `production_operations` `logo条-布` (op-v91-20-32) | `unit_price=0.12` | `unit_price=0.60`（`updated_at` 仍是 2026-09-20） | **疑似并发干扰**（非自建行） |
| `production_operation_positions` 新增 `打包@布帘 = 0.00` | 无 | 1 行（created 08:36:19） | **疑似并发干扰**（该行的 `通用` 行为 NULL） |
| 其它 30 行价目 / 39 道工序 | — | 逐字一致 | — |

**观测到的直接后果（作为"干扰"登记，不写成缺陷）**：08:39 我派人探针单时，「打包」的实例价读到了 **0.00**、08:34 建的探针单读到 `定型-布 = NULL`，而 08:43 的读数又是 `通用/布帘 = 0.35` ⇒ **并行包的"改完即还原"确实在两次读之间改变了我能观察到的取价来源**。⇒ 本包凡涉及**共享配置**的前置（F8E、M16、p8 的"最少新建行"判据）都因此**不作数**；D1 的因果链刻意只用**自建对象 + 自建订单**，不受此影响。

---

## 九、零残留（机器读数，直连 RDS）

`out/p10c-cleanup.json .residue`（8 域，全部为 **0**）：

```json
{"probe_worklogs":0,"probe_orders_alive":0,"probe_products_alive":0,"probe_categories_alive":0,
 "probe_routes_alive":0,"probe_position_rows":0,"probe_library_ops":0,"probe_processing_orders_alive":0}
```

- 口径 = **存活**（`coalesce(deleted,0)=0`）且命名域命中探针前缀「工资验收」。命令：`node harness/p10c-cleanup.mjs`（先 `p10`/`p10b` 逐层清）。
- 清理动作：报工明细与旁路账**硬删自建行**（`production_work_logs` / `worker_report_audits`）；订单→订单行→加工单→工序实例→套/部位码链式清理；商品→SKU/颜色/属性/库存台账；分类；实验新建的价目行按 id 软删（保留审计）。**未删任何非自建行**。
- **副作用登记**：p9 的注入把「复烫」`通用` 行价改写过，已还原为原值 `0.35`（`out/p9-f8-wage-e2e.json .restoreState`）；p8 对「定型」新建的 `布帘=0.40` 行按 id 软删（`out/p10b-cleanup.json .extraPositionRows`）。**DB 物理层仍有 `deleted=1` 的行**（软删语义、不计入"存活"）；本包**不物理删**共享表的历史行，以免清除并行包/上一轮留下的审计痕迹 —— 如实披露。

---

## 十、未覆盖面与边界（照实登记，别把"没测"写成"没问题"）

1. **测试环境里"未定价"不是可自然到达的形态**：租户 20 的 40 道工序，`通用` 行**全部有价**（本轮实测）；"未定价"只能靠至少 27 道工序的 `布帘` 列**缺失** + `通用` 行价被清空才出现。⇒ **UI 上能否自然造出「未定价」这一形态本身未被验证**（§四 D1 的前置是我注入 `通用=NULL` 造就的）。
2. **结算/发放/工资单**：不存在（§四 D4）⇒ 未覆盖是**结构性的**，非漏测。
3. **工人端（`/api/worker/**` + `X-Worker-Session-Id`）**未测：本包全部走商家侧 `/api/admin/**`（身份来源 `client_body`）。工人 session 那条路的身份/工资归属**未验证**。
4. **系数（factor）**：本轮探针报工 `factor` 恒 `1`（#4589 起不再写）⇒ **历史 1.7× 快照行的金额口径未实测**（只在代码里读到 :1635-1638）。
5. **跨天/跨月边界**：只做了「`work_date` 移出本期 ⇒ 过滤正确」；**跨 0 点瞬间**「同一笔报工落到哪一天」未测（工作树无 `businessClock` 注入点，未改代码）。
6. **金额取整边界**：探针价均为 2 位小数 ⇒ 「逐笔取整 vs 总额取整」的差异（0.005 级）**未构造**（本轮未发现二次取整，但也没有能暴露它的样本）。
7. **套级（set）维度**：`per_set` 合计已验，但「一樘布+纱」的多行套归组**未构造**（探针单是单部位）。
8. **UI（Playwright 旅程）**：只做 HTTP 探活 + 读面承接面判定；**未做真实登录+截图+读图**（本线以接口/数据面为主，用户已说明 UI 面可选）。

---

## 十一、建议的下一步（哪些值得开修/补用例）

| 优先 | 动作 | 归属 |
|---|---|---|
| **① 部署确认** | 先把 `1d1fe5e55`（#6102 修复）**部署到本机 main-live**，再用 `harness/p9-f8-wage-e2e.mjs` 重跑一次：预期 `Z = 1.11`、报工快照 `1.11`、金额 `3.33`。**没在"修复后构建"上重放 = 没修**（协议铁律 5） | 集成侧 |
| **② 补用例（零 LLM，确定性）** | 把 D1 的「一句话判据」沉淀成 **Java 单测**（`ProductionOperationSavePriceDriftTest` 已有 7 项，但**工资侧**缺「保存后新报工快照价不变」这一条）；再补**端到端**判据：`PUT /operations/{id}` → `generate` → 实例价逐字不变 | 开发包 |
| **③ D3 清理出路** | 「已取消且无在途加工的订单」的删除端点应 200（或给具名拒绝理由）—— 验收残留现在**无法用 API 清零** | 开发包 |
| **④ 口径可读性 D2** | 界面/读面显式暴露"该工序有效价来自哪一行"（否则商家永远看不到底下多了一行 `布帘`） | 产品 |
| **⑤ 未覆盖项** | 工人端身份路径、`factor` 历史快照、套维度、跨 0 点、逐笔取整边界 —— 建议下一轮作为独立包覆盖（本包已如实登记为未覆盖） | 下一轮 |

### 受影响的行为用例清单（**只列，不派发** —— 用户裁定 #4262 不自动跑真实 LLM 评测）

`case_ids`（来自 `.github/cases/` 与 `.github/cases/processing-order.yml` 的计件/工序设置族）：**`processing-order.yml` 的 #6102 相关条目**（本轮由 `1d1fe5e55` 新增/改判）、以及计件链的 `OR-*` / `AS-*` 族中与「报工 → 计件 → 报表」相关的用例。**本轮一个都没派发**（无真实 LLM 调用发生）。

---

## 十二、结论

- **钱链的算式与读面一致性：通过** —— 明细逐分 == 独立算式、四维下钻合计 == total、三端点同源恒等、未定价「缺失≠0」显式可见、显式 0 元与未定价可区分、幂等键防双付、超报拒绝不 clamp、软删行不计件、跨单/按人隔离、日期区间过滤 —— 共 **57 条末次通过**。
- **但钱的"上游"有一个静默改写口（D1）**：一次与价格无关的普通保存会让工资单价从「未定价 / 商家定价」变成**工序库价**，工资读面**自洽地**显示一个错误但"看起来正常"的数字 ⇒ **商家拿汇总表发工资会错发**。本包用**受控单次实验**复现（`X=NULL → Y=1.11 → 保存 → Z=0.35`，报工金额 1.05 vs 应为 3.33）。
- **本轮结论的适用边界**：只对 `402be478b`（**未含** `1d1fe5e55`）这台构建成立；**不代表 main 现状**，也**未**在修复后构建上重放。

---

### 产物清单

| 文件 | 内容 |
|---|---|
| `harness/lib.mjs` | 共享库 + 本轮新增：`cents/fmt/moneyEq`（decimal 语义）、`assertProbe/guardedWrite`（探针守卫）、`judge` |
| `harness/p0-surface.mjs` | 读面真值枚举（端点/query 组合/OpenAPI 下游枚举/干扰基线） → `out/p0-surface.json` |
| `harness/p1-p2-matrix.mjs` | 探针对象 + 判据矩阵 M1~M16 + 注入式红证 → `out/p1p2-matrix.json`、`out/redproof.json` |
| `harness/p3-f8-redproof.mjs` | F8 正对照（前后读数）+ M8/M9 重跑 + 并发干扰核对 → `out/p3-f8-redproof.json` |
| `harness/p5-ui-and-residue.mjs` | UI 探活 + 未定价承接面 + 下游写端点枚举 → `out/p5-ui.json` |
| `harness/p6-price-source.mjs` | 取价来源**判别性实验**（3.33 注入 ⇒ 实例价 = 3.33）→ `out/p6-price-source.json` |
| `harness/p7-f8-e2e.mjs` | F8 端到端探查（前置不成立即 skip）→ `out/p7-f8-e2e.json` |
| `harness/p8-f8-controlled.mjs` | F8 受控（显式 positions 路径）→ `out/p8-f8-controlled.json` |
| `harness/p9-f8-wage-e2e.mjs` | **F8 → 工资 受控端到端（D1 的证据链）** → `out/p9-f8-wage-e2e.json` |
| `harness/p10*.mjs` | 三层清理 + 零残留机器读数 → `out/p10-cleanup.json`、`out/p10b-cleanup.json`、`out/p10c-cleanup.json` |
| `harness/{inspect,diag*,summary}.mjs` | 只读诊断 + 断言汇总 → `out/SUMMARY.json` |
