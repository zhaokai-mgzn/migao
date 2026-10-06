# 2026-10-06 岗位 × 页面「覆盖补齐」结论（p2b）

被测面 `https://merchant.migaozn.com` · 租户 25「米高测试环境」`shop-8yn7` · **被测 SHA `73327161f`**（map 同 commit）
测量窗口 2026-10-06 09:40–09:48 (+08)；开测前 `gh run list --workflow=deploy-reconcile.yml` 近 5 次全 `completed`（无在飞部署）。
产物：`harness/p2b-coverage.mjs`（可复跑）· `out/p2b-coverage.json`（逐条读数）· `out/shots/p2b_*.png` 42 张 · `out/text-p2b/**`（异常条目全文）。

## 0. 一句话

**补满首轮的两处覆盖缺口，未发现产品侧拦漏/误拦**：正向 7 岗位 × 40 条路由 = **231 次真访问**（静态 33/33 全覆盖），
负向 **65/65** 组合逐条真探 ⇒ **fail(产品)=0 · 假红=0 · pass=303 · skip=56（全部有据，见 §3）**。本报告只回答「**拦不拦得住 / 进不进得去**」，**不构成「验收通过」**（强度边界见 §7）。

## 1. 覆盖前后对比（每格带读数，可复算）

| 面 | 首轮 `p2-roles-ui.mjs` | 本轮 `p2b-coverage.mjs` | 证据 |
|---|---|---|---|
| 正向访问次数 | 82（7 岗位 × 各自菜单顶层页） | **231**（7 岗位 × 33 静态路由，逐格） | `p2-roles-ui.json#roles[].visited` ⇄ `p2b-coverage.json#roles.*.routeVisits` |
| 正向并集路径 | 21 条 | **33 条**（静态路由全量） | 同上 |
| `map.json#routes` 0 次访问 | **19 / 40** | **7 / 40**（**全为动态段**，如实记 skip） | `#coverage.routesDynamicSkipped=7` |
| 负向组合 | 17 / 65（每岗位抽 3 条） | **65 / 65**（逐条真探） | `#coverage.negativeCombos=65, negativeLeaked=0` |
| 截图 | 28 / 82（前 4 页） | 42 张（每岗位 6） | `out/shots/p2b_*.png`（2.2 MB） |

期望值来源（**不读被测读面自证**）：`out/map.json#routes`（`gen-map.py` 从 `origin/main` 的 `app/(dashboard)/**/page.tsx` 导出）
+ `out/map.json#prefixes`（同源 `layout.tsx:16-75`，判定语义照抄 `layout.tsx:92` 的 `find(...)` = **数组序首次命中**）+ **DB 现取** `roles ⨝ role_permissions ⨝ permissions`（tenant 25）；数组序 vs 最长前缀偏离数 = **0**（`#coverage.orderDivergence: []`）。

## 2. 四态计数

| 态 | 数 | 构成（逐格可对：`out/p2b-coverage.json#rows`，共 359 行） |
|---|---|---|
| `pass` | **303** | 7 登录 + **224** 路由判读（allow 命中 / deny 被拦）+ 7 负向汇总 + 65 负向逐条 |
| `fail(产品)` | **0** | — |
| `skip(未覆盖)` | **56** | 49 = **7 条动态段 × 7 岗位**；7 = `/notifications`（**no-guard**）× 7 岗位 |
| `假红(判据缺陷)` | **0** | — |

每岗位期望分布（`out/run.log` 逐行）：admin `allow 32/deny 0/no-guard 1`、operator `30/2/1`、product_manager `16/16/1`、customer_service `15/17/1`、sales `12/20/1`、finance `10/22/1`、knowledge_editor `6/26/1`；负向组合 0/2/11/11/12/13/16 = **65**。

## 3. 逐条 fail / skip 清单（带证据引用）

- **`fail(产品)` = 0 条**：231 次静态访问里 `expect=deny` 的格**全部**命中 DOM「无权访问该页面」；`expect=allow` 的格**无一条**被误拦，且 `notFound=false` / `loading=true` / `stable=false` / `textLen<40` / `consoleErrors>0` **各为 0 条**（全量 231 格）。
- **`skip` = 56 条**（明细 `#rows`，`detail` 逐字）：
  - **49 条动态段**（`/after-sales/:id`、`/customers/:id`、`/orders/:id`、`/orders/:id/ship`、`/processing-orders/:id/production`、`/products/:id`、`/products/:id/edit` × 7 岗位）——理由逐字：「动态段无夹具：本轮无夹具 id ⇒ 未覆盖，**不伪装 pass/fail**」。
  - **7 条 `/notifications`**——理由逐字：「no-guard：`map.json#prefixes` 无前缀覆盖 ⇒ 无守卫码，期望不可判定 ⇒ **不判 pass**；实测可进」。
- **负向 65 条**：`denied=true` **65/65**，`textLen` 56–63（正是 403 卡），`loading/unstable/consoleErrors` 各 0（`#negative`）。

## 4. 疑似产品缺陷：**0 条**（3 条疑似项已逐条核销，附设计真值源）

| # | 疑似形态（读数） | 核销依据（文件::字段 + 原文片段） | 结论 |
|---|---|---|---|
| 1 | 客服/运营进 `/chat` 只见门禁卡：`#roles.customer_service.routeVisits["/chat"].textHead` =「米宝 · 在线对话 … **需要管理员授权** / 请联系企业管理员在「员工管理」中为你开通米宝使用权限」；admin 同页 709 字真会话 | `db/migration/V132__add_agent_chat_permission.sql:116-124`「`agent:chat` 的授权链接**只**允许落在 `admin` 角色上」；`docs/design/b-end-wechat-login-and-agent-gate.md:964`「客服持 `agent:session`（坐席）**但默认不持** `agent:chat` ⇒ 客服默认不可唤（符合裁定⓪）」 | **非缺陷（设计如此）**，引导文案给了出口 |
| 2 | `/notifications` 7 岗位**一律可进**、无守卫码（`#coverage.routesNoGuard=1`） | `app/(dashboard)/layout.tsx:66-74` 逐字：「🔴 `/notifications`（通知中心）**有意不登记**…菜单节点**无 `permissionCode`**（全员可见）…**不凭空造码**」 | **非缺陷（有意豁免，代码内有登记）** |
| 3 | 两处「未开启」态：`/briefing`「智能每日经营简报未开启」、`/production/pool`「合并派单开关 未开启」 | `/briefing` 对应 DB 真值 `tenants.briefing_enabled=false`（现取），与首轮 `p2` 建模一致；两页均给可行动出口 | **非缺陷（租户开关关着）** |

> 本轮**没有产生需派单的产品缺陷**。3 项形态可疑但都能被 durable 真值源解释 ⇒ 不判红（归因强度必须匹配证据强度）。

## 5. 收尾清理（前 / 后现取读数）

`p7-cleanup.mjs` 终态输出（`out/p7-cleanup.json`，`at=2026-10-06T01:48:59.337Z`）：

```
== p7 清理 before={"users":20,"knowledge":0,"orders":0,"tickets":1,"inbound":18} after={"users":20,"knowledge":0,"orders":0,"tickets":1,"inbound":18} dry=false
   DELETE 0  <= knowledge_cards / after_sales_tickets / order_items / orders（四条探针前缀均 0 命中）
   UPDATE 20 <= update users set deleted=1, status='disabled', username=null, phone=null where tenant_id=25 and (username like 'a06%' …)
```

我自己的现取读数（同刻，`harness/q.mjs`）：**清理前** `probe_users=20 / live_users=7 / knowledge=0 / orders=0 / tickets=1 / inbound=18` → **清理后** `probe_users=20 / live_users=1 / … 同前`（`live_users`=`deleted=0`，7→1 = 管理员本人）。
本轮写面**只**产生 6 个 `a06_*` 岗位账号（`p1-roles-seed.mjs` 重建，`pass:8`），已全部被 p7 软禁用；`out/pre-p2b-backup/` 保留了首轮的 `p1-roles.json` / `p7-cleanup.json`。

## 6. 判据侧 / 证据侧登记（不擅自改既有 harness，只登记）

| 编号 | 形态 | 读数 | 处置 |
|---|---|---|---|
| **D-p2b-1** | 证据选取偏斜（截图） | 42 张按 `map.json#routes` 前 6 条取 ⇒ 仅 **22/42** 是「真页」，**20/42** 是同一张 403 卡（`p2b_sales_agent_workspace*.png` 三张同为 24972 B） | 截图**非**任何判定的依据（判定用 DOM `denied`+`textLen`+`textHead`，231 格全有）；登记待改为「优先截 allow 格」 |
| **D-p2b-2** | 判据过弱（继承首轮 D10） | `textLen<40` 空白门**本轮从未触发**；实测 allow 页最小 `textLen`=**113**，403 卡 56–67 ⇒ 只在整壳未渲染时才红 | 与首轮 `REPORT.md` D10 同源，**未加严**（加严需按主内容区取文本，超范围） |
| **D-p2b-3** | 读数无判别力 | `p7-cleanup.json#before.users == #after.users == 20`，而真实变化是 `deleted=0` 的 `live_users` **7→1** ⇒ 该计数**结构性不变**（软删只清 `username`，`nickname like 'A06验收%'` 仍命中） | 登记；建议 p7 的 `users` 读数加 `and deleted=0`（**本轮不改既有 harness**）。另：p7 只软禁用不删除 ⇒ `A06验收*` 残留累加（14→20） |

## 7. 结论强度边界（明确写「没测到什么」）

1. **7 条动态段（49 格）仍 0 覆盖** —— 缺夹具 id（订单/商品/售后实体）；**skip 未折算 pass**。
2. **只判「拦不拦 / 进不进得去」**：页面内按钮、写面（建单/建品/改价）本轮**不重复**（首轮 `p4/p4d` 覆盖）。
3. 单租户（25）× 单 SHA（`73327161f`）× 单部署面 ⇒ **不可外推**；页面多空态（53 格含「暂无/共 0 条」）⇒「有数据时是否正常」未覆盖。
4. 未核销项：`/chat` 里 admin 可见 4 条 **2026-10-05 遗留米宝会话**（`#roles.admin.routeVisits["/chat"].textHead` 逐字「会话 2026-10-05 07:24…」「商品健康报告分析」）——`p7-cleanup.mjs` 表清单（users/knowledge_cards/after_sales_tickets/orders/order_items）**不含米宝会话表**。**证据不足**：未定位到 B 端会话存储表（缺：存储定位）⇒ 只登记不判定。
