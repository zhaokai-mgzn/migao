# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI 结构类 L0 不变式统一挂 MC-012，
#   「CI workflow 结构由 pytest 单测验证」是 misc.yml 里已登记的形态）
"""L0 守卫：落库/持久化调用外**不得有裸 `except ...: pass` / `except ...: continue`**（issue #4084）。

## 病灶（#4084 · #4070 实测）

`backend/ai-agent-service/app/api/chat.py` 的分页分支对 `session_memory.save_message(...)` 是
**`except Exception: pass`** —— 消息没落库、日志里也没有，而 SSE 照常 `done`：

1. 顾客这轮"看起来成功"（气泡正常滚动、`event: done` 正常到达）；
2. **回放历史时才发现少一条**（会话记录缺内容）⇒ 验收取证（#4041 靠会话记录做的线上取证）失真；
3. 同族形态（#4070）：生产签名新增一个可选参数、测试替身不认识该关键字 ⇒ `TypeError`
   被同一个 `except Exception` 吞掉 ⇒ assistant 消息**静默不落库**，只在别处表现为"计数不对"。

⇒ **"静默失效 = 最贵的一类缺陷"**（"只加字段没人渲染""工具说写了服务层没写"都是它的变体，
见 `migao-dev-flow` §19.2 / `migao-acceptance`）。本守卫把"落库失败不许静默"从**纪律**变成**判据**。

## 判据（纯 AST、零后端依赖、秒级）

对扫描面内每个 `try`（含 `try*`）节点：

1. **例外体是"静默"**：剥掉 docstring/常量表达式后为**空**、或**仅 `pass`**、或**仅 `continue`**；
2. **且 try 体内含落库/持久化调用**（口径见下）。

两条同时成立 ⇒ 报违规。**判据只看结构**：

- **不看文件名**（`test_criterion_is_structural_not_name_based` 直接钉住：叫 `chat.py` 的合法
  fail-open 不报、叫 `unrelated_module.py` 的吞点照报）；
- **不看措辞**（不扫 `# 忽略` 之类注释 —— 注释不是 AST 节点，改了注释不影响判定）；
- **按方法名识别落库**，**不按类名**（#4070 实测：真替身叫 `_FakeMemory`/`_Mem`/
  `InMemorySessionStore`，类名里根本没有 `SessionMemory` —— 按类名匹配会一个都扫不到）。

### 落库调用口径（`PERSIST_METHODS` / `PERSIST_WRAPPERS`，判据单一来源）

| 口径 | 覆盖 |
|---|---|
| `PERSIST_METHODS` | `save_message` / `update_session_title` / `create_session` / `close_session` / `delete_session` / `reopen_session` / `mark_last_interactive_answered`（卡片态落库，`#3036`）/ `commit` / `clear`（`SessionStateStore` 状态写） |
| `PERSIST_WRAPPERS` | 落库**单一策略点** `_save_message_or_report`（`app/api/chat.py`，`#4084`）—— 它是 `save_message` 的唯一出口，若有人把它换回裸 `except: pass`，本守卫必须同样报 |
| **别名形态** | `_marker = getattr(session_memory, "mark_last_interactive_answered", None)` 之后 `await _marker(...)` —— **字符串参数才是真名**，调用点写的是别名；不解析别名这两处就是判据盲区（本文件实测用了两次） |

## 扫描面与边界（照实登记：**未覆盖 ≠ 已覆盖**）

| 目录 | 状态 | 理由 |
|---|---|---|
| `app/api/**` | **在扫描面内** | #4084 的病灶面，本包独占写路径 |
| `app/graph/skills/**` | **不在**（登记于 `EXCLUDED_ROOTS`） | #4138 正在改该目录（另一包独占写路径）—— 先不纳入，避免造一个"永远是别人红"的判据；落地后加进 `SCAN_ROOTS` 即可（判据与扫描面解耦） |
| `app/memory/**` | **不在**（登记于 `EXCLUDED_ROOTS`） | 实测有同族形态（`close_session` / `delete_session` / `close_idle_sessions` 对 `_flush_pending_memories`、`SessionStateStore` 清理的 `except Exception: pass`）；不纳入的**唯一**原因是文件所有权（本包只独占 `app/api/**`）——**登记而不静默放过** |
| Redis 读缓存写（`setex`） | **不在判据内**（负例钉住） | 派生数据：丢了下次回源一次 DB 即可，且外层回源路径自带 warning；把它纳入只会让判据噪声化（`#4070` 的教训：**基于错误的真相模型写出的护栏 = 永远红**） |
| `return` / `break` 形态 | **不在判据内**（登记） | 控制流转移可被调用方观测（既有 fail-closed 形态如 `_pending_confirm_action` 退回只改写带留痕）——不纳入，避免把合法 fail-closed 判成吞点 |

## 每条判据都有能红的反例输入

| 用例 | 反例输入（改这一处即红） |
|---|---|
| `test_flags_bare_pass_around_save_message` | **红证①**：`try: await sm.save_message(...) except Exception: pass` ⇒ 必报 |
| `test_flags_bare_continue_around_persist_call` | `except Exception: continue` ⇒ 必报（`continue` 与 `pass` 同罪） |
| `test_flags_docstring_only_handler` | 例外体只有一句 docstring（剥掉后为空）⇒ 必报 |
| `test_flags_getattr_alias_form` | 别名形态（`_marker = getattr(sm, "mark_last_interactive_answered")`）⇒ 必报 |
| `test_real_scan_turns_red_when_a_swallow_is_injected` | 把吞点注入**真实扫描面** ⇒ 真实树那条判据必红（不往仓库写文件） |
| `test_accepts_fail_open_with_a_trace` | **负例③**：合法 fail-open（`logger.error` / `_report_persist_failure` / `raise`）⇒ **一律不报** |
| `test_ignores_non_persist_bodies` | Redis 读缓存写 + JSON 解析的 `pass` ⇒ 不报（登记边界，不是漏检） |
| `test_criterion_is_structural_not_name_based` | 叫 `chat.py` 的合法 fail-open 不报、叫 `unrelated_module.py` 的吞点照报 ⇒ 证明判据不认文件名 |
| `test_fails_closed_*`（三条） | 扫描面为空 / 文件解析不了 / **一个落库调用都没扫到** ⇒ 一律报错，不许静默空转 |
| `test_detector_sees_the_known_persist_call_sites` | 解析器失效 / 已知落库调用消失 ⇒ 必红（自证名单是**下限**） |
| `test_wrapper_is_registered_and_really_wraps_save_message` | 落库出口被改名/改成不调 `save_message` ⇒ 必红 |

**fail-closed**：扫描面不可读、文件解析不了、一个落库调用都没扫到、登记为落库出口的函数找不到
—— **一律报错**，不许「扫不到就通过」。所有失败信息都带 `suggestion`（可处置建议）。
"""

from __future__ import annotations

import ast
import warnings
from pathlib import Path
from typing import NamedTuple

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVICE_ROOT = REPO_ROOT / "backend" / "ai-agent-service"

#: **扫描面**（相对 `SERVICE_ROOT` 的目录）。判据与扫描面**解耦**：扩展面只改这一处。
SCAN_ROOTS: tuple[str, ...] = ("app/api",)

#: **登记的不在扫描面内的同族目录**（照实登记；理由必须非空，且路径必须真实存在 ——
#: 否则"排除"会静默指向空气，看起来有边界其实没有）
EXCLUDED_ROOTS: dict[str, str] = {
    "app/graph/skills": (
        "#4138 正在改该目录（另一包独占写路径）⇒ 先不纳入，避免造一个「永远是别人红」的判据；"
        "该 PR 落地后加进 SCAN_ROOTS 即可（判据本身与扫描面解耦）"
    ),
    "app/memory": (
        "实测存在同族形态（`close_session` / `delete_session` / `close_idle_sessions` 对"
        "`_flush_pending_memories` 与 `SessionStateStore` 清理是 `except Exception: pass`）；"
        "不纳入的**唯一**原因是文件所有权（AGENTS.md 铁律 6：本包只独占 app/api/**）"
    ),
    "app/tools": "小单包在动（本包不越界）；同一判据可在其落地后扩展",
}

#: **落库/持久化调用口径（判据单一来源）** —— 按**方法名**识别，不按类名/文件名
PERSIST_METHODS: frozenset[str] = frozenset({
    "save_message",                    # SessionMemory：对话消息落库（#4084 的病灶）
    "update_session_title",            # SessionMemory：会话标题落库
    "create_session",
    "close_session",
    "delete_session",
    "reopen_session",
    "mark_last_interactive_answered",  # 卡片态落库（#3036）
    "commit",                          # SessionStateStore / DB 事务提交
    "clear",                           # SessionStateStore 状态清除
})

#: 落库**单一策略点**（#4084）：`save_message` 的唯一出口，登记为判据口径的一部分
PERSIST_WRAPPERS: frozenset[str] = frozenset({"_save_message_or_report"})

#: 例外体的"静默"形态（剥掉 docstring/常量表达式后判定）
SILENT_PASS = "pass"
SILENT_CONTINUE = "continue"
SILENT_EMPTY = "empty"

_SUGGESTION = (
    "suggestion：落库失败**不许静默**（#4084）—— 允许 fail-open 继续执行，但必须留痕且可归因："
    "`app/api/chat.py` 的 `_save_message_or_report` / `_report_persist_failure`（ERROR + traceback "
    "+ `incident=` 短码 + `suggestion：`）就是既有口径，直接调它；"
    "确属可忽略的派生数据（如 Redis 读缓存写），请把该调用**移出**落库口径并在 EXCLUDED_* 里登记理由。"
)

#: **解析器自证名单（下限）**：扫描面内**逐字写明**的落库调用点 ——
#: `(相对仓库根路径, 落库口径)` 对。用路径而**不是行号**（行号会漂移，§18.3 不可变引用）。
#: 声明为**下限**：新增落库调用不产生摩擦；**已知点消失 / 解析器漏解析**必红。
KNOWN_PERSIST_CALL_SITES: frozenset[tuple[str, str]] = frozenset({
    ("backend/ai-agent-service/app/api/chat.py", "save_message"),
    ("backend/ai-agent-service/app/api/chat.py", "_save_message_or_report"),
    ("backend/ai-agent-service/app/api/chat.py", "commit"),
    ("backend/ai-agent-service/app/api/chat.py", "update_session_title"),
    # 别名形态（`_marker = getattr(session_memory, "mark_last_interactive_answered", None)`）：
    # 能出现在这里就证明**别名解析**真的在工作，而不是把这两处当空气
    ("backend/ai-agent-service/app/api/chat.py", "mark_last_interactive_answered"),
})


class Finding(NamedTuple):
    path: str                    # 相对仓库根
    try_lineno: int
    handler_lineno: int
    exc_type: str                # 例外类型文本（`Exception` / `(A, B)` / `<bare>`）
    kind: str                    # pass / continue / empty
    evidence: tuple[tuple[str, int], ...]   # 命中的落库调用：(口径名, 行号)


class ScanResult(NamedTuple):
    findings: list[Finding]
    sites: set[tuple[str, str]]  # 扫到的落库调用点 (相对路径, 口径名)
    files: int                   # 实际解析的文件数


# ──────────────────────────────────────────────────────────────────────────────
# 静态解析（纯 AST：本文件跑在 CI 只装了 pytest + pyyaml 的 L0 job 里）
# ──────────────────────────────────────────────────────────────────────────────


def _parse(path: Path) -> ast.Module:
    """解析一个 .py —— 读不到/解析不了**直接红**（fail-closed：读不到 ≠ 无违规）"""
    with warnings.catch_warnings():
        # 被判读文件里的无效转义序列等会就地告警（`-W error` 下变异常 ⇒ 假红）；
        # 屏蔽只作用于本次 `ast.parse`，不改变被判读文件的行为。
        warnings.simplefilter("ignore")
        try:
            return ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError) as exc:
            pytest.fail(
                f"[落库静默守卫] 读不到或解析不了 {path}：{exc!r}\n"
                f"suggestion：修掉该文件的语法/编码问题；**不要**改成「解析失败就跳过」"
                f"（那会让守卫静默空转 —— 正是本守卫要防的形态）。"
            )


def _rel(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:              # 注入的临时夹具目录不在仓库内
        return path.as_posix()


def _parents(tree: ast.AST) -> dict[int, ast.AST]:
    parents: dict[int, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[id(child)] = parent
    return parents


def _enclosing_function(node: ast.AST, parents: dict[int, ast.AST]) -> ast.AST | None:
    cur = parents.get(id(node))
    while cur is not None:
        if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return cur
        cur = parents.get(id(cur))
    return None


def _silent_kind(handler: ast.ExceptHandler) -> str:
    """例外体是否为"静默"形态；返回 "" 表示有留痕/有动作（不判违规）"""
    body = [s for s in handler.body
            if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))]
    if not body:
        return SILENT_EMPTY
    if len(body) == 1:
        if isinstance(body[0], ast.Pass):
            return SILENT_PASS
        if isinstance(body[0], ast.Continue):
            return SILENT_CONTINUE
    return ""


def _call_name(call: ast.Call) -> str:
    """调用名：`a.save_message(...)` → save_message；`save(...)` → save"""
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def _persist_aliases(scope: ast.AST) -> dict[str, str]:
    """`_marker = getattr(session_memory, "mark_last_interactive_answered", None)` ⇒
    `{_marker: mark_last_interactive_answered}`（字符串参数才是真名，调用点写的是别名）"""
    out: dict[str, str] = {}
    for node in ast.walk(scope):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target, value = node.targets[0], node.value
        if not (isinstance(target, ast.Name) and isinstance(value, ast.Call)):
            continue
        if not (isinstance(value.func, ast.Name) and value.func.id == "getattr"):
            continue
        if len(value.args) >= 2 and isinstance(value.args[1], ast.Constant) \
                and value.args[1].value in PERSIST_METHODS:
            out[target.id] = value.args[1].value
    return out


def _persist_calls(stmts: list[ast.stmt], aliases: dict[str, str]) -> tuple[tuple[str, int], ...]:
    """try **体**内的落库调用（只看 try 体：finally/其它 handler 里的调用不构成本 handler 的证据）"""
    hits: list[tuple[str, int]] = []
    for stmt in stmts:
        for node in ast.walk(stmt):
            if not isinstance(node, ast.Call):
                continue
            name = _call_name(node)
            resolved = aliases.get(name, name)
            if resolved in PERSIST_METHODS or resolved in PERSIST_WRAPPERS:
                hits.append((resolved, node.lineno))
    return tuple(hits)


def _exc_type_text(handler: ast.ExceptHandler) -> str:
    return ast.unparse(handler.type) if handler.type is not None else "<bare>"


def scan_file(path: Path) -> tuple[list[Finding], set[tuple[str, str]]]:
    """扫一个文件：返回（违规, 该文件里的落库调用点）"""
    tree = _parse(path)
    parents = _parents(tree)
    findings: list[Finding] = []
    sites: set[tuple[str, str]] = set()
    rel = _rel(path)

    for node in ast.walk(tree):
        if not isinstance(node, (ast.Try, ast.TryStar)):
            continue
        fn = _enclosing_function(node, parents)
        aliases = _persist_aliases(fn if fn is not None else tree)
        evidence = _persist_calls(node.body, aliases)
        for name, _lineno in evidence:
            sites.add((rel, name))
        if not evidence:
            continue
        for handler in node.handlers:
            kind = _silent_kind(handler)
            if kind:
                findings.append(Finding(
                    rel, node.lineno, handler.lineno,
                    _exc_type_text(handler), kind, evidence))
    return findings, sites


def _scan_roots(roots) -> list[Path]:
    """把扫描面展开成文件表 —— 目录不存在 / 一个文件都没有 ⇒ **报错**（fail-closed）"""
    files: list[Path] = []
    for root in roots:
        base = Path(root)
        if not base.is_dir():
            pytest.fail(
                f"[落库静默守卫] 扫描面 {base} 不存在（或不是目录）\n"
                f"suggestion：扫描面写错了 ⇒ 守卫会**静默空转**（看起来全绿，实际什么都没扫）。"
                f"请修正 SCAN_ROOTS，或恢复被删/搬走的目录。"
            )
        files.extend(sorted(base.rglob("*.py")))
    if not files:
        pytest.fail(
            f"[落库静默守卫] 扫描面 {list(roots)} 下没有任何 .py —— 守卫空转\n"
            f"suggestion：确认扫描面路径与仓库布局一致（这是 fail-closed，不是 skip）。"
        )
    return files


def _scan(roots) -> ScanResult:
    """扫描 + 汇总。`roots` 是参数 ⇒ 红证夹具可落盘注入（与真实树走**同一条**代码路径）"""
    findings: list[Finding] = []
    sites: set[tuple[str, str]] = set()
    files = _scan_roots(roots)
    for path in files:
        file_findings, file_sites = scan_file(path)
        findings.extend(file_findings)
        sites |= file_sites
    return ScanResult(findings, sites, len(files))


def _fail_closed(result: ScanResult) -> None:
    """扫不到任何落库调用 ⇒ 报错（**判据自己选择沉默** = 空判据，比没有判据更危险）"""
    if not result.sites:
        pytest.fail(
            "[落库静默守卫] 扫描面里**一个落库调用都没扫到** —— 判据已空转\n"
            "suggestion：说明 PERSIST_METHODS / 扫描面已与代码现实脱节（落库调用被改名、"
            "被搬去别处、或扫描面写错）。空判据比没有判据更危险（§19.1），故 fail-closed。"
        )


def _report(findings: list[Finding]) -> str:
    lines = ["[落库静默守卫] 下列落库/持久化调用被裸 `except` **吞掉**（#4084：静默失效）："]
    for f in findings:
        ev = ", ".join(f"{name}@L{lineno}" for name, lineno in f.evidence)
        lines.append(f"  {f.path}: 第 {f.handler_lineno} 行 "
                     f"`except {f.exc_type}: {f.kind}` 吞掉 [{ev}]（try @第 {f.try_lineno} 行）")
    lines.append(_SUGGESTION)
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# ① 检测器自证：红证 + 负例（**落盘注入**，不依赖仓库当下有没有缺陷）
#
# ⚠️ 夹具里的 `pass` 一律带尾注释：`growth_gate.find_weak_asserts` 的 `^\s*pass\s*$` 是**行级**
# 正则，会把夹具源码里的裸 `pass` 行误判成"测试体是空的 pass"（#3631 弱断言门禁）。
# 夹具是**数据**不是测试体 ⇒ 用尾注释把它与真弱断言区分开（判据本身不看注释，只看 AST）。
# ──────────────────────────────────────────────────────────────────────────────

_PASS_SWALLOW = '''\
"""红证夹具：裸 `except: pass` 吞掉落库调用（#4084 的病灶形态）"""


class _Mem:
    async def save_message(self, **kw):
        return "msg"


async def persist_turn(mem):
    try:
        await mem.save_message(session_id="s1", role="assistant", content="hi")
    except Exception:
        pass  # 吞点（夹具数据，非测试体 —— 尾注释避免被弱断言行正则误判）
'''

_CONTINUE_SWALLOW = '''\
"""红证夹具：`except: continue` 吞掉落库调用"""


async def persist_all(mem, items):
    out = []
    for it in items:
        try:
            await mem.save_message(session_id="s1", role="user", content=it)
        except Exception:
            continue
        out.append(it)
    return out
'''

_DOCSTRING_ONLY = '''\
"""红证夹具：例外体只有一句 docstring（剥掉后为空 ⇒ 同罪）"""


async def persist_turn(state_store):
    try:
        await state_store.commit("s1", {"a": 1})
    except Exception:
        """清理失败不影响主流程"""
'''

_ALIAS_SWALLOW = '''\
"""红证夹具：`getattr` 别名形态（调用点写的是别名，字符串参数才是真名）"""


async def mark_answered(session_memory):
    _marker = getattr(session_memory, "mark_last_interactive_answered", None)
    if _marker is not None:
        try:
            await _marker("s1")
        except Exception:
            pass  # 吞点（夹具数据）
'''

_FAIL_OPEN_WITH_TRACE = '''\
"""负例③：合法 fail-open —— 留痕（warning/error/incident 审计）或显式上抛，一律不得报"""


async def save_with_audit(mem, source):
    try:
        await mem.save_message(session_id="s1", role="assistant", content="hi")
    except Exception as exc:
        _report_persist_failure(exc=exc, op="save_message", source=source)
        return None


async def save_with_logger(mem):
    try:
        await mem.save_message(session_id="s1", role="user", content="hi")
    except Exception as exc:
        logger.error(f"[chat/send] save_message failed | error={exc}", exc_info=True)


async def save_fail_closed(mem):
    try:
        await mem.save_message(session_id="s1", role="user", content="hi")
    except Exception:
        raise


async def save_fail_closed_with_code(mem):
    try:
        await mem.save_message(session_id="s1", role="user", content="hi")
    except TypeError as exc:
        return {"ok": False, "error": str(exc)}
'''

_NON_PERSIST_SWALLOW = '''\
"""登记边界（**不是漏检**）：派生数据 / 非落库体上的 `pass` 不报"""


async def read_cache(client, key):
    try:
        await client.setex(key, 3600, "v")      # Redis 读缓存写：派生数据，丢了回源一次 DB
    except Exception:
        pass  # 口径外（夹具数据）


def parse_meta(raw):
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        pass  # 口径外（夹具数据）
    return {}
'''

_NAME_NEUTRAL_FAIL_OPEN = '''\
"""证明判据**不认文件名**：本文件故意叫 chat.py，但内容是合法 fail-open ⇒ 不得报"""


async def save_with_audit(mem):
    try:
        await mem.save_message(session_id="s1", role="assistant", content="hi")
    except Exception as exc:
        _report_persist_failure(exc=exc, op="save_message", source="chat.assistant")
        return None
'''

_NAME_NEUTRAL_SWALLOW = '''\
"""证明判据**不认文件名**：本文件叫 unrelated_module.py，吞点照样必须报"""


async def save_the_thing(mem):
    try:
        await mem.update_session_title("s1", "标题")
    except Exception:
        pass  # 吞点（夹具数据，非测试体 —— 尾注释避免被弱断言行正则误判）
'''


def _inject(root: Path, **named_sources: str) -> Path:
    """落盘注入：守卫扫的是**文件**，故夹具必须写成真实文件（可指定文件名 ⇒ 可验"不认名字"）"""
    root.mkdir(parents=True, exist_ok=True)
    for name, src in named_sources.items():
        (root / f"{name}.py").write_text(src, encoding="utf-8")
    return root


def test_flags_bare_pass_around_save_message(tmp_path):
    """红证①：`try: await sm.save_message(...) except Exception: pass` ⇒ 必报"""
    result = _scan([_inject(tmp_path, fixture_0=_PASS_SWALLOW)])
    assert [(f.kind, [n for n, _ in f.evidence]) for f in result.findings] == \
        [(SILENT_PASS, ["save_message"])], result.findings
    assert result.findings[0].exc_type == "Exception", result.findings[0]
    report = _report(result.findings)
    assert "persist FAILED" in report or "_save_message_or_report" in report, report
    assert "suggestion：" in report, report


def test_flags_bare_continue_around_persist_call(tmp_path):
    """`except Exception: continue` 与 `pass` 同罪 ⇒ 必报"""
    result = _scan([_inject(tmp_path, fixture_0=_CONTINUE_SWALLOW)])
    assert [(f.kind, [n for n, _ in f.evidence]) for f in result.findings] == \
        [(SILENT_CONTINUE, ["save_message"])], result.findings


def test_flags_docstring_only_handler(tmp_path):
    """例外体只有一句 docstring（剥离后为空）⇒ 必报；且状态写（commit）也在判据内"""
    result = _scan([_inject(tmp_path, fixture_0=_DOCSTRING_ONLY)])
    assert [(f.kind, [n for n, _ in f.evidence]) for f in result.findings] == \
        [(SILENT_EMPTY, ["commit"])], result.findings


def test_flags_getattr_alias_form(tmp_path):
    """`getattr` 别名形态 ⇒ 必报（不解析别名就是一个判据盲区）"""
    result = _scan([_inject(tmp_path, fixture_0=_ALIAS_SWALLOW)])
    assert [(f.kind, [n for n, _ in f.evidence]) for f in result.findings] == \
        [(SILENT_PASS, ["mark_last_interactive_answered"])], result.findings


def test_accepts_fail_open_with_a_trace(tmp_path):
    """负例③：合法 fail-open（审计 / logger / 显式上抛 / 带错的 fail-closed）⇒ 一律不报"""
    result = _scan([_inject(tmp_path, fixture_0=_FAIL_OPEN_WITH_TRACE)])
    assert result.findings == [], _report(result.findings)
    # 但它们确实**是**落库调用点（证明"不报"是因为有留痕，不是因为没扫到）
    assert ("save_message" in {n for _p, n in result.sites}), result.sites


def test_ignores_non_persist_bodies(tmp_path):
    """登记边界：Redis 读缓存写 / JSON 解析上的 `pass` ⇒ 不报（不是漏检，是口径外）"""
    result = _scan([_inject(tmp_path, fixture_0=_NON_PERSIST_SWALLOW)])
    assert result.findings == [], _report(result.findings)
    assert result.sites == set(), result.sites


def test_criterion_is_structural_not_name_based(tmp_path):
    """判据**只看结构**：叫 `chat.py` 的合法 fail-open 不报；叫 `unrelated_module.py` 的吞点照报"""
    root = _inject(tmp_path, chat=_NAME_NEUTRAL_FAIL_OPEN,
                   unrelated_module=_NAME_NEUTRAL_SWALLOW)
    result = _scan([root])
    assert [(Path(f.path).name, f.kind) for f in result.findings] == \
        [("unrelated_module.py", SILENT_PASS)], result.findings
    assert {n for _p, n in result.sites} == {"save_message", "update_session_title"}, result.sites


def test_fails_closed_when_scan_root_is_missing(tmp_path):
    """fail-closed：扫描面不存在 ⇒ 必须报错（不许静默空转）"""
    with pytest.raises(pytest.fail.Exception):
        _scan([tmp_path / "does_not_exist"])


def test_fails_closed_when_a_file_is_unparsable(tmp_path):
    """fail-closed：扫描面里有解析不了的文件 ⇒ 必须报错（读不到 ≠ 无违规）"""
    root = tmp_path / "app_api_fixture"
    root.mkdir()
    (root / "broken.py").write_text("def f(:\n", encoding="utf-8")
    with pytest.raises(pytest.fail.Exception):
        _scan([root])


def test_fails_closed_when_no_persist_call_is_found(tmp_path):
    """fail-closed：一个落库调用都没扫到 ⇒ 判据空转 ⇒ 必须报错"""
    root = _inject(tmp_path, fixture_0="def f():\n    return 1\n")
    result = _scan([root])
    assert result.findings == [], result.findings
    with pytest.raises(pytest.fail.Exception):
        _fail_closed(result)


# ──────────────────────────────────────────────────────────────────────────────
# ② 真实扫描面：#4084 的主判据
# ──────────────────────────────────────────────────────────────────────────────


def _real_roots() -> list[Path]:
    return [SERVICE_ROOT / r for r in SCAN_ROOTS]


def test_scan_face_is_registered_and_exclusions_point_at_real_directories():
    """扫描面/排除面**登记自证**：目录真实存在、理由非空、两面不重叠

    （"排除"若指向不存在的路径，看起来有边界其实没有 —— 那是"静默豁免"。）
    """
    assert SCAN_ROOTS, "扫描面不得为空"
    for root in SCAN_ROOTS:
        assert (SERVICE_ROOT / root).is_dir(), f"扫描面不存在：{root}"
    assert EXCLUDED_ROOTS, "排除面必须**逐条登记理由**（空表 = 未登记，不是「没有排除」）"
    for root, reason in EXCLUDED_ROOTS.items():
        assert (SERVICE_ROOT / root).is_dir(), f"登记的排除目录不存在：{root}（排除写错路径 = 静默豁免）"
        assert len(reason.strip()) > 20, f"排除理由太短，等于没写：{root} → {reason!r}"
    assert not (set(SCAN_ROOTS) & set(EXCLUDED_ROOTS)), "同一目录不能既扫又排除"


def test_no_persist_call_is_swallowed_in_the_scan_face():
    """主判据（#4084）：扫描面内不得有裸 `except: pass/continue` 吞落库调用"""
    result = _scan(_real_roots())
    _fail_closed(result)
    assert result.findings == [], _report(result.findings)


def test_real_scan_turns_red_when_a_swallow_is_injected(tmp_path):
    """「主判据**能红**」的直接证明：把吞点注入**真实扫描面** ⇒ 必红。

    不往仓库写文件 —— 扫描根是 `_scan` 的参数，与主判据走**同一条**代码路径。
    """
    clean = _scan(_real_roots())
    assert clean.findings == [], _report(clean.findings)
    dirty = _scan([*_real_roots(), _inject(tmp_path, injected_swallow=_PASS_SWALLOW)])
    assert [(f.kind, [n for n, _ in f.evidence]) for f in dirty.findings] == \
        [(SILENT_PASS, ["save_message"])], dirty.findings


def test_detector_sees_the_known_persist_call_sites():
    """解析器自证 + fail-closed：已知的落库调用点必须都被扫到（名单是**下限**）"""
    result = _scan(_real_roots())
    missing = KNOWN_PERSIST_CALL_SITES - result.sites
    assert not missing, (
        "已知落库调用点没被扫到（解析器失效 / 调用被改名搬走）：\n"
        + "\n".join(f"  {p} → {n}" for p, n in sorted(missing))
        + "\nsuggestion：若确实改名/搬走，同步 KNOWN_PERSIST_CALL_SITES 并说明理由；"
          "否则说明本守卫的识别口径已静默失效（#4084 要防的正是这种'判据自己选择沉默'）。"
    )


def test_wrapper_is_registered_and_really_wraps_save_message():
    """落库出口自证：登记为 `PERSIST_WRAPPERS` 的函数必须真的存在且真的调 `save_message`

    （否则"落库唯一出口"改名后，判据在这一层静默失明：裸 `except: pass` 包住包装调用不会被报。）
    """
    assert PERSIST_WRAPPERS, "落库出口登记表不得为空"
    found: dict[str, ast.AST] = {}
    for path in _scan_roots(_real_roots()):
        for node in ast.walk(_parse(path)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                found[node.name] = node
    for name in sorted(PERSIST_WRAPPERS):
        assert name in found, (
            f"登记为落库出口的 {name} 在扫描面里找不到\n"
            f"suggestion：出口被改名/搬走 ⇒ 同步 PERSIST_WRAPPERS（否则判据静默失明）。"
        )
        called = {n.attr for n in ast.walk(found[name]) if isinstance(n, ast.Attribute)}
        assert "save_message" in called, (
            f"{name} 体内没有调用 save_message ⇒ 它已不是落库出口"
            f"suggestion：要么恢复包装，要么从 PERSIST_WRAPPERS 摘掉并说明理由。"
        )