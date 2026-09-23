# UA 真浏览器实测 · 证据归档与复算配方（2026-09-23 晚）

本目录是 [../report.md](../report.md) §11「UA 补做与两处订正」的**原始证据**，
也是把「UA 未做 = **无浏览器环境**」这条**已证伪的理由**替换掉之后留下的**可复算件**。

> **一句话**：UA 之所以在 §3/§7 被记成「未做」，**不是因为本机没有浏览器**，
> 而是**当时没人去试**；本机 `tests/node_modules` 里一直有 `playwright`，
> 配套 Chromium **148.0.7778.96** 可用 —— 本次据此完成了一次**真实浏览器端到端**（见 `run.txt` 末行 `PROBE_DONE_OK`）。

## 0. 归档清单（逐字复制，未美化）

| 文件 | 是什么 | 字节 | sha256 |
|---|---|---|---|
| `probe-orders-new.mjs` | 探针源码：登录 → `/orders/new` → 选商品 → 选颜色 → 填净窗宽/净高 → 抓推导面板 | 6281 | `d87953b9dc6aeb65ced8c147683676668927f15ec6500cb04d20c1e5ac82107d` |
| `run.txt` | 上述探针**一次完整成功运行**的 stdout，末行 `PROBE_DONE_OK` | 7582 | `705faff5bf4a68c5927f4b776e29595e9dd43395113fcf0004a56ac7b4d820ac` |
| `00-登录页.png` | 旅程①：登录页（`title="米高 - AI电商管理系统"`） | 375819 | `8b5c2b68bdc431116a7c8cf93bb605e885e156a97006d8abad8569330a16e58f` |
| `01-orders-new-初始.png` | 旅程②：`/orders/new` 初始态 | 199541 | `01d362147f468f8d38e7a5dcdf4d75c59447e341400bb43c6e7d390816965f1b` |
| `02-选完商品.png` | 旅程③：选完商品「遮光窗帘」 | 266514 | `c19507e0f103f17669c13ae26d51b10146fe481c80c039814c0f7170e71dd953` |
| `02b-选完颜色.png` | 旅程④：选完颜色「浅灰」 | 264792 | `1c7fd436d4f11f84a9c8a2c37eb279040b81877de1bfd2bd57846b9734df27f9` |
| `03-填完宽高.png` | 旅程⑤：填完净窗宽 6.6 / 净窗高 2.6（自动徽标 + 面板已渲染） | 317474 | `9e7d522a6bc4832dfd816e480f74428e21517cf12236065df59557cc60d977cb` |
| `04-推导面板.png` | 旅程⑥：推导面板读数现场（§11.3 的截图证据） | 336045 | `0d65dccfad2a4ecd69e0783d3f7a31d4a9e95ce853a2c165a5eaf6cd00ba4c24` |
| `probe-typing-zero.mjs` | **第二条探针**：在同一套栈上逐字符敲 `0` `.` `5` / `0` `.` `6`，每一击读 DOM 值（§11.6） | 3441 | `3099d6afddd6ae44ffcbb342011d1113fb543cd4dfffefdea1fa6266ad8ba865` |
| `05-逐字符输0.5.png` | 上述探针跑完后的现场截图：`窗宽（米）` = **`0.6`**（第二轮终值，同帧可见 窗高 2.6 / 用料 1 / 商品「遮光窗帘 浅灰」） | 264835 | `c006bd11b714a6adf5311aa842519643ccd7aec0b0b59b0f0340bf4415b810c0` |

两条探针是**两次独立运行**（不是一次）：`probe-orders-new.mjs` 的 stdout = `run.txt`（有归档，末行 `PROBE_DONE_OK`）；
`probe-typing-zero.mjs` 的 stdout **未作为文件归档**，其读数见 §11.6（按 §2 ⑨ 重跑即可拿到）。

> ⚠️ **归档名是 `run.txt` 而不是 `run.log`**（源文件名是 `run.log`）：仓库 `.gitignore` 有 `*.log`，
> 且**全仓 tracked 的 `.log` 文件数为 0** —— 证据一律按既有先例存 `.txt`
> （如 `acceptance/2026-09-14/mini-app-e2e/run-logs/run1.txt`）。
> ⇒ **内容逐字未改**（sha256 与源文件同值：`705faff5bf4a68c5927f4b776e29595e9dd43395113fcf0004a56ac7b4d820ac`），
> 只换了扩展名以免与仓库忽略规则打架。

复核本目录没被改动过：

```bash
cd acceptance/2026-09-23/order-auto-derivation/ua
shasum -a 256 probe-orders-new.mjs probe-typing-zero.mjs run.txt *.png
```

## 1. 「读数 → 结论」的对应关系

`run.txt` 是**原始读数**（不是结论）。结论在 §11，映射如下 —— 想推翻任何一条结论，
只需指出它引的那行读数不足以支撑：

| run.txt 里的读数 | §11 的哪条结论 |
|---|---|
| L1–L3 `[shot] 00-登录页` / `title=…` / `✅ 登录成功` | 旅程真实走通（登录非桩） |
| L18/L22/L33 `testids(...)` 逐次增长 | 旅程每步都真的改变了 DOM（不是静态页） |
| L31 `[net] 200 /api/admin/orders/auto-features` + `"name":"超宽","reason":"净窗宽 6.6 米 > 超宽阈值 6.0 米"` | §11.3：自动特征上屏 |
| L32 `[net] 200 /api/admin/orders/craft-calc` + `"fabric_meters":13.3` | §11.3：面板 `用料 13.3 米` 与接口**同值** |
| L37–L46 `craft-plan-*` 十个读数 | §11.3 逐条判据（加工类型 / 接高 / 拼接 / 用料） |
| L47 `candidates(5)` | §11.3：5 个候选连同**每个的可行性理由**全部上屏 |
| L49 `PROBE_DONE_OK` | 该次运行**完整跑完**（不是中途截断的读数） |
| （第二条探针，见 `05-逐字符输0.5.png`）`窗宽（米）` = `0.6` | §11.6：`0.` 中间态未被吞、`0.5`/`0.6` 打得出来 |

⚠️ `run.txt` L4–L15 的 `[reqfail] …:: net::ERR_ABORTED` 与 L16/L17 的 `craft-calc-config` 是
**本旅程之外**的背景噪声（dashboard 轮询在页面跳转时被取消），**不影响** L31/L32 两条目标端点读数为 200。

## 2. 从零复现（本目录最重要的东西）

配方由主会话实测给出；本目录归档其读数。**任何一步省略都会以「看起来像产品 bug」的形态失败**
（见 §3 的四个坑），因此逐步照抄比自由发挥省事。

### 前置：确认浏览器侧齐备（这是「无浏览器环境」被证伪的地方）

```bash
# playwright 装在**主仓**的 tests/node_modules（不是 worktree 的）
node -e "console.log(require('<主仓>/tests/node_modules/playwright/package.json').version)"   # 1.60.0
ls ~/Library/Caches/ms-playwright/chromium-*/                                                   # chromium-1223
"$HOME/Library/Caches/ms-playwright"/chromium-1223/chrome-mac-arm64/"Google Chrome for Testing.app"/Contents/MacOS/"Google Chrome for Testing" --version
# → Google Chrome for Testing 148.0.7778.96
```

本机 PG 工具来自 Homebrew `postgresql@16`：`initdb` / `pg_ctl` / `psql` / `createdb` 均在 PATH 上。

### ① 起临时 PG

```bash
initdb -D /tmp/mgpg/data -U migao_admin --auth=trust
pg_ctl -D /tmp/mgpg/data -o "-p 5432 -k /tmp/mgpg -h 127.0.0.1" start
createdb -h 127.0.0.1 -p 5432 -U migao_admin ai_customer_service
```

> 同一件事在仓库里已有**先例脚本**可参考（一次性 PG + `docs/sql/schema.sql` bootstrap）：
> `acceptance/2026-09-21/4865-part-code-mapping/run.sh`。本次**没有**直接调它（它自带本单不需要的
> nginx 替身与桩），但形态同源。差别仅在本配方用 `migao_admin` / 固定 `5432`。

### ② 应用 bootstrap：跑 `schema.sql`，**不要**跑迁移链

```bash
psql -h 127.0.0.1 -p 5432 -U migao_admin -d ai_customer_service -f docs/sql/schema.sql
```

> 🔴 **新建库路径不跑迁移链**（`backend/admin-api/src/main/resources/db/migration/**`）——
> 迁移链假设基础表已存在，在空库上会因缺基础表**大面积失败**（主会话实测 **98 条**失败）。
> `docs/sql/schema.sql` 才是 bootstrap 的**终态**。

### ③ 注入评测种子（顺序不能反）

```bash
psql -h 127.0.0.1 -p 5432 -U migao_admin -d ai_customer_service -f tests/agent_eval/fixtures/xiaobu_eval_seed.sql
psql -h 127.0.0.1 -p 5432 -U migao_admin -d ai_customer_service -f tests/agent_eval/fixtures/mibao_eval_seed.sql
```

> ⚠️ **已知不干净点（如实登记）**：`mibao_eval_seed.sql` **末尾的 `DO` 块**会因缺
> `EVAL-MB-ORD-0006` 而 `RAISE EXCEPTION` ⇒ 该 `psql` 以非零退出。
> **实测它前面该插的都插了**（本次旅程用到的账号与商品都在），故**不阻断**本配方 ——
> 但也**不许**把它读成「种子注入完全成功」。
> 顺序（xiaobu 先、mibao 后）与仓库的**单一实现** `scripts/eval_stack_seed.sh` 一致
> （`SEED_FILES=("$FIXTURES/xiaobu_eval_seed.sql")`，`mibao` persona 才叠加第二个）；
> 该脚本是 **docker compose 口径**（`EVAL_COMPOSE_FILE` + `app_user`），本次走本地 PG + 直接 `psql -f`，
> **执行方式不同、顺序与内容同源**。

### ④ 给 tenant 1 补一行算料配置（**必需**）

```sql
INSERT INTO craft_calc_configs (id, tenant_id) VALUES ('ccc_ua_tenant1', 1);
```

> 缺这一行 ⇒ 页面显示 `craft-calc-config-missing`（`OrderCraftFields.tsx`），
> 推导面板根本不渲染 —— 会被误读成「功能没实现」。

### ⑤ 起 admin-api（`.env` 需两处覆盖）

worktree 的 `backend/admin-api/.env`（从 `.env.example` 拷）至少覆盖：

```
RDS_HOST=127.0.0.1
RDS_PORT=5432
RDS_USER=migao_admin
RDS_PASSWORD=<上一步 initdb 时那个用户的密码>
RDS_DB=ai_customer_service
AI_AGENT_BASE_URL=http://127.0.0.1:8001
AI_AGENT_SERVICE_TOKEN=<ai-agent 的 .env 里的 SERVICE_TOKEN 值>
```

> 🔴 **缺后两条的后果是「恒 422」**，不是"降级"：`POST /api/admin/orders/craft-calc` 与
> `/api/admin/orders/auto-features` 会**稳定返回 `422 CRAFT_CALC_UNAVAILABLE`**，
> 文案「未配置 ai-agent.service-token」。默认值见
> `backend/admin-api/src/main/resources/application.yml` 的 `ai-agent.base-url: ${AI_AGENT_BASE_URL:http://localhost:8000}`
> （**默认指向 :8000**，而本配方把 ai-agent 起在 **:8001** ⇒ 只差这一条也会 422）。
> 监听端口以 `frontend/admin-web` 的 `NEXT_PUBLIC_API_BASE_URL` 为准
> （`.env.example` 默认 `http://localhost:8080`；本次实测的 web 指向 `http://localhost:8090`，
> 见 `run.txt` 里 `[reqfail]`/`[net]` 前缀 —— **端口本身不是判据，两处一致即可**）。

### ⑥ 起 ai-agent（:8001）

```bash
cd <主仓>/backend/ai-agent-service
DATABASE_URL=postgresql+asyncpg://migao_admin:<密码>@127.0.0.1:5432/ai_customer_service \
  ./.venv/bin/python -m uvicorn app.main:app --port 8001
```

> 用 **主仓** 的 `.venv`（worktree 里没有）。`AI_AGENT_SERVICE_TOKEN` 的值取这里的 `SERVICE_TOKEN`。

### ⑦ 起 admin-web（:3001）—— 两个坑都会伪装成"页面坏了"

```bash
cd <worktree>/frontend/admin-web
npm ci            # ← 必须真装。worktree 的 node_modules 软链会被 Turbopack 拒（issue #5241）
npm run dev       # 监听 3001
```

> 🔴 **`BASE_URL` 必须写 `http://localhost:3001`，不能写 `http://127.0.0.1:3001`**：
> 用后者时 hydration 不接管，页面**永远停在 `AuthProvider` 的「加载中...」** ——
> 看上去像后端挂了，实际是站点口径问题。

### ⑧ 跑探针

```bash
PHONE=13600136000 BASE_URL=http://localhost:3001 OUT_DIR=<某空目录> \
  node acceptance/2026-09-23/order-auto-derivation/ua/probe-orders-new.mjs
```

> 🔴 **登录手机号是 `13600136000`（`debug_admin_eval` / 评测管理员）**，
> **不是**冒烟脚本默认的 `13800138000` —— 后者在本种子里是**顾客** `debug_customer_1`，
> 登进去 `/orders/new` 会显示「**无权访问该页面 …缺少权限 `order:list`**」，
> 看上去像下单页坏了。
>
> ⚠️ 探针第 4 行用**绝对路径**把 playwright 解析到主仓：
> `createRequire('/Users/guangzhen.zk/ai native/migao/tests/package.json')` ——
> 换一台机器 / 换一个检出位置时，**这一行要改**（它是本探针唯一的环境硬绑定点）。

### ⑨ 跑第二条探针（逐字符输 `0.5`，§11.6 的取证）

**同一套栈**（①–⑦ 全部照旧，登录手机号 `13600136000` 与 `BASE_URL=http://localhost:3001` 也都照旧），
换探针即可：

```bash
PHONE=13600136000 BASE_URL=http://localhost:3001 \
  node acceptance/2026-09-23/order-auto-derivation/ua/probe-typing-zero.mjs
```

> ⚠️ 该探针的截图路径是**写死的** `/tmp/ua-evidence/05-逐字符输0.5.png`（第 63 行，不走 `OUT_DIR`）
> ⇒ 在任何别的机器上重跑前**先改这一行**，否则要么写不出来、要么覆盖别人 `/tmp` 里的同一路径
> （`/tmp` 是跨会话共享写路径）。
> 它不落任何日志文件，读数只在 stdout（形如 `窗宽（米）逐字符：'0'→"0"  '.'→"0."  '5'→"0.5"  终值 = "0.5"`）。

## 3. 四个坑速查（症状 → 根因）

| 症状 | 根因 | 处置 |
|---|---|---|
| 建库后想跑迁移链，失败 **98 条** | 迁移链假设基础表已在（**新建库路径不跑它**） | 用 `docs/sql/schema.sql` bootstrap 终态 |
| `mibao_eval_seed.sql` 非零退出 + `RAISE EXCEPTION` | 末尾 `DO` 块要 `EVAL-MB-ORD-0006`，种子里没造 | 已知不干净点，前面该插的已插；不阻断 |
| 页面 `craft-calc-config-missing`，推导面板不出现 | tenant 1 在 `craft_calc_configs` 里没有行 | 补一行（§2 ④） |
| `/craft-calc`、`/auto-features` **恒 422 `CRAFT_CALC_UNAVAILABLE`** | admin-api 缺 `AI_AGENT_SERVICE_TOKEN`（默认还指向 `:8000`） | 补 `AI_AGENT_BASE_URL` + `AI_AGENT_SERVICE_TOKEN`（§2 ⑤） |
| 页面永远「加载中...」 | `BASE_URL` 用了 `127.0.0.1:3001` ⇒ hydration 不接管 | 改 `http://localhost:3001`（§2 ⑦） |
| 工作区软链的 `node_modules` 起不来 | Turbopack 拒软链（issue #5241） | `npm ci` 真装（§2 ⑦） |
| `/orders/new` 显示「缺少权限 `order:list`」 | 用了 `13800138000`（顾客账号） | 用 `13600136000`（评测管理员）（§2 ⑧） |

## 4. 本目录的边界（照实登记，不许读成"UA 全做完"）

- 本目录**只覆盖一条旅程**：商品「遮光窗帘」+ 颜色「浅灰」+ 净窗宽 6.6 / 净窗高 2.6。
  **其余商品 / 颜色 / 尺寸组合未走**。
- §11.6 的逐字符读数**只覆盖一个站点**（下单页「窗宽（米）」）。
  **不许**把它推广成「全仓 6 个数字输入站点都已真浏览器验证」—— 其余站点的护栏在 #5228 / #5237，
  本次**一个都没跑**。
- 本旅程**没有**覆盖「商家手工改加工类型 / 拼次后被判『未跟随』」这条路径 ⇒
  **UA-2 仍未做**（§11.4），本目录里**没有任何**可支撑它的读数。
- **未做**：`bmini-app` 真机、多租户切换、「不采纳推导项」后的组合键核对（§11.5）。
- 本目录**不是**自动化测试：没有 `# case_ids:` 声明，不进 CI 判据面；它是**人可复算的验收证据**。
  要把它变成防回退判据，应另立用例（`#5218`/`#5228` 家族已有同类做法）。
