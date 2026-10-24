# issue #7482 页脚品牌升级（观星台 / MIGAO 两行 lockup + 浅金玻璃底小牌）· 多模态验收证据

用户 2026-10-22（承接 #7480）：「先加 1 2」—— 拉丁副标 + 浅金玻璃底小牌。

- 分支：`feat/7482-brand-plate`；**本机生产构建**（`npm run build` + `npm start -p 3001`，`NEXT_PUBLIC_API_BASE_URL=http://localhost:8080`）
- 采样命令：`node <preset>/skills/migao-dev-flow/scripts/ui-multimodal-acceptance.mjs --site http://localhost:3001 --path /dashboard --out /tmp/ui-7482b --phone 13900001025 --code 123456 --shot sidebar --shot sidebar-brand`
- 视口 1440×980；登录 = 管理员手机验证码（`13900001025`）；`summary.json`：`loginOk: true` / `http5xx: []` / `testids: 33`

## 读图判定（逐条「看到了什么」）

| # | 验收点 | 读数 |
|---|---|---|
| 1 | 玻璃底小牌 | `sidebar-brand.png`：圆角小牌，暖金→白的极浅渐变 + 细描边；不再是一行裸字 |
| 2 | 两行 lockup | 上「观星台」（13px、字距拉开、暖白）+ 下「MIGAO」（9px、字距 0.3em、暖灰 `neutral-400`）；星标在左侧 |
| 3 | 与折叠控制同一行 | `sidebar.png` 底部：左牌、右「‹ 收起」，同一行不重叠 |
| 4 | 顶部不被牵连 | 左上角仍只有 `[Logo] 亿家纺织` |

改前对照：`acceptance/2026-10-22-7480-brand-footer/sidebar.png`（一行字 + 星标，无小牌、无拉丁副标）。

## 未覆盖（照实登记）

- 移动端抽屉态（页脚同组件，本轮未截）；
- 侧边栏折叠态（既有单测覆盖「不渲染 brand」；#7480 轮已截过折叠态：只留 `›` 图标 + 金色细线）；
- 商家自定义企业 Logo 形态。

## 一处门禁纠偏（照实登记）

初版把 MIGAO 写成 `text-gold-500/80`，被 `frontend/admin-web/tests/unit/warm-token-palette-guard.test.ts` 的
判据 1c（`gold` 不得用于文字，实测对比度 2.76:1 未达 AA）判红 ⇒ 改成暖灰 `neutral-400`（`#b8aa94`，暖色 token、对比度达标）。
金色只留在**星标图形**与页脚顶边细线上（非文字），既守住对比度，也保住「织金」点缀。
