# 二郎神 (Erlang Shen) — Quality Loop Engineering v2.0

> 米高项目 Quality Loop Engineering 体系。天眼看穿 mock、哮天犬独立嗅探、守门不放行。
> 给军师（OpenClaw）的部署和执行参考。2026-06-19。

## 一、角色分工

| 角色 | 实体 | 职责 |
|------|------|------|
| **军师** | OpenClaw gateway | 调度、判断、下发任务、汇报。**不写代码不跑测试** |
| **Agent** | Claude Code (`--agent dev-agent`) | 写码、TDD、跑验收脚本。遵守 CLAUDE.md 铁律 |
| **CI** | GitHub Actions (pr-check.yml) | QA Growth Gate — 检查测试文件存在性 |

## 二、服务器布局

```
/opt/youke/              ← migao 项目代码 (git 仓库)
/opt/junshi/             ← 军师工作区 (prompts/metrics/archive.py)
/opt/qa-results/         ← 验收结果 ({issue_id}/primary.json, reviewer.json)
/var/log/migao-*.log     ← Agent/军师运行日志
```

## 三、定时任务

### OpenClaw 原生 cron（主调度 — 军师 LLM 直接执行）

二郎神所有调度逻辑由 OpenClaw gateway 的 `openclaw cron` 管理。LLM 直接执行，不依赖 bash 脚本。

**当前 7 条 cron job：**

| # | Job Name | Schedule | 职责 |
|---|----------|----------|------|
| 1 | `junshi-casedraft` | `0,30 * * * *` (每30min) | 扫 needs-verification issue，LLM 反推 case 草稿 DRAFT_JSON |
| 2 | `junshi-automerge` | `6,16,26,36,46,56 * * * *` (每10min) | 扫 open PR，CI/issue/范围/E2E 四条件 → squash merge |
| 3 | `junshi-verify-trigger` | `12,22,32,42,52,02 * * * *` (每10min) | 扫已 merge PR，deploy 完成后发 VERIFY_TRIGGER |
| 4 | `junshi-stale-watch` | `3,33 * * * *` (每30min) | 巡检 needs-verification stale (>3天)，评论催促 |
| 5 | `junshi-hold-escalate` | `0 9,12,15,18,21 * * *` (每3h) | 扫 hold/auto-fail 积压 (>7天)，分级升级 P0/P1/P2 |
| 6 | `junshi-daily-report` | `0 19 * * *` (每天19:00) | 质量日报，追加到日报 issue + 钉钉摘要 |
| 7 | `主干同步+PR巡检` | `*/30 * * * *` (每30min) | git 主干同步 + open PR 红牌识别 + 静默/汇报 |

**迁移服务器时重建步骤：**

```bash
# 前提：OpenClaw gateway 已运行，gh CLI 已认证，/opt/youke 已 clone

# 1. casedraft — 扫新 issue 反推草稿
openclaw cron add \
  --name junshi-casedraft \
  --schedule "0,30 * * * *" --tz Asia/Shanghai \
  --thinking high --timeout-seconds 300 \
  --prompt "你是二郎神体系的军师。扫 needs-verification issue → LLM 反推 case 草稿 (DRAFT_JSON)。

  步骤 0 — 先判断是否 skip_template（以下类型不匹配模板，直接发 DRAFT_JSON）：
  - 模板类：标题含 新建模板/补充模板/模板
  - CI/CD/部署：改 .github/workflows/、terraform/、Dockerfile
  - 纯文档：只改 docs/、README
  - 配置/重构：只改 .env、application.yml，无功能变更

  步骤 1 — 需要模板的正常流程：
  1. gh issue list --label needs-verification --state open --json number,title,body,comments --limit 10
  2. 过滤 comments 里无 DRAFT_JSON 的
  3. 读 /opt/youke/docs/verification-templates/ 匹配模板
  4. 写 3-5 条业务真值（业务语言，不带 SQL/API）
  5. 生成 DRAFT_JSON 评论（<!-- DRAFT_JSON {...} -->）
  6. 未匹配模板 → 创建 '新建模板: {slug}' issue（去重）
  7. 匹配但 asserts 不足 → 创建 '补充模板: {name}' issue（去重）

  边界：不写代码不跑测试。skip_template 的不走 quality_gate。"

# 2. automerge — 扫 PR 自动合并
openclaw cron add \
  --name junshi-automerge \
  --schedule "6,16,26,36,46,56 * * * *" --tz Asia/Shanghai \
  --prompt "你是二郎神体系的军师。扫 open PR → 满足条件则 squash merge。
  条件：① CI 全部 COMPLETED+SUCCESS ② 关联 issue（Fixes/Closes #xxx）
  ③ 非 infra/config 纯变更 ④ E2E 有对应 spec
  gh pr list --state open --json number,title,labels,checks,closingIssuesReferences
  gh pr merge <num> --squash --auto
  边界：不满足条件不 merge。merge 失败 → 加 junshi-error label。"

# 3. verify-trigger — deploy 后发验收触发
openclaw cron add \
  --name junshi-verify-trigger \
  --schedule "12,22,32,42,52,02 * * * *" --tz Asia/Shanghai \
  --prompt "你是二郎神体系的军师。扫已 merge PR → deploy 完成后发 VERIFY_TRIGGER。
  1. gh pr list --state merged --json number,title,closingIssuesReferences,mergedAt --limit 20
  2. 找关联 issue，跳过已有 VERIFY_TRIGGER 的
  3. 检查 deploy workflow (gh run list --workflow=deploy-*.yml)
  4. deploy 成功 → 发 VERIFY_TRIGGER 评论
  边界：只触发不验收。deploy 失败 → 不触发，加 junshi-error label。"

# 4. stale-watch — 巡检停滞 issue
openclaw cron add \
  --name junshi-stale-watch \
  --schedule "3,33 * * * *" --tz Asia/Shanghai \
  --prompt "你是二郎神体系的军师。巡检 needs-verification stale (>3天无进展)。
  gh issue list --label needs-verification --state open --json number,title,updatedAt
  超过3天 → 评论催促。超过7天 → 升级 block/need-human。
  边界：只巡检不写码。"

# 5. hold-escalate — 积压升级
openclaw cron add \
  --name junshi-hold-escalate \
  --schedule "0 9,12,15,18,21 * * *" --tz Asia/Shanghai \
  --prompt "你是二郎神体系的军师。扫 hold/auto-fail 积压 (>7天) → 分级升级。
  P0 (订单/支付) → block + @ 凯总。P1 (商品/客户) → need-human。P2 → 评论提醒。
  边界：只升级不处理。"

# 6. daily-report — 质量日报
openclaw cron add \
  --name junshi-daily-report \
  --schedule "0 19 * * *" --tz Asia/Shanghai \
  --prompt "你是二郎神体系的军师。每天 19:00 生成质量日报。
  1. 统计当日 issue/PR/验收数据
  2. 汇总 primary/reviewer 结果
  3. 追加到日报 issue + 钉钉摘要"

# 7. 主干同步+PR巡检
openclaw cron add \
  --name "主干同步+PR巡检" \
  --schedule "*/30 * * * *" --tz Asia/Shanghai \
  --prompt "你是二郎神体系的军师。每30分钟同步主干 + 巡检 open PR。
  阶段1：git fetch + git status，干净则 pull --ff-only。有冲突则 stash 后 pull 再 stash pop。
  阶段2：gh pr list --state open，红牌识别（关联 #387/#388/#389/#390 的 PR，涉及 controller/service 的 P0 PR）。有动作才汇报。
  边界：不 force push / reset --hard。不审 PR。不发空汇报。"
```

### Linux crontab（bash 兜底）

OpenClaw cron 为主，linux crontab 仅保留 Agent 写码和验收两条：

```
*/5 * * * * cd /opt/youke && bash scripts/agent-poll.sh >> /var/log/migao-agent.log 2>&1
*/5 * * * * cd /opt/youke && bash scripts/verify-poll.sh >> /var/log/migao-verify.log 2>&1
```

> **junshi-poll.sh 已删除**（2026-06-19）：全部 6 项职责已迁移至 OpenClaw cron。
> **learn.py 已移除**（2026-06-19）：自进化由军师 LLM 直接承担。

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

### verify-poll.sh (验收调度，每 5 分钟)

```
1. git pull (同步最新脚本)
2. 扫 OPEN issue + CLOSED(ai-verify/pending) → 找 VERIFY_TRIGGER 无 VERDICT_JSON 的
3. reopen（如果 CLOSED）→ 确保服务 → primary.py → reviewer.py → merge.py
4. 如果没有待验收 issue → 跳过
```

关键设计:
- 独立锁文件 `/tmp/migao-verify.lock`（不与 agent-poll 互斥）
- 纯验收，不抢 issue、不写码、不创建 PR
- 服务按需启停（如果 agent-poll 已启动服务则复用）

### junshi-poll.sh — 已废弃（2026-06-19）

6 项职责已全部迁移至 OpenClaw 原生 cron（见下方）。bash 脚本已删除，不再在 crontab 中。

### dual_verify 脚本

| 脚本 | 谁跑 | 做什么 |
|------|------|--------|
| `case_draft.py` | 军师 (openclaw cron) | 匹配模板 → 反推 L2/L3/L4 草稿 → quality_gate 校验 |
| `primary.py` | Agent (agent-poll) | E2E 全量 + issue spec 中的 pytest/JUnit |
| `reviewer.py` | Agent (agent-poll) | 独立 API 调用 + 模板 expect 字段真实验证 |
| `merge.py` | Agent (agent-poll) | 读 primary.json + reviewer.json → close/hold/block |

### reviewer.py expect 验证 (v2)

不再只看 HTTP 200。解析模板 `expect:` 字段，支持 AND 组合条件 + 6 种验证模式：
- `data > N` / `data >= N` / `<` / `<=` / `==`
- `items 非空` / `data 非空`
- `每项 field = value` / `!=` / `<` / `>`
- `items 中每条 field NOT IN (v1, v2)`

expect 失败 → passed=False，置信度降低。

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
- `reviewer_asserts`: API 端点 + expect 规则（reviewer.py 使用）
- `primary_specs`: E2E spec 路径（case_draft L3 使用）
- `common_pitfalls`: 常见错误（case_draft L2 使用）

模板生长: quality_gate 拦截 → 军师下发任务 → Agent 补充/新建模板 → PR → 下次覆盖更全。


## 七、完整闭环

```
Issue 创建 (CONTRACT_JSON + business_truths)
  → 军师 case_draft → DRAFT_JSON 评论
  → Agent 抢单 → Review (REVIEW_JSON) → TDD → PR (Closes #xxx)
  → CI: 单测 + QA Growth Gate
  → Gate pass → 军师 auto-merge
  → Deploy → 军师发 VERIFY_TRIGGER
  → Agent 验收 (primary + reviewer(with expect) + merge)
  → merge.py 判定: close / hold / block
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

## 九、当前已知限制

1. 军师主调度已用 OpenClaw 原生 cron，bash crontab 仅作 fallback — 后续可去冗余
2. case_draft 模板匹配是关键词硬编码 — OpenClaw LLM 已有 casedraft cron，可逐步接管
3. gate_patterns 是死数据 — pr-check.yml 不读模板
4. 关键词映射在 case_draft.py 和 reviewer.py 中重复维护
5. reviewer expect 验证的 regex 无法处理嵌套 AND/OR 条件
