# 下一轮深入功能测试 · 总报告（2026-10-03 下午批次）

> 状态：**进行中**（三包在飞；§3 各线读数待回收后填入）
> 时间口径：全部 **Asia/Shanghai（+08）**；引用 GitHub/CI 时间戳（UTC）时逐处标注换算
> 协议：`migao-acceptance`（L1 机器判定 + 每条断言带红证 + 证据链 + 不自我验收）

---

## 0. 本轮为什么这么切

前两轮已覆盖：41 路由全页面 / 9 身份 RBAC 三层 / 库存与工艺初始化 / 单据逐项 / 工人 H5 / 连贯链路 18 环
（`acceptance/2026-10-02/tenant20-full-sweep/`）；派工×工序×路线、配置写面横切、计件量价链、跨租户隔离、发货仓储
（`acceptance/2026-10-03/*/`）。

**本轮只打三块从未被探过的面**（并发 3，沿用上一轮跨包隔离协议）：

| 线 | 目录 | 覆盖对象 | 为什么是它 |
|---|---|---|---|
| ① | `agent-service-sweep/` | AI Agent 服务域（`:8001`）：B/C 双身份作用域、租户链路与并发串号、知识库+客服工作台闭环 | 全产品唯一**零覆盖**的主面；线②上轮已登记为未覆盖面 |
| ② | `batch-writeface-sweep/` | 导入 / 导出 / 批量上下架与删除 / `detach-and-delete` / 上传 6 端点 + 并发幂等 | **爆炸半径最大且从未探过**（上轮登记：batch/import/export/upload 未覆盖） |
| ③ | `finance-stock-time-sweep/` | 钱的收尾段（结算/发放/导出）、库存下游（退货/调账/报损/库龄/残料）、账期时间口径 | 线①上轮只验到「算」；时间口径是系统性风险面（9/25 出过同类假红） |

**明确不在本轮范围**：真实 LLM 评测（用户 #4262 裁定不自动派发）；打印/标签通道；登录链路；C 端小程序（#5642）；裁剪机等未落地模块。

---

## 1. 环境与构建点（**先钉事实，再看结论**）

| 项 | 实测事实 | 复核命令 |
|---|---|---|
| 仓库工作树 | `/Users/guangzhen.zk/ai native/migao`，分支 **`feat/logistics-track-cache`**，HEAD `0a28014ff` | `git status -sb` |
| `origin/main` | `d877f19ef` | `git rev-parse --short origin/main` |
| admin-api `:8080` | pid 99086，cwd `migao-wt/main-live/backend/admin-api`，启动 **13:09:45 +08**，构建点 **`d1c09d02f`** | `lsof -ti :8080` + `git -C /Users/guangzhen.zk/migao-wt/main-live log -1` |
| admin-web `:3001` | pid 20265，启动 09:54:23 +08 | 同上 |
| worker-h5 `:3100` | pid 27848，启动 10-02 22:54:12 +08 | 同上 |
| ai-agent-service `:8001` | **起服务前未监听**；由线①自行从**干净 origin/main 检出**拉起 | `lsof -ti :8001` |
| DB / Redis | 云 dev RDS `ai_customer_service`（TCP 实测通）、Redis `r-bp162…` | `nc -z pgm-bp1p7w92k81ob5to-pub.pg.rds.aliyuncs.com 5432` |
| 被测租户 | `tenant_id=20`（米高POC演示布艺，管理员 13870217889，短信万能码 123456） | — |

### 1.1 运行构建 vs `origin/main` 的差集（**本轮最关键的环境事实**）

⚠️ **构建点在批内被切换过（协议红线，已按时间切分归属）**：

| 时段（+08） | `:8080` 构建点 | 进程 | 影响的包 |
|---|---|---|---|
| 13:09:45 – 13:44:15 | `d1c09d02f` | pid 99086 | 线②③ 的开跑读数 |
| **13:44:16 起** | **`7e9f66ce5`**「fix(6181): 商家发货三步原子化 —— 建单按调用方显式传入的流转事实，整条路单事务（**#6190**）」 | pid 60585 | 线① 全部 + 线②③ 的切换后读数 |

⇒ 已发指令要求线②③**按时间切分归属**、**跨切换窗口的判据重跑**、并各产 `buildpoint-shift.json`。
**内容级**结论（源码面）不受构建切换影响，照旧成立。

**`main-live(d1c09d02f)..origin/main` 的差集**（切换前实测）= **3 个提交**：

| 提交 | 内容 |
|---|---|
| `d877f19ef` | #6178/#6180 活锚自检空比对 fail-closed（scripts） |
| `14e5bcbd9` | #6187 flaky 台账追加（CI 台账） |
| `7ea465067` | #6184 验收产物入仓（acceptance/**） |

⇒ 当时**业务代码 diff = 零**（`git diff --stat` 为空）⇒ 运行行为等价于 `origin/main`。
**切换后** `main-live HEAD = 7e9f66ce5`（含 #6190）—— 见 §1.2 的更新。

### 1.2 两个"声明 vs 可达"的事实订正（铁律 11）

1. **#6185（物流轨迹缓存，P1·涉钱）并未合入 main**：`origin/main` 无 `backend/ai-agent-service/app/core/logistics_trace_cache.py`，
   且 `origin/main` 的 `app/core/__init__.py` / `app/tools/logistics_track.py` **都不 import 它**（自洽）⇒
   该功能由**在飞 PR #6189**（`feat/logistics-track-cache`，issue #6185 仍 `OPEN`）承载。
   ⚠️ **主检出的当前分支就是这个在飞分支**（`git status -sb` 首行 = `## feat/logistics-track-cache...`），其工作树里
   `logistics_trace_cache.py` 与 `logistics_track.py` 是**未提交改动**（属 PR #6189 的正常工作树态）。
   ⇒ 任何**从主检出**起的服务，跑的都**不是 main**，读数不得写成 main 现状。线①已按此要求改从干净 `origin/main` 检出起服务。
   *（本条是主会话自己的一次自我订正留档：初判「无主未提交代码」是错的，真相是"在飞 PR 的工作树"。）*
2. **#6181（商家发货建单重做，P1 回归）**：**2026-10-03 13:44:16 +08 前未合入**，当时现行契约 = **回退态**
   （商家发货路**不产生发货单**，上轮判据 `K3-2`/`K3-3` 处于"先红后绿"窗口）；
   **切换后已随 `7e9f66ce5`（#6190「商家发货三步原子化」）上线** ⇒ 该窗口**关闭**，
   `K3-2`/`K3-3` 应由红转绿 —— **需按「修复必须重放」用 `shipments-sweep/harness/run-all.mjs` 重放确认**（列入 §4 待办）。

---

## 1.3 射程订正：线④ 已跑过（含其缺口 → 已转交线①）

`acceptance/2026-10-03/tenant-concurrency-sweep/`（线④，随 #6184 入 `origin/main`）**已经覆盖**「并发 × 跨租户串号 + `:8001` 租户链路」的相当一部分：
`/api/internal/tools/execute` 的租户归属（`body.tenant_id` 决定 / `X-Tenant-Id` 头在 `:8001` **不被消费**，20→35 件、21→1 件、1→93 件、越租户 0 件）、写工具 403 拦截、admin-api 线程边界 14 条 pass（180/388 线程服务过 >1 租户）。

**⇒ 本轮线①（`agent-service-sweep`）据此收窄为「接手线④ 的缺口」，不再重复其已覆盖项**：

| 线④ 的缺口（其 §9 自曝） | 线① 的接手动作 |
|---|---|
| 它的 `:8001` 跑在**仓内工作树未提交代码**上（非 `origin/main`） | 从**干净 `origin/main` 检出**起服务 ⇒ 构成独立复测，并登记两者构建点差异 |
| `DEBUG=true` + `X-Debug-Role` **无 token 放行**旁路（`:8001/api/chat/orders/mine` → 200/租户 1），只能记为"代码级声明" | 以 **`DEBUG=false`** 起服务 ⇒ 断言该请求 **必须 401/403**；再用 `DEBUG=true` 侧夹住证明判据有判别力 |
| C 端真实 token 的端到端未测（云 dev 无 `users↔orders` 关联） | 能构造则补测；不能则**照实登记未覆盖**，不得用调试旁路冒充 |
| `@Async SessionDistillListener` 只有代码级读数 | 隔离栈建会话→结束→断言 `knowledge_candidates.tenant_id` 与结束方一致 |
| 知识库全生命周期、客服工作台转人工闭环 | 归线①（其原射程） |

**注**：线④ 报告 §10 **自曝未做双 AI 交叉验证** ⇒ 其结论**不得**被引用为"已双裁通过"；本批次三包同理，报告结论一律由主会话独立抽样复核后才收口。

### 1.3.1 主会话对线④ 两条关键声明的独立核实（`origin/main`，只读，铁律 11）

| 线④ 的声明 | 主会话核实读数（`git show origin/main:<path>`） | 判定 |
|---|---|---|
| `DEBUG` 旁路"生产不可达" | `app/utils/auth.py`：放行分支**同时**要求 `settings.DEBUG` ∧ `X-Debug-Role` 头（`DEBUG_CUSTOMER_USER_ID="debug_customer_1"`，且 `_DEBUG_USER_ID_RE` 白名单锚定 + `service token` 未配置时 **503 fail-closed**） | ✅ 与声明一致 |
| —（加强）| `app/config.py:15` `DEBUG: bool = False`（**默认关**）+ `:118-132` `validate_production_secrets`：非 DEBUG 下缺 `JWT_PUBLIC_KEY`/`SERVICE_TOKEN` ⇒ **抛异常拒启动**（fail-fast） | ✅ 「生产不可达」**由代码保证**，不是仅靠部署约定 |
| `:8001` 不消费 `X-Tenant-Id` | 与 §1.3 表内读数一致 | ✅ |

⇒ 线① 的 `DEBUG=false` 判据因此**可红**（`DEBUG=false` 时该分支必然不可达），不是空断言。

---

## 2. 跨包隔离协议（三包共用，防"归因错"）

同租户（20）三包并发 ⇒ 三条纪律，缺一条读数就不可信：

1. **探针对象自建**：统一前缀（线① `线①验收` / 线② `线②验收` / 线③ `线③验收`），用后自清；
2. **短写窗口 + 逐条还原**：必须改的既有行，逐条立即还原；
3. **归因按行内容**：命中自己前缀 = 本包副作用（发现）；不是自己的行 = **外来行** ⇒ 记 `skip`（疑似并发干扰），**先还原再重跑**。

另：三包**均禁止**跑 `verify-all.sh gate/full`、`batch-gate`、全量 pytest（机器级重活锁口径，§27）。
主会话已实测锁在本批次启动时**曾被 `verify-all.sh gate` 占用**、启动后**已释放**。

---

## 3. 各线读数（待回收）

> 回收后逐线填入：§3.x 读数汇总（pass/fail/skip 分列）+ 发现清单（级别/证据文件）+ 未覆盖面 + 红证台账 + 零残留自证。

（待填：线① `agent-service-sweep/REPORT.md`）
（待填：线② `batch-writeface-sweep/REPORT.md`）
（待填：线③ `finance-stock-time-sweep/REPORT.md`）

---

## 3.5 ✅ 已确证：验收工具链自身的时区缺陷（**非产品缺陷**，但污染历史台账的"时间"字段）

**发现（2026-10-03 13:41 +08，主会话复现）**：历轮验收包的 `harness/lib.mjs::nowCST()` 存在**双重时区换算**，
产出的 `cst` 字段 = **真实 +08 时刻 + 8 小时**。

**根因（本机实测，非推断）**：
```
本机 TZ 未设 ⇒ 本地时区即 Asia/Shanghai；真实 2026-10-03 13:42
getTimezoneOffset() = -480  ⇒  代码里 off = -(-480) = +480
new Date(d.getTime() + off*60000) 再用【本地 getter】getHours() 取值
⇒ 偏移被加了两次 ⇒ 输出 "2026-10-03 21:42 +08"
对照：Intl.DateTimeFormat(...,{timeZone:'Asia/Shanghai'}) → 13:42:09 ✅
```
**自相矛盾即可判红**：`out/buildpoint.json` 同时写 `observedAt.cst = "2026-10-03 21:40:23 +08"` 与
`observedAt.utc = "2026-10-03T05:40:23Z"` —— 后者换算正是 **13:40**。同一文件两个字段差 8 小时。

**污染范围（守卫清单）**：

| 载体 | 是否带该 bug | 证据 |
|---|---|---|
| `acceptance/2026-10-03/shipments-sweep/harness/lib.mjs`（**已入 `origin/main`**，随 #6184） | 🔴 有 | 其台账写"测量窗 18:47–18:50 +08"，而 `out/*.json` 的 cst = `18:34:55 / 18:49:21 / 18:50:07` ⇒ 真实时刻为 **10:34–10:50** |
| `acceptance/2026-10-03/agent-service-sweep/harness/lib.mjs`（本轮） | 🔴 有（从上一轮复制） | 已发订正给线① |
| `acceptance/2026-10-03/finance-stock-time-sweep/harness/lib.mjs`（本轮） | 🔴 有（从上一轮复制） | 已发订正给线③（并要求重算其账期判据的时间窗） |
| `acceptance/2026-10-03/batch-writeface-sweep/harness/lib.mjs`（本轮） | ✅ 干净 | 已改 Intl，且注释里已识破"getTimezoneOffset 返回 0"这一误判 |
| `dispatch-routing-sweep` / `config-writeface-sweep` / `piecework-wage-sweep` / `tenant-concurrency-sweep` / `tenant20-full-sweep` | ✅ 无 `nowCST` | 逐文件 `grep` 判定 |

**影响面（精确，不过度声称）**：
- 受影响的是**台账的"时刻"字段**（`at` / `observedAt.cst` / 叙述里的"测量窗"）⇒ **引用这些时刻前必须 −8h**；
- **不**影响判据的通过/失败结论（该函数只用于打时间戳与日志）；
- **例外**：本轮线③ 的**账期/日切类判据**若用 `nowCST()` 计算"今天/本月/窗口"，其**结论**会整体错位 8 小时 ⇒ 已要求它用独立口径（SQL `now() at time zone 'Asia/Shanghai'` 或整数时间戳）重算并重跑该族。

**修法**：去掉 `+ off*60000`（本地 getter 本就直接可用），或改用
`new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',hour12:false,...})`。

**复算命令（一条，可复现本条发现）**：
```bash
node -e "const d=new Date(),p=n=>String(n).padStart(2,'0');const l=new Date(d.getTime()+(-d.getTimezoneOffset())*60000);console.log('真实:',d.getHours()+':'+p(d.getMinutes()),'| 旧nowCST:',l.getHours()+':'+p(l.getMinutes()),'| Intl:',new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',hour12:false,timeStyle:'medium'}).format(d))"
```

**处置（本轮内）**：① 三包当场修（已发订正）；② 本条作为**类级结果**登记，并作为「时间口径横切」这一整线价值的**首个实证**——
我们连自己的工装都在时区上栽跟头，被测系统的账期口径更需要专门一轮；③ 已入 main 的 `shipments-sweep` 台账
**不**在本轮回改（避免与在飞包冲突），改由**收口时统一修 + 在 §6 登记**。

---

## 3.6 主会话对在飞读数的**独立核验**（不自我验收；只录已复核项）

> 口径：以下每一行都由主会话**独立复算**（`git show origin/main:<path>` 读实现 + 实跑 psql + 读包自己的 JSON），
> 不采信包的叙述。**包最终 REPORT 若与本表冲突，以本表为准**（或包给出更强证据后由主会话更新本表）。

### 线② `batch-writeface-sweep`：4 组判据定性（把"假红/期望错"从"产品缺陷"里摘出来）

| 包内读数 | 包的判定 | **主会话定性** | 独立依据 |
|---|---|---|---|
| `A5.1/A5.2/A5.3/A5.4/A5.6`（导出 0 行、表头空） | fail | 🔵 **假红（harness 缺陷）** | 导出实现是真 **xlsx 二进制**（`ProductService.exportProducts`：`XSSFWorkbook` + `contentType=…spreadsheetml.sheet` + `Content-Disposition: 商品列表.xlsx`）；包自己的读数自相矛盾：`bytes=5500` 却 `rowCount=0, headers=[]` ⇒ 解析器没读懂 xlsx |
| `A6.1`（导入模板表头空） | fail | 🔵 **假红（同因）** | 模板同为 xlsx |
| `B1.1/B1.2/B1.3`（batch 上架 3/3 失败） | fail | 🔵 **期望错（不是缺陷）** | `ProductService.batchOnShelf` 白名单 `Set.of("off_sale")`，源码注释逐字「只有 off_sale/in_warehouse 状态的商品可上架」；探针商品是 `draft` ⇒ **系统正确拒绝** |
| `C1.3` 两项 `dangling` | fail | 🔵 **工具报错（≠ 命中）** | 读数是 `"ERR Error: Command failed: psql …"`；主会话实测同一连接正常（`select count(*) from products where tenant_id=20` ⇒ **41**）⇒ 必须重查或记 `skip` |
| `C1.4`（二次 detach-and-delete ⇒ 404） | fail | 🟡 **口径登记（非缺陷）** | 资源已不存在 ⇒ 404 是标准 REST 语义；实现注释若声称"幂等 200"则**注释需订正** |
| `B3.0`（正对照：探针商品 SKU 子行 = 0） | fail | ⚠️ **前置不成立 ⇒ SKU 闭包未判定** | 包自己红了正对照 ⇒ 该闭包判据此时无判别力，须补夹具重跑或记 skip |
| `B3.1`（`batch/delete` 后 `product_colors` 孤儿 1 行） | fail | 🔵 **假红（schema 前提不成立）** | 独立核实：`product_skus` / `product_colors` **都没有 `deleted` 列**（软删只在 `products` / `stock_ledger_entries`）⇒ 包的 `c.deleted=0` 查询前提为假；子表**按设计随父行逻辑不可见**。正确判据应是「父行软删后子行**是否仍可被读面/写面独立触达**」，若不可达 ⇒ 应判 PASS |
| `A4.3`（`.csv` 扩展名 ⇒ 200） | fail | 🟡 **待核口径** | `WorkbookFactory.create` 只认真 Excel；产品是否声明支持 CSV 决定此条是缺陷还是"期望过严" |

### 线① `agent-service-sweep`：3 条 fail 定性为假红

| 包内读数 | 主会话定性 | 独立依据 |
|---|---|---|
| `B2-20` / `B2-21` / `B6-3` | 🔵 **假红（判据缺前缀归一化）** | 同一个 JSON 内：`expected customer_id="A1_…"` vs 实得 `"probe_line1_A1_…"`；`B6-3` 的 mismatch 明细 `want:20, got.tenant_id:20` ⇒ **`tenant_id` 逐条一致**，唯一差异是自身探针前缀 |

> 线① 其余读数经核**判据设计正确**：A 组 18/18（含正对照 `A2-positive` ⇒ 200，排除"一律 401"）、
> `B5-2` 伪造 `X-Tenant-Id` 无效、`B7` C 端 JWT 不认内部面、`B3/B4` 跨租户与他人会话全拒。
> 且它已**从干净 `origin/main` 检出**起服务（`migao-wt/line1-agent @ d877f19ef`，`dirty=""`），
> 并在 `DEBUG=false` 下实测「无 token + `X-Debug-Role` ⇒ 401」——**补上了线④ 只能"代码级声明"的那条**。

### 线③ `finance-stock-time-sweep`

（待回收；已要求其账期族用独立时间口径重算——见 §3.5）

---

## 3.7 🔴 产品发现（主会话独立定位，源码级）：财务查询的日期窗口用 **UTC 日界**，不是 +08 日界

**级别：P1 · 涉钱**（月度汇总 / 应收对账 / 交易列表的**日期归属**）

**根因（`origin/main` 逐字）**：
```java
// backend/admin-api/src/main/java/com/migao/admin/service/FinanceService.java:430-436
private OffsetDateTime parseDateStart(String date) { return OffsetDateTime.parse(date + "T00:00:00Z"); }  // ← 固定 UTC
private OffsetDateTime parseDateEnd(String date)   { return OffsetDateTime.parse(date + "T23:59:59Z"); }
```
调用点**三处同源**：`getTransactions`（:84 起）、`getSummary`（:195 起）、`getReconciliation`（:291 起，比对 `Order::getCreatedAt`）。

**可观察后果**：`startDate=endDate=2026-10-01` 的实际窗口 = `[10-01T00:00Z, 10-01T23:59:59Z]` = **北京时间 `[10-01 08:00, 10-02 07:59:59]`**
⇒ 北京 `00:00–08:00` 的交易被归到**前一天/前一月**（跨月/跨年时归错月），且当天 `08:00` 之后的窗口会**混入次日数据**。

**证据（三方互相印证，非单点读数）**：
1. **源码逐字**（上）；
2. 线③ `out/C0-injection-fingerprint.json` 的探针逐条 UTC 换算；
3. 线③ 实测三连（`C1-B`/`C1-C`/`C1-E` 全部"不包含"、`C2-2026-01` `incomeCount=0` 而独立 SQL 计 1 笔）：

| 探针（写库为 +08） | UTC 值 | 是否落在 UTC 窗口 `[10-01T00:00Z, 10-01T23:59:59Z]` | 实测 | 是否自洽 |
|---|---|---|---|---|
| `3B = 10-01T00:00+08` | `09-30T16:00Z` | ❌ 窗口之前 | 不包含 | ✅ |
| `3C = 10-01T02:00+08` | `09-30T18:00Z` | ❌ | 不包含 | ✅ |
| `3E = 2026-01-01T00:01+08` | `2025-12-31T16:01Z` | ❌ | 不包含 | ✅ |

**同时纠正线③ 的一处误判**：它把 `C4`（"把探针平移 +1 天 ⇒ 判据仍命中 ⇒ **空断言**"）判为红。
实测：平移后 `10-02T00:00+08 = 10-01T16:00Z`，**恰好落进 UTC 窗口** ⇒ 命中是**正确行为**；
该条应改判为「窗口确实在过滤，只是边界是 UTC」的**正对照**（证据更强）。已发指令要求改判并重设计红证
（用 `北京 10-01 07:59:59` = `09-30T23:59:59Z` 这种**跨口径判别点**，并**写明所选口径**）。

**复算命令（一条，可复现）**：
```bash
# 窗口边界是 UTC 的证据
git show origin/main:backend/admin-api/src/main/java/com/migao/admin/service/FinanceService.java | sed -n '430,436p'
# 探针的 +08 → UTC 换算
TZ=Asia/Shanghai date -j -f '%Y-%m-%dT%H:%M:%S%z' '2026-10-01T00:00:00+0800' -u '+%Y-%m-%dT%H:%M:%SZ'   # ⇒ 2026-09-30T16:00:00Z
```

### 3.7.1 升级：这是**类级**缺陷（三处同族调用点 + 已有守卫未覆盖该形态）

`git grep "T00:00:00Z\|T23:59:59Z\|atStartOfDay" -- admin-api/src/main` 命中**三个服务、两个同族写法**：

| 文件:行 | 写法 | 影响面 |
|---|---|---|
| `FinanceService.java:431,435` | `OffsetDateTime.parse(date + "T00:00:00Z")` | 财务汇总 / 交易列表 / 应收对账的**日期归属** |
| `OrderService.java:208,211` | 同上（`Order::getCreatedAt`） | **订单列表按日期筛选**的归属 |
| `ProductService.java:194,199` | `.atStartOfDay().atOffset(ZoneOffset.UTC)` | **商品列表按日期筛选**的归属 |

**而仓里早有正确单源，且这三个服务本来就在用**：`backend/admin-api/src/main/java/com/migao/admin/time/BusinessClock.java`
（issue #3802：全仓「业务今天/业务现在」唯一来源，口径固定 `Asia/Shanghai`，`startOfDay(date)` 即 `00:00:00+08:00`）。
它的 javadoc **逐字描述的就是这个缺陷形态**：「更差的拼写是 `LocalDate.now().atStartOfDay().offset(ZoneOffset.ofHours(8))`：取的是 **UTC 日**边界、只是给它贴了 +08 标签」。

**已有类级守卫的射程（本轮新形态正好落在它之外）**：
`backend/admin-api/src/test/java/com/migao/admin/time/BusinessClockSourceGuardTest.java`（禁 `src/main` 内 `"Asia/Shanghai"` 字面量 / 无参 `now()`，每条禁则须有坏样本 `rulesHaveDiscriminatingPower`）
—— 其坏样本是 `LocalDate.now().atStartOfDay().atOffset(ZoneOffset.ofHours(8))`，**不含** `parse(date + "T00:00:00Z")` 这一形态。

⇒ **处置口径（精确、可固化）**：
1. 三个调用点改为 `businessClock.startOfDay(LocalDate.parse(date))` / `startOfDay(plusDays(1)).minusNanos(1)`（或等价）；
2. **给已有守卫加一条 needle**（`T00:00:00Z` / `T23:59:59Z` 在 `admin-api/src/main` 内出现即红）+ 坏样本 + 注入式红证；
3. 实例判据：财务/订单/商品三处的**日期归属**各一条会红的断言（用 `北京 00:30` 的探针 ⇒ 必须落**当日**）；
4. 加固后跑 `BusinessClockSourceGuardTest` 证明"未登记即红"。

**口径待裁定（交人工五类之一）**：产品意图是否统一为 +08 日界。**AI 可先固化的部分**：判据与守卫；
**必须问用户的一句**：「列表/汇总的日期参数按 **+08 日界**（推荐，与 `BusinessClock` 单源一致），还是保持 UTC？」——
在拿到裁定前，**安全默认动作** = 不改行为、先把判据与守卫落好（判据可先红后绿）。

---

## 3.8 线③ 其余读数定性（主会话核验）

| 读数 | 主会话定性 | 依据 |
|---|---|---|
| `A1/A2/A3` + `A4`（结算/发放/导出面不存在） | ✅ **正确的 SKIP**（未覆盖，非通过） | 8 个候选面全 404；`FinanceController` 仅 4 端点；全 `src/main` 内 `结算\|发放\|settle\|payout\|disburse` 命中 2 处且**皆为注释** ⇒ 给 open issue **#5653**「今天能算不能结」补上实得形态 |
| `B2`/`B3`（`100.0` vs `100`、`11.6113` vs `11.6113`） | 🔵 **假红（字符串形态）** | 数值相等，仅 `toFixed` 形态不同 ⇒ 应改数值比较 |
| `B8`（1 个批次余量不一致） | ⏳ **待取证**（可能真） | 已要求给出三数 + 批次 id + SQL 复算 |
| `C6`（#6185 缓存） | ✅ **正确的 SKIP** | `:8080` 构建点 `d1c09d02f` 不含 #6185（见 §1.2）⇒ 按任务书只登记当前行为，不判缺陷 |
| `Z1`（残留 13 行） | ⏳ **待收口** | 必须给逐表=0 终态读数，否则零残留判据不成立 |
| `Z2`（存量真实数据零改动） | ✅ 强证据 | 写过的 8 张表非探针行前后 sha256 逐表相等 |

---

## 4. 发现项处置（待回收后填：链内修 / 开单 / 登记 / 裁定）

（待填）

---

## 5. 本轮**未能**覆盖的面（照实登记，不粉饰）

（待回收后按各包 §5 汇总）
