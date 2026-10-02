# case_ids: MC-067
"""米宝**主动新手引导**（issue #5989 · P2）**静态面**判据 —— **只读源码文本 / AST，不 import 运行时依赖**。

## 为什么必须静态（issue #5989 的一条硬约束，实测踩到）

CI 的 `ci workflow helper unit tests` job **只装 `pytest pyyaml`**（不装 `pydantic` / `langchain_core` /
`fastapi`）⇒ 本文件**不得** `import app.*`。uv 实测：把 `app.context.page_registry`（它会经
`app.tools.base` 拉 pydantic + 环境变量）拉进本层 ⇒ 该 job **直接红**（本地有依赖、CI 没有）。
判据源：`docs/wiki/Change-Blast-Radius.md` 的「陷阱 1」。
⇒ **行为面**（真跑 `_handle_page_enter_request` / `build_proactive_push`）一律在
`backend/ai-agent-service/tests/test_proactive_onboarding.py`（那里有依赖），本文件判
「**源码里有没有这件事**」。两处**不重复**同一断言。

## 本文件判什么（逐条对应 issue #5989 的必做判据在**接线面**的那一半）

| # | 判据 | 会怎么红 |
|---|---|---|
| 1 | **接线在**：`send_message` 里 `__PAGE_ENTER__` 的分派**先于** `page_context`，且 handler 真的调用了判定本体 `build_proactive_push` | 摘掉分派 / 换顺序 / handler 不调判定 ⇒ 红 |
| 2 | **不新建推送基础设施**：新增段里没有 `asyncio.create_task` / `sleep` / `Queue` / `Thread` 等原语，只 `yield` 两种 SSE 事件 | 有人塞一个后台任务或定时 ⇒ 红 |
| 3 | **依赖面**：`menu_navigator.py` **不 import** `page_registry`（也不 import 任何 `app.*`）⇒ 它能被「只装 pytest/pyyaml」的解释器直接加载 | 恢复那条 import ⇒ 红 |
| 4 | **结构面（无步骤）**：判定输出只有一个 `to_data()`，其键是**闭集**且不含 `steps` | 塞一个 `steps` 键 ⇒ 红 |
| 5 | **文案面（无步骤词）**：`render()` / `page_capabilities()` 里**不出现**受控步骤词（若受控词表漂移 ⇒ 本判据在文件尾自证会红） | 往文案里写「先点…」⇒ 红 |
| 6 | **默认拒绝**：不发理由的闭集 `PUSH_REASONS` 四种齐全（一个不多一个不少） | 少一种 / 多一种 ⇒ 红 |
| 7 | **权限码不新造**：本包**没有**新增权限码 / 菜单码（不碰 `menu.ts`、不碰权限目录） | 让本包去改 `menu.ts` ⇒ 红 |
| 8 | **前端只递交不判定**：TS 侧把 route 放进 `__PAGE_ENTER__|` 消息体，且**不**自带「哪些页面能推」的清单 | 前端抄一份页面清单 ⇒ 红 |

## 明确不在本文件射程（照实登记）

- 真跑行为、超时、会话守卫、（`/orders/123` 这类**子页面**不推）：`backend/ai-agent-service/tests/test_proactive_onboarding.py`；
- 前端真调用（路由变化 ⇒ 递事件）：`frontend/admin-web/tests/unit/store/chat-proactive-onboarding.test.ts`；
- **LLM 行为**：主动提示**不经 LLM** ⇒ 无模型自由度可判（这也是本包不需要跑真实 LLM 评测的原因）。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Tuple

import pytest

REPO_ROOT = next(
    p for p in Path(__file__).resolve().parents if (p / ".github" / "cases").is_dir()
)
AI_SERVICE = REPO_ROOT / "backend" / "ai-agent-service"
NAV_MODULE = AI_SERVICE / "app" / "context" / "menu_navigator.py"
CHAT_API = AI_SERVICE / "app" / "api" / "chat.py"
MENU_TS = REPO_ROOT / "frontend" / "admin-web" / "src" / "config" / "menu.ts"
CHAT_STORE = REPO_ROOT / "frontend" / "admin-web" / "src" / "store" / "chat.ts"
LAYOUT_TSX = REPO_ROOT / "frontend" / "admin-web" / "src" / "app" / "(dashboard)" / "layout.tsx"
P1_STATIC_TEST = REPO_ROOT / "tests" / "unit_ci_workflows" / "test_menu_navigator.py"

#: 判定输出的**键闭集**（结构面判据）：多一个键就红 ⇒ `steps` 这类字段进不来。
PROACTIVE_DATA_KEYS = frozenset(
    {"proactive", "featureId", "label", "route", "capabilities", "citation"}
)

#: 不发理由的**闭集**判定本体里的四个常量名（判据 6）。
PUSH_REASON_NAMES = (
    "PUSH_REASON_UNREGISTERED",
    "PUSH_REASON_NOT_VISIBLE",
    "PUSH_REASON_ALREADY_PUSHED",
    "PUSH_REASON_AMBIGUOUS_ROUTE",
)

#: 「主动推送」段在 `chat.py` 里的**起始锚**（用可检索文本，不用行号 —— 行号几分钟就失效）。
PAGE_ENTER_ANCHOR = "#: 客户端**首次进入某个页面**时发的轻量轮次前缀"


def _read(path: Path) -> str:
    assert path.is_file(), f"被判据引用的文件不存在：{path}（路径漂移 ⇒ 红）"
    return path.read_text(encoding="utf-8")


def _step_words() -> Tuple[str, ...]:
    """受控步骤词表 —— **复用 P1 判据的同一份**（不造第二套口径）。

    ⚠️ 若那份词表被改名/删除 ⇒ 本文件**报错**（不是 skip）—— 断言两处不许静默失配。
    """
    tree = ast.parse(_read(P1_STATIC_TEST))
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == "STEP_WORDS":
            words = ast.literal_eval(node.value)
            assert words, "受控步骤词表为空 ⇒ 判据 5 会退化成恒绿"
            return tuple(words)
    raise AssertionError("在 P1 判据里找不到 STEP_WORDS（受控词表单一源漂移 ⇒ 红）")


def _p2_section(source: str) -> str:
    """`menu_navigator.py` 的 P2 段（从 P2 段头到文件尾）。"""
    marker = "# P2（主动新手引导，issue #5989 下半场）"
    idx = source.find(marker)
    assert idx > 0, "menu_navigator.py 里找不到 P2 段头（本轮改动的唯一落点）"
    return source[idx:]


def _page_enter_section(source: str) -> str:
    """`chat.py` 的主动推送段（锚 → `_send_plain_message` 之前）。"""
    start = source.find(PAGE_ENTER_ANCHOR)
    assert start > 0, "chat.py 里找不到主动推送段（锚文本漂移 ⇒ 红）"
    end = source.find("async def _send_plain_message", start)
    assert end > start, "主动推送段之后应当紧跟 `_send_plain_message`"
    return source[start:end]


def _function_source(source: str, name: str, *, drop_docstring: bool = False) -> str:
    """按 AST 取某个函数/方法的源码片段（**行号无关** —— 不许写裸行号引用）。

    `drop_docstring=True`：去掉函数自己的 docstring —— 本仓的文风里 docstring 会**明确写出**
    被禁止的反面例子（「不要写『先点…』」），把它算进文案判据就是「判据被自己的文案喂红」
    （`migao-dev-flow` §17.3）。
    """
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            if not drop_docstring:
                return ast.get_source_segment(source, node) or ""
            body = list(node.body)
            is_doc = (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            )
            lines = source.splitlines()
            start = (body[1] if is_doc and len(body) > 1 else node).lineno
            end = node.end_lineno or start
            return "\n".join(lines[start - 1:end])
    raise AssertionError(f"找不到函数 {name}（改名/删除 ⇒ 红）")


def _ts_function_source(source: str, pattern: str) -> str:
    """按**花括号配平**从 TypeScript 源码里切出一段（TS 不能用 Python 的 AST）。"""
    m = re.search(pattern, source)
    assert m, f"TS 源码里找不到 `{pattern}`（改名/删除 ⇒ 红）"
    i = source.index("{", m.end() - 1)
    depth = 0
    for j in range(i, len(source)):
        if source[j] == "{":
            depth += 1
        elif source[j] == "}":
            depth -= 1
            if depth == 0:
                return source[i:j + 1]
    raise AssertionError(f"花括号未配平：{pattern}")


def _data_dict_keys() -> set:
    """`ProactivePush.to_data()` 里 `return {...}` 字面量的键集合（**AST**，不扫原文）。"""
    tree = ast.parse(_read(NAV_MODULE))
    fn = None
    for cls in [n for n in tree.body if isinstance(n, ast.ClassDef)]:
        if cls.name != "ProactivePush":
            continue
        fn = next(
            (n for n in cls.body
             if isinstance(n, ast.FunctionDef) and n.name == "to_data"),
            None,
        )
    assert isinstance(fn, ast.FunctionDef), (
        "找不到 `ProactivePush.to_data`（被判对象漂移 ⇒ 红）"
    )
    for node in ast.walk(fn):
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
            return {k.value for k in node.value.keys if isinstance(k, ast.Constant)}
    raise AssertionError("`to_data` 没有返回 dict 字面量（结构面判据拿不到键集合 ⇒ 红）")


class TestWiring:
    """判据 1：**接线在**（`migao-dev-flow` §28.2：判据本体绿 ≠ 接线在）。"""

    def test_page_enter_dispatch_exists_in_send_message(self) -> None:
        body = _function_source(_read(CHAT_API), "send_message")
        assert "PAGE_ENTER_PREFIX" in body, "`send_message` 没有分派进页协议 ⇒ 前端递了也没人接"
        assert "_handle_page_enter_request" in body, "分派存在但没有对应的 handler"

    def test_page_enter_dispatch_precedes_page_context(self) -> None:
        """顺序即语义：进页轮次**不是**问问题 ⇒ 不许被族 4 的 `page_context` 分支抢走。"""
        body = _function_source(_read(CHAT_API), "send_message")
        assert body.index("PAGE_ENTER_PREFIX") < body.index("page_context is not None"), (
            "`__PAGE_ENTER__` 的分派必须排在 `page_context` 分支之前"
        )

    def test_handler_calls_the_decision_body(self) -> None:
        """接线锚（摘掉 ⇒ 红）：handler 里必须真的调用判定本体 `build_proactive_push`。"""
        body = _function_source(_read(CHAT_API), "_handle_page_enter_request")
        assert "build_proactive_push(" in body, (
            "`_handle_page_enter_request` 没有调用判定本体 ⇒ 接线断了（本判据就是摘线注入点）"
        )
        assert "PAGE_ENTER_PREFIX" in body, "handler 没有按前缀切 payload"

    def test_frequency_cap_is_server_side(self) -> None:
        """「每页每会话 ≤ 1 次」必须落在**服务端**（`already_pushed` 从会话状态读，不读客户端）。"""
        body = _function_source(_read(CHAT_API), "_handle_page_enter_request")
        assert "_load_pushed_features" in body and "_commit_pushed_feature" in body, (
            "上限臂不在服务端 ⇒ 上限只靠前端自觉（判据要求服务端可判）"
        )
        assert body.index("_commit_pushed_feature") < body.index("_push_stream"), (
            "顺序即安全顺序：**先记账、后推送**（否则重复推比漏推更糟）"
        )
        # commit 的返回值**必须被取用**（它用 False 表示写失败，不抛异常）
        commit_body = _function_source(_read(CHAT_API), "_commit_pushed_feature")
        assert re.search(r"return\s+bool\(", commit_body), (
            "`_commit_pushed_feature` 丢掉了 commit 的返回值 ⇒ 把「没记上」当成功（实测缺陷形态）"
        )

    def test_role_is_never_read_from_the_client(self) -> None:
        """越权面：主动推送段**不读** payload 里的 role / permissions（角色只从服务端会话取）。"""
        section = _page_enter_section(_read(CHAT_API))
        assert 'payload.get("role")' not in section, "读了客户端递交的 role"
        assert 'payload.get("permissions")' not in section, "读了客户端递交的 permissions"
        assert "current_user" in section, "连服务端会话身份都没用 ⇒ 裁剪无源"


class TestNoPushInfrastructure:
    """判据 2：**不新建推送基础设施**（无 SSE 主动推 / 无定时 / 无队列）。"""

    FORBIDDEN_PRIMITIVES = (
        "asyncio.create_task", "asyncio.sleep", "asyncio.Queue", "threading.Thread",
        "BackgroundTasks", "aioredis", "celery", "apscheduler",
    )

    def test_section_has_no_background_primitive(self) -> None:
        section = _page_enter_section(_read(CHAT_API))
        hits = [p for p in self.FORBIDDEN_PRIMITIVES if p in section]
        assert hits == [], f"主动推送段里出现推送基础设施原语 {hits} —— 本包有意不建"

    def test_push_stream_yields_only_text_and_done(self) -> None:
        """命中时只回 `text` + `done`（复用既有 SSE 形态，不是新通道）。"""
        body = _function_source(_read(CHAT_API), "_handle_page_enter_request")
        assert "SSEEvent.text(" in body and "SSEEvent.done(" in body
        assert "SSEEvent.card(" not in body and "SSEEvent.interactive(" not in body

    def test_no_llm_or_page_context_injection(self) -> None:
        body = _function_source(_read(CHAT_API), "_handle_page_enter_request")
        assert "send_message(" not in body, "主动推送**不经 LLM**（文案全部来自登记表）"
        assert "render_page_context" not in body and "build_page_context" not in body, (
            "进页轮次不该注入族 4 的页面上下文（那是「问问题」的轮次）"
        )


class TestDependencySurface:
    """判据 3：`menu_navigator.py` 必须能被「只装 pytest/pyyaml」的解释器加载。"""

    def test_navigator_imports_no_app_module(self) -> None:
        source = _read(NAV_MODULE)
        tree = ast.parse(source)
        bad = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("app"):
                bad.append(node.module)
            if isinstance(node, ast.Import):
                bad += [a.name for a in node.names if a.name.startswith("app")]
        assert bad == [], (
            f"menu_navigator.py 引入 app.* 依赖 {bad} ⇒ 只装 pytest/pyyaml 的 CI job 会直接红"
            "（`docs/wiki/Change-Blast-Radius.md` 陷阱 1）"
        )

    def test_navigator_third_party_imports_are_stdlib_only(self) -> None:
        source = _read(NAV_MODULE)
        allowed = {"__future__", "re", "dataclasses", "typing"}
        mods = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                mods.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods.add(node.module.split(".")[0])
        assert mods <= allowed, f"menu_navigator.py 出现非标准库依赖 {sorted(mods - allowed)}"

    def test_route_normalizer_is_single_semantics_with_page_registry(self) -> None:
        """两侧「路径规范化」**逐条同语义**（本模块不能 import 它 ⇒ 用同语料核语义）。"""
        nav_source = _read(NAV_MODULE)
        pr_source = _read(AI_SERVICE / "app" / "context" / "page_registry.py")
        for anchor in ("_ROUTE_MAX_LEN = 200", r'^/[A-Za-z0-9/_.\-]*$'):
            assert anchor in nav_source, f"menu_navigator 的路径口径缺少 `{anchor}`"
            assert anchor in pr_source, f"page_registry 的路径口径缺少 `{anchor}`（两侧漂移）"


class TestNoStepsSurface:
    """判据 4 / 5：**只给导航不给步骤** —— 结构 + 文案双层。"""

    def test_data_keys_are_a_closed_set_without_steps(self) -> None:
        """结构面：`to_data()` 的键闭集 —— **用 AST 取真语法单元**（不按引号扫原文）。

        ⚠️ 本判据的**唯一实现**是 `_data_dict_keys()`；`tests/unit_ci_workflows/`
        里凡「判据自己解析被测源码」的写法都必须过 `test_guard_parsing_is_comment_aware.py`
        那道元守卫（按引号扫原文 = 注释/docstring 就能把它喂中）—— 本条按它的修法 ① 改 AST。
        """
        keys = _data_dict_keys()
        assert keys == PROACTIVE_DATA_KEYS, f"data 键与闭集不一致：{sorted(keys)}"
        assert "steps" not in keys

    def test_render_and_capabilities_contain_no_step_words(self) -> None:
        section = _p2_section(_read(NAV_MODULE))
        words = _step_words()
        for fn in ("render", "page_capabilities"):
            body = _function_source(section, fn, drop_docstring=True)
            hits = [w for w in words if w in body]
            assert hits == [], f"`{fn}` 的文案里出现受控步骤词 {hits}"

    def test_no_steps_notice_is_rendered(self) -> None:
        """如实告知「不给步骤」那句必须在文案里（用户裁定的口径要能被用户看见）。"""
        section = _p2_section(_read(NAV_MODULE))
        assert "PROACTIVE_STEPS_NOTICE" in _function_source(section, "render")
        assert "操作步骤不在本轮" in section


class TestFailClosedSurface:
    """判据 6：不发理由的**闭集**（一个不多一个不少）。"""

    def test_reason_closure(self) -> None:
        section = _p2_section(_read(NAV_MODULE))
        for name in PUSH_REASON_NAMES:
            assert f"{name} = " in section, f"缺少不发理由常量 {name}"
        closure = re.search(r"PUSH_REASONS: Tuple\[str, \.\.\.\] = \((.*?)\)", section, re.S)
        assert closure, "找不到 PUSH_REASONS 闭集"
        members = set(re.findall(r"PUSH_REASON_[A-Z_]+", closure.group(1)))
        assert members == set(PUSH_REASON_NAMES), f"闭集与常量不一致：{sorted(members)}"

    def test_every_deny_path_returns_empty_push(self) -> None:
        """四条不发出口**都**返回 `ProactiveVerdict(<reason>)`（不带 push）⇒ 结构上推不出文案。"""
        body = _function_source(_p2_section(_read(NAV_MODULE)), "build_proactive_push")
        for name in PUSH_REASON_NAMES:
            assert f"ProactiveVerdict({name})" in body, f"{name} 的出口没有返回空 push"

    def test_verdict_exposes_should_push_gate(self) -> None:
        section = _p2_section(_read(NAV_MODULE))
        assert "def should_push" in section, "判定结果没有单一的「发不发」入口"


class TestBlastRadius:
    """判据 7：本包**不新造权限码 / 不碰菜单单一源**。"""

    def test_menu_ts_is_untouched_by_this_package(self) -> None:
        """`menu.ts` 是菜单单一源；主动引导只**读**它（经 P1 镜像）⇒ 本包不该改它。"""
        import subprocess

        diff = subprocess.run(
            ["git", "diff", "--name-only", "origin/main", "--", str(MENU_TS.relative_to(REPO_ROOT))],
            cwd=str(REPO_ROOT), capture_output=True, text=True,
        )
        assert diff.stdout.strip() == "", f"本包改了菜单单一源：{diff.stdout.strip()}"

    def test_p1_registry_is_reused_not_copied(self) -> None:
        """🔴 不许另造第二份真值：P2 段只**引用** P1 的 `MENU_TREE` / `NAV_FEATURES`。"""
        section = _p2_section(_read(NAV_MODULE))
        assert "MENU_TREE" in section and "NAV_FEATURES" in section
        assert "MenuNode(" not in section, "P2 段里手抄了菜单节点（第二份真值）⇒ 红"


class TestFrontendOnlySubmits:
    """判据 8：前端**只递交**，判定唯一真值在服务端。"""

    def test_store_sends_the_page_enter_event(self) -> None:
        source = _read(CHAT_STORE)
        assert "__PAGE_ENTER__|" in source, "前端没有递交进页事件 ⇒ 服务端判定永远收不到输入"
        assert "notifyPageEnter" in source

    def test_store_does_not_carry_a_page_list(self) -> None:
        """前端不许自带「哪些页面能推」的清单（否则就是第二份真值）。"""
        body = _ts_function_source(_read(CHAT_STORE), r"notifyPageEnter:\s*async\s*\(")
        assert "MENU" not in body and "/products" not in body and "feature" not in body.lower(), (
            "前端自带页面清单 ⇒ 判定被复制到了客户端"
        )

    def test_layout_triggers_on_route_change(self) -> None:
        """**首次进页**的触发面：面板所在布局在路由变化时递一轮（不看窗口宽度）。"""
        source = _read(LAYOUT_TSX)
        assert "notifyPageEnter" in source, "页面侧没有触发点 ⇒ 主动引导永远不会发生"
        assert re.search(r"\}, \[pathname[^\]]*\]\)", source), (
            "触发没有挂在 pathname 变化上（必须是「进页」事件，不是任意重渲染）"
        )
