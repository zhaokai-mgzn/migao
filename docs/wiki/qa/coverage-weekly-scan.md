# 覆盖率周扫 — coverage_weekly_scan

> 创建：2026-06-20 | 军师自动化 | 凯总指示阈值 60% / 每周一 10:30

## 目的

每周一全量扫一次 3 个模块的代码覆盖率，识别覆盖率不足的模块 / 文件，自动建 issue 走二郎神体系补全。

## 与旧 qa-cron 的关系

| 项 | 旧 qa-cron（OpenClaw e5eaad71） | 新 junshi-coverage-weekly |
|---|---|---|
| 触发频率 | 每 4h | 每周一 10:30 |
| 全量测试 | ✅ | ✅（`--run-tests` 模式） |
| 缺测扫描 | ✅ | ✅ |
| 覆盖率分析 | ❌ | ✅（新增） |
| 自动建 issue | ✅ | ✅（`--create-issues`） |
| 阈值 | - | **60%**（行覆盖率） |

**演进路径**：
- 原 GitHub Actions `qa-cron.yml` 最早由军师创建（commit a723003，2026-06-15）
- 2026-06-15 凯总指示迁移到 OpenClaw cron，文件已删（commit 5f1f2a3）
- 2026-06-20 凯总指示加覆盖率维度，频次改每周，旧 cron e5eaad71 退役

## 3 个模块覆盖方案

| 模块 | 工具 | 报告位置 |
|---|---|---|
| admin-api | JaCoCo 0.8.12（maven plugin） | `backend/admin-api/target/site/jacoco/jacoco.xml` |
| admin-web | vitest coverage | `frontend/admin-web/coverage/coverage-summary.json` |
| ai-agent-service | coverage.py + json 报告 | `backend/ai-agent-service/coverage.json` |

## 触发方式

**OpenClaw cron**：每周一 10:30
- cron id: `b0526a89-ed8d-4ca7-864f-7b656fbc03bf`
- 命名: `junshi-coverage-weekly`

**首次 dry-run**（2026-06-20 08:50）：凯总指示当天就验一次
- admin-api 50.54% / admin-web 18.58% / ai-agent 59.95%
- 3 顶层 + 30 子 issue 已建（#552-#584）

**首次正式建 issue**（2026-06-20 08:55-08:58）：按"按模块拆"原则
- admin-api: #552 + 9 子 (#553-#561)
- admin-web: #562 + 12 子 (#563-#574)
- ai-agent-service: #575 + 9 子 (#576-#584)

## 输出

- 报告归档：`/opt/qa-results/_archive/qa-growth/YYYY-MM-DD_HHMM_coverage-weekly/`
  - `summary.json` / `scan_results.json` / `issues_created.json` / `summary.md`
- 自动建 issue 标签：`needs-verification` + `coverage-gap` + `qa-growth`
- Issue body 含 **CONTRACT_JSON**（军师反推骨架，研发补全 case 类型）

## 阈值规则

- **行覆盖率 < 60%**：自动建 issue（每模块 1 顶层 + N 子 issue）
- **关键业务文件 < 80%**：在 issue body 标红，提示研发优先
- **0 case 文件**：通过现有缺测扫描识别（每 4h 旧 cron 职责，由 pr-check 补）

## 顶层 tracking 永 close 规则（2026-06-20 09:00 凯总指示）

覆盖率周扫的**顶层 tracking issue 永远不主动 close**：
- 即使模块整体 ≥ 60% 也保留并继续观察
- 累计达 60% 后继续增长：新发现的低覆盖文件会建新子 issue
- 只有"模块完全无低覆盖文件"才真的不建新顶层

**逻辑**：覆盖率是"长期健康指标"，不是"完成就关"的任务。

**已建顶层（2026-06-20 09:00）**：
- #552 admin-api 50.54%（9 个子 issue）
- #562 admin-web 18.58%（12 个子 issue）
- #575 ai-agent-service 59.95%（9 个子 issue）
- #585 verify-trigger #516 typo 跟踪

**禁止**：merge.py / primary.py / reviewer.py 自动 close 上述 issue（即使双验收通过）。

## 边界

✅ 只跑覆盖率分析 + 建 issue + 归档  
❌ 不改业务代码 / 不改测试文件 / 不改 CI 配置  
❌ 不跑 case（CI 流程负责）  
❌ 不主动 close issue（merge.py 负责）

## Issue 拆分规则（2026-06-20 凯总指示）

**大任务按功能拆，不放一个 issue**。

| 场景 | 拆法 |
|---|---|
| 覆盖率周扫 | 1 顶层 tracking + N 个 feature issue（每 feature ≤ 8 文件） |
| 多模块 bug 修复 | 1 顶层 + 每模块 1 issue |
| 跨多个 controller / service | 按业务领域拆（订单 / 客户 / AI 工具 / ...） |

**单 issue 文件上限 8 个**（覆盖率周扫硬规则，其他场景参考）。

## Label 规则（2026-06-20 09:15 凯总确认）

**是否走二郎神**取决于**有没有业务真值**：

| 业务真值 | 走二郎神？ | label | 谁接 |
|---|---|---|---|
| ✅ 有（bug/新功能/合规） | ✅ | `needs-verification` | dev agent 写 case |
| ❌ 无（覆盖率/重构/工具/跟踪） | ❌ | `qa-todo` 或 `process-improvement` | 研发自取 |

**覆盖率周扫所有 issue 都用 `qa-todo` + `coverage-gap`**，**不打 `needs-verification`**。

## 关联

- 二郎神 loop：`docs/wiki/qa/ershen-loop.md`
- QA Growth Gate：`docs/testing/qa-growth-gate.md`
- JaCoCo 集成（admin-api）：PR #376（commit 36d2c3c）
- 全项目覆盖率体系搭建：commit e0b87e3
