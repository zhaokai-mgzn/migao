# MIGAO 测试工程规范（2026-08-29 固化）

> 来源：2026-08 全项目审计 + 精简实战沉淀。所有新增/修改测试代码必须遵循本节规范。
> 本文档为测试工程规范的唯一事实来源（拆分/ignore 单一来源/数据脱敏/分层归属）。

## 0. 总原则

- **单一事实源**：同一信息只存在一处（生成物由脚本产出、ignore 清单在 pytest.ini、用例在 `.github/cases/`）。
- **可运行才有价值**：禁止"存在但从不运行"的测试（要么进 CI/调度，要么明确标注手动并归档）。
- **AI 可导航**：文件按场景域拆分、命名自解释、头部声明 `# case_ids`。

## 1. 测试文件拆分规范（大文件 ≤400 行）

> 背景：`test_mibao_advanced_multiturn.py` 曾达 2317 行，按域拆分为 5 个文件后 AI 可导航性与可维护性显著提升。

### 1.1 何时拆

- 单文件 > 1000 行，或单类 > 15 个测试 → 按**场景域**拆分（订单/商品/售后/可靠性/高级）。
- 拆分粒度：每个新文件一个 `Test<Domain>Xxx` 类，含 2~6 个同域测试。

### 1.2 shared 模块放什么（`tests/<feature>_shared.py`）

可以放：
- 纯 helper：数据构造函数（`make_*`）、runner 类（`MultiTurnRunner`）、校验函数（`verify_*`）、常量（`MOCK_*`）、`logger`。
- **必须是纯函数/类/常量，不依赖 pytest fixture。**

**禁止放**：
- `@pytest.fixture` 定义的 fixture —— pytest **只从 conftest.py 或测试模块自身收集 fixture**，放 shared 模块里不会被发现，测试会报 `fixture not found`（实战踩坑：`agent_context` 移入 shared 后 4 个测试 ERROR）。
- 依赖测试环境单例的模块级代码。

### 1.3 fixture 放哪

- 该域独有的 fixture → 测试模块自身（与测试类同级）。
- 多域共享的 fixture → `tests/conftest.py`（注意与现有 fixture 重名冲突，如已有 `agent_context` 则改名）。
- autouse 重置类 fixture（如 `_reset_singletons`）→ 测试模块自身，保留原模块级语义。

### 1.4 每个拆分文件的完整 import 集

拆分后方法体是"原样搬移"，因此**必须**携带方法体引用的全部符号，不能只依赖 shared 的导出：

```python
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from tests.<feature>_shared import (
    logger, ...  # 方法体用到的所有 helper
)
from app.agents.customer_service_agent import reset_agent   # autouse 重置用
from app.tools.registry import reset_tool_registry
```

排查手法（防 NameError）：
```bash
# LOAD_GLOBAL 静态扫描：找出方法体引用的、模块全局解析不到的裸名
.venv/bin/python - <<'EOF'
import importlib, inspect, builtins, dis
mod = importlib.import_module('tests.<module>')
globs = set(mod.__dict__) | set(dir(builtins))
for _, cls in inspect.getmembers(mod, inspect.isclass):
    if not cls.__name__.startswith('Test'): continue
    for _, fn in inspect.getmembers(cls, inspect.isfunction):
        for i in dis.get_instructions(fn):
            if i.opname == 'LOAD_GLOBAL' and i.argval not in globs and not i.argval.startswith('_'):
                print(cls.__name__, fn.__name__, i.argval)
EOF
```

### 1.5 拆分验证清单（缺一不可）

1. `py_compile` 全部新/旧文件通过
2. `pytest --collect-only`：收集数 = 拆分前总数（本仓库 1937 稳定值）
3. LOAD_GLOBAL 扫描无未定义裸名
4. **CI 实际执行通过**（LLM 场景测试本地可能挂起，以 CI 为准）

## 2. pytest ignore 清单规范（单一来源）

- **全部 ignore 只写在 `backend/ai-agent-service/pytest.ini` 的 `addopts`**，workflows 不再追加 `--ignore`。
- 每条 ignore 必须带注释说明原因（环境依赖/手动脚本/共享基础设施）。
- 被 ignore 但被其他测试 import 的文件（如 `test_e2e_chat_flow.py`），**文件头必须标注"共享基础设施，勿删"**。

## 3. E2E fixture 数据规范

- **录制即脱敏**：`record-replay.ts` 的 `maskSensitiveData` 对 11 位手机号做确定性掩码（同源→同掩码，保持跨文件一致）。手写 fixture 同样需脱敏。
- **重录机制**：`fixture-record.yml`（月度 + 手动）从 dev API 重录，变更自动开 PR；重录产物已脱敏。
- fixture 应避免含真实客户备注/地址等隐私数据。

## 4. 测试分层与归属规范

| 层 | 位置 | 调度 |
|---|---|---|
| 单元测试（mock） | `backend/ai-agent-service/tests/` | 每次 PR（ai-agent-tests.yml） |
| 契约/枚举对齐 | `tests/contracts/` | 每次 PR |
| integration（真实环境） | `tests/e2e/real/` + 4 个 integration 文件 | 每日 e2e-real.yml |
| Playwright fixture 层 | `tests/e2e/specs/`（`--project=web`） | PR quality 门禁 + 夜间全量 |
| 冒烟 p0/p1 | `tests/smoke/` | p0 部署后；p1 夜间 |
| 手动脚本 | `tests/manual/`（无 test_ 前缀） | 人工按需 |

- **禁止**：真实环境测试标 `integration` 标记却被 `-m "not integration"` 排除后无任何调度（归属到 e2e-real 每日跑）。
- **禁止**：Playwright 与 pytest 双套 1:1 重复同一批工具（真实 LLM 能力验证以 pytest API 层为准，2026-08-29 已删 Playwright real 层）。

## 5. case_ids 规范（G5 铁律补充）

- 新增/修改测试文件头部必须声明 `# case_ids:`，ID 必须是 `.github/cases/` 中存在且语义相关的用例。
- 拆分/改名后原 case_ids 集合必须完整保留并分配。
- 用例库无对应域时，选语义最近的现有用例并注释说明（如登录页测试用 `DF-014` 认证安全用例）。
- 改 `.github/cases/*.yml` 后必须重渲染生成物（`render_cases.py`）并提交（CI 有 render+diff 护栏）。

## 6. 单测外部依赖隔离（2026-09-06 固化，issue #2957 本地验证恶化根因）

**原则**：单测（`backend/ai-agent-service/tests/` + `tests/unit/` + `tests/test_*.py`）**不得真实连接外部存储/API**。

**为什么**：本地 `.env` 的 DATABASE_URL/REDIS_URL 指向云 dev（阿里云 RDS/Redis 公网地址）。单测一旦真实连接：
- 每用例挂起/超时数十秒（公网链路/安全组拦截），数百用例 → 本地 pytest 从分钟级恶化到小时级（实测 `verify-all.sh quick` 58min 未完成）；
- 恶化是**渐进累积**的：每次新增依赖（SessionStateStore/SessionMemory/context_manager 等）多几个未 mock 调用，无单点故障，难察觉；
- CI 无 `.env` → 一直正常，掩盖问题；本地慢 CI 快 = 环境差异信号，不是业务代码问题。

**强制要求**：
1. 新增测试若涉及存储/外部调用，必须 mock（`@patch`/`AsyncMock`/fixture），不得走真实连接路径。
2. `tests/conftest.py` 必须保留存储地址兜底（**已固化于 #2960，勿删**）：
   ```python
   os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test_db")
   os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
   ```
   环境变量优先级高于 `.env` 文件 → 单测内未 mock 连接毫秒级拒绝、走调用方降级；CI/集成测试显式注入真实 env 时 setdefault 不覆盖。
3. 新增依赖/重构工具链路后，**同步检查既有测试的 mock 面**：`grep -rn "SessionStateStore\|SessionMemory\|get_context_manager" tests/`，新调用点必须被 mock 或 conftest 兜底。
4. 验收信号：`pytest -q --durations=20` 单用例 >2s 即可疑；整文件应秒级完成。

**排查路径**（本地验证变慢时）：
```bash
pytest -q --durations=20   # 找最慢用例
# 慢用例日志若含 Connect call failed / Connection timeout / redis down / 云库域名 →
# 未 mock 真实调用泄漏，补 mock（不要在慢用例上堆 sleep/fixture 绕过）
```

## 7. 前端交互测试断言规范（2026-09-09 固化，issue #3070 知识库 UI 复盘）

**原则**：交互旅程测试断言「用户可见的结果」，禁止停留在「函数被调用」。
「按钮点了 API 通了」≠「用户看到成果物」——#3070 的模板套用/候选采纳两个 bug
正是 API 调用全成功、但列表不刷新/不跳转，用户完全看不到结果。

**强制要求**：
1. 点击类测试必须断言点击后的**可见结果**（按操作类型选）：
   - 列表刷新：`<api>` 再次被调用 **且** 新条目渲染在 DOM（`getByText(新条目标题)`）；
   - Tab 跳转：目标 Tab 内容渲染（断言目标内容元素，而非只断言 setState 调用）；
   - 弹窗：打开且回填（`getByDisplayValue` 断言表单值）；
   - 成果物去向：新建/套用/采纳/发布后的条目出现在列表首屏或跳转后的页面；
2. 禁止只写 `expect(api.xxx).toHaveBeenCalled()` 作为交互用例的终点断言；
   该断言仅可作为前置条件（确认触发），必须另有「结果可见」断言。
3. 布局/视觉类断言（fixed 遮挡、CSS 级联覆盖、min-h/padding 计算）**不得用 vitest 硬写**
   ——jsdom 是结构性盲区（#3070 实测 `p-4 pb-24` 的 paddingBottom 被简写覆盖，jsdom 不可见）。
   这类验证走真实浏览器几何探针（migao-dev-flow §15.2 / frontend-acceptance-checklist §8）。
4. 范例（正向参照）：`frontend/admin-web/tests/unit/pages/knowledge.test.tsx`
   「套用后可见可编辑」「采纳后可见可编辑」——断言跳转 + 列表刷新 + 卡片可见 + 编辑弹窗回填。
