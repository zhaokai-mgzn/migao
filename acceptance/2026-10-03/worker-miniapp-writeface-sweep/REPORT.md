# 线A 验收包 · 工人端（worker-h5）+ 小程序（bmini-app / mini-app）写面 sweep

- **执行者**：线A 验收子代理（worker-h5 + mini-app 写面 sweep）
- **构建点**：`/Users/guangzhen.zk/migao-wt/main-live` @ `43ca70322`（= `origin/main`，`43ca703221a714e143c468ff0b29c4a46e67a88f`）
- **被测服务**：admin-api `:8080`（pid 61739，启动 2026-10-03 16:22:58 +08）、worker-h5 静态 `:3100`（另有测试用只读静态服务 `:3160`）、ai-agent-service `:8001`、共享云 dev RDS 租户 20
- **观测窗口**：2026-10-03 16:22 ~ 17:05（+08）；本报告读数以 `out/SUMMARY.json` 为准
- **四态口径**：`pass` / `fail(产品)` / `skip(未覆盖，不冒充已验)` / `假红(判据缺陷，含故意失效控制项)`；**skip 永不折算成 pass**
- **不自我验收声明**：本包**只产读数 + 判定 + 证据**，不下「验收通过 / 评测 OK / 交付完成」类结论（铁律 2）。所有关键判据都配红证或负对照。

---

## §1 一句话结论 + 读数汇总

**一句话**：工人端与小程序写面的**核心写路径（扫码开工 → 落 `production_work_logs`）在 API 与真实 UI 两侧都被证明可用且幂等、租户隔离成立**；但**一体机裁高屏在「订单行 `product_id` 为空」时返回 HTTP 500**（用户可见面为「服务器内部错误」大字），已开 **#6219**，为本包唯一 `fail(产品)`。

| 套件 | pass | fail(产品) | skip(未覆盖) | 假红(判据缺陷) | total |
|---|---|---|---|---|---|
| P1 工人身份面（登录/会话/切换/登出/枚举/越权） | 16 | 0 | 0 | 0 | 16 |
| P2 扫码闭环（A1 核心写路径 + 幂等 + 状态机） | 24 | 0 | 1 | 0 | 25 |
| P2b 裁高 NPE 复现 + 单变量红证 | 4 | **1** | 0 | 0 | 5 |
| P3 小程序入库写面（识别/草稿/过账/标签） | 18 | 0 | 1 | 0 | 19 |
| P4 小程序其余写面 + C 端图片上传 | 20 | 0 | 0 | 0 | 20 |
| P5 UI 级（真机驱动 worker-h5 手机页 + 一体机页） | 9 | 0 | 0 | **1**（U6 故意失效控制项） | 10 |
| **合计** | **91** | **1** | **2** | **1** | **95** |

注脚（口径对齐，避免误读）：
- `fail(产品)` 唯一一条 = `N1.cutting-height-null-product`（= **#6219**，修复包在飞；它与 `P2b` 的 N5 三步单变量、`P5` 的 `U7` 是同一条缺陷的 **API 面 + UI 面**双侧证据）。
- `假红` 唯一一条 = `U6.redproof`：**故意写坏的期望**（要求扫码前输入框等于某个不存在的 token）⇒ 按设计必须红；它是"判据不是空断言"的**失效控制项**，不是产品缺陷。
- `skip` 两条 = `C17.cross-tenant-object`、`D21.cross-tenant-label`：租户 21 无「码 + 待做工序」夹具 / 无标签短码夹具 ⇒ **未覆盖**（跨租户读面本包已用"服务端零写入"侧证，见 §5）。

---

## §2 真缺陷清单（含最小复现 + 会红的判据 + 根因符号）

### D-A【P2 级 · 产品缺陷 · #6219】一体机裁高屏：订单行 `product_id` 为空 ⇒ 裁高读面 500，车间屏只有「服务器内部错误」

- **逐字读数（API 面，`out/P2b-cuttingheight-npe.json` / `N1`）**：同一短码、同一 session，
  `product_id` 有值 ⇒ `HTTP 200`；`product_id` 置 `NULL` ⇒ `HTTP 500 {"code":"INTERNAL_ERROR"}`。
- **单变量红证（`N5`，三步对照，只改一个自变量）**：`有 product_id = 200` → `置 NULL = 500` → `还原 = 200`。
- **逐字读数（UI 面，`out/P5-ui.json` / `U7`）**：一体机屏 `machine.html` 扫同一短码 ⇒ 网络面
  `GET /api/worker/production/cutting-height ⇒ 500`，页面可见文本：`机台模式 · 裁高 … 服务器内部错误 请重新扫一次水洗唛（或手工输入短码）`（截图 `out/shots/U7-machine-null-product.png`）。⇒ 用户可见面**是显式失败大字**（不是空值静默），但**车间无法作业**。
- **根因符号**：`backend/admin-api/src/main/java/com/migao/admin/service/WorkerCuttingHeightService.java` 的 `positionRow` ——
  `row.put("brand", item == null ? null : brands.get(item.getProductId()));`
  当批次内**没有任何订单行带非空 `product_id`** 时 `brands()` 返回 `Map.of()`（不可变空 Map），
  `item.getProductId()` 为 `null` ⇒ `ImmutableCollections$MapN.get(null)` 抛 NPE（`Map.of().get(null)` / `Map.of(k,v).get(null)` 均 NPE；`LinkedHashMap.get(null)` 返回 null ⇒ 只有 `brands()` 这条分支会炸）。
- **最小复现（零依赖，可复算）**：
  1. 造一张加工单 + 部位级短码（`la` 命名域夹具）；
  2. `update order_items set product_id = null where id = '<该订单行>'`；
  3. 工人登录拿 `X-Worker-Session-Id`；
  4. `GET /api/worker/production/cutting-height?token=<短码>` ⇒ **500 INTERNAL_ERROR**；把 `product_id` 还原 ⇒ **200**。
- **会红的判据**：`cutting-height 不得返回 5xx；缺值必须走 `missing[]` / 页面「—」这类显式降级`。判据为红的条件已被三步对照证明（`N5`）。
- **处置**：已由主会话开 **#6219**（修复包在飞）；**本包不修产品代码**（铁律）。

### D-B【P3 级 · 待裁定 · 契约与实现不一致】入库识别端点「条码优先、零 LLM」的省流路径**从工人端点不可达**

- **逐字读数（`out/P3-inbound.json` / `D1`）**：只给 `barcode`（不给图片）⇒
  `HTTP 400 {"code":"INBOUND_RECOGNIZE_NO_IMAGE","message":"请至少上传 1 张照片（上游标签 / 布卷包装）"}`。
- **源码顺序**：`WorkerInboundService.recognize` 里图片校验（`validImages`）在 `if (barcode != null)` 分支**之前** ⇒
  类注释声称的「前端已解码 ⇒ 走 `PATH_BARCODE`，**一次 LLM 都不调**」这条路径，**必须同时带图才可达**。
- **影响面**：工人端/小程序若照注释只传 `barcode` 想省一次 vision 调用，会直接 400（不是"省一次"而是"整次失败"）。
- **会红的判据**：`barcode 非空 ⇒ 走 barcode_decode 且 0 次模型调用`（判据红 = 本条缺陷成立；本包因不触真实模型只走到"拒绝"这一层，未采信任何 LLM 读数）。
- **处置建议**：要么把注释改成与实现一致（"必须带图"），要么把 barcode 分支提到图片校验之前；**本包不改代码，登记待裁定**。

---

## §3 假红与自身 harness 缺陷（自曝，全部已改判/已修）

| # | 位置 | 现象（逐字） | 性质 | 处置 |
|---|---|---|---|---|
| 1 | `P2/C23` | 用 `status >= 400` 判"可接受" ⇒ **把 500 记成 pass**（假绿） | 判据缺陷（吞 5xx） | 改三态：200 且带字段=pass｜4xx=可接受｜**5xx=fail** |
| 2 | `P3/D6` | `期望 undefined == undefined ⇒ pass`（`stock` 没取到值） | 判据缺陷（fail-open） | `lib.mjs::judge` 加 **fail-closed 守卫**：`undefined/null/NaN/空串` 一律不许判 pass（可空必须显式声明）；`D6` 复读 `100.0 == 100.0` |
| 3 | `P3/D8` | `409` 是真读数，但"库存不变"那半是 `stock=undefined` | 判据缺陷（半个空断言） | 同上守卫 + 补真读 `stock=100.0` |
| 4 | `P3/D5·D7` | 成片 `HTTP 400 BAD_REQUEST` | **夹具错**，非产品 | 两个真因：① `skuId` 精度（`product_skus.id` 是 bigint > 2^53，走 `Number()`/`JSON.parse` 会静默改值 ⇒ 服务端报"SKU 不属于该商品"）；② 预序列化 body 被**二次 stringify** ⇒ `Cannot construct instance … from String value`；另 `raw` 请求缺 `Content-Type` ⇒ 415。修法：psql 取 `id::text`、**数字字面量拼串** + `rawWorker()` 自带 `application/json` |
| 5 | `P3/D13` | 我写"必须 422"，实测工人面 **400** | 判据缺陷（期待过窄）× **两层状态码口径** | 收敛为 **4xx**，证据里同时登记两侧：Service 层=422（`BusinessException.validationError`）、工人面端点=400（`WorkerInboundService.asCarrierBadRequest` 类注释逐字「参数类拒绝从 422 改写成 400」） |
| 6 | `P4/E6` | ① "三个发货端点必须全 4xx"；② "`packed_at` 必须非空" | 判据过严（两次） | ① 判据是**订单**状态，`confirmed` 是合法起点；② `unpack` 把 `packed → producing` 时会**清掉**打包标记 ⇒ 终态读 `packed=false` 正常。改为断言"订单离开起始态 + `order_shipments.source='worker'` + `ship` 4xx" |
| 7 | `P4/E14~E18` | 我按源码 docstring 打 `POST /upload-image` 与 `/api/upload-image` ⇒ **404** | 夹具错（路径） | 实跑路由 = `openapi.json` 的 **`/api/chat/upload-image`**（`routes.py` 挂 `/chat` + `main.py` 挂 `API_PREFIX=/api`）；登记为观察项（§4-1） |
| 8 | `P4/E14~E20` | 页面/装置跨源 ⇒ `OPTIONS` 预检 **403**（`CORS_ALLOWED_ORIGINS` 只放行 `localhost:3000/3001`） | 装置缺陷 | Playwright `page.route(...).fulfill()` **Node 侧代理**（浏览器看到同源响应），**原样转发状态码**（500/401 不被改写） |
| 9 | `P5/U4` | 断言"带 token 进页面 ⇒ 输入框回填码值" | 我**造了一个不存在的功能** | 手机页无 token 深链（只从 URL 读 `tenant_id`）；`#wh5-report` **只在扫码成功后**渲染 ⇒ 拆成 `U4a`（扫码前：输入框存在且为空）+ `U4`（点 `#wh5-scan` 后出现开工按钮） |
| 10 | `P5/U7` | 用 `locator.fill` 驱动一体机屏 ⇒ 超时 | 装置缺陷 | 一体机屏**无 input**，吃的是**全页 keydown 扫码缓冲**（`machine-app.mjs::doc.addEventListener('keydown')`）⇒ 改 `page.keyboard.type(token)` + `Enter` |
| 11 | `P5/U6` | 红证的期望值写成 `undefined`（沿用已删除的变量） | 装置缺陷 | 改用**扫码前**读数 `codeBefore === "<token>-BROKEN"` ⇒ 稳定必红（现为唯一 `假红` 条目，属故意控制项） |
| 12 | `run-all` 存量指纹 | 首版用**全表**指纹 ⇒ 清理自己的探针行后必然"不一致"（`orders 411→366`） | 判据口径缺陷 | 改 `excludeProbe` 口径（排除 `la` 命名域）+ 逐表 probe/existing 分列（`p6-baseline.mjs`）；并引入**方向语义**判定（只增不减=并行包写入） |
| 13 | `run-all`/`p6` | `coalesce(id,'')` 在 bigint 主键上报 `invalid input syntax for type bigint` | 装置缺陷 | 改 `coalesce(id::text,'')` |

---

## §4 观察项（判据"红不了"，只登记，不判产品缺陷）

1. **上传接口文档路径 ≠ 实际挂载**：`app/api/upload.py` 模块 docstring 写 `POST /upload-image`，实际是 `/api/chat/upload-image`；文档路径实测 404。客户端照 docstring 拼路径会 404（`mini-app` 前端用的是实际路径，故仅文档修正）。
2. **worker-h5 手机页无 token 深链**：`index.html` 只从 URL 读 `tenant_id`；短码只能手输/扫码。页面从未宣称支持深链 ⇒ 不判缺陷。
3. **回执键集受全局序列化口径影响**：`application.yml` 的 `spring.jackson.default-property-inclusion: non_null` ⇒ 值为 null 的键（如"没有下一道"时的 `next_operation`）**整个被丢弃**。对外契约应表述为「**非空才有该键**」；客户端**不得**用 `hasOwnProperty('next_operation')` 判"有没有下一道"（要用值判）。本包 `C9a`（五键必在）+ `C9b`（还有下一道时 `next_operation` 必在且指向 DB 独立读出的剩余工序）已按此拆分。
4. **环境缺陷（非产品）**：`:3100` 的静态根 = `frontend/worker-h5`，而页面 `import '../../shared/operation-display.mjs'`（= `/shared/...`）在本机 404 ⇒ **整页白屏**（实测 body 仅 423 字节、0 个 `#wh5-login`）。本包改用 `:3160`（同一份静态文件，根目录 = `frontend/`，只读，不重启任何既有服务），并以 `page.route` 代理 `/api` 到 `:8080`。
5. **SMS 登录旁路码**：`SMS_BYPASS_CODE=123456` 在本机 `.env` 里存在（主会话 16:22 带 `.env` 重启后生效）。属本地调试能力，未纳入判据。

---

## §5 方法学结论（"真机 UI + 真 API + 真写库"怎么夹住）

1. **旁路所有装置，只信两侧读数**：UI 判据必须**同时**有①网络面（`page.on('response')` 抓状态码/响应体）②DB 面（`psql` 独立复读），并且期望值用**本包自己的算式**算（例：`U5` 断言 `production_work_logs 0→1` 且 `processing_position_operations.done_qty 0→2.00`，不抄响应体）。
2. **同源代理**：Playwright `route.fulfill` 做 Node 侧代理（绕开浏览器 CORS 预检），**原样保留上游状态码** ⇒ 500/401 不会被装置"洗白"；实测 `U7` 因此拿到真 `500`。
3. **驱动方式按页面真实输入形态**：手机页 = `fill` + `click`（`#wh5-code` → `#wh5-scan` → `#wh5-report`）；一体机屏 = **`page.keyboard.type` + `Enter`**（全页 keydown 扫码缓冲，无 input）。
4. **会话来源走真实登录链**：`U3` 用页面自己的登录（`#wh5-worker-no`/`#wh5-pin`/`#wh5-login`）落 `localStorage`，随后 `current-worker` 出现在真实 DOM；**不手搓 session 注入**。
5. **跨租户读面（`C17/D21` skip）用另一侧闭合**：租户 21 无合法夹具 ⇒ 未覆盖；但"工人 session（租户 20）+ 越权 `X-Tenant-Id` 头"实测**服务端零写入**（租户 21 侧计数 0），且 `X-Tenant-Id` 不是权限依据（身份只来自 session）⇒ 租户隔离在**写入侧**成立。
6. **共享云 dev 库的并发现实**：本包与线B 同时写租户 20 ⇒ **存量指纹无法在共享库上闭合**。可用的确定性替代是：①命名域零残留（逐表 `probe=0`）；②**方向语义**——非探针域计数**只增不减**= 并行包写入（登记，不计本包）；**下降**= 上一轮残留被本轮清理（基线含残留 ⇒ 判据缺陷，需先清后拍）。本包最后一次全量跑的读数即为此形态（`orders` 非探针域 374→406，期间线B 仍在校验写面）。

---

## §6 零残留（终态复读，采集时刻 2026-10-03 17:05:26 +08）

- `probeResidue()`（**逐表**，全部 0）：`probeUsers 0 / probeSessions 0 / probeOrders 0 / probeProcessingOrders 0 / probeSets 0 / probeItems 0 / probePositionOps 0 / probePartTokens 0 / probeWorkLogs 0 / probeAudits 0 / probeIdemKeys 0 / probeInboundItems 0 / probeInboundLabels 0` ⇒ `total=0`（`out/Z-residue.json`、`out/Z-baseline.json`）。
- **逐表 probe/existing 分列**（`out/Z-baseline.json`）：`orders{probe:0,existing:366}`、`processing_orders{0,271}`、`processing_position_operations{0,3021}`、`processing_set_part_tokens{0,287}`、`production_work_logs{0,15}`、`worker_report_audits{0,15}`、`users{0,19}`、`worker_sessions{0,8}`、`inbound_labels{0,4}`、`client_request_keys{0,41}` ⇒ **探针域逐表为 0**。
- **注入→删除红证**：清理逻辑本身可红 —— 前置清理前实测 `probeUsers=1 / probeSessions=1`，清理后为 `0`（`out/run-all.log` 的"前置残留 → 前置清理后"两行），证明清单不是空的。
- **存量零改动命题**：`ledgerUnchanged=false`（`excludeProbe` 口径）—— **不闭合的原因已定性**：清理删除本包探针行使行数下降（预期），同时线B 在窗口内持续写入生效（`orders` 非探针域 374→406）。**方向语义**（§5-6）是共享库上可复算的替代判据；本包不据此声称"存量逐字节未变"。

---

## §7 harness 目录树 + 一键重跑

```
acceptance/2026-10-03/worker-miniapp-writeface-sweep/
├── BRIEF.md                     # 任务书（本包范围/纪律）
├── REPORT.md                    # 本报告
├── harness/
│   ├── lib.mjs                  # 探针域常量/清理/指纹 + api/apiWorker/rawWorker + judge(fail-closed 守卫)
│   ├── p0-env.mjs               # 构建点 + 时钟自证 + 未登录 12 端点 401 基线
│   ├── p1-auth.mjs              # 工人身份面（登录/会话/切换/登出/枚举/越权/头不做权威）
│   ├── p2-scan.mjs              # 扫码闭环（读/写/幂等/状态机/审计/跨租户零写入/回执形状）
│   ├── p2b-cuttingheight-npe.mjs# 裁高 NPE 复现 + 三步单变量红证 + 负对照
│   ├── p3-inbound.mjs           # 小程序入库（识别/草稿/过账/标签/幂等/归属）
│   ├── p4-ship-upload.mjs       # 发货写面 + 小程序管理面负例 + C 端上传（:8001）
│   ├── p5-ui.mjs                # 真机 UI：手机页登录→扫码→开工 + 一体机屏 #6219 复现
│   ├── p6-baseline.mjs          # 存量指纹(excludeProbe) + 逐表 probe/existing 分列
│   └── run-all.mjs              # 一键：前置清理 → 7 段 → 终态清理 → 零残留 → SUMMARY.json
└── out/                         # 全部读数（JSON/日志/截图）
    ├── SUMMARY.json             # 交付读数（counts/perSuite/records/residue/buildPoint）
    ├── P1..P5 各段 JSON + *-summary.json、Z-residue.json、Z-baseline.json
    ├── run-all.log              # 全量跑的逐行日志（含前置/终态清理读数）
    └── shots/*.png              # UI 级截图（U1 登录视图 / U2 错 PIN / U3 登录后 / U4 扫码 / U5 开工后 / U7 一体机 500）
```

一键重跑（**唯一入口**，约 3 分钟）：

```bash
cd "/Users/guangzhen.zk/ai native/migao/acceptance/2026-10-03/worker-miniapp-writeface-sweep/harness"
API_BASE=http://127.0.0.1:8080 WORKER_UI=http://127.0.0.1:3160 node run-all.mjs
# 只跑单段（会话已在 store 时）：SEGMENTS=p2-scan,p2b-cuttingheight-npe node run-all.mjs
# 只重算汇总：SKIP_RUN=1 API_BASE=http://127.0.0.1:8080 node run-all.mjs
```

前置条件：admin-api `:8080`（带 `.env`，否则 SMS 旁路码为空）、worker-h5 静态 `:3100`（或测试用 `:3160`，根目录 = `main-live/frontend`）、ai-agent-service `:8001`（仅 P4 上传用）、Playwright 取自 `tests/node_modules/playwright`（**未新装依赖**）。

---

## §8 纪律声明

- **未**运行 `./verify-all.sh gate|full`、**未**跑 batch-gate、**未**跑全量 pytest（重活需机器级锁且非本包职责）。
- **未**发起任何**真实 LLM / 评测**调用：入库识别只走"不调模型"的路径（缺图/张数/零命中），发货识别用**空图**（`E5`，不发 vision）；`#4262` 口径下本包**不派发评测 workflow**。
- **未**改任何产品源码、测试、用例（写入仅限本包目录）。
- **未**开 issue、**未**提 PR；`#6219` 的定性与修复包归属**主会话**。
- **未**下「验收通过 / 评测 OK / 交付完成」类结论；skip 不折算 pass；每条关键判据都带红证/负对照（`C23b` `N5` `D14` `D19` `E6` `U2` `U6`）。
- 时间一律 **Asia/Shanghai（+08）**；引用 GitHub/CI 的 UTC 时间戳时已标注换算。
