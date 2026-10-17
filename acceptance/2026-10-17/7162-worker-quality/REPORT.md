# 工人端质检真页面验收（issue #7162）

- **日期**：2026-10-17（Asia/Shanghai）
- **形态**：真浏览器（Playwright chromium）+ **真 H5 页面**（`frontend/worker-h5` 静态直出，线上是同一份文件）
  + route 注入 `/api/worker/**` 夹具；视口 **390×844**（手机）。
- **为什么用夹具读面**：本机 :8080 admin-api 是 **#7162 之前**的构建（无 `/api/worker/quality/**`），
  真后端只能由 CI 全量跑；端点形状与准入由 `WorkerQualityControllerTest` / `QualityCheckServiceTest` 钉住。
  H5 静态页与线上同源形态（`index.html` + `src/*.mjs`，零构建），所以本报告判的是**真实页面行为**，不是 mock 组件。

## 结果

`verify.mjs` exit 0，`result.json` 全绿：

| 判据 | 读数 |
|---|---|
| ① 扫水洗唛落地报工页出现「质检」区块 | `blockVisible: true` |
| ① 初始态 = **未检**（不是「合格」） | `initialState: "未检"` |
| ② 点「录入质检判定」⇒ 三态表单 | `formVisible: true`，`resultOptions: 3` |
| ③ 选「返工」+ 原因提交 ⇒ 生成质检单 | `generatedNotice: true`，`stateAfter: "返工"`，`reasonShown: true` |
| ④ 提交 body 不带身份字段（身份只认 session） | `postBody = {order_item_id, result, reason}` |
| ⑤ 无 console.error | `consoleErrors: []` |

截图（AI 逐张读图确认过文案与状态）：
- `质检-未检.png`：报工卡下方出现「质检」区块，琥珀色「未检」+「录入质检判定」。
- `质检单已生成.png`：「质检单已生成」提示 + 橙色「返工」+「检验人 张师傅 · 2026-10-17 13:10」+「原因：缝线开裂」+「再录一次判定」。

## 边界（照实登记）

- **不做质检单打印/文档视图**（本轮只落记录 + 两端读面）。
- 本报告不覆盖「服务端 403 / 原因必填 422 / `inspector_kind` 落库」—— 由 admin-api 单测与 CI 覆盖。
- 报工三态（正常/返工/报废）与质检三态（合格/返工/报废）同屏共存：前者是**数量归属**，后者是**成品帘判定**，两块标题分开；
  本轮不改报工区（避免把两个事实混成一套口径）。
