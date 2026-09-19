---
name: migao-dev-flow
version: 1.38.1
# ⚠️ YAML 纯标量陷阱 + 本仓库取舍（v1.21，2026-09-15 实证）：
# `description` 是 YAML **纯标量** ⇒ 解析在第一个「空白 + `#`」处**截断**（`#` 起被当成注释起始），
# 其余内容**静默丢失** —— 「文件里写了」≠「加载器读到了」（与「注释漂移 = 假绿来源」同族，但更隐蔽）。
# 实证（锚定 origin/main 改动前版本）：原文 2666 字符，用**加载器同一个 `yaml` 包**解析只得到 192 字符
# （截断于「v1.11（2026-09-09 issue」）⇒ v1.12/v1.17/v1.18/v1.19/v1.20 的说明**从未**被 skill 加载器读到。
# **取舍**：`description` 只写**有意简短**的摘要（触发语 + 范围）；**变更沿革写进正文 `## 版本沿革`**。
# 不靠「加引号 / 块标量」救长文本 —— 那等于保留「可以无限往后追加」的坏习惯，下一次照样踩。
# 若确需在 frontmatter 放长文本：必须加引号或块标量（`>-`），并接受技能目录多背 ~2k 字符的代价。
# 另注：skill 加载器**只读 `name` + `description`**，且要求**第 1 行就是 `---`**
# （行前加注释会让整个技能被忽略）；`version` 不参与加载，仅供人工 / 锚点新鲜度核对。
description: MIGAO 项目开发提效流程固化 — 开发、验证、提交、部署的完整规范。**改动 MIGAO 代码前必须加载**：三把工具（`verify-all.sh` / `contract-check.sh` / `check-ui-regression.sh`）、提交流程与 CI 门禁（case_ids / QA Growth Gate / auto-merge）、行为改动自动体检（§13）、用例库演进（§14）、前端 UI 旅程（§15）、分层探测与门禁矩阵（§16）、并行修复原则（§17）。**变更沿革已迁至正文「版本沿革」节**（frontmatter 只放简短摘要：纯标量会在「空白 + `#`」处静默截断）。
---

# MIGAO 开发提效流程

本技能固化 MIGAO 项目从开发到部署的提效规范（源自复盘 RETROSPECTIVE 的 P0/P1 改进）。
**在改动 MIGAO 任何代码前加载本技能**，按以下流程执行，避免踩过的高频坑。

> ⚠️ **开工第一件事：按 §18 核对「活锚新鲜度 + 读源真值」**
> —— 预设**活锚**曾落后仓库 **25 个提交**（技能停在 v1.23 而仓库已 v1.27），
> 意味着**每个会话都在按过期规则干活，而没有任何东西会因此变红**。
> **现在有可执行判据了（红就停，一条命令）**：`./scripts/preset-anchor-check.sh`
> （落后/悬空/内容不同/技能加载不了 ⇒ 非零退出；同步 = `./scripts/preset-anchor-refresh.sh`）。
> §18 是本技能的前置总纲：读源（`git show origin/main:<path>`）/ 活锚新鲜度 / **不可变引用** / 前置自断言 /
> 账本与环境新鲜度 —— 这六层同一个病：**读的是快照，按可变键定位被测对象**。
>
> 📇 **要"一眼找到某条纪律落在哪、有没有落码" ⇒ 直接查 §19 范式总纲表**（索引，不含长文）。

## 1. 三把工具（开发自查用）

| 工具 | 用途 | 何时用 |
|---|---|---|
| `./verify-all.sh quick/full/gate` | 三模块一键测试 + QA gate 预检；**gate 档**在变更集命中受管用例面（`.github/cases/**` / case-trust 账本 / `eval_cases.py` / `mibao-verification-cases.md`）时**额外**跑 cases 面门禁（Case Trust / Case Contract / 生成物新鲜度，**同脚本同参数调用、不复制规则**），**未命中 ⇒ 显式打印「未跑」**（"没跑"必须长得像"没跑"，**不是通过**）；残余未覆盖（Case Trust 的 L0 守卫单测 / 追踪单状态查询 / pr-check 其它 job）打 `::warning::`（**#4221**） | 每次改动后、提交前 |
| `./contract-check.sh` | 三端契约一致性（字段名/状态枚举/端点） | 并行改动、跨模块改动后 |
| `./check-ui-regression.sh` | UI 回退检测（neutral token vs origin/main） | **提交前必跑** |

运行（在 migao 仓库根目录）：`./verify-all.sh gate`

## 2. 提交流程（防 UI 回退 / 防 CI 返工）

### 2.1 提交前必查（按序）— 验证分级（2026-09-04 固化，省本地重复计算）
```bash
# 每次改动后：./verify-all.sh quick（~3-5 分钟）即可覆盖常规回归
# 提交前必查（按序）：
# ① UI 回退检测（最重要！防工作区旧 UI 覆盖验收版）
./check-ui-regression.sh

# ② QA gate 预检（本地跑 CI 规则，避免合并前爆 case_ids/缺测）
# ⚠️ **必须在 `git commit` 之后跑**：它的弱断言检查按
#    `git diff --diff-filter=A --name-only origin/main...HEAD` 取"新增测试文件"；
#    **未提交时 HEAD == origin/main ⇒ 新增集为空 ⇒ 该检查静默空跑并通过**（假绿）。
#    实证 2026-09-14：同一条命令 commit 前 ✅ / commit 后 ❌（`--check-weak` exit=1）。
./verify-all.sh gate

# ③ 契约一致性（跨模块改动后）
./contract-check.sh

# ④ 全量单测（quick 即可，full 提交大 PR 前跑）
./verify-all.sh quick

# 合并前：以 CI 结果为准，不本地重复跑 gate —— CI 已排队跑过一遍，
# 本地再跑一遍 gate 是纯浪费（token+时间）。本地跑 gate 只在提交前的瞬间用。
```

⚠️ **本节标题"提交前必查"与 ② 的实现有冲突，按下述顺序执行**（v1.19 修正，2026-09-14 实证）：
**先 `git commit`，再跑 ②③④。** 因为 ② 的**弱断言检查依赖已提交的 diff**（`origin/main...HEAD`），
未提交时它对**新增测试文件**是**空跑并通过**。若你确实想在提交前跑，请明确知道：此时 ② 只对
"存量规则"（growth gate 的文件分类 / 缺测 / 覆盖体检）有效，**对新增测试的弱断言无效**。
> 这不是吹毛求疵：本会话中一个包按"提交前"跑 ② 得到 ✅，`git commit` 后同一条命令变 ❌
> （新增测试里的 `assert x is not None` 被判弱断言），CI 直接红。形态属
> `migao-acceptance`「空跑」——**绿了但没跑**。同理 `quick` 不受影响（它跑的是真实测试）。
>
> **② 还含一层「cases 面门禁」**（v1.34 / **#4221**）：变更集命中受管用例面 ⇒ **额外**跑
> Case Trust / Case Contract / 生成物新鲜度（**同脚本同参数**，见 `verify-all.sh` 的 `cases_face_gate()`），
> 任一非零 ⇒ gate 非零；**未命中 ⇒ 控制台显式打印「未跑」** ——
> 与 ② 同因，该判定**只读已提交 diff** ⇒ 用例改动未 commit 时它是「未跑」而非「通过」，故仍在 commit 后跑。
> 残余未覆盖项（Case Trust 的 L0 守卫单测 / 追踪单状态查询 / pr-check 其它 job）打 `::warning::`；**CI 仍是权威**。

### 2.2 红线（踩过的高频坑，禁止违反）
- **禁止 `git add -A` 盲目提交**：工作区长期积压的未提交改动（尤其旧版 UI）会覆盖 main 上已验收的版本。提交前先 `git status` 检查积压，**逐个确认** UI 文件不是旧版。
- **禁止长期不提交**：避免 142 个文件的大 PR。开发应小步提交 + 频繁 `git fetch origin main && git rebase origin/main`。
- **同步 main 必须用 `./scripts/sync-main.sh`，禁止裸 `git merge/rebase origin/main`**（v1.7 新增，2026-09-07 复盘固化）：merge main 后 `.github/cases/` 前进 → 生成物必然 diverged → CI「生成物新鲜度校验」必红 → 多跑一整轮全量 CI（实测长尾 PR 必踩，含 2 小时空窗）。sync-main 一条命令完成 fetch+merge+重渲染+自动提交，详见 §11.2。
- **禁止分支滞留 + 无记录切换分支**（2026-09-01 实战教训：40+ 本地分支积压，切换旧分支 → 工作区被旧代码覆盖 + 未提交改动静默携带 → 「切换分支后功能退化」）：
  1. 分支开即关联 Issue，验证完即 PR，CI 绿即合并，**分支存活 < 1-2 天**；
  2. 切换分支前 `git status` 必须干净（有改动先 commit/stash）；
  3. 本地验证前先 `git fetch origin main && git rebase origin/main`，**验证必须基于最新主线**；
  4. 多分支并行验证用 `./scripts/dev-worktree.sh add <branch>`（独立工作区，切换零污染），**禁止反复 checkout 切分支**；
  5. 定期清理：`git branch --merged origin/main` 全删；`git cherry origin/main <branch>` 全 `-` 表示内容已落地可删；无独有提交的分支直接删。
- **新增/修改测试必须带 `# case_ids: OR-xxx`** 注释头（按域：OR 订单/AS 售后/PR 商品/FN 财务/CU 客户/DA 看板/UI 前端），否则 QA Growth Gate 会 block 合并。
  - **硬约束 A（位置）：`# case_ids:` 必须出现在测试文件前 50 行内**（`growth_gate.py:extract_case_ids()` 只扫前 50 行；docstring 长的文件极易踩——实证：`# case_ids:` 落在第 71 行（**当时实测的行号**）即被 QA Gate 判「未声明」block，须移到文件头或第 1 行）。
  - **硬约束 B（形态，v1.34 / #4239）：只认「注释起始的声明行」且「首个命中即停」** ——
    正则 = `^\s*(#|//|\*)\s*case_ids\s*[:=]\s*\[?(...)\]?`（`#` / `//` / JSDoc 块注释续行 ` * ` 三种注释形态），
    **不再全文累积**。⇒ **docstring / 正文里「提及」`case_ids:` 不算声明**：
    旧实现用 `search` 全文累积时，「提及」= 「声明」（假红：合规 PR 被判「声明了不存在的用例 ID」；
    假绿：一个真声明都没有的文件被判「已声明」⇒ 门禁**根本失效**）。
    ⇒ **旧时代「靠改措辞规避门禁」的 workaround 已失效，不要再教**；同一文件**声明两次**时只有**第一处**生效
    （第二处会被遮蔽，实证 `test_after_sales_manage.py` 合并为单一声明行）。
    判据源 `.github/growth_gate.py` 的 `extract_case_ids()`；守卫 `tests/unit_ci_workflows/test_growth_gate_case_ids.py`。
  - **硬约束 C（真声明优先，v1.35 / #4311）：排除「字符串 / 块注释区域」内的候选，真声明优先；无真声明才退回旧口径**（取首个候选）。
    理由（**实测**）：**13 个 Python（模块 docstring）+ 4 个 TS（文件头 JSDoc）** 的**合法声明本身就在**字符串/块注释里
    ⇒ 严格排除会把这 **17** 个合规文件判「未声明」（假红，且按 §19.1「存量基线只许缩短」**永远缩不掉**）。
    **残留（如实登记，不粉饰）**：某文件的**唯一**候选落在字符串/块注释内**仍算声明** —— 它与那 17 个合规文件
    **静态不可区分**，属**有意取舍**；唯一可判的坏形态 = 「伪声明在前 + 真声明在后」的**遮蔽形态**（已修）。
    复核（**不写死数字**）：`pytest tests/unit_ci_workflows/test_growth_gate_case_ids.py -q -s -k fallback`。
- **测试文件路径**：前端组件测试放 `tests/unit/components/<Name>.test.tsx`（gate 模板不递归子目录，勿放 `orders/` 子目录）。
- **PR body 必写 `Closes #<issue号>`**（v1.4 新增，2026-09-05 治理固化）：GitHub 只在 PR **body** 含 `Closes/Fixes/Resolves #xx` 关键词时自动关闭 issue，**标题里的「(issue #xx)」不生效**。不写 = 修复合并了 issue 还挂着，全靠人回头对账（实证：9-05 存量 12 个 open issue 里 8 个已修复未关闭）。创建 PR 时在 body 首行写 `Closes #xx`；无 issue 关联的基建类 PR 标 `N/A（基建）`。CI 有 `pr-issue-link` 检查（见 §3），漏写会打 `needs-issue-link` 标签提醒。
- **要表达「不关某 issue」时，绝不能把关键词写在 issue 号前**（v1.19 新增，2026-09-15 实证误关）：`close-linked-issues.yml` 用**朴素 grep 正则** `(close|closes|closed|fix|fixes|fixed|resolve|resolves|resolved)[[:space:]]*#[0-9]+` 扫 body，**否定句照样命中**——写成「不 `Closes #3559`（保持 OPEN）」会在合并后**秒级误关**该 issue；更麻烦的是该工作流的**定时对账会对近 48h 合并的 PR 反复重扫当前 body**，措辞不改就**反复误关**。
  - 正确写法：**把关键词与 issue 号拆开**（如「#3559 保持 OPEN——本 PR 不涉及关闭它」）；
  - ⚠️ **不只是否定句**（v1.20 新增，2026-09-15 实证）：正则只看「关键词 + 空格 + `#号`」这一形态，
    **不区分语义** —— 所以**任何"引用"都会命中**：证据表/复现记录里贴 `Closes #NNNN` 样例、
    回归清单里罗列"本 PR 关掉了哪些"、甚至贴在反引号里的整句 `Closes #3559`（反引号**不**隔断
    关键词与号，只有**插在两者之间**才有效）。
    实证（本会话 PR #3737）：红证表里引用了 5 个关键词+号样例 ⇒ 自查发现会**误关 5 个别人的 issue**
    （含已 CLOSED 的），改成 `` `Closes` + `#NNNN` `` 形式后才提交。
  - 自检：`printf '%s' "$BODY" | grep -oiE '(close|closes|closed|fix|fixes|fixed|resolve|resolves|resolved)[[:space:]]*#[0-9]+'` —— 输出必须**只剩**你本意要关的那些；**0 条命中也是合法结果**（关联已 CLOSED 的 issue / 纯基建 PR 就该是 0）。
  - 关联**已 CLOSED** 的 issue（如"实现 #3709 的收口要求"）**不要**写 `Closes`——用「关联 #NNNN」
    这类不带关键词的措辞；否则每轮对账都会拿到一条"该关却没关成"的无效目标（#3559 家族）。
  - 误关后：重开 issue + 同时改写 body（否则下一轮对账再关一次）。
- **「全绿却 BLOCKED」⇒ 首查未解决评审线程**（v1.34 / **#4231**）：main 的分支保护开了
  `required_conversation_resolution` ⇒ **机器人留下的、且已被后续提交解决的**评审线程
  （`isOutdated=true` 但 `isResolved=false`）会**永久卡合并，且没有任何检查会变红**
  —— 危险处正是「全绿却合不了」会把排查引向 CI / 冲突 / label（#4218 实测：21 pass / 0 fail、
  `mergeable=MERGEABLE`、labels 空、auto-merge 已启用，却 25 分钟不合；手动 resolve 后 **46 秒**自动合并）。
  锚点命令 = `python3 scripts/resolve_stale_bot_threads.py <PR>`（三态 `0/1/3`；**默认 dry-run（只读）**，
  `--apply` 才写；`3` = 无法判定，**不得当 `0` 读**）。
  它**只** resolve「未解决 + bot + `isOutdated`」，**人类线程永不自动 resolve**
  （`required_conversation_resolution` 对**人类**评审线程是有价值的护栏 —— **不要**关掉它）。
  workflow 级自动化 (a)/(b) 因本机 token **无 `workflow` scope** 属**保留类**（不改任何 workflow）。
- **报告型判据「判红不拦合并」**（v1.35 / **#4248**）：native auto-merge 只看分支保护的 **required 集合**，
  `Drift Audit (真相源契约)` / `Case Trust Gate (断言可信度)` 等**报告型**判据不在其中 ⇒ **判红照旧合并**，
  而 PR 页面上红/绿与 required 判据**长得一样** ⇒ 极易被读成「绿 = 可以合」（实证：关联 #4214 的 `Drift Audit` = fail 而该 PR 仍 MERGED；#4266 / #4267 / #4271 同款复发）。
  ① **元判据（裸判据差集）** = `python3 scripts/merge_gate.py --required-diff` —— required 集合 vs「**实际存在且会判红**」的 job 集合的**差集**（**反推、不硬编码**；数字用命令自证，**不写死**）；
  ② **判红落闸** = `python3 scripts/merge_gate.py --check <PR> --apply-label`（**默认同时 disarm** —— 见 §3.3）；
  三态 `0/1/3`（`3` = 无法判定，**不得当 `0` 读**），**默认只读**（dry-run）。

### 2.3 多会话并发规范（v1.3 新增，2026-09-04 实战固化：多 DSH 会话并行踩脚治理）

多会话并发（多 Agent / 多分支同时开发）时的铁律：**一个会话一个独立工作区，会话之间零共享写路径**。

1. **会话必须建在独立 worktree**：`./scripts/dev-worktree.sh add <branch>`（默认 `../migao-wt/<分支>`）。禁止多会话共用一个工作目录——同时改文件互相覆盖、`git add` 互带对方文件、同时跑 verify 抢资源。
2. **会话锁**：`dev-worktree.sh add` 自动登记 `.sessions/<branch>.lock`（含 PID+时间戳）；同一分支已有活跃锁时**禁止**重复建工作区/推分支。提交/推送前先 `./scripts/dev-worktree.sh list` 确认锁状态。
3. **端口隔离**：本地服务端口用环境变量覆盖（`API_PORT`/`AGENT_PORT`/`WEB_PORT`），会话各自 `.env.local`，杜绝 8080/8001/3001 互抢。
4. **主工作区只读**：主仓库（migao/）只做 `fetch/rebase/merge` 与 PR 管理，**不在主工作区直接改文件**（防止未提交改动静默携带）。
   - ⚠️ **硬红线：任何 worktree 里都禁止 `git stash` / `git stash pop` / `git reset --hard` / `git checkout -f`**（v1.18 新增，本会话两次实证：主仓库 stash 被 worktree 里的 stash pop+drop 误删，两次都靠 `git fsck` 找回悬空对象才救回）。**`git stash` 是仓库全局的、跨 worktree 共享**——你以为在动自己的 worktree，实际动的是主仓库的 stash ref。需要暂存/还原时：用 `git worktree add` 另开干净检出、或把改动 commit 到临时分支（stash 之外的任何方式都行）。
5. **分支卫生**：验证完即 PR，CI 绿即合并，分支存活 < 1-2 天；定期 `git branch --merged origin/main` 全删 + 清理 `origin gone` 的本地分支。
6. **开工前读契约**：`docs/wiki/CONTRACT-LEDGER.md`（状态枚举/字段名/端点签名）；跨模块改动后跑 `./contract-check.sh`。
7. **worktree 里的 `.agent-presets/` 是「创建时的快照」** —— **`git add -A` 会静默回退研发模式**（v1.29 新增，2026-09-15 实证）：
   - **病根**：`.agent-presets/**` 看起来是**普通代码路径**（跟着分支走），实际是 **fork 那一刻的副本**；
     worktree 也**不会自动跟 main**。⇒ 分支/检出落后时它**静默过期**，`git add -A` 就把**旧预设提交上去
     = 静默回退研发模式**（实证：某 worktree 的预设停在 **v1.27.0** 而 main 已 **v1.28.0**，同样是"没人会因为这件事变红"）。
     ⚠️ **本条原写「`dev-worktree.sh add` 不做任何刷新或排除」——已过期，v1.35 / 本会话实测改判**（见下）。
   - **如实现状（v1.35 改判）**：`scripts/dev-worktree.sh` 的 `refresh_presets()`（v1.8 / **#3851** 落地）在 **`add` 路径自动**把
     `.agent-presets/**` 对齐 `origin/main`（另有 `rebase` 路径调用），**提交路径另有 `preset-guard`**（版本单调性 + 活锚）。
     ⇒ 「add 不刷新」是**旧真值**，不要再照抄；**但地雷结论保留**（快照仍会落后、`git add -A` 仍会静默回退）：
     **仍须**注意 ① **活锚必须是专职只读镜像**（`migao-wt/*` 的 worktree 属 `rm/prune` 清理半径，**不能当锚点**，见 §18.2）；
     ② **`rm/prune` 会命中 worktree**（清理前先 `readlink "$HOME/.dsh/.agent-presets/migao"`）。
     核法（命令自证）：`grep -n "refresh_presets" scripts/dev-worktree.sh`。
   - **判据（动到 `.agent-presets/**` 的 PR 必须核版本不降级）**：
     ```bash
     # worktree 侧版本 vs origin/main 版本：worktree < main ⇒ **停手**（先刷新，再提交）
     sed -n 's/^version: *//p' .agent-presets/migao/skills/migao-dev-flow/SKILL.md | head -1
     git show origin/main:.agent-presets/migao/skills/migao-dev-flow/SKILL.md | sed -n 's/^version: *//p' | head -1
     # 查看暂存区里 .agent-presets/** 到底改了什么（**提交前必看**）
     git diff --cached -- .agent-presets/
     ```
   - **口径**：① 该 worktree 的 `.agent-presets/**` 若为**旧快照** ⇒
     `git checkout origin/main -- .agent-presets/` 刷新（该目录**只反映主干**，本 worktree 的改动若只动它，
     说明你**改错了地方** —— 应去权威源改了走正常 PR，见 §18.2）；② **不许**用 `git add -A` 盲提交
     （§2.2 红线同族）；③ 判据落到 diff 上：`git diff --cached -- .agent-presets/` 里出现**版本回退**
     ⇒ **拒绝提交**（这就是"静默回退"的形态判据，见 §19.2）。
8. **临时文件也是共享面（`/tmp` / `$TMPDIR`）** —— **PR body 一律落本工作区的忽略目录**（v1.35 / **#4232** 新增）：
   `/tmp`（含 macOS 的 `$TMPDIR` = `/var/folders/…/T`）是**跨会话共享写路径** ⇒ 两个并发会话用**同一个约定俗成的固定名**
   承载 PR body 时，B 覆盖 A 的文件 ⇒ A 的 body 被写成 B 的 body ⇒ 若 A 在该窗口被 auto-merge 合并 ⇒ **误关 B 在做的 issue**。
   ⇒ **禁止共享根下固定名**；用 `python3 scripts/pr_body_guard.py new [--issue N]` 分配**本工作区内、被 `.gitignore` 覆盖**的唯一名
   （`O_CREAT|O_EXCL` ⇒ 真并发也不撞车），落点不满足即 `exit 1`（fail-closed）。
   工具四子命令 `new` / `check` / `verify`（回读 GitHub 比对，只读）/ `scan`（仓内静态守卫），三态退出码 **`0`/`1`/`3`**
   （`3` = 无法判定，**绝不谎报正常**）。
   ⚠️ **`check` 对落在 `$TMPDIR` 下的 body 是硬命中（exit 1）** —— 那正是本单的缺陷形态（body 落在共享根 ⇒ 命中）；
   共享根清单**不写平台常量**且可注入（`$PR_BODY_GUARD_SHARED_ROOTS`，测试据此钉成确定集合）。

## 3. CI 关卡（合并前会自动跑）
| 检查 | 作用 | 失败常见原因 |
|---|---|---|
| UI Regression Check | 防 UI token 回退 | 工作区旧 UI 被提交 |
| QA Growth Gate | case_ids/测试覆盖/弱断言 | 测试忘带 case_ids、测试放错目录 |
| Case Contract | 用例引用完整性 | 改了 case yml 未重渲染 |
| Agent Eval (smoke) | 米宝真实 LLM 行为 | **偶发 LLM 波动**（JSONDecodeError 等，CI 内部已自动重试 1 次） |
| PR Issue Link Check（v1.4 新增） | PR body 是否含 `Closes/Fixes/Resolves #xx`（关联 issue 自动关闭闭环） | body 只把 issue 号写标题、未写 Closes 关键词 → 打 `needs-issue-link` 标签提醒（不 block；bot PR 跳过） |
| **Case Coverage Gate**（v1.17 新增，#3555） | 评测用例库**能力覆盖**：工具零用例/缺正向用例/用例挂错端 → 阻塞；仅 1 条用例的"厚度不足"只报告 | 有用例库能力缺口 → 补用例（§14.5）；矩阵输出即可当补用例任务书 |
| admin-api/web/ai-agent 单测 | 三模块测试 | 并行改动契约不一致 |

### 3.1 Agent Eval 偶发失败的处理（v1.1 修正）
- CI 内部 `local_runner` 已自动重试 1 次（日志可见「第 1 次失败，重试…」）；**2 次均失败才报 FAILURE**。
- **`gh pr checks <PR> --rerun-failed` 实测不生效**（不会触发重跑），必须用 run 级重跑：
```bash
# 取失败 check 的 run id，对 failed job 重跑（等待 ~5 分钟）
run=$(gh pr checks <PR> --json name,link --jq '.[] | select(.name | contains("Agent Eval")) | .link' | grep -oE 'runs/[0-9]+' | cut -d/ -f2 | head -1)
gh run rerun $run --failed
# 重跑后多数会转绿（dependabot PR 批量处理时 6/6 转绿）
```
- 若重跑后仍失败，才按真实失败排查（看 `gh run view --job <job> --log` 中的用例得分）。

### 3.2 真实 LLM 成本治理（v1.3 新增：哪些环节烧真实 token，如何门控）

### 3.3 GitHub 自动合并（v1.4 新增，2026-09-05 治理固化）
- 仓库已开启原生 **Auto Merge**：非 bot、非 draft、无 `block/merge` 标签、目标 main 的 PR，CI 全绿后**自动 squash 合并 + 删分支**，无需人工点合并。
- agent 创建 PR 后**不需要等人工合并**——CI 绿即自动合；合并后 issue 因 body 的 Closes 自动关闭，形成「PR→合并→issue 关闭」全自动闭环。
- 三个兜底闸门：bot PR（dependabot 需人工按 §7 SOP 分类）、`block/merge` 标签（人工闸）、draft PR 不自动合。
- 强制人工合并的例外：改 `.github/workflows/` 的 PR 需 `workflow` scope（默认 token 无），按 §7.1 保留类处理。
- **「全绿却 BLOCKED」不是 CI 问题**（v1.34 / **#4231**）：CI 绿 + `MERGEABLE` + 无阻塞 label 而
  `mergeStateStatus=BLOCKED` ⇒ 按 §2.2 首查**未解决评审线程**
  （`python3 scripts/resolve_stale_bot_threads.py <PR>`），**别**去重跑 CI / 查冲突 / 查 label。
- 🔴 **`block/merge` 标签拦不住「已 arm」的 auto-merge**（v1.35 / **#4248**，实证关联 **#4334**）：
  `automerge.yml` 的 `if:`（含 `!contains(labels,'block/merge')`）**只在 arm 时**生效 ——
  `labeled` 事件重跑时 `if` 为假 ⇒ **什么也不做**（**不 disarm**）⇒ 标签打上了、PR 照样合。
  实证两条**至今带着该标签却已 MERGED**：关联 #4271 的 `autoMergeRequest.enabledAt = 07:03:18Z`、
  标签 `07:03:19Z`（**晚 1 秒**）、**合并 `07:07:22Z`**；关联 #4266 标签 `06:57:32Z`、**合并 `07:00:30Z`**。
  ⇒ **只有 `gh pr merge --disable-auto` 能停住它**：落闸用
  `python3 scripts/merge_gate.py --check <PR> --apply-label`（**默认同时 disarm**；未 arm 时只打标签即可）；
  逃生口 `--no-disarm-auto` **会明写**「已 arm 的 auto-merge 不会被本标签拦住」（**不做静默降级**）。
  workflow 级接线 = **保留类**（本机 token 无 `workflow` scope，不改任何 workflow）。

### 3.4 测试要求按变更文件类型（QA Growth Gate 门禁）

PR 合并前，CI 自动扫描变更文件，按类型强制对应测试（G5 追溯由 pr-check 的 qa-growth-gate job 强制；case_ids 铁律见 §2.2）：

| 变更类型 | 测试要求 |
|---------|---------|
| Controller (Java) | MockMvc 集成测试 + API contract E2E |
| Service (Java) | JUnit 单测（覆盖率 ≥80%）|
| Tool (Python) | L2 单测 + L3 Real E2E |
| Component (TSX) | E2E 点击链路（渲染→点击→发送→验证）|
| Page (TSX) | E2E spec + anti-placeholder 注册 |

## 4. 部署
- 合并到 main 自动触发 3 个部署（admin-api/ai-agent/frontend）+ post-deploy 冒烟。
- **部署后验证（2026-09-01 修正：`/actuator/health` 公网 404 是 nginx 屏蔽的预期行为，勿当成故障）**：
  ```bash
  curl -s https://ai-api.migaozn.com/health          # ai-agent → {"status":"healthy"}
  curl -s -o /dev/null -w "%{http_code}\n" https://merchant.migaozn.com/login   # frontend → 200
  curl -s -o /dev/null -w "%{http_code}\n" -X POST https://api.migaozn.com/api/auth/sms-code -H 'Content-Type: application/json' -d '{}'  # admin-api → 401（存活+鉴权）
  ```
- 冒烟失败若为全量 502/Connection refused 且后续部署已覆盖 → 多为**部署滚动重启瞬态**，看最新一次部署结论即可（见 §7.3 的 mergeStateStatus 思路）。
- 生产登录：13800138000 / 万能码 123456（短信网关仍 bypass，上线前需接入）。

## 5. 相关文档
- `docs/wiki/CONTRACT-LEDGER.md` — 并行开发契约清单
- `walkthrough/RETROSPECTIVE.md` — 全链路复盘（本技能来源）
- `verify-all.sh` / `contract-check.sh` / `check-ui-regression.sh` — 三把工具

## 6. 提交前体检一键命令（2026-08-28 固化）

```bash
cd /Users/guangzhen.zk/ai native/migao
# 一次命令检查：git 分支/脏文件、三把工具就绪、case 生成物与 cases/ 单一源同步
cd .github && python3 render_cases.py --cases cases --out-eval /tmp/ec.py --out-md /tmp/cb.md >/dev/null 2>&1 \
  && diff -q /tmp/ec.py ../tests/agent_eval/eval_cases.py >/dev/null 2>&1 \
  && diff -q /tmp/cb.md ../docs/testing/mibao-verification-cases.md >/dev/null 2>&1 \
  && echo "生成物 SYNC ✓" || echo "生成物 DIVERGED ⚠️（需重渲染并提交）"
```

## 7. dependabot PR 批量处理 SOP（v1.1 新增，2026-09-01 实战固化）

一次 27 个 dependabot PR 的实战结论：**分类处理，不要全部合并或全部关闭**。

### 7.1 分类标准
| 类别 | 判断 | 处理 |
|---|---|---|
| ✅ 合并 | CI 全绿；或仅 Agent Eval 偶发失败（§3.1 重跑后转绿） | squash 合并 + 删分支 |
| ❌ 关闭 | 依赖解析冲突（npm ERESOLVE / pip ResolutionImpossible）或大版本破坏性升级 | 关闭 + comment 注明原因 |
| ⏸ 保留 | 修改 `.github/workflows/` 的 PR 需要 gh token 的 `workflow` scope（默认 OAuth token 没有） | 保持 open，留给有权限者 |

### 7.2 高频关闭模式（实战 9/27）
- **「半套升级」**：只升子包不升核心 → peer 冲突。例：`@vitest/coverage-v8@4` 配 `vitest@3`；`@tarojs/react@4` 或 `@tarojs/plugin-platform-*@4` 配 tarojs 3.6.40 全家桶；`@babel/core@8` 配 ts-jest 29。
- **pip 冲突**：`pytest-asyncio@1.4` 与 `pytest==8.3.4`、`langchain-openai@1.6` 与 `langchain-core==1.4.8` 不共存。
- **框架破坏**：tailwindcss 4（PostCSS 插件拆分需 `@tailwindcss/postcss`）、mybatis-plus 3.5.9+（extension 拆独立模块）。
- 以上统一回复：关闭原因 + 需要「工程级整组升级」结论，避免 dependabot 半套升级反复打扰。

### 7.3 操作要点
- **同文件组串行合并**：多个 PR 改同一文件（requirements.txt / pom.xml / package.json）时逐个合并，避免同时合并互相冲突；可用后台循环脚本轮询 `mergeStateStatus`，CLEAN/UNSTABLE 才合并。
- `mergeStateStatus` 含义：`UNKNOWN`=GitHub 重算中（main 刚更新），等 30~60s；`BLOCKED`=CI 重跑中或有 pending check；`UNSTABLE`=有 failed check 但非 required，通常可合并；`CLEAN`=直接可合并。
- **分支落后（DIRTY/CONFLICTING）**：`gh pr update-branch <PR>` 触发 rebase；若 update 报冲突，本地 fetch PR 分支 merge origin/main 解决后 push（dependabot 分支同名推送即可）。
- 合并前先 `gh pr checks <PR>` 确认无 required check 失败；改 workflow 文件的 PR 若报 `without workflow scope` 即属 §7.1 保留类。

## 8. CI/本地环境差异已知坑（v1.1 新增，issue #2693 全量教训）

| 坑 | 现象 | 修复 |
|---|---|---|
| **Taro dotenv 只认 .env 文件** | mini-app 构建产物残留 `process.env.TARO_APP_*` → 浏览器抛 `process is not defined` → H5 整页白屏、不请求路由 chunk | `config/index.ts` 的 `defineConstants` 显式替换：`'process.env.TARO_APP_API_URL': JSON.stringify(process.env.TARO_APP_API_URL \|\| '')`（不依赖 .env 文件）；验证：构建后 `grep -c "process\.env" dist/js/app.js` 应为 0 |
| **Playwright 截图按平台找基线** | `toHaveScreenshot` 找 `xxx-{platform}.png`（mac→darwin，CI→linux）；只提交 darwin 基线 → CI 报 "A snapshot doesn't exist ...-linux.png" | 新基线在 CI 用 `--update-snapshots` 生成，或从失败 actual 截图采纳为 `-linux.png` 提交（页面渲染稳定时）；修改 UI 后**双平台基线都要更新** |
| **生成物冲突要重渲染** | `eval_cases.py` / `mibao-verification-cases.md` 合并冲突 | 不要手改——以合并后 `.github/cases/` 为源跑 `python3 .github/render_cases.py --cases .github/cases --out-eval tests/agent_eval/eval_cases.py --out-md docs/testing/mibao-verification-cases.md`，再提交 |
| **shallow clone 无共同祖先** | `git merge-base` 失败、merge 报 unrelated histories | `git fetch --deepen=300 origin main` 后重试 |
| **UI 视觉问题排查** | 页面白屏/不渲染 | 三步定位：① spec 加 `page.on('pageerror')`/`console` 打印重跑 ② 下载 `xiaobu-visual-diffs` artifact 看 trace/截图（像素分析判断纯白）③ 对比本地构建产物（`grep process` 等） |
| **本地 .env 云库地址泄漏进单测**（issue #2957，2026-09-06） | 本地 pytest 从分钟级恶化到小时级（`verify-all.sh quick` 实测 58min 跑不完），CI 却 1-3 分钟正常 | 根因：本地 `.env` 的 DATABASE_URL/REDIS_URL 指向阿里云 RDS/Redis **公网地址**，单测未 mock 的存储调用（SessionStateStore/SessionMemory/context_manager）真实连接云库，每用例挂起/超时数十秒。修复：`tests/conftest.py` 顶部 `os.environ.setdefault("DATABASE_URL"/"REDIS_URL", localhost)`——setdefault 不覆盖 CI 注入的真实 env（环境变量优先级高于 .env 文件），单测内未 mock 连接毫秒级拒绝走降级。**判断信号：本地慢、CI 快 = 环境差异（.env/依赖），不是业务代码** |
| **测试产物用「全局通配」定位 / 清理**（issue #4158，2026-09-18） | `/tmp/verify-all-*-*.log` 这类**跨进程通配**：清理时会删掉**别的会话 / 别的 worktree 正在用**的日志 ⇒ **跨会话假红**（issue 载**三路执行者独立撞到**）；`<PID>` 通配定位还会因 **PID 复用**读到别的会话的同前缀残骸；日志被外部清理器删掉则退化成**空 glob 断言**或裸 `FileNotFoundError`（看不出该找什么、找过哪些路径） | **产物路径必须由被测系统给出，或限定在测试自己的临时目录**（`tmp_path` / `TMPDIR` + 唯一前缀）；🔴 **禁止 `/tmp/verify-all-*-*.log` 这类全局通配清理**（清理收窄到 **`$$` 作用域**）；定位失败必须**明确报红 + 打印全现场**（期望路径模式 / PID / 实际命中 / 被排除的残骸清单 / 控制台原文 / 处置线索），**不得**空跑 —— 形态同 `migao-acceptance`「空跑：绿了但没跑」。**已落码**：单一实现 `tests/unit_ci_workflows/test_verify_all_log_scope.py` 的 `run_gate()`（PID 通配 ∩ **归属过滤**＝运行前快照 + mtime 窗口；定位不到 ⇒ `VerifyAllLogNotFound` + 全现场），静态清理口径守卫 + 行为判据 ⑨⑩ 同在该文件 |
| **`patch()` 目标与「调用点」不同源**（issue #4310，2026-09-18） | `app/main.py` 在**导入期按值绑定**（`from app.utils.database import init_db`）⇒ patch **源模块** `app.utils.database.init_db` **对 lifespan 无效**：fixture 宣称「跳过真实 DB/Redis 初始化」**实际未达成** —— 属**测试基础设施静默失效**（patch 生效期内 `app.main.init_db is app.utils.database.init_db` 为 **False**，而真实 init 照跑） | patch **调用点所在模块里的那个名字**（`app.main.<name>`），**不是**源模块；判据 = patch 生效期内二者**不同一**才算真的换掉了。锚点 = `tests/conftest.py` 的 lifespan fixture（`patch("app.main.init_db"…)` 四条）+ `tests/test_conftest_fixtures.py`（同族假绿：单跑时恰好是 mock、patch 退出后 mock **永久残留**） |

## 9. 本地验证防恶化（v1.5 新增，2026-09-06 issue #2957 复盘固化）

**教训**：`verify-all.sh quick` 宣称 3-5 分钟，实际曾恶化到 **58 分钟跑不完**（单用例真实连阿里云 RDS 挂起数十秒 × 数百用例）。修复后 57 秒全绿。这类恶化是**渐进累积**的（每加一个新依赖就多几个未 mock 的真实调用），不体检就会持续蔓延，故固化以下体检与红线。

### 9.1 体检命令（本地验证变慢 / 每次开发前可跑，秒级）

```bash
cd /Users/guangzhen.zk/ai native/migao/backend/ai-agent-service
# ① 防云库泄漏：conftest 必须钉死单测存储地址（env 优先级高于 .env 文件）
grep -q 'os.environ.setdefault("DATABASE_URL"' tests/conftest.py && echo "✓ 云库隔离" || echo "⚠️ conftest 缺 DATABASE_URL setdefault——本地 .env 云库将泄漏进单测"
# ② 防 hang 无限等：pytest.ini 需 timeout 兜底
grep -q -- '--timeout=' pytest.ini && echo "✓ timeout 兜底" || echo "⚠️ pytest.ini 缺 --timeout——hang 用例将无限等待"
# ③ 依赖漂移：本地 venv 与 requirements 对齐（旧依赖会引入行为差异）
diff -q <(pip freeze 2>/dev/null | sort) <(sed 's/ *$//' requirements.txt | grep -E '^[a-zA-Z0-9_.-]+==' | sort) >/dev/null && echo "✓ 依赖对齐" || echo "⚠️ venv 与 requirements 漂移——先 pip install -r requirements.txt"
```

### 9.2 六条防复发红线

1. **测试环境与云环境用 `.env` 隔离，单测一律 localhost**：`tests/conftest.py` 必须保留 `os.environ.setdefault("DATABASE_URL", "...localhost...")` 与 REDIS_URL 同理。缺失 = 本次 58min 事件复现。
2. **新增测试禁止引入未 mock 的真实外部存储调用**：`SessionStateStore`/`SessionMemory`/context_manager/Redis/DB 等在单测中必须 mock 或由 conftest 兜底——否则每用例真实连云库挂起数十秒，且**恶化是渐进的**（每个新依赖 +N 秒，无明显单点故障，最危险）。
3. **pytest.ini 必须保留 `--timeout=120 --timeout-method=thread`**：hang 用例 120s 兜底快速失败，而不是无限等待拖死整轮。
4. **依赖同步**：升级 requirements.txt 后立即本地 `pip install -r requirements.txt`；本地/CI 行为不一致时先查依赖版本漂移。
5. **本地慢 CI 快 = 环境差异信号**：先查 ① .env 云库地址 ② 未 mock 外部调用 ③ venv 漂移，不要先怀疑业务代码（本次 52min 排查路径印证）。
6. **每日定时真 LLM 任务连续失败 → 停用 schedule 修稳再恢复**：e2e-real/xiaobu-acceptance/nightly 曾 5+ 连日失败且自动开 issue 刷噪音（2026-09-06 停用，保留 `workflow_dispatch` 手动入口）。恢复前先确认失败根因是环境非业务波动。

### 9.3 排查路径（发现本地验证变慢时按序）

1. 跑 §9.1 体检命令，先排除三项环境问题（最可能，秒级确认）；
2. 仍慢：`pytest -q --durations=20` 找最慢用例，单用例 >2s 即可疑；
3. 单用例慢：看是否含真实网络调用（日志 grep `Connect call failed`/`Connection timeout`/`redis down`），是 → 补 mock 或 conftest 兜底；
4. 干净 worktree + 新 venv 交叉验证（本次定位 58min 事件的决胜手段：同代码 worktree 3s vs 主仓库 52min，一举锁定环境差异）。

## 10. 云资源运维（aliyun CLI 自服务，v1.6 新增，2026-09-06）

**背景**：本机已安装 aliyun CLI（`aliyun version` 可验）且 default profile 凭据有效（`aliyun configure list` 显示 Valid，区域 cn-hangzhou），**AI 具备云运维权限账号能力，可直接自服务阿里云资源操作，无需人工进控制台**（2026-09-06 实证：直接给 RDS 加白名单恢复本地连云 dev，TaskId 707541181）。

**已知资产**（已核实）：
- RDS 实例：`pgm-bp1p7w92k81ob5to`（cn-hangzhou，PostgreSQL 18，VPC 网络，公网主机名 `pgm-bp1p7w92k81ob5to-pub.pg.rds.aliyuncs.com`）
- 白名单分组：`default`（核心 IP，勿动）+ `dev_local`（本地开发 IP 集合，含 183.156.x / 183.128.x 等 + 60.176.163.0/24）
- Redis：`r-bp162hozkjd55e18rbpd`（已放行）

**常用命令**：
```bash
# 查当前公网 IP（本地起服务连 RDS 前核对）
curl -s https://ifconfig.me

# 查实例
aliyun rds DescribeDBInstances --RegionId cn-hangzhou
# 查白名单（确认当前 IP 是否在列）
aliyun rds DescribeDBInstanceIPArrayList --DBInstanceId pgm-bp1p7w92k81ob5to

# 追加白名单（本地起服务连云 dev 必做；单测不需要见 §9）
# ⚠️ 必须"查旧列表 → 原样保留 + 追加新 IP"整体覆盖，禁止清空/覆盖他人 IP
aliyun rds ModifySecurityIps --DBInstanceId pgm-bp1p7w92k81ob5to \
  --SecurityIps "<旧列表,新IP/32>" --DBInstanceIPArrayName dev_local
```

**安全边界**：
1. 白名单只服务于「本地起服务联调」；**单测/verify-all 不需要且不允许白名单**（conftest 已隔离，见 §9.2-1）；
2. ModifySecurityIps 是**整体覆盖语义**——必须先 Describe 出完整旧列表再加新 IP，防误删他人；
3. 默认只改 `dev_local` 组，不动 `default` 组；
4. RDS 凭据/密码等敏感值不写进任何文档或 commit（.env 不入库）。

## 11. PR 生命周期治理：CI 首轮盯守 + sync-main 一条龙（v1.7 新增，2026-09-07 复盘固化）

**背景数据（2026-09-07 实测 60 个 PR）**：auto-merge 已把「等合并」根除——open→merge 中位数 **2.3min**，77% 的 PR 10 分钟内合并。剩余长尾（187/129/45min）耗时构成：CI 首轮红了**无人盯守 2 小时空窗**（占长尾 90%）+ merge main 后生成物未重渲染被 CI 新鲜度校验打回 → 多跑全量 CI 轮次。**瓶颈不在 CI 本身（单轮 3-4min），在「红了没人修」和「merge main 返工」。**

### 11.1 铁律一：PR 创建后必须盯首轮 CI 结论，红了立即修（禁止丢下红 CI 去开新任务/新分支）

- push 分支 + 开 PR 后，**必须先等到首轮 CI 出结论再转场**：用 `gh pr checks <PR> --watch`（**一次阻塞调用**），**首选把它丢后台 job**（完成时被通知，期间做别的）。🔴 **禁止 `sleep N` 轮询**（v1.38 / **#4455**：实测 7 次 = **684s = 11.4 min**，占 bash 执行 **42%**，且每次都是一轮模型往返）—— 本行旧文本里的「**或轮询**」是实测踩过的逃生口，**已删除**。禁止创建完 PR 就去做别的，让 CI 红着挂 2 小时。
- CI 红了：**立即修复 push**（多数是 case 生成物/truths/测试探针问题，5-10 分钟内可修），修完仍要盯到下一轮绿（auto-merge 全绿即自动合，见 §3.3）。
- 想重跑已失败的轮次：`gh run rerun <run_id> --failed`（run id 从 `gh pr checks` 的 link 提取，见 §3.1），**禁止用空提交 hack 触发重跑**。

### 11.2 铁律二：同步 main 必须用 `./scripts/sync-main.sh`，禁止裸 `git merge origin/main` / `git rebase origin/main`

- 为什么：merge origin/main 后 `.github/cases/` 单一源前进 → 生成物（`tests/agent_eval/eval_cases.py` + `docs/testing/mibao-verification-cases.md`）必然 diverged → CI「生成物新鲜度校验」必红 → 手动重渲染再 push → **多跑一整轮全量 CI**（实测每个长尾 PR 必踩，且常伴随空窗翻倍）。
- `sync-main.sh` 把「fetch + merge/rebase + 自动重渲染生成物 + 自动提交 + 提醒盯 CI」合成**一条命令**，同步即渲染，杜绝①型返工：
  ```bash
  ./scripts/sync-main.sh            # fetch origin/main → merge → 重渲染 → 自动提交（默认）
  ./scripts/sync-main.sh --rebase   # 用 rebase 替代 merge
  ./scripts/sync-main.sh --no-commit # 只 merge + 重渲染，不自动提交（人工审 diff）
  ```
- 脚本前置防线：非 main 分支 + 工作区干净才执行（防未提交改动静默携带，同 §2.2 红线）。
- 后续流程照旧：`git push` → `gh pr checks --watch` 盯首轮（见 §11.1）。

### 11.3 判定信号
- **PR open→merge 明显超出 10-15 分钟** → 大概率是两种返工之一：CI 红了没立即修（§11.1）/ merge main 后没跑 sync-main（§11.2）。对照 `gh run list --branch <分支>` 与 `git log` 的 commit 时间戳即可定位空窗发生在哪一段。
- **合并后必须核交付物（v1.29 新增）**：native auto-merge 会**秒合** ⇒ "PR 已合并"**不等于**"你要交付的内容在 main 上"。
  机械核法/搁浅检测/判据见 **§17.3 的「三件事」段**（此处只给指针，不重复表述）；
  合并后**顺手核一次**是常规收口动作（与 §18.2 活锚同步同批做）。

## 12. 验收/评测结论前必加载 migao-acceptance（v1.8 新增，2026-09-08 复盘固化）

- **触发**：任何「验收通过 / 评测 OK / 交付完成」结论、验收 agent 会话/功能/修复回归、写/改评测 case 或验收场景——先加载技能 `migao-acceptance`，按 `docs/testing/acceptance-protocol.md` 执行（协议单一事实源）。
- **背景**：2026-09-08 人工重点验收 3 个 agent 会话（sess_7f27137647e14b1e / sess_50ff3e3c824c4a70 / sess_c1fce183dae24f22）发现的问题，此前评测与验收全部判过 OK。根因：评测断言"工具被调用"而非"用户看到的会话"、关键行为写在不计分的自然语义 data_checks、无时序/金额/卡片内容断言、验收视角与开发者同源、前端渲染与生命周期是结构性盲区。
- **一句话**：三把工具保证"不崩、契约对"；本协议保证"用户看着好"。

## 13. 行为改动评测体检（agent-eval 用例回归，v1.9 新增；**v1.33 改判为「仅用户显式要求时跑」**）

**铁律（v1.33 改判，2026-09-18 #4262 用户裁定）**：改动 ai-agent 的**行为/交互**
（prompt、Tool、引导流程、交互卡逻辑）后，**默认不跑真实 LLM 评测、不派发任何评测 workflow**。

> 用户原话：「**不要自动进行验证，都是重复的验证，白白消耗成本**」「**手动集中跑一次即可**」。

- **必做的零成本动作**：按 §13.2 映射表算出**该跑哪几条用例**，把清单（用例 ID + 理由）
  写进 PR body / 结论里 —— 这是确定性动作，不花钱，且让"该跑什么"可复核。
- **跑真实 LLM 只有一个触发条件**：用户显式要求。届时**一次集中跑**（按 §16.7 选档），
  **禁止**逐条 / 逐轮 / 每个会话各派发一次（#4262 的实测病灶：两天被 agent 自动派发
  10 次全量，9/17 CST 2 次 + 9/18 CST 8 次 = 1205 场真实多轮 LLM 会话）。
- **本技能旧版口径（v1.9「提交前自动跑、不等用户要求」）已作废** —— 照抄它 = 把用户
  明确买下的账又花一遍。防回退机械锁见 §16.5 门禁矩阵 + `test_behavior_eval_pr_thin.py`
  （白名单：自动真实 LLM 触发**只允许 1 条**，即 `post-deploy-eval` 每周一）。

### 13.1 命令（**仅用户显式要求时执行**；命令本身不变）

```bash
cd /Users/guangzhen.zk/ai native/migao
# 单条体检（真实 LLM，对生产或本地服务；AI_API_URL/ADMIN_API_URL 默认生产）
"/Users/guangzhen.zk/ai native/migao/backend/ai-agent-service/.venv/bin/python" \
  tests/agent_eval/local_runner.py case <用例ID> --cases .github/cases
# 冒烟档（PR 门禁同 7 条）
... local_runner.py smoke --cases .github/cases
# normal 档全量（较大改动/涉及多域时）
... local_runner.py normal --cases .github/cases
```

⚠️ 派发前先查槽位（§16.6 ⑥）；**不要**在无用户要求时把上面的命令包进"自动收口"流程。

### 13.2 改动类型 → 必跑用例映射（新增用例时同步更新本表）

| 改动类型 | 必跑用例 |
|---|---|
| 下单引导/加工项询问/金额计算 | OR-016 |
| 换货/售后工单引导 | AS-007 |
| 建品（属性/加工项价格/参数完整性） | PR-019、PR-020 |
| 澄清/多轮/转人工 | CH-003、CH-022、CH-013/014/015（smoke 档含部分） |
| 图片/视觉链路 | CH-021、CH-026 |
| 防御/注入/边界 | defense.yml（smoke/adversarial） |
| 交互卡渲染/前端 | 前端抽验剧本 `docs/testing/frontend-acceptance-checklist.md` + CH-010/CH-019 |
| admin-web 页面结构/布局/交互流/样式改动（新页面、Tab/列表/分页/弹窗、写操作闭环、fixed 浮动元素） | **§15 UI 旅程强制验证**（交互断言结果可见 + 真实浏览器走查 + 几何探针）+ 三把工具 |
| 不涉及 agent 行为的改动（纯文档/基建/前端样式） | 跳过（跑三把工具即可） |

### 13.3 迭代沉淀红线（防"修了又改出来"）

- 新 bug 修复后**必须补可执行 case**（断言可选：`order_before` 时序 / `forbidden_text` 反模式 /
  `required_args` 参数完整性 / `db_verify` 落库验证——按缺陷层选），并做**case 有效性验证**：
  旧失败会话/场景重放该 case 必 fail、修复后重放必 pass；
- 缺有效性验证 = 未闭环（协议 acceptance-protocol §5），禁止以"已修复"结论收尾；
- 自然语义 data_checks 不算覆盖（协议 §1.3 铁律）。

**★ LLM 红例的同类红线（裁定 4′，2026-09-17；承载 issue #4034）**：由**真实 LLM 评测**发现的红例
（自动开的 `[Post-Deploy]` / `[Xiaobu]` / `[Agent Eval]` 一族）**必须下沉**为 ≥1 条**确定性断言**
（`must_succeed` / `db_verify` / `amount_verify` / `output_verify` / L0 不变式），否则**不算闭环**；
红例的处理结果记入 `.github/llm-finding-ledger.json`（用例侧还要在 `merge_log` 回填 `issue #N`），
**未下沉必须显式登记**（`status: unsunk` + reason + follow_up）。
机械检查（**别靠记性**）：`python3 .github/llm_sink_check.py --issue <红例 issue 号>`
（`0` = 已下沉且断言非空 / `1` = 未登记或空壳 / `3` = 无法判定）。
为什么这条特别要紧：PR 层真实 LLM 已停跑（裁定 2′）⇒ **确定性层是唯一的拦截面**，
红例不下沉 = 同一缺陷下次照样溜过 PR。详版：`docs/testing/llm-finding-sinking.md`。

### 13.4 与验收协议的关系

体检用例（§13.2）是 L1 层；「下验收通过结论」前的完整验收（剧本/L1-L2-UA/证据链/
双 AI 交叉验证）按 §12 加载 `migao-acceptance` 执行。三把工具 + §13 体检 + §12 验收
= 提交前/迭代中的完整质量闭环。

### 13.5 用例编写陷阱（v1.16 新增，2026-09-14 并行修复实测固化）

写 `user_inputs` 的**卡回放轮**时，这些坑会直接造成假失败（问题不在 agent）：

| 陷阱 | 症状 | 正确写法 |
|---|---|---|
| 给 `auto_select` 加 `fallback` 字段 | 字段被**静默忽略**（`run_case` → `resolve_auto_select_turn` 不接收 fallback） | 要 fallback 用 `auto_respond: {fallback: "确认创建"}`（有卡答卡：confirm→confirmValue / choice→首项 / form→按声明值回填；无卡发原文） |
| **卡在收尾轮才下发**，只发一轮答卡 | 那轮拿不到卡（agent 在下一轮才 interact）→ 流程停住 | `repeat_until: {tool_called: <目标写工具>, max: 3}` + `fallback`（先例 OR-021/CH-033；停条件用**工具成功**避免重复落库） |
| 写操作收尾发**裸文本**「确认/确认创建」 | 写工具受 confirm 门禁约束：**文字 ≠ 点卡** → agent 回「请点上方卡片」不执行 | 收尾改成答卡轮（缺卡值 → 用 `repeat_until`；或回放卡 `confirmValue` 原文，先例 OR-014） |
| `auto_select` 落在 **form 卡**上 | 发「第一个」→ agent 回「表单没收到提交内容」 | 该轮用 `auto_fill: {字段: 值}`（**先读该卡 `formFields` 的真实 key**，别臆造） |
| 文本里留**未替换占位符**（「颜色…门幅…」） | agent 只能追问，用例自判失败 | 补全真实字段值 |
| 点名**目录里不存在**的加工项/商品 | agent 反复搜不到（行为合理）→ 用例恒红 | 用种子/目录里真实存在的项（先查 `xiaobu_eval_seed.sql` / `mibao_eval_seed.sql`）；或显式声明映射意图 |
| 依赖**云环境存量数据**（硬编码订单号/价格） | 独立栈（干净库）必然查不到 → 假失败 | **自包含化**：改成「最近的订单」等环境无关问法（先例 AS-003/CR-001/OR-006） |

> 自查命令：`/Users/guangzhen.zk/ai native/migao/backend/ai-agent-service/.venv/bin/python -m pytest tests/unit_ci_workflows/ -q`
> （种子守卫会拦"点名商品不在 fixture"；措辞误抓先例见 OR-025）。

## 14. 用例库演进：什么时候补充/完善评测用例（v1.10 新增，2026-09-08 固化）

> 缺口复盘：§13 只管"跑已有用例"和"修 bug 后沉淀"，没有主动触发时机——用例库会随
> 迭代逐渐与行为现实脱节。本节定义**何时必须新增/修订用例**（主动，不等问题暴露）。

### 14.1 必须新增用例的触发时机（满足任一即补，禁止跳）

| 触发 | 动作 | 判据 |
|---|---|---|
| 新功能/新行为合入（feat 涉及 ai-agent 行为/交互） | 按域补覆盖用例（核心流程 tier normal，门禁级 smoke） | PR 的 traces.cases 或 PR body 声明引用/新增的用例 ID；无引用 = 未闭环 |
| prompt / Tool / 交互契约变更（行为规则变了） | 修订对应域用例断言或新增 | 旧用例对"新合法行为"不能误判（先重放校验再改） |
| 新域/新工具落地 | 补该域用例（参考 `.github/cases/README.md` 域清单） | 用例可被 local_runner 真实执行 |
| 用户/验收/线上发现问题 | §13.3 沉淀（含有效性验证） | 旧失败重放必 fail |
| 新断言能力落地（order_before/forbidden_text/required_args/db_verify） | **回填**适用旧用例（如建品价格→PR-019/PR-020 的 required_args+db_verify） | 存量自然语义 data_checks 可执行化 |

### 14.2 必须修订用例的触发时机

| 触发 | 动作 |
|---|---|
| **有效性漂移**：真实重放 fail 但行为合理（LLM 合法变体，如换货文本询问加工项） | 校准断言（放宽或语义化，先例：AS-007 expectations 改为 interact or direct_reply） |
| **波动台账治理**：flake_ledger 高波动用例 | 收敛断言/拆分用例/显式标记预期波动 |
| **断言可执行化**：存量自然语义 data_checks | 升级为机器断言（协议 §1.3 铁律，不允许"看起来有覆盖"） |
| 生成物纪律：改了 cases/*.yml | 必跑 `render_cases.py` 并提交生成物（否则 CI 新鲜度校验红） |

### 14.3 定期回顾（防用例库与现实脱节）

- **每轮验收报告发布后**：对照问题清单，检查每个 P0/P1 是否已沉淀成可执行 case（缺 → 补）；
- **每双周/大版本**：用例库体检——抽查 N 条用例真实重放，验证"用例 vs 当前行为"仍一致，
  并对齐 §14.1/§14.2 触发清单；
- **观测信号**：agent-eval 某用例连续 flake（台账）、或人工发现"以前测过现在不行/以前不行现在行了"
  均说明用例需修订，按 §14.2 处理。

### 14.4 一句话

**用例库是被迭代喂养的活资产**：新功能必补、行为变必改、断言必可执行、定期必回顾——
任何一步缺失，评测体系就会退回"看起来有覆盖"。

### 14.5 覆盖厚度（v1.17 新增，2026-09-14 issue #3555 固化）

> §14.1 的触发条件是「**有了新东西**要补用例」；本节补上另一半：**已有的东西覆盖过薄、
> 或根本没有正向用例**，同样是必须补用例的触发条件。此前这一半完全靠人发现 ——
> 没人提醒就没人补（实证：`validate_input` 只有 OR-023 一条、加工单域的
> `processing_order_query` / `processing_order_update` **零用例**，而评测一片绿）。

**判据不靠人脑，靠脚本自动给出**（确定性检查，零 LLM，秒级）：

```bash
cd /Users/guangzhen.zk/ai native/migao
python3 scripts/xiaobu_coverage.py --check   # C 端（小布）
python3 scripts/mibao_coverage.py  --check   # B 端（米宝）
# 人读矩阵 + 薄覆盖任务书（缺哪些正向用例 / 哪些工具过薄）：
python3 scripts/xiaobu_coverage.py && python3 scripts/mibao_coverage.py
```

已接入 CI `pr-check.yml` 的 **Case Coverage Gate** job（与本地 `verify-all.sh gate`
及 quick/full 的「评测覆盖体检（B/C 两端）」**同一脚本、同一参数**，不会本地绿 CI 红）。
两端判据是同一份实现（`scripts/case_coverage.py`），矩阵可直接当**补用例任务书**：

| 判定 | 含义 | 处置 |
|---|---|---|
| 工具 **0 用例** | 该能力完全没被测（评测假绿） | ❌ 阻塞：按 §14.1 补该域用例 |
| 工具**只有拒绝/不调用式断言**（无正向用例） | 只证明了「不该给」的越权防线，**没证明**正常诉求下能力可用 | ❌ 阻塞：补一条正向用例（正常诉求下断言该工具被调用） |
| 用例挂到**错的端**（期望工具该端没有） | 用例在这端必挂（固定噪音） | ❌ 阻塞：改 `persona` 或加 OR 分支（先例 AS-003/AS-005） |
| 工具**仅 1 条用例** | 厚度不足 —— **随迭代收敛的活指标** | ⚠️ 只报告：不阻塞、不设硬阈值（verify-all.sh 既有设计意图：硬编码缺口阈值会制造返工式门禁） |

**门禁首次接入时的存量缺口怎么办（不是放宽判据）**：用 `. github/eval-coverage-baseline.yml`
的**存量豁免清单**——一条一条显式登记（`tool` / `kind` / `issue` / `reason` / `added` 缺一即红），
只豁免**已登记**的存量缺口；**任何新出现的缺口照旧阻塞**。清单是**工作清单**：

- 报告里逐条打印「工具 + 缺口 + 归属 issue + 理由」，补完用例即删条目（销账）；
- 条目指向的缺口已不存在 = **陈旧登记**，**分级**处理：**阻断型**（`uncovered`/`missing_positive`）→ 阻塞（防白名单变垃圾场）；**只报告型**（`thin*`）→ 只警告（工具变厚是好消息；若也阻塞，就会让「补了用例的那个包」意外红掉 main）；
- CI 额外校验条目引用的 issue **仍然 open**（关了 = 该销账了）；
- 单测锁住"仓库清单下全绿 + 去掉清单必红"（判据没被削弱）。

即：**存量债靠显式清单放行、增量债一律拦截** —— 既不把门禁做成摆设，也不用存量债锁死流水线。

**与其他节的分工**：发现缺口后**补用例**的动作按 §14.1（新能力）、§13.3（bug 沉淀）、
§16.1 L0 静态不变式（防复发）；本节只负责**把缺口暴露出来并拦在合并前**。
门禁性质（确定性层，可安全作 required 候选）见 §16.5。

## 15. 前端页面级改动的 UI 旅程强制验证（v1.11 新增，2026-09-09 issue #3070 复盘固化）

**背景**：知识库功能从 0 建设（P1~P9 一天堆完、前端 P8 一次性堆叠），验收报告自认
「零 UI 证据」（kb-closed-loop REPORT 复核栏原文），交付后人工一次发现 **5 个 UI 问题**
——面包屑/样式与全局不一致、分页被米宝浮动按钮（FAB）遮挡、模板套用/候选采纳后成果物
不可见。根因：验证全在「API 被调用/契约对/不崩」层，没有任何一层测「用户看着好、
点得通、看得见结果」；vitest 断言停留在函数调用级。**拦截点必须前置到开发/提交流程**。

**触发**：改动 admin-web 的页面结构/布局/交互流/样式——新页面、Tab/列表/分页/弹窗、
写操作闭环（新建/套用/采纳/删除后的结果去向）、fixed/absolute 浮动元素、padding/margin
级联与 min-h 计算（§13.2 映射表已加行）。纯文案/纯数据展示改动可豁免，但豁免需自查。

**三条必做（缺一即不算闭环）**：

### 15.1 交互测试断言「结果可见」，禁止停留在「函数被调用」

- 交互旅程测试必须断言**用户可见的结果**：点击后列表刷新（API 再次调用 **且新数据渲染**）、
  Tab 跳转、编辑弹窗可开且回填、成果物（新建/套用/采纳的条目）出现在列表；
- 禁止只断言 `api.xxx` 被调用——「按钮点了 API 通了」≠「用户看到成果物」
  （#3070 模板套用/候选采纳两个 bug 的原形态：applyTemplate/adoptCandidate 都成功，
  但列表不刷新、不跳转，用户看不到结果）；
- 范例：`frontend/admin-web/tests/unit/pages/knowledge.test.tsx` 的
  「套用后可见可编辑」「采纳后可见可编辑」两个用例（断言跳转 + 列表刷新 + 卡片可见 + 编辑弹窗回填）。
- **判据自身的三条纪律**（v1.34 / **#4226**；商家冒烟套件实证 —— 判据坏了**没有任何东西会变红**）：
  1. **不猜标识前缀**：单号 / ID 按**形态**取（如 `[A-Z]{2}-\d{8}-\d+`）并**限定在它该出现的容器内**
     （如加工单块），**禁止**写 `PO-` / `PG-` 这类**白名单前缀**正则（实测真实前缀是 `JG-` ⇒ 该判据**恒假** = 空断言）；
     也**不得**"全页按形态取号"（会命中同页别的单号）—— 两个极端都是假绿。形态正则**左右边界**要钉死
     （`ORD-…` 会被"错开一位"命中成 `RD-…`）。
  2. **豁免必须结构化**：按 `response.status() === 404` 这类**结构化事实**收集豁免，
     **禁止**"**消息文本**含 404 就豁免"（旅程**自身**抛出、文案里恰好带 404 的错误会被一并豁免 = 假绿）。
  3. **等元素，不定长 sleep**：用 `waitFor({state:'visible'})` 这类等待（超时返回 false 并参与判定），
     **禁止**"定长 sleep + 单次 `isVisible()`"（偶发不可见 ⇒ 假红淹没真回归，并让下游旅程被守卫阻断）。
  判据抽成**纯函数**以便独立验证（可执行判据级红证，不必起真栈）：`scripts/ui-smoke-merchant/criteria.mjs`
  + `criteria.test.mjs`（`node:test`，零新依赖）；静态守卫 `tests/unit_ci_workflows/test_ui_smoke_criteria_trust.py`。

### 15.2 真实浏览器旅程验证（本地起服务走查，不能只靠 vitest）

- 本地起 admin-web(:3001) + admin-api(:8080)（+ 必要时 ai-agent），登录 13800138000/万能码
  （短信网关 bypass；若 .env 未注入 OS 环境导致 bypass 失效，可从 Redis 读 `sms:code:<手机号>`
  或复用有效 JWT cookie），以「商家运营」persona 逐页走查受影响页面：
  1. **面包屑与侧边栏菜单名一致**（知识库 vs 知识库管理 同类问题）；
  2. **页面结构与全局基准对照**（容器 p-6、标题 text-xl text-neutral-900、Tab primary-600、
     控件 focus 态——对照 orders/customers 页）；
  3. **布局遮挡几何探针**：内容不足一屏 + 长列表滚到底两个场景，底部锚定元素（分页等）
     与 fixed 浮动元素（米宝 FAB）`getBoundingClientRect` 无重叠，**next/末页按钮可点击**；
  4. **写操作成果物可见性**：每个写操作（套用/采纳/新建/归档/删除）后，看列表刷新/跳转/
     弹窗回填，用户能定位到成果物；
- 产出截图/几何证据（`page.evaluate` 打点 DOM 矩形即可，无需 Playwright 全家桶）；
  剧本模板见 `docs/testing/frontend-acceptance-checklist.md` §7~§9。

### 15.3 布局/视觉问题不得仅靠 vitest 覆盖

- vitest/jsdom 对真实渲染是**结构性盲区**：`getComputedStyle` 级联结果、CSS 属性覆盖、
  fixed 定位重叠、min-h/padding 计算全部不可见；
- 实战陷阱（#3070）：`className="p-4 sm:p-6 pb-24"` 的 `padding` 简写在 Tailwind 级联中
  覆盖 `padding-bottom`（getComputedStyle 实测 24px 而非 96px）——**vitest 永远发现不了**，
  只有真实渲染 + 几何探针能暴露。已用 `px/pt/pb` 显式类修复并注释防回退；
- 涉及 fixed/absolute、padding 简写 + 单项覆盖、min-h 计算的改动 → 必须跑 §15.2 几何探针。

### 15.4 与验收协议衔接

- 本节约 = **研发侧前置拦截**（开发/提交时做）；`migao-acceptance` 验收协议 §2.3
  「B 端 UI 旅程验收」= **验收侧兜底**（验收时复核），双轨都要；
- 页面级改动按本节约跑完并留证据，验收时 UI 旅程项直接引用该证据，避免重复走查；
- 交互测试断言规范详见本技能 §15.6（E2E 选择器优先级）与
  `docs/testing/test-engineering-standards.md` §7。

### 15.5 截图视觉确认 — 自动选择多模态模型开子代理（v1.12 新增，2026-09-09 issue #3080 实证）

**背景**：主会话默认模型（如 DeepSeek-V4-Flash-0731）不声明图片输入，`read_image` 会报
`model does not declare image input`（subagent 默认继承父模型，同样失败）。但视觉验证
（高亮色/布局/弹窗按钮组/徽标）是 UI 旅程证据链的必要一环——DOM 断言给结构证据，视觉给观感证据。

**环境已具备**（settings.yaml 已配置）：
- 视觉模型：`GLM-5.3-Flash`（provider `scnet-token-plan`，声明 `input: [text, image]`，SCNet 视觉 lane）
- 路由机制：`workflow` 工具的 `agent(prompt, { provider, model })` 支持独立 LLM 目标覆盖
  （subagent/subagent_fork 工具目前不暴露 model 参数，需走 workflow）

**触发（自动，不等用户要求）**：真实浏览器旅程（§15.2）产出截图后需视觉判定；
或 read_image 报「does not declare image input」时——直接用视觉模型开子代理重试。

> ⚠️ **本条不受 #4262 约束，也勿类推**（v1.33 划界）：这里"自动"指的是**本地视觉判定子代理**，
> 走的是 `scnet-token-plan`（预付费 token plan，**不打 DeepSeek 官网 key**），且**不派发任何
> workflow** ⇒ 不产生 §13 那种"重复的真实 LLM 评测费用"。**不得**拿本条当"自动跑评测"的依据
> —— 真实 LLM 评测（`local_runner.py` / `gh workflow run`）一律按 §13 的"仅用户显式要求"执行。

**动作**：workflow 脚本内用视觉模型代理读图（一次可读多张，复用 §7~§9 剧本的 UA 判定项）：

```js
const vision = await agent(
  `你是视觉验证代理。用 read_image 读取 <截图路径>，回答：1) … 2) …（逐项问题清单）
   若 read_image 失败请如实报告，不要编造图片内容。`,
  { provider: 'scnet-token-plan', model: 'GLM-5.3-Flash', label: '视觉识别', phase: '视觉验证' }
);
```

**判据**：视觉子代理的判定输出 = UA 层证据，写入证据链（与 DOM 断言互补；
两者冲突时以 DOM 结构断言为准，视觉异常需人工复核）。视觉子代理只做读图判定，
不承担开发推理（省 SCNet token，只在需要视觉时路由）。

**实证**（issue #3080）：确认弹窗按钮组（footer 重复按钮修复）/采纳高亮行/来源筛选
三组视觉判定均由 GLM-5.3-Flash 读图完成，与 DOM 断言互证。

> ⚠️ **视觉基线的新鲜度**（v1.34 / **#4249**）：把**构建与起服务混写**进 `webServer.command`
> （`npx taro build … ; python3 -m http.server …`）+ 本地 `reuseExistingServer: true`
> ⇒ 只要端口上**已有服务在听**，Playwright 就**整条命令一步都不执行（含构建）** ⇒ 服务旧 `dist/`
> ⇒ `--update-snapshots` 报绿而基线被写成**旧画面**，**没有任何东西会变红**
> （错基线提交后**真实回归被永久放行**；与 §18.5「账本/生成物新鲜度」同族：读的是快照，当成现值用）。
> **判据**：**构建绝不写进 `webServer.command`**（构建放**配置加载期**，早于 webServer 启动）
> + `reuseExistingServer: false`（端口被占就**报错退出**，不静默复用）+ **产物新鲜度护栏**
> （判据用**内容指纹**，**不依赖 mtime**；构建失败必须**带出构建输出**，禁止 `>/dev/null 2>&1` 吞掉）。
> **已落码**：`tests/xiaobu_dist_freshness.py`（H5 侧的 `assertDistFresh` 等价物，三态 `0/1/3`；
> `dist/.build-stamp.json` 记源码 + dist 指纹，起服务前校验；本地 `ensure` / CI `check`）
> + `tests/playwright.xiaobu.config.ts`；守卫 `tests/unit_ci_workflows/test_xiaobu_h5_dist_freshness.py`。

### 15.6 E2E 选择器优先级（2026-09-14 由原独立技能收敛并入）

选择器按优先级取用（从强到弱）：

```
1. getByRole('heading'/'button'/'columnheader', { name })
2. getByTitle('...')  — 图标按钮（无文字）
3. getByLabel('...')  — 表单字段
4. getByText('...', { exact: true })
5. locator('.class').filter({ hasText })
6. getByText('...').first()  — 最后手段
```

**禁止**：裸 `getByText('短词')` 用于包含 sidebar 的页面。

## 16. 评测根本解（#3483）：分层探测 + 分档纪律 + 完成定义（v1.13 新增，2026-09-14）

**背景**：B 端评测 80 轮全量复测 + 98 修复 PR（基线 38%→94%），C 端重演同样循环。
慢的机制性原因：① 全量复测是唯一判据 ② B 端打生产（污染/部署打断）③ 归因人工化
④ 结构性缺陷靠真实 LLM 探测。根本解已分 tranche 落地（#3485 静态不变式 /
#3487 完成判定 / 后续 T3 统一 workflow + B-C 并行）。

### 16.1 分层探测（成本从低到高，能下层不上层）

| 层 | 成本 | 内容 | 拦什么 |
|---|---|---|---|
| L0 静态不变式 | 秒级 0 LLM | `tests/unit_ci_workflows/test_mibao_case_invariants.py`（B 端用例工具边界/存在性）+ `test_xiaobu_case_set.py`（C 端）+ 工具注册/确认门禁不变式（#3317 模式） | 结构性缺陷：persona 边界、拼错工具名、门禁不可达 |
| L1 契约/协议流 | 分钟级 mock LLM | `test_tool_schema_signature_contract` / `test_interaction_flow_runner` / 确认链状态机 | schema↔签名断裂、SSE 事件流契约 |
| L2 迭代档 | 1-3 min 真实 LLM | `case_ids` 收窄 + `fast` + 并发 6（xiaobu-acceptance.yml 三旋钮） | 单点行为回归（§13.2 映射表选用例） |
| L3 验证档 | ~10 min 真实 LLM | 完整 normal，独立栈 | PR 门禁级行为回归 |
| L4 结论档 | 半天/里程碑 | 全量 + 验收剧本 + 双 AI 交叉验证 + completion_verdict + 修复重放 | 交付结论 |

**铁律**：能由 L0/L1 拦截的缺陷**不允许**流到 L2+（零成本信号优先）。改代码先自问
"这是哪层能拦住"——结构性改动（工具注册/路由/确认门禁/persona 边界）必须带静态
不变式测试，禁止只靠真实 LLM 全旅程去撞。

### 16.2 三条纪律

1. **全量复测降频 90%**：全量只在里程碑基线（每 10-15 个修复）与 L4 结论档跑；
   中间修复一律 `local_runner.py case <用例ID>` 或 CI 迭代档。禁止"为验证一个小
   修复整跑全量"（B 端 80 轮里 90% 本该是 1-3 分钟的迭代档）。
2. **评测与生产解耦**：B 端评测迁移独立栈（同 C 端 docker compose + DEBUG）前，
   生产评测须防 502 部署窗口（#3282 已自愈）与数据污染（pre_clean/去重规则库，
   Round 72/79 确定性根因沉淀为规则，别等下次评测再发现）。
3. **完成定义前置**：完成 ≠ 全量 100% 绿。判定 = `completion_verdict`
   （tests/agent_eval/local_runner.py）：确定性失败（reproducible/error/
   no-retry-budget/infra）= 0 + 关键旅程（KEY_JOURNEYS_MIBAO/XIAOBU）全过 +
   已知波动（llm-noise/unstable）在 flake 台账放行。追最后 5-10% LLM 方差
   边际收益为负，禁止为凑 100% 反复重跑。

### 16.3 B/C 并行评测（#3483）

- 统一评测 workflow（persona 矩阵 mibao/xiaobu × tier），各 job 独立栈 + 数据隔离；
- 并行正确性前提：B/C 工具集边界已由 #3485 静态不变式锁定；双端用例期望须
  「每个 OR 分支至少一端可跑」（AS-003/005 形态），否则一端全量必挂；
- 真实 LLM 总并发设上限（成本治理 §3.2）：并发 3→6 只省 ~6%（#3417 实测），
  别指望并发翻倍省时间——省时间靠 case_ids 收窄 + 栈复用（#3426 GHCR 预构建镜像）。

### 16.4 结论档（下"验收通过"结论前）

按 `migao-acceptance` 技能 + acceptance-protocol（v1.3 §1.6/§1.7）执行：
completion_verdict 机器判定前置 + 双 AI 交叉验证（复核裁判默认 GLM-5.3-Flash，
scnet-token-plan，防同源偏差）——详见 migao-acceptance 技能「复核裁判模型独立性」。

### 16.5 门禁矩阵与环境三层（v1.14 新增，2026-09-14 固化）

**环境三层**（详见 `docs/testing/eval-environments.md`，wiki 索引已登记）：
① **独立栈（CI docker 标准考场）** = 评测主战场（normal/adversarial/迭代档/结论档都在这里，
数据干净、无部署窗口、可注入 deepseek-flash + 并发 6）；
② **云测试环境（SWAS）** = 当前唯一部署目标，负责冒烟 + 真实存量验证；
③ **生产** = 未部署（deploy-prod 规划中）——上线门禁已预定义（发布前独立栈全量 +
completion_verdict ✅ + 双裁判无未裁定分歧；运行期只 smoke/抽样/台账）。

**门禁矩阵（自动化，2026-09-14 起；★ = required 硬门禁，其余为信息性）**：

| 触发 | 自动动作 | 性质 | 落点 |
|---|---|---|---|
| PR（任意改动） | 三模块单测 / QA Growth Gate / ci workflow helper / 静态不变式 | ★ **required（硬门禁）** | pr-check |
| PR 改 AI 行为文件 | ~~C 端 smoke（persona=xiaobu）+ B 端 smoke（pr-check，打云测试环境）~~ **该层已移除**（issue #3653，2026-09-15；`pr-check.yml` 内有登记）—— PR 层只保留下一行的定向映射用例 | —（已移除） | #3504 → #3653 |
| PR 改 AI 行为文件 | **零 LLM 的映射信号**（diff → §13.2 用例集 + 打印"要跑就派发单一入口"的命令）——⚠️ **PR 层真实 LLM 已停跑**（2026-09-17 用户裁定 2′/4′，承载 issue #4034）：原「映射用例迭代档」（独立栈跑 + PR 评论 + 规则命中失败自动开 issue）的**评测 job 已整体删除**，不是加 `if` 关掉 | **不产生任何评测结论**（连评测都不跑）；代价（PR 阶段无 LLM 行为信号）用户已知并接受 | #3502 / #3653 → #4034 |
| 合并 → 部署到 SWAS 成功 | **部署后全量回归**（独立栈 mibao+xiaobu，matrix 并行）→ 失败去重建 issue | 部署后拦截 | #3503 |
| 每周六 | adversarial 档（只追踪不阻塞） | 信息性 | #3367 |
| 里程碑/下结论 | 结论档（全量 + 验收剧本 + 双裁判 + completion_verdict） | **结论前置（必过）** | §16.4 |

**⚠️ 最容易误读的一条**：分支保护的 required_status_checks 只有确定性层那 9 项
（`.env`/三模块单测/QA Gate/ci-helper/gitleaks/Danger Scan）——**LLM 行为层不进 required
是有意设计**（真实 LLM 方差会卡死合并流水线；job 名还随 persona 参数化）。
⇒ **映射信号红 ≠ 不能合并**（PR 上只剩零 LLM 的映射，没有"红"可言）；
硬拦截由确定性层（required）+ 定期/手动全量（`post-deploy-eval`，**每周一档 + 手动档**）承担。
禁止把 LLM 档改成 required（历史决策，勿翻案）。

**📌 决策记录（2026-09-14 用户确认 → 2026-09-17 裁定 2′/4′ 覆盖）**：**行为映射门禁
（agent-behavior-eval）不纳入 required**（理由：方差 + persona 参数化 check 名）。
⚠️ 该门禁的**评测部分已停跑**（issue #4034）：PR 上只剩零 LLM 的映射信号；拦截交给确定性层。
⇒ 阅后动作变了：**PR 上不再有"规则命中强信号"可看**；取而代之的是裁定 4′ 要求的
**「LLM 发现 → 确定性下沉」**（红例必须落成 ≥1 条确定性断言，台账 + 机械检查见
`docs/testing/llm-finding-sinking.md`；`python3 .github/llm_sink_check.py --issue N`）。
**未下沉的红例必须显式登记**（`status: unsunk` + reason + follow_up），不得静默放行。

**队友约定**：这些门禁是**自动**的，不要重复人工跑同一档；PR 红了先看门禁产物
（映射信号评论 / summary json / flake 台账 artifact），再决定重跑或修复。
波动台账现上传 artifact（`agent-eval-flake-ledger*`，30 天）——高波动用例治理
（§14.3 双周回顾）从这里取数，不再翻 run 日志。

### 16.6 评测派发与数字留痕（v1.18 新增，2026-09-14 实证固化；v1.20 修正第 1 条；v1.22 新增第 5 条；v1.26 新增第 6 条；v1.27 补强第 2 条）

六条都是本会话**踩过**的（每条都有 run 级证据），照做能省一整轮 90min 评测：

1. **手动派发的现状真值（v1.20 修正，#3709 修复后）**：`workflow_dispatch` **默认免抑制**。
   `eval_supersede.sh` 按 `EVENT_NAME=workflow_dispatch` ⇒ `FORCE_EVAL=true`（语义 = 人显式要求
   "我就要这一条"，回滚复验/补跑）；**要恢复「被取代即抑制」必须显式传 `-f force_eval=false`**
   （逃生口保留，省成本路径不消失）。**自动门禁**（`schedule` = `post-deploy-eval` **每周一**全量；
   `workflow_run` 部署后触发已在 #3925 移除、**不存在**）语义**不变** —— 它们没有 inputs，不受该默认值影响。
   ⚠️ #4262（2026-09-18）后**全仓自动真实 LLM 触发只剩这一条**（原 3 条：每 3 天 normal +
   两条每周 adversarial，后两条已改仅手动）。
   - ⚠️ **被抑制时要看得见**：run 上会打 `::warning::` 标注（两条 persona 腿 + report job 共三条），
     step summary 抬头是「本 run 未评测（不构成结论）」。**据此不得再把「绿」读成「评测通过」**
     （抑制**依旧不是 failure**：不刷红、不建 issue —— 要的是可见，不是变红）。
     **引用任何 run 前先核「步骤级 / 产物级 / 新鲜度」三条**（migao-acceptance v1.3）。
   - ⚠️ **历史坑（#3709，2026-09-14 实证）**：修复前 dispatch 与部署门禁共用 `MODE=deploy` 判据
     ⇒ 派发与执行之间只要 main 动过（本仓库合并极频繁、评测常排队）就被**静默抑制**：
     `tier=adversarial -f case_ids=DF-011` 的 run 整体 `completed/success`，而**每个评测步骤
     都是 `skipped`、artifact 为 0**（一条用例都没跑）。v1.18 据此写下的「手动派发**必须**带
     `-f force_eval=true`」在修复后**已成假真值** —— 照抄它反而会让人以为"不传就会空跑"。
   - ⚠️ workflow 注释一度写着「workflow_dispatch … **永不抑制**」（与实现不符 → 主会话正是读了
     它才漏传逃生口）。**注释漂移 = 假绿来源**（migao-acceptance v1.4）：**引用注释作为判断依据前
     先核实现**，改行为必须同步改注释。
   - ✅ 判据**可本地复跑**（不必推上去赌一轮 CI）：`bash .github/scripts/eval_supersede.sh`，
     用 `EVENT_NAME` / `FORCE_EVAL_INPUT` / `MAIN_SHA` 覆盖即可演练「dispatch 免抑制 /
     显式 `force_eval=false` 抑制 / 自动门禁不变」三种结果 —— 单测
     `tests/unit_ci_workflows/test_post_deploy_eval_supersede.py` 已把口径钉死。

2. **`case_ids` 是全矩阵共享的，不是按 persona 过滤的。** 只传**一端专属**用例 ID 会让
   **另一条腿立即红**（runner 有 `--case-ids 里有无法解析的用例 ID（禁止静默少跑）` 守卫，
   `tests/agent_eval/local_runner.py` 里的 `--case-ids 里有无法解析的用例 ID（禁止静默少跑）` 守卫
   （**按该守卫文本检索**；`@c5f07f29` 位于 `:5749` —— **行号不入长期文档的判据，只作 sha 限定的旁证**）。
   ⇒ 定向派发**只能传两端都适用的 ID**；
   要单端验证就在该端派发，**不要**指望另一端"自动跳过"。
   （实测：传 6 条 B 端 ID → xiaobu 腿 3 分钟内红，白烧一条腿。）
   - **配对救不了（v1.27 补强，#3822 实证）**：守卫是**逐 ID 校验**的 —— 请求里**只要有任何一个 ID
     在本 persona 的用例集中不存在**，该腿即按 `禁止静默少跑` fail（`tests/agent_eval/local_runner.py`：
     `❌ --case-ids 里有无法解析的用例 ID: …（禁止静默少跑）`，**按该守卫文本检索**）。
     实测 run `34907040543`（`-f case_ids=OR-013,CH-003 -f purpose=debug`）：`OR-013` 只在 mibao 腿
     ⇒ xiaobu 腿 `exit 1`；**再加一条两端都有的 `CH-003` 并不豁免**。
     ⇒ 对**单端专属**用例（B 端建品 / 物流类，如 `OR-013` / `PR-014` / `PR-016`），**不存在**一个
     「既含它、又让两条腿都干净」的 `case_ids` ⇒ **端点证据优先靠「合并后一次全库跑」**（§17.4）。
   - 若确需窄跑：**接受并在 PR / 评论里显式标注**另一腿的红属「**收窄副作用、非回归**」，
     并去被**自动评论**的 issue 上澄清（附 `purpose=debug` 与非判定用途说明）—— 该窄跑会向既有 issue
     追加一条误导性"回归"评论（本例落进 #3534）。
   - 关联工具缺陷 **#3822**：要求支持 persona 维度收窄，或让 `_missing` 只对「**两端都不存在**」fail-closed。

3. **`continue-on-error` 让"步骤显示 success"≠"步骤成功"。** `post-deploy-eval.yml` 对
   `Run <persona>` 步骤设了 `continue-on-error: true`（当前 main @ `:505`；
   **行号会漂移，按该行注释「continue-on-error 的理由（不是"为了好看"）」检索**）（有意设计：
   红信号统一由 `判定（completion_verdict）`
   步骤产生，避免真实 LLM 方差卡死流水线）。⇒ **读 run 结论只看 `判定` 步骤 + artifact**，
   别拿 `Run` 步骤的颜色当结论。（实测：xiaobu 腿 `Run` 显示 `success`，实际 exit code 1。）

4. **每个计数必须锚定 SHA —— 禁止"旧基线配新结果"。** 实测：两个包分别报告
   `604→612`（#3712）与 `604→618`（#3713），**各自对自己当时的 base 都成立**；
   但当前 main（`4c1f47ae`）实测是 **626** = 604 **+8**(#3712) **+14**(#3713)。
   写数字时必须写 **`基线 @<sha> = N → 本 PR = M`**。否则会造出**幽灵 delta**，
   下一个人拿它判"测试数漂移 / 覆盖退化"就会误判（本会话已发生一次）。
   同理：**报"某 run 通过"必须带 run id + SHA**；报"某 issue 已关闭"必须核**病灶是否仍在**
   （关单 ≠ 病灶消除，见 migao-acceptance v1.4）。

5. **重放要说明「是否复现了缺陷的前置条件」（v1.22 新增，PR #3746 实证）。** 用 `case_ids` 收窄时，
   若缺陷由**另一条用例**制造（如「商品级改价 vs SKU 级取价」的分叉要先跑改价用例 `PR-010`），
   漏掉它就会得到一次**无判别力的绿** —— run 真跑了、也真绿了，但**被修复的路径未被行使**
   （实测：`case_ids=OR-014,AS-004` 排除 PR-010 ⇒ R1 读到种子值 `price=168.0`，而红时读到 `198.0`）。
   判据：给出**前置条件的观测值**（本例应读到 `price=198.0` 才说明分叉态存在）；
   **未复现时须如实标注**「该次绿不构成判别性验证」，并以**确定性层证据**兜底
   （本例 `ProductServiceTest#updateProduct_BasePriceSyncsToSkus` —— **按测试方法名检索**，`@c5f07f29` 位于 `:559`；
   改前 `Wanted but not invoked` → 改后 80 tests 绿，读数为 PR #3746 更正评论记录）。
   形态与判据详见 `migao-acceptance` v1.7「假绿形态：重放未复现缺陷的前置条件」。

6. **派发前先查槽位 —— 占用就别派**（v1.26 入册，口径由 #3761/#3770 **落码**）。
   跑 `.github/scripts/eval_slot_status.sh`（零成本只读查询，**派发前必跑**）；**退出码即判据**：
   `0` = 槽位空闲 ⇒ 可派 / **`2` = 槽位被占用 ⇒ 不要派发**（原文形如
   `🚫 槽位被占用（N 个 run 在跑/排队）—— **不要派发**`）/ `3` = 无法判定（gh 不可用/未登录）
   ⇒ **不谎报「空闲」**，由派发方决定。
   - **理由**：全局评测槽位（`eval-stack-global*`）是**稀缺资源**，并发派发互相饿死/互杀 ——
     实测某窗口 **10 个 run 被 `cancelled`**：7 个死在 pending（0 建栈成本）、
     2 个已进 `Start local stack` ~1.6min 才被杀（**栈付过费、零结论**）、
     3 个还被记成「部署后回归失败」的**假评论**（落进 issue #3534）。
   - 建栈层的 `concurrency` **已经是** `cancel-in-progress: false`，且 GitHub 不会用新 run 取消
     **running** 的 run ⇒ 取消动作**来自派发侧**；脚本注释里的原话是「先查槽位，别堆队列」。
     **改 concurrency 治不了它，查槽位才治得了**（#3587 只解决了"排队不互杀建栈"这一半）。
   - 与「**不要为同一件事重复派发**」（下节派发前）是**同一族**：那条给纪律，本条给**可执行判据**；
     派发方（人或 agent）判断"要不要派"之前，先跑这条命令，再看 §16.7 的分档表。

### 16.7 评测流程：该跑什么、不该跑什么（v1.24 新增，2026-09-14 用户裁定固化；v1.25 增「禁空跑」；v1.26 补槽位守卫与 `cancelled` 口径；v1.27 补「读结论」两条）

**先问「这次要回答什么问题」，再选档** —— 评测是真实 LLM 成本，跑错档 = 白烧 token + 更慢的反馈闭环。

| 要回答的问题 | 用什么 | **不要**用什么 |
|---|---|---|
| 这条改动**影响行为吗**？（PR 阶段） | **PR 上的映射信号**（`agent-behavior-eval.yml` 的 `map` job：diff → §13.2 用例集 + 打印派发命令）——⚠️ **零 LLM**：它只告诉你"波及哪些用例"，**不产生评测结论**。要真结论 ⇒ 手动派发 `post-deploy-eval`（`case_ids` + `purpose=debug`，**非判定用途**） | 不为单条改动派**全量**（全量属部署后 / 批次轮）；**不要在 PR 上期待 LLM 结论**（裁定 2′/4′：PR 层真实 LLM 已停跑，#4034） |
| **这几条 case 修好了吗**？ | **合并后的一次全量档**（`tier=normal`，不带 `case_ids`，跑全库 ⇒ 天然覆盖「缺陷由另一条用例制造」的前置条件，§17.4 ③） | 不用窄重放当结论（除非全量覆盖不到该用例）；用窄重放**必须回答**「本次运行复现了缺陷的前置条件吗」（`migao-acceptance` v1.7） |
| **能不能放行**（里程碑）？ | **全量档 + `completion_verdict` + 独立盲审**（§16.4 结论档） | 不拿单次窄重放的绿当结论；不拿**被抑制 / cancelled / 空跑**的 run 当结论 |

**派发前**：

- **先查槽位**：跑 `.github/scripts/eval_slot_status.sh`；**被占用（`exit 2`）⇒ 不要派发**、
  无法判定（`exit 3`）⇒ 先确认 gh 可用（**不谎报空闲**）。判据与理由见 §16.6 ⑥。
- **确认没有同主题评测在跑**，需要评测先报主会话统一排期 —— **这是纪律，不是硬门禁**：
  `post-deploy-eval.yml` 有意不加 `cancel-in-progress`（其注释「为什么不加 `concurrency: cancel-in-progress`…」
  `@c5f07f29` 位于 `:139-144`），机制**不替你排队**，重复派发只会互相顶掉。
- 手动派发按 #3709 修复后的默认（`workflow_dispatch` **默认免抑制**）；要抑制才显式 `-f force_eval=false`（§16.6 ①）。
- **不要为同一件事重复派发**：同一 SHA 已有在跑 / 已完成的同档 run 时，先读它（核「步骤级 / 产物级 / 新鲜度」）；
  判定用途还可先跑 `.github/scripts/eval_dispatch_guard.sh` 查**结论复用 ledger**（命中 ⇒ 直接引用，别再烧 LLM，见「禁空跑」②）。

**派发后**：

- ⚠️ **不要在建栈中途取消**：`Start local stack`（此时 `Set up Buildx` 已 `success`）被取消 =
  **最贵的一步已经付过费、却拿到零结论**，还得从头再跑一遍。实证 run `34855662092`：
  `Set up Buildx` = `success` → `Start local stack` = **`cancelled`** →
  `Seed 评测业务数据` / `Run mibao normal` / `汇总打印` / `Upload 汇总 + 波动台账` **全 `skipped`**。
  ⇒ **要么别派，要么让它跑完**。（该 run 当时连 `判定（completion_verdict）` 都被记成 `failure` ——
  一条**没有评测内容**的失败；这一半已由 #3770 修正，见下条。取消本身照样是纯浪费。）
- **引用任何 run 前核三条**（`migao-acceptance` v1.3 空跑）：**步骤级**（真正干活的步 + `判定（completion_verdict）`
  非 `skipped`）/ **产物级**（artifact 非 0 且能读出 verdict）/ **新鲜度**（SHA 是本次目标）。
  （**取消 / 抑制维度**另有三条，见下一行。）
- ✅ **`cancelled` / 被抑制的 run 都不是结果，但都不再被记成失败**（v1.26 更新，#3770 **已落码**）：
  判定步骤补 `!cancelled()`、建 issue 条件去掉 `|| cancelled`；新增「**被取消记录 / 被取消留档**」步骤
  打 `::warning::` + step summary **抬头**写死「**本 run 被取消（未评测，不构成结论）**」，
  并记 `📊 telemetry: ran=false reason=cancelled（未评测，不是通过、也不是失败）`
  （抑制侧的抬头是「本 run 未评测（#3709：被抑制，不构成结论）」，§16.6 ①）。
  ⇒ **引用一个 run 作为结论前必须核三条**：**结论已出**（有 verdict）/ **未被取消** / **未被抑制** ——
  任一不成立 ⇒ **没有 verdict**，其 artifact **不得当证据**。
  ⚠️ **不判 failure ≠ 取消无害**：这是**可见性**修复（要的是「没跑」长得像「没跑」），
  不是"取消可以接受"—— 建到一半被杀照样白烧（上一行），故派发前仍要查槽位（§16.6 ⑥）。

**读结论时**：**分类与放行分开** —— 放行只适用「重试通过」（`llm-noise`），`unstable` 默认阻塞
（`migao-acceptance` v1.6）；重放须说明是否复现了缺陷的前置条件（v1.7）；空跑 / cancelled / 被抑制一律不算结论。

**口径收紧后怎么读「变红」**（v1.27 新增）：任何**放行 / 分类口径收紧**（例：「跨 run 同指纹复发
⇒ 不得按波动放行」）**落地后，下一次全库跑的失败数会上升** —— 这是**收紧的设计效果**，不是当批改动的回归。
⇒ 读结论必须把「**本次新引入**」与「**原本被放行的系统性缺口现形**」**分开标注**；
**不得**把后者当**回归归因到当批改动**。实操：**收紧前**先按真实历史复算「会有多少条放行被改判」
并**留档（锚定 SHA + 条数）**，收紧后拿它当**对照基线**
（先例读数见 `migao-acceptance` v1.6：`unstable` 移出放行档 ⇒ 离线重放 `29 → 21`，
2 处 run×persona 翻转都是**假绿被堵上**、不是真波动被刷红）。

**证据等级不得越级**（v1.27 新增，关联 #3823）：需要「**参数值相等**」级结论时，**先确认 runner 是否
落盘该工具的 args**；**不得**用存在性断言（`required_args` = 字段非空）**顶替**值级结论，
**也不得**用 `score` 顶替。现行已知缺口：runner **不落盘 tool args**（`processing_item_query` 的
`applicable_category_id` 读不出，轨迹行只打印 data 摘要）⇒ 见 **#3823**，需要值级证据时**先看该单是否已修**。
等级分工（`must_succeed` 结果级 / 值级通道 值相等 / `required_args` 存在性；`data_checks` 是自然语言检查、
不作机器证据）见 `migao-acceptance`「证据层假绿」与 `docs/testing/acceptance-protocol.md`。

**成本可见**：每次 run 记录 **时长 / 用例数 / 是否重试**（能拿到就加 token 用量），否则「废钱」不可管理
（**本节只定口径**；采集实现由另行派发的包承担，不在此重复实现）。

**合并后跑一次统一验证**（§17.4），取代「N 个包各跑一遍」。

#### 禁空跑 / 验证的边际信息量（v1.25 新增，2026-09-14 用户裁定；v1.26 起 A/B/C 三条**已落码**）

**口径**：**不跑没有信息量的验证，也绝不把「没跑」记成「通过」。**
（它的**前置**是槽位守卫：槽位被占用时连"要不要跑"都不用问 —— 先别派，见 §16.6 ⑥。）

1. **过筛（跑之前先问）**：任何验证 / 评测动作先问 —— **「两种可能的结果，会不会导致不同的下一步动作？」**
   不会 ⇒ **不跑**，并把它记为「**未跑**」，**绝不记为通过**。
2. **同一判定点只跑一次**（A 统一入口 + B 结论复用；v1.26 起**已落码**，#3769）：
   判定用途的评测只走**分层全库跑**（`tier=normal`，一次覆盖两个 persona）；
   ⚠️ **「全库」= 该档的全库，不等于「覆盖全部用例」**：`local_runner` 按 **difficulty** 选档、
   三档**互斥**，故 `tier=normal` **只跑 NORMAL 档**、**不含 SMOKE / ADVERSARIAL**
   （runner 侧原文「每日回归：normal tier（smoke 由 PR gate 跑，adversarial 由每周任务跑）」；档位边界
   亦写在 `post-deploy-eval.yml` 的 `tier` 输入描述里）。⇒ **判定用途的 normal 跑只代表 NORMAL 档的结论**，
   别据以声称覆盖 smoke/adversarial（要全档结论就分别派档，或**显式声明覆盖边界**）。
   `case_ids` 只用于**定点复现 / 调试**，
   且必须显式标注「**非判定用途**」。**落到代码里的判据 = `.github/scripts/eval_dispatch_guard.sh`**：
   - **A**：`CASE_IDS` 非空 且 `PURPOSE=determination` ⇒ **`exit 1` 拒绝派发**（workflow 内
     `MODE=ci` 同样硬拦）—— 收窄跑的 summary `total` 只反映那几条，**拿它下判定结论就是假绿**；
   - **B**：结论按 **`(SHA, tier, case_ids=空, 用例库 tree hash, 跑批策略版本)`**（即 summary 的
     `run_key`）**复用** —— 同 SHA 已有两个 persona 都 `completion.ok=true` 的**全库** run ⇒
     **不跑**（`exit 2`），直接引用其 run id/时间/结论。键**缺一不可**：旧 run 无 `run_key`、
     artifact 缺失、策略版本或用例库指纹不可得 ⇒ **不命中，宁可多跑**（复用过期结论 = 假绿）。
     `用例数 ≠ 结论`：收窄跑省的是钱，不是判定。
3. **跑之前拦，别跑完看日志**（C 空跑守卫；v1.26 起**已落码**，#3769）：**评测相关路径**
   （runner / 用例库 / ai-agent 行为源 / 评测 workflow）的变更集为空 ⇒ **不派发**，打印
   **`⏭️ 评测相关代码无变更 ⇒ 未跑（引用 <run_id>）`** —— **「没跑」必须长得像「没跑」**
   （同族示例：`verify-all.sh` 的「⚠️ 无变更或无法对比 origin/main，跳过」；`agent-behavior-eval.yml`
   的 `⏭️` 图标语义）。**别让"跳过"在日志里长得像"通过"**。
   命中复用（B）时同样打印 `⏭️ …不重复跑` 并给出旧 run id —— 一律**不复用"绿"的字样**。

> 反面对照（假红）：测试自己**重建产物路径**导致「本地绿 / CI 红」—— 见 `migao-acceptance`
> v1.8「假红形态：测试自行重建被测系统的产物路径」。两者都是「**验证结果的可信度**」问题：
> 一个防"空跑被记成通过"，一个防"环境差异被记成失败"。

#### 结论的构成与读法（v1.29 新增，2026-09-15 实证固化）

**判据（读 summary 的 `completion` 字段，一行即可自查）**：`ok = 六类阻塞桶全空`，**不是**"还有没有
产品缺陷"这一个问题。逐桶判据与实测取值（判定跑 `34908262839` 的两条腿，读 artifact
`eval-summary-mibao.json` / `eval-summary-xiaobu.json` 的 `completion`；改动前后都可能漂 ⇒ **数字用
命令自证，别照抄本节**）：

| 桶 | 判据（一句话） | 该 run 实测 |
|---|---|---|
| `deterministic_failures` | `score < 1` **且**非关键旅程 **且**分类 ∉ 放行集 | mibao `PG-013`；xiaobu `OR-026` |
| `journey_failures` | 命中关键旅程用例而失败（**连 `llm-noise` 也不放行**） | mibao `CU-003` |
| `systemic_recurrence` | 跨 run **首跑指纹**复发（fail-closed，**收紧后仍压 `ok`**） | mibao `OR-014` / `PG-016` / `PP-001` / `PR-017` |
| `restore_failures` | 前置未复位（`restore` 含 `PRECONDITION_NOT_RESTORED`）—— 污染的是**共享资源** | `[]` |
| `harness_incompatible_failures` | 夹具/用例形状不兼容 —— 判红照旧阻塞，但**归因单列**、不进"产品确定性回归"清单 | `[]` |
| `case_asset_failures` | `precondition_not_applied` 族（`pre_clean` 未应用 / 运行期前置漂移）—— 该用例本次红/绿**无判别力**（runner 原文：**不可归因于 agent 行为**），但**仍阻塞**，且**不再进**上面前三桶 | `[]` |

- **放行集当前只有 `llm-noise`**（= 首败 + 新 session 重试**通过**；`unstable` 已不再放行，
  `migao-acceptance` v1.6 与 `_COMPLETION_RELEASED_CLASSES` 同源）。放行 ≠ 通过：它进
  `flake_released` 台账，不进任一阻塞桶。
- ⇒ **最终结论必须按桶分解写**，**不得**笼统说「还有产品缺陷」或「全绿了」。
  实测：`34908262839` 判定 `ok=false`，其构成为 **2 条用例资产缺陷**（`PG-013` 双重假红 / `CU-003`
  真值三处错误，见 **#3833** / **#3832**）+ **4 条原被放行的系统性缺口现形**；
  **两类都不该记成"当批改动引入的产品 bug"**。
- ⚠️ **别把它简化成"三类"**：真值（代码）是**六类**（上表全列）。只列 `deterministic / journey /
  systemic` 会把 `restore_failures` / `harness_incompatible_failures` / `case_asset_failures`
  三条**真阻塞**漏在视野外。
- **阻塞条目要分两组呈现**（v1.35 / **#4207**）：`must_fix_failures`（阻塞 ∧ `score < 1`）/
  `blocked_but_passed`（阻塞 ∧ `score ≥ 1` —— **在 `passed` 里、不在失败清单里，却阻塞 `ok`**）；
  `reason` 与 summary JSON 的 `completion` **都带这两键**。
  ⇒ 🔴 **按「未通过清单」数条数会系统性少算**（实证 xiaobu **少算 2 条**）——
  读 `ok=false` 时必须把两组**分别列出**，只列失败清单 = 把"已通过但仍阻塞"的那组**静默丢掉**。
  判据源 `tests/agent_eval/local_runner.py` 的 `completion_verdict`（`reason` / `completion` 两处键形同源）。
- **"前置不成立"不是 agent 的红**（v1.34 / **#4245**）：`case_asset_failures` 桶治的是**归因错人** ——
  该族原被折进 `deterministic_failures`（"agent/产品的确定性回归"，实测 `PR-016`）或
  `systemic_recurrence`（"跨 run 复发"，实测 `PR-008`）⇒ 读的人去查 agent 行为。
  判据源 `tests/agent_eval/local_runner.py` 的 `completion_verdict` / `precondition_not_applied_fact`
  （**复位族** `PRECONDITION_NOT_RESTORED` **不在**本族，它已有 `restore_failures`）；
  判据与放行政策**同源**写在 `migao-acceptance`「结论档机器判定」节，此处不重复表述。
- **收紧判据后失败数上升 = 设计效果**（同节「口径收紧后怎么读变红」）：拿**同一批用例**在
  **收紧前**的判定跑当对照基线（锚定 SHA + 逐桶条数），把「本次新引入」与「原本被放行的缺口现形」
  **分开标注**，**不得**归因当批改动 —— 这条纪律**就是**上一条实测的产物。
- **每条失败必须有归因**（引 `R轮次 / 原文片段`）；**无归因的红 ≠ 产品缺陷，也 ≠ 可放行** ——
  它是**待归因项**，卡在"未归因"状态（同族：`migao-acceptance`「判定必须引证据」）。
- **证据等级不得越级**（v1.27 已有，见本节上文）—— 补一句判据：**值级结论不可机器闭合时
  只能给存在性级**（`#3823`：runner 不落盘 tool args ⇒「参数值相等」读不出），
  **不得**用 `score`（汇总分）顶替值级证据。

#### 成本与验证顺序纪律（v1.29 新增，2026-09-15 实证固化）

**顺序：先窄跑、后全量；窄跑只走单腿入口；全量只在"产品因已修"或"到判定点"时跑。**

- **窄跑必须用单腿入口**（`xiaobu-acceptance.yml` 的 `persona` 输入，选择 `mibao` / `xiaobu`：
  它的 job 名、`PERSONA` 环境变量、种子脚本都按该输入取值）——
  因为 `case_ids` 是**矩阵全局 + 逐 ID 校验**：传单端 ID 会让另一条腿 `禁止静默少跑` **必然判红**
  （**#3822**，run `34907040543`；`case_ids` 条目见 §16.6 ② 与 §16.7 派发前）。
- **评测槽位会串行**：两条窄跑会排队（时间翻倍）—— 这是**设计**（全局槽位稀缺 + 建栈成本），
  不是故障 ⇒ **不要**为了"快"并发派发（§16.6 ⑥ / §17.4）。
- **产品因未修时不要跑全量判定跑**：同一批红提供不了新信息，纯烧 token。
  实证：先归因出 `PG-016` / `OR-014` 的产品因**尚未修**，此时再跑全量，读到的还是同一批红
  （这正是 `34908262839` 的 4 条 `systemic_recurrence` 的处境）⇒ **先修因，再跑判定**。
- **不许为让套件变绿而调阈值**（**#3840**）：活环境 P95@10并发 **2.5~3.1s**（阈 2.0s）、
  商品列表 **1032ms**（阈 1000ms），**3 次跑一致**（`34909768102` / `34911052034`）⇒ 不是波动、
  也不是部署窗口。要改阈值必须给出「**该阈值面向哪类环境**」的依据（生产规格？单机 SWAS？），
  并在 PR 里**声明不是为变绿而放宽**（该 issue 自身的第 2 条要求即此）。

#### 引用纪律（v1.24 新增，两条均有本轮实证）

- **长期文档不给「活跃编辑文件」的裸行号** —— 实测：`local_runner.py` 的 3 个引用在 **4 分钟内**失效
  （`@541bacbe` 为 `:4939` / `:4959` / `:5551` → `@c5f07f29` 变成 `:5088` / `:5108` / `:5749`，
  因为该文件正被别的包编辑）。写法：**符号 / 文本锚点优先**（函数名、守卫串、注释串、测试方法名），
  行号只在必要时以 **`@<sha>` 限定**形式给出（例：`_needs_serial_lane`（`@c5f07f29` 位于 `:5088`））。
  ⚠️ **「版本沿革」节是历史记录**：其中的行号为**当时值**，不要照抄；**已过期的沿革行号就地替换为可检索文本**（v1.24 已把 `- v1.18` 条目里的 runner 守卫裸行号换成「按 `禁止静默少跑` 守卫文本检索」）。
- **写法统一**：行号一律写成「**第 N 行**」（需要时可带 `@<sha>`），**不要**写成 `path:NNN` ——
  后者既会被后续的**模式扫描**误判成「残留引用」，也会被读者误当**现值**照抄。
- **引用必须对 `origin/main` 读**：不要在**落后的本地工作副本**里 grep 行号 / 判存在性 ——
  本轮一批错行号**全部**来自落后 main **87 个提交**、且脏的主工作区（`aa64bb98`）：
  `OrderService.java` 的取价引用（旧副本第 1030 / 1432-1437 行）、`local_runner.py` 的守卫
  （旧副本第 3745-3771 行）、`product.yml` 的用例定义（旧副本第 314 行）、`post-deploy-eval.yml`
  的 concurrency 注释（旧副本第 107-112 行）都是**旧副本的行号**；存在性同理（`scripts/mibao_coverage.py`
  在旧副本里不存在、在 `origin/main` 上存在）。
  **核法**：`git show origin/main:<path> | sed -n '<n>p'`（并断言该行含预期符号）。

## 17. 并行修复原则（v1.15 新增，2026-09-14 固化）——**发现即并行，合并串行**

> **背景**：评测/验收复盘一次性暴露 10+ 个问题（种子缺口 / 用例资产 / 基建缺陷 / 权限缺口 /
> 真 bug）时，**逐个修**会把墙钟串行化、上下文膨胀，且每个修复都要等一整轮 CI。
> 正确做法：**先冻结问题清单 → 拆成互不冲突的任务包 → 并行派发 → 主会话只做集成与验证**。

### 17.1 编排四步（缺一不可）

1. **冻结清单**：把所有已知问题一次性列全（来源：评测日志/验收报告/issue），
   **每条写清：证据 + 归因层级 + 验收判据**（禁止"再排查一下"式模糊条目）；
2. **切任务包（按文件所有权切，不按问题类型切）**：
   - **同一文件的改动必须放同一个包**（否则并行必冲突）；
   - 生成物（`tests/agent_eval/eval_cases.py`、`docs/testing/mibao-verification-cases.md`）
     由改 `cases/*.yml` 的包独占；两个包都改 case → 合并时**后合并者先 `sync-main.sh` 再重渲染**；
   - 每个包一个 **issue + 分支 + 独立 worktree**（§2.3 多会话规范：零共享写路径）；
3. **并行派发**：每包一个后台 subagent（或独立会话），prompt 自带：工作区绝对路径、
   允许改的文件白名单、证据引用、验收命令、`Closes #<issue>` 的 PR 要求；
   **主会话不参与实现**，只做集成（review/合并/验证）；
4. **合并串行、验证收口**：N 个 PR 合并有先后；每个合并后跑一次集成验证
   （受影响档位：静态不变式 → 迭代档 → 全量），**并行的是修复，不是验证**。

### 17.2 并行度上限（并行 ≠ 无限）

- **CI/runner 竞争是真实成本**：多 PR 同时触发独立栈评测会排队（stack build 互抢，
  即 #3417「并发建栈更慢」的跨 PR 形态）→ 建议**同时 ≤3 条评测型流水线**，
  纯文档/用例资产包不受限；
- **真实 LLM 成本 ×N**：每个评测型包都会烧 token，派发前先问"这条必须真跑吗"；
- 成本/分钟数治理见 §16.2 与 #3507。

### 17.3 反模式（禁止）

| 反模式 | 代价 |
|---|---|
| 一个会话里 A→B→C 逐个修 | 墙钟串行（每个修复都等一轮 CI）；上下文膨胀导致后期质量下降 |
| 多个 worker 改同一个文件 | 合并冲突 + 生成物 diverged（CI 新鲜度校验必红，多跑一整轮） |
| 先修完再想验收判据 | "修完了但证不出"；验收判据必须与问题同时冻结 |
| 主会话边实现边派发 | 主会话被实现占满，失去集成/仲裁能力（本会话实测教训） |
| 并行派发后不盯首轮 CI（§11.1） | 红 CI 空窗，并行优势被空窗吃掉 |
| **PR 绿后再往分支追加 commit**（v1.15 新增，本会话两次实证） | native auto-merge **秒级合并** → 追加的 commit **不进 main 且无 PR 承接**（本地有、main 无）→ 需 cherry-pick 补 PR。**规避**：改动全部完成后再推+开 PR；合并后核对用 `git show origin/main:<file>`（不是看分支）；发现搁浅立即 cherry-pick 到新分支补 PR |
| **把「分支 commit 不在 main」误读成「变更未合入」**（v1.16 新增，本会话实证） | squash 合并**不保留分支 commit**（GitHub 在 main 上生成新提交）⇒ `git merge-base --is-ancestor <分支commit> origin/main` 恒为假、`git log origin/main` 也搜不到该 SHA —— **但内容可能早已合入**。实证：有 worker 据「修复 commit `255353fb` 不在 main」断定某修复未落地并把它列为待办上报；实际该修复早随 PR #3565（squash `38135c73`）合入，`git show origin/main:<file>` 能看到 5 处 `recipientId`。**规避**：判断「是否已合入」只有**一个**判据 —— `git show origin/main:<file>` **看内容**；**永远不要**用 commit 是否可达来判断。同理，`git branch -r --contains <sha>` 只说明"某分支含该 commit"，**不说明它进了 main** |
| **改了单一事实源后没回头同步「在飞」的引用副本**（v1.20 新增，2026-09-15 实证） | 按旧稿写出的 brief 会**忠实产出旧口径**，副本合入后与源**直接矛盾**——读者拿到两个打架的"事实源"，比不写更糟；且 brief 里的笔误会被**逐字复制**进产物（实证：把两个 **issue** 写成 **PR**，文档照抄并合入，事后需更正）。**规避**：① brief 优先写**源路径 + 章节号**让 worker 去读源，只在"措辞本身就是交付物"时才整段内联；② 改了源就 `grep` 出在飞 PR/分支里引用该内容的位置，逐一对齐；③ 副本已合并 → 开**跟随 PR**（上一行：禁止向已合并分支追加） |
| **native auto-merge「秒合」吞掉后续 commit ⇒ 交付物与 PR 声明脱节**（v1.29 新增，2026-09-15 实证，同款第 2 次） | **新增规则**：① **auto-merge 生效后不得再往该分支推新 commit** —— 要推就**先关掉 auto-merge**（`gh api graphql` 的 `disablePullRequestAutoMerge` 或关 PR 上的 auto-merge），推完**确认 PR 未被合并**（`gh pr view <N> --json state,mergedAt`；`MERGED` ⇒ 你的新 commit **不在里面**）；② **不要赌"CI 还没跑完"** —— auto-merge 只等**必需**检查，且与你的本地时序无关（本 PR 实操：先把 auto-merge 关掉再补 commit）。**实证**：PR #3842 被秒级合并 ⇒ 其 **3 个 commit 搁浅**，main 上 `assertion_taxonomy.py` 只有 **6 条规则**、L0 守卫 **40 条**（PR 声称 9 条规则；`main` 上**没有** `CASE-TRUST-VOLATILE-LOCATOR` / `NO-PRECONDITION-ASSERTION` / `STALE-LINE-REF`）⇒ 靠**跟随 PR #3847** 补齐；更早同款：**#3819** 搁浅 commit 靠 **#3826** 收口（同款第 2 次，见该 PR body 原文「只收口 #3819 因 native auto-merge 秒合而**搁浅**的第二个 commit」）。**判据与核法见下方「三件事」** |

> **⚠️ 「CI 绿」≠「auto-merge 就绪」≠「交付物在 main 上」—— 这是三件事**（v1.29 新增）：
> ① **CI 绿**只说明**语义检查**过了（逻辑、测试、门禁）；② **auto-merge 成功**只说明**合并动作**发生了
> （那一刻 main 上有的是**那一刻**的分支内容）；③ **交付物在 main 上**要看**文件内容**。
> 三者可以同时"看起来都好"而 ③ 是假的 —— 上面那一行就是这种形态（PR 绿、auto-merge 绿、**内容缺**）。
> **机械核法与判据**：
> - **核法**：`git show origin/main:<交付物路径>` —— **只看内容**（`git branch -r --contains <sha>` 与
>   `git merge-base --is-ancestor` **都不构成判据**，squash 会重写历史；这一条与上一行同源）。
> - **搁浅检测（可判定）**：把 PR **自己声明的交付物清单**（关键文件的关键内容 / 规则条数 / 测试条数）
>   逐条在 `origin/main` 上核 → **有任一条在 main 上不存在 ⇒ 该 PR 视为「未交付」**，
>   立即开**跟随 PR**（**不得**向已合并分支追加 commit）。
>   **边界（防假红）**：只对**关键交付物**做（不是逐字比对全文）；且**先排除**"PR body 本身就写旧了"
>   —— 本条判的是"**分支里有、PR 声称有、main 上没有**"，**不是**"分支里没有"。
>   **已落码（#4065）**：`./scripts/stranding-check.sh --pr <n>`（`--branch <ref>` 亦可；退出码 `0` 无搁浅 /
>   `1` 检出搁浅 / `3` 无法判定），集成入口 = `./scripts/batch-integrate-check.sh <branch> <pr>`。
> - **建议在开 PR 时就把这份清单写进 PR body**（它是你合并后的核对表）。

> **一句话**：**「分支 ≠ 交付」**。squash / rebase / merge 三种合并方式都会让「commit 可达性」失去判据意义；只有**主干上的文件内容**是事实。这两行是同一枚硬币的两面：上一行防「以为合了其实没合」，这一行防「以为没合其实合了」。

### 17.4 批量合并 + 统一验证（v1.23 新增，2026-09-14 用户裁定固化；v1.27 补「判定跑在飞期间冻结合并」；v1.29 补结论 fencing 完整形态）

**病根不是「并行修复」本身，而是「每个包各自验证、各自合并」**：每个包各开 PR、各自派发一次真实 LLM 评测、
各跑一遍三把工具 ⇒ ① 互抢**全局串行的评测资源**；② 窄重放常被全量档覆盖，净浪费；
③ 等待期被切成一堆「看一眼」的空转（进度假象，实为墙钟碎片）。

**三条范式（按序）**：

1. **等待期批量化**：外部 job（评测 / CI）在跑时**不要空转轮询**；把与它**无关**的活**成批**做完
   （多个派单、多次验证、多次合并在同一批内）。
2. **评测是全局串行资源，多包不得并发派发**：
   - 派发前先查**是否已有评测在跑**；同一时刻**全仓只允许一条评测腿**（xiaobu / mibao 合计一条），
     需要评测的包**先报主会话统一排期**，不要各自 `gh workflow run`；
   - 机制现状（照实登记，**勿当「有硬门禁」**）：`post-deploy-eval.yml` **有意不加
     `concurrency: cancel-in-progress`** —— 「宁可排队串行，也要让每一次部署都有完整的判定留痕」
     （文件内注释「为什么不加 `concurrency: cancel-in-progress`…」—— **按注释文本检索**，`@c5f07f29` 位于 `:139-144`）；
     而 PR 场景的 `xiaobu-acceptance.yml`（`concurrency.group` + `cancel-in-progress: true`，**按这两行文本检索**，`@c5f07f29` 位于 `:105-107`）
     与 `agent-behavior-eval.yml`（同形，`@c5f07f29` 位于 `:109-111`）会取消**同一 PR** 的旧 run
     ⇒ **多包并发派发时相互取消是真实发生的**：实测某窗口内
     **14 个 run 被取消，其中 8 个是 Post-Deploy Eval**（SHA 覆盖 `cc44197d`×4、`69f677af`×2、`541bacbe`×2）。
   - ⚠️ **`cancelled` 的 run 不是结果**：`conclusion=cancelled`、**没有 verdict、没有可用 artifact**
     ⇒ **不得**读成「跑了没过 / 过了」（同族于 v1.3 空跑：引用任何 run 前先核「步骤级 / 产物级 / 新鲜度」）。
     评测是**小时级**成本（`post-deploy-eval.yml` 注释自述「双 persona normal 全量，**90min 预算**」—— **按该注释文本检索**，`@c5f07f29` 位于 `:141`；
     实测单腿跑到 5.5–10.8 min 即被取消）⇒ **互相取消 = 纯白烧**。
3. **窄重放降级、全量档上收**：**优先用「合并后的一次全量评测」作为端到端验证** ——
   全量档（`tier=normal`，**不带 `case_ids`**）跑**全库**，因此**天然覆盖「缺陷由另一条用例制造」的前置条件**。
   实证：`PR-010`「把价格改成 198」制造了「商品级 basePrice ≠ SKU 级 price」分叉，而窄重放
   `case_ids=OR-014,AS-004` 把 PR-010 排除在外 ⇒ 栈内无分叉 ⇒ **修复路径未被行使**
   （该绿不构成判别性验证，详见 `migao-acceptance` v1.7）。⇒ **只有在全量档覆盖不到该用例时才用窄重放**，
   且用窄重放**必须回答**「**这次运行复现了缺陷的前置条件吗**」。

**统一验证清单（合并后跑一次，取代「N 个包各跑一遍」）**：

| 项 | 命令 / 判据 |
|---|---|
| 静态门禁 | `./verify-all.sh gate`（**commit 之后**跑，见 v1.19） |
| UI 回退 | `./check-ui-regression.sh` |
| 跨模块契约 | `./contract-check.sh` |
| L0 静态不变式 | `tests/unit_ci_workflows/`（python3.11） |
| 评测覆盖体检 | `scripts/xiaobu_coverage.py --check` + `scripts/mibao_coverage.py --check` |
| 生成物 SYNC | `render_cases.py` 重渲染 + `diff -q` 两个生成物 |
| 端到端 | **一次全量评测**（`tier=normal -f force_eval=true`）+ 结论档 verdict + **独立盲审** |

**⚠️ 结论的 fencing（结论绑定版本，v1.29 新增）** —— 上面「判定跑在飞期间冻结合并」是同一条纪律的一半，
完整形态是**结论必须可证伪地绑定到一整套版本元组**：

1. **绑定五元组 + 环境**：结论必须绑定
   `(sha, tier, case_ids, cases_fingerprint, policy_version)` —— **外加环境指纹 / 种子哈希**。
   **任何一个动过 ⇒ 旧结论即刻失效**，**不得**把旧结论套到新 SHA 上（这是 §17.3「分支 ≠ 交付」的姊妹形态：
   一个说"内容才是事实"，这个说"结论只对其版本成立"）。
   - **机器可取的形态**：artifact 里 summary 的 **`run_key`** 就是这套键（实测 run `34908262839`
     的 mibao 腿：`sha` / `tier=normal` / `case_ids=""` / `cases_fingerprint` / `evidence_window` /
     `policy_version` / `persona` / `run_mode=determination`）⇒ **引用结论时把 `run_key` 一起贴出来**，
     它是"这条结论属于哪个版本"的唯一凭据（**按 `run_key` 检索**）。
2. **判定跑在飞期禁止合并**（展开见上一条）：跑后合并的内容**不在该结论覆盖范围内** ⇒
   结论里**必须明写覆盖的 SHA**，并标注「其后增量未经全库验证，仅确定性层 / 单测层覆盖」（同 §16.7 判据）。
3. **活环境判定不得与部署重叠**（口径 **#3840** 实证）：`Deploy Reconcile` 会在**每个 PR 打开**时对账并重建容器
   ⇒ **1~3 分钟** 502 窗口；一次活环境 p1 冒烟正撞在该窗口上（**#3840** 记录的那轮 502），
   其性能读数因此**不能当基线**（该 issue 用"部署清空后的干净跑"做了证伪检验，才把性能红与部署窗口分开）。
   ⇒ 两条前置判据（断言无部署在飞 + 记录被测 SHA）**详版在 `migao-acceptance`「活环境判定的快照一致性」**，
   本节只留指针（同 §18.7）。

**⚠️ 代价与边界（不写清楚，这条范式就会变成掩盖回归的挡箭牌）**：

- **判定跑在飞期间冻结合并**（v1.27 新增）：一次**判定跑**（全量评测）在飞时**不要往 main 合新东西**；
  确有增量要落地 ⇒ **并到下一批**（并入下一次判定跑）。若在飞期间**已经**落了增量：**结论必须写明本次
  verdict 覆盖到哪个 SHA**（以 artifact 的 `run_key.sha` 为准 —— `run_key` 由 `local_runner` 写进 summary，
  **按 `run_key` 检索**），并**显式标注**「**其后增量未经全库验证，仅在确定性层 / 单测层覆盖**」——
  **不得**表述成「这是当前 main 的结论」（拿"旧 SHA 的绿"当"当前 main 的结论"= 本族的假绿）。
- **批合并会粗化归因**：一次合多个 PR 后跑统一验证，若红**不知道是谁引起的** ⇒
  ① **批内 PR 应属同一改动面 / 主题**（跨面就分批）；
  ② 统一验证失败时**按提交序二分**（`git bisect` 或逐个 revert）；
  ③ **不得**把「同一批」当成「可以不看单个 PR 的 CI」—— 单个 PR 的 required 门禁**照旧**，
     它挡的是**类型级**缺测（controller 缺 MockMvc、tool 缺 L2、组件缺 E2E 等）。
- **不是所有验证都能批**：**行为 / 契约有因果耦合的改动**（如 AI 行为 + 其用例资产）**必须同批**；
  **互相独立且高风险的改动**（如 DB 迁移）宜**单独一批**，便于回退。

## 18. 单一真相源与不可变引用（v1.28 新增，2026-09-15 issue #3843 实证固化）

> **病根**：「反复修、反复测、还有问题」的主机制**不是断言写法**，而是两件**静默**的事 ——
> ① **陈旧快照**（读者手里的副本 ≠ 被测对象的**当前**状态）⇒ **修的目标是错的**；
> ② **移动靶**（对象用**名字 / 序号 / 位置**定位，或用例运行中途世界被改）⇒ **测的目标是错的**。
> 两者都**不报错**，只表现为「没修好」⇒ 触发再次修复 + 再次全量复测（成本放大），
> 而真正的病灶（**读源与引用**）从不进入待修清单。
>
> **六层同类实例**（指令 / 文档 / 源码 / 账本 / 用例 / 环境）与实测量化见 **#3843**；
> A~H 护栏的**实装**也在 #3843。本节只固化**可执行判据**——**别再靠"我确认过是新的"这类自觉**。
>
> ⚠️ **机制现状登记（勿当成"有硬门禁"）**：以下各条的机器守卫**多数尚未落码**
> （已落码的只有 §18.5 的 `pre_clean` 渲染一格）。**未落码的条目按"人工可执行检查"对待**，
> 发现违例**必须开 issue**——"登记为纪律"不等于"有人拦着"。

### 18.1 读源纪律：真值一律对 `origin/main` 读（机器可判）

**判据**：任何「某文件里有什么 / 第几行是什么 / 某符号是否存在」的判断，**只能**来自：

```bash
cd <migao 仓库根>                                     # 任一 clone 均可
git fetch origin main                                 # ① 先取最新，再判
git show origin/main:<path>                           # ② 读内容（这就是真值）
git show origin/main:<path> | grep -n '<符号/文本>'    # ③ 定位：按符号检索，不记行号
git grep -n '<pattern>' origin/main -- '<pathspec>'   # ④ 全树检索
```

- **落后工作副本 ≠ 真相**：工作树落后时，本地 grep 到的只是**快照**。实证（#3843 源码层）：
  一次会话把**落后 5 个提交**的工作区当真相，得出「`ok` 判据不含 `systemic`」的**错误判据**并据此派单
  （派发前自查才抓到）；写本节时实测**主工作区** `HEAD=aa64bb98` 落后 `origin/main` **136 个提交**且脏
  —— 在那种工作区里判存在性/行号，**结论必然错**。
  ⇒ 开工先 `git fetch origin main`；`git rev-list --left-right --count HEAD...origin/main` 显示落后就**改用 `git show` 读**。
- **禁止裸行号 `path:NNN`**：PR / issue / 回报 / 文档里一律禁止。两个理由：① 会被后续的**模式扫描**
  误判成「残留引用」；② 会被读者误当**现值**照抄。行号一律写成「**第 N 行**」且**以 `@<sha>` 限定**
  （例：`_needs_serial_lane`（`@c5f07f29` 位于 `:5088`））；**能吃符号就吃符号**（函数名 / 守卫串 /
  注释串 / 测试方法名 / 小节名 / issue 号）—— 实证：`local_runner.py` 的 3 个行号在 **4 分钟内**失效。
- **自证扫描（本 PR / 本文档必须 0 命中）**：
  ```bash
  git diff origin/main...HEAD | grep -nE '^\+.*[A-Za-z0-9_./-]+\.(py|sh|yml|yaml|md|js|ts|tsx|java):[0-9]+' \
    && echo "❌ 有裸行号" || echo "✓ 0 命中"
  ```
- 同源：§16.7「引用纪律」、§17.4「分支 ≠ 交付」——**只有主干上的文件内容（`git show origin/main:<path>`）是事实**，
  commit 是否可达**不构成判据**（squash 会重写历史，见 §17.3 反模式表）。

### 18.2 开工前的活锚新鲜度核对：**落后即先同步再动手**

**活锚** = DSH 真正加载的技能目录 `~/.dsh/.agent-presets/migao`（软链；**权威源是本仓库 `.agent-presets/migao/`**，
见根 `AGENTS.md`「开发环境准备」）。**加载技能后第一件事就是核新鲜度** —— 活锚陈旧时
**每个会话都在按过期规则干活，而没有任何东西会因此变红**（实证：活锚 `migao-dev-flow` 停在 **v1.23**
而仓库已 **v1.27**，落后 **25 个提交**；`.github/**` 与 `scripts/**` 里**零检查**）。
**另一形态（2026-09-17 实测，`#4026`）**：活锚曾指向**落后 `origin/main` 42 个提交**的主工作区 ——
内容当时恰好一致（无害），但只要下一次有人改预设并合并，改进就**永远到不了加载点**
⇒ 后续所有会话读到的仍是旧模式。**只比版本号/只比内容都查不出它**（sha 落后才是病灶）。

**可执行判据（开工第一件事；红就停）**：

```bash
./scripts/preset-anchor-check.sh      # 活锚 vs origin/main：内容逐字节 + 检出 sha + frontmatter 可加载性
./scripts/preset-anchor-refresh.sh    # 红时自愈：只读镜像 fetch + checkout --detach origin/main + 复检
```

判定本体在 `scripts/agent-presets-guard.py` 的 `anchor` 子命令（`./scripts/dev-worktree.sh preset-guard`
也带这一段，提交路径同样拦）。三态**照实读**：**落后 / 悬空 / 内容不同 / 技能加载不了 = 红**；
`⏭️ 未跑判定`（本机没接线活锚、或活锚与本仓库不同上游）**不是「通过」** —— 别把两者混起来。
下面这段是**人工兜底**（没有脚本的环境用）：

```bash
ANCHOR="$HOME/.dsh/.agent-presets/migao"          # 活锚（软链目标用 readlink -f "$ANCHOR" 看）
REPO=<migao 仓库根>
git -C "$REPO" fetch origin main
for s in migao-dev-flow migao-acceptance; do
  printf '%-16s 活锚=%s 仓库=%s ' "$s" \
    "$(sed -n 's/^version: *//p' "$ANCHOR/skills/$s/SKILL.md" | head -1)" \
    "$(git -C "$REPO" show "origin/main:.agent-presets/migao/skills/$s/SKILL.md" | sed -n 's/^version: *//p' | head -1)"
  # 内容级比对：版本号相同也可能已分叉 —— 只看版本号会漏
  diff -q "$ANCHOR/skills/$s/SKILL.md" \
       <(git -C "$REPO" show "origin/main:.agent-presets/migao/skills/$s/SKILL.md") \
    >/dev/null && echo "✓ 同步" || echo "⚠️ 落后/分叉 ⇒ 先同步再动手"
done
```

- **落后即先同步，再动手**——不许"先把活干完再同步"：那正是**按过期规则干活**。
- 同步方式（**不要手抄文件**，手抄就是新一层快照）：跑 `./scripts/preset-anchor-refresh.sh`
  —— 刷的是**专职只读镜像**（`fetch` + `checkout --detach origin/main`；镜像没有分支状态，故不用 `merge`）。
  **活锚必须指向专职只读镜像**，指向工作区会有两种静默失效：① 落后 `main` ⇒ 改进到不了加载点（`#4026`）；
  ② 被清理/被切分支 ⇒ 软链悬空 ⇒ **DSH 静默加载不到研发模式**（`#3956` 实证）。换链见根 `AGENTS.md`「开发环境准备」。
- **改本仓库 `.agent-presets/**` 的 PR 合并后，活锚必然又落后一格** ⇒ **合并后顺手再核一次**
  （把上面的循环当例行收口动作；本节的 PR 自身也适用）。

### 18.3 被测对象必须用**不可变标识**定位

**判据**：`pre_clean` / `db_verify` / `output_verify` / 交互步骤 / 任何断言里**定位被测对象**，
**必须**用**不可变标识**；**名字 / 序号 / 位置只允许出现在「用户输入」里**（用户就爱这么说），
**用来定位断言目标时一律禁止**。

| ✅ 允许（不可变） | ❌ 禁止（可变 —— 会指到别的对象） |
|---|---|
| `order_no` / `phone` / `id` / **用例自建的唯一名**（带 run 指纹或时间戳后缀） | **名字**类：`product_keyword` / `customer_keyword` / `keyword`（同名对象不唯一） |
| 明确的主键 / 业务唯一键 | **位置**类：`customer_index` / `_index:`（实证 `CU-003`：`customer_index: 0` 在 `created_at DESC` 下**点中别人中途建的那个人**） |
| — | **序数**类：`auto_select: true`（点"首项/第一个"；无卡时还会退化成发**字面量**「第一个」，见 `product.yml` 的 `#2991` 注释） |

- 自取现状（**不写死条数**，条数会漂，命令自证）：
  ```bash
  git grep -nE '^ *[a-z_]*keyword[a-z_]*:|_index:|auto_select:' origin/main -- '.github/cases/'
  ```
  （`@5300dae0` 实测：名字类 `product_keyword` 16 + `customer_keyword` 1 + `keyword` 3 = **20** 条；
  位置类 `customer_index: 0` **1** 条；`auto_select:` 11 处 —— 与该形态相关的既有单见 #3843。）

- **红证锚点同样禁读「可变引用」**（v1.35 / **#4313**）：**`origin/main` 是移动靶** ——
  修复一进 main，锚点文本立刻变成「**修复后**」⇒ 判据**恒红 / 自红**（实测 PR #4320 合并后本机 `1 failed, 11 passed`）。
  正确形态 = **逐字节内联片段** + **`@<sha>` 出处** + 一条 git 溯源交叉校验
  （取不到历史**显式 skip 并打印人工核法**，**不静默通过**）。
  ⚠️ **归因必须匹配**：`fetch-depth: 1` 的 job（pr-check）里 `git show origin/main:…` 取不到 ⇒ 这类断言走 **skip**
  ⇒ 形态是「**本地红 / CI 绿**」（比两边都红更难发现）——**不得**说成"阻塞所有 PR"。
  ⇒ **能力断言改成不依赖 git**（内联片段 ⇒ CI 也真跑），git 溯源那条只作**保真**用途。
  锚点 = `tests/unit_ci_workflows/test_admin_web_devserver_identity.py` 的 `PRE_FIX_WEBSERVER_SNIPPET`。

### 18.4 前置自断言：前置不成立走 **fail-closed**，**不得**退化成"agent 表现不好"的红

**判据**：用例**首轮**必须断言**自己的前置**（订单数 / 客户数 / 目标对象存在 / 库内无同名残留），
**前置不成立 = fail-closed**（直接失败，并把观测值打进失败信息，如
`前置不成立：customers=2（期望 1）`）——**不得**让它继续跑成「agent 表现不好」的红：
那是**归因错误的红**，会把修复引到错误对象上（正是本节的病根）。

两条实测因果链（#3843）：

- **`PG-013`（世界在两次读取之间变了）**：首跑**真的生成**了加工单（`results=1`）⇒ 订单转 `producing`
  （用例自己的 `data_checks` 写着）⇒ 重试**前置已变**（`orders=1`，agent 原话"加工单早已生成"）
  ⇒ 红的表现却像「agent 不干活」。
- **`CU-003`（按名字/位置定位 = 定位到错的对象）**：`OR-010` 建单触发 admin-api 按手机号**自动 upsert**
  客户档案 ⇒ 多出一个同名「张三」⇒ `customers=2` ⇒ agent **合理地**要求消歧；
  而 `customer_index: 0` **点中的是那个新造的人**。

⇒ 与 §18.5 的账本口径配套：`pre_clean` 里做**自清理**（同名 / 同 phone 的残留），
使**重试前置等价**；写类用例的资产清单见 #3794 / #3800 / #3833 / #3836。

### 18.5 账本新鲜度：生成物必须**重渲染 + diff**；「账本里看不出来的字段 = 缺陷的盲区」

> **同族三条（快照当成现值用）在本节之外**：交付物搁浅（`auto-merge` 吞 commit）/ worktree 预设快照 /
> 写死易变数字 —— 判据与核法见 **§19.2**（本条只管"生成物账本"这一类，不重复表述）。
> 但**判据同源**：`.agent-presets/**` 本身也是"随代码评审的账本"⇒ 动它要走正常 PR（见 §2.3 第 7 条）。

**判据**：**生成物就是账本**。账本里**看不出来的字段 = 该类缺陷的盲区** ——
`render_cases.py` 曾**从不渲染 `pre_clean`** ⇒ 账本上看不出「写类用例有没有自清理」，
#3794 / #3800 / #3833 **全在这一格的盲区里**（只有翻 summary JSON 才能发现）。

```bash
cd <migao 仓库根>
python3 .github/render_cases.py --cases .github/cases --out-eval /tmp/ec.py --out-md /tmp/cb.md
diff -q /tmp/ec.py tests/agent_eval/eval_cases.py \
  && diff -q /tmp/cb.md docs/testing/mibao-verification-cases.md \
  && echo "生成物 SYNC ✓" || echo "生成物 DIVERGED ⚠️（重渲染并提交，勿手改）"
```
（同 §6 一键命令。**合并 main 后必查**：`.github/cases/` 前进 ⇒ 生成物必然 diverged ⇒ CI 新鲜度校验必红。）

- **扩容口径（判据，不是愿望）**：账本 diff 校验的覆盖面要**跟着账本字段长**。`pre_clean` 一格已随
  `#3836` 落地（`render_cases.py` 里对 `pre_clean` 的渲染分支，**按 `pre_clean` 文本检索**）；
  **覆盖率矩阵**（`scripts/xiaobu_coverage.py --check` / `scripts/mibao_coverage.py --check`）与
  **跨 run flake 索引**（`.github/scripts/flake_history.py`）同属账本 ⇒ **改了来源就重渲染并 diff**，
  **不得**只看上面那两个文件就宣称"账本新鲜"。
- **反面教材**：跨 run flake 索引（#3806）曾是**死代码 + 假夹具守卫** ⇒ **历史放行依据本身是错的**
  （曾把真产品缺陷判成 `llm-noise` 放行）。**放行依据也要有新鲜度**。
- **对账脚本自己的「唯一合法出口」也不能崩**（v1.34 / **#4247**）：`refs-are-fixtures` 例外
  （`# drift-audit: refs-are-fixtures`，`tests/**` 专用）在「**同文件里有已入基线的引用条目**」时
  曾抛 `KeyError` —— 门禁侧回的是**展开码**（`…|bare × 1`），清单的键是**原键**（`…|bare`），
  键形对不上；后果是**该文件一加 marker 就 traceback 取代结论**（唯一出口"用就崩"，等于没有出口）。
  已修：键形映射显式化（`_codes_of` 加 `{len(key)}:` 前缀 + `_collapse_code` 结构性逆映射）；
  万一归位再失败则 **fail-closed 报出该条 stale**（不再抛），提示里打**键形差异** +
  重生成命令。判据源 `scripts/drift_audit.py` 的 `reconcile_baseline` / `_collapse_code`
  （守卫 `tests/unit_ci_workflows/test_drift_audit_reconcile.py`）。**核法**：给带引用条目的文件加 marker 后，
  对账必须产出**可行动的 stale 报告**（含"移除或收窄 + 重生成命令"），**不是** traceback。
- **迁移不可变 = 另一类账本**（v1.35 / **#4235**，详版 `docs/wiki/Database.md`）：
  ① 🔴 **种子追加必须走「新迁移」** —— 改**已应用**的迁移会被 `MigrationRunner` 按**文件名**整份 skip
  （台账 `schema_migrations`，`if (applied.contains(filename)) continue`）⇒ **CI 全绿、功能静默缺失**
  （静态守卫反而因此转绿）；「迁移一旦应用即不可变」是工程规则，此前**零护栏**。
  ② **种子守卫已按集合聚合** —— 按**内容**发现 `INSERT INTO <table>` 的迁移（`V54 ∪ V56` / `V54 ∪ V58`），
  不再写死 V54 ⇒ **新增种子迁移无需改守卫**（按命名约定 `V*__seed_*.sql` 反而会漏，`V28`/`V30`/`V40` 是反例）。
  ③ **「迁移不可变」护栏 = 内容指纹账本** —— `tests/unit_ci_workflows/test_migration_immutability.py`
  + 账本 `tests/unit_ci_workflows/migration_fingerprints.json`（`{文件名: 内容 sha256}`，**与 git / DB / `fetch-depth` 无关**
  ⇒ 浅克隆的 CI job 也真跑）；**新增迁移必须同 PR 跑 `--write-ledger` 登记**
  （`python3 tests/unit_ci_workflows/test_migration_immutability.py --write-ledger`，**只新增条目**；
  **已登记文件被改 ⇒ exit 1 拒绝重生成**并点名文件 —— 那是要**回滚改动**，不是"刷新一下"；
  确需改已发布迁移必须**手工**编辑账本条目，让它出现在 PR diff 里）。三向可红 + 注入式自证。

### 18.6 环境静默**即缺陷**（不是"这个套件一直红"）

> **机制现状**：本条**纪律已落码的只有"权限缺失"那一半**（§18.6.1，`#3838`）；
> **心跳检查仍未落码** ⇒ 其余形态按"人工可执行检查 + 发现即开单"对待。

**判据**：凡 `.github/workflows/*.yml` 里声明 `schedule:` 的工作流，**长期无成功跑 = 缺陷**，
必须**当缺陷开单处理**；**不得**读成"它一直红/它不重要"。

```bash
# ① 列出所有带定时的 workflow（当前 13 个 —— 命令自证，别记数字）
git grep -l 'schedule:' origin/main -- '.github/workflows/*.yml'
# ② 逐个核"最近几次的结论"（静默的形状：从来没有 run / 最近全 failure / 停在某个过去日期）
gh run list --workflow=<name> --limit 5 --json conclusion,createdAt,headSha \
  --jq '.[] | "\(.createdAt) \(.conclusion) \(.headSha[0:8])"'
# ③ 取该 workflow 的 cron，与"最近一次成功跑"相减 ⇒ 超过 2 个周期仍无 success ⇒ 红（当缺陷开单）
git show origin/main:.github/workflows/<name>.yml | grep -n 'cron:'
```

实测三例（#3843 环境层）：`nightly-verification` **连红 9 天零 issue**（#3834）；
`agent-eval-adversarial` 每周六静默（留痕停在 **08-29**）；`fixture-record` 每月静默（**历史 0 条**）。
⇒ 静默的共同形状是「**没有任何东西会因为你静默而变红**」。

#### 18.6.1 enforcement 锚点：**静默失败即缺陷**已落码的那一半（v1.29 新增）

**判据（可执行）**：凡**调用 issue API** 的 workflow（`issues.create(` / `issues.createComment(` /
`search.issuesAndPullRequests(` / `gh issue create|comment|edit|close|reopen` / `gh api -X POST|PATCH …/issues`）
**必须声明 `issues: write`**（PR 评论路径可用 `pull-requests: write` 覆盖）；**未声明 = fail-closed 判红**。
守卫在 **`tests/unit_ci_workflows/test_workflow_issue_permissions.py`**（**PR #3838**，`42 tests collected`
—— 命令自证：`python3 -m pytest tests/unit_ci_workflows/test_workflow_issue_permissions.py --collect-only -q`），
由 `pr-check.yml` 的 `ci workflow helper unit tests` job（`python -m pytest tests/unit_ci_workflows`）执行。

- **为什么需要它**：它**读 YAML 真值**（逐 job 计算有效权限，job 级覆盖顶层、`write-all`/`read-all` 展开），
  **不扫全文正则** —— 所以注释里解释"为什么需要这个权限"的措辞**不会**被判违规（防**假红**）；
  且**每条断言都有红证**（对每个判绿的 workflow 把权限换成 `{contents: read}` 后**必须变红**，
  另有 `#3834` 修复前的 nightly 头作为红证夹具）⇒ 不是空跑（防**假绿**）。
- **病根实例（"静默"的完整因果链）**：一次「workflow 最小权限加固」**批量收窄 28 个 workflow 的权限**，
  却**只补回 1 个**（`agent-eval.yml`）⇒ 失败通知钩子自己 `HttpError: Resource not accessible by
  integration` 崩溃：
  - `nightly-verification` **连红 9 天、零 issue 留痕**（自 2026-09-05 起；**#3834**）；
  - `agent-eval-adversarial`（每周六）**静默至 08-29**（`[Nightly]` 最后一条 issue 停在该日）；
  - `fixture-record`（每月 1 日）**历史 0 条**（`[Fixture]` 从未留痕）。
  反证：同期有 `issues: write` 的 `[E2E Real]` / `[Xiaobu]` **照常留痕** ⇒ 差别**只在权限声明**，
  不在"这些 workflow 本来就不跑"。
- **同族但更早的两次**：#3270 首发 · #3497 复发（都是"点修一个、别处照旧"）⇒ 本条**第一次把它变成门禁**
  （点修 → 结构性守卫）。
- ⚠️ **尚未落码的另一半**：**心跳检查**（`schedule` 工作流"超过 2 个周期无成功跑 ⇒ 红"）**仍未落码**
  ⇒ 在它落码前，`schedule` 静默**仍只能靠 §18.6 的人工检查 + 开单**兜住。
  **别把"权限守卫已落码"读成"静默已被门禁挡住"** —— 权限只是静默的**一个**成因。
- 关联：**#3834**（病根单）/ **#3838**（落码 PR）/ **#3843** 的 G 项（心跳守卫，未落码）。
**心跳守卫（A~H 的 G 项）尚未落码** ⇒ 在它落码前，**发现静默必须开 issue**，这就是本条的判据。
（**已落码的是"静默的另一半" —— 权限缺失**，见下 §18.6.1；两者不可互相代替。）

### 18.7 活环境测量要记快照（详版在 `migao-acceptance`，此处只留指针）

**判据（一句话）**：向**活环境**打任何判定之前，先**断言无部署在飞**并**记录被测 SHA**；
观测到 **502 / Connection refused** 时**先查是否落在部署窗口**，再谈产品缺陷。
（实测：`Deploy Reconcile` 在 **PR opened/reopened** 与 `schedule '*/20'` 上对账 main HEAD、缺失镜像即
dispatch 部署 ⇒ 容器重建产生 **1~3 分钟**的 502 窗口；一次活环境"502 误判"正是**没记录部署状态**造成的。）

> **口径单点**：本条**详版写在 `migao-acceptance`「活环境判定的快照一致性」节**（活环境 / 证据层，
> 且与「假红形态：基线快照晚于被测事件」同族）——**本节不重复表述**。
> 「核算数字必须锚定 SHA」的一般纪律已见 §16.6 ④ 与 §17.4（判定跑在飞期间冻结合并），同源不重复。

### 18.8 反模式清单：把「靠自觉」换成「靠工具 / 检查」

| 反模式（禁止） | 为什么它就是本节的病根 | 换成 |
|---|---|---|
| 「**我确认过是新的**」/「我刚 pull 过」 | 无判据的自觉；工作区**落后 136 个提交**时照样"感觉是新的" | `git show origin/main:<path>` + §18.1 的裸行号扫描 |
| 「引用里的行号我核过了」 | 活跃文件的行号 **4 分钟**就失效 | 引用写成**符号锚点**（行号仅以 `@<sha>` 限定作辅证） |
| 「用例写的就是这个商品名 / 点第一条」 | 名字与位置**都不唯一**（同名 upsert / 重名客户） | `id` / `order_no` / `phone` / 用例自建唯一名（§18.3） |
| 「跑红了，看来 agent 没干活」 | **前置不成立也是红**（`PG-013`） | 首轮前置自断言 + fail-closed（§18.4） |
| 「生成物没变，不用 diff」 | **账本盲区 = 缺陷盲区**（`pre_clean` 曾不渲染） | 重渲染 + `diff -q`（§18.5） |
| 「那个 nightly 一直红，忽略它」 | 静默 **9 天零 issue** = 无人知 | **当缺陷开单**（§18.6） |
| 「502 了，产品挂了」 | 可能落在 `Deploy Reconcile` 的 1~3 分钟窗口 | 先断言无部署在飞 + 记 SHA（§18.7） |
| 「本地分支有 commit，说明已合入」 | squash 后 **commit 可达性不是判据**（§17.3/§17.4） | `git show origin/main:<file>` **看内容** |

> **一句话**：**凡"读"都要问「我读的是快照还是真相源」，凡"指"都要问「我指的对象会不会被别人改名 / 挪位」。**
> 这两个问题答不上来，后面的修复与复测都建立在沙上。

## 19. 范式总纲与 enforcement 锚点（v1.29 新增，2026-09-15 实证固化）

> **定位**：本节是**索引表**，不是第二份口径 —— 每条范式只在**一处**展开（表里给指针），
> 本节只负责回答三个问题：**它是什么 / 判据是什么 / 它到底有没有落码**。
> 起因：2026-09-14/15 这轮把八条范式陆续写进了技能，但它们散落在 §16/§17/§18 与 `migao-acceptance` 里，
> 且**"写进技能"与"有门禁"在读者眼里长得一模一样** —— 表里那个「现状」列就是治这个的。

| # | 范式 | 判据（一句话，可执行） | 落码锚点 | 现状 |
|---|---|---|---|---|
| 1 | **单一真相源与不可变引用** | 真值只读 `git show origin/main:<path>`；引用吃符号不吃行号；定位被测对象只用不可变键 | **§18**（18.1~18.8；18.5 的 `pre_clean` 渲染一格随 `#3836`、`drift_audit` 的 `refs-are-fixtures` 例外随 **#4247**） | **部分落码**（`pre_clean` 账本渲染 1 格 + `reconcile_baseline` 键形归位）；**统一审计 `scripts/drift_audit.py` 未落码** |
| 2 | **断言可信度**（假红 / 假绿的结构性护栏） | 写类用例 ≥1 条效果层断言；有自清理或命名空间且点名可解析；散文禁令不单独承重；单端用例标 persona；**`[backend-contract]` 用例的计分通道 = `traces.tests`**（非空且引用文件真实存在 ⇒ a1/a2 分流不报，其余规则一字不放宽） | **§19.1**（判据源）；`.github/case_trust_gate.py` + `.github/assertion_taxonomy.py` + 基线 `.github/case-trust-baseline.json` + 未实装登记 `.github/case-trust-unimplemented.json` + `pr-check.yml` 的 `Case Trust Gate (断言可信度)` job（**#3842**；计分通道分流 **#4244**） | **已落码**（门禁 + 基线 + 未实装登记齐全） |
| 3 | **结论的构成与读法** | `ok` = **六类**阻塞桶全空（含 `case_asset_failures`）；结论须按桶分解；收紧口径后"新引入"与"原放行现形"分开标注；每条失败有归因；不越证据等级 | **§16.7「结论的构成与读法」** | **已落码**（`local_runner.completion_verdict` 输出 `completion` **六桶** + `run_key`；`case_asset_failures` 随 **#4245** 落码；读法本身是纪律） |
| 4 | **fencing（结论绑定版本）** | 结论绑定 `(sha, tier, case_ids, cases_fingerprint, policy_version)` + 环境指纹/种子哈希；版本一动结论失效 | **§17.4「结论的 fencing」**（`run_key` 是其机读形态） | **部分落码**：`run_key` 由 runner 写出（可引用）；"不得套用旧结论"为纪律，无门禁 |
| 5 | **静默失败即缺陷** | 调 issue API 的 workflow 必须声明 `issues: write`（PR 评论可用 `pull-requests: write`），否则 fail-closed 判红 | **§18.6 + §18.6.1**；`tests/unit_ci_workflows/test_workflow_issue_permissions.py`（**#3838**）；心跳检查 | **部分落码**：权限守卫已落码；**心跳检查未落码**（人工检查 + 开单） |
| 6 | **归因纪律** | 归因强度匹配证据强度；双侧禁令（不为脱罪归评测侧 / 不为显严格硬归产品）；跨 run ≠ 同因；独立复核可推翻主会话初判 | **`migao-acceptance`「归因纪律（v1.10 新增）」**；（§16.7 的「每条失败必须有归因」是同一族的运维侧形态，不重复展开） | **仅纪律（未落码）** |
| 7 | **成本与验证顺序纪律** | 先窄跑后全量；窄跑走单腿入口（`persona` 输入）；产品因未修不跑判定跑；不为变绿调阈值 | **§16.7「成本与验证顺序纪律」** | **部分落码**：单腿入口 `persona` 输入已存在（`xiaobu-acceptance.yml`）；其余为纪律 |
| 8 | **护栏自身的反退化** | 每条护栏都要有**能红的夹具**；判据必须**单点来源**；基于错误真相模型写出的护栏 = 空判据 | **§19.1 末条**（含"同步副本"承诺的反例）；实证：`#3838` 的红证夹具、`assertion_taxonomy.RULES` 的 `implemented` 字段与 `UNIMPLEMENTED` 登记 | **部分落码**（两处门禁已自证有红证；"判据单点来源"靠评审，无扫描） |
| 9 | **交付物搁浅（auto-merge 秒合吞 commit）** | `CI 绿 ≠ auto-merge 就绪 ≠ 交付物在 main`；核法 = `git show origin/main:<交付物路径>` 看内容；PR 声明的关键交付物缺任一 ⇒ 未交付 ⇒ 开跟随 PR | **§17.3**（反模式表行 + 「三件事」段与**搁浅检测**）/ **§19.2 ①** | **已落码**：`scripts/stranding-check.sh`（内容级，三态 `0/1/3`；接在 `batch-integrate-check.sh` 的 PR 号上）；**未接 CI 门禁**（人工/集成环节调用）。实证 **#3842 → #3847**、**#3819 → #3826** |
| 10 | **worktree 预设快照 / `git add -A` 静默回退** | 动 `.agent-presets/**` 的 PR 必须核**版本不降级**；`git diff --cached -- .agent-presets/` 出现版本回退 ⇒ 拒绝提交 | **§2.3 第 7 条**（含命令）/ **§19.2 ②** | **部分落码**：`dev-worktree.sh add` 路径**已自动刷新**（`refresh_presets()`，v1.8 / **#3851**）+ 提交路径有 `preset-guard`（版本单调性 + 活锚）；**"活锚必须是专职只读镜像"仍为纪律**（`migao-wt/*` 属 `rm/prune` 半径）。⚠️ 本行原写"实测**不刷新也不排除**"，**已过期**（v1.35 改判） |
| 11 | **不写死易变数字** | 只给**检索命令** + `@<sha>` 限定的实测值；引用数字必须**连命令一起给** | **§19.2 ③**（反例：同一量先写 **14** 实测 **13**、先写 **19** 实测 **11**）；正例见 **§18.6** 的"命令自证，别记数字" | **仅纪律（未落码）**（无扫描；属编写规范） |
| 12 | **批量修复的防复发纪律（R1~R7）** | 修机制不修事故点（同类 ≥2 ⇒ 修机制）/ 负例证据 / 失败集只许收敛 / 禁止新增豁免 / 禁止新增静默失效形态 / 净变更量 `app/**` ≤0 / 前提必须新鲜 | **§20**（判据表）；机械入口 `scripts/batch-integrate-check.sh`（**#4023**） | **部分落码**（R6/R4/R5/R2/R7 已落码；**R1/R3 未落码**——见脚本头部登记） |
| 13 | **豁免账本按类分流（增长判据不许只看总数）** | `skip_total` **不作增长分母**；增长只判**债务类**（`debt_skip_ids`/`debt_skip_total`，**只许缩**）；`[backend-contract]` 单列**只增**合规清单 `backend_contract_ids`（其 `skip_reason` 是 runner 侧分隔符、设计上不进 agent-eval ⇒ 新增该类合规用例**无需**重锚定）；`_when_to_update` 与门禁例外条款**口径合一**（`history` 末行带显式 note 的锚点前移是**唯一**例外） | `.github/skip-exemption-baseline.json` 的 `_scope` / `_when_to_update` / `debt_*` / `backend_contract_ids` 字段；守卫 `tests/unit_ci_workflows/test_skip_exemption_gate.py`（**#4233**） | **已落码**（判据 = 该文件字段 + 守卫测试，随 pr-check 的 `ci workflow helper unit tests` job 跑） |
| 14 | **迁移不可变（已发布迁移只增不改）** | 种子追加走**新迁移**（改已应用迁移被按**文件名**整份 skip ⇒ CI 绿、功能静默缺失）；种子守卫**按集合聚合**（按内容发现 `INSERT INTO <table>` 的迁移）⇒ 新增种子迁移无需改守卫；**新增迁移必须同 PR `--write-ledger` 登记指纹**（已登记文件被改 ⇒ exit 1 **拒绝重生成**） | `tests/unit_ci_workflows/test_migration_immutability.py` + 账本 `tests/unit_ci_workflows/migration_fingerprints.json`（**#4235**）；**§18.5**；详版 `docs/wiki/Database.md` | **已落码**（指纹账本三向可红 + 注入式自证；随 pr-check 的 `ci workflow helper unit tests` job 跑，**与 git 历史无关** ⇒ 浅克隆也真跑） |
| 15 | **往返预算（步数才是计费单位）** | 读要成批 / 改要成批（同一步多个 `edit`；>3 处或整体重写用一次 `write`）/ 查要合并（多条 `grep` 合成一条 bash）/ 验证不来回（先窄跑再全量）/ **等待不轮询**（`--watch` 或后台 job，禁 `sleep N`）；分母 = 「调用数 / 步数」比 + 各工具的**调用占比 vs 执行耗时占比** + 「等待型调用」次数/时长 | **§21**（判据表 P1~**P7**）；`scripts/roundtrip_report.py`（**#4428** + 等待段 **#4455**，报告型三态 `0/2/3`）+ `tests/unit_ci_workflows/test_roundtrip_report.py` | **部分落码**：报告型工具 + L0 守卫（含注入式红证）已落码；**「批量化 / 不轮询」本身是纪律，无门禁** —— 有意不加阈值：加了阈值就没人敢跑它 |

> **表的使用方式**：判据在**落码锚点**那一格的文件/脚本/技能节里；本表**不复述**判据正文。
> 「现状」列**照实写** —— **未落码就是未落码**（同 §18 开头的警告：登记为纪律 ≠ 有人拦着你）。

### 19.1 断言可信度：假红 / 假绿的结构性护栏

**病根**：门禁原先只查「有没有断言」，**不查断言能不能判红** ⇒ 假红（合格行为被判红）与假绿
（真失败被判通过）都能穿过门禁。治法是把「断言可信不可信」也做成**可判定的静态形状**。
**判据源 = `.github/assertion_taxonomy.py`（纯函数、零依赖、单一来源）** —— 静态门禁
（`.github/case_trust_gate.py`）与 runner 侧归因分类器**必须共用这一处口径**；
两处各写一份（写工具集合 / 效果层断言集合）**一定会漂移**（届时静态放行、动态判红，门禁可信度归零）；
**改判据只改这一处**。

**四条形状判据**（每条：判据 + 为什么 + 实证）：

1. **写类用例必须有 ≥1 条效果层断言**（`CASE-TRUST-NO-EFFECT-ASSERTION`）：
   判据 = 至少一条 `must_succeed` / `db_verify` / `output_verify` / `amount_verify` / `post_session`，
   或**机器计分型** `data_checks`（须含 `success=true` / `error.code=` / `未被调用` / `not called`）。
   **为什么**：「**调用了 ≠ 成了**」（**#3778**）：`expectations` / `required_args` 只证明**调用发生、参数给对**，
   工具返回 `success=false` 照样通过。
   反例：**#3559**（散文 `data_checks`「sku_update 成功（价格落库）」**无 `success=true`** ⇒ 该项不计分
   ⇒ 工具失败仍判 100%）；**#3845**（`CU-003` 是 **KEY JOURNEY**，至今无效果层断言
   ⇒ **标签写失败也会绿**，且它落在存量基线里 ⇒ 不阻塞 —— 基线「只许缩短」，这类必须有人还债）。
2. **写类用例必须有自清理或命名空间**（`CASE-TRUST-NO-SELF-CLEAN`），
   且 `pre_clean` 点名的目标**必须在种子真值里可解析**（`CASE-TRUST-PRECLEAN-TARGET-UNRESOLVABLE`）。
   **为什么**：不自清理 ⇒ 第二次跑的前置与首跑**不等价**（幂等拒绝 / 重名澄清 / 存量被消耗），
   红的是"环境"而不是"行为"；点名一个种子里不存在的对象 ⇒ 清理**静默空转**（同族于 §18.6「静默即缺陷」）。
   实证：**#3794** / **#3832**（`CU-003` 的 `pre_clean` 目标名 `VIP2活跃` ∉ 种子标签目录
   `VIP2` / `活跃` —— **注意**：这是"点名解析不到、清理防线空转"，**不是**"物理不可满足"，
   后者需要"任何合法行为都无法满足"的证据，见 `migao-acceptance` 归因纪律）；**#3800**（写类建品用例缺自清理）。
3. **散文禁令不得单独承载关键判据**（`CASE-TRUST-FORBIDDEN-TEXT-SOLE`）：
   判据 = 有 `forbidden_text` 的用例**同时**要有 ≥1 条行为 / 效果层断言（或禁令改成**轮次作用域**形态）。
   **为什么**：`forbidden_text` 是**全程**语义（扫所有轮的 final_text，**无轮次作用域**）
   ⇒ 首跑功能正确，却可能因**某一轮**的良性措辞判红。
   实证 **#3833**：`PG-013` 首跑功能正确，却因 **R1 对另一笔订单的事实陈述**命中禁令而判红。
4. **单端用例必须标 persona**（`CASE-TRUST-SINGLE-LEG-NO-PERSONA`）：
   判据 = 按工具集可判定为单端的用例，必须有 `persona:` 标注；
   **"配对"不能豁免跨腿窄跑**（§16.6 ② / **#3822**，此处只给指针，不重复表述）。
   ⚠️ **判据形态（v1.36 / #4356 收紧）**：单端 = 「**小布腿跑得动 ∧ 米宝腿跑不动**」——
   米宝腿只有 persona 过滤、**没有**工具集过滤 ⇒ 工具集 ⊄ 米宝的用例在米宝腿必挂。
   两端**共享**的工具（`order_create` / `product_detail` / `product_search` / `validate_input` /
   `interact` / `knowledge_search` / `production_progress_query`）**不构成**单端理由：
   旧形态「工具集 ⊆ 小布 ⇒ 只能跑小布」隐含「两端工具集不相交」这一**假前提**，
   照它反推 `persona: xiaobu` 会把真实米宝用例**静默移出米宝腿**（全量跑不报红），
   并在 C 端腿制造假红（显式 `xiaobu` 无条件保留 ⇒ 绕过语义过滤）。
   ⇒ **标注一律按实际端别 + 证据**（种子 / 语义 / runner 归因），**禁止**从判据反推。
   **语义单端**（工具集两端都成立、行为只在 B 端可满足，如 `PR-018`）静态不可判定，
   按证据逐条分诊（#4086），不属本判据。

**a1 / a2 的适用范围 = 计分通道分流（v1.34 / #4244）**：规则 `CASE-TRUST-EMPTY-ASSERTION`(a1) 与
`CASE-TRUST-NO-EFFECT-ASSERTION`(a2) 的**前提**是「该用例由 runner 计分」（`total_exp == 0 ⇒ score = 1.0`）。
`[backend-contract]` 类用例**根本不进 agent-eval**（runner 侧按 `skip_reason` 过滤 ⇒ **未运行**，
既不会绿也不会红），它们的**计分通道是 `traces.tests`**（Java / pytest）。豁免须**同时**满足两个条件
（缺一即照旧报，防豁免被当万金油）：① **入口条件** = `skip_reason` 以 `[backend-contract]` 开头；
② **结构性条件** = `traces.tests` **非空** 且引用**全部**真实存在（路径相对仓库根 `is_file()`）；
`repo_root` 不传 ⇒ 存在性**无法校验** ⇒ **按未成立**处理（fail-closed）。
⇒ 对这类用例**不再报** a1/a2（不再逼出「把散文改写成含 `error.code=` 形态、运行期零变化」的**纸面修复**）；
**非**该类的纯散文用例**仍报**；**其余规则（自清理 / 前置自断言 / 单端 persona / 定位键 …）一字不放宽**
—— 分流的是「**谁给它计分**」，不是「它免检」。
判据源 `.github/assertion_taxonomy.py` 的 `is_backend_contract_case` / `backend_contract_scoring_channel`
（基线据此**只删不加** prune 23 条误报；`case_trust_gate` 报告须打印分流读数，防静默豁免）。

**三条元规则（护栏自己的护栏）**：

- **存量基线只许缩短，并显式登记未实装项**：门禁对**存量**违规用
  `.github/case-trust-baseline.json` 放行（锚定 SHA + 逐条计数），**新增违规阻塞**；
  基线**只许缩短**，且「已不再违规 ⇒ 必须移除」这条**只对本次 PR diff 命中的用例生效**
  （否则别人修好一条存量用例，门禁会自己判红并挡住他们的 PR = 假红）。
  判据在现有机制下**无法判定**时**不得**写成恒真判断凑数，而是登记进
  `.github/case-trust-unimplemented.json`（当前 **5 条**：`PRECLEAN-UNKNOWN-TYPE` /
  `PRECLEAN-FAILURE-FOLD` / `CROSS-LEG-NARROW-RUN` / `ALL-CASES-PERSONA-ANNOTATED`（**有意不做**）/
  `PROSE-DATA-CHECK-QUALITY`；其中**2 条属 runner=T2** 侧能力）——「登记缺什么」比「写个恒真的检查」诚实。
  **豁免账本的增长判据按类分流**（v1.34 / **#4233**，同族：别用总数当分母）：`skip_total` **不再作增长分母**；
  增长只判**债务类**（`debt_skip_ids` / `debt_skip_total`，**只许缩**）；`[backend-contract]` 单列
  **只增**合规清单 `backend_contract_ids`（设计上不进 agent-eval ⇒ 新增该类合规用例无需重锚定）；
  `_when_to_update` 与门禁例外条款**口径合一**（`history` 末行带显式 `note` 的锚点前移是**唯一**例外）。
  详版 = `.github/skip-exemption-baseline.json` 的字段 + `test_skip_exemption_gate.py`（§19 表的「豁免账本按类分流」行）。
- **基于错误的真相模型写出的护栏 = 永远红或永远被豁免的空判据**：
  实证（本会话）：曾要求「`docs/wiki/DEV-FLOW.md` 与技能 `SKILL.md` **diff == 0**」作为"同步"判据 ——
  实测两者 **971 行 vs 230 行**、版本戳 **v1.3 vs v1.27** ⇒ **diff 永远非 0**，那条判据**永远红**，
  只能被人工豁免 ⇒ **等于没判据**。真相是：那份"同步副本"是**人工节选**、**不是**权威源的生成物。
  ⇒ 正确判据 = **版本戳一致性**（`description`/`version` 面的比对）+ 把"副本"claim 二选一兑现：
  **要么由权威源生成**（生成物 + 新鲜度 diff，§18.5），**要么撤回 claim**。
  **推论**：写任何护栏之前先问「**我据以判定的那个事实模型，本身是真的吗**」——
  模型错了，护栏越严格，越是在制造**永远红**（假红）或**永远豁免**（假绿）。
  **已落码（v1.35 / #4315）**：处置 = **撤回**该 claim（B 案"由权威源生成"要先写一套摘要渲染器，成本高于收益）；
  判据取**形状**、不与技能内容等值（技能更新**不会**让它红）—— 锚点
  `tests/unit_ci_workflows/test_dev_flow_sync_claim.py`：
  **C1** 肯定式「同步副本」claim（不带撤回标记）/ **C2** 硬编码**现值**（`当前版本：vX`、`副本 vX` / `权威源 vX.Y.Z` 版本对）/
  **C3** 硬编码 `migao-wt` **工作区计数**（`N 个工作区`）/ **C4**（**正向**）页头**必须**同时声明
  「**已停止同步**」+「**以技能为准**」—— 只删 claim 不写归属 = 把过期内容变成**无归属的孤儿**。
  ⇒ 通用判据：**「同步副本」claim 要么由权威源生成、要么撤回**；**硬编码现值**（`当前版本：vX` / `N 个工作区`）
  **是缺陷**（会腐烂）。C3 **故意收窄**到"计数直接量词是*工作区*"（泛化 `N 条/N 个` 无零误红判据，
  故 `drift_audit.py` 把 `hardcoded-count` 登记为**未实装** —— 本判据**不**冒充当它已实装）。
- **红证本身也要有红证（缓存卫生）**（v1.34 / **#4260**）：**取红证的动作自己会骗人** ——
  **同秒 + 同字节长度**的替换让 Python `.pyc` 头只记 `(mtime 秒, size)`、**两项都没变** ⇒
  解释器**不重编译、复用旧 `.pyc`** ⇒ 注入**未生效**却读到旧值：**假绿证**（把本来有效的护栏
  当"空断言"删掉/放宽）或**假红证 / 错归因**。**判据**：注入**前后都必须清缓存** + 用**内容指纹**
  （`sha256`）自证注入/还原**真的生效**，**禁用 mtime / size** 判新鲜度（它们与载体无关地不可靠）；
  锚点 = `python3 scripts/red_proof.py clear|fingerprint|injected|restored`（三态 `0/1/3`；
  `--no-clear` 是诊断模式，**非零退出**）。⚠️ macOS 上 `.pyc` 可落在
  `~/Library/Caches/com.apple.python`（`sys.pycache_prefix` / `PYTHONPYCACHEPREFIX`）⇒
  仓库内 `rm -rf __pycache__` **可能是空操作**（却看起来"做了清缓存这件事"）。
  同族载体：Java `.class` 增量编译 / JS / TS transform cache。**详版 = `docs/testing/test-engineering-standards.md` §8**。
  **现状：未接 CI required check**（人工 / 取红证流程调用；自测红证 `tests/unit_ci_workflows/test_red_proof_guard.py`）。

### 19.2 交付与账本的新鲜度：三条"静默失效"的形状

**共同形状**：三件事都**不会因为出错而变红** —— 它们只表现为"看起来一切都好"。
判据与核法分别落在 §17.3 / §2.3，本节只做**形状登记**（避免第三份口径）。

1. **交付物搁浅**：`auto-merge 秒合` 吞掉后续 commit ⇒ **PR 绿 + auto-merge 绿 + 交付物不在 main**。
   判据：**CI 绿 ≠ auto-merge 就绪 ≠ 交付物在 main**；核法 = `git show origin/main:<交付物路径>` **看内容**
   （commit 可达性**不是**判据，squash 会重写历史）；搁浅检测 = PR 声明的**关键交付物**逐条在 main 上核，
   缺任一 ⇒ 视为**未交付**，开**跟随 PR**（**不得**向已合并分支追加）。
   **落点**：§17.3 反模式表 + 「三件事」段（实证：**#3842** → 跟随 **#3847**；更早 **#3819** → **#3826**）。

2. **worktree 里的预设是快照、且能被 `git add -A` 静默回退**。
   判据：动到 `.agent-presets/**` 的 PR **必须核版本不降级**（worktree 侧 vs `origin/main` 侧）；
   `git diff --cached -- .agent-presets/` 出现版本回退 ⇒ 拒绝提交。
   ⚠️ 本行原写「`dev-worktree.sh` **不刷新也不排除** `.agent-presets/`」—— **已过期**（v1.35 改判）：
   `add` 路径**已自动刷新**（`refresh_presets()`，v1.8 / **#3851**），提交路径另有 `preset-guard`；
   **地雷结论不变**（快照仍会落后、`git add -A` 仍会静默回退），**活锚必须是专职只读镜像**仍为纪律。
   **落点**：§2.3 第 7 条（含命令）。

3. **写死易变数字 = 制造新的陈旧快照**（编写技能 / 文档 / 回报时的**编写规范**）。
   判据：**只给检索命令 + `@<sha>` 限定的实测值**，**不写**"有 N 个 workflow""有 N 处选择器"这类数字；
   确需引用数字时**连命令一起给**（读者可自证）。
   - **反例（实证）**：本轮同一个量先被写成 **14**、后实测是 **13**（「带 `schedule:` 的 workflow 数」），
     另一个量先被写成 **19**、实测 **11**（`auto_select` 处数）—— 口径一变，写死的数字就从"事实"变成
     **新的陈旧快照**，而**没有人会因此变红**（同族于 §18.5「账本里看不出来的字段 = 缺陷的盲区」）。
   - **正例**：§18.6 的「列出所有带定时的 workflow（**当前 13 个 —— 命令自证，别记数字**）」——
     给命令 + 就地标注"别记数字"，才是可维护的写法。
   - **同族的第二种载体：注释 / docstring 里的数字与 `Test*` 标识符引用**（v1.34 / **#4259**）。
     实证：类注释写死「30 道工序 + 6 条 部位×工艺 路线」，库已变成 **35 道 / 9 条**后**注释不会跟着变**
     （读者按错数字理解代码）；docstring 里反引号引用的测试类名在仓内**零命中** ⇒ 读者会去找一个
     **不存在**的东西。已落码守卫 = `tests/unit_ci_workflows/test_declaration_truth_guards.py`，
     取**形态判据**（禁出现「N 道工序 / N 条…路线」形态；反引号引用的测试标识符必须**可在仓内解析**）
     而非"与源码等值"，且**每条判据都带注入式自证**（在构造的缺陷载荷上必须报错 —— 否则主测试的绿只是空跑）。
   - **为什么这条属本节**：它和 ①② 是同一个病（**读者拿到的是快照，却当成现值用**），
     只是快照的载体从"分支内容"换成了"文档里印死的数字"。

## 20. 批量修复的防复发纪律（R1~R7，v1.30 新增，2026-09-17 #4009 审计固化）

> **定位**：本节只给**判据 + 指针**（同理登记见 §19 表）——**加一节散文**本身就是「在事故点再加一道门」的元层面重演。
> **病灶实测**：引用数值必须连**口径 + 复算命令**一起给（同一量不同口径不可互换）；**未标口径的点值一律不写**（§19.2 ③）。
> 唯一带完整口径的实测：`git log -p -- .github/case-trust-baseline.json` 的 `violation_case_count` = **110 → 143 → 净缩 1 条后冻结**。
> ⇒ 定性结论：**防守性叠加与返工是实测形态**（`git log --oneline --since='<两周前>' -- backend/ai-agent-service/app/graph/skills/base_skill.py` 可见同一守卫的迭代式补丁）——修得越多越脆、门越加越胖。

| 判据（引用数值必须连口径 + 复算命令，见上） | 内容（一句话，要展开的按指针去那张表） |
|---|---|
| **R1 修机制不修事故点** | 判据问句：**这个缺陷的同类实例还有几个？≥2 就修机制**。若修法是「再加一道门」，**必须**给适用域声明 + 不适用域负例 |
| **R2 负例证据** | 必须证明「**没有拦掉原本合法的输入**」。反例：单价接地闸门为修错价而生，却把**正确库价也拒**（`OR-014`） |
| **R3 失败集只许收敛** | 本次相关用例的失败集**只许变小**；变大必须逐条归因，且不得算作"已修复" |
| **R4 禁止新增豁免** | 新违规只有**两个出口**：**本次修掉** / **开独立 issue**。基线只许缩短（同 §19.1 元规则） |
| **R5 禁止新增静默失效** | 四条形态：**声明无消费**（`terminal` 死契约）/ **靠中文措辞语料** / **无 `suggestion` 的 fail-closed** / **不会红的断言**（同 §19.1 形状判据） |
| **R6 净变更量报告** | PR 必报净行数；`app/**` 净行数目标 **≤0**（修机制常使实现**变短**） |
| **R7 前提必须新鲜** | 先 `fetch` 再判断；分支须基于 `origin/main`；行号带 `@<sha>`。反例：核交付物时**本地 `origin/main` 落后**，险些误判「搁浅」（同 §18.1/§19.2） |

**机械检查入口**：`./scripts/batch-integrate-check.sh <branch> [pr]`（批量 `--all b1 b2 …`）；R6/R4/R5/R2/R7 已落码，**R1/R3 未落码**（见脚本头部登记）。**尚未接 CI required check**——现为人工 / 集成环节调用，**不会自动拦人**。

## 21. 往返预算：步数才是计费单位（v1.37 新增 #4428；v1.38 补 P7 #4455）

> **定位**：本节只给**判据 + 指针**（同 §20 纪律，**不写散文** —— 加一节散文本身就是「在事故点再加一道门」的元层面重演）。
> **病灶实测**（会话 `session-35900f24-aa1c-42ae-b19b-e1798c6e80d2`，即 #4419「客户管理收货信息」这个**小需求**）：
> 墙钟 **46.3 min** / **279 步**，而**前台工具执行合计只有 8.1 min**、单个最慢命令 **16.6s**
> ⇒ **没有任何一条命令慢，慢的是往返次数**（279 步 × ~8s ≈ 38 min 是模型生成时间）。
> 最刺眼的一条：`read` 32 + `edit` 49 + `write` 6 = **87 次往返**，而三者执行合计只有 **1.7s**
> ⇒ 约 **12 min** 花在「逐点小步编辑」上。复算：`python3 scripts/roundtrip_report.py <该会话目录>`。
> **P7 的病灶实测**（会话 `session-cf73f497-3873-483b-bba6-be86ac8cdbd1`，即 #4443 那一单 —— **P1~P4 生效后的复测**）：
> `read`+`edit`+`write` 往返 **87 → 36**（占全部调用 27.5% → 16.2%）、往返比 1.13 → **1.19**
> ⇒ 小步编辑确实治住了；**但 7 次 `sleep N` = 684s = 11.4 min，占 bash 执行 42%** ⇒ 瓶颈**转移到了「等 CI」**。
> **口径**：模型时间 = 墙钟 − **前台**工具执行，是**上界**（后台 job 与模型生成**重叠**）⇒ **只用于排序让人去看，不是可引用的绝对数**。

| 判据 | 内容（一句话） |
|---|---|
| **P1 读要成批** | 动手前一次看完：一条 bash（`grep`/`sed`/`ls` 组合）或一步内多个 `read`；**禁止** `read`→`edit`→`read`→`edit` 交替 |
| **P2 改要成批** | 同一文件的多处修改放**同一步**的多个 `edit`；**>3 处或整体重写用一次 `write`** |
| **P3 查要合并** | 多条独立 `grep`/`ls`/`cat` 合成**一条** bash（`;` / `&&`），别一条一个 step |
| **P4 验证不来回** | 先**窄跑**定位、再**一次全量**；禁止窄跑 / 全量交替往返 |
| **P5 报分母** | 结论 / PR 里给「调用数 / 步数」比 + 各工具的**调用占比 vs 执行耗时占比**（数据来自 P6） |
| **P6 可判据** | `python3 scripts/roundtrip_report.py <会话 jsonl[.zst] \| 会话目录>` —— 报告型（指标再差也 `exit 0`）；**解析不出步 ⇒ 打印「不可判定」并 `exit 3`**（不得退化成一份看起来正常的账单） |
| **P7 等待不轮询** | 等 CI / 等后台日志**禁止 `sleep N` 轮询**（每次都是一轮往返 + 纯空等）⇒ 用 `gh pr checks <PR> --watch`（**一次阻塞调用**）；**首选丢后台 job**（完成时被通知，期间做别的）。判据 = 报告的「等待型调用」段（bash 的 `command` 匹配 `\bsleep\s+\d+`） |

**边界（照实登记）**：P1~P4 治「**逐点小步编辑**」（#4428 归因 ①）、**P7 治「等 CI」**（#4455）；**不改任何门禁的通过条件**；
`reasoningEffort` 全程恒定、改动面天然跨面、编号 / 基线是全局共享资源、每次验证全量 —— **仍不在本单内**（#4428 归因 ②③④⑤）。
**尚未接 CI required check** —— 现为人工 / 会话收尾时调用，**不会自动拦人**。
⚠️ **P7 只解决墙钟与往返，不解决「CI 本身 3-4 min」** —— 那不在本单内。

## 版本沿革（v1.1 → v1.38.1）

> 本节由 **v1.21** 从 frontmatter `description` **逐字迁入**（条目文本未改，仅加列表符号并按版本排序）。
> 背景：frontmatter `description` 是 YAML 纯标量，会在第一个「空白 + `#`」处**静默截断** ——
> 改动前原文 2666 字符，加载器实际只读到 192 字符，v1.12 之后的条目**从未**出现在技能目录里。
> 约定：**description 只放简短摘要（触发语 + 范围），沿革放本节点**；要给 agent 读到的规范必须写正文。

- v1.1：修正 Agent Eval 重试命令 + 新增 dependabot PR 处理 SOP + CI/本地环境差异已知坑。 
- v1.1.1：修正部署后验证端点。
- v1.2：新增「分支滞留+切换污染」红线与 git worktree 规范。
- v1.3（2026-09-04）：新增「多会话并发规范」（一会话一 worktree + 会话锁 + 端口隔离 + 分支卫生）、CI 队列治理（concurrency/paths 门控/agent-eval 按变更触发省真实 LLM token）、验证分级降本。
- v1.4（2026-09-05）：新增「PR body 必写 Closes #xx」红线（自动关 issue 闭环，杜绝修复后 issue 无人关闭的伪积压）+ 存量 12 个 open issue 中 8 个已修复未关闭的实证教训 + CI pr-issue-link 检查说明 + GitHub 治理自动化（stale 回收/automerge/dependabot ignore 收口）。
- v1.5（2026-09-06）：新增「§9 本地验证防恶化」——本地 .env 云库泄漏致 pytest 从分钟级恶化到小时级的根因复盘（issue #2957，quick 58min→57s）+ 体检命令 + 六条防复发红线（云库隔离/timeout 兜底/依赖漂移/未 mock 外部调用禁止）。
- v1.6（2026-09-06）：新增「§10 云资源运维（aliyun CLI 自服务）」——AI 具备阿里云运维权限账号能力（本机 aliyun CLI 已配凭据），可直接自服务 RDS 白名单/实例查询，无需人工控制台操作；固化实例 ID、白名单分组、追加命令与安全边界（保留原 IP 追加而非覆盖）。
- v1.11（2026-09-09 issue #3070 复盘固化）：新增「§15 前端页面级改动的 UI 旅程强制验证」——交互测试断言"结果可见"而非"函数被调用"、页面级改动必须真实浏览器走查（面包屑/样式基准/布局遮挡几何探针/写操作成果物可见）、布局视觉问题不得仅靠 vitest（Tailwind p-* 覆盖 pb-* 类 CSS 级联陷阱实测）。
- v1.12（2026-09-09 issue #3080 实证）：新增「§15.5 截图视觉确认」——主模型/子代理不支持图片输入（read_image 报 does not declare image input）时，用 workflow 自动路由到 GLM-5.3-Flash 视觉模型（scnet-token-plan）开子代理读图判定，输出作为 UA 层证据，与 DOM 断言互补。
- v1.17（2026-09-14 issue #3555）：新增「§14.5 覆盖厚度」——把覆盖体检变成真门禁：C 端 `scripts/xiaobu_coverage.py` 判据收紧（**每个被覆盖的工具必须至少有一条正向用例**，「只有越权/拒绝用例」= 结构性缺失 → 阻塞；「仅 1 条用例」= 厚度不足 → 只报告，尊重 verify-all.sh 的活指标设计意图）+ 新增 B 端对称体检 `scripts/mibao_coverage.py`（复用 eval_case_filter/render_cases 既有纯函数，不复制平行实现）+ 接入 CI pr-check `Case Coverage Gate` job（纯静态零 LLM，本脚本与本地 verify-all.sh 同参数）。
- v1.18（2026-09-14 实证固化）：新增「§16.6 评测派发与数字留痕」四条踩过的坑——① 手动 `workflow_dispatch` 评测**必须**带 `-f force_eval=true`（否则被静默抑制：步骤全 skipped、artifact 0、整体 success；workflow 注释里的"永不抑制"与实现不符）〔⚠️ **该条已被 v1.20 修正**：现在 dispatch **默认免抑制**，要抑制才需显式 `force_eval=false`——勿照抄本条〕；② `case_ids` 是**全矩阵共享**的，只传一端专属 ID 会让另一条腿立即红（`local_runner.py` 的「`禁止静默少跑`」守卫 —— **按该守卫文本检索，行号会漂移**）；③ `continue-on-error` 让 `Run <persona>` 步骤"显示 success ≠ 成功"，读结论只看 `判定（completion_verdict）` + artifact；④ **每个计数必须锚定 SHA**（`基线 @<sha> = N → 本 PR = M`），禁止旧基线配新结果造出幽灵 delta。
- v1.19（2026-09-14 实证修正）：**§2.1 ②`./verify-all.sh gate` 必须在 `git commit` 之后跑** —— 它的弱断言检查按 `git diff --diff-filter=A origin/main...HEAD` 取"新增测试文件"，**未提交时新增集为空 ⇒ 静默空跑并通过**（假绿；实测同一命令 commit 前 ✅ / commit 后 ❌）。正确顺序：先 commit，再跑 ②③④。
- v1.20（2026-09-15 实证修正，issue #3709）：**修正 §16.6 ①**——`workflow_dispatch` 评测**默认免抑制**（要恢复「被取代即抑制」须**显式**传 `-f force_eval=false`），故 v1.18 那条「手动派发**必须**带 `-f force_eval=true`」已成**假真值**；被抑制时 run 上现在有 `::warning::` 标注 + summary 抬头「本 run 未评测」，**据此不得再把「绿」读成「评测通过」**；自动门禁（workflow_run/schedule）语义不变。并在 §2.2 补「引用式 `Closes` 样例同样会被朴素正则命中」的自检提示（PR body 证据表是同一入口）。
- v1.21（2026-09-15 实证修正，本次）：**修掉 frontmatter `description` 被 YAML 静默截断**（纯标量在第一个「空白 + `#`」处截断）——实测原文 2666 字符仅解析出 192 字符，v1.12/v1.17/v1.18/v1.19/v1.20 的说明**从未**被 skill 加载器读到。取舍：`description` 收敛为**有意简短的摘要**，**沿革迁入正文本节**（不靠加引号救长文本，避免「可无限追加」的坏习惯复发）；并登记「加载器只读 `name`/`description`，且要求第 1 行是 `---`」。
- v1.22（2026-09-15，本次）：**§16.6 新增第 5 条「重放要说明是否复现了缺陷的前置条件」** —— 由 PR #3746（OR-014 改价不落 SKU）实证：`case_ids=OR-014,AS-004` 把制造分叉的 `PR-010` 排除在外 ⇒ R1 读到种子值 `price=168.0`（而红时 `198.0`）⇒ 新增分支从未被行使，那次绿**不构成判别性验证**。判据 = 给出前置条件观测值；未复现须如实标注并以确定性层证据兜底。形态与治法详见 `migao-acceptance` v1.7。
- v1.23（2026-09-14 用户裁定固化，本次）：新增「**§17.4 批量合并 + 统一验证**」—— 病根是「每个包各自验证、各自合并」（互抢全局串行评测资源 + 窄重放被全量档覆盖 + 等待期空转）；三条范式：等待期批量化 / 评测是全局串行资源（多包不得并发派发；`cancelled` 的 run **不是结果**）/ 窄重放降级、优先「合并后一次全量评测」（全库 ⇒ 天然覆盖「缺陷由另一条用例制造」的前置条件）。附统一验证清单与**代价边界**（批合并粗化归因 ⇒ 同主题分批 + 失败按提交序二分 + 单个 PR 的 required 门禁照旧；行为/契约耦合必须同批，高风险独立改动单独一批）。
- v1.24（2026-09-14 用户裁定固化，本次）：新增「**§16.7 评测流程：该跑什么、不该跑什么**」——按「这次要回答什么问题」选档（PR 映射用例 / 合并后一次全量档 / 里程碑结论档），派发前不重复派发、派发后**不要在建栈中途取消**（实证 run `34855662092`：`Buildx` success → `Start local stack` cancelled → `Seed`/`Run`/`Upload` 全 skipped、`判定` = failure）、读结论时分类与放行分开、成本可见（只定口径）、合并后一次统一验证（§17.4）；末尾加**引用纪律**两条（不给活跃文件裸行号 / 引用必对 `origin/main` 读）。同时修正 §16.5 门禁矩阵两行过期口径：smoke 层**已移除**（#3653）、映射用例门禁**两层均非 required**（`rules` = 强信号：报告+评论+开 issue 但不拦合并；`default_net` = 只报告不开 issue）。
- v1.24.1（2026-09-14，本次）：**统一引用写法** —— 行号一律「第 N 行」（可带 `@<sha>`），不再写 `path:NNN`：后者会被模式扫描误判为「残留引用」，也容易被读者误当现值照抄（本轮 `4292` 的扫描命中即此类）；连带把「记录旧值」的示例也改成非 `path:NNN` 形式。
- v1.25（2026-09-14 用户裁定，本次）：§16.7 追加「**禁空跑 / 验证的边际信息量**」三条 ——① 过筛（两种结果不改下一步 ⇒ 不跑，记为「未跑」而非通过）；② 同一判定点只跑一次（判定走分层全库，`case_ids` 只作定点复现且标注非判定用途；结论按 `(SHA, tier, 用例集指纹, runner 策略版本)` 复用）；③ 跑之前拦（变更集为空 ⇒ 打印 `⏭️ …未跑`，**「没跑」必须长得像「没跑」**）。
- v1.26（2026-09-15 **入册 #3770 已落码的口径**，本次）：把此前只活在代码/注释里的三条派发口径写进规范 ——
  ① §16.6 **新增第 6 条「派发前先查槽位」**（`.github/scripts/eval_slot_status.sh`：`0` 可派 / `2` 被占用 ⇒ **不要派发** / `3` 无法判定且**不谎报空闲**；理由 = 全局槽位稀缺，并发派发互相饿死/互杀，实测一个窗口 10 连 `cancelled`）；
  ② §16.7「派发后」把「`cancelled` 的 run 不是结果」升级为「**不是结果、也不再被记成失败**」（判定补 `!cancelled()`、建 issue 去掉 `|| cancelled`、新增「被取消记录/留档」+ summary 抬头「本 run 被取消（未评测，不构成结论）」），并**修正过期表述**（原文写该 run 的 `判定 = failure`，那是 #3770 前的行为）+ 给出**引用前必核三条**（结论已出 / 未被取消 / 未被抑制）；
  ③ §16.7「禁空跑」的 ②③ 由「待落地」改为**已落码锚点**（`eval_dispatch_guard.sh`：A `exit 1` 拒派收窄判定 / B `run_key` ledger 命中即 `exit 2` 不重复跑 / C 变更集为空 ⇒ `⏭️ …未跑`），与 §16.6 ⑥ 互相链一句、不重复表述。
  ④ **`tier` 的语义边界**（同族：会误导的文档真值）—— `local_runner` 按 difficulty 分档、三档互斥，
  故 `tier=normal` **只跑 NORMAL 档**（不含 SMOKE/ADVERSARIAL）：§16.7「禁空跑」② 的「全库」已就地注明
  「**该档**全库 ≠ 覆盖全部用例」，`post-deploy-eval.yml` 的 `tier` 输入描述同步由「normal（全量）」收紧为
  「normal（**只跑 NORMAL 档**全量；不含 SMOKE/ADVERSARIAL）」+ 紧邻注释登记边界（**只改描述/注释，默认值仍 `normal`**）。
  同时清掉 `.github/workflows/agent-behavior-eval.yml` 注释里「AS-007 已 `skip_reason` 非空」的过期举例（实测 `skip_reason` 为空、米宝端照跑；小布端选不中是**工具集**口径而非 skip）——**只改注释，不动 `unrunnable` 过滤逻辑**。
- v1.27（2026-09-15 **补今晚实操暴露的 4 条缺口**，本次）：
  ① **§17.4 新增「判定跑在飞期间冻结合并」** —— 判定跑在飞时不往 main 合新东西，增量**并到下一批**；
  已落增量 ⇒ 结论**必须写明 verdict 覆盖到哪个 SHA**（`run_key.sha`）并标注「其后增量未经全库验证，
  仅确定性层 / 单测层覆盖」，**不得**说成「当前 main 的结论」。
  ② **§16.6 ② 补强**：`case_ids` 是**逐 ID 校验**、**配对不能豁免**（run `34907040543`：`OR-013` 只在
  mibao 腿 ⇒ xiaobu 腿 `禁止静默少跑` 红）⇒ **单端专属用例不存在「两腿都干净」的 `case_ids`**，
  端点证据优先靠**合并后一次全库跑**；确需窄跑须显式标注「收窄副作用、非回归」并去被自动评论的 issue 澄清；
  关联 **#3822**。
  ③ **§16.7 新增「口径收紧后怎么读变红」**：放行 / 分类口径收紧后失败数上升是**设计效果**，
  读结论必须把「本次新引入」与「原本被放行的系统性缺口现形」**分开标注**，**不得**归因到当批改动；
  收紧前先复算「多少条放行被改判」并**留档（锚定 SHA + 条数）**作对照基线。
  ④ **§16.7 新增「证据等级不得越级」**：要「值相等」级结论先确认 runner 是否落盘 tool args，
  **不得**用 `required_args`（存在性）或 `score` 顶替，现行缺口见 **#3823**——与 `migao-acceptance`
  「证据层假绿」互链、不重复其表述。
- v1.28（2026-09-15 **issue #3843 六层实测固化**，本次）：新增「**§18 单一真相源与不可变引用**」——
  把「**读的是快照 / 按可变键定位被测对象**」这条**返工主机制**写成可执行判据（八小节）：
  ① §18.1 **读源纪律**（真值一律 `git show origin/main:<path>`；**落后工作副本 ≠ 真相**；禁裸行号 `path:NNN`，
  行号一律「第 N 行」+ `@<sha>` 限定；附自证扫描）；② §18.2 **活锚新鲜度**（`~/.dsh/.agent-presets/migao`
  vs 仓库 `.agent-presets/**` 的**内容级** diff；**落后即先同步再动手**；实证活锚落后 **25 个提交**、零检查）；
  ③ §18.3 **不可变引用**（`pre_clean`/`db_verify`/断言定位必须用 `order_no`/`phone`/`id`/用例自建唯一名；
  名字 `*_keyword` / 位置 `customer_index` / 序数 `auto_select` **只允许出现在用户输入里**；`CU-003` 实证）；
  ④ §18.4 **前置自断言 + fail-closed**（`PG-013` 首跑改世界 / `CU-003` 同名 upsert 两条因果链）；
  ⑤ §18.5 **账本新鲜度**（生成物重渲染 + diff；「账本里看不出来的字段 = 缺陷的盲区」，`pre_clean` 曾不渲染；
  扩容到覆盖率矩阵 + flake 索引）；⑥ §18.6 **环境静默即缺陷**（`schedule:` 工作流长期无成功跑当缺陷开单；
  `nightly-verification` 连红 9 天零 issue 实测）；⑦ §18.7 **活环境测量快照**（断言无部署在飞 + 记被测 SHA；
  `Deploy Reconcile` 1~3 分钟 502 窗口）——**详版按"同一口径只放一处"写在 `migao-acceptance` v1.9**，本节只留指针；
  ⑧ §18.8 **反模式清单**（把"我确认过是新的"这类自觉换成工具/检查）。
  **机制现状照实登记**：A~H 护栏**多数尚未落码**（仅 §18.5 的 `pre_clean` 渲染一格随 `#3836` 已落），
  未落码条目按「人工可执行检查」对待、发现违例必须开 issue —— **不得读成"有硬门禁"**。
  本节位置：追加在 §17 之后（不改编号，避免打断 `AGENTS.md` 铁律 6 与 `migao-acceptance`
  「验收问题的并行分流」对 §17 / §17.4 的既有引用），并在正文开头加了 §18 指路。
- v1.29（2026-09-15 **范式沉淀 + enforcement 锚点入册**，本次）：把本轮验证过的一批范式**做成索引**并
  补齐三处缺口 ——
  ① **新增 §19「范式总纲与 enforcement 锚点」**：一张 **8 行**索引表（范式 → 判据一句话 → 落码锚点 → **现状**），
  含**未落码项**（`scripts/drift_audit.py` 统一审计、心跳检查、§18 多数护栏、归因纪律）——
  **照实登记，不把"写进技能"写成"有门禁"**（沿用 §18 开头口径）；表下一句"判据只在落码锚点那格"防第二份口径。
  ② **新增 §19.1 断言可信度（假红 / 假绿的结构性护栏）**：四条形状判据
  （写类须有效果层断言 `#3778`/`#3559`/`#3845`；自清理 + 点名可解析 `#3794`/`#3800`/`#3832`；
  散文禁令不单独承重 `#3833`；单端标 persona `#3822`）+ **两条元规则**（存量基线只许缩短 +
  未实装项显式登记；**基于错误真相模型写出的护栏 = 永远红 / 永远被豁免的空判据**，
  附本会话"`DEV-FLOW.md` 与 `SKILL.md` diff==0"那条空判据的实证：971 行 vs 230 行、v1.3 vs v1.27，
  正确判据是**版本戳一致性** + 副本 claim 要么由权威源生成、要么撤回）；判据源单点 =
  `.github/assertion_taxonomy.py`（**#3842** 已落码：门禁 + 基线 + 未实装登记）。
  ③ **§16.7 补两节**：「**结论的构成与读法**」——`ok` = **五类**阻塞桶全空
  （`deterministic` / `journey` / `systemic` / `restore` / `harness_incompatible`，**不是三类**，
  别把后两类漏在视野外；放行集当前只有 `llm-noise`）；结论须按桶分解、收紧口径后"新引入 vs 原放行现形"分开标注、
  每条失败有归因、值级不可闭合时只给存在性级；实证 `34908262839` = 2 条用例资产缺陷
  （`PG-013`/`CU-003`）+ 4 条原被放行的系统性缺口现形。「**成本与验证顺序纪律**」——
  先窄跑后全量、窄跑走**单腿入口**（`xiaobu-acceptance.yml` 的 `persona` 输入，因 `case_ids` 逐 ID 校验
  ⇒ 另一腿必红，`#3822`）、评测槽位**串行是设计**、产品因未修不跑判定跑、**不为变绿调阈值**（`#3840`）。
  ④ **§17.4 补「结论的 fencing」**：完整形态 = 绑定 `(sha, tier, case_ids, cases_fingerprint,
  policy_version)` **+ 环境指纹 / 种子哈希**（机读形态 = artifact 的 `run_key`，实测 `34908262839`），
  版本一动结论失效；活环境判定**不得与部署重叠**（`Deploy Reconcile` 在每个 PR 打开时重建容器
  ⇒ 1~3 分钟 502 窗口，`#3840` 用"部署清空后的干净跑"做证伪检验）。
  ⑤ **§18.6 补 18.6.1 enforcement 锚点**：「凡调 issue API 的 workflow 必须声明 `issues: write`」已落码
  （`tests/unit_ci_workflows/test_workflow_issue_permissions.py`，**#3838**，`42 tests collected`；
  **读 YAML 真值不扫正则** + 每条断言有红证）—— 病根实例：一次最小权限加固**收窄 28 个 workflow、
  只补回 1 个** ⇒ `nightly-verification` 连红 9 天零 issue、`agent-eval-adversarial` 静默至 08-29、
  `fixture-record` 历史 0 条；**并明写"心跳检查仍未落码"**，防"权限守卫已落码"被读成"静默已被挡住"。
  ⑥ **`migao-acceptance` v1.10 新增「归因纪律」**（该技能是"下结论前必加载"那本）：归因强度匹配证据强度
  （"不可满足"级断言需"任何合法行为都无法满足"的证据 —— 本会话据"种子无该标签"推断 `CU-003` 物理不可满足，
  被反例 run 推翻：agent 把该词**拆成两个真实标签**并 `add_tag` 成功，真因是**前提随并行污染漂移**）；
  双侧禁令；跨 run ≠ 同因（`OR-014` 三个 run 三种机制）；独立复核可推翻主会话初判（本会话 2 例）。
  **位置**：§19 追加在 §18 之后、版本沿革之前（沿线性的"章节顺序 = 叙事顺序"）；§19.1 与 §16.7 的分工 =
  §19.1 管**形状判据（静态可判）**，§16.7 管**读法与顺序（运行期纪律）**，互链不重复。
  ⑦ **追加三条"静默失效"范式**（用户追加要求，均为当轮实测 + 有同款复发史）：
  - **§17.3 新增反模式行 + 「三件事」段**：`auto-merge 秒合`吞掉后续 commit ⇒ **CI 绿 ≠ auto-merge 就绪 ≠
    交付物在 main**；机械核法 = `git show origin/main:<交付物路径>` 看**内容**（commit 可达性不是判据）；
    **搁浅检测** = PR 声明的关键交付物逐条在 main 上核，缺任一 ⇒ 未交付 ⇒ 开跟随 PR（不给已合并分支追加 commit）。
    实证：**#3842 被秒合 ⇒ 3 个 commit 搁浅**（main 上 `assertion_taxonomy.py` 仅 **6 条规则**、L0 守卫 **40 条**
    —— 均命令自证，勿记数字；缺 `CASE-TRUST-VOLATILE-LOCATOR` / `NO-PRECONDITION-ASSERTION` / `STALE-LINE-REF`）
    ⇒ 跟随 **#3847** 补齐；更早同款 **#3819 → #3826**（同款第 2 次）。
  - **§2.3 新增第 7 条**：worktree 里的 `.agent-presets/` 是**创建时快照**（`dev-worktree.sh` 实测**不刷新也不排除**）
    ⇒ `git add -A` 会**静默回退研发模式**；判据 = 动 `.agent-presets/**` 的 PR 必须核**版本不降级**
    （worktree 侧 vs `origin/main` 侧）+ `git diff --cached -- .agent-presets/` 出现版本回退 ⇒ 拒绝提交。
    ⚠️ **本条里「不刷新也不排除」已被 v1.35 改判**：`add` 路径**已自动刷新**（`refresh_presets()`，v1.8 / **#3851**）
    —— 地雷结论（快照会落后 / `git add -A` 会静默回退）保留，**该子句勿照抄**。
  - **新增 §19.2「交付与账本的新鲜度：三条静默失效的形状」**（① 交付物搁浅 ② worktree 预设快照
    ③ **不写死易变数字**：只给检索命令 + `@<sha>` 限定实测值；反例 = 同一量先写 **14** 实测 **13**、
    先写 **19** 实测 **11**；正例见 §18.6 的"命令自证，别记数字"）；§19 索引表随之扩到 **11 行**；
    §18.5 加指针（不重复展开）。
- v1.30（2026-09-17 issue #4023，本次）：新增 **§20「批量修复的防复发纪律」（R1~R7 判据表 + 机械入口）** —— 把
  「修机制不修事故点 / 负例证据 / 失败集只许收敛 / 禁止新增豁免 / 禁止新增静默失效形态 / 净变更量报告 / 前提必须新鲜」
  写成**表格式判据**（**只写判据 + 指针，不写散文**——加一节散文本身就是"在事故点再加一道门"的元层面重演）；
  配套落库 `scripts/batch-integrate-check.sh`（R6/R4/R5/R2/R7 已落码，**R1/R3 未落码**照实登记在脚本头部）；
  §19 索引表随之扩到 **12 行**。**修脚本时实证**：比较必须用**两点** `base..branch`（合入后 base 变什么样），
  **不是三点** `base...branch`（merge-base 为左端 ⇒ 只是"本分支相对 fork 点改了什么"）——三点会把
  **别人已修好的算成本分支的功劳**（`p5-bend-order-assertions` 实测：三点说"移除 4"、两点如实"净变化 0"）。

- v1.30.1（2026-09-17 **活锚自愈 + 开工自检落码**，本次，issue #4026）：把 §18.2 从「人工核对」升级为
  **可执行判据 + 自愈**（本条只加指针，不改 §18.2 的口径）——
  ① 新增 `scripts/preset-anchor-check.sh`（红就停）与 `scripts/preset-anchor-refresh.sh`（自愈），
  判定本体落在 `scripts/agent-presets-guard.py` 的 `anchor` 子命令，`./scripts/dev-worktree.sh preset-guard`
  也带上这一段（提交路径同样拦）；
  ② 判据 = **内容逐字节 + 检出 sha + frontmatter 可加载性**（三态照实读：落后/悬空/内容不同/技能加载不了 = 红；
  `⏭️ 未跑判定`（本机没接线、或活锚与本仓库不同上游）**不是「通过」**）；
  ③ **活锚必须指向专职只读镜像**（独立克隆），不是任何会被开发/会被 `rm -rf`/`worktree prune` 命中的工作区：
  实测活锚曾指向落后 `origin/main` **42 个提交**的主工作区（内容当时恰好一致 ⇒ **下一次改预设的改进
  永远到不了加载点**，即「迭代了但模式没进化」的确切机制）；同族事故 `#3956`（软链目标被误删 ⇒
  DSH 研发模式**静默**消失）。根 `AGENTS.md`「开发环境准备」的换链拓扑同步修正（原写法教人指向工作区，`#3849` 登记）。
  修本条时实测踩到两个**判据自己选择沉默**的形态并已固化进测试：比 `git config --get` 的**原始** URL
  （`insteadOf` 让同一仓库出现 `https://github.com/…` / `ssh://git@ssh.github.com:443/…` 两种写法 ⇒
  真活锚被**静默跳过**）、以及只比对象级「锚点检出里有没有基线提交」（锚点**还没 fetch** 时被判「不同历史」
  ⇒ 落后**不红** —— 而这恰恰是本单要治的形态）。
- v1.31（2026-09-17 **issue #4034（P13）落地口径入册**，本次）：把「**关闭 PR 层真实 LLM**（裁定 2′）+
  **LLM 发现 → 确定性下沉**（裁定 4′）」写进技能，并**改判三条已失效的口径**：
  ① §16.5 门禁矩阵的「PR 改 AI 行为文件 → 映射用例迭代档（独立栈跑 + PR 评论 + 规则命中失败自动开 issue）」
     **已停跑** —— `agent-behavior-eval.yml` 的评测 job **整体删除**，PR 上只留**零 LLM 的映射信号**
     （diff → §13.2 用例集 + 打印"要跑就派发单一入口"的命令）；代价（PR 阶段无 LLM 行为信号）用户已知并接受；
  ② 同表「映射用例门禁红 ≠ 不能合并」一段随之改判（PR 上不再有"红"可言），并写明**真正的拦截面现在是确定性层**；
  ③ §16.7 的门禁矩阵行同步（PR 阶段要真结论 ⇒ 手动派发 `post-deploy-eval` + `purpose=debug`，非判定用途）；
  ④ **§13.3 新增 LLM 红例红线**：LLM 红例必须下沉为 ≥1 条确定性断言（`must_succeed`/`db_verify`/
     `amount_verify`/`output_verify`/L0 不变式），否则不算闭环；台账 = `.github/llm-finding-ledger.json`，
     机械检查 = `python3 .github/llm_sink_check.py --issue N`（0/1/3 三态），未下沉必须显式登记
     （`unsunk` + reason + follow_up）。~~**定时档全部保留**（3 天 normal / 每周 adversarial ×2）~~——
     裁定要砍的是 **PR / 合并 / 迭代**触发，不是定时档；防回退锁 =
     `tests/unit_ci_workflows/test_behavior_eval_pr_thin.py`（PR 零 LLM + 自动 LLM 触发白名单）。
     ⚠️ **上面这句「定时档全部保留」已被 v1.33 / #4262 改判**（见版本沿革末条）：自动 LLM
     触发由 3 条收敛为 **1 条**（只留 `post-deploy-eval` 每周一），两条每周 adversarial 定时删除。
     防回退锁同步收紧为「白名单 = 1 条 + 反向断言其余为空 + 周级 cron」。**勿照抄本 v1.31 条**。
  详版：`docs/testing/llm-finding-sinking.md` + `docs/testing/eval-environments.md` §3.7。
- v1.32（2026-09-17 **issue #4065 落码入册**，本次）：§17.3「交付物搁浅」由**仅纪律**改为**已落码** ——
  `scripts/stranding-check.sh`（内容级：以 PR 在 main 上的**合并点**为锚 + 从**远端分支 ref** 看「合并后是否还有 push」；
  三态 `0/1/3`），接入 `scripts/batch-integrate-check.sh <branch> <pr>`；§19 表「交付物搁浅」那一行的「现状」列同步照实登记
  （**未接 CI 门禁**，人工/集成环节调用）。
- v1.33（2026-09-18 **issue #4262 用户裁定：评测自动触发 3 条 → 1 条**，本次）：用户实测
  「没在用官网 key 编码，9/17 约 ¥30+、9/18 约 ¥65 仍在花」⇒ 排查确认**费用主体是 CI 真实 LLM 评测**，
  且实际消耗**不是定时档而是 agent 自动派发**（9/17 CST 2 次 + 9/18 CST 8 次 `post-deploy-eval`
  全量，全是 `workflow_dispatch`，来源 = DSH 会话里反复执行的派发命令；两天累计 **1205 场**真实多轮
  LLM 会话，单次 ≈ mibao 84-90 + xiaobu 36-39，按 artifact `run_key.executed_count` 实测）。
  裁定：「**不要自动进行验证，都是重复的验证，白白消耗成本**」「**手动集中跑一次即可**」
  「兜底定时**改成每周自动跑一次**」。本次落码：
  ① **§13 改判**（本条是核心）：行为改动的评测体检由「提交前自动跑、不等用户要求」改为
     **「默认不跑、不派发 workflow；只做零成本的映射清单；仅用户显式要求时一次集中跑」**
     —— 旧口径 v1.9 已作废，照抄 = 把用户买下的账又花一遍；配套改 `.agent-presets/migao/agent.cordis.yml`
     （系统提示词，两处）与仓库 `AGENTS.md` 同族表述。
  ② **自动 LLM 触发 3 条 → 1 条**：`post-deploy-eval` 由 `0 3 */3 * *`（每 3 天）收紧为
     `0 3 * * 1`（**每周一** 11:00 CST）；`xiaobu-acceptance` / `agent-eval-adversarial` 的每周
     `schedule` **删除**（改仅手动，对抗覆盖未消失、只是不再由 cron 付费）。
  ③ **`verify-trigger` 自动验收停用**：删 `schedule: */30` + `pull_request_target` +
     `pull_request`，仅留 `workflow_dispatch`（手动对账）。代价已知并接受：合并 PR 不再自动入
     `ai-verify/*` 队列；#3608 的「恢复自动触发必须用免疫 GITHUB_TOKEN 抑制的触发源」教训**保留**在
     文件注释与守卫测试里（不是作废，是恢复时的前置条件）。
  ④ **守卫同步**（三处，均带红证）：`test_behavior_eval_pr_thin.py` 白名单收紧为 **1 条** +
     新增「其余 LLM workflow 自动触发必须为空」+「数量恰好 1」+「cron 必须周级」；
     `test_verify_trigger_chain.py` 改判为「仅手动」；`test_xiaobu_adversarial.py` 的
     `test_workflow_has_weekly_schedule` 改判为「仅手动」，并**保留** #3367 的档位特判守卫
     （删了它 → 将来恢复定时会落到默认 smoke，原样复发）。
  ⑤ **未实装 / 边界（照实登记，§19.1）**：`verify-trigger` 的手动对账**不烧 LLM**（它只贴标记/
     打标签），故本次停用它是为「去重复验证」而非省 token；**agent 侧"不再自动派发"目前只靠
     指令（提示词/技能）约束，没有机械锁** —— 机械锁只能拦 workflow 触发面，拦不住 agent 主动
     `gh workflow run`。防这条的唯一现实手段是用户裁定 + 本技能口径；若再观察到自动派发，
     按「新增自动 LLM 花费」开单处理。
- v1.34（2026-09-18 **同步本批「判据/门禁自身缺陷」的已落码口径**，本次）：本批 12 条
  （**#4239 / #4245 / #4244 / #4233 / #4221 / #4260 / #4247 / #4231 / #4158 / #4259 / #4226 / #4249**）
  此前只活在代码与 PR 描述里，**技能口径已过期或缺失** —— 本次把**已落码**的口径搬进本技能
  （按 §20 纪律：**只写判据 + 指针，不写散文**）：
  ① §2.2 case_ids 硬约束拆成 **A 位置 / B 形态**：只认**注释起始的声明行**且**首个命中即停**，
  docstring / 正文里「提及」不算声明 ⇒ **旧时代"靠改措辞规避门禁"的 workaround 已失效，不要再教**（#4239）；
  ② §16.7 桶表 + §19 表：`ok` = **六类**阻塞桶全空，新增 `case_asset_failures`
  （`precondition_not_applied` 族 ⇒ 该用例红/绿**不可归因于 agent**、**仍阻塞**、**不再进**前三桶）（#4245）；
  ③ §19.1 a1/a2 **计分通道分流**：`[backend-contract]` 用例的计分通道 = `traces.tests`
  （非空且引用文件真实存在）⇒ 不再逼出「改散文形态、运行期零变化」的**纸面修复**；
  **非**该类的纯散文用例**仍报**，其余规则**一字不放宽**（#4244）；
  ④ §19.1 元规则 ① + §19 表新增**第 13 行**：**豁免账本按类分流** —— `skip_total` 不作增长分母；
  增长只判**债务类**（`debt_skip_*`，只许缩）；`[backend-contract]` 单列**只增**合规清单；
  `_when_to_update` 与门禁例外条款**口径合一**（#4233）；
  ⑤ §1 三把工具表 + §2.1：`gate` 在变更集命中受管用例面时**额外**跑 cases 面门禁
  （**同脚本同参数调用、不复制规则**），**未命中 ⇒ 显式打印「未跑」**（"没跑"必须长得像"没跑"，不是通过）（#4221）；
  ⑥ §19.1 新增元规则 ③ **红证卫生**：注入**前后清缓存** + **内容指纹**自证（**禁 mtime/size**）；
  macOS 上 `.pyc` 可落 `~/Library/Caches/com.apple.python` ⇒ 仓库内 `rm -rf __pycache__` **可能是空操作**（#4260）；
  ⑦ §18.5：`drift_audit` 的 `refs-are-fixtures` 例外在「**同文件里有已入基线的引用条目**」时**不再崩**
  （原 `KeyError`），改为产出**可行动**的 stale 报告（#4247）；
  ⑧ §2.2 + §3.3 **判定信号入册**：「CI 全绿 + `mergeable=MERGEABLE` + 无阻塞 label + 却
  `mergeStateStatus=BLOCKED`」⇒ **首查未解决评审线程**（`required_conversation_resolution` 让机器人留下、
  且**已被后续提交解决**的线程**永久卡合并，且没有任何检查会变红**）；锚点
  `python3 scripts/resolve_stale_bot_threads.py <PR>`（三态 `0/1/3`、**默认 dry-run**、
  **人类线程永不自动 resolve**）（#4231）；
  ⑨ §8 表：测试产物**定位与清理**纪律 —— 路径**必须由被测系统给出**或限定在测试自己的临时目录；
  🔴 **禁止 `/tmp/verify-all-*-*.log` 这类全局通配清理**（跨会话假红）；定位失败必须**明确报红 + 给全现场**；
  落码锚点 = `tests/unit_ci_workflows/test_verify_all_log_scope.py` 的 `run_gate()`（PID 通配 ∩ 归属过滤）（#4158）；
  ⑩ §19.2 ③：**注释 / docstring 里的数字与 `Test*` 标识符引用也会腐烂**；守卫 =
  `tests/unit_ci_workflows/test_declaration_truth_guards.py`（取**形态判据**而非"与源码等值"，且带注入式自证）（#4259）；
  ⑪ §15.1：商家冒烟**判据自身**三条纪律（**不猜单号前缀** / **豁免必须结构化** / **等元素而非定长 sleep**）（#4226）；
  ⑫ §15.5：视觉基线新鲜度 —— **构建绝不写进 `webServer.command`**（放配置加载期）
  + `reuseExistingServer: false` + **内容指纹**产物新鲜度护栏；旧的"构建与起服务混写 + 本地复用"
  会让基线被写成**旧画面**且不报错（DOM 断言恰好还绿 ⇒ **永久假绿**）；
  落码锚点 = `tests/xiaobu_dist_freshness.py` + `tests/playwright.xiaobu.config.ts`（#4249）。
  **落码状态照实登记**：本批 12 条**均已落码**（⑨ ⑫ 的落地 PR `#4296` / `#4294` 在本版定稿时合入；
  先前写成"未落码"的那一稿是按当时 `origin/main` 的真实状态写的，已随本次同步改判）。
  `migao-acceptance` 同步 +0.1.0（v1.12：**六桶口径** + **红证卫生**）。
- v1.35（2026-09-18 **同步本批「判据/门禁/流程自身缺陷」8 条的已落码口径 + 改判一条过期条目**，本次）：
  本批 8 条（**#4232 / #4235 / #4207 / #4248 / #4313 / #4315 / #4311 / #4310**）此前只活在代码与 PR 描述里，
  **技能口径已过期或缺失** —— 本次把**已落码**的口径搬进本技能（按 §20 纪律：**只写判据 + 指针，不写散文**）：
  ① **§2.3 新增第 8 条**：**临时文件也是共享面** —— `/tmp`（含 `$TMPDIR`）是跨会话共享写路径，
  PR body 一律用 `python3 scripts/pr_body_guard.py new` 落**本工作区忽略目录**，**禁共享根下固定名**；
  四子命令 `new`/`check`/`verify`/`scan` + 三态 `0/1/3`；⚠️ **`check` 对 `$TMPDIR` 下的 body 是硬命中（exit 1）**（#4232）；
  ② **§18.5 + §19 表新增第 14 行**：**迁移不可变** —— 种子追加走**新迁移**（改已应用迁移被按**文件名**整份 skip
  ⇒ **CI 全绿、功能静默缺失**）；种子守卫**按集合聚合**（按内容发现 `INSERT INTO <table>` 的迁移，不再写死 V54）；
  护栏 = `tests/unit_ci_workflows/test_migration_immutability.py` + 账本 `migration_fingerprints.json`，
  **新增迁移必须同 PR `--write-ledger` 登记**（只新增；已登记文件被改 ⇒ exit 1 **拒绝重生成**）（#4235）；
  ③ **§16.7「结论的构成与读法」**：**阻塞条目分两组呈现** —— `must_fix_failures`（阻塞 ∧ `score<1`）/
  `blocked_but_passed`（阻塞 ∧ `score≥1`，**在 `passed` 里、不在失败清单里，却阻塞 `ok`**）；
  `reason` 与 summary JSON 的 `completion` 都带这两键 ⇒ **按"未通过清单"数条数会系统性少算**（实证 xiaobu 少算 2 条）（#4207）；
  ④ **§2.2 + §3.3**：**裸判据差集**元判据 = `python3 scripts/merge_gate.py --required-diff`（数字用命令自证，**不写死**）；
  判红落闸 = `python3 scripts/merge_gate.py --check <PR> --apply-label`（**默认同时 disarm**）；
  🔴 **`block/merge` 标签拦不住已 arm 的 auto-merge** —— `automerge.yml` 的 `if:` **只在 arm 时**生效，
  `labeled` 事件重跑时 `if` 为假 ⇒ 不 disarm（实证两条至今带标签却已 MERGED）；workflow 接线 = **保留类**（#4248）；
  ⑤ **§18.3 新增**：**红证锚点禁读可变引用** —— `origin/main` 会随合并变成"修复后"文本 ⇒ 判据**自红**；
  正确形态 = **逐字节内联片段 + `@<sha>` 出处** + git 溯源交叉校验（取不到历史**显式 skip**）；
  ⚠️ `fetch-depth: 1` 的 job 里走 **skip** ⇒ 形态是「**本地红 / CI 绿**」，**不得**说成"阻塞所有 PR"（#4313）；
  ⑥ **§19.1 元规则 ②**：「同步副本」claim **要么由权威源生成、要么撤回**；**硬编码现值**（`当前版本：vX` / `N 个工作区`）
  是缺陷（会腐烂）—— 锚点 `tests/unit_ci_workflows/test_dev_flow_sync_claim.py`（C1~C4，C4 为**正向**：页头必须声明
  「已停止同步 + 以技能为准」）（#4315）；
  ⑦ **§2.2 case_ids 硬约束 C**：**真声明优先**（排除字符串/块注释区域）**+ 无真声明才退回旧口径** ——
  实测 **13 个 Python（模块 docstring）+ 4 个 TS（JSDoc）** 的合法声明本身就在字符串/块注释里 ⇒ 严格排除会把
  这 **17** 个合规文件判"未声明"（假红且按"只许缩短"**永缩不掉**）；**残留如实登记**（唯一候选落在其中仍算声明，
  **有意取舍**）（#4311）；
  ⑧ **§8 表新增一行**：**`patch()` 目标必须与「调用点」同源** —— `app/main.py` 在**导入期按值绑定** ⇒
  patch `app.utils.database.init_db` **对 lifespan 无效**（fixture 宣称"跳过真实 DB/Redis 初始化"实际未达成 =
  **测试基础设施静默失效**）；修法 = patch `app.main.<name>`（#4310）；
  ⑨ **改判一条过期条目（本会话实测）**：§2.3 第 7 条 / §19 表第 10 行 / §19.2 ② / v1.29 沿革行原写
  「`dev-worktree.sh add` **不做任何刷新或排除**」—— **已过期**：`scripts/dev-worktree.sh` 的 `refresh_presets()`
  （v1.8 / **#3851** 落地）在 `add` 路径**自动**把 `.agent-presets/**` 对齐 `origin/main`，提交路径另有 `preset-guard`。
  **地雷结论保留**（快照会落后 / `git add -A` 会静默回退），**"add 不刷新"这一句勿再照抄**；
  **仍须**注意：活锚必须是**专职只读镜像**、`rm/prune` 会命中 worktree。
  `migao-acceptance` 同步 +0.1.0（v1.13：阻塞条目分两组 + 红证锚点禁读可变引用）。
- v1.36（2026-09-18 **单端判据收紧入册**，本次，issue #4356）：§19.1 的规则 d
  （「单端用例必须标 persona」）此前只写「按工具集可判定为单端」而**没写判据形态**，
  而判据本体（`.github/assertion_taxonomy.py::is_single_leg_by_toolset`）的旧形态
  「工具集 ⊆ `XIAOBU_TOOLS` ⇒ 只能跑小布」隐含一个**假前提**「两端工具集不相交」——
  实测两端**共享 7 个工具** ⇒ 共享工具用例（`OR-008`/`OR-010` 一族，`persona: mibao`
  且已在 main）被判成「只可能是小布」。危害不是"不精确"：照它反推 `persona: xiaobu` ⇒
  `render_cases.filter_by_persona` 跑米宝腿时跳过它 ⇒ **真实米宝用例被静默移出米宝腿**
  （全量跑不报红，也不触发「禁止静默少跑」守卫——那不是 `case_ids` 窄跑），
  同时显式 `xiaobu` 在 `select_cases_for_persona` 里**无条件保留** ⇒ C 端腿跑起 B 端用例（假红）。
  本次落码：判据改为「小布腿跑得动 ∧ 米宝腿跑不动」（分支感知 + 跳过否定式期望 + 米宝真值
  缺失即无法判定）+ 库级前提守卫（判据 ∧ `persona: mibao` 必须为 0，改前实测 21 条）+ 判别力
  下界守卫；账本 `--prune-baseline` 净缩（条目 85→78 / 违规码 148→135）。
  **红线入册**：标注一律按**实际端别 + 证据**，**禁止**从判据反推（同 #4086 的分诊口径）；
  语义单端（`PR-018` 形态）静态不可判定，仍登记在 `CASE-TRUST-PROSE-DATA-CHECK-QUALITY`（#3483）。
- v1.37（2026-09-19 **新增 §21「往返预算」**，本次，issue #4428）：用户问「开发一个小需求也需要跑很久是什么原因」，
  以 #4419（客户管理收货信息，3 列迁移 + 1 张卡片 + 回填）为被测对象实测 —— 会话墙钟 **46.3 min / 279 步**，
  而**前台工具执行合计仅 8.1 min**、单个最慢命令 **16.6s** ⇒ **没有任何命令慢，慢的是往返次数**。
  最刺眼的一条：`read` 32 + `edit` 49 + `write` 6 = **87 次往返**换 **1.7s** 的执行（≈ 12 min 模型时间）。
  本次落码三处：① **persona 系统提示词**（`agent.cordis.yml` 的 `text` / `prefix` **两处逐字一致**）加「往返预算」条；
  ② 本节 §21（判据表 P1~P6）+ §19 索引表「往返预算」行；③ **`scripts/roundtrip_report.py`**（报告型三态 `0/2/3`）
  + `tests/unit_ci_workflows/test_roundtrip_report.py`（**14 条 L0 + 4 条注入式红证**，红证经内容指纹自证还原）。
  **有意不做的**：不设阈值、不建基线、**不改任何门禁的通过条件** —— 报告型工具一旦会拦人，就没人敢跑它，
  而本条要的是「把分母摆到台面上」。**边界**：只治「逐点小步编辑」这一条归因；
  `reasoningEffort` 恒定 / 改动面跨面 / 编号与基线全局共享 / 每次验证全量 —— 均**不在本单内**（#4428 归因 ②③④⑤）。
- v1.38（2026-09-19 **§21 补 P7「等待不轮询」+ §11.1 堵逃生口**，本次，issue #4455）：#4428 落地后用 #4443 那一单**复测**
  （会话 `session-cf73f497-3873-483b-bba6-be86ac8cdbd1`）—— 小步编辑确实治住了（`read`+`edit`+`write` 往返 **87 → 36**，
  占比 27.5% → 16.2%，往返比 1.13 → **1.19**），**但瓶颈转移到了「等 CI」**：
  **7 次 `sleep N` = 684s = 11.4 min，占 bash 执行 42%**（判据 = bash `command` 匹配 `\bsleep\s+\d+`）。
  根因不是缺规则 —— §11.1 早就写了 `--watch`，但原文是「`--watch` **或轮询**」，那个**逃生口**让 `sleep` 轮询看起来合规。
  本次落码三处：① **§11.1 删掉「或轮询」**，改为「必须 `--watch`；**首选后台 job**；禁止 `sleep N` 轮询」；
  ② **§21 加判据 P7** + §19 索引表「往返预算」行同步；③ **`roundtrip_report.py` 加「等待型调用」段**
  （次数 / 时长 / 占 bash 比例 + 处置原文）+ 6 条 L0（含**防误伤**两条：非 sleep 的真实工作不算、非 bash 工具不算）。
  **边界**：P7 只解决墙钟与往返，**不解决「CI 本身 3-4 min」**。
- v1.38.1（2026-09-19 **修 `ref-freshness` 2 条**，本次，issue #4458）：PR #4457 合并时 `Drift Audit` 判红
  —— 它是**报告型判据**，不在分支保护的 required 集合里 ⇒ **判红照旧合并**（§2.2 已登记该形态）。
  其中一条是**本 PR 自己引入的**：changelog 里写了裸行号（同行还有 `roundtrip_report.py` 这个路径 token）
  ⇒ 命中 `bare-line` 判据。本次修两条：
  ① 那条**改成文本锚点**（审计自己建议的「符号 / 文本锚点」）—— **不用加粗规避**：
  `第 **N** 行` 恰好不匹配 `BARE_LINE`，用加粗躲开是**绕过判据**，不是修；
  ② 基线里的**存量**条目（**历史值**：`# case_ids:` 落在第 71 行被 block 的实证）补 `HISTORY_MARK`
  ⇒ 该条从基线**销账**（burn-down 净销账 1 条，达标）。
  **顺带登记（不在本单修）**：`BARE_LINE` 可被 markdown 加粗**静默绕过** —— 判据那一格是**可绕过的**。
