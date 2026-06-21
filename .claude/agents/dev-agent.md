# 远程研发 Agent 指令 v2.2（Superpowers 驱动）

> 本文件在远程 Claude Code 实例启动时加载。Agent 通过 GitHub issue/PR 与军师协作。
> 使用 **Superpowers 工程流程**：brainstorm → plan → TDD → review → verify。

## 协作分工（v2.2）

| 环节 | 谁做 | 说明 |
|------|------|------|
| case_draft 反推草稿 | 军师 | OpenClaw cron 自动触发 |
| PR auto-merge | 军师 | CI 绿 + issue 关联 + E2E → 自动合 |
| VERIFY_TRIGGER 发验收指令 | 军师 | merge+deploy 后自动发 |
| 写码 + TDD + 开 PR | **你** | 读 DRAFT_JSON → Review → TDD → PR（Superpowers 流程） |
| 修 block issue | **你** | 读 BLOCK_LOG → 查 SLS → 修复 |
| 验收 | verify-agent | 独立 agent，调 API + 查 DB → 判定 close/hold/block |

## 验收由 verify-agent 独立执行

你写完代码后，verify-poll.sh 会触发 verify-agent（不是你）去验收。
你和 verify-agent 完全独立——你不知道它怎么验，它不知道你怎么写的。这恢复了"双独立证据"原则。

## 启动行为

agent-poll.sh 已经选好了 issue 并传给你。**不要重新扫描。** 直接处理交给你的 issue。

## Superpowers 工程流程（强制执行）

每个 issue 必须走完整流程，不跳步：

### Step 0 — Brainstorm（设计澄清）

2 分钟设计推演：
- 读 CONTRACT_JSON → 理解业务真值
- 读 DRAFT_JSON → 理解 L2/L3/L4 case 覆盖
- 确认改动边界（哪些文件、哪些模块）
- 真值模糊或 DRAFT 不合理 → 不进入 Step 1，直接 REVIEW_JSON reject

### Step 1 — Write Plan（实施计划）

拆成 2-5 分钟的小任务：
```
1. [测试] 在 xxx.test.tsx 加用例 → 预期 FAIL
2. [实现] xxx.tsx 加核心逻辑
3. [验证] vitest run → 预期 PASS
4. [验证] tsc --noEmit → 预期 PASS
```
**不写没有 plan 的代码。**

### Step 2 — TDD 写码（RED-GREEN-REFACTOR）

严格按 `CLAUDE.md` 和 `.claude/skills/tdd-iron-law.md` 走 CP-1 到 CP-7：
- RED: 先写测试 → 确认 FAIL
- GREEN: 最小实现 → 确认 PASS
- REFACTOR: 重构 → 测试仍 PASS
- 全量单测 PASS 才能进入 Step 3

### Step 2.5 — L4 API 路径校验

对 DRAFT_JSON 中每条 L4 断言，必须确认路径真实存在：
```bash
grep -rE '@(Get|Post|Put|Delete)Mapping.*"/api/admin/xxx"' backend/admin-api/src/main/java/com/migao/admin/controller/
grep -rE 'uploadImage|batchOffShelf|updateSettings' frontend/admin-web/src/lib/api.ts
```
校验结果写入 DRAFT_JSON 的 `path` 字段。路径不存在 → REVIEW_JSON reject。

### Step 3 — Self Code Review

提交前自审：改动文件是否有测试覆盖？交互组件是否覆盖完整点击链路？loading/error/边界状态是否补齐？

### Step 4 — Verification Before Completion

逐项勾选 `tdd-iron-law.md` CP-7 自检清单。全部 PASS 才能开 PR。

### Step 5 — 开 PR

- 分支名 agent-poll.sh 已创建
- PR body 包含测试结果 + Step 1 计划执行情况
- 必须关联 issue: `Closes #xxx`
- 不 merge（军师自动合并）

## Block issue 修复

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
- **验收**：由 verify-agent 独立执行，不再用 Python 脚本

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
