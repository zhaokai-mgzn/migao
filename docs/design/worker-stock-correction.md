# 工人端「库存修正」（按批次把余量改成实盘米数）

> 需求来源：2026-10-29 用户逐字「手机端还要增加一个库存修正的功能，apk程序也要同步增加这个功能，
> 允许工人对某个批次的布匹进行修正」。追踪：issue #8104（主仓 `zhaokai-mgzn/migao`）。
> 关联：批次余量读面 #7604 · 按批次盘点（唯一写面）#5865 · 裁剪报工确认批次 #7647 ·
> 手机端收口到 bmini #7806 · APK 工人菜单 #8089 / migao-terminal #8。

---

## 0. 一句话

工人发现「这一卷布实际只剩 42 米，系统说还有 45.5 米」时，在手机上**按批次**把余量改成实测米数；
服务端把它当作一次**按批次盘点**落账（批次分录 + SKU 库存同事务对齐），并留下「谁、为什么」。

---

## 1. 形态（两处入口，同一份页面）

```
                     https://app.migaozn.com/b/#/pages/worker/home/index
                     ┌────────────────────────────┴───────────────────────────┐
   手机浏览器 / 微信内（手机端）                              观星台终端.apk（商米 V2s 手持机）
   /b/ 工人工作台「库存修正」行卡                            同一份 /b/ 页面（WebView）⇒ 同一张行卡
                     └────────────────────────────┬───────────────────────────┘
                                                  ▼
                              pages/worker/stock/index（搜批次 → 填实盘 → 提交）
                                                  ▼
               GET  /api/worker/batch-stock/batches      （找批次 + 原因闭词表）
               POST /api/worker/batch-stock/correction   （一次修正）
                                                  ▼
             BatchStocktakeService#stocktake（唯一写面：批次分录 reason=stocktake + SKU 库存同事务）
```

- **APK 无需重新打包**：APK 加载的就是 `/b/#/pages/worker/home/index`（`MainActivity.WORKER_HOME_URL`），
  行卡随页面发布自动出现；Android 壳只拦「`/b/` 的黄金策登录页」与机台页（`/w/machine.html` / `page=cut_calc`），
  不拦新路由。⇒ 本单**不改 migao-terminal 仓**（要在 APK 里「同步」的是页面，不是包）。
- **手机端只落 bmini**：2026-10-26 方向裁定（#7806）「后续新的工人面一律落 bmini」；
  worker-h5 `/w/` 只把 `stock` 键登记进闭词表镜像（无对应面，见 `render.mjs` 的 `PAGE_STOCK`）。

---

## 2. 五条口径（每条都有会红的判据）

| # | 口径 | 判据（回归时会怎么红） |
|---|---|---|
| 1 | **不写第二套库存逻辑**：服务端只调 `BatchStocktakeService#stocktake`（批次台账写入点唯一，类级守卫 `tests/unit_ci_workflows/test_batch_stocktake_write_point.py`） | 在别处直接 `consumptionMapper.insert` ⇒ 类级守卫红；把 productId 改成请求体自带 ⇒ `WorkerBatchStockServiceTest` ① 红 |
| 2 | **准入先于写入**：批次必须属于本租户（404）；实盘米数 0.1 米粒度、非负（负数 400、超精度/缺值 422，**不静默取整**）；原因取闭词表（未知 422）；备注 ≤60 字 | 放行 `-1` / `42.55` ⇒ `WorkerBatchStockServiceTest` ③④ 红 |
| 3 | **幂等**：`client_request_id` 必填，拼成运行标识 `wc-<id>`；库层唯一索引 `uk_batch_consumption_stocktake` 兜住重试（第二遍 `replayed`，不双记） | 每次提交都换新键 ⇒ 重试双记；`worker-stock-page` ⑦ 红 |
| 4 | **实盘为准、零差异零写入**：实盘 == 当刻余量 ⇒ `unchanged`（不落分录、不动 SKU 库存） | 把 `unchanged` 当 `applied` 回 ⇒ 回执判据红 |
| 5 | **台账答得出「谁、为什么」**：批次分录 `operator` = 工人姓名、`note` 以「工人库存修正：姓名（工号 X），原因 …」开头（工人 session 在 `resolveOperator()` 眼里是 system ⇒ 必须显式给） | 去掉 audit ⇒ `WorkerBatchStockServiceTest` ① 的 audit 断言红；库存流水会显示「系统自己改的」= 假账 |

---

## 3. 接口契约（snake_case，与工人端其它读面同口径）

### `GET /api/worker/batch-stock/batches?keyword=&page=1&size=20`

```json
{"success": true, "data": {
  "items": [{"batch_id": 7, "batch_no": "PC-20261020-0007", "product_id": "prod-1",
             "product_name": "雪尼尔窗帘布", "sku_code": "2659-04-28", "dye_lot": "A12",
             "inbound_no": "RK-20261020-0001", "received_date": "2026-10-20",
             "remaining_meters": 45.5}],
  "total": 1, "page": 1, "size": 20,
  "reasons": [{"code": "miscount", "label": "数量记错了"}, {"code": "damaged", "label": "破损 / 报废"},
              {"code": "wrong_batch", "label": "报工选错批次"}, {"code": "other", "label": "其他"}]
}}
```

- `keyword` 命中批次号 / 旧系统批次号 / 货号 / 缸号 / 入库单号（服务端 LIKE；空 = 最近入库的批次）。
- **原因清单跟读面一起下发**：端侧不写第二份选项（否则「屏上能选、提交被拒」）。

### `POST /api/worker/batch-stock/correction`

```json
{"batch_id": 7, "actual_meters": 42, "reason": "miscount", "note": "裁过一截", "client_request_id": "8f2b-…"}
```

回执（**四数一起回**，读的人不必自己减）：

```json
{"success": true, "data": {
  "run_id": "wc-8f2b-…", "batch_id": 7, "batch_no": "PC-20261020-0007",
  "product_name": "雪尼尔窗帘布", "sku_code": "2659-04-28",
  "status": "applied",            // applied | unchanged | replayed
  "before_meters": 45.5, "actual_meters": 42, "delta_meters": -3.5, "after_meters": 42,
  "worker_name": "张三", "worker_no": "CY-1001"
}}
```

---

## 4. 台账与审计（为什么不是新 reason 族）

- 工人修正 = **实盘为准**，与商家盘点在账上是同一种事实 ⇒ 沿用 `reason=stocktake` + `stocktake_run_id`。
- 「工人修正 / 商家盘点」的分列**本单不做**：那需要给批次来源加第四个 reason（迁移 + 形状约束 + 回滚路径）。
  重启条件：真的出现「按 reason 统计盘点来源」的需求时另开迁移单（见 issue #8104 边界段）。
- `note` 形如 `工人库存修正：张三（工号 CY-1001），原因 数量记错了，备注 裁过一截 · 批次盘点：批次 PC-… 盘前 45.5 米 → 实盘 42 米`
  （列宽 255，服务端截到 250）；库存流水（`stock_ledger_entries.operator`）同一 operator。

---

## 5. 页面（`frontend/bmini-app/src/pages/worker/stock/index.tsx`）

- 四态互斥：读取中 / 读不到（可重试）/ 未登录（引导工号 + PIN 登录）/ 就绪；
- 选中批次 → 面板（系统余量 + 实盘输入 + 原因 chips + 备注 + 提交）；提交前 `Taro.showModal` 二次确认
  （文案里同时有「系统读数 → 实盘读数」）；
- 回执三态分开说（已修正 / 与系统一致未写入 / 此前已记过账）；提交成功后列表余量按回执回写；
- **端侧幂等键语义**：同一份输入的重试复用同一个键；改了批次 / 米数 / 原因 / 备注 ⇒ 换新键；
- 提交体 = `utils/workerStock.ts::buildCorrectionBody` 的**构造式白名单**（无 worker_id / worker_name / tenant_id）。

菜单：`WorkerPages.STOCK = "stock"`（默认集合里就有，商家后台「设置工人端菜单」可逐人关）；
入口显隐 ≠ 访问拦截（关掉菜单 ≠ 工人改不了库存）。

---

## 6. 边界（照实登记）

- **不做盘点单**：无单号 / 无审批 / 无打印（沿用 #5865 的 A 最小录入式）；
- **一次提交只改一个批次**（批量盘点仍是商家面）；
- **不新增 reason 族**（见 §4）；
- **小程序发版是人工环节**（#7806）：代码合入 ≠ 用户手机上的小程序已是新版；`/b/` H5 腿自动发布；
- 真机核对项：商米 V2s 上 `/b/` 页面的输入法 / 数字键盘、二次确认弹窗观感（本单只做 H5/真机一致的语义与几何下限）。

---

## 7. 判据索引

| 面 | 判据 |
|---|---|
| 后端接口 / 权限 / 401 | `WorkerBatchStockControllerTest`（无 session 401 + 零调用 / 零 `@RequirePermission` / 请求体无身份字段 / snake_case 绑定 / 4xx 透传） |
| 后端口径 / 审计 / 幂等键 | `WorkerBatchStockServiceTest`（复用唯一写面 + audit operator/note / 负数 400 / 超精度 422 / 未知原因 422 / 批次 404 / 三态透传 / 原因闭词表） |
| 菜单闭词表 | `WorkerPagesTest`、`WorkerPageCatalogControllerTest`、`frontend/worker-h5/tests/worker-h5-pages.test.mjs`（镜像逐值） |
| 端侧纯逻辑 | `frontend/bmini-app/tests/worker-stock.test.ts`（白名单 / 米数口径 / 三态文案 / 幂等键形态） |
| 端侧页面 | `frontend/bmini-app/tests/worker-stock-page.test.tsx`（未登录只引导 / 列表 / 面板 / 二次确认 / 回执 / 幂等键复用与换键 / 401 / 空态与读失败） |
| 可达性 / 写入口 / 视觉 | `page-entry-reachability`、`worker-surface-ledger`、`worker-card-contrast-guard`、`input-center-guard`、`worker-copy-plain-text-guard` |
| 用例 | `.github/cases/bmini.yml` 的 **BM-056**（真值 `batch-stocktake.worker-correction`） |
