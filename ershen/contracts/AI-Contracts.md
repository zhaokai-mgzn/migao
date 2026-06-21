# AI 协作契约 v5.0 — AI First 架构

> 军师 (OpenClaw) + CI (GitHub Actions) + Agent (Claude Code) 通过 **标签 + 评论 + JSON 机读块** 协作。
> 一个 issue 从创建到 close 全程不换号。
> 本文档派生自 `ershen/handbook.md`（主权威文档），如有冲突以 handbook 为准。

## 生命周期状态机

```
        创建 issue (CONTRACT_JSON + needs-verification)
              │
              ├── CI case-draft → needs-draft 标签
              │
              ├── agent-poll 信号0 → dev-agent LLM 生成 DRAFT_JSON
              │
              ├── agent-poll 信号2 → Phase 1 Review (REVIEW_JSON)
              │         │
              │         ├── accept → Phase 2 TDD → PR
              │         ├── supplement → Phase 2 TDD（自行修正 minor issue）
              │         └── reject → needs-redraft
              │              │      + CI redraft 隐藏旧 DRAFT
              │              │      + needs-draft 标签
              │              │      + agent-poll 信号0 (读REJECT反馈→重新生成)
              │              │
              │              └── ≥3 次 reject → block/need-human 熔断 🛑
              │
              ├── PR → CI (单测 + QA Growth Gate)
              │         │
              │         ├── pass → OpenClaw automerge
              │         └── fail → junshi-review/needs-changes
              │                    + agent-poll 信号1 修复
              │
              ├── PR merge → CI verify-trigger → VERIFY_TRIGGER + ai-verify/pending
              │
              ├── verify-poll → verify-agent LLM 验收
              │         │
              │         ├── pass → close + verified/auto ✅
              │         ├── hold → ai-verify/hold（保留 ai-verify/pending）
              │         │         + ≥3 次 HOLD → block/need-human 熔断
              │         └── block → block/dual-mismatch + needs-verification
              │
              └── L2 模式反思（每天2:00）→ 自动修模板
                  L3 元反思（每周一）→ 改进计划
```

## 标签状态机

| 标签 | 谁打 | 含义 | 下一步 |
|------|------|------|--------|
| `needs-verification` | 创建时 | 待军师出 case / Agent 开发 | agent-poll 抢 |
| `needs-draft` | CI case-draft / CI redraft | 等 agent-poll 生成 DRAFT_JSON | agent-poll 信号0 |
| `needs-redraft` | agent-poll (reject) | 已 reject，等 CI 触发 redraft | CI redraft → needs-draft |
| `ai-verify/pending` | CI verify-trigger | 等 verify-poll 验收 | verify-poll 扫描 |
| `ai-verify/hold` | verify-agent | 验收暂停（服务不可达等） | OpenClaw hold-escalate |
| `verified/auto` | verify-agent | 验收通过已 close | 闭环 |
| `block/dual-mismatch` | verify-agent | 验收不一致 | agent-poll 优先抢 |
| `block/need-human` | agent-poll(熔断) / verify-poll(死循环) | 需人工介入 | 凯总/娜总 |
| `junshi-review/needs-changes` | CI pr-check / OpenClaw automerge | PR 需修复 | agent-poll 信号1 |

## 机读块格式

### CONTRACT_JSON（issue body 末尾，创建时写入）

```html
<!-- CONTRACT_JSON
{
  "business_truths": [
    "条件A → 结果B",
    "用户执行X → 系统返回Y"
  ]
}
-->
```

### DRAFT_JSON（agent-poll 信号0 → dev-agent 生成，贴到 issue 评论）

```html
<!-- DRAFT_JSON
{
  "issue_id": N,
  "template": "name",
  "truths_count": N,
  "auto_asserts": N,
  "skip_template": false,
  "specs": ["path1", "path2"],
  "drafted_at": "ISO8601"
}
-->
```

### REVIEW_JSON（Phase 1 Review → dev-agent 贴到 issue 评论）

```html
<!-- REVIEW_JSON
{"action":"accept|reject|supplement","issue_id":N,"reason":"具体原因"}
-->
```

### VERIFY_TRIGGER（CI verify-trigger 贴到 issue 评论）

```html
<!-- VERIFY_TRIGGER
{"issue_id":N,"pr_number":N,"commit":"sha","pr_author":"user","merged_at":"ISO8601"}
-->
```

### VERDICT_JSON（verify-agent 贴到 issue 评论）

```html
<!-- VERDICT_JSON
{
  "issue_id":N,
  "decision":"close|hold|block",
  "confidence":0.9,
  "passed_truths":9,
  "total_truths":10,
  "verifier":"verify-agent-v5",
  "traces":[...]
}
-->
```

## 信号优先级

agent-poll 按优先级扫描：

| 优先级 | 信号 | 动作 |
|--------|------|------|
| **0** | `needs-draft` 标签 | dev-agent 生成 DRAFT_JSON（初始/REJECT重生成） |
| **1** | `junshi-review/needs-changes` PR | dev-agent 读 CI 失败原因 → 修复 |
| **2** | `needs-verification` (unassigned, has DRAFT, reject<3) | Review → TDD / skip_template 直通 |

verify-poll：

| 优先级 | 信号 | 动作 |
|--------|------|------|
| **0** | ≥3 VERDICT_JSON + 最后 HOLD | escalate → block/need-human |
| **1** | `ai-verify/pending` + VERIFY_TRIGGER 无 VERDICT_JSON | verify-agent 验收 |

## 三层反射

| 层级 | 频率 | 内容 |
|------|------|------|
| **L1 即时** | 每轮 | REJECT→读反馈重生成, HOLD×3→熔断 |
| **L2 模式** | 每天 2:00 | REJECT/HOLD 聚类 → 同模板≥3次→自动修 YAML |
| **L3 元** | 每周一 | block率/瓶颈/改进计划 |

## 铁律

- **一个 issue 走到底**，不创建子 issue
- **所有交互带 JSON 机读块**，不靠自然语言猜
- **军师只做判断，Agent 做执行**——写码/验收不混
- **LLM 收益 > 机械才用 AI**——标签操作等机械操作用 CI
- **3 次 reject 熔断**，block_depth 从 REVIEW_JSON 累计
- **验收独立**：写码的不验，验的不写
