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
   - ⚠️ **改了 `.github/cases/**`（或 `.github/case-trust-baseline.json`）的分支，同步 main 必须用 `./scripts/sync-main.sh --rebase`**（issue #4984）：merge 会把「本分支缺少 main 新增的用例销账块（`must_succeed` / `namespaces` / `precondition` 等）」当成**有意删除**、**无冲突**接受 ⇒ **静默回退** main 已缴的 case-trust 债（实测 #4965：5 个文件净删 −27/−25/−20/−3/−2 行），随后门禁判红且**归因指向错误方向**。`sync-main.sh` 的 merge 模式现已**前置拒绝**这种组合 + 合并后**内容级校验**；替代路径就是 `--rebase`。
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
