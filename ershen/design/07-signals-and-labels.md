# 07 — 信号与标签体系

二郎神体系通过 GitHub Labels 和 Issue/PR Comments 完成纯异步解耦通信。

## 标签体系 (18 个)

### 流水线状态标签

| 标签 | 颜色 | 含义 | 设置者 | 清除者 |
|------|------|------|--------|--------|
| `needs-truths` | #FBCA04 | 缺业务真值/CONTRACT_JSON | CI (contract-check) | 用户 |
| `needs-verification` | #FBCA04 | 军师已介入，进入 quality loop | CI (contract-check) | 自动 (验收完成) |
| `needs-draft` | #FBCA04 | 等待生成 DRAFT_JSON | CI (case-draft/redraft) | agent-poll |
| `needs-redraft` | #FBCA04 | REJECT/SUPPLEMENT 后等待重 draft | CI (redraft) | agent-poll |

### 验收状态标签

| 标签 | 颜色 | 含义 | 设置者 | 清除者 |
|------|------|------|--------|--------|
| `ai-verify/pending` | #1D76DB | 等待验收 | CI (verify-trigger) | verify-poll |
| `ai-verify/hold` | — | 验收 hold (置信度 ≥80%) | verify-agent | — |
| `verified/auto` | — | 自动验收通过 | verify-agent | — |

### 阻塞/异常标签

| 标签 | 颜色 | 含义 | 设置者 | 清除者 |
|------|------|------|--------|--------|
| `block/need-human` | — | 死循环/熔断，需人工 | verify-poll / agent-poll | 人工 |
| `block/dual-mismatch` | — | 验收 block | verify-agent | — |
| `junshi-review/needs-changes` | #FBCA04 | CI 失败/缺测试/缺 Fixes | CI (PR Check) | agent-poll |
| `junshi-review/blocked` | #D93F0B | 业务冲突/缺验收/需人类审批 | 军师 | 人工 |
| `junshi-review/pass-with-followups` | #0E8A16 | 通过但有跟进项 | 军师 | — |
| `junshi-error` | #D93F0B | deploy/触发失败 | 军师 | 人工 |

### 质量追踪标签

| 标签 | 颜色 | 含义 | 设置者 |
|------|------|------|--------|
| `qa-growth` | — | QA Growth Gate 覆盖率追踪 parent | 军师 (coverage-track) |
| `qa-todo` | — | 覆盖率补全子任务 | 军师 (coverage-track) |
| `coverage-gap` | — | 覆盖率缺口 | 军师 (coverage-track) |
| `coverage-tracking` | — | 覆盖率追踪 parent issue | 军师 (coverage-track) |

## JSN 信号 (5 种)

所有角色间复杂通信通过 Issue/PR Comment 中的 HTML comment 块 (`<!-- TYPE_JSON ... -->`) 传递。

### CONTRACT_JSON
```json
{"schema_version":"1.0","type":"bug|feature","business_truths":["真值1","真值2"],"parent_issue":N}
```
- **位置**: Issue body
- **设置**: 用户/CI
- **读取**: dev-agent (Phase 1)

### DRAFT_JSON
```json
{"draft_version":"v3","issue_number":N,"business_truths":[...],"auto_asserts_count":N}
```
- **位置**: Issue comment
- **设置**: dev-agent
- **读取**: 用户 (review) / verify-agent (验收)

### REVIEW_JSON
```json
{"action":"accept|reject|supplement","issue_id":N,"reason":"","additions":[]}
```
- **位置**: Issue comment
- **设置**: 用户
- **读取**: dev-agent (Phase 1) / CI (redraft)

### VERIFY_TRIGGER
```json
{"issue_id":N,"pr_number":N,"commit":"sha","pr_author":"login","merged_at":"ISO8601"}
```
- **位置**: Issue comment
- **设置**: CI (verify-trigger.yml)
- **读取**: verify-poll.sh

### VERDICT_JSON
```json
{"issue_id":N,"decision":"close|hold|block","confidence":0.0,"passed_truths":N,"total_truths":N,"traces":[...]}
```
- **位置**: Issue comment
- **设置**: verify-agent
- **读取**: 军师 / 用户

## 信号生命周期示例

```
#671 (PR body typo 修复)
  Issue #585 创建 → CI contract-check → needs-truths
  → 用户补 CONTRACT_JSON → CI → needs-verification
  → CI case-draft → needs-draft
  → agent-poll 扫描 → dev-agent 生成 DRAFT_JSON → comment
  → 用户 review → accept
  → agent-poll 扫描 → dev-agent TDD 写码
    → git push → PR #671
  → CI PR Check 全绿 → 军师 automerge → merge
  → CI verify-trigger → VERIFY_TRIGGER + ai-verify/pending
  → verify-poll 扫描 → verify-agent 验收
    → VERDICT_JSON: close → verified/auto
  → 军师 (next scan) 检测已 close → 无需操作
```

## 巡检过滤规则

执行巡检时必须：
- **排除** `needs-verification` 标签的 issue (军师已介入)
- **排除** body 含 `DRAFT_JSON` / `REVIEW_JSON` / `CONTRACT_JSON` 的 issue
- **关注** `junshi-review/needs-changes` 的 PR
- **关注** CI 失败的 PR
