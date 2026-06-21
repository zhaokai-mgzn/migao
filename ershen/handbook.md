# 二郎神 (Erlang Shen) — Quality Loop Engineering v5.0

> AI First 原则：LLM 收益 > 机械操作时用 AI，机械更快更省时用 CI/脚本。
> 2026-06-21（v5.0 — AI First 架构）。
>
> **本文档是二郎神体系的唯一主权威文档**（the single source of truth）。
> 如有冲突，以本手册为准。

## 一、架构原则

```
机械层 (CI + crontab)            LLM 层 (Claude Code + OpenClaw)
─────────────────────────       ─────────────────────────────
确定性操作：标签、模板评论、      理解和判断：DRAFT生成、Review、
git、语法检查、心跳告警           TDD写码、验收判定、模式反思

CI 做闹钟（事件驱动，瞬时）        LLM 做大脑（理解上下文，推理）
bash 做手臂（机械执行）            Agent 做手（写码+验收）
```

**铁律**：LLM 收益 > 机械才用 AI。标签操作、模板评论、git 同步等纯机械操作由 CI/脚本完成。

## 二、角色分工

| 角色 | 实体 | 职责 |
|------|------|------|
| **军师** | OpenClaw gateway | merge 决策、巡检、日报、模式反思(L2/L3)。**不写代码不跑测试** |
| **研发 Agent** | Claude Code (`dev-agent`) | DRAFT 生成、Phase 1 Review、TDD 写码。**不验收自己的代码** |
| **验收 Agent** | Claude Code (`verify-agent`) | **独立验收**（调 API + 查 DB + check_assert 管道），不写代码 |
| **调度工人** | agent-poll.sh / verify-poll.sh | 扫描信号 → 调用 Agent 执行 → 处理结果 |
| **CI** | GitHub Actions | 标签触发、VERIFY_TRIGGER、语法检查、PR CI |

## 三、服务器布局

```
/opt/youke/              ← migao 项目代码 (git 仓库)
/opt/junshi/             ← 军师工作区 (prompts/ metrics/ archive.py)
/opt/junshi/prompts/     ← OpenClaw cron prompt 文件
/opt/qa-results/         ← 验收结果 ({issue_id}/verdict.json)
/var/log/migao-*.log     ← Agent/军师运行日志
/opt/openclaw/           ← OpenClaw gateway 安装目录
```

## 四、定时任务

### OpenClaw 原生 cron（军师调度层）

由 OpenClaw gateway 管理，共 7 个二郎神 cron：

| # | Job Name | Schedule | 职责 |
|---|----------|----------|------|
| 1 | `junshi-automerge` | 每10min | 四条件判断 → squash merge / needs-changes |
| 2 | `junshi-stale-watch` | 每30min | 巡检 stale issue (>3天无进展) |
| 3 | `junshi-hold-escalate` | 9,12,15,18,21 | 积压 >7天 HOLD → 升级人工 |
| 4 | `junshi-daily-report` | 19:00 | 质量日报 (quality_report.py + LLM 写人话) |
| 5 | `junshi-pattern-reflect` | 2:00 | **L2 模式反思**：REJECT/HOLD 聚类 → 自动修模板 |
| 6 | `junshi-meta-reflect` | 周一 10:00 | **L3 元反思**：block率/瓶颈/改进计划 |
| 7 | `junshi-coverage-weekly` | 周一 10:30 | 覆盖率周扫 + 自动建 issue |

> `junshi-casedraft` 已停用（CI + agent-poll 替代，事件驱动比 5 分钟轮询更快）。

### Linux crontab（执行工人层）

```
# 二郎神体系
*/5 * * * * cd /opt/youke && bash scripts/agent-poll.sh >> /var/log/migao-agent.log 2>&1
*/5 * * * * cd /opt/youke && bash scripts/verify-poll.sh >> /var/log/migao-verify.log 2>&1
*/5 * * * * bash /opt/youke/scripts/heartbeat.sh
```

### GitHub Actions（CI 信号层）

| Workflow | 触发 | 职责 |
|----------|------|------|
| `junshi/case-draft` | issue open/labeled (needs-verification) | 无有效DRAFT时打 `needs-draft` 标签 |
| `junshi/redraft` | issue_comment (REVIEW_JSON reject/supplement) | 隐藏旧DRAFT(OUTDATED) + 打 `needs-draft` |
| `junshi/verify-trigger` | PR closed (merged) | 贴 VERIFY_TRIGGER + `ai-verify/pending` + reopen |
| `Bash Syntax Check` | push (scripts/*.sh) | `bash -n` 语法验证 |
| `PR Check` (pr-check.yml) | PR open/sync | QA Growth Gate + 失败时打 `junshi-review/needs-changes` |

## 五、核心脚本

### agent-poll.sh（研发工人，190 行）

三信号优先级扫描 → LLM 执行：

```
信号 0: needs-draft → dev-agent 生成 DRAFT_JSON（初始或 REJECT 重生成）
信号 1: needs-changes PR → dev-agent 读 CI 失败原因 → 修复
信号 2: needs-verification (unassigned, has DRAFT, reject<3)
         ├── skip_template=true → 直接 Phase 2 TDD
         └── 否则 → Phase 1 Review → accept/supplement → Phase 2 TDD
                                     → reject → needs-redraft
```

关键设计：
- **200 行纯 bash**，零正则判断，所有理解交 LLM（dev-agent）
- DRAFT 生成时区分初始/REJECT 重生成，读 REVIEW_JSON 反馈修正
- 熔断：同 issue REJECT ≥3 次 → `block/need-human`
- 已有有效 DRAFT_JSON 时不重复生成（防 CI 重复打标签）

### verify-poll.sh（验收工人，136 行）

```
1. 扫描 ai-verify/pending (open + closed) → VERIFY_TRIGGER 无 VERDICT_JSON
2. 死循环检测：≥3 VERDICT_JSON + 最后 HOLD → escalate block/need-human
3. 确保服务 (JAVA_HOME=21) → verify-agent LLM 验收
4. 兜底：Agent 未贴 VERDICT_JSON → 从日志自动提取
```

关键设计：
- 独立锁文件，与 agent-poll 并行
- 凭据通过环境变量传递，不写入 prompt
- `check_assert.py` 管道确定性校验，LLM 不自己判断 pass/fail

### heartbeat.sh（心跳告警，29 行）

```
检查 agent/verify log 时间戳 >15分钟 → 告警（stdout 输出 = cron 邮件通知）
检查 lock 文件 >30分钟 → 死锁告警
```

### check_assert.py（确定性断言校验）

verify-agent 的唯一校验层。`curl | check_assert --rule` 管道，输出确定性 JSON（all_pass/rules）。LLM 不判断 pass/fail，check_assert 说 fail 就是 fail。

## 六、Agent 清单

| Agent | 文件 | 职责 |
|-------|------|------|
| `dev-agent` | `.claude/agents/dev-agent.md` | DRAFT 生成 + Phase 1 Review + TDD 写码 (CP-1~CP-7) |
| `verify-agent` | `.claude/agents/verify-agent.md` | 独立验收：curl + psql + check_assert 管道 |

> `case-draft` 和 `orchestrator` agent 已删除——DRAFT 生成统一用 dev-agent，调度由 OpenClaw + CI 负责。

## 七、CI 链路

```
Issue 创建 ──→ junshi/case-draft (打 needs-draft)
  → agent-poll 信号0 → dev-agent 生成 DRAFT_JSON
  → agent-poll 信号2 → Phase 1 Review → accept/supplement/reject
      ├── reject → needs-redraft → junshi/redraft (隐藏旧DRAFT + needs-draft)
      │            → agent-poll 信号0 (读REJECT反馈→重新生成)
      │            → agent-poll 信号2 → 重新 review
      │            → 3次 reject → block/need-human 熔断
      └── accept/supplement → Phase 2 TDD → PR (Closes #xxx)
          → PR Check CI → 失败时 needs-changes → agent-poll 信号1 修复
          → OpenClaw automerge → squash merge
          → junshi/verify-trigger → VERIFY_TRIGGER + ai-verify/pending
          → verify-poll → verify-agent 验收 → VERDICT_JSON → close/hold/block
```

## 八、验证模板体系

`docs/verification-templates/` 目录下 14 个 YAML 模板 + 1 个 `frontend-fix` (skip_template=true)。

模板核心字段:
- `reviewer_asserts`: API 端点 + expect 规则
- `primary_specs`: E2E spec 路径（L3 使用）
- `common_pitfalls`: 常见错误（L2 使用）
- `skip_template: true`: 跳过模板校验，直接进 Phase 2（纯前端改动）

> 模板匹配和 draft 生成全部由 dev-agent (LLM) 完成，不再用 case_draft.py 关键词硬编码。

## 九、三层进化反射体系

| 层级 | 频率 | 执行者 | 职责 |
|------|------|--------|------|
| **L1 即时** | 每5分钟 | agent-poll | REJECT→读反馈重生成, HOLD×3→熔断 |
| **L2 模式** | 每天 2:00 | OpenClaw pattern-reflect | REJECT/HOLD 聚类分析, 同模板≥3次→自动修 YAML |
| **L3 元** | 每周一 10:00 | OpenClaw meta-reflect | block率趋势/瓶颈/改进计划, quality_report --days 7 |

## 十、完整闭环（v5.0）

```
Issue 创建 (CONTRACT_JSON + business_truths)
  → CI needs-draft 标签
  → agent-poll 信号0 → dev-agent LLM 生成 DRAFT_JSON
  → agent-poll 信号2 → Phase 1 Review (REVIEW_JSON)
      ├── reject → CI redraft → 信号0 (读反馈重新生成) → 重新 review
      └── accept/supplement → Phase 2 TDD → PR (Closes #xxx)
  → CI: 单测 + QA Growth Gate (失败→needs-changes→agent修复)
  → OpenClaw auto-merge (CI绿+issue关联+E2E齐→merge)
  → CI verify-trigger → VERIFY_TRIGGER + ai-verify/pending
  → verify-poll → verify-agent LLM 验收 (curl|check_assert → VERDICT_JSON → close/hold/block)
  → L2 模式反思 (每天) → 自动修模板
  → L3 元反思 (每周) → 改进计划
```

## 十一、关键修复记录

### v5.0 (2026-06-21) — AI First 重构

| 修复 | 重要性 |
|------|--------|
| agent-poll.sh: bash fi 语法错误修复（阻塞 2 天） | 🔴 |
| agent-poll.sh: REVIEW_JSON 误匹配 DRAFT 说明文字 → 精确匹配 `<!-- REVIEW_JSON` | 🔴 |
| agent-poll.sh: 重写为 LLM 驱动（260→190 行，零正则） | 🔴 |
| verify-poll.sh: LLM 驱动 + lsof 安装 + JAVA_HOME + 死循环检测 | 🔴 |
| case_draft.py: 删除（540 行模板引擎 → dev-agent LLM 替代） | 🔴 |
| CI: case-draft/redraft/verify-trigger 三件套 + bash 语法检查 | 🔴 |
| CI: pr-check 失败自动 needs-changes 标签 | 🔴 |
| heartbeat.sh: cron 心跳 + 锁超时检测 | 🟠 |
| 模板: frontend-fix (skip_template) + product-sku-stock 扩充至 22 asserts | 🟠 |
| OpenClaw: casedraft 停用 + hold-escalate 去重 + automerge EXPECTED fix | 🟠 |
| OpenClaw: L2 pattern-reflect + L3 meta-reflect 新增 | 🟠 |
| 日志: logrotate 配置 (daily, 30 天, 100M) | 🟡 |
| security: Python -c 注入消除 + ISSUE_ID 数字校验 | 🟡 |

### v3.0 (2026-06-19) — LLM 验收

| 修复 | 重要性 |
|------|--------|
| primary/reviewer/merge 删除，LLM 替代 | 🔴 |
| verify-agent 独立验收，恢复双独立证据 | 🔴 |
| OpenClaw 原生 cron 替代外部 crontab | 🔴 |
| CLAUDE.md + 全部文档: 端口 8080→8081 | 🟡 |
