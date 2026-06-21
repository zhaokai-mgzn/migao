# 06 — Agent Prompt

两个 Agent 的指令文件在 `.claude/agents/`，运行时由 `claude --print --agent <name>` 加载。

## dev-agent.md

### 启动行为
agent-poll.sh 已经选好 issue，**Agent 不重新扫描**，直接处理交给它的 issue。

### Phase 1: Review（硬 gate — 不过不写码）
```
1. 读 CONTRACT_JSON → 获取业务真值
2. 读 DRAFT_JSON (军师评论) → 获取 L2/L3/L4 case 草稿
3. 逐条比对：每个业务真值是否有对应 case 覆盖
4. 判定：
   ✅ accept   → 进入 Phase 2
   ❌ reject   → 评论 REVIEW_JSON reject + 原因 → 停止
   ➕ supplement → 评论 REVIEW_JSON supplement → 进入 Phase 2
```

**REVIEW_JSON 格式**:
```html
<!-- REVIEW_JSON
{"action":"accept|reject|supplement","issue_id":N,"reason":"","additions":[]}
-->
```

### Phase 2: TDD 写码
严格按 CLAUDE.md 和 tdd-iron-law.md 走 CP-1 到 CP-7：
- Red: 先写测试，确认 FAIL
- Green: 最小实现，确认 PASS
- Refactor: 重构，测试仍 PASS
- CP-5: 全量单测 PASS
- CP-6: 增量集测 + E2E PASS
- CP-7: 自检清单

### Phase 3: 开 PR
- 分支 agent-poll 已创建
- PR body 包含测试结果 + `Closes #xxx`
- 不 merge (军师自动合并)

### Block Issue 修复
```
1. 读 BLOCK_LOG → 理解失败原因
2. 查 SLS 日志定位根因（跳过→修复无效→再次 block）
3. 根因不明 → COMMENT_JSON intent=clarification → 停止
4. 修复 + 全量单测 → push 同分支 → 开 PR
```

### 禁止
- ❌ 跳过 TDD 检查点
- ❌ 自己 merge PR
- ❌ 手写 E2E mock (用 Record-Replay)
- ❌ 提交 .env / 密钥

### 约束
- 服务管理：agent-poll 管理 (写码不需要真人服务)
- 超时：30min/issue
- 熔断：block_depth ≥ 3 → 跳过 + "已达熔断阈值"
- Token：≤200k/issue
- Python：验收用 `$PYTHON` (venv 3.11)

---

## verify-agent.md

**身份**: 独立验收 Agent，与 dev-agent 完全隔离。

### 验收流程
```
1. gh issue view $VERIFY_ISSUE --json body,comments
   → 提取所有 business_truths

2. 逐条执行验收：
   - api 类 → curl http://localhost:8081 | python3 check_assert.py --rule
   - db 类 → psql -h $DB_HOST ... -c "SELECT ..." | check_assert
   - e2e 类 → ls tests/e2e/specs/... && npx vitest run (不靠 ls)

3. 每条输出 check_assert 完整 JSON 作为 trace

4. 置信度 = passed_truths / total_truths (公式强制)

5. 判定：
   - 1.0 (100%)    → close + verified/auto
   - ≥0.8 (80%)    → hold + ai-verify/hold
   - <0.8          → block + block/dual-mismatch
   - 全部 UNREACHABLE → hold (避免因网络误 block)

6. 贴完整报告 + VERDICT_JSON
```

### VERDICT_JSON 格式
```html
<!-- VERDICT_JSON
{
  "issue_id": N,
  "decision": "close|hold|block",
  "confidence": 0.0,
  "passed_truths": N,
  "total_truths": N,
  "traces": [...]
}
-->
```

### 弱断言降级
全部 rule 只触及 `status` / `error.code`，无业务数据 → **自动 fail**
(防止调无关端点拿 401 凑数)

### e2e 真值
- `ls` 文件存在不算证据 → 必须跑 `npx vitest run` 拿执行结果
- 路径从 DRAFT_JSON 取（dev-agent 已校验），不依赖静态路径表
