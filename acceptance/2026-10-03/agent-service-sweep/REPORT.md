# 线① AI Agent 服务域独立验证报告（2026-10-03）

- **日期/时区**：2026-10-03（本机 Asia/Shanghai，UTC+8）。观测窗口 **13:38–13:52 +08**（原始 JSON 内 `at` 为 +08、`atUtc` 为 UTC 原文）。
- **产物目录**：`acceptance/2026-10-03/agent-service-sweep/`（`harness/*.mjs` + `out/*.json` + `out/*.log` + 本报告）。
- **是否改 MIGAO 业务代码**：**否**。只新增本包 `harness/` 脚本与 `out/` 读数；未触碰 `backend/**`、`frontend/**`、`.github/cases/**`、`CHANGELOG.md`。
- **是否派发真实 LLM 评测**：**否**（#4262）。**本包主动 LLM 评测派发 = 0；被动 LLM 调用 = 1 次**（`D6-2` 蒸馏面契约探针，这是被测端点的既有行为，非评测派发）：蒸馏面只做**契约级**读数（200 + 结构），不判内容质量；`/chat/send`、SSE、ASR 全部**未跑**（记未覆盖）。
- **双 AI 交叉验证**：**本包未做**（线④也未做）。结论仅代表本包单侧取证；`out/*.json` 留给主会话做独立抽样复核。**本报告不声称"双裁通过"**。

---

## §0 核心判据（先说读数）

| 记号 | 读数 |
|---|---|
| **判据总数** | **117** 条（A 18 + A-DEBUGtrue 对照 19 + B 20 + C 12 + D 14 + E 6 + F 14 + R 11 + Z 3） |
| **pass** | **115** |
| **fail** | **0**（产品面）；**1 条为设计如此的故意失效控制项**（`Z2-1`，必须红 ⇒ 证明断言链在真跑） |
| **skip** | **1**（`F6-2` @Async 监听器触发存在性 —— 20s 窗口内未观测到候选行） |
| **假红（harness 缺陷，已修并重跑转绿）** | **4 条**（见 §7，**不得计入发现清单**） |
| **发现清单** | **2 条真发现**（F-D1 P2 值级确定性 / F-D2 P2 代码级）+ 1 条既有边界知悉（F-D3 P3） |
| **未覆盖面** | 7 项（见 §5） |
| **零残留** | **total = 0**（逐表读数见 §6） |

**一句话结论**：本线覆盖的确定性面（鉴权契约 / 租户链路与并发串号 / 知识卡片与候选全生命周期 / 客服工作台状态机 / 四类注入式红证）**未发现 P0/P1 缺陷**；`DEBUG` 旁路两侧夹住是**本线最有价值的读数**（把线④只能"代码级声明"的缺口补成实测）。两条 P2 已按证据强度分级登记。

---

## §1 被测对象与构建点自证

### 1.1 两个被测对象（口径必须分开，禁止互相顶替）

| 对象 | 构建点 | 自证方式 | 进程启动（+08） |
|---|---|---|---|
| **ai-agent-service :8001**（**本线自起**） | **`d877f19efabb6993c6d29652e8c949e1fcb173c8`**（`origin/main`，`fix(scripts): #6178 活锚自检空比对不得报绿…`） | worktree = `/Users/guangzhen.zk/migao-wt/line1-agent`（`git worktree add --detach … origin/main`）；`git status --porcelain` = **空**（`dirty=""`） | `13:44:52`（`DEBUG=false` 常驻批） |
| **admin-api :8080**（已跑，**13:44:16 起被换成新构建**） | **`7e9f66ce57915ce17f6e949e3dc23d53bae291eb`**（`fix(6181): 商家发货三步原子化 … (#6190)`，提交时间 `2026-10-03T05:42:36Z` = **13:42:36 +08**） | pid 60585，cwd=`migao-wt/main-live/backend/admin-api`，`ps -o lstart=` | `13:44:16` |

- **⚠️ 构建点切换已发生**：任务上下文给的是 `main-live @ d1c09d02f`，但实测 **13:44:16 起换成 `7e9f66ce5`**（含 #6190）。⇒ **本报告 C/D/E/F/R 组（13:44:16 之后）全部归属 `7e9f66ce5`，与 `d1c09d02f` 无关**。切换是**中途**发生的（A/B 组首跑在 13:43:02–13:44:03，仍在 `d1c09d02f` 窗口内；详情见 §7 批次说明）。
- **服务中途重启**：ai-agent 重启 3 次（`DEBUG=false` 首跑 → `DEBUG=true` 判别力批 → `DEBUG=false` 常驻批），每次重启后**未复用旧读数**；常驻批（`13:44:52` 起）承载 C/D/E/F/R/Z 全部读数。**读数作废口径**：`DEBUG=true` 批的读数**只用于 A 组对照**，不用于任何其它判据。
- **ai-agent 启动日志**：`out/ai-agent-service.debugfalse.log`（首跑）、`out/ai-agent-service.debugtrue.log`（判别力批）、`out/ai-agent-service.running.log`（常驻批）。
- **本包批次日标记**：`out/BATCH-MARKER.json`（`batchStart` + `buildPoint`）。

### 1.2 与线④（`tenant-concurrency-sweep`）的构建点差异（主会话点名要求）

| 项 | 线④ | **本线** |
|---|---|---|
| `:8001` 代码来源 | **仓内工作树未提交代码**（主检出，当时在 `feat/logistics-track-cache`） | **干净 `origin/main` 检出**（`migao-wt/line1-agent @ d877f19ef`，`dirty=""`） |
| 意义 | `X-Tenant-Id` 不被消费 / 内部面租户归属等读数是在"工作树态"上取的 | **同批结论在 `origin/main` 上独立复现** ⇒ 本线天然构成对线④的**独立复测**（A3-x / B7-x 与线④ G 组同向） |

### 1.3 事实订正（任务上下文与主会话两次订正的核对结果）

| 声称 | 实测 | 判定 |
|---|---|---|
| 主检出 `logistics_trace_cache.py` 的 `git cat-file -e HEAD:…` **不存在** | **存在**（`git cat-file -e HEAD:backend/ai-agent-service/app/core/logistics_trace_cache.py` → 成功；`git log --all` 显示由 `04fdee0aa`（#6185）引入，且 `04fdee0aa` 是 **HEAD 的祖先**） | ❌ **主会话第一条订正的这一半不成立**（其第二条订正已自行改口，与本实测一致） |
| 主检出 HEAD = `0a28014ff` 且在飞分支 `feat/logistics-track-cache` | 一致（`git worktree list` 首行 + `git status -sb`） | ✅ |
| `origin/main` 无 `logistics_trace_cache.py`、且不 import 它 | 一致（`git ls-tree origin/main:…/app/core/` 无该文件；`origin/main:…/tools/logistics_track.py` 中 `logistics_trace_cache` 命中数 = **0**） | ✅ **origin/main 自洽**（不存在"缺失 import"缺陷 ⇒ **F-D-noissue**） |
| `main-live(d1c09d02f)..origin/main` 只差 3 提交、业务代码 diff = 0 | ✅ 命令复算成立（`d877f19ef / 14e5bcbd9 / 7ea465067`；`git diff --stat d1c09d02f origin/main -- backend/` 输出为空） | ✅（但**该结论对本线只有半天有效**：13:44:16 起 8080 已是 `7e9f66ce5`） |
| `04fdee0aa` 不在 `origin/main` 提交史 | 一致（`git merge-base --is-ancestor 04fdee0aa origin/main` → 非祖先） | ✅ **#6185 未合入 main** ⇒ 其缓存行为**不在本线覆盖范围**（本线从 `origin/main` 起服务，`logistics_track.py` 路径无缓存实现） |

---

## §2 断言矩阵与读数表（pass / fail / 假红 / skip 分列）

### 2.1 判据组 A —— 服务可起性 + 鉴权契约（**两侧夹住**）

| id | 判据 | DEBUG=false | DEBUG=true |
|---|---|---|---|
| A1-1 | `/health` 200 且 `status=="healthy"` | PASS | PASS |
| A1-2 | `/ready` 200 且 `status=="ready"` | PASS | PASS |
| A1-3 | 未注册路径 ⇒ 404（不得 500） | PASS | PASS |
| A1-4 | 错误方法 ⇒ 405 | PASS | PASS |
| A2-notoken-{sessions,latest,quick-actions} | 无 token（带 `X-Debug-Role: customer`） | **PASS=401** ×3 | **PASS=200** ×3 |
| A2-badtoken | 畸形 Bearer ⇒ 401 `TOKEN_INVALID` | PASS | PASS |
| A2-expired | 过期 JWT ⇒ 401 `TOKEN_EXPIRED` | PASS | PASS |
| A2-foreignkey | 异钥签名 ⇒ 401 `TOKEN_INVALID` | PASS | PASS |
| A2-aud | `aud` 不含 `migao` ⇒ 401 | PASS | PASS |
| A2-positive | 合法 RS256 token ⇒ 200 | PASS | PASS |
| A5-discriminator | **判别力自证**（DEBUG=true 侧 3 条全放行） | — | PASS |

**合计 A 组：18 + 19 = 37 PASS / 0 FAIL / 0 SKIP**（证据：`out/probe-auth-debugfalse.json`、`out/probe-auth-debugtrue.json`）。

> **为什么这是本线最有价值的读数**：同一个请求（`GET /api/chat/sessions` + `X-Debug-Role: customer` + 无 token）
> 在 `DEBUG=false` 下 **401**、`DEBUG=true` 下 **200**（放行为 `tenant_id=1` 的 C 端身份）。
> 线④ §2.2 只能把"生产不可达"记为**代码级声明**；本线用**启动期环境变量覆盖**（`DEBUG=false .venv/bin/python -m uvicorn …`，
> 未改仓内 `.env`）把它变成**实测对照**。

### 2.2 判据组 A3/A4 —— B 端内部面（Service Token）

| id | 判据 | 读数 |
|---|---|---|
| A3-1 | 缺 `X-Service-Token` ⇒ 401 `AUTH_REQUIRED` | PASS |
| A3-2 | 错 Service Token ⇒ 401（不得 500） | PASS |
| A3-3 | 正对照：正确 Token ⇒ 200 且工具集非空（**51** 个只读工具） | PASS |
| A3-4 | 写工具经内部面 ⇒ 403 `WRITE_TOOL_FORBIDDEN`（`order_create`） | PASS |
| A3-5 | 未知工具 ⇒ 404 `TOOL_NOT_FOUND` | PASS |
| A4-1 | `SERVICE_TOKEN` 不在 `/health` `/ready` `/openapi.json` 与 401 响应体中回显（0 处命中） | PASS |

### 2.3 判据组 B —— 租户链路与身份作用域（**20 PASS / 0 FAIL / 0 SKIP**）

| id | 判据 | 读数 |
|---|---|---|
| B1-1/B1-2 | 正对照：租户 A / 租户 B 各建会话成功 | PASS ×2 |
| B2-20/B2-21 | 会话落库 `tenant_id` == JWT claim（逐条） | PASS ×2 |
| B3-1 | **跨租户读历史（B 读 A 会话）⇒ 403 `PERMISSION_DENIED`**，响应体不含 A 内容 | PASS |
| B3-2/B3-3 | 跨租户关闭 / 删除 ⇒ 403 | PASS ×2 |
| B3-4 | 跨租户被拒后 **A 会话无副作用**（`deleted=0`、status 未被改） | PASS |
| B4-1 | 同租户**不同用户**读他人会话 ⇒ 403（身份作用域含用户维度） | PASS |
| B4-2 | 正对照：属主自读 ⇒ 200 | PASS |
| B5-1 | JWT **缺 `tenantId` claim** ⇒ 401 `TOKEN_INVALID`（不得默认落某租户） | PASS |
| B5-2 | 无 token + **伪造 `X-Tenant-Id`** ⇒ 401（头不得成为租户来源） | PASS |
| B5-3 | 合法 A token + `X-Tenant-Id: B` ⇒ 仍只返回 A 的会话（跨租户条目 = 0） | PASS |
| B6-1 | 并发建会话 **18 条**（并发度 6×3 身份、**交错**伪造 `X-Tenant-Id`）全部 200 | PASS |
| B6-2 | 并发：响应 `tenant_id` 与请求身份**一一对应**（不一致 = 0） | PASS |
| B6-3 | 并发：**DB 留痕** `tenant_id/customer_id` 与请求**一一对应**（核对 18 行） | PASS |
| B6-4 | 并发：**交叉回读**（用对侧租户 token）**全部 403**（无一条串号可读） | PASS |
| B7-1/B7-2 | C 端 JWT 调 B 端内部面 / 工具执行面 ⇒ 401（内部面不认 JWT） | PASS ×2 |
| B7-3 | 登记：内部面只读工具集读数（**51** 个） | PASS（登记项） |

### 2.4 判据组 C —— 知识卡片全生命周期（**12 PASS / 0 FAIL**）

| id | 判据 | 读数 |
|---|---|---|
| C1-1 | 建卡 ⇒ 200 且有 id | PASS |
| C1-2 | **建卡后 DB 逐字段（11 字段）**与请求体一致（`status=draft`、`version=1`、`deleted=0`） | PASS |
| C1-3 | 建卡租户归属 == 登录租户（不得落他租户） | PASS |
| C2-1/C2-2 | 更新 ⇒ 200；DB `title/answer/category` 生效、**`version` 1→2**、租户不变 | PASS ×2 |
| C3-1 | 发布 ⇒ DB `status='published'`、`reviewed_at` 打点 | PASS |
| C3-2 | 读面一致：列表按关键词可读且 status/title 与 DB 一致 | PASS |
| C3-3 | 读面一致：`/search` 可读 | PASS |
| C4-1 | 归档 ⇒ DB `status='archived'`（失效） | PASS |
| C4-2 | 归档后读面：不得再冒充生效（不返回 / 返回但带 `archived`） | PASS |
| C5-1/C5-2 | 更新 / 删除**不存在**的卡 ⇒ 4xx（不得 200、不得 500） | PASS ×2 |

### 2.5 判据组 D —— 未命中候选 → 蒸馏 → 入卡（**14 PASS / 0 FAIL**）

| id | 判据 | 读数 |
|---|---|---|
| D1-1 | 正对照：3 条 `pending` 探针候选落库 | PASS |
| D2-1 | `pending-count` ⇒ 200 且计数 ≥ 3 | PASS |
| D2-2 | 候选列表含本包 3 条且 `tenantId` 一致 | PASS |
| D3-1 | `adopt` ⇒ 200 且返回新卡 | PASS |
| D3-2 | **状态流转** `pending → adopted` + `reviewed_at` 打点 | PASS |
| D3-3 | 入卡产物 DB 逐字段（tenant/title/answer）来自候选、租户一致 | PASS |
| D3-4 | 登记：入卡产物 `source_type=manual / source_ref=线①验收 / status=published` | 登记 |
| D4-1 | `reject` ⇒ `pending → rejected` + `status_note` | PASS |
| D4-2 | `reject` **不得产生知识卡片** | PASS |
| D5-1 | `adopt-edited` ⇒ 入卡用**编辑后**的值（非候选原值） | PASS |
| D5-2 | `adopt-edited` 后候选**不得仍 pending** | PASS |
| D6-1 | 蒸馏面无 Service Token ⇒ 401 | PASS |
| D6-2 | 蒸馏面契约：200 + `success` + `data.candidates` 为数组（**不得 500**） | PASS（**LLM 调用 1 次**：内容为空的降级返回） |
| D6-3 | 登记：本次蒸馏返回 **0 条**候选（LLM 侧降级/空；内容质量不在本线判定范围） | 登记 |

### 2.6 判据组 E —— 知识模板（**6 PASS / 0 FAIL**）

| id | 判据 | 读数 |
|---|---|---|
| E1-1 | 模板清单 ⇒ 200 且 `data` 为数组 | PASS |
| E1-2 | 登记：模板 **1** 个（`curtain`） | 登记 |
| E1-3 | 登记：**库中无 `knowledge_templates` 表** ⇒ 模板为**代码内建**（"建/改/停用"无 DB 载体） | 登记 |
| E2-1 | 应用模板 `curtain` ⇒ 200 且返回结果对象 | PASS |
| E2-2 | 登记：应用后**新建 27 张卡片**（见 §6.2 副作用登记） | 登记 |
| E3-1 | 应用不存在的模板 ⇒ 4xx（不得 500） | PASS |

> **未覆盖**：「模板建/改/停用」在本次被测构建里**无对应端点/DB 表**（只有 list + apply）⇒ 如实登记，不用 apply 冒充。

### 2.7 判据组 F —— 客服工作台（**13 PASS / 0 FAIL / 1 SKIP**）

| id | 判据 | 读数 |
|---|---|---|
| F0-1 | 夹具：先建**真实 AI 会话**（FK 要求，见 §4 F-D1） | PASS |
| F1-1 | 转人工建会话 ⇒ 200、初始 `status='waiting'` | PASS |
| F2-1 | DB 逐字段（`tenant_id/customer_id/ai_session_id/status`）与请求一致 | PASS |
| F3-1 | 工作台列表（本租户）**可见**该转人工会话 | PASS |
| F3-2 | 他租户（21）列表**看不到**租户 20 的会话 | PASS |
| F3-3 | **跨租户按 id 读详情 ⇒ 4xx**，不返回他租户内容 | PASS |
| F4-1 | 接管 ⇒ `waiting → active` 且 `employee_id` 落库 | PASS |
| F4-2 | 接管后详情面**可查**（闭环"能不能用"） | PASS |
| F4-3 | 状态机：已 `active` 再 assign ⇒ 拒 | PASS |
| F4-4 | **跨租户分配员工**（租户 B 员工 → 租户 A 会话）⇒ 拒，DB `employee_id` 仍空 | PASS（**但归因见 §4 F-D2**：拒绝来自"员工不存在"而非租户校验） |
| F5-1 | 结束会话 ⇒ `status='ended'` + `ended_at` 打点 | PASS |
| F5-2 | 状态机：已 `ended` 再 end ⇒ 拒 | PASS |
| F6-1 | **@Async 蒸馏监听器**：结束后产出的候选 `tenant_id` **无跨租户行** | PASS（**空集恒真，见 §7**） |
| **F6-2** | **@Async 监听器触发存在性**：20s 窗口内**未观测到任何候选行** | **SKIP（未覆盖）** |

### 2.8 判据组 R —— 红证台账（**11 PASS / 0 FAIL**）

见 §3。

### 2.9 判据组 Z —— 零残留（**2 PASS + 1 故意 FAIL**）

见 §6。

---

## §3 红证台账（每条判据族至少一次注入式红证）

| 红证 | 注入（改一行 DB / 换租户 / 换期望） | 注入后读数 | 还原 | 内容指纹自证 | 结论 |
|---|---|---|---|---|---|
| **RP-A1/A2** | **两侧夹住**（非注入式，属"直连真对象"）：同一路径同一头，`DEBUG` 两侧 | `DEBUG=false`⇒**401**；`DEBUG=true`⇒**200** | 无需还原（两侧读数成对归档） | 两批 JSON 文件 sha256 记录在 `probe-redproof.json` | ✅ 判据有判别力 |
| **RP-B1** | `update sessions set tenant_id=21 where id=<探针会话>`（把会话挪到他租户） | 属主（租户 20 token）自读 ⇒ **403 `PERMISSION_DENIED`** | `set tenant_id=20` | `sha256(before)=…` ≠ `sha256(injected)`；还原后 **== before** | ✅ 每步断言会红 |
| **RP-B2** | （同上，还原侧） | 还原后 ⇒ **200**，指纹回到 `before` | — | **逐字节相等** | ✅ 红由注入造成、非恒红 |
| **RP-B3** | 前置对照 | 注入前 **200** / 还原后 **200** | — | — | ✅ 基线非空 |
| **RP-C1** | `update knowledge_cards set title='线①验收被改坏-…' where id=<探针卡>` | 「读面 == 期望标题」判据**当场为假**（读面返回改坏后的标题） | `set title=<原值>` | `sha256(fp0)≠sha256(fp1)` | ✅ 读面一致性判据会红 |
| **RP-C2** | （还原侧） | 判据**回绿**，`sha256(fp2)==sha256(fp0)` | — | **逐字节相等** | ✅ |
| **RP-D1** | `update knowledge_candidates set status='pending' where id=<已 rejected 候选>` | 「处置后不得仍 pending」判据**当场为假** | `set status='rejected'` | 状态读数 before/injected/restored 全留证 | ✅ 状态机判据会红 |
| **RP-D2** | （还原侧） | 判据**回绿** | — | — | ✅ |
| **RP-E1** | `update agent_sessions set tenant_id=21 where id=<探针会话>` | 「他租户必须拒」判据**被破**：租户 B **读到 200**（内容外泄形态） | `set tenant_id=20` | 基线 4xx / 注入 200 / 还原 4xx | ✅ 工作台租户判据会红 |
| **RP-E2** | （还原侧） | 租户 B 重新 **4xx** | — | — | ✅ |
| **Z1-2** | `insert into sessions … customer_id='probe_line1_ZCONTROL'` | 零残留计数**当场 = 1** | `delete` | 计数 0→1→0 | ✅ 零残留读数**不是恒 0 空断言** |

**命中"空断言"陷阱的一处已自我纠正（见 §7）**：`F6-1`（@Async 候选租户归属）在**空集上恒真** ——
候选行数 = 0 时"跨租户条数 = 0"必然成立。故本报告**不把它读成 pass**：与之配对的 `F6-2`（存在性）已如实记 **SKIP**，
`F6-1` 只作"**已观测到的行**无跨租户"的弱结论。

---

## §4 发现清单（逐条证据 + 复现步骤 + 归因层级）

### F-D1（**P2 · 确定性 · 归因=值级**）转人工端点对「不存在的 `aiSessionId`」返回 **500** 而非 4xx，并把 DB 约束报错写进日志

- **可复制复现**（零 LLM，逐字）：
  ```bash
  TOK=$(curl -s -X POST http://127.0.0.1:8080/api/auth/sms/login -H 'Content-Type: application/json' \
        -d '{"phone":"13870217889","code":"123456"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["data"]["accessToken"])')
  curl -s -o /dev/stdout -w '\nHTTP %{http_code}\n' -X POST http://127.0.0.1:8080/api/admin/agent-sessions \
    -H "Authorization: Bearer $TOK" -H 'Content-Type: application/json' \
    -d '{"aiSessionId":"probe_min","customerId":"probe_line1_min","reason":"线①验收最小体"}'
  # 实测：HTTP 500 {"success":false,"error":{"code":"INTERNAL_ERROR","message":"服务器内部错误"},"requestId":"req_9de8813818a84314",…}
  ```
- **逐字证据**（admin-api 日志，`acceptance/2026-10-03/out/main-live-7e9f66ce5-api.log` 第 5537–5557 行）：
  ```
  ERROR c.m.a.config.GlobalExceptionHandler - 系统异常:
  ### Error updating database.  Cause: org.postgresql.util.PSQLException:
  ERROR: insert or update on table "agent_sessions" violates foreign key constraint "agent_sessions_ai_session_id_fkey"
  ```
- **归因层级**：**值级**（字段 `aiSessionId` 的取值未做存在性校验；FK 在 DB 层才拦）。
  **不做更强归因**（不声称"任何合法行为都必失败"——正常链路里 ai-agent 传的是真实会话 id，实测正路 200，见 `F1-1`）。
- **影响面**：`POST /api/admin/agent-sessions`（转人工入口，**由 ai-agent 的转人工链路调用**）。
  **涉钱/涉权限：否**。真实风险 = ①把客户端可控输入变成 500 + ②内部 DB 约束名进日志（信息面）。
- **本包不做修复、不开 issue**（按任务纪律，交主会话处置）。

### F-D2（**P2 · 代码级 · 归因=存在性**）`assignSession` 不校验**员工所属租户**；同租户限制靠"员工必须存在"间接生效

- **代码级读数**（`backend/admin-api/src/main/java/com/migao/admin/service/AgentSessionService.java`，`assignSession` 内）：
  ① 会话归属校验（`session.getTenantId() != TenantContext.getTenantId()` ⇒ 404）**有**；
  ② 员工校验只有 `agentEmployeeMapper.selectById(employeeId)`（存在）+ `status != offline`，
  **没有** `employee.getTenantId() == 会话.tenantId` 这一步。
- **实测读数**：`F4-4` 用**租户 B 的探针员工**去 assign 租户 A 的会话 ⇒ HTTP **404「客服员工不存在」**。
  ⇒ 拒绝**成立**，但**归因不是租户校验**，而是"`selectById` 在 `TenantContext` 拦截器/`@TableLogic` 下按租户取不到该行"。
- **为什么不能升为"已定缺陷"**：无法给出"**该员工在本租户可见**"的反例 ⇒ 属**存在性级证据**，
  正确读法是「**校验缺位（代码级）** + 当前实现下拒绝（行为级）」。
- **建议判据（给修复包）**：断言"跨租户员工 id ⇒ 4xx"**之外**，补一条**单变量**：把员工行 `tenant_id` 改成会话租户 ⇒ 应 200；
  改回 ⇒ 应 4xx。**涉钱/涉权限：涉权限面**（他租户员工接管会话），但因无可用员工数据（`agent_employees` 云 dev **全表为空**）**未能实证**。

### F-D3（**P3 · 既有边界 · 知悉项**）内部面「持有 Service Token 即可指定任意租户」（承线④ F-1，**未变**）

- 本线在 `origin/main` 上独立复现同向结论：内部面只校验 `X-Service-Token`，`body.tenant_id` 决定租户（线④ G2 已给 20→35 件 / 21→1 件 / 1→93 件读数）。
- 本线新增读数：**写工具被单独拦**（`A3-4` ⇒ 403 `WRITE_TOOL_FORBIDDEN`）⇒ 破坏面被限制在只读。
- **涉权限、不涉钱**；**不重复登记为缺陷**（线④ 已给建议）。

### 与上述并行的「**不作为发现**」登记（避免被误读）

| 项 | 读数 | 为什么不列入发现 |
|---|---|---|
| `origin/main` 的 `logistics_track.py` 无缓存实现 | `logistics_trace_cache` 命中 0 | `origin/main` **自洽**（该文件与 import 都不存在）⇒ 不是缺陷；#6185 行为不在本线范围 |
| `knowledge_templates` 表不存在 | 模板清单来自代码内建（1 个 `curtain`） | **能力保留**（list/apply 可用）；"建/改/停用"无载体 ⇒ 记**未覆盖**（§5），不算缺陷 |
| 蒸馏面返回 0 条候选 | `D6-3` 登记 | LLM 面降级（契约不破），本线不判内容质量（#4262） |
| `apply` 模板后新建 27 张卡 | 见 §6.2 | **业务正常行为**（模板应用就是批量建卡）；已作副作用登记 |

---

## §5 未覆盖面（照实登记 —— **不得读成"通过"**）

1. **SSE / 流式面**：`app/api/chat.py` 的 `StreamingResponse(text/event-stream)` 与 `POST /api/chat/send` **必走真实 LLM** ⇒ 按 #4262 未跑。
2. **ASR**：`/api/chat/transcribe`（`app/api/asr.py`）依赖外部 ASR 服务 ⇒ 未跑。
3. **视觉识别面内容质量**：`POST /api/internal/vision/recognize` 只做了**鉴权存在性**覆盖（A3 族），未判识别结果。
4. **`@Async SessionDistillListener` 触发存在性**（**线④点名缺口，本线未闭合**）：`F6-2` = **SKIP**。
   - 已做的：会话走完 `waiting → active → ended`（`F1/F4/F5`），结束后 **20s 窗口**内查询
     `knowledge_candidates where source_ref like '%<agentSessionId>%' or '%probe_line1%'` ⇒ **0 行**。
   - **为什么没闭合**：候选产出依赖 LLM 蒸馏（`knowledge/distill`），耗时 ≥ 本次观测窗口（D6-2 单次调用已耗秒级且返回 0 条）；
     无法在不刷 LLM 额度的前提下等待到确定时点。⇒ **不硬凑**，如实记未覆盖。
   - **本线唯一能给的弱结论**：`F6-1`（已观测到的候选行**无跨租户**）在**空集上恒真**，**不构成租户归属证据**。
5. **真实 C 端用户 token 端到端**：本线用**与被测进程 `JWT_PUBLIC_KEY` 配对的私钥**（`~/migao-keys/jwt-private.pem`）铸造 RS256 token
   ⇒ 覆盖了"**C 端 JWT 契约与租户作用域**"（B 组），但**不是**真实小程序/微信登录链路签发的 token（未走 `externalId`/`openid` 绑定面）。
6. **未跑的 `:8001` 面**：`/api/chat/memories`、`/api/chat/upload`（代理转发）、`/api/internal/briefing/*`、
   `/api/internal/production/*`（7 条算料面）、`/api/internal/registration/*`、`/api/chat/products`、`/api/chat/payments`。
7. **未跑的 `:8080` 面（工作台侧）**：`/api/admin/agent-sessions/{id}/messages`（客服发言 ⇒ 触发 `waiting→active` 自动转换 +
   `@Async` 蒸馏，本线改走 `assign` 覆盖状态机）、`/monitor` 监控面板、`/api/customer/agent-sessions/**`（C 端人工会话面）。
8. **本包未做双 AI 交叉验证**（线④ §10 亦未做）⇒ 本报告结论为**单侧取证**，`out/*.json` 供主会话独立抽样复核。

---

## §6 零残留自证

### 6.1 逐表计数（机器读数，`out/probe-residue.json`）

| 表 | 清理前 | 清理后 |
|---|---|---|
| `sessions`（`probe_line1_%`） | **48** | **0** |
| `session_messages`（其消息） | 0 | 0 |
| `agent_sessions`（`probe_line1_%`） | **6** | **0** |
| `agent_messages` | 0 | 0 |
| `knowledge_cards`（`线①验收%`） | **5** | **0** |
| `knowledge_candidates`（`线①验收%`） | **5** | **0** |
| `agent_employees`（`l1emp%`） | **2** | **0** |
| **合计** | **64** | **0** |

- 清理方式：`delete … where customer_id like 'probe_line1_%' and (customer_id like '%<本包 tag>%')`（**tag 白名单**，
  逐条来自本包输出）+ 前缀 `线①验收%` / `l1emp%`；**未触碰**任何非本包前缀的行。
- **零残留判据的红证** `Z1-2`：注入 1 行 ⇒ 计数 **1** ⇒ 删除 ⇒ 计数 **0**（证明该读数不是恒 0 空断言）。
- **行级还原**：本包对**既有行**的改动只有 `RP-B/RP-E` 的 `tenant_id` 注入，**逐条立即还原**并用
  `sha256` 指纹证明**还原后 == 注入前**（`RP-B2`、`RP-C2` 逐字节相等）。

### 6.2 副作用登记（**不可自清，如实登记**）

| 副作用 | 读数 | 说明 |
|---|---|---|
| 应用知识模板 `curtain`（`E2-1`） | 租户 20 新建 **27** 张 `knowledge_cards`（`created_at` 窗口 `2026-10-03 13:46:45.108791+08` ~ `13:46:45.975633+08`） | **业务正常行为**（模板应用 = 批量建卡）；产物**不属于探针前缀**，无正当理由删除 ⇒ **不清理、如实登记**。后续如需回退：按上述时间窗定位 27 行 |
| 探针 AI 会话触发的 `@Async` 蒸馏 | 20s 窗口内 **0** 条候选 | 无残留；亦无产出（见 §5.4） |

---

## §7 假绿 / 假红自查（含本包自己踩的 4 条假红）

### 7.1 本包**已发生并已修正**的 harness 假红（**4 条，不得计入发现清单**）

| # | 假红 | 根因（判据缺陷，非产品缺陷） | 修正 | 修正后 |
|---|---|---|---|---|
| 1 | `B2-20/B2-21/B6-3`（3 条） | `customer_id` 期望写成 `A1_bmuryux5s`，实得 `probe_line1_A1_bmuryux5s` —— **我拼的期望里漏了自己的探针前缀**（`tenant_id` **本来就对**） | 期望改用 `PROBE_USER()` 生成的全量 id | **转绿**（B 组 20/20） |
| 2 | `A2-expired`/`A2-positive`（曾 2 条） | 用 **Node 侧 `openssl` 手工拼 RS256 签名**，自签自验失败（用 `PyJWT` 验同一份 claims 才通过）⇒ 工装造的 token 被服务端判 `Signature verification failed`。**读数是"服务拒了"，但那是工装错** | 改走 `mint_jwt.py`（PyJWT，唯一事实源），并在本地用 `jwt.decode` **自证 token 可验**后才打请求 | **转绿**（A 组 18/18） |
| 3 | `F3-1` | 用 `keyword=probe_line1` 过滤工作台列表 —— 而 keyword 命中的是展示字段（姓名/手机号），探针 `customerId` 不在其中 ⇒ 空集被读成"列表看不到" | 去掉 keyword，按全量列表核 id | **转绿** |
| 4 | `RP-C1/RP-C2` | 读面取 `data.records`，而该端点用的是 **`data.items`**（`{"total","page","size","items"}`）⇒ `hit=undefined` 被读成"判据为假"（**表面是红证成立，实际是工装取错键**） | 取键改为 `items → records → list` 兜底 | **转绿**（红证 11/11） |

> **教训（已写入判据写法口径）**：凡「期望字符串 == 实得字符串」的判据，**先问一句"我拼的期望里带没带我自己的前缀"**；
> 凡「读面 == 期望」的判据，**先 dump 一次原始响应确认取键**（本轮 `items` vs `records` 即此坑）。

### 7.2 其它自查项

| 形态 | 本包处置 |
|---|---|
| **空断言（恒真）** | `F6-1` 在**空集上恒真** ⇒ **已降级为弱结论**，并把存在性判据 `F6-2` 记 **SKIP**（不读成 pass）。`E2-2`/`D6-3`/`B7-3`/`D3-4` 明确标为**登记项（非判据）** |
| **假绿（基线取晚 / 陈旧产物）** | 所有"改变后再读"的判据（RP-B/C/D/E）**基线取在注入前**，且**还原后复读**（三段读数俱全） |
| **时间戳双偏移** | `nowCST()` 首版把真实 `13:42` 输出成 `21:42 +08`（本地 getter + 手工偏移叠加）⇒ 已改为 `Intl.DateTimeFormat('sv-SE', {timeZone:'Asia/Shanghai'})`；**受影响的是 13:42 之前的首批读数**，已归档 `out/superseded/`，`utc` 字段始终可信。**以 `13:43+` 批次为准** |
| **两次运行混在同一日志** | 旧批次日志已移入 `out/superseded/`；`out/run.log` 自 `13:43` 起为单一批次 |
| **故意失效控制项** | `Z2-1` 恒 FAIL（设计如此）⇒ 证明 recorder/judge 链路在真跑；若它变绿 = 整套读数不可信 |
| **构建点中途切换** | admin-api 于 `13:44:16` 换构建 ⇒ **A/B 首跑（13:43:02–13:44:03）属旧构建窗口**；C/D/E/F/R/Z 全部在 `7e9f66ce5` 上。报告已按窗口标注，**不混用** |
| **修复必须重放** | §7.1 四类假红**都做了重跑**（不是"改完就宣布好了"）；读数以重跑批为准 |

---

## §8 产物清单

| 文件 | 内容 |
|---|---|
| `harness/lib.mjs` | 共享库（JWT 铸造 / psql 只读与守卫写 / Recorder / judge / 构建点 / 探针域守卫） |
| `harness/mint_jwt.py` | PyJWT 铸造器（**唯一事实源**，见 §7.1#2） |
| `harness/p0-service-auth.mjs` | A 组（知识/鉴权；`MODE=debugfalse|debugtrue` 两侧） |
| `harness/p1-tenant-isolation.mjs` | B 组（租户链路 / 并发串号 / 身份作用域） |
| `harness/p2-knowledge-cards.mjs` | C 组（知识卡片全生命周期） |
| `harness/p3-knowledge-candidates.mjs` | D 组（候选 → 蒸馏 → 入卡） |
| `harness/p4-knowledge-templates.mjs` | E 组（知识模板） |
| `harness/p5-agent-sessions.mjs` | F 组（客服工作台 + @Async 缺口） |
| `harness/p6-redproof.mjs` | R 组（红证台账） |
| `harness/p7-residue.mjs` | Z 组（零残留 + 故意控制项） |
| `out/probe-*.json` | 逐条断言 + 证据引用（8 个判据组文件） |
| `out/ai-agent-service.{debugfalse,debugtrue,running}.log` | `:8001` 三次启动的原始 stdout（**无 `\| tail` 截断**） |
| `out/superseded/` | `nowCST` 修复前的旧批次日志（时戳带 +8h 偏差） |
| `out/BATCH-MARKER.json` | 批次日标记（构建点 + 批次起点） |
| `out/SUMMARY.json` | 汇总读数 |

**复跑方式**（`run-all.mjs`）：见同目录 `harness/run-all.mjs`。
