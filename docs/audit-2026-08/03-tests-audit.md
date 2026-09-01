# migao 测试体系与仓库卫生审计报告

- 审计范围：`tests/`（e2e 93 个跟踪文件 / smoke / agent_eval / unit_junshi / unit_dual_verify）、`backend/ai-agent-service/tests/`（109 个顶层 py + contracts/unit/e2e 子目录）、`.github/cases/`（18 领域 + registry）+ `.github/templates/`（24 yml + 3 md）、`docs/testing/mibao-verification-cases.md`、相关配置与 CI workflows。
- 方法：只读审计（git ls-files、AST 静态导入校验、引用闭包分析、workflow 路径比对、wc -l / grep 抽查），未修改任何业务文件。
- 结论速览：**测试体系总量庞大但"跑起来"的部分远小于表面**——CI 实际执行的用例占比低（smoke 仅 7/104、e2e specs 仅 4/36 个文件、backend 有 ~2900 行 integration 测试被排除、2 个 spec 整文件全 skip）；存在一批刷量型 coverage 测试、空壳目录与死代码；文档（CLAUDE.md、cases/README）与仓库现状明显脱节。

---

## A. 重复 / 重叠测试

### A1. `*_coverage.py` 系列：pt1/pt2/pt3 流水账刷量，与专用测试大面积重叠 【P1】
【文件】`backend/ai-agent-service/tests/test_tools_coverage_pt1.py`（60 行）/ `test_tools_coverage_pt2.py`（69 行）/ `test_tools_coverage_pt3.py`（81 行）
【问题】
- pt1 的 9 个测试**全部**是 `test_class_exists`：只 `from app.tools.X import Y; assert Y is not None`，不验证任何行为。
- 这些 class_exists 与被测工具各自的专用测试文件完全重叠：`ProductManageTool`（pt1 ↔ test_tools_product_manage.py）、`OrderManageTool`（pt2 ↔ test_tools_order_manage.py）、`OrderCreateTool`（pt2 ↔ test_tools_order_create.py）、`DashboardStatsTool`（pt2 ↔ test_tools_dashboard_stats.py）、`AftersaleQueryTool`（pt3 ↔ test_tools_aftersale_query.py）…… 23 个 class_exists 断言对应的 import 路径在 32 个 `test_tools_*.py` 中已被真实用例覆盖。
- pt2 的 4 个 registry 上下文测试（set/get_tool_context、create_default_registry、reset）与 `test_tools_registry.py`（15 个测试）同域。
【建议】删除 pt1（纯刷量）；pt2/pt3 中 19 个 class_exists 删除，pt2 的 4 个 registry 测试合并进 `test_tools_registry.py`；pt3 的 ToolContext/ToolResult/_ensure_list/_json_string_parser 行为测试并入 `test_tools_base.py` / `test_tools_langchain_adapter.py` / `test_tools_interact.py` 后删除整个 pt 系列。

### A2. `test_utils_coverage.py` 与专用 utils 测试重复 【P1】
【文件】`backend/ai-agent-service/tests/test_utils_coverage.py`（210 行，issue #583）
【问题】`TestLogSanitizer`（mask_phone/mask_text/filter_params…）与 `test_utils_log_sanitizer.py` 重复；`TestFieldMapper`（java_to_python/python_to_java/get_price…）与 `test_utils_field_mapper.py` 重复；还覆盖 database/http_client/auth/redis_client，与 `test_utils_database.py`、`test_utils_http_client.py`、`test_utils_auth.py`、`test_utils_redis_client.py` 同样同域。
【建议】删除本文件，其 6 个模块的行为测试分别并入对应的 `test_utils_*.py`；"coverage" 命名误导，不应保留。

### A3. `test_misc_coverage.py` / `test_misc_pt1_coverage.py` 与专用测试重复且命名误导 【P1】
【文件】`test_misc_coverage.py`（91 行，#577）、`test_misc_pt1_coverage.py`（64 行，#576）
【问题】
- `_extract_text` / `_build_classifier_prompt` 与 `test_intent_classifier.py`、`test_rule_matcher.py`、`test_graph_nodes.py` 重复；`_parse_extraction_result` 与 `test_memory_extractor.py` 同域；retry_policy/cost_tracker 测试与 `test_llm_retry_policy.py`、`test_llm_cost_tracker.py` 重复。
- 两个文件并非同一系列（一个测 retry/cost，一个测 extractor/intent/suggestions/factory/main），却命名为 pt1/pt2 + misc，掩盖被测对象。
【建议】行为测试分别并入对应专用文件后删除；若保留，按被测模块重命名（如 test_llm_retry_coverage.py）。

### A4. `test_api_coverage.py` 命名误导 + 与 chat 测试重叠 【P2】
【文件】`test_api_coverage.py`（407 行，#581）
【问题】实际是 app/api/chat.py 私有 helper（_format_datetime/_convert_history_to_agent_format/_validate_image_url…）与 upload/internal 的行为测试，与 `test_chat.py`、`test_sse.py`、`test_upload.py` 部分重叠；叫 "coverage" 掩盖了它是有价值的行为测试。
【建议】改名 `test_api_chat_helpers.py` 并去重；不要删除（内容真实有用）。

### A5. Playwright `real` 套件 vs backend pytest `real` 套件：同一批工具的"真实 LLM E2E"双套并行 【P1】
【文件】`tests/e2e/real/ai-agent/mibao-b-end.spec.ts`、`mibao-c-end.spec.ts`、`mibao-chat-flow.spec.ts`、`tests/e2e/real/chat/chat.spec.ts`（共 78 个 test）↔ `backend/ai-agent-service/tests/e2e/real/test_query_tools.py`、`test_write_tools.py`、`test_creation_flows.py`、`test_security.py`
【问题】两侧按同一份工具清单（order_manage/product_manage/customer_manage/employee_manage/role_manage/dashboard_stats/aftersales/notification/settings/session/quick_reply/category/processing/knowledge…）做真实 LLM E2E，1:1 对应（如 playwright `order_manage - 创建订单` ↔ pytest `test_order_create_with_processing_info`）。UI 驱动 vs API 直连，维护成本双倍。
【建议】保留 pytest API 层（已被 `e2e-real.yml` 定时调度）；playwright real 层明确降级为"手动 UI 验证工具"或删除，避免双份真实环境消耗。

### A6. 顶层 `test_*.py` 与 `unit/` 子目录同名文件并存 【P2】
【文件】`test_tools_order_create.py` ↔ `unit/test_tools_order_create.py`；`test_tools_dashboard_stats.py` ↔ `unit/test_tools_dashboard_stats.py`
【问题】同名同主题两处存放，内容不同步（顶层为 8/25 新版，unit/ 为 8/13 旧版），pytest 两处都收集，测试分裂。
【建议】合并到一处（保留顶层新版），删除 unit/ 旧版。

### A7. playwright.config.ts：`web` 与 `chromium` 两个 project 覆盖完全相同的文件集 【P1】
【文件】`tests/playwright.config.ts`
【问题】`web`（testMatch specs/* 排除 auth）与 `chromium`（testIgnore auth|real）筛选结果等价。CI `pr-check.yml` 显式传文件时（api-contract/anti-placeholder/cross-page-consistency/dashboard），两个 project 都会匹配 → **同一 spec 在 CI 里跑两遍**，质量门禁耗时翻倍且无额外收益。
【建议】删除冗余的 `chromium` project（config 注释自称"向后兼容"，但显式文件模式已兼容），只保留 auth-setup / auth-pages / web / real。

---

## B. 过期 / 失效测试

### B1. `tests/unit_dual_verify/`：空壳目录，零测试文件 【P0】
【文件】`tests/unit_dual_verify/`（仅 `__init__.py` + `conftest.py`，conftest 只是往 sys.path 塞 scripts 目录）
【问题】没有任何 test_*.py，pytest 收集 0 个用例；全仓无任何 workflow/脚本引用。是"双端验证"计划的残留空壳。
【建议】删除目录；若确有双端验证计划，先立项再建目录，禁止空壳占位。

### B2. `tests/unit_junshi/`：孤儿测试，CI 从不运行 【P1】
【文件】`tests/unit_junshi/test_coverage_batch.py`、`test_label_guard.py`（测 `junshi/coverage_weekly.py` 与 junshi-case-draft workflow 的 label guard）
【问题】全仓（.github/workflows、verify-all.sh、任何 .sh/.yml/.md）零引用；junshi 系列 workflow 只做 issue 标签自动化，不跑 pytest。这两个测试写得是正经单测，但没人运行 → 过期风险高（workflow 一改 label 逻辑就静默失真）。
【建议】接入 `pr-check.yml` 或 `ai-agent-tests.yml` 一起跑（成本极低）；否则删除。

### B3. `test_mibao_scenarios.py`：脚本伪装成测试，pytest 收集 0 用例 【P1】
【文件】`backend/ai-agent-service/tests/test_mibao_scenarios.py`（494 行）
【问题】0 个 `test_*` 函数：是一份 `scenario_*` + `main()` + `sys.exit(1)` 的独立脚本（`if __name__ == "__main__"`），pytest 静默跳过，任何 workflow 也不运行 → 494 行死代码，且命名误导（看起来像测试）。
【建议】移到 `scripts/` 或 `tests/manual/` 并去掉 test_ 前缀；或重写为 pytest 参数化用例并入 `test_e2e_mibao_scenarios.py`。

### B4. `test_skill_skills/` 目录：死目录 【P2】
【文件】`backend/ai-agent-service/tests/test_skill_skills/`（`__init__.py` + `base_skill.py` 268 行，与 `app/graph/skills/base_skill.py` 1138 行内容不同）
【问题】无任何 test_*.py、无任何 import 引用；疑似某次重构遗留的"测试专用 skill 基类"，无人使用。
【建议】删除；如仍需要该夹具，移入 conftest 或 fixtures 并给出引用。

### B5. `test_post_deploy_verify.py`：docstring 承诺"部署后自动运行"，实际从不运行 【P0】
【文件】`backend/ai-agent-service/tests/test_post_deploy_verify.py`
【问题】docstring 写明"每次 ai-agent-service 部署后自动运行"，但 `deploy-ai-agent-service.yml` 与 `ai-agent-tests.yml` 两处 pytest 都显式 `--ignore=tests/test_post_deploy_verify.py`，部署后只跑 smoke-test.yml（p0）→ 该文件在 CI 从未执行，承诺与实现不符。
【建议】二选一：把关键校验并入部署后步骤真正跑起来；或改 docstring 标注"手动脚本"并归档。

### B6. integration 标记测试（2920 行）在 CI 永不执行 【P0】
【文件】`test_business_verification.py`（1306 行）、`test_cross_service_tenant.py`（520）、`test_e2e_full_chain.py`（431）、`test_performance_isolation.py`（663），共 113 个 integration 标记测试
【问题】`ai-agent-tests.yml` 与 `deploy-ai-agent-service.yml` 均加 `-m "not integration"` 排除；`e2e-real.yml` 只跑 `tests/e2e/real/`（不含这些文件）→ 4 个文件、~2900 行、113 个测试在 CI 中永远不执行，任何回归都不会被发现。
【建议】明确归属：能 mock 的降级为普通单测纳入常规 CI；需要真实环境的移入 `tests/e2e/real/` 让 e2e-real.yml 调度；其余删除。绝不允许"存在但从不运行"的测试。

### B7. smoke 套件：CI 只跑 7/104 个测试 【P0】
【文件】`tests/smoke/test_04_ai_chat.py` ~ `test_11_knowledge_ai_advanced.py`（9 个文件 ~3000 行）、`test_react_smartness.py`
【问题】`smoke-test.yml`（部署后 + pr-check 前置）只执行 `pytest -m "p0"`，全仓 p0 标记仅 7 个（test_01:1 / test_02:3 / test_03:3）。其余 97 个 p1/performance 标记测试（覆盖 AI 对话、多租户、订单生命周期、售后通知、知识库 AI 等核心域）从未进入 CI；`test_react_smartness.py`（"6 scenarios, 35 turns"）既无 pytest 标记也无 test 函数，且模块级 `if not SERVICE_TOKEN: exit(1)` —— 本地无该环境变量时 `pytest tests/smoke` 会在**收集阶段直接 SystemExit 崩掉**（CI 靠注入 SMOKE_SERVICE_TOKEN 才幸免）。
【建议】① 新增 nightly workflow 跑 `pytest -m "p1"`（或全量）；② `test_react_smartness.py` 改名为 `react_smartness_check.py` 移出 smoke 目录，或改为真正的 pytest 用例并显式跳过（skip），消除收集崩溃隐患。

### B8. e2e Playwright specs：36 个 spec 文件只有 4 个进 CI 【P1】
【文件】`tests/e2e/specs/**/*.spec.ts`（36 个文件，~480 个 active test）
【问题】`pr-check.yml` 的 e2e-quality-gate 只跑 `quality/api-contract`、`quality/anti-placeholder`、`quality/cross-page-consistency`、`dashboard/dashboard` 4 个文件；其余 32 个文件（auth 之外的订单/商品/客户/售后/分类/聊天/设置/存储等）无任何 workflow 运行（e2e-real.yml 是 backend pytest）。这些 spec 是 fixture mock 模式本可进 CI，却长期"存在但不跑"。
【建议】在 pr-check 或独立 e2e workflow 中跑全部 fixture 类 spec（`--project=web`，`E2E_MOCK_AUTH=true`），或明确分层：quality 门禁 + 每周全量。

### B9. 引用校验抽查：backend 测试静态导入面健康，无失效 import 【正面确认】
【文件】`backend/ai-agent-service/tests/`（120 个 test_*.py）
【问题】AST 静态校验全部 `from app.X.Y import Z`（含 AnnAssign 定义符号）：0 个缺失模块、0 个缺失符号。`tests/e2e` 的 spec/helper/fixture 相对导入闭包：0 个缺失文件。
【建议】无（本项确认通过；未做运行级验证，建议 CI 保证收集通过作为兜底）。

---

## C. 跟踪了不该跟踪的文件

### C1. 生成物被 git 跟踪：`mibao-verification-cases.md` 与 `eval_cases.py` 【P1】
【文件】`docs/testing/mibao-verification-cases.md`（1428 行）、`tests/agent_eval/eval_cases.py`（85KB）
【问题】两者都是 `render_cases.py` 的生成物（文件头声明"GENERATED — DO NOT EDIT"），却提交进 git。当前与源 `.github/cases/*.yml` 同步（118=118 条 ID 一致），但**没有 CI 新鲜度检查**：一旦有人改 cases 忘重渲染，文档与用例库静默分叉（`truths.py check` 只验 truths_ref 解析，不验渲染物）。生成物是否入库属于仓库策略，本仓选择入库，可接受，但缺护栏。
【建议】加一个 CI 步骤：`python3 .github/render_cases.py ... && git diff --exit-code`（或对两生成物做 diff），保证渲染物与源永远同步；否则从跟踪中移除。

### C2. fixture JSON 录入了真实环境数据 【P1】
【文件】`tests/e2e/fixtures/customers-list.json`（真实手机号 `13456800919`、真实客户备注"首单收货地址：浙江"、真实时间戳 2026-05/06）、orders/products/after-sales 等 9 个 JSON
【问题】`e2e/scripts/record-fixtures.ts` 从真实/预发 API 录制后直接提交。虽是 mock 用途，但属于生产数据入库（隐私/合规风险），且数据会过期（页面结构一变 fixture 即失真，anti-placeholder 等质量测试会假失败/假通过）。
【建议】录制后统一脱敏（手机号/姓名/备注打码）再提交；或在 CI 中加"fixture 无真实手机号"检查；并定期重录（README 已提示 CI 录制步骤，实际未落地）。

### C3. 仓库卫生正面确认（未跟踪清单）【信息】
【文件】`.gitignore`
【问题】以下均**未被跟踪**（已核实）：`__pycache__/`、`*.pyc`、`playwright-report/`、`test-results/`、`tests/e2e/.auth/`、`coverage.json`、`growth-gate-result.json`（根与 .github 两处）、`logs/`、`.pytest_cache/`。`.github/__pycache__` 在磁盘存在但未跟踪。
【建议】无（保持现状）。

---

## D. 命名与组织

### D1. CLAUDE.md 自相矛盾：page-objects vs pages 两种路径 【P0】
【文件】`CLAUDE.md` 第 193、280 行（`tests/e2e/page-objects/`）vs 第 287 行（`tests/e2e/pages/{domain}/{page}.page.ts`）
【问题】实际目录是 `tests/e2e/pages/`，`page-objects/` 从未存在。两处互相矛盾的声明会直接误导 AI 研发创建不存在的路径。
【建议】统一为 `tests/e2e/pages/{domain}/{page}.page.ts`，修正 193/280 两处。

### D2. Page Object 大规模孤儿：13/26 个页面对象不被任何 spec 引用 【P1】
【文件】`tests/e2e/pages/` 下孤儿：`admin/employees.page.ts`、`categories.page.ts`、`dashboard.page.ts`、`knowledge/knowledge.page.ts`、`orders/order-detail.page.ts`、`orders/order-list.page.ts`、`orders/order-new.page.ts`、`orders/order-ship.page.ts`、`processing.page.ts`、`products/product-detail.page.ts`、`products/product-form.page.ts`、`products/product-list.page.ts`、`register.page.ts`
【问题】specs 已全面迁移到"fixture 内联 mock"风格（如 `orders/order-list.spec.ts`、`admin/employees.spec.ts` 全文无任何 page object import），Page Object 层被架空：13 个页面对象成为死代码，同时 CLAUDE.md 仍强制"E2E 必须用 Page Object 模式"——规范与代码脱节。
【建议】删孤儿 page object；或将 CLAUDE.md 规范改写为"spec 内联 mock 为准、Page Object 仅用于跨 spec 复用的复杂交互（chat/settings 等仍在使用）"。另 `helpers/api.helper.ts` 只被孤儿 `fixtures/base.ts` 引用，属同类问题。

### D3. `quality/` 三件套存在性确认 + 两个附加 quality spec 未入 CI 【P2】
【文件】`tests/e2e/specs/quality/anti-placeholder.spec.ts`、`api-contract.spec.ts`、`cross-page-consistency.spec.ts`（均真实有效，已入 pr-check）
【问题】同目录 `business-judge.spec.ts`（418 行）、`search-alignment.spec.ts`（160 行）是有价值的质量测试，但 pr-check 未包含 → 从不执行。
【建议】将这两个也纳入 e2e-quality-gate（成本极低）。

### D4. `.github/cases/README.md` 过期 【P2】
【文件】`.github/cases/README.md`
【问题】README 声明"12 域 80 条用例"，实际现为 **19 个 yml（18 域 + registry）、118 条用例**（9 smoke + 82 normal + 27 adversarial）；api/agents/ui/finance/misc/utils/registry 等新域未在 README 体现。
【建议】重新渲染/更新 README 的域与数量统计。

### D5. CLAUDE.md 引用 4 个不存在的 workflow 【P0】
【文件】`CLAUDE.md` 第 239、553 行
【问题】声称存在 `backend-tests.yml`、`frontend-tests.yml`、`e2e-tests.yml`、`smoke-tests.yml`，实际 workflows 里是 `ai-agent-tests.yml`、`pr-check.yml`、`e2e-real.yml`、`smoke-test.yml`。AI 研发按文档找 workflow 会扑空。
【建议】更新 CLAUDE.md 的 workflow 清单与职责描述（另：第 225/239 行的"覆盖率 ~85%/~0%"等指标也已过期，一并核对）。

### D6. e2e 命名基本达标 + 少量不规范 【P2】
【文件】`tests/e2e/specs/`（36 文件）
【问题】主体符合 `{domain}/{feature}.spec.ts`（admin/after-sales/auth/catalog/chat/customers/dashboard/orders/platform/products/quality/settings/smoke/storage 全小写 kebab 域目录）✓；但 `catalog/processing.spec.ts` 与根级 `pages/processing.page.ts` 并存（同类页面归属不一致，根级 page 尚有 categories/dashboard/login/register 等 7 个，而规范要求按域归档）。
【建议】将根级 page object 按域归档（login/register → auth、categories/processing → catalog、dashboard → dashboard），或明确根级仅放跨域基类（base/layout）。

### D7. backend pytest e2e 目录组织混乱 【P2】
【文件】`backend/ai-agent-service/tests/e2e/specs/test_tool_coverage.py`、`tests/e2e/real/`
【问题】`e2e/specs/` 下只有 1 个"specs"测试（test_tool_coverage.py），且它 import 被 pytest.ini `--ignore` 的 `tests/test_e2e_chat_flow.py` 的基础设施——依赖链脆弱（将来若删除 test_e2e_chat_flow.py，此文件直接收集失败）；"specs vs real" 分层与 pytest.ini 的 ignore 规则叠加后难理解。
【建议】将 `e2e/specs/test_tool_coverage.py` 与其依赖的基础设施一并整理（移入顶层或 real 之外的"mock e2e"命名），并在 pytest.ini 注释清楚 ignore 语义。

### D8. 配置与文档路径核对 【信息】
【文件】`backend/ai-agent-service/pytest.ini`、`tests/tsconfig.json`、`tests/package.json`
【问题】pytest.ini `testpaths=tests` 收集顶层 + unit + contracts + e2e/specs（不含 real），ignore 列表（e2e/real、test_llm_pipeline、test_e2e_chat_flow、test_multimodal_content_handling）与两个 workflow 的追加 ignore 不在一处、靠注释维护，容易漂移。tsconfig/package.json 正常。
【建议】把 ignore 清单收敛到 pytest.ini 单一来源，workflow 不再追加（或反之），并在 CI 中加"收集通过 + 0 skipped-by-default 阈值"哨兵。

---

## E. 规模问题

### E1. `product-create.spec.ts`：整文件全 skip 的死壳 【P0】
【文件】`tests/e2e/specs/products/product-create.spec.ts`（255 行，**0 active / 32 skipped**）
【问题】32 个测试全部 `test.skip`（新增商品表单的所有区块检查），文件看起来"有测试"实际一行都没跑；与其配套的 `pages/products/product-form.page.ts` 也因此成为孤儿。商品创建是核心业务，却处于零 UI 测试状态。
【建议】按当前 UI 重写（表单已大改导致全部 skip），或删除并明确"由 backend pytest test_tools_order_create 覆盖"；禁止留全 skip 文件。

### E2. `edit-render.spec.ts`：同上 【P1】
【文件】`tests/e2e/specs/products/edit-render.spec.ts`（94 行，**0 active / 3 skipped**）
【问题】整文件禁用。
【建议】重写或删除。

### E3. 超大测试文件 【P2】
【文件】`backend/ai-agent-service/tests/test_mibao_advanced_multiturn.py`（**2317 行** / 21 测试）、`test_business_verification.py`（1306 行）、`test_mibao_multiturn_intelligence.py`（1253 行 / 11 测试）、`test_xiaobu_multi_turn_scenarios.py`（819 行）、`test_e2e_mibao_scenarios.py`（653 行）、`test_e2e_chat_flow.py`（914 行 / 16 测试）
【问题】多轮/场景类测试以"巨型文件"堆叠，单文件超 1000 行难以维护与定位；且 `test_mibao_advanced_multiturn.py`（21 测试 2317 行）与 `test_mibao_multiturn_intelligence.py`（11 测试 1253 行）同主题（米宝多轮智能）并存。
【建议】按场景域拆分（每文件 ≤400 行），合并同主题文件；至少在文件头维护场景清单。

### E4. spec 其余规模正常 【信息】
【文件】`tests/e2e/specs/**` + `tests/e2e/real/**`
【问题】除 E1/E2 外，其余 spec 43~612 行，无空壳无占位（最小 pages-render.spec.ts 43 行、anti-placeholder.spec.ts 53 行，均真实有效）；`order-create.spec.ts` 10 测试中 3 个 skip（30%），建议跟进补齐。
【建议】order-create 的 skip 项评估后补跑或删除。

---

## 附：CI 实际执行矩阵（现状核实）

| 测试路径 | CI 执行情况 |
|---|---|
| backend `pytest tests/`（顶层+unit+contracts+e2e/specs，去 ignore、去 integration） | ai-agent-tests.yml + deploy-ai-agent-service.yml |
| backend `tests/e2e/real/`（pytest，真实 LLM） | e2e-real.yml（每日 00:00 定时 + 手动） |
| backend integration 标记（4 文件 113 测试 ~2920 行） | **从不执行** |
| backend test_post_deploy_verify / manual_test_pe_flow | **从不执行**（显式 ignore） |
| tests/smoke p0（7 个） | smoke-test.yml（部署后 + 复用） |
| tests/smoke p1（97 个）+ react_smartness | **从不执行** |
| tests/unit_junshi（2 文件） | **从不执行**（无引用） |
| tests/unit_dual_verify（0 测试） | 空壳，无引用 |
| tests/agent_eval local_runner（smoke 9 条） | agent-eval.yml / pr-check agent-eval-smoke / adversarial |
| tests/agent_eval eval_runner.py | **从不执行**（死代码，无引用） |
| Playwright e2e（36 spec） | pr-check 只跑 4 个文件（且因 web+chromium 项目重复各跑 2 遍） |
| Playwright real（4 spec，真实 LLM） | **从不执行**（无 workflow 调用） |
| frontend vitest | pr-check |

---

## 结论（按优先级）

- **P0（先修，影响正确性与信任）**：B1 空壳目录、B5 部署验证名不副实、B6 integration 测试从不执行、B7 smoke 只跑 7/104 + react_smartness 收集风险、D1/D5 CLAUDE.md 双重误导（路径 + workflow 名）、E1 商品创建 spec 全 skip。
- **P1（清理主力）**：A1-A3 coverage 系列刷量去重、A5 real 双套、A7 playwright 项目重复双跑、B2/B3/B8 孤儿与不执行、C1/C2 生成物护栏与真实数据入库、D2 page object 孤儿、E2 全 skip spec。
- **P2（优化）**：A4/A6 命名与合并、B4/B9 死目录确认、D3 quality 附加项入 CI、D4 cases README 过期、D6/D7 目录规范、E3 超大文件拆分、E4 跟进。
