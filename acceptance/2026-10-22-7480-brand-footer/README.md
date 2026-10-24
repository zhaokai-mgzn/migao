# issue #7480 侧边栏页脚品牌署名改版 · 多模态验收证据

用户 2026-10-22 截图（红框圈住底部「观星台」）+ 逐字：「毕竟是我们的品牌，这样放置设计的太丑陋了，让我们品牌高大上一点」。

- 分支：`feat/7480-brand-footer`；**本机生产构建**（`npm run build` + `npm start -p 3001`，`NEXT_PUBLIC_API_BASE_URL=http://localhost:8080`）
  —— 刻意不用 `next dev`：开发态左下角的「N」指示器会压住页脚署名，截图里会变成假象。
- 采样命令：`node <preset>/skills/migao-dev-flow/scripts/ui-multimodal-acceptance.mjs --site http://localhost:3001 --path /dashboard --out /tmp/ui-acceptance-7480c --phone 13900001025 --code 123456 --shot sidebar --shot sidebar-brand`
- 视口 1440×980；登录 = 管理员手机验证码（`13900001025`，用户 2026-10-22 指定后续验证账号）
- `summary.json`：`loginOk: true` / `http5xx: []` / `testids: 32`

## 读图判定（逐条「看到了什么」）

| # | 验收点 | 读数 |
|---|---|---|
| 1 | 署名与折叠控制**同一行** | `sidebar.png` 底部一行：左 `✦ 观星台`，右 `‹ 收起`（不再是一行孤零零的灰字 + 居中「收起」两段） |
| 2 | 品牌形态 | `sidebar-brand.png`：金色四角星 + 「观星台」13px、字距拉开的暖白字；左侧顶边有一道由金渐隐的 1px 细线 |
| 3 | 顶部不被牵连 | 左上角仍是 `[Logo] 亿家纺织`，无品牌副标题 |
| 4 | 版式未破 | 页脚行高与 nav 底部留白正常；`收起` 仍可点（既有判据 `收起` 点击测试未改、仍绿） |

改前对照：`acceptance/2026-10-22-7476-sidebar-brand/sidebar.png`（11px 灰字「观星台」孤零零在左下、与居中「收起」错位）。

## 未覆盖（照实登记）

- 移动端抽屉态（页脚同组件，但本轮未截）；
- 侧边栏**折叠态**（既有单测覆盖「不渲染 brand」，未截）；
- 商家自定义企业 Logo 的形态（本轮账号未设 Logo）。
