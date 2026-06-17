# AI 协作契约 v2.0 — 单 Issue 全生命周期

> 军师 (GitHub) 和 Agent (服务器) 通过 issue 的**标签 + 评论 + JSON 机读块**协作。
> 一个 issue 从创建到 close 全程不换号。

## 生命周期状态机

```
        创建 issue (CONTRACT_JSON)
              │
              ▼
         needs-verification
              │
              ├── 军师检测 → case_draft → 评论 DRAFT_JSON
              │
              ├── Agent 抢 issue → TDD 写码 → PR → merge
              │
              ├── 军师检测 merge → 评论 VERIFY_TRIGGER
              │
              ├── Agent 跑验收 → primary+reviewer+merge
              │         │
              │         ├── pass → close + verified/auto ✅
              │         │
              │         └── block → +block/dual-mismatch
              │              │      +保留 needs-verification
              │              │      +评论 BLOCK_LOG
              │              │
              │              └── Agent 重新抢 → 修复 → PR → merge
              │                     │
              │                     └── 重新验收 → 循环
              │                            │
              │                            └── 3次打回 → block/need-human 🛑
              │
              └── hold → hold/auto-fail（需人工补充）
```

## 契约格式

### 1. Issue 创建 → CONTRACT_JSON（issue body 末尾）

```html
<!-- CONTRACT_JSON
{"schema_version":"1.0","type":"feature","business_truths":["条件A→结果A"],"affected_modules":["ai-agent-service"]}
-->
```

### 2. 军师反推 case → DRAFT_JSON（issue 评论）

```html
<!-- DRAFT_JSON
{"issue_id":100,"template":"order-classify","business_truths":["..."],"l2_cases":[...],"l3_specs":[...],"l4_asserts":[...]}
-->
```

### 3. 军师触发验收 → VERIFY_TRIGGER（issue 评论）

PR merge + deploy 完成后，军师发：

```html
<!-- VERIFY_TRIGGER {"issue_id":100} -->
```

Agent 扫描到后执行 primary.py → reviewer.py → merge.py（本地全链路）。

### 4. 验收结果 → VERIFY_RESULT（Agent 评论）

```html
<!-- VERIFY_RESULT
{"issue_id":100,"primary":{"status":"pass","confidence":95},"reviewer":{"status":"pass","confidence":92},"merge_decision":"close"}
-->
```

### 5. 打回日志 → BLOCK_LOG（merge.py 自动评论）

```html
## ⚠️ 验收 Blocked（第N/3次）

<!-- BLOCK_LOG
{"block_depth":2,"failed_specs":["tests/..."],"conflicts":["主通过复不通过"]}
-->
```

### 6. Agent 完成 → COMMENT_JSON（Agent 评论）

```html
## 🤖 研发 Agent 完成  PR: #123
<!-- COMMENT_JSON {"from":"claude-code-agent","intent":"pr_submitted","issue_id":100,"pr_number":123,"tests_pass":true} -->
```

## 标签状态机

| 标签 | 谁打 | 含义 | 下一步 |
|------|------|------|--------|
| `needs-verification` | 创建时 | 等军师出 case / Agent 开发 / Agent 修复 | Agent 抢 |
| `block/dual-mismatch` | merge.py | 验收不一致 | Agent 优先抢 + 修复 |
| `block/need-human` | merge.py(熔断) | 打回≥3次 | 凯总/娜总介入 |
| `hold/auto-fail` | merge.py | 双方都失败 | 研发补充 |
| `verified/auto` | merge.py | 验收通过 | 闭环 |

## Agent 扫描优先级

```
1. block/dual-mismatch + needs-verification  → 验收被阻，立即修复
2. needs-verification (有 DRAFT_JSON 评论)   → 新功能/Bug，开始写码
3. VERIFY_TRIGGER 评论 (无 VERIFY_RESULT)    → 跑验收
```

## 铁律

- **一个 issue 走到底**，不创建子 issue
- **所有交互带 JSON 机读块**，不靠自然语言猜
- **军师不跑验收脚本**，只发 VERIFY_TRIGGER + 读 VERIFY_RESULT
- **Agent 跑全链路验收**，merge.py 在服务器本地执行
- **3 次打回熔断**，block_depth 从 BLOCK_LOG 评论累计
