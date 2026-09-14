# 小布小程序 E2E 验收报告

- 时间: 2026/9/14 21:01:36
- 环境: 微信开发者工具模拟器 + app.migaozn.com 测试环境
- 被测构建: dist/app.js 构建时间 2026/9/14 20:34:56（src/config 最新变更 src/components/chat/MessageInput.tsx @ 2026/9/14 20:34:47）

## 对话页验收 — ❌ 1 项失败

| # | 步骤 | 结果 | 详情 |
|---|------|------|------|
| 1 | 入口页面为对话页 | ✅ | path=pages/chat/index/index |
| 2 | 导航栏客服名已渲染（botName 非空） | ✅ | name=光头强 |
| 3 | 导航栏副标（租户名·智能购物助手） | ✅ | text=词元通达 · 智能购物助手 |
| 4 | 会话初始化完成（快捷操作/空态/消息任一出现） | ✅ | quickActions=false empty=false bubbles=2 |
| 5 | 「🔄 新对话」回到空会话（快捷操作重现） | ✅ | 快捷操作已重现 |
| 6 | 导航名与空态问候语同源（同一 botName） | ✅ | nav=光头强 empty=你好，我是光头强 |
| 7 | 快捷操作卡片存在（算料报价/查订单/找产品/售后咨询/查物流） | ✅ | items=5 first=🧮算料报价 |
| 8 | 点击快捷操作后用户消息上屏 | ✅ | 帮我算一下窗帘用料和价格20:58 |
| 9 | AI 助手回复（SSE 流式） | ✅ | 🤖 AI 助手亲，帮您算窗帘用料和价格没问题~ 需要先了解几个信息，您填一下就好👇亲，表格已经发给您啦~ 填好窗户尺…(len=269) |
| 10 | 输入条单容器：textarea 常驻且无模式切换键 | ✅ | textarea=true container=true modeSwitch=false holdBtn=false |
| 11 | placeholder「发消息或按住说话」（双语义） | ✅ | placeholder=发消息或按住说话 |
| 12 | 空草稿时右下为「按住说话」语音键 | ✅ | message-input__icon-btn--voice 存在 |
| 13 | 有草稿 → 语音键收起 + 发送键出现且激活（自适应动作键） | ✅ | voiceBefore=true voiceAfter=false sendClass=message-input__icon-btn message-input__icon-btn--send streamIdleWait=4ms |
| 14 | 键盘输入消息上屏（新气泡+新内容） | ✅ | 你好，有什么热销的窗帘推荐？20:58 |
| 15 | AI 回复第二条（SSE 流式，新内容） | ❌ | 🤖 AI 助手亲，为您挑了几款店里的热销款~ 👇  🛒 **热销窗帘推荐**  1. **遮光窗帘** · ¥19…(len=491) |

截图：
- `chat/02-ready.png`
- `chat/03-quick-action-reply.png`
- `chat/04a-draft-send-key.png`
- `chat/01-entry.png`
- `chat/02-ready.png`
- `chat/03-quick-action-reply.png`
- `chat/04-typed-reply.png`
- `chat/05-final.png`

## 个人中心页验收 — ✅ PASS

| # | 步骤 | 结果 | 详情 |
|---|------|------|------|
| 1 | 切换到「我的」tab | ✅ | path=pages/profile/index/index |
| 2 | 个人中心页渲染 | ✅ | profile-page 存在 |
| 3 | 用户信息区展示 | ✅ | nickname=微信用户 |
| 4 | 「我的订单」区块 | ✅ | 存在 |
| 5 | 「我的售后」区块 | ✅ | 存在 |
| 6 | 设置项（关于我们/隐私协议） | ✅ | labels=关于我们 / 隐私协议 |

截图：
- `profile/01-profile.png`
- `profile/02-profile-full.png`

## 登录页验收 — ✅ PASS

| # | 步骤 | 结果 | 详情 |
|---|------|------|------|
| 1 | 登录页可达 | ✅ | 当前页=pages/chat/index/index（已登录自动跳转，预期行为） |

截图：
- `login/01-login-redirected.png`

## 多轮表单化交互验收 — ✅ PASS

| # | 步骤 | 结果 | 详情 |
|---|------|------|------|
| 1 | 页面就绪 | ✅ | path=pages/chat/index/index |
| 2 | 第1轮：推荐窗帘收到回复（卡片或文本） | ✅ | 出现 .message-bubble--assistant |
| 3 | 第2轮：选品规格收到回复（新气泡） | ✅ | 已回复 |
| 4 | 第3轮：下单意图收到回复 | ✅ | 已回复（信息性：form-card=未出现，纯文本收参同属合法） |
| 5 | S5：订单卡片手机号脱敏 | ✅ | 脱敏格式匹配 |

截图：
- `multiturn/01-recommend.png`
- `multiturn/02-form-card.png`
- `multiturn/03-confirm-card.png`
- `multiturn/04-order-card.png`
- `multiturn/05-final.png`

## 售后咨询链路验收 — ✅ PASS

| # | 步骤 | 结果 | 详情 |
|---|------|------|------|
| 1 | 入口页面为对话页 | ✅ | path=pages/chat/index/index |
| 2 | 新对话后快捷操作重现 | ✅ | 快捷操作已出现 |
| 3 | 售后咨询快捷卡片存在 | ✅ | label=🤝售后咨询 |
| 4 | 点击后用户消息上屏（售后意图） | ✅ | 我想咨询售后问题21:00 |
| 5 | AI 售后回复（SSE 流式） | ✅ | 🤖 AI 助手亲您好，我是米高窗帘的售后客服小布😊 售后问题都能帮您处理～  我先帮您看一下您名下的订单，您可以直接点选要售后的那一笔：亲，上面点选一下要售…(len=393) |
| 6 | 回复语义与售后相关 | ✅ | 含售后语义 |

截图：
- `aftersales/01-aftersales-reply.png`
- `aftersales/02-final.png`

## 转人工链路验收 — ✅ PASS

| # | 步骤 | 结果 | 详情 |
|---|------|------|------|
| 1 | 入口页面为对话页 | ✅ | path=pages/chat/index/index |
| 2 | 输入框可用（单容器 textarea 常驻） | ✅ | textarea 可见 |
| 3 | 用户消息上屏（转人工意图） | ✅ | 我要转人工21:01 |
| 4 | AI 回复（转人工处理话术） | ✅ | 🤖 AI 助手亲，收到您的转人工请求啦～ 不过现在是非营业时间，人工客服已经休息了 😴  您先别急，可以这样做： - 📝 **直接留言**：把您遇到的问题… |
| 5 | C 端「已转人工」横幅出现 | ✅ | handoff 横幅存在 |

截图：
- `handoff/01-handoff.png`
- `handoff/02-final.png`

## 汇总

| 结果 | 数量 |
|------|------|
| ✅ PASS | 37 |
| ❌ FAIL | 1 |
| 判定 | **存在失败项，需修复** |
