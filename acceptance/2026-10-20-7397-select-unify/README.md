# #7397 全站下拉框收口 + 筛选条字段可增长 · Playwright 页面多模态验收

- 日期：2026-10-20（Asia/Shanghai）
- 被测分支：`fix/7397-select-control-unify`（工作区 `/Users/guangzhen.zk/ai native/migao`）
- 入口：admin-web `http://localhost:3001` + admin-api `http://localhost:8080`（§15.7 唯一入口）
- 账号：本机 dev 库管理员 `13900001025`（`SMS_BYPASS_CODE=123456`，`.env` 未入库）
- 目标页：`/production`（截图里的作业看板状态筛选）、`/knowledge`（截图里的关键词输入框 + 三个下拉）
- 视口：1440×980（截图 DPR = 2 / 3）

## 为什么用自写脚本采集（如实登记）

§15.7 的采集器 `~/.dsh/.agent-presets/migao/skills/migao-dev-flow/scripts/ui-multimodal-acceptance.mjs`
在本会话**先失败后绕开**：它按 `LOGIN_SHAPE` 指纹切「管理员登录」页签，而本机登录页的两个页签
实测文本是「员工登录账号密码」/「管理员登录手机验证码」，脚本期望的是「员工登录/账号密码」那种带 `/` 的形态
⇒ **fail-closed 报「页面形态已变」**（脚本行为正确，是它的指纹过期）。本包未改那份预设（属预设仓的包），
改用等价的直连 Playwright 脚本（同一份 chromium、同一条真登录路径：点页签 → 手机号 + 验证码 → 登录 →
再进目标页截图），并**逐字记录**登录成功后的 URL 与控件读数。
📌 待办（不在本包）：把 `LOGIN_SHAPE` 的页签文案更新到当前登录页 —— 否则§15.7 的标准采集器在每个会话都会红。

## 机器读数（采集脚本 stdout，逐字）

```text
login ok -> http://localhost:3001/dashboard

production:
  inputs : [{ ph: "请输入作业单号或订单号", w: 220 }]
  selects: [{ cls: "rounded h-9 pl-3 pr-9 … appearance-none …", w: 140, h: 36,
              bg: "url(\"data:image/svg+xml,%3Csvg …", appearance: "none" },
            { cls: "h-8 pl-2 pr-7 … appearance-none …", w: 62, h: 32,
              bg: "url(\"data:image/svg+xml,%3Csvg …", appearance: "none" }]

knowledge:
  inputs : [{ ph: "搜索标题 / 关键词 / 常见问法 / 回答内容", w: 786 }]
  selects: 3 × { cls: "rounded h-9 pl-3 pr-9 … appearance-none …", w: 144, h: 36,
                 bg: "url(\"data:image/svg+xml,%3Csvg …", appearance: "none" }
```

- `bg` 不再是 `none`、`appearance` 是 `none` ⇒ 箭头由**我们的** SVG 画（改前：`bg: none` + 系统原生箭头）。
- knowledge 关键词输入框 **220 → 786 px**（长占位文案完整可见）。

## AI 读图逐条判定（看到了什么，不写「应该是什么」）

| # | 验收点 | 证据 | 判定 |
|---|---|---|---|
| 1 | 作业看板「状态」下拉：无原生带框小箭头，右侧是一个**暖色细箭尖**，圆角 4px、高 36px，与左侧关键词输入框齐平 | `production-select.png`（元素级截图）+ `production.png` | ✅ |
| 2 | 知识库三个筛选下拉（全部分类 / 全部来源 / 全部状态）形态一致：同一箭尖、同高、同宽（144px） | `knowledge.png` | ✅ |
| 3 | 知识库「关键词」输入框：占位文案「搜索标题 / 关键词 / 常见问法 / 回答内容」**完整可见**，输入框吃掉整行剩余宽度（786px），「重置 / 查询」在右 | `knowledge-input.png`（元素级）+ `knowledge.png` | ✅ |
| 4 | 表格分页「每页 20 条」下拉：紧凑档（h-8）也换成同一份箭尖 | `pager-select.png` + `production.png` | ✅ |
| 5 | 版式零回退：作业看板查询区仍在页内一行、列表列宽/行高/操作列冻结与改前同构；知识库 Tab 栏/表格/分页不变 | `production.png` / `knowledge.png` | ✅ |
| 6 | 无脚本报错：采集期控制台只有两条与本次无关的资源错误（`ERR_NAME_NOT_RESOLVED`，第三方图标；`two children with the same key`，作业看板行 key 的存量告警） | 采集 stdout | ⚠️ 存量观察项，非本包引入 |

## 观察项（照实登记，不当作通过也不当作缺陷结论）

- 截图左下角有 Next.js **dev 模式**浮层（「1 Issue」）；生产构建不渲染。
- 作业看板控制台有 `Encountered two children with the same key` 的存量告警（同一条作业单在分页返回里出现两次，
  改前就有）；本包未处理 —— 重启条件 = 用户看到重复行 / 台账要求清零。
- 输入框自身的 4px / 8px 圆角差异（筛选面 4px、表单字段面 8px）**有意保留**（见 issue #7397 边界节）。

## 复现

```bash
# 1) 起 admin-api（显式导出 .env；Spring Boot 不读 .env）
cd backend/admin-api && set -a && . ./.env && set +a && ./mvnw -q spring-boot:run
# 2) 起 admin-web（当前分支代码）
cd frontend/admin-web && npm run dev
# 3) 采集（直连 Playwright；脚本见本目录同批 PR 的说明，或按上文读数复算）
#    标准采集器恢复 LOGIN_SHAPE 后应可直接用：
#    MIGAO_REPO_ROOT=$PWD node ~/.dsh/.agent-presets/migao/skills/migao-dev-flow/scripts/ui-multimodal-acceptance.mjs \
#      --site http://localhost:3001 --path /production --phone 13900001025 --code 123456 --out /tmp/ui-acceptance-7397
```
