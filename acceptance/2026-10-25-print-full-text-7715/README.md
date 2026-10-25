# 销售单纸面「打印全」（issue #7715）—— 真 Chromium 前后对照

用户 2026-10-25 逐字「这里打印预览的文字要打印全，不能缩略」：销售单打印预览的明细「颜色」列
显示成 `2659-08 月落雾…`（`text-overflow: ellipsis`）。本轮把纸面长文本（颜色 / 货号 / 客户 / 地址）
改为**折行印全文**（`break-words`），省略号形态整条撤掉。

## 这两张图是什么

同一份 `SalesDoc` 组件（`frontend/admin-web/src/components/orders/SalesDoc.tsx`）渲染出的 HTML，
在真 Chromium 里按**三联纸几何**排版后截图（`@media print` + 纸面可打印宽度）：

- `before-ellipsis.png` = **对照臂**：把旧形态 `.sales-cut`（`text-overflow: ellipsis` + `nowrap`）注入回去
  —— 复现用户截图里那句 `2659-08 月落雾…`；
- `after-wrap-full-text.png` = **改后**：颜色格折行印全 `2659-08 月落雾灰蓝拼接加长款`。

两臂用的是**同一份 DOM、同一把尺子**（只差那一条 CSS），所以差异只可能来自这次改动。

## 读数（改前 → 改后）

| 读数 | 改前（注入 `.sales-cut`） | 改后 |
|---|---|---|
| 颜色格 `text-overflow` | `ellipsis` | `clip` |
| 颜色格 `white-space` | `nowrap` | `normal` |
| 颜色格行数 | 1 行（后半截被吃掉：`scrollWidth > clientWidth`） | 2~3 行，无横向溢出 |
| 颜色格高度 | 7.1mm | 11.9mm |
| 纸面内容高 | 89.7mm | 94.5mm |
| 单联可用高 | 128mm | 128mm（**仍装得下，1 页**） |

🔴 **改前的 89.7mm 与用户真机截图底部读数「89.7mm ≤ 可用 128mm，装得下，预计 1 页」逐字吻合**
⇒ 这个对照臂与现场同几何，不是"另搭一个看起来像的页面"。

## 怎么复跑的（三步，都在本机完成，不用起整套服务）

1. 把组件渲成 HTML：临时 vitest 用例 `render(<SalesDoc inline printTarget="sales" … />)` 后落盘
   `.sales-print-area` 的 `outerHTML`（夹具用用户截图同款数据：单号 `20261025048430001`、客户
   `冒烟发货提交1792779315927`、颜色 `2659-08 月落雾灰蓝拼接加长款`、7.3 米 × 30.80 = 224.84）；
2. 用该 HTML 作为 `--content` 编译 Tailwind（`npx tailwindcss -i src/app/globals.css …`），
   把产物内联进页面；
3. Playwright（`tests/node_modules/playwright`，chromium headless）：`emulateMedia({media:'print'})`、
   视口宽 = 241mm − 左右各 12mm = **217mm**、正文 9pt，量 `text-overflow` / `white-space` /
   `scrollWidth` vs `clientWidth` / 行数 / 内容高（内容高按 `PrintDocPreview.measureSheets` 同款口径：
   临时把 `.sales-sheet` 的固定高度与裁切摘掉再量）。

## 边界（如实登记，别把这张图读成"验收通过"）

- 这是**组件级**真浏览器验证（同组件、同纸面几何），**不是**商家端 33 旅程真栈冒烟：
  本机 admin-api 未起、云库不接，这一趟没有跑 `scripts/ui_smoke_merchant.sh`；
- 针式点阵真机上的**行距 / 换行落点**只有真机才量得准（`lib/print-media.json` 的
  `continuous-241x140.pendingMeasurements` 早已登记）；**重启条件** = 上线后在真机打一张核对
  「折行后的颜色格是否仍在撕线内」；
- 判据（会红）在代码侧：`frontend/admin-web/tests/unit/components/SalesDoc.test.tsx` 的 ⑤ +
  `tests/unit_ci_workflows/test_print_paper_full_text_guard.py`（四份纸面单据同尺，
  省略号 / `truncate` / `line-clamp` 一律红）。这两张图只是**人读证据**，不是门禁。
