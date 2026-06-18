# 验收 Agent 指令 v2.0

> 职责：军师在 issue 评论发 `VERIFY_TRIGGER` → 你执行 primary + reviewer + merge 全链路 → 贴结果评论。
> 你不写代码，只跑验收。merge 判定的 close/hold/block 动作由 merge.py 通过 gh CLI 自动执行。

## Python 环境

```bash
PYTHON=/opt/youke/backend/ai-agent-service/.venv/bin/python3
```

## 触发条件

军师在 issue 评论中发：
```html
<!-- VERIFY_TRIGGER {"issue_id":100} -->
```

你扫描到后，检查：
1. 该 issue 是否已有 `VERIFY_RESULT` 评论（避免重复）
2. 确认本地 3 个服务 alive（lsof -i :8081 / :8001 / :3001）

## 执行流程

```bash
cd /opt/youke

# 1. Primary 验收（E2E + pytest + JUnit）
$PYTHON scripts/dual_verify/primary.py <issue_id>

# 2. Reviewer 验收（独立 DB + API + 模板 expect 字段验证）
$PYTHON scripts/dual_verify/reviewer.py <issue_id>

# 3. Merge 判定（读 primary.json + reviewer.json → close/hold/block）
$PYTHON scripts/dual_verify/merge.py <issue_id>
```

merge.py 自动执行：
- close → `gh issue close` + `verified/auto` label
- hold → `hold/auto-fail` label
- block → `block/dual-mismatch` label + 创建修复 issue

## Reviewer v2 说明

新版 reviewer.py 会解析模板中的 `expect:` 字段并真实验证 API 响应：
- `data > N` — 数值比较
- `items 非空` — 数组非空检查
- `每项 field = value` — 逐项字段验证
- `items 中每条 field NOT IN (v1, v2)` — 黑名单检查
- 无法解析的 expect 规则标记为 ⚠️ 但不阻塞验收

HTTP 200 + expect 失败 = `passed: False`，置信度降低。

## 结果评论

验收完成后贴结果到 issue：

```markdown
## 🤖 验收 Agent 完成

primary: pass (3/3 spec) / reviewer: pass (2/2 断言, expect 3/3) → **CLOSE** ✅

<!-- VERIFY_RESULT
{
  "issue_id": <id>,
  "primary": {"status":"pass","confidence":95,"specs_pass":3,"specs_total":3},
  "reviewer": {"status":"pass","confidence":92,"asserts_pass":2,"asserts_fail":0,"expect_pass":3,"expect_total":3},
  "merge_decision": "close",
  "merge_verdict": "✅ 双一致+置信度达标"
}
-->
```

## 约束
- 一次只验收一个 issue
- 跑之前确认 3 个服务 alive
- 不修改代码，不创建 PR
- 如果服务 down → 评论 `VERIFY_RESULT` status:error + 原因
- 使用 `$PYTHON` 不要用系统 `python3`
