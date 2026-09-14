# 小布小程序 E2E 验收（微信开发者工具）

基于官方 [miniprogram-automator](https://github.com/wechat-miniprogram/miniprogram-automator) 驱动微信开发者工具模拟器，
对已构建产物做真实链路验收（渲染 + 交互 + 真实后端 SSE 对话），并自动截图。

## 前置条件（一次性）

1. 微信开发者工具已安装（`/Applications/wechatwebdevtools.app`）并**登录账号**
2. 开发者工具：**设置 → 安全设置 → 服务端口** 开启（自动化连接必需）
3. 先构建产物：`npm run build:weapp`（产物输出到 `dist/`，含真实 AppID）

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
- **SSE 回复较慢**：真实 LLM + 工具调用，回复等待窗口 120s
- **端口**：自动化默认 9420（由 `cli auto --auto-port` 建立）；开发者工具自身 IDE 端口（如 21161）不是自动化端口
- **新增场景文件**：放 `scenarios/` 下并在 `run.js` 的 `SCENARIOS` 注册；文件头必须带 `// case_ids: ...`（QA Growth Gate）
- **产物不入库**：`screenshots/` 与 `report.md` 已 gitignore；留档请 copy **关键**截图 + 报告到 `acceptance/<日期>/mini-app-e2e/`
