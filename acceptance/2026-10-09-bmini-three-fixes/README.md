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

见 `out/after/`（同一脚本、同一视口、同一组桩数据；修复分支构建产物）。

## 边界（照实登记）

- **桩数据不是真库**：探针把卡点面/待办面用桩喂进去（形状**逐字照服务端** `ProductionStuckPointService.report()`
  的嵌套键；第一版探针写成平铺键，读数里工序名落到兜底文案 —— 那是**探针**的缺陷，已在脚本里更正并留注释）。
  「真库端到端」由集成后的线上复探承担，不在本探针射程内。
- **`coveredPx` 只看聊天页与底栏的关系**：其余三个 tab 页（数据/坐席/我的）内容可滚，本探针未做「最后一行是否可达」的常驻判据
  （试过一版，列表短时读数不可判别，未留）。
- Chromium 里 `env(safe-area-inset-bottom)` 恒 0 ⇒ iOS 安全区那一半的读数靠真机复测，本探针给不出。
