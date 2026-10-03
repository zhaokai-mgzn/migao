# 线③ 独立验证报告 —— 财务/库存下游 + 账期时间口径

- **包**：`acceptance/2026-10-03/finance-stock-time-sweep/`
- **角色**：线③ 独立验证包（只做验收取证，**未改 MIGAO 业务代码、未改 `.github/cases/**`**）
- **生成时刻**：2026-10-03 13:50 +08（Asia/Shanghai）
- **权威读数轮**：run3，测量窗 `2026-10-03 13:49:06 → 13:49:27 +08`
- **读数汇总**：**pass 31 / fail 9 / skip 7 / 假红已改判 3（B2/B3/B8，修正后计入 pass）/ total 47**
- **被测租户**：`tenant_id=20`（管理员 `13870217889`，万能码 `123456`）
- **结论一句话**：**钱能算到"报表"为止 —— 结算单/发放/导出三段落仓内完全不存在（A 族 4 skip）；账期窗口用 UTC 日界而非 +08，跨月/跨年归错（C 族 9 fail，P1 涉钱）；库存下游（加权平均/台账/盘点/批次/残料/省料看板）读面与独立 SQL 重算一致（B 族 14 pass）。**

---

## §0 核心判据（TL;DR）

| # | 判据 | 实得 | 级别 |
|---|---|---|---|
| 1 | 计件**结算单**能否生成（按人/月/工序汇总 + 金额独立算式 + 结算冻结） | **面不存在**：8 个候选端点全 404；`FinanceController` 仅 4 端点；全仓 `结算\|发放\|settle\|payout\|disburse` 仅 2 处**注释**；无相关 DB 表 | skip（**未覆盖**，对应 open issue #5653） |
| 2 | **发放留痕**（发放 ≤ 结算 / 重复发放拒绝 / 发放台账） | **面不存在**：5 个候选端点全 404 | skip（未覆盖） |
| 3 | **导出**（行/列/精度与读面逐字一致；空结果不畸形） | **面不存在**：7 个候选端点全 404 ⇒ **连红证都造不出来**（无可注入对象） | skip（未覆盖） |
| 4 | 计件工资报表总额/逐人 = 独立 SQL 重算 | 总额 `36.33 == 36.33`；3 人逐行一致 | ✅ pass（正对照：**"能算"这一半真的在工作**） |
| 5 | 移动加权平均（首次/二次/未记单价） = 独立 SQL（HALF_UP 4 位） | `12.5` / `11.6113` / 保持原值 —— 三处全等 | ✅ pass |
| 6 | 台账条数 = 变动次数（入库 3 次 / 调账 1 次 / 盘点 3 批次） | `3==3`、`1`、`台账增量3==分录增量3` | ✅ pass |
| 7 | 台账链条首尾相接 + `delta == after−before` | 全相接、全自洽 | ✅ pass |
| 8 | 调账/盘点**不改**移动加权均价 | 两处均价均**不变** | ✅ pass |
| 9 | 批次余量读面 = DB 独立重算 `quantity + Σ(delta)` | 3 批次全一致 | ✅ pass |
| 10 | 残料 / saving-board 读面 = DB | 残料 `0==0`；省料看板批次 `5==5` | ✅ pass（写面因无数据未覆盖） |
| 11 | `POST /api/admin/batch-stock` 语义 | HTTP **404**（该路径无方法映射，**正确行为**，非缺陷） | ✅ pass |
| 12 | 🔴 **账期窗口 = +08 日界** | **UTC 日界**：北京 `10-01 00:00`/`02:00`/`2026-01-01 00:01` 全部**不被其所属日窗口收录**；`10-01 02:00` 落进 **09-30** 窗口；`2026-01-01 00:01` 落进 **2025-12-31** 窗口（**跨年归错**） | ❌ **fail ×9（P1 涉钱）** |
| 13 | 跨端点口径自洽 | 同一笔"北京今日凌晨"订单：**Dashboard 按 +08 收录（order-trend 10-03 = 351）/ 订单列表按 UTC 排除（total=9，未收录）** | ❌ **fail（内部自相矛盾）** |
| 14 | 测量期间构建点不漂移 | before==after（`7e9f66ce5` / pid 60585） | ✅ pass |
| 15 | 零残留 + 存量零改动 | 逐表残留 **9 表全 0**；9 张写过的表既有行**零字段变化、零消失** | ✅ pass |

---

## §1 构建点自证（含切换登记）

**被测活环境**：admin-api `:8080`，worktree `/Users/guangzhen.zk/migao-wt/main-live`。

| 项 | 值 |
|---|---|
| 权威轮构建点 | **`7e9f66ce5`**「fix(6181): 商家发货三步原子化 —— 建单按调用方显式传入的流转事实，整条路单事务 (#6190)」 |
| commit 时刻 | `2026-10-03T05:42:36Z` = **13:42:36 +08** |
| 进程 | pid **60585**，启动 `六 10月/ 3 13:44:16 2026`（+08） |
| JVM 时区 | `user.timezone=Asia/Shanghai`（`jcmd VM.system_properties` 实读） |
| 权威测量窗 | `13:49:06 → 13:49:27 +08`（`utc 05:49:06.700Z → 05:49:27Z`） |
| 文档期 origin/main | 起始 `d877f19ef` → 收口 `05ca1f6c9` |

### 1.1 构建点切换登记（`out/buildpoint-shift.json`）

**实测切换点：`2026-10-03 13:44:16 +08`**（`d1c09d02f` pid 99086 → `7e9f66ce5` pid 60585）。

| 轮 | 窗口（+08） | sha | pid | 进程面自证 | 处置 |
|---|---|---|---|---|---|
| recon | 13:40:23 → 13:40:26 | `d1c09d02f` | 99086 | ✅ | 现状只读枚举；其结果已在 run3 于新构建逐条复现一致 |
| run1 | 13:44:26 → 13:44:49 | `7e9f66ce5` | **unknown** | ❌ | 🚫 **整轮 superseded**（换构建重启瞬态，`lsof -t` 读不到 pid ⇒ 进程面无法自证） |
| run2 | 13:47:51 → 13:48:12 | `7e9f66ce5` | 60585 | ✅ | 可用（harness 修正后重跑） |
| **run3** | **13:49:06 → 13:49:27** | **`7e9f66ce5`** | **60585** | ✅ **B0 双采样 before==after** | ✅ **权威轮** |

> **事实订正（§7-⑤）**：主会话提出"首轮读数观测窗横跨切换点"。据本包时间戳：**切换点 13:44:16 早于首轮开始 13:44:26 共 10 秒 ⇒ 首轮并未跨越**，唯一落在旧构建上的是 recon（13:40:23，只读枚举）。但首轮 pid 读数为 `unknown`，无法自证进程面，**故仍整体判为 superseded 而不引用其结论** —— 权威结论一律取 run3。

### 1.2 哪些读数受切换影响

- **需重测的（已全部在 run3 于 `7e9f66ce5` 重跑）**：A 族面存在性 404 探测、B 族库存写/读链、C 族账期窗口、Z 族零残留 —— **均已重跑同批记录构建点**（`out/buildpoint-run.json`）。
- **不受影响的（源码/内容级，非运行期）**：`FinanceService.parseDateStart/End` 的 UTC 字面量、`FinanceController` 端点面、全仓 `结算|发放` 命中数、DB 表清单 —— 见 §4，均以 `git show origin/main:<path>` 级证据给出。
- **`#6185` 不在运行构建内**：`grep -rl "logisticsCache\|物流缓存" src/main/java` 在该构建**零命中**（`origin/main` 同）。⇒ C6 只作当前行为登记，**不判缺陷**。

---

## §2 断言矩阵（pass / fail / 假红 / skip 四态分列）

### 2.1 PASS（31）

| id | 判据 | 期望来源（独立） |
|---|---|---|
| T1 | harness 时钟 = SQL `now() at time zone 'Asia/Shanghai'`（差 0s） | DB 侧时钟 |
| T2 | harness `cst` 与 `utc` 相差恰 8h（防同文件自相矛盾） | 8h 恒等 |
| A0a | 计件工资总额 = `SUM(round(qty*price,2))` | 独立 SQL |
| A0b | 计件工资**逐人**金额逐行一致（3 人） | 独立 SQL |
| B1 | 首次入库 ⇒ 均价 = 进价（`12.5`） | `movingAverage` 口径 SQL 重算 |
| B2 | 二次入库 ⇒ `(60.5*12.5+39.5*10.25)/100` HALF_UP 4 位 = `11.6113` | 独立 SQL numeric |
| B3 | 未记单价 ⇒ 只加数量、均价保持 `11.6113` | 口径 doc |
| B4 | 台账条数 = 变动次数（3 次入库 ⇒ 恰 3 条） | 前后计数差 |
| B5 | 台账链条 `after[i]==before[i+1]` 且 `delta==after−before` | 独立不变式 |
| B6a | 调账（−15）后均价**不变** | 口径 doc + 调账前实测 |
| B6b | 调账台账条数 = 1 | 前后计数差 |
| B7a | 盘点后批次余量 = 实盘值 | 本包指定实盘值 |
| B7b | 盘点台账增量 == 批次分录增量（3==3） | 双增量相等不变式 |
| B7c | 盘点**不改**均价 | 口径 doc |
| B8 | 批次余量 = `quantity + Σ(delta)`（有符号）3 批次全一致 | 独立 SQL（口径 = `remaining()` 的 `rest = inbound + used`） |
| B9 | 残料读面 `total == count(*)`（0==0） | 独立 SQL |
| B10 | saving-board 批次合计 == `count(distinct stock_batches)`（5==5） | 独立 SQL |
| B11 | `POST /api/admin/batch-stock` ⇒ 404（正确行为） | 源码：唯一 `@PostMapping` 是 `/stocktake` |
| C1-A / C1-D | `2026-09-30 23:59:59+08` / `2025-12-31 23:59+08` 落在本日窗口 | +08 墙钟日历 |
| C2-2025-12 / 2026-09 / 2026-10 | 月度窗口覆盖该月探针 | 独立 SQL（+08） |
| C3 | 5 条时间探针确实落库可读（反假绿控制） | 探针构造清单 |
| C7-A | 窗口唯一性成立（`2026-09-30` 恰一个窗口） | +08 日历 |
| C4 | **红证**：绿→注入→红（前置命中 true → false） | 注入式 |
| C5 | **红证还原**：sha256 逐字节回原 + 判据回绿 | 内容指纹 |
| C8a | 边界夹逼·下界：`北京 10-01 08:00`（= UTC 下界）**被收录** ⇒ **过滤链路确实在工作** | 两种口径一致点 |
| Z1 | 零残留：9 表全 0 | 逐表计数 |
| Z2 | 存量零改动：9 张写过的表既有行零字段变化/零消失 | 前后逐字段 diff |
| B0 | 测量期间构建点/进程未漂移 | before==after 双采样 |

### 2.2 FAIL（9）—— **全部同一根因（UTC 日界）**

| id | 期望（+08 口径） | 实得 | 证据 |
|---|---|---|---|
| C1-B | `2026-10-01 00:00:00+08` 落在 `10-01` 窗口 | `hit=false`（该日 0 行） | `out/summary-raw.json` |
| C1-C | `2026-10-01 02:00:00+08` 落在 `10-01` 窗口 | `hit=false` | 同上 |
| C1-E | `2026-01-01 00:01:00+08` 落在 `2026-01-01` 窗口 | `hit=false` | 同上 |
| C2-2026-01 | 1 月窗口 `incomeCount ≥ 1` | `incomeCount=0`（无窗口基线 380） | `out/C2-expected-by-month.json` |
| C7-C | 恰落在 `[2026-10-01]` | 实测 `["2026-09-30"]` | ±2 天逐窗扫描 |
| C7-E | 恰落在 `[2026-01-01]` | 实测 **`["2025-12-31"]`** ⇒ **跨年归错** | ±2 天逐窗扫描 |
| C8b | `北京 10-01 07:59:59` 应被 `10-01` 收录 | `hit=false` | `out/C0-injection-fingerprint.json` |
| C8c | `北京 10-01` 流水**不得**落进 `09-30` 窗口 | `09-30` 窗口 `hit=true`（**归错月份**） | 同上 |
| C9 | 两端口径一致（订单列表也应收录该单） | Dashboard `order-trend[10-03].orders=351` **收录**；列表 `startDate=endDate=2026-10-03` `total=9`、**未收录** | `out/C9-cross-endpoint.json` |

### 2.3 假红（3）—— **本包断言自身的缺陷，已改判并修正**

| id | 原判 | 真相 | 修正 |
|---|---|---|---|
| **B2** | fail「期望 `stock=100.0` ≠ 实得 `100`」 | **假红**：`numeric` 经 `row_to_json` → JSON number → JS `100`，字符串比较把 `100` vs `100.0` 判成不等。均价 `11.6113` 本就相等 | 改数值比较（`Number(a.stock)===100`）⇒ **pass** |
| **B3** | fail 同上（`110.0` vs `110`） | **假红**，同一形态 | 同上 ⇒ **pass** |
| **B8** | fail「1 个批次余量不一致」 | **假红**：**本包算式写错** —— 用了 `quantity − Σ|delta|`，而口径是 `quantity + Σ(delta)`（**有符号**，`consumedByBatchId` 取有符号 `deltaSum`）。盘点盈余（`delta=+20`）被算成扣减 | 改有符号求和 ⇒ **pass** |

**B8 三数 + 批次 id + 复算命令**（主会话索要，run3 实读）：

| 批次 id | batch_no | `quantity`（入库米数） | `Σdelta` | 独立期望余量 | 读面实得 |
|---|---|---|---|---|---|
| `20` | `PC-20261003-0007` | `60.5` | `-5.5` | `55` | `55` ✅ |
| `21` | `PC-20261003-0008` | `39.5` | `-9.5` | `30` | `30` ✅ |
| `22` | `PC-20261003-0009` | `10.0` | `+20.0` | `30` | `30` ✅ |

```bash
# 复算（口径 = StockBatchConsumptionService.remaining(): rest = inbound + used，used = 有符号 Σdelta）
psql "$DB" -c "select b.id, b.batch_no, b.quantity, coalesce(sum(c.delta),0) delta_sum,
                      b.quantity + coalesce(sum(c.delta),0) expect_remaining
               from stock_batches b left join stock_batch_consumptions c
                 on c.batch_id=b.id and c.deleted=0
               where b.tenant_id=20 and b.sku_id=<探针skuId> and b.deleted=0
               group by 1,2,3 order by 1;"
# 对照读面
curl -s -H "Cookie: access_token=$TOKEN" "localhost:8080/api/admin/batch-stock/batches?skuId=<探针skuId>"
```

### 2.4 SKIP（7）—— 如实登记，**永不记 pass**

| id | 面 | 为什么 skip |
|---|---|---|
| A1 | 计件结算单 | 8 候选端点全 404 ⇒ 无可断言对象 |
| A2 | 发放留痕 | 5 候选端点全 404 |
| A3 | 导出 | 7 候选端点全 404 ⇒ 无可注入对象（红证亦不可造） |
| A4 | 结构性归因 | 见 §5 |
| B9b | 残料**写面**（recover/scrap） | 本租户 `fabric_remnants` 现存 **0 行** ⇒ 无残料可回收/报废 |
| C6 | #6185 物流缓存 | 不在运行构建内 ⇒ 按任务书只作当前行为登记 |
| Z4 | 并发新增登记 | 本次窗口未观测到其它包并发新增 |

---

## §3 红证台账

**判据：不会红的断言 = 空断言。** 本包红证分两类。

### 3.1 C4/C5——注入式红证（**绿 → 红 → 还原 → 绿**）

| 阶段 | 读数 | 自证 |
|---|---|---|
| 前置（须绿才有判别力） | `c3ref…A`（`2026-09-30 23:59:59+08`）在 `09-30` 窗口 `hit=**true**` | — |
| 注入 | `occurred_at` → `2026-10-05 12:00:00+08`（挪出该窗口） | **内容指纹 sha256**：`5ebcfe6e…8bf6` → `c0815a28…94b5`（变=true） |
| 复跑同判据 | `09-30` 窗口 `hit=**false**` ⇒ **当场红** | ✅ 判据**会红** |
| 还原 | 逐字段写回原值 | sha256 **回原** `5ebcfe6e…8bf6`（相等=true） |
| 复跑同判据 | `hit=**true**` ⇒ **回绿** | ✅ 闭合 |

> **红证锚点纪律**：锚点是**本包自造的探针行**（不是 `origin/main` 这类移动靶），故修复落地后本红证**不会自红**。
> **⚠️ 一次已改判的设计错误**：初版把红证做在**已经红的**判别探针上 ⇒ 注入后红无变化 ⇒ 无判别力，且我据此**误判 C4 为"空断言"**。**该结论作废**（详见 §7-①）。

### 3.2 C8——跨口径判别点（把"是否算缺陷"变成可判定）

按主会话指定设计，用**两个只差 1 秒**的探针夹住 UTC 日界：

| 探针 | 北京墙钟 | UTC 值 | UTC 窗口是否收录 | +08 口径是否应收录 | 实得 |
|---|---|---|---|---|---|
| **C8a** | `2026-10-01 08:00:00` | `2026-10-01T00:00:00Z` | ✅（恰含入下界） | ✅ | `hit=true` ✅ **pass（正对照：过滤真的在工作）** |
| **C8b** | `2026-10-01 07:59:59` | `2026-09-30T23:59:59Z` | ❌ | ✅ | `hit=false` ❌ **fail** |
| **C8c** | 同上 | 同上 | ✅（落 09-30 窗口） | ❌（不得落 09-30） | `09-30` 窗口 `hit=true` ❌ **fail** |

⇒ **C8a 绿 + C8b/C8c 红** 三者同时成立，唯一自洽解释 = **窗口确实在过滤，但边界是 UTC 而非 +08**。这既排除了"窗口不生效"，也给出了缺陷的精确位置（**日界整体后移 8 小时**）。

### 3.3 故意的失效控制项（必红）

- **C1-B / C1-C / C1-E / C7-C / C7-E / C8b / C8c / C9** 共 8 条**当前即为红**，且其红色**只能**由 UTC 日界解释（C8a 已证明过滤链路正常）。这不是"故意造红"，而是**真实缺陷的确定性显形**；本包另有一条**人工失效控制项**：
- **B11**：把 `POST /api/admin/batch-stock` 的期望写成"404"——若该路径哪天被误加写入映射，此条**立刻翻红**（正向护栏）。

---

## §4 发现清单（**涉钱项置顶**）

### 🔴 F1【P1 · 涉钱 · 待主会话派单】财务/订单/商品的日期查询窗口按 **UTC 日界**计算，而非 +08 日界

**一句话**：北京 `00:00–08:00` 的交易/订单/商品会被归到**前一天**（跨月/跨年时**归错月/错年**）；`startDate=endDate=D` 的实际窗口是"北京 D 日 08:00 → D+1 日 07:59:59"。

**期望来源（口径）**：产品口径 = **+08**。依据（仓内自证，非外部裁定）：
1. `BusinessClock.BUSINESS_ZONE = ZoneId.of("Asia/Shanghai")` 是仓内声明的"业务今天"**唯一单点**（issue #3802），且 `BusinessClockSourceGuardTest`（`case_ids: DA-001, DA-002, DA-004`）**禁止** `src/main` 下出现别的 `Asia/Shanghai` 字面量或无参 `now()`。
2. 同日窗口的**正确范式**已在仓内：`DashboardController.java:68`、`DailyBriefingService.java:462` 都用 `businessClock.startOfDay(...)`。
3. 前端**已显式规避**同一坑：`frontend/admin-web/src/app/(dashboard)/products/page.tsx:22-30` 注释逐字 ——
   > 「不得写成 `new Date().toISOString().slice(0,10)`（**UTC** 日）：在 UTC+8 的每天 00:00~08:00（CST）这 8 小时里 UTC 日 = 前一天 ⇒ 导出文件名 `products_YYYY-MM-DD.xlsx` 的日期与商家认知不符（与 **#4772** 的「每月 1 日查上一个月」**同一根因族**）」，
   并在 `:35` 定义 `formatLocalDate()`、`:324` 使用它。
4. ⇒ **同一仓库内已有单源与正确用法，前端也已防**，财务/订单/商品三处**仍按 UTC 日界** ⇒ 属**已知缺陷形态的漏改**，非设计选择。

**证据（内容级，`origin/main` = `05ca1f6c9`）**：

| 位置 | 逐字 | 类型 |
|---|---|---|
| `FinanceService.java:430-436` | `parseDateStart: date + "T00:00:00Z"` / `parseDateEnd: date + "T23:59:59Z"` | 硬编码 UTC |
| `OrderService.java:208,211` | `wrapper.ge(..., OffsetDateTime.parse(startDate + "T00:00:00Z"))` / `wrapper.le(..., endDate + "T23:59:59Z")` | 同写法 |
| `ProductService.java:194,199` | `.atStartOfDay().atOffset(ZoneOffset.UTC)` / `.plusDays(1).atStartOfDay().atOffset(ZoneOffset.UTC)` | 同写法 |
| `DashboardController.java:68` | `businessClock.startOfDay(businessClock.today().withDayOfMonth(1))` | ✅ 反例（正确） |
| `DailyBriefingService.java:462` | 同上 | ✅ 反例（正确） |

**影响面**：`GET /api/admin/finance/summary`、`/finance/transactions`、`/finance/reconciliation`（三处**同源** `parseDateStart/parseDateEnd`）、`GET /api/admin/orders`（列表日期筛选）、商品列表 `createdFrom/createdTo`。**已实测受影响**：C1-B/C1-C/C1-E、C2-2026-01、C7-C/C7-E、C8b/C8c、C9（共 9 条）。

**复算命令**（零成本，可直接跑）：
```bash
cd "/Users/guangzhen.zk/ai native/migao"
# ① 三处漏改 + 两处正确范式（内容级，只读 origin/main）
git show origin/main:backend/admin-api/src/main/java/com/migao/admin/service/FinanceService.java   | grep -n 'T00:00:00Z\|T23:59:59Z'
git show origin/main:backend/admin-api/src/main/java/com/migao/admin/service/OrderService.java     | grep -n 'T00:00:00Z\|T23:59:59Z'
git show origin/main:backend/admin-api/src/main/java/com/migao/admin/service/ProductService.java   | grep -n 'ZoneOffset.UTC'
git show origin/main:backend/admin-api/src/main/java/com/migao/admin/controller/DashboardController.java | grep -n 'businessClock.startOfDay'
# ② 前端同源证据
git show origin/main:'frontend/admin-web/src/app/(dashboard)/products/page.tsx' | sed -n '22,36p'
# ③ 运行时复现（本包 harness，可重跑）
cd acceptance/2026-10-03/finance-stock-time-sweep/harness && node run-all.mjs   # 看 C1/C7/C8/C9
```

> **待确认项（1 句）**：最终产品口径以 **+08** 为准 —— 若产品方另有他意，则 F1 降级为"口径登记"；但依据 1–4，此争议已基本消除。

**是否涉钱**：**是**（月度营收/对账/资金流水归属）⇒ 标 **P1**，**不由本包修复、不由本包开 issue**，交主会话处置。

---

### 🟡 F2【P2 · 非涉钱 · 产品能力缺口，对应 open issue #5653】计件"能算不能结"：结算单/发放留痕/导出三段落**仓内完全不存在**

**形态**：钱能算到**报表**为止，往下的收尾段**没有任何实现**——不是"接口在但没页面"，而是**连接口、实体、表都没有**（比"只有接口没页面"更彻底）。

**逐条登记**：

| 族 | 期望能力 | 实得（实测） |
|---|---|---|
| 计件**结算单** | 按人/月/工序汇总生成；金额可独立复算；结算后源报工**冻结**（不得再被改） | ❌ 全无。8 候选端点 **全 404** |
| **发放**留痕 | 发放额 ≤ 结算额；重复发放被拒；发放台账可查 | ❌ 全无。5 候选端点 **全 404** |
| **导出** | 行/列/金额与读面逐字一致（含精度、含汇总行）；空结果不输出畸形文件 | ❌ 全无。7 候选端点 **全 404** ⇒ **连"空结果不畸形"的红证都造不出来**（无可注入对象） |

**结构性证据（五重，互相独立；②③⑤ 由主会话提供、本包**逐条独立复核**）**：
1. `FinanceController`（origin/main）**仅 4 个端点**：`GET /summary`(:43)、`GET /transactions`(:58)、`POST /transactions`(:82)、`GET /reconciliation`(:98) —— **无结算、无发放**。
2. **全仓端点扫描**：`@(Get|Post|Put|Delete)Mapping` 里筛 `settle|payout|disburse|wage|export` ⇒ **全仓仅命中 1 处**：`ProductController.java:221 @GetMapping("/export")`（**商品**导出）⇒ **财务域零导出端点**。
3. **后端关键字命中**：`backend/admin-api/src/main/java` 内 `结算|发放|settle|payout|disburse` **仅 2 处，且皆为注释/文档**：
   - `AuthService.java:1358`（权限码分组的**注释**）
   - `ProductionService.java:1566`（系数口径 doc 里的"呈现/结算值"字样）
4. **DB 无相关表**：`select tablename from pg_tables where tablename ~* 'settle|payout|wage|payroll|disburse'` ⇒ **空集**。
5. **前端同样没有入口**（双侧皆无 ⇒ 不是"接口在但没页面"）：
   - `frontend/admin-web/src/app/(dashboard)/finance/` 与 `.../production/piecework/` 下 `grep -icE '结算|发放|settlement|payout'` ⇒ **零命中**（两目录各仅 1 个 `page.tsx`，逐个文件核过）。
   - 计件页**整个只调一个端点**：`api/admin/production/piecework/summary`（`grep -oE` 全量提取，唯一命中）。

**结论句**：计件「结算 / 发放 / 导出」在**后端与前端双侧均不存在** —— `FinanceController` 仅 4 个端点、全仓唯一导出端点是**商品**导出、财务与计件页面**零结算入口**。故只能验到「算」（报工→钱），「结」与「发放」**既无接口也无界面** ⇒ 这是 open issue **#5653**「今天能算不能结：与财务域零耦合、无导出、无发放台账」的**逐字实得形态**，本轮以 **skip** 记录，**不按通过计**。

**"能算"这一半是真的在工作**（正对照，反假绿）：`A0a` 计件工资总额 `36.33` = 独立 SQL `SUM(round(qty*price,2))`；`A0b` 逐人 3 行全一致 ⇒ 缺口**只在收尾段**，不是"钱的链路全废"。

**复算命令**：
```bash
cd "/Users/guangzhen.zk/ai native/migao"
# ① 端点面：只有 4 个
git show origin/main:backend/admin-api/src/main/java/com/migao/admin/controller/FinanceController.java | grep -nE '@(Get|Post|Put|Delete|Patch)Mapping'
# ② 全仓命中数（应为 2，且都是注释）
git grep -niE '结算|发放|settle|payout|disburse' origin/main -- 'backend/admin-api/src/main/java'
# ③ 无相关表
psql "$DB" -tAc "select tablename from pg_tables where schemaname='public' and tablename ~* 'settle|payout|wage|payroll|disburse'"
# ④ 运行时：候选面全 404（token 取本包 loginApi）
for p in /api/admin/finance/settlements /api/admin/finance/payouts /api/admin/finance/export \
         /api/admin/production/piecework/settlements /api/admin/production/settlements \
         /api/admin/production/payouts /api/admin/finance/transactions/export; do
  printf '%s → %s\n' "$p" "$(curl -s -o /dev/null -w '%{http_code}' -H "Cookie: access_token=$TOKEN" "localhost:8080$p")"
done   # 期望：全部 404
# ⑤ 全仓端点扫描：唯一导出端点是**商品**导出
git grep -nE '@(Get|Post|Put|Delete)Mapping' origin/main -- 'backend/admin-api/src/main/java' | grep -iE 'settle|payout|disburse|wage|export'
# ⑥ 前端双侧零入口
git ls-tree -r --name-only origin/main -- 'frontend/admin-web/src/app/(dashboard)/finance' 'frontend/admin-web/src/app/(dashboard)/production/piecework'
for f in frontend/admin-web/src/app/'(dashboard)'/finance/page.tsx frontend/admin-web/src/app/'(dashboard)'/production/piecework/page.tsx; do
  echo -n "$f: "; git show "origin/main:$f" | grep -icE '结算|发放|settlement|payout'
done   # 期望：各 0
```

**是否涉钱**：**是**（发放=真金白银的出口）⇒ 标 **P2**（缺口，非错值），对应 open issue **#5653**，本包只补"实得形态"。

---

## §5 未覆盖面（含"面不存在"逐条登记）

| # | 面 | 状态 | 说明 |
|---|---|---|---|
| 1 | 计件**结算单** | **不存在** | §4-F2（8 端点 404 / 4 端点面 / 2 处注释 / 0 表） |
| 2 | **发放**留痕 | **不存在** | 同上（5 端点 404） |
| 3 | **导出**（任何域） | **不存在** | 同上（7 端点 404）；「空结果不畸形」红证亦不可造 |
| 4 | 残料**写面** `recover` / `scrap` | **未覆盖（无数据）** | 本租户 `fabric_remnants` **0 行** ⇒ 无残料可回收/报废；造残料须驱动加工单产余料，超本包体量。**读面已验**（`0==0`） |
| 5 | `#6185` 物流缓存 | **不在运行构建内** | 运行构建 `7e9f66ce5` 与 `origin/main` 均无 `logisticsCache\|物流缓存` 命中 ⇒ 只作当前行为登记，**不判缺陷**（缓存键/档位/失败不缓存三判据**未覆盖**） |
| 6 | 退货/退回入库（`allow_return_restock` 全链） | **未覆盖** | 需真实售后完结工单 + 商品开关 `allow_return_restock=true` 驱动；本包仅**核对口径**（`recordChangesAgainstSnapshot` ⇒ 回补**不改**移动加权均价，已由 B6a 同族判据间接验证），**端到端未跑** |
| 7 | 报损 | **未覆盖** | 仓内无独立"报损"端点；同族动作是人工调账（B6a/B6b 已验）与盘点（B7a-c 已验） |
| 8 | 批次**效期** | **面不存在** | `stock_batches` 无 `expiry_date`/`shelf_life` 列；批次读面已验（B8），**效期概念未覆盖** |
| 9 | 库龄/呆滞（按日计算、含跨天） | **未覆盖** | 未发现库龄/呆滞端点或列；**"按日计算含跨天"无对象可验** |
| 10 | 发放额 ≤ 结算额 / 重复发放被拒 | **不存在** | 依赖 §4-F2 |
| 11 | Dashboard/Briefing 统计口径 vs DB 独立重算（全字段） | **部分覆盖** | 已验 `order-trend`/`todayOrders` 的**日期归属**（C9）与 `businessClock` +08 口径（源码级）；**各数字逐项独立重算未做**（超本轮预算），登记为未覆盖 |
| 12 | 历史简报"不得随新数据漂移"（快照 vs 实时） | **未覆盖** | 本租户 `daily_briefings` **0 行**（`out/recon-stock.json`）⇒ 无历史简报可测漂移；表结构含 `content jsonb` + `source_snapshot jsonb`，**快照式设计已在结构上具备**，但**未取得实测证据** |
| 13 | `numeric(10,2)` 精度边界（0.005 舍入方向/大数/负数） | **部分覆盖** | 已验 `numeric(12,4)` 均价 HALF_UP 4 位（B2，`11.6113`）与 `numeric(12,1)` 库存（B1/B3）；**`0.005` 银行家舍入方向专项未做**（登记） |

---

## §6 零残留与存量零改动自证

### 6.1 零残留（终态逐表 = 0）

`out/residue.json`（run3 终态）：

```json
{"products":0,"skus":0,"inbound":0,"inbound_items":0,"batches":0,"consumptions":0,"ledger":0,"txns":0,"orders":0}
```

**探针命名域**：机器可判 id 前缀 `c3`/`c4`/`c5`（订单 `c3…`、流水 `c3ref…`、入库单 `c3inb…`/`c3RK…`、货号 `c3prod…`、SKU `c3sku…`）+ 中文域 `线③验收`（客户名/操作人/备注）。清理为**硬删**，只删探针行。

**`Z1` 那 13 行的去向（主会话索要）**：那是 **run1 的残留**，非终态。根因两条、均已修：
1. `assertProbeSql` **反向拦截了自己的清理语句**（清理用 `sku_id=<js number>`，不含探针命名域 token）⇒ 改为按 `sku_code`/`inbound_no`/`product_id` 命名域删除。
2. **`ref_no` 不是可靠探针锚点**：盘点/调账落的台账行 `ref_no` 是 **`NULL` 或 `batch_no`（`PC-…`）**，**不带探针前缀** ⇒ `ref_no like 'c3%'` 漏删，进而 `products` 被 FK 挡住删不掉。⇒ 改用**主锚 `product_id`**（探针货号，所有下游行都带它）。
   - 13 行 = products 1 / inbound 3 / batches 3 / ledger 3 / consumptions 3，已于 `13:47` 手工清干净（清理后实测逐表 0），随后 run2/run3 均在**干净起点**上开跑并以 `Z1` pass 收口。

### 6.2 存量真实数据零改动

**方法**：对 11 张受影响表做**前后逐字段快照**（`stock-snapshot-before/after.json`），排除探针行，按内容 **sha256** 比对（**禁用 mtime/size**）。

**判别对象收窄（关键修正）**：本包命题是"**未改动任何既有非探针行**"。并行包**新增**的行不是本包的改动 ⇒ 新增行只作**并发登记**（§2.4 Z4），不计违规；否则并行包一建商品就误判本包违规（run2 实测即因此误判 `Z2`：`products 35→40`、`product_skus 36→45`，全是**并行包新增**）。

**run3 终态（`Z2` pass）**：9 张写过的表 **既有行零字段变化、零消失**：

| 表 | 前后 sha256（前 12 位） |
|---|---|
| products | `b5af3840a6c2 == b5af3840a6c2` |
| product_skus | `505f8451e4f8 == 505f8451e4f8` |
| inbound_orders | `cac4e74a2ac4 == cac4e74a2ac4` |
| inbound_order_items | `5a9475953df2 == 5a9475953df2` |
| stock_batches | `051d92759624 == 051d92759624` |
| stock_ledger_entries | `2d0111a7b078 == 2d0111a7b078` |
| stock_batch_consumptions / finance_transactions / orders | 同前 == 同后（见 `out/stock-snapshot-diff.json`） |

**结构性归因**：本包**所有**写语句经 `assertProbeSql` 强制命中探针命名域（未命中**当场抛错**），清理只删探针行 ⇒ 非探针行在机制上不可能被本包改写。时间口径探针造的是**历史时间戳**（2025-12 / 2026-01 / 2026-09 / 2026-10），**均为本包自建探针行**，且其中被注入改动的一行已按**内容指纹**逐字节还原（§3.1）。

### 6.3 跨包隔离

同租户另有并行包（线① `agent-service-sweep`、线② `batch-writeface-sweep`）。本包：① 只动 `c3`/`c4`/`c5`/`线③验收` 命名域对象；② 既有行零改动（§6.2）；③ 归因按**行内容**，非自己的行记 `skip` 并注明并发干扰（Z2/Z4 已如此处置）。

---

## §7 事实订正

| # | 原表述 | 订正 | 依据 |
|---|---|---|---|
| ① | **C4 = "空断言"**（我初判：把判别探针平移 +1 天后仍命中 ⇒ 判据是空的） | ❌ **作废**。真相：平移目标是 `2026-10-02 02:00+08` = `2026-10-01T18:00Z`，**恰落在 `10-01` 的 UTC 窗口内** ⇒ 命中是**正确行为**，说明**窗口确实在过滤**。是我**红证设计错**（把红证做在**已经红**的探针上），不是判据空 | 主会话独立定位 + 我复核 UTC 换算；已重设计为 §3.1 的**绿→红→还原→绿**，并补 §3.2 跨口径判别点 |
| ② | C5 曾判 fail（"还原后未回绿"） | ❌ **作废**：当时 `hit=false` 与 C1-B **同因**（UTC 日界），**不是还原失败**（sha256 相等=true）。重设计后 **C5 pass** | run3 读数 |
| ③ | **B2/B3 fail**（`stock=100.0` ≠ `100`） | **假红**：`numeric` → JSON number → JS `100`，**字符串形态**不等而数值相等。已改数值比较 ⇒ **pass** | §2.3 |
| ④ | **B8 fail**（"1 个批次余量不一致"） | **假红**：**本包算式**用错（`quantity − Σ\|delta\|`），正确口径是 `quantity + Σ(delta)`（**有符号**）。已改 ⇒ **pass**，三数见 §2.3 | §2.3 |
| ⑤ | **`nowCST()` 输出 +8h 偏差**（harness bug：本地 getter + 手动偏移 ⇒ 双重换算；`out/buildpoint.json` 里 `cst=21:40` 与 `utc=05:40Z` 自相矛盾） | **已修**：改用显式时区 `Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai'})`（跨机不依赖 `TZ`）。**影响范围**：所有 `cst` **日志/JSON 字段**需 **−8h** 才是真实 +08 时刻，`utc` 字段恒可信。**未影响判据**：C 族期望值全部来自**写死的时间字面量**（`2026-10-01 02:00:00+08` 等）与**独立 SQL**，`out/C0-injection-fingerprint.json` 的 `13:44:42 +08` 已是修正后读数；全部读数为 **run2/run3（修正后）**，**无需重算**。并新增 **T1/T2 时钟自检**（harness cst 对 SQL `now() at time zone 'Asia/Shanghai'`，差 0s）作类级护栏（§2.1） | T1/T2 pass |
| ⑥ | **"首轮读数横跨构建切换点"** | **不成立**：切换点 `13:44:16` **早于**首轮开始 `13:44:26` 共 10 秒 ⇒ 首轮已在 `7e9f66ce5` 上。唯一旧构建读数是 recon（`13:40:23`，只读枚举）。**但**首轮 pid 读数 `unknown`（重启瞬态）⇒ 仍整体判 **superseded**，权威轮 = run3 | §1.1 |
| ⑦ | `psql()` 包装别名 `t` | **harness bug 已修并类级固化**：列名若也叫 `t`，PG 会解析成**列**而非行类型 ⇒ `row_to_json(text) does not exist`。包装别名改为 `__q`，使"列名撞包装别名"**在内层不可能发生** | 实测报错 → 修后通过 |
| ⑧ | `Z2` "存量零改动"曾**假绿**（空快照） | **已修**：初版用**一条通用谓词**引用各表没有的列（`transaction_no`/`sku_code`）⇒ SQL 报错 ⇒ 快照退化为**空集** ⇒ "空集==空集"**恒真**（正是 migao-acceptance 明令的"关系式断言在空集上恒真"）。⇒ 改为**逐表各自谓词** + **空集守卫显式告警** | run2 日志可见 12 次 `column ... does not exist` |

---

## 附：产物清单

| 文件 | 内容 |
|---|---|
| `harness/lib.mjs` | 共享库（API/psql/Recorder/judge/buildPoint/指纹/定点小数/时钟） |
| `harness/run-all.mjs` | 总入口（快照→T/A/B/C 族→清理→残留→零改动→SUMMARY） |
| `harness/famT-clock.mjs` | 时钟自检 T1/T2 |
| `harness/famA-money.mjs` | 家族 A（结算/发放/导出 + 计件报表正对照） |
| `harness/famB-stock.mjs` | 家族 B（加权平均/台账/调账/盘点/批次/残料/省板） |
| `harness/famC-time.mjs` | 家族 C（账期窗口/边界夹逼/跨端点/红证） |
| `harness/recon.mjs` | 现状只读枚举 |
| `out/SUMMARY.json` | 全量结构化读数（47 条） |
| `out/buildpoint-run.json` | 构建点 before/after 双采样 |
| `out/buildpoint-shift.json` | 构建点切换登记 + 归属 |
| `out/C0-injection-fingerprint.json` | 时间探针注入内容指纹 |
| `out/C9-cross-endpoint.json` | 跨端点口径不自洽读数 |
| `out/stock-snapshot-{before,after,diff}.json` | 存量零改动前后指纹与逐字段 diff |
| `out/{A1,A2,A3}-*-surface.json` | 结算/发放/导出面 404 枚举 |
| `out/residue.json` | 终态逐表残留计数 |
| `out/B6-adjust.json` / `out/B7-stocktake.json` / `out/B11-batch-stock-root.json` | 调账/盘点/根路径语义读数 |
