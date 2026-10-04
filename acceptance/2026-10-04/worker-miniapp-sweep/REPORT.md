# 线① 验收包 · 工人端（worker-h5）+ 小程序（bmini-app / mini-app）写面 sweep — 2026-10-04 第四轮

- **执行者**：线① 验收子代理（`/api/worker/**` 写面 + bmini/mini 写面）
- **被测面（读数一律取自它）**：`https://api.migaozn.com` + `https://ai-api.migaozn.com`（`/ready`=200）
- 🔴 **行为实测构建点 = `de614623d`**（2026-10-02 10:22:50 UTC = 18:22 +08，落后 `origin/main` **152** 个提交）——
  由**集成侧独立复现**（issue **#6294**）收敛：部署步远端输出逐字 `PREV_GOOD_TAG=sha-de61462` +
  `❌ 磁盘可用 3998MB < 门槛 4096MB ⇒ 中止构建`；近 80 条 deploy run 的 `deploy=success` 数为 **0**。
  **台账声称 `ff655a06c` 而该 commit 从未成功部署。**
  **本包独立给出行为面印证**：`out/P0d-deployed-identity.json` 的 500 形态与「早于 `#6219` 修复」相容（见 F3）。
- **本地 worktree 只是参照，不是被测对象**：`/Users/guangzhen.zk/migao-wt/main-live` @ `43ca70322`
  （与 `origin/main` 在本线功能面差 **75 文件**）⇒ 本包**不拿它当被测对象**；它只用于 `buildPoint()` 记录与
  §7 的「MIME 对照实验」静态文件来源。
- **被测租户**：`tenant_id=25`「米高测试环境」，管理员 `13800138000`，短信万能码 `123456`，企业编码 `shop-8yn7`
- **观测窗口**：2026-10-04 09:05 ~ 09:18（+08）
- 🔄 **环境变更留痕（复核后，2026-10-04 09:30:44 +08）**：被测面已切到 **`sha-6838a05`（= main HEAD `6838a0533`）**，
  **#6294 的部署问题已修**（清盘 13.63GB 构建缓存后重发布成功）。
  ⇒ 本报告下述读数**仍是被测时刻（`de614623d`）的读数**，**未重跑**（复核指令：只修表述、不重跑判据）。
  相关结论的**当前状态**请按「#6294 已修」重读：F3 的「线上不含修复」描述的是**09:05~09:18 那个窗口**的镜像。
- **四态口径**：`pass` / `fail(产品)` / `skip(未覆盖，不冒充已验)` / `假红(判据缺陷，含故意失效控制项)`；**skip 永不折算成 pass**
- **不自我验收声明**：本包**只产读数 + 判定 + 证据**，不下「验收通过 / 评测 OK / 交付完成 / 已达标」类结论

---

## §1 一句话结论

**工人端与小程序写面在这台线上机上仍然能跑通全部核心写路径**（扫码报工落 `production_work_logs`、幂等回放、状态机拒绝、入库草稿→过账、发货 pack/ship/unpack、RBAC/租户隔离），
**但工人端 H5 的 UI 层在部署面整页不可用**（nginx 把 `.mjs` 发成 `application/octet-stream`，浏览器拒绝执行 module script）；
同时本包以**行为面判别式**给出了「线上跑的不是台账声称的 `ff655a06c`」的独立印证。
两条都已被集成侧开单：**F1 = #6293**（nginx MIME + 四条发布自检腿零 MIME 判据）、**F3 = #6294**（部署构建点错位）。

---

## §2 四态汇总表（按套件）

| 套件 | pass | fail | skip | 假红 | total |
|---|---|---|---|---|---|
| P0b 空租户冷启动链（商品→下单→收款→加工单→工序实例） | 7 | 0 | 0 | 0 | 7 |
| P1 工人身份面（登录/会话/切换/登出/伪造/越权/头不做权威） | 16 | 0 | 0 | 0 | 16 |
| P2 扫码闭环（核心写路径 + 幂等 + 状态机 + 审计） | 24 | 0 | 1 | 0 | 25 |
| P2b 裁高读面（**老构建**行为 + 单变量三步对照） | 4 | **1** | 0 | 0 | 5 |
| P3 小程序入库写面（识别/草稿/过账/标签） | 18 | 0 | 1 | 0 | 19 |
| P4 小程序其余写面 + C 端图片上传 | 20 | 0 | 0 | 0 | 20 |
| P5 UI 级（本地只读静态服务；部署面 MIME 缺陷单列 P0c） | 9 | **1**（故意失效控制项） | 0 | **1** | 10 |
| **合计** | **98** | **2** | **2** | **1** | **102** |

**两条 `fail` 的定性（都不算「当前源码的产品缺陷」）**：

| id | 定性 | 依据 |
|---|---|---|
| `P2b/N1.cutting-height-null-product` | **老构建（`de614623d`）的行为面读数**，**不是**当前源码缺陷 | `origin/main` 的 `WorkerCuttingHeightService.positionRow` 已含 `productId == null ? null : brands.get(productId)` 短路、`brands()` 空集返回 `new LinkedHashMap<>()`（修复 commit `24b7381d1` / #6219，且 `git merge-base --is-ancestor 24b7381d1 ff655a06c` = **YES**）⇒ 线上 500 只可能来自**旧镜像**（见 F3），不是「已修缺陷被报成现状」 |
| `P5/U6.redproof` | **故意的失效控制项**（期望值故意写坏） | 期望 `codeBefore === "<token>-BROKEN"` 而实测 `""` ⇒ 按设计**必须红**，证明 U4 的判据确实在读真实 DOM（不是空断言） |

### 复核 objection 之 6：`P2/C23b` 在**非 NULL 输入上**空转 pass（夹具漂移，已登记）

- **实测逐字（`out/P2-scan.json` 的 `C23b` / `run.log:111`）**：条目**名称**写「本夹具订单行 `product_id` 为 NULL 时的读数」，
  而同一 `detail` 的实测值是 **`product_id={"product_id":"…"}`（非 NULL）∧ 端点 HTTP 200`** ⇒
  「不得 5xx」这一断言在**非 NULL 输入**上通过 ⇒ **不是在测它声称的那件事**（migao-acceptance「空断言/同轮不精确」族）。
- **为什么会漂移**：`C23b` 复用 `F5` 夹具，而 `F5.itemId` 的 `product_id` 在本题材里**始终非 NULL**
  （真正置 NULL 的是 `P2b` 的 `N1`/`N5` 与 `P0d` 的专项夹具）。
- **处置（不改断言、只登记）**：判为 **夹具漂移**；真 NULL 场景已由
  **`N1`（含红证）+ `N5`（单变量三步）+ `P0d`（部署面判别式）+ `P5/U7`（一体机 UI 面）** 四条覆盖
  ⇒ 本条**不产生**「NULL 场景已验」这一结论。`pass` 计数**不调整**（四态合计仍 102），但在本节明确它**不是** NULL 场景的证据。
- **会红的判据（若将来要固化成真判据）**：`输入 = product_id IS NULL`（断言前置里**显式校验输入为 NULL**），
  否则该断言**恒真**——这正是本条被登记为缺陷而不是被读成「已覆盖」的原因。

**两条 `skip`**：`P2/C17.cross-tenant-object`、`P3/D21.cross-tenant-label` ——
**记录时刻（09:15:13~09:15:23 +08）库里的对照租户是线③临时租户 26**「米高测试环境-隔离对照」（09:04:48 +08 建），
它**没有**「码 + 待做工序」/「标签短码」夹具 ⇒ **无对照对象，未覆盖**（不冒充已验）。

> 🔴 **证据与叙述的差异（复核 objection 已修正，留痕）**：`out/P3-inbound.json` 里 `D21` 的 `detail` 逐字是
> **「租户 21 无标签短码夹具 ⇒ 未覆盖（不冒充已验）」** —— 那是**旧底座写死 `T21 = 21` 时录下的字符串**，
> 与「租户 21 已于 **2026-10-04 08:31** 连同租户 20/1 一起清空」这一事实不符。
> ⇒ 更正：① **真实原因 = 无可用对照夹具**（记录时刻的对照租户是 26）；② **租户 21 已不存在**；
> ③ 底座模板**已按动态取对照租户修正**（见 §7 变更表第 4/5 行 + 「出证后编辑」留痕）。
> 本条 skip 的**结论（未覆盖）不受影响**，受影响的只是原因文字。

---

## §3 真缺陷清单

### F1【P1 · 部署缺陷 · 已开单 **#6293**】部署面工人端 H5 + 一体机页**整页白屏**：`.mjs` 被发成 `application/octet-stream`

- **逐字读数（`out/P0c-ui-deployed-mime.json` / `D2`）**：
  `GET https://app.migaozn.com/w/src/app.mjs` ⇒ **200 ∧ `content-type: application/octet-stream`**（16059 B），
  而 HTML 用的是 `<script type="module" src="./src/app.mjs">` ⇒ 浏览器按 HTML 规范**拒绝执行**。
  集成侧补充同一读法：`/w/src/machine.mjs` ⇒ `application/octet-stream`（25186 B）⇒ **一体机裁高屏同病**。
- **单变量对照（同 host 家族，逐个实测）**：

  | 资源 | Content-Type | 结论 |
  |---|---|---|
  | `/w/src/app.mjs` · `/w/src/machine.mjs` | `application/octet-stream` | ❌ 拒执行 |
  | `/w/src/styles.css` | `text/css` | ✅ 映射在 ⇒ **只缺 `.mjs` 一条** |
  | `/js/app.js`（C 端）· `/b/js/app.js`（bmini） | `application/javascript` | ✅ 正常 |

- **真实浏览器面（`D4`）**：`title="工人报工"` ∧ body `innerText` = **空串** ∧ `#worker-h5-root` **0 个子节点** ∧
  `input=0` / `button=0`；console 逐字
  `Failed to load module script: Expected a JavaScript-or-Wasm module script but the server responded with a MIME type of "application/octet-stream". Strict MIME type checking is enforced for module scripts per HTML spec.`
  截图：`out/shots/D-mime-workerh5-blank.png`、`out/shots/probe-workerH5.png`。
- **对照面（bmini 正常）**：`https://app.migaozn.com/b/` 渲染出「员工登录 / 管理员登录」表单
  （`out/UI-probe.json` / `targets.bmini.dom.bodyText`）⇒ 证明不是「整个 CDN 都坏」。
- **归因（五层）**：① 现象＝部署面页面白屏；② 直接因＝`.mjs` 的 `Content-Type` 非 JS MIME；
  ③ 服务端因＝nginx 静态直出、MIME 表缺 `.mjs`（`server: nginx/1.31.3`；仓库侧 `deploy/swas/nginx.conf`
  无 `types` 块、无 `.mjs` 映射）；④ 流程因（**F6**）＝发布后自检腿只判「200 + sha256 + body 标记」，
  零 MIME 判据 ⇒ 内容全等也全绿；⑤ 影响＝车间报工页与一体机页**一起不可用**。
- **本线判据（会红）**：`module script 的 Content-Type ∈ JS MIME 集合`。红证即上文 console 逐字。
- **本线射程内的后果**：**工人端 H5 的 UI 级写面验证不可行** ⇒ `P5` 的 UI 读数**不冒充**部署面验证
  （见 §4「P5 口径」）。

### F3【P0 · 部署缺陷 · 已开单 **#6294**】行为实测构建点 ≠ 台账构建点：线上跑 `de614623d`，`#6219` 修复未生效

- **矛盾起点**：`#6219` 的修复 commit `24b7381d1` 在 Git 上是 `ff655a06c`（**台账声称**的被测构建点）的**祖先**，
  而线上 `GET /api/worker/production/cutting-height` 在「订单行 `product_id` 为空」时仍 **500**。
- **本包的行为面判别式（`out/P0d-deployed-identity.json`）**：按 `git show 24b7381d1 -- backend/admin-api/src/main/java/com/migao/admin/service/WorkerCuttingHeightService.java` 逐字核对，
  该修复**只动两处** —— ① `positionRow` 里**只把 `brand` 那一行**改成显式短路（插入 `String productId = …` 再判空）；
  ② `brands()` 的空集分支 `Map.of()` ⇒ `new LinkedHashMap<>()`。
  **紧邻的 `product_name` 行原本就有** `item == null ? null :` 守卫，**未被本次修改**（复核 objection 已据此修正）：

  ```text
  旧（24b7381d1^ 的 brand 行，**无守卫** —— 这正是 NPE 点）：
      row.put("brand", item == null ? null : brands.get(item.getProductId()));
      row.put("product_name", item == null ? null : item.getProductName());   // 旧码原本就有守卫
  新（24b7381d1 之后 = origin/main 的该区段）：
      String productId = item == null ? null : item.getProductId();
      row.put("brand", productId == null ? null : brands.get(productId));
      row.put("product_name", item == null ? null : item.getProductName());   // 未改
  ```

  ⇒ **判别式仍然成立**：`item == null` 时旧码在**取 `brand` 那一行**就抛（`brands.get(null)` 在**不可变空表**上 NPE），
  而 `brand` 是 `product_name` 的**前一行** ⇒ 旧码**不可能**产出「200 + `missing[]`」这种响应体形状；
  新码两行都已短路（`brand` 由本次改造、`product_name` 本来就有）⇒ **必得 200 + `missing[]`**。
  实测 **`HTTP 500` ∧ `error.code=INTERNAL_ERROR` ∧ 取不到 `missing[]` 形状** ⇒ 与「修复已部署」**不相容**。
- **单变量三步（同码）**：有 `product_id` ⇒ **200**（`positions[0]` 含 `product_name`/`base`/`cutting_height`/`missing:[]`）；
  置 `NULL` ⇒ **500**；还原 ⇒ **200**。
- **归因**：本包证据强度只能到「**线上运行的代码不含该修复**」这一层；
  「为什么」（部署腿从未成功、镜像 `sha-de61462`、磁盘门槛中止）由集成侧 durable 证据给出（#6294）⇒ **两者互证**。
- **对本线射程的影响（重要）**：本线 `P2b/N1` 的 500 **不是**「已修缺陷被报成现状」的当前源码缺陷，
  而是**老构建行为**；同时它也是「工件/部署面与台账声明不一致」的**行为面证据**。

### F4【P2~P3 · 环境/夹具前提】空租户冷启动链有三处**必须先知道**的前提（否则直接卡死或误读成功）

| 序 | 前提 | 逐字读数 | 证据 |
|---|---|---|---|
| 1 | `POST /api/admin/products` **必带 `categoryId`**（空租户无分类） | 第一版 ⇒ **HTTP 422 `VALIDATION_ERROR`「分类ID不能为空」**；且分类表名 = `categories`（不是 `product_categories`） | `out/P0b-step0-category.json`、`out/P0b-step1-product.json` |
| 2 | `POST /api/admin/processing-orders/generate` 对订单行的准入 = `processing_info.saleForm === '布料'`（或 `processingItems` 非空） | 只给 `craft/curtainType/componentRole` ⇒ **HTTP 200 ∧ body `success:false`「订单 … 无加工项，无需生成加工单」** ⇒ **HTTP 200 不是成功**，必须读 per-order `success` | `out/P0b-step5-generate.json`；源码 `ProcessingOrderService.prepare`（`snapshot.isEmpty()` ⇒ 该文案） |
| 3 | `product_skus` **没有 `deleted` 列**（带 `deleted=0` 过滤 ⇒ SQL 报错） | `ERROR: column "deleted" does not exist` | 见 §7 复算命令 |

> 按集成侧口径，**第 1 条**登记为 **P2（可自助恢复：建商品表单内联「管理分类→添加分类」）**。

### F5【P3 · 跨线并发】命名空间冲突：线B 的商品复用本线自建分类 ⇒ 本线分类被外键钉住、无法自清

- **读数**：`run-all` 终态清理后 `probeCategories=1`（`out/Z-residue.json`），阻塞源**不是本线对象**：
  线B 的 **36** 个 `线B验收商品-*` 把 `products.category_id` 指向本线自建分类
  `6bb606a303c304277a1d3928a97752f0`（`线A验收分类-mut4p1fzas`）。
- **处置**：本线**不得**改删非探针对象（BRIEF §3.6）⇒ 等线B 释放后**再跑一次同一清理**，
  实测收敛到 `probeCategories=0 / total=0`（§6）。⇒ 这是**并发布局的观察项**，不是本线残留失控。
- **会红的判据**：`probeCategories == 0`（实测 1 ⇒ 判据自身有效）。

### F6【P2 · 断言健壮性缺口 · 归在 **#6293** 下】内容哈希全等 ≠ 页面可用：发布自检腿零 MIME 判据

- **读数（本包独立现取）**：`curl -s https://app.migaozn.com/w/src/app.mjs | shasum -a 256`
  = `c07670ade0523580b9dcc50d69f1d65156ededc09e40d0013730ae5a63a18ae3`
  = `git show origin/main:frontend/worker-h5/src/app.mjs | shasum -a 256`（`index.html` 同样相等）
  ⇒ **身份/新鲜度判据全部通过，而页面是死的**。
- `deploy/scripts/worker-h5-verify-served.sh` 的判据集合 = ① 200 ② body sha256 == 仓库 ③ body 含 `src/app.mjs`
  ④ `/w/src/app.mjs` 200 + sha256 == 仓库 ⇒ **没有一条看 `Content-Type`**。
- **会红的判据**：`发布后自检必须断言入口 module 的 Content-Type ∈ JS MIME`
  （当前的腿在 MIME 坏掉时**依然全绿** ⇒ 这是「空断言」方向，集成侧实测四条腿 MIME 判据计数全为 0）。
- ⚠️ 本包**不改 `deploy/**`**（测量窗口内不动部署面，修复排在三线收口后 —— 集成侧指令）。

---

## §4 套件明细与关键判据（含红证/负对照）

### P0b 空租户冷启动链（**本轮独有价值**，7/7 pass）

`商品(含SKU) → 下单(订单行带**真实 `product_id`**) → 确认收款 → 加工单 + **2 行可扫码工序实例**`

| id | 判据 | 读数 |
|---|---|---|
| `CH0.category` | `POST /api/admin/categories` 2xx ∧ DB 有行 | HTTP 200 |
| `CH1.product+sku` | `POST /api/admin/products` 2xx ∧ `product_skus` 恰 1 行 | HTTP 200，SKU 1 行 |
| `CH2.order-with-product-id` | 下单 2xx ∧ `order_items.product_id == 请求值`（**不踩 #6219 路径**） | `product_id=a1551c9a…` 与请求一致 |
| **`CH3.prepay-gate`** | **负对照**：未确认收款的订单**不得**生成加工单 | HTTP 200 ∧ **未生成**（`dbPo=null`） |
| `CH4.confirm-payment` | `PUT /payment` 200 ∧ DB `status=confirmed` | 一致 |
| `CH5.generate-processing-order` | `POST /processing-orders/generate` 200 ∧ per-order `success≠false` ∧ 工序实例 ≥1 | poId 非空、工序实例 **2 行** |
| `CH6.e2e-empty-tenant-first-order` | 四段端点全 2xx + 三段 DB 复读一致 + `set_id` 非空且 `qty>0` | 可扫码工序实例 = **2** |

> `CH3` 是本套件里**真正会红**的负对照（判据方向 = 前置闸门；`pending` 单不得出加工单）。
> 该链的模板（工序字段形状）落 `out/.chain.json`，被 `lib.mjs::pickOpTemplate()` 优先读取 ⇒ p2/p2b 夹具可用。

### P1 工人身份面（16/16 pass）
建探针工人（`POST /api/admin/workers`）→ 工号+PIN 登录 → `X-Worker-Session-Id` 是**唯一**身份来源；
伪造/缺失 session ⇒ 401；`X-Tenant-Id` 换租户**不改变**身份（`A11`，判据修正留档：请求头不是权限依据）；
`A12` 登录未给租户 ⇒ 422（不落默认租户）。

### P2 扫码闭环（24 pass / 1 skip）
正路径 `C1~C9b`：`scan` 只读自证 → `complete` 落 1 行 `production_work_logs` → `qty/qualified/worker` 与请求一致
（期望由本包独立算式给出）→ 工序 `done_qty/done_at/started_at/worker_id` 推进 → `worker_report_audits.identity_source=server_session`
→ **同 `X-Client-Request-Id` 重放仍 1 行**（幂等）→ 无幂等键重复完工 ⇒ 4xx 且不加数量 → 回执形状（`C9a` 五键 + `C9b` 有下一道时 `next_operation` 指向 DB 独立读出的剩余工序）。
负例 `C10~C16`：同 seq 两道 ⇒ `OPERATION_AMBIGUOUS` 且**零写入**；跨部位工序 ⇒ `OPERATION_NOT_IN_SCAN_TARGET`；超量/负数/零 ⇒ 拒绝；坏 token ⇒ 404；空 token ⇒ 422。
`C18` **红证**：body 塞别人的 `worker_id/worker_name` ⇒ 仍记在登录者头上。
`C17` **skip**（见 §2）。

### P2b 裁高读面（4 pass / 1 fail）
`N2`（还原 ⇒ 200）、`N3`（商品存在但无品牌属性 ⇒ 200）、`N4`（`scan` 不受影响 ⇒ 归因只在 `cutting-height` 层）、
`N5`（**单变量三步** 有=200 → 置NULL=500 → 还原=200）；`N1` = 老构建行为面读数（§3-F3）。

### P3 小程序入库写面（18 pass / 1 skip）
`D1`：只给 `barcode` ⇒ **400 `INBOUND_RECOGNIZE_NO_IMAGE`**（源码注释声称的「解码优先、零 LLM」省流路径
从工人端点**不可达** —— 图片校验在解码分支之前；本轮在新租户/新构建点**复现一致**，登记为**待裁定**的契约与实现不一致）。
其余：草稿不动库存 ⇒ 过账才动；`Idempotency-Key` 幂等；标签短码 + 打印留痕；库存/台账由 DB 独立复读。
`D21` **skip**（对照租户 26 无标签夹具）。
**未调用任何真实 LLM**（只走缺图/张数/零命中等不调模型的路径）。

### P4 小程序其余写面 + C 端上传（20/20 pass）
小程序登录链负例（`/api/auth/mini/login`、`/bmini/login`、`/employee/login`、`/sms/send|login`、`/password/change`）、
发货写面 `pack/ship/unpack/recognize`、管理面负例（`pool/preview|dispatch`、`orders/{id}/ship` 的权限/租户面）、
售后/会话写面**只碰输入校验与权限**（闭环归线②）、C 端上传（ai-agent）的**无凭证/类型/大小/不落存储**。

### P5 UI 级（9 pass / 1 故意失效控制项）—— **口径必须读清**

- **部署面 UI：不可用**（F1）⇒ 工人端 H5 的 **UI 级写面验证登记 `skip(未覆盖)`**，
  **不得**用「页面能打开」冒充已验（BRIEF §3.9）。检查点：`out/P0c-ui-deployed-mime.json`。
- **本段 9/10 的读数取自「本地只读静态服务 `http://127.0.0.1:3170`」**（`harness/local-jsmime-server.mjs`，
  **只读**、不改产品代码/不改 nginx/不碰既有服务；静态文件 = `main-live/frontend/worker-h5/**`），
  `/api/**` 由 Node 侧代理到**被测已部署 API**。
  **它的作用只有一条：把「MIME 头」这一个自变量单独拎出来做单变量对照** ——
  同一份页面在**正确 MIME** 下能完成「登录 → 当前工人上屏 → 扫码 → 开工 → 落库」，
  在**部署面 MIME** 下 `#worker-h5-root` 0 子节点 ⇒ 归因锁定到 MIME，而**不是**页面代码。
  ⇒ 这 9 条**不构成**「部署面 UI 已验证」；它们只是归因对照 + 本线写面在真实浏览器下的补充读数。
- 截图登记：`out/shots/U1-login-view.png`、`U2-bad-pin.png`、`U3-logged-in.png`、`U4-scan-view.png`、
  `U5-after-report.png`、`U7-machine-null-product.png`、`D-mime-workerh5-blank.png`、`probe-workerH5.png`、`probe-bmini.png`。
- **bmini H5（部署面）**：`https://app.migaozn.com/b/` 正常渲染登录页（`out/UI-probe.json`）⇒
  本轮**未**做 bmini 的 UI 写面旅程（时间预算给了 MIME 归因 + 冷启动链）⇒ **登记 `skip(未覆盖)`**（见 §5）。

---

## §5 未覆盖清单（`skip` 及原因与重启条件）

| # | 未覆盖项 | 原因 | 重启条件 |
|---|---|---|---|
| 1 | **工人端 H5（`/w/`）部署面 UI 级写面** | 部署面 `.mjs` MIME 缺陷 ⇒ 页面整页白屏（F1/#6293） | #6293 修复并**重新发布**后，对 `https://app.migaozn.com/w/` 直跑 `p5-ui.mjs`（`WORKER_UI=https://app.migaozn.com/w`） |
| 2 | **一体机裁高屏（`/w/machine.html`）部署面 UI** | 同 1（`machine.mjs` 同病） | 同 1 |
| 3 | **bmini H5（`/b/`）UI 写面旅程** | 时间预算优先给了 MIME 归因 + 空租户冷启动链；本轮只到「页面可渲染 + 输入框可定位」（`out/UI-probe.json`） | 下一轮直接把 `p5-ui` 的驱动方式套到 `/b/`（需先确认登录契约：`/api/auth/employee/login` 的字段与验证码路径） |
| 4 | `P2/C17` 跨租户**写入**对象面 | 记录时刻的对照租户 26（线③临时租户）无「码 + 待做工序」夹具（`P2-scan.json` 的 `C17.detail` 逐字「租户 26 无…」） | 有第二个带工序夹具的租户时重跑（**不得**用租户 25 自己的对象冒充对照） |
| 5 | `P3/D21` 跨租户**标签**面 | 同上（**无对照夹具**）；⚠️ `P3-inbound.json` 里该条 `detail` 逐字写的是「租户 21 无标签短码夹具」= **旧底座写死 `T21=21` 时录下的字符串，与证据时刻的库状态不符**（租户 21 已于 08:31 清空）⇒ 原因以本行为准，见 §2 的差异留痕 | 同上 |
| 6 | 小程序 `mini/login` 的**成功链**（微信 code2session） | 需真微信 code（外部输入） | 具备真微信 code / 小程序模拟器时（本机未监听 ⇒ 需人工开） |
| 7 | 打印/标签**硬件**通道 | 无硬件（BRIEF §6 明确不做） | 不做 |
| 8 | 真实 LLM 评测 | 用户 #4262 裁定 | 用户显式要求时 |

**`skip` 永不折算成 `pass`**（BRIEF §3.2）——上表 8 项在本轮**均未**产生 `pass` 判定。

---

## §6 残留清理（清理前后现取读数）

**清理对象 = 本包命名域**：名称前缀 `线A验收` + id 前缀 `la`（含冷启动链 `lac`）。
**未碰**任何非探针行（`guardedWrite` 会拒绝非探针对象）。

| 时刻 | 读数 | 来源 |
|---|---|---|
| `run-all` 前置残留 | `total=0`（全 0，上一轮的 4 商品/5 分类已被本轮前置清理收敛） | `out/run.log` |
| `run-all` 终态（09:16:21） | `total=1`，唯一残留 = `probeCategories=1`（被线B 36 个商品以 FK 钉住，**F5**） | `out/Z-residue.json` / `residueAtRunAllEnd` |
| **收尾清理前（09:18）** | `{probeUsers:0, probeSessions:0, probeOrders:0, probeProcessingOrders:0, probePositionOps:0, probeWorkLogs:0, probeProducts:0, probeCategories:1, total:1}` | 见下命令 |
| **收尾清理后（09:18）** | `{…全部 0…, total:0}`，`cleanupProbe().errors = []` | `out/Z-residue.json` 的 `finalCleanupPass` |

- **清理逻辑本身可红（注入→删除自证）**：① 前置清理前后 `probeUsers 2→0 / probeSessions 5→0 / probeProducts 4→0 / probeCategories 5→0`
  （`out/run.log` 两行）；② 收尾 `probeCategories 1→0`（本次 `finalCleanupPass.before/after`）。
- **口径缺陷自曝（本轮实测）**：`cleanupProbe()` 原实现把若干 `DELETE` 串在一次 `psql -c` 里，
  `ON_ERROR_STOP=1` 下**一条失败会连坐后面全部语句**（实测「删 `products` 撞
  `stock_ledger_entries_product_id_fkey`」把同一次调用里的 `worker_sessions`/`users` 删除整段跳掉）。
  已改为**逐条独立 try/catch + 登记 errors**，并把商品域 FK 依赖（`stock_ledger_entries` /
  `stock_batch_consumptions` / `stock_batches` / `fabric_remnants` / `inbound_order_items` /
  `product_attributes` / `product_colors` / `product_skus`）排在 `products` **之前**。
- **存量零改动命题**：`ledgerUnchanged = false` —— **不闭合**，可复算的原因是**三线并发**：
  同一窗口内线②/③ 仍在写租户 25（`out/Z-baseline.json` 的 `perTable.existing` 在我这一轮里就在变），
  且 `run-all` 的前置清理也会删掉**上一轮我自己**的探针行。⇒ 本包**不据此声称**「存量逐字节未变」；
  可用的确定性替代 = **本包命名域逐表归零**（上表）+ `Z-baseline.json` 的 `probe/existing` 分列。

---

## §7 harness 目录树 + 一键重跑

```
acceptance/2026-10-04/worker-miniapp-sweep/
├── REPORT.md                        # 本报告
├── harness/
│   ├── lib.mjs                      # 复制自 2026-10-03 底座 + 本轮改动（见下「相对底座的改动」）
│   ├── bootstrap-chain.mjs          # ★新增：空租户首个订单端到端（商品→下单→收款→加工单→工序实例）
│   ├── p0-env.mjs                   # 构建点/时钟/未登录 12 端点 401
│   ├── p0d-deployed-identity-probe.mjs  # ★新增：部署镜像身份**行为面**判别探针（F3 判别式）
│   ├── ui-probe.mjs                 # ★新增：部署面 UI 可达性 + 真实 console/DOM 读数
│   ├── ui-deployed-mime.mjs         # ★新增：F1 最小复现 + 三面单变量对照
│   ├── local-jsmime-server.mjs      # ★新增：**只读**静态服务（唯一自变量 = `.mjs` 的 MIME）
│   ├── p1-auth / p2-scan / p2b-cuttingheight-npe / p3-inbound / p4-ship-upload / p5-ui / p6-baseline
│   └── run-all.mjs                  # 前置清理 → bootstrap → p0..p6 → 终态清理 → SUMMARY
└── out/                             # 全部读数（JSON + run.log + shots/*.png）
    ├── SUMMARY.json                 # 交付读数（counts / perSuite / records / residue / buildPoint / findings）
    ├── P0b-*.json · P0c-ui-deployed-mime.json · P0d-deployed-identity.json · P1..P5 各段
    ├── Z-residue.json · Z-baseline.json · run.log
    └── shots/*.png                  # UI 级截图（含部署面白屏证据）
```

**一键重跑（唯一入口）**：

```bash
cd "/Users/guangzhen.zk/ai native/migao"
API_BASE=https://api.migaozn.com TENANT_ID=25 ADMIN_PHONE=13800138000 SMS_CODE=123456 \
LIVE_WORKTREE=/Users/guangzhen.zk/migao-wt/main-live \
OUT_DIR=acceptance/2026-10-04/worker-miniapp-sweep/out \
node acceptance/2026-10-04/worker-miniapp-sweep/harness/run-all.mjs
# 只跑单段：SEGMENTS=p2-scan,p2b-cuttingheight-npe node …（同样带这组 env）
# UI 段需要先起只读静态服务（后台 job，收尾 kill）：
#   node acceptance/2026-10-04/worker-miniapp-sweep/harness/local-jsmime-server.mjs
# F1 / F3 的复算（幂等、只读）：
#   curl -sI https://app.migaozn.com/w/src/app.mjs | grep -i content-type          # application/octet-stream
#   curl -sI https://app.migaozn.com/b/js/app.js  | grep -i content-type          # application/javascript（对照）
#   API_BASE=https://api.migaozn.com TENANT_ID=25 ADMIN_PHONE=13800138000 SMS_CODE=123456 \
#     OUT_DIR=acceptance/2026-10-04/worker-miniapp-sweep/out node …/harness/p0d-deployed-identity-probe.mjs
```

> **重跑注意（本包实测到的装置摩擦，登记而非隐藏）**：`run-all` 的**终态清理会删掉本包 `la` 探针工人与 session**，
> 之后单独跑 `p3-inbound.mjs` 会 `throw store 里没有 workerA`（它的前置是 `p1-auth` 建号）。
> ⇒ 单段重跑的**正确顺序** = ① `p1-auth`（建号+登录）→ ② 目标段；或直接跑 `run-all`（它自带有序编排）。
> 本轮 `p3` 的判定读数取自 `run-all` 的那一次（`out/P3-inbound.json`，09:15:23 +08），**未被上述摩擦影响**。

**相对 `2026-10-03` 底座的改动（逐条，都在本包目录内）**：

| # | 改动 | 为什么 |
|---|---|---|
| 1 | `buildPoint()` 增 `apiBase / readsFrom / localWorktreeRole / deployedBuildpoint` | 本线**被测面 = 已部署 API**，本地 worktree 只是参照 ⇒ 读数里必须能把两者分开 |
| 2 | `pickOpTemplate()` 优先读 `out/.chain.json` | 空租户**没有**存量工序实例（§3-F4） |
| 3 | `cleanupProbe()` 逐条独立 + 商品域 FK 顺序 + 残留计数扩到 products/skus/categories | §6 的口径缺陷自曝 |
| 4 | `p2-scan.mjs`：跨租户对照从写死 `21` 改为**动态取「id ≠ 本租户的第一个」**；无对照则 `skip` | 旧租户 20/1/21 已于 2026-10-04 08:31 清空 |
| 5 | `p3-inbound.mjs`：前置清理里写死的 `${20}` → `${TENANT_ID}` | 同上（否则清理打错租户） |
| 6 | `p5-ui.mjs`：默认 `WORKER_UI` 指本地只读静态服务 | 部署面整页不可用（F1） |
| 7 | **出证后编辑（披露）**：`p3-inbound.mjs` 在 `D21` 出证（09:15:23）**之后**于 **09:18:30** 又被编辑 —— 把写死的「租户 21」改成动态取「id ≠ 本租户的第一个租户」，并把 skip 文案参数化 | 旧底座写死 21（该租户已于 2026-10-04 08:31 清空）⇒ 若不复现该缺陷，下一轮会得到一条**指向不存在租户**的原因文字。**后果照实登记**：`out/P3-inbound.json` 的 `D21` 里保存的是**编辑前**录入的字符串（「租户 21 …」），**当前模板无法逐字复现它** ⇒ 该条证据与模板之间存在**版本偏斜**，读的人必须以 §2 的差异留痕为准（结论「未覆盖」不受影响） |
| 8 | `p2-scan.mjs` 的 `C23b` 描述**未改**（保留原文） | 见 §2「复核 objection 之 6」——该条在**非 NULL 输入上**空转 pass，已按「夹具漂移」登记而非改文案 |

---

## §8 纪律声明

- **未**运行 `./verify-all.sh gate|full`、**未**跑 `batch-gate`、**未**跑全量 pytest（机器级重活锁，非本包职责）。
- **未**发起任何**真实 LLM / 评测**调用（#4262）；入库识别只走「不调模型」的路径，发货识别用空图。
- **未**改任何产品源码 / 测试 / 用例 / `deploy/**`；写入仅限 `acceptance/2026-10-04/worker-miniapp-sweep/**`。
  （例外与说明：为做 F1 的单变量对照，起了**只读**静态服务 `local-jsmime-server.mjs`（后台 job，收尾 kill），
  以及一个 Python 侧已存在的 `:3160`（**未动**）；两者都不写盘。）
- **未**开 issue、**未**提 PR；F1 → **#6293**、F3 → **#6294**（**集成侧开单**，本包只引用）。
- **未**下「验收通过 / 评测 OK / 交付完成 / 已达标」类结论；`skip` 不折算 `pass`。
- **写操作只碰探针对象**（`线A验收` / `la`）；**未**改删任何非探针行。
- 时间一律 **Asia/Shanghai（+08）**；引用 GitHub/CI（UTC）时间戳处已逐处标注换算。

### 附：套件四态与「假红」的对照自证

| 面 | 判据 | 本轮读数 |
|---|---|---|
| 库层面冷却链负对照 | `CH3.prepay-gate`（未付款不得出加工单） | pass（`dbPo=null`） |
| 幂等面 | `C7` / `C20`（同键重放仍 1 行） | pass |
| 身份不可冒领 | `C18`（body 塞别人 id ⇒ 仍记登录者） | pass |
| 零写入负例 | `C10/C11`（工序未确定 ⇒ 一个字节都不写） | pass |
| **故意失效控制项** | `U6.redproof`（期望值故意写坏） | **fail（按设计）** |
| 断言健壮性缺口 | F6（sha256 全等而页面全死） | 观察项（已并入 #6293） |
