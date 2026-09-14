---
name: migao-dev-flow
version: 1.21.0
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

## 1. 三把工具（开发自查用）

| 工具 | 用途 | 何时用 |
|---|---|---|
| `./verify-all.sh quick/full/gate` | 三模块一键测试 + QA gate 预检 | 每次改动后、提交前 |
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
  - **硬约束：`# case_ids:` 必须出现在测试文件前 50 行内**（`growth_gate.py:extract_case_ids()` 只扫前 50 行；docstring 长的文件极易踩——实证：`# case_ids:` 落在第 71 行即被 QA Gate 判「未声明」block，须移到文件头或第 1 行）。
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

### 2.3 多会话并发规范（v1.3 新增，2026-09-04 实战固化：多 DSH 会话并行踩脚治理）

多会话并发（多 Agent / 多分支同时开发）时的铁律：**一个会话一个独立工作区，会话之间零共享写路径**。

1. **会话必须建在独立 worktree**：`./scripts/dev-worktree.sh add <branch>`（默认 `../migao-wt/<分支>`）。禁止多会话共用一个工作目录——同时改文件互相覆盖、`git add` 互带对方文件、同时跑 verify 抢资源。
2. **会话锁**：`dev-worktree.sh add` 自动登记 `.sessions/<branch>.lock`（含 PID+时间戳）；同一分支已有活跃锁时**禁止**重复建工作区/推分支。提交/推送前先 `./scripts/dev-worktree.sh list` 确认锁状态。
3. **端口隔离**：本地服务端口用环境变量覆盖（`API_PORT`/`AGENT_PORT`/`WEB_PORT`），会话各自 `.env.local`，杜绝 8080/8001/3001 互抢。
4. **主工作区只读**：主仓库（migao/）只做 `fetch/rebase/merge` 与 PR 管理，**不在主工作区直接改文件**（防止未提交改动静默携带）。
   - ⚠️ **硬红线：任何 worktree 里都禁止 `git stash` / `git stash pop` / `git reset --hard` / `git checkout -f`**（v1.18 新增，本会话两次实证：主仓库 stash 被 worktree 里的 stash pop+drop 误删，两次都靠 `git fsck` 找回悬空对象才救回）。**`git stash` 是仓库全局的、跨 worktree 共享**——你以为在动自己的 worktree，实际动的是主仓库的 stash ref。需要暂存/还原时：用 `git worktree add` 另开干净检出、或把改动 commit 到临时分支（stash 之外的任何方式都行）。
5. **分支卫生**：验证完即 PR，CI 绿即合并，分支存活 < 1-2 天；定期 `git branch --merged origin/main` 全删 + 清理 `origin gone` 的本地分支。
6. **开工前读契约**：`docs/wiki/CONTRACT-LEDGER.md`（状态枚举/字段名/端点签名）；跨模块改动后跑 `./contract-check.sh`。

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

- push 分支 + 开 PR 后，**必须先等到首轮 CI 出结论再转场**（`gh pr checks <PR> --watch` 或轮询 `gh pr checks <PR>`），禁止创建完 PR 就去做别的，让 CI 红着挂 2 小时。
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

## 12. 验收/评测结论前必加载 migao-acceptance（v1.8 新增，2026-09-08 复盘固化）

- **触发**：任何「验收通过 / 评测 OK / 交付完成」结论、验收 agent 会话/功能/修复回归、写/改评测 case 或验收场景——先加载技能 `migao-acceptance`，按 `docs/testing/acceptance-protocol.md` 执行（协议单一事实源）。
- **背景**：2026-09-08 人工重点验收 3 个 agent 会话（sess_7f27137647e14b1e / sess_50ff3e3c824c4a70 / sess_c1fce183dae24f22）发现的问题，此前评测与验收全部判过 OK。根因：评测断言"工具被调用"而非"用户看到的会话"、关键行为写在不计分的自然语义 data_checks、无时序/金额/卡片内容断言、验收视角与开发者同源、前端渲染与生命周期是结构性盲区。
- **一句话**：三把工具保证"不崩、契约对"；本协议保证"用户看着好"。

## 13. 行为改动自动体检（agent-eval 用例回归，v1.9 新增，2026-09-08 固化）

**铁律**：改动 ai-agent 的**行为/交互**（prompt、Tool、引导流程、交互卡逻辑）后，
**提交前自动跑相关评测用例**——不等用户要求、不靠用户记脚本。这是「米高研发」模式的
自动动作，不是可选项。

### 13.1 必跑命令

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
| PR 改 AI 行为文件 | C 端 smoke（persona=xiaobu）+ B 端 smoke（pr-check，打云测试环境） | 信息性（**不阻塞**） | #3504 |
| PR 改 AI 行为文件 | **映射用例迭代档**（diff → §13.2 用例集，独立栈跑 + PR 评论）——**分层**：规则命中的用例失败 → **阻塞**；兜底默认集失败 → **只报告**（与本 PR 无因果，评论显式标注"⚠️ 兜底网（不阻塞）"） | 规则桶阻塞 / 兜底网信息性 | #3502 |
| 合并 → 部署到 SWAS 成功 | **部署后全量回归**（独立栈 mibao+xiaobu，matrix 并行）→ 失败去重建 issue | 部署后拦截 | #3503 |
| 每周六 | adversarial 档（只追踪不阻塞） | 信息性 | #3367 |
| 里程碑/下结论 | 结论档（全量 + 验收剧本 + 双裁判 + completion_verdict） | **结论前置（必过）** | §16.4 |

**⚠️ 最容易误读的一条**：分支保护的 required_status_checks 只有确定性层那 9 项
（`.env`/三模块单测/QA Gate/ci-helper/gitleaks/Danger Scan）——**LLM 行为层不进 required
是有意设计**（真实 LLM 方差会卡死合并流水线；job 名还随 persona 参数化）。
⇒ **C 端 smoke 红 ≠ 不能合并**，而是"立刻拿到行为信号，据此决定"；硬拦截由确定性层
（required）+ 部署后全量（#3503）承担。禁止把 LLM 档改成 required（历史决策，勿翻案）。

**📌 决策记录（2026-09-14，用户确认）**：**行为映射门禁（agent-behavior-eval）同样不纳入
required**，理由与上同（方差 + persona 参数化 check 名）。它的拦截力是"规则命中用例失败 →
workflow 内红 + PR 评论"（强信号）；**规则命中红 = 改动真的影响了行为，必须先看产物再决定，
不得当作可忽略**。若将来要纳入 required，必须先把"确定性部分"与"LLM 部分"拆开，
**禁止裸加 required**。

**队友约定**：这些门禁是**自动**的，不要重复人工跑同一档；PR 红了先看门禁产物
（映射用例评论 / summary json / flake 台账 artifact），再决定重跑或修复。
波动台账现上传 artifact（`agent-eval-flake-ledger*`，30 天）——高波动用例治理
（§14.3 双周回顾）从这里取数，不再翻 run 日志。

### 16.6 评测派发与数字留痕（v1.18 新增，2026-09-14 实证固化；v1.20 修正第 1 条）

四条都是本会话**踩过**的（每条都有 run 级证据），照做能省一整轮 90min 评测：

1. **手动派发的现状真值（v1.20 修正，#3709 修复后）**：`workflow_dispatch` **默认免抑制**。
   `eval_supersede.sh` 按 `EVENT_NAME=workflow_dispatch` ⇒ `FORCE_EVAL=true`（语义 = 人显式要求
   "我就要这一条"，回滚复验/补跑）；**要恢复「被取代即抑制」必须显式传 `-f force_eval=false`**
   （逃生口保留，省成本路径不消失）。**自动门禁**（`workflow_run` 部署后 / `schedule` 每 3 天全量）
   语义**不变** —— 它们没有 inputs，不受该默认值影响。
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
   `tests/agent_eval/local_runner.py:4292`）。⇒ 定向派发**只能传两端都适用的 ID**；
   要单端验证就在该端派发，**不要**指望另一端"自动跳过"。
   （实测：传 6 条 B 端 ID → xiaobu 腿 3 分钟内红，白烧一条腿。）

3. **`continue-on-error` 让"步骤显示 success"≠"步骤成功"。** `post-deploy-eval.yml:494` 对
   `Run <persona>` 步骤设了 `continue-on-error: true`（有意设计：红信号统一由 `判定（completion_verdict）`
   步骤产生，避免真实 LLM 方差卡死流水线）。⇒ **读 run 结论只看 `判定` 步骤 + artifact**，
   别拿 `Run` 步骤的颜色当结论。（实测：xiaobu 腿 `Run` 显示 `success`，实际 exit code 1。）

4. **每个计数必须锚定 SHA —— 禁止"旧基线配新结果"。** 实测：两个包分别报告
   `604→612`（#3712）与 `604→618`（#3713），**各自对自己当时的 base 都成立**；
   但当前 main（`4c1f47ae`）实测是 **626** = 604 **+8**(#3712) **+14**(#3713)。
   写数字时必须写 **`基线 @<sha> = N → 本 PR = M`**。否则会造出**幽灵 delta**，
   下一个人拿它判"测试数漂移 / 覆盖退化"就会误判（本会话已发生一次）。
   同理：**报"某 run 通过"必须带 run id + SHA**；报"某 issue 已关闭"必须核**病灶是否仍在**
   （关单 ≠ 病灶消除，见 migao-acceptance v1.4）。

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

> **一句话**：**「分支 ≠ 交付」**。squash / rebase / merge 三种合并方式都会让「commit 可达性」失去判据意义；只有**主干上的文件内容**是事实。这两行是同一枚硬币的两面：上一行防「以为合了其实没合」，这一行防「以为没合其实合了」。

## 版本沿革（v1.1 → v1.21）

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
- v1.18（2026-09-14 实证固化）：新增「§16.6 评测派发与数字留痕」四条踩过的坑——① 手动 `workflow_dispatch` 评测**必须**带 `-f force_eval=true`（否则被静默抑制：步骤全 skipped、artifact 0、整体 success；workflow 注释里的"永不抑制"与实现不符）〔⚠️ **该条已被 v1.20 修正**：现在 dispatch **默认免抑制**，要抑制才需显式 `force_eval=false`——勿照抄本条〕；② `case_ids` 是**全矩阵共享**的，只传一端专属 ID 会让另一条腿立即红（`禁止静默少跑` 守卫 `local_runner.py:4292`）；③ `continue-on-error` 让 `Run <persona>` 步骤"显示 success ≠ 成功"，读结论只看 `判定（completion_verdict）` + artifact；④ **每个计数必须锚定 SHA**（`基线 @<sha> = N → 本 PR = M`），禁止旧基线配新结果造出幽灵 delta。
- v1.19（2026-09-14 实证修正）：**§2.1 ②`./verify-all.sh gate` 必须在 `git commit` 之后跑** —— 它的弱断言检查按 `git diff --diff-filter=A origin/main...HEAD` 取"新增测试文件"，**未提交时新增集为空 ⇒ 静默空跑并通过**（假绿；实测同一命令 commit 前 ✅ / commit 后 ❌）。正确顺序：先 commit，再跑 ②③④。
- v1.20（2026-09-15 实证修正，issue #3709）：**修正 §16.6 ①**——`workflow_dispatch` 评测**默认免抑制**（要恢复「被取代即抑制」须**显式**传 `-f force_eval=false`），故 v1.18 那条「手动派发**必须**带 `-f force_eval=true`」已成**假真值**；被抑制时 run 上现在有 `::warning::` 标注 + summary 抬头「本 run 未评测」，**据此不得再把「绿」读成「评测通过」**；自动门禁（workflow_run/schedule）语义不变。并在 §2.2 补「引用式 `Closes` 样例同样会被朴素正则命中」的自检提示（PR body 证据表是同一入口）。
- v1.21（2026-09-15 实证修正，本次）：**修掉 frontmatter `description` 被 YAML 静默截断**（纯标量在第一个「空白 + `#`」处截断）——实测原文 2666 字符仅解析出 192 字符，v1.12/v1.17/v1.18/v1.19/v1.20 的说明**从未**被 skill 加载器读到。取舍：`description` 收敛为**有意简短的摘要**，**沿革迁入正文本节**（不靠加引号救长文本，避免「可无限追加」的坏习惯复发）；并登记「加载器只读 `name`/`description`，且要求第 1 行是 `---`」。
