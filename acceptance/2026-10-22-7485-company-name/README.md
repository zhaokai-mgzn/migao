# issue #7485 页脚带上公司法定名称 · 多模态验收证据

用户 2026-10-22（承接 #7482）截图 + 逐字：「要不要带上我们公司的名称，这样是否合适？可以用一行暗淡的小字」

- 分支：`feat/7485-company-name`；**本机生产构建**（`npm run build` + `npm start -p 3001`，`NEXT_PUBLIC_API_BASE_URL=http://localhost:8080`）
- 采样命令：`node <preset>/skills/migao-dev-flow/scripts/ui-multimodal-acceptance.mjs --site http://localhost:3001 --path /dashboard --out /tmp/ui-7485 --phone 13900001025 --code 123456 --shot sidebar --shot sidebar-brand`
- 视口 1440×980；登录 = 管理员手机验证码（`13900001025`）；`summary.json`：`loginOk: true` / `http5xx: []` / `testids: 34`

## 读图判定（逐条「看到了什么」）

| # | 验收点 | 读数 |
|---|---|---|
| 1 | 公司名在位 | 页脚底部一行暖灰小字「杭州词元通达科技有限公司」，位于品牌小牌**下方**、左对齐页脚内边距 |
| 2 | 主次不抢 | 品牌小牌（观星台 / MIGAO）仍是视觉主体；公司名为 10px `neutral-500`，对比度低于品牌字 |
| 3 | 与折叠控制不冲突 | `‹ 收起` 仍在品牌行右侧，与公司名不同行、不重叠 |
| 4 | 顶部不被牵连 | 左上角仍只有 `[Logo] 亿家纺织` |

改前对照：`acceptance/2026-10-22-7482-brand-plate/sidebar.png`（只有品牌小牌，无公司名）。

## 未覆盖（照实登记）

- 移动端抽屉态（页脚同组件，本轮未截）；
- 折叠态（既有单测覆盖「不渲染 brand / company」）；
- 商家自定义企业 Logo 形态。
