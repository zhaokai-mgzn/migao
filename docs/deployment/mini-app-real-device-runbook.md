# C 端小布小程序 · 真机调试 runbook（v1.0 已走通）

> 状态：**2026-09-15 全链路真机验证通过**（构建 → 预览扫码 → 渲染 → 真实微信登录 → SSE 对话）。
> 一次性接入：`deploy/scripts/wx-mini-test-env-setup.sh`（AppID/Secret → 服务器 → 本地私有配置）。
> 本文 = 接入之后的每日真机验证流程 + 本次 walkthrough 的全部踩坑实证。

## 0. 链路拓扑（实测确认）

```
手机微信扫码 ──预览/真机调试──> 微信开发者工具（macOS，导入 frontend/mini-app）
     │
     └─ HTTPS ─> https://app.migaozn.com   ← 云测试环境（SWAS，push main 自动部署）
                     │ nginx
                     ├─ /api/chat/*   → ai-agent-service :8000（SSE 对话）
                     └─ /api/*        → admin-api :8080（登录/客户/订单等）
```
- **小程序唯一合法域名 = `app.migaozn.com`**（nginx 已分流，见 deploy/swas/nginx.conf）
- 本地**不启**后端；DB/Redis 云 dev（RDS 白名单已含本机公网 IP，aliyun CLI 可自服务）
- 登录：`wx.login` → `POST /api/auth/mini/login {code, tenantId}` → 后端真实 code2Session
  （服务器 `.env.admin-api`：`WECHAT_MINI_APPID=wx6ee2f682c1b4822c` + Secret）

## 1. 一次性前置（人）

1. 开发者工具已装已登录；**登录微信必须是 `wx6ee2f682c1b4822c` 小程序的成员/开发者**
2. 设置 → 安全设置 → 服务端口 开启
3. `frontend/mini-app/project.private.config.json`（gitignored）含真实 AppID：
   `{ "appid": "wx6ee2f682c1b4822c", "libVersion": "3.17.2", "setting": {"urlCheck": false, ...} }`
4. `frontend/mini-app/.env.local`（gitignored）：
   ```
   TARO_APP_API_URL=https://app.migaozn.com
   TARO_APP_AI_API_URL=https://app.migaozn.com
   TARO_APP_ID=wx6ee2f682c1b4822c
   ```

## 2. 构建 + 自检

```bash
cd frontend/mini-app && npm run build:weapp
grep -o '"appid": "[^"]*"' dist/project.config.json          # wx6ee2f682c1b4822c
grep -roh "https://app.migaozn.com" dist/app.js | head -1    # 出现
grep -c "process\.env" dist/app.js                            # 0（issue #2693）
```

## 3. 出二维码（两通道）

```bash
CLI=/Applications/wechatwebdevtools.app/Contents/MacOS/cli
P="$PWD/frontend/mini-app"
# A. 预览（本次实测通道；出二维码后手机微信扫码）
"$CLI" preview --project "$P" --qr-format image --qr-output ~/Desktop/preview-qr.png --qr-size 480
open ~/Desktop/preview-qr.png
# B. 真机调试（GUI 工具栏按钮；本次按钮失灵，见 §4.5，修好后优先用——可跳过域名校验）
```
> 二维码有有效期（通常数小时）；每次改代码后重新 build + preview 出新码。

## 4. 踩坑记录（2026-09-15 实测，全部实证）

### 4.1 ⚠️ project.config.json 的 es6/enhance 被 DevTools 翻转 → 白屏
- **现象**：页面空白 / `Maximum call stack size exceeded`（`$` 自递归）→ `h.E.app.mount` 为 null；底部 tabBar 在、内容空
- **根因**：`setting.es6/enhance` 被开发者工具打开/编译时**静默改为 true**（仓库原值 false/false），「增强编译」与 Taro 4.2.1 产物叠加不兼容
- **修复**：`git checkout -- frontend/mini-app/project.config.json` → close+open 重编译；实测 reopen 后保持 false 不回弹
- **判据**：提交前 `git status` 见 `M frontend/mini-app/project.config.json` 且 es6/enhance=true ⇒ 立即还原，不提交

### 4.2 ⚠️ 预览版登录无反应 → request 合法域名校验
- **现象**：真机预览版点击「微信一键登录」无反应（实际按钮进「登录中…」，请求**没到服务器**——admin-api 日志零 code2Session）
- **根因**：预览/开发版在手机上强制校验 request 合法域名；`app.migaozn.com` 未配置时 wx.request 被微信拦截
- **修复（立即）**：手机端打开小程序的 **开发调试**（右上角胶囊「···」→ 开发调试 → 打开调试）→ 重启后跳过域名校验 + 出现 vConsole
- **修复（永久）**：mp.weixin.qq.com → 开发管理 → 开发设置 → 服务器域名 → request 合法域名添加 `https://app.migaozn.com`（imageUpload 走 Taro.uploadFile，uploadFile 域名同加）
- **判据**：服务器日志 `grep code2Session admin-api`——真机点登录后应出现调用记录

### 4.3 模拟器渲染正常 ≠ 真机渲染正常
- 模拟器（Electron V8）宽容，真机（iOS JSCore + 手机基础库）严格；真机空白时先查服务器有无 code2Session——没有 = 崩在登录前渲染

### 4.4 首页商品卡 = 设计功能（NewArrivals 空态新品推荐），非残留
- 首次误判为 e2e 残留；实为 `NewArrivals.tsx` 空态欢迎屏新品推荐位（点商品卡唤起对话）。已按用户意见重设计对齐 QuickActions 卡片语言（UI-042 相关包）

### 4.5 GUI「真机调试」按钮点不动（无二维码无提示）
- **现象**：工具栏「真机调试」点击无任何反应；`cli preview` 通道正常
- **处置**：本次用 `cli preview`（§3-A）绕过；根治待 DevTools 版本/窗口状态问题（疑似自动化探测会话残留占用，close+open 后仍复现一次）

### 4.6 iOS USB 真机调试通道不稳
- 日志见 `ios-adapter init error` + `Device disconnected: InternalError`；扫码/推送不稳时改「真机调试 → 局域网调试」（手机连同一 WiFi）

## 5. 真机验证清单（本次实测通过 ✅）

- [x] 预览二维码扫码 → 登录页渲染（手机 8.0.76 / 基础库 3.17.3）
- [x] 开启开发调试后点「微信一键登录」→ 后端 `code2Session 成功`（19:47 实证 openid=o8JhL3Yx8xXjHfMebMAWdjP-TXis）
- [x] 对话 → SSE 流式回复（19:48~19:57 六轮客户消息，小布 persona，含下单流程「继续下单 9231 遮光窗帘」）
- [x] 交互卡（choice 选择卡）渲染；下单规格收集部分回复退化为纯文本（agent 卡片一致性，见 §6 待办）

## 6. 待办（walkthrough 产出的问题清单）

| # | 问题 | 状态 |
|---|---|---|
| P1 | C 端气泡 markdown 裸奔（**粗体**/- 列表） | ✅ 已修：`src/utils/richText.ts` + MessageBubble 按行渲染（UI-042，tests 9/9） |
| P3 | 选择卡选项行触控目标偏小（~22pt） | ✅ 已修：ChoiceCard option `min-height: 88px`（44pt 规范） |
| P4 | 新品推荐卡片风格突兀 | ✅ 已修：NewArrivals 对齐 QuickActions 卡片语言 |
| P2 | 交互卡时有时无（order.md 已强制 choice 卡但 LLM 偶发纯文本） | ⏳ 待评测环（OR-016 下单）复现归因后修 prompt/协议 |

## 7. 服务器侧证据观察点（AI 可自证）

```bash
aliyun swas-open run-command --command-content "docker compose -f /opt/migao-deploy/docker-compose.yml logs --since 30m admin-api 2>/dev/null | grep -a 'code2Session'" \
  --instance-id b23c69e599524b1da719734f72e6a0e3 --biz-region-id cn-hangzhou --name check --type RunShellScript
# 同理 ai-agent 日志 grep 'Message received'（排除 user_admin_001 = 后台探针身份）
```
- 2026-09-15 19:47 实证：`code2Session 成功: openid=o8JhL3Yx8xXjHfMebMAWdjP-TXis`（真机登录）
