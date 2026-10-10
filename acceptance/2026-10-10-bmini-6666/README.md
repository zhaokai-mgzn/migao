# bmini（员工手机端）修复包的真几何读数（2026-10-10，issue #6666）

> **判据口径**（主会话钉死，别换成「有没有留 50px」）：底栏遮挡 = 「滚到底后最靠下的**叶子文本**
> bottom」与「底栏 top」之比：`> 0` ⇒ 那一行落在底栏之下 ⇒ 永久不可读。
>
> **不新造探针**：本目录复用 `acceptance/2026-10-09-bmini-three-fixes/bmini-geometry-probe.mjs`
> （issue #6596/#6597 那份），**只新增两节**：
> ⑥ 各 tab 页「滚到底后叶子文本 bottom vs 底栏 top」；⑦ 坐席会话详情页的页盒 / 输入区 /
> **状态类名与算出来的颜色**。同一脚本、同一视口（390×844，Chromium 移动仿真）、
> **API 全桩、零真实写请求**。

## 怎么复算

```bash
# BEFORE：线上正在跑的版本（app.migaozn.com/b/）
cd <repo>/tests
PROBE_OUT=<repo>/acceptance/2026-10-10-bmini-6666/out/before \
  node <repo>/acceptance/2026-10-09-bmini-three-fixes/bmini-geometry-probe.mjs

# AFTER：本分支的构建产物（不是部署到线上，是本地 dist）
cd <repo>/frontend/bmini-app && npm run build:h5
python3 -m http.server 10087 --directory dist &
cd <repo>/tests
PROBE_PREFIX= PROBE_OUT=<repo>/acceptance/2026-10-10-bmini-6666/out/after \
  node <repo>/acceptance/2026-10-09-bmini-three-fixes/bmini-geometry-probe.mjs http://127.0.0.1:10087
```

产物锚点（`readings.json` 里的 `servedIndexSha256_16` / `servedAppJsSha256_16`）：

| 臂 | index.html sha256[:16] | js/app.js sha256[:16] |
|---|---|---|
| BEFORE（线上） | `b1f3a2ef2929ec66` | `52cbdcbd34812c4b` |
| AFTER（本分支 dist） | `97c60535be0d3bb1` | `c87d82bed24ca3ef` |

## 判据 1（P0）：底栏不再吃掉最后一行 — `tabbarInset`

| 页面 | BEFORE 叶子文本 bottom / 底栏 top | BEFORE `coveredPx` | AFTER 叶子文本 bottom / 底栏 top | AFTER `coveredPx` | 判读 |
|---|---|---|---|---|---|
| **数据**（内容溢出） | 799.5 / 794 | **+5.5 ⇒ 红** | **761.5** / 794 | **-32.5 ⇒ 绿** | 修前最后一行（「暂无待办，AI 正在处理中」）落在底栏之下；修后整行在底栏之上 |
| 坐席（桩数据不溢出） | 179.5 / 794 | -614.5 | 179.5 / 794 | -614.5 | **这条缺陷只咬内容溢出的页面** |
| 我的（不溢出） | 342.6 / 794 | -451.4 | 342.6 / 794 | -451.4 | 审计说「四个 tab 页都被压」**不成立**（退出登录离底栏还有 451px） |

页面高（同一读数里的 `scrollHeight`/`rootBottom`）：数据页 BEFORE `rootBottom 844.4`（= 100vh + 24 设计 px 的
内容盒溢出）⇒ AFTER `843.9`（`border-box`）；`scrollHeight` 2067 → 2105（预留从 12 CSS px 变成 50 CSS px）。

截图：`out/before/tabbar-inset-dashboard.png`（最后一行被底栏压住）↔ `out/after/tabbar-inset-dashboard.png`
（读图：那一行与底栏之间有可见缝隙，整行可读）。

> ⚠️ **本目录的 BEFORE 是「线上今天仍在跑的版本」，不是我的分支**；AFTER 是**本分支构建的本地 dist**。
> 「已部署到线上并复探」这件事本包没做（要等合并/发布），别把本目录读成「线上已修好」。

## 判据 2：坐席会话详情的状态配色 — `sessionDetail.statusClass / statusColor`

| 臂 | `className` | `getComputedStyle().color` | 判读 |
|---|---|---|---|
| BEFORE | `detail-header__status detail-header__status--${detail?.status}` | `rgb(10, 37, 64)` | 类名是**字面量**（`${…}` 没插值）⇒ 三套配色一套都没生效，颜色停在**继承**的 `#0a2540` |
| AFTER | `detail-header__status detail-header__status--active` | `rgb(18, 183, 106)` | = `index.scss` 的 `.detail-header__status--active { color: #12b76a }` ⇒ 配色**真的生效了** |

截图：`out/before/session-detail.png` ↔ `out/after/session-detail.png`（同一个桩会话，状态都是「进行中」）。
**未固化**：本轮桩用的是 `active` 形态；`waiting` / `ended` 两套只在类级判据的射程内（`tests/className-interpolation.test.ts`）。

## 判据 5：坐席会话详情页的输入区（**审计的前提部分不成立**）

| 量 | BEFORE | AFTER |
|---|---|---|
| `.detail-page` 盒 | top 0 / bottom 844 / height 844 | 同（= 视口高，**不溢出**） |
| 原生导航条 | **渲染不出来**（`null`） | 同 |
| `.detail-input` | top 788.9 / bottom **844** | 同 |
| `inputBelowViewportPx` | **0** | **0** |

⇒ 「输入区没为键盘/安全区留位」里的**安全区那一半不成立**（输入区本来就补了
`calc(16px + env(safe-area-inset-bottom))`，实测底边正好落在视口底边）；**键盘那一半本机判不了**
（真机键盘 / `visualViewport`）⇒ 留给 §15.7 真机确认，本包的改动只是与聊天页**同源**的 `box-sizing: border-box`
（防「根级 padding 把 100vh 顶出视口」这一族，聊天页实测过 864/844）。

## 冒烟对照（没有把别的面改坏）

`chatInput`：`coveredPx = 0`、`chatPageHeight = 844`（与 #6596 的修后读数一致）⇒ 本包改动**没有**把聊天页
输入条的预留改坏。全量单测同口径：`frontend/bmini-app` **88 suites / 875 tests 全绿**。
