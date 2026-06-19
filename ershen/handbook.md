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

### OpenClaw 内部 cron（主调度，LLM 原生）

军师的核心调度由 OpenClaw gateway 的 `openclaw cron` 管理，LLM 直接执行（非 bash 脚本）：

```
junshi-verify-trigger   每10min (:02,:12,:22,:32,:42,:52)
junshi-automerge        每10min (:06,:16,:26,:36,:46,:56)
junshi-casedraft        每30min (:00, :30)
主干同步+PR巡检          每30min
junshi-stale-watch      每30min (:03, :33)
junshi-hold-escalate    每3h (9:00, 12:00, 15:00, 18:00, 21:00)
junshi-daily-report     每天 19:00
```

查看/管理：`openclaw cron list|add|edit|delete`

### Linux crontab（bash 过渡方案，仅 fallback）

服务器上 3 条 crontab，在 OpenClaw cron 之外提供 bash 级兜底：

```
*/5 * * * * cd /opt/youke && bash scripts/agent-poll.sh >> /var/log/migao-agent.log 2>&1
*/5 * * * * cd /opt/youke && bash scripts/verify-poll.sh >> /var/log/migao-verify.log 2>&1
*/3 * * * * cd /opt/youke && bash scripts/junshi-poll.sh >> /var/log/migao-junshi.log 2>&1
```

> **注意**：junshi-poll.sh 与 OpenClaw cron (casedraft/automerge/verify-trigger) 功能重叠，作为 fallback 保留。后续 OpenClaw cron 稳定后移除。
> **learn.py 已移除**（2026-06-19）：自进化职责由军师 LLM 直接承担，不再需要独立 cron。

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

### junshi-poll.sh (军师调度，每 3 分钟)

6 项职责，按顺序执行：

1. **扫新 issue → case_draft**: 对 needs-verification 且无 DRAFT_JSON/REVIEW_JSON 的 issue 运行 case_draft.py
2. **quality_gate 拦截 → 下发任务**:
   - 未匹配模板 (NEW_TEMPLATE_NEEDED) → 创建 "新建模板: {slug}" issue
   - 已有模板断言不足 → 创建 "补充模板: {name}" issue
   - 去重：检查是否已有同名 open issue
3. **扫 PR → auto merge**: CI 全部 COMPLETED+SUCCESS + 关联 issue → merge
4. **扫 merged PR → VERIFY_TRIGGER**: 对已 merge 但未验收的 issue 发触发评论
5. **巡检 stale** (>3天 needs-verification 无进展) → 评论催促
6. **巡检 hold** (>7天 hold/auto-fail) → 升级 block/need-human
7. **每天 19:00**: quality_report.py → 追加到持久日报 issue

### dual_verify 脚本

| 脚本 | 谁跑 | 做什么 |
|------|------|--------|
| `case_draft.py` | 军师 (junshi-poll) | 匹配模板 → 反推 L2/L3/L4 草稿 → quality_gate 校验 |
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
