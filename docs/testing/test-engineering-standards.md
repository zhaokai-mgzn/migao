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

### 3.1 脱敏的作用域铁律：**记忆/落库保原文，只脱敏出站展示层**（issue #3386）

事故（DB 实证，run 34742490138）：图谱层在返回前把 `final_content` 脱敏成 `138****8000`，
而 `final_answer` **同时是落库 assistant 消息的来源**（= 模型下一轮读到的自己的历史）
→ 模型读到残缺值后把 `****` 填成 `0`，用 `13800008000` 调 `order_create`；
11 位纯数字通过了格式校验 → 订单 `20260913384380002` 的 `customer_phone` 被**静默写错**，
顾客收不到短信与配送联系，全链路无告警。

- **禁止**在任何"写回会话/落库/喂给模型"的路径上脱敏（图谱 `final_content`、
  `save_message`、工具返回、写入工具入参）；
- **必须**在顾客可见的出站面脱敏：SSE 文本/卡片（`app/api/chat.py` 的
  `_mask_for_customer` / `_mask_card_for_customer`）、C 端 `GET /history` 回放
  （小程序刷新页面就是这条路径）；
- B 端（商家/客服）**不脱敏** —— 客服要打电话给顾客，脱敏会破坏运营；
- 写工具侧兜底：模型若真把掩码值填回写工具（`138****8000`、或星号填 0 的
  `13800008000`），`_masked_phone_write_block` 会拦下并回放本会话已知真号；
- 断言侧：`check_phone_provenance`（全局）要求落库手机号可追溯到用例给的号码/种子号码；
  需要精确核对的用例再写 `db_verify: [{fetch: order_phone, expect_phone: …}]`；
- 自查：新增脱敏逻辑时先问"这一层是**展示面**还是**记忆面**"——分不清就别做，
  脱敏多做一层就可能把展示层的残缺值变成记忆层的脏数据。

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

## 8. 红证卫生：注入前后清缓存 + 内容指纹自证（2026-09-18 固化，issue #4260）

**这条管的是「取红证的动作」本身** —— 它出在**证据生成层**：这一层是用来抓其它所有问题的。
`migao-acceptance` 要求「**每条断言都要有红证（不会红的断言 = 空断言）**」，而**红证的可信度
此前没有任何东西保护**。

### 8.1 病根：同秒同长度替换 ⇒ 复用旧 `.pyc`（实测）

「注入缺陷 → 跑测试 → 应红 → 还原」里，改前/改后**同字节长度**的文件在**同一秒内**替换时，
Python 的 `.pyc` 头只记 `(mtime 秒, size)` 两项 —— 两者**都没变** ⇒ 解释器**不重编译**、直接复用旧
`.pyc` ⇒ **注入未生效**，而测试读到的是**旧行为**。两个后果都很难看：

- **假绿证**：注入没生效 ⇒ 测试仍绿 ⇒ 误判「这条判据不会红」（结论是"空断言"，其实是注入失败）
  ⇒ 可能把一个**本来有效**的护栏当废的删掉/放宽；
- **假红证 / 错归因**：读到旧值下的红 ⇒ 把红归因给没生效的注入，写出错误的因果。

**它是「依赖时间粒度做新鲜度判定」这一族的成员**（与 §19.2 ③「不写死易变数字」同族）：
只要判据依赖 mtime/大小/序数这类**易变或粒度不足**的键，就有被静默掩盖的空间。

### 8.2 正确动作（固化成脚本，不靠每个 agent 自觉）

```bash
# ① 记基线（内容指纹，非 mtime/size）
python3 scripts/red_proof.py fingerprint --json <file>... > /tmp/red_proof.json
# ② 注入缺陷（同秒同长度也没关系）
# ③ 自证「注入真的生效了」+ **清缓存**（未生效 ⇒ 非零退出，绝不静默跑测试）
python3 scripts/red_proof.py injected --manifest /tmp/red_proof.json
# ④ 跑测试，取红证（此时读到的一定是注入后的真值）
# ⑤ 还原
# ⑥ 自证还原干净 + **再清一次缓存**（否则下一轮取的是本轮残留）
python3 scripts/red_proof.py restored --manifest /tmp/red_proof.json
```

三条不可省的纪律：

1. **判据只用内容指纹**（`content_fingerprint` = 文件内容的 sha256）：**禁止**用 mtime / 文件大小
   判「注入生效了没」—— 那正是本缺陷的形态。还原校验同理（指纹必须回到基线）。
2. **注入自证要 fail-closed**：注入后**先**断言内容确实变了（可与声明的预期指纹比对），**再**跑测试。
   否则「注入没生效」与「这条判据是空的」不可区分 —— 这正是假绿证的来源。
3. **清缓存是动作，不是自觉**：注入前清一次（去掉上一轮残留）、注入后清一次（去掉本轮注入前的产物）。
   `--no-clear` 只用于**诊断**：它会报告「运行时会复用哪个旧产物」并**非零退出**，而不是继续跑。

### 8.3 各载体的缓存目录（同族不止 Python）

| 载体 | 缓存/产物 | 说明 |
|---|---|---|
| Python `.pyc` | `__pycache__/`、`*.pyc`、**`sys.pycache_prefix` 的真实落点** | 见 8.4：落点可能在仓库**外** |
| Python 测试缓存 | `.pytest_cache/`、`.mypy_cache/`、`.ruff_cache/` | |
| JS/TS（Next/Vite/Vitest/Jest） | `.next/cache/`、`node_modules/.cache/`、`node_modules/.vite/`、`.turbo/`、`.jest-cache/`、`.parcel-cache/`、`*.tsbuildinfo`、`.eslintcache` | 快速重复写同一文件时转换缓存同理 |
| Java `.class` | `target/classes/`、`target/test-classes/`、`build/classes/` | 增量编译下定向跑单测 + 手工注入时可能跑到旧 class |
| Shell / 生成物 | —— | 不依赖 mtime 精度：一律用**内容指纹**判新鲜度 |

**能力边界（照实登记，别把「登记了」读成「治住了」）**：`scripts/red_proof.py` 按**目录/文件名白名单**
清缓存（上表左列即白名单）；Java 侧**不覆盖**自定义 `outputDirectory` 与 Gradle 变体目录，
JS/TS 侧不解析框架版本 —— 这些是**登记项**，遇到时按 8.2 的内容指纹 + 手工清对应目录处理。

### 8.4 实测盲区：`rm -rf __pycache__` 可能是**空操作**

`sys.pycache_prefix`（或 `PYTHONPYCACHEPREFIX`）非空时，`.pyc` **落在仓库外**。
本机实测（macOS 系统 python3）：`sys.pycache_prefix` = `~/Library/Caches/com.apple.python`，
`scripts/` 下**根本没有 `__pycache__` 目录** ⇒ 一条 `rm -rf __pycache__` 看起来"做了清缓存这件事"，
实际什么都没删，而 `.pyc` 头仍与源文件一致 ⇒ 注入照样被掩盖。

⇒ 清缓存必须按 `importlib.util.cache_from_source()` 的**真实落点**做（`scripts/red_proof.py` 已这么做）。
同族形态：**「做了清缓存这个动作」不等于「缓存被清了」** —— 凡"清理/复位"类动作都要有**清完之后的断言**
（`assert_caches_clear`：清完仍剩产物 ⇒ fail-closed），否则它只是一个**看起来像清理的空操作**。

### 8.5 自证红证

- 判别力红证（同秒同长度替换 ⇒ 旧值 / 清缓存后 ⇒ 真值 + 三处 fail-closed 的变异验证）：
  `tests/unit_ci_workflows/test_red_proof_guard.py`。
- 本节的判据**未接 CI required check**：现为取红证流程 / 人工调用（照实登记，勿读成"有硬门禁"）。
