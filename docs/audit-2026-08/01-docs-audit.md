# MIGAO 文档体系审计报告

> 审计日期：2026-08-28 ｜ 审计方式：只读（未修改任何项目文件）
> 范围：`CLAUDE.md`、`README.md`、`docs/wiki/`（16 篇）、`docs/architecture|deployment|design|api|testing/`、`.agents/skills/`、`.claude/skills|agents/`
> 验证手段：以 `backend/` 代码、`.env.example`、`.github/workflows/`、`deploy/`、`git ls-files`、`git log` 为事实源交叉核对
> 结论速览：A 事实矛盾 19 条 ｜ B 过期内容 7 条 ｜ C 重复内容 6 条 ｜ D 超长/混杂 2 条 ｜ E 生成物 1 条 ｜ F 索引 3 条

---

## A. 事实矛盾（同一事实多文档说法不一 / 与代码不符）

### A1. 【P0】LLM 视觉模型：CLAUDE.md 说 MiniMax M3，代码已换 DeepSeek V4 Flash Vision
- 位置：`CLAUDE.md:402`（技术栈表 "LLM | DeepSeek V4 Pro (主) + MiniMax M3 (视觉)"）
- 冲突方：`README.md:4,63`（"DeepSeek V4 Flash Vision"）、`docs/wiki/Home.md:24`、`docs/wiki/AI-Agent.md:83`（deepseek-v4-flash-vision-exp）
- 代码事实：`backend/ai-agent-service/app/config.py:35` 注释 "视觉多模态 LLM（图片识别）—— DeepSeek vision（2026-08 起替换 MiniMax M3）"；`config.py:39` `VISION_MODEL = "deepseek-v4-flash-vision-exp"`；`.env.example` `VISION_MODEL=deepseek-v4-flash-vision-exp`；`app/llm/factory.py:79` 同。
- 结论：**CLAUDE.md 的 "MiniMax M3" 已过期**（2026-08 已替换）；README/AI-Agent.md 与代码一致。`config.py` 中 `MINIMAX_MODEL`/`DASHSCOPE_MODEL` 仅是兼容别名。
- 建议动作：**重写** CLAUDE.md:402 为 "DeepSeek V4 Pro (主) + DeepSeek V4 Flash Vision (视觉)"。

### A2. 【P1】README 内部模型名自相矛盾：Qwen 3.7-Max / qwen-vl-plus
- 位置：`README.md:40`（mermaid "D --> H[DashScope Qwen 3.7-Max]"）、`README.md:78`（"图片识别（qwen-vl-plus）"）
- 冲突方：同文件 `README.md:63`（DeepSeek V4 Pro / V4 Flash Vision）；代码 `config.py:39,117`（deepseek-v4-*）。
- 建议动作：**重写** mermaid 与功能表，删 Qwen 引用，统一为 DeepSeek 模型。

### A3. 【P1】AI 工具数量：23 vs 30+ vs 实际 31
- 位置：`README.md:4,9,42,123,315`（"23 个业务工具/23 Tools"）；`docs/wiki/AI-Agent.md:19,40` 与 `docs/wiki/Home.md:3,33`（"30+ Tools"）
- 代码事实：`backend/ai-agent-service/app/tools/registry.py` 实际注册 31 个工具（tools 目录 33 个 py）。
- 建议动作：**重写**为统一数字 "31 个工具"（README 是主要过期方）。

### A4. 【P1】DB 表数量：39 vs 41 vs 正文清单 46
- 位置：`README.md:32,323`（"39 张表"）；`docs/wiki/Architecture.md:8,20`（39）；`docs/wiki/Database.md:5`（"39 张业务表"）但同文件 9-20 行列出的表名实际有 **46 个**
- 代码事实：`docs/sql/schema.sql` 有 **41** 张 `CREATE TABLE`。
- 建议动作：**重写** 三处为 "41 张表"，并让 Database.md 表清单与数量对账（清单 46 与声明 39 明显不符）。

### A5. 【P2】Controller / Service / Entity 数量：README 与 Home 互相矛盾且都过期
- 位置：`README.md:106-109`（"19 个 REST Controller / 21 个业务 Service / 31 个数据实体 / 31 个 Mapper"）；`docs/wiki/Home.md:32`（"22 Controllers, 23 Services, 42 Entities"）
- 代码事实：**26** Controller（@RestController）/ **23** Service（@Service）/ **44** Entity（@TableName）/ 44 Mapper。
- 建议动作：**重写** README 与 Home 为实际数字（26/23/44/44）。

### A6. 【P1】端口号：CLAUDE.md/README 的 8081/8001 vs 代码与 wiki 的 8080/8000
- 位置：`CLAUDE.md:245,327-340`（admin-api :8081、ai-agent :8001）；`README.md:191,214,227`（8081/8001）；`docs/wiki/Quick-Start.md:8,11`（8080/8000）；`docs/wiki/Home.md:10`、`docs/wiki/Architecture.md:7`（8080/8000）
- 代码事实：`backend/admin-api/src/main/resources/application.yml:2` `port: 8080`；`backend/ai-agent-service/app/config.py:20` `PORT = 8000`；`deploy/docker-compose.yml:61,84` admin-api `8080:8080`、ai-agent `8001:8000`；`frontend/admin-web/.env.development:7` `NEXT_PUBLIC_API_BASE_URL=http://localhost:8080`、`NEXT_PUBLIC_AI_API_BASE_URL=http://localhost:8001`
- 结论：ai-agent 的 8001 有 compose/前端 env 支撑（容器内 8000）；**admin-api 的 8081 没有任何配置支撑**（代码/环境/compose 全是 8080）。`docs/wiki/Troubleshooting.md:11` 只解释了 ai-agent 的覆盖，未提 admin-api。
- 建议动作：**重写** CLAUDE.md/README 本地端口为 8080/8000（或统一为 compose 的 8080/8001 并在 README 注明 compose 映射），并更新 Troubleshooting.md 的说明。

### A7. 【P1】Case Contract 条数：80 条/12 域 vs 实际 118 条/19 域
- 位置：`CLAUDE.md:561,576`（"80 条 × 12 域"、"smoke 9 / normal 45 / adversarial 26"）；`docs/wiki/Testing.md:29,38-41`（同）
- 代码事实：`.github/cases/` 下 **19 个域 yml**，用例总数 **118 条**（smoke 9 / normal 82 / adversarial 27）。
- 建议动作：**重写** CLAUDE.md 与 Testing.md 的条数/域数/tier 分配（118/19/9+82+27）。

### A8. 【P1】DB 迁移范围：Database.md "V1~V9" vs 实际 V1~V16
- 位置：`docs/wiki/Database.md:49`（"当前迁移: V1 ~ V9 + V20260604 ~ V20260614"）
- 冲突方：`docs/wiki/RBAC.md:14`（"V16"）、`docs/design/employee-permission-chain.md:15,76`（V16/V15）、`docs/design/session-management-redesign.md:252-253`（V12/V13）
- 代码事实：`backend/admin-api/src/main/resources/db/migration/` 存在 **V1~V16**（含 V10~V16）。
- 建议动作：**重写** Database.md:49 为 "V1~V16 + V2026xxxx"，并补 V10~V16 一句说明。

### A9. 【P0】CI workflow 名引用 vs 实际文件：backend-tests / frontend-tests / smoke-tests / e2e-tests 均不存在
- 位置：`CLAUDE.md:239`（"CI workflow `backend-tests.yml`…`frontend-tests.yml`…`smoke-tests.yml`…`e2e-tests.yml`"）
- 实际：`.github/workflows/` 只有 14 个文件（含 `ai-agent-tests.yml`、`smoke-test.yml`（单数）、`e2e-real.yml`）；`git log --diff-filter=D` 证实这四个文件**从未存在于 git 历史**。
- 建议动作：**重写** CLAUDE.md:239 为实际工作流（pr-check / ai-agent-tests / smoke-test / e2e-real）。

### A10. 【P0】CI-CD.md 工作流清单：声称 12 个、表列 13 行、含不存在的 e2e-web，漏 2 个实际文件
- 位置：`docs/wiki/CI-CD.md:3`（"12 个 GitHub Actions 工作流"）；表（5-19 行）含 `e2e-web`（**不存在**，实际为 `e2e-real.yml`）
- 实际：14 个 workflow；表中缺失 `agent-eval-adversarial.yml`、`ai-agent-tests.yml`；`smoke-test` 实际单数名 `smoke-test.yml`。
- 建议动作：**重写** CI-CD.md 工作流表（14 个 + 实际文件名），并把 `e2e-web` 改为 `e2e-real`。

### A11. 【P1】PostgreSQL 版本：技术栈说 PG 15，迁移章节说 "与 PostgreSQL 18 不兼容"
- 位置：`CLAUDE.md:496`、`docs/wiki/Database.md:42`（"Flyway 已移除（与 PostgreSQL 18 不兼容）"）
- 冲突方：`README.md:61,32`、`CLAUDE.md:400`、`docs/wiki/Home.md:22`、`deploy/docker-compose.yml:19`（`postgres:15-alpine`）全部为 PostgreSQL 15（历史 Terraform 还是 14）。
- 结论：项目并未使用 PG 18，"与 PG 18 不兼容"说法无依据、自相矛盾（可能是 Flyway 版本与 PG15/云 RDS 的兼容问题被误记）。
- 建议动作：**重写** 两处措辞为真实原因（如"与所用 PG 版本/Flyway 版本不兼容"）。

### A12. 【P1】认证方式与登录端点：api-reference 说 Cookie+账号密码，现状是 Bearer+短信、密码登录已禁用
- 位置：`docs/api/api-reference.md:13,1287`（"所有需要认证的接口通过 HttpOnly Cookie 携带 JWT（非 Authorization header）"）；`:118-129`（`POST /api/auth/account/login` 账号密码）；`docs/deployment/auth-and-deployment.md:105-106,135-140`（同）
- 现状：`frontend/admin-web/src/lib/request.ts` 请求拦截器加 `Authorization: Bearer`（同时 withCredentials）；`docs/wiki/RBAC.md:78` 管理后台登录为 `/api/auth/admin/login` 短信验证码、"密码登录已禁用 #375"。
- 备注：api-reference.md:45 说 `{"code":200,...}` 已废弃与代码 `dto/ApiResponse.java`（success/data/error/requestId）一致——这条是对的，但认证传输方式与登录端点已过期。
- 建议动作：**重写/标注历史**：api-reference.md 与 auth-and-deployment.md 均为 v8.0 无"历史参考"横幅，应按现状修订认证方式，或加横幅归入历史文档。

### A13. 【P2】测试工具表述：Development.md 说 TestContainers 已用、smoke 用 Playwright，与 CLAUDE.md 相反
- 位置：`docs/wiki/Development.md:35`（"JUnit 5 + MockMvc + TestContainers"）、`:38`（"E2E 冒烟 | Playwright (tests/smoke/)"）
- 冲突方：`CLAUDE.md:222`（"TestContainers 计划中"）、`CLAUDE.md:225,231` 与 `docs/wiki/Testing.md:7,25`（smoke 为 pytest，非 Playwright）。
- 建议动作：**重写** Development.md 为 "MockMvc + Mockito（TestContainers 计划中）"、smoke 用 pytest。

### A14. 【P2】README 目录统计过期：design "4 篇"、deployment "4 篇"
- 位置：`README.md:156`（"docs/design/ # 产品设计文档（4 篇）"）、`:157`（"docs/deployment/ # 部署指南（4 篇）"）
- 实际：design 目录 6 个 md（另加 logo-redesign/README.md），deployment 目录 8 个 md。
- 建议动作：**重写** 数字或去掉数量。

### A15. 【P2】README "15 个单元/集成测试" vs 实际 79 个
- 位置：`README.md:113`（"src/test/ # 15 个单元/集成测试"）
- 代码事实：`backend/admin-api/src/test` 共 79 个 Java 测试文件。
- 建议动作：**重写**。

### A16. 【P2】README Spring Boot 版本 3.3.5 vs pom 3.3.9
- 位置：`README.md:57`（"Boot 3.3.5"）；`backend/admin-api/pom.xml:10` `spring-boot-starter-parent 3.3.9`。
- 建议动作：**重写**为 3.3.9。

### A17. 【P2】smoke 测试文件数与 E2E spec 数过期
- 位置：`README.md:160`（"11 个测试文件"）、`docs/wiki/Testing.md:7`（"11 文件"）、`Testing.md:9`（"30 文件"）
- 实际：`tests/smoke/test_*.py` **12** 个；`tests/e2e/specs/` **36** 个 spec。
- 建议动作：**重写** 数字。

### A18. 【P2】OSS 双 Bucket 状态："待实施" vs 已实现
- 位置：`docs/deployment/oss-storage-strategy.md:5`（"状态：设计完成，待实施"）、`:414-417`（"⏳ 修改 admin-api 代码…"）
- 实际：`backend/admin-api/src/main/resources/application.yml` 含 `OSS_PERMANENT_BUCKET`/`OSS_TEMPORARY_BUCKET`；`tests/e2e/specs/storage/oss-dual-bucket.spec.ts` 存在。
- 建议动作：**重写** 状态为"已实施"，补链接到 E2E 与 application.yml。

### A19. 【P2】README Docker Compose 本地模式与 CLAUDE.md"云 dev"铁律互斥
- 位置：`README.md:176-195`（方式一：docker-compose 起本地 PostgreSQL/Redis 全栈）；`CLAUDE.md:243`（"铁律：本地只启动 3 个组件，DB/Redis/中间件全部用云 dev"）
- 建议动作：**保留** compose 但标注"离线/首次可选"，明确默认遵循云 dev 铁律，避免 AI 拿到两种互斥指令。

---

## B. 过期内容（标注弃用/残留/不再存在）

### B1. 【P1】四份 v8.0 文档无"历史参考"横幅，内容与现状冲突
- 位置：`docs/architecture/multi-tenant-multi-platform.md`（:3 v8.0；含旧包路径 `com/ai_customer_service`（:288）、账号密码登录（:410））；`docs/deployment/auth-and-deployment.md`（:34 旧包路径、:135 账号密码登录）；`docs/api/api-reference.md`（:13 Cookie 认证、:121 账号密码登录）；`docs/design/product-page-review.md`（v8.0 review 稿）
- 对比：`docs/architecture/architecture.md`、`rag-architecture.md`、`production-ai-architecture.md`、`docs/design/skill-spec.md`、`docs/deployment/deployment-aliyun.md`、`admin-web-sae-migration.md`、`deployment-checklist.md` 均已有"历史参考"横幅。
- 建议动作：**合并/标注**：给上述 4 份加"历史参考（v8.0，2026-04）"横幅并链接到 wiki 现役页；或归档到 `docs/legacy/`。

### B2. 【P2】architecture.md 历史文档内混入 2026-08-14 SWAS 注释 + 遗留"阿里云云效"CI
- 位置：`docs/architecture/architecture.md:638,658,690,695`（SWAS 2026-08-14 注释）、`:768`（"CI/CD | 阿里云云效"——实际为 GitHub Actions）
- 建议动作：**重写/清理**：要么纯历史（删除 SWAS 补丁注释、标注云效为当时事实），要么整体指向现役 wiki。

### B3. 【P2】Terraform/SAE 遗留：已正确标注，但 oss-bucket-creation-guide.md 仍以 Terraform 为主流程且状态为"新增"
- 位置：`docs/deployment/oss-bucket-creation-guide.md:5`（"状态：新增"）、`:42-73`（方式一 Terraform 全流程）
- 现状：wiki/Deployment.md:70-72 与 CLAUDE.md:418 已声明 Terraform 历史遗留；本文件顶部无 SWAS 时代提示。
- 建议动作：**保留**但加横幅："Terraform 为历史遗留，仅供参考；当前环境变量在 SWAS `.env.*` 配置"。

### B4. 【P2】README/文档引用已不存在的目录或文件（walkthrough/）
- 位置：`docs/wiki/DEV-FLOW.md:5,61`、`.agents/skills/migao-dev-flow/SKILL.md:66`（引用 `walkthrough/RETROSPECTIVE.md`）
- 事实：`walkthrough/` 目录**不存在**。
- 建议动作：**删除**该引用或补回复盘文档。

### B5. 【P2】生成物头部"单一源"描述与 CLAUDE.md 不一致
- 位置：`docs/testing/mibao-verification-cases.md:4`（"单一源：`ershen/seed/migao/cases/`（部署副本 `.github/cases/`）"）vs `CLAUDE.md:561`（"行为用例只存一份 `.github/cases/<domain>.yml`"）
- 事实：仓库内唯一源是 `.github/cases/`；`ershen/` 不在本仓库。
- 建议动作：**重写** 文件头为 `.github/cases/`（随 render_cases.py 同步更新模板头）。

### B6. 【P2】skills-lock.json 缺 migao-dev-flow，且 .agents/ 整体被 gitignore
- 位置：`skills-lock.json`（只锁了 frontend-design/miniapp-develop/skill-vetter 三个第三方技能）；`.gitignore:105`（`.agents/`）
- 影响：`migao-dev-flow` 是自研核心流程技能却无版本锁定记录；且 DEV-FLOW.md:4 声称"DSH 技能机器本地不进 git"——当前确实不进 git，但团队共享靠 `docs/wiki/DEV-FLOW.md` 副本，存在漂移风险（副本内容已与 SKILL.md 一致，但无同步校验）。
- 建议动作：**保留**现状但补：把 migao-dev-flow 纳入 skills-lock.json；或加一个"副本一致性"检查脚本。

### B7. 【P2】产品文档遗留："客服工作台小程序"独立小程序等设计仍被引用为现状
- 位置：`docs/design/agent-workspace-design.md:880-889`（独立小程序、PC H5 部署）；实际 admin-web 内已实现坐席工作台（Frontend.md:9 "(dashboard) … 聊天坐席"）
- 建议动作：**标注历史**或注明"已由 admin-web 聊天坐席页替代"。

---

## C. 重复内容（同一信息 ≥2 处）

### C1. 【P1】TDD/CP 检查点与验证命令在 CLAUDE.md 内部重复 3 遍 + 外部 2 处
- 位置：`CLAUDE.md:137-167`（CP-5/CP-6 命令）≈ `CLAUDE.md:320-383`（"完整验证命令清单"）≈ `CLAUDE.md:449-490`（"构建与验证命令"）；另 `docs/wiki/Development.md:3-17`、`docs/wiki/Testing.md:76-93` 重复
- 建议动作：**合并/删除**：CLAUDE.md 保留"7 检查点摘要 + 指向"，删除 320-383 命令清单块；测试命令单一事实源放 `docs/wiki/Testing.md`（或 `.claude/skills/tdd-iron-law.md`）。

### C2. 【P2】分支/Commit 规范三处重复
- 位置：`CLAUDE.md:429-447`、`docs/wiki/Development.md:19-29`、`README.md:329-345`
- 建议动作：**合并**：保留 README（对外）与 Development.md（对内）一致内容，CLAUDE.md 只写一行指向。

### C3. 【P2】部署"三工作流 + SWAS"表四处重复
- 位置：`CLAUDE.md:543-557`、`docs/wiki/Deployment.md:5-15`、`docs/wiki/CI-CD.md:7-19`、`README.md:269-277`
- 建议动作：**合并**：单一事实源 `docs/wiki/Deployment.md`，其余指向。

### C4. 【P2】Case Contract 说明两处重复
- 位置：`CLAUDE.md:559-583` 与 `docs/wiki/Testing.md:27-43`（tier 表、生成物清单、校验命令几乎一致）
- 建议动作：**合并**：保留 CLAUDE.md 摘要（铁律 + 闭环 6 环节），tier/命令放 Testing.md。

### C5. 【P2】migao-dev-flow 技能与 DEV-FLOW.md 双副本
- 位置：`.agents/skills/migao-dev-flow/SKILL.md` 与 `docs/wiki/DEV-FLOW.md`（后者 :3 声明为同步副本）
- 建议动作：**保留**双份但建立单一事实源 + 同步机制（或在 DEV-FLOW.md 加"上次同步 hash"），防止未来漂移；同时给 SKILL.md 的硬编码本机路径 `:20`（`/Users/guangzhen.zk/ai native/migao`）改为相对仓库根提示。

### C6. 【P2】仓库内 .agents/skills 混入 3 个与本项目无关的第三方通用技能
- 位置：`.agents/skills/frontend-design/SKILL.md`（英文、通用设计）、`.agents/skills/skill-vetter/SKILL.md`（英文、ClawdHub/OpenClaw 术语，与本项目工具链无关）、`.agents/skills/miniapp-develop/SKILL.md`（通用小程序开发，含支付宝/抖音/百度/uni-app，本项目仅 Taro+微信）
- 事实：`skills-lock.json` 显示三者来自 modelscope.cn；与项目文档体系（CLAUDE.md 声称的 Matt Pocock 技能体系）是两套来源。
- 建议动作：**保留/删除**：若确要使用则说明用途并纳入 lock；否则从项目技能目录移出，避免 AI 加载无关技能（尤其 skill-vetter 面向 OpenClaw 生态）。

---

## D. 超长 / 混杂文件

### D1. 【P1】CLAUDE.md（624 行）揉合 9+ 个关注点
- 内容清单：① GitHub 操作规范 ② AI-TDD 铁律+7 检查点+违规后果+测试分层+铁律摘要（约 32-288 行，占半篇）③ 米宝 Skill/Tool 标准 ④ 完整验证命令清单（320-383）⑤ 项目概述/技术栈/目录 ⑥ 分支/Commit ⑦ 构建命令（449-490）⑧ MigrationRunner ⑨ CI/CD ⑩ Case Contract ⑪ Skill 使用规范 ⑫ 已安装插件
- 建议动作：**拆分**为：
  - `CLAUDE.md` 只留：项目概述、技术栈一行、入口指向（wiki INDEX）、"铁律摘要 + 指向 tdd-iron-law.md"；
  - TDD 检查点 → `.claude/skills/tdd-iron-law.md`（已存在，作单一事实源）；
  - 测试命令 → `docs/wiki/Testing.md`；部署 → `docs/wiki/CI-CD.md`/`Deployment.md`；GitHub 规范 → `docs/wiki/Development.md`；MigrationRunner → `docs/wiki/Database.md`；Skill/Tool 标准 → `docs/wiki/agent-design-standard.md`；
  - 删除 320-383 与 449-490 两块重复命令。

### D2. 【P2】api-reference.md（1297 行）与 rag-architecture.md（1500+ 行）体量过大且含大量历史代码示例
- 位置：`docs/api/api-reference.md`（v8.0 端点 + Cookie 认证描述）；`docs/architecture/rag-architecture.md`（已标历史，但正文约 1500 行 Python 示例）
- 建议动作：**合并/压缩**：api-reference.md 重写为当前端点精简版（或指向 SpringDoc OpenAPI：pom 已含 springdoc）；rag-architecture.md 压缩为"设计要点 + 指向代码"。

---

## E. 已提交的生成物

### E1. 【P1】生成物仍被 git 跟踪，且无"源 vs 生成物"一致性门禁
- 位置：`docs/testing/mibao-verification-cases.md`、`tests/agent_eval/eval_cases.py`（`git ls-files` 确认两者均在版本库中）
- 声明：`CLAUDE.md:566` 与 `docs/wiki/Testing.md:29-33` 称两者为 `render_cases.py` 生成物"禁止手改"
- 风险：生成物被提交但 `.github/workflows/pr-check.yml` 只有 `case-truth-check`（引用完整性），**没有"重渲染后 diff 为空"的校验**——手改生成物不会被发现；且生成物头部单一源描述（ershen/…）与实际源（.github/cases/）不一致（见 B5）。
- 建议动作：**保留**提交（人读文档 + CI 运行需要），但：
  1. 在 pr-check 增加 `render_cases.py && git diff --exit-code` job；
  2. 统一生成物头部单一源为 `.github/cases/`。

---

## F. 索引质量

### F1. 【P0】docs/wiki/INDEX.md 未覆盖 2 个页面：DEV-FLOW.md、CONTRACT-LEDGER.md
- 位置：`docs/wiki/INDEX.md`（13 个场景行）；`docs/wiki/` 实际 15 个内容页
- 影响：`CONTRACT-LEDGER.md` 被 DEV-FLOW.md/migao-dev-flow 技能声明为"并行开工前必读"，`DEV-FLOW.md` 为技能同步副本，均未入索引，AI 按 INDEX 导航时发现不了它们。
- 建议动作：**重写** INDEX.md 补两行（DEV-FLOW → 开发提效流程；CONTRACT-LEDGER → 并行开发契约清单）。

### F2. 【P0】死链：Troubleshooting.md 引用不存在的技能文件
- 位置：`docs/wiki/Troubleshooting.md:79`（"详见 … [SLS 日志查询 Skill](../../.claude/skills/aliyun-sls-log-query.md)"）
- 事实：`.claude/skills/` 只有 `tdd-iron-law.md`（`.gitignore:109` 忽略其余）。`aliyun-sls-log-query.md` **不存在**。
- 建议动作：**删除**该链接（或补回该技能文件）。

### F3. 【P2】次要死链/弱链
- `docs/wiki/DEV-FLOW.md:61`、`.agents/skills/migao-dev-flow/SKILL.md:66` → `walkthrough/RETROSPECTIVE.md` 不存在（并入 B4）。
- 其余抽查（wiki 内互链、docs/deployment/*、tests/README.md、docs/testing/mibao-verification-cases.md）目标均存在，无死链。
- 建议动作：删除或补回。

---

## 附录：本次审计的关键代码事实核对表

| 事实项 | 文档声称 | 代码/仓库实际 | 结论 |
|---|---|---|---|
| 视觉模型 | CLAUDE.md：MiniMax M3 | config.py:39 `deepseek-v4-flash-vision-exp`（2026-08 替换） | CLAUDE.md 过期 |
| 主模型 | README：DeepSeek V4 Pro | config.py:117 `deepseek-v4-pro` | 一致 |
| 工具数 | 23 / 30+ | registry 注册 31 | 23 过期 |
| 表数 | 39 | schema.sql 41 | 39 过期 |
| Controller/Service/Entity | 19/21/31（README）、22/23/42（Home） | 26/23/44 | 双过期 |
| admin-api 测试 | 15 | 79 | 过期 |
| smoke 测试文件 | 11 | 12 | 过期 |
| E2E specs | 30 | 36 | 过期 |
| Case 条数 | 80（9+45+26） | 118（9+82+27） | 过期 |
| 迁移版本 | V1~V9 | V1~V16 | 过期 |
| PG 版本 | 15 ／ "PG18 不兼容" | compose PG15 | "PG18" 无依据 |
| admin-api 端口 | 8081 | 8080（yml/compose/env） | 8081 无支撑 |
| ai-agent 端口 | 8001（本地） | 默认 8000，compose 宿主 8001 | 部分有支撑 |
| CI workflows | backend-tests/frontend-tests/smoke-tests/e2e-tests | 均不存在（git 历史也无）；实际 14 个 | 引用过期 |
| CI-CD 工作流数 | 12（表含 e2e-web） | 14，无 e2e-web | 过期 |
| 响应信封 | {"code":200} 已废弃 | ApiResponse {success,data,error,requestId} | 文档说法正确 |
| 认证传输 | api-reference：Cookie only | request.ts 用 Bearer + withCredentials | api-reference 过期 |
| 生成物跟踪 | 声明"生成物禁止手改" | 两生成物均在 git 中；无 diff 门禁 | 缺校验 |
| OSS 双 Bucket | "待实施" | 代码已实现 + E2E spec | 状态过期 |
| Boot 版本 | 3.3.5 | 3.3.9 | 过期 |
| .agents/skills | CLAUDE.md 声称 Matt Pocock 体系 | 实际 lock 记录 modelscope 3 个第三方技能 | 两套体系并存 |

---

## 优先级汇总

- **P0（4 条）**：A1 视觉模型名、A9/A10 CI workflow 名、A7 Case 条数、F1/F2 索引缺失与死链
- **P1（8 条）**：A4 表数、A6 端口、A8 迁移版本、A11 PG 版本、A12 认证方式、C1 TDD 重复、D1 CLAUDE.md 拆分、E1 生成物门禁
- **P2（其余）**：各类统计数字过期、文档数、历史横幅补齐、技能目录清理、OSS 状态等
