# 小程序 e2e 逐轮摘要（2026-09-14，工作区 SHA aa64bb98 = verify-h）

每轮都是**重建后**的完整 `npm run test:e2e`（微信开发者工具模拟器 + 真实后端 SSE）。

| 轮次 | 日志 | PASS | FAIL | 红的那一步 | 归因 |
|---|---|---|---|---|---|
| run0（修前基线，主会话） | e2e-report-before-fix-2632.md | 26 | 6 | 导航栏品牌名 / 输入条默认语音模式 / 发送按钮激活 / multiturn 第1轮90s无回复 / 第2轮90s无回复 / 转人工未找到发送按钮 | **全部为断言/选择器问题（假红）** |
| run1 | run-logs/run1.txt | 37 | 1 | multiturn 第3轮：输入草稿后未渲染发送键 | 断言/等待逻辑（流式未结束，见 REPORT §4-1） |
| run2 | run-logs/run2.txt | 38 | 0 | — | 全绿（但含 run3~run5 暴露的断言缺陷，属「当时看不出的假绿」） |
| run3 | run-logs/run3.txt | 40 | 1 | 导航名与空态问候语同源（空态未渲染） | **我新写的断言前置条件不成立**（进程续聊到历史会话）——已修 |
| run4 | run-logs/run4.txt | 40 | 1 | FormCard 必填校验生效（空表单提交被拦截） | **旧断言宽于契约**（LLM 未标 required）——已修 |
| run5 | e2e-report-run5.md | 37 | 1 | AI 回复第二条（SSE 流式，新内容） | **断言竞态**（文本比对）——已改，**未重放** |

## 关键红/绿原文（run5 节选）
```
  7:✅ 构建新鲜度检查通过：dist/app.js 构建时间 2026/9/14 20:34:56（src/config 最新变更 src/components/chat/MessageInput.tsx @ 2026/9/14 20:34:47）
  9:✅ 已连接模拟器
  10:✅ 页面就绪: pages/chat/index/index
  14:  ✅ 入口页面为对话页 — path=pages/chat/index/index
  15:  ✅ 导航栏客服名已渲染（botName 非空） — name=光头强
  16:  ✅ 导航栏副标（租户名·智能购物助手） — text=词元通达 · 智能购物助手
  17:  ✅ 会话初始化完成（快捷操作/空态/消息任一出现） — quickActions=false empty=false bubbles=2
  18:  ✅ 「🔄 新对话」回到空会话（快捷操作重现） — 快捷操作已重现
  19:  ✅ 导航名与空态问候语同源（同一 botName） — nav=光头强 empty=你好，我是光头强
  20:  ✅ 快捷操作卡片存在（算料报价/查订单/找产品/售后咨询/查物流） — items=5 first=🧮算料报价
  21:  ✅ 点击快捷操作后用户消息上屏 — 帮我算一下窗帘用料和价格20:58
  22:  ✅ AI 助手回复（SSE 流式） — 🤖 AI 助手亲，帮您算窗帘用料和价格没问题~ 需要先了解几个信息，您填一下就好👇亲，表格已经发给您啦~ 填好窗户尺…(len=269)
  23:  ✅ 输入条单容器：textarea 常驻且无模式切换键 — textarea=true container=true modeSwitch=false holdBtn=false
  24:  ✅ placeholder「发消息或按住说话」（双语义） — placeholder=发消息或按住说话
  25:  ✅ 空草稿时右下为「按住说话」语音键 — message-input__icon-btn--voice 存在
  26:  ✅ 有草稿 → 语音键收起 + 发送键出现且激活（自适应动作键） — voiceBefore=true voiceAfter=false sendClass=message-input__icon-btn message-input__icon-btn--send streamIdleWait=4ms
  28:  ✅ 键盘输入消息上屏（新气泡+新内容） — 你好，有什么热销的窗帘推荐？20:58
  29:  ❌ AI 回复第二条（SSE 流式，新内容） — 🤖 AI 助手亲，为您挑了几款店里的热销款~ 👇  🛒 **热销窗帘推荐**  1. **遮光窗帘** · ¥19…(len=491)
  33:  ✅ 切换到「我的」tab — path=pages/profile/index/index
  34:  ✅ 个人中心页渲染 — profile-page 存在
  35:  ✅ 用户信息区展示 — nickname=微信用户
  36:  ✅ 「我的订单」区块 — 存在
  37:  ✅ 「我的售后」区块 — 存在
  38:  ✅ 设置项（关于我们/隐私协议） — labels=关于我们 / 隐私协议
  43:  ✅ 登录页可达 — 当前页=pages/chat/index/index（已登录自动跳转，预期行为）
  46:  ✅ 页面就绪 — path=pages/chat/index/index
  47:  ✅ 第1轮：推荐窗帘收到回复（卡片或文本） — 出现 .message-bubble--assistant
  49:  ✅ 第2轮：选品规格收到回复（新气泡） — 已回复
  50:  ✅ 第3轮：下单意图收到回复 — 已回复（信息性：form-card=未出现，纯文本收参同属合法）
  51:  ✅ S5：订单卡片手机号脱敏 — 脱敏格式匹配
  55:  ✅ 入口页面为对话页 — path=pages/chat/index/index
  56:  ✅ 新对话后快捷操作重现 — 快捷操作已出现
  57:  ✅ 售后咨询快捷卡片存在 — label=🤝售后咨询
  58:  ✅ 点击后用户消息上屏（售后意图） — 我想咨询售后问题21:00
  59:  ✅ AI 售后回复（SSE 流式） — 🤖 AI 助手亲您好，我是米高窗帘的售后客服小布😊 售后问题都能帮您处理～  我先帮您看一下您名下的订单，您可以直接点选要售后的那一笔：亲，上面点选一下要售…(len=393)
  60:  ✅ 回复语义与售后相关 — 含售后语义
  64:  ✅ 入口页面为对话页 — path=pages/chat/index/index
  65:  ✅ 输入框可用（单容器 textarea 常驻） — textarea 可见
  66:  ✅ 用户消息上屏（转人工意图） — 我要转人工21:01
  67:  ✅ AI 回复（转人工处理话术） — 🤖 AI 助手亲，收到您的转人工请求啦～ 不过现在是非营业时间，人工客服已经休息了 😴  您先别急，可以这样做： - 📝 **直接留言**：把您遇到的问题…
  68:  ✅ C 端「已转人工」横幅出现 — handoff 横幅存在
  72:📋 E2E 验收汇总:
  73:  ✅ PASS: 37 项
  74:  ❌ FAIL: 1 项
```
