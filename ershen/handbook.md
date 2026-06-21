# 二郎神 (Erlang Shen) — Quality Loop Engineering v3.0

> 米高项目 Quality Loop Engineering 体系。天眼看穿 mock、哮天犬独立嗅探、守门不放行。
> 给军师（OpenClaw）的部署和执行参考。2026-06-19（v3.0 精简版）。
>
> **本文档是二郎神体系的唯一主权威文档**（the single source of truth）。
> 其他文档（`AI-Contracts.md`、`ershen-loop.md`、`CLAUDE.md` QL 段等）均派生自本手册。
> 如有冲突，以本手册为准。更新流程：改本手册 → 同步派生文档。

## 一、角色分工

| 角色 | 实体 | 职责 |
|------|------|------|
| **军师** | OpenClaw gateway | 调度、判断、下发任务、case_draft、巡检、日报。**不写代码不跑测试** |
| **研发 Agent** | Claude Code (`claude --agent dev-agent`) | 写码（TDD）。**不验收自己写的代码** |
| **验收 Agent** | Claude Code (`claude --agent verify-agent`) | **独立验收**（调 API + 查 DB + 判定），不写代码 |
| **CI** | GitHub Actions | 单测 + QA Growth Gate + 部署 |

## 二、服务器布局

```
/opt/youke/              ← migao 项目代码 (git 仓库)
/opt/junshi/             ← 军师工作区 (prompts/metrics/archive.py)
/opt/qa-results/         ← 验收结果 ({issue_id}/verdict.json)
/var/log/migao-*.log     ← Agent/军师运行日志
```

## 三、定时任务

### OpenClaw 原生 cron（主调度）

二郎神核心调度由 OpenClaw gateway 管理。共 11 条 cron job（+4 条非军师个人 cron）。

**军师 7 条：**

| # | Job Name | Schedule | 职责 |
|---|----------|----------|------|
| 1 | `junshi-casedraft` | `*/5 * * * *` (每5min) | 扫 needs-verification issue → DRAFT_JSON |
| 2 | `junshi-automerge` | 每10min | 扫 open PR → 四条件满足则 squash merge |
| 3 | `junshi-stale-watch` | 每30min | 巡检 stale issue (>3天) |
| 4 | `junshi-hold-escalate` | 每3h | 积压升级 P0/P1/P2 |
| 5 | `junshi-daily-report` | `0 19 * * *` | 质量日报 |
| 6 | `主干同步+PR巡检` | `*/30 * * * *` | git pull + PR 红牌识别 |
| 7 | `junshi-coverage-weekly` | `30 10 * * 1` (每周一) | 覆盖率周报 |

查看/管理：`openclaw cron list` · `openclaw cron run <id>` · `openclaw cron runs --id <id>`

### Linux crontab（bash 兜底）

```
*/5 * * * * cd /opt/youke && bash scripts/agent-poll.sh >> /var/log/migao-agent.log 2>&1
*/5 * * * * cd /opt/youke && bash scripts/verify-poll.sh >> /var/log/migao-verify.log 2>&1
```

### GitHub Actions（事件驱动补充）

| # | Workflow | 触发 | 职责 |
|---|----------|------|------|
| 1 | `junshi-case-draft.yml` | issue open/label | 即时响应（不等 cron 轮询） |
| 2 | `junshi-verify-trigger.yml` | PR merged | VERIFY_TRIGGER（纯事件驱动，无需 LLM） |

> 三层不冲突：OpenClaw cron 周期性兜底 + GA 事件即时响应 + crontab Agent 轮询。各自去重（已有 DRAFT_JSON / VERIFY_TRIGGER 则跳过）。


## 四、脚本职责

### agent-poll.sh (Agent 调度，每 5 分钟)

```
1. git reset --hard + git checkout main + git pull (同步代码)
2. 抢 issue 优先级: block/dual-mismatch > qa模板任务 > needs-verification(有DRAFT_JSON)
3. git checkout -b feat/issue-{id}-{desc} (创建分支)
4. start_services → claude --print --agent dev-agent "遵守铁律..." → stop_services
5. 如果没有 coding issue → 跳过（验收已拆分到 verify-poll.sh）
```

关键设计:
- PYTHON 变量指向 venv Python 3.11 (`/opt/youke/backend/ai-agent-service/.venv/bin/python3`)
- 锁文件 `/tmp/migao-agent.lock` 带 30 分钟超时
- cron 环境保护 (HOME + PATH)
- 验收逻辑已拆分到 verify-poll.sh，本脚本不再承担验收职责

### verify-poll.sh (验收调度，每 5 分钟) — v3.0 LLM 验收

```
1. git pull (同步最新脚本)
2. 扫 OPEN + CLOSED(ai-verify/pending) → 找 VERIFY_TRIGGER 无 VERDICT_JSON
3. reopen（如果 CLOSED）→ 确保服务（自动 source .env）
4. claude --agent dev-agent "验收 issue #N..." → LLM 自主调 API + 查 DB + 判定
5. LLM 贴 VERDICT_JSON + close/hold/block
```

关键设计:
- 独立锁文件 `/tmp/migao-verify.lock`
- **不再跑 primary.py/reviewer.py/merge.py**（2026-06-19 起 LLM 替代）
- LLM 自行推理 API path、处理认证、解析响应——不依赖模板
- 凭据通过环境变量传递（SERVICE_TOKEN, PGPASSWORD），不写入 prompt
- 10 分钟内完成

### junshi-poll.sh — 已废弃（2026-06-19）

6 项职责已全部迁移至 OpenClaw 原生 cron（见下方）。bash 脚本已删除，不再在 crontab 中。

### dual_verify 脚本

| 脚本 | 谁跑 | 做什么 | 状态 |
|------|------|--------|------|
| `case_draft.py` | OpenClaw cron + GA | 匹配模板 → 反推 L2/L3/L4 草稿 → quality_gate 校验 | 活跃 |
| `primary.py` | — | E2E + pytest/JUnit | ❌ 已删除 |
| `reviewer.py` | — | API 调用 + 模板 expect | ❌ 已删除 |
| `merge.py` | — | 读 primary.json + reviewer.json | ❌ 已删除 |

> **v3.0（2026-06-19）**: primary/reviewer/merge 已删除。verify-poll.sh 触发 `claude --agent verify-agent`，LLM 独立调 API + 查 DB + 判定。
> verify-agent 与 dev-agent 完全独立——写码的不验，验的不写。恢复双独立证据原则。

### learn.py (自进化 → 已由军师 LLM 接管)

2026-06-19 起，自进化职责由军师 OpenClaw LLM 直接承担，不再需要独立 cron 触发 learn.py。

军师 LLM 在空闲周期内自动：
1. 扫 `/opt/qa-results/` 分析近期验收结果
2. 检测模式（漏关键词、模板缺口、mock 欺骗）
3. 创建 issue 或直接更新 `learned_rules.json`
4. 自改进 prompt/规则

`learn.py` 脚本保留在仓库中，作为 LLM 可调用的工具（`python3 junshi/learn.py --stats` 等按需使用）。

## 五、QA Growth Gate (pr-check.yml)

PR 阶段按文件类型检查测试文件是否存在于 diff 中：
- Python tools/graph/agents → 对应 test 文件
- Java controller/service/mapper/security → 对应 Test 类
- 前端 components/pages/lib → 对应 spec/unit test

缺测 → CI fail → block merge。有测 → 放行。

**三条防线**: Gate ("你写测试了吗?") → 军师验收 ("测试写对了吗?") → expect 验证 ("业务真值通过了吗?")

## 六、验证模板体系

8 个模板 (`docs/verification-templates/*.yml`)，核心字段:
- `reviewer_asserts`: API 端点 + expect 规则（verify-agent 使用）
- `primary_specs`: E2E spec 路径（case_draft L3 使用）
- `common_pitfalls`: 常见错误（case_draft L2 使用）

模板生长: quality_gate 拦截 → 军师下发任务 → Agent 补充/新建模板 → PR → 下次覆盖更全。


## 七、完整闭环（v3.0）

```
Issue 创建 (CONTRACT_JSON + business_truths)
  → 军师 case_draft → DRAFT_JSON
  → Agent 抢单 → Review (REVIEW_JSON) → TDD → PR (Closes #xxx)
  → CI: 单测 + QA Growth Gate
  → Gate pass → 军师 auto-merge
  → Deploy → 军师发 VERIFY_TRIGGER
  → Agent LLM 自主验收（调 API + 查 DB → 判定 close/hold/block）
  → 军师 LLM 分析 → 生长 action → 下次更准
```

## 八、关键修复记录

| 修复 | 重要性 |
|------|--------|
| agent-poll.sh: `--custom-instructions` → `--agent dev-agent` (Claude Code 2.1.179) | 🔴 否则 Agent 根本跑不起来 |
| agent-poll.sh: 验收路径从死代码复活 (exit 0 阻塞) | 🔴 |
| agent-poll.sh: cron 环境保护 (HOME + PATH) | 🔴 |
| agent-poll.sh: PYTHON 变量 (venv 3.11, 不用系统 3.6) | 🔴 |
| junshi-poll.sh: CI 全绿判断 (PENDING 不算 all_pass) | 🔴 |
| junshi-poll.sh: merge 失败不报假成功 | 🔴 |
| junshi-poll.sh: gh issue create 不支持 --json (v2.63) | 🟠 |
| junshi-poll.sh: grep -oP 不兼容 Rocky Linux (改用 sed) | 🟠 |
| case_draft.py: _sanitize_truth 重复定义修复 | 🟡 |
| case_draft.py: auto_patch 移除 git commit/PR (军师不写代码) | 🟡 |
| reviewer.py: expect 字段真实验证 (不只是 HTTP 200) | 🔴 |
| CLAUDE.md + 全部文档: 端口 8080→8081 | 🟡 |
| AI-Contracts.md: 删除矛盾段落 (军师跑验收) | 🟡 |
| primary/reviewer/merge 删除，LLM 替代 (v3.0) | 🔴 |
| verify-agent 独立验收，恢复双独立证据 | 🔴 |

## 九、当前已知限制（v3.0）

1. LLM 验收依赖 DB/API 服务可用性 — 服务挂则验收挂（已验证 start_services 自动恢复）
2. RDS 白名单需手动维护 — 新服务器 IP 需加白名单（2026-06-19 已加 121.40.28.213）
3. case_draft 模板匹配 LLM 已可替代关键词硬编码 — 待观察
4. reviewer expect 验证已由 LLM 推理取代 — 不再依赖模板 reviewer_asserts
5. ~~军师用外部 crontab~~ → 已迁移至 OpenClaw 原生 cron
