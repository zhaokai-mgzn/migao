# case_ids: OR-029
"""系统提示「能力索引」—— `域 → 该域可执行的写工具`（issue #4125，关联 #4123 第二刀）。

## 被测事实

域切分下模型每轮只看见自己域的 1~12 个工具，**没有任何东西告诉它其余能力存在、归谁**；
被域闸门拒（`cross_skill_target`）时也就不知道该去哪儿。本包在 `_build_system_prompt` 的
组装里加一层**静态小地图**（Layer 2.6）：一行一个域 + 该域可执行的**写工具**；
只读工具用一句话表述为"全局可用"（它们是跨域共享的，逐条列举只会白烧预算）。

## 判据必须**从事实 derive**（本文件的核心）

索引内容 = `SkillConfig.tool_names` × 注册表 `read_only` 事实的机械投影 ——
**不写死任何 skill 名/工具名**（本仓对"白名单复发"有专门守卫，见 `test_capability_denial_guard.py`）。
故本文件用**现算的期望值**与提示词里**实际渲染出来的索引**做逐域比对（不是快照、不是人眼）。

## ⚠️ 边界（与 `references/base/principles.md` 第 21 行「回复中禁止出现工具名/字段名」不冲突）

索引是**给模型看的**（system prompt），**不是给用户说的**（assistant 输出）。
两条守卫把这条边界钉死：
  · `test_index_is_not_rendered_on_any_user_facing_path` —— 渲染函数在 `app/**` 里**只**被
    `_build_system_prompt` 引用（静态 AST 扫描 + 植入负例自证能红）；
  · 索引本身不给用户可复述的话术，原则层的「面向用户一律中文 / 禁止工具名」规则原样保留
    （`test_prompt_snapshots.py` 既有断言未动）。

## 每条断言的红证（改这一处即红）

| 用例 | 反例输入（改这一处即红） |
|---|---|
| `test_index_present_in_every_registered_domain` | 不渲染索引（= 改前）⇒ 全红 |
| `test_index_matches_skill_config_facts_per_domain` | 索引里手写一个域/漏一个域/少列一个写工具 ⇒ 红 |
| `test_index_lists_only_registered_non_readonly_tools` | 把只读工具也列进域行（或写上不存在的工具名）⇒ 红 |
| `test_no_persona_only_tool_appears_in_another_personas_index` | 索引按"全局工具"渲染 ⇒ C 端提示词里出现 `order_query` |
| `test_index_is_derived_from_registry_not_hardcoded` | 索引写死真实 skill 名 ⇒ 合成注册表下渲染不出合成域 |
| `test_index_stays_within_budget` | 索引膨胀（例如逐条列只读工具）⇒ 超预算即红 |
| `test_index_is_not_rendered_on_any_user_facing_path` | 在别处（用户可见路径）调用渲染函数 ⇒ 红 |
"""
import ast
from pathlib import Path
from unittest.mock import patch

import pytest

from app.graph.skills.base_skill import _PROMPT_CACHE, _build_system_prompt
from app.graph.skills.skill_registry import get_skill_registry
from app.tools.registry import get_tool_registry

#: 索引区块的起始标记（渲染与解析共用同一串 —— 解析不到即"没有索引"）。
_MARKER = "【能力索引】"

#: 渲染函数的模块级名字（静态边界扫描的对象）。
_RENDERER = "_capability_index"

_APP_DIR = Path(__file__).resolve().parents[1] / "app"


@pytest.fixture(autouse=True)
def _clear_prompt_cache():
    _PROMPT_CACHE.clear()
    yield
    _PROMPT_CACHE.clear()


# ────────────────────── 事实派生（现算，不抄清单） ──────────────────────

def _read_only_names() -> set:
    return {t.name for t in get_tool_registry().get_all_tools()
            if getattr(t, "read_only", False)}


def _writable(cfg, read_only: set) -> list:
    """该域**可执行的写工具** = `tool_names` 里非只读的那些（保序 = 配置声明序）。"""
    return [t for t in (cfg.tool_names or []) if t not in read_only]


def _same_persona(cfg) -> list:
    personas = set(cfg.system_prompts or {})
    return [c for c in get_skill_registry().get_all()
            if personas & set(c.system_prompts or {})]


def _expected_index(cfg) -> dict:
    """该域提示词里**应该**出现的索引（`{域: [写工具]}`，只含有写工具的域）。"""
    read_only = _read_only_names()
    out = {}
    for other in sorted(_same_persona(cfg), key=lambda c: c.name):
        writes = _writable(other, read_only)
        if writes:
            out[other.name] = writes
    assert out, f"{cfg.name} 的期望索引为空 —— 判据会空跑（fail-closed）"
    return out


def _parse_index(prompt: str) -> dict:
    """从组装好的提示词里**解析**实际渲染出的索引（解析不到 → 空 dict）。"""
    lines = (prompt or "").split("\n")
    for i, line in enumerate(lines):
        if not line.startswith(_MARKER):
            continue
        out: dict = {}
        for nxt in lines[i + 1:]:
            if not nxt.startswith("- "):
                break
            name, sep, tools = nxt[2:].partition(": ")
            assert sep, f"索引行格式不是 `- <域>: <工具…>`：{nxt!r}"
            out[name] = tools.split()
        return out
    return {}


def _persona_tool_sets() -> dict:
    out: dict = {}
    for cfg in get_skill_registry().get_all():
        for persona in (cfg.system_prompts or {}):
            out.setdefault(persona, set()).update(cfg.tool_names or [])
    assert out, "persona→工具集 派生为空 —— 判据空跑（fail-closed）"
    return out


# ────────────────────── ① 存在性 + 逐域事实一致 ──────────────────────

def test_index_present_in_every_registered_domain():
    """每个已注册域的提示词里都必须**有**索引（改前无 ⇒ 本用例红）。"""
    missing = []
    for cfg in get_skill_registry().get_all():
        prompt = _build_system_prompt(cfg.name)
        if not _parse_index(prompt):
            missing.append(cfg.name)
    assert not missing, (
        f"以下域的 system prompt 里没有能力索引：{missing} —— "
        f"模型被拒后仍然不知道能力面在哪")


def test_index_matches_skill_config_facts_per_domain():
    """**机械比对**（不靠人眼）：实际渲染的索引 == 配置事实的投影（逐域逐工具）。"""
    failures = []
    for cfg in get_skill_registry().get_all():
        got = _parse_index(_build_system_prompt(cfg.name))
        want = _expected_index(cfg)
        if got != want:
            only_rendered = {k: got[k] for k in got if k not in want}
            only_fact = {k: want[k] for k in want if k not in got}
            diff = {k: (got[k], want[k]) for k in got if k in want and got[k] != want[k]}
            failures.append(
                f"{cfg.name}: 杜撰 {only_rendered} / 遗漏 {only_fact} / 内容不符 {diff}")
    assert not failures, (
        "能力索引与 SkillConfig.tool_names 事实不一致（R2 ②）：\n  " + "\n  ".join(failures))


def test_index_lists_only_registered_non_readonly_tools():
    """索引里的每个工具名都必须是**已注册的非只读**工具（防杜撰 + 防把只读混进域行）。"""
    registered = {t.name for t in get_tool_registry().get_all_tools()}
    read_only = _read_only_names()
    bad = []
    checked = 0
    for cfg in get_skill_registry().get_all():
        for domain, tools in _parse_index(_build_system_prompt(cfg.name)).items():
            for name in tools:
                checked += 1
                if name not in registered:
                    bad.append(f"{cfg.name}: `{name}` 不是已注册工具（杜撰）")
                elif name in read_only:
                    bad.append(
                        f"{cfg.name}: `{name}` 是只读工具却列进了 `{domain}` 的写工具行"
                        f"（只读已全局可用，逐条列举白烧预算且误导路由）")
    assert checked > 0, "一处索引条目都没扫到 —— 本判据会恒真（空判据）"
    assert not bad, "\n  " + "\n  ".join(bad)


def test_index_states_that_readonly_tools_are_globally_available():
    """只读工具必须有一句「全局可用」的表述（否则模型不知道该直接查，仍会去找域）。"""
    prompt = _build_system_prompt("order")
    head = prompt.split(_MARKER, 1)[1].split("\n- ", 1)[0]
    assert "只读" in head and ("全局" in head or "所有流程" in head), (
        f"能力索引抬头没说明只读工具全局可用：{head!r}")


# ────────────────────── ② R2 ③：persona 边界在**提示词**层面也成立 ──────────────────────

def test_no_persona_only_tool_appears_in_another_personas_index():
    """索引只能列**本 persona 可达**的工具 —— persona 可达集仍是硬边界（R2 ③）。

    索引是模型直接读到的东西：把别端专属的工具名写进提示词 = 告诉它"你能用"。
    判据（现算，不抄清单）：`渲染出的工具集 ⊆ 该域所属 persona 的可达集`；
    并附 C 端见证 —— B 端专属工具一个都不许出现在 xiaobu 的索引里。
    """
    by_persona = _persona_tool_sets()
    personas = sorted(by_persona)
    assert len(personas) >= 2, f"只派生到 {personas} —— 边界判据无从成立"

    leaks = []
    rendered_total = 0
    checked = 0
    for cfg in get_skill_registry().get_all():
        own_personas = set(cfg.system_prompts or {})
        if not own_personas:
            continue
        reachable = set().union(*(by_persona[p] for p in own_personas))
        rendered = set()
        for _domain, tools in _parse_index(_build_system_prompt(cfg.name)).items():
            rendered.update(tools)
        rendered_total += len(rendered)
        checked += 1
        hit = sorted(rendered - reachable)
        if hit:
            leaks.append(f"{cfg.name}（{sorted(own_personas)} 端）的索引列了不可达工具 {hit}")

    assert checked >= 6, f"只比对了 {checked} 个域 —— 判据疑似空跑"
    assert rendered_total > 0, "一处索引都没渲染出来 —— 本判据会恒真（空判据）"
    assert not leaks, "persona 硬边界被能力索引打破：\n  " + "\n  ".join(leaks)

    # C 端见证（R2 ③ 的原始措辞）：B 端**专属**工具不得出现在 xiaobu 域的索引里
    assert {"mibao", "xiaobu"} <= set(by_persona)
    b_only = by_persona["mibao"] - by_persona["xiaobu"]
    assert b_only, "Mibao 无专属工具 —— 见证判据对空集恒真"
    for cfg in get_skill_registry().get_all():
        if "xiaobu" not in (cfg.system_prompts or {}):
            continue
        rendered = set()
        for _domain, tools in _parse_index(_build_system_prompt(cfg.name)).items():
            rendered.update(tools)
        assert not (rendered & b_only), (
            f"{cfg.name}（C 端）的索引里出现 B 端专属工具 {sorted(rendered & b_only)}")


# ────────────────────── ③ derive 而非写死（合成注册表自证） ──────────────────────

def test_index_is_derived_from_registry_not_hardcoded():
    """**把注册表换成合成事实**：索引必须跟着变 —— 写死 skill 名/工具名的实现必红。"""
    from app.graph.skills.skill_config import SkillConfig

    synth = [
        SkillConfig(
            name="zzz_synth", domain="zzz", display_name="合成域",
            tool_names=["zzz_manage", "order_query"],   # 后者是真只读工具 → 不该进域行
            system_prompts={"synth_persona": "合成 prompt"},
        ),
    ]

    class _FakeRegistry:
        def get_all(self):
            return synth

        def get(self, name):
            return next((c for c in synth if c.name == name), None)

    with patch("app.graph.skills.skill_registry.get_skill_registry",
               return_value=_FakeRegistry()):
        parsed = _parse_index(_build_system_prompt("zzz_synth"))

    assert parsed == {"zzz_synth": ["zzz_manage"]}, (
        f"合成注册表下渲染出 {parsed} —— 索引没有从注册表事实 derive（写死了真实 skill/工具名）")


# ────────────────────── ④ 预算（实测量级见 PR） ──────────────────────

#: 索引区块的字符上限（**实测值 + 余量**；口径：`_index_block_len()`）。
#: 实测（2026-09-18，`_build_system_prompt` 组装块）：B 端 9 域共用 **587** 字符的块
#: （180 tokens @cl100k_base 代理量级），C 端 6 域共用 **232** 字符（125 tokens）——
#: 上限取 700（≤ 目标 300 token 的等量级 + ~20% 余量）。
#: ⚠️ 为什么用字符而不是 token：tiktoken 不在 `requirements.txt` 里，且其分词器与线上模型不同
#: （cl100k 只是代理量级）—— 把不稳定量做成判据会变成"永远绿/永远红"的空判据
#: （`migao-dev-flow` §19.1 元规则）。token 量在 PR 里连命令一起给。
_INDEX_BUDGET_CHARS = 700


def _index_block_len(skill_name: str) -> int:
    prompt = _build_system_prompt(skill_name)
    assert _MARKER in prompt, f"{skill_name} 没有索引"
    head, _, tail = prompt.partition(_MARKER)
    block = _MARKER + tail.split("\n\n", 1)[0]
    return len(block)


def test_index_stays_within_budget():
    """索引区块 ≤ 预算（防"小地图"长成第二份工具手册，白烧每轮 token）。"""
    sizes = {cfg.name: _index_block_len(cfg.name)
             for cfg in get_skill_registry().get_all()}
    over = {k: v for k, v in sizes.items() if v > _INDEX_BUDGET_CHARS}
    assert not over, (
        f"索引超预算（上限 {_INDEX_BUDGET_CHARS} 字符）：{over}；"
        f"全量实测 {sizes} —— 精简文案或只列写工具")


# ────────────────────── ⑤ 边界：只在 system prompt，不在任何用户可见路径 ──────────────────────

def _renderer_callers(src_dir: Path) -> set:
    """扫 `app/**`：哪些模块**引用了**索引渲染函数名。"""
    hits = set()
    for path in sorted(src_dir.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == _RENDERER:
                hits.add(path.name)
            elif isinstance(node, ast.Attribute) and node.attr == _RENDERER:
                hits.add(path.name)
    return hits


def test_index_is_not_rendered_on_any_user_facing_path():
    """渲染函数在 `app/**` 里**只**被 `base_skill` 引用（= 只进 system prompt）。

    `references/base/principles.md` 第 21 行禁止**回复**里出现工具名/字段名；索引是给模型看的
    小地图，不是给用户说的文本。若哪天有人把同一份渲染拿去拼用户可见话术（追问问句/卡片文案），
    本判据当场红 —— 这条边界必须能红，否则只是一句声明。
    """
    callers = _renderer_callers(_APP_DIR)
    assert callers == {"base_skill.py"}, (
        f"索引渲染函数被 {sorted(callers)} 引用（只允许 base_skill.py，即只进 system prompt）—— "
        f"若确要用于用户可见文本，必须先解决「回复中禁止出现工具名/字段名」这条原则")


def test_boundary_guard_reports_a_planted_user_facing_caller(tmp_path):
    """负例（红证）：把引用塞进替身目录 ⇒ 判据必报（否则上面那条是永远绿的空判据）。"""
    (tmp_path / "follow_up.py").write_text(
        "from app.graph.skills.base_skill import _capability_index\n"
        "\n"
        "def user_visible_hint():\n"
        "    return _capability_index('order')\n",
        encoding="utf-8")
    assert _renderer_callers(tmp_path) == {"follow_up.py"}, (
        "植入「用户可见路径也调用渲染函数」后判据仍不报 —— 这是空判据")