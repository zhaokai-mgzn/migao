# 修复批次计划（冻结清单）—— dispatch-routing-sweep 发现的 8 条

> 冻结时间：**2026-10-03 07:33 +08**（Asia/Shanghai）
> 依据：仓库 `AGENTS.md` 铁律 6（并行修复：冻结清单 → 按文件所有权分包 → 每包 issue+分支+worktree+后台 subagent → 主会话只做集成与验证）+ 铁律 8（类级固化）+ 铁律 12。
> 上游证据：本目录 `REPORT.md`（93 pass / 6 fail / 99 条断言）+ `out/*.json` + `out/screenshots/*.png`。
> 基线：`origin/main = d4babbf17`；被测后端构建点 `402be478b`；租户 20。

## 一、冻结清单与分流

| # | 发现 | 级别 | 分流 | 出口 |
|---|---|---|---|---|
| F8 | 保存工序设置静默改写计件单价（未定价→0 元 / 改价被回退） | P1·涉钱 | **本批包 P1** | issue **#6102** |
| F1 | 「停用工序」按钮 100% 失效（跨端词表分裂） | P1·用户可见 | **本批包 P2** | issue **#6103** |
| F3 | 缺口清单 20/22 误报 + 有害建议 + `裁剪-纱` 漏报 | P2·可读面 | **本批包 P3** | issue **#6104** |
| F4 | 默认配置下纱帘单 + 9 个选项之一 ⇒ 整单生成失败 | P2 | **待裁定 → 串行面**（修复点在 `db/init/schema.sql` 的逐租户种子块，该文件被 §17.2 列为「并行包不要碰的面」；且存量租户需数据迁移） | 见 §四 |
| F2 | 自建工序应做数量恒为 1（单位是米也一样） | P2·涉钱 | **待人类裁定口径**（「引擎目录外的工序该按什么计量」是业务口径，不是纯缺陷） | 见 §四 |
| F7 | 路线「适用帘种」写面无闭词表校验（规则部位维有） | P3 | 候补包（与 P1 同模块但不同文件：`ProductionRoutingCommandService.java`） | 见 §四 |
| F5 | 工序库改价不影响派工取价（两账分叉） | P3·观察 | 登记（UI 已走正确入口；仅对外契约写面存在分叉） | 见 §四 |
| F6 | `裁剪-纱` 默认配置下不可达且无登记 | P3·登记 | 并入 F3 的「可达性」出口 | #6104 |

> **fail 条数 ≠ 缺陷数**：本轮 6 条 fail 对应 4 个问题（F8 两条 = 同一机制双向；F1 两条 = 接口层 + UI 层双证）。

## 二、批次 1 明细（3 包，并发 = 3 ≤ §17.2 上限）

| 包 | issue | 分支 | 工作区 | 改动面（文件所有权） | 判据（红证口径） |
|---|---|---|---|---|---|
| **P1** | #6102 | `fix/6102-op-save-price-drift` | `migao-wt/6102-op-save-price-drift` | `backend/admin-api/.../ProductionOperationCommandService.java` + 其测试类；**独占 `.github/cases/processing.yml`** | Java 单测：`update()`（body 不含 `unit_price`）后 `collapseToLogical` 有效价**逐字不变**；显式带 `unit_price` 才可变；`create()` 兜底行仍带库价（不回归） |
| **P2** | #6103 | `fix/6103-disable-op-status-vocab` | `migao-wt/6103-disable-op-status-vocab` | `frontend/admin-web/.../production/routings/page.tsx`、`frontend/admin-web/src/types/index.ts` + 前端测试；**独占 `.github/cases/ui.yml`** | 断言**实际 payload** 的 `status` ∈ 后端受理词表；**元守卫**：前端取值域 ⇄ 后端 `STATUSES` 不一致即红 |
| **P3** | #6104 | `fix/6104-routing-gaps-rule-aware` | `migao-wt/6104-routing-gaps-rule-aware` | `backend/admin-api/.../ProductionOperationQueryService.java` 的 `routingGaps` + 其测试类；**不改 `.github/cases/**`** | 缺口 = 活跃主线 ∪ 活跃规则都未消费；「挂了路线但不可达」必须可见；note 建议不得有害 |

**工作区基线自证**：三个 worktree 的 HEAD 均为 `d4babbf17`（= 当时 `origin/main`），落后 main 0 个提交。

### 不碰的面（写进每包任务书，防「声明只在被约束对象的文档里」）

`db/init/schema.sql` · `.agent-presets/**` · 主工作区与其它包的工作区 · 别人的在飞面（P1 不碰 `QueryService.collapseToLogical`；P3 不碰 `CommandService`）· 包外的 `.github/cases/*.yml`（P1 独占 `processing.yml`，P2 独占 `ui.yml`，P3 不碰）。

### 包内验证纪律（§2.1 D 口径）

**只跑定点判据**（各自测试类 / 前端测试文件 + 前端包加 `./check-ui-regression.sh`）；**绝不**在包内跑 `verify-all.sh gate/quick/full`（全量档要拿机器级重活锁，N 包各自跑 = 墙钟 ×N）。红证 = 临时摘掉修复 ⇒ 必红 + 恢复 ⇒ 必绿，两组读数逐字写进 PR body。

## 三、集成与收口（主会话）

1. 三包回报后逐包核：`git -C <wt> status --porcelain`（有无未提交残料）、PR 是否 draft、body 是否含 `Closes #NNNN` 与红证段。
2. **合并串行**；用 `./scripts/batch-gate.sh fix/6102-... fix/6103-... fix/6104-...` 跑**本批唯一一次**全量 gate（机器级重活锁由它自己拿）。
3. 每 PR 的 CI 并行兜底且仍是权威；合并后按铁律 9 **在 main 上复算**目标判据（`git show origin/main:<path>` 看内容，不看 commit 可达性）。
4. 合并后把本批读数回填进 `REPORT.md` 的 §九（交叉验证/裁定状态）。

## 四、人类裁定结果（2026-10-03 07:36 +08，用户逐字选择）

| # | 裁定 | 处置 |
|---|---|---|
| **F2** | **保留兜底 1，但「写面告警 + 读面标记」** | **下一批包 P5**（改 `ProductionOperationCommandService`（建工序写面告警）+ `ProductionOperationQueryService`（读面标记）⇒ 与在飞的 P1/P3 **同文件**，必须等它们合并后再开，否则写面冲突） |
| **F4** | **只改种子（新租户生效），不写存量租户迁移** | **下一批包 P4**（改 `backend/admin-api/src/main/resources/db/init/schema.sql` 的逐租户种子块：给「拼N次 / 加花边 / 加铅块 / 接高 / 加logo条 / 加立边 / 扣环 / 防翘扣」补 `position='布帘'`；**明确接受**「存量租户（含 20）仍会卡单」这一缺口并写进 PR body 的「未固化/边界」段） |
| **F7** | 等下一批 | 候补包 P6（`ProductionRoutingCommandService` 的 `positions` 复用 `POSITION_LIMIT_VOCABULARY`） |
| **F5** | 等下一批 | 候补（是否关掉 `PUT /operations {unit_price}` 或加「写后取价必须相等」判据） |

> ⚠️ **裁定的代价已登记（不粉饰）**：F4 选「只改种子」⇒ **租户 20 与其它存量租户不会被修**（仍会因纱帘 + 那 9 个选项整单失败）；这是**有意接受**的缺口，重启条件 = 「存量租户提出该问题」或「一次通用数据迁移窗口」。


## 五、集成日志（主会话，实时追加）

| 时刻(+08) | 动作 | 读数 / 结论 |
|---|---|---|
| 07:44 | P2 交付 | PR #6105（draft）；工作区干净；关键词只剩 `Closes #6103`；**集成侧独立重跑** 元守卫 `6 passed` |
| 07:45 | P2 真库补证 | `disabled`⇒**200** 且库内 `active→disabled`；`inactive`⇒**422**；已还原（`p11-status-vocab.json` 3/3），并回填为 PR 评论 |
| 07:45 | P1 交付 | PR #6106（draft）；**存量断言改判有据**（旧断言逐字钉缺陷行为 0.40）；**集成侧独立重跑** `7+32 = 39/39 BUILD SUCCESS` |
| 07:46 | P3 交付 | PR #6107（draft）；真库 22→**2 未消费 + 1 不可达**；红证 A/B 双向（摘规则面 / 摘可达性各自必红） |
| 07:47 | 批次集成尝试 #1 | `batch-gate` 报 **CHANGELOG 整合冲突**（三包都改了同一文件）⇒ **没有跑**那次全量（没跑 ≠ 通过）。根因 = 集成方派发疏漏（未把 `CHANGELOG.md` 划给唯一写者） |
| 07:49 | 建集成分支 | `batch/6102-6103-6104`（起点 `origin/main@9881df72c`）；三包 merge，CHANGELOG 用 `git merge-file --union` 解 —— **两侧条目都保留、冲突标记 0** |
| 07:50 | 批次集成尝试 #2 | 就绪判定按设计**拒绝**（集成分支没有 PR）⇒ 用文档化逃生口 `--no-require-ready`（**已披露**：跳过的是"该分支有无 PR/CI 绿"的判定） |
| 07:58 | **本批唯一一次全量** | `3 通过 / 1 失败`：唯一红 = `ci workflow helper` 的 `test_machine_heavy_lock.py::TestVerifyAllWiring::test_the_marker_really_reaches_a_child_process` |
| 07:59 | 该红**归因（非本批）** | 单变量对照：无 `MIGAO_HEAVY_LOCK_HELD` ⇒ `1 passed`；置 `=1` ⇒ `1 failed`（与 gate 日志逐字同）。而 `verify-all.sh` 拿锁时 `export MIGAO_HEAVY_LOCK_HELD=1` ⇒ 该测试的红证在**本地全量档的主路径下失效**。本批 diff 对 `test_machine_heavy_lock.py` / `verify-all.sh` / `machine-heavy-lock.sh` **为空**（内容级自证） |
| 08:00 | 存量债开单 + 派包 | issue **#6112**；包 P4 = `fix/6112-lock-wiring-test-isolation`（修**测试侧隔离**，禁改 `verify-all.sh` 的 export 与锁语义） |
| 08:00 | **P2 的 CI 真红** | `admin-web typecheck + unit tests` 红：`tests/unit/components/OperationsScopeColumn.test.tsx::#4960-③` **5s 超时**（不是断言失败）⇒ 先判 flake vs 回归，已 `gh run rerun --failed` 观察中 |
| 08:01 | **P1 已合并** | PR #6106 → squash `1d1fe5e55`；**铁律 9 内容级自证**：`git show origin/main:…ProductionOperationCommandService.java` 里 `priceSourceRows` 出现 **5 处** |
| 08:02 | P3 同步新 main | merge `origin/main`（CHANGELOG union 解，冲突标记 0）→ 推送 `b47992681`；等其 CI |

### 待办（按序）

1. P2 的 flake 判定：rerun 绿 ⇒ 归为 flake（按仓库 flaky 台账口径处理）后合并；rerun 红 ⇒ 退回 P2 包修（它拥有该页面与测试）。
2. P3 CI 绿 ⇒ 合并（串行）。
3. P4 交付 ⇒ 集成侧核 + 合并；合并后**重跑一次**批次全量（验证「本地全量档不再因这条存量债红」）。
4. 全部落地后：`origin/main` 内容级复算 + 回填 `REPORT.md` §九 + 关单（`Closes` 自动 / 人工兜底）。

## 六、批次 2 明细（2026-10-03 08:06 +08 派发）

| 包 | issue | 分支 / 工作区 | 改动面 | 判据要点 |
|---|---|---|---|---|
| **F4** | **#6114** | `fix/6114-seed-position-cloth` / `migao-wt/6114-seed-position-cloth` | `db/init/schema.sql` 的**新租户生效种子块** + 测试；独占 `.github/cases/processing-order.yml` | 内容腿（种子规则 `position='布帘'`）+ **行为腿两侧夹住**（纱帘单能派工且不出布帘变体 / 布帘单仍插变体）；**不写存量迁移**（缺口写进边界段） |
| **F7** | **#6115** | `fix/6115-route-positions-vocab` / `migao-wt/6115-route-positions-vocab` | `ProductionRoutingCommandService.java`（路线 `positions` 复用 `POSITION_LIMIT_VOCABULARY`）+ 测试 | 越界 ⇒ 422 且**写库前拦截**；合法值 200；**元守卫**：两处值域同源（造第二份词表即红） |
| **F2** | 待开 | — | `ProductionOperationCommandService`（建工序写面告警）+ `ProductionOperationQueryService`（读面标记） | **等 P3 合并后再开**（同文件写面冲突）；口径 = 保留兜底 1，只治「静默」 |

**本批写面纪律（吸取批次 1 的教训）**：
- 🔴 **`CHANGELOG.md` 由集成方独占**（包一律不碰，只在回报里给建议文本）—— 批次 1 三包都改它，害得 `batch-gate` 报整合冲突、那次全量**没跑成**。
- `.github/cases/processing-order.yml` 由 **F4 独占**；F7 **不碰 cases**（只声明既有用例 id）。
- 集成分支策略照旧：`merge` 串行 + 冲突用 `git merge-file --union`（两侧条目都保留），并做内容级自证。

## 七、批次 1 收口 + 批次 2 进展（2026-10-03 08:28 +08）

### 已合并（每一条都做了 `origin/main` **内容级自证**，不看 commit 可达性）

| PR | squash | 内容级自证（`git show origin/main:<file>`） |
|---|---|---|
| P1 #6106 | `1d1fe5e55` | `priceSourceRows` 出现 5 处 |
| P4 #6113 | `502721ea2` | `MIGAO_HEAVY_LOCK_HELD` 出现 13 处（隔离已落地） |
| P3 #6107 | `8263c33d2` | `unreachable_operations` 出现 2 处 |
| P2 #6105 | `dc10e5d2e` | 页面 `status: 'disabled'` 1 处 + 测试改判 1 处 |
| F7 #6116 | `a4aaa3c24` | `validatePositions` 出现 3 处 |

**P2 的返工链（值得留档）**：它自报「155 passed」但 CI 红 ⇒ 集成侧用「干净 main vs 它的分支」单变量对照定位到 `OperationsScopeColumn.test.tsx:153` 逐字钉旧值（`{status:'inactive'}`）⇒ 退回并要求**以全量套件为交付依据** ⇒ 返工后本地全量 `Test Files 273 passed / Tests 3786 passed | 1 skipped`，红证「注入旧值 ⇒ 两个文件都红」。

### 待办（新的，都是本轮暴露的）

1. 🔴 **F7 合入时没带 CHANGELOG 条目**（用户可见行为变更 ⇒ 铁律 7 要求）；F4/F2 同样没带（按批次纪律由集成方独占）。⇒ **一次性跟随 PR 补 `[Unreleased]` 三条**（#6115 / #6114 / #6117），不向已合并分支追加 commit。
2. **F2 的两条未固化项**（PR #6118 body 已登记）：
   - ① 前端不渲染新键 ⇒ **裁定「写面告警」目前只到 API 层，商家界面仍无提示** ⇒ 需要一个小跟包（frontend 渲染 `qty_rule_hint` / `qty_rule_missing`）。
   - ② 假阴性：自建工序名恰等于逻辑名（如 `韩褶`）被判「目录内」，但派工仍走兜底 1 ⇒ 判定口径与引擎**真实查表键**未完全对齐 ⇒ 需裁定是修对齐还是接受并登记。
3. **批次级重跑**：F4/F2 落地后把全部包并进集成分支，跑**一次**全量 —— 目的具体：证明 P4 的修复**真的消掉了**本地全量档那条存量债红（否则 P4 的效果没被验证到）。
4. F4 已定为 **PG-066** 用例号；其 schema.sql 镜像**不需要动**（三源/冻结判据原样绿，归档迁移逐字节未动）。
