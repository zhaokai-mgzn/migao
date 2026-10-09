# B 端 H5 三处修复的验收证据（2026-10-09）

> 用户 2026-10-09 在 iOS 微信 webview 打开 `https://app.migaozn.com/b/` 报出三处缺陷。
> 本目录是**独立探针**（不是开发者单测）在**真环境**与**真浏览器**上量到的读数，用于：
> ① 复现（BEFORE）；② 修复后重放（AFTER，同一脚本同一视口）。
>
> 对应 issue：#6596（输入条被底栏遮挡 + 两行布局）· #6597（「卡在哪」标签折行 / 加工单详情看不到卡在哪）。

## 为什么用探针而不是「看截图」

用户报的是**看得见**的缺陷（被遮住 / 折行），而单测只能判形态（源码里有没有某条规则），
判不了「在真浏览器里到底遮没遮」。本探针把这两条变成**几何数字 + 文本读数**：

| 缺陷 | 机器读数 | 判据 |
|---|---|---|
| #6596 输入条被遮 | `chatInput.coveredPx` = 输入条底边 − 底栏顶边 | `> 0` ⇒ 遮住；`≤ 0` 且页面不高出视口 ⇒ 通过 |
| #6597 标签折行 | `todoTags[].lineBoxes`（Range 逐行盒）+ 标签宽 vs 文本宽 | 任一标签 `lineBoxes > 1` ⇒ 折行 |
| #6597 详情页看不到卡在哪 | `orderDetail.stuckPointRequests` / `mentionsStuck` | 必须 ≥1 次请求 **且** 正文出现卡点信息 |

## 怎么跑（零真实写请求）

```
cd <repo>/tests          # Playwright 装在这里
node <repo>/acceptance/2026-10-09-bmini-three-fixes/bmini-geometry-probe.mjs            # 线上 app.migaozn.com/b/
# 本地产物（先 cd frontend/bmini-app && npm run build:h5，再把 dist 服务起来）
PROBE_PREFIX= PROBE_OUT=/tmp/after node <repo>/acceptance/.../bmini-geometry-probe.mjs http://localhost:10087
```

探针做的事（三条都**只读**）：

1. 真 Chrome，视口 390×844（iPhone 12/13，与 `tests/playwright.bmini.config.ts` 同口径）；
2. 把**所有**后端 API 用 `page.route` 桩掉 ⇒ 页面渲染走真前端代码，但**不产生任何真实写请求**，
   也不会污染测试环境数据；
3. 塞一个未过期的 JWT 形状 token（Taro H5 的 storage 是 `JSON.stringify({data})` 包装，
   写裸字符串会让 `checkAuth()` 判未登录并跳登录页 —— 这是本探针第一版踩过的坑）。

## BEFORE 读数（线上 `app.migaozn.com/b/`，产物锚点 `index.html` sha256[:16] = `b1f3a2ef2929ec66`）

| 项 | 读数 | 结论 |
|---|---|---|
| `.chat-page` 高度 | **864px**（视口 844） | 页面本身高出 20px（`100vh` + 状态栏 `paddingTop`，content-box） |
| `.message-input` 底边 / `.merchant-tabbar` 顶边 | 864 / 794 | **`coveredPx = 70`** ⇒ 输入条被底栏盖住（用户截图一致） |
| `.task-item__tag` | 宽 33.3 CSS px、`lineBoxes = 2`（「卡在哪」「待排产」均 2 行） | 标签折行 |
| 加工单详情页 | `stuckPointRequests = 0`、`mentionsStuck = false` | 页面**从不请求**卡点面 ⇒ 点进来也看不到「卡在哪」 |

截图：`out/before/chat-page.png`（输入条只剩顶部一条缝、被底栏压住）、
`out/before/dashboard-todo.png`（标签「卡在 / 哪」两行）、`out/before/order-detail.png`。
原始读数：`out/before/readings.json`。

## AFTER 读数

### ① 输入条（`#6596`）— `out/after-6596/`

| 项 | BEFORE | AFTER | 判据 |
|---|---|---|---|
| `.message-input` 底边 vs 底栏顶边 | **被遮 70px** | **`coveredPx = 0`** | 不被底栏遮挡 ⇒ 通过 |
| `.chat-page` 高度 | 864（视口 844） | **844 = 视口** | 整页不再溢出 |
| 默认态 | 输入框（要打字） | **`按住说话`**（输入框不渲染） | 默认语音模式 ⇒ 通过 |
| 四个控件是否同一行 | 两行（输入框一行、动作一行） | **同一行**（切换 / 中间区 / 加图 / 发送 的纵向中心**完全相等** `764.89`） | 单行布局 ⇒ 通过 |

### ②「卡在哪」标签 + ③ 加工单详情卡点块（`#6597`）— `out/after-6597/`

（同一脚本、同一视口、同一组桩数据；`#6597` 修复分支构建产物）：

| 项 | BEFORE | AFTER（#6597 分支） | 判据 |
|---|---|---|---|
| `.task-item__tag` | 宽 33.3 / `lineBoxes = 2` | 宽 49.9（文本 37.5）/ **`lineBoxes = 1`** | 不折行 ⇒ 通过 |
| 加工单详情 `stuckPointRequests` | 0 | **1** | 接上了卡点面 |
| 加工单详情 `mentionsStuck` | false | **true**（正文出现「卡在哪 … **打包** 等了 74.6 小时」，逐字等于服务端读数） | 看得见卡在哪 |

⚠️ `out/after-6597/readings.json` 里的 `chatInput` 段**不是 AFTER** —— 那个分支不含 `#6596` 的修复
（输入条仍被底栏遮住，`coveredPx = 70`），保留它只为对照；`#6596` 的 AFTER 由该分支自己的构建复算。

## 边界（照实登记）

- **桩数据不是真库**：探针把卡点面/待办面用桩喂进去（形状**逐字照服务端** `ProductionStuckPointService.report()`
  的嵌套键；第一版探针写成平铺键，读数里工序名落到兜底文案 —— 那是**探针**的缺陷，已在脚本里更正并留注释）。
  「真库端到端」由集成后的线上复探承担，不在本探针射程内。
- **`coveredPx` 只看聊天页与底栏的关系**：其余三个 tab 页（数据/坐席/我的）内容可滚，本探针未做「最后一行是否可达」的常驻判据
  （试过一版，列表短时读数不可判别，未留）。
- Chromium 里 `env(safe-area-inset-bottom)` 恒 0 ⇒ iOS 安全区那一半的读数靠真机复测，本探针给不出。

## 一条踩过的坑：`index.html` 是**弱锚点**（会被读成「同一份构建」）

`#6596` 与 `#6597` 两个分支的 `npm run build:h5` 产物，`dist/index.html` 的 sha256[:16] **完全相同**
（都是 `05287e043d6c7754`，两文件逐字节一致）—— 因为 `index.html` 只引用**固定名字**的 chunk
（`/js/app.js`、`/js/702.js`），**不含应用代码**（实测 `grep -c message-input index.html` = 0）。
⇒ 只拿 `index.html` 当构建指纹，会把两份不同的代码读成同一份（正是「声称的对象 ≠ 我读到的对象」）。
**处置**：探针同时输出**代码指纹** `servedAppJsSha256_16`（取 `/js/app.js`，`cache: 'no-store'`）：
`#6596` 构建 = `f36480c3e073fbe5`。两分支构建的真实差异另有直接读数佐证：`coveredPx` **70 → 0**。

## 🔴 集成读数：三处修复**同时生效**的那一份产物（用户升级后真正看到的样子）

上面两组 AFTER 各自只含一个分支的修复。真正要交付的是**三处一起**的那份产物 —— 主会话把三个修复分支
合进一个集成 worktree（`git worktree add --detach origin/main` + 逐个 `merge`，**无冲突**）、持机器级重活锁
`npm run build:h5`（exit 0），再用**同一支探针**量（`out/after-integration/`）：

| 用户报的问题 | 集成产物读数 | 判据 |
|---|---|---|
| ① 输入条被底栏遮 | `coveredPx = 0`（BEFORE 70）、整页 844 = 视口 | 通过 |
| ① 默认语音 + 一行 | 默认 `按住说话`、四控件纵向中心**完全相等**（764.89） | 通过 |
| ②「卡在哪」标签折行 | 12 个标签全部 `lineBoxes = 1`（BEFORE 全 2）、宽 49.9 | `tagWrapVerdict = OK` |
| ③ 详情页看不到卡在哪 | `stuckPointRequests = 1`（BEFORE 0）、正文出现「卡在哪 … **打包** 等了 74.6 小时」 | 通过 |

产物指纹：`servedAppJsSha256_16 = 548d8615341f3f07`（**代码**指纹；`index.html` 是弱锚点，见上一节）。
④ 工人自由报工不在本端产物射程内（后端 + 报工页写入口），其独立证据见 PG-071 与
「注入式红证：禁掉完工记账 ⇒ 恰好两条涉钱判据变红」。
