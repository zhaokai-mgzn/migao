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

## 产物

| 产物 | 位置 | 说明 |
|------|------|------|
| 截图 | `e2e/screenshots/<scenario>/*.png` | 每个场景关键步骤全屏截图 |
| 报告 | `e2e/report.md` | 步骤级 PASS/FAIL 汇总（均被 gitignore，不入库） |

## 场景

| 场景 | 文件 | 覆盖 |
|------|------|------|
| 对话页 | `scenarios/chat-scenario.js` | 入口渲染、品牌导航、会话就绪、快捷操作发消息（SSE）、新对话、语音/键盘切换、键盘输入发消息 |
| 个人中心 | `scenarios/profile-scenario.js` | tab 切换、用户信息、订单/售后区块、设置项 |
| 登录页 | `scenarios/login-scenario.js` | 品牌区、一键登录按钮、协议链接；已登录自动跳转（预期） |
| 多轮表单化 | `scenarios/multiturn-scenario.js` | 推荐→选品→规格→下单信息收参、订单卡片手机号脱敏 |
| 售后链路 | `scenarios/aftersales-scenario.js` | 售后咨询快捷操作 → 真实后端 SSE 售后回复（退货/退款引导语义） |
| 转人工链路 | `scenarios/handoff-scenario.js` | 输入「我要转人工」→ SSE human_handoff → C 端「已转人工」横幅 |

## 说明与坑

- **默认语音模式**：模拟器支持录音，输入条默认「按住说话」（对应 case UI-007）；E2E 会自动点模式切换键转键盘模式再输入
- **SSE 回复较慢**：真实 LLM + 工具调用，回复等待窗口 120s
- **端口**：自动化默认 9420（由 `cli auto --auto-port` 建立）；开发者工具自身 IDE 端口（如 21161）不是自动化端口
- **新增场景文件**：放 `scenarios/` 下并在 `run.js` 的 `SCENARIOS` 注册；文件头必须带 `// case_ids: ...`（QA Growth Gate）
- **产物不入库**：`screenshots/` 与 `report.md` 已 gitignore；如需留档可手动 copy 到 docs/
