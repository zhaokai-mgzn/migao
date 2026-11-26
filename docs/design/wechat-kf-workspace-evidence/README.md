# 微信客服工作台状态 · 页面视觉证据（issue #9202 / 母单 #9194 子项 2 前端面）

## 证明了什么

| 文件 | 形态 | 读图判定 |
|---|---|---|
| `kf-workspace.png` | 列表含一条**微信客服**会话（`channel=wechat_kf`、`sendStatus=accepted`、`2/5`）+ 一条**普通人工**会话 | 微信客服会话多一行「微信客服 · 已接收 · 额度 2/5」，与既有状态徽标同一视觉层级、不抢主信息；普通会话**整行没有**任何微信客服标识；右栏输入框可用 |
| `kf-workspace-exhausted.png` | 同一会话 `budgetUsed=5/5` | 输入区上方出现琥珀提示「微信客服 48 小时额度已用完（5/5）…」；textarea 变为禁用态（占位文案同步说明）、发送按钮置灰；无溢出、无换行错位 |

## 怎么产生的（可复现）

1. 分支 worktree 起前端 dev server：`cd frontend/admin-web && npm run dev`（:3001）
2. 用 Playwright（`tests/node_modules`）驱动真实 Chromium，**路由拦截** `/api/auth/me` 与 `/api/admin/agent-sessions*` 提供两条会话数据，页面本身是分支源码真实渲染
3. 断言 + 截图脚本：`/tmp/kf-shot.js`（临时脚本，未入库）；DOM 读数 = `微信客服已接收额度 2/5` / 普通会话 `null` / 额度用尽 `textarea.disabled === true`

## 真实登录验收（2026-11-25 21:04 +08，本机栈 + 云 dev RDS）

上表两张图是**路由拦截**下的渲染判定（L1 代理）。**同日已补真实登录**，证据如下：

| 文件 | 形态 | 读图判定 |
|---|---|---|
| `real-login-list.png` | 员工账号真实登录（`/api/auth/employee/login`，真库鉴权）→ `/agent-workspace/human-sessions`，两条会话（微信客服 `2/5` + 普通人工） | 微信客服行多一行「微信客服 · 已接收 · 额度 2/5」；普通行**整行没有**任何微信客服标识；右侧输入区可用 |
| `real-login-exhausted.png` | 同一会话 `used=5/5`（改库后刷新） | 输入区上方琥珀提示「微信客服 48 小时额度已用完（5/5）…」；textarea 禁用、占位文案同步、发送按钮置灰 |

**环境与读数（可复现）**

1. 云 dev RDS 白名单：`ALIYUN_BIN=/opt/homebrew/bin/aliyun ./scripts/dev-db-whitelist.sh --yes` ⇒ 追加 `115.194.13.103` 到 `dev_local`，TCP 复测 `Connection succeeded`；
2. `admin-api` :8080（`WECHAT_KF_ENABLED=true` + 一次性 `WECHAT_KF_SECRET_MASTER_KEY`）+ `admin-web` :3001；
3. 夹具（租户 46）：`sessions` + `agent_sessions` 两条（`acc-kf-9202` 带 `kf_session_remote` / `kf_outbox=accepted` / `kf_send_budget=2`，`acc-plain-9202` 无 kf 行）+ 临时员工 `kf_acc_tmp@ciyuan`；
4. DOM 读数：`微信客服已接收额度 2/5` / 普通会话 badge `0` / `2/5` 时 `textarea.disabled=false` / `5/5` 时 `disabled=true` 且出现 `kf-budget-exhausted`；
5. **清理自证**：六张表按 id 删除后 `SELECT` 求和 = **0**（会话 2 + 镜像/预算/outbox 各 1 + 临时账号 1 全部为 0）。

**照实登记的边界**

- 本验收证明的是「真实登录 + 真库 + 真实 admin-api 装饰链路」，**不含微信侧真实送达**（那需要真机账号，见母单 #9194 子项 3）；
- 首登会弹「功能引导」遮罩，脚本按真实用户操作点「关闭」后才继续（不是 force click 穿透）。

## 照实登记的缺口

- ~~本机到云 dev RDS 不可达~~ ⇒ **已解除**（2026-11-25 21:00 +08 追加白名单，见上节）。
- 仍缺：**微信侧真机送达**（客户发消息 → AI 回复 → 客户收到；转人工；人工结束后回 AI）。
- 确定性判据仍在 `frontend/admin-web/tests/unit/pages/human-sessions-kf.test.tsx` 与 `tests/unit/lib/kf-session-status.test.ts`（KF-029）：本目录的截图**只作补充**，不替代单测。
