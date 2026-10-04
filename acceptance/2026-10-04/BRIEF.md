# 2026-10-04 深度测试轮 · 任务书（三线：工人端/小程序 · 售后退款 · 并发竞态）

> 本文件是**执行规格的承载体**（铁律 12(d)：规格不得只活在会话上下文里）。
> 执行者 = 三线后台验收子代理；主会话只做集成与独立复核（不自我验收，铁律 1）。
> 时间口径：一律 **Asia/Shanghai（+08）**；引用 GitHub/CI（UTC）时间戳时逐处标注换算。

## 0. 为什么是这三块 / 为什么打部署面

- 2026-10-03 的同名三条 sweep 打的是**租户 20/1/21**，这三个租户连同全部数据已于 2026-10-04 08:31 清空；
  新测试租户 = **tenant 25「米高测试环境」**（空数据）⇒ 这三块在新租户上**从未被测过**，旧结论不可继承。
- **本地 :8080 不作被测对象**：它跑在 `main-live@43ca70322`，与 `origin/main` 在三块功能面上
  **差 75 文件 / 10147 insertions**（含 #6219 裁高修复、售后副作用并发台账、工序价格版本并发判据）
  ⇒ 拿它测会把**已修缺陷**当现状报出来（假红）。本线一律打**已部署面**。

## 1. 被测环境事实（**先钉事实，再看结论**）

| 项 | 值 | 复核命令 |
|---|---|---|
| 被测构建点 | **已部署 `ff655a06c`**（admin-api 部署于 2026-10-04 05:47 +08，ai-agent 于 07:13 +08） | `gh run list --workflow=deploy-admin-api.yml --limit 5 --json headSha,conclusion,createdAt` |
| 与 `origin/main` 的关系 | 差 **4 个提交，全部非业务**（#6290 冒烟配置 / #6286 flaky 台账 / #6281 CI 红证 / #6283 dep lock）⇒ **功能面等价** | `git diff --stat ff655a06c..origin/main -- backend/admin-api/src/main backend/ai-agent-service/app frontend/worker-h5 frontend/bmini-app frontend/mini-app`（空） |
| 部署在飞 | **无**（最后一个 deploy run 2026-10-04 08:30 +08 = `failure`，其后无 `in_progress`/`queued`） | `gh run list --workflow=deploy-admin-api.yml --limit 5 --json status,conclusion,createdAt` |
| admin-api | `https://api.migaozn.com` | 租户 25 管理员短信登录 200 |
| ai-agent | `https://ai-api.migaozn.com`（`/ready` = ready） | `curl -s https://ai-api.migaozn.com/ready` |
| admin-web / worker-h5 / bmini | `https://merchant.migaozn.com` · `https://app.migaozn.com/w/` · `https://app.migaozn.com/b/` | 各自可访问 |
| DB / Redis | 云 dev RDS `ai_customer_service` + `r-bp162…`（连接参数从 `backend/admin-api/.env` 读，harness 的 `psql()`/`redisGet()` 已内置） | — |
| **被测租户** | **tenant 25**「米高测试环境」，管理员手机 **13800138000**，短信万能码 **123456**，企业编码 `shop-8yn7` | — |
| 租户 25 基线 | users=1 · roles=7 · permissions=32 · production_operations=41 · production_route_rules=27 · products=0 · orders=0 · sessions=0 | psql 现取 |

## 2. 三线射程与目录

| 线 | 目录（产出落这里） | 复用底座（**不复制、不修改**，用 env 覆盖指向新环境） | 覆盖对象 |
|---|---|---|---|
| ① 工人端 + 小程序写面 | `acceptance/2026-10-04/worker-miniapp-sweep/` | `acceptance/2026-10-03/worker-miniapp-writeface-sweep/harness/`（p0→p6 + `run-all.mjs`） | `/api/worker/**` 全部写端点（登录/会话/扫码报工/入库/发货/标签）+ bmini/mini 写面与权限/租户/幂等/状态机 |
| ② 售后退款 | `acceptance/2026-10-04/aftersales-refund-sweep/` | `acceptance/2026-10-03/aftersales-concurrency-sweep/harness/`（p0→p10 + `run-all.mjs`） | 工单状态机 → 审核 → **退款（金额精度/负例/回补开关两侧）** → 财务与库存联动 → 并发完结/派工 |
| ③ 并发竞态 | `acceptance/2026-10-04/race-sweep/` | `acceptance/2026-10-03/tenant-concurrency-sweep/harness/`（probe*.mjs）**+ 自建**同资源竞态探针 | 同资源并发写（库存扣减/回补、工单完结、批次、派工、批量写）· 幂等键重复提交 · **跨租户 `TenantContext` 串号**（需第二个租户，见 §4.3） |

**启动口径（三线统一，逐字可复算）**：

```bash
cd "/Users/guangzhen.zk/ai native/migao"
API_BASE=https://api.migaozn.com AI_API_BASE=https://ai-api.migaozn.com \
TENANT_ID=25 ADMIN_PHONE=13800138000 SMS_CODE=123456 \
LIVE_WORKTREE=/Users/guangzhen.zk/migao-wt/main-live \
OUT_DIR="acceptance/2026-10-04/<线目录>/out" \
node acceptance/2026-10-03/<对应底座>/harness/run-all.mjs
```

> `LIVE_WORKTREE` 只用于 `buildPoint()` 记录**本地**构建点（要如实标注「本地旧构建点，非被测面」）；
> **读数一律取自 `API_BASE` 指向的已部署面**。harness 的 `psql()` 直连云 RDS —— 属预期（夹具与库侧判据）。

## 3. 纪律（违反任一条 = 本线读数不可引用）

1. **不自我验收**：本线只产**读数 + 判定 + 证据**，**不得**写「验收通过 / 交付完成 / 已达标」。
2. **四态口径**：`pass` / `fail(产品)` / `skip(未覆盖，不冒充已验)` / `假红(判据缺陷)`；**skip 永不折算成 pass**。
3. **每条关键判据要么有红证、要么有负对照**（故意写坏的期望必须红；把被测行为改坏必须红）。
4. **判定必须引证据**（`out/*.json` 的文件名 + 字段 + 原文片段）；**无引用 = 无判定**。
5. **归因强度必须匹配证据强度**：证据不足就写「证据不足 + 缺什么」，**不许编归因**，也不许一律甩给评测侧。
6. **写操作只碰探针对象**（`PROBE_PREFIX` 前缀 + `la`/`lb` id 前缀；harness 的 `guardedWrite` 会拒绝非探针对象）。
   不得改删非探针行、不得改产品代码、不得跑 `verify-all.sh gate`/全量 pytest（机器级重活锁）。
7. **不得调用真实 LLM 评测**（用户 #4262 裁定）。
8. **必须清理**：本线自建的探针数据在收尾时清理（`p9-cleanup.mjs`/`residue.mjs` 已有则复用），
   并在报告 `§残留` 给出**清理前后现取读数**。
9. **UI 级**：可行则做（Playwright/无头浏览器需登记工具与截图路径）；不可行**如实登记 skip**，
   不得用「页面能打开」冒充写面验证。

## 4. 三线各自的**前提**（本轮特有，必须处理）

### 4.1 线①：租户 25 是**空库** ⇒ 夹具链要自己从零搭
`harness/lib.mjs::pickOpTemplate()` 依赖**已存在的** `processing_position_operations` 实例（`set_id is not null`），
租户 25 一行都没有 ⇒ 直接跑会 `throw 找不到可参照的工序实例`。**必须先走真实 API 建出**：
商品（含 SKU）→ 下单 → 确认收款 → 生成加工单/工序实例（`/api/admin/production/**`），
并把这条链路本身作为**一条独立判据**（空租户首个订单的端到端可用性）。
夹具订单行**必须带真实 `product_id`**（否则会踩 #6219 那条已知缺陷路径，把别的判据染红 —— 那是**假红**）。

### 4.2 线②：退款判据的期望值由**本线独立算式**给出
金额/库存期望**不得**读被测读面（`HARNESS 纪律`）；回补开关两侧（`allow_return_restock` true/false）都要跑。

### 4.3 线③：跨租户并发需要一个**对照租户**（临时）
- 走**产品入驻流程**建一个临时租户（企业名 `米高测试环境-隔离对照`，管理员手机 **13800138001**，
  短信万能码 123456，行业「布艺纺织」）⇒ 记下它的 tenant id；
- 收尾时**必须清空该临时租户并删除其 `tenants` 行**（按 FK 拓扑序：子表优先，`users` 先于 `tenants`），
  留档现取读数（`select id,name from tenants` 必须**只剩 25**）；
- 若临时租户清理失败 ⇒ **必须在报告首行红字登记**，不得静默留下。

## 5. 产出物（每线）

- `out/*.json`（harness 原生产物，逐条判据）+ `out/run-all.log`；
- `REPORT.md`：一句话结论 / 套件四态汇总表 / 真缺陷清单（每条 = 最小复现 + 会红判据 + 根因符号/文件 + 五层归因）
  / 未覆盖清单（skip 及原因与重启条件）/ 残留清理读数 / **被测构建点与 SHA**；
- `out/SUMMARY.json`：机器可读汇总（`{line, buildpoint, counts:{pass,fail,skip,false_red}, findings:[...]}`）。

## 6. 明确不做

打印/标签硬件通道、微信开发者工具真机模拟器（未监听 ⇒ 登记 skip）、真实 LLM 评测、裁剪机等未落地模块、
`verify-all.sh gate`/`batch-gate`/全量 pytest。
