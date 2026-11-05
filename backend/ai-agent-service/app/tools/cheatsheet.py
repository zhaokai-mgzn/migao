"""选工具小抄：按**本轮 skill 的声明面**从工具注册表 + 本体投影（issue #8176）。

## 为什么存在

B 端每轮绑 34~39 把工具，「选错工具」是主要失败来源之一。选工具的口径原先**手抄**在
9 处（`references/prompts/*.md` 的「场景 → 工具」表 + `general_agent.py` /
`product_skill.py` 的内联表），与工具真值必然漂移 —— 同族实证：#7291 的 10 处手写边界
声明里 9 处与真值相反（`非单据对象创建 ✅ 支持`，而 `employee_manage` 的 action enum
里根本没有 create）。本模块把那 9 处换成**投影**：

| 事实 | 真值源 |
|---|---|
| 能做什么（工具名 / 入参 / 只读性 / 权限码） | `app/tools/registry.py`（各工具的元数据与 `description`） |
| 商家怎么叫它（业务术语、对象关系） | `app/ontology/schema.yaml` 的 `objects` |
| 不该用 A 做 B | 工具的 `description` 里的「【不要用于】」段（#8133 形态） |

## 口径（三条硬约束）

1. **不写死任何工具名 / skill 名**：条目全部从注册表现算（判据用合成事实自证「derive 而非写死」）。
2. **不新增事实**：`BaseTool.triggers` / `BaseTool.not_for` 是 `description` 里同名段的
   **投影**（同一份字节），不另存副本 ⇒ 结构上不可能漂成第二事实源。
3. **不从本体推能力**：ontology 只贡献业务对象词表（商家叫法 + 对象关系），
   **不贡献**「能不能做」—— schema 的 `actions` 段已按 issue #8172 出库。

Seam: `render_cheatsheet(skill_name)` → str（只给 mibao；调用方按 persona 门控）。
`python -m app.tools.cheatsheet --check`：同一输入两次渲染逐字节比对（确定性判据）。
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Iterable, List, Optional, Sequence, Tuple

#: 段首标记（渲染与解析共用同一串；解析不到 = 「没有小抄」）。
MARKER = "【选工具小抄】"

_HEADER = (
    MARKER
    + "商家这么说→用哪把（✗ = 别拿它做这些）："
)

#: 每个工具最多渲染几条触发词、每条最多几个字（小抄是**索引**，不是第二份 description ——
#: 触发词只做「商家这么说时先看这一把」的锚点，选错面靠 `✗` 与工具自己的 description 兜）。
_TRIGGER_MAX = 1
_TRIGGER_CHARS = 8
#: `not_for` 最多渲染几个跳转目标（只渲染目标名 —— 具体「什么情况下别用」在 description 里）。
_NOT_FOR_MAX = 2
#: 本体词表：整行最多几个字（超了截断 —— 宁可少说也不白烧每轮 token）。
_OBJECT_LINE_CHARS = 60

#: 商家说法的引号形态（`【触发】` 段里实际出现两种；纯字符串扫描，不用正则取引号内内容）。
_QUOTE_PAIRS: Tuple[Tuple[str, str], ...] = (("「", "」"), ("'", "'"), ("“", "”"))

#: `not_for` 条目里的跳转形态：「（用 X）」。
_TARGET_OPEN = "（用 "

#: 本体词表行的前缀（判据据此把它与工具条目区分开）。
OBJECT_LINE_PREFIX = "- 业务对象（本体）："


# ── `description` 段的**纯字符串**解析（`triggers` / `not_for` 的唯一实现）────────
# 为什么不用正则：本仓对「按引号定界取值」有专门守卫（注释里的假字面量会被当真值），
# 故这里一律 `find` / `startswith` / `split`，不写带引号捕获组的正则。
def segment(description: str, marker: str) -> str:
    """取 `description` 里 `marker` 段（到下一个 `【` 段或结尾为止）；没有 ⇒ 空串。"""
    text = description or ""
    start = text.find(marker)
    if start < 0:
        return ""
    rest = text[start + len(marker):]
    end = rest.find("【")
    return (rest if end < 0 else rest[:end]).strip()


def quoted_phrases(text: str) -> List[str]:
    """按出现顺序取 `text` 里被引号括起来的短语（三种引号形态）。"""
    out: List[str] = []
    index = 0
    text = text or ""
    while index < len(text):
        for opening, closing in _QUOTE_PAIRS:
            if not text.startswith(opening, index):
                continue
            end = text.find(closing, index + len(opening))
            if end > index + len(opening):
                phrase = text[index + len(opening):end].strip()
                if phrase:
                    out.append(phrase)
                index = end + len(closing)
                break
            break
        else:
            index += 1
    return out


def not_for_entries(text: str) -> List[Tuple[str, str]]:
    """`【不要用于】` 段 → `[(商家说法, 该用的工具名)]`（解析不出目标名的条目丢弃）。

    `text` 可以是**整段 description**，也可以**已经是**该段（调用方常直接传 `tool.not_for`）——
    两种形态都吃，避免"传错一层就静默返回空"这类假绿。
    """
    out: List[Tuple[str, str]] = []
    body = segment(text, "【不要用于】") if "【不要用于】" in (text or "") else (text or "")
    for chunk in body.split("；"):
        chunk = chunk.strip()
        if not chunk:
            continue
        start = chunk.find(_TARGET_OPEN)
        if start < 0:
            continue
        end = chunk.find("）", start + len(_TARGET_OPEN))
        if end < 0:
            continue
        target = chunk[start + len(_TARGET_OPEN):end].strip()
        if target:
            out.append((chunk[:start].strip(), target))
    return out


# ── 注册表 / 本体（事实源；不在这里抄任何清单）─────────────────────────────────
def _registry(registry: Any = None) -> Any:
    if registry is not None:
        return registry
    from app.tools.registry import get_tool_registry

    return get_tool_registry()


def _declared(skill_name: str) -> List[str]:
    """本轮 skill 的**声明面**（`SkillConfig.tool_names`，保序）；不在注册表 ⇒ 空。"""
    from app.graph.skills.skill_registry import get_skill_registry

    cfg = get_skill_registry().get(skill_name)
    return list(cfg.tool_names or ()) if cfg is not None else []


@lru_cache(maxsize=1)
def _ontology() -> Any:
    from app.ontology.loader import load_ontology

    return load_ontology()


def _ordered_tools(registry: Any, names: Sequence[str]) -> List[Any]:
    """按**声明面顺序**取工具实例（确定性来源：`SkillConfig.tool_names` 是保序列表）。

    不存在的名字直接跳过（声明面与注册表是两个事实，缺失由「双向一致」判据具名报红，
    而不是在这里静默促成"看起来正常"的绿）。
    """
    by_name = {t.name: t for t in registry.get_all_tools()}
    return [by_name[name] for name in names if name in by_name]


def iter_rendered_tools(skill_name: str, registry: Any = None) -> List[Any]:
    """本次**真正被渲染**的工具（红证钩子：判据把它替换成"静默跳过某工具"的版本）。

    单独抽成函数是为了让「渲染器漏渲染一把工具」变成一个**可注入**的形态 ——
    判据注入该函数即可验证「双向一致」判据会红并具名那把工具。
    """
    return _ordered_tools(_registry(registry), _declared(skill_name))


# ── 渲染 ────────────────────────────────────────────────────────────────────
def _tool_triggers(tool: Any) -> str:
    """触发词（最多 `_TRIGGER_MAX` 条、每条 ≤ `_TRIGGER_CHARS` 字）；没有 ⇒ 空串。"""
    phrases = quoted_phrases(segment(getattr(tool, "description", "") or "", "【触发】"))
    picked: List[str] = []
    for phrase in phrases:
        if not (0 < len(phrase) <= _TRIGGER_CHARS):
            continue
        if phrase in picked:
            continue
        picked.append(phrase)
        if len(picked) >= _TRIGGER_MAX:
            break
    return "/".join(picked)


def _tool_not_for(tool: Any) -> str:
    """「别拿它做这些」的跳转目标（最多 `_NOT_FOR_MAX` 个，逗号分隔）；没有 ⇒ 空串。"""
    targets: List[str] = []
    for _label, target in not_for_entries(getattr(tool, "description", "") or ""):
        if target in targets:
            continue
        targets.append(target)
        if len(targets) >= _NOT_FOR_MAX:
            break
    return ",".join(targets)


def _tool_line(tool: Any) -> str:
    """一行一把工具：`- <名>〔写〕 <触发词> ✗ <跳转目标…>`。"""
    line = "- " + str(getattr(tool, "name", "") or "")
    if not getattr(tool, "read_only", True):
        line += "〔写〕"
    triggers = _tool_triggers(tool)
    if triggers:
        line += " " + triggers
    not_for = _tool_not_for(tool)
    if not_for:
        line += " ✗" + not_for
    return line


def _first_token(name: str) -> str:
    return (name or "").split("_")[0]


def _object_line(tool_names: Iterable[str], ontology: Any) -> str:
    """**一行**本体词表：`商家叫法（对象关系）`（只讲"是什么 / 连着谁"，不讲"能不能做"）。

    选哪些对象：对象名与「本次渲染的工具名」有词面交集（首段相等，或规范名是其前缀）。
    这是**呈现层的分组**，不是能力判定 —— 故漏一个 / 多一个都不会让模型高估能力面。

    为什么压成一行：本体在 prompt 里的职责只有「商家怎么叫它」；多行会让每轮预算
    付一份与选工具无关的词表（判据：`test_cheatsheet_block_stays_within_budget`）。
    """
    tokens = {_first_token(n) for n in tool_names}
    normalized = [n.replace("_", "") for n in tool_names]
    parts: List[str] = []
    for obj in sorted(getattr(ontology, "objects", {}).values(), key=lambda o: o.name):
        own = obj.name.replace("_", "")
        hit = _first_token(obj.name) in tokens or any(
            name.startswith(own) for name in normalized if own)
        if not hit:
            continue
        relations = "、".join(
            r.description for r in (getattr(obj, "relations", []) or []) if r.description)
        parts.append(f"{obj.display_name}（{relations}）" if relations else obj.display_name)
    line = OBJECT_LINE_PREFIX
    for part in parts:
        candidate = line + ("；" if line != OBJECT_LINE_PREFIX else "") + part
        if len(candidate) > _OBJECT_LINE_CHARS:
            break
        line = candidate
    return "" if line == OBJECT_LINE_PREFIX else line


def render_cheatsheet(skill_name: str, *,
                      registry: Any = None,
                      ontology: Any = None) -> str:
    """渲染本轮 skill 的选工具小抄；**没有任何工具可渲染 ⇒ 空串**（不产出空壳段）。

    Args:
        skill_name: 本轮 skill 名（`SkillConfig` 的键）。
        registry: 工具注册表（缺省 = 全局注册表）；判据用合成注册表自证 derive。
        ontology: 本体（缺省 = 包内 schema）；判据用合成本体自证词表来自本体。

    Returns:
        str: 以 `MARKER` 开头的多行文本；无工具时为空串。
    """
    tools = iter_rendered_tools(skill_name, registry)
    if not tools:
        return ""
    lines = [_HEADER]
    lines.extend(_tool_line(tool) for tool in tools)
    object_line = _object_line([t.name for t in tools], ontology or _ontology())
    if object_line:
        lines.append(object_line)
    return "\n".join(lines)


def _all_skill_names() -> List[str]:
    from app.graph.skills.skill_registry import get_skill_registry

    return sorted(cfg.name for cfg in get_skill_registry().get_all())


def check_deterministic() -> int:
    """`--check`：每个 skill 连渲两次必须**逐字节相同**。三态退出码 `0/1/3`。"""
    rendered = {name: render_cheatsheet(name) for name in _all_skill_names()}
    non_empty = {k: v for k, v in rendered.items() if v}
    if not non_empty:
        print("[cheatsheet] 不可判定：一个 skill 都没渲染出小抄（fail-closed，不得当 0 读）")
        return 3
    unstable = []
    for name in sorted(non_empty):
        again = render_cheatsheet(name)
        if again != non_empty[name]:
            unstable.append(name)
    if unstable:
        print(f"[cheatsheet] 渲染不确定（同一输入两次不同）：{unstable}")
        return 1
    print(f"[cheatsheet] 确定性通过：{len(non_empty)} 个 skill，逐字节一致"
          f"（长度 {sorted(len(v) for v in non_empty.values())}）")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    import sys

    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--check"]:
        return check_deterministic()
    if args and args[0] == "--render":
        skill = args[1] if len(args) > 1 else ""
        text = render_cheatsheet(skill)
        if not text:
            print(f"[cheatsheet] skill '{skill}' 没有可渲染的工具")
            return 3
        print(text)
        return 0
    print("用法：python -m app.tools.cheatsheet --check | --render <skill>")
    return 2


if __name__ == "__main__":   # pragma: no cover - CLI 入口
    raise SystemExit(main())
