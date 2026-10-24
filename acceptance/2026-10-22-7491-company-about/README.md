# issue #7491 公司名撤出侧边栏 + 用户菜单「关于观星台」· 多模态验收证据

用户 2026-10-22：「我们的公司名？放左下角用户会有想法的吧」→ 选定「撤出侧边栏 + 用户菜单加『关于观星台』」。

- 分支：`feat/7491-company-about`；**本机生产构建**（`npm run build` + `npm start -p 3001`）
- 采样（两次）：
  1. 侧边栏：`node <preset>/.../ui-multimodal-acceptance.mjs --site http://localhost:3001 --path /dashboard --out /tmp/ui-7491 --phone 13900001025 --code 123456 --shot sidebar`
  2. 用户菜单：同上，另加 `--click 用户菜单 --out /tmp/ui-7491-menu`
- 登录 `13900001025`；视口 1440×980；`loginOk: true` / `http5xx: []`

## 读图判定（逐条「看到了什么」）

| # | 验收点 | 读数 |
|---|---|---|
| 1 | 侧边栏不再有公司名 | `sidebar.png` 页脚只有「✦ 观星台」+ 右侧「‹ 收起」；`page-text.txt` 里搜不到「杭州词元通达科技有限公司」 |
| 2 | 用户菜单有「关于观星台」 | `user-menu.png`：账号名 / 岗位 / 所属企业 之后、退出登录之前，一行 ⓘ「关于观星台」 |
| 3 | 链接可达 | 本机 `curl :3001/about` = **200**；线上 `https://merchant.migaozn.com/about` = **200**（同一 Next 应用的官网关于页） |
| 4 | 不抢工作台 | 侧边栏品牌署名形态不变（星标 + 观星台 + 收起同一行） |

改前对照：`acceptance/2026-10-22-7487-footer-lockup/sidebar.png`（页脚第二行公司名）。

## 未覆盖（照实登记）

- 移动端抽屉态（用户菜单在移动端为同一组件，未截）；
- 折叠态（既有单测覆盖「不渲染 brand」）；
- `/about` 页面内容本身不在本单改动范围（只验证可达）。
