# 无方向审计报告（2026-09-04）

> 审计方式：全维度扫描（git 健康 / 测试质量 / 文档一致性 / 依赖健康 / CI 部署 / 独立验证并行）。
> 基线：分支 `feat/2815-cend-long-term-memory`（HEAD f666a157）vs `origin/main`（e7f61882）。
> 全程只读，未修改代码、未 push、未触发 CI。

## 0. 结论速览

| 严重度 | 数量 | 一句话 |
|---|---|---|
| **P0** | 0 | 无阻断性问题 |
| **P1** | 8 | 当前 PR 的 Agent Eval 真实失败（OR-010）；部署万能码自愈；gate 组件豁免掩盖测试缺口；Spring Boot / Next.js EOL；CHANGELOG/README/gb47746 文档严重滞后 |
| **P2** | 14 | stash 悬置、远程分支残留、case_ids 缺口、confirm 守卫 2 处缺口、env 入库、config 随 main 漂移、render_cases 映射不全、依赖升级机会、文档口径不一 |
| **P3** | 10+ | 规范化小项（gitignore/cron/选择器/断言正则等） |

**健康面（通过项）**：三把工具全绿（gate / contract-check / ui-regression / quick 6 项全过）；生成物单一源完全同步（166=166=166，truths 0 冲突）；E2E 视觉基线双平台齐全；E2E 34/34 spec 全部带 case_ids；confirm 守卫机制整体健全；依赖配对自洽且 Taro 4.2.1 已最新；docs INDEX 无断链；无死 workflow；无硬编码密钥；时区已统一 UTC+8。

---

## 1. P1 — 高严重度（8 项）

### 1.1 当前 PR #2818 的 Agent Eval 为「真实失败」，不是偶发波动
- **证据**：`gh run view 33840768953 --job 100937580636 --log` 显示两次尝试中 **OR-010「创建订单-汇总确认简化流程」均 score=0%**（期望 `validate_input` + `order_create`，实际 LLM 只调了 product_search/product_detail/interact），且日志出现「第 1 次失败(exit 1)，重试…」后第二次仍失败。其余用例全部 100%/80%。
- **与 §3.1「偶发 LLM 波动可重跑转绿」不同**：同一用例两轮都挂在同一个期望上 → 更像当前分支行为变更（memory 注入/agent_type 分流改动 chat.py、base_skill.py）导致下单链路与用例期望不符，**先排查再重跑**。
- **建议**：本地 `pytest tests/agent_eval` 单跑 OR-010 复现；检查 memory 注入对 order 技能工具选择的影响；修复后重跑 Agent Eval。
- 另：PR #2813（feat/2806）Agent Eval 失败属偶发模式（§3.1），可先 `gh run rerun <run> --failed`。

### 1.2 deploy.sh 自动补 SMS 万能码（生产 fail-closed 缺口）
- `deploy/swas/deploy.sh` 1.6/1.6b 节：服务器 `.env.*` 缺 `SMS_BYPASS_CODE` 时**自动写入 123456**（POC 决策 D2，技术债 #2616）。
- 风险：生产首次部署未显式置空即启用万能码登录。当前 SWAS 为测试环境暂缓，但 **deploy-prod.yml 启用前必须改为「缺失即报错」**。

### 1.3 QA Growth Gate 组件测试缺口被豁免掩盖
- 23 个组件测试放在 `frontend/admin-web/tests/unit/components/{chat,corporate,dashboard,layout,orders,products}/` 子目录；gate 模板 `tests/unit/components/{2}.test.ts` **不递归子目录** → 找不到测试。
- `qa-exemptions.yml` L142-234 恰好把这 ~60 个组件全部列为豁免（共 93 条）→ **这些组件任何改动都不再受 gate 测试覆盖校验**（SkuMatrix 等少数豁免有正当理由，chat/orders/dashboard/layout 大部分没有）。
- **建议**：测试平铺到 `tests/unit/components/<Name>.test.tsx`，删除对应豁免条目。

### 1.4 Spring Boot 3.3.9 已 EOL
- `backend/admin-api/pom.xml:10` spring-boot-starter-parent 3.3.9；3.3.x OSS 支持至 2025-06、商业延伸至 2026-06，当前（2026-09）**已完全 EOL，无安全补丁来源**。
- 连带：升级需同步 springdoc 2.6.0 → 2.8+/3.x。建议整组升级 PR（boot 3.5.x + springdoc + 全量单测 + contract-check）。

### 1.5 Next.js 14.2.35 出安全支持期
- `frontend/admin-web/package.json` next ^14.2.18 → lock 14.2.35；当前最新 16.3.4，14.x 已基本出安全支持期。
- 建议至少升 15.3+，React 19 可随第二波；admin-web 需全量回归。

### 1.6 CHANGELOG 严重滞后
- CHANGELOG.md 最大 issue 号 #2616、止于 2026-08-30；git 已合并到 #2817（e7f61882）。#2815 长期记忆、#2810/#2814 时区、#2806 M3 取价、#2804 舍入、#2803 财务文案、#2802 RBAC 越权修复、GB 合规系列**全部未记录**。

### 1.7 README 内部自相矛盾 + 零覆盖新功能
- Taro 3.6（README.md:25,144）vs 4.2.1（README.md:63，代码实为 4.2.1）；「31 个工具」5 处（实际注册 33 个，registry.py 实测）；Service 23 vs 26；工作流 16 vs 19。
- 零覆盖：长期记忆系统、全栈 UTC+8、GB/T 47746-2026 合规、M3 服务端取价。

### 1.8 gb47746-2026-compliance.md 状态过时
- GB-05 仍标「⏳ 建议后续」（:52），但 #2808/#2809 已合并收口；「服务端取价为遗留增强项」（:34,42,50）但 #2806 已落地。

---

## 2. P2 — 中严重度（14 项）

### Git 健康
1. **stash@{0} "dashboard-pr-wip" 悬置**（10 文件 354+/144-，dashboard 看板 WIP）：来源分支 fix/wechat-code2session-textplain 本地已删、仅远程存在（13 个独有提交未合并）。先查 PR 状态：open → apply 恢复；已落地 → drop。
2. **远程 25 个已合并分支残留**（cherry 全 `-`）：chore/deps-setup-*、docs/gb47746-closure、feat/2776/2780/2782、issue-1198--、fix/2807-copy-truthfulness、afterhours-timezone、aftersale-order-no、ci-aiagent-touch、dashboard-rounding、deploy-disk-precheck、e2e-auth-me-global-mock、finance-diff-label、login-redirect-loop、miniapp-aftersales-e2e、miniapp-handoff-e2e、nginx-tz、rbac-menu-entry、rbac-operator-scope、rbac-ui-role-assign、workspace-redirect、xiaobu-aftersale-skill、xiaobu-aftersale-v2。`git branch -r --merged` 因 squash 失效，须用 `git cherry` 口径清理。
3. **37 个未合并远程分支需逐一核对 PR 状态**（含 fix/wechat-code2session-textplain 等历史遗留）。

### 测试
4. **7 个测试文件缺 case_ids**（30 天内新增 3 + 修改 4）：
   - 新增：`test_internal_tool_execute_guard.py`、`test_tool_write_not_cached.py`（#2394）、`sanitize-html.test.ts`（#2395）；
   - 修改：`JwtAuthenticationFilterTest.java`、`floating-assistant.test.tsx`、`hooks/useResizableHeight.test.ts`、`pages/chat-page.test.tsx`。
   - 已合并不再 block，但违反铁律，建议补声明。
5. **human_handoff 无代码层确认拦截**：`app/tools/human_handoff.py:112-113` `read_only=False, destructive=False` 无 `requires_confirmation` → 转人工（状态变更写操作）仅靠 prompt 约束。建议加 `requires_confirmation=True`。
6. **aftersale_create 缺 validate_input 前置**：`customer_aftersales_skill.py:6` 工具列表无 validate_input（对比 order/product skill 均含）。

### 部署/CI
7. **admin-web 两个 `.env.*` 被 git 追踪**：`.env.development` / `.env.production`（内容仅公共 URL，无密钥，但违反「.env.* 不入库」）。建议 `git rm --cached` 并提交 .env.example 形态。
8. **deploy.sh 配置随 main 漂移**：从 codeload 拉 main 最新 compose/nginx/deploy.sh，镜像 sha 锁定但配置不锁定；回滚（image_tag）时配置可能与目标版本不符。建议按 IMAGE_TAG 校验/固定配置版本。
9. **render_cases SKILL_MAP/DOMAIN_TITLES 只覆盖 12 域**：9 个新域（agents/api/finance/misc/onboarding/registry/token-refresh/ui/utils）落空 → 95/166 用例 Skill.GENERAL、md 章节显示英文域名。local_runner 不消费 skill（无功能影响），建议补映射重渲染。

### 依赖
10. **langchain 组无 dependabot 防护**：pip 块无 ignore/分组，dependabot 可能单独提 langchain-openai 1.6.x 撞 core==1.4.8 冲突。建议加 ignore 或整组升级策略（照抄 mini-app 的写法）。
11. **mybatis-plus 3.5.8 落后 9 个小版**：升 3.5.9+ 时 starter 拆 extension、分页插件走 `mybatis-plus-jsqlparser` 独立构件（现直钉 com.github.jsqlparser 需评估替换）。可与 Spring Boot 升级合成一次 Java 侧 PR。
12. **本地 venv 与 requirements.txt 漂移**：venv 建于 8-13，requirements 改于 9-02；pydantic 2.10.4 vs 2.13.5、uvicorn 0.34 vs 0.52.4 等。本地测试跑旧版、Docker 装新版 → 建议重建 venv 或 CI 强制比对。

### 文档
13. **验证用例 CU-003 与代码不符**：mibao-verification-cases.md:693 描述「打标签 TODO 空实现」，CustomerService.java:98-106 已实现。
14. **端口口径三处文档不一致**（8000 vs 8001）；**schema.sql/schema_full.sql 缺 user_memories 表**（迁移 V20260608 已建、Database.md:20 已列）。

---

## 3. P3 — 低严重度（10+ 项）

1. 根目录裸 `playwright-report/`、`test-results/` 未加 gitignore（当前产物在 tests/ 下，无泄漏）。
2. 本地 main 落后 origin/main 3 提交（纯快进，`git branch -f main origin/main` 即可；feat/2796 合并前需 rebase，落后 16）。
3. `nightly-verification` 与 `xiaobu-acceptance` cron 完全相同（`0 18 * * *`），同时段两个重 LLM workflow，建议错峰。
4. `--check-weak` 正则误报：`assert \w+ is None` 命中有效断言（test_chat.py:202-203），建议收窄。
5. 无断言函数：test_upload.py:50-60、test_main.py:83-94、test_mibao_advanced_summary.py:24。
6. E2E 视觉基线覆盖薄：仅 1 spec 2 快照；H5 tab 短词、mibao-minimize-layout:38 标题断言建议改 getByRole。
7. docs/git-workflow.md、docs/curtain-fabric-quote-rules.md 未被 INDEX 收录；AI-Agent.md 工具表含已禁用 RAG 工具。
8. danger_scan 只扫 `.yml` 不扫 `.yaml`；deploy_files 判定不含 `scripts/` 前缀。
9. deploy/docker-compose.yml 注释引用不存在的 `deploy/terraform/`；RUNNER_VERSION="2.337.0" 硬编码。
10. 根目录与 `.github/` 两份 growth-gate-result.json 内容不一致（均为旧产物，已 gitignore）；后续以 `./verify-all.sh gate` 实时输出为准。
11. smoke 测试 10/12 缺 case_ids（均为存量文件，warn 级）；存量 pages/ 测试 14 个缺 case_ids（warn 级）。
12. `@types/node: ^26.4.0`（admin-web）配运行时 node:20-alpine，建议降到 20.x 匹配。

---

## 4. 健康面（通过项，无需动作）

- 三把工具：`./verify-all.sh gate`（1 通过 0 失败）、`./contract-check.sh`（全部通过）、`./check-ui-regression.sh`（UI 无回退）、`./verify-all.sh quick`（6 通过 0 失败）。
- 生成物单一源：render_cases 复跑 diff 为空（166 用例 = eval_cases.py = verification md）；truths 267 真值/295 引用、0 冲突、1 显式缺口（MC-012）。
- E2E 视觉基线双平台：2 darwin + 2 linux 全部成对，无 "snapshot doesn't exist" 风险。
- E2E 选择器：34/34 spec 带 case_ids；导航均用 page.goto()，无裸短词点击 sidebar 违规。
- confirm 守卫机制：base_skill.py `_requires_confirmation` + 19 个工具标记 + read_only_actions 豁免 + 3 个守卫测试（test_destructive_tool_confirm_guard 等）。
- 依赖配对：Taro 4.2.1 全家桶一致且已最新；vitest 3.2.6/coverage-v8 3.2.6、jest 29/ts-jest 29、babel 7/ts-jest 均自洽；pip check 无 broken；lock 文件同步；node_modules 零跟踪。
- dependabot：mini-app 块 ignore 锁 @tarojs/* 防半套升级（记录 #2644/#2645/#2634 教训）。
- 安全：gitleaks + block-env-files 双门禁在位；非忽略文件无硬编码密钥；.gitignore 覆盖 .env/.pytest_cache/test-results 等。
- 已知坑修复在位：Taro dotenv defineConstants 显式替换（防 H5 白屏）；nginx 全栈 TZ: Asia/Shanghai。
- 脚本：dev-worktree.sh 与规范一致；cleanup_user_memories.py 默认 dry-run + 幂等。
- 文档索引：INDEX.md 覆盖全部 17 页无孤儿；docs/wiki 零断链；CONTRACT-LEDGER 抽查 7 项全部与代码一致（维护最及时的文档）。
- CI：20 个 workflow 无死引用、无重复触发；growth-gate 历史 blocker（enum_labels 等）全部已解决（重跑 0 blocker）。

---

## 5. 优先修复路线（建议顺序）

1. **PR #2818 Agent Eval 真实失败排查**（P1-1.1）——先本地复现 OR-010，确认是分支行为变更还是用例期望漂移；这是合并当前分支的阻塞项。
2. **文档三件套**（P1-1.6/1.7/1.8）：CHANGELOG 补齐 #2802~#2817 → gb47746 状态收口 → README 数字/新功能修正（改代码前按 AGENTS.md 走 TDD 流程，纯文档改动可直推 PR）。
3. **gate 组件测试缺口**（P1-1.3）：23 个子目录测试平铺 + 清理 qa-exemptions.yml 组件豁免（工程级，含测试搬迁）。
4. **Java 侧整组升级**（P1-1.4 + P2-2.11）：Spring Boot 3.5.x + springdoc 2.8+ + mybatis-plus 3.5.9+，一次 PR 内完成 + 全量单测 + contract-check。
5. **前端升级波次**（P1-1.5）：Next 15.3+（React 19 第二波），admin-web 全量回归。
6. **部署 fail-closed**（P1-1.2）：deploy.sh 万能码改为「缺失即报错」；顺手处理 .env 入库（P2-2.7）与 config 随 main 漂移（P2-2.8）。
7. **测试合规补漏**（P2-2.4/2.5/2.6）：7 个文件补 case_ids；human_handoff 加确认标记；aftersale skill 补 validate_input。
8. **Git 卫生**（P2-2.1/2.2/2.3）：处理 stash、清理 25 个已合并远程分支、main 快进、feat/2796 rebase。
9. **依赖防护**（P2-2.10）：dependabot pip 块补 langchain 组 ignore/整组策略；重建 venv（P2-2.12）。

---

## 6. 修复执行记录（2026-09-04，同批提交）

> 本报告落盘后按 §5 路线推进修复。PR #2818 于审计进行中已合并进 main（fb664358），OR-010 修复即基于 main 分支。

### 6.1 已完成并提交（本批）

| # | 修复项 | 内容 | 验证 |
|---|---|---|---|
| 1 | **OR-010 Agent Eval 真实失败**（P1-1.1） | 本地复现确认根因：评测输入「选1/2件」与真实 choice 卡交互协议不匹配（前端点击发送 label/value，非自然语言序号；商品按米计价而用例写「件」），LLM 反复 product_detail 追问、永不进入 order_create。改为显式描述「选散剪售卖，2.8米门幅」+「确认下单」+「2米」，重渲染生成物 | 本地 local_runner 单跑 OR-010 **1/1 通过 100%**；全量 smoke **8/9**（OR-010 ✅；PR-010 为预存偶发失败，见 6.2） |
| 2 | **CHANGELOG 补齐**（P1-1.6） | 补录 #2617~#2818 共 ~100 PR，按主题分 14 组（长期记忆/澄清护栏/GB 合规/时区/财务看板 RBAC/小布功能/入驻/安全加固/依赖工程等） | 生成物与 git log 对照无缺项 |
| 3 | **gb47746 文档收口**（P1-1.8） | GB-05 ⏳ → ✅（#2808 宣传真实性 / #2809 命名统一）；M3 服务端取价从「遗留增强」改为已落地（#2813）；§3.6/§4/§6 同步更新 | 文档状态与 git 合并历史一致 |
| 4 | **README 修正**（P1-1.7） | Taro 3.6→4.2.1（3 处）；工具数 31→33（3 处）；Service 23→26；workflows 16→19；功能概览补长期记忆/时区/图片澄清/上下文快照/服务端取价 | grep 全量复查无残留旧数字 |
| 5 | **测试文件 case_ids 补漏**（P2-2.4） | 7 个文件补声明：`test_internal_tool_execute_guard.py`(DF-008)、`test_tool_write_not_cached.py`(DF-008)、`sanitize-html.test.ts`(DF-010)、`JwtAuthenticationFilterTest.java`(DF-014,DF-016)、`floating-assistant.test.tsx`(UI-011)、`useResizableHeight.test.ts`(UI-006)、`chat-page.test.tsx`(UI-011) | 对应测试集全过 |
| 6 | **aftersale_create validate_input 前置**（P2-2.6） | `_VALIDATION_RULES` 补 `aftersale_create` 规则（order_id/ticket_type/reason 必填 + ticket_type/priority 枚举）；execute 新增枚举值检查；`customer_aftersales_skill` 工具列表补 validate_input；新增 4 个测试 | Red→Green 验证，受影响的 86 个测试全过 |
| 7 | **deploy.sh 万能码 fail-closed**（P1-1.2） | 两处「缺失 SMS_BYPASS_CODE 自动补 123456」改为「缺失即 exit 1 + 修复指引」（测试环境填 123456、生产置空禁用），注释标注 audit-2026-09 P1 | bash -n 语法通过 |
| 8 | **Git 卫生**（P2-2.1/2.2） | stash@{0} dashboard-pr-wip：blob 级对比确认全部改动已被 #2677 吸收 → drop；远程 25 个已合并分支（gh PR 全部 MERGED 核对）→ 删除，远程 64→26 | git branch -r 复查无残留 |

### 6.2 评估后暂不修改（含决策依据）

- **human_handoff 确认闸**（P2-2.5 建议 `requires_confirmation=True`）：**不改**。依据：①转人工是**用户显式请求**（"我要转人工"本身即确认意图），非 LLM 自发写操作；②#2812 刚验收的 E2E（CH-013/014）期望「我要转人工→SSE human_handoff→C 端横幅」直转链路，加闸会拦截（last_msg 非确认词）导致链路断裂；③GB 3.2 要求「转人工便捷入口、不层层隐藏」，加确认闸与之冲突。风险已由 prompt 铁律（EXAMPLES-customer_aftersales 转人工边界）+ allowed_roles=["customer"] 覆盖。
- **PR-010 偶发失败**（smoke 9 用例中 1 个 ⚠️ 80%）：本地与 CI 表现不一致（CI 缺 product_update(price=198)、本地缺 product_processing_item_manage(action=add)），属 7 轮长链 LLM 波动，非本批引入、非 required check，记录观察不修。
- **gate 组件测试缺口**（P1-1.3，23 个子目录测试 + 60 条豁免）：工程级测试搬迁，涉及 qa-exemptions 大改与全量 E2E 回归，**建议独立 PR** 处理，不在本批混合提交。
- **Java/前端整组升级**（P1-1.4/1.5）、**langchain 依赖防护**（P2-2.10）、**venv 重建**（P2-2.12）：工程级任务，独立排期。
- **admin-web `.env.*` 入库**（P2-2.7）、**deploy.sh 配置随 main 漂移**（P2-2.8）、**render_cases 域映射**（P2-2.9）、**CU-003 文档口径**（P2-2.13）、**端口/schema 口径**（P2-2.14）：留待后续批次，避免本批 diff 过大。
