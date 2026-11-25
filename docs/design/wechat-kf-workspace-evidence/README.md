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

## 照实登记的缺口

- **不是「真实登录」验收**：本机到云 dev RDS（`pgm-bp1p7w92k81ob5to-pub.pg.rds.aliyuncs.com:5432`）**TCP 不可达**（6s 超时），且本安装里 `aliyun` / `docker` 均被禁用 ⇒ 无法用 `./scripts/dev-db-whitelist.sh --yes` 追加白名单、也无法本地起 PG 替代 ⇒ 登录链路（`/api/auth/me` 走真库）不可用。
- 因此本目录证据 = **渲染层判定（L1 代理）**，不是端到端登录验收。**重启条件**：本机公网 IP 进入 RDS `dev_local` 白名单（或提供可达的 dev 环境）后，按 `migao-dev-flow` §15.7 重跑真实登录 + 截图。
- 确定性判据仍在 `frontend/admin-web/tests/unit/pages/human-sessions-kf.test.tsx`（KF-029，含红证）：本目录的截图**只作补充**，不替代单测。
