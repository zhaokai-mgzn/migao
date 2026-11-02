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

## 9. 判据形态：**文本形态断言** = 空断言高危（2026-10-14 固化，issue #6876 自查产出）

**这条管的是「判据钉的是形态还是行为」** —— 它出在 §8 的**上游**：§8 保证「红证是真的」，
本节保证「**注入的坏形态真的等价于要防的那种坏**」。两条合起来才撑得住
`migao-acceptance` 的「**每条断言都要有红证（不会红的断言 = 空断言）**」。

### 9.1 病根：坏形态有**第二种写法**，而判据只钉了第一种（实测）

某包要防「出现第二份短码分配器」，类级守卫第一版写成**文本形态**断言：

```java
// ❌ 只在坏形态恰好按你预想的写法写时才红
assertThat(src).doesNotContain("for (int i = 0; i < MAX_ALLOCATE_ATTEMPTS; i++)");
```

注入方把循环上界换成**字面量** `8`（不再引用那个常量）：**坏行为一字未变**（仍是第二份分配器、
仍绕过唯一事实源），而判据**照样绿**；清缓存 + clean 重编后**仍绿**。
⇒ 这**不是** §8 的「注入没生效」，而是**判据本身是空断言**（它从来没在判那件事）。
两个层次要分清：§8 治「红证可不可信」，本节治「**判据在不在判**」。

### 9.2 判别式（一句话）

**这条判据钉的是「这段代码做了什么 / 引用了哪个单一事实源」，还是「这段文本长什么样」？**

- 钉**行为 / 引用关系** ⇒ 换个写法仍然红（真判据）；
- 钉**文本形态** ⇒ 只有「坏形态恰好按你预想的写法写」时才红 ⇒ 一旦存在第二种等价写法，它就是空断言。

### 9.3 正确动作（三步，缺一不可）

1. **优先钉语义动作**：引用关系（是否引用分配上限常量 / 是否调用 `randomCode()`）、**唯一事实源**
   （同一常量 / 同一函数 / 同一 mapper 方法）、调用计数（出现第二份实现 ⇒ 计数 2）、
   副作用（写入行数、外呼次数）。本案最终钉法 = 「是否引用上限常量」+「是否自调 `randomCode()`」
   两条**语义动作**判据（那条文本形态断言被替换掉）。
2. **只能文本形态时，必须再注入一次「换个写法的等价坏形态」**（等价 = 坏行为相同、写法不同）：
   常量 ⇄ 字面量 · `for` ⇄ `while` ⇄ `IntStream` · `if (x == null) return;` ⇄ `Optional` · 同一 SQL 换写法。
   **等价坏形态仍绿 ⇒ 判据无效**，回去改钉语义动作；**不许**靠堆正则 / 堆关键字充数。
3. **红证按 §8 走**（内容指纹 + 清缓存 + fail-closed 自证），并把**注入的坏形态原文**写进 PR body ——
   否则复算者无法复现「到底注入了什么」，也就无从判断这条红证的判别力。

### 9.4 边界（照实登记，别把"这次抓到了"读成"以后都抓得到"）

语义动作判据**也可能**被绕过（把那个常量复制成第二个常量、反射调用、字符串拼接后再调）
⇒ 覆盖是**概率**不是**证明**；可叠加的组合（**引用关系 + 唯一事实源 + 调用计数**）判别力强于任何单条。
同族形态：§8.4「做了清缓存这个动作 ≠ 缓存被清了」、§7 前端交互断言 —— 共同本质 =
**「看起来在判」≠「真的在判」**。凡「断言里出现的是字面量文本」或「一条断言只做一次动作」的判据，
都要先过一遍 9.2 的判别式。

### 9.5 自证

- 本案留痕：`backend/admin-api/src/test/java/com/migao/admin/service/ShortCodeAllocatorSingleSourceGuardTest.java`
  （由文本形态改成语义动作后，两种等价坏形态在内存对照臂里各自判红；注入复跑具名报红），
  出处 = issue #6867 的 B1 包（PR #6876）自查。
- 本节的判据**未接 CI required check**（同 §8.5：现为流程 / 人工调用；照实登记，勿读成"有硬门禁"）。

## 10. 「返回值即契约」：mock 的默认返回值会变成业务事实（2026-11-03 固化，issue #6274）

### 10.1 规则

当某个既有方法的**返回值从「无意义」变成「契约」**（例：`update(...)` 的受影响行数 `1` = 号归我 /
`0` = 刚被抢 ⇒ 换号重试），**同一个 PR 内**必须扫出**所有** mock 该方法的夹具并**显式桩值**；
判据取向 =「返回值被业务读取、却没有显式桩值」即可疑。默认值 `0` / `false` / `null` 在业务上会被
读成「失败 / 被抢 / 不存在」，而不是「未设置」。

**机械口径：mock 的默认返回值不得被断言当成契约事实** —— 契约事实必须来自**真实现**
（真库 / 真装配）或**显式夹具**（显式 `thenReturn(...)` 的桩值）；「没桩」不等于「没发生」。

### 10.2 为什么：5 条与批次号无关的用例在 CI 上整片红（逐字）

#6248 把「判占用 + 占用」并成一条语句后，`stockBatchMapper.update(...)` 的**受影响行数**成为契约。
Mockito 对 `int` **默认返回 `0`** ⇒ 5 条与批次号**毫无关系**的既有用例把「每次都被抢」当成事实
⇒ 20 次重试耗尽 ⇒ **409**：

- `WorkerInboundServiceTest` ×2 · `AutoBatchMountPointTest` ×2 · `WorkerInboundControllerTest` ×1；
- 症状指向错误方向（看起来像「过账功能坏了」），实际是**夹具前提被新契约改写**；
- 修法（已落地）：三个驱动过账的 mock 夹具 `setUp` 把该调用桩成 `1`，注释写明契约来源：
  ```java
  // 批次号取号（issue #6248）= `stockBatchMapper.update(...)` 的**受影响行数**（1 = 号归我）。
  when(stockBatchMapper.update(any(StockBatch.class))).thenReturn(1);
  ```
  本机复跑 7 个类 ⇒ **172 tests / 0 failures**。

### 10.3 怎么判

1. **同 PR 扫夹具**：先现取「候选面」= 所有 mock 了该类型 / 驱动到该路径的夹具，再逐文件确认桩点显式
   给出了 `1` / `0` 的语义 —— **「没桩」的夹具不会出现在任何 `when(...)` 里**，只能靠候选面逐个点：
   ```bash
   grep -rln "StockBatchMapper" backend/admin-api/src/test/java   # 候选面：一个都不能少
   ```
   粗筛（只当线索；跨行写法 `.when(bean).method(...)` 会误命中 / 漏判，本仓实测 3 处）：
   ```bash
   grep -rn "when(.*stockBatchMapper" backend/admin-api/src/test/java | grep -v "thenReturn"
   ```
2. **契约写进方法 Javadoc**（`@return 受影响行数 = 契约：1 / 0`），让下一个改名的人先读到；
3. **反向显式化**：某条用例若**依赖**默认值表达「失败」，必须显式写 `when(...).thenReturn(0)` ——
   「沉默的默认值」与「显式声明」在回归时的可读性完全不同；
4. **现有守卫**：**无**（如实登记 —— 本轮只落规范；机械元守卫「返回值为契约而未显式桩值即红」未实装，
   重启条件 = 同形态第二次复发，届时按 §9.3 钉**语义动作**而非文本形态）。

### 10.4 反例

```java
// ❌ 新契约下什么都没桩：Mockito 默认 0 ⇒ 业务读成「每次都被抢」⇒ 重试耗尽 409
@Mock private StockBatchMapper stockBatchMapper;
// setUp 里没有 when(stockBatchMapper.update(any())) —— 这条用例与批次号毫无关系，CI 上却红

// ✅ 显式声明这次调用「号归我」：读用例的人一眼看到前提
when(stockBatchMapper.update(any(StockBatch.class))).thenReturn(1);
```

## 11. 真库判据**不得共享可变全局占位**（号段 / 自增 / 租户内唯一键）（2026-11-03 固化，issue #6274）

### 11.1 规则

同一个真库上跑的多条判据**不得共享可变全局占位** —— **真库判据必须各用独立号段 / 区间，或用事务回滚，
不许共享自增号段**。凡**故意耗尽**某范围（号段 / 自增 / 唯一键）的判据，必须与其他判据**隔离到不同区间**，
且**至少按一种与执行顺序无关的方式自证**（例如强制方法名字典序复现 CI 的红序）。「期望成功」的判据
**不得从 0 起步** —— 它的重试预算不得被别人故意耗尽的范围吃掉。

### 11.2 为什么：判据 ③ 占满头部，吃光判据 ⑥ 的 20 次重试预算（CI 逐字）

`BatchNoTakeRaceRealDbTest` 的判据 ③（`restartIntoAnOccupiedHeadFailsClosedInsteadOfSilentlyReusing`）
**故意**占满当天头部 `0001..0020`（造「重启落在已占头部」），而生产重试上限**恰好 20**；
判据 ④/⑥ 期望成功却从 `0` 起步 ⇒ 候选一路撞在**既有占用**上、20 次重试被吃光 ⇒ 成败取决于线程交错
（判据 ④ 在 CI 里靠 `0021/0022` 擦线过）。CI 逐字（issue #6274 正文引用了同一条读数）：判据 ⑥ 红 `expected: 2L but was: 1L`，读数：

```
[READING #6248 ⑥ 零注入 round 1] 成功数=1 状态码=[200, 409] 落败异常类型=[BATCH_NO_EXHAUSTED]
批次行=1 批次号=[PC-20261003-0023] 单终态=[posted, draft]
```

修法 = `SAFE_START = 5000`：三条**期望成功**的判据（①/④/⑥）从它起步，两条**故意耗尽**的（③/⑤）保持 `0`。
自证 = 同一份判据按「默认顺序」与「**强制方法名字典序**（③ 先于 ⑥ = CI 的红序）」各跑一次 ⇒ 均 **6/6**。
源码里这段约束写进了 `resetBatchSeq(int)` 的 Javadoc（`BatchNoTakeRaceRealDbTest.java`；
下面是去掉 Javadoc 标记后的摘录）：

```
⚠️ 期望成功的判据必须用 SAFE_START 而不是 0（本判据在 CI 上就是这样红过的）：
判据 ③ 会把当天头部 0001..0020 占满，而重试上限恰好是 20 ⇒ 从 0 起步的请求会把 20 次重试
全部耗在被占的头上 ⇒ 显式 409。取一个远离头部的位置，判据就与执行顺序无关。
```

### 11.3 怎么判

1. **区间常量**：每个真库判据类必须显式声明它使用的起始位置 / 区间（如 `SAFE_START`、`RESERVED_RANGE`），
   并写明「本判据是否故意耗尽某区间」；
2. **区间不相交**：「故意耗尽」的判据独占区间；「期望成功」的判据从 `SAFE_START` 起步；
3. **登记**：新增真库判据必须同批登记进 `tests/unit_ci_workflows/test_realdb_failclosed.py` 的
   `REALDB_FILES`（现取：`backend/admin-api/src/test/java/com/migao/admin/service/BatchNoTakeRaceRealDbTest.java`
   → `direct`），否则真库 fail-closed 判据①红；
4. **自证**：至少跑两种执行顺序（默认 + 强制字典序）各一次，均全绿才算「与执行顺序无关」；
5. **现有守卫**：`test_realdb_failclosed.py` 只保证「真库判据被登记 / 缺真库时 fail-closed」，
   **不判**区间是否相交（如实登记：区间相交的机械元守卫未实装，重启条件 = 同形态第二次复发）。

### 11.4 反例

```java
// ❌ 期望成功的判据从 0 起步：兄弟判据把 0001..0020 占满时，20 次重试预算被吃光 ⇒ 看线程交错
resetBatchSeq();                                  // 0
assertThat(post(...)).isEqualTo(200);

// ✅ 期望成功用 SAFE_START（远离被故意耗尽的范围）；只有故意耗尽的判据才用 0
resetBatchSeq(SAFE_START);                        // 5000
assertThat(post(...)).isEqualTo(200);
```

## 12. 判据**不得写坏共享工作树**：注入走文本参数，不落盘（2026-11-03 固化，issue #8415）

**出处**：issue #8415 → 修法 PR #8482（**已 MERGED**，main 合并提交 `6e158ffd1`）；本节只固化口径，判据本体不在本 PR。

### 12.1 规则（可被 checkout 执行）

**判据运行期禁止把任何变异 / 坏形态写回仓库工作树** —— 包括「写入 → 断言 → `finally` 还原」；
注入式用例一律把变异**当文本参数**传给被测函数，落盘只许写 `tmp_path`。

### 12.2 为什么：CI 用 `-n 4`，写回窗口内别的判据会读到变异体（实测）

`tests/unit_ci_workflows/test_worker_h5_auth_failure_copy.py::test_injection_unwired_case_file_is_red`
原实现把 `.github/workflows/worker-h5-tests.yml` **写回真实工作树**、判完再还原：

```python
# 修前（旧实现，issue #8415 的病灶）
WORKFLOW.write_text(broken, encoding="utf-8")
problems = copy_defects(_api_text(), _production_auth_failed_message())
WORKFLOW.write_text(orig, encoding="utf-8")     # finally 里还原
```

而 `ci workflow helper unit tests` 跑的是 **`-n 4`**（`.github/workflows/pr-check.yml` 的
`python -m pytest tests/unit_ci_workflows -q … -n 4`）⇒ 「写回」窗口内，**任何**读同一份 workflow
的判据都会读到变异体。受害判据 `test_real_source_has_no_login_failure_copy_defect` 红在一条与登录
文案无关的问题上（逐字）：

```
AssertionError: 登录失败文案的类级判据判红：
  - worker-h5-tests.yml 不再跑 `node --test frontend/worker-h5/tests/*.test.mjs`（实例判据会退回死文件）
```

放大复现（`-n 2` 只挑「读方 + 写方」两条，跑 40 次）：修前 **39/40 红**，修后 **40/40 绿**。
旁证（durable）：`.github/flaky-ledger.json` 的 run `39927788364` 条目里，**同一次**失败的
`failing_tests` 同时含 `test_worker_h5_auth_failure_copy.py::test_real_source_has_no_login_failure_copy_defect`
与 `test_worker_h5_ci_wiring.py::test_red_proof_continue_on_error[step]` —— 两条读的是**同一份**
`worker-h5-tests.yml`（后者只读不写 ⇒ 它是受害者，不是共犯）。

### 12.3 怎么判（现有守卫 + 机械写法）

1. **文本注入**：被测函数签名带 `workflow_text: str | None = None`，缺省读真实文件
   （= 生产判定路径**不变**），注入用例显式传文本；并追加一条「变异没泄漏到真实文件」的断言：

   ```python
   assert WORKFLOW.read_text(encoding="utf-8") == wf, "变异注入泄漏到真实文件了（判据会与并行腿互相打架）"
   ```

2. **类级元守卫**（PR #8482 已落地，同在 `tests/unit_ci_workflows/test_worker_h5_auth_failure_copy.py`）：
   - `test_no_guard_mutates_the_repo_tree_in_place` —— AST 扫描 `tests/unit_ci_workflows/*.py` 的
     「写仓内路径」形态，**未登记即红**；
   - `test_repo_tree_write_allowlist_only_shrinks` —— 台账 `REPO_WRITE_ALLOWLIST` **只许缩短**
     （登记了却没有真实写点 ⇒ 红）；
   - `test_repo_tree_write_judge_has_discriminating_power` —— 判别力自证：写仓内路径（两种隐蔽度）必红，
     写 `tmp_path` / **读**仓内路径不红。
3. **判红形态**：具名报到 `<文件>:<行> <表达式>`；出口 = 「把变异改走文本参数」，不是「再包一层 `finally`」。

### 12.4 反例

```python
# ❌ 写回 + finally 还原：共享写面依然存在，-n 4 下随并行度抽签
WORKFLOW.write_text(WORKFLOW.read_text().replace(A, B), encoding="utf-8")
try:
    assert copy_defects(...)          # 此刻同套件里任何读 WORKFLOW 的判据都读到 B
finally:
    WORKFLOW.write_text(orig, encoding="utf-8")

# ✅ 文本注入：不落盘，生产判定路径不变
broken = wf.replace(A, B)
assert broken != wf, "变异注入没生效"                  # 先自证注入生效（§8.2 同口径）
assert copy_defects(..., workflow_text=broken)
assert WORKFLOW.read_text(encoding="utf-8") == wf     # 变异没泄漏
```

**边界（照实登记）**：元守卫判的是**形态**，射程 =「模块级仓内路径名字」与表达式里出现
`REPO_ROOT` / `__file__`；路径经函数参数 / 变量拼接后再传、行内 `Path.replace` **不在射程**；
它**判不了**「写完有没有还原」—— 写本身就是共享写面，这是刻意的（#8415 的还原本身是正确的，仍然红）。

## 13. 三态口径：**判不了 ≠ 违规**（2026-11-03 固化，issue #8061）

**出处**：issue #8061 → 修法 PR #8486（**仍 OPEN**：机制已定，`_reached_conclusion()` 与 9 条判据**尚未进 main**）。

### 13.1 规则

判据 / 审计的退出码三态且**互不同义**：`0` 通过（有结论：无漂移）· `1` 违规（有结论：确实有漂移）·
`3` **判不了**（**没有产出结论**：`error` / `unknown`）。
⇒ 「没有结论」的 findings（`error` / `unknown` / `not_applicable` 名下）**不得计入**任何违规 / 漂移计数，
必须**具名摘出**并在报告里打印（摘出 ≠ 静默丢弃）：`error` / `unknown` 折 `3`；`not_applicable`
表示「该对象本轮未跑」—— **不折非零，但也不得读成「通过」**。
消费侧（workflow step / 台账 / 值班腿）必须**出声消费 `3`**：既不得读成 `0`，也不得读成 `1`。

### 13.2 为什么：报告一半说「判不了」、一半说「确实有漂移」（逐字）

`drift-audit.yml` 定时腿 10-29 ~ 11-02 连续 5 次 `failure`；其中 run `41369129772` 的报告**自相矛盾**：

```
❌ **判据不可判**（三态 `3`，**不得读成 0**）—— 它们**没有产出结论**：· [heartbeat] status=unknown
本次相对基线的增减：… 面外新增 1（不阻塞，定时腿红） … ⇒ DRIFT
退出码（三态…）：1 判红（有结论：确实有漂移…）
```

`heartbeat` 因为 `GITHUB_WORKFLOW` 取不到（`host-unknown`）而声明「本轮没读出结论」，却仍把它名下
那条 finding 留在 `new_drift_out_of_scope` 里 ⇒ `tri_state()` **先看计数**（`main` 上的实现：
`new_drift` / `stale_baseline_blocking` / `dropped_baseline_entry` / burn-down 命中即 `return 1`，
之后才看 `error` / `unknown`）⇒ 返回 `1`。⇒ `3`（判不了）与 `1`（违规）**同码**。

复算（本机，同一份 `origin/main`）：

```bash
python3 scripts/drift_audit.py --check --strict-stale --fail-on-unknown --base origin/main
# 改前：rc=1 · 面外新增 1 · 退出码「1 判红（有结论）」  ← 与它自己的「判据不可判」那节相反
# 改后：rc=3 · 面外新增 0 · 退出码「3 不可判」+ 那条读数仍被具名打印（⏸️ new-out-of-scope：…）
```

### 13.3 怎么判（唯一判定点 + 负控）

1. **唯一判定点**：修法（PR #8486，**仍 OPEN**）在 `scripts/drift_audit.py` 增加 `_reached_conclusion()` ——
   `error` / `unknown` / `not_applicable` = **没有结论**；`run_audit()` 把这些判据名下的 findings 从
   `new_drift` / `new_drift_out_of_scope` / `dropped_baseline_entry` / `env_findings` 摘出，逐条进
   `non_conclusive_findings` 并**具名打印**（一条都不丢），`verdict` 不再报 `drift`。
2. **判据**：`tests/unit_ci_workflows/test_drift_audit_not_conclusive_not_violation.py`（9 条，随
   PR #8486 提交 —— **尚未进 main**）：三态守门 / `not_applicable` 不得以违规码退出 / 报告具名 + `cwd`·`worktree` 解析同源 /
   两组注入式红证 / **负控** `test_control_conclusive_checks_still_block`（只放行「没结论」这一态 ⇒
   不会退化成把守卫改瞎）。
3. **消费面**：`tri_state()` → rc `3` → `drift-audit.yml` 审计 step **原样 `exit`**（非 0 ⇒ job failure）
   → `if: failure()` 的 P1 值班步骤（开 / 更 issue）→ `mechanism-liveness.yml` 的存活读数。
   ⇒ `3` 少掉的是「确实有漂移」这个**假结论**，不是「出声」。
4. ⚠️ `tri_state()` 的三态码**早已存在**（issue #5151）；#8061 的病是**计数层**把「没结论」的 findings
   混进了违规集合 ⇒ 修的是「谁有资格进计数」，不是「再加一个退出码」。

### 13.4 反例

```python
# ❌ 先看计数：判不了的那条已经被算进 new_drift_out_of_scope ⇒ 返回 1（把「判不了」谎报成「违规」）
if s["new_drift"] or s["new_drift_out_of_scope"]:
    return 1
if any(c["status"] == "unknown" for c in rep["checks"]):
    return 3
return 0

# ✅ 先摘「没结论」，再只对「有结论」的计数
non_conclusive = [f for f in findings if not _reached_conclusion(f.check)]
report(non_conclusive)                          # 具名打印，一条都不丢
if non_conclusive:
    return 3
return 1 if conclusive_findings else 0
```

**边界（照实登记）**：射程只到 `scripts/drift_audit.py` 这一族 ——「别的脚本 / 别的台账也把
`not_applicable` 当违规」**判不了**；`unknown` 在**未声明** `--fail-on-unknown` 时仍只报告（`0`），
这是既有语义、不放宽（CI runner 上活锚天然不存在，无条件折非零 = 每个 PR 常红）。
