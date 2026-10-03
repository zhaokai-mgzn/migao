# 开发指南

## AI-TDD 流程

强制 Red→Green→Refactor，**7 个检查点（CP-1~CP-7）缺一不可**。

> 本节是 AI-TDD 铁律的**仓库载体**：根 `CLAUDE.md` 已随仓库精简删除（issue #2646/#2647），
> 其正文于 issue #5081 迁入本节（命令部分按现状重写，未照抄已过期的清单）。
> DSH「米高研发」preset 的会话入口与 `.github/PULL_REQUEST_TEMPLATE.md` 都回指本节。

| CP | 步骤 | 动作 |
|----|------|------|
| CP-1 | 识别范围 | 列出受影响模块 + 测试文件，回答测试覆盖问题 |
| CP-2 | Red | 先写测试，运行确认 **FAIL** |
| CP-3 | Green | 最小实现，测试 **PASS** |
| CP-4 | Refactor | 重构，测试保持 PASS |
| CP-5 | 单测全量 | 受影响模块**全量**单测 PASS |
| CP-6 | 集成 + E2E | 增量集测 + E2E + 类型检查 PASS |
| CP-7 | 自检 | 逐项勾选确认清单 |

**AI 行为约束（以下规则对 AI 有硬约束力，违反任一条视为失职）**：

- **禁止「改完再说」**：不得先实现功能再补测试，必须先写测试 → 确认 FAIL → 再写实现 → 确认 PASS。
- **禁止「看起来没问题」**：声称完成前必须贴出测试运行结果，不得仅凭代码审查判断正确性。
- **禁止跳过 CP-5**：改动涉及模块的全量单测必须跑且全部 PASS，不跑 = 视为未完成。
- **禁止「这个改动太小不需要测试」**：任何逻辑改动（字段新增、参数变更、条件判断等）都必须有测试覆盖；纯文案/格式化改动除外。
- **改动前先报告测试覆盖情况**：CP-1 阶段必须明确说出「本次改动涉及的模块有 X 个测试文件，其中 Y 个直接覆盖改动点」；**Y=0 ⇒ 必须先补测试再改代码**。

### CP-1：识别变更范围（Identify Scope）

**必须回答**：本次变更涉及哪些模块？涉及哪些文件？

- 后端 `backend/admin-api` / `backend/ai-agent-service`；前端 `frontend/admin-web` / mini-app；配置 / CI（`.github/workflows/`）
- 测试：新增测试文件 / 修改现有测试（头部必须声明 `# case_ids:`）
- 涉及**新交互组件**（按钮/表单/卡片等）⇒ 需 E2E 完整点击链路
- 涉及**新 SSE 事件**（`tool_call` / `tool_result` / `interact` 等）⇒ 需 E2E 事件验证
- 涉及**新 Tool**（写操作）⇒ 需 E2E confirm 前校验 + `tool_result` 验证
- 涉及**核心业务流程**（订单/商品/客户等）⇒ 需同步 `tests/e2e/specs/quality/` 的 api-contract 与 cross-page-consistency

**输出**：受影响模块与测试文件清单 + 测试覆盖情况回答。

### CP-2：Red 阶段 —— 先写测试（Write Tests First）

**铁律：禁止先写实现代码再补测试。**

- 新增功能：先写功能测试（单元 + 集成 + E2E）；修复 Bug：先写能复现 Bug 的失败测试；重构：先确认现有测试覆盖重构目标
- **E2E 覆盖决策（必须执行）**：检查 `tests/e2e/` 是否已覆盖本次变更 → 评估是否需要新增（需要：用户交互流程 / API 端点 / 跨模块集成 / 数据持久化；不需要：纯内部逻辑 / 配置变更 / 文档更新 / 已有 E2E 覆盖）→ 需要则先写用例
- 运行新增/修改的测试，**必须看到 FAIL**（未见到失败 = 测试没验证到东西）

**输出**：测试运行结果，必须包含 `FAILED`。

### CP-3：Green 阶段 —— 写最小实现（Implement Minimal Code）

**铁律：只写能让测试通过的最小代码，禁止过度设计。**

**输出**：同一组测试的运行结果，必须包含 `passed`。

### CP-4：Refactor 阶段 —— 重构代码

**铁律：重构时必须保持测试持续通过，禁止破坏现有功能。** 每次重构后重跑测试。

**输出**：重构后的代码，测试仍然 PASS。

### CP-5：单测全量验证（Full Unit Test）

**铁律：变更涉及的所有模块，必须运行全量单测，全绿才算完成。**

```bash
./verify-all.sh full      # 三模块全量单测
```

**输出**：所有单测 `passed`，无 `failed`。（模块内定向命令见 `docs/wiki/Testing.md`。）

### CP-6：集成测试 + E2E 测试增量验证（Incremental Integration & E2E Test）

**铁律：只跑本次变更涉及的集成测试与 E2E（避免全量回归耗时过长），但下列检查缺一不可。**

```bash
./verify-all.sh quick            # 受影响面的常规回归（含前端 vitest + tsc）
./check-ui-regression.sh         # UI 回退检测（防工作区旧 UI 覆盖验收版）
./contract-check.sh              # 跨模块改动：三端契约一致性
```

- 前端类型检查必跑（`npx tsc --noEmit`）
- 真实 E2E 前需重启本地服务，见 `tests/README.md`

**输出**：集测 `passed`、`tsc` 退出码 0、E2E `passed`（如有新增）。

### CP-7：完成自检清单（Self-Check Before Completion）

**铁律：声称「完成」或准备合并 PR 前，必须逐项勾选以下清单。**

```
□ CP-1：已识别变更范围，已回答测试覆盖情况
□ CP-2：已先写测试，运行确认 FAIL
□ CP-3：已写实现代码，运行确认 PASS
□ CP-4：已重构代码，测试仍 PASS
□ CP-5：已运行受影响模块的全量单测，全部 PASS
□ CP-6：已运行本次变更涉及的增量集测 + E2E + 类型检查，全部 PASS
□ CP-7：已完成本自检清单，无遗漏
□ E2E 测试覆盖决策已显式执行（新增 / 已有覆盖 / 不需要并说明原因）
□ 新增交互组件 → E2E 覆盖完整点击链路（渲染→点击→发送→验证）
□ 新增数据列表页 → 已在 tests/e2e/specs/quality/anti-placeholder.spec.ts 的 PAGES 数组中注册
□ 新增/修改 API 返回字段 → 已在 api-contract.spec.ts 验证必填字段存在 + 类型正确
□ 修改列表/详情字段 → 已在 cross-page-consistency.spec.ts 验证一致性
□ E2E 使用 Page Object 复用交互，禁止手写 mock（用 Record-Replay fixture）
□ 无硬编码密钥、无敏感信息泄露；相关文档已更新
```

**输出**：勾选完整的自检清单，无未勾选项。

### 违规后果

| 违规行为 | 后果 |
|---------|------|
| 先写实现后补测试 | 立即停止，删除实现代码，回到 CP-2 重做 |
| 跳过全量单测（CP-5） | 禁止合并 PR，必须补跑 |
| 跳过增量集测 / E2E（CP-6） | 禁止合并 PR，必须补跑 |
| E2E 弱断言（仅检查可见性 / 无数据断言） | 视为虚假完成，重写为强断言（tool_result / tool_call / 数据字段） |
| 新增交互组件未覆盖完整点击链路 | 禁止合并 PR，必须补 E2E 完整链路 |
| 新增业务数据列表/详情页未注册 anti-placeholder | 禁止合并 PR，必须先注册 PAGES 数组 |
| 未完成自检清单就声称「完成」 | 视为虚假完成，必须重新执行所有检查点 |
| 测试失败仍然提交代码 | 立即回滚，修复测试后再提交 |

**PR 合并前置**: 重启本地服务 → 全量单测 PASS → 增量集测 PASS → 增量 E2E PASS。缺一不可。

## 分支/Commit

```
feat/<scope>-<desc>    # scope: frontend/backend/ai-agent/qa/infra
fix/<scope>-<desc>
chore/<scope>-<desc>
```

Commit: `feat(frontend): 描述` / `fix(backend): 描述` / `test:` / `refactor:` / `docs:` / `chore:`

禁止 push main，必须 PR + 关联 Issue (`Fixes #xxx`)。

## 本地验证与分支治理（2026-09-01 实战教训）

**教训**：曾积压 40+ 本地分支未合并，切换旧分支后工作区被旧代码覆盖，未提交改动被静默携带 → 「切换分支后功能退化」。规则：

1. **分支开即关联 Issue，验证完即 PR，CI 绿即合并**——分支存活目标 < 1-2 天。
2. **切换分支前 `git status` 必须干净**（有改动先 commit/stash）——未提交改动会被静默带到新分支。
3. **本地验证必须基于最新主线**：验证前先 `git fetch origin main && git rebase origin/main`，否则验证的是旧基线。
   - ⚠️ **改了 `.github/cases/**`（或 `.github/case-trust-baseline.json`）的分支，同步 main 必须用 `./scripts/sync-main.sh --rebase`**（issue #4984）：merge 会把「本分支缺少 main 新增的用例销账块（`must_succeed` / `namespaces` / `precondition` 等）」当成**有意删除**、**无冲突**接受 ⇒ **静默回退** main 已缴的 case-trust 债（实测 #4965：5 个文件净删 −27/−25/−20/−3/−2 行），随后门禁判红且**归因指向错误方向**。`sync-main.sh` 的 merge 模式现已**前置拒绝**这种组合 + 合并后**内容级校验**；替代路径就是 `--rebase`。另：冲突文件**恰好只有 `CHANGELOG.md`** 时本脚本会自动保留两侧条目（块之间空行分隔）并做三条内容级验证 —— 无残留冲突标记 / `### ` 条目集合 == 两侧并集（一条不丢）/ 两侧原版逐行按原序保留；任一条不过就**还原成冲突态** + 退出 1 交人工。**其它任何冲突形态行为不变**（原提示 + 退出 1）。
4. **多分支并行验证用 git worktree**（每个分支独立工作目录，切换零污染）：
   ```bash
   ./scripts/dev-worktree.sh add <branch>   # 建独立工作区（默认 ../migao-wt/<分支>）
   ./scripts/dev-worktree.sh list
   ./scripts/dev-worktree.sh rm <分支> --delete-branch
   ```
5. **定期清理滞留分支**：
   ```bash
   git branch --merged origin/main | xargs git branch -d            # 已合并全删
   git cherry origin/main <branch> | grep -c '^+'                    # 全 '-' = 内容已落地，可删
   git log origin/main..<branch> --oneline                           # 看独有提交，确认无独有内容后删
   git worktree prune                                               # 清残留 worktree
   ```
   删除前先确认分支内容已通过 PR 合入 main（squash 合并后 hash 不同，`git cherry` 仍会显示 `+`，以 PR 状态与文件内容为准）。

### worktree 依赖准备（2026-10-01 固化，issue #5930）

> 🔴 **依赖一律在本工作区内安装（npm ci）；禁止把 node_modules 软链到主工作区或其他工作区**

每个 worktree 都是独立目录，依赖请**在本工作区内**装（这也是 `./scripts/dev-worktree.sh add` 建完工作区时
打印的那一段 —— **本页与脚本同源**，不各写一份）：

```bash
cd <worktree> && npm ci                       # 根依赖
cd <worktree>/frontend/mini-app && npm ci     # 子包依赖（有该子包时）
```

**为什么这条是硬的（2026-10-01 22:18 现场事故，issue #5930）**：主工作区 `tests/node_modules`
被清成**空目录**。成因是**一个类** ——「跨工作区共享 `node_modules` 的软链」×「任何会删/重建
`node_modules` 的动作」。本包实测复现：worktree 的 `tests/node_modules` 是指向主工作区的软链时，
在它所在目录跑一次 `npm ci`（第一步就是删 `node_modules`）⇒ **目标目录仍在、内容全空**（fixture 3 → 0 个文件）。
这类破坏**在仓库外发生、git 里看不见**（软链不入库）⇒ **没有任何判据会因此变红**，是典型的静默失效。

- **正确姿势** = 上面那两条命令（每个 worktree 自装）；不要用软链「省一次安装」——
  省下的几分钟会以「另一个工作区的依赖被清空」的形式还回来，而且**当场没有任何东西会报**。
- **`rm` 侧的安全网**：`./scripts/dev-worktree.sh rm`（以及 `rm --delete-branch`）在
  `git worktree remove` **之前**先把 worktree 内的符号链接逐一解链，并**具名打印**每条
  「路径 → 目标」；指向**仓库外 / 本仓库工作区**的形态另加 ⚠️ 点名（后者正是本事故的成因）。
  ⇒ 删除动作**不可能**穿过软链（顺序即安全顺序）。**有意不 fail-closed**：解链之后破坏动作已经结构安全，
  而拒绝只会逼人改用 `rm -rf <worktree>`（那一条**不解链**，反而把暴露面重新打开）。
- **判据**：`tests/unit_ci_workflows/test_dev_worktree_symlink_safety.py`（用例 MC-054）——
  控制流判据（解链调用必须先于删除、且不许只写在注释里）+ 真 fixture 上的 PATH 垫片见证
  「删除那一刻还有没有软链」+ 外部目标逐字节完好 + 类级教法扫描（仓内不许把这个姿势教成步骤）。

## 本地验证防恶化（2026-09-06 固化，issue #2957）

**背景**：`verify-all.sh quick` 宣称 3-5 分钟，曾实际恶化到 **58 分钟跑不完**（单用例真实连阿里云 RDS 挂起数十秒 × 数百用例），而 CI 因无 `.env` 一直正常（1-3 分钟）——本地/CI 差异是环境问题信号，不是业务代码问题。

**根因**：本地 `.env` 的 DATABASE_URL/REDIS_URL 指向云 dev（阿里云 RDS/Redis **公网地址**），单测中未 mock 的存储调用（SessionStateStore/SessionMemory/context_manager）真实连接云库 → 每用例挂起/超时数十秒。此类恶化是**渐进累积**的：每新增一个依赖就多几个未 mock 的真实调用，无明显单点故障。

**已固化防复发机制**（PR #2960 合并）：
1. `backend/ai-agent-service/tests/conftest.py` 顶部 `os.environ.setdefault("DATABASE_URL"/"REDIS_URL", localhost)` —— setdefault 不覆盖 CI 注入的真实 env（环境变量优先级高于 .env 文件）；单测内未 mock 连接毫秒级拒绝走降级。
2. `pytest.ini` 保留 `--timeout=120 --timeout-method=thread`：hang 用例 120s 兜底快速失败。
3. `verify-all.sh`：ai-agent quick 去 `--no-cov`、full 用 `-n 4` 并行（pytest-xdist）。

## verify-all.sh 档位覆盖面（2026-09-14 固化，issue #3680）

**quick 与 full 对 ai-agent 用同一选择集**（`AI_AGENT_TESTS="tests/ -q --no-cov -n 4"`）——
quick 省掉的只是 admin-api 的**全量** Maven（`mvnw test` vs `mvnw test -q`）等开销，
**不是 ai-agent 覆盖**：两档的 ai-agent 判据完全一致。

| 档位 | admin-api | ai-agent | admin-web |
|---|---|---|---|
| `quick` | `./mvnw test -q` | `pytest tests/ -n 4` | vitest + tsc |
| `full`  | `./mvnw test` | `pytest tests/ -n 4` | vitest + tsc |

**实测墙钟（issue #3680 取证，本机）**：ai-agent 检查项改前 **1103 passed / 13.8s** →
改后 **3859 passed / 20 skipped / 44.2s**（+30s；`-n 4` 并行）。
整档 `./verify-all.sh quick` 改前 **1m35s**、改后 **2m15s~3m10s**（负载波动下可拉长；
本机曾因另一会话 Maven 满载量到 3m9s~5m50s）。**整档耗时大头始终是 admin-api 的 Maven**，
故本改动不改变"快档"定位；若整档持续 >5 分钟，先按上文「本地验证防恶化」体检（环境问题）。

**教训（本地绿 / CI 红制造机）**：quick 的 ai-agent 选择曾是 glob 白名单
（`tests/unit tests/test_tools_*.py tests/test_graph_*.py tests/test_intent_router.py`），
当时只匹配 `tests/` 顶层 169 个测试文件里的 42 个 —— 其余 127 个（~75%）被**静默跳过**
（不报错、无提示、退出码 0）。实证：PR #3674 本地 `./verify-all.sh quick` 绿，CI 却红在
`tests/test_order_create_quantity_bounds.py`（#3622 的 L0 静态不变式），而 `gate` 档只跑
QA 预检、不跑单测 ⇒ 开发者本地**没有任何一层**能看到它。

**红线**：禁止把 ai-agent 选择改回 glob 白名单（**失败开放**：新增顶层测试文件默认漏掉）；
`tests/` 目录选择是**失败关闭**的（新增文件默认被覆盖）。
守卫：`tests/unit_ci_workflows/test_verify_all_quick_scope.py`（L0，含真实 `--collect-only`
行为验证 + 旧白名单变异测试），改回去必红。

### `gate` 档的 bmini 腿 + 本地门禁覆盖矩阵（2026-09-27 固化，issue #4221 族）

`frontend/bmini-app`（Taro 一源双编译，B 端 h5 + 小程序）此前在 `./verify-all.sh` 里
**没有任何腿** ⇒ 改 bmini 的包在本地拿不到 `tsc` / `jest` / `build` 覆盖，只能手工跑
（最近两个 bmini 包的回报里逐字写着「手工跑了三条」）；而 CI 侧有两条腿
（`.github/workflows/bmini-app.yml`）⇒ **缺口只在本地**，代价 = 一轮 CI 往返。

现在 **`gate` 档**按「变更集命中触发面」派发一条 bmini 腿，四件与 CI **逐字同命令**：
`npx tsc --noEmit` / `npm test` / `npm run build:h5` / `npm run build:weapp`。

- **只在 `gate` 档**：`quick` 是开发者快循环，3~5 分钟的构建不进快档（用户裁定）；
- **触发面 = 该腿判定对象的输入闭包**：`frontend/bmini-app/**` ＋ 它 import 到的**跨目录**仓内文件
  （现取 1 个：`frontend/admin-web/src/lib/print-media.json`）。**有意不照抄** CI 的谓词
  （CI 是 `frontend/bmini-app/|tests/|\.github/` —— 后两类改动**影响不到** tsc/jest/build，
  照抄只会让不相关的改动多等 3~5 分钟）。⚠️ 这个差异**不会**制造「本地绿 / CI 红」：CI 的触发面
  比本地**更宽**，而两侧跑的是**同一批命令**（同源判据见下）—— 本地省掉的只是「在不相关的 PR 上
  白跑一遍 bmini」；反过来，任何**可能改变判定结果**的输入（模块目录 + 跨目录 import）都在本地
  触发面内，且新增未裁定的跨目录输入会**判红**；
- 🔴 **缺依赖 ⇒ fail-closed（记 ❌，**不**跳过）**：`node_modules` 缺失/装不全时打印「缺什么 +
  `cd frontend/bmini-app && npm ci`」并让 `gate` 非零退出 —— `⏭️ 未就绪` 在**合并门禁**上会被读成
  「这项没事」，而这条腿存在的全部意义就是拦住 bmini 的编译/类型错（**「没跑」不得等于「通过」**）。
  这是三态之外的**第四态**，适用范围严格受限：只在变更集命中该腿触发面之后（否则是假红）；
- 未命中触发面时控制台**显式声明「未跑」**（不是 ✅）。

**覆盖面本身也是一张具名登记的矩阵**：`tests/unit_ci_workflows/local_gate_matrix.json`
（模块 → 档位 / 腿名 / 覆盖形态；`uncovered_modules` 与 `trigger_face_uncovered_inputs` 登记缺口）。
判据 = `tests/unit_ci_workflows/test_local_gate_matrix.py`：**新增一个模块目录而不登记 ⇒ 红**；
登记的腿从 `verify-all.sh` 里消失或换档（声称档位 ≠ 实际出现档位）⇒ 红；新增跨目录输入而没裁定
⇒ 红；未覆盖台账**只许缩短**（上限现取、写死在判据里）；本地腿的四条命令与 CI YAML 漂移 ⇒ 红。
**已登记缺口（本单只登记、不扩面）**：`frontend/mini-app` 本地无腿（CI 的 `mini-app.yml`
两条腿兜）—— 见 `uncovered_modules`。

**「未就绪」不得等于「通过」（同族，`FM-E10`）**：`verify-all.sh` 的 `report_env()` 在依赖没装好时打
`⏭️ 未就绪`（跳过）—— 这在**开发者快循环**里是合理的，但在**合并门禁**上「没跑」会被读成「这项没事」。
bmini 一条腿已改成**第四态** `report_strict()`（变更集**命中**它的触发面 ⇒ 依赖缺 ⇒ 记 ❌ 且非零退出）；
**其余走 `report_env()` 的腿仍是 ⏭️` ⇒ 已具名登记为未守护缺口**，逐条见
`docs/wiki/CI-CD.md` 的「CI / 台账反复出错点」节（`FM-E10`，含 owner、现取读数与方案）。
⚠️ **两个口径要分开**：#5707 现取「本机打 ⏭️」的 3 条腿**全是缺依赖**（= 环境，不是门禁缺陷，CI 上它们真跑）；
门禁缺陷只是「变更集命中某模块 + 依赖缺 ⇒ 本地绿」这一形态，而**合并门禁档（`gate`）主路径已经没有 `report_env` 模块腿**。

**工装坑：`node --test <dir>` 是假红（`FM-E14`）**：Node 内置 runner 传**目录**会被读成 **1 条失败**，
必须传 glob（`node --test <dir>/*.test.mjs`，本仓 `verify-all.sh` 的 worker-h5 腿就是这么写的）。
✅ **#5707 已落判据**（不再是缺口）：判据 13 =
`tests/unit_ci_workflows/test_dev_mode_failure_modes.py::test_node_test_targets_are_globs_in_the_registered_carriers`
—— 射程 = **两处具名载体**（`verify-all.sh` + `.github/workflows/worker-h5-tests.yml`）；
把任一处的参数字面量改成目录形态 ⇒ **该判据判红**。逐条见 `docs/wiki/CI-CD.md` 的 `FM-E14`。

**开发中体检**（发现本地验证变慢时按序，秒级）：
```bash
cd backend/ai-agent-service
# ① 云库隔离
grep -q 'os.environ.setdefault("DATABASE_URL"' tests/conftest.py && echo "✓ 云库隔离" || echo "⚠️ conftest 缺 DATABASE_URL setdefault"
# ② timeout 兜底
grep -q -- '--timeout=' pytest.ini && echo "✓ timeout 兜底" || echo "⚠️ pytest.ini 缺 --timeout"
# ③ 最慢用例
pytest -q --durations=20    # 单用例 >2s 即可疑
# ④ 干净环境对照（决胜手段）：worktree + 新 venv 跑同代码，快 = 环境差异
```

**红线**：
- 新增测试**禁止**引入未 mock 的真实外部存储调用（SessionStateStore/SessionMemory/context_manager/DB/Redis）——见 test-engineering-standards.md §6。
- 升级 requirements.txt 后立即本地 `pip install -r requirements.txt`，防依赖版本漂移导致本地/CI 行为不一致。
- 每日定时真 LLM 任务连续失败 → 停用 schedule（保留 `workflow_dispatch`）修稳后再恢复，防自动开 issue 刷噪音（2026-09-06 已停 e2e-real/xiaobu-acceptance/nightly）。

## 机器级重活并发准入（2026-09-30 固化，issue #5814）

**病（现场实测，不是推断）**：2026-09-30 14:24 CST，三份**同样的**全量 `tests/unit_ci_workflows`
同时跑在 8 核开发机上 —— ① 自托管 runner 的 CI job（现已停用）② 本会话一个 subagent 的
`./verify-all.sh gate` ③ **另一个会话**一个 subagent 的 `./verify-all.sh gate`
（`migao-wt/orders-new-batch5`）；外加 6 个 `node (vitest)` 孤儿（PPID=1）从 13:56 烧到 14:24
（28 分钟纯浪费）；`load average` 一度 **45.44**，处置后回到 **2.87**。
⇒ 类级病 = **同一台机器上的重活没有并发准入**（3 份里 2 份是 agent 会话造成的，与 runner 无关）。

**修法（一条命令覆盖三类）**：`scripts/machine-heavy-lock.sh`

```bash
./scripts/machine-heavy-lock.sh status           # 只读：锁持有者 / load average / PPID=1 孤儿 / top CPU
./scripts/machine-heavy-lock.sh acquire <名字>    # 拿锁（拿不到 ⇒ 非零退出 + 谁在跑 + 可复制 kill 命令）
./scripts/machine-heavy-lock.sh release          # 释放（只释放自己持有的那份）
```

- **锁文件在机器级共享路径**（默认 `$HOME/.migao-heavy.lock`，可用 `MIGAO_HEAVY_LOCK_FILE` 覆盖）——
  🔴 **绝不能放各自 worktree**：漏掉的正是**跨会话**那一路（两个会话各持各的锁 = 「有锁」与「没锁」
  在机器上完全一样）。
- **`acquire` 顺手回收孤儿**（机械动作，不靠人记得）：判定 = `PPID == 1` **且** 进程名命中测试
  运行器族（node / vitest / jest / playwright / pytest）**且**命令行里有一个 token 落在已知工作根
  （`_work` / `migao-wt` / 主工作区）之下。**为什么安全**：这类进程的父进程已经没了 ⇒
  **不可能是任何人正在等的结果**；且用**路径前缀**限定射程 ⇒ **只杀 CI 工作区 / worktree 下的**，
  **绝不按名字裸杀**（`MIGAO_HEAVY_ROOTS` 可覆盖射程）。
- **接线**：`./verify-all.sh gate` 是**全量套件的唯一入口**；🔻 **锁的射程（v1.96.0 改判，issue #5863）
  覆盖所有会跑全量测试的档**（`quick` / `full` / `frontend` / `backend` / `agent` / `redproof` / `gate`）——
  原实现只包 `gate`，理由是「其余档不是同一台机器上的重活」，而该前提与事实不符（`full` 档按脚本自己的
  档位说明就是三模块全量 ~10-15 分钟；实测 `gate` 持锁期间 `load average` 16.71/28.71/20.14 / 8 核 ⇒
  锁外确有重活）。未知 / 空档位不拿锁。进入前 `acquire`、`trap … EXIT` 释放；**拿不到锁 ⇒ 非零退出 + 出声**（不是静默跳过、
  更不是记成 ✅ —— 「没跑」必须长得像「没跑」）。三态语义（✅/❌/⏭️）一字未改。
- **值守面**：`acquire` 的**拒绝行为** + `status` 读数。**没有常驻守护进程 / launchd agent** ——
  **拒绝本身就是机制**（不是「提醒你记得去看」）。
- 🔻 **「直连整目录」那一路也已收进锁**（2026-10-02，issue #6019）：**套件自带 acquire/release** ——
  `tests/unit_ci_workflows/conftest.py` 在 `pytest_collection` 钩子里拿锁（**任何收集之前**）、
  在 `pytest_sessionfinish` 里释放；**拿不到 ⇒ `pytest.exit` 非零 + 出声**（含锁文件路径 / 持有者 /
  `./scripts/machine-heavy-lock.sh status`），默认不排队、`MIGAO_HEAVY_WAIT` 存在时排队。
  触发面**只在整目录**（位置参数覆盖整个 `tests/unit_ci_workflows`，含 `--collect-only`）；
  跑子集（单文件 / `-k` / `-m` 收窄）**不拿**（研发日常，很轻）。三类**有意豁免**（各有判据）：
  `MIGAO_HEAVY_LOCK_HELD=1`（祖先已持锁 ⇒ 再 acquire 就是死锁）/ `CI` 为真（托管 runner 不占本机）/
  xdist worker（只在控制器拿一次）。`verify-all.sh` 拿锁成功后 `export MIGAO_HEAVY_LOCK_HELD=1`
  （嵌套的 ci-helper 腿不要二次 acquire）。台账登记为 `surface=suite-internal` 载体
  （它在 `tests/unit_ci_workflows/**`，**不在**语料普查面内 ⇒ 由
  `test_heavy_suite_entry_ledger.py` 的 suite-internal 判据**单独**裁）。
- 🔴 **不得挂死：有界等待 + 祖先已持锁 ⇒ 立即拒绝**（2026-10-02，issue #6074）。上面那条
  `export MIGAO_HEAVY_LOCK_HELD=1` 是**豁免**；它依赖**上游接线**，而「缺接线」的后果
  **不应当是挂死**。实测形态（2026-10-02 23:00 +08，集成分支 worktree）：祖先（`verify-all.sh`）
  已持锁、标记没传下来，而 `scripts/batch-gate.sh` 默认注入的 `MIGAO_HEAVY_WAIT=2700` 被**继承**
  ⇒ 子进程 pytest 去抢**祖先手里的同一把锁** ⇒ **挂死 26 分钟 / 0% CPU / 全程握着机器级锁**，
  只能 `kill -9`。⇒ 两条出口（都在 `tests/unit_ci_workflows/conftest.py`）：
  ① **锁持有者是本进程祖先**（`_lock_holder_is_an_ancestor` 读锁文件的 `pid=` + `ps` 祖先链）
  ⇒ **不排队，立即 fail-closed 拒绝**（那条路**注定**等不到：持有者要等本进程结束才释放）；
  ② **墙钟预算** `_suite_lock_timeout_seconds`（= `MIGAO_HEAVY_WAIT` + 60s；未设置时 60s）
  ⇒ 锁脚本自己卡住也走得出去。两条都复用**同一份**拒绝报文（锁路径 / 持有者 / 怎么办）。
  **持有者不是祖先的排队语义一字未改**（`--wait` 仍等到释放后取得，有判据对照）。
  判据 = `test_suite_self_lock.py::TestNeverHangsWhenAnAncestorHoldsTheLock`（**硬超时**的真子进程 +
  真整目录 pytest 调用；挂死 ⇒ `TimeoutExpired` ⇒ 判红）+ `test_machine_heavy_lock.py` 的
  `TestVerifyAllWiring::test_macquire_exports_the_marker_after_a_successful_acquire` /
  `::test_the_marker_really_reaches_a_child_process`（接线**真的**落到子进程环境里）。
  接线声明登记在 `tests/unit_ci_workflows/wiring_claims_ledger.json`（锚 = `verify-all.sh::macquire`
  —— 该表自本次起允许 `.sh` 载体）。

## 批次统一验证：本机全量「每批一次」（2026-10-02 固化，issue #6012）

**病（现场实测，不是推断）**：2026-10-02 17:24–17:29 CST —— 1 个 `gate` 持锁（进程寿命 49 分钟，
其中约 **33 分钟在等锁**）、**7 个 gate 在跑**（6 个排队：40 / 31 / 20 / 12 / 7 / 2 分钟）、
最高 `已等 2354s / 上限 2400s`（**到点即失败重来**）、`load average` **21.6 / 43.6 / 61.3**（8 核）；
绕开锁的重活 3 个（整目录 `pytest tests/unit_ci_workflows`×2 + `--collect-only`）。
同日 GitHub CI 的 `PR Check` 只要 **3/4/6/9 分钟**且**每 PR 并行**。
⇒ 类级病 = **「每个包各自跑一遍全量」×「8 核只装得下一份全量」**：上一节的锁治的是 **CPU 争用**，
治不了**份数**（而 `gate` 里最重的 `ci workflow helper` 腿的触发面 = `.github/**` 或 `tests/unit_ci_workflows/**`，
每个补类级判据的包都必然命中 ⇒ N 份全量是**结构性**的）。

**修法**：`scripts/batch-gate.sh`（一条命令 = 整批只跑一次）

```bash
./scripts/batch-gate.sh <branch1> <branch2> [...]    # merge 串行 → 一次 gate → 逐包面级归因（0/1/3）
./scripts/batch-gate.sh --in <worktree> <branch> ... # 在既有集成 worktree 里跑那一次
```

- 包内（开发阶段）**只跑定点判据**（子集运行 ⇒ 不拿锁、可与其它包并行）；**不跑** `gate` / `quick`
  —— 两者都是全量档、都要拿机器级锁，逐包跑 = 墙钟 ×N。
- **归因是面级映射**（这个包碰没碰失败腿的触发面），面内多于一个包时**不**指认唯一真凶；
  整合冲突 / 读不到分支 ⇒ **不跑**且非零（「没跑」必须长得像「没跑」）。
- 判据 = `tests/unit_ci_workflows/test_batch_gate.py`（N 个包 ⇒ 那次全量**恰好被调用 1 次**；
  调用数**不随 N 增长**；红 ⇒ 面级归因；冲突/读不到分支 ⇒ 不跑 + 非零）。
- 并发仍守 `migao-dev-flow` §17.2 的 **≤3**；CI 仍是权威（本入口是**起飞前**的整合层守护）。
- 🔻 **盖不到的**：有人**绕过脚本**直接 `pytest tests/unit_ci_workflows`（那一路没有锁）；
  靠研发模式纪律（活锚 `~/.dsh/.agent-presets/migao` → 预设仓
  `zhaokai-mgzn/migao-agent-presets` 的只读镜像）+ 本节的唯一入口保证。

**判据**：`tests/unit_ci_workflows/test_machine_heavy_lock.py`（三态语义 / 孤儿回收 / **不误杀** /
`verify-all.sh` 接线与顺序 / 静态契约）+ `tests/unit_ci_workflows/test_heavy_suite_entry_ledger.py`
（**类级元守卫**：会拉起全量套件的入口必须已登记且接了锁，**未登记即红**；台账 =
`tests/unit_ci_workflows/heavy_entry_ledger.json`；`surface=suite-internal` 那一条由
`TestSuiteInternalEntries` 单独裁）+ `tests/unit_ci_workflows/test_suite_self_lock.py`
（**直连整目录**自己拿锁：接线真跑 / 拦在收集之前 / 纯函数触发面与三类豁免 / fail-closed / 释放面）。

## 子包 worktree **不许**直跑全量（2026-10-03 固化，issue #6084）

上一节把「一批只跑一次全量」做成了**入口**（`scripts/batch-gate.sh`），但**纪律不是机制**：
两条实测事实说明误跑的入口仍然敞开 ——
① 在**集成 worktree** 里跑全量 gate 曾**挂死 26 分钟并握着机器级重活锁**（缺陷已修：`#6076` /
PR `#6077` = `cbd0b9173`，套件自带准入现在「祖先持锁 ⇒ 立即拒绝 + 有界等待」）——
**修好不等于不会再被误跑**；
② 在**子包 worktree** 里跑全量 = 把「批次那一次」**提前烧掉**（D 口径的全部意义就是**一批一次**），
还会跟别人的重活抢同一把机器锁。

**修法**：`verify-all.sh` 在任何重活派发**之前**按**现取的事实**判角色（**不依赖 agent 自报**）：

| 角色 | 判定依据（现取） | 处置 | 会不会持锁 + 跑整目录 |
|---|---|---|---|
| 主检出 | `git rev-parse --absolute-git-dir` == `--git-common-dir` | **允许** | 会（人工 / 批次的**一次性**全量在这里跑） |
| 批次集成 worktree | 上述不等，**且** `git rev-parse --git-path` 处有标记 | **允许** | 会（`batch-gate.sh` 留的标记） |
| 子包 worktree | 上述不等，**且**没有标记 | **拒绝**（`exit 5`） | **不会** —— 拒绝先于 `macquire` 与档位分发 |
| **非 git 仓库 / `git` 不可用** | 上面两种都取不到（`git rev-parse` 失败 / 输出为空） | **拒绝**（`exit 5`，fail-closed） | **不会** —— 拿不准就不许跑全量 |
| CI（`CI` 为真） | 环境标记 | **不受影响** | 会（托管 runner 不占本机资源） |

- **两种「拒绝」的归因是分开的**（2026-10-03 收口，issue #6101 复核发现）：`package`（子包 worktree）
  与 `unknown`（非 git 仓库 / `git` 不可用）**各有自己的「为什么」与**台账 `why` —— 台
  账正是角色读数的仪表，两者共用一套措辞会把「有人在工作树外跑全量」误报成「子包直跑」
  （判据 = `test_package_heavy_entry_ban.py::TestRefusalAttributionIsSplit`，含注入式红证）。
- **`--allow-package-heavy` 对两种角色都放行**（`package` 与 `unknown` 同权）：逃生口是「命令行
  可见的显式动作」，不该因为「为什么判不出角色」而少一个出口（判据同上：`test_allow_flag_also_allows_unknown`）。
  ⚠️ 放行**不等于** `rc=0`：非 git 目录里放行之后脚本继续往下走，随即收在既有的「无变更 ⇒ `exit 3`」。
- **标记是文件，不是名字前缀 / 环境变量**：名字前缀会漂（`batch-gate.sh --in <任意路径>` 形态
  建出来的集成工作区**不叫** `batch-*`）；环境变量**可被子包自己 export** ⇒ 等于把「我是谁」交给
  被判对象自报。标记路径由 `git rev-parse --git-path` 现取（= `.git/worktrees/<name>/…`）：
  **不在工作树里** ⇒ 不进 `git status`、不会被 `git add -A` 提交，`git worktree remove` 时随之消失。
- **逃生口只在命令行上可见**：`--allow-package-heavy`（放行时打印醒目一行）。有意**不做**环境变量
  逃生口 —— 本仓刚按 `#6056` 删掉一个不可见的（`MIGAO_BATCH_GATE_SKIP_READY`，YAGNI + 不可见）。
- **退出码**：`5` = **角色守卫拒绝**。⚠️ 与既有 `3`（无变更）/ `4`（有变更但零项真跑）**不复用**：
  3/4 说的是「变更集」的读数，而 5 说的是「**调用角色**」被拒 —— **此时变更集根本没算**，
  用 3/4 会把它读成「你没改东西」/「跑了但零项真跑」（都是**错误归因**，会把人引去查 diff）。
- **台账（只追加，`.jsonl`）**：`tests/unit_ci_workflows/package_heavy_entry_ledger.jsonl`
  —— 每次**拒绝 / 显式放行**各记一条，**幂等**（键 = `MIGAO_ROLE_LEDGER_ID`：同一进程树只记一笔）。
  现取计数（**拒绝 / 放行分开报**）：

  ```bash
  ./scripts/package-heavy-entry-ledger.sh count     # refused=<n> / override=<n>
  ```

  为什么要分两类：本台账正是 `Dev-Mode-Balance.md` §10 那条「批次粒度」优化的**重启条件**
  （≥5 次批次记录）要用的读数 —— 把「被拦下的浪费」与「人类明知故犯的放行」混成一个数，两者都读不出来。
- 🔻 **盖不到的**（照实登记）：判据**不保证**有人不用 `verify-all.sh` 而直连
  `pytest tests/unit_ci_workflows` —— 那一路由 `conftest.py` 的**套件自带准入**承担
  （上一节，判据 `test_suite_self_lock.py`）；`git` 不可用 / 工作树外 ⇒ 判 `unknown` ⇒ **拒绝**
  （fail-closed；行为面判据见下面「夹具复用」小节）。

**判据**：`tests/unit_ci_workflows/test_package_heavy_entry_ban.py`（四态处置 / 拒绝**先于任何重活**
（`PATH` 审计桩证明没有起过测试进程）/ 摘掉标记 ⇒ 拒绝 / 逃生口只在命令行 / 台账幂等与分类计数 /
**四条注入式红证** / `batch-gate.sh` 真接线留下标记 / **非 git 目录与 `git` 不可用的端到端
fail-closed**（含其注入式红证）/ **真锁与真台账未被碰**）。

### 夹具复用：写同类判据请 import 这个 harness（2026-10-03，issue #6085 的后续）

判据要跑**真脚本**（`verify-all.sh` / `batch-gate.sh` / `machine-heavy-lock.sh` /
`package-heavy-entry-ledger.sh`）时，**不要各自手搓沙箱** —— 用共享 harness：

```python
from unit_ci_workflows import heavy_entry_sandbox as hs

sb = hs.build(tmp_path / "repo")                 # 自足临时仓（git init + 包分支 + 本地 origin/main）
wt = hs.build_worktree(sb, "pkg")                # linked worktree（= 「子包 worktree」形态）
v = hs.run_verify(sb, wt, tmp_path, script=hs.install_real_script(wt))   # 真脚本 + PATH 审计桩
```

- **仓根那份 `verify-all.sh` 必须是桩（`exit 0`）** —— 它只被**真 `batch-gate.sh`** 当「那一次
  gate」调用；放真脚本会让每次 `batch-gate.sh` 都真跑一次全量 gate ⇒ **互等机器级锁 ⇒ 180s
  超时**（`#6085` 首轮 CI 实测；修后同一条腿 **0:35**）。要判真脚本就用
  `hs.install_real_script(root)` 把它放进**被测的那个工作树**（真脚本的 `ROOT` 由自己所在位置算出）。
- 判据**一律**把 `MIGAO_HEAVY_LOCK_FILE` / `MIGAO_PACKAGE_HEAVY_LEDGER` 指到 `tmp_path` ——
  `hs.clean_env` 把这件事做成**结构保证**（默认落 `tmp_path`；显式路径先过
  `hs.unscoped_tmp_root`，落在 `$HOME` 下当场失败），不再靠人记得。
- 血泪教训（桩仓根 / 审计桩转发方式 / `origin/main` 必需 / 读数不许用「锁文件还在」…）逐条写在
  `tests/unit_ci_workflows/heavy_entry_sandbox.py` 的模块 docstring 里，**改夹具前先读它**。

## 重活锁的**准入/溢出**台账（2026-10-03 固化，issue #6091；蓝图 P2 的「测量那一半」）

**治的形态（蓝图 `Dev-Mode-Balance.md` §4 行 4/5 + §10 的 P2 行）**：D 口径下本机是「并发 = 1 的
重活单槽」，重活要么拿到锁、要么**安静排队**（实测排队 45 分钟的先例），而**没有任何台账**回答
「到底溢出多少次、每次都等多久、是谁在抢」。⇒ 分档容量（P2 的另一半）与批次粒度都只能凭感觉。
本包**只做测量/留痕**：把事实记下来，并把「槽满」变成**出声**。

> 🔻 **本包不做分档准入**（heavy/service/jvm/tooling/ops），也不改任何容量/并发决策 ——
> 那是需求方拿着这份读数才谈得上的下一件事。

**台账（只追加 JSONL，默认落在本机、与锁文件同域）**：

```bash
# 路径：${MIGAO_HEAVY_LEDGER:-$HOME/.migao-heavy-lock-ledger.jsonl}
./scripts/machine-heavy-lock.sh stats                    # 全量读数
./scripts/machine-heavy-lock.sh stats --since 24h        # 相对窗口（24h / 90m / 7d）
./scripts/machine-heavy-lock.sh stats --since 2026-10-03T00:00:00+08:00
./scripts/machine-heavy-lock.sh stats --since 1          # unix epoch 秒
./scripts/machine-heavy-lock.sh stats --since 7d --json  # 机器可读（离线，零第三方）
```

⛔ **它不进仓库**：JSONL 放仓里会触发 `drift_audit` 的 ext-census 漂移（⑨ 包的先例）⇒ 本台账
有意放在 `$HOME`（**不在任何 worktree 内**，`dev-worktree.sh rm/prune` 也碰不到它）。
**台账不会出现在 `git status` 里** —— 这是设计，不是巧合。
它**不依赖网络 / `gh`**：`stats` 只读本地文件（`python3` 标准库解析）。

**六类 `kind` 的语义（判据逐条钉住，见下「判据」）**：

| kind | 语义 | 关键读数 |
|---|---|---|
| `acquired_nowait` | 立即拿到（本次调用**一次都没等**） | `wait_seconds == 0` |
| `acquired_after_wait` | **排队等待后**拿到 | `wait_seconds > 0` |
| `refused_busy` | **溢出 / 准入被拒**：默认语义下第一次尝试就被活的持有者挡回 | 溢出计数的一半 |
| `acquire_timeout` | 溢出（等待档）：`--wait <n>` 等满上限仍被挡回 | 溢出计数另一半 + 「白等了多久」 |
| `stale_reaped` | 陈旧锁回收（原持有者 PID 已死） | 回收频率 |
| `released` | 释放 | 「持有者 / 抢占者」榜 |

> `unknown` 是**读出口径**给「形态不认识的行」（旧格式 / 别处手写的 fixture）留的桶 ——
> **不猜**：它不参与溢出计数。

**字段（记录契约）**：`ts`（**带时区偏移**，如 `2026-10-03T06:56:26+0800`）· `kind` · `req`
（请求者名字，来自既有 `acquire <名字>` 参数，如 `verify-all.sh gate`）· `wait_seconds` ·
`worktree` · `branch` · `surface`（`single` / `batch-integration`）· `holder` · `holder_pid` ·
`owner_pid`。首行是 schema 头（`_kind` = `migao.heavy-lock-ledger`），读出口径按它认对象。

**批次面（「批次粒度」重启条件 = 批次记录 ≥5 次）**：`scripts/batch-gate.sh` 发起的那一次全量
**不需要改 batch-gate 一行**就能被数出来 —— 它跑的 worktree 里有 `#6084` 留的批次标记
`migao-package-heavy-entry-allow`（位置由 `git rev-parse --git-path` 现取 ⇒ **不在工作树里**、
不进 `git status`）⇒ 本脚本记 `surface=batch-integration`，`stats` 单独报 `batch_integration=`。

**「槽满 ⇒ 出声」的处置（拒绝报文里的三条可行动出口）**：
① 为什么（锁被谁占着 + PID + 已跑多久 + worktree/cwd）；② **改走 CI**（推一次即可 —— GitHub 上
每个 PR 并行跑同一套 required 检查，它是**权威**，且不占本机这颗单槽）；③ 在 PR body 写
「**本机未跑（机器级重活锁被谁占着）+ 理由 + CI 覆盖清单**」。
**不许静默排队**：`wait=0` 的既有默认语义一字未改，只有显式 `--wait` / `MIGAO_HEAVY_WAIT` 才排队。

**旁路（绝不动锁语义）**：① **写台账时绝不持锁** —— 全部写点在 `_acquire_once` **之外**（判定已定、
锁要么还没写、要么已删）；② **写失败只打 `::warning::`**，`acquire`/`release` 的判定与退出码
**一字不变**；③ 一次 `printf >>`（O_APPEND 短行原子），**不 fork `python3`**。
实测开销（80 组 acquire+release 均值）：`origin/main` 基线 `252.9ms` → 带台账 `293.3ms`
（**+40ms / 组**）；`status` 100 次 `mean=201ms`（与基线同量级）。

### 一次真实的 `stats` 读数（可复算）

```text
$ ./scripts/machine-heavy-lock.sh stats --since 24h
── 机器级重活锁 准入/溢出台账（只读；口径见 docs/wiki/Development.md）──
台账文件    : /Users/<you>/.migao-heavy-lock-ledger.jsonl
时区        : UTC+0800（本机）—— 台账 `ts` 带该偏移；`--since` 不带时区时按它解释
时间窗      : --since 24h
记录条数    : 4（时间窗内）
按 kind     :
  acquired_nowait      1
  refused_busy         1
  acquire_timeout      1
  released             1
溢出（准入被拒）次数 : 2 / 4 次 acquire 尝试（50.0%）   ← **本台账的核心读数**（refused_busy=1 + acquire_timeout=1）
  处置口径  : 溢出 ⇒ **改走 CI**（推一次即可，CI 是权威）＋ 在 PR body 写「本机未跑 + 理由 + CI 覆盖清单」。不许静默排队。
wait_seconds: n=4 p50=0 p95=3 max=3
top 请求者  : verify-all.sh gate×3, pytest unit_ci_workflows（直连整目录）×1
top 持有者  : verify-all.sh gate×4
批次记录    : 0 条（surface=batch-integration）—— 「批次粒度」重启条件的读数之一
```

**三条硬口径（都判据化）**：① **读不到台账 ⇒ 明说「暂无记录」**，**不是** 0 分的假绿
（「0 是读数，没有读数不是 0」）；② **半行 / 非法 JSON / 非对象 ⇒ 具名跳过几条**（出声不崩）；
③ `--since` 只认 `24h` / `90m` / `7d` / ISO8601（带或不带时区 —— 不带按**本机**时区）/ epoch 秒，
**不认识就 `exit 2`**（不猜窗口：猜错 = 悄悄换了时间窗而读数看起来一样）。
🔴 **它不是门禁**：读数再差也 `exit 0` —— 本命令是**分母/事实**，不设阈值、不拦任何东西。

**判据**：`tests/unit_ci_workflows/test_machine_heavy_lock_ledger.py`（20 条，每条能单独变红：
六类 kind 的语义 / 批次面 / 固定夹具的计数·分位数·top 榜 / 空账与坏行 / `--since` 三态 /
**写失败不改判定**（注入不可写路径）/ **参数个数契约**（`printf` 实参 ≠ `%s` 个数 ⇒ 格式串重启 ⇒
每条记录后多一行残缺 JSON）/ 写点必须在持锁窗口之外）。
**判据一律把台账指到 `tmp_path`**（`_run_lock` 强制注入 `MIGAO_HEAVY_LEDGER`）——
**绝不写用户的真台账**（⑨ 包踩过「判据污染真台账」的坑）。

**未固化 / 边界（照实登记，§19.1）**：台账**无限增长**（轮转/上限未做；只追加是本机口径的取舍）·
**多机不适用**（路径与语义都是「本机单槽」；多机各记各的，不聚合）· `stats` 的**时区口径 = 本机**
（`--since` 不带时区时按它解释，`--json` 里给 `utc_offset`）· 本判据**不判**「分档准入实现了没有」。

## 测试分层

| 层 | 工具 | 覆盖要求 |
|----|------|---------|
| admin-api 单测 | JUnit 5 + MockMvc + TestContainers | 核心 Service ≥80% |
| ai-agent 单测 | pytest + httpx | 核心 Tool ≥80% |
| admin-web 单测 | Vitest + Testing Library | 关键页面 100% |
| E2E 冒烟 | Playwright (tests/smoke/) | 核心流程 100% |

## 安全

- 密钥走环境变量，不硬编码
- JWT RS256 非对称签名
- 所有业务表有 tenant_id，查询必须过滤（从 JWT 取）
- CORS 仅允许已知域名

## 🎯 AI 验收体系（项目生命线，2026-06-16 凯总明确）

**所有交付（人/AI 员工）必须遵守的铁律**：

### 1. 任何功能/Bug 先开 issue
- 用 `.github/ISSUE_TEMPLATE/feature.md` 或 `bug.md`
- 自动加 `needs-verification` label

### 2. 业务真值用业务语言（凯总 11:54 明确）
- ✅ "含加工待发货 = 状态为待发货 且 含加工项"
- ❌ "SELECT COUNT(*) ..."（技术）

### 3. 自动反推 case 草稿 → 研发 review
- 提交 issue 后 1-5 分钟，自动评论 L2/L3/L4 草稿
- 研发可改/删/补，**草稿不是命令**

### 4. PR 合 main → 双验收自动跑
- 主验收：跑 spec + L2/L3 业务断言
- 复核验收：DB/API 独立断言（**不看 spec**，避免合谋）
- 双一致 + 100% → 自动 close
- 不通过 → 留研发/凯总

### 5. 5 层兜底
1. 置信度评分
2. 双验收一致性
3. 业务真值独立断言
4. 凯总/娜总抽样
5. commit hash 追溯

### 6. 禁止
- ❌ 跳过 issue 直接写代码
- ❌ 业务真值用技术语言
- ❌ 研发拒绝 review 草稿
- ❌ 凯总/娜总人为验收（除非 block/override）
- ❌ 自动写业务 case 终稿

### 参考
- 验证流水线：`.github/workflows/case-draft / redraft / verify-trigger`（case-draft / redraft / verify-trigger）
- 研发流程：TDD → PR → CI Gate → 双验收 → AutoMerge → Close
- 行为用例单一源（case-contract）：`.github/cases/*.yml` — issue 的 CONTRACT_JSON 声明 `cases: ["OR-002"]`；TDD Red 阶段先跑引用的用例确认 FAIL；新增/修改测试文件头部声明 `# case_ids:`（G5 门禁）
- **评测分档纪律与完成定义（#3483）**：分层探测（L0 静态不变式 → L1 契约 → L2 迭代档 → L3 验证档 → L4 结论档）；全量复测只在里程碑/结论档跑；完成判定 = `completion_verdict`（必须处理的失败=0 —— 除 `llm-noise` 外的一切 score<1，含 `unstable` + 关键旅程 KEY_JOURNEYS_* 全过 + **仅 `llm-noise`** 台账放行）。详见技能 `migao-dev-flow` §16 + [acceptance-protocol](../testing/acceptance-protocol.md) §1.6/§1.7
- 详情见 issue #450 v3.1 + [Testing](Testing.md)
