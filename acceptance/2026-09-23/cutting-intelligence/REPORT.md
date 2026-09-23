# 裁剪智能化（批次实物账 + 排料省料 + 池化派单 + 余料回收）验收报告

- **验收日**：2026-09-23
- **锚（被验对象）**：`origin/main = b43a6cb29635d58a771ba62febf98331dc5506d4`
- **验收协议**：`migao-acceptance` v1.13.0（含「交付物可达性判据 v1.11」：**谁发射 / 哪个入口可达 / 有无测试钉住**）
- **范围**：24 个已合入交付单元（`#5141` … `#5188`，见 §1）
- **⚠️ 先读 §6.1**：本报告推翻了其中一条**主验收判定**（C1「真库判据在 CI 里从未跑过」= **假**），原文保留。

---

## 0. 判定摘要

| 维度 | 判定 | 依据 |
|---|---|---|
| 交付物可达性 | **24/24 单元已合入主线**，每单元均有「发射点 + 可达入口 + 测试钉住」三件套（§1/§2） | `git log`/`git diff` 于锚 SHA 逐单元复算 |
| UA（用户代理）判定 | **4/4 通过** | 独立验收 #2（§4） |
| 断言形态（关键行为是否只写在自然语义里） | 44 条抽样 ⇒ **0 个实例** | 独立验收 #2（§5） |
| 红证（会不会红的断言） | 高风险面（钱/库/约束/幂等）逐条有单点可变红的红证；**6 个机具型红证无 CI 调用** ⇒ 已立 `#5193` | §5 + `#5193` |
| 双 AI 交叉验证 | C2/C3/C4/C5 **一致**；C1 **不一致 → 主验收被推翻并订正**；C6 **无法判定 → 本报告已补齐载体** | §6 |
| 独立性 | ⚠️ **弱于协议标准**：跨模型 provider 不可用 ⇒ 复核验收与主验收**同模型族** | §8 |
| 未闭环项 | 7 项，全部是**证据强度/可达性补强**，**无一影响本功能的业务判定** | §7 |

---

## 1. 交付单元（24 个，按合并顺序）

| PR | issue | merge SHA | 能力（一句话） |
|---|---|---|---|
| #5141 | #5141 | `0a7c183af` | 多行入库单过账**批次号逐行生成**（对齐「一行 = 一个批次」） |
| #5147 | #5063 | `94aacbc46` | 库存米数**小数化（1 位小数）**，三层 INTEGER 一并升级 |
| #5152 | #5149 | `614eeb018` | 旧系统 → MIGAO **导入能力盘点** + 期初批次导入口径（文档） |
| #5155 | #5150 | `8900d3194` | `product_manage` 商品级库存入参放宽为 1 位小数（复用精度闸门） |
| #5156 | #5148 | `28be0fcc8` | 过账**并发闸** + 单号重试/索引口径 + 建单幂等键 |
| #5157 | #5145 | `20ab9238a` | **阶段 1**：派加工单**扣批次库存** + 消耗台账 + 余量分布（记录期） |
| #5160 | #5142 | `2dcb5e4bf` | **裁剪智能排料 v1**：A 类完整布并排（纯函数 + 判据） |
| #5162 | #5154 | `707ae2188` | 商品 + SKU **批量导入**（幂等 + 逐行校验报告 + 1 位小数） |
| #5163 | #5153 | `8a92450c5` | **批次建账入口**：期初入库单 + 旧批次号 + <1 米尾料可登记 |
| #5164 | #5158 | `92d40407f` | **排料接线**：领料按排料结果落账 + 两个米数落库 + 对账拆分 |
| #5165 | #5151 | `fb04bf432` | 用例解析渲染腿 **fail-closed** + 判据异常与发现数 0 分离（三态） |
| #5168 | #5167 | `3230416ff` | **best-fit** 批次指派策略（默认仍 FIFO，可显式切换） |
| #5172 | #5169 | `13e34fd32` | **池化 + 跨订单成组派单**（默认关；待派池 + 成批预览 + 兜底） |
| #5173 | #5166 | `982d2c5da` | **自毁式真值主张守卫**（零容忍 + 排除反面教材注释） |
| #5175 | #5174 | `cb961754f` | **SKU 级批次护栏生效**（读快照实际写入的 sku 键）+ 跨 SKU 显式拒绝 |
| #5176 | #5171 | `42d2f1f37` | `yaml_light` **多行标量取值保真**（块/跨行标量不再静默丢行） |
| #5178 | #5177 | `60e543564` | **池看板**（池化可用化）+ 订单级**加急/到货日** + 加急插队 |
| #5180 | #5170 | `11cd7677d` | skill **v1.48.0**（`.github/` 脚本两条实测约束 + 只读核查纪律） |
| #5181 | #5179 | `059cb5bfd` | `yaml_light` **双引号标量转义解码**（生成物取值对齐真值） |
| #5183 | #5182 | `c7a834fdb` | **事件驱动自动成批派单** + 业务兜底（默认关，阶段 2b-3） |
| #5185 | #5159 | `19488492c` | **省料度量 L2/L3**：批次分档聚合看板 + 单位产出消耗（存量单列、两指标并用） |
| #5186 | #5184 | `d0079bcde` | 自动派单**到点自愈载体**（只查业务约束，默认关） |
| #5187 | #5146 | `c5adc883d` | **余料成本回收**（非资产台账 + 可配小件尺寸 + 优先匹配 + 回收记账 + 报废留痕） |
| #5189 | #5188 | `b43a6cb29` | **米宝批次/省料只读工具 + 交互卡**（口径复用服务端读面） |

> 复算：`gh pr list --state merged --limit 30 --json number,title,mergeCommit`；或对任一 merge SHA 跑 `git diff --name-only <sha>^1 <sha>`。

---

## 2. 能力 × 三件套（**本节取代此前的口头「15 项」清单**）

**为什么取代**：独立验收 #1 曾给出一份「15 项交付物」清单并判 14/15，但该清单**只存在于会话提示里、不在仓库中** ⇒ 复核方无法复算（交叉验证 C6 判「无法判定」，判得对）。
⇒ 本报告把清单**落到仓库里**，改成「按合并单元逐条复算」的形式，从此可被任何第三方重跑。

| # | 能力 | 谁发射（代码路径，`com.migao.admin.` 省略） | 哪个入口可达 | 有无测试钉住（case / 测试） |
|---|---|---|---|---|
| 1 | 多行入库单批次号逐行生成 | `service/InboundOrderService` | `web:(dashboard)/inbound-orders/page.tsx` | `PR-045` |
| 2 | 库存 1 位小数 | `service/ProductService`、`controller/agent/AgentProductController` | 商品页 / 米宝 `product_manage` | `OR-047`、`PR-046`~`PR-051` |
| 3 | 过账并发闸/幂等键 | `service/InboundOrderService` | 入库单 API | `PR-058` |
| 4 | 派加工单扣批次库存 + 消耗台账 | `service/StockBatchConsumptionService` | `controller/ProcessingOrderController`、`controller/StockBatchController`、`components/products/BatchStockPanel.tsx` | `PR-055`~`PR-057`、`PG-060`、`BM-007` |
| 5 | A 类完整布并排排料 | `service/CuttingPlanService`（纯函数） | 生成加工单内部调用（无独立页面） | `PG-061` |
| 6 | 商品+SKU 批量导入 | `service/ProductImportService`、`controller/ProductController` | `web:(dashboard)/products/page.tsx` | `PR-059`、`PR-060` |
| 7 | 期初入库单 + 旧批次号 + <1m 尾料登记 | `service/InboundOrderService`、`controller/InboundOrderController` | `web:(dashboard)/inbound-orders/page.tsx` | `PR-061`、`PR-062` |
| 8 | 排料接线（米数落库 + 对账拆分） | `service/ProcessingOrderService`、`service/StockBatchConsumptionService` | 生成加工单 API | `PR-063`~`PR-065` |
| 9 | best-fit 批次指派 | `service/StockBatchConsumptionService` | `controller/StockBatchController` | `PR-066`~`PR-068` |
| 10 | 池化 + 跨订单成组派单 | `service/ProcessingOrderService`（`POOLED_DEFAULT_ENABLED=false`） | `controller/ProductionPoolController` | `PR-069`~`PR-072` |
| 11 | SKU 级批次护栏 | `service/ProcessingOrderService.buildSnapshot`（写 `sku` 键） | 生成加工单 API | `PR-076`~`PR-078` |
| 12 | 池看板 + 订单加急/到货日 + 插队 | `controller/OrderController`、`controller/MenuController`、`components/orders/OrderUrgencyPanel.tsx` | `web:(dashboard)/production/pool/page.tsx`、`web:(dashboard)/orders/new/page.tsx` | `PR-079`~`PR-082` |
| 13 | 自动成批（默认关） | `service/AutoBatchDispatchListener` | 事件驱动（确认支付/入库/改单） | `PR-086`~`PR-089` |
| 14 | 到点自愈载体（默认关） | `config/AutoBatchDueScanScheduler`、`config/AutoBatchDueScanHealthIndicator` | `migao.production.auto-batch.due-scan-cron` | `PR-090`~`PR-092` |
| 15 | 省料度量 L2/L3 看板 | `service/StockBatchConsumptionService.savingBoard/savingTrend` | `controller/StockBatchController`、`controller/MenuController`、`web:(dashboard)/production/saving-board/page.tsx` | `PR-093`~`PR-096` |
| 16 | 余料回收 + 可配小件尺寸表 | `service/RemnantService`、`controller/RemnantController` | `web:(dashboard)/production/remnants/page.tsx`、`components/settings/RemnantItemSizesPanel.tsx` | `PR-097`~`PR-099` |
| 17 | 米宝批次/省料只读工具 + 交互卡 | `ai-agent-service/app/tools/batch_stock_query.py` | 米宝对话（`components/chat/BatchStockCard.tsx`） | `PR-100`~`PR-102` |

**已知可达性缺口**：第 16 项 `production/remnants` 页面**未进侧边栏菜单**（与 pool / saving-board 不一致）⇒ 已立 `#5191`（P2，可达性而非功能）。

> 复算：`git diff --name-only <merge>^1 <merge> | grep -E "Controller\.java$|/page\.tsx$|Panel\.tsx$"`；case 号：`git diff -U0 <merge>^1 <merge> | grep -E "^\+ *- id: "`。

---

## 3. 验收方法

三路独立执行，**不复用实现会话的上下文**：

1. **可达性路**：在锚 SHA 上逐单元跑 `git diff` ⇒ 三件套（发射点 / 入口 / 测试引用）；判据 v1.11。
2. **UA 路（用户代理）**：以商家/工人身份走真界面与真 API，逐条判定**看得见、点得到、出事有反馈**；**禁止把判定留给「待人工」**。
3. **断言形态路**：抽样判「关键行为是否只写在自然语义 `data_checks` 里」——那是**空断言**（不会红）。

**判定纪律**：每条断言必须能引到**证据**（run id / SHA / 原始输出行）；**skip ≠ pass**；修复必须重放。

---

## 4. UA（用户代理）判定 — 4/4 通过

来源：独立验收 #2（执行体与实现包不同）。判定项与结论保留在其实施记录中；本报告只登记**结论与判据形态**：
- 商家侧可见（池看板 / 省料看板 / 余料台账 / 订单加急面板）；
- 工人侧可见（批次指定 / 小件尺寸表）；
- 米宝侧可见（批次与省料问答卡）；
- 配置类页面（小件尺寸表）遵循 `migao-dev-flow` §22。

> 局限：UA 判定为**用户代理**（AI 扮演），不是真人验收；真人验收前不宣称「用户验收通过」。

---

## 5. 断言形态与红证

- **44 条抽样（`PR-055`~`PR-099` 不含 073/074/075，加 `PG-060`/`BM-007`）：90 条 `traces.tests` 路径，缺失 0**（交叉验证 C5 逐条以 `git cat-file -e` 复算一致）。
- **0 个实例**：抽样中未发现「关键行为只写在自然语义里」的用例。
- **红证**：「不会红的断言 = 空断言」。高风险面逐条带单点可变红的红证（如 `#5146` 的 8 条真库判据各自带「手动改某列 ⇒ 同一读数必须变」的红证；`#5166` 是**自毁式真值主张守卫**本身）。
- **缺口（已立 issue）**：6 个机具型红证脚本（`pool-board` / `saving-metrics-red-proof-backend` / `-web` / `auto-batch` / `auto-batch-due-scan` / `cutting-plan`）**没有任何 CI 或门禁调用** ⇒ 红证只在人手跑时存在（`#5193`，P1）。

---

## 6. 双 AI 交叉验证（C1~C6）

复核方为**独立执行体**（未读主验收的工作树；一律用 `git show`/`git grep origin/main` + `git cat-file -e`；基线 `origin/main = c5adc883d`）。

### 6.1 C1 — 判定「不一致」，**主验收被推翻并订正** ✅ 已订正

| | |
|---|---|
| **主验收原判定** | 「所有 `*RealDbTest` 在 CI 上**从未跑过**」⇒ 真库判据在 CI 不受门禁、不会让任何 PR 变红（立为 `#5192` **P0**） |
| **复核方判定** | 「从未跑过」**很可能为假** —— 前提成立（`admin-api-test` 确无 `services:`、无装 PG），但推论错在「**无 PG 服务 = 无 PG 二进制**」：这些测试**不连服务**，而是 `PgCluster.start()` **自带一次性集群**（`initdb` + `pg_ctl`），`BIN_DIRS` 命中即不 abort；`ubuntu-latest`（24.04）官方镜像**内置 PostgreSQL** |
| **最终定案（集成方取证）** | **主验收原判定为假**；真库判据**本机在跑、CI 也在跑** |

**定案用的「正证」（不是推论，是执行痕迹）** —— `gh run view --job 106996112942 --log`（job = `admin-api unit tests`，run `35802605549`，runner `Image: ubuntu-24.04 / Version 20260907.300.1`）：

```
grep -cF "本机没有 PG 二进制" /tmp/job.log        # ⇒ 0（没有任何一条 skip 话术上屏）
2026-09-23T00:35:47.4522331Z [#5177 判别性实验] 真库快照读回 = {itemId=acc-5177-item, isUrgent=true, quantity=3, ...}
2026-09-23T00:35:59.8971163Z [#4967 判别性实验] 领活前该行 = {started_at=null, worker_id=null, ...}
2026-09-23 00:36:01.215 INFO c.migao.admin.service.RemnantService - 余料登记: tenant=5146, po=JG-ORD-5146-1, batch=PC-5146-TAKEN, lines=1, status=customer_taken
```

三条互相独立的证据：① 日志里带**只有真库测试才会打印**的「判别性实验」标记（`#5146/#5158/#5159/#5167/#5169/#5174/#5177/#4865/#4967`）；② 12 个真库夹具租户号逐条留痕（`4967:33 / 5146:900 / 5147:203 / 5158:164 / 5159:102 / 5167:173 / 5169:163 / 5174:105 / 5177:13 / 5182:325 / 5184:200`）；③ `PC-5146-TAKEN` 等字面量**只存在于** `RemnantRecoveryRealDbTest.java`，而该日志行由 `RemnantService` 在**写库成功之后**打印 ⇒ 集群没起来就不可能出现在日志里。

**对结论层的影响**：
- 真库判据的**证据等级不需要下调**（原判定若被执行，会导致**错误方向的证据降级与门禁放松**）。
- `#5192` 已重写为 **P1**，剩余风险改为「**缺 PG 时静默 skip 成绿**」（镜像换代/换 runner ⇒ 全体真库判据无声失效），修法 = CI 显式 fail-closed（`MIGAO_REQUIRE_REALDB=1` ⇒ `fail` 而非 `abort`）+ 二进制前置断言 + 「判据不许悄悄消失」的静态守卫。
- **方法论教训（留档）**：把「**没有 A**」当成「**没有 B**」——中间那一步必须去验，否则「证据不足」会被写成「事实不存在」。

### 6.2 其余交叉项

| 项 | 判定 | 说明 |
|---|---|---|
| C2 六个红证机具无 CI 调用 | **一致** | 逐名 `git grep` 在 `.github/workflows/*` + 三把工具中命中数**全为 0**；只在散文/文档里被提到 ⇒ `#5193` |
| C3 markdown `**` 泄漏到商家可见文案 | **一致** | 渲染层是纯文本插值（`{term.definition}` / `{p.copy.hint}`），`craft-calc-glossary.ts` / `tenant-params.ts` 的字符串字面量确含 `**`；`admin-web/src` 下 markdown 渲染器只出现在 `MessageList.tsx` ⇒ `#5194` |
| C4 PR-079/080 散文声称的红证无负向夹具 | **一致（措辞略过度概括）** | 用例侧确有散文声称红证；`product.yml:2850` 那条 UI 面红证确实无夹具（另有几条其实指名后端） ⇒ `#5195` |
| C5 44 条用例 `traces.tests` 存在性 | **一致（一处措辞不准）** | 42 条（含 backend-contract）+ `PG-060` + `BM-007` = 44 条用例 / 90 条路径 / 缺失 0；`PG-060`/`BM-007` 分别在 `processing-order.yml` / `bmini.yml`（不在 `product.yml`） |
| C6 「15 项三件套齐全」不可复核 | **无法判定 → 本报告已补齐载体** | 该清单此前只在会话里 ⇒ §2 已把可复算清单落库 |
| 载体一致性（池化/自动成批默认关、`#5188` 未合入） | **一致** | `POOLED_DEFAULT_ENABLED=false`、`AUTO_BATCH_DEFAULT_ENABLED=false` 为唯一缺省解析点；`#5188` 当时 OPEN ⇒ 现已由 `#5189 @ b43a6cb29` 合入 |

---

## 7. 未闭环项（全部为**证据强度/可达性补强**，无一影响业务判定）

| issue | 级别 | 内容 | 与判定层的关系 |
|---|---|---|---|
| `#5192` | P1 | 真库判据「缺 PG 静默 skip 成绿」（原 P0「从未跑过」**已被本报告推翻**） | 证据强度：不影响已取得的真库读数 |
| `#5193` | P1 | 六个红证机具无 CI/门禁调用 | 红证只在人手跑时存在 |
| `#5194` | P1 | markdown `**` 泄漏到商家可见文案 | 体验缺陷，不影响功能判定 |
| `#5195` | P1 | PR-079/PR-080 散文声称的红证无负向夹具 | 断言形态局部缺口 |
| `#5196` | P2 | `[backend-contract]` 的 `data_checks` 是文档不是断言 | 判据一致性 |
| `#5190` | P2 | `#5145` 批次台账缺 RealDbTest（依赖 `#5192`） | 证据强度 |
| `#5191` | P2 | `/production/remnants` 未进侧边栏菜单 | 可达性 |

**业务侧前置（非代码）**：
1. 客户需**先建账**（或录入期初入库单）⇒ 记录期才开始，度量才有分子分母；
2. 商家自行决定何时开启 `best-fit` 指派与**自动成批**（两者默认关是刻意的：记录期内不开行为变更）。

---

## 8. 偏离与限制登记

1. **⚠️ 跨模型独立性不足**：协议 §1.7 要求「双 AI 交叉验证用**不同模型族**」，本次跨模型 provider 在本会话**不可用** ⇒ 复核验收与主验收**同模型族**，独立性**弱于**协议标准。已如实登记（复核方亦在报告开头主动声明）。
2. **UA 判定是用户代理**，不是真人验收 ⇒ 本报告不宣称「用户验收通过」。
3. **C1 的定案只取了 1 个 job 的日志**（`106996112942`）。该 job 覆盖全部 10 个 `*RealDbTest` 的租户号痕迹；未逐 job 复算历史全部 run。
4. `#5194`（`**` 泄漏）在**本次验收时仍是活的** ⇒ 商家可见文案里会看到字面 `**`。

---

## 9. 复算命令（任何第三方可重跑）

```bash
# 锚
git fetch -q origin main && git rev-parse origin/main      # ⇒ b43a6cb29635d58a771ba62febf98331dc5506d4

# §1 交付单元表
gh pr list --state merged --limit 30 --json number,title,mergeCommit

# §2 三件套（逐单元）
git diff --name-only <merge-sha>^1 <merge-sha> | grep -E "Controller\.java$|/page\.tsx$|Panel\.tsx$"
git diff -U0 <merge-sha>^1 <merge-sha> | grep -E "^\+ *- id: "

# §6.1 C1 正证
gh run view --job 106996112942 --log > /tmp/job.log
grep -cF "本机没有 PG 二进制" /tmp/job.log
grep -oE "\[#[0-9]{4} [^]]{0,30}\]" /tmp/job.log | sort | uniq -c
grep -oE "\b(4967|5146|5147|5158|5159|5167|5169|5174|5177|5182|5184)\b" /tmp/job.log | sort | uniq -c
```

---

## 10. 验收后订正与新增发现（2026-09-23 追加，锚 `5229a73d4` 之后）

> 本报告的正文是**锚 `b43a6cb29` 的快照**，一字未改。本节记录**验收结束后**才取得的读数 —— 其中一条**改变了 §7 的口径**。

### 10.1 ✅ C1 已定案：#5192 的 Java 侧已修并落库

`PR #5199`（→ `f273adcb5`）：`PgCluster.startOrAbort()` 单一收口 + `MIGAO_REQUIRE_REALDB=1` 时缺 PG **判 FAIL 而非 skip** + CI 前置断言 + 静态守卫。
**红证 A 的对照组成立**：不带标记 + 搜索路径指空 ⇒ `Tests run: 0 / BUILD SUCCESS / EXIT=0`（这才是「静默绿」的确切读数，surefire 把 aborted 容器记成 `Tests run: 0`、`Skipped: 0`）；带标记 ⇒ `AssertionFailedError` + `EXIT=1`。
该包还**主动纠正了本报告 §1 的使用点清单**：`ProductionScanClaimRealDbTest` 与 `ProductionPartCodeRealMappingTest` **各藏一份嵌套 `PgCluster` 副本**（遮蔽包级共用件；按文本锚点 `private static final class PgCluster` 检索 —— **故意不写行号**：行号会随这两份副本被删掉而失效，`#5199` 正是把它们删了）⇒ 只改包级共用件时这两条真库判据照旧静默 skip。已删并收口（15 个使用点）。

### 10.2 🔴 新增 P0 `#5203`：**Python 侧的真库判据一直在 CI 上静默 skip**（本报告 §7 未覆盖）

**这条改变了 §7 的口径**：§7 把 `#5192` 当作「真库判据」相关的唯一项，但**真正在发生的失效在 Python 侧** —— 与 `#5192`（Java）**不同源**，`#5199` 治不到。

| 证据 | 读数 |
|---|---|
| 口径不对称 | Java `PgCluster.BIN_DIRS` 有硬编码兜底 `/usr/lib/postgresql/{16,15,14}/bin`；Python `_pg_available()` = `all(shutil.which(b) …)` —— **只认 PATH**，无兜底 |
| runner 上取到的读数 | job `107186750040` 打印 `initdb = /usr/lib/postgresql/16/bin/initdb` —— 该步先 `command -v initdb`、**找不到才回落** ⇒ PATH 里没有 initdb |
| 受控实验（猴补丁只藏三个二进制） | 本机全量 `3691 passed / 1 skipped` → **`3609 passed / 83 skipped`**；那 13 个模块 `190 passed` → `79 skipped` |
| CI 实测 | `3561 passed / 87 skipped`；扣掉新增 44 条守卫后投影 ≈ `3565 / 83` ⇒ **83 条被精确复现**，残差 4 |

⇒ **同一台 runner 上 Java 真库判据在跑、Python 在 skip**；被跳过的正是**迁移/回填/库存/幂等**这一族「钱与账」读数。
⇒ 且**无人会知道**：`[backend-contract]` 的 `traces.ci` 只被校验「引用的 workflow 文件存在」，**没有任何东西校验「那条通道真的执行了」**。

**方法论留档（我自己的两次仪器错误）**：
1. 第一次对照实验用「改 PATH」⇒ 把本机 `python3` 一起藏掉、29 个收集错误 ⇒ **无效实验**；换成只猴补丁 `shutil.which` 三处才成立。
2. 早前 `gh run view --log-failed` 返回空输出**不是**「没有失败信息」，而是 macOS **没有 `timeout` 命令**、命令根本没跑起来。
⇒ 两条都提醒：**「取到空/取到异常」先怀疑仪器，别先写结论**（与 §6.1 的「把没有 A 当成没有 B」同族）。

### 10.3 验收后新立的跟随 issue

| issue | 级别 | 内容 |
|---|---|---|
| `#5203` | **P0** | Python 侧 13 个真库判据在 CI 静默 skip（上文 10.2） |
| `#5216` | P1 | `auto-batch` / `due-scan` 红证机具**不删旧 surefire 报告** ⇒ 运行被打断时给出**错误归因**（同族 `pool-board` 有这道卫生） |
| `#5217` | P2 | 菜单**三源同构**守卫只比名字**不比图标** ⇒ 图标漂移无人抓（实证 `production-piecework` 前端 `Calculator` / 服务端 `Coins`） |

### 10.4 验收后落库的 PR

| PR | issue | merge | 说明 |
|---|---|---|---|
| `#5199` | `#5192` | `f273adcb5` | Java 侧真库 fail-closed（10.1） |
| `#5206` | `#5194`+`#5191` | `d3761834a` | 商家可见文案 `**` 泄漏收口（AST 守卫，含正控/负控）+ 余料台账进侧边栏（三源同构 + 权限同码，**未放宽**） |
| `#5212` | `#5193` | *(armed)* | 六个红证机具接入门禁：`--check` 前提自检面进 required job（**未改 workflow**，靠既有 `tests/unit_ci_workflows` 收集面）+ 本地 `verify-all.sh redproof` 实跑档 |

**过程中被门禁抓到的真缺陷（值得留档）**：`#5206` 首轮被 required 门禁判红 —— 新用例走了 `[backend-contract]` 豁免通道却**没给 `traces.ci`**，且没按基线 `_how_to_regen` **重锚**（读数 83 → 85 必须在同一 PR 内追加 history 行）。⇒ **门禁有效**，且该缺陷是「通道存在但没指明谁跑它」的同族形态。

### 10.5 §0 判定摘要的口径更正

- 「未闭环 7 项」⇒ 现为 **10 项**（原 7 项 + `#5203` P0 + `#5216` + `#5217`）；其中 **`#5203` 是唯一影响「本批真库判据可信度」的一项**。
- **§7 的读法更正**：`#5192`（Java）已闭环；**Python 侧的真库判据在 `#5203` 修好之前，其 CI 通道是「绿着没跑」** ⇒ 引用这些判据作为「最强证据层」时，**必须区分是 Java 还是 Python**，不可笼统写「真库判据已在 CI 跑」。
