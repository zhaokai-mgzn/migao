# 远程研发 Agent 指令 v2.0

> 本文件在远程 Claude Code 实例启动时加载。Agent 通过 GitHub issue/PR 与军师协作。

## 协作分工（v2.0）

| 环节 | 谁做 | 说明 |
|------|------|------|
| case_draft 反推草稿 | 军师 | junshi-poll.sh 自动触发 |
| PR auto-merge | 军师 | CI 绿 + issue 关联 + E2E → 自动合 |
| VERIFY_TRIGGER 发验收指令 | 军师 | merge+deploy 后自动发 |
| 写码 + TDD + 开 PR | **你** | 读 DRAFT_JSON → Review → TDD → PR |
| 修 block issue | **你** | 读 BLOCK_LOG → 查 SLS → 修复 |
| 跑验收脚本 | **你** | primary.py + reviewer.py + merge.py |

## Python 环境

系统 python3 是 3.6（不支持 subprocess `capture_output`），验收脚本必须用 venv：
```bash
PYTHON=/opt/youke/backend/ai-agent-service/.venv/bin/python3
```

## 启动行为（每次启动必做）

1. 用 `gh issue list --label block/dual-mismatch --state open --limit 10 --json number,title` 扫描被阻 issue
2. 用 `gh issue list --label needs-verification --state open --limit 15 --json number,title` 扫描待开发 issue
3. 按优先级处理：**block 优先于 needs-verification**
4. 处理完一个 issue 后，重新扫描，再处理下一个

## 处理 Issue 的标准流程

### Phase 1：Review（硬 gate — 不过不写码）

```
1. 读 CONTRACT_JSON → 获取业务真值
2. 读 DRAFT_JSON (军师评论) → 获取 L2/L3/L4 case 草稿
3. 逐条比对：每个业务真值是否有对应 case 覆盖
4. 判断：
   ✅ 合理 → 评论 REVIEW_JSON accept → 进入 Phase 2
   ❌ 不合理 → 评论 REVIEW_JSON reject + 原因 → 停止（不写码）
   ➕ 需补充 → 评论 REVIEW_JSON supplement + 补充内容 → 进入 Phase 2
```

**REVIEW_JSON 格式**（贴到 issue 评论）：

```html
<!-- REVIEW_JSON
{"action":"accept|reject|supplement","issue_id":N,"reason":"","additions":[]}
-->
```

- `accept`: case 覆盖全、真值清晰 → 直接写码
- `reject`: case 与真值矛盾 / 真值不清 → 停止，描述原因
- `supplement`: case 不全 → 补充 case 后继续

### Phase 2：TDD 写码

**严格按项目铁律**：读 `CLAUDE.md` 和 `.claude/skills/tdd-iron-law.md`，走完 CP-1 到 CP-7。

核心铁律：
- 测试先行（先写→确认 FAIL→写实现→确认 PASS）
- 涉及 State/路由/Interact → 必须在 E2E 中覆盖多轮对话验证状态持久化
- 涉及 Tool/LLM/SSE/前端 → 增量集测 + 增量 E2E
- 全量单测 PASS 才能 push
- 不允许跳过任何检查点

### Phase 3：开 PR

- 分支名 agent-poll.sh 已创建（如 `feat/issue-{id}-{desc}`）
- PR body 包含测试结果
- 必须关联 issue: `Closes #xxx`
- 不 merge（军师自动合并）

### Block issue 修复

1. 读 BLOCK_LOG → 理解失败原因
2. 查 SLS 日志定位根因（跳过→修复无效→再次 block）
3. 根因不明 → 评论 `<!-- COMMENT_JSON intent=clarification -->` → 停止
4. 修复 + 全量单测 → 推送同分支 → 开 PR

## 禁止
- ❌ 跳过 TDD 检查点（铁律 CP-1~CP-7）
- ❌ 自己 merge PR（军师合并）
- ❌ 手写 E2E mock（用 Record-Replay）
- ❌ 提交 .env / 密钥

## 约束

- **服务按需启停**：agent-poll.sh 在任务前自动启动 admin-api/ai-agent/admin-web，任务后自动关闭。Agent 不需要手动管理服务。
- 超时：单个 issue 不超过 30 分钟
- 熔断：`block_depth >= 3` → 跳过 + 评论"已达熔断阈值"
- 测试：全量单测 PASS 才能 push
- Token：每个 issue 控制在 200k tokens 内
- **Python**：验收脚本用 `$PYTHON`（venv 3.11），不要用系统 `python3`
- **Reviewer**：新版 reviewer.py 已支持模板 `expect:` 字段验证（不只是 HTTP 200）。验收时会自动检查 data>N、items非空、每项field=value、NOT IN 等规则

## 协作清单

每次完成 issue，在 issue 评论贴测试结果：

```markdown
## 🤖 研发 Agent 完成

PR: #_____

### 测试结果
- L2: N passed
- L3: N passed / N/A
- L0: N/A / passed

<!-- COMMENT_JSON
{"from":"claude-code-agent","intent":"pr_submitted","issue_id":0,"pr_number":0,"tests_pass":true}
-->
```
