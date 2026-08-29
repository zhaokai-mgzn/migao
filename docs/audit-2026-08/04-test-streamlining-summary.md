# migao 测试用例精简 — 执行总结（2026-08-28）

> 依据 `.audit/tests-audit.md`（完整审计报告）实施。所有删除均经引用闭包验证 + 测试运行验证。

## 结论：测试用例可以精简，且已实际精简

原始 1284 个跟踪文件中，测试体系存在**大量"存在但无价值 / 存在但不运行"**的文件。
已删除 17 个文件、重命名 3 个、启用 36 个被静默禁用的真实测试、修复 1 处 CI 双跑、脱敏 19 个真实手机号。

## 已完成的精简

### 1. 删除刷量型 coverage 测试（6 个文件，92 个测试）
这些文件是"覆盖率缺口"刷量产物（issue #576-#583），全仓无覆盖率 fail-under 门禁，纯增 CI 运行时间与 AI 上下文噪音：

| 文件 | 测试数 | 问题 | 处置 |
|---|---|---|---|
| `test_tools_coverage_pt1.py` | 9 | 全部 `class_exists`（`assert X is not None`） | 删除 |
| `test_tools_coverage_pt2.py` | 11 | 7 个 class_exists + 4 个 registry（与 test_tools_registry.py 重复） | 删除 |
| `test_tools_coverage_pt3.py` | 14 | class_exists + ToolContext/Result 基础（与 test_tools_base.py 重复） | 删除 |
| `test_utils_coverage.py` | 32 | 与 test_utils_log_sanitizer(14)/field_mapper(18)/database/http_client/auth/redis 六文件重复 | 删除 |
| `test_misc_coverage.py` | 17 | 与 test_memory_extractor/intent_classifier/rule_matcher 重复 | 删除 |
| `test_misc_pt1_coverage.py` | 9 | 与 test_llm_retry_policy(19)/test_llm_cost_tracker 重复 | 删除 |

### 2. 删除重复的 unit/ 旧版测试（3 个文件，22 个测试）
顶层 8/25 新版与 unit/ 8/13 旧版同名并存，顶层为超集：

| 文件 | 处置 |
|---|---|
| `unit/test_tools_order_create.py`（4 测试） | 删除（顶层 333 行版已覆盖权限/成功/失败/网络错误） |
| `unit/test_tools_dashboard_stats.py`（6 测试） | 删除（顶层 314 行版已覆盖） |
| `unit/test_tools_order_create_customer.py`（12 测试） | 删除（顶层已覆盖 guest 拒绝/客户 SMS 全流程） |

### 3. 删除空壳目录（1 个）
- `tests/unit_dual_verify/`（仅 __init__.py + conftest.py，0 测试，全仓无引用）

### 4. 启用被静默禁用的真实测试（+36 个测试）
- `tests/test_skill_skills/base_skill.py` → 改名 `test_base_skill.py`
  - **问题**：36 个真实测试（确认守卫/思考标签剥离/成本追踪等），因文件名不匹配 `test_*.py` 被 pytest 永不收集
  - **修复**：git mv 后立即进入收集集（36 passed ✓）

### 5. 重命名误导性文件（2 个，保留价值）
- `test_api_coverage.py` → `test_api_chat_helpers.py`（63 个真实行为测试，原名掩盖内容）
- `test_skill_routing_coverage.py` → `test_skill_routing_integrity.py`（8 个真实不变量测试）

### 6. 修复 Playwright CI 双跑（tests/playwright.config.ts）
- `web` 与 `chromium` 两个 project 筛选结果完全等价 → 删除 `chromium` project
- 原 `npx playwright test` 每个 spec 跑两遍，现 417→382 个测试单遍执行

### 7. 删除死链 e2e 资产（11 个文件）
- **孤儿 page object × 13**：`products/product-{detail,form,list}`、`register`、`admin/employees`、`categories`、`knowledge/knowledge`、`dashboard`、`orders/order-{detail,list,new,ship}`、`processing`（唯一消费者 `fixtures/base.ts` 自身无人引用）
- `fixtures/base.ts`（22 个 page 的死聚合器，0 引用）
- `helpers/api.helper.ts`（仅被 base.ts 引用）
- **全 skip spec × 2**：`product-create.spec.ts`（32 skip）、`edit-render.spec.ts`（3 skip）——整文件 0 active，UI 已改版

### 8. fixture 数据脱敏（7 个 JSON，19 个手机号）
- `customers-list/orders-list/after-sales-list/employees-list/products-*/orders-detail` 中真实手机号（13456800919 等）确定性掩码化
- 确定性映射（同源→同掩码）保持跨文件一致性，不破坏 cross-page-consistency/api-contract 测试

## 验证结果

| 验证项 | 结果 |
|---|---|
| pytest 收集（ai-agent） | 2018 → 1941（-114 删 + 36 新启用 + 重命名）✓ |
| 受影响领域单测（tools/utils/llm/api/unit/contracts） | **1091 passed** ✓ |
| 新启用 base_skill | 36 passed ✓ |
| 重命名文件 | 71 passed ✓ |
| Playwright config 加载 | 382 tests / 33 files 单遍 ✓ |
| 残留孤儿引用扫描 | 0 ✓ |

> 注：全量套件中部分 LLM 场景测试（`test_e2e_mibao_scenarios`、`test_mibao_advanced_multiturn` 等）在**本地无 CI env** 时挂起（预存在问题，CI 有 `DEEPSEEK_API_KEY` 等 env 可跑），与本次精简无关，未触碰。

## 未实施（需决策）

| 项目 | 建议 |
|---|---|
| `test_mibao_scenarios.py`（494 行脚本伪装测试，0 收集） | 移入 `scripts/` 或改为真 pytest 用例（P2） |
| `tests/unit_junshi/`（32 个真实测试无人运行） | 接入 CI 跑（P1，已验证可跑） |
| smoke `p1` 97 个测试不进 CI | 新增 nightly workflow 跑 p1（P1） |
| integration 标记 113 个测试（~2900 行）永不执行 | 明确归属：mock 化降级 / 移入 e2e/real / 删除（P0） |
| 28 个 e2e fixture spec 不进 CI（仅 4 个在 pr-check） | 分层：quality 门禁 + weekly 全量（P1） |
| `test_post_deploy_verify.py` 承诺"部署后自动跑"实为 ignore | 二选一：真正接入或标注手动（P0） |
| 生成物（mibao-verification-cases.md / eval_cases.py）无新鲜度门禁 | CI 加 `render_cases.py && git diff --exit-code`（P1） |
