# 裁剪报工确认批次 —— 工人端 UI 证据（issue #7647）

## 这是什么

工人端 H5 报工页「批次」区块的**真浏览器截图**（Chromium，390×844 DPR2）。
由 `ui-evidence/shot.mjs` 生成：静态服务本仓 `frontend/worker-h5` + Playwright 路由打桩
（`/api/worker/**` 全部由脚本内夹具返回），**不碰真库、不起 admin-api**。

跑法（在仓库根；playwright 取自 `tests/node_modules`）：

```
node acceptance/2026-10-24-7647-cutting-batch/ui-evidence/shot.mjs
```

## 四张图各证明什么

| 文件 | 屏面 | 判据 |
|---|---|---|
| `01-assigned-prefilled.png` | 派工指定了批次 ⇒ 输入框**预填** `PC-20261020-0007`（可改）+ 候选 chip（`余 42.50 米` / `余 3.00 米 · 余量不足`）+ 实心「报 工」可点 | 预填 + 可改 + 候选可读 |
| `02-unassigned-empty-disabled.png` | 本单没指派批次 ⇒ 输入框**空**（占位示例）+ 一行 accent 提示「请先填批次号再报工…」+ 「报 工」**灰化不可点** | 未指派 ⇒ 必须手输才能报工 |
| `03-typed-enabled.png` | 填入 / 点候选后 ⇒ 提示消失、按钮恢复可点 | 填了就放行（前端门禁不是死墙） |
| `04-receipt-after-report.png` | 报工回执句：`已报工 · 下一道：打包 · 批次 PC-20261020-0007 · 余量 -1.50 米 · 本批余量不足，缺口 4.50 米已如实记账` | 回执带批次 / 余量 / 缺口 |

## 边界（照实登记）

1. **这是打桩屏面**：服务端响应由脚本夹具给出，证明的是**前端**形态（区块 / 预填 / 门禁 / 候选 / 回执）；
   服务端「缺批次 422 / 换批次回补 + 扣减 / 余量不足落负账」由 Java 判据证明
   （`StockBatchConsumptionCuttingReportTest` / `ProductionScanCompleteServiceTest`，见用例 PG-092）。
2. 第 4 张图的「下一道 = 打包」是打桩里的**不完整** operation（只给了 `logical_name`）⇒ 屏面上
   「应做 / 未定价」缺数是夹具副作用，不是产品形态；真实服务端的 `next_operation` 是完整工序视图。
3. 未做真栈（admin-api + 云 dev 库）同屏冒烟：需要真加工单 + 真批次行 + 工人登录态；本单未跑，
   如需另起一次真栈旅程（按 SDQS 口径造数 + 清理自证）。
