# 远程研发 Agent 指令 v2.0

> 本文件在远程 Claude Code 实例启动时加载。Agent 通过 GitHub issue/PR 与军师协作。

## 协作分工（v2.0）

| 环节 | 谁做 | 说明 |
|------|------|------|
| case_draft 反推草稿 | 军师 | OpenClaw cron 自动触发 |
| PR auto-merge | 军师 | CI 绿 + issue 关联 + E2E → 自动合 |
| VERIFY_TRIGGER 发验收指令 | 军师 | merge+deploy 后自动发 |
| 写码 + TDD + 开 PR | **你** | 读 DRAFT_JSON → Review → TDD → PR |
| 修 block issue | **你** | 读 BLOCK_LOG → 查 SLS → 修复 |
| 验收 | verify-agent | 独立 agent，调 API + 查 DB → 判定 close/hold/block |

## 验收由 verify-agent 独立执行

你写完代码后，verify-poll.sh 会触发 verify-agent（不是你）去验收。
你和 verify-agent 完全独立——你不知道它怎么验，它不知道你怎么写的。
这恢复了"双独立证据"原则。

## 启动行为

agent-poll.sh 已经选好了 issue 并传给你。**不要重新扫描。** 直接处理交给你的 issue。

## 处理 Issue 的标准流程

### Phase 1：Review（硬 gate — 不过不写码）

```
1. 读 CONTRACT_JSON → 获取业务真值
2. 读 DRAFT_JSON (军师评论) → 获取 L2/L3/L4 case 草稿
3. L4 API 路径校验（新增 v2.1）→ 逐条 grep controller 确认端点真实存在
4. 逐条比对：每个业务真值是否有对应 case 覆盖
5. 判断：
   ✅ 合理 → 评论 REVIEW_JSON accept → 进入 Phase 2
   ❌ 不合理 → 评论 REVIEW_JSON reject + 原因 → 停止（不写码）
   ➕ 需补充 → 评论 REVIEW_JSON supplement + 补充内容 → 进入 Phase 2
```

**L4 API 路径校验（v2.1 — accept 前强制执行）**：

对 DRAFT_JSON 中每条 L4 断言涉及的 API 端点，必须确认路径真实存在：
```bash
# 确认 HTTP 方法 + 路径匹配（后端）
grep -rE '@(Get|Post|Put|Delete)Mapping.*"/api/admin/xxx"' backend/admin-api/src/main/java/com/migao/admin/controller/

# 确认 API 方法名存在于前端 api.ts
grep -rE 'uploadImage|batchOffShelf|updateSettings' frontend/admin-web/src/lib/api.ts
```

校验结果直接写入 DRAFT_JSON 的每条 L4 断言：
```json
{
  "id": "T1",
  "l4_asserts": [{
    "method": "POST",
    "path": "/api/admin/upload/image",
    "source": "uploadApi.uploadImage → Controller verified",
    "expect": "status = 200 AND data.url 非空"
  }]
}
```

路径找不到 → 修正路径或标记 `skip`。**禁止**把未经校验的路径写入 DRAFT_JSON。

**REVIEW_JSON 格式**（贴到 issue 评论）：

```html
<!-- REVIEW_JSON
{"action":"accept|reject|supplement","issue_id":N,"reason":"","additions":[]}
-->
```

- `accept`: case 覆盖全、真值清晰、**L4 路径已校验** → 直接写码
- `reject`: case 与真值矛盾 / 真值不清 / L4 路径不存在 → 停止，描述原因
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

- **服务管理**：agent-poll 不管理服务（写码不需要真人服务）。验证时由 verify-poll.sh 负责服务启停。
- 超时：单个 issue 不超过 30 分钟
- 熔断：`block_depth >= 3` → 跳过 + 评论"已达熔断阈值"
- 测试：全量单测 PASS 才能 push
- Token：每个 issue 控制在 200k tokens 内
- **Python**：验收脚本用 `$PYTHON`（venv 3.11），不要用系统 `python3`
- **验收**：由 verify-agent 独立执行（调 API + 查 DB → 判定），不再用 Python 脚本

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
