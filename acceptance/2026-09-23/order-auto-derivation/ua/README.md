# UA 真浏览器实测 · 证据归档与复算配方（2026-09-23 晚）

本目录是 [../report.md](../report.md) §11「UA 补做与两处订正」的**原始证据**，
也是把「UA 未做 = **无浏览器环境**」这条**已证伪的理由**替换掉之后留下的**可复算件**。

> **一句话**：UA 之所以在 §3/§7 被记成「未做」，**不是因为本机没有浏览器**，
> 而是**当时没人去试**；本机 `tests/node_modules` 里一直有 `playwright`，
> 配套 Chromium **148.0.7778.96** 可用 —— 本次据此完成了一次**真实浏览器端到端**（见 `run.txt` 末行 `PROBE_DONE_OK`）。

## 0. 归档清单（逐字复制，未美化）

| 文件 | 是什么 | 字节 | sha256 |
|---|---|---|---|
| `probe-orders-new.mjs` | 探针源码（**已参数化** `WIDTH_M` / `HEIGHT_M`，默认 `6.6` / `2.6` ⇒ 不带参数即复现第一条旅程）：登录 → `/orders/new` → 选商品 → 选颜色 → 填净窗宽/净高 → 抓推导面板 | 6354 | `539f281d1bddd98af5a850d88d1becfd7ba8b639982930fb9afda19adbf9806b` |
| `run.txt` | 上述探针**一次完整成功运行**的 stdout，末行 `PROBE_DONE_OK` | 7582 | `705faff5bf4a68c5927f4b776e29595e9dd43395113fcf0004a56ac7b4d820ac` |
| `00-登录页.png` | 旅程①：登录页（`title="米高 - AI电商管理系统"`） | 375819 | `8b5c2b68bdc431116a7c8cf93bb605e885e156a97006d8abad8569330a16e58f` |
| `01-orders-new-初始.png` | 旅程②：`/orders/new` 初始态 | 199541 | `01d362147f468f8d38e7a5dcdf4d75c59447e341400bb43c6e7d390816965f1b` |
| `02-选完商品.png` | 旅程③：选完商品「遮光窗帘」 | 266514 | `c19507e0f103f17669c13ae26d51b10146fe481c80c039814c0f7170e71dd953` |
| `02b-选完颜色.png` | 旅程④：选完颜色「浅灰」 | 264792 | `1c7fd436d4f11f84a9c8a2c37eb279040b81877de1bfd2bd57846b9734df27f9` |
| `03-填完宽高.png` | 旅程⑤：填完净窗宽 6.6 / 净窗高 2.6（自动徽标 + 面板已渲染） | 317474 | `9e7d522a6bc4832dfd816e480f74428e21517cf12236065df59557cc60d977cb` |
| `04-推导面板.png` | 旅程⑥：推导面板读数现场（§11.3 的截图证据） | 336045 | `0d65dccfad2a4ecd69e0783d3f7a31d4a9e95ce853a2c165a5eaf6cd00ba4c24` |
| `probe-typing-zero.mjs` | **第二条探针**：在同一套栈上逐字符敲 `0` `.` `5` / `0` `.` `6`，每一击读 DOM 值（§11.6） | 3441 | `3099d6afddd6ae44ffcbb342011d1113fb543cd4dfffefdea1fa6266ad8ba865` |
| `05-逐字符输0.5.png` | 上述探针跑完后的现场截图：`窗宽（米）` = **`0.6`**（第二轮终值，同帧可见 窗高 2.6 / 用料 1 / 商品「遮光窗帘 浅灰」） | 264835 | `c006bd11b714a6adf5311aa842519643ccd7aec0b0b59b0f0340bf4415b810c0` |
| `run-splice.txt` | **第三轮运行**（`WIDTH_M=10 HEIGHT_M=2.6`）的 stdout：候选表带出**每个候选的拼接次数**（§11.7） | 7852 | `aba25cf581ca03d5b0fa558bba73f0b4d5c1eca797e046620ac59c85d457612d` |
| `06-推导面板-倒幅候选7次拼接.png` | 该轮现场截图：窗宽 **10** / 高 2.6 / 用料 **20.3 米**，候选里「倒幅（定宽买高）：可行 · 用料 23.2 米 · **拼接 7 次**」 | 334066 | `eada674ad4c47d3c2ffe0d01b372b74dbb0f8352c6da2077753caea541855c6b` |

本目录的读数是**三轮独立运行**（不是一次）：
① `probe-orders-new.mjs`（默认 `6.6` × `2.6`）⇒ stdout = `run.txt`（末行 `PROBE_DONE_OK`）；
② `probe-typing-zero.mjs`（逐字符输 `0.5`）⇒ stdout **未作为文件归档**，读数见 §11.6（按 §2 ⑨ 重跑即可拿到）；
③ `probe-orders-new.mjs`（`WIDTH_M=10 HEIGHT_M=2.6`）⇒ stdout = `run-splice.txt`，截图 = `06-…png`（见 §11.7）。

> ⚠️ **源目录 `/tmp/ua-evidence/` 在第③轮之后已被改写**（如实登记，因为它影响「去哪找原始件」）：
> `probe-orders-new.mjs` 已被换成参数化版；`02-选完商品` / `02b-选完颜色` / `03-填完宽高` 三张 png 被第③轮覆盖
> （字节数已变）；第①轮的 `04-推导面板.png` **在源目录里已不存在** ⇒ 本目录的这份（sha256 `0d65dccf…`）
> 是**归档时刻的原始字节**，也是**现存唯一副本**。第①轮的 `run.txt` 未受影响（仍 7582 字节）。
> ⇒ 上表各文件的 sha256 以**归档时刻**为准，不随后续源目录覆盖而变；核对归档用下面那条命令即可。

> ⚠️ **归档名是 `run.txt` 而不是 `run.log`**（源文件名是 `run.log`）：仓库 `.gitignore` 有 `*.log`，
> 且**全仓 tracked 的 `.log` 文件数为 0** —— 证据一律按既有先例存 `.txt`
> （如 `acceptance/2026-09-14/mini-app-e2e/run-logs/run1.txt`）。
> ⇒ **内容逐字未改**（sha256 与源文件同值：`705faff5bf4a68c5927f4b776e29595e9dd43395113fcf0004a56ac7b4d820ac`），
> 只换了扩展名以免与仓库忽略规则打架。

复核本目录没被改动过：

```bash
cd acceptance/2026-09-23/order-auto-derivation/ua
# 第一批（§0 上表那 11 个文件；**逐字列出** —— 别用 `*.png` 通配，
# 它现在会把 §0.1 第二批的 png 一起卷进来，输出与上表对不上）
shasum -a 256 probe-orders-new.mjs probe-typing-zero.mjs run.txt run-splice.txt \
  00-登录页.png 01-orders-new-初始.png 02-选完商品.png 02b-选完颜色.png 03-填完宽高.png \
  04-推导面板.png 05-逐字符输0.5.png 06-推导面板-倒幅候选7次拼接.png
# 第二批（§0.1 下表）
shasum -a 256 probe-ua2-manual-override.mjs probe-typing-zero-sites.mjs probe-plan-unavailable.mjs \
  run-ua2-manual-override.txt run-typing-zero-sites.txt run-plan-unavailable.txt \
  ua2-*.png sites-*.png degraded-*.png
```

### 0.1 第二批归档（issue #5255：UA-2 判定 + 四站点逐字符 + 降级提示对照）

本批由**独立验收包**（worktree `../migao-wt/5255-ua-realbrowser-extension`，分支
`test/5255-ua-realbrowser-extension`）在同一套本地栈上产出；被测 commit =
`df88e4f6922ad4b37e7c27a8e82ba98baf23be21`（= `origin/main` 起点）。逐字清单与 `sha256` 见
[../report.md](../report.md) §12.4（**不在此重复**，避免两处各写一份会漂移）。

| 文件 | 是什么 |
|---|---|
| `probe-ua2-manual-override.mjs` | UA-2 探针：`S0` 基线 → 手工改接高 → 手工改加工类型 → 手工加拼次 → 手工改用料 + 改宽（未跟随）→ 点「恢复按公式计算」 |
| `run-ua2-manual-override.txt` | 上述探针的 stdout（含逐条 `[DOM] notice_*` 逐字与 `[server]` 引擎 plan 读数） |
| `probe-typing-zero-sites.mjs` | 四站点逐字符探针（`'0'`→`'.'`→`'5'` 每击读 DOM + 抓提交载荷 + `'0'` 一击 + 各站点守卫） |
| `run-typing-zero-sites.txt` | 上述探针的 stdout |
| `probe-plan-unavailable.mjs` | 降级提示探针（issue #5255 §A 判据 3 的**对照件**：让 `data.plan` 真的缺席） |
| `run-plan-unavailable.txt` | 上述探针的 stdout |
| `ua2-10…ua2-15`（7 张 png） | UA-2 每个状态的**同帧截图**（含 `ua2-14b-未跟随告知.png`） |
| `sites-b1…sites-b4`（8 张 png） | 四站点提交前/提交后的同帧截图 |
| `degraded-推导服务未就绪.png` | 「推导服务未就绪」真实触发现场的截图 |

> **与本目录第一批的关系**：第一批（§0）只覆盖一条「全自动推导」旅程，**UA-2 与多站点逐字符都不在里面**；
> 第二批**不改**第一轮的任何读数（两份 stdout 各自独立、可分别复算）。
> ⚠️ **本目录两批都仍然不是自动化测试**（无 `# case_ids:`、不进 CI 判据面）。

### 0.2 第三批归档（issue #5262：两条观察项的**补读数** —— 请求载荷 + 422 上屏文本）

本批由**独立取证包**（worktree `../migao-wt/5262-ua-observations`，分支 `test/5262-ua-observations`）
在同一套本地栈上产出。⚠️ **被测 commit = `e48818410`（= `origin/main` 起点）** —— 与 §0.1 第二批的
`df88e4f69` **不是同一个 commit**，两批读数**不可逐字比对**。判定见 `../report.md` §13。

| 文件 | 是什么 |
|---|---|
| `probe-5262-plan-attribution.mjs` | #5262 探针：`S0c`（面板收起）→ `S0`（展开后全自动基线）→ `S1`（**只**改接高 0.05）→ `S1b`（清空接高）→ `S2`（接高 0.05 **+** 拼2次 ⇒ 422）→ `S3`（清空接高、拼2次保留 ⇒ 200 对照）→ `S4`（显式点「定高买宽」+ 拼2次）→ `S5`（恢复） |
| `run-5262-plan-attribution.txt` | 上述探针**最终版**一次完整运行的 stdout（**权威读数**：含 `[req]` 请求载荷「人工面四键 + `*_sent`」、`[server]` 逐字段、逐帧 `[diff]` 对照、错误行 `in_viewport`） |
| `run-5262-plan-attribution-r2.txt` | **同探针、未含「滚动修复」版**的完整读数（保留以复核 `panel_in_viewport` / `calc_error_in_viewport` 的**未滚动前**取值；两版的 `[req]`/`[server]` 序列逐字相同） |
| `5262-a1-S0c-面板收起.png` | `S0c`：**面板收起** ⇒ `加工类型` radiogroup **不在 DOM**（解释 §0.1 归档里 `cutting_mode_checked=[]` 的读数假象） |
| `5262-a2-S0-展开后基线.png` | `S0`：展开「改工艺参数」后的全自动基线（此刻加工类型已选中「定高买宽」、**无「自动」徽标**） |
| `5262-a3-S1-只改接高0.05.png` | `S1`：**只**手工改接高 0.05 ⇒ 面板出现「人工指定（不再被自动改判）」+ 依据行「加工类型按人工值…逐字采用」 |
| `5262-a4-S1b-清空接高.png` | `S1b`：清空接高 ⇒ 回到「系统推导」（可逆性） |
| `5262-b1-S2-接高0.05+拼2次-422.png` | `S2`：**422 帧**（面板同帧仍写「已并入特殊选项 ⇒ 插工序 + 计件」） |
| `5262-b1b-S2-422-错误行.png` | `S2` 同一帧、把**试算失败红字滚入视口**后的截图（一屏同时拍到「红字错误」+「面板说已并入」） |
| `5262-b2-S3-拼2次-合法对照.png` | `S3`：清空接高（拼2次保留）⇒ 引擎 200「定宽买高 + 拼2次」（同一面板文案、引擎同意） |
| `5262-b3-S4-显式定高买宽+拼2次.png` | `S4`：显式点「定高买宽」+ 拼2次 ⇒ 请求**确实带** `cutting_mode`，但引擎回 `定宽买高`（同族相邻发现，未定性，见 §13.3） |
| `5262-b4-S5-恢复.png` | `S5`：拼次回「由推导决定」+ 加工类型回「未指定」⇒ 恢复（此帧 `cutting-mode-auto` 徽标才出现 = 「自动」） |

> **本批相对 §0/§0.1 的两处探针增量**（这两条正是 #5255 归档里缺的读数）：
> ① **记请求载荷**（`[req]`，含「这个键到底发没发」的 `*_sent` 布尔）—— 只记响应无法回答
> 「引擎**实际收到**的人工值是什么」；② **先展开「改工艺参数」再抓 S0**（另留 `S0c` 收起态作对照）
> —— 否则 S0 与 S1 不在同一 DOM 条件下，会出现「选中态从空集变成选中」这种**读数假象**。

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
| （第二轮，见 `05-逐字符输0.5.png`）`窗宽（米）` = `0.6` | §11.6：`0.` 中间态未被吞、`0.5`/`0.6` 打得出来 |
| （第三轮，见 `run-splice.txt`）`candidates(5)` 里两条可行候选 = `拼接 0 次` / `拼接 7 次`；`倒幅 + 接宽` 的理由带真实数字 `20.3 − 7×2.8 = 0.7 米 > 上限 0.1 米` | §11.7：候选级拼接次数上屏 + 契约公式与上屏文案同源 |

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

> 🔴 **本条的路径已过期（2026-09-23 第三批实测）**：`docs/sql/schema.sql` **已不存在** ——
> issue **#5243 / PR #5256**（`feat(db): 建库收口为「唯一建库脚本 + 归档链」`，commit `6198407e3`）
> 把它移到了 **`backend/admin-api/src/main/resources/db/init/schema.sql`**，
> 并把 `docs/sql/` 只留下 `archive/`。照旧配方跑会得到
> `psql: 错误: docs/sql/schema.sql: No such file or directory`（`SCHEMA_FAIL`）——
> 形态像"配方坏了"，实际是**建库脚本搬了家**。详见 §3 末两行。

```bash
# 现行路径（仓库相对全路径；`docs/sql/schema.sql` 是**旧路径**，已随 #5256 迁走）
psql -h 127.0.0.1 -p 5432 -U migao_admin -d ai_customer_service \
  -f backend/admin-api/src/main/resources/db/init/schema.sql
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

**第二批（#5255）实测补齐的 4 件事**（缺任一条：要么起不来、要么**登录不上**，且形态都像产品 bug）：

```bash
# ① 先打包（worktree 里没有 target/ ⇒ 没有 jar 可跑）
./mvnw -q -DskipTests -Dmaven.test.skip=true package     # 在 <worktree>/backend/admin-api

# ② 万能验证码**默认是关的**（`sms.bypass-code: ${SMS_BYPASS_CODE:}`，空 = fail-closed）⇒ 必须显式给。
#    不给的后果：点「获取验证码」被 60s 防刷拦下、登录返回 401「短信验证码错误或已过期」——
#    看上去像账号/权限问题，实际是没启用 bypass。
SMS_BYPASS_CODE=123456

# ③ Redis 要**可达**（验证码/令牌走它）：本机 6379 是别人带密码的实例（`NOAUTH Authentication required`）
#    ⇒ 起一个自己的空密码实例最省事：redis-server --port 6380 --save '' --appendonly no
REDIS_HOST=127.0.0.1 REDIS_PORT=6380 REDIS_PASSWORD=

# ④ JWT RSA：worktree 的 `rsa/private.pem` 是 **gitignored**（只有 public.pem 入库）
#    ⇒ `java -jar` 直接 `JWT RSA 密钥加载失败`（fail-fast，不回退 HS256）。用 PEM 内容注入最省事：
JWT_PRIVATE_KEY_PEM="$(cat <主仓>/backend/admin-api/src/main/resources/rsa/private.pem)" \
JWT_PUBLIC_KEY_PEM="$(cat <主仓>/backend/admin-api/src/main/resources/rsa/public.pem)" \
java -jar target/admin-api-1.0.0-SNAPSHOT.jar
#    （另一条路 = 把 private.pem 拷进 worktree 的 `src/main/resources/rsa/` —— 但**必须在 `mvn package` 之前**拷，
#      先打包后拷 ⇒ jar 里没有它，照样起不来。）
```

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
# 默认尺寸（6.6 × 2.6）⇒ 复现 run.txt
PHONE=13600136000 BASE_URL=http://localhost:3001 OUT_DIR=<某空目录> \
  node acceptance/2026-09-23/order-auto-derivation/ua/probe-orders-new.mjs

# 换尺寸（10 × 2.6）⇒ 复现 run-splice.txt（候选表会带出每个候选的拼接次数，见 §11.7）
PHONE=13600136000 BASE_URL=http://localhost:3001 OUT_DIR=<另一个空目录> WIDTH_M=10 HEIGHT_M=2.6 \
  node acceptance/2026-09-23/order-auto-derivation/ua/probe-orders-new.mjs
```

> 🔴 **每轮必须换一个 `OUT_DIR`**：该探针的截图名是**固定的**（`00-登录页` … `04-推导面板`），
> 同一个 `OUT_DIR` 跑第二轮会**静默覆盖**第一轮的截图 —— 这正是源目录 `/tmp/ua-evidence/`
> 丢掉第①轮 `04-推导面板.png` 的原因（见 §0 的登记）。

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

### ⑩（第二批）先做**两处数据准备**（否则站点②/站点④ 的读数会被业务校验污染）

```bash
# ④ 退款站点的提交值：种子里 8 张单 actual_amount 全是 0.00 ⇒ 提交必 422「退款金额不能超过实收款 0.00」
psql -h 127.0.0.1 -p 5432 -U migao_admin -d ai_customer_service -c "UPDATE orders SET actual_amount = 100.00;"
```

```sql
-- 判据 3 的对照态（「推导服务未就绪」）需要该行的 SKU **解析不出正数门幅**：
--   door_width 是 NOT NULL ⇒ 置 NULL 会报 `null value in column "door_width" … violates not-null constraint`；
--   且唯一约束是 (product_id, color_id, door_width) ⇒ 同一 product+color 的两行**不能同时**改成同一个值
--   （`重复键违反唯一约束 uq_product_skus_combination`）⇒ 一个置 ''、另一个置非数字文案，两行都解析不出数。
UPDATE product_skus SET door_width = ''      WHERE id = 1;   -- prod_eval_summer
UPDATE product_skus SET door_width = '未维护' WHERE id = 6;   -- 同一 product+color 的另一行
```

### ⑪（第二批）跑 UA-2 探针（手工改 ⇒ 「未跟随 / 人工锁定」告知）

**同一套栈**（①–⑦ 照旧；登录手机号 `13600136000`、`BASE_URL=http://localhost:3001` 也都照旧）：

```bash
PHONE=13600136000 BASE_URL=http://localhost:3001 OUT_DIR=<某空目录> CUT_TO=定宽买高 \
  node acceptance/2026-09-23/order-auto-derivation/ua/probe-ua2-manual-override.mjs
```

> ⚠️ **顺序不能随意换**：探针按 `S0→S1(接高)→S1b(清空接高)→S2(加工类型→定宽买高)→S3(拼1次)→S4(用料 7.7 + 改宽)→S5(恢复按公式)`
> 推进。**合法组合**是前提：`定高买宽` 下拼次只能是 0、`倒幅` 下不能接高 —— 顺序错了会拿到引擎的 400/422
> （见 §3 末行），读数会被「算料失败」污染。
> ⚠️ `CUT_TO` 必须是**真实存在的另一档**（`定宽买高`）；档位表里第一项是「未指定」，
> 按 index 盲选会点到「未指定」（= 清掉人工覆盖，**不产生**「人工指定」读数）—— 第一轮就这么错过一次。

### ⑫（第二批）跑四站点逐字符探针 + 降级提示探针

```bash
# 四站点：① /products/<id> 行内改价 ② /inbound-orders 数量/单价/卷长 ③ /finance 金额 ④ /orders 处理退款
PHONE=13600136000 BASE_URL=http://localhost:3001 OUT_DIR=<另一个空目录> PRODUCT_ID=prod_eval_dark_green \
  node acceptance/2026-09-23/order-auto-derivation/ua/probe-typing-zero-sites.mjs

# 降级提示（判据 3 的对照件；前置 = §2 ⑩ 的第二段 SQL）
PHONE=13600136000 BASE_URL=http://localhost:3001 OUT_DIR=<再一个空目录> PRODUCT=夏日清风窗帘 COLOR=米白色 \
  node acceptance/2026-09-23/order-auto-derivation/ua/probe-plan-unavailable.mjs
```

> ⚠️ `probe-typing-zero-sites.mjs` **必须换 `OUT_DIR`**（截图名固定，同目录重跑会静默覆盖）。
> ⚠️ 它会在本地库里**留下痕迹**（SKU 改价、入库草稿、财务流水、一笔退款）—— 一次性库无所谓，
> 但若要在同一库上跑别的旅程，先跑别的再跑它。
> ⚠️ 站点② 的建单按钮文案是「**新建入库单**」（不含连续子串「建单」）⇒ 选择器写 `/建单/` 会 30s 超时。
> ⚠️ 站点④ 需要 `orders.actual_amount > 0`（§2 ⑩）。

### ⑬（第三批）跑 #5262 探针（请求载荷 + 422 上屏文本）

**同一套栈**（①–⑦ 照旧；登录手机号 `13600136000`、`BASE_URL=http://localhost:3001` 也都照旧）：

```bash
PHONE=13600136000 BASE_URL=http://localhost:3001 OUT_DIR=<某空目录> \
  node acceptance/2026-09-23/order-auto-derivation/ua/probe-5262-plan-attribution.mjs
```

> ⚠️ **内部步骤顺序固定**（`S0c → S0 → S1 → S1b → S2 → S3 → S4 → S5`），不要按"合法组合"重排 ——
> 本探针要的正是 **`S2` 那个非法组合**（人工接高 + 拼次 ≥ 1）的 422 现场（见 §3 末两行）。
> ⚠️ **输出目录换新**：截图名固定（`5262-a1…b4`），同目录重跑会静默覆盖。

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
| 换个尺寸重跑后，上一轮的截图**不见了** | 探针截图名固定（`00-`…`04-`），同一 `OUT_DIR` 会被静默覆盖 | **每轮换 `OUT_DIR`**（§2 ⑧）—— 源目录就是这么丢的第①轮 `04-推导面板.png` |
| 点「获取验证码」返回「发送过于频繁，请 60 秒后重试」，登录 401「短信验证码错误或已过期」 | `sms.bypass-code` **默认空 = fail-closed**（没用 `SMS_BYPASS_CODE` 启用万能码） | 起 admin-api 时给 `SMS_BYPASS_CODE=123456`（§2 ⑤ 第二批 ②） |
| `java -jar` 启动即 `JWT RSA 密钥加载失败，无法启用 RS256 签名` | worktree 的 `rsa/private.pem` 是 gitignored（只有 public.pem 入库） | `JWT_PRIVATE_KEY_PEM`/`JWT_PUBLIC_KEY_PEM` 注入 PEM 内容（或**打包前**拷 private.pem）（§2 ⑤ 第二批 ④） |
| admin-api 连不上 Redis（`NOAUTH Authentication required`） | 本机 6379 是**别人**带密码的实例 | 起自己的 `redis-server --port 6380`（§2 ⑤ 第二批 ③） |
| 站点④ 退款提交必 `422 退款金额不能超过实收款 0.00` | 种子里 8 张单 `actual_amount` 全是 `0.00` | 先把某张单调大（§2 ⑩）—— 否则会把**业务校验**误读成**解析口径**问题 |
| 想造「门幅未维护 ⇒ `plan` 缺席」的降级态，`UPDATE … door_width = NULL` 却报 not-null | `door_width` 是 `NOT NULL`；且唯一约束 `uq_product_skus_combination` = `(product_id, color_id, door_width)` ⇒ 同一 product+color 的两行不能改成同一个值 | 一行置 `''`、另一行置非数字文案（§2 ⑩ 的 SQL） |
| 探针选 `getByRole('button', { name: /建单/ })` 30 秒超时 | 站点② 的按钮文案是「**新建入库单**」（不含连续子串「建单」） | 选择器用 `/新建入库单/`（§2 ⑫） |
| 手工加「拼2次」后 craft-calc 稳定 `422 CRAFT_CALC_UNAVAILABLE`（引擎原文「加工类型「定高买宽」是买宽订单、零拼接 ⇒ 拼次只能是 0」） | **不是缺陷**，是引擎的合法性判据：`定高买宽` 下拼次只能是 0、`倒幅` 下不能接高 | 探针按**合法组合**排序（§2 ⑪）—— 否则读数会被「算料失败」污染 |
| 按配方跑到 ② 就 `SCHEMA_FAIL`：`psql: 错误: docs/sql/schema.sql: No such file or directory` | **建库脚本搬家了**（#5243 / PR #5256，commit `6198407e3`）：旧 `docs/sql/schema.sql` → 现行 `backend/admin-api/src/main/resources/db/init/schema.sql`（`docs/sql/` 只剩 `archive/`） | 用 §2 ② 的**现行路径**（见该节的红字提示） |
| 想复现「`定高买宽` + 拼2次 ⇒ 422」，**光点加工类型「定高买宽」+ 拼2次复现不出来**（拿到的是 `200 定宽买高`） | 引擎 `curtain_calc.derive_plan` 的 `_implied_mode()` 里「**人工拼次 ≥ 1 ⇒ 蕴含倒幅**」**先于**显式 `cutting_mode` 生效 ⇒ 显式「定高买宽」被**静默改写**成「定宽买高」，不抛错 | 422 的真实前置 = **人工接高（把 effective_mode 钉死在定高买宽）** + **拼次 ≥ 1** 同时存在；探针 `S2` 即按此构造（§2 ⑬） |
| 面板写「拼接 拼2次（已并入特殊选项 ⇒ 插工序 + 计件）」，而同一屏红字说引擎拒绝该组合 | 面板那行由前端按**人工覆盖值**直接算出（不读引擎判定）；失败时 `calc` 不更新 ⇒ 面板继续显示**上一次成功**的 `plan`（用料也是陈旧值） | 本单**只取证**：读数与定性见 `../report.md` §13.2（判据 3「不得仍显示已并入」不满足） |

## 4. 本目录的边界（照实登记，不许读成"UA 全做完"）

- 本目录**只覆盖一条旅程**：商品「遮光窗帘」+ 颜色「浅灰」+ 净窗宽 6.6 / 净窗高 2.6。
  **其余商品 / 颜色 / 尺寸组合未走**。
- §11.6 的逐字符读数**只覆盖一个站点**（下单页「窗宽（米）」）。
  **不许**把它推广成「全仓 6 个数字输入站点都已真浏览器验证」—— 其余站点的护栏在 #5228 / #5237，
  本次**一个都没跑**。
  > ⚠️ **本条已被 §0.1 第二批部分补上**（issue #5255 §B 的**四个站点 5 个字段**：商品详情行内改价 /
  > 入库单 数量·单价·卷长 / 财务 金额 / 退款金额 —— 读数见 `run-typing-zero-sites.txt`）。
  > 但**仍然不是"全仓数字输入都过了"**：其余站点（`SkuMatrix` / 算料配置 / 工人工端 等）**依旧没跑**，
  > 护栏仍在 #5228 / #5237。原文保留以留痕。
- 本旅程**没有**覆盖「商家手工改加工类型 / 拼次后被判『未跟随』」这条路径 ⇒
  **UA-2 仍未做**（§11.4），本目录里**没有任何**可支撑它的读数。
  > ⚠️ **本条已由 §0.1 第二批补上**（issue #5255 §A：手工改接高 / 加工类型 / 拼次 / 用料四条路径 +
  > 「推导服务未就绪」降级提示的对照读数 ⇒ 读数见 `run-ua2-manual-override.txt`、`run-plan-unavailable.txt`，
  > 判定见 `../report.md` §12.1）。**判定结论不是"全绿"**：判据 2 判「**半满足**」（可改进点、非缺陷 ——
  > 告知缺「推导值 / 差多少米」这个量，已在 §12.3 登记为待裁定），本单**只回报、未改实现**。
  > 原文保留以留痕。
- **未做**：`bmini-app` 真机、多租户切换、「不采纳推导项」后的组合键核对（§11.5）。
- **第二批仍**未覆盖 / 未跑的（照实登记，详见 `../report.md` §12.3）：真变异红证（本单禁改 `frontend/**`）、
  UA-2 的**订单落库后核对**（只到界面告知 + 引擎响应）、降级态里 `size-door-width-missing` 徽标**未出现**的归因、
  以及两条观察项（只改接高却把加工类型标成「人工指定」；`定高买宽 + 拼2次` 的 422 与「已并入特殊选项」并存）。
  > ⚠️ **末两条（两条观察项）已由 §0.2 第三批取证**（issue #5262，被测 commit `e48818410`）：
  > 读数见 `run-5262-plan-attribution.txt`、**定性见 `../report.md` §13**（① 判缺陷、② 判缺陷；
  > 并**订正**了 "只改接高会让选中态从空集变成选中" 这条读数假象）。**其余各项仍未做**，原文保留以留痕。
  > ⚠️ 第三批**仍未覆盖**：订单**提交后**的工序 / 计件落库核对、其余商品 / 颜色 / 尺寸组合、
  > `S4` 那条「显式加工类型被蕴含口径静默改写」的定性（登记为待裁定，`../report.md` §13.3）。
- 本目录**不是**自动化测试：没有 `# case_ids:` 声明，不进 CI 判据面；它是**人可复算的验收证据**。
  要把它变成防回退判据，应另立用例（`#5218`/`#5228` 家族已有同类做法）。
