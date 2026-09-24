"""模糊输入的「可点击猜测」—— 从**事实**机械投影（issue #5329，提问引导「类型 2」）。

判据来源：`docs/agent-feature-design.md` §九「提问引导（跨族关注点）」的
**类型 2 · 不知道怎么表述**（P0：对话层「猜测式追问」，无新基建）。

## 这个模块治什么

B 端同事「不知道自己想要什么」其实是三个不同的问题，本模块只治第 2 类：
**知道自己要什么，但说不出来**。用户说「我想看看最近的情况」时，回一句开放式反问
（「请问您想查什么」）等于把问题原样丢回去 —— 他本来就说不出。正确形态是
**理解后的猜测 + 可点击的方向**：

    我理解你想看「经营看板」，是这个吗？也可以直接点下面的方向，我马上帮你查～
    ① 经营看板   ② 查订单   ③ 退货   …

## 三条设计铁律（逐条落码，不是注释）

> **与 §九 的关系**：§九 要求面向用户的引导是能力索引（#4125）那条投影的「**第二条腿**」——
> 同源、但渲染成用户语言，从而**不漂移**。本模块「选哪些能力配被引导」这一半与
> `app/graph/skills/base_skill.py` 的 `_capability_index` **是同一份事实**
> （`SkillConfig.tool_names` × 注册表 `read_only`，见 `project_guesses`）；
> 渲染那一半取自**工具自己声明的触发原话**，也不是手写清单 ⇒ 两条腿同源，只有渲染形态不同。

1. **不是新文案库**：每条引导 = `SkillConfig.tool_names`（当前 skill 的**绑定集**）
   × 工具 `description` 的 `【触发】` 段里**用户原话**的机械投影 ——
   **不写死任何 skill 名 / 工具名 / 引导文案**（同 `tests/test_capability_index_prompt.py` 的路子）。
   🔴 「引导了却做不到，比不引导更伤」：绑定集是**硬闸**（`unanswerable`）。
2. **必须是用户语言，不是能力名**：`references/base/principles.md` 的「回复中禁止出现
   工具名/字段名」本模块**延伸到引导面**（`named_internal` 是那条线的机械检测器）。
   不说「跨域查询」「批量操作」，只说同事嘴里的话。
3. **术语桥反着用**：`prompts/*.md` 的「术语映射」拿用户口语去**理解**用户；
   这里拿**工具自己声明的触发原话**去生成用户看得懂的引导 —— 同一份事实，反方向使用。

## 为什么原话取自工具 description（而不是手写一张清单）

工具 description 按 `docs/wiki/agent-design-standard.md` 的规范必须回答
「何时用 —— 用户说什么时触发」，`【触发】` 段里的引号短语**就是**该能力认得的用户说法。
从那里取词有两个别处拿不到的性质：
  · **可追溯是构造出来的**，不是标注出来的 —— 短语属于哪个工具，就由哪个工具回答，
    没有「文案 ↔ 能力」的第二份会漂移的映射表；
  · **做不到的引导进不来** —— 能力解绑/工具下线时，对应短语随之消失（自动收敛）。

## 尺寸（实测量级，见 PR）

45/45 已注册工具都有 `【触发】` 段，共 210 条引号短语；米宝 9 个域里有 7 个能投影出
**L1 可路由**的引导（settings / knowledge 域的触发词不落在 L1 关键词表上 ⇒ 诚实地不出现，
而不是硬凑一条点了没反应的选项）。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from loguru import logger

#: 引导产物形态 —— 与 `app/tools/interact.py` 的 choice 组件**同协议**：
#: 复用既有卡片管道（`chat.py` 收 `ToolMessage(name="interact")` → SSE `interactive`
#: → 前端 ChoiceCard），不新造一条下发链路。
COMPONENT = "choice"

#: 工具 description 的触发段（形态见 `docs/wiki/agent-design-standard.md` 的
#: 「Tool description 必须回答何时用」）。
_TRIGGER_RE = re.compile(r"【触发】(.*?)(?=【|\Z)", re.S)

#: 触发段里的**用户原话**（各式引号包裹，2~14 字）。
_QUOTED_RE = re.compile(r"['‘’\"“”「]([^'‘’\"“”」]{2,14})['‘’\"“”」]")

#: 含英文/数字的短语是 schema 话术（`XX商品详情` / `recentOrders`），不是用户语言 ⇒ 不投影。
_NOT_USER_LANGUAGE_RE = re.compile(r"[A-Za-z0-9]")

#: 引导句骨架 —— **只有骨架是固定的**，括号里的内容全部来自投影。
_GUESS_TITLE = "我理解你想看「{guess}」，是这个吗？也可以直接点下面的方向，我马上帮你查～"
_DIRECTION_TITLE = "我大概明白你想查点什么。点一下下面的方向，我马上帮你查～"

#: 字段名从工具参数 schema 取（`status` / `keyword` …）。过短的键（`id`）会误伤中文
#: 普通词，故只认 ≥4 字符的键；**工具名不受此限**（它们本身足够长且形态独特）。
_MIN_FIELD_LEN = 4

#: L1 规则匹配器（确定性、无 LLM）—— 懒加载单例（每次 `RuleMatcher()` 都要重建关键词表）。
_RULE_MATCHER = None


# ────────────────────── 事实源（全部现算，不抄清单） ──────────────────────

def _registered_tools() -> Dict[str, Any]:
    """已注册工具 `{名: 实例}`（注册表是"能力真实存在"的唯一事实源）。"""
    from app.tools.registry import get_tool_registry

    return {t.name: t for t in get_tool_registry().get_all_tools()}


def _skill_config(skill_name: str):
    """按名取 SkillConfig；未注册 ⇒ None（调用方 fail-closed）。函数内导入避免环。"""
    from app.graph.skills.skill_registry import get_skill_registry

    return get_skill_registry().get(skill_name)


def _persona(skill_name: str) -> str:
    """该 skill 的 persona（由 `system_prompts` 的 key **derive**，不写死）。

    歧义（≠1 个）⇒ 空串 = 不放宽（与 `base_skill._family_personas` 的 fail-closed 同口径）。
    """
    cfg = _skill_config(skill_name)
    personas = sorted(cfg.system_prompts or {}) if cfg else []
    return personas[0] if len(personas) == 1 else ""


def _family(skill_name: str) -> List[Any]:
    """**同一 persona 家族**的 skill（现算；与 `base_skill._capability_index` 同口径）。

    家族 = 该 persona 能路由到的全部域 —— 引导要给的是"这一端能办的事"，
    不是"整个系统存在的事"（后者会把别端能力摆到用户面前）。
    """
    persona = _persona(skill_name)
    if not persona:
        return []
    from app.graph.skills.skill_registry import get_skill_registry

    return [c for c in get_skill_registry().get_all() if persona in (c.system_prompts or {})]


def bound_tool_names(skill_name: str) -> frozenset:
    """当前 skill **真的绑定**且**已注册**的工具名（判据 2 的唯一事实源）。

    = `SkillConfig.tool_names` ∩ 注册表。两者缺一都不算"答得出来"：
    未注册 = 工具不存在；未绑定 = 本流程没有它（调用即 `Tool not found`）。
    """
    cfg = _skill_config(skill_name)
    if cfg is None:
        return frozenset()
    registered = _registered_tools()
    return frozenset(t for t in (cfg.tool_names or []) if t in registered)


def _route_key(intent_value: str, persona: str) -> str:
    """意图 → 路由 key（**与运行时同一份事实**：注册表的 intent→route_key 映射）。

    ⚠️ 本函数刻意**不 import `app.graph.nodes`**（`nodes.py` 要 import 本模块 ⇒ 会成环）；
    因此运行时包装（`nodes._get_intent_to_route` 的 direct_reply / knowledge fallback）
    在这里没有复刻 —— **由测试用运行时那一个函数交叉核对**（`test_vague_guess.py`
    的判据 4 断言 `_intent_to_route_key(...) == guess["skill"]`），分歧会当场变红。
    """
    from app.graph.skills.skill_registry import get_skill_registry

    mapping = get_skill_registry().get_intent_to_route_map(persona=persona or "mibao")
    return mapping.get(intent_value, "general")


def _rule_matcher():
    """懒加载 L1 规则匹配器单例（`RuleMatcher()` 每次都要重建关键词表）。"""
    global _RULE_MATCHER
    if _RULE_MATCHER is None:
        from app.router.rule_matcher import RuleMatcher

        _RULE_MATCHER = RuleMatcher()
    return _RULE_MATCHER


# ────────────────────── 判据 3：引导文本不得含内部名 ──────────────────────

def named_internal(text: str) -> List[str]:
    """文本里出现的**内部名**：已注册工具名 + 工具参数字段名（判据 3 的检测器）。

    `references/base/principles.md` 的「回复中禁止出现工具名、字段名」在**引导面**的
    机械形态 —— 卡片是用户直接看到并点击的东西，出现 `dashboard_stats` / `status`
    等于把内部实现摆到用户面前。

    返回命中的内部名（升序去重）；空列表 = 干净。刻意保持**纯函数**，
    好让判据的红证可以单独喂它一条脏文本（否则那条守卫永远绿）。
    """
    text = str(text or "")
    if not text:
        return []
    low = text.lower()
    tools = _registered_tools()          # 只取一次（投影路径上会被逐短语调用）
    hits = {name for name in tools if name and name.lower() in low}
    for tool in tools.values():
        props = ((getattr(tool, "parameters", None) or {}).get("properties") or {})
        for key in props:
            key = str(key)
            # 字段名按**词边界**匹配：`order_query` 里的 `query` 不是"字段名泄漏"
            # （下划线在正则里属词字符 ⇒ `\bquery\b` 不命中它），
            # 但独立的 `status` / `keyword` 必须命中。
            if len(key) >= _MIN_FIELD_LEN and re.search(
                    rf"\b{re.escape(key)}\b", low):
                hits.add(key)
    return sorted(hits)


def _user_phrases(tool: Any) -> List[str]:
    """工具 description 的 `【触发】` 段里**用户原话**（保序 = 声明序，机械可复现）。

    过滤：占位符/英文（`XX商品详情`）、含内部名的、过短过长的 —— 剩下的才是"同事嘴里的话"。
    """
    matched = _TRIGGER_RE.search(getattr(tool, "description", "") or "")
    if not matched:
        return []
    out = []
    for raw in _QUOTED_RE.findall(matched.group(1)):
        phrase = raw.strip()
        if not phrase or _NOT_USER_LANGUAGE_RE.search(phrase):
            continue
        if named_internal(phrase):
            continue
        out.append(phrase)
    return out


# ────────────────────── 投影 ──────────────────────

def _routable_intent(phrase: str, skill_name: str, persona: str) -> str:
    """该用户原话能否被判到一个**真实意图**，且该意图**路由回同一个 skill**。

    这是判据 4（点选后进入正常处理路径、不是又一轮澄清）的机械形态：
    返回值非空 ⇒ 点选后 L1（**确定性、无 LLM**）就能把它送到"能回答它的那个流程"。
    跨域短语（如 `dashboard_stats` 的 `最近X条订单` → `order_query`）在这里被挡掉 ——
    否则用户点了"最近X条订单"会被送进订单流程，而那句话本来属于看板。
    """
    hit = _rule_matcher().match(phrase)
    if hit is None:
        return ""
    intent_value = hit.intent.value
    if intent_value in ("general", "greeting", "farewell", "capabilities"):
        return ""
    if _route_key(intent_value, persona) != skill_name:
        return ""
    return intent_value


def project_guesses(
    skill_name: str, *, guessed_intent: str = "", limit: int = 3,
) -> List[Dict[str, Any]]:
    """「可点击的猜测」候选 —— 每个域一条，**全部从事实投影**。

    Args:
        skill_name: 当前流程（模糊轮里是 `general`）—— 它的**绑定集**是硬闸。
        guessed_intent: L2 分类器**猜过的方向**（低置信改写前保留下来，不丢弃）。
            命中候选集时排到首位 —— 这一条就是「我理解你想看 X，是这个吗」里的 X。
        limit: 最多几条（卡片选项上限，防 UI 溢出）。

    Returns:
        `[{label, value, intent, skill, tool}]`；每个条目的 `tool` 一定落在
        `bound_tool_names(skill_name)` 里（构造即满足判据 2），`value` 一定是
        L1 可路由回 `skill` 的用户原话（构造即满足判据 4）。
        证据不足时返回 `[]`（fail-closed：宁可退回原有路径，也不发一张猜错的卡）。
    """
    persona = _persona(skill_name)
    if not persona:
        logger.warning(f"[vague-guess] skill '{skill_name}' persona 不唯一，放弃投影")
        return []
    bound = bound_tool_names(skill_name)
    if not bound:
        return []
    registered = _registered_tools()

    candidates: List[Dict[str, Any]] = []
    for other in sorted(_family(skill_name), key=lambda c: c.name):
        picked = None
        for tool_name in (other.tool_names or []):
            if tool_name not in bound:
                continue                      # 判据 2：本流程答得出来的才配被引导
            tool = registered.get(tool_name)
            if tool is None or not getattr(tool, "read_only", False):
                continue                      # 模糊输入先要"查得出来"（写操作不在本单）
            for phrase in _user_phrases(tool):
                intent_value = _routable_intent(phrase, other.name, persona)
                if not intent_value:
                    continue
                picked = {
                    "label": phrase,
                    "value": phrase,          # 点击即发这句人话 —— 与 label 同源（不藏暗号）
                    "intent": intent_value,
                    "skill": other.name,
                    "tool": tool_name,
                }
                break
            if picked:
                break
        if picked:
            candidates.append(picked)

    if not candidates:
        return []

    # 猜过的方向排首位（「我理解你想看 X，是这个吗」的 X；猜不中时由第 3 步兜底）
    lead = None
    if guessed_intent:
        lead = next((g for g in candidates if g["intent"] == guessed_intent), None)
        if lead is None:
            target = _route_key(guessed_intent, persona)
            lead = next((g for g in candidates if g["skill"] == target), None)
    if lead is not None:
        candidates = [lead] + [g for g in candidates if g is not lead]

    return candidates[:limit]


def unanswerable(skill_name: str, guesses: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """**判据 2 的硬闸**：返回 `guesses` 里当前 skill **答不出来**的条目。

    判据 = 条目点名的工具 ∈ `bound_tool_names(skill_name)`（已注册 ∩ 已绑定）。
    刻意独立成函数：投影自身构造即满足它，但**闸门必须能被单独喂一条脏数据**
    （否则"塞一条指向未绑定能力的引导 ⇒ 必须变红"这条红证无处施加）。
    """
    bound = bound_tool_names(skill_name)
    return [g for g in (guesses or []) if str((g or {}).get("tool") or "") not in bound]


def build_guess_card(
    skill_name: str, *, guessed_intent: str = "", limit: int = 3,
) -> Optional[Dict[str, Any]]:
    """组装**可点击的猜测卡**（`interact` choice 同协议载荷）；无候选 ⇒ None。

    载荷只带 `label` / `value`（**用户语言**）—— 能力追溯（`tool` / `skill` / `intent`）
    留在 `project_guesses` 的返回值里，**不下发**给前端：卡片是用户直接看到的东西，
    内部名一个都不许出现在上面（判据 3）。
    """
    guesses = project_guesses(skill_name, guessed_intent=guessed_intent, limit=limit)
    if not guesses:
        return None
    options = [{"label": g["label"], "value": g["value"]} for g in guesses]
    title = _DIRECTION_TITLE
    if guessed_intent and guesses[0]["intent"] == guessed_intent:
        title = _GUESS_TITLE.format(guess=guesses[0]["label"])
    return {"component": COMPONENT, "title": title, "options": options}