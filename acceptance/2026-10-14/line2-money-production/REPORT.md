# 线② 验收报告 —— 钱 / 工资 / 库存时效 / 派工 / agent 服务面（2026-10-14 环境重建轮）

> 角色：本线是**验收子代理·线②**，只产「读数 + 判定 + 证据」，**不写「验收通过 / 交付完成」**（BRIEF §3.1）。
> 时间口径：Asia/Shanghai（+08）。原始 UTC 读数一律标注换算。
> 被测构建点：**`90192bcac82b1d276d2793986ca9c64f47e47d16`**（= 本机主检出 HEAD = 本轮被测面；`git rev-parse HEAD` 现取）
> 被测面：admin-api `http://127.0.0.1:8080`（PID 54364）· ai-agent `http://127.0.0.1:8001`（PID 30865，**DEBUG=true**）· admin-web `http://127.0.0.1:3001`（PID 54424）· 云 dev RDS `ai_customer_service` · 租户 **32**。
> 被测构建点自证：`out/finance-stock-time-sweep/buildpoint-run.json` → `before.sha == after.sha == 90192bcac`、`shifted=false`、窗口 `20:30:06 → 20:30:22 +08`；agent 侧 `out/agent-service-sweep/SUMMARY.json.buildPoints.aiAgent.shaFull == 90192bcac…`、`procStart=三 10月/14 20:34:43 2026`。

---

## 〇、一句话结论

**四段 sweep 共 248 条断言：191 pass / 45 fail / 12 skip；45 条 fail 里真缺陷只有 2 条（另 1 条待裁定），24 条是判据/夹具侧假红、18 条是本机环境注入问题（JWT 密钥对不匹配 + DEBUG=true + 无租户 B）。钱与工资的算法口径本身全绿且被独立算式复核，派工侧的真缺陷是「纱帘侧规则/取路漏一道工序」。**

---

## 一、四态汇总表

| sweep | pass | fail | skip | 合计 | 备注 |
|---|---|---|---|---|---|
| `finance-stock-time-sweep`（`run-all.mjs`） | 38 | 0 | 8 | 46 | 库存加权平均/台账不变式/账期 +08 口径全绿；skip 均为「面不存在」或空集无判别力 |
| `piecework-wage-sweep`（**无 run-all，按设计顺序驱动 p0→p9**） | 29 | 3 | 2 | 34 | 3 条 fail **全部**为判据侧缺陷（M8-01/M9-01/M10-02），已逐条独立复现反证 |
| `dispatch-routing-sweep`（**无 run-all，按 p0→p11→p10 驱动**） | 68 | 19 | 0 | 87 | 19 条 fail = 真缺陷 2(+1 待裁定) + 判据/夹具 16 |
| `agent-service-sweep`（`run-all.mjs`） | 56 | 23 | 2 | 81 | 23 条 fail **全部**是本机环境注入（密钥/DEBUG/无租户B），非产品 |
| **合计** | **191** | **45** | **12** | **248** | `fail 45 = 真缺陷 3 + 假红 24 + 环境夹具 18`；**skip 永不折算为 pass** |

机器可读见 `out/SUMMARY.json`。

### 1.1 本线自跑的最小复现（非既有 harness）

| 文件 | 用途 | 读数 |
|---|---|---|
| `out/piecework-wage-sweep/line2-repro-m8m9.json` | M8-01/M9-01 的**最小复现 + 原始响应体**（自建探针单，收尾自清，残留 0） | 幂等：新键首报 200 / 同键重放 200+`replayed:true` / 同键不同体仍 200+`replayed:true`；超报 30>20 ⇒ **422 `REPORT_QTY_EXCEEDS_PLANNED`**；报满后再报 1 ⇒ **422**；已报满+同键重放 ⇒ 两次都 422（复现 harness 形态） |

---

## 二、真缺陷清单

### L2-F1（P1·派工准确性 / 涉钱下游）纱帘侧「韩褶」漏插一道 `上车布-纱`

- **最小复现**：登录租户 32 → 建纱帘单（`craft=韩褶`）→ `POST /api/admin/processing-orders/generate` ⇒ 返回 200，工序序列**整条缺** `上车布-纱`。
- **会红判据**：harness 期望逐字全序 `精裁-纱 → 纱三边 → 韩褶-纱 → **上车布-纱** → 熨烫-纱 → 定型-纱 → 复烫-纱 → 车被-纱 → 外帘打卷 → 打包 → 外帘装袋 → 外帘发货`；实得 11 道、独缺 `上车布-纱`、其余 12 项逐字一致。任何「按库内真值逐字比较」的判据都会红。
- **证据**：
  - `out/dispatch-routing-sweep/p2-matrix.json` → `D-03`（`status=fail`，detail 原文含「期望 …上车布-纱… 实得 …」两串）；
  - 同文件 `S-01`（一樘布+纱，第 1 个部位即纱帘序列不符，同样是缺 `上车布-纱`）；
  - `out/dispatch-routing-sweep/p2-coverage.json` → `uncovered=['裁剪-纱','上车布-纱','质检','配料','腰靠垫','绑带-纱']`（41 道里 35 道被派工，`上车布-纱` 是 6 个未派工者之一）；
  - 现取 SQL：`production_route_rules where tenant_id=32 and trigger_value like '韩褶%'` ⇒ **只有 2 行**：`craft|韩褶|position=布帘|insert|上车布|after=韩褶`、`craft|韩褶|position=NULL|insert|韩褶|after=三边` ⇒ **纱帘侧没有对应的 `上车布` 行**；
  - 反证「不是库里缺变体」：`production_operations where name like '上车布%'` ⇒ `上车布-布(米,active)`、**`上车布-纱(米,active)`** 都在 ⇒ 是**取路/规则未命中**，不是数据缺失。
- **根因符号/文件**：`production_route_rules`（`trigger_kind=craft / trigger_value=韩褶 / position='布帘' / action=insert / operation=上车布`）在纱帘部位无对照行；消费侧 `backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java::buildRoute`（按 position 命中规则并 collapse）。
- **五层归因**：现象=纱帘+韩褶少 1 道 → 服务层=规则按部位命中后无「另一部位变体补位」→ 接口层=`generate` 200 静默 → 数据层=规则表纱帘侧缺行 → 期望层=harness 用库内真值逐字全序（非写死字符串）。

### L2-F2（P2·口径待裁定）选项工序在目标部位无变体时「静默成功、少一道工序」

- **最小复现**：纱帘单 + 特殊选项 `拼1次`（或 `加花边/加铅块/接高/加logo条/加立边/扣环/防翘扣`）⇒ `generate` 返回 **200**，产出序列为**基线纱帘序列**（不含该选项工序）。
- **会红判据**：harness 期望「显式失败且**指名**缺的工序」（9 条判据同形）；实得 200 + 静默。
- **证据**：`out/dispatch-routing-sweep/p2-matrix.json` → `S-03`、`F-拼1次@纱帘`、`F-加花边@纱帘`、`F-加铅块@纱帘`、`F-接高@纱帘`、`F-加logo条@纱帘`、`F-加立边@纱帘`、`F-扣环@纱帘`、`F-防翘扣@纱帘`（共 9 条，detail 原文均为「预期显式失败，实际生成成功（工序=精裁-纱,纱三边,…）」）；`out/dispatch-routing-sweep/p3-writes.json` 另有同族 2 条。
- **数据侧事实**：库内只有 `拼1次-布`、`花边-布`，**无 `-纱` 变体** ⇒ 选项对纱帘确实无对应工序。
- **归因强度声明**：证据只到「静默成功」这一层。**「应当显式失败」是 harness 的判据主张**，产品文档未明写 ⇒ 登记为**待裁定**，不武断判产品缺陷（缺的证据 = 产品侧对「选项无变体」的口径声明）。

### L2-F3（P0·评测可用性，非产品）本机 ai-agent 的 `JWT_PUBLIC_KEY` 与 harness 私钥**不成对** ⇒ `/api/chat/**` 全部 401

- **最小复现**：用 `~/migao-keys/jwt-private.pem`（RS256）签 token → `POST http://127.0.0.1:8001/api/chat/sessions` ⇒ `401 TOKEN_INVALID`。
- **会红判据**：正对照 `B1-1`「合法 RS256 token 建会话 ⇒ 200 且 data.id 非空」实得 401。
- **判别证据（指纹级）**：
  - `openssl rsa -pubout < ~/migao-keys/jwt-private.pem | shasum -a 256` ⇒ `86978d00525224acf0454262ff91f3e10fea13f0bf83bfa68a4cdfee6e779612`
  - `backend/ai-agent-service/.env::JWT_PUBLIC_KEY`（`\n` 还原后）`openssl rsa -pubin -pubout | shasum -a 256` ⇒ `6292bfb239f214d01556ccf96d84fabb7f8f7e99761e1051fee4cbe7025c1c67`
  - ⇒ **两个公钥不是同一把**。本机**没有**任何与 `.env` 公钥配对的私钥（已遍历 `~/migao-keys/`）。
- **证据文件**：`out/agent-service-sweep/probe-tenant-isolation.json`（`B1-1/B1-2` 401、`B3-1..4` `TOKEN_INVALID`、`B4/B5/B6` 全红）、`out/agent-service-sweep/probe-auth-debugfalse.json`（`A2-positive` 401）。
- **归因**：环境注入问题（密钥轮换后本机未同步私钥），**不是产品缺陷**；但它把「ai-agent 的 JWT 面（约 19 条判据）」整块打成不可引用。
- **重启条件**：把与该公钥配对的私钥放到 `JWT_PRIVATE_KEY` 指向的路径（或把 `.env` 的公钥换成 `~/migao-keys` 那对），重跑 `agent-service-sweep`。

---

## 三、判据侧问题清单（假红 / 夹具漂移 / 期望过期）

### 3.1 期望值过期伪影

| 条目 | 判别证据（谁判的 / 判据文件 / 为什么是判据侧） |
|---|---|
| **W-08**（dispatch「停用工序」按钮 100% 失效） | harness 结论基于旧代码：现 main 的 `frontend/admin-web/src/components/production-config/features.ts:643` 的 `disableOpByName` 发的是 **`{status:'disabled'}`**（非 `'inactive'`），后端 `ProductionOperationCommandService.java:52 STATUSES=Set.of("active","disabled")` ⇒ 该按钮在 `90192bcac` 上**可用**。harness 引用的 `types/index.ts:1867-1869` 注释本身即 #6103 的**修复留痕**（「工序域没有 inactive，写它必被拒」）。⇒ 判据的期望取自修复前的世界。 |
| **W-01b**（自建工序应做数量 ≠ 12.3 米） | 期望「unit=米 ⇒ 应做=用料米数」与产品口径冲突：`ProcessingOrderService.java:2512` 明写「一律取不到 ⇒ 端点在缺键时**兜底 1** 并在 qty_source 标 fallback」，实测 `qty=1.00米 qty_source=fallback` 与代码注释**逐字一致** ⇒ 是期望过期，非产品缺陷。 |
| **C6 skip**（声称运行构建点「不含 #6185」） | **判据命名空间错位**：#6185 的落地对象是 **ai-agent-service** 的 `backend/ai-agent-service/app/core/logistics_trace_cache.py`（commit `37204f4e9`，`git merge-base --is-ancestor 37204f4e9 HEAD` = **YES**）；而 harness 在 **admin-api 的 Java 源码**里 grep「物流缓存」⇒ 必然无命中。⇒ skip 的前提是错的，本轮应把该条判据指向 Python 侧。 |

### 3.2 假红（判据缺陷 / 夹具漂移 / harness 崩溃）

| 条目 | 判别证据 |
|---|---|
| **M9-01**（超报未拒） | 判据把**返工**计入应做上限；产品判据 `ProductionService.java::applyReport` 首行 `boolean advances = "normal".equals(workType) && qualifiedQty.signum() > 0;`，**只有 normal 才走 `assertWithinPlannedQty`**。夹具形态：`opRated1` 应做 20、已报 8(normal) + 3(rework) ⇒ 剩余 12，本次 5 ≤ 12 ⇒ **200 正确**。独立反证：`line2-repro-m8m9.json::M9-b1`（应做 20 报 30）⇒ **422 `REPORT_QTY_EXCEEDS_PLANNED`**，护栏在线。 |
| **M8-01**（幂等重放 422） | 夹具把幂等重放打在**已报满**的实例上（`opRated2` 先被 `r2` 报满 20/20），首报即被超上限拦 ⇒ `report()` 第 ④ 步 `clientRequestIdService.discard()` 释放占位（`ProductionService.java:1146` 注释明写）⇒ 键不存在，`replayed` 字段无从出现。独立复现 `M8-c1/c2`（已报满 + 同键两次）⇒ 两次都 422，与 harness 读数同形；而 `M8-a1/a2`（余量充足）⇒ 首报 200、重放 **200 + `replayed:true`**，`p3-f8-redproof.json::idempotency` 亦记录 `firstHttp=200/secondHttp=200/replayed=true/before=6→mid=7→after=7`。⇒ 幂等机制正常，判据选错了夹具状态。 |
| **M10-02**（改价反向快照） | `p1-p2-matrix.mjs:53 predTotalEqualsOwnMath(readTotal, expTotal) => cents(readTotal) === expTotal`（BigInt 分），而调用点 `:358` 传的是 **`fmt(expAfterNew.total)`（已格式化字符串）** ⇒ 类型不可比、恒假。同文件其余 20 处调用均传原始 BigInt。 |
| **P9-01（改价漂移探针）** | `p9-price-drift.json` 内**同名两条**记录：`P9-01 pass`（「读面 NULL→NULL；实例价 NULL→NULL」）与 `P9-01 fail`（`TypeError: Cannot read properties of null (reading 'id')`）⇒ 后者是探针崩溃（取基线行取到 null），非产品读数；`P9-02 pass` 还证明还原后存活行只剩 `通用` 一行。 |
| **E-01**（piecework「F8 未修」判定） | **夹具漂移**：注入对象就是既有 `position='布帘'` 行（`p6-price-source.json`：`injected.id = bba467f9…` **等于** `baselinePrices.布帘RowId = bba467f9…`）⇒ 改的正是塌缩价源本身，观测到的只是「改布帘价 ⇒ 取价变」。产品文档 `ProcessingOrderService.java:2777` 明写收敛规则「用户裁定**取布帘价**」、`ProductionOperationQueryService.java:234 COLLAPSE_PRICE_SOURCE_POSITION="布帘"` ⇒ 该观测是**规格内行为**，F8 的判别性在此形态下不成立。F8 真正在位的证据是同一轮 `F8X-02`（一次普通保存**不新建**任何价目行）、`F8X-03`（保存后新实例仍 `NULL` 未定价）、`F8X-04`（未定价不进 per_operation 金额）三条 pass。 |
| **DR-01 / DR-03 / DR-04 / DR-05**（p10「配置零漂移」4 红） | **基线过期**：p10 的基线 = `out/surface.json`（p0 在 20:31:13 采集），而比对发生在 **20:34:29**，其间并行线①已新建工序/路线、`p3-writes`（本线）已改过矩阵价与规则并还原。判别证据 = 漂移对象**全部带非本线前缀**：`DR-01`「新增工序 **写面横切工序写面**267110」、`DR-04`「多出 **写面横切工序写面**267110@布帘 ｜ 多出 打包@布料 ｜ 缺失 打包@布帘」、`DR-03`「多出 `option|加花边|insert|花边|三边|120|null` ｜ 缺失 `…|120|布帘`」——`写面横切工序写面` 是 p3-writes 的探针命名域（非本线 line2 前缀，是并行线的写法）。而本线自己的清理读数（§五）`probe_ops=0 / probe_routes=0` ⇒ 本线未留残留。harness 用「开工态」当基线比对「收敛态」⇒ 零漂移断言失去判别力。 |
| **agent-service `Z1-1`（零残留 fail）** | `p7-residue.mjs` 的删除依赖调用方传 `PROBE_TAGS`，本轮未传（harness run-all 第 41 行注释「缺省不删」）⇒ 报 4 卡 + 4 候选残留；本线已按前缀手工清至 **0**（§五）。属 harness 参数化缺口，非产品。 |
| **piecework `p5-ui-and-residue` 崩溃** | `p5-ui-and-residue.mjs:25` **硬编码** `loginApi('13870217889')`（旧租户 20 的管理员）⇒ `401 AUTH_FAILED「该手机号未注册」`，进程退出码 1，`p5-ui.json` 只留下崩溃前的 `U-01 pass`（计件工资页 HTTP 200）。⇒ 判据把租户信息写死，本租户管理员是 `13800138000`。 |

---

## 四、未覆盖清单（skip 及原因与重启条件）

| 条目 | 原因 | 重启条件 |
|---|---|---|
| finance `A1/A2/A3`（结算单/发放/导出） | 面不存在：8 个候选端点**全 404**（`A1-settlement-surface.json` 逐条留证） | 产品新增结算/发放/导出面后 |
| finance `A0`（计件读面正对照） | 采集时本租户 `production_work_logs` 为空 | **已具备**（本轮 piecework 已造出报工）⇒ 先跑 piecework 再跑 finance |
| finance `A4` | 结构性归因（源码级存在性登记） | — |
| finance `B9b`（残料写面 recover/scrap） | `fabric_remnants` 0 行，无可回收对象 | 造出余料行后 |
| finance `C6` | 前提错位（见 §3.1） | 判据改指 ai-agent 的 `logistics_trace_cache` 后 |
| finance `Z4` + 6 张空集快照表 | 空集无判别力（非 pass） | 独占租户窗口重跑 |
| piecework `M16-01/02`、`F8E-00`、`F8Z-00` | F8 复现前置「有通用行、无活跃布帘行」的逻辑工序 = 0 道 | 构造该矩阵态后 |
| agent `F3-2/F3-3`、`RP-B*` | 无租户 B 对照身份（本机只有 tenant 32 + 并行线新建的 34） | 存在第二个真实租户 + JWT 密钥对修好 |
| dispatch `P5 UI-00` | Playwright 登录页 `#phone` 45s 超时（页面 HTTP 200 可达，`p5-ui.json` 无任何 DOM 断言落地） | admin-web dev 编译稳定/重启后重跑 |
| agent-service 全 JWT 面（约 19 条） | 密钥对不匹配（L2-F3） | 见 L2-F3 重启条件 |
| **真实 LLM 相关** | 本机 `backend/ai-agent-service/.env` **无 `PRIMARY_API_KEY`** ⇒ 按 BRIEF §1/§3.7 与 issue #4262 **不跑**、**不派 workflow** | 用户显式要求时集中跑一次 |

> 注：`skill`/工具面（`B7-1..3` pass）、admin-api 知识卡/候选/模板/工作台（`C/D/E` 共 32 条 pass）**未受** JWT 问题影响 —— 它们走 admin-api 的真实登录 token，故 ai-agent 的服务面仍有可引用读数（`B7-3` 工具清单：`product_search, product_detail, logistics_track, customer_logistics_track, knowledge_search, order_query, customer_order_query, customer_address_query, order_manage, order_create, processing_order_generate, processing_order_query, processing_order_update…`）。

---

## 五、残留清理读数（清理前后**现取**）

| 域（租户 32） | 清理前 | 清理后 |
|---|---|---|
| `knowledge_cards`（`title like '线②验收%'`） | 4 | **0** |
| `knowledge_candidates`（`suggested_title like '线②验收%'`） | 4 | **0** |
| `agent_sessions`（`customer_id like 'probe_line%'`） | 2 | **0** |
| `agent_messages`（随上） | 2 | **0** |
| `production_work_logs`（本线最小复现探针） | 7（复现脚本自清） | **0**（脚本内 `residueAfter.orders=0/pos=0/logs=0/products=0/cats=0`） |

- 清理动作 = 按前缀/外键序删（`knowledge_cards`/`knowledge_candidates`/`agent_messages`→`agent_sessions`）。
- **非本线所写、按纪律未清**（属并行线①/③的探针，登记不计入本线残留）：`orders(customer_name like '%验收%' and deleted=0)=74`、`products=12`、`categories=12`、`production_work_logs=16`、`processing_orders=83`、`production_operation_positions(status='active')=115`、`production_operations` 无本线残留（`probe_ops=0`）、`production_route_templates` 无本线残留（`probe_routes=0`）。
- `tenants` 现取 = **32**（米高测试环境）与 **34**（米高测试环境-隔离对照，`created_at 2026-10-14 20:35:03 +08`，**并行线所建，非本线**）。
- **未清空租户 32**（BRIEF §3.9）。

---

## 六、钱的口径：期望值由**本线独立算式**给出（不读被测读面）

- **独立算式**（十进制/HALF_UP 到分、零浮点）：`金额 = Σ 逐笔 HALF_UP(qualified_qty × unit_price 快照 × coalesce(factor,1))`，且 `work_type != 'normal'` 与 `price_state='unpriced'` 的笔**不计**。口径出处（非被测读面）：`ProductionService.java::applyReport`（`advances` 定义、快照单价注释）+ `assertWithinPlannedQty`。
- **独立复算读数**（本线用 psql 取原始 `production_work_logs` 后自算）：16 行 → 计入 12 行、排除 4 行（3 条 rework + 1 条 unpriced）⇒ **独立算式合计 = 51.30 元**；其中 12 行逐笔金额（3.20 / 8.00 / 0.00 / 2.00 / 7.50 / 5.00 / 0.80 / 12.30 / 5.00 / 2.50 / 4.00 / 1.00）。
- **交叉核对**：harness 记录的 A 单读面 `total=11.2`（`per_operation`: 精裁-布 3.20 + 布三边 8.00 + 熨烫-布 0.00）与本线对该单重算**逐分一致**；`unpriced.qty=5`（定型-布）与本线排除项一致。⇒ 钱面判据的期望**不是**抄被测读面。
- 未覆盖的钱面：结算/发放/导出（面不存在，A1~A3 skip）⇒ 计件链的终点仍只有 `summary` 报表。

---

## 七、纪律自证

1. **未改产品代码**：本线新增文件只有 `acceptance/2026-10-14/line2-money-production/out/**`（含最小复现脚本 `line2-repro-m8m9.mjs`），`backend/**`、`frontend/**` 零改动（`git status --porcelain` 中无这两个目录）。
2. **未跑重活**：未跑 `verify-all.sh`/`batch-gate`/全量 pytest；`machine-heavy-lock.sh acquire` 一次（name=`line2-finance-sweep`），财务段结束即释放。
3. **未调真实 LLM / 未派 workflow**。
4. **写面只碰探针**：所有写操作经 harness 的 `guardedWrite`（必须带 `-- probe-ok`）或探针前缀对象；本线最小复现脚本收尾自删至 0。
5. **判定均引证据**（文件名 + 字段 + 原文片段）；**无引用处已写「证据不足」**（L2-F2 明示待裁定）。
6. **skip 未折算为 pass**；四态并列，环境/夹具侧单列一栏。

---

## 八、产物索引

```
acceptance/2026-10-14/line2-money-production/
├── REPORT.md                     ← 本文件
└── out/
    ├── SUMMARY.json              ← 机器可读四态 + findings
    ├── finance-stock-time-sweep/ {summary-raw.json, SUMMARY.json, run.log, residue.json,
    │                              buildpoint-run.json, stock-snapshot-*.json, stdout.log, RUN-META.txt}
    ├── piecework-wage-sweep/     {p1p2-matrix.json, p1p2-raw.json, p6-price-source.json,
    │                              p3-f8-redproof.json, p7-f8-e2e.json, p8-f8-controlled.json,
    │                              p9-f8-wage-e2e.json, *.stdout.log, run.log, RUN-META.txt,
    │                              line2-repro-m8m9.{mjs,json}}
    ├── dispatch-routing-sweep/   {p2-matrix.json, p2-coverage.json, p3-writes.json,
    │                              p4-redproof.json, p4b-judge-redproof.json, p5-ui.json,
    │                              p6-settings.json, p8-routes.json, p9-price-drift.json,
    │                              p10-drift.json, surface.json, *.stdout.log, run.log, RUN-META.txt}
    └── agent-service-sweep/      {probe-*.json, SUMMARY.json, run.log, run-all.stdout.log, RUN-META.txt}
```
