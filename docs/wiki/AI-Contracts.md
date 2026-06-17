# AI 协作契约规范 v1.0

> 军师（远程 AI）和 Claude Code（开发 AI）通过 GitHub issue/PR/评论异步协作。
> 每种交互都有标准化的机读 JSON 块，确保双方精确理解，不靠猜测。

## 生命周期

```
创建 issue ──→ 军师反推 case ──→ 研发 review ──→ 开 PR ──→ merge
(CONTRACT)    (DRAFT_JSON)     (REVIEW_JSON)   (PR_BODY)     
                                                              │
                                                              ▼
close ←── 双一致 ── 军师验收 ←──────────────────────────────┘
         (VERDICT_JSON)
                         │
                         ├── block → 创建修复 issue → 修 → PR → merge → 重新验收 ↻
                         │          (CONTRACT + PARENT)   (PR_BODY + PARENT)
                         │
                         └── hold → 研发补充 → 重新验收
                                    (COMMENT_JSON)
```

---

## 契约 1：Issue 创建

**文件**：`.github/ISSUE_TEMPLATE/feature.md` / `bug.md` / `cloud-verify.md`

**机读块**：issue body 末尾的 `<!-- CONTRACT_JSON -->`

```json
{
  "schema_version": "1.0",
  "type": "feature | bug | cloud-verify",
  "business_truths": [
    "条件 A → 期望结果 A",
    "条件 B → 期望结果 B"
  ],
  "affected_modules": ["admin-api", "admin-web"],
  "red_flags": ["#387"],
  "exclusions": ["不包含 mobile 端"],
  "parent_issue": null
}
```

**谁写**：创建 issue 的人（凯总/娜总/AI）填写业务真值章节。
**谁读**：军师 → case_draft.py 解析 `CONTRACT_JSON` 获取真值列表 → 反推 case。

---

## 契约 2：军师反推 Case 草稿

**介质**：issue 评论

**机读块**：`<!-- DRAFT_JSON -->`

```json
{
  "schema_version": "1.0",
  "issue_id": 452,
  "template": "order-classify",
  "business_truths": ["含加工待发货 = ..."],
  "l2_cases": [
    { "truth_index": 0, "file": "tests/test_graph_nodes.py", "scenario": "..." }
  ],
  "l3_specs": ["tests/e2e/specs/orders/order-list.spec.ts"],
  "l4_asserts": [
    { "truth_index": 0, "method": "db", "query": "orders WHERE status AND has_processing" }
  ],
  "red_flags": ["#387"]
}
```

**谁写**：军师 case_draft.py 自动生成。
**谁读**：研发 + Claude Code → 解析 `DRAFT_JSON` → 按 TDD 写码。

---

## 契约 3：研发 Review 回复

**介质**：issue 评论

**场景 A** — 同意 case 草稿，开始写码：
```markdown
## ✅ Review 通过

同意军师 case 草稿，开始写码。

<!-- REVIEW_JSON
{
  "action": "accept",
  "issue_id": 452,
  "comment": ""
}
-->
```

**场景 B** — 不同意某个 case：
```markdown
## ❌ Review 不通过

L2 case 1 不合理：业务真值要求"含加工待发货"，但测试场景覆盖的是"无加工待发货"。

<!-- REVIEW_JSON
{
  "action": "reject",
  "issue_id": 452,
  "rejected_items": ["l2_cases[0]"],
  "reason": "L2 case 1 覆盖场景与业务真值不符"
}
-->
```

**场景 C** — 补充 case：
```markdown
## ➕ 补充 case

额外需要覆盖：多租户隔离场景下，租户 A 的订单不应出现在租户 B 的列表中。

<!-- REVIEW_JSON
{
  "action": "supplement",
  "issue_id": 452,
  "additions": ["多租户隔离: 租户A订单不出现在租户B"],
  "additional_specs": ["tests/e2e/specs/quality/tenant-isolation.spec.ts"]
}
-->
```

**谁写**：研发 / Claude Code。
**谁读**：军师 → 如果 reject → 重新反推 case。如果 accept → 等 PR merge 后验收。

---

## 契约 4：PR 提交

**文件**：`.github/PULL_REQUEST_TEMPLATE.md`

**PR body 必须包含**：
```markdown
## 关联 Issue
Closes #452

## 改动摘要
（一句话描述）

## 测试清单
- [ ] L2 单测：_____（文件路径，测试数）
- [ ] L3 E2E：_____（spec 路径）
- [ ] L0 持久化：_____（如涉及 State/路由）

## 涉及模块
- [ ] admin-api
- [ ] ai-agent-service
- [ ] admin-web

<!-- PR_CONTRACT
{
  "issue_id": 452,
  "l2_tests": ["tests/test_graph_nodes.py"],
  "l3_specs": ["tests/e2e/specs/orders/order-list.spec.ts"],
  "l0_required": false,
  "modules": ["ai-agent-service"]
}
-->
```

**谁写**：研发 / Claude Code 开 PR 时。
**谁读**：军师 → 从 PR_CONTRACT 获取测试文件列表 → merge 后跑 primary.py 验证这些文件。

---

## 契约 5：军师验收报告

**介质**：issue 评论

**机读块**：`<!-- VERDICT_JSON -->`

```json
{
  "issue_id": 452,
  "decision": "close | hold | block",
  "verdict": "✅ 双一致 + 置信度达标",
  "primary": { "status": "pass", "confidence": 95, "specs_pass": 3, "specs_total": 3 },
  "reviewer": { "status": "pass", "confidence": 92, "asserts_pass": 2, "asserts_fail": 0 },
  "conflicts": [],
  "commit": "abc1234"
}
```

**谁写**：军师 merge.py 自动生成。
**谁读**：Claude Code → 解析 VERDICT_JSON → close 则结束，block 则进入修复流程。

---

## 契约 6：Block → 修复

**修复 issue**：军师 merge.py 自动创建（见 `scripts/dual_verify/merge.py` `act_on_decision`）。

**修复 issue body** 含：
```json
<!-- CONTRACT_JSON
{
  "schema_version": "1.0",
  "type": "bug",
  "parent_issue": 452,
  "business_truths": ["...原 issue 的业务真值..."],
  "failed_truths": ["含加工待发货订单状态应为待发货"],
  "failed_specs": ["tests/e2e/specs/orders/order-list.spec.ts"],
  "conflicts": ["主验收通过但复核不通过（可能 mock 数据骗人）"]
}
-->
```

**修复 PR body** 含：
```markdown
Closes #453  (修复 issue)
Fixes #452   (原 feature issue)

<!-- PR_CONTRACT
{
  "issue_id": 453,
  "parent_issue": 452,
  "fix_for": "block/dual-mismatch",
  ...
}
-->
```

修复 PR merge → 军师检测到 `parent_issue` → 重新验收原 issue #452。

---

## 契约 7：军师与研发的通用评论

**介质**：issue/PR 评论

所有军师 ↔ 研发的互动评论末尾都附带 `<!-- COMMENT_JSON -->`，标识发送方、意图、关联 issue：

```json
<!-- COMMENT_JSON
{
  "from": "junshi | claude-code | developer",
  "intent": "case_draft | review_response | verification_report | fix_notice | manual_note",
  "issue_id": 452,
  "timestamp": "2026-06-17T10:30:00Z"
}
-->
```

**谁写**：任何一方发评论时附带。
**谁读**：另一方解析 `from` 和 `intent` 知道该怎么处理。

---

## 标签状态机

| 标签 | 含义 | 谁打 | 下一步 |
|------|------|------|--------|
| `needs-verification` | 等军师出 case / 等验收 | 创建 issue 时自动 | 军师出 case → 研发 review |
| `in-progress` | 研发正在写码 | 研发认领时 | 开 PR |
| `block/dual-mismatch` | 验收不一致 | 军师 merge.py | 研发立即修复 |
| `hold/auto-fail` | 双一致失败 | 军师 merge.py | 研发补充 |
| `verified/auto` | 验收通过 + 已 close | 军师 merge.py | 闭环 |

---

## 铁律

1. **所有交互必须有机读 JSON 块** — 不靠自然语言猜
2. **issue 必须先于代码** — 没有 issue 不写代码
3. **业务真值用业务语言** — 不带 SQL/API
4. **block 后 24h 内必须有修复 PR** — 不让验收债务堆积
5. **修复 PR 必须关联 parent_issue** — 让军师知道该重新验收谁
