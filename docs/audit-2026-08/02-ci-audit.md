# migao CI/CD 与脚本体系审计报告

> 审计日期：2026-08-28（会话时间基准）｜ 审计范围：`.github/workflows/`（14 个 yml）、根目录 3 个脚本、`deploy/`、`.github/` 下 Python 工具与配置、PR/Issue 模板、README/CLAUDE.md/wiki 文档对照。
> 方法：read 全文 + `git ls-files` / `ls` / `git log` 验证引用存在性与历史。**本报告只读，未修改任何文件。**
> 结论速览：死引用 10 处、重复逻辑 8 处、冗余步骤 7 处、与现状不符 7 处、脚本重叠 3 处。

---

## 一、死代码 / 死引用（A）

### A1. CLAUDE.md 引用 4 个不存在的 workflow
【文件】`CLAUDE.md`（第 239 行「CI 成熟度说明」）
【问题】声称存在 `backend-tests.yml` / `frontend-tests.yml` / `smoke-tests.yml` / `e2e-tests.yml`。经 `git ls-files` 与 `git log --all` 验证：**这 4 个文件从未存在于 git 历史**，当前 14 个 workflow 中只有 `ai-agent-tests.yml` 与之对应。真实对应关系：admin-api 单测 → `pr-check.yml` 内 job；admin-web 单测 → `pr-check.yml` 内 job；E2E smoke → `smoke-test.yml`（workflow_call）；Playwright → `pr-check.yml` 的 e2e-quality-gate job。
【建议】重写该段落为实际文件名（pr-check.yml / ai-agent-tests.yml / smoke-test.yml）。

### A2. docs/wiki/CI-CD.md 工作流清单与现状脱节
【文件】`docs/wiki/CI-CD.md`（第 3–19 行）
【问题】标题写「12 个 GitHub Actions 工作流」，实际 14 个：清单**缺 `ai-agent-tests.yml` 与 `agent-eval-adversarial.yml`**；同时列出**已删除的 `e2e-web`**（git 历史 370d6cf5 已删除，现 e2e-real.yml 为不同用途）。`e2e-real` 描述「仅 workflow_dispatch」，实际含每日 schedule（`0 16 * * *`）。
【建议】按 14 个实际文件重写清单，删除 e2e-web 行，补 agent-eval-adversarial、ai-agent-tests。

### A3. tech-stack.yml 引用不存在的 deploy workflow
【文件】`.github/tech-stack.yml`（第 19 行）
【问题】`services[].admin-web.deploy_workflow: deploy-admin-web.yml` —— 该文件不存在，实际为 `deploy-frontend.yml`。
【建议】修正为 `deploy-frontend.yml`（该字段被二郎神引擎消费，错误的部署名会导致部署映射失效）。

### A4. pr-check.yml 引用已删除的文档
【文件】`.github/workflows/pr-check.yml`（第 212、246 行）
【问题】错误信息与 PR 评论链接 `docs/testing/qa-growth-gate.md`，**文件不存在**（git 历史 1308c569 曾创建、699dad1c 删除，内容已迁至 `docs/wiki/Testing.md`）。
【建议】链接改为 `docs/wiki/Testing.md`，或在 workflow 内嵌入说明。

### A5. pr-check.yml 的 junshi fallback 是死分支
【文件】`.github/workflows/pr-check.yml`（case-truth-check job，第 305–306 行）
【问题】fallback `junshi/truths.py` + `templates/` + `cases/` 均不存在（`junshi/` 目录只跟踪了 `coverage_weekly.py`）。主路径（`.github/`）正常，fallback 永远不会命中。
【建议】删除该 fallback 分支，保留 `.github/` fail-closed 主路径。

### A6. growth_gate.py 的 junshi fallback 是死路径
【文件】`.github/growth_gate.py`（第 464 行 `_find_tech_stack`）
【问题】fallback `junshi/tech-stack.yml` 不存在；同理 `_load_yaml`/`load_case_index` 里 `../junshi` 的 sys.path 注入无实际文件命中（yaml_light 靠 `.github/` 自身路径生效）。
【建议】删除 `junshi/` fallback 与 sys.path 注入，仅保留 env 覆盖 + `.github/` 默认路径。

### A7. 根目录残留被跟踪的 PR 草稿
【文件】`pr-body.txt`（仓库根，被 git 跟踪）
【问题】内容是旧 PR #1199 的 body 草稿（"Closes #1199 …"），与任何 CI/脚本无关。
【建议】删除。

### A8. terraform 下无引用的验证脚本
【文件】`deploy/terraform/test_dual_bucket.sh`
【问题】全仓库（workflow/文档/脚本）无任何引用，是一次性验证脚本。terraform 本身已正确标注遗留（main.tf 头部 + README + CLAUDE.md 均注明 SAE 已弃用、RDS/OSS 可参考）。
【建议】删除该脚本；terraform 目录保留标注遗留即可（或整体归档到 `docs/legacy/`）。

### A9. OSS 托管脚本仅被历史文档引用
【文件】`deploy/scripts/apply-oss-website.sh`、`deploy/scripts/clean-oss-dir-markers.sh`、`deploy/oss-website.xml`、`deploy/oss-cname-cert.xml`
【问题】仅被 `docs/deployment/deployment-aliyun.md`（SAE/OSS 时代历史文档）引用，无任何 workflow 引用；当前前端部署走 SWAS 容器（deploy-frontend.yml → swas-deploy-ci.sh），OSS 静态托管路径已不再使用。
【建议】随 terraform 一并归档或删除；如保留，应在文件名/注释标注「OSS 时代遗留，当前 SWAS 部署不使用」。

### A10. CLAUDE.md 用例规模数字过时
【文件】`CLAUDE.md`（Case Contract 节："80 条 × 12 域"）
【问题】实际 `.github/cases/` 为 19 域 118 条（活跃 82 条：smoke 9 / normal 47 / adversarial 26）。"smoke 9 条、adversarial 26 条"与事实一致，但 normal 声称 45、实际 47。
【建议】更新数字（或以 "N 条" 泛化）。

---

## 二、重复逻辑（B）

### B1. 三个 deploy workflow 重跑 PR 已跑的单测
【文件】`deploy-admin-api.yml`（44–46 行）、`deploy-frontend.yml`（42–48 行）、`deploy-ai-agent-service.yml`（60–89 行）vs `pr-check.yml`（admin-api-test / admin-web-test）与 `ai-agent-tests.yml`
【问题】同一批测试在 PR 阶段与 merge 后 deploy 阶段各跑一遍：admin-api `./mvnw test -q`、admin-web `npm ci + tsc + vitest`、ai-agent pytest 全量。
【建议】保留 deploy 前快速门禁（防合入坏代码上线）有合理性，但三处命令与 pr-check 完全同源，建议：① deploy 流程只保留「构建 + 部署 + 冒烟」，单测依赖 PR 门禁；② 或至少把 admin-api 的 `./mvnw test -q` 降为 `./mvnw package -DskipTests` 前的编译检查。权衡后推荐保留现状但合并 B2。

### B2. deploy-ai-agent-service 的 Fast Gate 是全量子集
【文件】`.github/workflows/deploy-ai-agent-service.yml`（49–58 行 vs 60–89 行）
【问题】Fast Gate 只跑 `test_intent_router.py` / `test_preference_tracker.py` / `test_tools_base.py`，而随后「Run unit tests」跑 `pytest tests/` 全量（已包含这三个文件）——同一批用例执行两遍，且两次 `pip install -r requirements.txt`。
【建议】删除 Fast Gate step（或保留为构建前快速失败门禁但去掉重复 install，两步骤合并为一个 step）。

### B3. agent-eval.yml 内 smoke 与 full 重复
【文件】`.github/workflows/agent-eval.yml`（34、43 行）
【问题】`local_runner.py full` 的 `active_cases()` 已包含 smoke tier（已核实源码），先跑 smoke 再跑 full = smoke 用例每日跑两遍，LLM 调用成本翻倍。
【建议】删除 smoke step，仅保留 full；如要快速失败诊断可把 smoke 改为独立 job。

### B4. 同一 smoke 套件多入口双跑
【文件】`pr-check.yml`（agent-eval-smoke job）、`agent-eval.yml`、`smoke-test.yml`、`e2e-real.yml`
【问题】「冒烟」存在 4 层：PR gate 的 LLM cases smoke、每日 agent-eval 的 smoke（与 PR 是同一条命令 `local_runner.py smoke --cases .github/cases`，每日与每次 PR 双跑）、deploy 后 pytest P0（不同套件）、e2e-real 每日真实 LLM。其中 PR gate 与每日任务的功能重叠。
【建议】PR gate 保留（阻塞合并）；每日任务把 agent-eval + e2e-real 合并为一个 schedule workflow 的 2 个 job（见 C 节合并收益），减少 3 个独立 schedule 时钟。

### B5. growth gate 的弱断言检查可并入主调用
【文件】`.github/workflows/pr-check.yml`（qa-growth-gate job 内 165–201 行）
【问题】`growth_gate.py --check-weak` 是独立 step；`--check-cases`（G5）在主调用已启用。分工本身合理（数据源：tech-stack.yml + qa-exemptions.yml 单源化已完成），但弱断言可作为 `--check-weak` 参数并入主调用一次输出，减少一个 step 与一次 git diff 计算。
【建议】将两个 step 合并为一次 `python3 .github/growth_gate.py --files ... --check-weak ...`（或在主调用里加 `--check-weak` 开关）。

### B6. case-contract 校验四处重复
【文件】`issue-contract-check.yml`（125–155 行）、`junshi-case-draft.yml`（57–84 行）、`pr-check.yml`（case-truth-check job）、`pr-check.yml`（qa-growth-gate G5）
【问题】「用例引用完整性」在 issue 级（warn）、DRAFT 级（提醒）、PR 级（truths_ref fail-closed）、PR 级（case_ids 追溯）四处实现。PR 级的两处（case-truth-check 与 G5）都是「用例/真值引用存在性」。
【建议】保留 issue/DRAFT 级（不同触发时机）；PR 级把 case-truth-check 并进 qa-growth-gate job（G5 已含 --check-cases），删独立 job。注意 job 名与分支保护耦合，合并需同步改 required checks。

### B7. needs-truths → needs-verification 转换双实现
【文件】`issue-contract-check.yml`（47–71 行）、`junshi-case-draft.yml`（29–40 行）
【问题】两个 workflow 都在做「issue 补了业务真值 → 转 needs-verification 标签」的机械操作，逻辑重复、可能竞争打标。
【建议】保留 `junshi-case-draft.yml`（触发更全：opened/edited/labeled），`issue-contract-check.yml` 只做提醒评论与 needs-verification 直判，删掉转换分支。

### B8. 失败打标签双路径
【文件】`pr-check.yml`（qa-growth-gate 内 204–214 行 vs label-needs-changes job）
【问题】qa-growth-gate 失败时自己 `gh pr edit --add-label junshi-review/needs-changes`，随后 label-needs-changes job（`if: failure()`）又会打同一个标签（幂等但双路径，注释已承认这是 G3 fix 的产物）。
【建议】qa-growth-gate 内只 `exit 1`，标签统一由 label-needs-changes 打（G3 注释已说明这是正确架构）。

---

## 三、冗余步骤（C）

### C1. deploy-frontend 推 GHCR 无人消费
【文件】`.github/workflows/deploy-frontend.yml`（55–66 行）
【问题】同时登录 ACR + GHCR，推送 4 个 tag；`deploy.sh` 只从 ACR pull，全仓库（workflow/deploy/文档）无任何 ghcr.io 引用。GHCR 推镜像纯属浪费带宽与时间，且 GHCR 有 500MB 镜像大小限制风险。
【建议】删除 GHCR 登录与 ghcr.io 两条 push（保留 ACR 双 tag）。

### C2. deploy-ai-agent-service 重复 install
【文件】`.github/workflows/deploy-ai-agent-service.yml`（52、85 行）
【问题】Fast Gate 与全量单测各执行一次 `pip install -r requirements.txt -q`（同 B2，合并后自然消除）。
【建议】随 B2 合并为一个 step。

### C3. 镜像构建缓存策略不一致
【文件】`deploy-ai-agent-service.yml`（buildx + `type=gha` cache）vs `deploy-admin-api.yml`（普通 `docker build` 无 cache）vs `deploy-frontend.yml`（普通 build 无 cache）
【问题】同一套 ACR 流水线三种构建方式，admin-api/frontend 每次全量构建（Maven/Next 依赖层不缓存），慢且不一致。
【建议】统一为 `docker/setup-buildx-action` + gha cache（与 ai-agent-service 对齐），或在三处都说明为何不缓存。

### C4. e2e-real 上传无价值 artifact
【文件】`.github/workflows/e2e-real.yml`（49–56 行）
【问题】失败时上传 `.pytest_cache/` 与 `__pycache__/`——缓存目录无诊断价值；失败已通过建 issue + run URL 追踪。
【建议】删除该 step，或改为上传 pytest 详细报告（`--tb=long` 输出到文件）。

### C5. e2e-quality-gate 双 npm ci 无缓存
【文件】`.github/workflows/pr-check.yml`（e2e-quality-gate job，111–117 行）
【问题】`tests/` 与 `frontend/admin-web/` 各 `npm ci` 一次，setup-node 未配 cache。
【建议】为两个 working dir 配 setup-node cache（或合并安装）。

### C6. deploy-frontend 缺 concurrency group
【文件】`.github/workflows/deploy-frontend.yml`
【问题】另两个 deploy workflow 都有 `concurrency: cancel-in-progress: false`，deploy-frontend 没有——并发 push 到 frontend 路径时多次触发 RunCommand（服务器 flock 兜底，但 CI 侧应尽早串行）。
【建议】补上 concurrency group（`deploy-frontend`），或注释说明有意依赖服务器锁。

### C7. 两个 deploy 各自跑一遍 post-deploy P0 冒烟
【文件】`smoke-test.yml` 被 `deploy-admin-api.yml` 与 `deploy-ai-agent-service.yml` 分别 `workflow_call`
【问题】admin-api 与 ai-agent 先后部署时，对同一组生产端点（api.migaozn.com / ai-api.migaozn.com）跑两遍 P0 冒烟。
【建议】可接受（各服务独立验证更清晰）；若想省成本可合并为 needs 两个部署的单一冒烟 job——但会引入跨 workflow 依赖复杂度，性价比低，倾向保留现状。

---

## 四、与现状不符（D）

### D1. workflow 注释声称 ACR 镜像「历史遗留、线上不消费」——与实现矛盾（重点）
【文件】`deploy-ai-agent-service.yml`（17 行）、`deploy-frontend.yml`（14 行）
【问题】注释：「ACR 镜像构建为历史遗留（SWAS 服务器自己源码构建，线上不消费该镜像）」。**与实现完全相反**：`deploy/swas/deploy.sh` 头部写明「SWAS 服务器拉取 CI 预构建镜像（不做源码构建）」，并逐服务 `docker compose pull`；`deploy/swas/docker-compose.yml` 的镜像都指向 ACR；README/CLAUDE.md 也写「CI 构建镜像 + 服务器 pull」。这两条注释是迁移期残留，**会误导维护者误删部署必需的镜像构建步骤**（且 deploy-ai-agent-service 里还配套 buildx 构建，说明构建是活的）。
【建议】删除或更正这两行注释（改为「CI 构建镜像推送 ACR → 服务器 pull」）。

### D2. docs/wiki/CI-CD.md 部署链路描述过时
【文件】`docs/wiki/CI-CD.md`（32–44、66–74 行）
【问题】链路写「服务器执行 deploy.sh：… docker compose up -d --build」，实际 deploy.sh 是 `docker compose pull` + `up -d --no-deps`（不做源码构建）；「超时 1800s」实际 3600；「ACR 凭据历史遗留、线上已不消费」与 D1 同源矛盾（实际服务器要 docker login 拉 ACR）。
【建议】按 `deploy/swas/deploy.sh` 现状重写部署链路段。

### D3. README/CLAUDE.md 本地端口与 compose 不符
【文件】`README.md`（191–194 行）、`CLAUDE.md`（本地启动节）、`deploy/docker-compose.yml`（60–61 行）、`.github/tech-stack.yml`（11 行）
【问题】README/CLAUDE.md/tech-stack 声称 admin-api 本地端口 **8081**，但 `deploy/docker-compose.yml` 映射 **8080:8080**（ai-agent 为 8001:8000 一致）；生产（deploy.sh 健康检查）是 8080/8000/3001。本地端口三处文档与 compose 冲突。
【建议】统一：compose 改 8081 或文档改 8080（以 compose 为准则改文档）。

### D4. deploy/docker-compose.yml 注释指向遗留
【文件】`deploy/docker-compose.yml`（4 行）
【问题】「生产环境使用阿里云 RDS/Redis，见 deploy/terraform/」——terraform 已标注遗留（SAE 时代），生产现为 SWAS + 服务器侧 `.env.admin-api` 等。
【建议】注释改为「生产配置见 deploy/swas/ + 服务器侧 env」。

### D5. CLAUDE.md「本地只启动 3 个组件」与 compose 冲突
【文件】`CLAUDE.md`（本地开发环境节）vs `deploy/docker-compose.yml`
【问题】CLAUDE.md 铁律「本地只启动 3 个组件，DB/Redis 用云 dev」，但 README 推荐 `docker-compose up --build`（deploy/docker-compose.yml 会起本地 postgres + redis 共 4 个容器）。两文档互相矛盾。
【建议】在 README 注明「compose 起本地 DB 仅用于无云环境演练；日常开发按 CLAUDE.md 用云 dev」。

### D6. 部署后冒烟覆盖不一致
【文件】`deploy-frontend.yml`（无 smoke job）vs `deploy-admin-api.yml` / `deploy-ai-agent-service.yml`（有）
【问题】admin-api 与 ai-agent 部署后有 post-deploy P0 冒烟，前端部署没有（前端只有构建期 vitest/tsc）。若前端构建产物有问题（如 build 时注入的 API base URL），部署后无校验。
【建议】deploy-frontend 增加对 `https://<前端域名>` 的 HTTP 200 检查 step（或复用 smoke-test 的轻量前端探测），明确有意为之的话在注释说明。

---

## 五、脚本间重叠（E）

### E1. verify-all.sh 的 gate 与 CI 规则漂移（重点）
【文件】`verify-all.sh`（gate_check 函数，40–55 行）vs `.github/workflows/pr-check.yml`（qa-growth-gate job）
【问题】脚本头声称「开发自查与 CI 用同一命令」，但实为两套参数：CI 主调用带 `--check-cases .github/cases`（G5 用例追溯），verify-all 的 gate_check **没有 `--check-cases`、也没有 `--check-weak`**；CI 还多一个独立弱断言 step。→ 本地 `verify-all.sh gate` 全绿 ≠ CI qa-growth-gate 必绿，规则漂移。
【建议】把 gate 校验抽成单一入口（例如新增 `scripts/qa-gate-local.sh` 或让 verify-all 的 gate 模式补齐 `--check-cases` + `--check-weak` 与 CI 完全一致），并加注释说明必须与 pr-check 同步。

### E2. contract-check.sh 未接入 verify-all 与 CI
【文件】`contract-check.sh`、`verify-all.sh`
【问题】三脚本职责：verify-all=三模块测试+门禁、check-ui-regression=UI token 回退、contract-check=跨端契约一致性。verify-all 已集成 check-ui-regression（quick/full），但 **contract-check 既不被 CI 引用、也不在 verify-all 的任何 mode 里**，只出现在 docs/wiki/DEV-FLOW.md 与 .agents skill 中作为人工命令。
【建议】verify-all.sh 增加 `contracts` mode（或并入 `gate`），形成「一个入口：`./verify-all.sh {quick|full|gate|contracts|frontend|backend|agent}`」，三脚本职责互补、可合并为单一入口的子命令。

### E3. check-ui-regression.sh 双调用点（无逻辑重复，仅记录）
【文件】`verify-all.sh`（66、75 行）与 `pr-check.yml`（ui-regression-check job）
【问题】同一脚本两个入口：本地默认 worktree 模式、CI `--head` 模式。逻辑无重复（verify-all 直接调用脚本），但 UI 检测在 PR gate 与本地自查双跑属预期行为。
【建议】保留；将 CI 与本地模式的差异（--head vs worktree）在脚本头注释写明（已写，OK）。

---

## 六、.github/ 工具与配置的被引用关系（调研要求 4）

| 文件 | 被谁引用 | 用途 |
|------|---------|------|
| `.github/truths.py` | `issue-contract-check.yml`（`truths.py case <id>`）、`pr-check.yml` case-truth-check（`truths.py check`）；CLAUDE.md 本地校验命令 | 业务真值 ID 解析 + case truths_ref 引用校验（fail-closed） |
| `.github/render_cases.py` | 无 workflow 引用（纯本地生成工具，CLAUDE.md 校验命令）；生成物 `tests/agent_eval/eval_cases.py` 被 `local_runner.py` 兜底导入、`docs/testing/mibao-verification-cases.md` 供人读 | cases/*.yml 单一源 → 两个生成物 |
| `.github/growth_gate.py` | `pr-check.yml` qa-growth-gate（主调用，带 `--check-cases`）、pr-check 弱断言 step（`--check-weak`）、`verify-all.sh` gate_check（本地复刻） | 数据驱动测试覆盖门禁 G1/G2/G4/G5 |
| `.github/qa-exemptions.yml` | `growth_gate.py`（pr-check / verify-all 均传 `--exemptions`） | 豁免路径数据（glob，`*` 不跨 `/`） |
| `.github/tech-stack.yml` | `growth_gate.py`（`--tech-stack` 规则源） | 模块→测试映射单一规则源（含一处死引用 A3） |
| `.github/yaml_light.py` | truths.py / render_cases.py / growth_gate.py 内部 import | 轻量 YAML 解析（flow-style 不支持，case 文件须 block style） |

> 分工小结：growth gate 的「规则（tech-stack.yml）+ 豁免（qa-exemptions.yml）+ 执行器（growth_gate.py）+ CI 编排（pr-check qa-growth-gate job）」四层分工是健康的，主要问题是 verify-all.sh 复刻了执行层却参数不同步（E1）、以及 PR 级 case 校验重复（B6）。

---

## 七、优先级汇总（Top 8）

### P0 —— 误导/可能破坏部署，建议优先处理
1. **D1（+D2）**：`deploy-ai-agent-service.yml` / `deploy-frontend.yml` 注释称 ACR 镜像「历史遗留、线上不消费」，与 `deploy.sh` 实际「服务器 pull ACR 镜像」矛盾 → 删除/更正注释，防止误删部署必需步骤。【建议：重写注释】
2. **A1**：CLAUDE.md 引用 4 个不存在 workflow（backend-tests/frontend-tests/smoke-tests/e2e-tests），AI 研发按文档找不到文件 → 重写该段。【建议：重写】
3. **E1**：`verify-all.sh gate` 与 pr-check qa-growth-gate 参数不一致（缺 `--check-cases`/`--check-weak`），本地绿 ≠ CI 绿 → 对齐为单一入口。【建议：重写 gate_check / 抽共享入口】

### P1 —— 成本与一致性
4. **B1+B2**：三个 deploy 重跑 PR 单测；deploy-ai-agent-service 的 Fast Gate 是全量子集、重复 install → 合并 Fast Gate 与全量，deploy 流程精简。【建议：合并到 deploy-ai-agent-service / 删除重复步骤】
5. **C1**：deploy-frontend 推 GHCR 无人消费 → 删除 GHCR 登录与 push。【建议：删除】
6. **B3+B4**：agent-eval.yml 每日 smoke+full 重复（full 含 smoke）；每日 LLM 任务 3 个独立 schedule → agent-eval 删 smoke step；agent-eval + e2e-real 合并为一个 schedule workflow。【建议：合并/删除】
7. **A2**：docs/wiki/CI-CD.md「12 个工作流」实际 14 个，含幽灵 `e2e-web`，部署链路描述过时 → 按现状重写。【建议：重写】
8. **A3**：tech-stack.yml `deploy_workflow: deploy-admin-web.yml` 不存在 → 改为 deploy-frontend.yml。【建议：修正】

### P2 —— 清理项
- **A4** qa-growth-gate.md 死链接 → 改指 docs/wiki/Testing.md；**A5/A6** junshi fallback 死分支删除；**A7** 删 pr-body.txt；**A8** 删 test_dual_bucket.sh；**A9** OSS 脚本归档；**A10** 更新 cases 数字。
- **B5** 弱断言并入主调用；**B6** case-truth-check 并入 qa-growth-gate；**B7** 标签转换去重到 junshi-case-draft；**B8** 打标签统一到 label-needs-changes。
- **C3** 统一 buildx+gha cache；**C4** 删无价值 artifact；**C5** npm cache；**C6** 补 concurrency；**C7** 冒烟双跑可接受。
- **D3** 端口 8081 vs 8080 统一；**D4** compose 注释改指 SWAS；**D5** README 与 CLAUDE.md 本地启动矛盾说明；**D6** deploy-frontend 补部署后探测。
- **E2** contract-check 并入 verify-all 入口。
