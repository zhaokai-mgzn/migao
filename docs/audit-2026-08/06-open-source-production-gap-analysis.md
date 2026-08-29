# MIGAO 开源治理与企业生产化差距分析报告（06）

> 审计日期：2026-08-29 ｜ 审计方式：**只读**（未修改任何业务文件）
> 方法：5 个并行只读子审计（开源治理 / CI-CD 工程 / 安全合规 / 生产运维 / AI 生产化）+ 主线程独立核验（gh api 实测、git 历史、密钥扫描、部署脚本与 compose 全文）+ 与存量审计 `01-docs-audit.md` / `02-ci-audit.md` / `03-tests-audit.md` / `04` / `05` 交叉比对。
> 结论速览：**工程内功（CI 门禁/测试/评测/AI 可靠性）显著超出同类中小开源项目；但"开源社区外壳"（治理文件/版本发布/README 信任状）与"企业生产要件"（可回滚/可观测/安全左移/成本治理/合规）两个方向各有 P0 缺口。** 补齐顺序建议：先"开源外壳"（1~2 周可完成，纯增量），再"生产安全 P0"，再"发布/可观测性/成本治理"（需决策与较大投入）。

## 决策记录（2026-08-29 产品负责人拍板）

| # | 决策 | 对本报告的影响 |
|---|---|---|
| D1 | **RAG 在 POC 阶段不开放**（不恢复 DashVector 知识库） | 2.4-A1 处置改为"全面下线并标注文档"，删除"恢复"选项；README/wiki/rag-architecture.md 的 RAG 描述需按现状修订，杜绝文档失实 |
| D2 | **SMS 万能码 123456 在 POC 阶段保留**（后续对接真实 SMS 服务） | 2.2-S1 处置改为"接受 + 显式警告 + 技术债跟踪"；**不再**要求部署脚本强制置空；对接真实 SMS 的验收标准必须含"移除 bypass 逻辑" |
| D3 | **许可证保持 MIT**（本审计决定，见 2.1-G4） | 补 THIRD_PARTY.md + SPDX 头；Apache-2.0 升级列入 v1.0 发布前复审项 |

---

## 0. 评估框架：两个合格线

| 合格线 | 定义 | 检查来源 |
|---|---|---|
| **A. 高标准开源** | GitHub 社区标准（README/License/贡献/行为准则/安全披露/版本发布）+ 项目成熟度信号（活跃度、可追溯性、制品溯源） | GitHub Community Standards、CII Best Practices、开源社区最佳实践 |
| **B. 企业可复制生产** | 企业选型尽职调查五问：① 许可证与合规 ② 安全基线 ③ 维护活跃度与版本 ④ 可运维性（回滚/观测/备份）⑤ 成本与数据治理 | 开源软件企业采用尽职调查框架 |

**现状定位**：A 线 "外壳" 缺位但底子好；B 线 "内功" 强但关键生产要件（回滚、观测、成本、合规）未闭环。**两个方向的 P0 建议并行推进，总工作量约 2 个月（1 人全职 + 按需决策）**。

---

## 1. 已具备 —— 无需重建的差异化强项（带证据）

| 维度 | 现状 | 证据 |
|---|---|---|
| **PR 门禁密度** | 8 个检查 job + 失败自动打标/清标；tsc、ESLint 均在 CI 执行 | `.github/workflows/pr-check.yml`（block-env / admin-api-test / admin-web-test / e2e-quality-gate / ui-regression-check / qa-growth-gate / case-truth-check / agent-eval-smoke） |
| **数据驱动质量门禁** | QA Growth Gate：tech-stack.yml 单一规则源 + 豁免 + 弱断言检测 + case_ids 用例追溯，fail-closed | `.github/growth_gate.py`；`verify-all.sh` gate 已与 CI 参数对齐（8-29 修复） |
| **行为用例单一源** | `.github/cases/` 123 条（smoke 10 / normal 86 / adversarial 27），生成物重渲染 diff 阻塞 | `pr-check.yml:328-344`（case-truth-check）；`.github/render_cases.py` |
| **评测体系** | PR 门禁跑 smoke tier 真实 LLM；对抗用例每周追踪；夜间回归；军师双验收闭环 | `agent-eval.yml` / `agent-eval-adversarial.yml` / `nightly-verification.yml` / `junshi-*` |
| **AI 可靠性工程** | LLM 60s 超时 + 收敛式重试（指数退避+jitter）+ 三态熔断 + 降级兜底 + 工具 30s 超时 + SSE 心跳/断连清理 | `app/llm/retry_policy.py`、`app/core/circuit_breaker.py`、`app/core/fallback.py`、`app/api/chat.py:502-601` |
| **AI 工具安全分层** | destructive 工具代码层 confirm 兜底 + 写前 validate_input + 内部 API 仅只读工具 + JWT RS256 fail-fast | `app/graph/skills/base_skill.py:520-561`、`app/tools/base.py`、`app/api/internal.py:67-80`、`app/utils/auth.py` |
| **部署模型** | CI 构建镜像推 ACR → SWAS 仅 pull+up（不做源码构建）；flock 并发锁；磁盘自愈；部署后健康检查 + P0 冒烟 | `deploy/swas/deploy.sh`、`deploy/scripts/swas-deploy-ci.sh`、`smoke-test.yml` |
| **安全基线部分** | .env 提交门禁、JWT 密钥历史泄漏已轮换（67668e17 初始提交含旧私钥，现 key 已更换）、admin-api/ai-agent 非 root 容器、上传 magic-number 校验 | `pr-check.yml:16-34`、`git log` 67668e17、各 Dockerfile |
| **文档与自审计文化** | wiki 16 页索引、AGENTS.md/CLAUDE.md 研发铁律、存量 5 份审计文档（含 19 条文档矛盾清单） | `docs/wiki/INDEX.md`、`docs/audit-2026-08/01~05` |

---

## 2. P0 —— 不补就够不上任何一条合格线

### 2.1 开源治理外壳缺失（与"高标准开源"差距最大的一项）

| # | 缺口 | 现状（证据） | 建议 |
|---|---|---|---|
| G1 | **社区健康文件全缺** | 根目录无 CONTRIBUTING.md / SECURITY.md / CODE_OF_CONDUCT.md / GOVERNANCE.md / SUPPORT.md / CHANGELOG.md；`.github/` 无 CODEOWNERS、dependabot.yml、FUNDING.yml、ISSUE_TEMPLATE/config.yml | 全部为增量文件，**第 1 周即可完成**。SECURITY.md 提供私有漏洞披露通道（GitHub Security Advisories）；CONTRIBUTING.md 外部贡献者入口（含 QA Growth Gate / case_ids 门禁说明） |
| G2 | **零版本发布体系** | `git tag`=0、GitHub Releases=0、无 semver 声明、无 CHANGELOG；镜像 tag 为时间戳（`v$(date)`）且服务器恒用 `latest`；buildx 显式 `--provenance=false`（`deploy-ai-agent-service.yml:86`） | 建立 semver：`release.yml` 工作流（Conventional Commits 推导/手动触发 → tag `vX.Y.Z` → Release notes）；镜像 tag 改 git SHA 不可变 tag；启 provenance/SBOM |
| G3 | **README 信任状不合格** | 无 badges/截图/FAQ/支持渠道/路线图/贡献者；与 docs 存在 **19 处事实矛盾**（同文 Qwen vs DeepSeek、23 vs 31 工具、19 vs 26 Controller、Boot 3.3.5 vs 3.3.9 等，见 01-docs-audit）；**GitHub 仓库 description 为空**（gh api 实测） | 按 01-docs-audit 核对表整体修订 README + 顶部 4 枚 badge（CI/coverage/license/version）+ 补 2-3 张截图；补仓库 description |
| G4 | **许可证对企业法务不充分**（**决策 D3：保持 MIT**） | MIT 无专利授权条款；无 NOTICE.md / THIRD_PARTY.md；无依赖许可证审计；源码无 SPDX 头 | **决定：保持 MIT**——① POC/开源早期最大化传播（MIT 义务最少）；② 本项目核心价值在应用层业务逻辑，专利风险低，Apache-2.0 的专利授权收益有限；③ 合规补强走"轻量路线"：补 THIRD_PARTY.md（依赖许可证清单，Java pom + Python requirements + npm lock 三端）+ 源码文件 SPDX 头（`// SPDX-License-Identifier: MIT`）；④ **升级 Apache-2.0 列入 v1.0 正式发布前复审项**（届时若有外部贡献者，需先建立 CLA 或征得全部贡献者同意再切换） |
| G5 | **社区牵引为零** | 0 star / 0 fork；main 历史被压缩重写（68 提交/3 天/单作者，外部无法回溯 8-27 前）；无 ADOPTERS / roadmap / 公开里程碑 | ROADMAP.md（把 README 进度表升级为对外路线图）；ADOPTERS.md；保持 git 历史完整（禁止再压缩）；issue labels 成文化 |

### 2.2 生产安全 P0（证据已复核）

| # | 风险 | 证据 | 处置 |
|---|---|---|---|
| S1 | **SMS 万能验证码 123456 生效**（**决策 D2：POC 阶段接受，记技术债**） | `application.yml:134` `bypass-code: ${SMS_BYPASS_CODE:123456}`——默认值即 123456，**生产 env 即使不配置也会生效**；任意手机号可登录（含 super_admin）。当前未接真实短信，冒烟测试依赖该机制 | ① 保留现状（尊重决策）；② SmsService 增加"bypass 生效时"警告日志（一次）；③ 部署脚本打印 POC 提示（可选）；④ **建技术债 Issue**：验收标准 = 对接真实 SMS 后移除 bypass 并补测试 |
| S2 | **DEBUG=true 无 token 直通租户 1** | `backend/ai-agent-service/.env.example:10` `DEBUG=true`；`app/config.py:140` DEBUG 绕过安全校验；安全审计确认 `auth.py:262-273` DEBUG 下无 token 进入 admin 会话 | `.env.example` 默认改 false；生产部署脚本强制校验 DEBUG=false；config.py 加警告日志 |
| S3 | **历史提交含 JWT 私钥** | `git log` 67668e17 Initial commit 曾提交 `rsa/private.pem`（已轮换：现 key md5 与旧 key 不同） | 已缓解；如需彻底清除可 `git filter-repo` 重写历史（会破坏历史完整性，与 G5 冲突，建议保留+文档说明轮换时间点） |
| S4 | **"5 层隔离"声明失实** | `docs/wiki/Architecture.md:11-17` 宣称含 "PG RLS 行级安全"，但 migration V1-V17 **无任何 RLS SQL**（隔离实为 MyBatis 租户拦截器 fail-closed）；DashVector 已禁用（见 A1） | 修订文档为事实（"MyBatis 租户拦截器 + JWT 派生 tenant_id"）；如需纵深防御再评估补 RLS |
| S5 | **日志 PII 明文** | `base_skill.py:611,616` `[tool-exec]` 记录 `args=json.dumps(tool_args)[:300/500]`，order_create/customer_manage 参数含姓名/手机号/地址明文；记忆提取 `extractor.py:101` 存原始消息前 100 字 | 工具参数日志统一走 `LogSanitizer.filter_params`；消息日志截断 + 脱敏 |

### 2.3 发布与运维 P0

| # | 缺口 | 证据 | 建议 |
|---|---|---|---|
| O1 | **部署不可回滚** | `deploy.sh:26` 默认 `latest`；CI 推的时间戳 tag 无消费者（`deploy-ai-agent-service.yml:93` IMAGE_FULL 写入 env 后未用）；健康检查失败仅 exit 1 不自动回退；`deploy.sh:61` `docker image prune -f` 会清掉上一版镜像；回滚文档仍是 SAE 遗留（`deployment-checklist.md:229-238` 用 `aliyun sae`） | git SHA 不可变 tag + deploy.sh 支持指定 tag + 健康检查失败自动回退前一版本 + 补 SWAS 时代回滚 runbook |
| O2 | **零可观测性** | 日志仅容器 stdout（人类可读文本非 JSON）；admin-api 无 request id（Java 侧无 MDC/`X-Request-ID`）→ 跨服务无法串联；actuator 仅 health/info/metrics 无 prometheus；SLS/ARMS 采集配置全是 SAE 遗留；14 个工作流无失败通知渠道 | SWAS 侧接 SLS Logtail（JSON 日志 + 统一 trace id）；云监控建 CPU/内存/磁盘/5xx/健康检查告警并触达钉钉/短信；workflow 失败通知 |
| O3 | **无资源限制 + 单点无降级** | `deploy/swas/docker-compose.yml` 无 mem_limit/cpus；admin-api `-XX:MaxRAMPercentage=75.0` 容器无限制时按**宿主机**内存算堆；单台 SWAS 承载全部服务 | compose 设 mem_limit/cpus（如 admin-api 1.5G/1c、ai-agent 1G/1c、admin-web 512M）；文档化 SWAS 规格与容量基线 |
| O4 | **零停机缺失** | `deploy.sh:55-57` 直接 `up -d --no-deps` 重建 + `docker compose restart nginx`（stop+start 非 reload）→ SSE/长连接硬断流、502 窗口 | nginx 改 `-s reload`；服务依赖等待；评估 nginx 双 upstream 权重金丝雀 |

### 2.4 AI 生产化 P0（证据已复核）

| # | 缺口 | 证据 | 建议 |
|---|---|---|---|
| A1 | **RAG 已禁用，文档失实**（**决策 D1：POC 阶段不开放**） | `registry.py:390,406,426,443` 四处 `[RAG 禁用]`；`customer_knowledge_skill.py:12-39` 改走 LLM 通用知识并附免责；`internal.py:149,307` 返回 `RAG_DISABLED`；`rag-architecture.md` 声称的 DashVector 租户隔离/混合检索/Reranker 全部落空 | 按"下线"处理：① `rag-architecture.md`、README、docs/wiki 的 RAG 描述加"已下线/历史"标注并改述现状（知识库问答走 LLM 通用知识）；② `registry.py` 的 `[RAG 禁用]` 注释链到本决策记录；③ 建 Issue 追踪"RAG 恢复"作为 POC 后候选（若重新开放需重接 DashVector 租户隔离 + 注入防护 + 命中率指标） |
| A2 | **无租户级 LLM 配额/成本硬阻断** | 唯一限流是进程内 per-session（重启清零）；`cost_tracker.check_budget` 超预算**仅告警不阻断**；defense.yml DF-004 自述"速率限制未实现"；Redis `ratelimit:` 前缀无消费者 | Redis 分布式限流（per-tenant/per-user）+ per-tenant 月度预算硬阻断（429/降级话术）+ 成本落库供计费 |
| A3 | **PII 进入长期记忆且未接线** | `extractor.py:16-34` 提取"订单号、**手机号、地址**"写入 `user_memories` 表；`format_for_prompt` 全仓无调用点（收集却从不使用）；无保留期/删除 API | 停用提取或加 PII 字段黑名单；补 90 天保留期 + 用户删除 API；接线或彻底下线 |

### 2.5 CI 安全左移 P0

| # | 缺口 | 证据 | 建议 |
|---|---|---|---|
| C1 | **无 secret 扫描/SAST/镜像扫描/Dependabot** | 16 个 workflow 无 gitleaks/detect-secrets/trivy/snyk/semgrep/bandit；`npm audit` 为 `continue-on-error: true` 非阻塞（`pr-check.yml:103-106`）；无 dependabot.yml；actions 全部浮点 major tag 未 SHA pin | gitleaks PR 门禁（block）+ trivy 扫镜像（deploy 前 block critical）+ dependabot.yml（Java/Python/npm/GHA）+ actions SHA pin |
| C2 | **admin-web 镜像以 root 运行** | `frontend/admin-web/Dockerfile` 无 USER（另两个服务已有非 root）；单阶段构建、无 HEALTHCHECK | 多阶段（node build → 运行）+ `USER node` + HEALTHCHECK；三处基础镜像 pin digest；统一 buildx+gha cache |
| C3 | **覆盖率高门槛形同虚设** | growth_gate G2 已实现但**任何 workflow 未接线**（无 `--coverage-threshold/--coverage-report`）；pom 无 `jacoco:check`；pytest 无 `--cov-fail-under`；vitest 无 thresholds | 三端加硬阈值（先 60 再逐模块提高），pr-check 接线 G2 |

---

## 3. P1 —— 显著提升企业信任与可维护性

| 维度 | 项 | 要点 |
|---|---|---|
| 工程 | Python 依赖不可复现 | `tests/smoke/requirements.txt` 全部 `>=`；requirements.txt 有 `>=`（pytest-timeout、dashscope）；无锁文件 → pip-tools/uv 锁文件 + 全 pin；Dockerfile 去 `--trusted-host` |
| 工程 | deploy-frontend 健壮性 | 无 concurrency group；无 post-deploy 探测（NEXT_PUBLIC_* 配错无信号）；e2e-real 上传无用 artifact |
| 工程 | contract-check 未入 CI | 仅文档引用，无 workflow 调用，"三把工具与 CI 同规则"声明对 contract-check 不成立 → verify-all 加 contracts mode + pr-check 独立 job |
| 工程 | 对抗用例不进回归 | DF-006 注入/DF-007 越权明确失败且"只追踪不阻塞"（`agent-eval-adversarial.yml`）→ 代码层已兜底的用例升 nightly 并设阈值 |
| 安全 | 登录无限流锁定 / 上传路径穿越 / OSS 删除 IDOR / ServiceToken 租户自报 / prod profile 漂移 / 审计不落库 / 无隐私政策 | 均为安全子审计坐实项；需逐一修复 + 补隐私政策页（个保法） |
| 运维 | 备份无 IaC 无演练 | RDS 备份仅 SAE 时代示例命令；OSS 永久桶无版本控制 → terraform 补策略 + 季度恢复演练 |
| 运维 | 配置服务器侧无版本化无轮换 | `.env.*` 仅存服务器；ACR 凭据明文落盘 `.env.registry`；JWT/DB/Redis 密钥全静态 → env 模板入仓 + KMS/SOPS + 轮换 runbook |
| 运维 | TLS 证书续期不在仓 | nginx 挂载 letsencrypt 但仓内无 certbot/renew 任务 → compose 加 certbot 容器或文档化 systemd timer |
| AI | 语义缓存缺失 / SSE 断连白烧 token / 成本追踪进程内存态 / 评测单租户（固定 `X-Tenant-Id: 1`）/ 无链路追踪 | 见 AI 子审计 G5-G9 全表 |
| 开源 | 许可证补强（若不上 Apache-2.0）/ README 截图与 FAQ / CODEOWNERS / DCO 或 CLA | 见治理子审计 P1 表 |

---

## 4. P2 —— 可选优化（保持高标准时再投入）

- lint/format 门禁补齐（Java spotless / Python ruff / 前端 prettier --check 入 CI）
- 文档漂移治理（CI-CD.md 14 vs 实际 16 workflow、cases 数 117 vs 123、CLAUDE.md 覆盖率指标过期）
- terraform SAE 残留资源清理/归档；MigrationRunner 事务化 + advisory lock
- 生产 runbook（5-8 个）+ 季度演练 + SLO/SLA 定义
- 容量文档（SSE 长连接 × nginx worker_connections）+ 多实例粘性方案
- Prompt/模型版本管理 + per-tenant 模型覆盖灰度；Graph 级总超时 + LLM 并发信号量
- 语义化版本配套的 FUNDING/ADOPTERS/公开 Projects；git 历史完整性策略

---

## 5. 落地路线图（按依赖与工作量排序）

### 第 1 周 —— 纯增量为主、整体低风险（按 D1~D3 决策微调后）
1. 社区健康文件：`SECURITY.md`、`CODE_OF_CONDUCT.md`、`CHANGELOG.md`、`dependabot.yml`（+ `FUNDING.yml`）—— **零风险（纯新增文件）**
2. **SMS/DEBUG 处理（按决策 D2 调整）**：不改业务行为；① SmsService 加"bypass 生效"警告日志；② `.env.example` DEBUG 默认改 false（纯配置模板，不影响生产）；③ 建技术债 Issue（接真实 SMS 验收含移除 bypass）—— **零业务风险**
3. 日志脱敏：`[tool-exec]` 参数走 `LogSanitizer`（`base_skill.py:611,616`）；记忆提取 PII 黑名单 —— **代码改动，按 TDD 流程（先补日志断言测试 → 改 → 全量 pytest）**，行为不变，风险低
4. nginx 屏蔽 `/actuator/*`、`/v3/api-docs*`、`/swagger-ui*` 公网路径 + 端口绑 `127.0.0.1` —— **已核实 nginx upstream 全部走容器服务名（`admin-api:8080` 等），不依赖宿主端口映射，绑定 loopback 不影响转发与 deploy.sh 健康检查（其本身用 127.0.0.1 直连）；外部流量全部经 80/443**，风险低（需在服务器 reload 后冒烟）
5. 生产 compose 加 mem_limit/cpus —— 低风险；**admin-web `USER node` 移出本周**（`next start` 可能写 `.next/cache`，需构建 + 启动验证，降为 M 级）
6. gitleaks PR 门禁 + actions SHA pin —— 低风险（dependabot 接管升级）

### 第 2-3 周 —— M 级，4 个"需验证/演练"项
7. `CONTRIBUTING.md` + README 全面修订（按 01-docs-audit 核对表）+ 4 枚 badge + 仓库 description —— **零风险（含 RAG 描述按 D1 下线修订）**
8. semver 发布体系：`release.yml` + git SHA 镜像 tag + deploy.sh 支持指定 tag + 回滚 runbook —— **⚠️ 部署链路改动，需先在 SWAS 上手动演练一轮**（新 deploy.sh 由服务器自愈拉取，若出 bug 部署即失败，靠 flock + 健康检查兜底，不破坏运行中容器）
9. JSON 日志 + 统一 trace id（Java 加 MDC 透传 X-Request-ID）+ SLS Logtail 采集 + 云监控告警触达 —— **⚠️ 日志格式变更影响服务器排查习惯；Java 侧改动需全量单测；SLS 采集属服务器侧操作，建议独立一期**
10. 依赖锁文件（pip-tools/uv）+ 覆盖率阈值三端接线 —— **⚠️ 两个坑：① 锁文件可能引入传递依赖版本变化，生成后必须全量跑测试；② 覆盖率阈值必须先摸底当前值（`jacoco report`/`coverage json`），从低于现状的阈值起步（如 50%），否则所有 PR 变红**；Dockerfile `--trusted-host` 经核实为 HTTPS 源冗余参数，**保留并加注释即可，不改（零风险）**
11. deploy-frontend 补 concurrency + 域名 200 探测；contract-check 入 CI —— 低风险
12. nginx `-s reload` 替代 restart（reload 同样触发上游重解析，且失败不中断服务）+ compose healthcheck/depends_on —— **⚠️ depends_on: service_healthy 需调好 start_period 否则阻塞部署；建议 healthcheck 单独验证后再接 depends_on**

### 第 2 个月 —— L 级（按 D1~D3 决策后的剩余项）
13. ~~**RAG 决策**~~ **（D1 已决策：POC 不开放）** → 执行"下线标注"文档修订（README/wiki/rag-architecture.md），建 RAG 恢复追踪 Issue
14. 租户级 LLM 配额/成本硬阻断 + 成本落库看板（关联 admin 系统设置）
15. user_memories 保留期/删除 API 或下线；隐私政策页
16. 备份 IaC（RDS 策略/OSS 版本控制）+ 季度恢复演练；密钥上移 KMS/SOPS + 轮换
17. 链路追踪（LangSmith/OTel）+ LLM 错误率/延迟/成本指标与告警；语义缓存

### 第 3 个月 —— 治理与规模
18. SLO/SLA + 容量规划文档 + 多实例粘性方案（nginx sticky + 共享状态迁 Redis）
19. GOVERNANCE.md + ADOPTERS.md + 公开路线图/里程碑；DCO/CLA 机制
20. 若走 Apache-2.0：许可证切换 + THIRD_PARTY 审计 + SPDX 头

---

## 6. 证据索引与复核说明

- 本报告全部 P0 证据（SMS bypass / DEBUG / RAG 禁用 / 历史私钥 / latest tag）均经主线程 **grep/git 独立复核**，非仅采信子审计。
- 需服务器/云控制台侧复核的项（本次静态审计无法验证）：`.env.admin-api` 是否显式置空 `SMS_BYPASS_CODE`、SWAS 安全组/防火墙端口收敛、RDS 备份与 Tair 持久化配置、`.env.registry` 现状。
- 仓库外（父目录）发现明文凭据文件（`root_password.txt`、xray/clash 配置等）不属于本仓库，但建议一并清理或移入密码管理器。

---

## 7. 结论

**开源源代码合规、CI/测试/评测、AI 工程纪律已达到"可演示"水准，是国内少见的工程内功扎实项目。** 要达到"高标准开源 + 可复制投入企业生产"，缺口集中在：

1. **开源外壳**（1-2 周）：治理文件全缺 + 零版本发布 + README 信任状 —— 最易补齐、纯增量；
2. **生产安全 P0**：SMS 万能码 / DEBUG 直通 / 日志 PII / 文档失实（RLS、RAG）—— 先修后谈上线；
3. **发布与运维**：不可回滚 + 零可观测 + 无资源限制 —— 事故不可逆的关键短板；
4. **AI 成本与合规**：租户配额 / 成本硬阻断 / PII 记忆治理 —— 多租户 SaaS 商业化的前提；
5. **CI 安全左移**：secret 扫描 / 依赖扫描 / 镜像扫描 / 覆盖率门禁 —— 与"高标准"对齐的最后一块。

> 建议按仓库既有规范推进：每条差距建 Issue（带 CONTRACT_JSON）→ 分支 → TDD → PR（关联 Issue）→ CI 门禁 → 合并；治理文件类纯文档变更可直接 PR 快速落地。
