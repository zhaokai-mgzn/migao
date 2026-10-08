# 第三轮深入功能测试 · 总报告（2026-10-03 下午/晚批次）

> 状态：**进行中**（两条线在飞；§3 读数待回收后填入）
> 时间口径：全部 **Asia/Shanghai（+08）**；引用 GitHub/CI 时间戳（UTC）时逐处标注换算
> 协议：`migao-acceptance`（L1 机器判定 + 每条断言带红证 + 证据链 + 不自我验收）
> 触发：用户 2026-10-03 16:12 +08 指示「这几个模块再做一次深度测试验证」——
> 指前一轮总报告 §6「下一批建议」之外的**两个组合**（若只再开一轮就选这两个）：
> ① **工人端 + 小程序写面**（零覆盖、真实生产写路径，性价比最高）
> ② **售后退款闭环 + 并发竞态**（涉钱、不可逆，且"并发"是全新方法学维度）

---

## 0. 本轮为什么这么切

前两轮已覆盖：41 路由全页面 / 9 身份 RBAC 三层 / 库存与工艺初始化 / 单据逐项 / 工人 H5 冒烟 /
连贯链路 18 环（`acceptance/2026-10-02/tenant20-full-sweep/`）；派工×工序×路线、配置写面横切、
计件量价链、跨租户隔离、发货仓储、AI Agent 服务域、批量导入导出、财务与库存下游
（`acceptance/2026-10-03/*/`）。

**本轮只打两块"从未被系统探过 + 真实生产写路径"的面**，并补**一个方法学缺口**：

| 线 | 目录 | 覆盖对象 | 为什么是它 |
|---|---|---|---|
| **A** | `worker-miniapp-writeface-sweep/` | 工人端 H5（`/api/worker/**` 扫码报工/完工/发货写面）+ 小程序 bmini-app 写面（入库过账/打标/派工/发货/售后状态/会话） | **车间里真正在点的按钮**；历史上只做过工人 H5 冒烟（登录 + 页面就位），**写面零覆盖** |
| **B** | `aftersales-concurrency-sweep/` | 售后退款闭环（建单→状态机→退款→退货回补库存→金额三方一致）+ **并发/竞态**（并发退款防双花 / 并发扣减超卖 / 并发派工 / 并发改状态）+ 大批量读（>1000 行） | **涉钱、不可逆、跨域最多**（订单×售后×库存×财务）；且**并发是全新维度**——至今全部测试都是串行单用户 |

**明确不在本轮范围**：真实 LLM 评测（用户 #4262 裁定不自动派发）；微信开发者工具 UI 级小程序 e2e
（`:21161` 未监听，需人工开模拟器）；打印/标签通道硬件。

---

## 1. 环境与构建点（**先钉事实**）

| 项 | 实测事实 | 复核命令 |
|---|---|---|
| 本轮准备时刻 | **2026-10-03 16:15:58 +08** | `cat acceptance/2026-10-03/env/env-round3.json` |
| 被测构建点 | `main-live` 工作树检出 **`43ca70322`**（= 准备时刻的 `origin/main`；含 #6204 导出截断+负库存修复、#6214 承载体第三批） | `git -C /Users/guangzhen.zk/migao-wt/main-live log -1 --format='%h %ad %s' --date=iso` |
| 切换登记 | 由 `cd0a7fd54`（16:02 起）→ `43ca70322`（16:15:38 起）；**切换在两条线开跑之前完成** ⇒ 本轮读数**单一构建点** | `acceptance/2026-10-03/env/prep-round3.sh` + `env/env-round3.json` |
| admin-api `:8080` | pid 55553（16:15:38 起），健康 401（需鉴权，正常） | `lsof -ti :8080` |
| worker-h5 `:3100` | 原进程 cwd 已被替换（全 404）⇒ 本轮重启，`/index.html` ⇒ **200** | `curl -o /dev/null -w '%{http_code}' http://127.0.0.1:3100/index.html` |
| ai-agent-service `:8001` | pid 63146，健康 200 | `curl http://127.0.0.1:8001/health` |
| admin-web `:3001` | pid 20265，200 | — |
| DB / Redis | 云 dev RDS（`ai_customer_service`）、Redis | `acceptance/2026-10-03/batch-writeface-sweep/harness/lib.mjs::psql()` |
| 被测租户 | `tenant_id=20`（米高POC演示布艺，管理员 13870217889，短信万能码 123456） | — |

**源码引用纪律**：一切源码级引用以 `git -C /Users/guangzhen.zk/migao-wt/main-live show HEAD:<path>` 为准
（主检出 ≠ 被测构建点）。

### 1.1 ⚠️ 环境事故与修复（**本轮第 1 条过程发现**，2026-10-03 16:22 +08）

| 项 | 内容 |
|---|---|
| 现象 | 两条线开跑后**管理员短信登录 401**（`AUTH_FAILED 短信验证码错误或已过期`），万能码 `123456` 不生效 |
| 根因 | 主会话 16:15 重启 `:8080` 时**未加载 `backend/admin-api/.env`** ⇒ Spring 属性 `sms.bypass-code`（`application.yml` 的 `${SMS_BYPASS_CODE:}`）为空。启动日志逐字：`[测试模式] 短信发送已 bypass，请使用万能验证码 (未启用)` |
| **为什么是"第二次"** | **同一事实上一批已留档但未定性、未开单**（`acceptance/2026-10-03/INTEGRATION-LOG.md` 逐字：「按 `Quick-Start.md` 的 `cd backend/admin-api && ./mvnw spring-boot:run` 起的进程里 `sms.bypass-code` 为空…⇒ dev 登录 401；`set -a; . ./.env; set +a` 后即通。**未定性、未开单**」）⇒ **同一个坑 3 小时内踩第二次**（铁律 10 / §30.2 的典型形态） |
| 处置（本轮内） | `acceptance/2026-10-03/env/fix-api-env.sh`：kill → `set -a; . ./.env; set +a` → `./mvnw -q spring-boot:run`；自证 = 启动日志出现 `[POC 模式]` 告警 + `POST /api/auth/sms/login {13870217889,123456}` ⇒ `success=true`（admin 王小明）|
| 影响面（精确） | **构建点未变**（前后都在 `43ca70322`，容器未换）；**DB 未变**（前后 DB peer 都是 `8.139.140.111:5432` = 云 RDS 公网 IP）⇒ **不影响任何 DB 侧读数**；受影响的只有"运行期环境注入"这一项。两条线在 16:22 前采集的、依赖 admin token 的读数按 **superseded** 处理 |
| 待办 | ① 根因承载体 = `docs/wiki/Quick-Start.md` 的本地启动命令**没有 `.env` 注入步骤**（实测逐字：`cd backend/admin-api && ./mvnw spring-boot:run`）；② 按 §30.2 应**开单 + 派小包**（doc 修 + 一条"起服务前自检 `.env` 已注入"的判据）；本轮先登记，包在两条线收口后派（机器负载：并发 ≤3） |

---

## 2. 跨包隔离协议（两线共用，防"归因错"）

同租户（20）两包并发 ⇒ 三条纪律，缺一条读数就不可信：

1. **探针对象自建**：统一前缀（线A `线A验收` / 线B `线B验收`），用后自清；
2. **短写窗口 + 逐条还原**：必须改的既有行，逐条立即还原；
3. **归因按行内容**：命中自己前缀 = 本包副作用；不是自己的行 = **外来行** ⇒ 记 `skip`（疑似并发干扰），**先还原再重跑**。

另：两包**均禁止**跑 `verify-all.sh gate/full`、`batch-gate`、全量 pytest（机器级重活锁口径，§27）；
**禁止真实 LLM 调用/评测**（#4262）。

---

## 3. 各线读数（回收中）

> 口径：**包的读数**与**主会话独立复核**分开列；冲突时以更强证据一方为准。
> 判据四态分列：pass / fail（产品）/ 假红（判据缺陷）/ skip（未覆盖，**永不记 pass**）。

### 3.1 线A `worker-miniapp-writeface-sweep`

（待回收）

### 3.2 线B `aftersales-concurrency-sweep`

（待回收）

---

## 4. 发现项处置

> 口径：AI 能靠 durable 证据裁的当场自裁，只把业务口径/涉钱/权限/不可逆/需外部输入五类交人工。

### 4.1 主会话独立定位并已开单的产品发现（两条都**不是**包里的 pass）

| # | 发现 | 级别 | 承载体 | 证据链（可复算） |
|---|---|---|---|---|
| **F1** | **一体机裁高读面 500**：订单明细 `product_id` 为空时，`WorkerCuttingHeightService::positionRow` 对 `brands(...)` 的**不可变空表** `Map.of()` 做 `get(null)` ⇒ NPE ⇒ `500 INTERNAL_ERROR`（javadoc 意图恰是「缺 ⇒ null，不猜」） | **P2** | **issue #6219** | ① 线A `C23` 读数 `HTTP 500` + `INTERNAL_ERROR`；② API 日志 16:26:24.407 逐字 `NullPointerException at WorkerCuttingHeightService.positionRow(:149) → read(:107) → WorkerProductionController.cuttingHeight(:198)`；③ 源码 `brands()` 空 productIds ⇒ `Map.of()`；④ `javap -c` 行号表 `:149 → 偏移 152` = `brands → getProductId() → Map.get`；⑤ **JDK21 实跑**：`Map.of().get(null)` ⇒ NPE、`Map.of(k,v).get(null)` ⇒ NPE、`LinkedHashMap.get(null)` ⇒ `null` |
| **F2** | **售后工单并发完结 ⇒ 库存被回补 4 次**（`updateTicketStatus` 读-判-写、`updateById` 无条件覆盖；`maybeRestockOnReturn` 零并发保护 —— 而同一事务里的 `linkRefundToOrderAndFinance` **有** DB 原子条件更新 ⇒ **一个副作用有护栏、另一个没有**） | **P1·涉钱/库存**（不可逆虚增） | **issue #6220** | ① 线B `LB-C2` 三轮一致：`成功数=4 / 库存 98→106 / 台账 4 行 / 时间线 5 行 / 退款侧 refundOver=false`；② **主会话独立 DB 复核**：三张探针工单（`AS-20261003-0020/0021/0022`）各恰 4 行 `stock_ledger_entries`，逐行 `98→100、100→102、102→104、104→106`；③ 源码流转表 + `updateById` 写法；④ 可达性：双击/两人同时点"完结" |
| **F3** | **退款金额 `0.001` 被接受（200）却在写库时静默舍成 `0`**：金额入口无小数位准入（`orders.refund_amount` / `finance_transactions.amount` 均为 `numeric(·,2)`），而库存侧 `StockQuantity.requireOneDecimal` 的既有范式是**显式拒绝** | **P2·涉钱·精度** | **issue #6221** | ① 线B `LB-PREC-01/02/03` 逐字：`0.01 ⇒ 200/0.01/0.01`（正对照）、**`0.001 ⇒ 200/0/0`**、`0.004⇒0`、`0.005⇒0.01`、`0.009⇒0.01`；② 主会话现查 `information_schema` 列类型（`numeric(12,2)` / `numeric(10,2)`）；③ 同仓两套口径（库存拒、金额不拒） |
| **F4** | **分页参数无准入：`size<0` ⇒ `total` 被算成 `0` 而 `items` 返回全部行**（同一响应自相矛盾：`total=0` vs `rows=478`） | **P3·读面** | **issue #6222** | ① 线B `LB-C4` 读数；② **主会话独立复现**：`size=-5` ⇒ `200 / total=0 / size=500 / rows=478`；`size=-1&page=-1` 同；对照 `size=5000 ⇒ size 钳 500、total 诚实、跨页求和==total` |
| **F5** | **`refund_method` 是零生产者字段**：DB 列在、API 响应返回它、前端 `types/index.ts` 声明为 `'original_route'｜'bank_transfer'｜'balance'` 三值枚举，但**全仓 0 个写入点** ⇒ 「退款方式」在用户面前恒为空（`声明存在 ≠ 可达`） | **P3·售后**（口径待人工挑"接线 vs 下线"） | **issue #6224** | ① 线B `LB-REF-B05` 逐字：工单 `refund_method` 全程 `null`；② 主会话**生产者扫描**：`grep -rn "setRefundMethod\|refundMethod" backend/ --include=*.java` ⇒ 仅 entity/DTO 声明 + 2 处**读**（映射进响应），**0 写点**；③ 迁移无回填 |

### 4.1.1 修复包派发（2026-10-03 16:42 +08 起，并发 = 3）

| 包 | issue | 分支 / worktree（**路径含空格**） | 状态 |
|---|---|---|---|
| F-6220 | #6220（P1） | `fix/6220-aftersales-concurrency` @ `/Users/guangzhen.zk/ai native/migao-wt/6220-aftersales-concurrency` | 已派（在飞） |
| F-6219 | #6219（P2） | `fix/6219-cutting-height-npe` @ `/Users/guangzhen.zk/migao-wt/6219-cutting-height-npe` | 已派（在飞） |
| F-6221 / F-6222 | #6221 / #6222 | 待派（线A 收口后，保持并发 ≤3） | 待派 |

> ⚠️ **本机 worktree 根有两种**（`/Users/guangzhen.zk/migao-wt/` 与 `/Users/guangzhen.zk/ai native/migao-wt/`，后者含空格）——
> `dev-worktree.sh` 的两个根都出现过（同一批次的 6220 落在带空格那个、6219 落在不带空格那个）。
> **派包时必须用 `git worktree list` 的实测输出定位**，不要按习惯拼路径（本会话已因此误发过一次路径）。

**同一轮里被抓出的两条"假绿"（判据形态，须回灌口径）**：

| 包内判据 | 表象 | 真值 | 形态 |
|---|---|---|---|
| 线A `C23` | 判 **pass** | 实测 `HTTP 500` | `pass` 分支写成 `status >= 400` ⇒ **把 5xx 一起吞了** |
| 线B `LB-C4-BULK-READ` | 判 **pass** | 实测 `total=undefined rows=null` | **读数取不到真值却判通过**（`records` vs `items` 取数路径）⇒ 与上一轮线① 同族 |

⇒ 口径：**任何"4xx 可接受"的期望必须写 `>=400 && <500`**；**任何 `undefined/null` 的读数不得支撑 pass**。

### 4.2 待人工确认

（本轮暂无；F1/F2 均按 §30.1 由 AI 依 durable 证据自裁为缺陷）

---

## 5. 本轮**未能**覆盖的面（照实登记，不粉饰）

（待填）
