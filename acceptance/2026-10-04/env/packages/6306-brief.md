# #6306 修复任务书（durable · 已吸收第三轮独立复核对原修法的更正）

> 用途：并发槽位腾出后**零摩擦派包**。派包提示词可直接引用本文件。
> 生成：2026-10-04 11:24 +08（in-repo durable 形式；派包前的现场读数需复算一次）

## 0. 一句话

工人端主页面 `/w/` 与一体机页 `/w/machine.html` **整页白屏**（真浏览器：`bodyText=""`、`rootChildren=0`），
根因是 `render.mjs` / `machine.mjs` 静态 import 的 **`../../shared/operation-display.mjs` 未随发布落地**
（该路径落到 nginx SPA 兜底 ⇒ `200 text/html` ⇒ module script 被浏览器拒绝）。
**与 #6293（`.mjs` MIME）是两个独立缺陷**：#6293 修好入口 MIME 后页面**仍白屏**（10:43:59 +08 真浏览器实测）。

## 1. 现场复算（派包时先跑一次，确认病灶仍在）

```bash
curl -sI https://app.migaozn.com/shared/operation-display.mjs   # 期望：200 text/html（=404→兜底）
curl -sI https://app.migaozn.com/w/src/app.mjs                  # 期望：200 application/javascript
curl -sI https://app.migaozn.com/w/src/render.mjs               # 期望：200 application/javascript
OUT_DIR=/tmp/6306 node acceptance/2026-10-04/worker-miniapp-sweep/harness/ui-probe.mjs   # 期望：bodyText=""、consoleErrors 含 "text/html"
```

## 2. ⚠️ 修法（**不要**用"把 frontend/shared 铺到站根 /shared/"——第三轮复核已证其修不好）

**原修法为何无效（high 级复核结论）**：`#6293` 的 MIME 修复是 **location 级**的 ——
`deploy/swas/nginx.conf` 的 `default_type application/javascript` **只写在 `location /w/` 块内**，
镜像 `mime.types` **无 `.mjs` 表项** ⇒ 铺到站根后由 `location /` 静态直出，`.mjs` 落回 `application/octet-stream`，
**白屏照旧**（病灶从 `200 text/html` 变成 `200 application/octet-stream`）。且它会**放宽刻意收窄的托管红线**
（CI 断言 `TARGET == <静态根>/w`），并在站根制造一个不在任何腿托管/清理范围内的孤儿顶层条目。

### ✅ 采纳的修法：**树内迁移**（零 nginx 改动、零红线放宽）

1. `frontend/shared/operation-display.mjs` → **`frontend/worker-h5/src/shared/operation-display.mjs`**；
2. `frontend/worker-h5/src/render.mjs`、`frontend/worker-h5/src/machine.mjs` 两处 import 改为 `./shared/operation-display.mjs`；
3. 同步更新守卫登记的 canonical 路径：`tests/unit_ci_workflows/test_operation_display_name_guard.py` 的锚点正则
   （现为 `from\s+['"][^'"]*shared/operation-display\.mjs['"]` ⇒ 迁移后仍应命中，核对 C6/C7 断言）；
4. 若 `frontend/shared/` 迁空 ⇒ 确认是否还有其它消费者（第三轮复核已用
   `git grep shared/operation-display origin/main` 确认**只有 worker-h5 两处 import**；bmini/mini 树持有逐字 TS 副本，值等价由 C7 把守）。

## 3. 类级固化（本单最重要的一条，方向已由复核更正）

在 `deploy/scripts/worker-h5-verify-served.sh` 增加**模块闭包判据**（并同步 bmini/c-end 两腿同族）：

- 起点 = **发布集内每一个 `*.html` 入口**（worker 有**两个**：`index.html → src/app.mjs`、`machine.html → src/machine-app.mjs`；
  ⚠️ 只从 `index.html` 出发会漏掉 `machine.mjs` 这条链，而它恰是坏点导入者之一）；
- 解析面 = **静态 `import … from` + 动态 `import('…')` 字面量**（`app.mjs:336` 有真实 `await import('./api.mjs')`）；
- 每个 `.js/.mjs` 必须 `200` 且 Content-Type ∈ **JS MIME 白名单**；**空集判红**；
- 额外收集 `<link rel="stylesheet" href>` 并断 `200`（**复核补的正向盲区**：CSS 404 时页面无样式而 module 闭包仍绿）；
- **种子/孤儿模块口径要写明**（例：`frontend/worker-h5/src/shipment.mjs` 在仓库内无任何 import 指向，
  但它是发布集成员 ⇒ 判据应从**发布集**导出、而不是从"谁能被 import 到"导出）；
- **元守卫**：按"现取腿集合"判（新增第四条腿自动纳入、未带判据即红）；变异注入（删掉闭包检查、白名单恒真、空集）
  各自必红；**只改注释 ⇒ 不许红**。

## 4. 红证要求（缺一不算修好）

1. **实例红证**：本地起一个把 `.mjs` 发成 `text/html` 的静态服务器（可复用
   `acceptance/2026-10-04/worker-miniapp-sweep/harness/local-jsmime-server.mjs` 的形态），闭包判据必须**红**；
2. **元守卫红证**：删掉闭包检查 / 白名单恒真 / 空集 ⇒ 具名判红，撤回 ⇒ 绿；
3. **线上终判据（本单的收口）**：发布落地后 `ui-probe.mjs` 的**真浏览器 DOM** 必须
   `rootChildren > 0 ∧ inputs > 0`、`consoleErrors` 为空、且截图非空白 —— **"页面能渲染"才是目的**，
   "某个 URL 的 Content-Type 正确"只是手段（本单正是"只验手段 ⇒ 假绿闭环"的实例）。

## 5. 边界与未固化

- 本单只覆盖 **worker-h5 树**；bmini / C 端是打包产物，静态闭包扫描**不能证明**其懒加载 chunk 齐备
  （真浏览器旅程判据另开）。
- 修好后**必须补** line① 的 `p5-ui` 真实 UI 旅程（UA 层），把本轮唯一的 skip 面转成实读数。
- `frontend/shared/` 若仍有其它消费者，迁移范围需相应扩大（派包时现取确认）。

## 6. 证据索引

- `acceptance/2026-10-04/replay-postdeploy/ui/UI-probe.json`（真浏览器 DOM + consoleErrors + 截图路径）
- `acceptance/2026-10-04/replay-postdeploy/ui/module-closure-scan.json`（闭包扫描：8 模块，唯一坏点）
- `acceptance/2026-10-04/replay-postdeploy/ui/bmini-cend-closure-scan.json`（射程边界：bmini/C 端干净）
- `acceptance/2026-10-04/replay-postdeploy/41-mime.log`、`60-mime-after-6293.log`（#6293 修复前后对照）
- issue：<https://github.com/zhaokai-mgzn/migao/issues/6306>（含第三轮复核的修法更正评论）
