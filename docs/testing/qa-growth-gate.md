# QA Growth Gate

CI 门禁系统，在 PR 合并前自动检查代码变更是否配备了对应测试。

**缺测文件 → CI 红 → 合并按钮失效**（block 模式）。

## 检查规则

### 变更文件 → 测试要求

| 变更文件 | 要求 | 级别 |
|---------|------|------|
| `app/tools/*.py` | `test_tools_*` 或 `tests/e2e/real/` | ❌ block |
| `app/graph/*.py` | `test_graph_*` 或 `test_skill_*` | ❌ block |
| `app/agents/*.py` | `test_agent_*` 或 `test_intent_*` | ❌ block |
| `controller/*.java` | `*ControllerTest.java` | ❌ block |
| `service/*.java` | `*ServiceTest.java` | ❌ block |
| `mapper/*.java` | `*MapperTest.java` | ❌ block |
| `security/*.java` | `SecurityConfigTest` / `JwtTokenProviderTest` | ❌ block |
| `entity/*.java` / `dto/*.java` | API contract E2E | ⚠️ warn |
| `components/*.tsx` | `tests/unit/components/` | ❌ block |
| `app/*` (页面) | `tests/e2e/specs/` + PAGES 注册 | ❌ block |
| `lib/*.ts` / `store/*.ts` | `tests/unit/lib/` / `store/` | ❌ block |
| `terraform/*.tf` / `.github/workflows/*.yml` | smoke test | ℹ️ info |

### 自动通过

以下文件类型自动跳过检查：测试文件（`*Test*`、`*spec*`、`tests/`）、文档（`*.md`）、配置（`.gitignore`、`.env.example`、`*.xml`、`*.json`、`*.lock`）、SQL（`*.sql`）、图片（`*.png`、`*.jpg`、`*.svg`）。

## 如果 PR 被阻塞

### 1. 补测试（推荐）

为变更文件补充对应测试。参考各模块测试规范：

- **Java 后端**: JUnit 5 + MockMvc，参考 `backend/admin-api/src/test/`
- **Python AI 服务**: pytest，参考 `backend/ai-agent-service/tests/`
- **前端**: Vitest，参考 `frontend/admin-web/tests/unit/`

### 2. 申请豁免（仅限预存代码）

如果文件是预存代码（非本次 PR 新增），且当前无法补测，在 `.github/qa-exemptions.yml` 中添加：

```yaml
exemptions:
  - pattern: "backend/admin-api/src/main/java/com/migao/admin/controller/LegacyController.java"
    type: legacy
    reason: "预存代码，仅做路由转发。Issue #xxx 跟踪补测。"
    expires: "2026-09-01"
```

⚠️ **`legacy` 豁免必须通过 PR review 审批**，不能单方面添加。
⏰ 豁免有过期时间，过期后需重新评审。

## 覆盖率阈值（后续上线）

| 模块 | 语言 | 目标阈值 |
|------|------|---------|
| admin-api | Java | 60% |
| ai-agent-service | Python | 60% |
| admin-web | TypeScript | 60% |

覆盖率门禁当前尚未激活（基线建立中）。待各模块覆盖率报告稳定后升级为 block。
