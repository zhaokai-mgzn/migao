# #6942 UI 验收工装残余三条 —— 成对读数（2026-10-15，本机真栈）

栈：admin-web `http://localhost:3001` + admin-api `http://localhost:8080`（租户 32）。
所有命令同形（只换 `--group` / `OUT_DIR`）：

```bash
REPO_ROOT="$PWD" BASE_URL=http://localhost:3001 API_BASE=http://localhost:8080 \
PHONE=13800138000 SMS_CODE=123456 OUT_DIR=<下方目录> \
node scripts/ui-smoke-merchant/spec.mjs --group <N>
```

| # | 判据 | 修前（`origin/main` = 091313a2a） | 修后（本分支） | 目录 |
|---|---|---|---|---|
| ① | `15-orders-new` 自造商品前置 + 清理自证 | ① 该轮 `--group 15` 建单旅程被**发码 400** 阻断（单组跑）；② **全量** `--group 1` 里 15- 虽绿，但搜索词仍取自「列表首个商品」= **别人的对象**（issue ① 的 404 就是它被清掉后的形态）；③ 旧 `cleanupProduct` 对 `on_sale` 商品**必 422** ⇒ 一件都没删掉（残留实测 10 件） | **1 pass / 0 fail / 31 skip**；证据逐字「自造商品…已清理，商品总数 14→14」 | `out-before-group-15` / `out-after-group-15` |
| ② | 单组跑登录确定性（`--group 12`） | **0 pass / 1 fail / 28 skip**；`12-processing` 报 `getByText('加工项管理') … navigated to "http://localhost:3001/login"` + 三条 401 + `400 POST /api/auth/sms/send` | **1 pass / 0 fail / 31 skip** | `out-before-group-12` / `out-after-group-12` |
| ② | 全量 `--group 1` | 8 pass / **1 fail（`10-product-detail`：发码 400 被当旅程失败）** / 20 skip | **9 pass / 0 fail / 23 skip** | `out-before-group-1` / `out-after-group-1` |
| ③ | 名称台账（`--group 28`） | **0 pass / 0 fail / 29 skip**（台账里的 `27-corporate` / `28-register` 都不是注册名） | **1 pass（`28-corporate-about`）/ 0 fail / 31 skip（32 条记录）** | 见 PR body 逐字读数 |

## 单组跑逐旅程扫描（判据 K 的证据面）

`out-sweep-singles/`：`--group NN` 逐个跑（20 组）+ 另跑的 1/10/11/12/15/16/21/25/28。
**跑到的旅程全绿**（`0 fail`）；未覆盖：`17-order-ship`、`32-production-qr-and-piecework`
（`--group 17` / `--group 32` 前缀被 `16-`/`12-` 分支接走 ⇒ 该形态下一条都不跑，32 条全 skip）。

## 残留清理读数

本机取证期间共清掉 **10 件** 冒烟遗留商品（`冒烟SKU商品/详情商品/门幅/建单商品` 前缀，均为 `on_sale`）：
`商品总数 24 → 14`，逐件 `下架=200 / DELETE=200 / GET=404`。
其中 1 件的残留是**本轮原代码**造成的（`清理失败 —— 留痕由残留计数断言承接` 却没人红），
已由本分支的「清理失败即判红」修掉（见 `out-after-group-15` 的 `14→14`）。

## 本目录的入库口径（为什么只入 json/md/log，不入截图）

- 入库：每个读数目录的 `smoke-results.json`（逐条 errors/notes/evidence 逐字）+ `smoke-summary.md` + `stdout.log`，
  加本文件（成对读数总表）。合计约 **0.5MB**。
- **不入库截图**（本轮共 25 张、约 3.6MB）：本轮的判据是**结构化**读数（`[http] <状态> <方法> <URL>` 与
  `GET /{id} == 404`），不靠读图定案 ⇒ 截图对「可复算」没有增量，只增仓库体积。
  重启条件：真需要**视觉面**判定时（例如门幅下拉的**渲染**差异、tab 高亮的视觉态），
  按 `migao-dev-flow` §15.7 另跑一轮多模态验收并入库那一轮的截图。

## rebase 到 #6941 合并后的 main（`daa08f558`）复验读数

与上游 `spec.mjs` 解冲突时**保留本 PR 的修法**，并删掉 #6941 已冗余的 `loginWindow` 机制
（`let loginWindow` / `onConsole` 的 `if (loginWindow && /status of 4\d\d/.test(text)) return` /
`smsLogin` 的窗口包裹 / `done()` 里 `if (/\/api\/auth\/sms\/send/.test(f)) continue`）——
本 PR 的「发码失败只记不抛 + `[http]` 逐条对应消化」覆盖同一条噪声；#6941 与登录无关的四条原样保留
（`waitForText`=2 / `确认状态流转`=1 / 加工分类前置自造=3 处 / `ensureLoggedIn`=29）。

| 命令 | rebase 前（本分支旧 tip） | rebase 后（`daa08f558` + 本分支） |
|---|---|---|
| `--group 1` | `9/32 通过，0 失败，23 skip` | **`10/32 通过，0 失败，22 skip`**（上游把 `16-`/`17-`/`32-` 从 skip 转成通过） |
| `--group 12` | `1/32 通过，0 失败，31 skip` | **`1/32 通过，0 失败，31 skip`** |
| `--group 15` | `1/32 通过，0 失败，31 skip` | **`1/32 通过，0 失败，31 skip`**（`14→14` 无残留） |

删冗余后**只有** `25-settings` 的「只读期间 4xx」自有账本仍需要发码容忍（它的账本挂在
`page.on('response')` 上、不看 `journey.done`）⇒ 保留的是 `smsSendToleratedResponse` **结构化判据本身**，
不是 #6941 的 `loginWindow` 窗口放行。
