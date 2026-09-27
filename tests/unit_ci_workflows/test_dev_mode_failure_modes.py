# case_ids: MC-028, MC-038
"""**容易犯的问题必须固化进研发模式**：技能里的每一条纪律都要有「判别动作 / 判据 / 台账」三选一。

## 病根（不是「文档写得不够好」，而是**散文拦不住任何东西**）

本会话实测：一句写着「与种子矩阵逐值同步」的注释（`RoleService` 的 `issue #5291` 那处）**骗过了两个包**，
其中一个据此把错误归因写进了 `origin/main` 的代码注释。⇒ **「写一段劝告」不是交付**：
劝告不会被任何判据读，收窄它、删掉它、让它腐烂，**都不会有东西变红**。

同族（同一份转述被独立复核推翻的两条，见 `docs/design/rbac-single-source.md` §1.4 与 issue #5687）：

- **转述 ≠ 复核**：一份清单里的 13 件事，逐条去 `origin/main` 读一遍才发现有若干条**读错了对象**
  （典型：「验收协议 v1.11 的三问」其实住在 `.agent-presets/migao/skills/migao-acceptance/SKILL.md`
  的「交付物可达性判据（v1.11 新增）」，而 `docs/testing/acceptance-protocol.md` 里**没有**这一节）；
- **计数对象不等价**：用 `grep -c '^### '` 判「casebook 摘要跟没跟上」时，现取差值是
  `case_blocks + 1`（那 1 条是 `### 真值缺口用例（truths_ref 为空…）` 这个**非用例标题**）
  ⇒ **两个计数不是同一个对象**，必须先把那 1 条具名扣掉再比。

## 本文件锁什么（十条判据，逐条都有能单独变红的负向夹具）

| # | 判据 | 取法（**结构化，不读散文**） | 红证 |
|---|---|---|---|
| 1 | 技能里那一节**存在且非空** | 按标题字面定位 `## ` 节 | 删掉整节 ⇒ 红 |
| 2 | **覆盖面登记（边界）小节存在且非空** | 按标题字面定位 `### ` 子节 | 删掉边界子节 ⇒ 红 |
| 3 | 台账条目 ⇄ 技能节里的 `FM-xN` 记号 **双向相等** | 正则取记号；两个方向都判 | 技能里加一条未登记 ⇒ 红；台账里有而技能没写 ⇒ 红 |
| 4 | 每条**三选一**（`criterion` / `action` / `ledger_ref`）且**可解析** | `kind` 决定必须给哪个字段；`criterion`=`<path>::<symbol>`，symbol 必须在文件里**逐字出现** | 只写劝告（kind 缺失）⇒ 红；判据指到不存在的符号 ⇒ 红 |
| 5 | 每条至少有一条**机器可核的 evidence**（`<path>` 或 `<path>::<symbol>`） | 逐条解析到磁盘 | 锚点写错（符号漂移）⇒ 红 |
| 6 | **判别动作行（现取）**：边界节里列出的 id 集合 == 台账里 `kind=action` 的 id 集合 | 正则取 backtick 里的 id | 新增一条只靠人执行的条目而不登记 ⇒ 红；把 action 条目升级成判据后不移出边界 ⇒ 红 |
| 7 | CI 面的每条 `FM-EN` 必须**具名出现在 `docs/wiki/CI-CD.md`**，且 `guarded` 必须有可解析判据、`registered` 必须有可解析台账引用、`gap` **必须有 owner + 显形条件且不得带判据** | 双向 + 按 state 分派 | 「已修的又登记一遍」⇒ 红；「gap 却带着判据」= 陈旧 ⇒ 红 |
| 8 | **未守护台账只许缩短**：`state=gap` 条数 ≤ **本文件冻结的上限** | 上限**写在本文件里**（台账改不动它） | 新增一条 gap 而不动上限 ⇒ 红 |
| 9 | **本单未固化项只许缩短**：条数 ≤ 本文件冻结上限，每条须带 `reason` + `restart_when` | 同上 | 加一条「未固化」⇒ 红 |
| 10 | **fail-closed**：语料为空 / 节为空 ⇒ **非空违规**，不得静默放行 | 空串喂进纯函数 | 空技能文本 ⇒ 红（不许「没东西可判 ⇒ 绿」） |

**另一组（判据 14~18）= §26「转述与派单的纪律（集成侧 / 协调侧）」** —— §25 的**对称面**：
§25 治的是**执行侧**（包 / agent 把读到的对象读错），而**转述侧**（派单、写提示词、把别人的读数写进
指令的那一方）此前**没有任何承载体**，实测却是最频繁出错的一方（两个包各核出 7 处不准）。
这一组沿用**同一套机制**（记号 ⇄ 台账双向绑定 · kind/state 三选一 · 判别动作行现取 · 边界子节 · 只许缩短），
只把 id 族换成 `FM-R*`、把台账 key 换成 `relay_entries`：
14 = 节存在 / 边界子节存在；15 = `relay_entries` ⇄ §26 记号**双向相等** + 每条
`kind`∈{criterion,action,ledger} **且** `state`∈{guarded,registered,gap}（**任一非法 ⇒ 报「只写了劝告」**）
+ `same_family` 里的记号必须真实存在 + `evidence` 可解析；16 = §26 的**判别动作行（现取）**；
17 = relay 面 `gap` 条数只许缩短；18 = §26 里**不许出现裸行号引用**（行号会腐，`FM-A10` 同因）。

**另三条（判据 19/20/21）= 「承载体自己会不会腐烂 / 产物在不在工具的半径里 / 清单标题的条数会不会腐烂」**：

- **判据 19 = §19 索引表第 19 行（活索引）的读数 ≡ 台账现取**：范围端点 `FM-<族><i>`~`FM-<族><j>`
  必须等于该族 id 的**现取 min/max**（⚠️ **端点不是条数** —— 该族有缺号时两者必然不等，这正是
  `FM-A4`/`FM-A8` 的形态），`INDEX_CLAIMS` 策展表里登记的计数必须等于现取，**未登记的读数形态 ⇒ 红**
  （只许缩短）；行被删 / 读数取不到 ⇒ 红（fail-closed）。病灶实测：那一行与台账**脱钩**
  （端点停在旧号、`kind=action` 的条数停在 4），而**没有任何判据管它** ⇒ 腐烂是静默的。
- **判据 20 = 技能里**教的**建 worktree 命令必须落在**收尾半径**内**（`FM-R8`）：路径参数必须在
  `WT_BASE`（= `MIGAO_WT_BASE`，或默认 `<仓库根>/../migao-wt`）之下；`--detach` **纯检出豁免**
  （只读、用完即删，不产生需要收尾的分支产物）。病灶实测：`scripts/issue-lifecycle.sh reap-merged`
  **存在**、也真在跑，而本会话**每个** worktree 都被判「不在工作区根下 ⇒ 自动收尾半径外」
  —— 派单模板给的命令让检出落在**仓库里面** ⇒ **工具存在 ≠ 产物可达**。
- **判据 21 = 两份清单标题里的条数 ≡ 台账现取**（`LIST_COUNT_CLAIMS` 策展表：§25.2 的 **A 族** /
  §26.2 的 **R 族**）：标题里的 `（N 条）` 必须等于现取；**标题被删 / 读数形态被删 ⇒ 红**（fail-closed）。
  病灶 = 本单**现取到的实况**：§26.2 的标题写着「七条」而台账 `relay_entries` 现取 **8** 条，
  **此前没有任何判据管它** —— 与判据 19 治的「§19 索引行腐烂」**同族**（对象从索引行换成清单标题）。
  **边界**：只认 `（N 条）` 这一种**结构化**形态；自然语言计数与叙述句仍在面外（台账 `NS-4` 的 ②）。

**另有三条（判据 11/12/13）**：11/12 = 抢号唯一性（用例号 / 迁移版本号，见本文件末节）；
**判据 13 = `FM-E14`** —— `node --test` 的**目标参数必须是 glob**（传**目录**会被 Node 内置 runner
读成 **1 条失败的假红**），承载体 = `verify-all.sh` 与 `.github/workflows/worker-h5-tests.yml` 两处。
⚠️ 这条**不是**「把纪律写成散文」：写成散文的那一版（`docs/wiki/Development.md` 里已有该坑）**拦不住**
任何人把参数字面量改成目录形态 —— 判据 13 才是那个「拦住」（`FM-E14` 的 gap 就是按这个口径销账的）。

## 为什么判据 3/6/7 要**双向**

单向（只判「台账里的条目在技能里有没有写」）会被两种形态绕过：
① **在技能里写一条永不被判的纪律**（记账本没记 ⇒ 下一个人删台账条目时它照样烂在技能里）；
② **把已修的东西又登记一遍**（用户点名要避免的「重复登记」）—— 只有反向判据拦得住。

## 🔴 明确的边界（**不要**把本守卫读成覆盖面更大的东西）

- **它只保证「每条纪律都有承载体」，不保证「承载体本身是对的」**：`criterion` 解析成的是
  「文件里逐字出现这个名字」，**不是**「该判据真的会为这条纪律变红」。红是那条判据自己的事
  （本仓的口径在 `migao-dev-flow` §23 的 G7 与 `docs/wiki/CI-CD.md` 的「红证机具的可靠性」节）；
- **`kind=action` 条目靠人执行** —— 判据只能保证它**列在边界节里**、有可复制命令，
  **没有任何东西**会拦住「人不去执行它」（边界节的存在是给下一个人看的账，不是门禁）；
- **只覆盖 `FM-` 记号这一种形态**：一条**完全不写记号**的新纪律（纯散文加进技能）在本判据面内
  **看不见** —— 它不会命中判据 3（记号集合没变），也不会命中判据 4（台账里没有它）。
  这是**已知残余**（识别散文纪律需要有语义判定，本仓刻意不做文本层的一刀切）；
- **`evidence` 只核到「路径/符号存在」**：`refs` 里的 `#NNNN` / `PR #NNNN` 是**叙述性引用**，
  本判据**不联网核**（离线判据不连 GitHub）；
- **判据 7 只要求 `FM-EN` 具名出现在 `docs/wiki/CI-CD.md` 的**那一节**里 ——
  它**不**保证 CI 面的每一条旧纪律都已入册（存量不在本单射程）；
- 🔴 **判据 11/12（取号）的边界（本单自己踩到，如实登记）**：只看**已合并状态** ⇒ 拦不住『main + 在飞分支』的撞号
  ⇒ 那条唯一性判据给人一个它**并不具备**的保护感。**实证**：本单写侧先取 `MC-026`（当时现取最大号 = `MC-025`），
  而 #5705 在 2026-09-27 11:41:05 合并时已占 `MC-026` / `MC-027` ⇒ 本单**顺延为 `MC-028`**。
  **为什么不"加强"它**：能看到的在飞分支只有本地已 fetch 的 remote refs（CI 的 `actions/checkout` 只取当前分支
  ⇒ 同一份代码在 CI 与本机会得到**不同读数**），走 GitHub API 则引入网络依赖 ⇒ 违反「翻 required / 写判据要先
  确认**判定方式是确定的**」（`migao-dev-flow` §2.2）。⇒ **选择显式登记边界**，不硬凑。
  **显形条件**：main 上已合并占号 且 某个在飞分支同号（本会话用例号已撞 7~8 次、迁移号 1 次）。
- **判据 21 只覆盖两份清单标题里的 `（N 条）`**（§25.2 的 A 族 / §26.2 的 R 族）：`merge_log` 的历史句、
  正文里的自然语言计数（「两条」「七条」这类）**不在面内** —— 与 `FM-A11` 的 prose 边界同因
  （要覆盖得**逐条进策展表**，不是放宽正则）；本单实测的那处病灶（§26.2 写「七条」而现取 8 条）
  正是靠**人工复核**发现的，判据 21 保证的是它**不会再静默腐烂**，不是「结构上不可能出现」。
- 本判据**不改任何门禁的通过条件、不新增豁免**。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable

REPO_ROOT = Path(__file__).resolve().parents[2]

SKILL_REL = ".agent-presets/migao/skills/migao-dev-flow/SKILL.md"
LEDGER_REL = "tests/unit_ci_workflows/dev_mode_failure_modes_ledger.json"
CICD_REL = "docs/wiki/CI-CD.md"
LEDGER_PATH = REPO_ROOT / LEDGER_REL

#: 技能里承载本清单的节标题（字面；台账 `skill.section` 必须与它逐字相同）。
SECTION_HEADING = "## 25. 判别动作：读数与它声称的对象"
#: 覆盖面登记（边界）子节标题。
BOUNDARY_HEADING = "### 25.6 覆盖面登记：本清单**覆盖不到**什么"
#: 「判别动作行」在边界节里的取法（backtick 里的 `FM-xN` 记号）。
ACTION_LINE_PREFIX = "**判别动作行（现取）**："

#: 记号形态：`FM-` + 族字母 + 序号。
#: **技能面只用 A~D**（清单 A~D 落在 §25）；**CI 面单独一个族（E）**，落在 `docs/wiki/CI-CD.md`。
#: 两个面**分开取**：否则 §25 正文里引用一句 `FM-E2`（"登记见 CI-CD.md 的 FM-E2"）会被当成
#: "技能里写了一条未登记的纪律" ⇒ 假红（本单实测踩到，正是本文件要治的「读数与它声称的对象不是同一个」）。
ENTRY_ID_RE = re.compile(r"\bFM-[A-D]\d+\b")
CI_ID_RE = re.compile(r"\bFM-E\d+\b")
#: `criterion` / `evidence` 的 `<path>::<symbol>` 形态。
ANCHOR_SEP = "::"

#: 判据 8：`state=gap` 的**上限**（**冻结在本文件里** —— 台账改不动它；只许缩短）。
#: 历史读数（**每一次升降都在 diff 里可见**，这正是「不许默默加」的设计）：
#:   `3`（#5706 建账）→ `4`（#5709 新增 `FM-E17`，见台账 `PD-1`）→ `2`（#5707 两笔**销账**，见 `PD-2`：
#:   `FM-E4` → `guarded`（main 侧生成物新鲜度守护腿已落地并真跑过）·
#:   `FM-E14` → `guarded`（判据 13 落码，见本文件末节））→ **`1`**（#5707 本包再销一笔，见 `PD-8`：
#:   `FM-E17` → `guarded` —— 两条发布腿各自补了 `schedule` 兜底面（用户裁定 = 方案 A「周期重建重发布」），
#:   静态形状判据因此从「会给不存在的保护盖章」变成**真绊线**，判据 =
#:   `tests/unit_ci_workflows/test_publish_leg_fallback_surface.py`）。
#:   ⚠️ **`FM-E10` 仍留 `gap`，本包不动它**（它自己那半 = redproof 档 9 条实跑腿，在本包射程外）。
#: ⚠️ 判据语义 = `现取 gap 条数 ≤ GAPS_FROZEN` ⇒ **只许缩短**：把上限**抬到高于现取条数**不会红
#:   （所以要「上限 == 现取」得靠**销账时同批降上限**这个动作，而不是靠判据；本单就是这么做的）。
GAPS_FROZEN = 1
#: 判据 9：`not_solidified` 的**上限**（同上）。
#: 历史读数（每一次升降都在 diff 里可见）：`3`（#5706 建账）→ **`4`**（#5707 的用例库陈旧读数包新增
#: `NS-4`：用例库陈旧读数的**覆盖面** —— 面外实例「技能 §19 索引行」+ 面内形态「自由文本计数」，
#: 见台账 `PD-3`）。
NOT_SOLIDIFIED_FROZEN = 4
#: 本单新增的两条 CI 判据的**射程**（判据 11/12；收窄射程要先改这里）。
CASE_CORPUS_DIR = ".github/cases"
LIVE_MIGRATION_DIR = "backend/admin-api/src/main/resources/db/migration"
#: 判据 12 的**已登记**存量（`migration-archive/` 里版本号重复的 V 号，**只许缩短**）。
ARCHIVE_DUP_VERSIONS_FROZEN = 2
#: 取号判据（判据 11/12）的**已登记边界** —— 逐字出现在本文件的模块 docstring 里，由
#: `test_case_id_allocation_boundary_is_registered` 钉住（删掉 ⇒ 红）。**本单自己踩到过**：
#: 写侧取 MC-026 时现取最大号是 MC-025，而 #5705 合并后已占 MC-026/MC-027 ⇒ 顺延为 MC-028。
CASE_ID_ALLOCATION_BOUNDARY = "只看**已合并状态** ⇒ 拦不住『main + 在飞分支』的撞号"
#: 该边界必须随身携带的**实证锚**（撞号涉及的单号；少一个 ⇒ 红）。
CASE_ID_ALLOCATION_EVIDENCE = ("MC-026", "MC-027", "MC-028")

#: §26（**转述 / 派单面** = §25 的**对称面**）的节标题与边界子节标题（字面；台账 `skill` 之外
#: 单列，因为两面的**取法不同**：§25 取 `## 25.` 到下一个 `## `，§26 同法但 id 族不同）。
RELAY_SECTION_HEADING = "## 26. 转述与派单的纪律"
RELAY_BOUNDARY_HEADING = "### 26.4 覆盖面登记：本节**覆盖不到**什么"
#: §26 的台账 key（**与 `entries` 分开**：混成一个集合会让「§25 正文里引用一句 `FM-R1`」被读成
#: 「§26 里写了一条未登记的纪律」⇒ 假红；与 `ENTRY_ID_RE` / `CI_ID_RE` 分开取**同因**）。
RELAY_LEDGER_KEY = "relay_entries"
#: 记号形态：`FM-R` + 序号（R = relay / 转述）。
RELAY_ID_RE = re.compile(r"\bFM-R\d+\b")
#: 判据 17：relay 面 `state=gap` 的**上限**（冻结在本文件里 —— 台账改不动它；只许缩短）。
#: 语义与 `GAPS_FROZEN` 逐字同口径：`现取 ≤ 上限`，**抬到高于现取不会红** ⇒「上限 == 现取」靠
#: 销账时**同批降上限**这个动作。初值 = 建面时的现取条数（**每一次升降都在 diff 里可见**）。
#: 历史读数：`2`（#5707 建面：`FM-R4` / `FM-R7`）→ **`6`**（本单回灌四条**只靠人执行**的转述纪律
#:   `FM-R9` ~ `FM-R12`，见台账 `PD-5`：四条都能机械核「记号已登记 / `action` 非空 / 判别动作行现取」，
#:   但**判不了**「转述方有没有真去打开那个文件 / 有没有真跑那条检索 / 提修法前有没有复现」
#:   ⇒ 是**真缺口**，不许塞进 `guarded` 把「无机械锁」写成「已守护」）→ **`7`**（#5721 新增 `FM-R13` =
#:   「派单消息里的『环境已同步』断言会过期」，见台账 `PD-7`：`land` 侧那一半**已机械** —— preflight 每次
#:   打印工具来源（路径 + sha + 与 `origin/main` 的差），判据 `tests/unit_ci_workflows/test_land_tool_provenance.py`；
#:   而**派单侧那一半在仓外**（不 durable、判据读不到）⇒ 仍是**真缺口**）→ **`9`**（本单把**协调侧派单的
#:   7 处实测错法**回灌成两条，见台账 `PD-9`：`FM-R14` = 报集合成员 / 条数 / 全称量词 / 现状 / 载体前
#:   **先现取**、把**原始输出行**贴进结论（五处实测逐条写在它的 `symptom` / `gap_shows_when` 里）；
#:   `FM-R15` = **交出去的命令**先核**口径与前置**、把适用面写进派单。两条治的都是「**转述方到底跑没跑
#:   那条命令**」这一层 —— 判据看得见文本形态（记号已登记 / `action` 非空 / 判别动作行现取 /
#:   `evidence` 锚可解析），**看不见他跑没跑** ⇒ 是**真缺口**，不许塞进 `guarded` 把「无机械锁」写成「已守护」）。
RELAY_GAPS_FROZEN = 9
#: 判据 18：「文件 + 冒号 + 数字」形态的**裸行号引用**（行号会腐 —— `FM-A10` 已有实证：
#: 同一句话的行号几个提交后就指向别的对象）。射程 = §26 节文本。
#: ⚠️ **本判据自己不许把那个形态原样写进任何仓内文本**（`FM-A11`「举例即实例」）：注入式红证的
#: 标本串用**拼接**构造（扫描器看不到完整形态），说明文字一律「描述形态而不写出形态」。
LINE_REF_RE = re.compile(r"\b[\w./-]+\.(?:py|sh|md|json|ya?ml|ts|tsx|java|sql|mjs|txt):\d+")
#: 红证用的**裸行号**标本（拼接构造，见上）。
LINE_REF_SPECIMEN = "scripts/verify-all.sh" + ":" + "42"
#: §26.4 覆盖面登记必须**点名**的面（**正向**：防「把边界删光了事」，同
#: `test_dev_worktree_preset_wording.py` 判据 2 的口径）。删掉任一面 ⇒ 红。
RELAY_BOUNDARY_MARKERS = ("kind=action", "FM-R", "evidence", "收尾半径", "reap-merged", "派单消息",
                          # 本单（`FM-R9` ~ `FM-R12`）新增的面：四条**无机械锁** / workaround 的收窄
                          # （**先直连**，只有实测失败才绕）/ 转发壳与实现不同文件
                          "无机械锁", "先直连", "转发壳",
                          # #5721（`FM-R13`）新增的面：`land` 的**工具来源**读数（哪一份 / sha / behind）
                          "工具来源",
                          # 本单（`FM-R14` / `FM-R15`）新增的三面：① 「现取得出的**原始输出行**」这一形态
                          # 判不了（判据看不见他跑没跑）；② 「**交出去的命令**」的适用面（口径 / 前置）在仓外；
                          # ③ **载体**（值住在哪个数据源）要人知道有哪几个候选
                          "原始输出行", "交出去的命令", "载体")

#: 判据 13（`FM-E14`）的**射程**：本仓会跑 `node --test` 的**测试腿**（本地门禁腿 + 它的 CI 面）。
#: 收窄 / 扩大射程都要先改这里（frozen），语料是**具名路径**、不是 glob（不触发射程元守卫）。
NODE_TEST_GLOB_CARRIERS_FROZEN = ("verify-all.sh", ".github/workflows/worker-h5-tests.yml")
#: 判据 13 的**载体台账**（**只许缩短**）：目标参数**有意不是**测试文件集的调用点 ——
#: 就绪探针 `node --test --test-only /dev/null` 探的是「node 支不支持 `--test`」，不是测试集。
NODE_TEST_TARGET_ALLOWLIST_FROZEN = ("/dev/null",)
#: 一处 `node --test` 调用：到行尾 / `;` / `&` / `|` 为止（选项与位置参数都在这一段里）。
NODE_TEST_INVOCATION_RE = re.compile(r"\bnode\s+--test\b([^\n;&|]*)")
#: 「像路径」的目标参数（含 `/` 或 `.`）—— 散文里的**提及**（如 `(node --test)` 这种 job 名、
#: 注释里的 `` `node --test` 步 ``）不含这两者 ⇒ 不会被读成调用（**prose 豁免**，同 `FM-A11` 的分界）。
NODE_TEST_PATHLIKE_RE = re.compile(r"[/.]")


def strip_hash_comments(text: str) -> str:
    """剥掉 `#` 注释段（只认**行首或空白后**的 `#`；URL 里的 `#` 前面不是空白 ⇒ 不剥）。"""
    out: list[str] = []
    for line in (text or "").split("\n"):
        m = re.search(r"(?:^|\s)#", line)
        out.append(line[: m.start()] if m else line)
    return "\n".join(out)


# ──────────────────────────────────────────────────────────────────────────────
# 纯函数层：**判据吃文本**（红证当场在内存里构造坏形态，不改磁盘）
# ──────────────────────────────────────────────────────────────────────────────

def real_file_text(rel: str) -> str | None:
    """默认读盘器：仓库相对路径 ⇒ 文本；不存在 ⇒ None（**不抛**，交给判据判红）。"""
    p = REPO_ROOT / rel
    if not p.is_file():
        return None
    return p.read_text(encoding="utf-8")


def section_text(doc: str, heading: str) -> str | None:
    """按**标题前缀**取一节（到下一个同级或更高级标题为止）；取不到 ⇒ None。

    取**前缀**而不是全等：节标题后面常挂「（vX.Y.Z 新增，<日期> 用户裁定「…逐字…」）」这类
    会随版本变长的尾巴 —— 用全等会让判据在**每次抬版本号**时假红（把判据钉在易变的对象上）。
    """
    lines = doc.split("\n")
    level = len(heading) - len(heading.lstrip("#"))
    start = None
    for i, line in enumerate(lines):
        if line.strip().startswith(heading):
            start = i + 1
            break
    if start is None:
        return None
    end = len(lines)
    for j in range(start, len(lines)):
        s = lines[j].lstrip("#")
        if lines[j].startswith("#") and (len(lines[j]) - len(s)) <= level:
            end = j
            break
    return "\n".join(lines[start:end])


def ids_in(text: str, pattern: "re.Pattern[str]" = ENTRY_ID_RE) -> set[str]:
    return set(pattern.findall(text or ""))


def action_ids(ledger: dict) -> set[str]:
    return {e["id"] for e in ledger.get("entries", []) if e.get("kind") == "action"}


def _resolve_anchor(spec: object, file_text: Callable[[str], str | None]) -> str | None:
    """`<path>` 或 `<path>::<symbol>` ⇒ None（可解析）／违规原因。"""
    if not isinstance(spec, str) or not spec.strip():
        return f"锚点为空：{spec!r}"
    path, _, symbol = spec.partition(ANCHOR_SEP)
    text = file_text(path)
    if text is None:
        return f"锚点指向的文件不存在：{path}"
    if symbol and symbol not in text:
        return f"锚点在文件里逐字找不到：{spec}"
    return None


def ledger_violations(
    *,
    skill_text: str,
    cicd_text: str,
    ledger: dict,
    file_text: Callable[[str], str | None] = real_file_text,
) -> list[str]:
    """全部违规（空列表 = 全绿）。**纯函数**：只吃文本 + 读盘器，红证可当场构造坏形态。"""
    bad: list[str] = []

    # ── 判据 1/2/10：节存在、边界子节存在、空语料 fail-closed ───────────────────
    sec = section_text(skill_text, SECTION_HEADING)
    if not skill_text.strip():
        bad.append("技能语料为空 ⇒ 判据无从判定（**未跑 ≠ 通过**，fail-closed）")
    if sec is None:
        bad.append(f"技能里找不到节标题：{SECTION_HEADING!r}（整节被删 ⇒ 固化失效）")
        sec = ""
    elif not sec.strip():
        bad.append(f"技能节 {SECTION_HEADING!r} 是空的 ⇒ 固化失效")
    bnd = section_text(skill_text, BOUNDARY_HEADING)
    if bnd is None:
        bad.append(f"技能里找不到覆盖面登记子节：{BOUNDARY_HEADING!r}（删掉边界 ⇒ 红）")
        bnd = ""
    elif not bnd.strip():
        bad.append(f"覆盖面登记子节 {BOUNDARY_HEADING!r} 是空的（「无边界」= 声称覆盖一切）")

    skill_ids = ids_in(sec)
    ledger_ids = {e.get("id") for e in ledger.get("entries", [])}
    if not ledger_ids:
        bad.append("台账 `entries` 为空 ⇒ 未登记即红的另一半无从判定（fail-closed）")

    # ── 判据 3：条目 ⇄ 技能记号 双向相等 ──────────────────────────────────────
    for missing in sorted(ledger_ids - skill_ids):
        bad.append(f"{missing}：台账里有，技能节里**没有**写 ⇒ 纪律没有落到研发模式")
    for extra in sorted(skill_ids - ledger_ids):
        bad.append(f"{extra}：技能节里写了，台账里**未登记** ⇒ 未登记即红")

    # ── 判据 4/5：每条三选一 + 至少一条机器可核 evidence ───────────────────────
    for e in ledger.get("entries", []):
        eid = e.get("id", "?")
        kind = e.get("kind")
        if kind not in {"criterion", "action", "ledger"}:
            bad.append(
                f"{eid}：`kind`={kind!r} 不在 {{criterion, action, ledger}} 里 "
                f"⇒ 这一条**只写了劝告**（没有判别动作 / 判据 / 台账）"
            )
            continue
        if kind == "criterion":
            problems = [_resolve_anchor(c, file_text) for c in e.get("criteria") or []]
            problems = [p for p in problems if p]
            if not e.get("criteria"):
                bad.append(f"{eid}：kind=criterion 但没给 `criteria`")
            bad += [f"{eid}：{p}" for p in problems]
        elif kind == "action":
            if not str(e.get("action") or "").strip():
                bad.append(f"{eid}：kind=action 但 `action` 为空 ⇒ 离散文只有一步之遥")
        else:
            ref = e.get("ledger_ref")
            if not isinstance(ref, str) or ANCHOR_SEP not in ref:
                bad.append(f"{eid}：kind=ledger 但 `ledger_ref` 不是 `<path>::<记号>` 形态：{ref!r}")
            else:
                reason = _resolve_anchor(ref, file_text)
                if reason:
                    bad.append(f"{eid}：台账引用失效 —— {reason}")
        if not e.get("evidence"):
            bad.append(f"{eid}：没有任何 `evidence` ⇒ 这条固化**不可复核**")
        for ev in e.get("evidence") or []:
            reason = _resolve_anchor(ev, file_text)
            if reason:
                bad.append(f"{eid}：evidence 失效 —— {reason}")

    # ── 判据 6：判别动作行（现取）── 边界节列出的 id == kind=action 的 id ────────
    declared: set[str] = set()
    hit_line = False
    for line in bnd.split("\n"):
        if line.strip().startswith(ACTION_LINE_PREFIX):
            hit_line = True
            declared |= ids_in(line)
    if not hit_line:
        bad.append(
            f"覆盖面登记子节里没有 `{ACTION_LINE_PREFIX}` 行 ⇒ "
            f"「哪些条目只靠人执行」没有现取登记"
        )
    else:
        live = action_ids(ledger)
        for missing in sorted(live - declared):
            bad.append(f"{missing}：只靠人执行的条目不写在边界节 ⇒ 下一个人读不到这条账")
        for extra in sorted(declared - live):
            bad.append(
                f"{extra}：边界节把它登记成「只靠人执行」，而台账里它不是 kind=action ⇒ 陈旧"
            )

    # ── 判据 7：CI 面具名出现在 docs/wiki/CI-CD.md + 按 state 分派 ─────────────
    ci_ids = ids_in(cicd_text, CI_ID_RE)
    findings = ledger.get("ci_findings", [])
    for f in findings:
        fid = f.get("id", "?")
        if fid not in ci_ids:
            bad.append(f"{fid}：未具名出现在 `{CICD_REL}` ⇒ CI 面的纪律没有落点（只写散文）")
        state = f.get("state")
        if state not in {"guarded", "registered", "gap"}:
            bad.append(f"{fid}：`state`={state!r} 不在 {{guarded, registered, gap}} 里")
            continue
        if state == "guarded":
            crit = f.get("criteria") or []
            if not crit:
                bad.append(f"{fid}：state=guarded 却没给 `criteria`（守护为匿名 ⇒ 不可复核）")
            for c in crit:
                reason = _resolve_anchor(c, file_text)
                if reason:
                    bad.append(f"{fid}：守护判据不可解析 —— {reason}")
        elif state == "registered":
            ref = f.get("ledger_ref")
            reason = _resolve_anchor(ref, file_text) if isinstance(ref, str) else "缺 `ledger_ref`"
            if reason:
                bad.append(f"{fid}：state=registered 但登记引用不可解析 —— {reason}")
        else:
            if f.get("criteria") or f.get("ledger_ref"):
                bad.append(
                    f"{fid}：state=gap 却带着判据/台账引用 ⇒ **陈旧**（要么改成 guarded/registered，"
                    f"要么它已经不是缺口）"
                )
            if not str(f.get("gap_owner") or "").strip():
                bad.append(f"{fid}：gap 没有 `gap_owner`（缺口不许匿名存在）")
            if not str(f.get("gap_shows_when") or "").strip():
                bad.append(f"{fid}：gap 没有 `gap_shows_when`（无守护时的**显形条件**必须写出来）")

    # ── 判据 8：未守护台账只许缩短 ────────────────────────────────────────────
    gaps = [f for f in findings if f.get("state") == "gap"]
    if len(gaps) > GAPS_FROZEN:
        bad.append(
            f"未守护（gap）条数 {len(gaps)} > 上限 {GAPS_FROZEN}（上限冻结在本判据里）⇒ "
            f"新增缺口必须先把它做成判据或并入既有台账，不许默默加"
        )

    # ── 判据 9b：抬上限这类**决策**必须留痕，且条目不可静默删除 ──────────────────
    pd = ledger.get("policy_decisions", [])
    if not pd:
        bad.append(
            "台账缺 `policy_decisions` ⇒「**抬上限**」这类决策没有留痕"
            "（条目只许缩短 ⇒ 不可静默删除）"
        )
    for d in pd:
        for key in ("what", "decided_by", "why", "invariant", "targets"):
            if not str(d.get(key) or "").strip():
                bad.append(f"决策 {d.get('id', '?')}：缺 `{key}`（决策必须写清 谁裁的 / 为什么 / 不变式 / 靶子）")

    # ── 判据 9：本单未固化项只许缩短 ──────────────────────────────────────────
    ns = ledger.get("not_solidified", [])
    if len(ns) > NOT_SOLIDIFIED_FROZEN:
        bad.append(f"未固化项 {len(ns)} > 上限 {NOT_SOLIDIFIED_FROZEN} ⇒ 只许缩短")
    for item in ns:
        if not str(item.get("reason") or "").strip():
            bad.append(f"未固化项 {item.get('id', '?')}：缺 `reason`")
        if not str(item.get("restart_when") or "").strip():
            bad.append(f"未固化项 {item.get('id', '?')}：缺 `restart_when`（重启条件）")

    # ── 判据 14~18：§26（**转述 / 派单面**）—— 与 §25 **同一套机制**，两面**各自**双向绑定 ────
    rsec = section_text(skill_text, RELAY_SECTION_HEADING)
    if rsec is None:
        bad.append(f"技能里找不到节标题：{RELAY_SECTION_HEADING!r}（整节被删 ⇒ 转述面的固化失效）")
        rsec = ""
    elif not rsec.strip():
        bad.append(f"技能节 {RELAY_SECTION_HEADING!r} 是空的 ⇒ 固化失效")
    rbnd = section_text(skill_text, RELAY_BOUNDARY_HEADING)
    if rbnd is None:
        bad.append(f"技能里找不到覆盖面登记子节：{RELAY_BOUNDARY_HEADING!r}（删掉边界 ⇒ 红）")
        rbnd = ""
    elif not rbnd.strip():
        bad.append(f"覆盖面登记子节 {RELAY_BOUNDARY_HEADING!r} 是空的（「无边界」= 声称覆盖一切）")

    relay = ledger.get(RELAY_LEDGER_KEY) or []
    if not relay:
        bad.append(f"台账缺 `{RELAY_LEDGER_KEY}`（或为空）⇒ 转述面的纪律没有承载体（未登记即红）")
    relay_ids = {e.get("id") for e in relay}
    rskill_ids = ids_in(rsec, RELAY_ID_RE)
    for missing in sorted(relay_ids - rskill_ids):
        bad.append(f"{missing}：台账里有，技能 §26 里**没有**写 ⇒ 纪律没有落到研发模式")
    for extra in sorted(rskill_ids - relay_ids):
        bad.append(f"{extra}：技能 §26 里写了，台账 `{RELAY_LEDGER_KEY}` 里**未登记** ⇒ 未登记即红")

    for e in relay:
        eid = e.get("id", "?")
        kind, state = e.get("kind"), e.get("state")
        if kind not in {"criterion", "action", "ledger"}:
            bad.append(
                f"{eid}：`kind`={kind!r} 不在 {{criterion, action, ledger}} 里 ⇒ "
                f"这一条**只写了劝告**（没有判别动作 / 判据 / 台账）"
            )
            continue
        if state not in {"guarded", "registered", "gap"}:
            bad.append(
                f"{eid}：`state`={state!r} 不在 {{guarded, registered, gap}} 里 ⇒ "
                f"这一条**只写了劝告**（承载体没有形态：有守护 / 有登记 / 是缺口，三选一）"
            )
            continue
        if (kind, state) not in {("criterion", "guarded"), ("ledger", "registered"), ("action", "gap")}:
            bad.append(
                f"{eid}：`kind`={kind!r} 与 `state`={state!r} 不配对 "
                f"（criterion↔guarded · ledger↔registered · action↔gap）"
            )
        if not str(e.get("action") or "").strip():
            bad.append(
                f"{eid}：`action` 为空 ⇒ 每条都必须给出**判别动作**（一次就能做、可复制），"
                f"否则它与劝告无异"
            )
        for key, why in (("symptom", "症状（一句话）"), ("covers", "它**覆盖到哪一半**")):
            if not str(e.get(key) or "").strip():
                bad.append(f"{eid}：缺 `{key}` ⇒ {why}必须写出来，否则承载体不可复核")
        if state == "guarded":
            crit = e.get("criteria") or []
            if not crit:
                bad.append(f"{eid}：state=guarded 却没给 `criteria`（守护为匿名 ⇒ 不可复核）")
            for c in crit:
                reason = _resolve_anchor(c, file_text)
                if reason:
                    bad.append(f"{eid}：守护判据不可解析 —— {reason}")
        elif state == "registered":
            ref = e.get("ledger_ref")
            reason = _resolve_anchor(ref, file_text) if isinstance(ref, str) else \
                "缺 `ledger_ref`（state=registered 必须点名登记载体）"
            if reason:
                bad.append(f"{eid}：{reason}")
        else:
            if e.get("criteria") or e.get("ledger_ref"):
                bad.append(
                    f"{eid}：state=gap 却带着判据/台账引用 ⇒ **陈旧**（要么改成 guarded/registered，"
                    f"要么它已经不是缺口）"
                )
            if not str(e.get("gap_owner") or "").strip():
                bad.append(f"{eid}：gap 没有 `gap_owner`（缺口不许匿名存在）")
            if not str(e.get("gap_shows_when") or "").strip():
                bad.append(f"{eid}：gap 没有 `gap_shows_when`（无守护时的**显形条件**必须写出来）")
        fam = str(e.get("same_family") or "")
        if not fam.strip():
            bad.append(f"{eid}：没有 `same_family` ⇒ 孤立登记会让下一个人读不出它与哪一族同形")
        for mark in sorted(set(re.findall(r"\bFM-[A-Z]\d+\b", fam))):
            if mark not in skill_text and mark not in cicd_text:
                bad.append(f"{eid}：`same_family` 点了 `{mark}`，而它在技能与 {CICD_REL} 里都找不到")
        if not e.get("evidence"):
            bad.append(f"{eid}：没有任何 `evidence` ⇒ 这条固化**不可复核**")
        for ev in e.get("evidence") or []:
            reason = _resolve_anchor(ev, file_text)
            if reason:
                bad.append(f"{eid}：evidence 失效 —— {reason}")

    # ── 判据 16：判别动作行（现取，**§26 面**）────────────────────────────────
    rdeclared: set[str] = set()
    rhit_line = False
    for line in rbnd.split("\n"):
        if line.strip().startswith(ACTION_LINE_PREFIX):
            rhit_line = True
            rdeclared |= ids_in(line, RELAY_ID_RE)
    if not rhit_line:
        bad.append(
            f"§26 覆盖面登记子节里没有 `{ACTION_LINE_PREFIX}` 行 ⇒ "
            f"「哪些条目只靠人执行」没有现取登记"
        )
    else:
        rlive = {e["id"] for e in relay if e.get("kind") == "action"}
        for missing in sorted(rlive - rdeclared):
            bad.append(f"{missing}：只靠人执行的条目不写在 §26 边界节 ⇒ 下一个人读不到这条账")
        for extra in sorted(rdeclared - rlive):
            bad.append(f"{extra}：§26 边界节把它登记成「只靠人执行」，而台账里它不是 kind=action ⇒ 陈旧")

    # ── 判据 17：relay 面的 gap 只许缩短 ───────────────────────────────────────
    rgaps = [e for e in relay if e.get("state") == "gap"]
    if len(rgaps) > RELAY_GAPS_FROZEN:
        bad.append(
            f"转述面未守护（gap）条数 {len(rgaps)} > 上限 {RELAY_GAPS_FROZEN}（上限冻结在本判据里）⇒ "
            f"新增缺口必须先把它做成判据或并入既有台账，不许默默加"
        )

    # ── 判据 18：§26 里不许出现裸行号引用（`FM-A10`：行号会腐）──────────────────
    for hit in sorted(set(LINE_REF_RE.findall(rsec))):
        bad.append(
            f"§26 里出现裸行号引用 `{hit}` ⇒ 行号会腐（`FM-A10`）；引用一律给 "
            f"`<path>::<符号>` 锚（**行号不写**）"
        )

    return bad


def check_discriminating_power(*, skill_text: str, cicd_text: str, ledger: dict,
                              file_text: Callable[[str], str | None] = real_file_text) -> dict:
    """判别力自证：三种坏形态**各自**必须在内存里判红（本仓 §17.3 的口径）。"""
    base = json.loads(json.dumps(ledger))          # 深拷贝：变异发生在内存对象上

    no_boundary = skill_text.replace(BOUNDARY_HEADING, "### 25.6 （标题被删）", 1)

    dropped_id = sorted({e["id"] for e in ledger["entries"]})[0]
    skill_without_one = re.sub(rf"\b{re.escape(dropped_id)}\b", "FM-X0", skill_text)

    unregistered = skill_text.replace(SECTION_HEADING, SECTION_HEADING + "\n\n- `FM-A99` 一条没登记的纪律\n", 1)

    prose_only = json.loads(json.dumps(base))
    prose_only["entries"][0]["kind"] = "prose"

    new_gap = json.loads(json.dumps(base))
    new_gap["ci_findings"].append({
        "id": "FM-E99", "state": "gap", "gap_owner": "x", "gap_shows_when": "y",
    })

    # ── §26（转述面）的坏形态：与 §25 面**对称**的六种 + 一种只属于它的（裸行号）──────
    relay_base = base.get(RELAY_LEDGER_KEY) or []
    relay_first = str(relay_base[0].get("id")) if relay_base else "FM-R1"
    no_relay_section = skill_text.replace(RELAY_SECTION_HEADING, "## 26. （标题被删）", 1)
    relay_without_one = re.sub(rf"\b{re.escape(relay_first)}\b", "FM-R0", skill_text)
    relay_unregistered = skill_text.replace(
        RELAY_SECTION_HEADING, RELAY_SECTION_HEADING + "\n\n- `FM-R99` 一条没登记的纪律\n", 1)
    relay_prose = json.loads(json.dumps(base))
    relay_prose.setdefault(RELAY_LEDGER_KEY, [{}])[0]["kind"] = "prose"
    relay_no_state = json.loads(json.dumps(base))
    relay_no_state.setdefault(RELAY_LEDGER_KEY, [{}])[0]["state"] = "advice"
    relay_new_gap = json.loads(json.dumps(base))
    relay_new_gap.setdefault(RELAY_LEDGER_KEY, []).append({
        "id": "FM-R98", "kind": "action", "state": "gap", "gap_owner": "x",
        "gap_shows_when": "y", "same_family": "FM-A10", "evidence": [],
    })
    relay_line_ref = skill_text.replace(
        RELAY_SECTION_HEADING, RELAY_SECTION_HEADING + f"\n\n见 `{LINE_REF_SPECIMEN}` 的读数\n", 1)
    # 🔴 本条是**红证当场抓出来的**：`same_family` 的记号提取原先用 `[A-ER]`（有意排除别的族），
    # 于是「点了一个**不存在**的记号」（如 `FM-Z9`）**提取不到 ⇒ 判据静默放行** = 空断言。
    # 修法 = 提取放宽到 `[A-Z]`，再逐条核「该记号在技能 / CI-CD 里具名存在」。
    relay_bad_family = json.loads(json.dumps(base))
    relay_bad_family.setdefault(RELAY_LEDGER_KEY, [{}])[0]["same_family"] = "`FM-Z9`"
    # 🔴 判据 16 的**定点**红证（本单新增，针对回灌的四条）：把某条 `kind=action` 的条目从
    #    **判别动作行**里删掉（只删那一行里的它，不碰 §26.2 的表格行）⇒ 必须报
    #    「只靠人执行的条目不写在 §26 边界节」。那一行与那个 id 都**现取**，不写死内容。
    _bnd_line = next(l for l in (section_text(skill_text, RELAY_BOUNDARY_HEADING) or "").split("\n")
                     if l.strip().startswith(ACTION_LINE_PREFIX))
    _last_action_id = sorted(e["id"] for e in relay_base if e.get("kind") == "action")[-1]
    relay_action_line_gap = skill_text.replace(
        _bnd_line, _bnd_line.replace(f"`{_last_action_id}`", ""), 1)
    assert relay_action_line_gap != skill_text, "内存构造的变异体与原文本逐字相同（变异没生效）"

    return {
        "no_boundary": ledger_violations(skill_text=no_boundary, cicd_text=cicd_text,
                                         ledger=base, file_text=file_text),
        "dropped_id": ledger_violations(skill_text=skill_without_one, cicd_text=cicd_text,
                                        ledger=base, file_text=file_text),
        "unregistered": ledger_violations(skill_text=unregistered, cicd_text=cicd_text,
                                          ledger=base, file_text=file_text),
        "prose_only": ledger_violations(skill_text=skill_text, cicd_text=cicd_text,
                                        ledger=prose_only, file_text=file_text),
        "new_gap": ledger_violations(skill_text=skill_text, cicd_text=cicd_text,
                                     ledger=new_gap, file_text=file_text),
        "empty_skill": ledger_violations(skill_text="", cicd_text=cicd_text,
                                         ledger=base, file_text=file_text),
        "control_comment_only": ledger_violations(
            skill_text=skill_text + "\n<!-- 只加一条注释：不改任何记号、不改任何声明 -->\n",
            cicd_text=cicd_text, ledger=base, file_text=file_text),
        "no_relay_section": ledger_violations(skill_text=no_relay_section, cicd_text=cicd_text,
                                              ledger=base, file_text=file_text),
        "relay_dropped_id": ledger_violations(skill_text=relay_without_one, cicd_text=cicd_text,
                                              ledger=base, file_text=file_text),
        "relay_unregistered": ledger_violations(skill_text=relay_unregistered, cicd_text=cicd_text,
                                                ledger=base, file_text=file_text),
        "relay_prose_only": ledger_violations(skill_text=skill_text, cicd_text=cicd_text,
                                              ledger=relay_prose, file_text=file_text),
        "relay_no_state": ledger_violations(skill_text=skill_text, cicd_text=cicd_text,
                                            ledger=relay_no_state, file_text=file_text),
        "relay_new_gap": ledger_violations(skill_text=skill_text, cicd_text=cicd_text,
                                           ledger=relay_new_gap, file_text=file_text),
        "relay_line_ref": ledger_violations(skill_text=relay_line_ref, cicd_text=cicd_text,
                                            ledger=base, file_text=file_text),
        "relay_bad_family": ledger_violations(skill_text=skill_text, cicd_text=cicd_text,
                                              ledger=relay_bad_family, file_text=file_text),
        "relay_action_line_gap": ledger_violations(skill_text=relay_action_line_gap,
                                                   cicd_text=cicd_text, ledger=base,
                                                   file_text=file_text),
    }


# ──────────────────────────────────────────────────────────────────────────────
# 断言层
# ──────────────────────────────────────────────────────────────────────────────

def _require(text: str | None, rel: str) -> str:
    """路径漂移 ⇒ 红（**不得静默跳过**：判据依赖的语料读不到时，「没东西可判」不是通过）。"""
    if text is None:
        raise AssertionError(f"判据依赖的语料不存在：{rel}（路径漂移 ⇒ 红，不得静默跳过）")
    return text


def _live() -> tuple[str, str, dict]:
    skill_text = _require(real_file_text(SKILL_REL), SKILL_REL)
    cicd_text = _require(real_file_text(CICD_REL), CICD_REL)
    ledger = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    return skill_text, cicd_text, ledger


def test_real_files_are_clean() -> None:
    """判据 1~9 在**当前仓库**上全绿；红 = 逐条问题见断言文案。"""
    skill_text, cicd_text, ledger = _live()
    bad = ledger_violations(skill_text=skill_text, cicd_text=cicd_text, ledger=ledger)
    assert bad == [], "研发模式固化台账未通过：\n" + "\n".join(f"  - {p}" for p in bad)


def test_policy_decision_record_is_load_bearing() -> None:
    """判别力自证：删掉 `policy_decisions`（抬上限的决策留痕）⇒ 必红。"""
    skill_text, cicd_text, ledger = _live()
    folded = json.loads(json.dumps(ledger))
    folded.pop("policy_decisions", None)
    bad = ledger_violations(skill_text=skill_text, cicd_text=cicd_text, ledger=folded)
    assert any("policy_decisions" in p for p in bad), bad
    stripped = json.loads(json.dumps(ledger))
    stripped["policy_decisions"][0]["decided_by"] = "  "
    bad2 = ledger_violations(skill_text=skill_text, cicd_text=cicd_text, ledger=stripped)
    assert any("decided_by" in p for p in bad2), bad2


def test_empty_skill_corpus_is_not_silently_green() -> None:
    """判据 10：空语料 ⇒ 非空违规（「没东西可判 ⇒ 绿」是被明确拒绝的形态）。"""
    _, cicd_text, ledger = _live()
    bad = ledger_violations(skill_text="", cicd_text=cicd_text, ledger=ledger)
    assert bad != [], "空技能文本被判绿 ⇒ 判据会静默空跑"


def test_discriminating_power_in_memory() -> None:
    """**判别力自证**：每种坏形态各自判红，且只改注释**不**判红（对照读数）。

    三种坏形态**当场在内存里构造**（不改磁盘）—— 依据 = `docs/wiki/CI-CD.md` 的
    「红证机具的可靠性：改磁盘文件的变异**可能不被读到**」节。
    """
    skill_text, cicd_text, ledger = _live()
    r = check_discriminating_power(skill_text=skill_text, cicd_text=cicd_text, ledger=ledger)

    assert any("覆盖面登记子节" in p for p in r["no_boundary"]), r["no_boundary"]
    assert any("技能节里**没有**写" in p for p in r["dropped_id"]), r["dropped_id"]
    assert any("未登记即红" in p for p in r["unregistered"]), r["unregistered"]
    assert any("只写了劝告" in p for p in r["prose_only"]), r["prose_only"]
    assert any("未守护（gap）条数" in p for p in r["new_gap"]), r["new_gap"]
    assert r["empty_skill"] != [], r["empty_skill"]
    assert r["control_comment_only"] == [], (
        "只加一条注释就判红 ⇒ 判据在误伤（对照读数必须为空）"
    )
    # §26（转述面）的六种坏形态 + 裸行号形态，逐条各自判红
    assert any("整节被删" in p for p in r["no_relay_section"]), r["no_relay_section"]
    assert any("§26 里**没有**写" in p for p in r["relay_dropped_id"]), r["relay_dropped_id"]
    assert any("未登记即红" in p for p in r["relay_unregistered"]), r["relay_unregistered"]
    assert any("只写了劝告" in p for p in r["relay_prose_only"]), r["relay_prose_only"]
    assert any("只写了劝告" in p for p in r["relay_no_state"]), r["relay_no_state"]
    assert any("转述面未守护（gap）条数" in p for p in r["relay_new_gap"]), r["relay_new_gap"]
    assert any("裸行号引用" in p for p in r["relay_line_ref"]), r["relay_line_ref"]
    assert any("same_family" in p for p in r["relay_bad_family"]), r["relay_bad_family"]
    # 判据 16 的**定点**红证：判别动作行里少一条 `kind=action` 的条目 ⇒ 红（本单新增）
    assert any("只靠人执行的条目不写在 §26 边界节" in p for p in r["relay_action_line_gap"]), \
        r["relay_action_line_gap"]


def test_mutation_harness_really_changes_the_text() -> None:
    """证明「变异真的被读到了」（否则上面那条自证也可能是空断言）。"""
    skill_text, cicd_text, ledger = _live()
    deep = json.loads(json.dumps(ledger))
    r = check_discriminating_power(skill_text=skill_text, cicd_text=cicd_text, ledger=deep)
    assert r["control_comment_only"] != r["no_boundary"], "对照读数与注入读数相同 ⇒ 变异没生效"
    mutated_skill = skill_text.replace(BOUNDARY_HEADING, "### 25.6 （标题被删）", 1)
    assert mutated_skill != skill_text, "内存构造的变异体与原文本逐字相同"
    assert BOUNDARY_HEADING not in mutated_skill
    assert deep == ledger, "变异泄漏进了基准台账对象"


def test_boundary_section_names_the_out_of_scope_forms() -> None:
    """边界节必须写清「本清单覆盖不到什么」（不是一句「见上文」）。

    ⚠️ marker 表是**正向**判据（写不出来 ⇒ 红）：本单（`FM-A15`）新登记的三条覆盖边界
    （`required` 集合的**时效性** / 非 required 红的清单只覆盖「**已上报**」的 / 「**不阻塞**」≠「没问题」）
    各带一个 marker ⇒ **删掉那三条登记就红**（判据 14 的常驻面）。
    """
    skill_text, _, _ = _live()
    bnd = _require(section_text(skill_text, BOUNDARY_HEADING), BOUNDARY_HEADING)
    for marker in ("kind=action", "FM-", "evidence", "时效性", "已上报", "不阻塞"):
        assert marker in bnd, f"覆盖面登记缺 `{marker}` 这一面"


# ──────────────────────────────────────────────────────────────────────────────
# 判据 11/12：本单补的两条「反复出错点」判据（清单 E 的 E7 / E8）
# ──────────────────────────────────────────────────────────────────────────────

def case_id_lines(text: str) -> list[str]:
    return re.findall(r"^\s*-\s*id:\s*([A-Z]+-\d+)\s*$", text, re.MULTILINE)


def migration_versions(names: list[str]) -> list[str]:
    return [m.group(1) for n in names if (m := re.match(r"V(\d+)__", n))]


def duplicate_ids(texts: list[str]) -> dict[str, int]:
    seen: dict[str, int] = {}
    for t in texts:
        for cid in case_id_lines(t):
            seen[cid] = seen.get(cid, 0) + 1
    return {k: v for k, v in seen.items() if v > 1}


def test_case_ids_are_unique_across_the_corpus() -> None:
    """判据 11（**抢号即红**）：用例号在 `.github/cases/**` 里全局唯一。

    **治的形态**：两个并行包各自「取现取最大号 + 1」⇒ 双双写成同一个新号；先合的那个无事，
    **后合的**把重号带进 main（本会话实测 7 次：UI-061 / UI-064 / MC-022 / MC-023 / BM-019 …）。
    修法不是「rebase 后再查一次」这句劝告 —— 而是**把唯一性变成判据**：重号一进 PR，
    这条判据在那个 PR 上就红（**红在后合的那一个**，正是它需要改号的那一个）。
    """
    lines = []
    for p in sorted((REPO_ROOT / CASE_CORPUS_DIR).glob("*.yml")):
        lines.append(p.read_text(encoding="utf-8"))
    assert lines, f"{CASE_CORPUS_DIR} 下没有语料 ⇒ 判据会静默空跑（fail-closed）"
    total = sum(len(case_id_lines(t)) for t in lines)
    assert total > 0, "语料里一个用例号都没取到 ⇒ 解析口径失效"
    dups = duplicate_ids(lines)
    assert dups == {}, f"用例号重号（抢号形态）：{dups}"


def test_case_id_duplicate_is_detected_in_memory() -> None:
    """判据 11 的判别力自证：内存里构造两处同号 ⇒ 必被抓到。"""
    a = "cases:\n  - id: MC-001\n  - id: MC-002\n"
    b = "cases:\n  - id: MC-002\n  - id: MC-003\n"
    assert duplicate_ids([a, b]) == {"MC-002": 2}
    assert duplicate_ids([a, "cases:\n  - id: MC-003\n"]) == {}


def test_migration_versions_are_unique_in_the_live_dir() -> None:
    """判据 12（**抢号即红**，射程 = **活的**迁移目录）：版本号在 `db/migration` 里唯一。

    **射程为什么只到 `db/migration`（明确的边界）**：`db/migration-archive/` 里**存量**就有
    版本号重复（实测 `ARCHIVE_DUP_VERSIONS_FROZEN` 个 V 号各两份、文件名不同）——
    它已冻结、不再新增 ⇒ 把唯一性套到归档上会是**存量假红**。抢号只发生在**新写的**那一个目录里。
    与既有判据的分工：`tests/unit_ci_workflows/test_migration_immutability.py` 判的是
    **文件名**在两个载体目录间不重复 + 已登记文件逐字节冻结，**不判版本号**。
    """
    d = REPO_ROOT / LIVE_MIGRATION_DIR
    names = sorted(p.name for p in d.glob("V*.sql"))
    assert names, f"{LIVE_MIGRATION_DIR} 下没有迁移 ⇒ 判据会静默空跑（fail-closed）"
    versions = migration_versions(names)
    counts: dict[str, int] = {}
    for v in versions:
        counts[v] = counts.get(v, 0) + 1
    dups = {k: v for k, v in counts.items() if v > 1}
    assert dups == {}, f"活的迁移目录里版本号重号（抢号形态）：{dups} —— Flyway 会在应用时炸"


def test_archive_duplicate_versions_are_registered_and_only_shrink() -> None:
    """判据 12 的边界台账：归档目录里的重号**只许缩短**（现取 ≤ 冻结值）。"""
    d = REPO_ROOT / "backend/admin-api/src/main/resources/db/migration-archive"
    names = sorted(p.name for p in d.glob("V*.sql"))
    counts: dict[str, int] = {}
    for v in migration_versions(names):
        counts[v] = counts.get(v, 0) + 1
    live_dups = sorted(k for k, v in counts.items() if v > 1)
    assert len(live_dups) <= ARCHIVE_DUP_VERSIONS_FROZEN, (
        f"归档目录重号 V 号 {live_dups} 多于冻结上限 {ARCHIVE_DUP_VERSIONS_FROZEN}"
    )


def registered_anchor_problems(*, ledger: dict,
                              file_text: Callable[[str], str | None] = real_file_text) -> list[str]:
    """每条 `state=registered` 的 `ledger_ref` 必须**可被打断**：删掉锚的**全部**出现 ⇒ 必须判红。

    🔴 **实测教训（本单第一次写错了，红证当场抓住）**：我原先按「锚在该文件里**恰好出现 1 次**」判，
    而真实失效形态是「**只删其中一处** ⇒ 仍解析得到 ⇒ 0 条违规」⇒ 那句「删掉这段 ⇒ 红」是**空断言**。
    ⇒ 语义改成 **删掉锚的全部出现**（这才是「删掉这条登记 ⇒ 红」的正确读法），
    并要求**面内 ≥1 条**（0 条 = 判据空跑，**未跑 ≠ 通过**）。
    """
    bad: list[str] = []
    applicable = 0
    for f in ledger.get("ci_findings", []):
        if f.get("state") != "registered":
            continue
        fid = str(f.get("id", "?"))
        ref = str(f.get("ledger_ref") or "")
        path, _, anchor = ref.partition(ANCHOR_SEP)
        if not path or not anchor:
            bad.append(f"{fid}：state=registered 但 `ledger_ref` 不是 `<path>::<锚>` 形态：{ref!r}")
            continue
        text = file_text(path)
        if text is None:
            bad.append(f"{fid}：`ledger_ref` 的载体不存在：{path}")
            continue
        if anchor not in text:
            bad.append(f"{fid}：`ledger_ref` 的锚在载体里找不到：{ref}")
            continue
        applicable += 1
        stripped = text.replace(anchor, "")
        reader = (lambda rel, _p=path, _s=stripped, _f=file_text: _s if rel == _p else _f(rel))
        viol = ledger_violations(skill_text=reader(SKILL_REL) or "", cicd_text=reader(CICD_REL) or "",
                                 ledger=ledger, file_text=reader)
        if not any(fid in p for p in viol):
            bad.append(
                f"{fid}：删掉锚「{anchor}」的**全部**出现后不判红 ⇒ 这条登记挂在**打不断**的锚上（空断言）"
            )
    if applicable == 0:
        bad.append("面内 0 条 `state=registered` 条目 ⇒ 判据空跑（**未跑 ≠ 通过**，fail-closed）")
    return bad


def test_registered_anchors_are_breakable() -> None:
    """常驻自证：每条 `registered` 的登记锚都**可被打断**（本单实测踩过「删一处不红」）。"""
    _, _, ledger = _live()
    bad = registered_anchor_problems(ledger=ledger)
    assert bad == [], "registered 登记锚不可打断：\n" + "\n".join(f"  - {p}" for p in bad)


def test_registered_anchor_check_has_discriminating_power() -> None:
    """判别力自证（内存构造）：① 面内 0 条 ⇒ 红（防空跑）；② 载体不存在 ⇒ 红；③ 正常 ⇒ 绿。"""
    _, _, ledger = _live()
    assert registered_anchor_problems(ledger=ledger) == []
    empty = json.loads(json.dumps(ledger))
    empty["ci_findings"] = [f for f in empty["ci_findings"] if f.get("state") != "registered"]
    assert registered_anchor_problems(ledger=empty) != []
    broken = json.loads(json.dumps(ledger))
    nxt = next(f for f in broken["ci_findings"] if f.get("state") == "registered")
    nxt["ledger_ref"] = "docs/wiki/NO_SUCH_CARRIER.md::whatever"
    assert registered_anchor_problems(ledger=broken) != []


def boundary_problems(doc_text: str, boundary: str = CASE_ID_ALLOCATION_BOUNDARY) -> list[str]:
    """取号判据的**边界声明**必须写在文件里并带实证锚（删掉声明或删掉实证 ⇒ 红）。"""
    bad: list[str] = []
    if boundary not in doc_text:
        bad.append(f"取号判据的边界声明不在文件里：{boundary!r}")
    for marker in CASE_ID_ALLOCATION_EVIDENCE:
        if marker not in doc_text:
            bad.append(f"边界声明缺少撞号实证锚 `{marker}`（实证不许匿名）")
    return bad


def test_case_id_allocation_boundary_is_registered() -> None:
    """判据 11/12 的**覆盖面登记**：只看已合并状态 ⇒ 拦不住「main + 在飞分支」的撞号。

    没有这一条，那两条唯一性判据会给人一个它**并不具备**的保护感
    （「既不加强也不登记」正是本单要治的形态）。
    """
    bad = boundary_problems(__doc__ or "")
    assert bad == [], "取号判据的边界未登记：\n" + "\n".join(f"  - {p}" for p in bad)


def test_boundary_registration_has_discriminating_power() -> None:
    """边界登记的判别力自证（内存构造，不改磁盘）。"""
    doc = __doc__ or ""
    assert boundary_problems(doc) == []
    assert boundary_problems(doc.replace(CASE_ID_ALLOCATION_BOUNDARY, "（声明被删）")) != []
    assert boundary_problems(doc.replace("MC-027", "MC-0XX")) != []


def test_migration_duplicate_is_detected_in_memory() -> None:
    """判据 12 的判别力自证：内存里构造同号两个文件 ⇒ 必被抓到。"""
    assert migration_versions(["V133__a.sql", "V133__b.sql"]) == ["133", "133"]
    counts: dict[str, int] = {}
    for v in migration_versions(["V133__a.sql", "V133__b.sql", "V134__c.sql"]):
        counts[v] = counts.get(v, 0) + 1
    assert {k: v for k, v in counts.items() if v > 1} == {"133": 2}
    assert migration_versions(["V132__x.sql"]) == ["132"]


# ──────────────────────────────────────────────────────────────────────────────
# 判据 13（`FM-E14`）：`node --test <目录>` 的**假红**必须被拦住（散文不算落点）
# ──────────────────────────────────────────────────────────────────────────────

def node_test_targets(text: str) -> list[str]:
    """取出每处 `node --test` 的**目标参数**（跳过 `-` 开头的选项，取第一个位置参数）。

    **两处收紧**（都是「读数与它声称的对象不是同一个」的形态，`FM-A1`/`FM-A11` 同族）：
    ① 先剥 `#` 注释 —— 注释里的**提及**不是调用；
    ② 目标参数必须**像路径**（含 `/` 或 `.`）—— job 名里的 `(node --test)` 取其位置参数会得到 `)`。
    ⚠️ **登记边界**：因此 `node --test <裸目录名>`（既无 `/` 也无 `.`，如 `tests`）**不判**
    （假绿方向：它不会误伤散文，代价是漏掉这一种更窄的写法；本仓两处载体的写法都是仓库相对路径）。
    """
    out: list[str] = []
    for m in NODE_TEST_INVOCATION_RE.finditer(strip_hash_comments(text)):
        for tok in m.group(1).split():
            if tok.startswith("-"):
                continue
            tok = tok.strip("\"'")
            if NODE_TEST_PATHLIKE_RE.search(tok):
                out.append(tok)
            break
    return out


def node_test_glob_problems(
    text: str, *, allowlist: tuple[str, ...] = NODE_TEST_TARGET_ALLOWLIST_FROZEN
) -> list[str]:
    """`node --test` 的目标参数不含 glob（且不在只许缩短的载体台账里）⇒ 违规。

    **治的形态**（实测，不是推断）：`node --test <目录>` 会被 Node 内置 runner 读成 **1 条失败**
    —— 它长得像「测试挂了」，其实一条用例都没跑（假红）。⇒ 目标参数必须是**测试文件集**
    （glob，如 `<目录>/*.test.mjs`），或登记在 `NODE_TEST_TARGET_ALLOWLIST_FROZEN` 里。
    """
    bad: list[str] = []
    for tok in node_test_targets(text):
        if "*" in tok or tok in allowlist:
            continue
        bad.append(
            f"`node --test {tok}`：目标参数不是 glob ⇒ 传**目录**会被 Node 内置 runner 读成 "
            f"**1 条失败的假红**（`FM-E14`）—— 改回 `<目录>/*.test.mjs`，或在只许缩短的载体台账里登记"
        )
    return bad


def test_node_test_targets_are_globs_in_the_registered_carriers() -> None:
    """判据 13 常驻：两处载体里的 `node --test` 目标参数都是 glob（`FM-E14`）。

    **反空跑**：每条载体至少取到 1 个目标参数 —— 取不到 ⇒ 解析口径失效 ⇒ 红
    （「没东西可判」不许长得像「通过」）。
    """
    for rel in NODE_TEST_GLOB_CARRIERS_FROZEN:
        text = _require(real_file_text(rel), rel)
        assert node_test_targets(text), (
            f"{rel} 里一个 `node --test` 目标参数都没取到 ⇒ 判据空跑（解析口径失效或该腿被删）"
        )
        bad = node_test_glob_problems(text)
        assert bad == [], f"{rel}：\n" + "\n".join(f"  - {p}" for p in bad)


def test_node_test_glob_guard_has_discriminating_power() -> None:
    """判据 13 的判别力自证（**内存构造**，不改磁盘）+ 两条对照读数。"""
    good = "run: node --test frontend/worker-h5/tests/*.test.mjs\n"
    directory_form = "run: node --test frontend/worker-h5/tests\n"
    assert node_test_glob_problems(good) == [], "glob 形态被误判 ⇒ 判据在误伤"
    assert node_test_glob_problems(directory_form) != [], "目录形态不判红 ⇒ 判据是空断言"
    # 对照读数①：只加一条注释 ⇒ **不红**（判据判的是调用形态，不是「文件变了没有」）
    assert node_test_glob_problems(good + "# 只加一条注释：不改任何调用\n") == []
    # 对照读数②：就绪探针的 `/dev/null` 在**只许缩短**的载体台账里 ⇒ 不判；
    # 台账之外的**新**目录形态仍判红（射程没有被放宽成「凡不是 glob 都不判」）。
    assert node_test_glob_problems("node --test --test-reporter=dot --test-only /dev/null\n") == []
    assert node_test_glob_problems("node --test frontend/other/tests\n") != []
    # 对照读数③（**prose 豁免**）：注释里的提及、以及 job 名里的 `(node --test)` ⇒ 不判
    # —— 否则本判据会被**它自己的说明文字**喂红（`FM-A11` 的形态：举例即实例）。
    assert node_test_glob_problems("    # 删掉 `node --test` 那一行 ⇒ 必红\n") == []
    assert node_test_glob_problems("    name: worker-h5 unit tests (node --test)\n") == []


# ──────────────────────────────────────────────────────────────────────────────
# 判据 14~18（§26 = 转述 / 派单面）：常驻自证 + 判别力自证 + 边界登记
# ──────────────────────────────────────────────────────────────────────────────

def relay_anchor_problems(*, ledger: dict,
                          file_text: Callable[[str], str | None] = real_file_text) -> list[str]:
    """每条 `state=guarded` / `registered` 的 relay 条目：锚**删掉全部出现** ⇒ 必须判红。

    语义与 `registered_anchor_problems`（`ci_findings` 面）**逐条同口径** —— 那里的实测教训是
    「按『锚恰好出现 1 次』判」是**空断言**（只删其中一处仍解析得到）；真实失效形态是
    「删掉这条登记所指对象的**全部**出现」。**面内 0 条 ⇒ 红**（未跑 ≠ 通过，fail-closed）。
    """
    bad: list[str] = []
    applicable = 0
    for e in ledger.get(RELAY_LEDGER_KEY) or []:
        state = e.get("state")
        if state not in {"guarded", "registered"}:
            continue
        fid = str(e.get("id", "?"))
        refs = list(e.get("criteria") or []) if state == "guarded" else [e.get("ledger_ref")]
        for ref in refs:
            path, _, anchor = str(ref or "").partition(ANCHOR_SEP)
            if not path or not anchor:
                bad.append(f"{fid}：锚不是 `<path>::<锚>` 形态：{ref!r}")
                continue
            text = file_text(path)
            if text is None:
                bad.append(f"{fid}：锚的载体不存在：{path}")
                continue
            if anchor not in text:
                bad.append(f"{fid}：锚在载体里找不到：{ref}")
                continue
            applicable += 1
            stripped = text.replace(anchor, "")
            reader = (lambda rel, _p=path, _s=stripped, _f=file_text: _s if rel == _p else _f(rel))
            viol = ledger_violations(skill_text=reader(SKILL_REL) or "",
                                     cicd_text=reader(CICD_REL) or "",
                                     ledger=ledger, file_text=reader)
            if not any(fid in p for p in viol):
                bad.append(
                    f"{fid}：删掉锚「{anchor}」的**全部**出现后不判红 ⇒ "
                    f"这条登记挂在**打不断**的锚上（空断言）"
                )
    if applicable == 0:
        bad.append("§26 面内 0 条 `state=guarded` / `registered` 条目 ⇒ 判据空跑（**未跑 ≠ 通过**）")
    return bad


def test_relay_anchors_are_breakable() -> None:
    """常驻自证：§26 面每条 `guarded` / `registered` 的锚都**可被打断**（同 `FM-A7` 的口径）。"""
    _, _, ledger = _live()
    bad = relay_anchor_problems(ledger=ledger)
    assert bad == [], "§26 面的登记锚不可打断：\n" + "\n".join(f"  - {p}" for p in bad)


def test_relay_anchor_check_has_discriminating_power() -> None:
    """判别力自证（内存构造）：① 面内 0 条 ⇒ 红（防空跑）；② 载体不存在 ⇒ 红；③ 正常 ⇒ 绿。"""
    _, _, ledger = _live()
    assert relay_anchor_problems(ledger=ledger) == []
    empty = json.loads(json.dumps(ledger))
    empty[RELAY_LEDGER_KEY] = [e for e in empty.get(RELAY_LEDGER_KEY, [])
                               if e.get("state") not in {"guarded", "registered"}]
    assert relay_anchor_problems(ledger=empty) != []
    broken = json.loads(json.dumps(ledger))
    nxt = next(e for e in broken[RELAY_LEDGER_KEY] if e.get("state") == "guarded")
    nxt["criteria"] = ["tests/unit_ci_workflows/NO_SUCH_GUARD.py::whatever"]
    assert relay_anchor_problems(ledger=broken) != []


def relay_boundary_missing_markers(skill_text: str) -> list[str]:
    """§26.4 覆盖面登记缺哪几个面（空列表 = 该点名的都点名了）。**纯函数**，红证可内存构造。"""
    rbnd = section_text(skill_text, RELAY_BOUNDARY_HEADING)
    if rbnd is None:
        return ["§26.4 覆盖面登记子节被删（边界不存在 ⇒ 红）"]
    return [m for m in RELAY_BOUNDARY_MARKERS if m not in rbnd]


def test_relay_boundary_section_names_the_out_of_scope_forms() -> None:
    """§26 的边界节必须写清「本节覆盖不到什么」（不是一句「见 §25」）。"""
    skill_text, _, _ = _live()
    _require(section_text(skill_text, RELAY_BOUNDARY_HEADING), RELAY_BOUNDARY_HEADING)
    missing = relay_boundary_missing_markers(skill_text)
    assert missing == [], f"§26 覆盖面登记缺这些面：{missing}"


def test_relay_line_ref_guard_has_discriminating_power() -> None:
    """判据 18 的判别力自证（**内存构造**）：裸行号 ⇒ 红；符号锚 / 只加注释 ⇒ 不红。"""
    skill_text, cicd_text, ledger = _live()
    injected = skill_text.replace(
        RELAY_SECTION_HEADING, RELAY_SECTION_HEADING + f"\n\n见 `{LINE_REF_SPECIMEN}` 的读数\n", 1)
    assert injected != skill_text, "内存构造的变异体与原文本逐字相同"
    bad = ledger_violations(skill_text=injected, cicd_text=cicd_text, ledger=ledger)
    assert any("裸行号引用" in p for p in bad), bad
    # 对照读数①：符号锚形态（`<path>::<符号>`）**不**被判据当行号 ⇒ 判的是「有没有行号」而不是「提没提文件」
    anchored = skill_text.replace(
        RELAY_SECTION_HEADING,
        RELAY_SECTION_HEADING + "\n\n见 `.github/render_cases.py::load_case_dicts` 的读数\n", 1)
    assert ledger_violations(skill_text=anchored, cicd_text=cicd_text, ledger=ledger) == []
    # 对照读数②：只加一条注释（无行号形态）⇒ 不红
    assert ledger_violations(
        skill_text=skill_text + "\n<!-- 只加一条注释：不改任何记号、不改任何声明 -->\n",
        cicd_text=cicd_text, ledger=ledger) == []


# ──────────────────────────────────────────────────────────────────────────────
# 判据 19：§19 **活索引行**的读数 ≡ 台账现取（治「索引自己腐烂」）
#
# 病灶（本单实测，具名登记在台账 `NS-4` 的 ①）：§19 是**活索引**（指向各节与承载体），
# 而它**自己腐烂了** —— 第 19 行与台账脱钩：范围端点停在旧号、`kind=action` 的条数停在 4，
# 而**没有任何判据管它** ⇒ 腐烂是静默的（§19 的「现状」列因此开始说谎）。
#
# 治法 = **新鲜度判据**（口径同 `scripts/generated_artifacts_freshness.py`：真值源只有一个）：
# 这一行里每一处**结构化**读数都要与现取逐值相等；**未登记的读数形态 ⇒ 红**（只许缩短）。
# 🔴 为什么**不**做成「从台账渲染进技能」的落盘生成器：技能面是**活锚**
# （`scripts/preset-anchor-check.sh` 逐字节比对仓库 ⇄ `$HOME/.dsh`），而「渲染进技能」会给
# **每一个改技能的包**新增一道必跑的渲染步骤 —— §19 正是**多包共写的活文档**（§17.2 写面冲突 /
# §23.9 C1「重复动作收敛」）。判据治的是**同一件事**（读数与现取脱钩）而**不引入这道写面**：
# 腐烂**写得出、活不下来**（这就是本单选择的上限，如实登记，不宣称「结构上不可能腐烂」）。
# ──────────────────────────────────────────────────────────────────────────────

INDEX_SECTION_HEADING = "## 19. 范式总纲与 enforcement 锚点"
#: 判据 19 的**覆盖面登记**子节（**正向**：边界写不出来 ⇒ 红；见 `INDEX_BOUNDARY_MARKERS`）。
INDEX_BOUNDARY_HEADING = "### 19.3 活索引读数（判据 19）：覆盖面登记"
INDEX_BOUNDARY_MARKERS = ("只覆盖本表第 19 行", "结构化", "自然语言计数", "INDEX_CLAIMS",
                          "活锚", "写得出", "活不下来")
#: §19 索引表里**第 19 行**（= 「固化必须有承载体」那一行，本台账在技能面的索引行）的前缀。
INDEX_ROW_PREFIX = "| 19 |"
#: 范围写法（与 `test_casebook_ledger_claims.py` 的 `RANGE_RE` **同形**：记号与 `~` 之间允许反引号 / 空白）。
INDEX_RANGE_RE = re.compile(r"\bFM-([A-Z])(\d+)\b[`\s]*[~～][`\s]*FM-([A-Z])(\d+)\b")
#: **结构化**的两种计数形态：键绑定（`` `kind=action` 的 9 条 ``）与列表计数（`现取 16 条`）。
#: ⚠️ 自然语言计数（「十几条」这类）刻意**不在面内** —— 与叙述句在文本层不可区分（同 `CLAIMS` 的边界口径）。
#: `[^\n|]` 同时保证不跨 markdown 表格的单元格（这一行是一行一行的表格行）。
INDEX_KEY_COUNT_RE = re.compile(r"`(kind|state)=([A-Za-z_]+)`[^\n|]{0,40}?([0-9]+)\s*条")
INDEX_LIST_COUNT_RE = re.compile(r"现取\s*\*{0,2}([0-9]+)\*{0,2}\s*条")
#: 记号族 → 台账表（`entries` 一个表覆盖 A~D 四个族）。
FAMILY_TABLE = {"A": "entries", "B": "entries", "C": "entries", "D": "entries",
                "E": "ci_findings", "R": "relay_entries"}
#: **策展表**（口径同 `test_agent_permission_parity.py` 判据 13 的 `COMMENT_CLAIMS` /
#: `test_casebook_ledger_claims.py` 的 `CLAIMS`）：索引行里**每一处计数读数**都要在这里登记
#: 「锚 + 取哪张表 + 口径」。**未登记即红**（新增一处陈旧读数逃不掉）。
#: 每项 = (正则，**恰好一个捕获组** = 文本里写的那个数 · 台账表 · 字段 · 值 · 口径说明)。
INDEX_CLAIMS = (
    (r"现取\s*\*{0,2}([0-9]+)\*{0,2}\s*条", "ci_findings", "", "",
     "清单 E 的**条数** —— `ci_findings` 的现取条数（⚠️ **不是**范围端点的号：该族有缺号 ⇒ 两者必然不等）"),
    (r"`kind=action`[^\n|]{0,40}?([0-9]+)\s*条", "entries", "kind", "action",
     "`entries` 里 `kind=action`（只靠人执行）的现取条数 —— 与 §25.6 判别动作行是同一个集合"),
)


def index_row(skill_text: str) -> str | None:
    """§19 索引表里第 19 行的原文；取不到 ⇒ None（交给判据判红，**不静默跳过**）。"""
    sec = section_text(skill_text, INDEX_SECTION_HEADING)
    if sec is None:
        return None
    for line in sec.split("\n"):
        if line.strip().startswith(INDEX_ROW_PREFIX):
            return line
    return None


def family_numbers(ledger: dict, fam: str) -> list[int]:
    """某记号族在台账里的序号（**现取**，升序）。该族可以**有缺号**（如 `E` 族的 6）。"""
    table = FAMILY_TABLE.get(fam)
    out: list[int] = []
    for e in (ledger.get(table) or []) if table else []:
        m = re.fullmatch(rf"FM-{re.escape(fam)}(\d+)", str(e.get("id", "")))
        if m:
            out.append(int(m.group(1)))
    return sorted(out)


def _ledger_count(ledger: dict, table: str, field: str = "", value: str = "") -> int:
    rows = ledger.get(table) or []
    if not field:
        return len(rows)
    return sum(1 for e in rows if e.get(field) == value)


def live_index_reading_problems(*, skill_text: str, ledger: dict) -> list[str]:
    """判据 19：§19 活索引行的每一处台账读数 ≡ 台账现取。空列表 = 全绿。**纯函数**。"""
    row = index_row(skill_text)
    if row is None:
        return ["§19 索引表里找不到第 19 行（`| 19 |` 开头）⇒ 活索引的读数无从判定"
                "（fail-closed：**未跑 ≠ 通过**，删行 / 改前缀都红）"]
    bad: list[str] = []

    # ── ① 范围端点 == 该族 id 的现取 min / max（**端点不是条数**）────────────────
    spans = INDEX_RANGE_RE.findall(row)
    if not spans:
        bad.append("§19 索引行里没有 `FM-<族><i>`~`FM-<族><j>` 形态的范围读数 ⇒ 判据无从判定"
                   "（形态被改掉 ⇒ 红，不许静默空跑）")
    for fam_a, lo, fam_b, hi in spans:
        if fam_a != fam_b:
            bad.append(f"§19 索引行的范围两端不是同一族：`FM-{fam_a}{lo}`~`FM-{fam_b}{hi}`")
            continue
        nums = family_numbers(ledger, fam_a)
        if not nums:
            bad.append(f"§19 索引行写了 `FM-{fam_a}` 族的范围，而台账里该族 **0 条** ⇒ 指向了不存在的表")
            continue
        if int(lo) != nums[0] or int(hi) != nums[-1]:
            bad.append(
                f"§19 索引行范围端点陈旧：写 `FM-{fam_a}{lo}`~`FM-{fam_a}{hi}`，"
                f"现取 = `FM-{fam_a}{nums[0]}`~`FM-{fam_a}{nums[-1]}`"
                f"（端点 = 该族 id 的现取 min/max，**不是条数**；该族条数 = {len(nums)}）"
            )

    # ── ② 已登记的读数 == 现取；**未登记即红**（只许缩短）────────────────────────
    covered: list[tuple[int, int]] = []
    for pattern, table, field, value, why in INDEX_CLAIMS:
        found = list(re.finditer(pattern, row))
        if not found:
            bad.append(f"§19 索引行里取不到已登记的读数 `{pattern}`（{why}）⇒ 判据空跑（未跑 ≠ 通过）")
            continue
        want = _ledger_count(ledger, table, field, value)
        for m in found:
            covered.append((m.start(), m.end()))
            got = int(m.group(1))
            if got != want:
                bad.append(f"§19 索引行的读数陈旧：写 **{got} 条**，现取 **{want} 条**"
                           f"（{why}；改台账而不改这行 ⇒ 红，改这行写旧数 ⇒ 红）")
    for rx, label in ((INDEX_KEY_COUNT_RE, "键绑定计数（`` `kind=` / `state=` `` 形态）"),
                      (INDEX_LIST_COUNT_RE, "`现取 N 条` 计数")):
        for m in rx.finditer(row):
            if not any(a <= m.start() and m.end() <= b for a, b in covered):
                bad.append(f"§19 索引行里有一处**未登记**的{label}：`{m.group(0).strip()}` ⇒ "
                           f"未登记即红（登记进 `INDEX_CLAIMS`，或别在这一行写这个数）")
    return bad


def test_live_index_readings_equal_the_ledger() -> None:
    """判据 19（常驻）：§19 活索引行的读数 ≡ 台账现取（端点 / 条数 / `kind=action` 条数）。"""
    skill_text, _, ledger = _live()
    bad = live_index_reading_problems(skill_text=skill_text, ledger=ledger)
    assert bad == [], "§19 活索引行与台账脱钩：\n" + "\n".join(f"  - {p}" for p in bad)


def index_boundary_missing_markers(skill_text: str) -> list[str]:
    """§19.3 覆盖面登记缺哪几个面（空列表 = 该点名的都点名了）。**纯函数**，红证可内存构造。"""
    sec = section_text(skill_text, INDEX_BOUNDARY_HEADING)
    if sec is None:
        return ["§19.3 覆盖面登记子节被删（判据 19 的边界不存在 ⇒ 红）"]
    return [m for m in INDEX_BOUNDARY_MARKERS if m not in sec]


def test_live_index_boundary_section_names_the_out_of_scope_forms() -> None:
    """判据 19 的**覆盖面登记**必须存在且点名（**正向**：删掉边界 / 删掉任一面 ⇒ 红）。"""
    skill_text, _, _ = _live()
    _require(section_text(skill_text, INDEX_BOUNDARY_HEADING), INDEX_BOUNDARY_HEADING)
    missing = index_boundary_missing_markers(skill_text)
    assert missing == [], f"§19.3 覆盖面登记缺这些面：{missing}"


def test_live_index_reading_guard_has_discriminating_power() -> None:
    """判据 19 的判别力自证（**内存构造**，不改磁盘）：四种坏形态各自判红 + 对照读数。"""
    skill_text, _, ledger = _live()
    row = index_row(skill_text)
    if row is None:
        raise AssertionError("定位 §19 第 19 行失败（fail-closed）")
    assert live_index_reading_problems(skill_text=skill_text, ledger=ledger) == []

    nums = family_numbers(ledger, "E")
    # ① **端点**退回旧值（本单实际修的那处：端点的号 ≠ 条数）
    stale = skill_text.replace(f"FM-E{nums[-1]}", f"FM-E{nums[-1] - 3}", 1)
    assert stale != skill_text, "内存构造的变异体与原文本逐字相同（变异没生效）"
    got = live_index_reading_problems(skill_text=stale, ledger=ledger)
    assert any("范围端点陈旧" in p for p in got), got

    # ② 把**条数**写成**端点的号**（`FM-E6` 缺号 ⇒ 两者不是同一个对象 ⇒ 必须红）
    list_hit = INDEX_LIST_COUNT_RE.search(row)
    if list_hit is None:
        raise AssertionError("§19 索引行里没有 `现取 N 条` 形态的读数（fail-closed）")
    conflated = skill_text.replace(list_hit.group(0), f"现取 {nums[-1]} 条", 1)
    assert conflated != skill_text
    got = live_index_reading_problems(skill_text=conflated, ledger=ledger)
    assert any("读数陈旧" in p for p in got), got

    # ③ **只靠人执行**那批的条数陈旧（本单实际修的第二处）
    key_hit = re.search(INDEX_CLAIMS[1][0], row)
    if key_hit is None:
        raise AssertionError("§19 索引行里没有 `kind=action` 的条数读数（fail-closed）")
    stale_key = skill_text.replace(
        key_hit.group(0), key_hit.group(0).replace(key_hit.group(1), "4", 1), 1)
    assert stale_key != skill_text
    got = live_index_reading_problems(skill_text=stale_key, ledger=ledger)
    assert any("只靠人执行" in p for p in got), got

    # ④ 行被删 ⇒ fail-closed 红；⑤ **未登记**的读数形态 ⇒ 红（只许缩短）
    assert live_index_reading_problems(
        skill_text=skill_text.replace(INDEX_ROW_PREFIX, "| 19x |", 1), ledger=ledger) != []
    unregistered = skill_text.replace(
        row, row + "`state=gap` 3 条", 1)
    assert unregistered != skill_text
    got = live_index_reading_problems(skill_text=unregistered, ledger=ledger)
    assert any("未登记" in p for p in got), got

    # ⑥ 对照读数：**只加一条注释**（不动任何读数）⇒ 不红
    assert live_index_reading_problems(
        skill_text=skill_text + "\n<!-- 只加一条注释：不改任何读数、不改任何登记 -->\n",
        ledger=ledger) == []


# ──────────────────────────────────────────────────────────────────────────────
# 判据 20：技能里**教的**建 worktree 命令必须落在**收尾半径**内（`FM-R8`）
#
# 病灶（本单实测）：`scripts/issue-lifecycle.sh reap-merged` **存在**、也真在跑，
# 而本会话**每一个** worktree 都被判「不在工作区根（`WT_BASE`）下 ⇒ 自动收尾半径外」——
# 派单模板让包用「裸 `worktree add` + 裸相对名」（CWD = 仓库）⇒ 检出落在**仓库里面**。
# ⇒ **工具存在 ≠ 产物可达**：收不掉不是工具坏了，是**产物不在它的半径里**。
#
# 治法 = 把**半径口径**做成对**模板**的机械判据（半径真值源 = `scripts/dev-worktree.sh` 的
# `WT_BASE` 与 `scripts/issue_lifecycle.py` 的 `wt_base_dir`，两处都认 `MIGAO_WT_BASE`）。
# ──────────────────────────────────────────────────────────────────────────────

#: 一处 `worktree add` 调用：到行尾 / 反引号 / `;` / `&` / `|` 为止（选项与位置参数都在这一段里）。
WORKTREE_ADD_RE = re.compile(r"git\s+worktree\s+add\s+([^\n`;&|]*)")
#: 会**吃掉一个参数**的选项（`-b <branch>` / `-B <branch>`）—— 剥掉它们才能取到位置参数（路径）。
WORKTREE_FLAG_TAKES_VALUE = frozenset({"-b", "-B", "--reason"})
#: **半径内**的形态：`../migao-wt/<slug>`（默认根的尾段）、或显式 `MIGAO_WT_BASE` / `WT_BASE`。
#: 口径与 `scripts/dev-worktree.sh` 的 `WT_BASE="${MIGAO_WT_BASE:-$REPO_ROOT/../migao-wt}"` 一致。
WORKTREE_RADIUS_SAFE_RE = re.compile(r"migao-wt/|MIGAO_WT_BASE|WT_BASE")


def worktree_add_paths(text: str) -> list[str]:
    """技能里每一条**带路径参数**的 worktree 调用 ⇒ 它的路径参数（第一个位置参数）。

    `--detach` **纯检出豁免**：只读、用完即删，不产生需要收尾的分支产物
    （它的纪律是**坐标**（避开共享临时根），由 `FM-A13` 承担 —— 见 §26.4 的登记）。
    """
    out: list[str] = []
    for m in WORKTREE_ADD_RE.finditer(text or ""):
        tokens = m.group(1).split()
        if "--detach" in tokens:
            continue
        positional: list[str] = []
        skip = False
        for t in tokens:
            if skip:
                skip = False
                continue
            if t in WORKTREE_FLAG_TAKES_VALUE:
                skip = True
                continue
            if t.startswith("-"):
                continue
            positional.append(t)
        if positional:
            out.append(positional[0])
    return out


def worktree_radius_problems(*, skill_text: str) -> list[str]:
    """判据 20：技能里教的建 worktree 命令的路径必须在**收尾半径**内。空列表 = 全绿。**纯函数**。"""
    paths = worktree_add_paths(skill_text)
    if not paths:
        return ["技能里**没有任何**带路径参数的建 worktree 命令 ⇒ 判据空跑（未跑 ≠ 通过）："
                "本条要求技能把**半径安全**的形态写出来（删光 = 没有模板可抄，同 `FM-R8` 的病灶）"]
    bad: list[str] = []
    for p in paths:
        if not WORKTREE_RADIUS_SAFE_RE.search(p):
            bad.append(f"技能里教的 worktree 路径 `{p}` 不在**收尾半径**内 ⇒ 产物收不掉（`FM-R8`）："
                       f"从仓库根调用并把路径放在 `../migao-wt/<slug>`（或显式 `MIGAO_WT_BASE=<根>`）下，"
                       f"否则 `scripts/issue-lifecycle.sh reap-merged` 一律判「半径外」")
    return bad


def test_worktree_templates_stay_inside_the_reap_radius() -> None:
    """判据 20（常驻）：技能里教的建 worktree 命令，路径必须在**收尾半径**内（`FM-R8`）。"""
    skill_text, _, _ = _live()
    bad = worktree_radius_problems(skill_text=skill_text)
    assert bad == [], "技能里教的 worktree 形态会让产物落在收尾半径外：\n" + \
        "\n".join(f"  - {p}" for p in bad)


def test_worktree_radius_guard_has_discriminating_power() -> None:
    """判据 20 的判别力自证（**内存构造**）：裸相对名 ⇒ 红；正例 / `--detach` / 注释 ⇒ 不红。"""
    skill_text, _, _ = _live()
    assert worktree_radius_problems(skill_text=skill_text) == []

    # ① **裸相对名**（CWD = 仓库 ⇒ 落在仓库里面）⇒ 红。标本**拼接构造**，避免扫描器把
    #    本文件的举例读成实例（`FM-A11`：举例即实例）。
    bare = "git worktree add -b " + "<br>" + " " + "bare-slug"
    assert bare not in skill_text, "标本串已经在技能里 ⇒ 该形态本来就在半径外"
    injected = skill_text.replace(RELAY_SECTION_HEADING, RELAY_SECTION_HEADING + "\n\n" + bare + "\n", 1)
    assert injected != skill_text, "内存构造的变异体与原文本逐字相同（变异没生效）"
    got = worktree_radius_problems(skill_text=injected)
    assert any("不在**收尾半径**内" in p for p in got), got

    # ② 对照读数①：`--detach` **纯检出**（同为裸相对名）⇒ **不**判 —— 判的是「建分支的产物」
    detached = skill_text.replace(
        RELAY_SECTION_HEADING,
        RELAY_SECTION_HEADING + "\n\n" + "git worktree add --detach " + "pure-checkout" + " origin/main\n", 1)
    assert worktree_radius_problems(skill_text=detached) == []

    # ③ 对照读数②：把正例删光 ⇒ fail-closed 红（「没有模板可抄」也是坏形态：同 `FM-R8` 的病灶）
    assert worktree_radius_problems(skill_text="\n## 26. 转述与派单的纪律\n\n（没有命令示例）\n") != []

    # ④ 对照读数③：**只加一条注释** ⇒ 不红
    assert worktree_radius_problems(
        skill_text=skill_text + "\n<!-- 只加一条注释：不改任何命令示例 -->\n") == []

    # ⑤ 覆盖面登记被判据**钉住**：删掉§26.4 里点名「收尾半径 / reap-merged / 派单消息」的那一面 ⇒ 红
    assert relay_boundary_missing_markers(skill_text) == []
    stripped_markers = skill_text.replace("收尾半径", "半径")
    assert stripped_markers != skill_text
    assert relay_boundary_missing_markers(skill_text=stripped_markers) != []
    no_boundary = skill_text.replace(RELAY_BOUNDARY_HEADING, "### 26.4 （标题被删）", 1)
    assert relay_boundary_missing_markers(skill_text=no_boundary) != []


# ──────────────────────────────────────────────────────────────────────────────
# 判据 21：两份清单标题的**条数** ≡ 台账现取（治「标题里的条数自己腐烂」）
#
# 病灶（本单**现取**到的实况）：§26.2 的标题写着「七条」，而台账 `relay_entries` 现取 **8** 条
#   —— 与判据 19 治的「§19 索引行腐烂」**同族**，只是对象从「索引行」换成了「清单标题」；
#   差别在于：**此前没有任何判据管它**（判据 19 只读 §19 那一张表格的第 19 行）。
# 治法同判据 19 的口径：**结构化**读数（标题里的 `（N 条）`）必须等于台账现取；取不到 / 标题被删 ⇒ 红
#   （fail-closed：**未跑 ≠ 通过**）。口径走**策展表**而不是放宽正则 —— 自然语言计数（「十几条」这类
#   叙述句）刻意**不在面内**（同 `CLAIMS` / `COMMENT_CLAIMS` 的边界口径）。
# ──────────────────────────────────────────────────────────────────────────────

#: 清单标题里的**结构化**条数读数：``（13 条；…）`` / ``（11 条）``。
LIST_COUNT_RE = re.compile(r"（\s*([0-9]+)\s*条")
#: 策展表：每项 = (标题前缀, **族字母**（`family_numbers` 的族）, 口径说明)。
#: ⚠️ §25.2 那个数说的是 **A 族**的条数，**不是** `entries` 全部（两回事：`entries` 覆盖 A~D）。
#: 标题前缀**逐字**出现在技能里；删标题 / 改前缀 ⇒ 红。
LIST_COUNT_CLAIMS = (
    ("### 25.2 清单 A", "A",
     "§25.2 清单 A 的条数 —— `entries` 里 **A 族**的现取条数（不是 `entries` 全部：它覆盖 A~D）"),
    ("### 26.2 清单 R", "R",
     "§26.2 清单 R 的条数 —— 台账 `relay_entries` 的现取条数"),
)


def list_count_problems(*, skill_text: str, ledger: dict) -> list[str]:
    """判据 21：每份清单标题里的条数 ≡ 台账现取。空列表 = 全绿。**纯函数**，红证可内存构造。"""
    bad: list[str] = []
    for heading, fam, why in LIST_COUNT_CLAIMS:
        lines = [l for l in (skill_text or "").split("\n") if l.strip().startswith(heading)]
        if not lines:
            bad.append(f"技能里找不到清单标题 `{heading}`（{why}）⇒ 判据无从判定"
                       f"（fail-closed：删标题 / 改前缀都红，**未跑 ≠ 通过**）")
            continue
        m = LIST_COUNT_RE.search(lines[0])
        if m is None:
            bad.append(f"清单标题 `{heading}` 里取不到 `（N 条）` 形态的条数读数（{why}）⇒ "
                       f"判据空跑（形态被改掉 ⇒ 红，不许静默放行）")
            continue
        got, want = int(m.group(1)), len(family_numbers(ledger, fam))
        if got != want:
            bad.append(f"清单标题的条数陈旧：`{heading}` 写 **{got} 条**，现取 **{want} 条**"
                       f"（{why}；改台账而不改标题 ⇒ 红，改标题写旧数 ⇒ 红）")
    return bad


def test_list_heading_counts_equal_the_ledger() -> None:
    """判据 21（常驻）：§25.2 / §26.2 两份清单标题的条数 ≡ 台账现取。"""
    skill_text, _, ledger = _live()
    bad = list_count_problems(skill_text=skill_text, ledger=ledger)
    assert bad == [], "清单标题的条数与台账脱钩：\n" + "\n".join(f"  - {p}" for p in bad)


def test_list_count_guard_has_discriminating_power() -> None:
    """判据 21 的判别力自证（**内存构造**，不改磁盘）：陈旧条数 / 删标题 / 删读数各自判红 + 对照读数。"""
    skill_text, _, ledger = _live()
    assert list_count_problems(skill_text=skill_text, ledger=ledger) == []

    # ① **条数退回旧值**（本单实际修的那处：§26.2 曾写 7，而现取 = 台账 `relay_entries` 条数）
    heading = LIST_COUNT_CLAIMS[1][0]
    line = next(l for l in skill_text.split("\n") if l.strip().startswith(heading))
    stale_line = LIST_COUNT_RE.sub("（7 条", line, count=1)
    assert stale_line != line, "内存构造的变异体与原文本逐字相同（变异没生效）"
    stale = skill_text.replace(line, stale_line, 1)
    assert stale != skill_text
    got = list_count_problems(skill_text=stale, ledger=ledger)
    assert any("条数陈旧" in p for p in got), got

    # ② 标题被删 ⇒ fail-closed 红（**未跑 ≠ 通过**）
    assert list_count_problems(skill_text=skill_text.replace(heading, "### 26.2 （标题被删）", 1),
                               ledger=ledger) != []
    # ③ 读数形态被删（只剩标题、没有 `（N 条）`）⇒ 红（不许静默空跑）
    assert list_count_problems(
        skill_text=skill_text.replace(line, heading + "：转述 / 派单的纪律", 1), ledger=ledger) != []
    # ④ 对照读数：**只加一条注释**（不动任何读数）⇒ 不红
    assert list_count_problems(
        skill_text=skill_text + "\n<!-- 只加一条注释：不改任何读数、不改任何标题 -->\n",
        ledger=ledger) == []
    # ⑤ 对照读数：**改台账而不改标题**同样红（两个方向都判 —— 与判据 19 同口径）
    thinner = json.loads(json.dumps(ledger))
    thinner[RELAY_LEDGER_KEY] = thinner[RELAY_LEDGER_KEY][:-1]
    got = list_count_problems(skill_text=skill_text, ledger=thinner)
    assert any("条数陈旧" in p for p in got), got


# ──────────────────────────────────────────────────────────────────────────────
# 判据 22（本单新增）：**回灌的两条转述纪律（`FM-R14` / `FM-R15`）双向在位、且是 `action`/`gap`**
#
# 病灶（本单实测，来源 = 协调侧派单的 7 处错法）：§26 此前只到 `FM-R13`，而**实测最频繁出错**的那一层
# （「转述方到底跑没跑那条命令」）没有条目 —— 于是同一批交付里，派单侧对两个包各核出 7 处不准。
# 本判据**不新增门禁**（承载体仍是判据 14~18 / 21 那一套），它只把**本批回灌的对象**钉成断言：
#   ① 两条的 id **逐字**出现在 §26、且在台账里**恰好一条**（锚唯一）；
#   ② `kind`/`state` = `action`/`gap` —— **不许**塞进 `guarded` 把「无机械锁」写成「已守护」；
#   ③ 它们是台账**末两条**（§26.2 标题条数与用例库端点都按现取对齐它们）；
#   ④ §26.4 的三张新覆盖面逐字在位（删任一面 ⇒ 红）。
# 红证**全部内存构造**（真文件当基线 → 改内存对象 → 直接喂纯函数），逐条点名命中的分支。
# ──────────────────────────────────────────────────────────────────────────────

#: 本单回灌的两条（顺序即现取顺序；在台账里必须是**最后两条**）。
RELAY_BACKFILL_IDS = ("FM-R14", "FM-R15")


def relay_backfill_problems(*, skill_text: str, ledger: dict) -> list[str]:
    """本批回灌面的自检（空列表 = 全绿）。**纯函数**，红证可内存构造。"""
    bad: list[str] = []
    relay = ledger.get(RELAY_LEDGER_KEY) or []
    rsec = section_text(skill_text, RELAY_SECTION_HEADING) or ""
    for rid in RELAY_BACKFILL_IDS:
        hits = [e for e in relay if e.get("id") == rid]
        if len(hits) != 1:
            bad.append(f"{rid}：台账 `{RELAY_LEDGER_KEY}` 里的命中数 = {len(hits)}（必须恰好 1）")
            continue
        if rsec.count(rid) == 0:
            bad.append(f"{rid}：§26 正文里一次都没出现 ⇒ 下一个人读不到这条纪律（双向绑定断了）")
            continue
        e = hits[0]
        if (e.get("kind"), e.get("state")) != ("action", "gap"):
            bad.append(
                f"{rid}：`kind`/`state` = {e.get('kind')!r}/{e.get('state')!r}，而本批两条"
                f"**只有纪律 + 判别动作、没有机械锁** ⇒ 必须是 `action`/`gap`"
                f"（塞进 `guarded` 就是把**无机械锁**写成**已守护**）"
            )
    tail = [e.get("id") for e in relay][-len(RELAY_BACKFILL_IDS):]
    if tail != list(RELAY_BACKFILL_IDS):
        bad.append(
            f"本批两条不是台账末两条（现取末两条 = {tail}）⇒ §26.2 标题条数与用例库端点会脱钩"
        )
    return bad


def test_relay_backfill_entries_are_registered_and_unlocked() -> None:
    """常驻：本批回灌的两条在技能与台账里**双向在位**、是 `action`/`gap`、且就是台账末两条。"""
    skill_text, _, ledger = _live()
    bad = relay_backfill_problems(skill_text=skill_text, ledger=ledger)
    assert bad == [], "本批回灌面自检失败：\n" + "\n".join(f"  - {p}" for p in bad)


def test_relay_backfill_guard_has_discriminating_power() -> None:
    """红证（**内存构造**，不改磁盘）：四种坏形态各自判红 + 只改注释对照 + 「变异真被读到」自证。"""
    skill_text, _, ledger = _live()
    assert relay_backfill_problems(skill_text=skill_text, ledger=ledger) == []

    # ① 删掉 §26 里 `FM-R14` 的**全部出现** ⇒ 红（命中分支 = 「§26 正文里一次都没出现」）
    stripped = skill_text.replace("FM-R14", "FM-R0")
    assert stripped != skill_text, "内存构造的变异体与原文本逐字相同（变异没生效）"
    got = relay_backfill_problems(skill_text=stripped, ledger=ledger)
    assert any("FM-R14" in p and "一次都没出现" in p for p in got), got

    # ② 台账里把 `FM-R15` 升成 `criterion`/`guarded`（= 把「无机械锁」写成「已守护」）⇒ 红
    #    ⚠️ 这是本批**最贵的那种误读**，必须能红；命中分支 = `kind`/`state` 不是 action/gap
    promoted = json.loads(json.dumps(ledger))
    nxt = next(e for e in promoted[RELAY_LEDGER_KEY] if e["id"] == "FM-R15")
    nxt["state"], nxt["kind"] = "guarded", "criterion"
    got = relay_backfill_problems(skill_text=skill_text, ledger=promoted)
    assert any("FM-R15" in p and "无机械锁" in p for p in got), got

    # ③ 台账里把 `FM-R14` **复制一份**（锚不唯一）⇒ 红（命中分支 = 命中数 != 1）
    dup = json.loads(json.dumps(ledger))
    dup[RELAY_LEDGER_KEY].append(json.loads(json.dumps(
        next(e for e in dup[RELAY_LEDGER_KEY] if e["id"] == "FM-R14"))))
    got = relay_backfill_problems(skill_text=skill_text, ledger=dup)
    assert any("FM-R14" in p and "恰好 1" in p for p in got), got

    # ④ 台账末两条被换成别的（标题条数 / 用例库端点会因此脱钩）⇒ 红（命中分支 = 不是末两条）
    reordered = json.loads(json.dumps(ledger))
    reordered[RELAY_LEDGER_KEY] = list(reversed(reordered[RELAY_LEDGER_KEY]))
    got = relay_backfill_problems(skill_text=skill_text, ledger=reordered)
    assert any("不是台账末两条" in p for p in got), got

    # ⑤ 自证「变异真被读到」：基线含 `FM-R14` 而 ① 的变异体不含它（防变异没生效的空断言）
    assert "FM-R14" in skill_text and "FM-R14" not in stripped
    # ⑥ 对照读数：**只加一条注释**（不动任何记号、不改任何声明）⇒ 不红
    assert relay_backfill_problems(
        skill_text=skill_text + "\n<!-- 只加一条注释：不改任何记号、不改任何声明 -->\n",
        ledger=ledger) == []


def test_relay_boundary_new_faces_are_named() -> None:
    """§26.4 的三张新覆盖面（**原始输出行** / **交出去的命令** / **载体**）逐字在位；删任一面 ⇒ 红。"""
    skill_text, _, _ = _live()
    assert relay_boundary_missing_markers(skill_text) == []
    for marker in ("原始输出行", "交出去的命令", "载体"):
        assert marker in RELAY_BOUNDARY_MARKERS, f"{marker} 没进 marker 表 ⇒ 删了也不会红"
        stripped = skill_text.replace(marker, "·")
        assert stripped != skill_text, f"内存构造的变异体与原文本逐字相同（{marker} 没被替换到）"
        missing = relay_boundary_missing_markers(stripped)
        assert marker in missing, (
            f"删掉 `{marker}` 却没红（分支 = relay_boundary_missing_markers："
            f"§26.4 缺这些面 {missing}）"
        )

