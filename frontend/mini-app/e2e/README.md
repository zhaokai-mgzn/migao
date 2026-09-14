# 小布小程序 E2E 验收（微信开发者工具）

基于官方 [miniprogram-automator](https://github.com/wechat-miniprogram/miniprogram-automator) 驱动微信开发者工具模拟器，
对已构建产物做真实链路验收（渲染 + 交互 + 真实后端 SSE 对话），并自动截图。

## 前置条件（一次性）

1. 微信开发者工具已安装（`/Applications/wechatwebdevtools.app`）并**登录账号**
2. 开发者工具：**设置 → 安全设置 → 服务端口** 开启（自动化连接必需）
3. 先构建产物：`npm run build:weapp`（产物输出到 `dist/`，含真实 AppID）
4. 无需手工登录：`run.js` 会**自动建立登录态**（见下「登录前置步骤」），失败则直接退出

### 登录前置步骤（单一事实源 `e2e/lib/login.js`，失败关闭）

C 端页面判定登录只查 storage（`checkAuth()` → `getToken()`，`src/store/authStore.ts:137`）。

**为什么不能走真实微信登录**：产品链路是 `Taro.login()` → `POST /api/auth/mini/login`
（`src/utils/auth.ts:18-34`），但在**微信开发者工具模拟器里该 code 被后端判
`WECHAT_API_ERROR: code 无效`**（2026-09-14 实测）——这是**环境限制，不是产品缺陷**。
⇒ e2e 改用等价方式建立会话：`POST /api/auth/sms/login`（测试环境短信网关 bypass）取 JWT，
再写入 C 端真正读取的 storage key：

| key | 产品读取点 | 值 |
|---|---|---|
| `auth_token` | `src/utils/auth.ts:63` `getToken()` | JWT |
| `auth_user` | `src/utils/auth.ts:74` `getUser()`（`app.tsx:20` → `initialize()` 恢复 `user`；导航名/副标题读它的 `botName`/`tenantName`） | `JSON.stringify(user)` |
| `tenant_id` | `src/utils/auth.ts:87` `getTenantId()` | number（已把 admin-api 的 `tenantId` 归一化为 snake_case） |
| `auth-store` | zustand persist 快照（`authStore.ts:153`） | `{"state":{...},"version":0}` |

> ⚠️ **注入形状 = 逐字镜像生产存下的形状**（不补字段、不改名）。唯一判据是**生产实际存下的那段 JSON**，
> 与类型声明是否准确**无关**：生产 `src/utils/auth.ts` 把接口返回的 `user` **原样**
> `JSON.stringify` 存进 `auth_user`，而 admin-api 的 `LoginResponse.UserInfo` 是 **camelCase**。
> **harness 不得在注入时补字段/改名让断言过** —— 那会造出「harness 形状 ≠ 生产形状」，
> 将来读到该字段的代码会 **e2e 绿、生产挂**（又一种证据层假绿）。
> 历史缺陷（曾声明 `User.tenant_id` 而后端不提供，已由 PR #3727 修为 `tenantId`）只是**当时的一个实例**；
> 这条纪律与类型是否已修无关，红证里「未含 `tenant_id`」「键集合 == 响应原物」两条**永久保留**。
> 契约不一致由**产品侧**修复收口（契约修复包 PR #3727；仓库级 H5 spec 的同类注入由它一并修），本 harness 只镜像。
> **权威形状已 live 复核**（2026-09-14）：`data.user` 键 = `botName, id, identityType, nickname, role, roles,
> tenantId, tenantName`（无 `tenant_id`；实测 `tenantId=1`/`tenantName=词元通达`/`botName=光头强`/`identityType=sms`）。
> null 字段（如 `avatar`）可能被后端省略 ⇒ 原物镜像自动正确。
>
> **能复现 / 不能复现（边界）**：✅ 登录态本身 + 租户级数据；❌ **微信顾客身份**（`identityType=sms` 是
> 短信/后台身份）⇒「顾客本人数据隔离」类断言不能由这条会话背书（由 agent-eval CH-011 覆盖）。
> 独立的 storage key `tenant_id` 是另一回事：生产存**登录请求的 tenantId**，短信登录无该参数 ⇒
> 取会话的 `user.tenantId`（语义同为「会话所属租户」），已在代码注释里声明该差异。

**⛔ 严禁**为了绕过上述环境限制去改产品鉴权代码（`src/store/authStore.ts` / `src/utils/auth.ts` /
admin-api 鉴权）；本步骤只服务于测试环境。

**行为（失败关闭）**：
- storage 里已有**有效** `auth_token`（三段 JWT 且未过期）⇒ 直接用，报告里标注
  「**来自模拟器 storage 残留**，非本 harness 建立」——提醒读者这份证据的可复现性取决于该残留；
- 无 / 空 / 非法 / 已过期 ⇒ 自动短信登录注入 → `reLaunch` → **重启模拟器会话让 App 冷启动**
  （`app.tsx:20` 的 `initialize()` 每次 App 装载只跑一次，光 reLaunch 不会重跑）→ 复核；
- 注入也失败 ⇒ **`LOGIN_MISSING` + 退出码 1**（绝不带着不确定的登录态继续跑，产出「环境残留给的绿」）。

**环境变量**（都有默认值，见 `e2e/lib/login.js` DEFAULTS）：
`E2E_LOGIN_API_BASE`（默认 `https://app.migaozn.com`）、`E2E_LOGIN_PHONE`（默认 `13800138000`）、
`E2E_LOGIN_CODE`（默认 `123456`）。

**冷环境复跑（证明证据不依赖环境残留）**：
```bash
# 清空模拟器 storage（去掉残留登录态）→ 由共用步骤从零建立 → 全量跑
cd frontend/mini-app && E2E_COLD_LOGIN=1 npm run test:e2e
```
`E2E_COLD_LOGIN` 走的是 `wx.clearStorageSync()`（**全量清**）而非逐键删 ⇒ 将来新增的一次性/引导类
storage key（如输入条一次性引导 `voice_hint_seen`）**天然会被清掉**，不会因残留而"跳过引导"。

**`e2e/report.md` 是单槽产物**：每次运行覆盖；**任何前置失败（陈旧构建 / `LOGIN_MISSING`）会把它删掉**
再 exit 1 —— 只做到"不产出新报告"不够，上一轮的旧报告同样会被下游当成本轮结论（"陈旧产物被当结论"的假绿）。
需要留档请在跑完后 copy 出去（`acceptance/<日期>/mini-app-e2e/`）。

**红证（双向，不需要模拟器/网络）**：
```bash
cd frontend/mini-app && node e2e/login-redproof.js   # 退出码 0 = 双向红证通过
```
覆盖：缺失/空/非 JWT/过期 ⇒ **红**（不能恒真）；有效 ⇒ **pass**（不能恒红）；
注入成功 ⇒ 4 个 key 真的落库；注入失败/过期 ⇒ `LOGIN_MISSING`。

## 运行

```bash
npm run test:e2e
```

### 陈旧构建护栏（失败关闭，2026-09-14 新增）

`run.js` 在连接模拟器**之前**校验构建产物与源码是否一致，不一致 → **直接报错退出**
（提示 `请先 npm run build:weapp`），不跑任何场景。判据两级：

| 级别 | 判据 | 何时生效 |
|---|---|---|
| ① **内容指纹（首选）** | `dist/.build-stamp.json`（由 `npm run build:weapp` 末尾的 `e2e/build-stamp.js` 写入）里的 `src/`+`config/` sha256 指纹 ≠ 当前指纹 | 有指纹即生效；与 mtime 无关，不惧 `git checkout`/换机/时钟偏差 |
| ② mtime 兜底 | `dist/app.js` mtime < `src/`、`config/` 最新文件 mtime | 指纹缺失（旧流程产物/被删）时退化，并打印告警 |
| ③ 产物缺失 | `dist/app.js` 不存在 | 永远 |

为什么必须失败关闭：2026-09-14 实测过 `dist/` 停留在 09-04 而 `src/` 已是 09-06 重设计后的版本 ——
「旧脚本 + 旧构建」自洽跑出 **35/36 全绿**，却完全没验证当前代码；重建后才暴露一批过期选择器。
这是 `migao-acceptance` v1.2 的「假绿」形态（验证对象与被测代码错配），靠人自觉不可靠，必须机器拦。

不选「自动先构建」的原因：① `dist/` 是**多流程共享**的产物目录（H5 视觉回归 `build:h5`、手动
dev 构建都写这里），e2e 悄悄重建会替换掉别人正在用的产物，副作用不可见；② 自动构建会掩盖
「忘了构建」这个信号 —— 而该信号本身就是要暴露的问题；③ 构建虽快（实测 ~5s），但受本地 Taro/env
影响，产物可能与本仓库声明的不一致，把「测到的到底是哪份产物」重新变成未知。

**已知边界**：① 指纹只覆盖 `src/` + `config/`，不含 `project.private.config.json` 等本地私有配置
（AppID 变化不触发护栏）；② 指纹文件在 `dist/` 内（gitignore），**CI/新克隆首次运行必然无指纹** →
退回 mtime 判据；CI 场景下「`dist` 缺失即失败」已兜住最危险的那种（对着不存在/别的产物跑）。

### 截图证据的「稳定帧」要求（2026-09-14 新增，证据层假绿）

`mp.screenshot()` 在 UI 刚变化后会返回**过渡帧/滞后帧**：实测「输入草稿后立即抓」与「1.5s 后抓」
帧不同；「点发送后连抓 3 张」帧各不同，约 3~4.5s 才稳定。直接落盘会让**截图证据与被断言的
DOM 状态不一致**（2026-09-14 实证：`chat/03` 与 `chat/04` 两帧 **md5 完全相同**，而两次抓取之间
DOM 里已多出两条消息）。故 `capture()` 连抓直到**连续两帧完全一致**才落盘。

⚠️ **稳定 ≠ 新鲜**：该机制保证「不是过渡帧」，**不保证**「就是当前状态帧」（若底层帧滞后超过
等待窗口，仍可能拿到一个「稳定的旧帧」）。**可迁移判据**：任何「截图/快照/导出物」类证据，
引用前都要过两道 —— ①连续两次抓取一致（稳定性）；②与同一时刻的 DOM/接口断言交叉核对
（一致性）。只满足 ① 不足以作为证据引用。


## 产物

| 产物 | 位置 | 说明 |
|------|------|------|
| 截图 | `e2e/screenshots/<scenario>/*.png` | 每个场景关键步骤全屏截图 |
| 报告 | `e2e/report.md` | 步骤级 PASS/FAIL 汇总（含被测构建时间；均被 gitignore，不入库） |
| **留档证据** | `acceptance/<日期>/mini-app-e2e/`（REPORT.md + 关键截图） | **入库**，供追溯（issue #3696：此前仓库里查不到任何小程序验收证据） |

## 场景

| 场景 | 文件 | 覆盖 |
|------|------|------|
| 对话页 | `scenarios/chat-scenario.js` | 入口渲染、品牌导航（botName/租户副标）、会话就绪、快捷操作发消息（SSE）、新对话、单容器输入条（UI-007）、键盘输入发消息 |
| 个人中心 | `scenarios/profile-scenario.js` | tab 切换、用户信息、订单/售后区块、设置项 |
| 登录页 | `scenarios/login-scenario.js` | 品牌区、一键登录按钮、协议链接；已登录自动跳转（预期） |
| 多轮表单化 | `scenarios/multiturn-scenario.js` | 推荐→选品→下单收参、订单卡片手机号脱敏 |
| 售后链路 | `scenarios/aftersales-scenario.js` | 售后咨询快捷操作 → 真实后端 SSE 售后回复（退货/退款引导语义） |
| 转人工链路 | `scenarios/handoff-scenario.js` | 输入「我要转人工」→ SSE human_handoff → C 端「已转人工」横幅 |

## 说明与坑

- **输入条是单容器双语义（`#2953`，2026-09-06 重设计）**：**没有**「语音/键盘模式切换键」，
  `.message-input__textarea` 常驻可见，右下动作组随草稿自适应 —— 空草稿=`.message-input__icon-btn--voice`、
  有草稿=`.message-input__icon-btn--send`、流式中=`--stop`。选择器唯一依据是
  `src/components/chat/MessageInput.tsx`；旧类名（`--hold-btn`/`--mode-btn`/`--btn`）**源码与产物里都不存在**，
  照抄旧类名 = 断言恒红（假红）。对应 case UI-007。
- **发送键需要先有草稿才渲染**：先 `textarea.input(文本)`，再等 `.message-input__icon-btn--send`。
  用 harness 的 `typeAndSend()`（发送键缺失/禁用一律返回 `ok=false`，禁止 `if (btn) tap()` 静默跳过 ——
  跳过会让「消息没发出」伪装成「后端无回复」）。
- **输入条选择器只依赖「稳定类名」**：`__container` / `__textarea` / `__icon-btn`（含
  `--voice`/`--send`/`--stop`/`--disabled`）。**不要**依赖 `__actions` 的子元素数量或
  textarea 的父层结构 —— 另一工作包正在把输入条从「column 两行」改为「`__row` 单行
  （加图键 → `__field` > Textarea → `__actions` 主动作键）」，那会移动加图键、给 textarea
  加深一层父节点。所有输入条访问都收敛在 `lib/harness.js` 的 `probeInputBar()` /
  `typeAndSend()`，**该布局落地后只需复核这一个文件**（届时可另加「三者同行」的 `__row`
  断言；现在**不能**加，`__row`/`__field` 在 main 上还不存在）。
- **SSE 回复较慢**：真实 LLM + 工具调用，回复等待窗口 120s。判「本次发送是否收到回复」只能用
  `harness.waitForAssistantReply(page, 发送前基线)`：**基线必须在发送前取**，否则「比较文本」与
  「比较气泡数量」两种写法都会假红（助手气泡在流式一开始就已创建；发送后取到的"旧文本"就是新回复本身）。
  2026-09-14 实测：同一断言先后以这两种方式假红（`acceptance/2026-09-14/mini-app-e2e/COLD-RUN.md` §B′）。
- **端口**：自动化默认 9420（由 `cli auto --auto-port` 建立）；开发者工具自身 IDE 端口（如 21161）不是自动化端口
- **新增场景文件**：放 `scenarios/` 下并在 `run.js` 的 `SCENARIOS` 注册；文件头必须带 `// case_ids: ...`（QA Growth Gate）
- **产物不入库**：`screenshots/` 与 `report.md` 已 gitignore；留档请 copy **关键**截图 + 报告到 `acceptance/<日期>/mini-app-e2e/`
