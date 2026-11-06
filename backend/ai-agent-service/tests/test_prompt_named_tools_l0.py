# case_ids: MC-248
"""**L0 判据**（issue #8775）：「prompt 里点名的工具，必须在该 skill 裁剪后的可执行集内」。

## 为什么这条判据存在（它比修一处代码值钱）

PR-130（真回归，run 42127246100）的现场：`product_search` 被模型照 prompt 调用 ⇒
`tool_not_found`，而日志里 `not found in global registry` 计数 = **0** —— 工具**在**全局
注册表，是被**技能子集**剔掉的（`config.py` 的 `TOOL_TRIM_ENABLED=True` /
`TOOL_TRIM_MAX_READ=16`；商品域 20 个声明工具 + 家族只读 35+ ⇒ **必然**超上限）。

那个回归**本来可以在合并前被静态判据抓到**（20 + 35 > 16 是静态可算的），不必烧一次
真实 LLM 评测。本文件就是那条判据：不调 LLM、不连网、不依赖真栈。

## 判据（唯一本体 = `_violations()`）

    prompt 点名的工具  ⊆  该 skill 经 tool_selection 裁剪后的可执行集

两侧都**现取**，且刻意不复用被测实现：

- 「点名」= 注册表里的工具名出现在该 skill 的 `system_prompts` 文本中，且作为**独立标识符**
  （前后不是 `[A-Za-z0-9_]`）。**不看**有没有反引号、不猜 `tool_hint` —— prompt 只要写了名字，
  模型就可能照着调；多算 = 多保底（方向安全），少算 = 线上 `tool_not_found`。
- 「裁剪后的可执行集」= **直接调用现有实现**：`plan_read_tools_for_state()` +
  `create_skill_registry(read_keep=read_keep)`（`prepare_turn` 的同一对调用），不复制逻辑。
- 场景取**可达组合**：空信号 / 该 skill 自己的每个意图 / 中性问法 / PR-130 的原句 /
  **对抗场景**（消息里塞满「**没**被点名**的**工具名 ⇒ 它们各拿满名命中分，把预算吃光 ——
  这正是 PR-130 把 `product_search` 挤出去的那个机制）。

## 每条判据都有红证（不会红的断言 = 空断言）

| 判据 | 红证（见本文件的 `test_red_proof_*` / 注入即红） |
|---|---|
| 全库 × 全场景「点名 ⊆ 可执行」 | 把 `product_search` 从 prompt 保底里摘掉 ⇒ 具名红（只报它一个） |
| 同上（PR-130 原形态） | 同时摘掉 prompt 保底与属主保底 ⇒ 复现真回归：`product_search` 等 4 把被裁、具名红 |
| 点名工具在**不裁剪**时也必须可绑定 | 该条独立于开关 ⇒ `TOOL_TRIM_ENABLED=False` 时依然有牙 |
| 负控 1：**没**点名的工具被裁 ⇒ 不红 | 对抗场景里被裁的全是没点名的 ⇒ `_violations()` 为空；把其中一把**假装成点名** ⇒ 立刻具名红 |
| 负控 2：关掉裁剪 ⇒ 不红 | `TOOL_TRIM_ENABLED=False` ⇒ 全绑定、零违规；此时把「点名集合」放大到全注册表 ⇒ 仍能具名红（判据没被关成空转） |
| 扫描面非空自证（fail-closed） | 扫到 0 个 skill / 0 个点名 / 0 个场景 ⇒ 直接红 |

## 边界（照实登记）

- 判**静态绑定面**，不判「模型会不会真的选对工具」—— 后者只有评测能判，本判据不烧评测。
- 扫的是 skill **自己的** prompt 文本（`system_prompts`）；运行期拼接的「工具速查」投影
  不参与判定（那是**工具说明**，不是「prompt 点名要它执行」）。
- 只锁「prompt 说了要用 ⇒ 必须可达」；「该绑什么」的业务口径仍由 `.github/cases/` 与
  `tests/unit_ci_workflows/test_mibao_b_end_readonly.py` 负责。
"""
import re

import pytest
from langchain_core.messages import HumanMessage

from app.graph.skills import tool_selection as ts
from app.graph.skills.skill_registry import get_skill_registry
from app.tools.registry import get_tool_registry

#: 注册表工具名（点名判定的**宇宙**：只认真实存在的工具名，不猜 `list_categories` 这类 action）
ALL_TOOL_NAMES = tuple(t.name for t in get_tool_registry().get_all_tools() if t.name)

#: 「独立标识符」边界（与实现无关的判定式：`product_search2` / `xproduct_search` 都不算点名）
_NAMED_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:"
    + "|".join(sorted((re.escape(n) for n in ALL_TOOL_NAMES), key=len, reverse=True))
    + r")(?![A-Za-z0-9_])"
)

#: PR-130 的**原句**（run 42127246100 的 `product_detail` 调用就发生在这一轮）
PR130_MESSAGE = "2699系列雪尼尔窗帘面料，2.8 米门幅，做 3 米宽的一幅窗帘，大概多少钱？"
NEUTRAL_MESSAGE = "帮我查一下最近订单的物流到哪了"

#: 扫描面（全部已注册 skill，B 端 + C 端都扫：裁剪只对 B 端生效，但「点名必须可执行」对两端都成立）
SKILLS = list(get_skill_registry().get_all())


# ── 判据本体（两侧都现取，不复用被测实现）──────────────────────────────────
def prompt_named_tools(cfg) -> list:
    """该 skill **prompt 里点名**的工具名（独立实现：直接扫 `system_prompts` 文本）。"""
    named: list = []
    for text in (cfg.system_prompts or {}).values():
        for name in _NAMED_RE.findall(str(text or "")):
            if name not in named:
                named.append(name)
    return named


def _plan(cfg, message: str, intent: str):
    """走**运行时同一条**路径：state 适配层 → 裁剪计划（`None` = 不裁剪）。"""
    persona = next(iter(cfg.system_prompts))
    state = {
        "agent_type": persona,
        "intent_result": {"intent": intent},
        "messages": [HumanMessage(content=message)] if message else [],
    }
    return ts.plan_read_tools_for_state(state, list(cfg.tool_names))


def executable_tools(cfg, message: str, intent: str) -> set:
    """裁剪后的**可执行集**（直接调用现有工厂，不复制逻辑）。"""
    registry = ts.create_skill_registry(list(cfg.tool_names), read_keep=_plan(cfg, message, intent))
    return set(registry.get_tool_names())


def bindable_tools(cfg) -> set:
    """不裁剪时的可执行集（声明面 ∪ 家族只读）—— 判「点名工具到底绑没绑」。"""
    registry = ts.create_skill_registry(list(cfg.tool_names), read_keep=None)
    return set(registry.get_tool_names())


def violations(cfg, named, message: str, intent: str) -> list:
    """判据本体：点名的工具里**不可执行**的那些（具名返回，空 = 合规）。"""
    executable = executable_tools(cfg, message, intent)
    return [n for n in named if n not in executable]


def scenarios(cfg) -> list:
    """可达输入场景：空信号 / 自己的每个意图 / 中性问法 / PR-130 原句 / **对抗场景**。"""
    intents = list(cfg.intents or [])
    head = intents[0] if intents else ""
    named = set(prompt_named_tools(cfg))
    # 对抗场景：消息里只有**没被点名**的工具名 ⇒ 它们各拿满名命中分，预算被吃光。
    others = [n for n in ALL_TOOL_NAMES if n not in named]
    out = [
        ("empty", "", ""),
        ("neutral", NEUTRAL_MESSAGE, head),
        ("pr130", PR130_MESSAGE, "product_inquiry"),
        ("adversarial", " ".join(others), head),
    ]
    out += [(f"intent:{i}", "", i) for i in intents]
    return out


# ── 1. 主判据：全库 × 全场景 ───────────────────────────────────────────────
@pytest.mark.parametrize("cfg", SKILLS, ids=[c.name for c in SKILLS])
def test_prompt_named_tools_are_executable(cfg):
    """prompt 点名的每个工具，在该 skill 裁剪后的可执行集内（issue #8775 的 L0 判据）。"""
    named = prompt_named_tools(cfg)
    if not named:
        raise AssertionError(
            f"{cfg.name}: prompt 里一个工具名都没点到 —— 扫描面为空，本判据会空转（fail-closed）")
    for label, message, intent in scenarios(cfg):
        missing = violations(cfg, named, message, intent)
        assert not missing, (
            f"{cfg.name}[{label}]：prompt 点名却**不可执行** {missing} —— 模型会照 prompt 调它们"
            f"并拿到 tool_not_found（PR-130 的形态；issue #8775）")


def test_named_tools_are_bindable_without_trimming():
    """点名工具必须**真的绑在本 skill 上** —— 这一半与裁剪开关无关（关掉裁剪时仍有牙）。"""
    checked = 0
    for cfg in SKILLS:
        bound = bindable_tools(cfg)
        unbound = [n for n in prompt_named_tools(cfg) if n not in bound]
        assert not unbound, (
            f"{cfg.name}: prompt 点名了**根本没绑定**的工具 {unbound} —— 那是另一类缺陷"
            f"（prompt 承诺了不可达的能力）；修法 = 绑上它，或别在 prompt 里点名")
        checked += 1
    assert checked >= 17, f"扫描面过小（{checked} 个 skill）—— 判据退化成空判据"


# ── 2. 红证：摘掉保底 ⇒ 具名红 ─────────────────────────────────────────────
def test_red_proof_dropping_one_named_tool_names_it(monkeypatch):
    """把 `product_search` 从 prompt 保底里摘掉 ⇒ 判据**具名**红（且只报它）。

    这是「判据会红」的最小正控：保留集其余部分完全不变，唯一变量就是那把被摘掉的工具。
    """
    cfg = get_skill_registry().get("product")
    named = prompt_named_tools(cfg)
    original = ts._prompt_named_tool_names
    monkeypatch.setattr(ts, "_prompt_named_tool_names",
                        lambda names: [n for n in original(names) if n != "product_search"])
    missing = violations(cfg, named, PR130_MESSAGE, "")
    assert missing == ["product_search"], (
        f"摘掉 product_search 的保底后，判据报的是 {missing} —— 期望恰好具名它一个")


def test_red_proof_prefix_state_reproduces_pr130(monkeypatch):
    """复现 PR-130 的**真回归**：没有 prompt 保底、属主保底也补不到（= 改动前的实际行为）。

    改动前 `owner_extra` 带 `n not in declared_set` ⇒ 「本 skill 自己声明的读工具」拿不到任何
    保底，只能拼分数；PR-130 那一轮它拼输了。摘掉两条保底后本判据必须具名报出同样的形态。
    """
    cfg = get_skill_registry().get("product")
    named = prompt_named_tools(cfg)
    monkeypatch.setattr(ts, "_prompt_named_tool_names", lambda _names: [])
    monkeypatch.setattr(ts, "_intent_owner_read_tool_names", lambda _intent: [])
    missing = violations(cfg, named, PR130_MESSAGE, "")
    assert "product_search" in missing, (
        f"改动前的形态没有复现：被裁的是 {missing} —— 判据抓不到 PR-130 那种「prompt 点名、"
        f"工具在全局注册表、却被技能子集剔掉」的回归")
    assert sorted(missing) == ["marketing_poster", "processing_item_query",
                               "product_image_generate", "product_search"], (
        f"复现形态与实测不符：{sorted(missing)}（现取基准 = 这 4 把）")


# ── 3. 负控 1：没点名的工具被裁掉 ⇒ 不红（那不是缺陷）────────────────────
def test_negative_control_unnamed_cut_is_not_a_violation():
    """对抗场景下确实有工具被裁，但被裁的全是**没点名**的 ⇒ 判据不许红。"""
    cfg = get_skill_registry().get("product")
    named = prompt_named_tools(cfg)
    label, message, intent = next(s for s in scenarios(cfg) if s[0] == "adversarial")
    executable = executable_tools(cfg, message, intent)
    cut = sorted(bindable_tools(cfg) - executable)
    assert cut, f"{cfg.name}[{label}]: 一个工具都没被裁 —— 裁剪没有生效，负控本身失效"
    cut_named = [n for n in cut if n in named]
    assert not cut_named, (
        f"{cfg.name}[{label}]: 被裁的工具里有 prompt 点名的 {cut_named} —— 主判据应该已经红了")
    assert not violations(cfg, named, message, intent), (
        f"{cfg.name}[{label}]: 没点名的工具被裁却判红了 —— 判据把正常裁剪当缺陷（误红）")
    # 判别力自证：把这些「没点名、已裁掉」的工具**假装成点名** ⇒ 判据必须立刻具名红。
    pretend = violations(cfg, cut, message, intent)
    assert pretend == cut, (
        f"{cfg.name}[{label}]: 假装点名后判据只报 {pretend}（期望 {cut}）—— "
        f"负控的「不红」可能来自判据失明，而不是「它们没被点名」")


# ── 4. 负控 2：关掉裁剪 ⇒ 不红（并说明这条判据此时是否仍有意义）───────────
def test_negative_control_trim_disabled_is_green_and_criterion_still_bites(monkeypatch):
    """`TOOL_TRIM_ENABLED=False` ⇒ 全部绑定、零违规；但判据**不是空转**。

    关裁剪时「点名 ⊆ 可执行」照样有意义 —— 它退化成「点名工具必须绑在本 skill 上」这一半
    （见 `test_named_tools_are_bindable_without_trimming`）：prompt 点名一把**没绑**的工具，
    照样会 `tool_not_found`，与开关无关。
    """
    monkeypatch.setattr(ts.settings, "TOOL_TRIM_ENABLED", False)
    cfg = get_skill_registry().get("product")
    named = prompt_named_tools(cfg)
    if _plan(cfg, PR130_MESSAGE, "") is not None:
        raise AssertionError("关掉裁剪后仍返回了裁剪名单 —— 负控的前提不成立（开关没生效）")
    assert not violations(cfg, named, PR130_MESSAGE, ""), (
        "关掉裁剪后 prompt 点名的工具仍不可执行 —— 这不是裁剪面，是绑定面缺陷")
    # 判别力自证：把「点名集合」放大到全注册表 ⇒ 没绑的那些必须具名报出（判据没被关成空转）
    inflated = violations(cfg, list(ALL_TOOL_NAMES), PR130_MESSAGE, "")
    unbound = sorted(set(ALL_TOOL_NAMES) - bindable_tools(cfg))
    assert sorted(inflated) == unbound and len(unbound) >= 10, (
        f"关裁剪时判据没有牙：报 {inflated[:5]}…，而没绑的应有 {len(unbound)} 把 —— "
        f"「不红」可能来自判据失明")


# ── 5. 扫描面非空自证（fail-closed：扫不到 ⇒ 红，不许「0 个 ⇒ 通过」）───────
def test_scan_surface_is_non_empty():
    """skill 数 / 点名数 / 场景数三个下界 —— 任一退化 ⇒ 具名红。"""
    skills = list(get_skill_registry().get_all())
    assert len(skills) == len(ts._all_skill_configs()), (
        f"扫描的 skill 数（{len(skills)}）与注册表（{len(ts._all_skill_configs())}）不一致 —— "
        f"有 skill 被跳过")
    assert len(skills) >= 17, f"注册到的 skill 只有 {len(skills)} 个 —— 扫描面退化"
    per_skill = {cfg.name: len(prompt_named_tools(cfg)) for cfg in skills}
    total_named = sum(per_skill.values())
    total_scenarios = sum(len(scenarios(cfg)) for cfg in skills)
    assert total_named >= 40, f"全库点名工具只有 {total_named} 个 —— 点名判定失效（per-skill={per_skill}）"
    assert total_scenarios >= 80, (
        f"全库场景只有 {total_scenarios} 个 —— 场景构造失效，判据覆盖不到可达输入")
