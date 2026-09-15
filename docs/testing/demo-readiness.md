# 演示就绪证据表（demo-readiness）

> **用途**：客户演示前 5 分钟看这一页。它回答**「哪一块我现在敢说 OK、哪一块只是没坏过但没验过」**。
> **纪律**：本页每个读数都标了来源（run URL / 文件 / 命令）。**没有来源的"应该没问题"不写进本页。**
> 本页**不下"演示已验收通过"的结论** —— 交付结论需按 `migao-acceptance` 协议做双 AI 交叉验证，本页只提供证据分级。

生成时间锚点：工作分支 = `origin/main` @ `10059c53`（2026-09-15 08:26 +0800）+ 本包 3 个 commit；
文中所有"实测"读数都锚定到具体 run id / 命令，不随 main 前进而失效（main 已继续前进是正常的）。
引用纪律：本页不写活跃文件的裸行号（跑完可能已漂移），一律用**符号 / 文本 / run id** 锚定。

---

## 0. 证据等级定义（沿用仓库口径）

| 等级 | 含义 | 判据 |
|---|---|---|
| **机器级** | CI 自动跑，**会红、可复核** | 有成功后仍会因回归转红的自动门禁（含红证 / 空跑护栏）；**且**能指出具体 run + 具体执行行 |
| **证据引用** | 有 artifact / 截图 / run，但**需人看** | 产物存在且可打开；**不保证**覆盖当前代码（须标注采集时间与被测 SHA） |
| **UA 级** | AI 用户代理或人按清单核对 | 判定标准写死可对号（不接受"表现正常"）；人只做不可自动化的动作（启动 / 截图） |
| **未验证** | 没有任何可引用证据 | 「没跑过」≠「坏的」，但演示时**不能声称 OK** |

⚠️ **等级不得越级**（`migao-dev-flow` §16.7）：mock 绿 ≠ 活环境绿；组件/单测绿 ≠ 旅程可用；
API 层 8/8 ≠ UI 层可用；**只跑 6 个文件的 E2E gate ≠ 全量 UI 可用**。

---

## 1. 演示证据等级表

### 1.1 C 端小程序（小布）

| 演示面 | 证据等级 | 证据 | 未覆盖的部分 | 演示前建议 |
|---|---|---|---|---|
| 小程序 · 对话 / 商品卡 / 下单卡 / 售后 / 转人工（旅程） | **UA 级** | `acceptance/2026-09-14/mini-app-e2e/REPORT.md` + `COLD-RUN.md`（冷环境复跑 38/38，09-14 21:53–21:56；截图 `screenshots-cold-run4/`）。**跑不进 GitHub CI**（需 macOS 微信开发者工具 + 登录 + 开放服务端口），故本轮起由 CI 做静态契约预检（见下两行）+ 人工 runbook §3 | ① 该轮 `dist` 构建指纹对应 **≤09-14 21:05 的 src**，其后 2 次 `frontend/mini-app/src` 改动未覆盖：`4d020423`（User 类型 `tenant_id` 谎报修正）、`5fa2c67d`（输入条单行重设计 #3759）；② **真实微信登录链路**（`Taro.login` → `/api/auth/mini/login`）在模拟器里被后端判 `WECHAT_API_ERROR: code 无效` ⇒ 恒不可自动化验证（环境限制，非产品缺陷）；③ 一张截图已标注**不可引用**（并发窗口，见 `COLD-RUN.md`） | 按 §3 runbook 走一遍（**只需人做启动+截图**，判据已写死）；重点看**输入条**（#3759 后的新形态） |
| 小程序 · e2e harness 契约（选择器 / storage 注入键） | **机器级（部分）** | 新门禁 `Demo Evidence Gate` job `Mini-app e2e static contract preflight`（run [`34913343797`](https://github.com/zhaokai-mgzn/migao/actions/runs/34913343797)，详见 §5）：`node e2e/preflight-selectors.js`（正向）+ `--redproof`（改名 ⇒ 必红）。本地与 CI 实测：正向 exit 0；红证 2/2 通过（`硬依赖类名改名` / `storage 键改名` 各 1 处 ⇒ 预检红） | **只证明「harness 依赖的名字还在」**，不渲染、不点按、不调后端 ⇒ **不是旅程证据** | 演示前看一眼该 job 是否绿；它是"人工 e2e 之前"的唯一自动信号 |
| 小程序 · H5 形态视觉回归（无会话 UX / 新品 / OrderCard） | **机器级** | `mini-app.yml` job `xiaobu H5 visual regression`（`build:h5` + Playwright `playwright.xiaobu.config.ts` 基线比对）。⚠️ 该 job 有 **diff 门控**：非 mini-app 相关变更会**整段跳过却 success**（实测 run `34912300454`：`⏭️ 无 mini-app 相关变更…跳过视觉回归空跑`，job 12 秒"成功"） | 仅 H5 形态 + mock 数据；**不是**小程序真机/模拟器形态 | 演示前若改过 mini-app，确认真跑过（看日志有没有那句 `⏭️`） |

### 1.2 B 端商家后台（admin-web）

| 演示面 | 证据等级 | 证据 | 未覆盖的部分 | 演示前建议 |
|---|---|---|---|---|
| 发货单 / 打印（UI-040，`shipment-doc.spec.ts`） | **机器级** | ① 新门禁 `Demo Evidence Gate` job `Demo path specs (admin-web, fixture mode)`（本包新增，见 §5）；② `nightly-verification` run [`34911052034`](https://github.com/zhaokai-mgzn/migao/actions/runs/34911052034) job `E2E fixture specs (full, web project)`（SHA `82d20090`）**3/3 ✓** | 只覆盖 fixture 假数据下的打印媒体隔离 + 发货人 payload；**真后端落库**由 admin-api 单测/`#3825` 覆盖，不在本层 | 演示前跑一次打印（真实打印机/PDF）——纸面样式是本层唯一无法替你确认的 |
| 下单 / 新增订单页 + 订单生命周期渲染 | **机器级** | 同上新门禁：`orders/order-create.spec.ts`（7 pass / 3 skip）、`orders/order-lifecycle.spec.ts`（3 pass）；nightly `34911052034` 同读数 | 真后端下单落库、库存校验、防连点锁事务（属 API/单测层） | 演示前 1 分钟点一次「新增订单」页确认能开 |
| 商品分类管理 | **机器级** | 同上新门禁：`catalog/categories.spec.ts`（本地 14 pass；其中 2 条本地 flaky，`--retries=1` 后过；nightly 14 pass / 0 fail） | 分类与商品的实际联动（真后端） | — |
| 页面渲染冒烟（全页面可开） | **机器级** | 同上新门禁：`smoke/pages-render.spec.ts`（4 pass） | 只断言"渲染出来"，不断言业务正确 | — |
| 米宝聊天输入条 / 最小化布局 | **机器级** | 同上新门禁：`chat/chat-panel-resize.spec.ts`（7 pass）、`chat/mibao-minimize-layout.spec.ts`（1 pass） | **不覆盖发消息/收回复/tool 卡片**（见下方"米宝聊天主流程"= 未验证） | 演示前手动发 1 条消息确认链路 |
| 首页看板 | **机器级** | `pr-check.yml` job `E2E quality gate`（6 文件清单含 `dashboard/dashboard.spec.ts`，24 tests）；nightly `34911052034` 24 pass / 0 fail | 只跑 fixture 数据 | — |
| 数据质量 / 契约 / 反占位 / 跨页一致 / 搜索对齐 | **机器级** | `pr-check.yml` 的 `E2E quality gate` 6 文件（另 5 个 quality spec）。⚠️ 该 job 的绿**只代表这 6 个文件**，不代表全量 UI | orders/products/customers/chat/settings 等 28 个 spec 文件**不在任何一个 PR 门禁里**（见 §4 缺口 1） | 不要把"E2E gate 绿"说成"UI 全量可用" |
| 商品列表 / 详情 / 编辑 | **未验证** | 反证：nightly `34911052034` 同 SHA 读数 `product-list` 20 pass / **21 fail**、`product-detail` 9/2、`product-edit` 11/2（fixture 模式断言红）。历史活环境旁证（**非当前代码**）：`acceptance/2026-09-14/merchant-ui-smoke/screenshots/08-products-list.png` 等（采集于 09-14 18:59，其后 admin-web 有 3 次改动） | fixture 模式下**大面积红**，未见任何"当前代码 + 当前环境"的机器级通过 | 演示前**手动点开商品列表/详情/编辑**各一次；不要把 `merchant-ui-smoke` 的旧截图当当前状态 |
| 订单列表 / 订单详情 | **未验证** | 反证：nightly 同 SHA `order-list` 8 / **30 fail**、`order-detail` 10 / **14 fail**、`order-remark-popover` 0 / **10 fail** | 同上；`order-list` 是演示最可能点到的页面 | 演示前手动点开订单列表 + 详情 + 备注浮窗 |
| 客户列表 / 客户详情 | **未验证** | 反证：nightly 同 SHA `customer-list` 13 / **6 fail**、`customer-detail` 8 / **6 fail** | 同上 | 演示前手动点开客户列表 + 详情 |
| 米宝聊天主流程（发消息 / 收回复 / tool 卡片渲染） | **未验证** | 反证：nightly 同 SHA `chat/chat.spec.ts` 8 pass / **12 fail**（含"页面加载后应显示消息输入框和发送按钮"红） | UI 层无机器级证据；**AI 能力本身**另有 API 层证据（见 1.3） | 演示前**必做**：手动发 1 条真实消息，确认输入框/回复/卡片都出来 |
| 售后工单列表 / 详情 | **未验证** | 反证：nightly 同 SHA `after-sales-list` 16 / **2 fail**、`after-sales-detail` 11 / **1 fail** | 少量红，但不是全绿 | 演示前手动点开售后列表 + 详情 |
| 设置 / 通知 / 加工项 / 存储 | **未验证** | 反证：`processing` 0 / **40 fail**、`settings` 8 / 14、`notifications` 6 / 12、`oss-dual-bucket` 4 / 6 | 加工项 spec 全红 | 演示若涉及加工单，**手动走一遍** |
| 登录页 | **证据引用** | 本包实测（2026-09-15）：`https://merchant.migaozn.com/` → **HTTP 307** 跳 `/login`；`/login` → **HTTP 200** | 登录**提交**链路（短信码）没有 e2e 覆盖：`specs/auth/login-sms.spec.ts` / `register.spec.ts` 属 `auth-pages` project，**没有任何 workflow 跑它**（`--project=web` 会 ignore `specs/auth/`） | 演示前用 13800138000 / 万能码 123456 亲手登一次（短信网关仍是 bypass） |

### 1.3 活环境（当前可用，本包实测）

| 演示面 | 证据等级 | 证据 | 未覆盖的部分 | 演示前建议 |
|---|---|---|---|---|
| 三域名存活 | **证据引用** | 本包实测 2026-09-15：`merchant.migaozn.com` 307→`/login`（200）；`api.migaozn.com` `POST /api/auth/sms-code` → **401**（存活 + 鉴权生效）；`ai-api.migaozn.com/health` → `{"status":"healthy","service":"ai-agent-service","version":"1.0.0"}` | 只是**存活**，不是功能 | 开演前 30 秒各 curl 一次即知 |
| AI 对话（B 端米宝 / 接口层） | **证据引用** | `nightly-verification` run [`34911052034`](https://github.com/zhaokai-mgzn/migao/actions/runs/34911052034) job `Smoke p1 regression`（活环境 `api.migaozn.com` + `ai-api.migaozn.com`）：**69 passed / 2 failed**，重试后 **70 passed / 1 failed**；`pytest` 汇总里**唯一失败项在 `test_06_perf.py`**（`test_product_list_latency` 1032ms > 1000ms 阈值；`test_concurrent_10_users_no_errors` P95 3083/2865ms > 2000ms 阈值）⇒ `test_04_ai_chat.py` 无失败项 | ⚠️ **性能阈值超限**（issue #3840）：并发 P95 约为阈值的 **1.4~1.5 倍**；**UI 层仍无证据**（API 通 ≠ 页面可用） | 演示**避免**当场跑 10 并发压测；单条对话交互不受影响 |
| 演示期间不要开 PR | **本包已复核机制** | `deploy-reconcile.yml` 触发源含 `pull_request: [opened, reopened]` → 对账 `main` HEAD 三服务镜像缺失即 `gh workflow run` 对应 deploy ⇒ **重建容器** ⇒ 1~3 分钟 502 窗口（主会话今晚实测） | 窗口时长取决于镜像/网络 | **演示期间冻结：不开 PR、不合并 PR、不触发 deploy** |

---

## 2. 四条「不许外推」（演示话术红线）

1. **mock 绿 ≠ 活环境绿**：本页所有"机器级"B 端读数都来自 **fixture 模式**（`E2E_MOCK_AUTH=true`，接口被 mock，无后端）。它证明的是"页面结构/交互/打印隔离在给定数据下成立"，**不证明**真实数据链路。
2. **只跑 6 个文件的 E2E gate ≠ 全量 UI 可用**：`pr-check.yml` 的 `E2E quality gate` 是**显式 6 文件清单**；28 个 spec 文件不在任何 PR 门禁里（§4 缺口 1）。
3. **API 层 8/8 ≠ UI 层可用**：活环境 p1 冒烟是**接口层**；UI 层（点击/渲染/卡片）另一层，B 端 UI 目前多数是"未验证"。
4. **`mini-app CI` 的 success 可能是空跑**：两个 job 都有 diff 门控，非相关变更时**步骤全 skipped 而 workflow success**（实测 run `34912300454`）。读"绿"前先看日志里有没有 `⏭️ …跳过…空跑`。

---

## 3. mini-app 真实 e2e runbook（**UA 级**；人只做启动/截图，判据写死）

**为什么是 UA 级而不是机器级**：`frontend/mini-app/e2e` 用 `miniprogram-automator` 驱动**微信开发者工具模拟器**（`harness.js` 里 `CLI_PATH=/Applications/wechatwebdevtools.app/...`），需要 macOS + 已登录 + 安全设置里开启服务端口 ⇒ **GitHub 托管 runner 上不可能跑**（不是"还没配"，是形态限制）。本包因此**没有**伪造一个"能绿"的 CI 形态，改为：① CI 只做静态契约预检（§1.1 第二行）；② 旅程证据走下面这份清单。

### 3.1 人做的动作（仅此三件，约 3 分钟）

```bash
# ① 前置（一次性，只能人做）：微信开发者工具 → 设置 → 安全设置 → 开启「服务端口」
# ② 构建产物（陈旧构建会被失败关闭护栏拦下，不会"旧脚本配旧构建自洽地绿"）
cd frontend/mini-app && npm run build:weapp
# ③ 冷环境复跑（清空模拟器 storage → 从零建立登录态；避免"环境残留给的绿"）
E2E_COLD_LOGIN=1 npm run test:e2e
```

**截图只能人做**：脚本会自动抓（`e2e/screenshots/`，稳定帧机制），人只需在失败时确认现场。

### 3.2 判定清单（逐条对号，不写"表现正常"）

| # | 判据（可对号） | 通过条件 | 不通过怎么办 |
|---|---|---|---|
| 1 | `run.js` 是否报 `陈旧构建护栏拦截` | **不报**（报了就是构建没更新，先重跑 ②） | 重跑 ②；仍报则看 `dist/.build-stamp.json` 指纹 |
| 2 | 报告头登录态来源 | 出现 `已注入登录态` 且含 `期望 botName=… / tenantName=…`；**不接受**"来自模拟器 storage 残留"（那是环境残留给的绿） | 加 `E2E_COLD_LOGIN=1` 重跑 |
| 3 | 6 个场景（对话/个人中心/登录/多轮/售后/转人工）的步骤级 PASS/FAIL | `e2e/report.md` 里**全 PASS**（上一可信轮 = 38/38） | 保留红 + 报告原文（红比假绿有价值，不要删场景） |
| 4 | 对话场景的**输入条**形态（#3759 之后**从未被本套件验证过**） | 空草稿 = 宽胶囊「按住 说话」；有草稿 = 发送键；流式中 = 停止键；**三者同行**（`__row` 单行布局） | 若形态不符 → 属**新发现**，记进 issue（本包只登记未验证，未替你判它坏） |
| 5 | 截图稳定性 | `e2e/report.md`「取证预算」节：无"需 >2 帧才稳定"的异常堆积；引用前对同一步骤的两帧做 md5 比对 | 过渡帧不得作为证据引用 |
| 6 | 产物留档 | 关键截图 + `report.md` 复制到 `acceptance/<日期>/mini-app-e2e/` 并提交（`e2e/screenshots/`、`e2e/report.md` **被 gitignore，不入库**） | 不入库 = 下次又"查不到证据"（issue #3696 的原始病灶） |

### 3.3 已知不可自动化（如实标注，不要硬编）

- **真实微信登录链路**：`Taro.login()` 的 code 在模拟器里被后端判 `WECHAT_API_ERROR: code 无效`（2026-09-14 实测）⇒ 本套件用 `POST /api/auth/sms/login` 注入等价登录态。**微信顾客身份**类断言不能由这条会话背书。
- **微信支付 / 真机授权**：同样不在本清单可覆盖范围。

---

## 4. 缺口登记（可跟进，本包不改判据）

| # | 缺口 | 证据 | 影响 | 建议归属 |
|---|---|---|---|---|
| 1 | **28 / 35 个 e2e spec 文件不在任何 PR 门禁里** | `pr-check.yml` 只列 6 文件；`mini-app.yml` 只跑 `specs/xiaobu/xiaobu-h5.spec.ts`；其余仅在 `nightly-verification.yml` 的 `--project=web` 全量里跑，而该 workflow 的 `schedule` 自 2026-09-06 被封存（只剩 `workflow_dispatch`） | 改 admin-web 时 orders/products/customers/chat 的回归**不会在 PR 拦下** | 本包已补 7 个 fixture 可跑的演示 spec（§5）；其余需**先修 fixture 红**才能纳管 |
| 2 | **全量 `--project=web` 是已知红：98 failed / 263 passed / 26 skipped**（run `34911052034`，SHA `82d20090`） | 同一 run 的 job 日志汇总行 | 不能把全量绿当目标（会变成永久噪音），需按 spec 逐个归因是"需真后端"还是"选择器陈旧" | 独立包（需真后端的 spec 应走"真后端 e2e"通道，或标注 `skip_reason`） |
| 3 | `specs/auth/**`（`login-sms` / `register`）**没有任何 workflow 跑** | `--project=web` 的 `testIgnore` 含 `specs/auth/`；无任何 workflow 跑 `--project=auth-pages` | 登录/注册旅程无机器级证据 | 独立包（登录是演示第一步，优先级高） |
| 4 | 小程序 e2e 无法进 CI（形态限制） | `harness.js` 的 `CLI_PATH` 指向 macOS 开发者工具 | 见 §3（UA 级 + 静态预检兜底） | 若要机器级，唯一现实路径是**自托管 macOS runner**（成本/维护另议） |
| 5 | 活环境 p1 性能阈值超限 | run `34911052034` job `Smoke p1`（1032ms/1000ms、P95 3083ms/2000ms） | 演示当天**不要**跑并发压测 | issue #3840 |

---

## 5. 本包新增的机器级信号（`Demo Evidence Gate`）

**已跑通的 CI 读数**（run [`34913343797`](https://github.com/zhaokai-mgzn/migao/actions/runs/34913343797)，PR #3855，`pull_request` 事件，两 job 均 `success`）：

```
job 1  Demo path specs (admin-web, fixture mode)
  ✅ manifest 有效：7 个 spec
  Running 43 tests using 4 workers
  ✓  36 [web] › e2e/specs/orders/shipment-doc.spec.ts:92:7 › 发货单 — 真实浏览器打印旅程（UI-040） › 发货页：发货人预填 + 打印媒体下只印单据、屏幕不重复显示 (6.5s)
  ✓  38 [web] › e2e/specs/orders/shipment-doc.spec.ts:145:7 › … › 订单详情：已发货可补打，纸面带运单号与已落库发货人 (6.3s)
  ✓  39 [web] › e2e/specs/orders/shipment-doc.spec.ts:173:7 › … › 发货提交：发货人随 payload 下发（改过的值优先） (3.0s)
  3 skipped
  40 passed (1.3m)

job 2  Mini-app e2e static contract preflight
  [preflight] 硬依赖选择器 2 个：.message-input__icon-btn--send .message-input__textarea
  [preflight] storage 注入键 4 个：auth-store auth_token auth_user tenant_id
  [preflight] ℹ️ 只读探针在源码里不存在（不判红，仅登记）：.message-input__hold-btn .message-input__mode-btn
  ✓ 红证通过：硬依赖类名改名（改动 1 处）⇒ 预检红（exit 1）
  ✓ 红证通过：storage 键改名（改动 1 处）⇒ 预检红（exit 1）
  ✅ 红证全部通过（2/2）—— 预检的双向判据都活着
```

> 本地（macOS）同清单复跑：`38 passed / 2 flaky（分类页 2 条首次失败、重试过）/ 3 skipped`；CI（linux）为 `40 passed / 3 skipped`。
> 两处读数都记下来：差异本身说明**本地绿不能当成 CI 绿**（反之亦然）。

- **文件**：`.github/workflows/demo-evidence.yml`（**新文件**；不改被并发包占用的 `pr-check.yml`）。
- **job 1 `Demo path specs (admin-web, fixture mode)`**：清单 = `tests/e2e/demo-path-specs.txt`（单一事实源），
  当前 7 个 spec：`orders/shipment-doc`（UI-040）、`orders/order-create`、`orders/order-lifecycle`、
  `chat/chat-panel-resize`、`chat/mibao-minimize-layout`、`catalog/categories`、`smoke/pages-render`。
  - 收录三判据（缺一不收）：① 属演示面；② **fixture 模式真能跑绿**（依据 = nightly run `34911052034` 同 SHA 读数 + 本地复跑 + 本 run）；③ **不在** pr-check 那 6 个文件里（不重复占 runner）。
  - **空跑护栏**（`migao-acceptance`「空跑」）：清单为空 / 列出的 spec 不存在 ⇒ 直接 `exit 1`；否则空实参会让 Playwright 跑全量 389 条或静默 0 条还 success。
  - 失败即上传 `tests/test-results/` + `tests/playwright-report/`（trace/截图），不"失败即丢证据"。
- **job 2 `Mini-app e2e static contract preflight`**：`frontend/mini-app/e2e/preflight-selectors.js`
  （正向 + `--redproof`）。它只回答"harness 依赖的选择器 / storage 注入键是否还被 src 产出"，
  **不是**旅程证据 —— 旅程仍是 §3 的 UA 级。
  - 脚本首版曾把**有意保留的作废契约探针**（`__mode-btn`/`__hold-btn`，`probeInputBar` 注释写明"不应存在"）当硬依赖 ⇒ 自己造了一个**假红**；已改为"只对 `waitForElement` 实参判红，探针仅登记"。
  - 脚本首版的**判据本身**也曾是空断言：裸 `includes()` 让 `message-input__textarea` 改成 `…-x` 仍判"存在" ⇒ **恒绿**。加了 `--redproof` 后当场抓出，改为带边界匹配（判据为 `name(?![\w-])`，即"后面不再跟类名字符才算同一个名字"）。
    ⇒ 教训写进代码注释：**没跑红证的守卫不许进 CI**。

---

## 6. 事实盘点（本包实测读数；含对 issue #3696 / #3817 陈述的更正）

### 6.1 各 workflow 实际跑什么

| workflow | 实际内容 | 是否含真实旅程 e2e | 空跑风险 |
|---|---|---|---|
| `mini-app.yml`（Mini-App CI） | job1 `typecheck + unit tests`（`tsc --noEmit` + `jest`）；job2 `xiaobu H5 visual regression`（`build:h5` + Playwright **mock 数据** + 基线比对，4 tests） | **否**（无小程序形态 e2e） | **有**：两 job 都有 diff 门控（`^(frontend/mini-app/\|tests/\|\.github/)`），跳过时 **success** |
| `bmini-app.yml`（Bmini-App CI） | 仅 `typecheck + unit tests` | 否 | 有（同款门控） |
| `pr-check.yml` `E2E quality gate` | Playwright **6 个显式文件**（quality ×5 + dashboard） | 部分（quality/dashboard） | 无（清单固定），但**覆盖面 = 6 文件** |
| `nightly-verification.yml` | job1 活环境 `smoke p1`；job2 `--project=web` **全量 389 tests** | **是（全量）** | ⚠️ `schedule` 自 2026-09-06 注释封存 ⇒ 只有 `workflow_dispatch` 手动才跑 |
| `e2e-real.yml` / `agent-eval.yml` / `xiaobu-acceptance.yml` 等 | 真实 LLM 评测（**本包未派发、未引用其结论**） | — | — |

### 6.2 对 #3817 的更正（本包实测）

| #3817 的陈述 | 实测 | 依据 |
|---|---|---|
| 「`shipment-doc.spec.ts` **从未在 CI 执行**」 | **部分不成立**：它在 **`nightly-verification` run [`34911052034`](https://github.com/zhaokai-mgzn/migao/actions/runs/34911052034)**（`workflow_dispatch`，2026-09-14T23:56Z，SHA `82d20090`，含该 spec 的 merge `103cf51d`）**真跑了且 3/3 全过** | 该 run job 日志：`✓ 315/316/317 [web] › e2e/specs/orders/shipment-doc.spec.ts:92/145/173` |
| 同上「合入后零执行」 | **不成立**：`gh run list --workflow=nightly-verification.yml` 在合入（2026-09-14T15:24Z）之后有 **2 次** dispatch run（`34909768102` 23:38Z、`34911052034` 23:56Z） | `gh run list` + 上面的执行行 |
| 「PR 声称 **4 passed** 与仓库 3 条 test 不符（陈旧读数）」 | **不成立**：`npx playwright test … shipment-doc.spec.ts` 的输出**恒含 `auth-setup` 依赖测试**（`✓ 1 [auth-setup] › e2e/fixtures/auth.setup.ts`）⇒ 3 条 spec test + 1 条 setup = **4 passed**。本包本地复跑得到同样的 `4 passed (20.2s)` | 本包本地复跑输出 |
| 「`pr-check` 清单不含 orders ⇒ 该 spec 无 **PR 门禁**证据」 | **成立**（这是 #3817 的真问题） | `pr-check.yml` 显式 6 文件清单；本包已用新 workflow 补上（§5） |

### 6.3 对 #3696 的更正与现状（本包实测）

| #3696 的陈述 | 实测 | 依据 |
|---|---|---|
| 「上次真实形态验证在 **09-04**；其后 mini-app 源码改动 **6 次**；e2e 产物被 gitignore ⇒ 仓库里查不到任何小程序验收证据」 | **已过时**：09-14 已补一轮**真实形态**验证并入仓 —— `acceptance/2026-09-14/mini-app-e2e/`（冷环境复跑 **38/38**，09-14 21:53–21:56，含 `COLD-RUN.md`、`run-logs/`、关键截图）+ `acceptance/2026-09-14/mini-app-input-bar/`（输入条 before/after 截图 + 帧稳定性）。**"产物不入库"这条已修** | `git ls-tree origin/main acceptance/2026-09-14/mini-app-e2e/`；`COLD-RUN.md` |
| 「登录链路从未被自动化验证」 | **部分已修**：harness 的登录**前置步骤**已落库（`e2e/lib/login.js` + `LOGIN_MISSING` 失败关闭 + 双向红证 `login-redproof.js`，PR #3720）；**真实微信登录**仍不可自动化（环境限制） | `frontend/mini-app/e2e/README.md`；`acceptance/2026-09-14/mini-app-e2e/login-redproof.txt` |
| （新发现，本包）**当前缺口缩到 2 次改动** | 证据轮 `dist` 构建指纹对应 **≤09-14 21:05 的 src**；其后 `frontend/mini-app/src` 有 2 次改动：`4d020423`（09-14 21:37）、`5fa2c67d`（09-14 22:41，输入条单行重设计 #3759）。**输入条正是所有对话/多轮场景都会触碰的组件** | `git log --format -- frontend/mini-app/src`（HEAD = `5fa2c67d`）；`COLD-RUN.md` 的构建指纹行 |
| （新发现，本包）harness 里仍有**恒为 false** 的作废探针 | `probeInputBar` 里 `modeSwitch` / `holdBtn` 读的是 `.message-input__mode-btn` / `.message-input__hold-btn` —— 这两个类在 #2953 重设计后**源码与产物里都不存在**（README 自己写明）⇒ 读数恒 `false`（若有断言引用它们，就是恒红/恒绿的空断言）。本包**未删**（它们是"有意保留的作废探针"，删掉会掩盖漂移），改由 preflight 的"探针仅登记"分支持续登记 | `frontend/mini-app/e2e/lib/harness.js` `probeInputBar`；`node e2e/preflight-selectors.js` 输出的 `ℹ️ 只读探针在源码里不存在` |

### 6.4 与 #3696 / #3817 的关系

- #3817：本包新增门禁把 UI-040 的 spec **纳进了 PR 门禁**（其处置建议 1），并更正确认了它此前**并非"从未执行"**（见 6.2）。判据 1/2 可对号，判据 3（不纳管才需标注）不适用。
- #3696（**保持 OPEN**，本包不声称它已解决）：结构性两条已被别的包修掉（证据入库 / 登录前置步骤），但"小程序旅程在 CI 无机器级信号"这条**依然成立且形态上无法消除**（需 macOS 开发者工具）⇒ 本包给的是 UA 级 runbook + 静态契约预检，**不是**机器级旅程证据。关联 issue #3696，不在此关闭它。
