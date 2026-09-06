# Bmini App — B 端商家小程序（米宝商家端）

米高 AI 智能客服 — B 端 agent 手机版（issue #2977）

## 这是什么

面向商家员工（老板/运营/客服）的移动经营助手，独立微信小程序（与 C 端「小布」小程序不同 appid/主体）：

| Tab | 功能 | 后端接口 |
|---|---|---|
| 问米宝 | AI 对话（SSE 流式，AgentRouter 自动路由米宝） | `POST /api/chat/send`（ai-agent-service） |
| 数据 | 经营一屏：5 数字 + 待办 | `/api/admin/dashboard/stats`、`/pending-tasks` |
| 坐席 | 移动坐席：待接管队列 + 详情接管/回复/结束 | `/api/admin/agent-sessions/*` |
| 我的 | 员工信息（昵称/角色/租户）+ 退出登录 | — |

## 登录（B 端语义，与 C 端相反）

- 首次：`<Button open-type="getPhoneNumber">` 授权 → `POST /api/auth/bmini/login {code, phoneCode}`
- 后端：openid 无绑定 → 换号跨租户匹配员工（role∉customer/agent）→ 绑定 `user_identities(bmini_app)` → 签发含 permissions 的员工 JWT
- **匹配不到员工即时拒绝，绝不自动建号**（BM-003）
- 二次：openid 已绑定 → 免授权直接登录

需要真实小程序 appid/secret 时配置 `WECHAT_BMINI_APPID/SECRET`；未配置且 `WECHAT_MOCK_ENABLED=true` 时走 Mock 联调。

## 技术栈

- Taro 4.2.1 + React 18 + TypeScript + Zustand + Sass
- 复用 C 端 mini-app 基建：SSEClient（enableChunkedTransfer）/ authStore / request / chatService / 卡片组件

## 快速开始

```bash
# 1. 安装依赖
npm ci

# 2. 开发模式（微信开发者工具，需先在后端开 mock：WECHAT_MOCK_ENABLED=true）
npm run dev:weapp

# 3. 构建
npm run build:weapp

# 4. 测试
npm test
npx tsc --noEmit
```

## CI

`.github/workflows/bmini-app.yml`：typecheck + 单测（v1.3 路径门控，仅 bmini-app 相关变更触发）。
