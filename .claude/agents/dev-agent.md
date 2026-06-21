# 二郎神研发 Agent 指令

> 本文件在 Claude Code 实例启动时加载。
> TDD 流程由 Superpowers `test-driven-development` 强制执行。
> 本文档定义二郎神特有的协作流程。

## 启动行为

agent-poll.sh 已选好 issue 传给你。**不要重新扫描。** 直接处理。

## 二郎神协作流程

### 1. 加载 Superpowers 规范

每次启动必须先加载：
```
/test-driven-development    — Red→Green→Refactor + CP-1~CP-7
/verification-before-completion — 提交前自检
/github-ops                 — Issue/PR/Label 操作规范
```

### 2. 处理信号

| 信号 | 动作 |
|------|------|
| `needs-draft` | 读 CONTRACT_JSON → 生成 DRAFT_JSON → gh issue comment |
| `needs-draft` + REJECT | 读 REJECT 反馈 → 重新生成 DRAFT |
| needs-verification (含 DRAFT) | Phase 1 Review → TDD 写码 → PR |
| `junshi-review/needs-changes` | 读 CI 失败原因 → 修复 → push |

### 3. Phase 1 Review

```
1. 读 CONTRACT_JSON → business_truths
2. 读最新 DRAFT_JSON → L2/L3/L4 case
3. 逐条比对：每个真值是否有对应 case 覆盖
4. 判定：
   ✅ accept     → Phase 2 TDD
   ❌ reject     → gh issue comment <!-- REVIEW_JSON {action:"reject",...} -->
   ➕ supplement → gh issue comment <!-- REVIEW_JSON {action:"supplement",...} -->
```

### 4. Phase 2 TDD → PR

Superpowers `test-driven-development` 全程执行。额外要求：
- 分支已由 agent-poll 创建
- PR body 含 `Closes #xxx` + 测试结果
- **不 merge**（军师 OpenClaw automerge 负责）

### 5. Block Issue 修复

1. 读 BLOCK_LOG → 理解失败原因
2. 根因不明 → `<!-- COMMENT_JSON intent=clarification -->` → 停止
3. 修复 + 全量单测 → push 同分支 → PR

## 约束

- 超时：30min/issue
- 熔断：`block_depth >= 3` → 停止
- 禁止自己 merge PR
- 禁止提交 .env / 密钥
- 验收由 verify-agent 独立执行（与你完全隔离）
