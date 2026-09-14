# 小程序（mini-app）e2e 可信化验收报告 — 2026-09-14

- **任务**：issue #3705（本包）— ① 修复 e2e 选择器对当前 UI 已过期（09-06 输入条重设计）② 加「陈旧构建」失败关闭护栏 ③ 重跑并逐条归因 ④ 证据入库（#3696 的两条结构性问题之一）
- **被验收对象**：`frontend/mini-app` 小布 C 端（微信开发者工具模拟器 + `miniprogram-automator` + 真实后端 SSE）
- **被测代码 SHA**：`aa64bb98`（主工作区分支 `verify-h`；`frontend/mini-app/src`、`config`、`e2e` 与 `origin/main` **逐字节一致** —— `git diff --stat HEAD origin/main -- frontend/mini-app/src frontend/mini-app/e2e frontend/mini-app/package.json` 为空，故结论对当前主线同样成立）
- **被测构建**：`dist/app.js` 构建时间 **2026-09-14 20:34:56**（run1~run5 均以此为被测产物；run5 之后因护栏红证流程重建过一次，源码未变）
- **源码指纹**（护栏判据）：`sha256(src+config) = fc36841d9431…`（71 个文件）
- **执行**：DSH 小程序 e2e worker 子代理（session `e6ce8cd9`）— 模拟器由用户开启的服务端口 `127.0.0.1:21161` 提供
- **可复跑**：`cd frontend/mini-app && npm run build:weapp && npm run test:e2e`

## 结论（分三类，不做「全部通过」式表述）

| 类别 | 状态 | 内容 |
|---|---|---|
| ① **陈旧构建护栏** | ✅ **已生效（含 4 项红证 + 1 项「不误报」绿证）** | 内容指纹（首选）+ mtime 兜底 + 产物缺失；失败关闭、不自动构建。见 §2 |
| ② **不受输入条设计影响的失败项** | ✅ 已修（1 项，含修前红/修后绿） | 导航栏品牌名假红（botName 硬编码「小布」）。见 §3-1 |
| ②′ **输入条相关项（会随 e393f824 过期）** | ⚠️ **已按当前源码对齐，等待 e393f824 的最终 class 清单后复位重放** | 已收敛到 `harness.probeInputBar()/typeAndSend()` 单点，复位只需改 1 个文件。见 §3-2 |
| ③ **等待对齐轮重放的修复** | ⚠️ **已改未重放（登记，不计入已验证）** | 气泡数量判定（断言竞态）、草稿态截图抓取时机。见 §6 |
| ④ **存疑项** | ❓ **无法判定** | `chat/04` 帧内容与同一时刻 DOM 断言不一致（两种假设，需要模拟器做判决实验）。见 §5-3 |

**不凑全绿的说明**：5 轮完整 e2e 依次暴露了 5 个不同的**断言缺陷**（run1~run5，见 §4 与 `runs-summary.md`）。每一轮的全绿都可能是「还有没暴露的假断言」—— 证据比一个漂亮的 38/38 更有用，故**照实记录每轮的 PASS/FAIL 与逐条归因**，不以「最后一次全绿」作结论。

## 1. 问题定性与修前基线

`e2e-report-before-fix-2632.md`（修前基线，26 PASS / 6 FAIL）。逐条归因：

| # | 失败步骤（修前） | 归因 | 证据 |
|---|---|---|---|
| 1 | 导航栏品牌名「小布」 | **断言问题（假红）** | 运行时 DOM 探针：`.chat-page__navbar-name` 存在且渲染 `光头强`（botName 由企业设置下发，UI-018）；旧断言写死「小布」⇒ 恒红 |
| 2 | 输入条默认语音模式（按住说话） | **断言问题（选择器过期）** | `.message-input__hold-btn` 在 `dist/` 与 `src/` 计数均为 **0** |
| 3 | 发送按钮激活 | **断言问题（选择器过期 + 无文本）** | `.message-input__btn` 计数 0；且新发送键是图标按钮，`text()` 恒空，旧 `includes('↑')` 恒假 |
| 4 | multiturn 第1轮「90s 无回复」 | **断言问题（连带假红）** | 发送键找不到 → 旧代码 `if (sendBtn) tap()` **静默跳过** → 消息根本没发出 |
| 5 | multiturn 第2轮「90s 无回复」 | 同上 | 同上 |
| 6 | 转人工：未找到发送按钮 | 同 #3 | `.message-input__btn` 计数 0 |

**缺陷 B（本轮主因之外的更大隐患）**：修前那份 35/36 白名单不是「跑出来的绿」而是「**跑在 2026-09-04 旧 `dist` 上**的绿」—— 旧脚本配旧构建自洽。重建后才暴露上述 6 项。此为「过期产物假绿」，见 §2。

## 2. 陈旧构建护栏（本次最大价值项）

实现：`e2e/lib/source-hash.js`（内容指纹）+ `e2e/build-stamp.js`（构建后写 `dist/.build-stamp.json`）+ `e2e/lib/harness.js: assertDistFresh()` + `e2e/run.js` 在**连接模拟器之前**调用 + `package.json` 的 `build:weapp` 末尾追加指纹写入。

判据（三级，全部失败关闭、exit 1、不启动模拟器）：

| 级别 | 判据 | 说明 |
|---|---|---|
| ① 内容指纹（首选） | `dist/.build-stamp.json` 的 `src/`+`config/` sha256 ≠ 当前指纹 | 与 mtime 无关；不惧 `git checkout`/换机/时钟偏差 |
| ② mtime 兜底 | `dist/app.js` mtime < `src/`/`config/` 最新文件 mtime | 指纹缺失时退化并打印告警 |
| ③ 产物缺失 | `dist/app.js` 不存在 | 永远 |

**红证/绿证原文**（完整矩阵见 `stale-guard-redproof.txt`，全部**不需要模拟器**即可复现）：

| 场景 | 期望 | 实测 |
|---|---|---|
| 只改 mtime、内容不变（`touch src/...`） | 放行（不误报） | ✅ `guard PASS mode=content-hash`（指纹未变） |
| 内容真变了、未构建（追加一行注释） | **红** | ✅ EXIT=1「构建产物与源码不一致（内容指纹）：dist 构建于 …（指纹 fc36841d9431…）/ 当前源码指纹 56e2271ff374…」 |
| 指纹缺失 + mtime 变新 | **红**（兜底生效） | ✅ EXIT=1「构建产物陈旧：dist/app.js（…21:05:51）早于源码 …（…21:05:52）」 |
| `dist/app.js` 缺失 | **红** | ✅ EXIT=1「未找到构建产物 dist/app.js」 |
| `npm run build:weapp` 后 | 放行 | ✅ `guard PASS mode=content-hash` |

取舍（为什么不是「自动先构建」）：`dist/` 是 `build:h5`（H5 视觉回归）/手动 dev 构建共享的产物目录，e2e 悄悄重建会替换别人正在用的产物、并掩盖「忘了构建」这个信号。

**已登记边界**：① 指纹覆盖 `src/`+`config/`，不含 `project.private.config.json`（AppID 变化不触发）；② 指纹文件在 `dist/`（gitignore），**CI/新克隆首次必然无指纹** → 退回 mtime；CI 场景下「产物缺失即失败」已兜住最危险形态。

## 3. 选择器对照（旧 → 新，逐个给源码依据）

依据文件：`frontend/mini-app/src/components/chat/MessageInput.tsx`（#2953「C 端单容器双语义」，2026-09-06 合并）与 `src/pages/chat/index/index.tsx`。

| 旧选择器 | 旧期望 | `dist`/`src` 计数 | 新选择器/判据 | 源码依据 |
|---|---|---|---|---|
| `.message-input__hold-btn` | 存在（默认按住说话） | 0 / 0 | `.message-input__icon-btn--voice`（**空草稿**时存在） | MessageInput.tsx:244-254 |
| `.message-input__mode-btn` | 存在（模式切换键） | 0 / 0 | **断言其不存在**（单容器无模式切换键） | MessageInput.tsx:200-256（无 mode 分支） |
| `.message-input__btn` | 存在且文本含 `↑` | 0 / 0 | `.message-input__icon-btn--send`（**有草稿**时存在，`class` 不含 `--disabled`） | MessageInput.tsx:235-242 |
| （未使用） | — | 2 / 1 | `.message-input__container`（单容器外壳） | MessageInput.tsx:167 |
| `.message-input__textarea` | 可见（切键盘模式后） | 2 / 1 | 常驻可见 + `placeholder="发消息或按住说话"` | MessageInput.tsx:201-215 |
| `.chat-page__navbar-name` | 文本含「小布」 | 2 / 1 | 存在且非空 **且** 与空态问候语 `你好，我是{botName}` 同源 | index.tsx:110 + MessageList.tsx:58 + utils/brand.ts |

已作废契约（「默认按住说话 + 可切换键盘」）**按新契约重写**而非硬套新类名：新断言 = 「textarea 常驻 + 无模式切换键 + 空草稿语音键 / 有草稿发送键」——与 case **UI-007** 于 2026-09-06 修订后的 `data_checks` 逐条一致（该 case 已在 #2953 同步更新，故本包**未改** `cases/ui.yml`，`merge_log` 原文：「输入条单容器重构（删模式切换键、textarea 常驻、语音改右下按住键、添图统一草稿语义）」）。

## 4. 重跑结果与逐条归因

见 `runs-summary.md`（含每轮日志 `run-logs/run1..5.txt`）。要点：

- **run1**（37/1）：唯一红 `multiturn 第3轮：输入草稿后未渲染发送键` → **等待逻辑缺陷**。DOM 探针实测：`waitForStreamEnd`（文本 1s 稳定启发式）在 R2 **2043ms** 就返回，而真实流式（动作键仍是停止键）**还要再跑 66s**（`waitForStreamIdle` 66088ms）—— 流式中发送键按设计不渲染，属合法行为。修法：新增 DOM 判据 `waitForStreamIdle`（动作键不再是 `--stop`）。
- **run2**（38/0）：全绿。**但当时的绿含未被暴露的断言缺陷**（run3~run5 才暴露）—— 这正是「全绿不等于验证过」的实例，故本报告不以它作结论。
- **run3**（40/1）：红 `导航名与空态问候语同源（空态未渲染）` → **我新写断言的前置条件不成立**（e2e 进程续聊到历史会话，空态不渲染）。该红同时是这条新断言自己的红证（它不会恒绿）。修法：把断言移到「🔄 新对话」之后（空态必然存在）。
- **run4**（40/1）：红 `FormCard 必填校验生效（空表单提交被拦截）` → **旧断言宽于契约**：`required` 是 LLM 决定的可选字段（`backend/ai-agent-service/app/tools/interact.py:203 "default": False`），FormCard 只对 required 字段报错（`FormCard.tsx:37-39`），未标必填时空提交放行属合法行为；校验分支本身由单测 `frontend/mini-app/tests/form-card.test.tsx:36` 覆盖。修法：仅当表单声明了必填标记才断言拦截，否则记为信息性且**不点击提交**（避免向真实后端发出空表单消息）。
- **run5**（37/1）：红 `AI 回复第二条（SSE 流式，新内容）` → **断言竞态**：旧写法 `aiReply2 !== prevAiText` 比较文本，而发送后 AI 回复可能已开始/完成，快照到的「旧」文本就是新回复本身。修法：改按**气泡数量增加**判定（`waitForBubbleCountIncrease`）。**已改未重放**（见 §6）。

**环境/后端类失败：0 项**。所有红均为断言/等待逻辑缺陷（真行为问题 0、环境问题 0）。
观察项（非失败）：run5 的 `AI 回复第二条` 内容为「商品搜索这会儿临时有点不稳定，试了两次…」——**本轮后端工具调用有瞬时抖动**；该步骤断言只要求「新增 assistant 气泡」，不校验回复质量，故不红，但如实记录。

## 5. 证据链与证据层的两个发现

### 5-1 产物入库（#3696 结构性问题之一）

本报告 + 原始报告 + 5 轮日志 + 9 张关键截图已入库（`e2e/report.md` 与 `e2e/screenshots/` 被 gitignore，此前仓库里查不到任何小程序验收证据）。规格对齐 `acceptance/2026-09-14/merchant-ui-smoke/`。

### 5-2 ⚠️ 证据层假绿：`mp.screenshot()` 会返回过渡帧/滞后帧（可迁移判据）

1. **现象**：run3 的 `chat/03-quick-action-reply.png` 与 `chat/04-typed-reply.png` **md5 完全相同**（`f0afd2889a60a45b0807157d8c222936`），而两次抓取之间 DOM 里已多出两条消息（用户气泡 + 新 assistant 气泡，均由通过的 DOM 断言背书）⇒ **截图证据与被断言的 DOM 状态不一致**。
2. **检测方法**：连续两帧**哈希比对**（连抓直到连续两帧一致才落盘）。
3. **红证/绿证**：修复前 `chat/03 == chat/04` = `f0afd288…`（run3）；修复后 `chat/03` = `28cf6cf725f1b5faf258c600dfd3a3b7` ≠ `chat/04` = `5b4d0269c6bc71386594b16d5d9afcfd`（run5）。
4. **实测量化**：输入草稿后立即抓与 1.5s 后抓帧不同；点发送后连抓 3 张帧各不同，约 3~4.5s 才稳定（探针输出见 §5-3）。
5. **推广（可迁移判据）**：任何「截图/快照/导出物」类证据，引用前必须过两道 —— ①**稳定性**（连续两次抓取一致）②**一致性**（与同一时刻的 DOM/接口断言交叉核对）。只满足 ① 不足以作为证据引用。
6. **⚠️ 稳定 ≠ 新鲜（边界，不夸大）**：本修复保证「不是过渡帧」，**不保证**「就是当前状态帧」—— 若底层帧滞后超过等待窗口，仍会拿到一个「稳定的旧帧」（见 5-3）。

### 5-3 ❓ 存疑（无法判定）：`chat/04` 帧内容仍与同一时刻 DOM 断言不一致

视觉复核（GLM-5.3-Flash 读图，§15.5）：run5 的 `chat/04-typed-reply.png`（也等于 `04a`、`05`，md5 `5b4d0269…`）画面显示的是**算料报价那一轮**（用户气泡「帮我算一下窗帘用料和价格」+ AI 长回复 + 表单卡），而同一时刻 DOM 断言「用户消息『你好，有什么热销的窗帘推荐？』已上屏」「新增 assistant 气泡 491 字」均通过。

两种假设，**现有证据不足以判定**：
- **(a) 帧滞后 > 等待窗口**：稳定帧可能仍是「稳定的旧帧」（见 5-2 边界）。
- **(b) 消息列表未滚动到最新**：`src/components/chat/MessageList.tsx:74` 给 `ScrollView` 传的是**常量** `scrollIntoView={scrollAnchorId}`，而 `counterRef`/`scrollIntoViewRef`（第 21-36 行的「强制 scrollIntoView 更新」意图）**从未接进 JSX** ⇒ 首次渲染之后追加消息不会重新触发滚动，最新消息落在视口之外（截图里就看不到）。
  - 反证：`multiturn/05-final.png` 却显示的是**最后一轮**（订单卡片），说明至少在那里视口到了最新内容 —— 与 (b) 不矛盾但削弱其解释力。

**判决实验**（需要模拟器，归入 e393f824 落地后的联合对齐轮）：发送后同时采集 ①`page.$('.message-list__scroll')` 的 `scrollTop`/`scrollHeight` ②列表 DOM 文本 ③连拍帧，比较「视口是否到底」。当前**不得**把 `chat/04` 当作「列表状态」的证据引用（已在报告与截图中标注）。

## 6. 未重放项登记（不计入已验证）

| # | 修复 | 依据 | 重放安排 |
|---|---|---|---|
| 1 | `AI 回复第二条` 断言 | run5 红证（旧写法实测假红）→ 后经冷跑发现「气泡计数」写法同样假红 | ✅ **已闭环（follow-up PR #3720）**：改为**发送前**取基线 → 等非空且 != 基线（`waitForAssistantReply`）；红线+绿线双向证据见 `COLD-RUN.md` §A′/§B′ |
| 2 | 草稿态截图抓取时机（`typeAndSend` 的 `onDraftReady` 回调，抓在点发送**之前**） | 视觉复核指出 run5 的 `04a-draft-send-key.png` 内容为发送后状态（草稿已清空） | 同上 |
| 3 | FormCard 条件分支的**绿路径** | run3/run4 提供了红证（未标 required 时旧断言必红），条件分支的绿路径本轮未被触发 | 同上（FormCard 是否出现由 LLM 决定，不可确定性构造） |
| 4 | **可复现登录步骤**（仓库内） | 本 harness 原**不注入登录态**，依赖模拟器 storage 残留（冷环境跑不出证据） | ✅ **已闭环（follow-up PR #3720）**：`e2e/lib/login.js` 共用登录步骤 + 缺失即 `LOGIN_MISSING` 失败关闭 + 双向红证（31/31）+ **冷环境 38/38 绿证**（`COLD-RUN.md`） |
| 5 | 输入条「单行布局」断言（`__row` 三者同行） | 另一工作包的新布局会把加图键移出 `__actions`、给 textarea 加深一层父节点；`__row`/`__field` **在 main 上尚不存在** ⇒ 本包**不能**断言，否则 PR 在其合并前必红 | 待其合并后补断言（现有选择器已双版本兼容，见 README「输入条选择器只依赖稳定类名」） |

## 7. 证据清单

| 文件 | 内容 |
|---|---|
| `REPORT.md` | 本报告 |
| `stale-guard-redproof.txt` | 护栏 5 场景红证/绿证矩阵（含指纹判据「不误报」绿证、源码无残留改动自证） |
| `runs-summary.md` | 5 轮 PASS/FAIL + 红色步骤 + 归因 |
| `run-logs/run1..5.txt` | 首包 5 轮完整控制台输出（含每条断言的详情与稳定帧日志） |
| `COLD-RUN.md` | **follow-up（PR #3720）**：冷环境复跑（清 storage 从零建立登录态）38/38 绿证 + `LOGIN_MISSING` 三判据双证据 + 「基线快照晚于被测事件」假红根因 |
| `run-logs/cold-run{1,3,4}-*.txt` | 冷跑原始日志（1=清 storage 首跑 / 3=诊断加强后抓到真缺陷 / 4=修正后 38/38 绿） |
| `e2e-report-cold-run4-green.md` | 冷环境终局报告（报告头含登录态来源与期望身份、构建内容指纹） |
| `login-redproof.txt` | 共用登录步骤的双向红证（31/31，脱网脱模拟器）+ live 登录响应形状附录 |
| `screenshots-cold-run4/` | 冷环境终局关键截图（空态语音键 / 键盘输入回复 / 订单脱敏 / 转人工横幅） |
| `e2e-report-run5.md` | 脚本生成的原始步骤级报告（run5，含被测构建时间行） |
| `e2e-report-before-fix-2632.md` | 修前基线（26 PASS / 6 FAIL） |
| `screenshots/` | 9 张关键截图（内容经 GLM-5.3-Flash 视觉复核；`02-chat-typed-reply.png` 附 §5-3 存疑标注） |
