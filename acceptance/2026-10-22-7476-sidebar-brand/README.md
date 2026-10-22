# issue #7476 侧边栏品牌位置调整 · 多模态验收证据

- 被测 SHA：`ce1586356`（分支 `feat/7476-sidebar-brand`；本机 `next dev` + `admin-api:8080`）
- 采样命令：`node <preset>/skills/migao-dev-flow/scripts/ui-multimodal-acceptance.mjs --site http://localhost:3001 --path /dashboard --out /tmp/ui-acceptance-7476 --phone 13600136000 --code 123456 --shot sidebar --shot sidebar-brand`
- 视口 1440×980；登录 = 管理员手机验证码（本机 `SMS_BYPASS_CODE`）；`summary.json` = `loginOk: true` / `http5xx: []` / `testids: 30`

## 读图判定（逐条「看到了什么」）

| # | 验收点 | 读数 |
|---|---|---|
| 1 | 左上角不再有品牌副标题 | `sidebar.png`：`[Logo] 词元通达（评测 seed）`，其下**没有**第二行「观星台」 |
| 2 | 品牌在底部、收起按钮上方 | `sidebar.png` / `sidebar-brand.png`：灰色小字「观星台」；`page-text.txt` 逐字 `… 通知中心 / 观星台 / 收起 …` |
| 3 | 版式未破 | 品牌行与「收起」不重叠；顶部块高度、与搜索框的间距与改前一致 |

## 假绿与未覆盖（照实登记）

- **dev-only 现象**：`next dev` 左下角的「N」devtools 指示器压在品牌行上（`sidebar.png` 可见黑圆）。
  生产构建不含该指示器；本轮**未**在 `next build` 产物上复核（未覆盖，重启条件 = 需要生产构建证据时）。
- 未覆盖：① 生产构建态；② 移动端抽屉态；③ 商家自定义企业 Logo 的形态（本轮账号未设 Logo）。
