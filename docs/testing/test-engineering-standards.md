# MIGAO 测试工程规范（2026-08-29 固化）

> 来源：2026-08 全项目审计 + 精简实战沉淀。所有新增/修改测试代码必须遵循本节规范。
> 优先级：本文档 > CLAUDE.md 相关条款（本文档是 CLAUDE.md 测试规范的细化与补充）。

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
