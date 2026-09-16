# case_ids: API-002, UI-017
"""卡型跨端契约不变式：「后端能发到这一端的卡型 ⊆ 这一端能渲染的卡型」（issue #3960）。

## 缺陷形态（本文件守卫的那道此前无人守卫的接缝）

后端 `app/api/chat.py::_detect_card_type` 是**卡型的唯一产出源**，它按工具名下发类型：
`product_list` / `product_detail` / `logistics` / `order` / `quotation`。此前没有任何机械守卫：

- C 端 `frontend/mini-app/src/components/chat/MessageBubble.tsx::renderCard` 实现 9 种，含 `quotation` → 齐全；
- B 端移动 `frontend/bmini-app/src/components/chat/MessageBubble.tsx::renderCard` 与 C 端同族 → 齐全；
- B 端桌面 `frontend/admin-web/src/components/chat/ToolResultCard.tsx` 只实现 5 种、**不含 `quotation`**，
  且 `default` 分支把内部类型名回显成「未知卡片类型: quotation」灰盒 ——
  既**没有任何按钮**（不可理解、不可点击），又把**内部类型名泄漏**给商家用户。

生产表现 = 「弹了个不能点的卡」，而新增/改动卡型时**不会有任何东西变红**。本文件就是那道护栏。

## 判据为什么是「persona 可达性」而不是朴素的 `backend ⊆ 每端`

朴素断言 `_detect_card_type` 的**全局值域 ⊆ B端桌面` 无法通过、也不该通过：
`curtain_calc`（→ `quotation`）是 **C 端专属**工具（`base_skill.py` 写死「C 端专属：`curtain_calc`
是小布（顾客自助）的报价能力；B 端米宝有自己的算料链路」，且只出现在
`customer_quote_skill.py::CUSTOMER_QUOTE_TOOLS`）—— B 端米宝**永远收不到** `quotation` 卡，
强行要求 B 端桌面渲染它是**过度建设**（无数据形态可依）。

正确判据 = **按 persona 从 Skill 注册表推导可达卡型**（真值，非人工清单）：

    reachable(persona) = ⋃ { _detect_card_type(t) | t ∈ skill.tool_names, persona ∈ skill.system_prompts }
    断言：reachable(persona) ⊆ 该 persona 每个渲染端的 case 集合

实测（@ 本 PR 的 origin/main）：`mibao` 可达 `{product_list, product_detail, logistics, order}`，
`xiaobu` 另有 `quotation` —— 与产品口径、与 `base_skill.py` 的注释三方一致。
这样判定的是「**后端真能发到这一端**的卡型」，而不是「后端函数理论上能返回的卡型」；
判据随注册表自动前进：**谁把 `curtain_calc` 绑给米宝的 Skill，这里立刻红**（那正是本接缝的复发形态）。

另加一条全局判据：`_detect_card_type` 的值域必须 ⊆ 全部渲染端 case 的并集
（任何卡型至少有一端能渲染 —— 不许存在「谁都渲染不了」的卡型）。

## 真值来源（刻意不靠「扫注释猜」）

1. **后端卡型**：对**真实函数** `_detect_card_type` 求值，工具名取自**工具注册表**、
   persona→工具取自 **Skill 注册表**（`skill.tool_names` × `skill.system_prompts`）。
2. **渲染集合**：读**源码真值**，取 `switch (card.type)` 的 `case '<type>':` 标签。
   `MessageBubble.tsx` 一个文件两个 switch（卡型在 `renderCard`、交互组件在 `renderInteractive`），
   故提取必须**限定在 `renderCard` 函数体内**；且判据只读**去注释后**的代码 ——
   实测踩过：`renderCard` 的 `default` 上方注释写着「未知卡片类型…」，
   不剥注释会让「泄漏内部术语」判据在 C 端**假红**（判据扫到注释而非渲染文本）。
3. **防静默空跑**：`_CARD_TOOL_ANCHORS` 与若干自断言保证「提取器坏掉 ⇒ 空集 ⇒ 子集断言真空通过」
   这条假绿路径被堵死（空断言 = 永远绿的断言）。

## 红证（本仓库验收协议要求「每条断言都要有红证」）

- **真实红（修复前实测）**：严格版判据报 `B端桌面 admin-web ToolResultCard 缺 ['quotation']`；
  泄漏判据报 `B端桌面 admin-web ToolResultCard：default 分支回显内部卡型名 card.type`。
- **变异红**（`TestRedProof`，每次运行都执行）：对 C 端源码真值做**文本变异**
  （删掉 `case 'quotation':` 行）后重新提取，断言 `xiaobu` 可达性判据**确实报出 `quotation` 违规** ——
  证明「断言会红」不是一次性人工验证，而是**常驻的判别性检验**。
- **构造红**：对「故意构造的、不在渲染集合里的卡型」断言必被每个渲染端判违规；
  对「故意构造的、无渲染端登记的 persona」断言必被判违规。
- **回放红**：把 B 端 `default` 还原成修复前的实现文本，泄漏判据必须能认出（证判据非空）。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.api.chat import _detect_card_type
from app.graph.skills.skill_registry import get_skill_registry
from app.tools.registry import get_tool_registry

# tests/ → ai-agent-service/ → backend/ → 仓库根
REPO_ROOT = Path(__file__).resolve().parents[3]
_CHAT_DIR = Path("src", "components", "chat")

# persona → 该 persona 的渲染端（**架构事实，不是卡型清单**）。
# 新增渲染端/新增 persona 时必须登记：未登记 persona 有卡型可达 → 判据红（见 test_every_persona_has_a_registered_end）。
PERSONA_ENDS: dict[str, tuple[str, ...]] = {
    "xiaobu": ("C端 mini-app MessageBubble",),
    "mibao": ("B端移动 bmini-app MessageBubble", "B端桌面 admin-web ToolResultCard"),
}

# 渲染端：名称 → 源文件。**加新渲染端只改这一处**（漏掉一个渲染端 = 重建一条无人守卫的接缝）。
RENDERERS = {
    "C端 mini-app MessageBubble": REPO_ROOT / "frontend" / "mini-app" / _CHAT_DIR / "MessageBubble.tsx",
    "B端移动 bmini-app MessageBubble": REPO_ROOT / "frontend" / "bmini-app" / _CHAT_DIR / "MessageBubble.tsx",
    "B端桌面 admin-web ToolResultCard": REPO_ROOT / "frontend" / "admin-web" / _CHAT_DIR / "ToolResultCard.tsx",
}

# 卡型锚点：**只用于防「提取器静默坏掉 ⇒ 子集断言真空通过」**，不是卡型清单的副本。
# 工具被重命名/删除（合法重构）时这里红 → 提示同步更新锚点与渲染端，这正是契约变更的入口。
_CARD_TOOL_ANCHORS = {
    "product_search": "product_list",
    "product_detail": "product_detail",
    "logistics_track": "logistics",
    "order_query": "order",
    "curtain_calc": "quotation",
}

# 交互组件（renderInteractive 的 switch）——不得被算作卡型
_INTERACTIVE_TYPES = {"confirm", "choice", "form"}

_CASE_TAG_RE = re.compile(r"""case\s+['"]([^'"]+)['"]""")
_TYPE_INTERPOLATION_RE = re.compile(r"\{\s*card\.type\s*\}")
_LINE_COMMENT_RE = re.compile(r"//[^\n]*")
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)


def _read(path: Path) -> str:
    """读源码真值（缺失即 fail-closed：护栏读不到被测对象时必须红，不得退化成空集）。"""
    if not path.is_file():
        raise AssertionError(f"渲染端源文件不存在：{path}（卡型契约的守卫对象消失了）")
    return path.read_text(encoding="utf-8")


def _strip_js_comments(source: str) -> str:
    """剥掉 JS/TS 注释 —— 判据必须只看**会被渲染的文本**。

    实测假红：`renderCard` 的 `default` 上方注释写着「未知卡片类型：对客户隐藏内部 type」，
    不剥注释 ⇒「泄漏内部术语」判据在 C 端红（判据扫到注释 = 「扫注释猜」的典型假红）。
    """
    return _LINE_COMMENT_RE.sub("", _BLOCK_COMMENT_RE.sub("", source))


def _function_body(source: str, func_name: str) -> str:
    """截取 `function <func_name>(...)` 到下一个顶层 `function `/`export function ` 之间的函数体。"""
    match = re.search(rf"^function\s+{re.escape(func_name)}\s*\(", source, re.MULTILINE)
    if match is None:
        raise AssertionError(f"源码里找不到 `function {func_name}(`（提取器与被测对象脱节）")
    tail = source[match.end():]
    next_top = re.search(r"^(?:export\s+)?function\s+\w+\s*\(", tail, re.MULTILINE)
    return tail[: next_top.start()] if next_top else tail


def _cases_in(source: str) -> set[str]:
    """源码片段里出现的 `case '<type>':` 标签集合。"""
    return set(_CASE_TAG_RE.findall(_strip_js_comments(source)))


def _card_switch_source(path: Path) -> str:
    """卡型 switch 所在的源码片段（按渲染端形态取真值）。

    `MessageBubble` 类组件一个文件两个 switch：卡型在 `renderCard` 内、交互组件在
    `renderInteractive` 内 —— 必须限定到 `renderCard`，否则 confirm/choice/form 被误算成卡型。
    """
    source = _read(path)
    return _function_body(source, "renderCard") if "MessageBubble" in path.name else source


def _renderer_card_types(path: Path) -> set[str]:
    """某个渲染端**卡型** switch 的渲染集合。"""
    return _cases_in(_card_switch_source(path))


def _default_branch_body(path: Path) -> str:
    """卡型 switch 的 `default:` 分支体，**已剥注释**（未知卡型的兜底渲染形态）。"""
    source = _strip_js_comments(_card_switch_source(path))
    idx = source.find("default:")
    if idx < 0:
        raise AssertionError(f"{path.name} 的卡型 switch 没有 default 分支（未知卡型将无兜底渲染）")
    return source[idx:]


def _all_backend_card_tools() -> dict[str, str]:
    """注册表里所有「会产出卡型」的工具 → 卡型（真值 = 对真实函数求值）。"""
    found: dict[str, str] = {}
    for tool_name in get_tool_registry().get_tool_names():
        card_type = _detect_card_type(tool_name, {})
        if card_type:
            found[tool_name] = card_type
    return found


def _persona_tools() -> dict[str, set[str]]:
    """persona → 该 persona 的 Skill 所绑定的工具名并集（真值 = Skill 注册表）。"""
    registry = get_skill_registry()
    skills = list(getattr(registry, "_skills", {}).values())
    if not skills:
        raise AssertionError("Skill 注册表为空 —— 可达性推导会退化成空集（恒真 = 空断言）")
    personas: dict[str, set[str]] = {}
    for skill in skills:
        for persona in (skill.system_prompts or {}):
            personas.setdefault(persona, set()).update(skill.tool_names or [])
    return personas


def reachable_card_types(persona: str) -> set[str]:
    """某 persona **实际可能收到**的卡型（由 Skill 注册表里的工具绑定推导）。"""
    tools = _persona_tools().get(persona)
    if tools is None:
        raise AssertionError(f"Skill 注册表里没有 persona「{persona}」—— 判据的被测对象不存在")
    return {t for t in (_detect_card_type(name, {}) for name in tools) if t}


def reachability_violations(
    reachable: dict[str, set[str]], renderer_types: dict[str, set[str]]
) -> dict[str, list[str]]:
    """判据（纯函数，可用构造输入做判别性检验）。

    入参 `reachable`：渲染端名 → 该端对应 persona 的可达卡型集合。
    返回 `{渲染端名: 不可渲染的卡型}`；全空 = 契约成立。
    单一实现：真实断言与红证（变异/构造）跑的是**同一份**判据，不会漂移。
    """
    return {
        name: sorted(types - renderer_types.get(name, set()))
        for name, types in reachable.items()
        if types - renderer_types.get(name, set())
    }


def _current_reachable_by_end() -> dict[str, set[str]]:
    return {
        end: reachable_card_types(persona)
        for persona, ends in PERSONA_ENDS.items()
        for end in ends
    }


def _current_renderer_types() -> dict[str, set[str]]:
    return {name: _renderer_card_types(path) for name, path in RENDERERS.items()}


class TestExtractorsAndTruthSources:
    """提取器自断言：提取坏了（空集/多算/扫注释）必须在这里红，而不是让契约断言真空通过。"""

    def test_message_bubble_extractors_are_scoped_to_render_card(self):
        for name in ("C端 mini-app MessageBubble", "B端移动 bmini-app MessageBubble"):
            types = _renderer_card_types(RENDERERS[name])
            assert {"product_list", "product_detail", "logistics", "order", "quotation"} <= types, (
                f"{name} 的 renderCard 应渲染全部真实卡型，实际提取到 {sorted(types)}"
            )
            leaked = types & _INTERACTIVE_TYPES
            assert leaked == set(), f"{name} 提取把交互组件误算成卡型：{sorted(leaked)}"

    def test_admin_web_extractor_is_non_vacuous(self):
        types = _renderer_card_types(RENDERERS["B端桌面 admin-web ToolResultCard"])
        assert types, "B 端桌面提取结果为空 —— 子集断言会真空通过（恒真的空断言）"
        assert "product_list" in types, f"B 端桌面应渲染商品列表卡，实际提取到 {sorted(types)}"

    def test_backend_extraction_is_non_vacuous(self):
        found = _all_backend_card_tools()
        missing = sorted(set(_CARD_TOOL_ANCHORS) - set(found))
        assert missing == [], (
            f"工具注册表里找不到卡型锚点工具 {missing} —— 注册表/映射被改坏，"
            f"后端卡型集合会静默缩小，子集断言将真空通过。实际枚举到：{sorted(found)}"
        )

    def test_persona_tool_derivation_is_non_vacuous(self):
        personas = _persona_tools()
        assert set(PERSONA_ENDS) <= set(personas), (
            f"登记了渲染端的 persona {sorted(set(PERSONA_ENDS) - set(personas))} 在 Skill 注册表里不存在"
            f"（可达性会退化成空集 = 空断言）。实际 persona={sorted(personas)}"
        )

    def test_extractor_ignores_comments(self):
        """提取器只看代码不看注释：注释里的 `case 'x':` 不得被算作渲染分支。"""
        assert _cases_in("// case 'ghost':\ncase 'real': {}") == {"real"}


class TestBackendCardTypeMapping:
    """backend 侧契约钉：卡型产出源 = 真实 `_detect_card_type` 求值（非注释、非清单副本）。"""

    @pytest.mark.parametrize("tool_name,expected", sorted(_CARD_TOOL_ANCHORS.items()))
    def test_detect_card_type_mapping(self, tool_name: str, expected: str):
        assert _detect_card_type(tool_name, {}) == expected

    def test_non_card_tool_returns_none(self):
        # 负例：普通读工具不下发卡片（判据必须能区分「有卡型」与「无卡型」）
        assert _detect_card_type("knowledge_search", {}) is None

    def test_quotation_is_xiaobu_only(self):
        """#3960 的产品口径落码：quotation 只对 C 端 persona 可达（B 端米宝不可达）。"""
        assert "quotation" in reachable_card_types("xiaobu")
        assert "quotation" not in reachable_card_types("mibao")


class TestCrossEndCardTypeContract:
    """核心不变式：每个 persona 可达的卡型，其每个渲染端都要有渲染分支。"""

    def test_persona_reachable_card_types_are_renderable_on_its_ends(self):
        reachable = _current_reachable_by_end()
        for end, types in reachable.items():
            assert types, f"渲染端 {end} 的 persona 未推导出任何卡型 —— 判据会真空通过"

        violations = reachability_violations(reachable, _current_renderer_types())
        assert violations == {}, (
            "后端能发到该端但该端没有渲染分支的卡型（生产表现 = 弹一个不能点的卡/占位灰盒）："
            + "；".join(f"{end} 缺 {missing}" for end, missing in violations.items())
        )

    def test_every_persona_has_a_registered_end(self):
        """未登记的 persona（新端/新 agent）一旦有卡型可达，必须红 —— 不许存在无人守卫的接缝。"""
        unregistered = {
            persona: sorted(reachable_card_types(persona))
            for persona in _persona_tools()
            if persona not in PERSONA_ENDS
        }
        assert unregistered == {}, (
            f"这些 persona 有卡型可达但没登记渲染端（新端会静默失去契约保护）：{unregistered}"
        )

    def test_no_card_type_is_unrenderable_everywhere(self):
        """全局判据：`_detect_card_type` 的任一取值都必须至少被一个渲染端渲染。"""
        all_types = set(_all_backend_card_tools().values())
        renderable = set().union(*_current_renderer_types().values())
        assert all_types - renderable == set(), (
            f"这些卡型没有任何渲染端实现（后端发出去必然落成兜底占位）：{sorted(all_types - renderable)}"
        )

    def test_default_branch_does_not_leak_internal_type_name(self):
        """未知卡型的兜底分支不得回显内部 type 名/内部术语（UI-017 口径，B 端同族）。"""
        offenders = []
        for name, path in RENDERERS.items():
            body = _default_branch_body(path)
            if _TYPE_INTERPOLATION_RE.search(body):
                offenders.append(f"{name}：default 分支回显内部卡型名 card.type")
            elif "未知卡片类型" in body:
                offenders.append(f"{name}：default 分支使用内部术语「未知卡片类型」")
        assert offenders == [], "；".join(offenders)

    def test_default_branch_shows_understandable_placeholder(self):
        """兜底分支必须给出可理解的中文占位（与 C 端「消息内容暂不支持预览」同族口径）。"""
        for name, path in RENDERERS.items():
            body = _default_branch_body(path)
            assert re.search(r"[\u4e00-\u9fa5]{4,}", body), (
                f"{name} 的 default 分支没有可读的中文占位文案：{body!r}"
            )


class TestUnreachableRendererBranches:
    """**保留但用测试标注**的反向缺口：渲染端有分支、后端**从不下发**该卡型。

    处置口径（issue #3960，最小做法）：**保留分支 + 用测试标注**，不顺手删除 ——
    反向缺口不会造成用户可见缺陷（多一个永不命中的 case 而已），
    而删除属于「顺手大改」（且 `knowledge` 是 B 端知识卡片检索的实际能力，
    未来接上 `knowledge` 卡片事件即可复用该分支）。
    真值：`SSEEvent.card` 全仓只有 `app/api/chat.py` 经 `_detect_card_type` 调用
    （`app/api/sse.py` 只提供工厂），故「后端卡型集合」就是唯一产出面。
    """

    def test_admin_web_knowledge_branch_is_currently_unreachable(self):
        """B 端桌面 `case 'knowledge'` 目前是死分支：后端从不把 `knowledge` 作为卡型下发。

        若哪天后端开始下发 `knowledge`，本用例会红 —— 那正是提醒：确认三端都接到了该卡型
        （`test_persona_reachable_card_types_are_renderable_on_its_ends` 会同时给出结论）。
        """
        assert "knowledge" not in _all_backend_card_tools().values(), (
            "后端已开始下发 knowledge 卡型 —— 请确认各渲染端分支与数据形态，并更新本标注"
        )
        assert "knowledge" in _renderer_card_types(RENDERERS["B端桌面 admin-web ToolResultCard"]), (
            "B 端桌面的 knowledge 分支已被删除 —— 若为有意清理，请同步删除本标注用例"
        )

    """红证：证明上面的判据**真的会红**（常驻判别性检验，不是一次性人工验证）。"""

    def test_violation_reported_when_a_renderer_case_is_deleted(self):
        """变异红证：文本删掉 C 端 `case 'quotation':` 后，xiaobu 可达性判据必须报出 quotation。"""
        path = RENDERERS["C端 mini-app MessageBubble"]
        original = _read(path)
        mutated = re.sub(r"^\s*case\s+'quotation':\s*\{?\s*$", "", original, flags=re.MULTILINE)
        assert mutated != original, "变异未生效（C 端源码里找不到 `case 'quotation':` 行）—— 红证实验无效"

        renderer_types = _current_renderer_types()
        mutated_end = "C端 mini-app MessageBubble（变异：删 quotation 分支）"
        renderer_types[mutated_end] = _cases_in(_function_body(mutated, "renderCard"))

        violations = reachability_violations(
            {mutated_end: reachable_card_types("xiaobu")}, renderer_types
        )
        assert "quotation" in violations.get(mutated_end, []), (
            f"删掉渲染分支后判据仍未报违规 ⇒ 断言是空断言。实际 violations={violations}"
        )

    def test_violation_reported_for_fabricated_card_type(self):
        """构造红证：故意构造一个不在任何渲染集合里的卡型，断言必被每个渲染端判违规。"""
        fabricated = "__fabricated_card_type__"
        reachable = {end: _renderer_card_types(RENDERERS[end]) | {fabricated} for end in RENDERERS}
        violations = reachability_violations(reachable, _current_renderer_types())

        assert set(violations) == set(RENDERERS), (
            f"构造的越界卡型未被每个渲染端判违规 ⇒ 判据恒真（空断言）。实际 violations={violations}"
        )
        for end, missing in violations.items():
            assert fabricated in missing, f"{end} 未报出构造卡型：{missing}"

    def test_unregistered_persona_is_flagged(self):
        """构造红证：未登记渲染端的 persona 必须被判红（防新端静默失去保护）。"""
        reachable = {"__fabricated_persona_end__": {"product_list"}}
        violations = reachability_violations(reachable, _current_renderer_types())
        assert violations == {"__fabricated_persona_end__": ["product_list"]}, (
            f"未登记的渲染端未被判红 ⇒ 「persona 必须登记」是空判据。实际 violations={violations}"
        )

    def test_leak_check_recognises_the_pre_fix_admin_web_default(self):
        """回放红证：泄漏判据必须认得出 #3960 修复前 B 端 `default` 的真实形态。"""
        pre_fix_default = (
            'default:\n      return (\n'
            '        <div className="bg-neutral-50 border border-neutral-200 rounded-lg p-3 '
            'text-xs text-neutral-500">\n'
            '          <span className="font-medium">未知卡片类型:</span> {card.type}\n'
            '        </div>\n      )'
        )
        assert _TYPE_INTERPOLATION_RE.search(pre_fix_default), (
            "泄漏判据认不出 #3960 的修复前形态 ⇒ 该判据是空断言"
        )
        assert "未知卡片类型" in pre_fix_default
