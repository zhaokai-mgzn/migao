# MIGAO 开发提效流程（历史节选，非权威）

> ⚠️ **本页不是 `migao-dev-flow` 技能的同步副本 —— 已停止同步**（issue #4315）。
> 它是**人工节选的历史快照**（停在某个历史时点）：**不会随技能更新而更新**，也**未逐节核对过现状**。
> **流程口径一律以技能为准**：`migao-dev-flow`（权威源：`.agent-presets/migao/skills/migao-dev-flow/SKILL.md`）。
> 本页与技能冲突时**按技能执行**；改流程规范**先改技能** —— 本页**不要再同步**（历史路径 `migao/.agents/skills/...` 已废弃）。
> 本页落后多少**不写死**（版本戳与计数是**现值**，会腐烂且没人会因此变红 —— 技能 §19.2 ③），用命令自证：
>
> ```bash
> # 章节级差异（判据本体：scripts/drift_audit.py 的 `sync-copy`；版本戳不写进本页）
> python3 scripts/drift_audit.py --check --only sync-copy
> # 权威源当前版本（**现取**，不要抄进本页）
> git show origin/main:.agent-presets/migao/skills/migao-dev-flow/SKILL.md | sed -n 's/^version: *//p'
> ```
>
> 内容源自历史全链路复盘（RETROSPECTIVE，**未入库**）的 P0/P1 改进，经实战固化。

## 1. 三把工具（开发自查用）

| 工具 | 用途 | 何时用 |
|---|---|---|
| `./verify-all.sh quick/full/gate` | 三模块一键测试 + QA gate 预检 | 每次改动后、提交前 |
| `./contract-check.sh` | 三端契约一致性（字段名/状态枚举/端点） | 并行改动、跨模块改动后 |
| `./check-ui-regression.sh` | UI 回退检测（neutral token vs origin/main） | **提交前必跑** |

运行（在 migao 仓库根目录）：`./verify-all.sh gate`

## 2. 提交流程（防 UI 回退 / 防 CI 返工）

### 2.1 提交前必查（按序）— 验证分级（2026-09-04 固化；**2026-09-14 v1.19 修正：先 commit，再跑 ②③④**）
```bash
# 每次改动后：./verify-all.sh quick（~3-5 分钟）即可覆盖常规回归
# 提交前必查（按序）—— ⚠️ 顺序修正：**先 `git commit`，再跑 ②③④**
# ① UI 回退检测（最重要！防工作区旧 UI 覆盖验收版）
./check-ui-regression.sh

# ② QA gate 预检（本地跑 CI 规则，避免合并前爆 case_ids/缺测）
./verify-all.sh gate

# ③ 契约一致性（跨模块改动后）
./contract-check.sh

# ④ 全量单测（quick 即可，full 提交大 PR 前跑）
./verify-all.sh quick

# 合并前：以 CI 结果为准，不本地重复跑 gate —— CI 已排队跑过一遍，
# 本地再跑一遍 gate 是纯浪费（token+时间）。本地跑 gate 只在提交前的瞬间用。
```

⚠️ **为什么必须"先 commit"**（2026-09-14 实证，issue #3724）：`gate` 取「新增测试文件」的方式是
`git diff --diff-filter=A … origin/main...HEAD`，**只含已提交内容**。未提交时 `HEAD == origin/main`
⇒ 集合恒为空 ⇒ 旧实现打印「无变更…跳过」并 `return 0`（**✅ 假绿**）——实证：同一条命令
`git commit` 前 ✅ / `commit` 后 ❌（新增测试里的存在性断言命中 `_WEAK_PATTERNS`），CI 直接红。
修复后（#3724）：

- **弱断言检查已改成同时看工作区**（已提交新增 ∪ 工作区新增/未跟踪测试文件）⇒ 提交前跑也**真的会扫**，
  命中即报 `file:line`；
- 「**缺测 / case_ids 追溯**」仍按已提交 diff 扫描 ⇒ 有未提交改动时预检会打 `::warning::`
  （已抬到**控制台可见**）**点名这块范围未覆盖**并提示 commit；
- **仅"未提交"不会让 `gate` 失败**（`quick` 在第一次 commit 之前跑是正当工作流，只因"没提交"就红是假红），
  但此时控制台的 ✅ **不等于"全部检查已覆盖"** —— 想让预检覆盖全部范围，就先 commit 再跑。

### 2.2 红线（踩过的高频坑，禁止违反）
- **禁止 `git add -A` 盲目提交**：工作区长期积压的未提交改动（尤其旧版 UI）会覆盖 main 上已验收的版本。提交前先 `git status` 检查积压，**逐个确认** UI 文件不是旧版。
- **禁止长期不提交**：避免 142 个文件的大 PR。开发应小步提交 + 频繁 `git fetch origin main && git rebase origin/main`。
- **禁止分支滞留 + 无记录切换分支**（2026-09-01 实战教训：40+ 本地分支积压，切换旧分支 → 工作区被旧代码覆盖 + 未提交改动静默携带 → 「切换分支后功能退化」）：
  1. 分支开即关联 Issue，验证完即 PR，CI 绿即合并，**分支存活 < 1-2 天**；
  2. 切换分支前 `git status` 必须干净（有改动先 commit/stash）；
  3. 本地验证前先 `git fetch origin main && git rebase origin/main`，**验证必须基于最新主线**；
  4. 多分支并行验证用 `./scripts/dev-worktree.sh add <branch>`（独立工作区，切换零污染），**禁止反复 checkout 切分支**；
  5. 定期清理：`git branch --merged origin/main` 全删；`git cherry origin/main <branch>` 全 `-` 表示内容已落地可删；无独有提交的分支直接删。
- **新增/修改测试必须带 `# case_ids: OR-xxx`** 注释头（按域：OR 订单/AS 售后/PR 商品/FN 财务/CU 客户/DA 看板/UI 前端），否则 QA Growth Gate 会 block 合并。
- **测试文件路径**：前端组件测试放 `tests/unit/components/<Name>.test.tsx`（gate 模板不递归子目录，勿放 `orders/` 子目录）。

### 2.3 多会话并发规范（v1.3 新增，2026-09-04 实战固化：多 DSH 会话并行踩脚治理）

多会话并发（多 Agent / 多分支同时开发）时的铁律：**一个会话一个独立工作区，会话之间零共享写路径**。

1. **会话必须建在独立 worktree**：`./scripts/dev-worktree.sh add <branch>`（默认 `../migao-wt/<分支>`）。禁止多会话共用一个工作目录——同时改文件互相覆盖、`git add` 互带对方文件、同时跑 verify 抢资源。
2. **会话锁**：`dev-worktree.sh add` 自动登记 `.sessions/<branch>.lock`（含 PID+时间戳）；同一分支已有活跃锁时**禁止**重复建工作区/推分支。提交/推送前先 `./scripts/dev-worktree.sh list` 确认锁状态。
3. **端口隔离**：本地服务端口用环境变量覆盖（`API_PORT`/`AGENT_PORT`/`WEB_PORT`），会话各自 `.env.local`，杜绝 8080/8001/3001 互抢。
4. **主工作区只读**：主仓库（migao/）只做 `fetch/rebase/merge` 与 PR 管理，**不在主工作区直接改文件**（防止未提交改动静默携带）。
5. **分支卫生**：验证完即 PR，CI 绿即合并，分支存活 < 1-2 天；定期 `git branch --merged origin/main` 全删 + 清理 `origin gone` 的本地分支。
6. **开工前读契约**：`docs/wiki/CONTRACT-LEDGER.md`（状态枚举/字段名/端点签名）；跨模块改动后跑 `./contract-check.sh`。

### 2.4 预设快照地雷：worktree 的 `.agent-presets/**` 是**创建时刻快照**（v1.8 新增，2026-09-15，issue #3851）

**症状（静默）**：worktree 建好那一刻，`.agent-presets/**` 是**当时**的副本；此后 main 上预设再推进，工作区
**不会自动跟上** ⇒ 这些文件相对 `origin/main` 就是「改动」（内容在**回退**）⇒ 一条 `git add -A` + push 就提交一个
**把研发模式回退若干版本**的 PR。而现有门禁（Case Contract / Coverage / QA Growth / Case Trust）**都不看
`.agent-presets/**` 的版本 ⇒ 不红**。

**实测（只写「形状」，不写条数 —— 条数是**时点值**，会腐烂且没人会因此变红，命令自证）**：
`migao-wt/` 下**确实会**出现「含该预设文件、但 `migao-dev-flow` 版本 ≠ main」的工作区，**数量与落后区间用下面的命令现取**。
**本单开工时就踩到了这个形状**：一个刚建几分钟的 worktree，其预设版本已经不是 main 的版本，
只能靠人工 `git checkout origin/main -- .agent-presets/` 补上：

```bash
# 自取现状（不写死条数；macOS 自带 uniq 无 -w，故用 sed+sort 计数）
git -C <migao 仓库根> worktree list --porcelain | grep '^worktree ' | cut -d' ' -f2- | while read -r wt; do
  f="$wt/.agent-presets/migao/skills/migao-dev-flow/SKILL.md"; [ -f "$f" ] || continue
  printf '%s %s\n' "$(sed -n 's/^version: *//p' "$f" | head -1)" "$wt"
done | sed 's/ .*//' | sort | uniq -c | sort -rn
```

**三层防线（互补，别只靠一层）**：

| 层 | 位置 | 管什么 |
|---|---|---|
| ① **创建路径**（根治） | `scripts/dev-worktree.sh add` | 建完工作区**自动** `git checkout origin/main -- .agent-presets/`；输出刷新了哪些文件与**理由** |
| ② **提交路径**（增量 fail-closed） | `./scripts/dev-worktree.sh preset-guard`（判定本体 `scripts/agent-presets-guard.py`） | 暂存/工作区的预设**版本下降** ⇒ **非零退出**；**合法升级放行**；同版本内容不同 = **分叉 → 告警**；**并判活锚新鲜度**（见 ④） |
| ③ **机械安全网**（全库/定时对账） | `#3843` 的统一审计 `drift_audit --check` 的「`.agent-presets/**` 版本单调性」守卫 | 存量工作区 + CI 侧对账。**与本单互补**：本单管增量、贴合工作区；审计管全库、定时 |
| ④ **加载点**（活锚，`#4026`） | `./scripts/preset-anchor-check.sh` / `preset-anchor-refresh.sh`（判定本体同上 `anchor` 子命令） | **DSH 真正加载的那份内容**是否就是 `origin/main`：内容逐字节 + 检出 sha + frontmatter 可加载性 ⇒ 落后/悬空/内容不同/加载不了 = **非零退出**（`⏭️ 未跑判定` ≠ 通过）。前三层都对了、活锚落后 ⇒ 改进仍**到不了加载点** |

```bash
# 提交前自查（版本下降即拒绝提交；升级/相同放行）
./scripts/dev-worktree.sh preset-guard              # 默认同时看暂存区与工作区
./scripts/dev-worktree.sh preset-guard --source index   # 只看 `git diff --cached`
# 命中时的修法（与 issue #3851 记录的人工修法同一形状）
git checkout origin/main -- .agent-presets/

# 加载点自查（开工第一件事；落后即先同步再动手）
./scripts/preset-anchor-check.sh                    # 红就停：落后/悬空/内容不同/技能加载不了
./scripts/preset-anchor-refresh.sh                  # 自愈：只读镜像 fetch + checkout --detach origin/main + 复检
```

> **④ 为什么单列一层**：①②③ 管的都是「**仓库里的**（工作区/暂存区/全库）预设内容」，
> 而**生效的是活锚**（`~/.dsh/.agent-presets/migao` 解析出的目录）。实测活锚曾指向落后 `origin/main`
> **42 个提交**的主工作区，**内容当时恰好一致** ⇒ 前三层全绿、也没有任何东西变红，
> 但下一次改预设的改进**永远到不了加载点**。故锚点必须是**专职只读镜像**（不是会在清理半径内的
> `migao-wt/*` worktree，也不是会被开发的主工作区），并由 `preset-anchor-refresh.sh` 负责跟随。

**存量清理（只出清单，脚本绝不代删）**：判据 = **分支已合入 `origin/main`**（祖先可达，或 `git cherry` 无 `+` 行
—— squash 合并后 commit 可达性不是判据）+ **工作树干净** + **无活跃会话锁** ⇒ 列「可安全移除」；否则列「需人看」并给原因：

```bash
./scripts/dev-worktree.sh prune --dry-run    # 必须显式 --dry-run；不带即拒绝执行（exit 2）
./scripts/dev-worktree.sh rm <分支或路径> --delete-branch   # 人工逐条确认后真删（脚本不代劳）
```

**禁止手法**：不要用「让 git 忽略这些文件的改动」的索引标记手法（`--skip-worktree` / `--assume-unchanged` 之类）——
那会把**合法的预设改动**（改研发模式本身）一起吞掉，「眼不见为净」在这里等于把正事也堵死。
**要改研发模式**：直接在工作区改 + 升 `version:`（`preset-guard` 对升级放行），PR 走正常评审。

> 同族病灶：`migao-dev-flow` §18.2（**活锚** `~/.dsh/.agent-presets/migao` 陈旧 ⇒ 按过期规则干活）、
> `#3849`（`AGENTS.md` 换链拓扑会指向**落后 136 提交**的主工作区）—— 三者都是「**读的是快照，不是真相源**」。
> 相关单：`#3843`（返工主机制 A~H 护栏）· `#3846`（断言可信度门禁包实测中发现并拦截此风险）。

## 3. CI 关卡（合并前会自动跑）
| 检查 | 作用 | 失败常见原因 |
|---|---|---|
| UI Regression Check | 防 UI token 回退 | 工作区旧 UI 被提交 |
| QA Growth Gate | case_ids/测试覆盖/弱断言 | 测试忘带 case_ids、测试放错目录 |
| Case Contract | 用例引用完整性 | 改了 case yml 未重渲染 |
| Agent Eval (smoke) | 米宝真实 LLM 行为 | **偶发 LLM 波动**（JSONDecodeError 等，CI 内部已自动重试 1 次） |
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

CI 里调用**真实 LLM**（生产 `ai-api.migaozn.com` + `SERVICE_TOKEN`）的环节只有 2 个必须留意：

| 环节 | 触发 | 规模 | 治理 |
|---|---|---|---|
| ~~**Agent Eval (smoke)**（pr-check 的 `agent-eval-smoke` job）~~ | ~~每次 PR~~ | ~~smoke tier ~7 条~~ | ⚠️ **已移除**（issue #3653，2026-09-15）：它评的是**已部署 main**（`ai-api.migaozn.com`），与本 PR 改动**无因果**，却是四层冗余里最贵的一层（实测 2.5h 内 85 次 ≈ 43% 的评测次数） |
| E2E Real | 每日 00:00 定时 | 135+ integration 真实 LLM | 频率已合理（低峰回归），保持 |

- ⚠️ **PR 层的真实 LLM = 0 次**（2026-09-17 用户裁定 2′/4′，承载 issue #4034）：
  `agent-behavior-eval.yml` 的评测 job 已**整体删除**，PR 上只留**零 LLM 的映射信号**
  （diff → §13.2 用例集 + 可复制派发命令）。判定用途走**单一入口** `post-deploy-eval.yml`
  （每 3 天 normal 全量 + 手动 `workflow_dispatch`）；定时档（3 天 normal / 每周 adversarial ×2）**全部保留**。
- 其余环节不烧真实 token：`nightly-verification` 是 fixture e2e + smoke p1（HTTP 层）；
  `agent-eval.yml`(normal 47 条) 与 `adversarial` 已降频为手动/每周（对抗档为**定时保留**）；
  `xiaobu-acceptance` 除定时对抗档外均为手动，且它是**单腿窄跑**入口（`persona` 输入）。
- **LLM 红例的闭环**（裁定 4′）：必须下沉为 ≥1 条确定性断言（`must_succeed`/`db_verify`/
  `amount_verify`/`output_verify`/L0 不变式）；账本 = `.github/llm-finding-ledger.json`，
  机械检查 = `python3 .github/llm_sink_check.py --selftest | --issue N | --all`
  （用法与"未机械化"登记见 `docs/testing/llm-finding-sinking.md`）。

- **观察指标**：`gh run list --status queued` 排队 >20 即需治理（先清 dependabot 潮，见 §7）。

### 3.3 断言可信度门禁（`Case Trust Gate`，2026-09-15 新增；#3483 T1 扩展格）

**为什么需要这一层**：原有用例侧门禁只有 `Case Contract (truths_ref)`（引用可解析 + 生成物新鲜）、
`Case Coverage Gate`（覆盖映射）、`QA Growth Gate`（改代码要有测试）—— **没有任何一条校验
断言本身是否可信**。于是「写了断言」与「断言真能判红」之间没有任何结构性约束，以下缺陷
**全部被门禁放行进来**（均有实证）：

| 缺陷形态 | 实证 |
|---|---|
| 用例**物理不可满足**（让 agent 挂种子里不存在的标签） | `CU-003` → #3832 |
| 散文禁令**独自承载**关键判据（全程语义、无轮次作用域） | `PG-013` → #3833 |
| 写类用例**无效果层断言**（「调用了 ≠ 成了」） | 31 条 → #3778 |
| `data_checks` 缺 `success=true` ⇒ **不计分** = 假绿 | `PR-021` → #3559 |
| 写类用例**无自清理** ⇒ 重试前置不等价 | #3800 / #3797 |
| 准备型 `pre_clean` 的未复位/失败路径未纳入折叠 | #3797 |

**机制**（判据的**单一源** = `.github/assertion_taxonomy.py`，纯函数、零第三方依赖）：

| 件 | 作用 |
|---|---|
| `.github/assertion_taxonomy.py` | **单一判据源**：写工具/写 action 显式枚举、效果层断言集合、前置等价性判据、persona 规则。静态门禁与后续 runner 侧动态分类器**共用**这一处口径（两处各写一份必漂移） |
| `.github/case_trust_gate.py` | 门禁外壳：① 取 `git diff --name-only origin/main...HEAD` 命中的 `cases/*.yml` → 比对 `origin/main` 与 HEAD 的用例块文本 → **只判新增/内容变化的用例条目** → 按基线裁决；② 对**全库**做**全量对账**（见下）；③ **burn-down 预算**裁决 |
| `.github/case-trust-baseline.json` | **存量**违规清单（burn-down，锚定 SHA）+ `burn_down` 预算块。清单内放行，清单外一律阻塞；**清单是活账本**：记了却不再违规 ⇒ 阻塞，仍在违规却被删 ⇒ 阻塞 |
| `.github/case-trust-unimplemented.json` | **未实装**规则清单（如实登记 + 缺什么），防「写成恒真判断凑数」 |
| `.github/case-trust-redproof.md` | 红证留档（补前必红 / 补后绿原文），由 L0 守卫锁定防事后改写 |
| `tests/unit_ci_workflows/test_case_trust_gate.py` | L0 守卫 + 退化守卫（已知缺陷夹具必须被判违规；正确形态不得误伤） |

**十条规则**（逐条带「为什么算缺陷」+ 反例 + 怎么改；失败信息里都有）：

1. `CASE-TRUST-EMPTY-ASSERTION` —— 计分断言数不得为 0（`total_exp == 0` ⇒ `score = 1.0` 恒绿）；
2. `CASE-TRUST-NO-EFFECT-ASSERTION` —— 写类用例必须 ≥1 条效果层断言
   （`must_succeed` / `db_verify` / `output_verify` / `amount_verify` / `post_session`，
   或含 `success=true` 等关键词的机器计分型 `data_checks`）；
3. `CASE-TRUST-NO-SELF-CLEAN` —— 写类用例必须声明 `pre_clean` 或 `namespaces`
   （⚠️ `namespaces` 只保证**并行互斥**，**不解决重试前置** ⇒ 记为弱证据）；
4. `CASE-TRUST-PRECLEAN-TARGET-UNRESOLVABLE` —— `pre_clean` 的点名目标必须能从
   `tests/agent_eval/fixtures/*.sql` **现算**的真值集合里解析到（`CU-003` 形态）；
5. `CASE-TRUST-FORBIDDEN-TEXT-SOLE` —— `forbidden_text`（全程语义）不得**单独**承载判据，
   必须配行为/效果层断言；已**轮次作用域**、或显式声明「禁令即主判据」
   （该用例块里写 `# forbidden-text-intent: <理由>`）时放行；
6. `CASE-TRUST-VOLATILE-LOCATOR` —— **定位被测对象必须用不可变标识**
   （手机号 / `order_no` / `id` / 用例自建对象的唯一名），**不得**用「名字子串 / 序号 / 列表位置」。
   位置/序号选择器（`_index` 之类）⇒ **阻塞**（列表顺序是运行时排序 ⇒ 定位会漂到别的对象）；
   名字子串/自然键（`*_keyword` 等）⇒ **警告**（当下正确、有风险，清单跟踪）。
   ⚠️ 名字/序号出现在 `user_inputs` 里是**合理**的（被测行为的一部分），**不在**本规则范围内。
   与「写用例必须有自清理」互补：那条治「**世界**被谁改了」，这条治「**我改的是哪个对象**」。
7. `CASE-TRUST-NO-PRECONDITION-ASSERTION` —— 多轮/写类用例必须对**自己的前置**给出可判定断言
   （`precondition` 字段，或**机器计分型** `data_checks`）。
   为什么：前置悄悄不成立时红的表现是 `unmatched expectation` ⇒ 看起来像「agent 不干活」，
   归因全错（实证 `PG-013` 重试前置不成立 / `CU-003` 客户数=2）。
   ⚠️ **只加 `must_succeed`/`db_verify` 不算**（它们只说明「工具没成功」，没说前置是什么）。
   **红线：不得为了让用例变绿而删这类断言。**
8. `CASE-TRUST-STALE-LINE-REF` —— `path:NNN` 行号引用必须对 `origin/main` 命中
   （把「不写裸行号」的纪律机器化；#3787 记着 5 处过期指引）。行号越界/文件不存在/
   符号在文件里完全找不到 ⇒ **阻塞**；行号漂移（符号在别处）⇒ 警告。
9. `CASE-TRUST-SINGLE-LEG-NO-PERSONA` —— 按工具集可判定为单端的用例必须标注 `persona`
   （#3822：缺标注的另一条腿必挂，`case_ids` 窄跑还会触发 runner 的「禁止静默少跑」守卫）。
   ⚠️ **判据形态（#4356 收紧）**：单端 = 「**小布腿跑得动 ∧ 米宝腿跑不动**」——
   米宝腿只有 persona 过滤、**没有**工具集过滤（`eval_case_filter.select_cases_for_persona`）
   ⇒ 工具集 ⊄ 米宝的用例在米宝腿**必挂**，那才是需要标注的一类。
   两端**共享**的工具（`order_create` / `product_detail` / `product_search` / `validate_input` /
   `interact` / `knowledge_search` / `production_progress_query`）**不构成**单端理由：
   旧形态「工具集 ⊆ 小布 ⇒ 只能跑小布」隐含「两端工具集不相交」这一**假前提**，
   照它反推 `persona: xiaobu` 会把真实米宝用例**静默移出米宝腿**（全量跑不报红），
   并在 C 端腿制造假红（显式 `xiaobu` 无条件保留 ⇒ 绕过 `MIBAO_SEMANTIC_PATTERNS` 语义过滤）。
   **语义单端**（工具集两端都成立、行为只在 B 端可满足，如 `PR-018`）静态不可判定，
   按证据逐条分诊（#4086），不属本判据。
10. `CASE-TRUST-SELF-TARGET-NO-MAX-GROWTH` —— **自建目标**的 `expect: 0` 前置必须给 `max_growth`
    （#4200：`namespaces` 声明了 `product_name:<KW>` ∧ 前置对同一名字声明 `expect: 0` ∧
    `max_growth` 缺失或 <1）。为什么：runner 的漂移判据是 `after - before > max_growth`
    （缺省 0），而用例**自己就会创建**那个名字的商品 ⇒ 正常行为下 `0 → 1 > 0` **恒判漂移**、
    `score` 归零（实测 `PR-008` / `PR-016` 逐条计分断言全 passed 而 `score=0.0`）。
    修法 = 加 `max_growth: 1`（只容忍自建的那一个；并行再造同名仍判漂移）；
    **不得**改 `expect` / 删断言绕过。先例：`HR-002`。

**三层判定必须同时存在**（缺任一层就必然假红或债务僵化）：

1. **只判 diff 命中条目** ⇒ 不阻塞存量、不「一次红全库」（新增违规的口子）；
2. **全量对账**（#4031 / #4009 裁定 1）⇒ 豁免清单必须与**全库**重算逐条一致，**不限 diff 命中**：
   - 记了却**不再违规** ⇒ **阻塞**，必须移除/收窄（旧口径只对 diff 命中项生效 ⇒ 只要没人再碰那条用例，
     它记的陈旧码就永远躺着 = **永久豁免**；实测：建账 110 → 加规则涨到 143 → **净缩 1 条后冻结**）；
   - `origin/main` 记着、现在**仍违规**却被**删掉** ⇒ **阻塞**（删条目 = 偷偷新增豁免，R4）；
   - 修法是机械的：`--prune-baseline`（**只删不加**）；`--regen-baseline`（重建）默认**拒绝增长**；
3. **burn-down 预算**（配置在基线文件的 `burn_down` 块，**生效口径读 `origin/main` 那一份**）：
   每（改用例的）PR 至少净缩 `per_pr_min` 条 + `OR-*` 优先档到期 + 全清单 `deadline` 清零；
   **只许缩短**（清单增长 = 新增豁免 ⇒ 红）。

**本地自查**：

```bash
python3 .github/case_trust_gate.py                      # PR 口径（diff origin/main...HEAD + 全量对账 + 预算）
python3 .github/case_trust_gate.py --files .github/cases/product.yml   # 判该文件全部条目（调试）
python3 .github/case_trust_gate.py --prune-baseline     # 清掉「已不再命中」的码/条目（只删不加）
python3 .github/case_trust_gate.py --regen-baseline     # 全量重建（口径变化时；默认拒绝增长）
python3 .github/case_trust_gate.py --today 2027-01-01   # 预算到期判定的确定性红证
python3.11 -m pytest tests/unit_ci_workflows/test_case_trust_gate.py -q # L0 守卫
```

**未实装项**（见 `.github/case-trust-unimplemented.json`，**不写恒真规则凑数**）：
每-PR 最低消减的**字面口径**（`scope=all_prs`，默认 `case_touching_prs` —— 见该文件登记的理由）、
未知 `pre_clean.type` 静默跳过（#3797）、`pre_clean` 失败路径未折叠判据（#3797）、
跨腿窄跑的运行期判定（#3822，属 runner 归因自动化即 #3483 的 T2）、
**全库** persona 标注（有意不做的宽口径）、纯散文 `data_checks` 的**语义**质量（LLM 审计层）。

> **已落地的两条（勿再照抄旧文）**：① 「未登记违规只报告不阻塞」已由 **#4046** 翻转为
> fail-closed（全库判出、清单没有的码 ⇒ 阻塞）；② `scripts/drift_audit.py` 的同款陈旧口径
> 已由 **#4045** 同步（全量对账 + 反向对账 + burn-down 预算，判据 **import 复用**
> `case_trust_gate.reconcile_baseline` / `burn_down_verdict`）。两条都从
> `.github/case-trust-unimplemented.json` 撤了登记 —— 留着就是与实现相反的假真值。
> ⚠️ 本节（及全页）**不是** `migao-dev-flow` 技能的同步副本：**已停止同步**（issue #4315），
> 本节口径**可能已过期**，一律**以技能为准**。章节差异由 `drift_audit` 的 `sync-copy` 判据持续报告
> （版本**不写死** —— 用页头那条命令现取，别再往本页抄版本号）。

## 4. 部署
- 合并到 main 自动触发 3 个部署（admin-api/ai-agent/frontend）+ post-deploy 冒烟。
- **部署后验证（2026-09-01 修正：`/actuator/health` 公网 404 是 nginx 屏蔽的预期行为，勿当成故障）**：
  ```bash
  curl -s https://ai-api.migaozn.com/health          # ai-agent → {"status":"healthy"}
  curl -s -o /dev/null -w "%{http_code}\n" https://merchant.migaozn.com/login   # frontend → 200
  curl -s -o /dev/null -w "%{http_code}\n" -X POST https://api.migaozn.com/api/auth/sms-code -H 'Content-Type: application/json' -d '{}'  # admin-api → 401（存活+鉴权）
  ```
- 冒烟失败若为全量 502/Connection refused 且后续部署已覆盖 → 多为**部署滚动重启瞬态**，以最新一次部署结论为准（见 §7.3 的 mergeStateStatus 思路）。
- 生产登录：13800138000 / 万能码 123456（短信网关仍 bypass，上线前需接入）。

## 5. 相关文档
- `migao-dev-flow` 技能（**权威源**，本页只是它的历史节选）— `.agent-presets/migao/skills/migao-dev-flow/SKILL.md`
- `docs/wiki/CONTRACT-LEDGER.md` — 并行开发契约清单
- 全链路复盘 RETROSPECTIVE（**未入库**、仓内无此路径）— 本页与技能的改进来源
- `verify-all.sh` / `contract-check.sh` / `check-ui-regression.sh` — 三把工具

## 6. 提交前体检一键命令（2026-08-28 固化）

```bash
# 一次命令检查：case 生成物与 .github/cases/ 单一源是否同步（CI 会 block 分叉）
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
