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

## 登录（issue #5485 起＝账号密码）

- 员工在登录页填 **`用户名@企业编码`**（如 `zhangsan@acme`）+ **密码** →
  `POST /api/auth/employee/login {identifier, password}`（`src/utils/auth.ts` 的 `employeeLogin`）
- **租户只由标识里的企业编码解析**（服务端）：前端**不解析租户、不传 `tenantId`**；
  `user.tenantId` 由服务端回填进本地存储并用于后续请求头
- 失败（企业编码不存在 / 用户名不存在 / 密码错）统一 **同一 401 同一文案**（反枚举），前端原样展示
- 账号由企业管理员在管理后台设置（含初始密码）；**首登强制改密**——改密前业务接口 403，
  本包**没有改密页**，只能提示「首次登录请到管理后台修改密码」（缺口已登记，见 issue #5485）
- 原「`<Button open-type="getPhoneNumber">` 授权 → 跨租户匹配员工 → 绑定 openid → 二次免密」**整条退场**：
  `POST /api/auth/bmini/login` 已废弃（旧版调用会拿到明确拒绝 + 引导文案，不是 404）；
  退场由 `tests/bmini-login-retired.test.ts` 元守卫看住（再次出现即红）

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
