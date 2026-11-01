"""本轮**工具面**构造：非对称切分（#4125）+ 按意图裁剪读面（issue #8174）。

为什么要单独成模块：`base_skill.py` 受 **LOC 棘轮**（`tests/unit_ci_workflows/loc_freeze_ledger.json`，
冻结值 4356，只许向下）约束 ⇒ 新增裁剪逻辑只能**搬出去**再加，不许把它继续加长。
本文件承载两件事：

1. **非对称切分**（#4125，原样搬迁）：写工具仍按域收紧；只读工具在同一 **persona 家族**内
   跨域共享。`create_skill_registry` 是**唯一**造 skill 工具子集的工厂（并负责
   `set_tool_scope` —— 校验域必须与执行域逐名一致，#4017）。
2. **读面裁剪**（#8174）：B 端每轮原先暴露 35~39 个工具（读面按家族全量并入），
   按**本轮意图**打分保留 top-k，**保底集合永不被裁**，并只裁 `read_only is True`。

## 口径（三条，缺一即失真）

- **只裁读面**：`read_only=False` 的工具一个都不裁（写面与权限完全不动）。
- **保底集合**（`ALWAYS_KEEP_TOOL_NAMES` + 本轮 skill 的写工具 + 上一轮用过的只读工具
  + **意图属主 skill 的读工具**）
  **永不被裁** —— 裁掉 `validate_input`/`interact` 这类兜底等于把流程关节打断；
  意图属主那条见 `_intent_owner_read_tool_names`（issue #8300）。
- **开关可回退**：`settings.TOOL_TRIM_ENABLED=False`（或非 B 端）⇒ `plan_read_tools` 返回
  `None`，`create_skill_registry` 走**与改动前逐字相同**的分支（C 端零回归）。

判据：`tests/test_tool_selection_trim.py`（case_ids: AG-009）。
"""
import re
from typing import Any, List, Optional, Sequence, Set, Tuple

from loguru import logger

from app.config import settings
from app.tools.registry import ToolRegistry, set_tool_scope

#: 保底集合（**永不被裁**）：兜底/交互/校验类工具与流程关节。实证见 #8174 的判据
#: `test_always_keep_set_survives_every_skill`。注册表里不存在的名字自然不生效
#: （`confirm_value` 当前无工具实例 —— 保留在清单里是**有意**的，它接回后自动生效）。
ALWAYS_KEEP_TOOL_NAMES: Tuple[str, ...] = (
    "nav_guide",
    "knowledge_search",
    "interact",
    "validate_input",
    "confirm_value",
)

#: 命中工具名（用户/意图里出现 `order_query` 这种原样名字）的权重。
_NAME_HIT = 60
#: 工具名分段（`order_query` → `order` / `query`）被命中时的权重。
_NAME_PART_HIT = 6
#: 本轮 skill **自己声明**的读工具先验（同分时本域优先，但不压过真实语义命中）。
_OWN_SKILL_PRIOR = 5
#: 描述/`not_for` 的词面命中基数与封顶（长描述不许靠体量淹没短工具）。
_DESC_HIT = 1
_DESC_HIT_CAP = 20

_ASCII_WORD_RE = re.compile(r"[a-z][a-z0-9_]{2,}")
_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]+")


# ── 注册表/SkillConfig 事实（**函数内**延迟导入：`skills/*_skill.py` 依赖 base_skill）──
def _all_skill_configs() -> List[Any]:
    """全部 SkillConfig。"""
    from app.graph.skills.skill_registry import get_skill_registry

    return list(get_skill_registry().get_all())


def _skill_config(skill_name: str) -> Optional[Any]:
    """按名取 SkillConfig；未注册 → None（调用方决定降级）。"""
    from app.graph.skills.skill_registry import get_skill_registry

    return get_skill_registry().get(skill_name)


def _read_only_tool_names() -> frozenset:
    """注册表事实：`read_only is True` 的工具名（**唯一口径**，不用源码正则近似）。"""
    from app.tools.registry import get_tool_registry

    return frozenset(
        t.name for t in get_tool_registry().get_all_tools()
        if getattr(t, "read_only", False)
    )


def _family_personas(tool_names: List[str]) -> frozenset:
    """请求的工具集**能被哪些 persona 家族解释** —— 逐工具取"绑定它的 skill 的 persona"再取交集。

    交集恰好唯一 ⇒ 家族成立（该域的只读工具可共享）；歧义（>1）或任一工具无人绑定（=∅）
    ⇒ **空集 = 不放宽**（fail-closed：宁可少共享，也不把一端工具泄给另一端）。
    """
    cfgs = _all_skill_configs()
    personas: Optional[set] = None
    for name in tool_names:
        owners = {
            persona
            for cfg in cfgs if name in (cfg.tool_names or [])
            for persona in (cfg.system_prompts or {})
        }
        personas = owners if personas is None else (personas & owners)
    return frozenset(personas or ())


def _family_read_only_tool_names(tool_names: List[str]) -> List[str]:
    """**同一 persona 家族**里的全部只读工具名（现算；家族不唯一 ⇒ `[]` = 不放宽）。"""
    personas = _family_personas(tool_names)
    if len(personas) != 1:
        return []
    read_only = _read_only_tool_names()
    names: set = set()
    for cfg in _all_skill_configs():
        if personas & set(cfg.system_prompts or {}):
            names.update(t for t in (cfg.tool_names or []) if t in read_only)
    return sorted(names)


def _intent_owner_read_tool_names(intent: str) -> List[str]:
    """**意图属主 skill** 声明的只读工具名（issue #8300 的保底项）。

    为什么要这条保底：`nodes._get_intent_to_route` 会**按绑定面过滤**意图 —— 例如
    `system_settings` / `ai_config` / `notification` 一律落到 fallback skill（`general`），
    因为属主 skill `settings` 不在图上（#6044 缺陷 C 的源头堵法）。改动前 #4125 的
    「同 persona 家族只读并入」把属主工具一起带进来；#8174 裁剪后它既不在执行 skill 的
    声明面（无 own-skill 先验）、词面又常零分 ⇒ 被裁 ⇒ 模型退到保底的 `nav_guide`
    答「菜单在哪」而不是「设置值是什么」（2026-11-01 评测实测 ST-001/ST-002）。

    只取 **mibao 属主**的读工具：本函数只在 B 端裁剪路径上被调用，C 端不参与裁剪；
    未命中任何属主（意图名漂移 / 走 fallback 的兜底意图）⇒ 空列表（不改既有行为）。
    """
    key = str(intent or "").strip()
    if not key:
        return []
    read_only = _read_only_tool_names()
    names: List[str] = []
    for cfg in _all_skill_configs():
        if "mibao" not in (cfg.system_prompts or {}):
            continue
        if key in (cfg.intents or []):
            names.extend(n for n in (cfg.tool_names or []) if n in read_only)
    return names


# ── 意图打分（确定性：同样输入两次结果逐字一致）────────────────────────────
def _cjk_bigrams(text: str) -> Set[str]:
    """中文**二字词**近似（无分词器依赖）：连续汉字串的相邻二元组。

    单字命中的噪音太大（「的」「查」），故只取二元组 —— 但单字串（如「图」）保留一个，
    否则短指令（「看图」）会完全失去中文信号。
    """
    out: Set[str] = set()
    for run in _CJK_RUN_RE.findall(text or ""):
        if len(run) == 1:
            out.add(run)
        else:
            out.update(run[i:i + 2] for i in range(len(run) - 1))
    return out


def _tool_text(tool: Any) -> str:
    """打分词面：`name + description + not_for`（`not_for` 存在才取，缺失不报错）。"""
    parts = [str(getattr(tool, "name", "") or "")]
    parts.append(str(getattr(tool, "description", "") or ""))
    not_for = getattr(tool, "not_for", None)
    if not_for:
        parts.append(not_for if isinstance(not_for, str) else " ".join(map(str, not_for)))
    return " ".join(parts)


def _score_tool(tool: Any, query_low: str, query_words: Set[str],
                query_bigrams: Set[str], own_skill: bool) -> int:
    """工具与本轮的匹配度（越大越该留）。**纯函数**，输入相同 ⇒ 输出相同。"""
    name = str(getattr(tool, "name", "") or "")
    score = 0
    if name and name in query_low:
        score += _NAME_HIT
    for part in name.split("_"):
        if len(part) >= 3 and part in query_words:
            score += _NAME_PART_HIT
    text = _tool_text(tool).lower()
    word_hits = len(set(_ASCII_WORD_RE.findall(text)) & query_words)
    bigram_hits = len(_cjk_bigrams(text) & query_bigrams)
    score += min(_DESC_HIT_CAP, word_hits * _DESC_HIT + bigram_hits * _DESC_HIT)
    if own_skill:
        score += _OWN_SKILL_PRIOR
    return score


# ── state → 本轮信号（读不到就给空值，绝不抛）──────────────────────────────
def _last_user_text(messages: Sequence[Any]) -> str:
    """最近一条**用户**消息的文本（多模态 content 只取 text 块）。"""
    for msg in reversed(list(messages or ())):
        if getattr(msg, "type", "") != "human":
            continue
        content = getattr(msg, "content", "") or ""
        if isinstance(content, str):
            return content
        texts = [
            item.get("text", "") for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        ]
        return " ".join(t for t in texts if t)
    return ""


def _intent_text(state: Any) -> str:
    """`intent_result.intent` 的字符串形态（Enum/str/None 都吃）。"""
    intent_result = (state or {}).get("intent_result") or {}
    if not isinstance(intent_result, dict):
        return ""
    value = intent_result.get("intent")
    if hasattr(value, "value"):
        return str(value.value)
    return "" if value is None else str(value)


def _recent_tool_names(messages: Sequence[Any]) -> List[str]:
    """**上一轮**模型点过的工具名（最近一条带 `tool_calls` 的 AI 消息）。"""
    for msg in reversed(list(messages or ())):
        calls = getattr(msg, "tool_calls", None)
        if calls:
            return [c.get("name", "") for c in calls if isinstance(c, dict) and c.get("name")]
    return []


# ── 裁剪决策 ───────────────────────────────────────────────────────────────
def plan_read_tools(tool_names: List[str], *, agent_type: str = "",
                    user_message: str = "", intent: str = "",
                    recent_tools: Sequence[str] = (),
                    enabled: Optional[bool] = None,
                    max_tools: Optional[int] = None) -> Optional[List[str]]:
    """算出**允许保留的只读工具名**；`None` = 不裁剪（与改动前逐字一致）。

    `None` 的三条来路（都是"不做决定"而不是"决定全裁"）：开关关 / 非 B 端 /
    本域工具面本来就 ≤ 上限（无可裁）。

    上限语义 = **本轮绑定工具总数**（`TOOL_TRIM_MAX_READ`，默认 16）：保底集合先占位，
    剩余槽位按分数从高到低填。保底集合超额时**上限让位**（保底永不被裁）。
    """
    if enabled is None:
        enabled = bool(settings.TOOL_TRIM_ENABLED)
    if not enabled or (agent_type or "") != "mibao":
        return None
    limit = int(max_tools if max_tools is not None else settings.TOOL_TRIM_MAX_READ)
    read_only = _read_only_tool_names()

    declared = [n for n in tool_names]
    # 候选池：本域声明的读工具 ∪ 家族读工具，**按注册表顺序**（排序稳定性的唯一来源）
    candidates = {n for n in declared if n in read_only}
    candidates |= {n for n in _family_read_only_tool_names(tool_names) if n in read_only}
    if not candidates:
        return None

    from app.tools.registry import get_tool_registry

    pool = [t.name for t in get_tool_registry().get_all_tools() if t.name in candidates]
    fixed = [n for n in declared if n not in read_only]      # 写工具：只占位，永不裁
    if len(pool) + len(fixed) <= limit:
        return None                                          # 本来就够小 ⇒ 不裁剪

    keep = [n for n in ALWAYS_KEEP_TOOL_NAMES if n in candidates]
    keep_set = set(keep)
    # 意图属主保底（#8300）：意图被过滤到别的 skill 时，属主 skill 的读工具仍要占位；
    # 但它**不突破上限**（上限让位只给 ALWAYS_KEEP / 写工具），超出预算的部分交给分数兜底。
    owner_budget = max(0, limit - len(fixed) - len(keep_set))
    keep += [n for n in _intent_owner_read_tool_names(intent)
             if n in candidates and n not in keep_set][:owner_budget]
    keep_set = set(keep)
    keep += [n for n in recent_tools if n in candidates and n not in keep]
    keep_set = set(keep)

    query_low = f"{user_message} {intent}".lower()
    query_words = set(_ASCII_WORD_RE.findall(query_low))
    query_bigrams = _cjk_bigrams(f"{user_message} {intent}")
    declared_set = set(declared)

    ranked = [n for n in pool if n not in keep_set]
    # 同分保持**注册表顺序**（`sorted` 稳定 + 池已是注册表序）⇒ 确定性
    ranked.sort(key=lambda n: -_score_tool(
        get_tool_registry().get_tool(n), query_low, query_words, query_bigrams,
        n in declared_set))

    budget = max(0, limit - len(fixed) - len(keep_set))
    keep_set.update(ranked[:budget])
    return [n for n in pool if n in keep_set]


def plan_read_tools_for_state(state: Any, tool_names: List[str],
                              *, enabled: Optional[bool] = None,
                              max_tools: Optional[int] = None) -> Optional[List[str]]:
    """`plan_read_tools` 的 state 适配层（`prepare_turn` 的唯一调用点）。"""
    state = state or {}
    messages = state.get("messages") or []
    return plan_read_tools(
        tool_names,
        agent_type=str(state.get("agent_type") or ""),
        user_message=_last_user_text(messages),
        intent=_intent_text(state),
        recent_tools=_recent_tool_names(messages),
        enabled=enabled,
        max_tools=max_tools,
    )


# ── 工厂（唯一造 skill 工具子集的地方，#4017）──────────────────────────────
def create_skill_registry(tool_names: List[str],
                          read_keep: Optional[Sequence[str]] = None) -> ToolRegistry:
    """创建仅包含指定 Tool 的 Registry 子集

    从全局单例 ToolRegistry 中引用 Tool 实例（不重复创建），
    避免每次 Skill 执行都实例化全部 Tool。

    **非对称切分**（issue #4125）：入参声明的工具之外，再并入**同一 persona 家族**的
    只读工具（写工具仍按域收紧）。

    **读面裁剪**（issue #8174）：`read_keep` 非 None 时，只读工具再过一个白名单
    （`plan_read_tools` 的结果）；`None` = 不裁剪，行为与改动前逐字一致。

    Args:
        tool_names: 需要的 Tool 名称列表（该 skill 声明的工具集）
        read_keep: 允许保留的只读工具名；`None` = 全保留（#8174 关闭态）

    Returns:
        ToolRegistry: 包含指定 Tool 子集 + 家族只读工具的注册器
    """
    from app.tools.registry import get_tool_registry

    full_registry = get_tool_registry()
    skill_registry = ToolRegistry()
    read_only = _read_only_tool_names() if read_keep is not None else frozenset()
    allowed = frozenset(read_keep) if read_keep is not None else frozenset()

    def _allowed(name: str) -> bool:
        return read_keep is None or name not in read_only or name in allowed

    for name in tool_names:
        if not _allowed(name):
            continue
        tool = full_registry.get_tool(name)
        if tool:
            skill_registry.register(tool)
        else:
            logger.warning(f"[base_skill] Tool '{name}' not found in global registry")

    # 只读工具跨域共享（#4125）：并入后**同一份并集**登记执行域（下面 set_tool_scope 用的就是
    # `skill_registry.get_tool_names()`）—— 校验域与执行域必须逐名一致，**不能一边并一边不并**
    # （#4017 的不变式：否则 validate_input 放行、模型却 `Tool not found` → 空头承诺、订单不落库）。
    for name in _family_read_only_tool_names(tool_names):
        if not _allowed(name):
            continue
        if skill_registry.get_tool(name) is None:
            tool = full_registry.get_tool(name)
            if tool:
                skill_registry.register(tool)

    # A5（issue #4017）：把**本轮可执行工具集**登记为执行域事实（`validate_input` 执行期
    # 据此拒绝域外目标）。登记的是**实际注册成功**的名单（不是入参 `tool_names`）。
    set_tool_scope(skill_registry.get_tool_names())
    return skill_registry
