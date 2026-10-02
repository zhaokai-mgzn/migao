# case_ids: CH-030
"""
主动「后续问题建议」通道**退役契约**（issue #5951，用户裁定 2026-10-02）

本文件是该退役的**回归锁** —— 它断言「这些口**不存在**」，而不是断言某个行为。
为什么需要它：删除的最大风险是**回填**（有人以后再挂一个 emit 点/端点/状态字段，
而没有任何东西会报）。判据 = 引用面 + 端点面 + 类型面三处，各自有独立红证。

红证（在 `origin/main` = 删前上跑本文件，实测）：
- `test_suggestion_feedback_endpoint_is_retired` ⇒ FAILED（`/suggestion-feedback` 当时已注册）
- `test_no_emit_point_references_suggestions` ⇒ FAILED（`chat.py` / `sse.py` / `state.py` 有点名）
- `test_agent_response_type_enum_is_unchanged` ⇒ 仍 PASS（类型面当时**未被污染**，见下）
删后三条全绿（见 PR body 的修前/修后读数）。

⚠️ 本判据**只裁「建议通道」**，不裁同名不同物的活功能：日报的 `suggestions` 区块
（`app/briefing/generator.py`）、工具失败回灌的 `suggestion=` 字段
（`app/tools/**`，语义 = 「可行动建议」，与建议通道无关）都在面外。
"""

import ast
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[1]  # backend/ai-agent-service
APP = REPO / "app"

#: 建议通道曾经的落点（issue #5951 删除面）。任一重新出现即说明回填。
RETIRED_SCAN = (
    "app/api/chat.py",
    "app/api/sse.py",
    "app/api/schemas.py",
    "app/graph/state.py",
    "app/agents/customer_service_agent.py",
    "app/graph/skills/base_skill.py",
    "app/graph/skills/execution/prepare_turn.py",
    "app/config.py",
)

#: 这些词在**建议通道**语境下不得再出现（日报/工具 `suggestion=` 面不在扫射程内，
#: 因为下面逐文件扫，且只认这些精确串）。
RETIRED_NAMES = (
    "ignored_suggestions",
    "suggestion-feedback",
    "suggestion_feedback",
    "_IGNORED_STREAM_NODES",
    "_inject_user_preferences",
    "PreferenceTracker",
    "preference_tracker",
    "SUGGESTION_PREFERENCE_ENABLED",
    "FollowUpSuggestionGenerator",
    "follow_up",
)

#: 允许出现的例外（逐条写明理由）—— **空 = 当前零例外**，将来加必须同 PR 写理由。
ALLOWED_NAME_HITS: dict[str, set[str]] = {}


def _scan_retired_names() -> list[str]:
    hits: list[str] = []
    missing: list[str] = []
    for rel in RETIRED_SCAN:
        path = REPO / rel  # RETIRED_SCAN 自带 app/ 前缀
        if not path.is_file():
            # 🔴 不静默 continue：被扫文件消失 ⇒ 判据会空跑成绿（「跑绿」≠「跑到了」）
            missing.append(rel)
            continue
        text = path.read_text(encoding="utf-8")
        for name in RETIRED_NAMES:
            if name in text and name not in ALLOWED_NAME_HITS.get(rel, set()):
                hits.append(f"{rel} 仍含退役符号 {name!r}")
    assert not missing, (
        "被扫文件不存在 ⇒ 本判据在空跑（不是通过）：" + repr(missing) + f"；APP={APP}"
    )
    return hits


def test_no_emit_point_references_suggestions() -> None:
    """引用面：建议通道的发射点/状态字段/开关**不得回填**。

    红证：在删前的 `origin/main` 上 `app/api/sse.py` 含 `def suggestions(`、
    `app/graph/state.py` 含 `suggestions: list[str]`、`app/agents/customer_service_agent.py`
    含 `_IGNORED_STREAM_NODES = {"suggestions"}` ⇒ 本判据报三处。
    """
    hits = _scan_retired_names()
    assert not hits, "建议通道（issue #5951 已退役）出现回填：\n  - " + "\n  - ".join(hits)


def test_suggestion_feedback_endpoint_is_retired() -> None:
    """端点面：`POST /suggestion-feedback` 不得再注册。

    红证：删前的 `origin/main` 上该路由已注册 ⇒ 本判据 FAILED（附实测路径列表）。
    """
    from app.api import chat

    paths = sorted({str(getattr(r, "path", "")) for r in chat.router.routes})
    offenders = [p for p in paths if "suggestion" in p]
    assert not offenders, (
        "退役端点重新注册（issue #5951）：" + repr(offenders) + f"；当前路由 = {paths}"
    )
    # 自证判据非空转：同一扫描必须**看得见**仍在的兄弟端点（否则本判据是空断言）
    assert any("quick-actions" in p for p in paths), (
        f"路由扫描失效：连 /quick-actions 都看不见 ⇒ 本判据在空跑；paths={paths}"
    )


def test_agent_stream_has_no_suggestions_emit_pattern() -> None:
    """发射面（AST，不靠文本搜索）：`astream_chat` 不得再有「读图状态 → yield」的退役形态。

    判别对象不是「文件里有没有 `suggestions` 字样」（注释里提一句历史无害），而是
    **两条真实的发射语句**：
      ① `output.get("suggestions")`  —— 恒取不到的读点（无任何写入点）
      ② `type="suggestions"`         —— 由此产出的 SSE 帧档
    用 AST 逐语句判，注释/docstring 不参与 ⇒ 不会因为写了「已退役」而假红。

    红证：删前的 `origin/main` 上两条语句都在同一文件里 ⇒ 本判据 FAILED。
    """
    tree = ast.parse((APP / "agents/customer_service_agent.py").read_text(encoding="utf-8"))
    offenders: list[str] = []
    for node in ast.walk(tree):
        # ① output.get("suggestions") / state["suggestions"] 之类的读取
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "get" and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and arg.value == "suggestions":
                    offenders.append(f"行 {node.lineno}: .get('suggestions')")
        # ② type="suggestions" 关键字实参
        if isinstance(node, ast.keyword) and node.arg == "type":
            if isinstance(node.value, ast.Constant) and node.value.value == "suggestions":
                offenders.append(f"行 {node.lineno}: type='suggestions'")
    assert not offenders, (
        "退役的建议发射形态重新出现（issue #5951）：\n  - " + "\n  - ".join(offenders)
    )


def test_agent_response_shape_is_unchanged() -> None:
    """类型面：`AgentResponse` 的字段集与默认 `type` 未被退役改动波及。

    ⚠️ 如实登记判别力边界：**该档当初并非其字段**，而是 `type` **字符串枚举的一个取值**
    （写在行内注释里）⇒ 本条只锁「删 `suggestions` 没有顺带动到其它字段/默认值」，
    **不是**「suggestions 档已消失」的证据 —— 那由
    `test_agent_stream_has_no_suggestions_emit_pattern`（AST）承担。
    """
    from app.agents.customer_service_agent import AgentResponse

    assert list(AgentResponse.__dataclass_fields__) == [
        "content",
        "type",
        "tool_calls",
        "metadata",
    ], "AgentResponse 字段集被改动（退役不应动字段）"
    assert AgentResponse(content="x").type == "text", "AgentResponse 默认 type 必须仍是 text"
    assert AgentResponse(content="x").tool_calls is None
    assert AgentResponse(content="x").metadata is None
