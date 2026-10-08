# 下一轮深入功能测试 · 总报告（2026-10-03 下午批次）

> 状态：**三线测试全部收口 + 修复阶段进行中**（§3 各线读数已入册；§3.4 为修复阶段记录）
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

   **1.2.1 事实订正之订正（2026-10-03 13:54 +08，线① 提出、主会话复核后采纳）**：
   主会话先前称「`git cat-file -e HEAD:…/logistics_trace_cache.py` ⇒ 不存在」——**该断言已失效，特此订正**。
   复核读数：
   - 主检出分支已**前进一格**：`0a28014ff → bf5e19e18`（「fix(logistics): #6185 消解 CI 首轮 4 条红 —— 职责归位 + 弱断言/快照刷新」），且 `0a28014ff` 是其后代链上的祖先；
   - `git cat-file -e HEAD:…/logistics_trace_cache.py` ⇒ **存在**（HEAD = `bf5e19e18…`）；
   - `git merge-base --is-ancestor 04fdee0aa HEAD` ⇒ **是祖先**；
   - **但 `origin/main` 依然不含该文件** ⇒ **#6185 未合入 main 的核心结论不变**。
   ⇒ 我方当时的"HEAD 无此文件"只对**当时的 HEAD**成立（分支随后被推进）；**把瞬时状态写成结论是方法错误**，留档自省。
   **影响面：零** —— 全部运行服务都不在主检出上（`:8080` = `migao-wt/main-live @ 7e9f66ce5`；`:8001` = `migao-wt/line1-agent @ d877f19ef`），主检出分支推进不影响任何读数。
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

## 3. 各线读数（回收中）

> 口径：**包的读数**与**主会话独立复核**分开列；冲突时以更强证据一方为准。判据四态分列：pass / fail（产品）/ 假红（判据缺陷）/ skip（未覆盖，**永不记 pass**）。

### 3.1 线③ `finance-stock-time-sweep` ✅ **已收口交付**

**产物**：`REPORT.md`（394 行）+ `harness/run-all.mjs` + `out/*.json`（含 `SUMMARY.json`、`buildpoint-shift.json`）

| 项 | 读数 |
|---|---|
| **读数汇总** | **pass 31 / fail 9 / skip 7 / 假红改判 3（B2/B3/B8，修正后计入 pass）/ total 47** |
| 权威轮 | run3，测量窗 `13:49:06→13:49:27 +08`，构建点 **`7e9f66ce5`**（pid 60585，启动 13:44:16），`B0` 双采样 before==after **零漂移** |
| 另一构建点 | recon 只读枚举 = `d1c09d02f`（pid 99086，13:40:23） |
| **事实订正（包自订）** | 切换点 `13:44:16` **早于**其首轮开始 `13:44:26` 共 10 秒 ⇒ **首轮并未横跨切换点**；但首轮 pid 读数 `unknown`（重启瞬态）⇒ 仍整体判 superseded、未引用其结论 |
| **零残留** | 9 表**全 0** |
| **存量零改动** | 9 张写过的表既有行**零字段变化、零消失**（sha256 前后相等） |

**该线 9 条 fail 全部同一根因（= §3.7 的 D1）**。包已按主会话指令把红证重做：**绿→红→还原→绿**（`C4/C5` pass，sha256 `5ebcfe6e…` 往返一致），并补 **`C8` 跨口径判别点** ——
`C8a` 北京 `10-01 08:00`（=UTC 下界）**被收录**（正对照：证明窗口确实在过滤）／`C8b` 北京 `10-01 07:59:59` **被排除**／`C8c` 该笔**落进 `09-30` 窗口** ⇒ 唯一自洽解释 = **边界是 UTC 而非 +08**。

**B 族（库存下游）14 条全绿**（全部以独立 SQL 重算对标）：加权平均 `12.5`/`11.6113`/未记单价保持原值；台账条数=变动次数（3/1/3==3）；链条首尾相接 + `delta == after−before`；调账与盘点**不改**均价；批次余量 = `quantity + Σ(delta)`；残料 `0==0`；省料看板 `5==5`；`POST /api/admin/batch-stock` = **404（正确行为**，唯一 `@PostMapping` 是 `/stocktake`）。

**包自曝并已修掉的 3 条假红 + 4 条 harness 缺陷（它已类级固化）**：
- `B2/B3`：`numeric`→JSON number 的**字符串形态**误判（`100` vs `100.0`）；
- `B8`：**包自己算式用错**（`quantity − Σ|delta|` vs 正确 `quantity + Σ(delta)` 有符号）——**非产品问题**（三数：批次 20/21/22、`quantity` 60.5/39.5/10.0、`Σdelta` −5.5/−9.5/+20.0、期望余量 55/30/30，读面全一致）；
- harness：①`nowCST()` 双换算（**与本报告 §3.5 同一缺陷**）⇒ 改 `Intl` + 新增 **T1/T2 时钟自检**（对 SQL `now() at time zone 'Asia/Shanghai'` 差 0s），**判据未受影响**（C 族期望来自写死字面量与独立 SQL）；②`psql()` 别名 `t` 与列名撞车 ⇒ 改 `__q`；③`Z2` 曾**假绿**（通用谓词引用缺列 ⇒ 快照空集 ⇒ 空集恒真）⇒ 改逐表谓词 + 空集守卫；④清理锚点 `ref_no` 不可靠（盘点/调账行为 `NULL`/`batch_no`）⇒ 改主锚 `product_id`（`Z1` 那 13 行的真因，已清干净）。

**未覆盖清单（13 条，见其 §5）**：结算单/发放/导出（面不存在）· 残料**写面**（`fabric_remnants` 0 行无对象）· #6185 缓存（不在构建内）· **退货/退回入库端到端**（需售后完结 + `allow_return_restock`，仅间接验证口径）· 报损（无独立端点）· 批次**效期**（表无该列）· **库龄/呆滞**（无端点/列）· Dashboard/Briefing **逐项**数字独立重算（仅验日期归属）· 历史简报漂移（`daily_briefings` 0 行）· `numeric(10,2)` 的 `0.005` 舍入方向专项。

### 3.2 线① `agent-service-sweep` ✅ **已收口交付**

**产物**：`REPORT.md`（§0~§8）+ `harness/`（`lib.mjs`、`mint_jwt.py`、`p0..p7`、`run-all.mjs`）+ `out/probe-*.json`（9 个判据组）+ 原始启动日志 + `out/SUMMARY.json` + `out/superseded/`（`nowCST` 修复前旧批次）

| 项 | 读数 |
|---|---|
| **读数汇总** | **117 条判据：pass 115 / fail 0（产品面）/ skip 1** + **1 条故意的失效控制项（必须红）** |
| 分组 | A 鉴权 18（`DEBUG=false`）+ 19（`DEBUG=true` 对照）｜B 租户链路与并发 20｜C 知识卡片生命周期 12｜D 候选/蒸馏/入卡 14｜E 知识模板 6｜F 客服工作台 13+1skip｜R 红证 11｜Z 零残留 2+1 控制项 |
| **两个构建点** | `:8001` = **`d877f19ef`**（干净 `origin/main` 检出 `migao-wt/line1-agent`，`dirty=""`，13:44:52 起，`DEBUG=false` 常驻）≠ 线④ 的"仓内工作树未提交代码" ⇒ **构成独立复测**；`:8080` = **`7e9f66ce5`**（13:44:16 换构建、含 #6190）—— A/B 首跑在旧构建窗口，已按窗口标注、未混用 |
| **零残留** | 清理前 64 行 ⇒ **清理后逐表全 0（total=0）**，且零残留读数**自带红证**（注入 1 行 ⇒ 1，删 ⇒ 0）；行级注入（`tenant_id`）逐条还原且 sha256 回注入前 |
| **假红 4 条**（harness 缺陷，已修+重跑转绿，**未计入发现清单**） | ①`B2/B6-3` 前缀归一化（主会话核出）② Node 侧手工拼 RS256 签名（自签自验失败）③ 工作台列表误用 keyword 过滤 ④ 读面取 `data.records` 而实为 `data.items` |

**最有价值读数 —— `DEBUG` 旁路两侧夹住**（补实线④ 只能"代码级声明"的缺口）：
同一请求 `GET /api/chat/sessions` + `X-Debug-Role: customer` + **无 token**：
**`DEBUG=false` ⇒ 401**（用**启动期环境变量覆盖**起服务，未改仓内 `.env`）／**`DEBUG=true` ⇒ 200**（放行为 `tenant_id=1`）。
红线判据 + 判别力自证（`A5-discriminator`）双绿 ⇒ **线④ §2.2 的缺口实测闭合**。

**该线发现 2 条（详见 §4.1）**：`F-D1`（转人工对不存在 `aiSessionId` 返 **500**）、`F-D2`（`assignSession` 不校验员工所属租户）；
另有 `F-D3`（P3 知悉）承线④ F-1。

**不可自清副作用（如实登记）**：`E2-1` 应用模板 `curtain` ⇒ 租户 20 新建 **27 张 `knowledge_cards`**（`13:46:45.108791+08 ~ 13:46:45.975633+08`），属**业务正常行为**、非探针前缀 ⇒ **不删**，回退定位口径见其 §6.2。

**未覆盖（照实，未当 pass）**：SSE/`chat/send`/ASR（必走真实 LLM，**主动评测派发 0**，被动 LLM 调用 1 次）· `vision/recognize` 内容质量 · `memories`/`upload`/`briefing`/`production`(7)/`registration`/`products`/`payments` 未跑 · **`@Async SessionDistillListener` 触发存在性 = SKIP**（线④ 点名缺口；会话走完 `waiting→active→ended` 但 20s 窗口内 `knowledge_candidates` **0 行**，候选产出依赖 LLM 蒸馏 ⇒ **不硬凑**；`F6-1` 因空集恒真已降级为弱结论）· 真实 C 端用户 token 端到端（用与 `JWT_PUBLIC_KEY` 配对的私钥自铸 RS256，覆盖契约与租户作用域，**非**小程序/微信登录链）· 工作台 `/messages`、`/monitor`、`/api/customer/agent-sessions/**` · 知识模板"建/改/停用"（被测构建**无端点/无 DB 表**，只有 list+apply）· 双 AI 交叉验证未做。

**对自己说法的订正（主会话复核后采纳）**：① 主会话"`HEAD` 无 `logistics_trace_cache.py`"的断言已失效（分支前进到 `bf5e19e18`）—— 详见 §1.2.1；② 「`shipments-sweep` 同 `nowCST` bug 且已入 main」线① **未复核即未转述**（符合铁律 11；该结论由主会话在 §3.5 自行给出）。

### 3.3 线② `batch-writeface-sweep` ✅ **已收口交付**

| 项 | 读数 |
|---|---|
| **读数汇总** | **pass 54 / fail 8 / skip 0 / total 62**；8 条 fail **三态分解** = 🔴 真缺陷 6 条断言 / 5 个缺陷 + ⚪ 故意失效控制项 1（`F4`，必须红）+ 🟡 判据缺陷（假红）1（`F2`：红半段成立、回绿半段未证，根因 = `probeSku` 同毫秒碰撞） |
| 构建点 | `main-live @ 7e9f66ce5`（pid 60585，13:44:16）；**全部有效读数窗口 13:45:00→13:58 +08 整段落在切换后**（A/B/D/E/F 五段**全部重跑**，非只登记）⇒ **切换对本包判据影响 = 无**（#6181/#6190 属发货面，切换前后无断言翻转） |
| **零残留** | 13 张表逐表计数全 0，13:58 复核仍 0 |
| 假红自查（其 §7 共 7 条） | 首轮 4 组 fail **全部**是假红/期望错（xlsx 解析器按 local header 读 POI streamed zip、batch 上架期望错、孤儿 schema 前提不成立、两处列名写错）+ 3 处 harness 缺陷（探针命名域、page clamp 定位、`TZ` 非 +08 的时区读数） |
| 落实主会话订正 | ① 导出改用 **central directory 解析** ⇒ 导出 **402 行 == total 402**、表头逐字 7 列 ✅（**已判**）；② `draft` 改判负例 + 走状态机 `draft→on_sale→off-shelf→on-shelf` 正对照链；③ `C1.3` 列名以 `information_schema` 实测为准 ⇒ 4 组活跃命中全 0；④ 二次调用按"不得 5xx"通过、注释落差记口径登记；⑤ **`A5.2` 是本轮唯一导出失配，且是新真缺陷**（首轮 `402==402` 因未过 500 上限而被**掩盖**） |

**发现 5 条**（详见 §4.1 的 D7~D11）；**未覆盖 8 条**（其 §5，均为"未判定"而非通过）：不落盘判定不可达（存储 = **OSS**，无列举权限）· OSS 侧对象残留无法列举 · `stocktake` 同 `runId` 并发幂等 · 导入并发 · 大批量 batch(>500 ids) · `DELETE /files/{fileId}` 跨租户/越权 · 导出字节级编码/样式 · UI 级复核。
**另**：`B3.2` 真孤儿扫描已改判为「**结构性保证、无判别力**」—— 注入真孤儿被 `product_skus_product_id_fkey` 当场拒绝、8 条 FK 现查 ⇒ 孤儿=0 是**约束的结果**而非被测行为（这是很好的"判据无判别力"自曝）。

---

### 3.4 修复阶段（2026-10-03 下午）与一条**门禁豁免口子**的发现

**修复包（§30 派单）**：

| 工单 | 分支 / PR | 读数 | 状态 |
|---|---|---|---|
| **#6198** 导出静默截断 + **#6199** 负库存 | `fix/6198-export-truncate-and-negative-stock` / **PR #6204**（rebase 后 `9f3709dbe`；原提交 `47ec5b619`） | 红 `Tests run: 11, Failures: 6`（`expected: 989 but was: 500`）→ 绿 `23 / 0`；CI **22 pass / 6 skipping / 0 fail**（rebase 后那轮；首次跑 27 pass）；`contract-check` EXIT=0 | ✅ **已合入 main**（`62995ea8f`，PR #6204）；**#6198 / #6199 双双自动 CLOSED** |
| **#6200** UTC 日界 → +08 | `fix/6200-date-window-cst` / **PR #6206** | 红 `13 run / 9 failed`（窗口 `[2026-10-03T23:59:59Z, 2026-10-03T00:00Z]` vs 期望 `[2026-10-02T16:00Z, 2026-10-03T16:00Z]`）→ 绿 `16 / 0`；相邻回归 278 passed | ✅ **已合入 main**（`9d9e00ee2`，PR #6206）+ **主分支复算 16 passed / 0 failed** |

**主会话对 PR #6204 的独立核验**（不采信包的转述）：改动面 = 6 文件 / 718 行，**未碰** `cases/**` 与生成物；
实现方式正确（导出改走**不带 `IPage` 的 `selectList`** ⇒ 穿透全局 500 上限，且条件与列表同源 ⇒「导出行数 == 列表 total」恒成立；
**未**采用"放开 `setMaxLimit`"这条降护栏路径）；`StockQuantity` 把**绝对值 vs 增量**的语义分野分开（增量负数是出库/盘亏的正常业务，不能拒）。
另**拦下一次绕过**：该 PR 原本 `auto-merge=ARMED`（CI 一绿即自动合入、绕过批次 `batch-gate`）⇒ 已 `--disable-auto` 制动（实测 `ARMED → DISABLED`）。

**🔴 发现（门禁豁免口子）：`case_ids` 只校存在性，不校指涉准确性。**
- 实现：`.github/growth_gate.py::case_trace_check` 只做 `declared ⊆ case_index` 的存在性判定；
  命中即 `level: pass`，**不校验"这条测试是否真对应那条用例"**。
- 实证：PR #6204 的两个新增测试声明 `case_ids: PR-059` / `PR-048`，而
  **`PR-059` = 「商品+SKU 批量导入：幂等键/逐行报告/库存 1 位小数」**（**导入**面）、
  **`PR-048` = 「库存类输入超过 1 位小数 ⇒ 显式拒绝」**（**精度**面）——
  与被测行为（**导出不被截断** / **负库存被拒**）**语义不符**，但门禁绿。
- ⇒ 该 gate 证明的是「声明了存在的 ID」，**不能**证明「用例与行为对得上」。
  这与 `gate-exemption-ledger` 的口径一致：**凡"能让检查变绿而不必真做对"的点**都要登记。
- **处置**：本批次先合修复（不阻塞）；**行为用例补录**（导出全量 / 非负准入 两条新用例，ID 由
  `scripts/next_case_id.py` 现取）列为**下一批第一件事**，并顺带评估是否给 gate 加"指涉准确性"的机械判据
  （注意：语义比对难以机械判定，可行的是**要求新行为必须用新 ID** + 对"复用存量 ID"给出理由，见 `migao-dev-flow` §14）。

### 3.4.1 集成记录与本次事故（如实登记，不粉饰）

**① 事故：PR #6206 在 `batch-gate` 之前被自动合并 —— 责任在集成侧（主会话）。**
- 逐字时间轴（`gh api …/issues/6206/timeline`）：`ready_for_review 07:47:47Z (zhaokai-mgzn)`
  → `auto_squash_enabled 07:48:04Z (github-actions[bot])` → `merged 07:52:30Z` —— 窗口仅 **4 分 26 秒**。
- **转 ready 的动作是集成侧做的**（`gh api user` = `zhaokai-mgzn`）：为了让 `batch-gate.sh` 的
  `--require-ready` 能取到完整 CI（draft 的 leg 不全跑）。
- **我的失误**：对 PR #6204 关闭 auto-merge 时我**回读确认**了（`ARMED → none`），但对 #6206
  **只发命令、未回读**就去处理别的事 ⇒ CI 转绿后仓库的 arm 腿把它 arm 回去并立即合并，**事后不可撤销**。
- **教训（已固化为本会话纪律）**：*制动是状态变更，必须当场回读确认*。
- 后续 `#6204` 的 auto-merge **三次被 arm**（`automerge.yml` / `flaky-ledger-reconcile.yml` / `flaky-triage.yml`
  三处都有 arm 腿）⇒ 每次都**关闭 + 当场回读**，最终保持 `none`。

**② 机制读数：两次全量入口被**正确**拒绝（这不是失败，是护栏生效）**
- `verify-all.sh gate` 在 linked worktree（`/Users/guangzhen.zk/migao-dev/6198`）内 **exit 5 拒绝**：
  「D 口径 = **一批只跑一次**全量，那一次属于**批次集成**；在这里直跑会把它**提前烧掉**」（issue #6084）。
  它给出的替代路径逐字为：① 包内只跑**定点判据**（不拿锁、可并行）② 一批的那一次 ⇒ `./scripts/batch-gate.sh`
  ③ **单包的一整套 ⇒ 交给 CI（每 PR 并行，仍是权威）**。
- ⇒ 本批的形态是 **①+③**：#6204 的权威验证 = **CI（含 `admin-api unit tests` 全量腿）27 pass / 0 fail**；
  修复包各自的定点红→绿读数见 §3.4 表。那**一次**全量留给"汇总报告补录"PR 的 `batch-gate`。

**③ 顺带发现已成单：#6212（P2·基建）**
`batch-gate.sh` 的就绪前置（要求非 draft）与 `automerge.yml` 的自动合并策略**结构性冲突**；
单内含逐字时间轴、两次 arm 腿的机器读数、三条既有护栏为何挡不住的归因，
并顺带登记 `batch-gate.sh`/`test_batch_gate.py` 里 **5 处**把出处标成 `issue #6028` 的**引用漂移**（铁律 11(a)）。

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
| `C1.3` 两项 `dangling` | fail | 🔵 **假红（列名写错，包已自修）** | 首轮写死 `production_operation_positions.operation_id` —— 该列**不存在**（实测列：`id/tenant_id/logical_name/position/unit_price/applicable/status/deleted/created_at/updated_at`，按 `logical_name` 关联）；包已在 harness 注释中自认「首轮两处假红都是我写错列名」，并改用实测列名 |
| `C1.3`（修订后复查：已删工序是否仍留活跃价目行） | 复查 | ✅ **主会话独立复算 = 0** | `select count(*) from production_operation_positions p where p.deleted=0 and p.logical_name in (select name from production_operations where deleted=1)` ⇒ **0**；且 `线②验收%` 的工序行与价目行**全部清零** ⇒ 真实行为**正确**（`detach-and-delete` 会把价目行 `deleted 0→1` 且 `unit_price` 置 null，见 `out/C1-detach.json`） |
| `C1.4`（二次 detach-and-delete ⇒ 404） | fail | 🟡 **口径登记（非缺陷）** | 资源已不存在 ⇒ 404 是标准 REST 语义；实现注释若声称"幂等 200"则**注释需订正** |
| `B3.0`（正对照：探针商品 SKU 子行 = 0） | fail | ⚠️ **前置不成立 ⇒ SKU 闭包未判定** | 包自己红了正对照 ⇒ 该闭包判据此时无判别力，须补夹具重跑或记 skip |
| `B3.1`（`batch/delete` 后 `product_colors` 孤儿 1 行） | fail | 🔵 **假红（schema 前提不成立）** | 独立核实：`product_skus` / `product_colors` **都没有 `deleted` 列**（软删只在 `products` / `stock_ledger_entries`）⇒ 包的 `c.deleted=0` 查询前提为假；子表**按设计随父行逻辑不可见**。正确判据应是「父行软删后子行**是否仍可被读面/写面独立触达**」，若不可达 ⇒ 应判 PASS |
| `A4.3`（`.csv` 扩展名 ⇒ 200） | fail | 🔵 **期望过严（产品不声明支持 CSV）** | 独立核实：`products/page.tsx:607` `accept=".xlsx,.xls"`；同文件 `:335` 注释「导入把 **xlsx** 写回商品 + SKU」；后端 `WorkbookFactory.create`（POI）只认真 Excel；全 `main` 无 CSV 支持声明 ⇒ 拆两半：伪 `.xlsx` ⇒ 422 ✅ **PASS**（有效判据）；`.csv` ⇒ **未定义行为，降为口径登记** |

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

**强化证据（同一仓库内的"正确范式"与"前端已知")：**

| 位置 | 写法 | 判定 |
|---|---|---|
| `DashboardController.java:68` | `businessClock.startOfDay(businessClock.today().withDayOfMonth(1))` | ✅ **正确范式已在用** |
| `DailyBriefingService.java:462` | 同上 | ✅ |
| `FinanceService.java:431,435` | `OffsetDateTime.parse(date + "T00:00:00Z")` / `"T23:59:59Z"` | 🔴 违规 |
| `OrderService.java:208,211` | 同上 | 🔴 违规 |
| `ProductService.java:194,199` | `.atStartOfDay().atOffset(ZoneOffset.UTC)` | 🔴 违规 |
| `frontend/.../products/page.tsx:26` | 注释逐字：「`00:00~08:00（CST）` 这 8 小时里 **UTC 日 = 前一天** ⇒ 导出文件名 `products_YYYY-MM-DD.xlsx`」+ `formatLocalDate()` 规避 | ✅ **前端已显式防此坑** |

⇒ 结论定性：**同一仓库既有单源、又有正确用法、前端还专门规避过**，而后端三处日期窗口仍按 UTC 日界 ⇒ 属**已知缺陷形态的漏改**，**不是**"设计选择/口径待定"。
（这同时把"是否算缺陷"的争议消掉；§4 只需保留一句"最终口径以 +08 为准"的待确认。）

### 3.7.2 🔴 强化到"**同系统内自相矛盾**"（用户可见，运行期复现）

不是抽象的边界偏移 —— 同一租户、同一构建（`7e9f66ce5`）下，**两个端点对"今天"给出不同答案**：

| 端点 | 实现 | 对探针单 `c3ordmurz286n`（`ordAt = 2026-10-03 02:00+08`）的收录 |
|---|---|---|
| `GET /api/admin/dashboard/stats`、`/order-trend` | `businessClock.startOfToday()` / `startOfDay(...)`（**+08 日界，正确**） | **计入今天**：`dashboardTodayOrders=351`、`orderTrendToday={date:"2026-10-03", orders:351}` |
| `GET /api/admin/orders?startDate=2026-10-03&endDate=2026-10-03` | `OrderService:208,211` 的 `T00:00:00Z`（**UTC 日界**） | **不计入**：`listStatus=200, listTotal=9, listHit=false` |

证据：`acceptance/2026-10-03/finance-stock-time-sweep/out/C9-cross-endpoint.json`（含 `at.utc` 与全部读数）。
源码对应：`DashboardController.java:65,68`（正确） ⇄ `OrderService.java:208,211`（UTC）——**两处口径不一致**。

**⇒ 这条把 D1 从"边界偏移（可能被辩称口径选择）"升级为"同产品内两处口径不一致，商家看板与订单列表对不上"**，
在 §4.2 的待确认项里也据此把推荐选项 A（统一 +08）的权重进一步抬高。

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
| `A1/A2/A3` + `A4`（结算/发放/导出面不存在） | ✅ **正确的 SKIP**（未覆盖，非通过） | **主会话独立全量核实（比包的候选清单更硬）**：① `FinanceController` 全部端点仅 **4 个**（`GET /summary`、`GET|POST /transactions`、`GET /reconciliation`）；② 全仓 `@*Mapping` 中含 `settle\|payout\|disburse\|wage\|export` 的**只命中 1 处** = `ProductController.java:221 "/export"`（商品导出）⇒ **财务域零导出端点**；③ **前端亦无入口**：`(dashboard)/finance` 与 `production/piecework` 下 `结算\|发放\|settlement\|payout` **零命中**，计件页只调 `api/admin/production/piecework/summary` 一个端点 ⇒ **前后端双侧空缺**，给 open issue **#5653**「今天能算不能结：与财务域零耦合、无导出、无发放台账」补上逐字实得形态 |
| `B2`/`B3`（`100.0` vs `100`、`11.6113` vs `11.6113`） | 🔵 **假红（字符串形态）** | 数值相等，仅 `toFixed` 形态不同 ⇒ 应改数值比较 |
| `B8`（1 个批次余量不一致） | ⏳ **待取证**（可能真） | 已要求给出三数 + 批次 id + SQL 复算 |
| `C6`（#6185 缓存） | ✅ **正确的 SKIP** | `:8080` 构建点 `d1c09d02f` 不含 #6185（见 §1.2）⇒ 按任务书只登记当前行为，不判缺陷 |
| `Z1`（残留 13 行） | ⏳ **待收口** | 必须给逐表=0 终态读数，否则零残留判据不成立 |
| `Z2`（存量真实数据零改动） | ✅ 强证据 | 写过的 8 张表非探针行前后 sha256 逐表相等 |

---

## 4. 发现项处置

> 口径（铁律 12(b)）：**能靠 durable 证据裁的当场自己裁**；只把业务口径/涉钱/权限/不可逆/需外部输入五类交人工，
> 且交人工时必须给出「卡在哪一条 + 具体问题（带选项与代价）+ 不裁时的安全默认动作」。

### 4.1 已裁定（AI 自裁，依据可复算）

| # | 发现 | 级别 | 裁定 | 固化口径（实例判据 + 类级守卫） |
|---|---|---|---|---|
| **D1** | **日期查询窗口按 UTC 日界**（`FinanceService:430-436`、`OrderService:208,211`、`ProductService:194,199`）⇒ 北京 00:00–08:00 数据归错天/错月；财务汇总/对账/交易列表 + 订单列表 + 商品列表三面受影响 | **P1 · 涉钱** | **判为缺陷（不是口径选择）** —— 依据：同仓已有单源 `BusinessClock`、看板/简报已用正确范式、**前端已显式规避该坑**（`products/page.tsx:26` 注释）⇒ 属已知形态的**漏改** | ① 三处改走 `businessClock.startOfDay(...)`；② 扩 `BusinessClockSourceGuardTest` 禁则（`T00:00:00Z`/`T23:59:59Z`/`ZoneOffset.UTC` 日界）+ 坏样本 + 注入红证；③ 三面各一条**会红**的归属判据（`北京 00:30` 探针须落当日） |
| **D2** | **计件「结算 / 发放 / 导出」前后端双侧不存在**（`FinanceController` 仅 4 端点；全仓唯一导出端点是商品导出；财务/计件页面零入口） | **P1 · 能力缺口** | **登记 + 并入 open issue #5653**（「今天能算不能结」），本轮以 skip 记录、**不按通过计** | 已在 #5653 追踪；本报告 §3.8 提供逐字实得形态与复算命令作证据 |
| **D3** | **`#6185`（物流轨迹缓存，P1·涉钱）** —— 本轮测试期间**未合入**，实现只在在飞 PR **#6189**（`feat/logistics-track-cache`） | P1 · 涉钱 | ✅ **登记已失效（已自证闭合）**：`37204f4e9`（PR #6189）现已是 `origin/main` 的**祖先** ⇒ **#6185 已合并**（2026-10-03 下午实测） | 无需固化；由 #6189 自身评审/CI 承接 |
| **D4** | **验收工装 `nowCST()` 双重时区换算**（历史台账 `cst` 字段 +8h；含**已入 main** 的 `shipments-sweep`） | 工具链缺陷（非产品） | **登记 + 本轮内修在飞包**；已入 main 的那份**收口时统一修** | 修法见 §3.5；建议加一条类级守卫：`harness/**/lib.mjs` 禁 `getTimezoneOffset()` 叠加本地 getter 的写法（或统一用 `Intl`） |
| **D5** | **转人工端点对不存在的 `aiSessionId` 返 500**（`agent_sessions_ai_session_id_fkey` 外键异常直冒，且**约束名写进日志**）—— 线① `F-D1` | P2 · 授权面（不涉钱） | **判为缺陷**（应 4xx + 友好文案；日志不得外泄 schema 名） ⇒ issue **#6210**（已开单，待派包） | 实例判据：`POST /api/admin/agent-sessions` 传不存在 `aiSessionId` ⇒ 断言 **4xx 且非 5xx**、且响应/日志不含约束名；类级：控制器层"外键异常 ⇒ 4xx"的通用处理（或 `@RestControllerAdvice` 归口） |
| **D6** | **`assignSession` 对员工无显式租户校验** —— 线① `F-D2` | **P3 · 纵深防御（经主会话核实：不是越权）** | **降级登记，不按缺陷派单** | 核实过程：`AgentSessionService:309-313` **对 session 有显式租户校验**；对员工只有 `agentEmployeeMapper.selectById`。但 `agent_employees` **有 `tenant_id` 列**且**不在** `MybatisPlusConfig.IGNORE_TENANT_TABLES`（该名单仅 `tenants`/`tenant_applications`/`platform_admins`/`notification_templates`/`notification_rules`）⇒ **租户插件在 SQL 层自动追加 `tenant_id = 当前租户`** ⇒ 跨租户员工天然查不到。建议（非必须）：补一句显式校验以保持与会话侧对称 + 让 404 的归因不依赖插件 |
| **D7** | **导出静默截断在 500 行**：列表 `total=989` 而导出仅 500 行、**无任何提示** —— 线② `A5.2` | **P1 · 数据完整性**（按导出件对账会漏） | **判为缺陷**（AI 自裁，根因已独立确认） | 根因：`MybatisPlusConfig:119 paginationInterceptor.setMaxLimit(500L)`（**全局分页上限**）× `ProductService.exportProducts` 的 `query.setSize(10000L)`（其注释逐字「不分页，**全量导出**」）⇒ 被拦到 500 且静默。判据：造 >500 行数据 ⇒ 导出行数必须 == 列表 `total`（现会红）；类级：导出口径与会话内查询同源（禁 `setMaxLimit` 静默截断导出），或导出走专用"无上限"查询并在 UI 标注上限 |
| **D8** | **商品改品路径可写负库存**：`PUT /api/admin/products/{id}` 传 `stock=-5` ⇒ **200 且落库**（`products.stock=-5.0`、`product_skus.stock=-5.0`、台账 `delta=-12, before=7, after=-5`）—— 线② `E2.1/E2.2` | **P1 · 数据完整性 / 间接涉钱**（可售库存为负 ⇒ 超卖） | **判为缺陷**（AI 自裁） | **同族护栏对照（独立核实）**：导入路径过 `StockQuantity.requireOneDecimal`、`stocktake` 盘亏 ⇒ **422 `INSUFFICIENT_STOCK`**（源码注释：「四条都发生在**任何写入之前**」）、`StockBatchController:70-71` 亦然 ⇒ **改品路径漏了同一份判据**。判据：`stock<0` ⇒ 4xx 且零写入（三条路径**同源**断言）；类级：库存写入统一收口 |
| **D9** | **上传 5MB 上限可被客户端 `Content-Type` 绕过**（`.png` + `application/pdf` + **19.9MB** ⇒ 200，落 OSS `images/` **公共可读**）—— 线② `D2.5` | P2 · 存储配额/内容安全 | **判为缺陷** ⇒ issue **#6207**（已开单，待派包） | 判据：按**实际字节流**判类型与大小（魔数 + 服务端计数），不信客户端头；超限 ⇒ 4xx 且**不落 OSS** |
| **D10** | **`directory` 参数无校验 ⇒ 500**（`directory=../../l2evil` ⇒ `500 INTERNAL_ERROR`；本地实现有 `safeResolve`→422，运行的 `OssService#generateObjectKey` **完全无校验**）—— 线② `D3.2` | P2 · 输入校验 + **实现间护栏不一致** | **判为缺陷** ⇒ issue **#6208**（已开单，待派包） | 判据：路径穿越 ⇒ 4xx 且不落盘；类级：**同一语义的护栏必须同源**（本地存储有 `safeResolve`、OSS 存储没有 ⇒ 加"守卫一致性"元判据） |
| **D11** | **重复提交无服务端幂等**：同 `X-Client-Request-Id` 并发 5 次 ⇒ **6 条商品**，`client_request_keys` **0 行** ⇒ 该链路**根本不读幂等键** —— 线② `E1.1` | P2 · 幂等 | **判为缺陷**（与上轮发货面 `K3b-1` 同族） ⇒ issue **#6209**（已开单，待派包） | 判据：同幂等键并发 N 次 ⇒ **恰 1 条** + `client_request_keys` 有留痕；类级：写面接入 `clientRequestIdService`（沿用既有点位，勿新造） |

### 4.2 待人工确认（唯一一条，其余均已自裁）

| 问题 | 选项 | 代价 | 不裁时的安全默认动作 |
|---|---|---|---|
| **D1 的最终产品口径**：列表/汇总的日期参数是否统一按 **+08 日界**？ | A. 统一 +08（推荐，与 `BusinessClock` 单源一致） B. 保持 UTC 并在文档/界面标注 | A：一次行为变更（跨月归属会变，需 changelog）；B：商家看到的"本月"与自然月不符，对账口径长期别扭 | **先把判据与守卫落好（判据可先红后绿），暂不改行为** |

---

## 5. 本轮**未能**覆盖的面（照实登记，不粉饰）

**权威口径**：三线 `REPORT.md` 各自的 §5 是**完整清单**（合计 **31 条**：线① 12 / 线② 8 / 线③ 13，含"面不存在"与"无对象可测"）。本处只列**必须记住的高层缺口**：

| 类别 | 缺口 | 原因（不可回避） |
|---|---|---|
| **面不存在** | 计件「结算 / 发放 / 导出」；知识模板「建/改/停用」（只有 list+apply）；批次效期列、库龄/呆滞端点 | 前后端双侧无载体 ⇒ 只能 skip（**不得记 pass**）；已并入 open issue **#5653** |
| **必走真实 LLM** | `:8001` 的 SSE（4 处）、`/api/chat/send`、ASR `/chat/transcribe` | 用户 #4262 裁定不自动刷额度 ⇒ **主动评测派发 0**（线① 被动 LLM 调用 1 次） |
| **无对象可测** | 残料**写面**（`fabric_remnants` 0 行）· 历史简报漂移（`daily_briefings` 0 行）· `@Async SessionDistillListener` 触发（20s 窗口 `knowledge_candidates` 0 行，候选依赖 LLM 蒸馏）· 退货/退回入库端到端（需售后完结 + `allow_return_restock`） | 夹具不可安全构造 ⇒ **不硬凑**，如实记未判定 |
| **环境/权限所限** | OSS 侧对象残留无法列举（不落盘判定不可达）· 真实 C 端用户 token 端到端（云 dev 无 `users↔orders` 关联，线① 用自铸 RS256 覆盖契约与租户作用域，**非**小程序/微信登录链） | 需要环境改造或外部权限 |
| **范围外未跑** | `vision/recognize` 内容质量 · `memories`/`upload`/`briefing`/`production`(7)/`registration`/`products`/`payments` · 工作台 `/messages`/`/monitor`/`/api/customer/agent-sessions/**` · 导入并发 · 大批量 batch(>500 ids) · `DELETE /files/{fileId}` 跨租户 · 导出字节级编码 · UI 级复核 · `numeric(10,2)` 的 `0.005` 舍入专项 | 体量/排期所限，**明确未判定** |

**方法学缺口（全批次共性）**：三线均**未做双 AI 交叉验证**（线④ 亦自曝未做）⇒ 本批次结论强度止于「主验收 AI 自证 + 红证 + 正对照 + **主会话独立抽样复核**」，**不得**被引用为"已双裁通过"。

---

## 6. 交接与完成性核验（2026-10-03 14:00 +08）

**三条线全部收口**（核验命令见每行）：

| 线 | REPORT | 读数 | 零残留 | harness |
|---|---|---|---|---|
| ① `agent-service-sweep` | ✅ 370 行 | **pass 115 / fail 0 / skip 1** + 1 控制项 | ✅ total=0（**主会话独立复算**：`probe_line1_` 四表全 0） | ✅ `run-all.mjs` |
| ② `batch-writeface-sweep` | ✅ 266 行 | **pass 54 / fail 8 / skip 0**（真缺陷 5 + 控制项 1 + 假红 1） | ✅ 13 表全 0（13:58 复核） | ✅ `run-all.mjs` |
| ③ `finance-stock-time-sweep` | ✅ 394 行 | **pass 31 / fail 9 / skip 7**（假红 3 已改判） | ✅ 9 表全 0 + 存量零改动 | ✅ `run-all.mjs` |

**逐条读数**：74 份 JSON（线① 11 / 线② 43 / 线③ 20）。
**处置**：**D1~D11**（P1×3：UTC 日界 / 结算-发放-导出不存在 / 导出截断+负库存；P2×5；P3×1；工具链×1 + #6185 登记×1），**唯一待人工确认项** = D1 的最终口径（+08 vs UTC，附安全默认动作）。
**构建点**：`:8080 = 7e9f66ce5`（13:44:16 起；**切换登记已入三份报告**，各线均按窗口归属、跨窗口判据已重跑）；`:8001 = d877f19ef`（干净 `origin/main` 检出，`dirty=""`）。

**下一批建议（未做，需另行派单）**：
1. **D7/D8 修复包**（导出截断 + 负库存）—— 两条 P1 同属"库存/导出写读面护栏不同源"，建议**同包**（同文件族：`MybatisPlusConfig` 影响面 + `ProductService`/`ProductController`）；
2. **D1 修复包**（三处日期窗口 + 守卫扩禁则）—— 需先取用户口径裁定；
3. **D9~D11**（上传校验 / directory 穿越 / 幂等接入）可合并为一个"写面输入校验与幂等"包；
4. **D5**（转人工 500 + 约束名外泄）单独小包。
