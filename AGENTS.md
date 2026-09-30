# AGENTS.md — MIGAO（AI 智能客服系统）

> DSH（DeepSeek Harness）会话的仓库级入口。开发前先读本文件，再按需查阅 docs/wiki/INDEX.md 定位规范页。

## 这是什么

面向布艺行业的多租户 AI 智能客服 SaaS：C 端小布 + B 端米宝双 Agent（LangGraph），
Java admin-api + Python ai-agent-service + Next.js admin-web + Taro mini-app。

## 改代码前（铁律）

1. **测试先行（AI-TDD CP-1~CP-7）**：先写失败测试（Red）→ 最小实现（Green）→ 重构。全量单测必须 PASS。7 个检查点的正文见 [docs/wiki/Development.md](docs/wiki/Development.md) 的「AI-TDD 流程」。
2. **三把工具**：提交前跑 `./verify-all.sh gate`（与 CI 同规则）、`./check-ui-regression.sh`（UI 回退）；跨模块改动加 `./contract-check.sh`。
   **改 web 页面另加一轮「Playwright 页面多模态验收」**（真实登录 + 截图 + AI 读图判定；承载体与假绿清单见 `migao-dev-flow` §15.7）。
3. **case_ids**：新增/修改测试文件头部必须声明 `# case_ids:`（对应 `.github/cases/` 用例，否则 CI QA Growth Gate block）。
4. **GitHub 操作**：禁止直推 main，必须走 PR 且关联 Issue——**PR body 必写 `Closes #<issue号>`**（GitHub 只在 body 含 Closes/Fixes/Resolves 关键词时自动关 issue，标题里的「(issue #xx)」不生效；漏写合并后 issue 不会自动关闭，CI `pr-issue-link` 会打 `needs-issue-link` 标签提醒；无 issue 关联的基建 PR 标 `N/A（基建）`）。详见 `migao-dev-flow` 技能 §2.2/§3.3。合并后 GitHub 异步关闭偶发失效（close-on-merge best-effort，实证 #2910/#2919 未自动关）→ `close-linked-issues.yml` 解析 body 关键词做合并后补偿关闭 + schedule 定时对账兜底（issue #2937；cron 声明 30 分钟、实测被 GitHub 节流至 2~5.5h 触发；pull_request closed 事件对 native auto-merge 合并实测不可靠），无需人工；若 issue 仍悬挂再按 §2.2 人工兜底。
5. **最少代码**：写码前爬「最少代码阶梯」（YAGNI → 复用 → 标准库 → 原生特性 → 已装依赖 → 一行 → 最小实现；**先理解再爬梯**）。只简化实现代码、**不降测试门禁**，安全护栏与既有架构契约永不砍。全文见 [docs/wiki/Code-Minimalism.md](docs/wiki/Code-Minimalism.md)。
6. **并行修复（发现即并行，合并串行）**：一次暴露多个问题时**禁止逐个串行修复**——
   先**冻结问题清单**（每条含证据 + 归因层级 + 验收判据）→ 按**文件所有权**切成互不冲突的任务包
   （同文件改动同包；改 `cases/*.yml` 的包独占生成物）→ 每包 = issue + 分支 + 独立 worktree +
   后台 subagent（§2.3 零共享写路径）→ **主会话只做集成与验证**。合并串行、验证收口；
   **并发 ≤3** —— **评测型流水线与开发包同口径**（争用的两个阶段见 `migao-dev-flow` §17.2）。全文与反模式见 `migao-dev-flow` 技能 §17。
7. **CHANGELOG 更新纪律**：**用户可见**的行为/口径变更（feat / fix 里改产品行为、算料口径、涉钱面、UI 可见面者）
   必须在 `CHANGELOG.md` 的 `## [Unreleased]` 补一条，标题形态 `### <一句话说清改后的形态>（<日期>，issue #NNNN）`
   （无关联 issue 时标 `PR #NNNN`）。
   **豁免口径（不入册）**：`chore`（含依赖升级、CI 台账滚动）、`docs`、`ci`，以及**纯测试 / 研发工具**类改动
   （改用例判据、改 `scripts/` 等）—— 它们对用户**无可观察影响**，塞进来只是凑数、还会淹没真变更。
   判据（零成本、可复算）：`git log --oneline <上次改 CHANGELOG 的 commit>..origin/main`，
   逐条按上述口径分流后再补录；**不许**按「差了多少个 issue 号」估数（issue 号是稀疏的，不是提交数）。
8. **类级固化（发现即固化）**：修一个缺陷**只修这一处 = 没修** —— 必须同时落 ① 实例判据（会红）
   ② **类级元守卫**（让同类进不来：未登记即红、豁免台账**只许缩短**且条数**现取**），并在 PR body 写
   **「固化声明」**（判据 = 文件::测试名 / CI job / 回归时会怎么红 / 未固化项）。判红必须**可归因**
   （实测读数 + 清单 + **可复制命令**）且给出的出口**真可行动**；**部分交付不许写 `Closes`**
   （用「关联 #NNNN」+ 人工关单并附证据）；降成本的固化**禁挂钟时长**（钉与负载无关的工作量读数）；
   核验前**自证坐标**（只读一律 `git show origin/main:<path>`，**禁读工作树**；变异注入先自证生效）。
   全文见 `migao-dev-flow` §23（G1~G10）。
9. **main 侧没有守护 ⇒ 合并后必须自证**：`pr-check` 只在 `pull_request` 触发 ⇒ **main 上的破坏没有任何 run 会报**
   （实证 `#5396` 半成品落 main，卡住**所有** PR 的 required 检查，只在下个 PR 上爆）。⇒ ① 引入**约束类判据**时必须
   **同 PR 补齐被约束对象**，并在 PR body 写明**真值在哪一侧 + 依据**；② 合并后**在 main 上复算**目标判据
   （`git show origin/main:<path>` 或纯检出跑一次），**不要**用「CI 绿」推断 main 健康。全文见 `migao-dev-flow` §23.7（A1~A3）。
10. **不许每天重做同一串动作（消灭「日更」）**：一晚做过 **≥3 次**的动作串 ⇒ 必须收敛成**一条命令**（脚本子命令），
    并在该命令里把"顺序即安全顺序"钉住；**清理挂在事件上**（新工作开始 / 落地完成）。
    ⛔ 不新增 schedule/cron（2026-09-21 裁定：**无人值守删除 / 破坏性动作**不安全——判据写错时没有人来得及拦）。
    🔻 **适用范围已于 2026-09-27 收窄**（用户裁定「按你建议的执行即可」；**只收窄，不取消**禁令）：禁令的**对象**是
    **无人值守的删除 / 破坏性动作**；**非破坏性 · 幂等 · 带自证断言**的**重发布 / 只读心跳**类周期任务**可以**新增，
    四条**同时**成立才算：① **远端执行体不做删除**（有**机械自证**：拒绝在静态根上清理 + 发布前后父目录
    `index.html` 哈希一致）——🔻（**由 PR #5733 的实例校准**：① 的**加强形态**，**不是**原裁定另立的第五条）
    **周期档自身不得是写盘档**：只读 / 通知档与写盘档必须是**显式两态**，默认档**不写盘**，写盘要人显式输入
    ② **幂等**（同一输入连跑两次结果逐字节一致）③ **失败可见**（判红有承接面，不许静默半成品）
    ④ **在本 PR body 显式声明「这是新增 schedule，判据 = 上述四条」**。
    具名实例必须**双向**登记：`tests/unit_ci_workflows/schedule_scope_ledger.json`（`exceptions` 各带三个**证据锚**；
    **在飞**的放 `pending`，**一落地即须升格**）⇄ 本条的「📌 已批准具名实例」行；**未登记即红** —— 判据 =
    `tests/unit_ci_workflows/test_iron_rule_10_schedule_scope.py`（存量 14 条为**冻结快照**，只许缩短；
    本判据**不为存量的安全性背书**，只裁新增）。
    凡"每天都要看"的必须有**值守面**（判红**自己开单** + 清零判据）—— 靠"记得去看"不算机制。
    📌 已批准具名实例（`schedule` 窄例外）：PR #5731（2026-09-27，批准人 = 用户）—— **重发布**两条：
    `.github/workflows/worker-h5-publish.yml` 的 `23 18 * * *` · `.github/workflows/bmini-h5-publish.yml` 的 `43 18 * * *`；
    PR #5733（2026-09-27，**在飞**）—— 第三条：C 端 H5 发布腿的 `53 18 * * *`（**只读心跳**：该腿的 cron 只走
    `notify`「只报告、绝不写盘」，写盘档要 `workflow_dispatch` + 显式 `publish=true`）。
    全文见 `migao-dev-flow` §23.9（C1~C4）。

11. **转述即未核实 · 声明存在 ≠ 可达**（2026-09-27 用户裁定「**发现容易犯的问题就应该固化到研发模式中避免再犯，
    而且如果 ci 或者台账经常出错的点也应该固化下来**」）：
    **(a)** 引用 / 转述**任何人**的读数（含集成侧给你的清单、别人的包、你自己的上一轮结论）之前，
    先问一句 **「我读到的那个东西，是不是它声称的那个对象？」** 并做**一次**核对 —— 把「声称的对象」
    写成 `<仓库相对路径>::<符号>`，去 `origin/main` 上看它是否真在那里（`git show origin/main:<path>`；
    **禁读工作树**）。**找不到 durable 证据的宁缺勿滥**（不写进研发模式）；**发现转述不准要当场指出**。
    **(b)** 凡声称「已交付 / 可达 / 已合并」⇒ 必须给一次**内容级**或**线上复探**读数 + **判据名**
    （`git show origin/main:<path>` / `bash scripts/stranding-check.sh <PR>`，三态 `0/1/3`，`3` 不得当 `0` 读）；
    一条**注册了但从未跑过**的发布腿 ≠ 交付。
    全文与承载体判据见 `migao-dev-flow` §25（`FM-A*`/`FM-B*`/`FM-C*`/`FM-D*`）与
    [docs/wiki/CI-CD.md](docs/wiki/CI-CD.md) 的「CI / 台账反复出错点」节（`FM-E*`）。
    ※ 判红**具名**（哪个对象 / 差多少 / 可复制命令）与**核验前自证坐标**已在铁律 8，此处**不重复**。

12. **发现即收敛 · 新业务需求直接开单**（2026-09-25 用户裁定；🔴 **2026-09-30 改判**，用户逐字
    「『会话内零新开 issue』是铁律 **这个铁律要改，如果有新业务需求就直接开issue**」）：
    **(a) 新业务需求 ⇒ 直接开 issue**（**合法默认路径，不需要任何标记**）：单子写清**需求 + 已定的口径 +
    承接分支/PR**，然后照常走「关联该 issue 的 PR」。
    **(b) 范围外的顺带发现**（做 A 时撞见的 B 缺陷 / 基建问题）仍**不开单**，只有三条出路，
    **没有"开单"这一条**：① **链内修**（同一 worktree / 同一分支 / **同一个 PR** / 同一批判据：实例判据 +
    类级元守卫 + 固化声明）；② **并入既有台账/追踪单**（#5511 保留总账 / #5496 裁定清单 / #5490 阻塞清单 /
    #4043 这类族级跟踪单）；③ **在会话里直接向人类提出**（写进回报正文，等人在对话里处置）。
    若确需人类裁定/外部输入，**在对话里问**，不要用开单代替提问；人类当场要求为**顺带发现**开单时，
    该单 body **首行**写 `人为要求：<原话或出处>`（`scripts/issue_lifecycle.py check-new-issues` 是**报告型
    分诊清单** —— 🔴 2026-09-30 起**不再判违规**，它只按这个标记过滤出「无标记的新单」供人核）。
    **(c) 历史口径保留（用于判断"这份发现该不该出链"）**：只有命中 5 条之一才谈得上出链，且必须写明是哪一条：
    ① **需裁定**（业务口径/涉钱/权限/不可逆）② **需外部输入**（客户/厂商/云侧/第三方）
    ③ **写面冲突**（与并发包同一份文件，§17.2）④ **体量超一个包**（迁移/跨端契约/多模块联动）
    ⑤ **证据不在本机可得**（必须真跑/真库/真环境）—— 命中后**按 (b) 的 ②/③ 处置，仍然不开单**。
    读数（一条命令，§23.9 C1）：当日**新开 issue 数 ÷ 合并 PR 数** —— 🔴 **「目标恒为 0」已随本次改判取消**：
    业务需求本来就该开单；这条读数现在的用途 = 发现「**顺带发现被私开成单**」的形态（比值异常升高时才去看分诊清单）。
    **(d) 会话收口（2026-09-25 用户裁定「不留尾巴」）**：会话结束时**不得留下** ① 未推送的提交 / 未开 PR 的分支
    ② 半成品 worktree ③ **只存在于会话上下文里的规格**（必须落成**远端可复原形式**：既有台账评论 / PR body）
    ④ **声称而未经核实**的动作（"包在跑"须核实 worktree + `git ls-remote`；"已修"须 `git show origin/main:<path>`）
    ⑤ "有意不做"被读成"已解决"（关单证据必须写明**接受的缺口 + 重启条件**）。
    **派活前必查**：`gh issue view <n> --json state` + 查同名 PR（已关闭 / 已有 PR ⇒ **不派**）；
    **多包并发**：同一轮多派必须**逐个核实落地**（实测同轮 3 派仅 1 落地）。
    全文与理由见 `migao-dev-flow` §24 / §24.1（2026-09-25 裁定；2026-09-30 改判的现行口径见 §24.0）。

## 按场景找文档（先查索引，按需 Read）

| 场景 | 入口 |
|---|---|
| 全部场景索引 | [docs/wiki/INDEX.md](docs/wiki/INDEX.md) |
| 开发流程 / 验证命令清单 | [docs/wiki/Development.md](docs/wiki/Development.md) |
| 写码最少化（防过度建设/加依赖前） | [docs/wiki/Code-Minimalism.md](docs/wiki/Code-Minimalism.md) |
| 测试工程规范（拆分/ignore/脱敏/分层） | [docs/testing/test-engineering-standards.md](docs/testing/test-engineering-standards.md) |
| **验收/评测（下"验收通过"结论前必读）** | [docs/testing/acceptance-protocol.md](docs/testing/acceptance-protocol.md)（配套 DSH 技能 `migao-acceptance`） |
| CI/CD / 部署 | [docs/wiki/CI-CD.md](docs/wiki/CI-CD.md) |
| 行为用例单一源 | `.github/cases/`（改后必须跑 `render_cases.py` 并提交生成物） |

## 开发环境准备（获取研发模式）

「米高研发」= DSH agent preset（`preset.yml` + `agent.cordis.yml` + `migao-dev-flow` / `migao-acceptance`
两个技能），**权威源就是本仓库 [`.agent-presets/migao/`](.agent-presets/migao/README.md)** —— 随代码一起评审、一起回溯。
DSH 从 root `~/.dsh/.agent-presets/`（`USER_PRESET_DIR = '.agent-presets'`）发现 preset，
因此把它软链到本仓库该路径即可获得同一份研发模式。
**⚠️ 锚点必须指向「专职只读镜像」，不是任何会被开发/会被清理的工作区**（`#3849`/`#4026`）：

**⚠️ 顺序铁律：先合并含 `.agent-presets/migao/` 的 PR，再执行换链** —— 仓库尚无该路径时换链会让 DSH 当场失效。

```bash
# ① 建**专职只读镜像**（独立克隆；本机约定路径 $HOME/migao-preset-anchor —— 长期保留、勿删）
MIRROR="$HOME/migao-preset-anchor"
git clone --no-checkout <本仓库 URL> "$MIRROR"
git -C "$MIRROR" checkout --detach origin/main
ls "$MIRROR/.agent-presets/migao/preset.yml"     # 镜像里已有该路径才继续

# ② 摘掉旧目录 / 旧软链（若是实体目录，先备份而不是直接删）
mv "$HOME/.dsh/.agent-presets/migao" "$HOME/.dsh/.agent-presets/migao.bak-$(date +%Y%m%d-%H%M%S)" 2>/dev/null || true

# ③ 换链：-s 建软链 / -f 覆盖已存在项 / -n 不跟随已存在的软链目录
ln -sfn "$MIRROR/.agent-presets/migao" "$HOME/.dsh/.agent-presets/migao"

# ④ 校验：应能读到 preset 元数据与技能
cat "$HOME/.dsh/.agent-presets/migao/preset.yml"
head -3 "$HOME/.dsh/.agent-presets/migao/skills/migao-dev-flow/SKILL.md"

# ⑤ 每天/每次开工：自检（红就停）+ 自愈（把镜像刷到 origin/main）
./scripts/preset-anchor-check.sh       # 落后/悬空/内容不同 ⇒ 非零退出
./scripts/preset-anchor-refresh.sh     # 刷新镜像并复检（改预设的 PR 合并后必跑一次）
```

- **为什么锚点不能指向工作区**（两条实测，别把锚点当"另一个工作区"）：
  ① 工作区会**落后 main**：实测活锚曾指向落后 `origin/main` **42 个提交**的主工作区 —— 内容当时恰好一致
  （无害），但**下一次改预设的改进就到不了加载点**，后续所有会话按旧模式干活且**无任何东西变红**（`#4026`）；
  ② 工作区会被**清理/切分支**：实测一条 `rm -rf … migao-preset-live …` 把当时的软链目标硬删了 ⇒
  软链悬空 ⇒ **DSH 静默加载不到研发模式**（不报错，只是"模式不见了"，`#3956`）。
  `migao-wt/*` 的 worktree 属 `dev-worktree.sh rm/prune` 的清理半径，**同样不能当锚点**。
  ⇒ 任何清理命令执行**之前**先 `readlink "$HOME/.dsh/.agent-presets/migao"`，把解析出的目标及其父目录排除在外。
- **换机 / 新队友**：`git clone` 本仓库 → 跑上面 ①~④（独立克隆镜像 + 换链），即获得同一份研发模式
  （不再依赖个人 `~/.dsh` 手抄副本 —— 手抄副本没有跟随机制，必然腐烂）。
- **改研发模式 = 提 PR**：改 `.agent-presets/migao/**` 走正常 PR 流程（评审 + 回溯）。
  ⚠️ **合并后活锚不会自动跟上**：跑一次 `./scripts/preset-anchor-refresh.sh`（否则下次会话读到的仍是旧模式）。
- 历史独立仓库 `zhaokai-mgzn/migao-agent-presets` 现为**历史 / 镜像，以本仓库为准**；其远程去留（保留/归档/删除）**待用户裁定**，裁定前不动它。详见 [`.agent-presets/migao/README.md`](.agent-presets/migao/README.md)。

## 环境

- 本地只启 3 组件：admin-api(:8080) + ai-agent-service(:8001) + admin-web(:3001)；DB/Redis 用云 dev
- DSH 专用技能：`migao-dev-flow`（三把工具/提交流程/QA 门禁 §3.4）、`migao-acceptance`（验收/评测协议）——由「米高研发」preset 自动加载
