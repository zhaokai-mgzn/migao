# 2026-10-14 环境重建轮 · 全量回归 + UI 验收（总报告）

> 用户口径（2026-10-14）：「清除现有测试租户，对所有功能再做一遍全量回归测试，使用全新租户，发现问题就立即修复，
> 本次还包含对 UI 界面&交互功能验收，**不包含黄金策的评测**，**不要跑真实 llm**」。
> 补充裁定（同轮问答）：被测面 = **本地三件套 + 云 dev 库**；清除口径 = **删 tenants 两行（25/31）+ 清空其全部子表
> → 走真实入驻流程新建一个全新租户 → 本轮只测它**。
> 判定口径 = `migao-acceptance`：四态 `pass / fail(产品) / skip(未覆盖) / 假红(判据缺陷)`，**skip 永不折算成 pass**，
> 每条判定引证据。时间口径：**Asia/Shanghai（+08）**。
> 执行规格见 `BRIEF.md`（三线任务书）；三线各自的报告在 `line1-worker-config/` `line2-money-production/` `line3-aftersales-race/`。

---

## 1. 结论（一句话）

环境重建完成（旧租户 25/31 及其 **9771 行**子表数据全清 ⇒ 走真实入驻建出**全新 tenant 32**），
对**同一份代码**（`90192bcac`）跑了 **三线业务 sweep + 全链路冒烟 + admin-web 真机 UI 旅程**，
共 **约 750 条断言**；**确认并修复 1 条真产品缺陷**（入库单「过账×作废」竞态，涉库存台账，已开修复包），
**其余 20 余条红灯经逐条判别为「判据侧」**（其中 3 类验收资产漂移已在本轮修好并重放转绿），
**2 条属业务口径、登记待裁定**。UI 面 34 条旅程 **28 通过 / 2 判据侧红灯（已归因） / 4 未覆盖（skip）**。
**本轮不跑黄金策评测、不调真实 LLM、不派评测 workflow**（本机 `backend/ai-agent-service/.env` 无 `PRIMARY_API_KEY`）。

## 2. 被测环境事实（先钉事实，再看结论）

| 项 | 值 | 复核 |
|---|---|---|
| **被测构建点** | 本机主检出 **`90192bcac82b1d276d2793986ca9c64f47e47d16`**（= 当时的 `origin/main`） | `git rev-parse HEAD` |
| **被测租户** | **tenant 32**「米高测试环境」· 编码 `shop-ttf1` · 管理员 **13800138000** + 万能码 **123456** | `select id,name,code from tenants` |
| 建租方式 | `POST /api/auth/register` → 200 / `applicationId=2110346504629841922` / `review_source=ai`（summary 逐字「规则层校验通过；大模型审查暂不可用，已按规则降级放行」⇒ **确未调 LLM**） | `evidence/register-response.txt` |
| 租户 32 开箱种子 | users=1 · roles=7 · permissions=32 · role_permissions=100 · production_operations=41 · production_route_rules=27 · **categories=1**（「窗帘成品」，20:26:32 由入驻种下）· products=0 · orders=0 | psql 现取 |
| 本地三件套 | admin-api `http://localhost:8080` · ai-agent `http://localhost:8001`（`DEBUG=true`）· admin-web `http://localhost:3001` | `bash acceptance/2026-10-14/tools/start-stack.sh status` |
| DB / Redis | 云 dev RDS `ai_customer_service` · Redis 仅 `token:blacklist:*`（无租户态） | `evidence/wipe-tenants.json` |

**⚠️ 本地形态的两条口径（读数归因的前置）**：

1. **必须用 `localhost`，不能用 `127.0.0.1`**：登录下发的 `access_token` / `refresh_token` cookie 带 `Domain=localhost`。
   用 `127.0.0.1` 访问 ⇒ 域名不匹配 ⇒ cookie 进不了 jar（冒烟刷新链路当场 401）、浏览器侧 CORS 白名单也不含它。
   本轮第一次 UI 旅程整轮失败就是这个原因（**环境注入错**，不是产品）。
2. **本地直起没有 nginx**：`/actuator/health` 在部署形态被 nginx 屏蔽（404），本地是 200 —— 判据必须按形态分支
   （本轮已修，见 §5.1）。

## 3. 环境重建（清除 → 新建）

| 步骤 | 读数 | 证据 |
|---|---|---|
| 清除前 | tenants = **25「词元通达」**(users 72 / orders 348) + **31「云锦布艺」**(1 用户 / 6 商品) | 本报告 §2 前的现取读数 |
| 清除 | `python3 acceptance/2026-10-14/tools/wipe-tenants.py --tenant-ids 25,31 --apply` ⇒ **79 张表 / 9771 行 + tenants 2 行**（拓扑序由 `pg_constraint` 现取、子表优先、单事务；首版把「子表优先」写反 ⇒ 被 FK 拒并整体回滚，修正后一次通过） | `evidence/wipe-tenants.json` |
| 附带清除 | `tenant_applications` 6 条（全属已删租户的入驻申请残留；不清它就无法用同一手机号重新入驻） | 本报告 |
| 残留自证 | 点名租户子表残留 **0 行**、`tenants` 点名行 **无** | 同上 |
| 新建 | 真实入驻 ⇒ **tenant 32**（§2） | `evidence/register-response.txt` |

## 4. 四态总表

| 面 | 读数 | 说明 |
|---|---|---|
| 线① 工人端 / 小程序 / 配置写面 | pass **270** / fail **31** / skip **13** / 假红 **24** | `line1-worker-config/` |
| 线② 钱 / 工资 / 库存时效 / 派工 / agent 服务 | pass **191** / fail **45** / skip **12**（假红 24 + 环境夹具 18） | `line2-money-production/` |
| 线③ 售后 / 租户隔离 / 并发竞态 | pass **83** / fail(产品) **2** / skip **4** / 假红 **3** | `line3-aftersales-race/` |
| 全链路冒烟（`tests/smoke`，非 LLM 档 9 个文件） | 修前 **62 pass / 9 fail / 14 skip** → 修后 **78 pass / 0 fail / 8 skip** | `main-smoke/pytest.log`、`pytest-after.log` |
| UI（admin-web 真机旅程 34 条） | **28 pass / 2 fail（判据侧，已归因）/ 4 skip** | `main-ui/` |
| 静态门禁 | `check-ui-regression.sh` ✅ · `contract-check.sh` ✅（6 项全过） | 见 §6 |

**fail 桶的纯度（防粗读成"一堆产品缺陷"）**：三线 **78 条 fail 里 1 条是本轮确认的真产品缺陷**（§5.2 F1），
其余经逐条判别为：判据侧假红 / 环境夹具 / 期望值过期 / 故意失效控制项（详见 §5.3 与各线 REPORT）。

## 5. 发现问题

### 5.1 已修复（判据侧 3 类 + 1 条工装改进，均有修前红 / 修后绿成对读数）

| # | 问题 | 修前读数 | 修后读数 | 判据 |
|---|---|---|---|---|
| **J1** | `tests/smoke/test_09_order_lifecycle.py` 的订单载荷**缺 `logisticsType` / `logisticsCompany`**，而 #5840（2026-10-01 用户裁定）起表单路径三项必填（闸门 = `OrderController.requireFormOnlyFields`）⇒ **7 条用例恒红**，且从没在 CI 跑过（CI 只跑 `-m p0`，本文件是 `p1`） | `7 failed`（逐条 422「常用物流/快递不能为空」） | 全绿 | `main-smoke/pytest.log` → `pytest-after.log` |
| **J2** | 新增负控：缺物流两项 ⇒ **422 且逐条具名**（把 #5840 的闸门钉住，防"闸门被回退成静默放行"） | —（新判据） | pass | `test_create_order_missing_form_required_fields_rejected` |
| **J3** | `test_01_health` 无条件要求 `/actuator/health == 404`（那是**部署形态** nginx 的行为）⇒ **本地直起形态恒红** | fail | 按形态分支（https ⇒ 404；本地 ⇒ 200 + `status=UP`）pass | `test_01_health.py` |
| **J4** | `test_02_auth` 刷新链路依赖 cookie jar，而刷新 cookie 带 `Secure` ⇒ httpx 在 **http** 上不发送它 ⇒ 本地**恒 401「缺少 Refresh Token」** | fail | 本地形态从 jar 显式带该 cookie（**部署形态一字不放宽**）pass | `test_02_auth.py` + `helpers.refresh_token_from_jar` |
| **J5** | UI 工装 `scripts/ui-smoke-merchant/spec.mjs` 的 `console.error "401"` **不带 URL** ⇒ 归因卡死（本轮实测：单看文案分不清是 admin-api 还是 ai-agent） | 无法归因 | 新增「失败响应账本」，把窗口内 `≥400` 的 `<status> <method> <url>` 并进错误清单 ⇒ 当场定位到 `POST /api/auth/refresh` / `GET /api/auth/me` | `spec.mjs`（`failedResponses`） |

> J1 的价值不只是"变绿"：它把一条**长期恒红、且不在任何 CI 档里**的判据面恢复成可用；J2 是它的负控
> （判据侧"修好即忘"的同族防线）。J5 让下一次同类红灯可归因，而不是再花一轮去猜。

### 5.2 真产品缺陷（1 条，已开修复包）

**F1（高 · 涉库存台账）入库单「过账 × 作废」交叉竞态 ⇒ `post` 抢到的过账权被 `cancel` 抹掉，库存 +5 与入库台账 1 行静默留在库里。**

- 复现：同一张草稿单**严格同时**发 `PATCH /api/admin/inbound-orders/{id}`（`action=post`）与（`action=cancel`）；
  20 轮命中 **3 轮（15%）**：`post=200` `cancel=200` 而库侧 `status=cancelled`、`stock 30.0→35.0`、`stock_ledger_entries` 1 行；
  其余 17 轮为单赢家（`post=409` / `cancel=200`，库存与台账 0 变化）——**正对照**。
- 根因（符号级）：`backend/admin-api/src/main/java/com/migao/admin/service/InboundOrderService.java`
  `#post` 用条件更新抢过账权（`markPosted`，0 行即 conflict），**同文件 `#cancel` 没有**：先读内存旧值判 `draft`，
  再 `updateById`（`WHERE` 仅主键）⇒ 与 post 的 CAS 不互斥。产品文案自己写着「已过账的入库单…冲销请另开单据」
  —— 契约在文案里，**没落到 SQL 谓词上**。
- 证据：`line3-aftersales-race/out/race/probe-write-raw.json::cases.W2`、`out/race/W2-rounds-index.txt`（逐轮毫秒时间线 + 库侧三读数）、
  `line3-aftersales-race/REPORT.md` §2.1；一键复算 `bash acceptance/2026-10-14/line3-aftersales-race/run-w2-rounds.sh`。
- 处置：**已修并已独立重放** —— issue **#6928** → PR **#6931**（`InboundOrderService#cancel` 改成与 `#post` 同款条件更新
  `markCancelled`（`WHERE id=? AND tenant_id=? AND status='draft' AND deleted=0`，0 行 ⇒ 409）+ 类级元守卫 MC-100 + 台账基线 0）。
  **主会话独立重放**（新起修复版 admin-api `:8081`，20 轮严格同时起跑，同一探针对象）：
  **修复后 18/18 轮 `inconsistent=0`**（`post=409 / cancel=200 / delta=0 / ledger=0`），
  **同脚本打原 `:8080`（未修）18 轮里 1 轮命中 `inconsistent=3`**（`post=200 / cancel=200 / db=cancelled / delta=5 / ledger=1`）
  —— 成对读数见 `evidence/w2-race-replay-mainsession.txt`（每段各有 2 轮因探针瞬态 `KeyError: 'requests'` 未计入，
  按「未跑」读，不计入分母）。命中率随负载在 **5% ~ 40%** 间波动（线③ 15% / 修复包 40%）⇒ 这也正是「只跑一轮会漏」的证据。

### 5.3 判据侧问题（逐条带**判别证据**；含主会话对子代理结论的**独立复核订正**）

> 归因纪律：证据不足就写"证据不足 + 缺什么"。下面前 4 条是**主会话独立复核后推翻子代理初判**的（子代理把它们记成了产品缺陷）。

| 编号 | 结论 | 判别证据 |
|---|---|---|
| **R1** | 线② `L2-F1`「纱帘侧韩褶漏插 `上车布-纱`」**不是产品缺陷**，是判据按**工序目录全序**期望、忽略了**部位维** | `ProductionSeedTemplateService.java` 的规范工艺变体规则里，`{韩褶, 布帘, insert, 上车布, 韩褶}` **逐字带着 issue #4962 的注释**（"`V71` 的字面量种子里 `韩褶 → 上车布` 就是 `position='布帘'`"，迁移链侧由 `V108__restore_route_rule_positions.sql` 写回）⇒ 部位维是**有意设计**（用户 2026-09-21「工序只能布帘有或纱帘有，可以在**适用条件**上设置」）。库内 `上车布-纱` 的 `applicable=true` 是**目录/计价**属性，不等于"必须被某条路线引用" |
| **R2** | 线① `L1-F2` / `L1-F4`「发货写面多改 `orders.shipped_at`」**不是产品缺陷**，是判据白名单漏了它 | 发货动作写发货时间就是**产品正确行为**（`orders.shipped_at` = 发货事实本身）；判据的允许集写成"仅 status/updated_at"，且同一判据对流水表做了同款豁免、漏了 orders ⇒ 判据侧允许集不全 |
| **R3** | 线③ `F2`「全新租户 0 商品分类 ⇒ 建商品 422 不可达」**不成立** | 现取：tenant 32 的 `categories` 在 **20:26:32**（入驻时）就有「窗帘成品」一条（#6295 的入驻种默认分类**在位**）；探针 `B1-category-gap.json` 的 `catsBefore=[]` 是其**查询口径/窗口**问题，且它自己随后 `POST /api/admin/categories` = 200 ⇒ 建有分类后建商品链路可走 |
| **R4** | UI `06-agent-sessions` / `07-chat` 的红灯**不是产品缺陷**（页面级断言两条都过） | J5 补上归因后逐字得到失败响应 = `401 POST http://localhost:8080/api/auth/refresh` + `401 GET http://localhost:8080/api/auth/me`（**admin-api**，不是 ai-agent；同窗口 ai-agent 侧 0 条 401）。两条都是冷启动的**未认证探针**：判定口径（`console.error` 计数）把"预期的 401"记成了失败 |
| R5 | 线② `L2-F3`（`/api/chat/**` 全 401）**是工装侧密钥错配**，不是产品鉴权 | 同一时刻用**真实登录 token** 直打 `:8001` 的 `/api/chat/quick-actions`、`/api/chat/sessions`（GET/POST）**均 200**（本报告 §7 复现）；线② 用的是自签 token（`~/migao-keys/jwt-private.pem`）⇒ 与 admin-api 签发密钥不成对。**注意**：本轮还实测到一条真环境坑 —— ai-agent 若从**已 source 过 `backend/admin-api/.env`** 的 shell 启动，会继承 `JWT_PUBLIC_KEY=classpath:rsa/public.pem` ⇒ `/api/chat/**` 全 **500** `InvalidKeyError`（我已按干净环境重启修复，见 §7） |
| R6 | 线③ `G1` / 线① 构建点自检 `W0-00b`、线② `LB0-01` 等**期望值过期伪影** | 判据写死 2026-10-04 部署台账 sha（`p0-env.mjs:23 EXPECTED='ff655a06c'`）或依赖 `LIVE_WORKTREE` 未注入 ⇒ 判据对象 ≠ 本轮被测对象（本机检出） |
| R7 | 线① P3 9 条 / P5 4 条 **夹具漂移** | P3：夹具送 `quantity='7.5'`（米数），而 #6812 起 photo 入库该字段 = **卷数正整数**（`WorkerInboundDraftRequest.java`）；P5：worker-h5 早改「工号+企业编码」(#6564)，夹具仍用 `?tenant_id=` |
| R8 | 线① `config/W6-05` **与初判相反**：本轮实测 **pass 且未增行**（`craft_calc_configs` 那行本就存在，`margin_multi 0.31→0.32`）；真问题是它的 **restore 段把"自己改的行"误判成"别线的行"** ⇒ 写面残留（已由该线手工还原 `0.31`） | `line1-worker-config/REPORT.md` + 现取 `max(margin_multi)=0.310` |
| R9 | 线③ `sweep#2/#3`（`tenant-isolation` / `tenant-concurrency`）**整 sweep 判"未覆盖"** | 这两个 harness **无 env 注入口**（`sweep.mjs` 主体矩阵 + 手机号硬编码 20/21/1）⇒ 被测对象注不进去、登录即 401 ⇒ **一条判据都没跑出**（不是"跑过且绿"，已按未覆盖登记）。线③ 另建 `probe-cross-tenant.mjs`（32↔34 真租户对）**4/4 补测通过**，部分补上射程 |
| R10 | 工装小缺陷若干（不影响判定，如实登记） | `shipments-sweep/lib.mjs::nowCST` 显式 `+08` 却取 UTC 墙钟 ⇒ 日志时间戳偏 8h；`race/run-all.sh` 路径拼接错（`acceptance/acceptance/…`）⇒ `MODULE_NOT_FOUND`；`worker-miniapp-writeface/SUMMARY.json` 的 `buildPoint.how` 引用了已删除的 main-live worktree |

### 5.4 待裁定（业务口径；已登记，不武断判产品）

| 编号 | 问题 | 为什么交人工 | 不裁时的安全默认 |
|---|---|---|---|
| **D1** | 线② `L2-F2`：**选项工序在目标部位无变体时"静默成功、少一道工序"**（拼1次/加花边/加铅块/接高/加logo条/加立边/扣环/防翘扣 对纱帘 ⇒ `generate` 200 且序列里没有它）。目录里这些工序对纱帘是 `applicable=false` | 属**业务口径**：选项对"不适用的部位"应当**拒绝并指名**还是**静默跳过**？产品文档未明写；而它**可能涉钱**（选项若计价，静默丢弃 = 收了钱没干活） | 现状不变；登记为观察项 + 建议：若选项带价 ⇒ 必须 fail-closed 指名缺口 |
| **D2** | 线③（并线① `I5`）：**商家发货路不认 `X-Client-Request-Id`**（同键两次都不回放；第二次因"未发生发货流转"422，`client_request_keys` 零命中、tracking 未被覆写 ⇒ **破坏性副作用为零**） | 幂等键的**覆盖范围**是产品契约问题（`X-Client-Request-Id` 在报工/入库链路上是硬要求，商家发货路是否也要求未明写） | 现状不变（第二次被安全拒绝，无脏数据）；登记 + 建议：要么纳入幂等契约并写进文档，要么明确"商家发货路不消费幂等键" |
| **D3** | 线① `L1-F1`：并发 5 次 `DELETE /operations/{id}/detach-and-delete` ⇒ `[200,200,200,422,422]`（**终态正确**：`deleted=1`、无半完成、无残留） | 与 F1 **同族**（check-then-act 无 CAS），但**后果无害**（幂等效果），是否值得改取决于"并发语义要不要 exactly-once" | 现状不变；登记为**同族跟随项**（F1 的类级固化若落地，本项应一并纳入射程评估） |

### 5.5 UI 界面 & 交互验收

> ⚠️ **本节的部分归因已被 §11 取代**（2026-10-14 深夜二次补跑）：`17-/32-` 的 skip 理由**不是**「租户未配生产路线」，
> `27-/28-` 也不是「预算到点未跑」—— 真因与修后读数见 **§11.2**；本节的数字是**首次全量**那一轮的原样读数，不改写。
- 运行器 = `scripts/ui-smoke-merchant/spec.mjs`（真浏览器 Playwright + 真后端 + 商家 persona + 截图），
  被测面 = 本地 admin-web `http://localhost:3001` → admin-api `http://localhost:8080`，租户 32。
- 结果：**28 / 34 通过**，2 失败（= §5.3 R4，判据侧），4 skip：
  - `17-order-ship` / `32-production-qr-and-piecework`：**前置不满足**（该租户未配「生产路线/默认工艺」⇒ 生成加工单
    接口 HTTP 200 但 `data` 为空，api 日志 `INCIDENT_PRODUCTION_ROUTING_UNRESOLVED`）。
    ⚠️ **观察项 → 已判「设计良好」，观察项关闭（2026-10-15；重启条件「有配好默认工艺的租户」已满足）**。首轮记的「接口 200 + 空 data + 只落日志」经复核**不成立**：
    - 服务端失败是**逐单结果**，不是只落日志：`ProcessingOrderService::generate` 的循环里 `try/catch BusinessException`
      ⇒ `GenerateResult.fail(rawId, code, message, suggestion)`，**且不影响其余单**；T3 fail-closed（缺工艺 / 无默认路线）也是
      `BusinessException(ERR_ROUTING_NOT_FOUND, "订单未给出工艺（craft），且该租户没有配置默认工艺，无法实例化工序", <建议>)` ⇒ 走**同一条**通道
      （`git show origin/main:backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java`）。
    - 前端**逐字转发、不改写不吞掉**：`frontend/admin-web/src/components/orders/ProcessingOrderBlock.tsx`
      `setError(r?.message ?? '生成失败')` + `setErrorHint(r?.suggestion ?? '')`。
    - 实测回执（租户 32，工艺已配）：`{"success":false,"message":"订单 … 当前状态 [pending] 不允许生成加工单，须为已确认","code":"VALIDATION_ERROR"}`
      —— **可行动**（该条也被 #6940 用作 `17-`/`32-` 的修法依据）。
    ⇒ 结论：**不是产品缺陷**；首轮那条是探针把**另一个租户**的叙事抄了进来（`data` 并不为空 —— 与 §11.2 的归因更正同源）。
    **仍未覆盖**：`17-`/`32-` 走的是**成功路径**，旅程式判据尚未覆盖「生成失败 ⇒ 商家看到可行动文案」这条**失败路径**（见 §9）。
  - `27-corporate` / `28-register`：整轮预算（1500s）到点，未跑（**不是通过**）。
- 证据：`main-ui/out/**`（截图按旅程命名）、`main-ui/spec.log`、`main-ui/replay.log`（重放 06/07/27/28）。
- **工人端（worker-h5）UI 层**：真 Chrome + CDP 几何探针 `scripts/probe-worker-h5-touch.mjs` ⇒ **31 条全过（exit 0）**
  （360/390/430 三视口的页头按钮单行 / 无横向溢出 / 触控高 ≥44px）；读数 `evidence/worker-h5-geometry-probe.json`。
  ⚠️ 该探针是**夹具渲染**（真页面 DOM + 真 `styles.css`），**不是**登录后的真机旅程 ⇒ 工人端**登录后写面**的 UI 级覆盖
  仍为**未覆盖**（见 §9）。
- **小程序端（bmini / mini-app）UI 层**：本地面（用户选定的被测面）**不驱动** Taro 小程序 —— 该面的 UI 判据由
  **CI 腿**承担（本 PR 上 `bmini-app build (h5+weapp)` / `bmini H5 tabBar geometry (e2e)` / `bmini-app typecheck + unit tests` /
  `mini-app typecheck + unit tests` / `xiaobu H5 visual regression` **全部 pass**，`gh pr checks 6927`）；
  写面契约由线① 的 API 级 sweep 覆盖。**已部署面**（`app.migaozn.com/b/`）本轮**未测**（不在用户选定的被测面内）。

## 6. 静态门禁

| 门禁 | 读数 |
|---|---|
| `./check-ui-regression.sh` | ✅ UI 无回退（关键文件与 main token 一致或为正常新增） |
| `./contract-check.sh` | ✅ 6 项全过（订单状态词表 / 退款字段三端 / 物流读字段 / 单 SKU 改价端点 / 退款蛇形契约 / intent 归属） |
| `./verify-all.sh gate` | ✅ **1 通过 / 0 失败**（含 QA Growth Gate 预检；未命中的面按设计**显式打印「未跑」**，不当通过读） |
| `./verify-all.sh gate`（**§11 收口轮复跑，最终 main `fc8b2e0a3`**） | ✅ **1 通过 / 0 失败，0 未就绪**（真跑 1 项 / 共 1 项，exit 0）。逐字「未跑」四项：`cases 面` / `红证机具面` / `bmini-app 腿` / `ci workflow helper 腿` —— 变更集未命中其触发面，**都不是「通过」**（CI 对每个 PR 无条件跑同名守卫）。⚠️ gate 自报一条口径：**预检不覆盖未提交改动**（本次是「报告与证据提交后」的读数） |
| CI（PR #6927） | ✅ 全绿：admin-api / ai-agent / admin-web / mini-app / bmini 单测 + typecheck、Case Trust / Case Contract / Case Coverage、QA Growth、UI Regression、E2E quality、Post-Merge Verify…（`gh pr checks 6927`，两条 required helper 腿在后半轮也 pass） |
| `./scripts/batch-gate.sh <本包> <修复包>`（多包只跑一次全量） | ⛔ **拒绝（exit 3，没跑）**：就绪判定里 `fix/6928-inbound-cancel-cas` 已**无 open PR** —— 该包在批次启动前 **21:43:21 +08 已合并** ⇒ 按 fail-closed 拒绝，**没跑那一次全量**（「没跑」既不等于通过、也不等于失败）。**等价覆盖** = ① 本包在**新基准**（`origin/main` 已含 F1 修复 + 本分支）上重跑 `./verify-all.sh gate` ⇒ ✅ **1 通过 / 0 失败**；② 修复包合并前 required 全绿（含两条 `ci workflow helper unit tests` 与 `admin-api unit tests`）。 |

## 7. 本轮的两条环境事实（供下一次接手）

1. **ai-agent 启动 shell 必须干净**：`backend/admin-api/.env` 里有 `JWT_PUBLIC_KEY=classpath:rsa/public.pem`
   （Spring 的 classpath 引用，**不是 PEM**）。若在 `set -a && . backend/admin-api/.env` 之后启动 ai-agent，
   子进程会继承它（env 优先级高于 ai-agent 自己的 `.env`）⇒ `/api/chat/**` 全 **500** `InvalidKeyError:
   Could not parse the provided public key`，而浏览器侧只看到"CORS 被拦"（500 响应不带 CORS 头）——**症状与根因离得很远**。
   本轮踩过并已修（干净环境重启后 `/api/chat/**` 200）。`tools/start-stack.sh` 里 ai-agent 在独立子 shell 启动，不继承。
2. **`localhost` vs `127.0.0.1` 不是等价写法**（见 §2 口径 1）。

## 8. 残留与终态（现取）

- `tenants` = **1 行**（只剩 `32 米高测试环境`）；临时对照租户 **34**（线③ 建）已按 FK 拓扑序清空并删行（清理前子表 391 行 → 0）。
- 各线**自建探针**清理后 = 0（线① `users_la/orders_la/po_la/ops_la/…` 全 0、`margin_multi` 还原 0.31；
  线② knowledge_cards/candidates/agent_sessions/messages 全 0；线③ 三命名域 + `lb3-race` 全 0）。
- tenant 32 内留有本轮**端到端旅程**产生的数据（UI 建单/冒烟/冷启动链，现取 orders 63 条含本轮命名域）
  —— 属**被测租户自身的测试数据**（该租户就是下一轮的起点），**不是本轮尾巴**；如需清空：
  `python3 acceptance/2026-10-14/tools/wipe-tenants.py --tenant-ids 32 --apply`。
- 机器级重活锁：已释放（`./scripts/machine-heavy-lock.sh status` 显示无持有者）。

## 9. 未覆盖清单（skip，永不折算 pass）

| 面 | 原因 | 重启条件 |
|---|---|---|
| 黄金策（B 端 agent）评测 | 用户本轮口径**明确不做** | 用户显式要求 |
| 真实 LLM 面（`test_04_ai_chat` / `test_11_knowledge_ai_advanced` / `test_react_smartness`、评测 workflow） | 本机无 `PRIMARY_API_KEY`；#4262 裁定不自动派发 | 用户显式要求 + 有 key |
| `tenant-isolation-sweep` / `tenant-concurrency-sweep` 两整 sweep | harness 无 env 注入口（硬编码租户 20/21/1）⇒ 一条判据都跑不出（线③ 已用自建 `probe-cross-tenant.mjs` 部分补测 4/4） | harness env 化后（需派包） |
| UI `17-order-ship` / `32-production-qr-and-piecework` | ~~租户未配默认工艺/生产路线（见 §5.5）~~ **该理由已作废**（真因 = 依赖探针把「订单未确认」误判成「租户未配路线」）⇒ **已修，三条转 pass**（§11.2） | — |
| UI `27-corporate` / `28-register` | ~~整轮预算到点未跑~~ **其中 `28-register` 是台账里的幽灵名**（实际名 `31-register`，本轮就 ✅）；`27-corporate-home` 单跑 ✅（§11.2） | — |
| **加工单「生成失败」的失败路径**（商家是否看到可行动文案） | `17-`/`32-` 走的是**成功路径**；失败路径的产品行为已由**代码级**证据判定（逐单 `GenerateResult.fail` + 前端逐字转发 message/suggestion，见 §5.5），但**没有旅程式判据**守着它不退化 | 派一个 UI 工装小包：造一条**必然失败**的生成（如订单停在 pending 或造一个无默认工艺的租户）⇒ 断言页面出现**服务端逐字 message**；配套类级判据 = 前端失败文案必须来自响应而非硬编码 |
| 打印/标签硬件通道、微信开发者工具真机模拟器、裁剪机等未落地模块 | 面不存在 | 落地后 |
| 线①/②/③ 各自的 skip 明细（共 29 条） | 见各线 REPORT 的「未覆盖清单」 | 各条自带 |

## 10. 明确不做（in scope 之外）

黄金策评测、真实 LLM 调用与评测 workflow、`verify-all.sh gate` 的逐包重复跑（批次统一一次）、
改产品代码（**除 §5.2 F1 的修复包外，三线验收期间 backend/**、frontend/** 零改动**）、
清空 tenant 32（它是下一轮的起点）。

---

## 修复包状态

| 项 | 状态 |
|---|---|
| **判据侧 J1–J5 + 本轮证据** | issue **#6926** → PR **#6927**（`gh pr checks 6927` 全绿；auto-merge 已 arm；本轮已两次随 main 前移 `update-branch`） |
| **F1（入库单过账×作废竞态）** | issue **#6928** → PR **#6931** ✅ **已合并**（auto-merge squash，merge commit **`9bc283cad`**，**2026-10-14 21:43:21 +08** = 13:43:21Z；issue 已 CLOSED）：`#cancel` 补条件更新 CAS + 真库并发判据 `InboundOrderCancelRaceRealDbTest`（3/3 pass，case **OR-066**）+ 类级元守卫 `InboundOrderStatusCasMetaGuardTest`（6/6 pass，case **MC-100**，豁免基线 0）+ 台账；**主会话独立重放**：修复版 18/18 轮 0 命中 ⇄ 未修 :8080 1/18 命中（`evidence/w2-race-replay-mainsession.txt`）。合并后内容级自证（`git show origin/main:<path>`）：`markCancelled` 在 mapper 1 处 / service 调用点 1 处、`REALDB_FILES` 登记 1 处 |
| D1 / D2 / D3 | **已开单**：**#6934**（D1 涉钱·待裁定）/ **#6935**（D2 契约·待裁定）/ **#6936**（D3 并发·已裁定「跟随 #6928 范式」⇒ 已派包，见 §11.1） |

---

## 11. 二次补跑 + 修复包落地（2026-10-14 22:00 ~ 2026-10-15 00:2x +08）

> 触发 = 用户在会话里选定的后续批次（② 补 UI 未覆盖 4 条 / ③ 待裁定三单落地 / ④ 验收资产修正包）。
> 口径不变：**skip 永不折算 pass**；判据侧缺陷与产品缺陷分开记；每条结论都要能复算。

### 11.1 修复包台账（7 单，全部合并；单元 = issue + 分支 + 独立 worktree + 后台执行者）

| 单 | PR | 合并（+08；UTC 原点见括号） | 内容 | main 侧自证读点（`git show origin/main:<path>`） |
|---|---|---|---|---|
| #6926 判据侧 J1–J5 | #6927 | **22:13:12**（`14:13:12Z`）`261377ff3` | smoke 三类恒红 + UI 红灯可归因 | `test_09` 的 `logisticsType`×5 / `spec.mjs` 的 `failedResponses`×4 / `helpers.py` 的 `refresh_token_from_jar`×1 |
| #6928 F1 入库过账×作废竞态 | #6931 | **21:43:21**（`13:43:21Z`）`9bc283cad` | `#cancel` 条件更新 CAS + 真库并发判据 | `markCancelled` 在 mapper 1 处 / service 1 处 |
| #6937 两条 sweep env 化 | #6944 | **22:45:25**（`14:45:25Z`）`bb55efa71` | 唯一注入口（缺一 exit 2）+ 写死主体守卫 + B 侧对照租户自造/自清 | `lib/subjects.mjs` 的 `guardSubjects` / `sweep.mjs` 引用它 ×2；**主会话注入式红证复现**：写死手机号 ⇒ `exit 3` + 逐字 file:line；A 有效 + B 不存在 ⇒ `exit 3`（`pass=38 fail=0 skip=50 total=88`） |
| #6938 夹具漂移 6 条 | #6943 | **22:57:50**（`14:57:50Z`）`091313a2a` | 卷数 / worker-h5 入口 / batch 对照租户 / `nowCST` / 命名空间豁免 / `run-all.sh` 路径 | `nowCST().cst = 2026-10-14 22:31:56 +08` = 真值（主线未合时是 `14:31:56 +08`，**错 8h**，同命令同 `TZ=UTC` 单变量对照） |
| #6940 UI 四条判据侧 | #6941 | **23:48:36**（`15:48:36Z`）`daa08f558` | 见 §11.2 | `waitForText`×2 / `ensureLoggedIn`×14 /「加工分类前置」×1 /「确认状态流转」×1 |
| #6936 D3 detach 并发 CAS | #6945 | **2026-10-15 00:10:56**（`16:10:56Z`）`8579755e6` | 内联条件更新（三谓词）+ 影响行数 0 ⇒ 409 | `LambdaUpdateWrapper`×3 / mapper `claimDelete` 残留 **0**（不留死代码）/ `PG-075` 元守卫 ×6；**主会话在合并后的 main 上独立复跑** `Tests run: 5, Failures: 0`，逐字 `[READING #6936 并发] 各状态=[409,409,409,409,200] 成功数=1`、`PG-075 豁免 现取=0 基线=0` |
| #6942 UI 工装残余三条 | #6947 | **2026-10-15 00:31:35**（`16:31:35Z`） | 旅程名台账⇄注册名双向守卫 / 清理链（`on_sale` 需先下架）/ 单组跑登录确定性（发码失败只记不抛 + tab 门禁改判 `aria-selected`） | `test_ui_smoke_name_ledger.py`（`case_ids:` 在）/ `test_ui_smoke_criteria_trust.py` 剥注释后核（8 处）/ `ALL_JOURNEY_NAMES` 已是 `27-corporate-home`…`31-register`（旧幽灵名仅存于**注释**里的「旧形态」说明）/ **主会话删冗余复核：`spec.mjs` 的 `loginWindow` 残留 = 0**（它按协调删掉了我那段已冗余机制）/ 证据面 `acceptance/2026-10-15/ui-harness-tail/smoke-tail-summary.md` 在位 |

> 说明：**#6945 的两条红不是 drift-audit**（我按同名 check 推断错了，由执行者用日志纠正）——
> 是 `test_logic_delete_write_shape.py`（#4608「三处软删必须显式写列」，它把软删抽进 mapper `@Update` 后 `#delete` 里那段内联片段消失
> ⇒ 判据不动、**改回实现侧**）与 `test_case_machine_fail_channel.py::test_i3_anchor…`（两条新用例按设计不进 agent-eval
> ⇒ 机器判红读数 **148 → 150**，同 PR 重锚，`no_channel_total` 仍 0）。

### 11.2 UI 面：4 条「未覆盖」全部落地，且**三条的原始理由被更正**

| 旅程 | 首轮记的理由 | 复核实测（逐字） | 修后 |
|---|---|---|---|
| `17-order-ship` / `32-production-qr-and-piecework`（+`16-`） | 「租户未配生产路线/默认工艺」（抄的是**另一个租户**的 `INCIDENT_PRODUCTION_ROUTING_UNRESOLVED tenantId=25` 叙事，且断言「data 为空」） | 本租户**已有**默认工艺 `韩褶` + 默认路线模板；真因 = **探针单没确认**，服务端逐字 `{"success":false,"message":"订单 … 当前状态 [pending] 不允许生成加工单，须为已确认","code":"VALIDATION_ERROR"}`（`data` **并不为空**） | 探针先 `PUT /orders/{id}/payment` ⇒ **三条 skip → pass**（`--group 1` **10/10 通过、0 失败**） |
| `12-processing` | 「等新建加工项超时」（api 日志里连该名字都搜不到） | 弹窗在**0 个活跃分类**时改渲染「当前还没有加工分类…请先创建：」⇒ 必填项为空 ⇒ 保存被客户端校验挡住、**POST 根本不发**；且分类**必须在 `nav()` 之前**建（页面加载时就把列表拉进内存，晚建 ⇒ 弹窗仍走「请先创建」分支） | 前置自造（API 建分类）+ `ensureLoggedIn` ⇒ **单组跑与全量跑都 ✅** |
| `10-product-detail` / `01-login`（时红时绿） | 未归因 | `POST /api/auth/sms/send` 的 **400** 来自**登录助手自己**点「获取验证码」，浏览器只报「status of 400」不带 URL ⇒ 首个旅程被 console 门禁误判；#6942 进一步定位为**确定性**（`ILLEGAL_STATE「今日发送次数已达上限」`，日上限 10 + 60s 防刷），旧 `smsLogin` 把发码失败当**硬门禁** ⇒ 单组跑登不进去（全量跑「正常」只是 `01-login` 先跑过的**顺序依赖**） | 发码失败只记不抛 + 逐旅程 `ensureLoggedIn` ⇒ 单组跑确定 |
| `27-corporate` / `28-register` | 「整轮预算 1500s 到点，未跑」 | `27-corporate` **不存在**（实际名 `27-corporate-home`，单跑 ✅）；`28-register` 是 `ALL_JOURNEY_NAMES` 里的**幽灵名**（实际名 `31-register`，本轮全量里就 ✅）⇒ `--group 28` 匹配不到任何旅程（0 pass / 0 fail / 29 skip） | 台账与实际名对齐 + **双向守卫**（§11.1 #6942） |

顺带查明的**产品侧**事实（不是本轮修复项，已开单/登记）：
- `DELETE /api/admin/products/{id}` 对 `on_sale` 必 **422**（「请先下架后再删除」），而 `draft → off_sale` 本身非法（「状态流转无效…允许的目标状态: 审核中/出售中」）
  ⇒ 旧 `cleanupProduct` **一件都没删掉**，残留商品正是 issue ① 那个 `404 /api/admin/products/<id>` 的**来源**（链条已在 #6942 打通并修好清理路径）。
- `performance.measure` 负区间在 `ProcessingRedirectPage` **复发**（#6799 ② 修过的错；`ui_smoke_known_console.json` 口径写明「再出现即真失败」）⇒ 开 **#6946**（本轮 12 轮复跑里出现 **1** 次，附复现要求）。

### 11.3 主会话的**复核订正**（铁律 11「转述即未核实」——两次都是我自己踩）

1. **#6945 两条红的归因**：我按「同名 check」推断成 drift-audit ⇒ 错，实际是两条 helper 判据（见 §11.1 说明）。
2. **#6937 的 `exit 3` 红证**：我上一轮报「未能复现（得到 exit 1）」⇒ **是我的注入方式不对**（同时注入了无效的 A）。
   重测：`TENANT_A=32 + TENANT_B=99998` ⇒ **`exit=3`** + 「对照租户 B（注入的 99998 登录失败 ⇒ 不可用）无对象可打」，读数 `pass=38 fail=0 skip=50 total=88`；
   注入一行写死手机号 ⇒ `exit=3` + 逐字 `sweep.mjs :: phone-literal → const HARDCODED_PHONE = "13800138000"`（跑完已还原，工作树 0 改动）。
   **结论更正为「复现成立」**。
3. `acceptance/2026-10-14/line3-aftersales-race/**` 在 **22:13** 被 #6937 的执行者观察到「被别的进程删除」——那是**我自己**在做收口时
   `git checkout main`（当时 main 尚未含 #6927）的**瞬态**；22:16 快进到含该 PR 的 main 后**已自动恢复**，现取 `REPORT.md` 与探针脚本都在。

### 11.4 残留与终态（收口时现取）

- `tenants` = **1 行**（只剩 `32 米高测试环境`）；#6937 自造的对照租户 **35 / 36** 已由该包**自清到 0**（逐表现取）。
- tenant 32 内：`orders` **141** / `products` **44**（命名含「冒烟/验收」**35** 件）/ `product_skus` **33** /
  `processing_items(active)` **0** / `processing_categories(active)` **0** —— 均为**该租户自身的测试数据**
  （该租户就是下一轮的起点）；清空口径见 §8 的 `wipe-tenants.py`。
- 清理链修正后（§11.2），后续旅程自造的商品会被**真正删掉**（先下架 → DELETE → `GET == 404` 收口）：#6942 已用它清掉 **10 件**遗留商品（24 → 14）。

### 11.5 收口时点（2026-10-15 00:3x +08）

- **七个修复包全部合并**（最后一包 #6947 于 **00:31:35 +08** 落地；mergedAt `16:31:35Z`），对应 issue **#6926 / #6928 / #6936 / #6937 / #6938 / #6940 / #6942 全部 CLOSED**。
- 新建但**未在本轮修复**的产品缺陷候选：**#6946**（`performance.measure` 负区间复发）；待裁定：**#6934**（D1 涉钱）/ **#6935**（D2 契约）。
- 独立复核（本会话）：① 七个包逐个做 **main 侧内容级自证**（`git show origin/main:<path>`，读点见 §11.1）；② **#6936 的判据在合并后的 main 上独立复跑** `Tests run: 5, Failures: 0`；③ **#6937 的两条注入式红证独立复现**（§11.1）；④ **最终 main 上重跑 UI**：
  `--group 1`（10~19）**10/10 通过、0 失败**（`out-r2-final-1/`）；`--group 12` 单跑 **✅ 1/32 通过、0 失败**（`out-r2-final-12/`）
  —— 这一轮同时**独立验证了 #6942 删掉 `loginWindow` 冗余机制后没有退化**（`spec.mjs` 现取 `loginWindow` 命中 = 0，而 10-/12- 仍绿）。
  ⚠️ 口径提醒：本轮旅程总数从 34 → **35**（`--group 1` 的 skip 记数随之变化），因为 #6942 把企业基础设置那几条**拆成独立旅程名**（`27-corporate-home` … `31-register`）——**「没跑」照样长得像「没跑」**，不折算 pass。
- 门禁（最终 main）：`check-ui-regression.sh` ✅ ｜ `contract-check.sh` ✅ 6/6 ｜ `plaintext_credential_guard.py` ✅ 零命中（5421 文件）｜ `verify-all.sh gate` 读数见 §6 的追加行。

