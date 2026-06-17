# 军师评审结论 Label 体系

> 2026-06-17 启动（凯总指示）
> 配合 GitHub branch protection 使用

## 三个 junshi-review label

| Label | 颜色 | 含义 | 触发场景 |
|---|---|---|---|
| `junshi-review/pass-with-followups` | 🟢 #0E8A16 | 评审通过 + 跟进项 | CI 绿、Fixes 齐、E2E 齐，**但有非阻塞跟进**（文档/小修/follow-up issue） |
| `junshi-review/needs-changes` | 🟡 #FBCA04 | 评审需改 | CI 红、缺测试、缺 Fixes #xxx、缺 E2E spec |
| `junshi-review/blocked` | 🔴 #D93F0B | 评审阻塞 | 业务真值冲突、缺关键验收、业务逻辑改动需人类审批 |

## 三个 ai-verify label（与 junshi 分开，表示"自动验收"环节）

| Label | 颜色 | 含义 | 触发场景 |
|---|---|---|---|
| `ai-verify/pending` | 🔵 #1D76DB | AI 验收中 | 军师/研发 AI 跑主+复+云 |
| `ai-verify/skip-deployment` | 🟣 #7057FF | 部署类等云 | is_deployment_issue v2 命中 |
| `ai-verify/hold` | ⚪ #BFD4F2 | 验收 hold | 等云 / 缺信息 / 需人工 |

## 评审流程（军师守则）

1. **PR 评审** → 挂 `junshi-review/*`
2. **主+复核验收** → 挂 `ai-verify/pending` → 完事换 `verified/auto` 或 `block/dual-mismatch`
3. **部署类** → 挂 `ai-verify/skip-deployment` 等 cloud.json
4. **军师评审通过 + 跟进项** → 挂 `pass-with-followups`（不是纯绿，但允许 merge）

## branch protection 配合（2026-06-17 配置）

```json
{
  "required_status_checks": {
    "strict": true,
    "contexts": [
      "Block .env files (except .env.example)",
      "admin-api unit tests",
      "ai-agent-service unit tests",
      "admin-web typecheck + unit tests",
      "mini-app typecheck + unit tests",
      "QA Growth Gate"
    ]
  },
  "required_pull_request_reviews": {
    "required_approving_review_count": 1,
    "dismiss_stale_reviews": true
  },
  "required_linear_history": true,
  "required_conversation_resolution": true,
  "allow_force_pushes": false,
  "allow_deletions": false
}
```

## 触发矩阵（自动挂 label）

| 评审结果 | 必挂 label | 可选 |
|---|---|---|
| CI 全绿 + Fixes + E2E | `pass-with-followups` | — |
| CI 红 | `needs-changes` | `block/dual-mismatch` |
| 缺 Fixes #xxx | `needs-changes` | — |
| 缺 E2E spec（前端 page.tsx 改动） | `needs-changes` | — |
| 业务逻辑改动 | `blocked` | `needs-junshi-approval` |
| 部署类 | `pass-with-followups` | `ai-verify/skip-deployment` |
| 双验收不一致 | `blocked` | `block/dual-mismatch` |
| 军师自动合 | 移除所有 review label | 加 `junshi-auto-merged` |

## 边界

- ❌ 军师**不**强制挂 label（凯总/娜总 override 可不挂）
- ❌ 军师**不**直接改 PR 业务代码（仅评审 + 挂 label + 评论）
- ✅ 军师评审后 1 分钟内挂 label + 发评论
- ✅ 评审结论与 PR 评论 + label 三者**必须一致**

## 实测记录

- #471 / #472：研发 19:39 自行合并前**未挂 junshi-review label** → 触发 `developer_merges_before_junshi_approval` ACC 错误模式
- 启用本体系后，研发必须等军师挂 label 才能合（CI check 必过 + 1 reviewer approval 必拿）
