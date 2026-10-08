# 2026-10-04 深度测试轮 · 总报告（工人端/小程序 · 售后退款 · 并发竞态）

> **状态**：三线**执行中**（并发 3 条后台验收子代理，符合 §17 ≤3）。本文件的「结果」各节在集成时填写；
> **未填 ≠ 通过**。判定口径一律 `migao-acceptance`：四态 `pass / fail(产品) / skip(未覆盖) / 假红(判据缺陷)`，
> **skip 永不折算成 pass**，每条关键判据要么有红证要么有负对照，判定必须引证据。
> 时间口径：**Asia/Shanghai（+08）**；引用 GitHub/CI（UTC）时间戳处逐处换算标注。

---

## 0. 为什么是这三块

- 2026-10-03 的同名三条 sweep 打的是**租户 20 / 1 / 21** —— 这三个租户连同全部数据已于
  **2026-10-04 08:31 +08** 清空（任务书见 `BRIEF.md` §0）。新测试租户 = **tenant 25「米高测试环境」（空数据）**
  ⇒ 这三块在新租户上**从未被测过**，旧结论**不可继承**。
- 用户口径（2026-10-04）：「新租户创建出来后做这些功能的深度测试 —— 工人端/小程序、售后退款、并发竞态」。

## 0.1 🔴 坐标更正（本报告最重要的一行 · 2026-10-04 09:16 +08）

**三线读数的实际被测面不是台账声称的 `ff655a06c`，而是 `de614623d`（2026-10-02 10:22:50 UTC，落后 `origin/main` 152 个提交）。**

- 台账声称：`gh run list --workflow=deploy-admin-api.yml` 最近 `success` = `ff655a06c` @ 2026-10-03T21:47:10Z；
- 行为实测：集成侧独立复现「同工单并发状态流转」得 `[200,200,200,200]` + 副作用×4，
  而被测标签源码 `AfterSalesTicketService.updateTicketStatus` 含 #6220 原子条件更新（应得 `[200,409,409,409]`）⇒ **不相容**；
- 直接证据（部署步远端输出）：`PREV_GOOD_TAG=sha-de61462` + `❌ 磁盘可用 3998MB < 门槛 4096MB ⇒ 中止构建`；
- 机制（**durable 审计**见 `env/out/deploy-ledger-audit.json`，含命令）：最近 80 条 `deploy-admin-api.yml` run =
  **10 success / 69 failure / 1 cancelled**；其中 **8 条 success 的 `Deploy to SWAS` 步全部 = `skipped`**（部署步 `success` 计数 = **0**），
  另 2 条 success（`37167694309` 09:20、`37169621752` 09:58）**正是本轮我派发的那两次**、只有它们真的换了镜像 tag；
  抽样 20 条 failure 类 run 的该步**全部 = `failure`**。⇒ 在我派发之前，**run 的 `success` 从不构成「部署成功」证据**（skip 不判红 = 假绿）。

⇒ 已开 **#6294**（P0·部署），并按用户授权完成清盘与重发布（见 §3.5），环境已于 **09:30:44 +08 切到 `sha-6838a05`**。

**环境变更时间线（本轮内被测面发生过切换，必须记档）**：

| 时刻（+08） | 事件 | 证据 |
|---|---|---|
| 09:16:23 | 开 #6294（坐标问题） | `gh issue view 6294` |
| 09:20:10 | 用户授权后派发部署（`workflow_dispatch`，headSha=`6838a0533`） | `gh run view 37167694309` |
| 09:25:10 | **before 半场重放**（运行前后各取一次 tag、自证同刻未切换 = `sha-de61462`） | `env/out/replay-predeploy.json` + `env/out/buildpoint-selfcheck.json` |
| 09:30:44 | 部署落地：运行 tag = **`sha-6838a05`** | `replay-postdeploy/run.log` **第 2 行**；汇总见 `env/out/buildpoint-selfcheck.json` |
| 09:30:48–09:32:56 | **after 半场重放**（集成 R1–R4，11:33 又补 R5 + 线② 全档）；线①/③ 前置段补跑见 §2.5.3 | `replay-postdeploy/**` |

⇒ 因此本报告的环境事实表是 **as of 09:16 +08** 的快照，**不是**全轮恒定值；凡引用运行 tag 的读数都带各自时刻。
**本报告所有功能类 fail 只定性为「老构建 `de614623d` 上实测存在」，不得读成 main 的缺陷**；
三线报告均已按此口径改写（字段各异：线② `buildpoint.behaviorMeasured`、线① `actualDeployedHow`、线③ `deploy_leg`，三线正文均已点明 `de614623d`）。

## 1. 环境事实（先钉事实，再看结论）

| 项 | 值 | 复核命令 |
|---|---|---|
| 被测构建点（**行为实测**） | **`de614623d`**（落后 main 152 提交）—— 台账声称 `ff655a06c` 但部署腿从未成功，见 §0.1 / #6294 | `docker ps` 实测镜像 tag = `sha-de61462`；SWAS 云助手 `cat /opt/migao-deploy/.last-good-tag` |
| 与 `origin/main` 的关系 | 差 **4 个提交，全部非业务**（#6290/#6286/#6281/#6283）⇒ **功能面等价**（实测 diff 为空） | `git diff --stat ff655a06c..origin/main -- backend/admin-api/src/main backend/ai-agent-service/app frontend/worker-h5 frontend/bmini-app frontend/mini-app` |
| 部署在飞（协议 v1.9 前置） | **无**（最后 deploy run 2026-10-04 08:30 +08 = `failure`；其后无 `in_progress`/`queued`） | `gh run list --workflow=deploy-admin-api.yml --limit 5 --json status,conclusion,createdAt` |
| admin-api / ai-agent | `https://api.migaozn.com` · `https://ai-api.migaozn.com`（`/ready` = ready） | `curl -s https://ai-api.migaozn.com/ready` |
| DB / Redis | 云 dev RDS `ai_customer_service` + `r-bp162…`（`backend/admin-api/.env`） | — |
| **被测租户** | **tenant 25**「米高测试环境」· 管理员 **13800138000** · 万能码 **123456** · 编码 `shop-8yn7` | `POST /api/auth/sms/login` |
| 租户 25 基线（开跑前） | users=1 · roles=7 · permissions=32 · production_operations=41 · production_route_rules=27（**出处 `BRIEF.md:27`**）· products=0 · orders=0 · ops_instances=0 · tickets=0（**出处 `env/round-baseline.json`**，09:02:25 +08 现取） | 两处分别标注 |

**为什么不用本地 `:8080`**：它跑 `main-live@43ca70322`，与 `origin/main` 在这三块功能面上差
**75 文件 / 10147 insertions**（含 #6219 裁高修复、售后副作用并发台账、工序价格版本并发判据）
⇒ 拿它作被测对象会把**已修缺陷**报成现状（假红）。本轮的读数**一律取自已部署面**；
`LIVE_WORKTREE` 仅用于记录本地构建点，三线报告均已注明「读数不取自它」。

## 2. 三线射程与产物

| 线 | 目录 | 复用底座（未修改，仅 env 覆盖） | 覆盖对象 |
|---|---|---|---|
| ① 工人端 + 小程序写面 | `worker-miniapp-sweep/` | `acceptance/2026-10-03/worker-miniapp-writeface-sweep/harness/` | `/api/worker/**` 全写端点（身份/会话/扫码报工/入库/发货/标签）+ bmini/mini 写面（RBAC/租户/幂等/状态机） |
| ② 售后退款 | `aftersales-refund-sweep/` | `acceptance/2026-10-03/aftersales-concurrency-sweep/harness/` | 工单状态机 → 审核 → 退款（金额精度/负例/回补开关两侧）→ 财务与库存台账联动 → 并发完结/派工 |
| ③ 并发竞态 | `race-sweep/` | `acceptance/2026-10-03/tenant-concurrency-sweep/harness/` | 同资源并发写 · 幂等键 · **跨租户 `TenantContext` 串号**（临时对照租户，收尾清理） |

三线统一启动口径见 `BRIEF.md` §2（`API_BASE` / `TENANT_ID=25` / `ADMIN_PHONE=13800138000` / `OUT_DIR`）。

## 2.5 部署恢复与升级后重放（before/after 成对证据）

### 2.5.1 清盘（用户 2026-10-04 09:17 +08 授权）

| 动作 | 可用空间 | 说明 |
|---|---|---|
| 清盘前 | **4079MB（90%）** | 远端闸门：可用 < 4096MB 即中止构建 |
| `rm -rf /opt/migao`（2.2GB 陈旧克隆） | 6289MB | 远端输出自己列出的回收出口 |
| `docker builder prune -f --filter until=168h` | **+0B** | 9.6GB 构建缓存**全是近 7 天**（如实记录这次"无效动作"） |
| `docker builder prune -af`（缓存可重建、非回滚点） | **17410MB（55%）** | `Total: 13.63GB` |
| 保留集自证 | — | 4 个在跑容器仍 healthy、回滚点标签全在、`/api/health`=401 |

### 2.5.2 重发布与**成对重放**

重发布：`gh workflow run deploy-admin-api.yml --ref main` → run `37167694309` → **09:30:44 +08 运行 tag = `sha-6838a05`**。

**第三次部署（12:02 +08，为验证 #6302）**：`EFFECTIVE_TAG=admin-api:sha-3d64650`（= main `3d64650f1`）、admin-web `sha-ff41c40` ⇒ 其后 R5 复跑转绿（见 §3.3）。

**第二次部署（11:34–11:43 +08，为验证 #6294 的类级修复）**：run `37174436955`（真构建，自述 `ACR 里 sha-a9b423d 缺失 ⇒ 完整构建部署`）
→ 运行 tag **`sha-a9b423d` = `a9b423dec` = 当时 main HEAD**；随后同 sha 再派 run `37174810324` 走**跳过路径**，
**新断言步 `Assert running tag == target` 实跑并 success**（历史假绿形态 = 跳过 + run 报绿；现在多了一条对"运行 tag == 目标 tag"的机械判定）。
集成侧用自己的只读通道独立复探：`migao-deploy-admin-api-1|…admin-api:sha-a9b423d|Up 5 minutes (healthy)`、ai-agent/admin-web 仍在 `sha-4a24347`、
`/api/health → 401`；**与 CI 探测步读数两路一致**。明细见 #6294 的「合并后实地自证」评论。

| 判据 | before（`sha-de61462` = de614623d） | after（`sha-6838a05` = main） | 结论 |
|---|---|---|---|
| R2 同工单并发完结（#6220） | `[200,200,200,200]`、台账 4 行、库存 98→**106** | **`[200,409,409,409]`、台账 1 行、库存 98→100** | ✅ 修复生效 |
| R3 退款精度（#6228） | `0.001→200` 且 `refund_amount=0`（静默归零） | **`0.001→422`（库内不变）；`0.01→200` 逐字落库** | ✅ 修复生效 |
| R4 分页 `size<0`（#6222） | `200` + `total=0` + 仍回整页 | **`400` + 「分页参数不合法: size=-5 …」** | ✅ 修复生效 |
| R1 `.mjs` MIME（#6293） | `application/octet-stream`（白屏） | `application/octet-stream`（**仍红**） | ⛔ 修复包 PR #6298 未合并/未部署，预期仍红 |
| R5 超长 `skuCode`（#6302） | **`HTTP 500 INTERNAL_ERROR`**（skuCode.len=44，11:33 +08 实测） | **`HTTP 422`** + 「商品货号 skuCode 最长 30 个字符（库列 varchar(30)），当前 44 个字符…」（12:04 +08，env `sha-3d64650` = main `3d64650f1`） | ✅ **修复生效**（#6310 合并并部署后成对重放：`{pass:4,fail:1}` → **`{pass:5}`**；正对照成立） |

> R5 是 2026-10-04 11:33 +08 新增的重放项（同一载体 `env/postdeploy-replay.mjs`，用法同 R1–R4）。
> 它的 before 值顺带把「环境坐标」钉死了一次：**该次运行 R1–R4 全绿**（MIME/并发完结/退款精度/分页下限），
> 说明环境确实已含 #6220/#6228/#6222/#6293 四条修复，而 #6302 尚在 main 之外。

线②（售后退款）用**其自身 harness 原样重放**（同判据、同夹具）：**fail 8 → 2**，`pass 51 → 57`、`skip 3`、`假红 0`、零残留。
残留 2 条已定性：① `LB0-01` = **期望值过期伪影**（判据仍拿 BRIEF 的 `ff655a06c` 去比，台账现在已是 `6838a0533`）；
② `LB1-SETUP-category-gap` **仍红** ⇒ #6295 在 main 上确认仍开放。

### 2.5.3 线①/③ 的重放

两线的重放需要各自的前置段（线③ 先跑 `bootstrap.mjs` 建临时租户与夹具；线① 先跑 `bootstrap-chain` + `p1-auth`），
首轮只跑探针脚本会 `ENOENT fixtures.json` / `store 里没有 workerA`（已如实记录为**我脚本的编排缺陷**，非产品问题），
补跑结果见 `replay-postdeploy/1x-worker-full.log`、`3x-*.log`。

## 3. 结果（三线四态 + 升级后重放 + 独立复核）

### 3.1 四态计数（本轮读数 → 升级到 main 后重放）

| 线 | 被测面 | before（`de614623d`） | after（`sha-6838a05`） | after 残留项定性 |
|---|---|---|---|---|
| ① 工人端 + 小程序写面 | API + 部署面 UI | pass 98 / fail 2 / skip 2 / 假红 1 / 102 | **pass 87 / fail 2 / skip 3 / 假红 0 / 92** | 2 条 fail 是 **NPE 红证判别式"不再触发"**（N1/N5 的会红判据=「NULL ⇒ 500」，新构建得 200/200/200）⇒ **#6219 已随部署生效** |
| ② 售后退款 | API | pass 51 / fail 8 / skip 3 / 假红 0 / 62 | **pass 57 / fail 2 / skip 3 / 假红 0 / 62** | ① `LB0-01` = 期望值过期伪影（判据写死 `ff655a06c`）；② `LB1-SETUP-category-gap` 仍红 ⇒ **#6295 在 main 确认开放** |
| ③ 并发竞态 | API | pass 17 / fail 5 / skip 1 / 假红 4 | **pass 14 / fail 4 / skip 1**（probe-write 4/4、probe-idem 5/0+1skip、probe-cross 5/0） | F4 发货幂等**已修**；**F1/F2/F3 在 main 仍复现** ⇒ #6300 / **#6299** / #6301 |
| 集成侧重放 R1–R5 | 部署面 + API | R1/R2/R3/R4 **全红**（R5 于 11:33 新增记录 before=500） | R1 红 → 修复已部署后转绿（见 §3.4）、**R2/R3/R4 转绿**、R5 待四修复部署后复跑 | #6220 / #6228 / #6222 三条修复均**实测生效**；#6302 的 before 已固定 |

**重放口径（含缺席披露——复核指出首版把这句写宽了）**：三条线用各自 harness 重放（同判据、同夹具），不是我重写判据；日志 `replay-postdeploy/**`。
⚠️ **两段未随本次重放**，故 after 的 `total` 与 before **不可直接比**：
① 线① **P5 UI 级 10 条**（`replay-postdeploy/worker/SUMMARY.json` 的 `perSuite` 明标 `{"status":"MISSING","file":"P5-ui.json"}` ⇒ `102→92` 正是少这 10 条）；
② 线③ **probe-redproof 4 条**（判据自证段；重放目录只有 write/idem/cross 三段 ⇒ `23→19`）。
两段都属判据自证/UI 面，不影响各线产品结论，但必须按**缺席**读、不得当成「跑过且通过」。

⚠️ **`fail` 桶的纯度**（复核指出「四态」标签下会被粗读成还有 4 条产品缺陷）：after 的 4 条 fail 里，
**线① 的 2 条是「红证判别式过期红」**（N1/N5 的会红判据＝「置 NULL ⇒ 500」，而产品已修 #6219 ⇒ 实测 200，判别式不再触发）、
**线② 的 1 条 `LB0-01` 是判据侧期望值过期伪影** ⇒ **真正仍开放的产品缺陷只有 1 条：#6295**（详见 §3.8）。
线② 的 `LB0-01` 是**判据侧伪影**（本线 `p0-env.mjs` 写死 `EXPECTED='ff655a06c'`，台账变 `6838a0533` 即红）——**未改判据去凑绿**，只登记修法。

### 3.2 缺陷处置（本轮开单 / 修复）

| 单 | 级别 | 现状 |
|---|---|---|
| [#6293](https://github.com/zhaokai-mgzn/migao/issues/6293) `.mjs` MIME + 三条自检腿零 MIME 判据 | P1 | **修复包 PR #6298 已合并**（squash `4a243473d`）⇒ 触发部署腿 `37169621752`，落地后复验见 §3.4 |
| [#6294](https://github.com/zhaokai-mgzn/migao/issues/6294) 部署腿长期失败 | P0 | **已修**（运维半）：清盘 13.63GB + 重发布 ⇒ 环境到 main（`sha-6838a05`，读数见 §2.5） |
| #6294 的**判据半**：「`Deploy to SWAS` 被 skip」仍被算作 run success | P0 | ✅ **已修并合并**：PR [#6305](https://github.com/zhaokai-mgzn/migao/pull/6305) → `ff41c40ed`；main 侧内容级核对 = 新增 `deploy/scripts/swas_deploy_running_tag.sh`（255 行）+ 三条 deploy 腿接线 + 元守卫 `tests/unit_ci_workflows/test_deploy_skip_is_not_success.py` 均在 |
| [#6306](https://github.com/zhaokai-mgzn/migao/issues/6306) **工人端/一体机页仍整页白屏（第二因：`/shared/*.mjs` 未发布）** | **P1** | 开放（#6293 修复后由真浏览器实测发现；**修好 MIME 不等于页面可用**） |
| [#6303](https://github.com/zhaokai-mgzn/migao/issues/6303) 验收 harness 落盘活 token | P2 | 开放（本轮已脱敏，缺机制） |
| [#6295](https://github.com/zhaokai-mgzn/migao/issues/6295) 入驻不种商品分类 ⇒ 首建商品 422 | P2 | 开放（main 侧确认仍无分类种子） |
| [#6299](https://github.com/zhaokai-mgzn/migao/issues/6299) **并发确认收款超卖、静默钳 0** | **P1** | 开放（main 重放复现：`[200,200]`、10→0） |
| [#6300](https://github.com/zhaokai-mgzn/migao/issues/6300) 并发过账同 SKU ⇒ 台账 before/after 同基 | P2 | 开放（main 重放复现） |
| [#6301](https://github.com/zhaokai-mgzn/migao/issues/6301) 同 runId 并发盘点 ⇒ 5×500 | P2 | 开放（main 重放复现） |
| [#6302](https://github.com/zhaokai-mgzn/migao/issues/6302) 超长 `skuCode` ⇒ 500 | P3 | 开放（两个独立发现者命中；DTO 无长度准入） |

**已随升级自动消失（不必开单）**：#6220（售后并发副作用翻倍）、#6228（退款 0.001 静默归零）、#6222（`size<0` 返回整页）、#6219（裁高 NPE）——**四条都由本轮 before/after 成对读数证明**（§3.1 表 + §2.5.2）。

### 3.4 #6293 的闭环 —— **只对「MIME」这一条判据成立；对「页面可用」不成立（见 §3.4.1 自我否证）**

`PR #6298` 改 `deploy/swas/nginx.conf`＋三条 `deploy/scripts/*-verify-served.sh` 各补 MIME 判据＋类级元守卫
`tests/unit_ci_workflows/test_served_leg_mime_guard.py`（**13 个用例**，其中 **10 个**走注入/变异方向的红证）。**转述订正**：issue 说"四条腿"，
`origin/main` 现取**只有 3 条**（worker / bmini / c-end）——元守卫按**现取集合**判，将来新增第四条自动纳入。
**复验读数（2026-10-04 10:05:27 +08，运行 tag = `sha-4a24347`）**：

| URL | 修复前 | 修复后 |
|---|---|---|
| `/w/src/app.mjs` | `application/octet-stream`（整页白屏） | **`application/javascript`** |
| `/w/src/machine.mjs` | `application/octet-stream` | **`application/javascript`** |
| `/w/src/styles.css` | `text/css` | `text/css`（**邻居未被波及** —— 正是 `default_type` 而非 `types{}` 的改法所要保证的） |
| `/js/app.js`、`/b/js/app.js` | `application/javascript` | 不变 |

原始读数：`replay-postdeploy/60-mime-after-6293.log`。

### 3.4.1 🔴 自我否证（本报告最该看的一段）：页面**仍然白屏**，还有第二个独立缺陷

修好 MIME 之后我没有停在 curl 读数上，而是**用真浏览器又开了一次页面**（`replay-postdeploy/ui/UI-probe.json`，10:43:59 +08）：

| 时点 | `/w/src/app.mjs` MIME | 浏览器 console 逐字 | 页面 |
|---|---|---|---|
| #6293 修复前 | `application/octet-stream` | `… MIME type of "application/octet-stream"` | 白屏 |
| #6293 修复后 | **`application/javascript`** ✅ | `… MIME type of "text/html"` ← **另一条缺陷** | **仍白屏**（`bodyText=""`、`rootChildren=0`） |

**根因（已开 [#6306](https://github.com/zhaokai-mgzn/migao/issues/6306)，P1）**：
`render.mjs` 与 `machine.mjs` 静态 import `../../shared/operation-display.mjs` ⇒ 线上解析为站根 `/shared/operation-display.mjs`，
而**三条 H5 发布腿都不发布 `frontend/shared/**`** ⇒ 该路径 404 → nginx SPA 兜底 → 返回 `index.html`（`text/html`）→ 浏览器拒绝 module script。
引入于 `199cd2faa`（2026-09-21，#5002）⇒ 该页面白屏已 ≈13 天。传递闭包扫描（8 个模块、唯一坏点）落盘 `replay-postdeploy/ui/module-closure-scan.json`。

⇒ **教训（写进本轮方法）**：判据必须钉在**用户可观察的那一层**。"MIME 正确"是**手段**，"页面能渲染"才是目的；
只验手段就会得出「已闭环」的**假绿**。本轮因此把 #6293 的收口判据从「curl 的 Content-Type」升级为
「真浏览器 DOM + 依赖闭包」——后者立刻否证了前者。

### 3.6 独立复核（GLM-5.3-Flash 交叉验证 · 无参与执行）

用 `workflow` 工具派 **4 名 GLM-5.3-Flash 复核裁判**（`provider=scnet-token-plan`）：3 名各审一条线、1 名**对抗性**审集成侧承载体。
裁判被要求"只读、不得写文件/改环境/下验收结论"，且**只找问题**。结果：**4/4 全部给出 objection**（**判定项合计 19 条** = 线① 6 · 线② 3 · 线③ 2 · 集成 8；各线自登记的条目数见 `SUMMARY.reviewObjections` / `temp_tenant.objection_fixes`，计数口径不同不改判定），**全部成立并已逐条处置**：

| 对象 | objection | 处置 |
|---|---|---|
| 线① | 6 条（F3 叙事失真 / D21 skip 原因不符 / 出证后编辑 harness 未披露 / `buildPoint.how` 不可复现 / `Z-residue.at` 过期 / `C23b` 空转 pass） | 线① 逐条改准 + 新增 `reviewObjections[]` 留痕 |
| 线② | 3 条（表格 fail=4 笔误 / `SUMMARY.segments` 为 `{}` 的失效引用 / "未开 issue" 归属矛盾） | 线② 改准 + 新增 H8 自曝「该字段不作段执行证据」 |
| 线③ | 2 条（清理叙事与证据相抵：20 条 `blocked` 全是**列名错误**而非 FK 拒绝 / `usersDeleted=1` 引用不存在） | 线③ **修脚本谓词 + 扩扫描面**（补 `finance_transactions`/`processing_orders`/`inbound_labels`/`stock_batches`）+ 加 `--dry` 只读校验 |
| 集成侧 | 8 条（重放断言比 expect 声明窄 / `endpoint-inventory` 仍写"已部署面=ff655a06c" / README 未记环境切换 / 清理漏洞与扫描盲区 / 自检器字段族漏认 + 结构性盲区 / "近 80 条"口径 / 字段名以偏概全 / 悬空 §3.8 引用） | 见下 |

**集成侧 8 条的处置（本条最值钱：判据自己被别人打红过）**：
1. 重放脚本 4 条断言**收紧到与 expect 等宽**（R2 增"非赢家全 409 + 库存 98→100"、R3 增"库内不留痕"、R4 增"文案可行动"、残留面扩到双夹具/分类/工单）；
2. `verify-evidence.py`：**认全三线红证字段族**（线①`red_proof`/线②`willRed`/线③`would_red`+`discriminating_control`——首版漏认导致 4 条假红）、
   **新增 C4b 证据文件存在性**（只写路径 = 空断言）、并在文件头**如实登记 4 条已知盲区**（不校验正文与 counts 一致性等）；
3. 其**红证自检**也暴露了我自己的疏漏：C4b 一上线就把自检用的**虚拟样张**判红 ⇒ 修样张（这正证明 C4b 在起作用）；
4. `endpoint-inventory.md` 补坐标更正（清单来自台账声称的 `ff655a06c`，**不是**被测面，两者差 1106 个文件）；
5. **新增 C7：README §3.1 的四态数字必须与产物逐年对上**（①②取 `replay-postdeploy/*/SUMMARY.json`、③取三段 `probe-*-summary.json` 求和）。
   动机 = 复核反复抓到「手抄读数与 JSON 悄悄分家」；红证 = 真 README 上**逐个**把 87→187 / 57→157 / 14→114 注入，三处**各自判红**，还原即绿
   （`python3 verify-evidence.py` 现为 **7 条**判据，全部可机械复算）；
6. README 补**环境变更时间线**（现落在 **§0.1**）与**部署恢复与成对重放**（现落在 **§2.5**）——原文误写成「§0.2 / §3.5」，那是不存在的节号（复核指出我在自己的处置清单里制造了悬空引用）；另统一「近 80 条 run」口径（现引 `env/out/deploy-ledger-audit.json`）、字段名不写「三线统一」。

### 3.6.1 第三轮复核（针对最新结论的对抗性验证）

第一/二轮之后我又补做了三类结论，于是再派 **2 名 GLM-5.3-Flash 裁判**专打它们（#6306 的根因与修法、PR #6305 的类级修复、本报告 §3.1–§3.9 的一致性）。
结论：**根因与机制全部独立复核成立，同时给出 12 条 objection，已逐条处置**。

| 裁判 | 成立项 | objection | 处置 |
|---|---|---|---|
| #6306 根因/修法 | 5 项（`/shared/*.mjs` 现取 `200 text/html` 且与 SPA 兜底同长；两处 import 逐字在位；三腿都不铺 `frontend/shared/**`；引入时点 `199cd2faa` 成立并补正 `machine.mjs` 系 `f351cd1d6`/09-29；闭包工件与 issue 叙述一致；bmini/C 端无同族） | **1 high（修法不足）+ 4** | ✅ **已更正 issue #6306**：原修法按字面做**修不好白屏**（站根 `/shared/*.mjs` 无 `default_type` ⇒ octet-stream 直出）⇒ 改为**树内迁移** `frontend/worker-h5/src/shared/`；闭包判据措辞改为「每个 `*.html` 入口」∪「静态 `import` + `import(…)` 字面量」；补 `<link href>` 盲区 |
| PR #6305 + 本报告 | 10 项（skip 假绿的机械转换、fail-closed 三态、只读护栏、类级元守卫「现取集合」、`# case_ids: MC-080` 在场、部分交付诚实、§3.1/§3.4/§3.7/§3.4.1 数字与证据吻合） | 7 条（2 medium：本报告夸大 + 重放口径；1 medium：PR #6305 的密钥暴露面；4 low） | 本报告 5 处已修（#6294 拆半 / 重放缺席披露 / fail 桶纯度 / §3.9 重启条件 / §3.6 悬空引用）；PR #6305 的 2 条已作为评审意见提交该 PR |

⇒ 三轮累计 **8 名** GLM-5.3-Flash 裁判；第一轮 19 条、第二轮 4 条、第三轮 12 条 objection，**全部逐条处置或转成评审意见**。
本报告的价值有一半来自这些裁判——它们抓出过我**脚本里的 bug**、**过期的期望值**、**修法本身修不好问题**、以及**我自己写下的悬空引用**。

### 3.7 收尾残留（现取自证）

**durable 现取工件：`env/out/residue-final.json`（2026-10-04 10:34:49 +08）**

```
tenants                      → count=1, ids="25"          ← 只剩 25（26/27 隔离对照租户均已清）
业务面（tenant 25/26/27 合计）→ products=0 skus=0 orders=0 order_items=0 tickets=0 ticket_timeline=0
                               finance_transactions=0 stock_ledger_entries=0 processing_orders=0
                               inbound_orders=0 inbound_labels=0 stock_batches=0 client_request_keys=0
```

⚠️ **判据缺陷自曝**：三线自己的 `out/Z-residue.json` / `out/run.log` 里存在**非零**残留读数
（如售后线 `Z-residue.json` 09:19:32 的 `total=1`、重放收尾 09:32:56 的 `t25_products=5/orders=5/tickets=13`），
它们是**清盘前的中间态快照**，不是终态 —— 终态以上面的 `residue-final.json`（10:34:49）为准。
另外：本轮 `env/postdeploy-replay.sh` 里"线② 清理"一步的路径写错（指向本线 overlay 目录，实际文件在 2026-10-03 底座目录）
⇒ 该步 `MODULE_NOT_FOUND exit=1` 且**当时无人发现**（是第二轮独立复核抓出来的）——**已修**（改为底座路径 + 构建点读数落盘）。
清理方式：按 `information_schema` 的 **FK 拓扑序**（子表优先）对 65 张 `tenant_id` 表反复 pass 至收敛；
**保留**租户本体/账号/角色权限/岗位/工序-部位-路线种子（即 onboarding 配置面不受影响）。
清理脚本与读数：`env/`（本文档同目录）与三线各自的 `out/Z-residue.json`、`out/cleanup*.json`、`out/tenants-now.json`。


### 3.7.1 证据强度分级（L1 / L2 / UA，如实标注，不冒充）

| 层级 | 本轮覆盖面 | 说明 |
|---|---|---|
| **L1**（机器可判定读数） | **主体**：三线的 154 个端点覆盖面里，凡是断言都落到「HTTP 码 + 库内行/值 + 响应字段」的可复算读数 | 例：并发状态码分布、台账行数与 before/after、库存终值、退款金额列值、分页 `total` 与行数自洽性 |
| **L2**（证据引用） | 每条 fail 都带 `out/*.json::字段` 引用，且**集成侧新增 C4b：引用的文件必须真实存在** | 复核裁判按行抽核过（两轮），发现过 4 处「引用不存在/不可复现」并已修 |
| **UA**（AI 用户代理判定） | ✅ **已覆盖（两块 UI 面都做了真浏览器旅程）**：① **bmini `/b/`** 6/6（§3.7.2）；② **worker-h5 `/w/` + 一体机页** 9 pass + 1 条**设计上必红**的红证对照（§3.7.3：登录视图 / 错误 PIN 负对照 / 「当前工人」真 DOM / 扫码页 / **点「开 工」⇒ 网络 200 + DB 落 1 行** / 回执渲染 / 一体机屏显式报错） | 结论边界：worker-h5 的「页面能跑」是在 **#6306 修复并发布之后**（`sha-6f76212`）取到的；一体机屏那条记录的是**已知 #6219 行为**（显式报错而非静默假装成功），不算新缺陷 |

⇒ 本轮结论的强度上限是 **L1 + L2**；凡涉及"用户能不能用/好不好用"的判断，本报告一律不下结论。

### 3.7.1.1 线③ 端点级 after 读数（四个修复全部落地后 · 2026-10-04 12:59 +08）

坐标 `EFFECTIVE_TAG=admin-api:sha-843bed9`（= main `843bed933`）；载体 = 线③ `probe-write.mjs`，**显式传 `API_BASE=https://api.migaozn.com`**（见 §3.7.4 的教训）：
**`pass=8 fail=0 skip=0 total=8`**。

| 判据 | before | **after** |
|---|---|---|
| W3 净增量 + 台账链 | 净增量对，但台账**同基**、链断裂 1 处 | 台账 `["84.0→94.0","94.0→109.0"]`、**链 0 处不一致** |
| W3b 链首尾相接（#6300） | ❌ | ✅ |
| W4 并发确认收款不超卖（#6299） | ❌ `2/2` 成功、`10.0→0.0` | ✅ **`1/2` 成功、`10.0→2.0`**（扣减恰一次、不为负） |
| W5 同 runId 并发盘点（#6301） | ❌ `5xx×5` | ✅ `200 6/6、5xx 0`、分录 1 行、Δ 恰一次 |
| W7 洁净 SKU 收敛控 | ❌ 链不一致 | ✅ 链 0 处不一致 |

**如实登记（判据措辞 vs 实际门禁）**：W5 的文案写"其余回执 replayed"，但门禁实际只卡「**无 5xx** + 分录 1 行 + Δ 正确」；
"replayed 回执"的真门禁在 #6318 包的**端点级用例**（真 MockMvc + 真 PG）里，本探针不为其背书。

### 3.7.2 bmini 真实 UI 旅程（UA 层第一批实读数 · 2026-10-04 11:49 +08）

脚本 `env/ui/bmini-journey.mjs`（**只走真实表单，不注入 token、不改 localStorage**）；证据 `env/ui/bmini-journey.json` + `env/ui/shots/bmini-U*.png`。
环境：`https://app.migaozn.com/b/`，测试租户 25 管理员手机号（短信走测试通道）。

| 判据 | 期望 | 实测 | 结论 |
|---|---|---|---|
| U1 登录页 | 路由 `#/pages/auth/login/index` | 同左（2 个输入框 + 员工/管理员两个 tab） | ✅ |
| U2 切「管理员登录」 | 表单变「手机号 / 验证码」 | `["请输入管理员手机号","请输入验证码"]` | ✅ |
| U3 获取验证码 | 点后有**可见反馈** + 记原始状态码 | **`POST /api/auth/sms/send` = 200**，UI 出现「58s 后重发」倒计时 | ✅ |
| U4 登录 | 离开登录页 + `sms/login` = 200 + 首屏显示租户身份 | **`POST /api/auth/sms/login` = 200** → `#/pages/chat/index/index`，首屏「**米高测试环境 · 商家经营助手**」 | ✅ |
| U5 数据页 | 渲染真实业务读数 | `#/pages/dashboard/index/index`：「米高测试，今日生产概览 · 数据来自米宝 · 每 30 分钟自动刷新 / 今天没有待处理 / 在制工序进度 …」 | ✅ |
| U6 我的页 | 已登录身份 + 功能入口 | 「**米高测试 / 企业管理员 / 米高测试环境**」+ 扫码报工 / 拍照入库 / 补打入库标签 / 智能派单 / 入库过账 / 售后处理 / 计件工资报表 / 退出登录 | ✅ |

**诚实记录：我在这一轮里制造并修掉了两条判据侧假红**（都是判据错、不是产品错）：
1. 首版把「数据」页断言写成路由含 `/data/`，而真实路由是 `#/pages/dashboard/index` ⇒ **假红**；照读数改成 `dashboard` 后转绿（**判据要跟着真实对象走，不能按自己的想象写**）。
2. 首版点「获取验证码」用了 `div/span` 文本精确匹配，点到外层大容器 ⇒ 未真发短信、登录失败 ⇒ **假红**；改用 Playwright `getByText().last()` 定位最内层元素后转绿。
   另外连续重跑会撞**短信限流（`sms/send` 4xx）**，脚本已按真实用户行为「等窗口 + 重试一次」，并断言 UI 必须有可见反馈（倒计时或限流文案）——**"静默无反应"才是要判红的形态**。

**观察项（判据红不了 ⇒ 按纪律登记，不当缺陷）**：旅程中捕获 **1 条 console 错误**
`NotFoundError: Failed to execute 'insertBefore' on 'Node' …`（React/Taro 在路由切换时的 DOM 协调告警）；出现时页面全部正常渲染、无功能受阻 ⇒ 记为观察项，不作为缺陷。

**稳定性复跑（同输入第二次）**：12:08:53 +08 再跑一次 ⇒ **同样 6/6**；逐条判据 verdict 与首跑**完全一致**、`sms/send`+`sms/login` 均 200、console 错误同为 1 条 ⇒
**不是 flaky**（这次"同输入两次同结果"本身就是该旅程的可复演证据）。读数落盘 `env/ui/rerun/bmini-journey.json`（另含 `env/ui/bmini-journey.json` = 首跑）。

**残留自证（本轮所有实测跑完之后）**：`tenants` 只剩 25（`米高测试环境` / `shop-8yn7`）；租户 25 的
`products / product_skus / orders / order_items / after_sales_tickets / stock_ledger_entries / finance_transactions / categories` **全部 = 0**，
按名字扫探针前缀残留 **0**，`users` = 1（管理员）⇒ R1–R5 + bmini 旅程的自建对象都已被各自载体清干净。

**本节的边界**：这条结论**只覆盖 bmini**；worker-h5 `/w/` 与一体机页**仍未做 UA 判定**（整页白屏，见 §3.4.1 与 #6306），二者不可互相代表。

### 3.7.3 worker-h5 / 一体机屏真实 UI 旅程（UA 第二块 · #6306 修复后的成对读数）

**成对（同一判据、修复前后）**

| 判据 | before（`sha-4a24347` 时代，白屏） | **after（`sha-6f76212` = main `6f76212d3`）** |
|---|---|---|
| 部署面 R1 的**依赖闭包**项 | `/w/src/shared/operation-display.mjs` → **`200 text/html`**（SPA 兜底） | **`200 application/javascript`** ✅ |
| 真浏览器 `ui-probe.mjs` | 整页白屏（`body` 仅 423 字节、0 个 `#wh5-login`） | `HTTP 200` + `ids=["worker-h5-root","wh5-worker-no","wh5-pin","wh5-login"]`、**console 错 0** ✅ |
| line① `p5-ui` 段 | **缺席（perSuite MISSING，10 项跑不出来）** | **9 pass + 1 条设计必红**（42 秒走完） |

**`p5-ui` 逐条（真实 Playwright 驱动本地只读静态服务上的 worker-h5；读数不取自本地树）**

| 判据 | 实测 |
|---|---|
| U1 登录视图可见 | `#wh5-login` / `#wh5-worker-no` / `#wh5-pin` 渲染 ✅ |
| U2 **负对照** 错误 PIN | 停在登录视图 + `#wh5-error` 显示业务文案「工号或 PIN 不正确」✅ |
| U3 正确登录 ⇒ 真 DOM 出现身份 | `header="当前工人：线A验收工人870898（工号 LAA70898）"` ✅ |
| U3b UI 真拉服务端读面 | `GET /api/worker/production/current-worker` 200 ✅ |
| U4/U4a 扫码页 | 手输框默认空 + 点「扫码」⇒ 服务端解析并渲染「开 工」✅ |
| **U5 UI 点「开 工」** | 网络面 `POST /api/worker/production/scan/complete` **200**；DB 面 `work_logs 0→1`、工序 `done_qty 2.00` ✅ |
| U5b 回执渲染 | 页面显示「已领活/下一道/本套完成」类文案 ✅ |
| U7 一体机屏切高 | `GET …/cutting-height` 500（**已知 #6219 的形态**），但页面**显式报错**「服务器内部错误 请重新扫一次水洗唛」而非静默假装成功 ✅ |
| U6 **红证对照** | 把 U4 期望故意改坏 ⇒ 该判据**判红**（证明它不是空断言）——按设计**必须红**，不计产品缺陷 |

**边界（照实）**：① `p5-ui` 跑在**本地只读静态服务**（同一份 `frontend/worker-h5/**`，正确 JS MIME）上以隔离变量，**部署面本身**另由 R1 闭包项与 `ui-probe`（真 `https://app.migaozn.com/w/`）判定；② 该次运行的"存量 sha256 一致=false"是因为同段 `bootstrap-chain` **建了非探针的真实订单**（探针残留本身 = 0），不是脏数据。

### 3.7.4 本轮**我自己**的错判与更正（留痕 · 不掩盖）

| 我做了什么 | 实际是什么 | 更正 |
|---|---|---|
| 用线③ 探针手工复算 #6301，得"同 runId 6 并发仍 `5xx×5`"，据此按**缺陷**口径开了 **#6318** | 那两次探针**打的是本机 :8080 的陈旧实例**（`main-live` @ `43ca70322`，编译产物里 `ON CONFLICT` 计数 = 0），其 stdout **逐字含我两次探针的 runId**；根因是我**手工调用漏传 `API_BASE`**（载体脚本本身是对的） | **#6318 已撤回缺陷结论并就地重定性**为两个真实缺口（端点级并发判据缺失 / 500 日志面缺上下文），由 PR #6320 承担；#6301 的原子闸**在端点上生效**（修复构建 6/6 全 200、分录 1 行、库存 Δ-3；打陈旧实例仍 `1/6+5xx×5` ⇒ 判别性对照成立） |
| 在部署环境容器日志里没查到该 500 的 ERROR，写下"红了但查不到" | 请求**根本没到那个容器** —— 我看的不是承接请求的进程 | 已把"**打到哪个进程**"列为报红前置取证（pid + classpath + 产物 mtime + runId 日志命中行数），写进 `env/method-notes.md` **N10** |
| 同一轮还发现两条**工具口径差**：W5 读 `data.results[].status`（DTO 字段是 `lines`）、台账过滤拿 runId 匹配 `ref_no`（盘点行 `ref_no`=批次号） | 是**我的载体**口径差，不是产品缺陷 | 记入 N10 并在集成侧载体修；**判据要跟着真实对象走**（与 §3.7.2 的两条判据侧假红同一教训） |

**类级固化（就地做掉）**：`race-sweep/harness/lib.mjs` 的 `API_BASE || 'http://localhost:8080'` 改为 **fail-closed**
（不显式给 base 即 `exit 2`，仅 `ALLOW_LOCAL_API=1` 允许回落本机）——自证：不传 base 时探针拒绝执行并打印原因。

### 3.8 在 main 上仍然复现的真缺陷（逐条：最小复现 / 会红判据 / 根因符号 / 证据）

| 单 | 最小复现（可复制） | 会红判据 | 根因符号（`git show origin/main:<path>`） | 证据 |
|---|---|---|---|---|
| **#6299** 超卖 | 建 SKU(stock=10) → 两张各 8 米订单 → 同时 `PUT /orders/{id}/payment` | 恰一单成功 + 扣减恰一次 + 库存不为负（实测 `[200,200]`、10→0） | `ProductSkuMapper.deductStock` = `SET stock = GREATEST(stock-#{qty},0) WHERE id=#{skuId}`（**无 `stock>=qty` 谓词**） | `replay-postdeploy/race/probe-write-raw.json::W4`；顺序对照 422 |
| **#6300** 台账链 | 两张同 SKU 草稿入库单（10/15 米）同时 `PATCH …{action:post}` | `stock_ledger_entries` 的 before/after 必须链式相接（实测两行同基） | `InboundOrderService#post`：`beforeQty = sku.getStock()` 快照读 → `receiveStock` 原子加 → `record(beforeQty, afterQty)` 用陈旧值 | 同上 `::W3/W7` |
| **#6301** 盘点 500 | 同批次 + 同 `runId` 并发 6 次盘点 | 应恰一赢家 + 其余幂等回执 200（实测 `[200,500×5]`） | 非原子"先查后插" + 部分唯一索引 `uk_batch_consumption_stocktake` 的 `DuplicateKeyException` 未映射 | **两个构建点都红**：`race-sweep/out/probe-write-raw.json::W5`（旧）与 `replay-postdeploy/race/probe-write-raw.json::W5`（main，`[200,500×5]`）；顺序对照 `race-sweep/out/probe-redproof-raw.json::RP1` |
| **#6302** 超长 `skuCode` | `POST /api/admin/products`，`skuCode` 长 31（列 `varchar(30)`） | 应 4xx 可行动文案（实测 500 `INTERNAL_ERROR`） | `ProductCreateRequest.skuCode` 无长度准入（`@Size` 缺失） | 服务端栈 `value too long for type character varying(30)` @ `ProductMapper.insert` |
| **#6306** 白屏第二因 | `curl -sI https://app.migaozn.com/shared/operation-display.mjs` | 必须 `200` + JS MIME（实测 `200 text/html`）；页面必须能渲染（实测 `bodyText=""`） | `frontend/worker-h5/src/render.mjs` 与 `machine.mjs` 的 `../../shared/operation-display.mjs`；发布腿未铺 `frontend/shared/**` | `replay-postdeploy/ui/UI-probe.json`、`module-closure-scan.json` |
| **#6295** 开租无分类 | 新租户 `POST /api/admin/products`（`categoryId` 必填） | 开箱首建商品应可达（实测 422「分类ID不能为空」） | `RegistrationService` 开租只种角色/权限/岗位与生产种子，**未种商品分类** | `aftersales-refund-sweep/out/B1-category-gap.json` |

### 3.9 未覆盖清单（三线汇总 · **skip 永不折算 pass**）

| 未覆盖面 | 原因 | 重启条件 |
|---|---|---|
| ~~`/w/` 与一体机页的 UI 写面旅程~~ | ✅ **已于 2026-10-04 12:41 +08 补做并跑通**（#6306 修复 + 发布落地后，`p5-ui` 9 pass + 1 必红红证 ⇒ §3.7.3） | —（已覆盖） |
| ~~bmini `/b/` 完整 UI 旅程~~ | ✅ **已于 2026-10-04 11:49 +08 补做并全绿（6/6）** ⇒ 见 §3.7.2 | —（已覆盖；worker-h5 侧仍见上一行） |
| `mini/login` 成功链 | 需真微信 `code2session` | 拿到测试小程序凭据 |
| 跨租户**写**面（PUT/DELETE 对方对象） | 本轮只覆盖读面与伪造头 | 出现第二个有数据的租户 |
| 售后 **UI 级**写面 | 无头浏览器未登记 | 补 Playwright 走查 |
| 「服务端已落库但客户端超时」故障注入 | 无注入能力 | 引入故障注入通道 |
| 打印硬件通道 / N≫8 竞争强度 / 多实例脏部署干扰 | 环境不具备 | 专用环境 |
| 真实 LLM 评测 | **#4262**（不自动跑，需用户显式要求） | 用户显式要求 |

## 4. 独立复核（已完成 · 见 §3.6）


- 复核通道：`scnet-token-plan` / `GLM-5.3-Flash`（非 DeepSeek 系，见 `migao-acceptance`「复核裁判模型独立性」）；
- 复核只读 transcript 与 `out/*.json` 证据，**不看本任务书的 spec**（独立视角）；
- 另按协议 §2.2 要求：**复核本轮在租户 25 上留下的真实会话**（工人会话 / C 端会话的生命周期与卡片态）。

## 5. 残留与自证（已完成 · 见 §3.7）


- 租户 25 最终读数（`tenants` 必须只剩 25）；
- 临时对照租户（线③）建立与清理的前后读数；
- 三线探针数据清理前后读数。

## 6. 复算命令（逐条可复制）

```bash
# 0) 被测构建点（行为实测 vs 台账声称）
bash acceptance/2026-10-04/env/swas-run.sh "docker ps --format '{{.Image}}' | grep admin-api; cat /opt/migao-deploy/.last-good-tag"

# 1) 协议合规自检（含红证自检：故意违规样本必须判红）
python3 acceptance/2026-10-04/verify-evidence.py --selftest
python3 acceptance/2026-10-04/verify-evidence.py

# 2) 集成侧重放（R1–R5：MIME / 并发完结 / 退款精度 / 分页下限 / 超长入参）
PHASE=postdeploy OUT_DIR=acceptance/2026-10-04/env/out PROBE_PREFIX=ZR \
  API_BASE=https://api.migaozn.com TENANT_ID=25 ADMIN_PHONE=13800138000 SMS_CODE=123456 \
  node acceptance/2026-10-04/env/postdeploy-replay.mjs

# 3) 三线全档重放（用各线自己的 harness；先跑各线的前置段）
OUT_DIR=acceptance/2026-10-04/replay-postdeploy/aftersales node acceptance/2026-10-04/aftersales-refund-sweep/harness/run-all.mjs
OUT_DIR=acceptance/2026-10-04/replay-postdeploy/race node acceptance/2026-10-04/race-sweep/harness/bootstrap.mjs
OUT_DIR=acceptance/2026-10-04/replay-postdeploy/worker node acceptance/2026-10-04/worker-miniapp-sweep/harness/run-all.mjs

# 4) #6293 的现场判据（修复部署后应得 application/javascript）
curl -sI https://app.migaozn.com/w/src/app.mjs | grep -i content-type

# 5) 收尾残留（应只见 25）
psql -c "select id,name from tenants; select count(*) from products where tenant_id=25;"
```
