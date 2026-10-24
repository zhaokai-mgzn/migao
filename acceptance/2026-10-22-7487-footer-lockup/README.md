# issue #7487 页脚重设计（星标 + 两行 lockup，去掉 MIGAO 与方框）· 多模态验收证据

用户 2026-10-22 截图 + 逐字：「移除米高的叫法，观星台=米高了，这样太丑了，你设计的好看些」

- 分支：`feat/7487-footer-lockup`；**本机生产构建**（`npm run build` + `npm start -p 3001`）
- 采样命令：`node <preset>/skills/migao-dev-flow/scripts/ui-multimodal-acceptance.mjs --site http://localhost:3001 --path /dashboard --out /tmp/ui-7487 --phone 13900001025 --code 123456 --shot sidebar --shot sidebar-brand`
- 视口 1440×980；`loginOk: true` / `http5xx: []` / `testids: 34`

## 读图判定（逐条「看到了什么」）

| # | 验收点 | 读数 |
|---|---|---|
| 1 | MIGAO 已移除 | 页脚只有「观星台」一行品牌字，无 `MIGAO`（`page-text.txt` 也搜不到） |
| 2 | 无方框 | 品牌不再有圆角底 / 描边（上一版的小牌消失），是「星标 + 两行字」的 lockup |
| 3 | 公司名成为第二行 | 「杭州词元通达科技有限公司」9px 暖灰，与「观星台」左对齐、在其下方 |
| 4 | 折叠控制 | `‹ 收起` 仍在品牌右侧、同一行、不重叠 |
| 5 | 顶部不被牵连 | 左上角仍只有 `[Logo] 亿家纺织` |

改前对照：`acceptance/2026-10-22-7485-company-name/sidebar.png`（圆角小牌 + MIGAO + 框外公司名）。

## 未覆盖（照实登记）

- 移动端抽屉态（页脚同组件，本轮未截）；
- 折叠态（既有单测覆盖「不渲染 brand / company」）。
