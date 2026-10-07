# 登录页 / 首次改密页「产品定位文案」验收证据（issue #6463）

## 改了什么

米高自身的定位文案由「企业级AI电商管理解决方案」改为「**企业级AI经营管理平台**」（用户 2026-10-07 裁定），
落点三处：登录页副标题、首次登录改密页副标题、`app/layout.tsx` 的 `<title>` 与 SEO description。

## 证据（怎么复算）

```bash
# ① 真实渲染：本分支构建的 dev server（:3001）
cd frontend/admin-web && npm run dev -- -p 3001
# ② 官方载体：登录页形态自检（不登录 / 不截图）—— 工具与页面指纹一致性
MIGAO_REPO_ROOT="$PWD" node "$HOME/migao-dev-preset-anchor/skills/migao-dev-flow/scripts/ui-multimodal-acceptance.mjs" \
  --login-shape-check --site http://localhost:3001
# ③ 截图 + 逐字文本（本目录脚本；@playwright/test 取自 <repo>/tests/node_modules）
node acceptance/2026-10-07-positioning-copy/shot-login-copy.mjs "$PWD" "$PWD/acceptance/2026-10-07-positioning-copy/out" http://localhost:3001
```

- 被测 SHA：见 `out/tested-sha.txt`（= 分支提交，dev server 跑的就是它）。
- 官方载体读数：`✅ 登录页形态自检通过：命中指纹 login-tabs-v5485（rc=0）`。
- 脚本读数（`out/summary.json`）：

```json
{
  "loginUrl": "http://localhost:3001/login",
  "loginTitle": "米高 - AI经营管理平台",
  "loginSubtitle": "企业级AI经营管理平台",
  "changePasswordUrl": "http://localhost:3001/login?callbackUrl=%2Fchange-password",
  "changePasswordTitle": "米高 - AI经营管理平台",
  "changePasswordSubtitle": "企业级AI经营管理平台"
}
```

## AI 读图判定（看 `out/01-login-full.png`，1440×980）

**看到了什么**（不是「应该是什么」）：

1. 顶部居中三行：金色织物 Logo → 「米高」→ 副标题**「企业级AI经营管理平台」**（一行，未折行、未溢出、与标题同轴居中）。
2. 旧文案「企业级AI电商管理解决方案」**不在页面上**（`out/page-text-login.txt` 可逐字复核）。
3. 下方登录卡（员工登录 / 管理员登录两页签 + 账号 / 密码输入 + 登录按钮）布局与改动前一致 —— 本次只动文字，没动版式。

## 未覆盖（照实登记，不当「通过」）

- **首次登录改密页在真实会话下的渲染未覆盖**：直接访问 `/change-password` 被 AuthGuard 重定向回
  `/login?callbackUrl=%2Fchange-password`（本机未起 admin-api、也没有 `must_change_password` 账号）
  ⇒ 该页的**同屏**证据缺失。替代证据：脚本在重定向后的页面上读到的同一句副标题 + 类级守卫判据②
  （`tests/unit_ci_workflows/test_positioning_copy_terms.py::test_user_facing_surfaces_now_use_the_new_tagline`）
  **强制两页副标题是同一句**。
- 重启条件：本机起 admin-api(:8080) + 一个首次登录账号 ⇒ 可补齐该页同屏截图。
