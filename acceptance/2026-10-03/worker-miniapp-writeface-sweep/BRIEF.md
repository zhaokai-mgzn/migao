# 线A 任务书 · 工人端 + 小程序写面 sweep（2026-10-03 第三轮）

> 本文件是**执行规格的承载体**（铁律 12(d)：规格不得只活在会话上下文里）。
> 执行者 = 后台验收子代理（本包）。主会话只做集成与独立复核。

## 0. 为什么是这一块

前两轮已覆盖：41 路由全页面 / RBAC / 库存工艺 / 单据逐项 / 派工×工序×路线 / 配置写面 / 计件量价 / 跨租户隔离 /
发货仓储 / AI Agent 服务域 / 批量导入导出 / 财务与库存下游。
**从未被系统探过、且是真实生产写路径**的两块 = **工人端（worker-h5）写面** + **小程序（bmini-app）写面**。
它们是"车间里真正在点的按钮"：报工完工、入库过账、打标打印、派工、发货 —— 写错了直接改生产数据。

## 1. 被测对象与环境（**先钉事实**）

| 项 | 值 |
|---|---|
| 被测构建点 | `main-live` 工作树检出 **`43ca70322`**（= 准备时刻的 `origin/main`）；源码引用一律 `git -C /Users/guangzhen.zk/migao-wt/main-live show HEAD:<path>`，**禁读主检出工作树**（主检出不等于被测构建） |
| admin-api | `http://127.0.0.1:8080`（重启于 2026-10-03 16:15 +08，见 `acceptance/2026-10-03/env/env-round3.json`） |
| worker-h5 | `http://127.0.0.1:3100`（`main-live/frontend/worker-h5` 静态服务，`/index.html`、`/machine.html`） |
| ai-agent-service | `http://127.0.0.1:8001` |
| DB | 云 dev RDS（连接参数从 `backend/admin-api/.env` 读，见共享 lib 的 `psql()`） |
| 被测租户 | `tenant_id=20`（米高POC演示布艺）；管理员手机 `13870217889`，短信万能码 `123456` |
| 探针命名域 | 名称前缀 **`线A验收`**；自建行 id 前缀 **`la`** |

## 2. 射程（要测什么）

### A1 工人端 H5 写面（`/api/worker/**`）

写端点（源码 = `backend/admin-api/src/main/java/com/migao/admin/controller/Worker*.java`）：
- `POST /api/worker/login`、`POST /api/worker/session/switch`、`/session/logout`、`/session/current`
- `GET /api/worker/me`、`GET /api/worker/production/current-worker`
- `GET /api/worker/production/scan?code=…` → **`POST /api/worker/production/scan/complete`**（扫码报工/完工：**本线最重要写路径**）
- `GET /api/worker/production/cutting-height`、`POST /api/worker/production/orders/{orderId}/operations/{operationId}/report`
- `POST /api/worker/shipment/recognize`、`POST /api/worker/shipment/orders/{orderId}/pack|ship|unpack`

必测维度（每条都要 L1 判据 + 红证）：
1. **鉴权与身份**：无 token / 过期 / 伪造 worker token / 会话 switch 后旧 token 是否失效；
2. **租户隔离**：租户 20 的工人操作租户 21 的对象 ⇒ 必须 4xx/0 命中（**不得**靠前端）；
3. **状态机**：未取件直接完工、重复完工、非法工序、超量报工 —— 各给期望（合法/拒绝）并独立从 DB 验证终态；
4. **幂等 / 重复提交**：同一 `scan` 或同一 `complete` 重复发（含 `X-Client-Request-Id`）⇒ 断言"恰好一行"或如实登记无幂等；
5. **数据落库正确性**：`production_work_logs`（或实际表）行数/数量/工人绑定/时间戳与请求一致（期望本包独立算出，**禁用被测读面当期望**）；
6. **UI 级**（可行则做）：worker-h5 页面在真实登录下的可操作性（若用 Playwright/无头浏览器，需登记工具与截图路径；不可行则**如实登记未覆盖**，不得用"页面能打开"冒充写面验证）。

### A2 小程序（bmini-app）写面

入口（源码 = `frontend/bmini-app/src/**`）：
- 登录链路：`POST /api/auth/mini/login`、`/api/auth/employee/login`、`/api/auth/sms/send|login`、`/api/auth/password/change`
- 入库写面：`POST /api/worker/inbound/recognize|upload|drafts`、`POST /api/worker/inbound/drafts/{id}/post`、`POST /api/worker/inbound/labels/{shortCode}/print`
- 生产写面：`POST /api/admin/production/pool/preview|dispatch`、`POST /api/admin/production/orders/{id}/ship`
- 售后 / 会话写面：`PUT /api/admin/after-sales/{id}/status`、`POST /api/admin/agent-sessions/{id}/assign|end`
  （⚠️ 线B 同时覆盖售后 —— **本线只碰"状态更新端点的输入校验与权限"这一小面**，闭环与并发归线B，避免重复与抢写）
- 只读面（作对照，不作主目标）：`/api/admin/production/pool`、`/api/chat/sessions*`、`/api/admin/dashboard/stats`

必测维度：写面契约（成功 + 至少一类**会拒绝**的负例）· 权限码（RBAC：缺权限必须 403）· 跨租户 · 幂等键（有则验、无则登记）· 并发（同一 draft 并发 post、同一工序并发派工**归线B**，本线只做简单重复提交）。

> ⛔ **明确不做**：真实 LLM 调用/评测（用户 #4262）；微信开发者工具 UI（`:21161` 未监听，需人工开模拟器 ⇒ 若确实必要，登记为**未覆盖**而不是绕过）；跑 `verify-all.sh gate/full`、`batch-gate`、全量 pytest（机器级重活锁）。

## 3. 纪律（违反任一条 = 本线读数不可引用）

1. **不自我验收**：本包只产**读数 + 判定 + 证据**，**不得**写"验收通过/交付完成"；
2. **可执行断言 + 红证**：每条关键断言必须给一条负向夹具（把行为改坏 / 喂错误轨迹 ⇒ **必红**），红证要有实跑读数；
3. **判定必须引证据**：`R轮次 / 请求响应原文 / DB 读数 / 源码符号`（文件的**仓库相对全路径 + 符号名**，**不写行号**）；
4. **四态分列**：`pass` / `fail(产品)` / `假红(判据缺陷)` / `skip(未覆盖 —— 永不记 pass)`；三态不许含糊；
5. **零残留**：探针对象用后自清，终态逐表计数 = 0（带一条注入→删除的红证）；存量行零改动（sha256 前后对照）；
6. **跨包隔离**：与线B 同租户并发 ⇒ 探针对象自建、短写窗口逐条还原、**归因按行内容**（不是自己的行 ⇒ 记 `skip` 并先还原再重跑）；
7. **时间口径**：一律 +08；复用共享 lib 的 `nowCST()`（**已修** Intl 版，禁 `getTimezoneOffset()` 叠加本地 getter 的写法）；
8. **不写仓内源码**：本包**不改任何产品源码 / 测试 / cases**，只写 `acceptance/2026-10-03/worker-miniapp-writeface-sweep/**`；
9. **发现即登记**：真缺陷写清"逐字读数 + 可复制最小复现 + 会红的判据 + 边界"，供主会话开单派包（**不要自己开 issue / 不提 PR**）。

## 4. 工具与复用

- 共享库：`acceptance/2026-10-03/batch-writeface-sweep/harness/lib.mjs`（`api()` / `loginApi()` / `psql()` / `guardedWrite()` → 写 SQL 必带 `-- probe-ok` / `assertProbe()` / `sha256()` / `nowCST()` / `tableSnap()`）。
  **复制一份到你自己的 `harness/lib.mjs` 再改**（不要跨目录 import 别人的包，避免互相影响）。
- 参考上轮同类包：`acceptance/2026-10-03/batch-writeface-sweep/harness/run-all.mjs`（结构：分组 → 判据 → 汇总 → `out/SUMMARY.json`）。
- worker-h5 前端源码：`main-live/frontend/worker-h5/src/*.mjs`（`api.mjs` 是端点清单）。

## 5. 交付物（缺一不算交付）

```
acceptance/2026-10-03/worker-miniapp-writeface-sweep/
├── REPORT.md          # 结论(不下"通过") / 读数汇总(四态) / 逐条判据与证据 / 红证 / 零残留 / 未覆盖清单
├── harness/
│   ├── lib.mjs
│   ├── p0-env.mjs     # 构建点自证 + 时钟自检（对 SQL now() at time zone 'Asia/Shanghai'）
│   ├── p1..pN.mjs     # 分组判据
│   └── run-all.mjs    # 一键重跑
└── out/               # 逐条 JSON + SUMMARY.json + run.log
```

`out/SUMMARY.json` 必须含：`buildPoint`（sha + 采集时刻 + 如何取证）、`counts{pass,fail,skip,falseRed}`、
逐条 `{id, group, verdict, evidence, redProof}`。
