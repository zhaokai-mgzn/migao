# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI 结构类 L0 不变式统一挂 MC-012，
#   「CI workflow 结构由 pytest 单测验证」是 misc.yml 里已登记的形态）
"""L0 守卫：测试替身的方法签名不得落后于生产签名（issue #4070）。

## 病灶（#4052 实现过程中实测的真红灯）

`tests/**` 下有一批 `SessionMemory` / `SessionStateStore` **替身类**。生产侧
`SessionMemory.save_message()` 新增一个可选参数（`tool_results`，issue #4052）后：

1. SSE 桥按**关键字**调用真 `SessionMemory.save_message(..., tool_results=...)`；
2. 替身签名不认这个关键字 ⇒ 抛 `TypeError`；
3. 该异常被 SSE 桥的 `try/except Exception` **吞掉**（只 `logger.error("save_message failed")`，
   `app/api/chat.py` 的 4 个调用点全是这个形状）；
4. ⇒ **assistant 消息静默不落库**，测试只表现为「计数/断言不对」，看不出根因。

更危险的是**判据自己选择沉默**：`test_business_verification` 红 1 条、`test_e2e_chat_flow`
红 2 条，而 `test_integration_multimodal` 当时**签名同样落后却全绿**。

## 判据（本文件 = L0 静态不变式，纯 AST、零后端依赖、秒级）

扫 `tests/**` 与 `backend/ai-agent-service/tests/**` 里**遮蔽了生产方法名**的类，
对每个 (替身, 生产方法) 断言「替身能接受生产调用点能给的实参」。

**调用口径按生产调用点的真实形态取**（实测，不是猜的 —— 判据错了护栏就会永远红）：

| 生产方法 | 生产调用点怎么传参（实测） | 判据 |
|---|---|---|
| `SessionMemory.save_message` | **全关键字**：`app/api/chat.py` 4 处调用点均为 `session_id=` / `role=` / `content=` / `tool_calls=` / `tool_results=` / `interactive=` / `tenant_id=` | 生产签名的**每个参数名**，替身要么有同名形参、要么有 `**kwargs` |
| `SessionStateStore.load` / `commit` / `clear` | **全位置**：`store.load(session_id)` / `store.commit(session_id, existing)` / `SessionStateStore().clear(session_id)` | 替身的位置形参数 ≥ 生产的位置形参数（或有 `*args`） |

⚠️ **store 侧为什么不用「同名形参」判据**（@20862169 实测）：
store 替身普遍用 `(self, sid, full)` / `(self, sid, f)` 这类**短名**形参 —— 对 52 个 store 替身
套「同名形参」判据会报 **94 条**，而它们**没有一个是坏替身**（生产调用点全部位置传参，
形参叫什么名字都不影响绑定）。那正是 §19.1「**基于错误的真相模型写出的护栏 = 永远红**」
的形态 ⇒ 判据必须匹配**真实调用口径**。

## 识别口径：按**方法名**，不按类名

替身识别 = 类**定义了标记方法**（`SessionMemory` → `save_message`；`SessionStateStore` →
`load` + `commit`）。**类名不构成判据**：真替身叫 `_FakeMemory` / `_Mem` /
`InMemorySessionStore` / `_FakeStore`，名字里根本没有 `SessionMemory` / `SessionStateStore`
—— 按类名匹配会**一个真替身都扫不到**（实测 7 个 `save_message` 替身全部不在类名里体现）。

## 反退化（每条都有能红的夹具）

| 用例 | 反例输入（改这一处即红） |
|---|---|
| `test_no_double_signature_lags_the_production_signature` | **主判据**：#4070 的形状 —— 生产签名加参数而替身不动 ⇒ 必红 |
| `test_real_tree_scan_turns_red_when_a_stale_double_is_injected` | 把落后替身注入**扫描范围** ⇒ 真实树那条判据必红（不往仓库写文件） |
| `test_detector_scans_the_known_doubles_in_the_real_tree` | 解析器失效 / 已知替身被删改名 ⇒ 必红（自证名单是**下限**） |
| `test_flags_stale_save_message_double` | 替身 `save_message` 少一个生产参数 ⇒ 必红 |
| `test_flags_store_double_with_short_positional_arity` | store 替身 `commit(self, sid)` 少一个位置形参 ⇒ 必红 |
| `test_accepts_kwargs_double` / `test_accepts_exact_signature_double` / `test_ignores_classes_that_do_not_shadow_production_methods` | **R2 阴性负例**：`**kw` 替身 / 签名一致的替身 / 名字像替身但没遮蔽生产方法名的类 ⇒ **一律不得误报** |
| `test_fails_closed_when_no_double_is_found` / `…_production_source_is_unreadable` / `…_production_class_is_renamed` | **fail-closed**：扫不到替身 / 生产源读不到 / 生产类被改名 ⇒ **必须报错** |

**fail-closed**：生产源读不到/解析不了、生产类或方法被改名、某个生产类一个替身都没扫到
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
TEST_ROOTS = (REPO_ROOT / "tests", SERVICE_ROOT / "tests")

#: 调用口径 —— 必须与生产调用点的真实形态一致（见模块 docstring 的实测表）
KEYWORD = "keyword"
POSITIONAL = "positional"

#: **判据登记表（单一来源）**：生产类 → (替身识别标记方法集, {被遮蔽方法: 调用口径})
REGISTRY: dict[tuple[str, str], tuple[tuple[str, ...], dict[str, str]]] = {
    ("app/memory/session_memory.py", "SessionMemory"): (
        ("save_message",),
        {"save_message": KEYWORD},
    ),
    ("app/memory/session_state_store.py", "SessionStateStore"): (
        ("load", "commit"),
        {"load": POSITIONAL, "commit": POSITIONAL, "clear": POSITIONAL},
    ),
}

#: **解析器自证名单（下限，⊆ 实际扫到的）**：issue #4070 的实测对象 —— 7 个 `save_message`
#: 替身，去重成 **5 个 (相对路径, 类名) 对**（`_Mem` 在同一文件里出现 3 次，见
#: `test_api_chat_helpers.py` 的 149 / 1222 / 1314 行）。
#: 用 (路径, 类名) 而**不是行号**：行号会漂移（§18.3 不可变引用）。
#: 声明为**下限**：新增替身不产生摩擦；**已知替身消失或解析器漏解析**必红。
KNOWN_SAVE_MESSAGE_DOUBLES: frozenset[tuple[str, str]] = frozenset({
    ("backend/ai-agent-service/tests/test_e2e_chat_flow.py", "InMemorySessionStore"),
    ("backend/ai-agent-service/tests/test_integration_multimodal.py", "InMemorySessionStore"),
    ("backend/ai-agent-service/tests/test_business_verification.py", "_InMemorySessionStore"),
    ("backend/ai-agent-service/tests/test_api_chat_helpers.py", "_FakeMemory"),
    ("backend/ai-agent-service/tests/test_api_chat_helpers.py", "_Mem"),
})

_SUGGESTION = {
    KEYWORD: (
        "suggestion：把该替身的形参同步成生产签名，**或**给它加 `**kwargs` 吸收新增关键字。"
    ),
    POSITIONAL: (
        "suggestion：把缺的位置形参补上（生产按位置传参 ⇒ `**kwargs` 帮不上忙），"
        "**或**给它加 `*args`。"
    ),
}
_WHY_IT_MATTERS = (
    "替身签名落后时，真实调用会抛 TypeError 并被 SSE 桥的 try/except 吞掉 ⇒ "
    "消息静默不落库（issue #4070）。"
)


# ──────────────────────────────────────────────────────────────────────────────
# 静态解析（纯 AST：本文件跑在 CI 只装了 pytest + pyyaml 的 L0 job 里）
# ──────────────────────────────────────────────────────────────────────────────


class _Sig(NamedTuple):
    """一个可调用对象的静态签名视图"""

    names: tuple[str, ...]      # 可关键字传参的形参名（posonly + args + kwonly，去掉 self）
    n_positional: int           # 可位置传参的形参个数（去掉 self）
    has_vararg: bool            # *args
    has_kwarg: bool             # **kwargs


def _sig(node: ast.AST) -> _Sig:
    a = node.args  # type: ignore[attr-defined]
    pos = [x.arg for x in (*a.posonlyargs, *a.args)]
    names = tuple(n for n in (*pos, *(x.arg for x in a.kwonlyargs)) if n != "self")
    return _Sig(names, len([n for n in pos if n != "self"]),
                a.vararg is not None, a.kwarg is not None)


def _parse(path: Path) -> ast.Module:
    """解析一个 .py —— 读不到/解析不了**直接红**（fail-closed：读不到 ≠ 无违规）

    解析时**屏蔽警告**：被判读的文件里有 `"\\s"` 这类无效转义序列时，编译器会就地
    `DeprecationWarning`（本守卫扫的是**整棵测试树**，那属**别人源码**的噪声，与本判据无关）；
    在 `-W error` 环境里它还会变成异常 ⇒ 假红。屏蔽只作用于本次 `ast.parse`。
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            return ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError) as exc:
            pytest.fail(
                f"[替身签名守卫] 读不到或解析不了 {path}：{exc!r}\n"
                f"suggestion：修掉该文件的语法/编码问题；若它本就不可导入，请把守卫的扫描根"
                f"收紧到可解析范围，**不要**改成「解析失败就跳过」（那会让守卫静默空转）。"
            )


def _class_methods(cls: ast.ClassDef) -> dict[str, ast.AST]:
    return {
        n.name: n
        for n in cls.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _production_signatures() -> dict[tuple[str, str, str], _Sig]:
    """从**生产源**反解签名真值（判据单一来源；读不到即 fail-closed）"""
    out: dict[tuple[str, str, str], _Sig] = {}
    for (module, cls_name), (_markers, methods) in REGISTRY.items():
        path = SERVICE_ROOT / module
        tree = _parse(path)
        cls = next((n for n in ast.walk(tree)
                    if isinstance(n, ast.ClassDef) and n.name == cls_name), None)
        if cls is None:
            pytest.fail(
                f"[替身签名守卫] {module} 里找不到生产类 {cls_name}\n"
                f"suggestion：生产类被改名/搬迁 ⇒ 本守卫会恒真空转，请同步 REGISTRY 并复核"
                f"『生产签名改了、替身要不要跟着改』。fail-closed，不得静默跳过。"
            )
        bodies = _class_methods(cls)
        for method in methods:
            node = bodies.get(method)
            if node is None:
                pytest.fail(
                    f"[替身签名守卫] {cls_name}.{method} 在生产源 {module} 里找不到\n"
                    f"suggestion：方法被改名/删除 ⇒ 同步 REGISTRY（fail-closed）。"
                )
            out[(module, cls_name, method)] = _sig(node)
    return out


class Finding(NamedTuple):
    path: str           # 替身所在文件（相对仓库根）
    lineno: int
    double: str         # 替身类名
    prod_class: str     # 被遮蔽的生产类
    method: str         # 被遮蔽的生产方法
    style: str          # 该方法的调用口径（决定处置建议）
    why: str            # 违规描述


class ScanResult(NamedTuple):
    findings: list[Finding]
    counts: dict[tuple[str, str], int]   # 每个生产类扫到的替身数
    doubles: set[tuple[str, str]]        # (相对路径, 替身类名)


def _rel(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:          # 注入的临时夹具目录不在仓库内
        return path.as_posix()


def _incompatibility(prod: _Sig, dbl: _Sig, style: str) -> str:
    """返回违规描述；空串 = 兼容"""
    if style == KEYWORD:
        if dbl.has_kwarg:
            return ""
        missing = [n for n in prod.names if n not in dbl.names]
        return f"缺形参 {missing}（生产按关键字传参）" if missing else ""
    if dbl.has_vararg or dbl.n_positional >= prod.n_positional:
        return ""
    return (f"位置形参只有 {dbl.n_positional} 个，少于生产的 {prod.n_positional} 个"
            f"（生产按位置传参）")


def _scan(roots) -> ScanResult:
    """扫描给定根下的**替身类**，比对生产签名。roots 是参数 ⇒ 红证夹具可落盘注入。"""
    prods = _production_signatures()
    findings: list[Finding] = []
    counts: dict[tuple[str, str], int] = {}
    doubles: set[tuple[str, str]] = set()

    for root in roots:
        for path in sorted(Path(root).rglob("*.py")):
            tree = _parse(path)
            rel = _rel(path)
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                bodies = _class_methods(node)
                for (module, cls_name), (markers, methods) in REGISTRY.items():
                    if not set(markers) <= set(bodies):
                        continue
                    counts[(module, cls_name)] = counts.get((module, cls_name), 0) + 1
                    doubles.add((rel, node.name))
                    for method, style in methods.items():
                        dbl_node = bodies.get(method)
                        if dbl_node is None:
                            continue
                        why = _incompatibility(
                            prods[(module, cls_name, method)], _sig(dbl_node), style)
                        if why:
                            findings.append(Finding(
                                rel, node.lineno, node.name, cls_name, method, style, why))
    return ScanResult(findings, counts, doubles)


def _fail_closed(counts: dict[tuple[str, str], int]) -> None:
    """扫不到替身 ⇒ 报错（不许「扫不到就通过」）"""
    empty = [f"{m}::{c}" for (m, c) in REGISTRY if not counts.get((m, c))]
    if empty:
        pytest.fail(
            "[替身签名守卫] 下列生产类**一个替身都没扫到**：" + ", ".join(empty) + "\n"
            "suggestion：扫不到 ≠ 无违规。若替身已被合法重构掉，请同步本文件 REGISTRY "
            "并说明理由；否则说明识别口径（标记方法名）已与现实脱节。"
        )


def _report(findings: list[Finding]) -> str:
    lines = ["[替身签名守卫] 以下测试替身的签名落后于生产签名："]
    lines += [
        f"  {f.path}:{f.lineno} class {f.double}({f.prod_class}.{f.method}) → {f.why}"
        for f in findings
    ]
    lines += [_SUGGESTION[style] + _WHY_IT_MATTERS
              for style in dict.fromkeys(f.style for f in findings)]
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# ① 检测器自证：红证 + R2 阴性负例（**落盘注入**，不依赖仓库当下有没有缺陷）
# ──────────────────────────────────────────────────────────────────────────────

_STALE_SAVE_MESSAGE = '''\
"""构造的落后替身：显式签名缺生产参数（红证夹具）"""


class StaleMemory:
    async def save_message(self, session_id, role, content):
        return "msg"
'''

_STALE_STORE = '''\
"""构造的落后 store 替身：commit 位置形参不足（红证夹具）"""


class StaleStore:
    async def load(self, sid):
        return {}

    async def commit(self, sid):        # 生产是 (session_id, state) —— 少一个
        return True
'''

_KWARGS_MEMORY = '''\
"""R2：`**kw` 替身（生产按关键字传参 ⇒ 完全兼容）"""


class KwargsMemory:
    async def save_message(self, **kw):
        return "msg"
'''

_EXACT_MEMORY = '''\
"""R2：签名与生产完全一致的替身"""


class ExactMemory:
    async def save_message(self, session_id, role, content, tool_calls=None,
                           tenant_id=None, content_type="text", extra_metadata=None,
                           interactive=None, tool_results=None):
        return "msg"
'''

_UNRELATED = '''\
"""R2：不遮蔽生产方法名的类 —— 名字像替身也好、完全无关也好，都不得误报"""


class SessionMemoryFactory:
    def __call__(self, *args, **kwargs):
        return object()


class TestSessionMemoryHelpers:
    def test_something(self):
        assert True


class UnrelatedThing:
    def save(self, payload, **kw):
        return payload
'''


def _inject(root: Path, *sources: str) -> Path:
    """落盘注入：把夹具源码写成真实文件（守卫扫的是**文件**，不是内存里的类）"""
    root.mkdir(parents=True, exist_ok=True)
    for i, src in enumerate(sources):
        (root / f"fixture_{i}.py").write_text(src, encoding="utf-8")
    return root


def test_flags_stale_save_message_double(tmp_path):
    """红证 ①：显式签名落后（缺参数）⇒ 必报"""
    result = _scan([_inject(tmp_path, _STALE_SAVE_MESSAGE)])
    assert [(f.double, f.method) for f in result.findings] == [("StaleMemory", "save_message")], \
        result.findings
    for expected_missing in ("tool_calls", "tool_results"):
        assert expected_missing in result.findings[0].why, result.findings[0].why
    report = _report(result.findings)
    # R5：fail-closed 的报错必须**带建议**，且建议要匹配调用口径（关键字 ⇒ 提 `**kwargs`）
    assert "suggestion：" in report and "**kwargs" in report, report


def test_flags_store_double_with_short_positional_arity(tmp_path):
    """红证 ②：store 替身位置形参不足 ⇒ 必报（`load` 够、`commit` 不够 ⇒ 只报 commit）"""
    result = _scan([_inject(tmp_path, _STALE_STORE)])
    assert [(f.double, f.method) for f in result.findings] == [("StaleStore", "commit")], \
        result.findings
    assert result.counts[("app/memory/session_state_store.py", "SessionStateStore")] == 1


def test_accepts_kwargs_double(tmp_path):
    """R2 阴性负例：`**kw` 替身不得误报（生产按关键字传参 ⇒ 它完全兼容）"""
    result = _scan([_inject(tmp_path, _KWARGS_MEMORY)])
    assert result.findings == [], result.findings
    assert result.counts[("app/memory/session_memory.py", "SessionMemory")] == 1


def test_accepts_exact_signature_double(tmp_path):
    """R2 阴性负例：签名完全一致的替身不得误报"""
    result = _scan([_inject(tmp_path, _EXACT_MEMORY)])
    assert result.findings == [], result.findings


def test_ignores_classes_that_do_not_shadow_production_methods(tmp_path):
    """R2 阴性负例：**类名不构成判据** —— 名字像替身（`SessionMemoryFactory`）或完全无关的
    类，只要没遮蔽生产方法名就一律不得误报"""
    result = _scan([_inject(tmp_path, _UNRELATED)])
    assert result.findings == [], result.findings
    assert result.counts == {}, result.counts
    assert result.doubles == set(), result.doubles


def test_fails_closed_when_no_double_is_found(tmp_path):
    """fail-closed 红证：扫描根里一个替身都没有 ⇒ 必须报错，不许静默通过"""
    result = _scan([tmp_path])
    assert result.findings == [], result.findings
    with pytest.raises(pytest.fail.Exception):
        _fail_closed(result.counts)


def test_fails_closed_when_production_source_is_unreadable(tmp_path, monkeypatch):
    """fail-closed 红证：读不到生产源 ⇒ 必须报错（不许「读不到就通过」）"""
    monkeypatch.setattr(__name__ + ".SERVICE_ROOT", tmp_path)   # 生产模块全都不存在
    with pytest.raises(pytest.fail.Exception):
        _scan([tmp_path])


def test_fails_closed_when_production_class_is_renamed(monkeypatch):
    """fail-closed 红证：生产类被改名/搬迁 ⇒ 必须报错（否则守卫恒真空转）"""
    monkeypatch.setitem(REGISTRY, ("app/memory/session_memory.py", "SessionMemoryRenamed"),
                        (("save_message",), {"save_message": KEYWORD}))
    with pytest.raises(pytest.fail.Exception):
        _scan([])


# ──────────────────────────────────────────────────────────────────────────────
# ② 真实树：#4070 的主判据
# ──────────────────────────────────────────────────────────────────────────────


def test_real_tree_scan_turns_red_when_a_stale_double_is_injected(tmp_path):
    """「真实树那条判据**能红**」的直接证明：把落后替身注入**扫描范围** ⇒ 必红。

    不往仓库里写文件 —— 扫描根是 `_scan` 的参数，与真实树用例走**同一条**代码路径，
    故这里红得起来 ⇒ `test_no_double_signature_lags_the_production_signature` 也红得起来。
    """
    assert _scan(TEST_ROOTS).findings == [], (
        "真实树本应干净 —— 先看 test_no_double_signature_lags_the_production_signature 的报错")
    dirty = _scan((*TEST_ROOTS, _inject(tmp_path, _STALE_SAVE_MESSAGE)))
    assert [(f.double, f.method) for f in dirty.findings] == [("StaleMemory", "save_message")], \
        dirty.findings


def test_detector_scans_the_known_doubles_in_the_real_tree():
    """解析器自证 + fail-closed：已知的 7 个 `save_message` 替身必须都被扫到"""
    result = _scan(TEST_ROOTS)
    _fail_closed(result.counts)
    missing = KNOWN_SAVE_MESSAGE_DOUBLES - result.doubles
    assert not missing, (
        "已知 save_message 替身没被扫到（解析器失效、替身被删/改名）：\n"
        + "\n".join(f"  {p}::{c}" for p, c in sorted(missing))
        + "\nsuggestion：若替身确实被删/改名，同步 KNOWN_SAVE_MESSAGE_DOUBLES 并说明理由；"
          "否则说明本守卫的识别口径已静默失效（那正是 #4070 要防的形态）。"
    )


def test_no_double_signature_lags_the_production_signature():
    """#4070 主判据：现存替身的签名不得落后于生产签名"""
    result = _scan(TEST_ROOTS)
    assert result.findings == [], _report(result.findings)