# AGENTS.md — MIGAO（AI 智能客服系统）

> DSH（DeepSeek Harness）会话的仓库级入口。开发前先读本文件，再按需查阅 docs/wiki/INDEX.md 定位规范页。

## 这是什么

面向布艺行业的多租户 AI 智能客服 SaaS：C 端小布 + B 端米宝双 Agent（LangGraph），
Java admin-api + Python ai-agent-service + Next.js admin-web + Taro mini-app。

## 改代码前（铁律）

1. **测试先行**：先写失败测试（Red）→ 最小实现（Green）→ 重构。全量单测必须 PASS。见 [docs/wiki/Development.md](docs/wiki/Development.md) 的 TDD 检查点。
2. **三把工具**：提交前跑 `./verify-all.sh gate`（与 CI 同规则）、`./check-ui-regression.sh`（UI 回退）；跨模块改动加 `./contract-check.sh`。
3. **case_ids**：新增/修改测试文件头部必须声明 `# case_ids:`（对应 `.github/cases/` 用例，否则 CI QA Growth Gate block）。
4. **GitHub 操作**：禁止直推 main，必须走 PR 且关联 Issue——**PR body 必写 `Closes #<issue号>`**（GitHub 只在 body 含 Closes/Fixes/Resolves 关键词时自动关 issue，标题里的「(issue #xx)」不生效；漏写合并后 issue 不会自动关闭，CI `pr-issue-link` 会打 `needs-issue-link` 标签提醒；无 issue 关联的基建 PR 标 `N/A（基建）`）。详见 `migao-dev-flow` 技能 §2.2/§3.3。合并后 GitHub 异步关闭偶发失效（close-on-merge best-effort，实证 #2910/#2919 未自动关）→ `close-linked-issues.yml` 解析 body 关键词做合并后补偿关闭 + schedule 定时对账兜底（issue #2937；cron 声明 30 分钟、实测被 GitHub 节流至 2~5.5h 触发；pull_request closed 事件对 native auto-merge 合并实测不可靠），无需人工；若 issue 仍悬挂再按 §2.2 人工兜底。
5. **最少代码**：写码前爬「最少代码阶梯」（YAGNI → 复用 → 标准库 → 原生特性 → 已装依赖 → 一行 → 最小实现；**先理解再爬梯**）。只简化实现代码、**不降测试门禁**，安全护栏与既有架构契约永不砍。全文见 [docs/wiki/Code-Minimalism.md](docs/wiki/Code-Minimalism.md)。
6. **并行修复（发现即并行，合并串行）**：一次暴露多个问题时**禁止逐个串行修复**——
   先**冻结问题清单**（每条含证据 + 归因层级 + 验收判据）→ 按**文件所有权**切成互不冲突的任务包
   （同文件改动同包；改 `cases/*.yml` 的包独占生成物）→ 每包 = issue + 分支 + 独立 worktree +
   后台 subagent（§2.3 零共享写路径）→ **主会话只做集成与验证**。合并串行、验证收口；
   评测型流水线同时 ≤3（runner 竞争 + 真实 LLM 成本）。全文与反模式见 `migao-dev-flow` 技能 §17。

## 按场景找文档（先查索引，按需 Read）

| 场景 | 入口 |
|---|---|
| 全部场景索引 | [docs/wiki/INDEX.md](docs/wiki/INDEX.md) |
| 开发流程 / 验证命令清单 | [docs/wiki/Development.md](docs/wiki/Development.md) |
| 写码最少化（防过度建设/加依赖前） | [docs/wiki/Code-Minimalism.md](docs/wiki/Code-Minimalism.md) |
| 测试工程规范（拆分/ignore/脱敏/分层） | [docs/testing/test-engineering-standards.md](docs/testing/test-engineering-standards.md) |
| **验收/评测（下"验收通过"结论前必读）** | [docs/testing/acceptance-protocol.md](docs/testing/acceptance-protocol.md)（配套 DSH 技能 `migao-acceptance`） |
| CI/CD / 部署 | [docs/wiki/CI-CD.md](docs/wiki/CI-CD.md) |
| 行为用例单一源 | `.github/cases/`（改后必须跑 `render_cases.py` 并提交生成物） |

## 开发环境准备（获取研发模式）

「米高研发」= DSH agent preset（`preset.yml` + `agent.cordis.yml` + `migao-dev-flow` / `migao-acceptance`
两个技能），**权威源就是本仓库 [`.agent-presets/migao/`](.agent-presets/migao/README.md)** —— 随代码一起评审、一起回溯。
DSH 从 root `~/.dsh/.agent-presets/`（`USER_PRESET_DIR = '.agent-presets'`）发现 preset，
因此把它软链到本仓库该路径即可获得同一份研发模式：

**⚠️ 顺序铁律：先合并含 `.agent-presets/migao/` 的 PR，再执行换链** —— 仓库尚无该路径时换链会让 DSH 当场失效。

```bash
# 在已克隆（且已含该路径）的 migao 仓库根目录执行
ls .agent-presets/migao/preset.yml     # ① 先确认仓库里已有该路径

# ② 摘掉旧目录 / 旧软链（若是实体目录，先备份而不是直接删）
mv "$HOME/.dsh/.agent-presets/migao" "$HOME/.dsh/.agent-presets/migao.bak-$(date +%Y%m%d-%H%M%S)" 2>/dev/null || true

# ③ 换链：-s 建软链 / -f 覆盖已存在项 / -n 不跟随已存在的软链目录
ln -sfn "$PWD/.agent-presets/migao" "$HOME/.dsh/.agent-presets/migao"

# ④ 校验：应能读到 preset 元数据与技能
cat "$HOME/.dsh/.agent-presets/migao/preset.yml"
head -3 "$HOME/.dsh/.agent-presets/migao/skills/migao-dev-flow/SKILL.md"
```

- **换机 / 新队友**：`git clone` 本仓库 → 在仓库根跑上面 ②~④，即获得同一份研发模式（不再依赖个人 `~/.dsh` 手抄副本）。
- **改研发模式 = 提 PR**：改 `.agent-presets/migao/**` 走正常 PR 流程（评审 + 回溯）；软链指向工作区文件，合并/拉取后自动生效。
- 历史独立仓库 `zhaokai-mgzn/migao-agent-presets` 现为**历史 / 镜像，以本仓库为准**；其远程去留（保留/归档/删除）**待用户裁定**，裁定前不动它。详见 [`.agent-presets/migao/README.md`](.agent-presets/migao/README.md)。

## 环境

- 本地只启 3 组件：admin-api(:8080) + ai-agent-service(:8001) + admin-web(:3001)；DB/Redis 用云 dev
- DSH 专用技能：`migao-dev-flow`（三把工具/提交流程/QA 门禁 §3.4）、`migao-acceptance`（验收/评测协议）——由「米高研发」preset 自动加载
