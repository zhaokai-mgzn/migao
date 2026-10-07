# 2026-10-07 · #6408 修复的**真环境 UI 重放**（证据承载体）

> 起因：`#6408`（智能派单页「一键成批派单」不带批次指派 ⇒ 排料省料与「预计节省」恒为 0）
> 的代码修复于同日随 PR #6504 合并，但**清零判据**（界面派单 ⇒ 真产生扣料行 + 界面数与落账相等）
> 当时被部署停摆挡住（#6503：SWAS 磁盘 4045MB < 门槛 4096MB）。
> 磁盘回收后本条重放才跑得起来 —— 这就是它的执行记录。

## 怎么跑

```bash
# 前置：线上 admin-web 已含修复（本条重放前先做了产物级核验，见下）
docker exec migao-deploy-admin-web-1 sh -c "grep -rho 'batches:.\{0,60\}' .next/static/chunks/"
# ⇒ batches:e.map(e=>({orderId:e.orderId,itemId:e.itemId})),assignmentRu… / assignmentRule:"fifo"

PROBE_PREFIX=SD07UI3 OUT_DIR="$PWD/acceptance/2026-10-07-pool-ui-replay/out" \
  node acceptance/2026-10-07-pool-ui-replay/ui-replay.mjs
```

- 复用 `acceptance/2026-10-06-pooling-savings/harness/{lib,steps}.mjs`（**不复制**实现，避免第二份判定）；
- 探针前缀专用（`SD07UI3`），收尾 `cleanup()` 删除，**实测零残留**（orders/items/PO/consumptions/sku/product/batch 全 0）；
- 驱动方式 = **真浏览器点界面**（Playwright + 管理员登录），不是直调 API。

## 判据与读数（8/8 通过）

| # | 判据 | 读数 |
|---|---|---|
| ① | 界面 `/preview` 请求体逐行带指派 + 显式 `fifo` + `pooled:true` | `batches` 4 行，每行 `{orderId,itemId}` 非空 |
| ①b | 不再是空指派（#6408 的缺陷形态） | `batches=4`（修复前恒 `[]`） |
| ② | 界面 `/dispatch` 请求体同上 | 4 行 + `assignmentRule:"fifo"` |
| ③ | 真库产生扣料行 | `stock_batch_consumptions` **4 行** |
| ③b | Σ(`saved_meters`) > 0 | **2.8 米**（逐行 1.4 − 0.7 = 0.7） |
| ④ | `preview.savedMeters == Σ(saved_meters)` | `2.8 == 2.8` |
| ⑥ | **屏幕上「预计节省」== Σ(saved_meters)** | 屏上 `2.8` == db `2.8`（面板文案见 `out/ui-replay.json`） |
| ⑤ | 同轮红绿对照（单变量 = 请求体） | 旧体 `batches:[]` ⇒ `0`；新体 ⇒ `1.4` |

**⑤ 是同轮单变量对照**：同一批订单几何、同租户、同端点，唯一变量是请求体形状。

## 多模态证据

`out/screenshots/pool-preview-with-savings.png`（派单前那一屏，逐字含
「成批预览（4 单 · **指派规则 fifo**）… **预计节省 2.80 米**」）、
`pool-before-select.png`、`pool-after-dispatch.png`。

⚠️ 教训（写下来免得下次再踩）：第一版脚本在 `waitForSelector('[data-testid="pool-preview"]')` 之后立刻截图，
截到的是「**正在预览…**」—— **选择器出现 ≠ 内容渲染完**，那种图是**假证据**。
改成 `waitForFunction(…includes('预计节省'))` 之后才拿到真数字。

## 有意不做 / 边界

- **不重跑 300 单四臂全量**（`main.mjs`）：它测的是**服务端**对四种请求体的反应（结论已知：空指派 0 行 / 逐行指派+fifo 45 米），
  而本次改的是**前端请求体形状** ⇒ 定点 UI 重放才是对应的判据；
- 本轮**没有**覆盖「加急插队派单」那条路径的界面重放（它走同一个 `buildPoolRequest`，单测已钉住请求体；
  真环境重放留作后续）。
