# case_ids: API-002, UI-017
"""卡型跨端契约不变式：「后端能发到这一端的卡型 ⊆ 这一端能渲染的卡型」（issue #3960）。

## 缺陷形态（本文件守卫的那道此前无人守卫的接缝）

后端 `app/api/chat.py::_detect_card_type` 是**卡型的唯一产出源**，它按工具名下发类型：
`product_list` / `product_detail` / `logistics` / `order` / `quotation`。此前没有任何机械守卫：

- C 端 `frontend/mini-app/src/components/chat/MessageBubble.tsx::renderCard` 实现 9 种，含 `quotation` → 齐全；
- B 端移动 `frontend/bmini-app/src/components/chat/MessageBubble.tsx::renderCard` 与 C 端同族 → 齐全；
- B 端桌面 `frontend/admin-web/src/components/chat/ToolResultCard.tsx` 当时只实现 5 种、**不含 `quotation`**
  （现为 6 种：新增 `production_progress`，见下「反向契约」节），
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

## 反向契约（issue #4016 P14 追加）：渲染端 case 集合 ⊆ 后端可产出卡型集合

上面那条是**正向**（后端能发 ⇒ 前端要能渲染）；本文件另加**反向**（前端有 case ⇒ 后端真会发）。
反向缺口的形态 = 「前端声称支持某卡型、后端**永远不发**」⇒ 该分支是**死 UI**，
但它**不会自己变红**：多一个永不命中的 `case` 而已，测试照绿、CI 照绿。

`#3960` 当时的口径是「**保留分支 + 用测试标注**，不顺手删除」（反向缺口无用户可见缺陷，
且 `knowledge` 分支未来接上卡片事件即可复用）。`#4016` **收紧了该口径**：审计实测
前端 11 个卡型名里有 **6 个**后端永不产出，别名与死分支让「实际语义只有 5 个」的真相
被 11 个名字掩盖、并且**没有任何东西会红**。故本包把该接缝升级为**硬判据**
（`test_renderer_case_sets_are_subset_of_backend_card_types`）。

**两个零发射点卡型的处置不同（照实登记）**：
- `payment` —— 工具层**没有任何数据源**（收款码走独立 REST、由卡片自取）⇒ 缺的是**触发机制**，
  按产品裁定**维持裁剪**（另开单）；
- `production_progress` —— `production_progress_query` 工具**存在且返回的正是卡载荷**
  ⇒ 属**接线漏一行**，用户 2026-09-18 裁定走「**补发射点**」：`_detect_card_type` 补映射后
  该卡型进入**可产出集合（5 → 6）**，三端渲染分支同步恢复（该工具同时绑在两个 persona 的
  Skill 上 ⇒ 正向判据要求 C 端 + B 端移动 + B 端桌面**三端都能渲染**，实测缺任一端即报红）。

> 口径演进的判据落点：正向判据护「发得出、渲染不了」，反向判据护「渲染得了、发不出」。
> 两者都读同一份源码真值提取器（不加第二份口径），红证见文末「常驻判别性检验」。

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
- **反向真实红（#4016 裁剪前实测，历史事实）**：`test_renderer_case_sets_are_subset_of_backend_card_types`
  当时报出三个渲染端的孤儿分支 —— C 端 `['knowledge', 'knowledge_result', 'logistics_track',
  'payment', 'product_recommend', 'production_progress']`、B 端移动同族（少 `payment` /
  `production_progress`）、B 端桌面 `['knowledge']`。除 `production_progress` 外均维持裁剪；
  `production_progress` 已由「补发射点」转为**可产出 + 三端可渲染**（见上节）。
- **反向变异红**：把某个卡型从 `_CARD_TOOL_ANCHORS`/映射里去掉后，判据必须报出对应孤儿
  （证明「裁剪后转绿」不是判据恒真）。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.api.chat import _card_payload, _detect_card_type
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
    # #4016 P14「补发射点」（用户 2026-09-18 裁定）：该工具返回的 data 正是卡载荷
    "production_progress_query": "production_progress",
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


def orphan_renderer_branches(
    renderer_types: dict[str, set[str]], producible: set[str]
) -> dict[str, list[str]]:
    """**反向**判据（纯函数，可用构造输入做判别性检验）。

    入参 `renderer_types`：渲染端名 → 该端卡型 switch 的 case 集合；
    `producible`：后端 `_detect_card_type` 在**注册表里的工具**上真能返回的卡型集合。
    返回 `{渲染端名: 后端永不下发的卡型}`；全空 = 反向契约成立。
    （真值取自**注册表**而非 `_detect_card_type` 的函数体：写进函数却没有任何工具能触发
    的映射同样是死路径 —— `production_progress` 曾是该形态的实例，现已按裁定补上映射。）
    """
    return {
        name: sorted(types - producible)
        for name, types in renderer_types.items()
        if types - producible
    }


# 前端路由字面量：agent 侧**不得**出现（两端路由不同 ⇒ 只能由各端自己拼）
_ROUTE_LITERAL_RE = re.compile(r"""["'`]/?(?:products|orders)/""")
_URL_FIELD_KEYS = ("href", "url", "link", "linkUrl", "jumpUrl")


class TestAgentSideCarriesNoRoutes:
    """L0：href 必须**事实驱动**且**由各端生成**（issue #4016 P14 第四节三条硬约束）。

    约束 1「两端路由不同（admin-web `/products/{id}`、`/orders/{id}`；mini-app 是 Taro 路由
    且当前零链接能力）⇒ agent 侧只给 `product_id`/`order_no` 这类不可变标识，
    **不得在 agent 侧写死 href**」与约束 3「href 只能由工具结果真值映射生成，**不得由模型编造**」
    都需要常驻机械判据 —— 否则「agent 悄悄拼了个路由」或「卡载荷里带上了模型给的 URL」
    都不会有任何东西变红（与 #3970「声称发卡但没发」同族的静默失效）。
    """

    def test_no_frontend_route_literals_in_agent_card_path(self):
        """agent 侧（chat.py）不得出现前端路由字面量 `/products/`、`/orders/`。"""
        source = _read(REPO_ROOT / "backend" / "ai-agent-service" / "app" / "api" / "chat.py")
        hits = [
            f"第 {no} 行：{line.strip()}"
            for no, line in enumerate(source.split("\n"), 1)
            if _ROUTE_LITERAL_RE.search(line)
        ]
        assert hits == [], (
            "agent 侧写死了前端路由（路由必须由各端自己拼，否则 C 端会拿到 B 端路径）："
            + "；".join(hits)
        )

    def test_route_literal_detector_recognises_a_planted_route(self):
        """红证（变异）：把路由字面量喂给判据必须被认出 —— 证上面那条不是空断言。"""
        planted = 'card["href"] = f"/products/{pid}"'
        assert _ROUTE_LITERAL_RE.search(planted), "路由判据认不出植入的路由字面量（空断言）"

    def test_card_payload_carries_no_url_fields(self):
        """卡载荷**不得**新增 href/url/link 型字段：真值标识由工具结果携带，路由各端自拼。

        载荷里出现 URL 字段 ⇒ 前端可能直接采信它 ⇒ 模型编造的链接变成可点链接
        （约束 3）。本判据对真实 `_card_payload` 求值（非清单副本）。
        """
        payload_type, payload = _card_payload(
            "product_search",
            {"success": True, "data": {"products": [{"id": "p-1", "name": "窗帘A"}]}},
        )
        assert payload_type == "product_list" and payload, "前置：该输入必须产出商品卡载荷"

        offenders = sorted(k for k in payload if k.lower() in _URL_FIELD_KEYS)
        offenders += sorted(
            f"products[].{k}"
            for p in (payload.get("products") or [])
            if isinstance(p, dict)
            for k in p
            if k.lower() in _URL_FIELD_KEYS
        )
        assert offenders == [], (
            f"卡载荷出现了 URL 型字段（href 必须事实驱动、由各端生成）：{offenders}"
        )

    def test_url_field_detector_recognises_a_planted_url_field(self):
        """红证（构造）：载荷里植入 `href` 必须被判据认出（防空断言）。"""
        planted = {"products": [{"id": "p-1", "href": "/products/p-1"}]}
        offenders = sorted(
            f"products[].{k}"
            for p in (planted.get("products") or [])
            if isinstance(p, dict)
            for k in p
            if k.lower() in _URL_FIELD_KEYS
        )
        assert offenders == ["products[].href"], f"URL 字段判据认不出植入字段：{offenders}"


class TestNoOrphanRendererBranches:
    """**反向**契约（issue #4016 P14）：渲染端 case 集合 ⊆ 后端可产出卡型集合。

    它取代了 `#3960` 的「保留分支 + 逐条标注」口径（原因见模块 docstring「反向契约」节）：
    标注只能记录**一条**已知缺口，且不留神就会与源码脱节；硬判据覆盖**全部**渲染端，
    且随源码自动前进 —— 谁再加一个后端永不产出的 `case`，这里立刻红。
    """

    def test_renderer_case_sets_are_subset_of_backend_card_types(self):
        renderer_types = _current_renderer_types()
        producible = set(_all_backend_card_tools().values())
        violations = orphan_renderer_branches(renderer_types, producible)
        assert violations == {}, (
            "前端有渲染分支、后端**永不下发**的卡型（死 UI：能力在代码里、路径不存在）："
            + "；".join(f"{end} 多出 {orphans}" for end, orphans in violations.items())
            + f"｜后端可产出集合={sorted(producible)}"
        )

    def test_orphan_criterion_is_non_vacuous(self):
        """防空跑：两侧都必须非空，否则上面的子集断言会**真空通过**。"""
        producible = set(_all_backend_card_tools().values())
        assert producible, "后端可产出卡型集合为空 —— 反向判据退化成空断言"
        for end, types in _current_renderer_types().items():
            assert types, f"渲染端 {end} 提取到 0 个 case —— 提取器坏了（反向判据会真空通过）"

    def test_orphan_reported_when_a_backend_mapping_is_removed(self):
        """变异红证：把一个卡型从后端可产出集合里**去掉**，判据必须报出该孤儿分支。

        这是「裁剪后转绿」的判别性检验 —— 若判据恒真，这条会绿着骗人。
        """
        renderer_types = _current_renderer_types()
        producible = set(_all_backend_card_tools().values())
        victim = sorted(producible & set().union(*renderer_types.values()))
        assert victim, "后端可产出集合与渲染端集合无交集 —— 变异实验无法构造"
        trimmed = producible - {victim[0]}

        violations = orphan_renderer_branches(renderer_types, trimmed)
        assert violations, f"去掉 {victim[0]} 后判据仍未报违规 ⇒ 反向断言是空断言"
        for end, orphans in violations.items():
            if victim[0] in renderer_types.get(end, set()):
                assert victim[0] in orphans, f"{end} 未报出被移除的卡型：{orphans}"

    def test_fabricated_renderer_case_is_flagged(self):
        """构造红证：故意构造一个后端永不产出的 case，断言必被判为孤儿。

        刻意**只喂构造输入**（不掺当前源码真值）：当前真值里的存量孤儿会让等值断言
        在修复前假红、修复后真绿 —— 那种「判据自己会随被测对象变化」的红证不是判别性检验。
        """
        fabricated = "__fabricated_orphan_card__"
        violations = orphan_renderer_branches(
            {"__fabricated_end__": {"product_list", fabricated}},
            set(_all_backend_card_tools().values()),
        )
        assert violations == {"__fabricated_end__": [fabricated]}, (
            f"构造的孤儿分支未被报出 ⇒ 反向判据恒真（空断言）。实际 violations={violations}"
        )

    """红证：证明**正向**判据也真的会红（常驻判别性检验，不是一次性人工验证）。"""

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
