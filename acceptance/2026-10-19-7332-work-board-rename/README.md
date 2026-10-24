# #7332 生产看板正名「作业看板」· Playwright 页面多模态验收

- 日期：2026-10-19（Asia/Shanghai）
- 被测分支：`feat/7332-work-board-rename`
- 被测 SHA：`f882c772e`（截图时 dev server / admin-api 均来自该 worktree）
- 入口：admin-web `http://localhost:3001` + admin-api `http://localhost:8080`（§15.7 唯一入口）
- 账号：本机 dev 库管理员 `13900001025`（`SMS_BYPASS_CODE=123456`，`.env` 未入库）
- 目标页：`/production`
- 采集结果：`loginOk=true` · `testids=53` · `http5xx=[]` · `summary.json`
- 证据文件：`01-full.png`（整页截图）、`page-text.txt`（逐字文本）、`testids.txt`、`summary.json`

## AI 读图逐条判定（看到了什么，不写「应该是什么」）

| # | 验收点 | 截图 / 文本读数 | 判定 |
|---|---|---|---|
| 1 | 侧边栏菜单名 | 生产管理组首项渲染为「作业看板」，且当前高亮 | ✅ |
| 2 | 面包屑 | 顶部为「生产管理 / 作业看板」 | ✅ |
| 3 | 页面标题 | H1 =「作业看板」；副标题「作业单在产进度与计件合计」 | ✅ |
| 4 | 两型同屏 | 列表「类型」列同时出现「出库作业单」与「加工单」两组行 | ✅ |
| 5 | 搜索提示 | 占位符 =「请输入作业单号或订单号」（#7079 起的作业单口径，未被本次改回） | ✅ |
| 6 | 旧名残留 | `page-text.txt` 中「生产看板」命中 **0** 次；「作业看板」命中 3 次（菜单/面包屑/标题） | ✅ |
| 7 | 布局回退 | 查询区、表头、行内动作、分页与改动前同构；无溢出、无错位 | ✅ |

## 观察项（照实登记，不当作通过也不当作缺陷结论）

- 截图左下角有 Next.js **dev 模式**的「1 Issue」浮层（开发态指示器，生产构建不渲染）。
  本次证据未展开定位；页面 `http5xx=[]`、渲染与交互正常。若生产构建仍出现同类可见告警，
  重启条件 = 用 `next build && next start` 复现并另单处理。
- 本轮只验桌面 1440×980 视口；手机端 bmini 的同名文案由 `frontend/bmini-app/tests/`
  的 19 条单测覆盖，本轮未做手机端真机截图。

## 复现

```bash
# 1) 起 admin-api（显式导出 .env；Spring Boot 不读 .env）
cd backend/admin-api && set -a && . ./.env && set +a && ./mvnw -q spring-boot:run
# 2) 起 admin-web
cd frontend/admin-web && npm run dev
# 3) 采集证据（Playwright 从主仓 tests/node_modules 解析）
MIGAO_REPO_ROOT="/Users/guangzhen.zk/ai native/migao" \
node ~/.dsh/.agent-presets/migao/skills/migao-dev-flow/scripts/ui-multimodal-acceptance.mjs \
  --site http://localhost:3001 --path /production \
  --phone 13900001025 --code 123456 --out /tmp/ui-acceptance-7332
```
