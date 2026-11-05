# case_ids: MC-222
"""选工具小抄：由**工具注册表 + 本体**投影，替掉 9 处手写速查表（issue #8176）。

## 病根（现取读数，不是假说）

「商家这么说 → 用哪把工具 / 别拿它做什么」原先**手抄**在 9 处：`references/prompts/*.md` 的
「场景 → 工具」表（order / product / data×2 / customer / staff / settings）+ `general_agent.py`
与 `product_skill.py` 的内联表各 1 处。手抄的能力/工具口径**必然漂移** —— 同族的实证是
#7291：10 处手写边界声明里 9 处与真值相反。

## 本包的形态（真值分工，不得改）

| 事实 | 真值源 |
|---|---|
| 能做什么（工具名 / 入参 / 只读性 / 权限码） | 工具注册表（各工具的元数据与 `description`） |
| 商家怎么叫它（业务术语、对象关系） | `app/ontology/schema.yaml` 的 `objects` |
| 不该用 A 做 B | 工具 `description` 的 `【不要用于】` 段（#8133 形态） |

`BaseTool.triggers` / `BaseTool.not_for` 是上述 `description` 段的**投影**（同一份字节），
不是第二份副本 —— 判据 `test_metadata_fields_are_projections_not_copies` 钉住这一点。

## 判据与红证（每条都注入式自证）

| 用例 | 红证（改这一处即红） |
|---|---|
| `test_cheatsheet_lists_exactly_the_declared_surface` | 渲染器静默跳过一把工具 ⇒ 红并**具名**该工具 |
| `test_no_phantom_tool_in_cheatsheet` | 小抄写出未注册的工具名 ⇒ 红 |
| `test_deleted_handwritten_rule_is_handed_over_by_metadata` | 把删掉的手写规则写回 prompt ⇒ 红；把该工具的 `【不要用于】` 删掉 ⇒ 红 |
| `test_deleted_table_tools_are_all_still_rendered` | 删表却没渲染该工具 ⇒ 红（真值随之消失） |
| `test_handwritten_tables_are_gone_from_prompts` | 把任一「场景 / 工具」表写回 ⇒ 红 |
| `test_cheatsheet_block_stays_within_budget` | 小抄膨胀（逐条列 description / 逐域重复）⇒ 超预算即红 |
| `test_rendering_is_byte_stable` / `test_check_detects_a_drifting_renderer` | 渲染不确定 ⇒ `--check` 判红；让渲染漂移 ⇒ 同上判红 |
| `test_every_mibao_skill_renders_a_non_empty_scan_surface` | 渲染出 0 把工具 ⇒ 红（不许「没渲染所以没不一致」） |
| `test_table_tools_declare_triggers_and_not_for_per_family` | 订单/加工单/加工项/财务/商品任一族漏 `【不要用于】` ⇒ 红 |
| `test_cheatsheet_is_injected_for_mibao_only` | C 端 prompt 出现该段 ⇒ 红 |
| `test_rendered_text_is_denoised` | 渲染段里出现内部编号 / HTML 注释 ⇒ 红 |
| `test_rendering_is_derived_not_hardcoded` | 写死真实工具名/本体 ⇒ 合成事实下渲染不出合成工具 |

## 边界（判不了什么）

- **不判**「小抄里那把工具业务上真的最合适」—— 那是评测/评审；本文件判的是
  **注册表 ⇄ 小抄的双向一致**与**删掉的手写规则是否被元数据接手**。
- **不判** C 端（元元）的速查表：`prompts/customer_quote.md` / `prompts/customer_knowledge.md`
  的表格本包**有意保留**（C 端提示词逐字节不变，与 #7291 的 persona 门控同口径）。
- 字符数只判**结构面**（手写表已清零 + 小抄块有预算）；总量读数在 PR body 里连命令一起给。
"""

import ast
import re
from pathlib import Path
from unittest.mock import patch

import pytest

from app.graph.skills.base_skill import _PROMPT_CACHE, _build_system_prompt
from app.graph.skills.skill_registry import get_skill_registry
from app.graph.skills import cheatsheet as cs
from app.tools.registry import get_tool_registry

SERVICE_ROOT = Path(__file__).resolve().parents[1]
REFERENCES = SERVICE_ROOT / "app" / "graph" / "skills" / "references"
PROMPTS = REFERENCES / "prompts"
INLINE_PROMPTS = (
    SERVICE_ROOT / "app" / "graph" / "skills" / "general_agent.py",
    SERVICE_ROOT / "app" / "graph" / "skills" / "product_skill.py",
)

#: mibao（黄金策）的 skill 集 —— 只有它们注入小抄（C 端逐字节不变）。
MIBAO_SKILLS = ("order", "product", "aftersales", "customer", "staff", "settings", "data", "general")

#: 小抄块的字符预算（实测最大 `general`；上限取实测 + 余量，超了说明它长成第二份工具手册）。
CHEATSHEET_BUDGET_CHARS = 1600

#: 手写速查表的表头（9 处的共同签名；C 端 `需求/工具` 表不在射程内）。
TABLE_HEADER = "| 场景 | 工具 |"

#: 被删掉的手写「不要用 A 做 B」规则 → 接手它的**工具元数据**（issue #8176 的核心验收）。
DELETED_RULES = (
    {
        "prompt": "product.md",
        "gone": "不要用 product_search",
        "source": "product_search",
        "target": "inventory_manage",
        "skill": "product",        # product 声明面同时有这两把 → 该行必须出现
        "case": "PR-101",
    },
    {
        "prompt": "order.md",
        "gone": "不得**用 `processing_item_query` 冒充",
        "source": "processing_item_query",
        "target": "processing_order_query",
        "skill": "order",
        "case": "OR-029",
    },
    {
        "prompt": "general.md",
        "gone": "**不要**调 processing_item_query",
        "source": "processing_item_query",
        "target": "processing_order_query",
        "skill": "general",
        "case": "OR-029",
    },
    {
        "prompt": "staff.md",
        "gone": "查角色用 role_manage，查员工用 employee_manage",
        "source": "employee_manage",
        "target": "role_manage",
        "skill": "staff",
        "case": "HR-001",
    },
    {
        "prompt": "settings.md",
        "gone": "不要拿 settings_manage 去查通知",
        "source": "settings_manage",
        # 通知工具**不绑本域** ⇒ 点名它会把「域外点名」豁免面撑大（燃尽靶只许缩短，issue #5444）
        # 故元数据写**去向（域）**：本域工具集里根本没有它，写工具名也不可执行。
        "route": "通知中心",
        "skill": "settings",
        "case": "ST-001",
    },
)

#: 被删掉的速查表 → 表里点名过的工具（真值不许随表一起消失）。
DELETED_TABLES = (
    ("order.md", "order", ("order_query", "logistics_track", "product_search", "product_detail",
                           "processing_order_query", "processing_order_set_query",
                           "production_progress_query", "production_worklog_query",
                           "processing_item_query")),
    ("product.md", "product", ("product_search", "product_detail", "product_update", "sku_update",
                               "inventory_manage", "stock_ledger_query", "inbound_order_query",
                               "batch_stock_query", "category_manage", "processing_item_query",
                               "operation_catalog_query", "craft_calc_config_query",
                               "craft_config_query", "product_batch_update")),
    ("data.md", "data", ("dashboard_stats", "briefing_query", "piecework_query", "session_manage",
                         "finance_api")),
    ("customer.md", "customer", ("customer_manage", "order_query")),
    ("staff.md", "staff", ("employee_manage", "role_manage", "piecework_query")),
    ("settings.md", "settings", ("settings_manage",)),
)

#: 逐族补全的元数据覆盖（订单 / 加工单 / 加工项 / 财务 / 商品）。
FAMILY_TOOLS = {
    "订单": ("order_query", "logistics_track", "sales_attribution"),
    "加工单": ("processing_order_query", "processing_order_set_query", "processing_order_update"),
    "加工项": ("processing_item_query", "processing_item_manage"),
    "财务": ("finance_api", "piecework_query", "briefing_query"),
    "商品": ("product_search", "product_detail", "inventory_manage", "category_manage"),
}


# ── 解析与派生（判据一律现算，不抄清单）────────────────────────────────────
def rendered_tool_names(text: str) -> list:
    """从小抄文本里解析出工具条目（**保序**；本体词表行按前缀排除）。"""
    names = []
    for line in (text or "").splitlines():
        if not line.startswith("- ") or line.startswith(cs.OBJECT_LINE_PREFIX):
            continue
        token = line[2:].split(" ")[0].replace("〔写〕", "")
        names.append(token)
    return names


CASES_DIR = SERVICE_ROOT.parents[1] / ".github" / "cases"


def _case_exists(case_id: str) -> bool:
    """用例库里是否存在该 id（删规则的唯一合法依据之一 = 对应负例仍在库）。"""
    needle = f"id: {case_id}"
    return any(needle in path.read_text(encoding="utf-8")
               for path in CASES_DIR.glob("*.yml"))


#: 业务域口径（工具名前缀）：`processing_*` 下**两个不同业务对象**共用同一个前缀 ——
#: 「加工单 ≠ 加工项」是本仓写进 prompt 的业务铁律，故这里按业务对象而不是按首段判定跨域。
_DOMAIN_PREFIXES = (("processing_order", "加工单"), ("processing_item", "加工项"))


def domain_of(tool_name: str) -> str:
    for prefix, domain in _DOMAIN_PREFIXES:
        if tool_name.startswith(prefix):
            return domain
    return tool_name.split("_")[0]


def declared_names(skill: str) -> list:
    cfg = get_skill_registry().get(skill)
    return list(cfg.tool_names or ()) if cfg is not None else []


def _consistency_errors() -> list:
    """每 skill 双向一致：声明面 ∩ 注册表 == 小抄条目（少一把 / 多一把都报，并**具名**）。"""
    registered = set(get_tool_registry().get_tool_names())
    errors = []
    for skill in MIBAO_SKILLS:
        want = [n for n in declared_names(skill) if n in registered]
        got = rendered_tool_names(cs.render_cheatsheet(skill))
        if got != want:
            missing = [n for n in want if n not in got]
            phantom = [n for n in got if n not in want]
            if missing:
                errors.append(f"{skill}: 声明面里有、小抄里没有 {missing}")
            if phantom:
                errors.append(f"{skill}: 小抄写了不存在的工具 {phantom}")
            if not missing and not phantom:
                errors.append(f"{skill}: 顺序与声明面不一致（渲染必须确定）{got} != {want}")
    return errors


# ── ① 小抄 ⇄ 注册表 双向一致 ─────────────────────────────────────────────
def test_cheatsheet_lists_exactly_the_declared_surface():
    """注册表有而小抄没有 ⇒ 红；小抄写了不存在的工具 ⇒ 红（双向，逐 skill）。"""
    errors = _consistency_errors()
    assert errors == [], "小抄与注册表不一致：\n  " + "\n  ".join(errors)


def test_no_phantom_tool_in_cheatsheet():
    """小抄里的**每个**工具名都必须是已注册工具（防杜撰 / 防拼写漂移）。"""
    registered = set(get_tool_registry().get_tool_names())
    bad = []
    for skill in MIBAO_SKILLS:
        for name in rendered_tool_names(cs.render_cheatsheet(skill)):
            if name not in registered:
                bad.append(f"{skill}: `{name}` 不在注册表")
    assert bad == [], "小抄里出现未注册的工具名：\n  " + "\n  ".join(bad)


def test_rendering_skips_are_reported_by_name():
    """**红证**：渲染器静默跳过一把工具 ⇒ 双向一致判据红，并**具名**该工具。"""
    real = cs.iter_rendered_tools
    victim = "order_query"

    def skipping(skill_name, registry=None):
        return [t for t in real(skill_name, registry) if t.name != victim]

    with patch.object(cs, "iter_rendered_tools", side_effect=skipping):
        errors = _consistency_errors()
    named = [e for e in errors if victim in e]
    assert named != [], f"静默跳过 `{victim}` 后判据没红（空断言）：{errors}"


# ── ② 删掉的手写规则 ⇒ 元数据 + 小抄接手 ─────────────────────────────────
def test_deleted_handwritten_rule_is_handed_over_by_metadata():
    """每条被删的「不要用 A 做 B」都必须：prompt 里消失 + 工具元数据里有 + 小抄里看得见。"""
    registry = get_tool_registry()
    bad = []
    for rule in DELETED_RULES:
        text = (PROMPTS / rule["prompt"]).read_text(encoding="utf-8")
        if rule["gone"] in text:
            bad.append(f"{rule['prompt']}: 被删的手写规则又回来了（真值重新分两份）：{rule['gone']}")
        source = registry.get_tool(rule["source"])
        if source is None:
            bad.append(f"{rule['source']}: 工具不存在（跳转目标无从承接）")
            continue
        route = rule.get("route")
        if route:
            if route not in source.not_for:
                bad.append(f"{rule['source']}: `【不要用于】` 没写去向「{route}」（手写规则的真值没落进元数据）")
        else:
            targets = [target for _label, target in cs.not_for_entries(source.not_for)]
            if rule["target"] not in targets:
                bad.append(f"{rule['source']}: `【不要用于】` 没点名 `{rule['target']}`（手写规则的真值没落进元数据）")
            line = next((ln for ln in cs.render_cheatsheet(rule["skill"]).splitlines()
                         if ln.replace("〔写〕", "").startswith(f"- {rule['source']} ")), "")
            if rule["target"] not in line:
                bad.append(f"{rule['skill']}: 小抄行没带出 `{rule['source']} → {rule['target']}`（生成物没接手）")
        if not _case_exists(rule["case"]):
            bad.append(f"{rule['case']}: 该族的负例不在用例库里（删了规则却没有负例兜着）")
    assert bad == [], "手写规则删了但真值没接手：\n  " + "\n  ".join(bad)


def test_deleted_table_tools_are_all_still_rendered():
    """删表不许丢真值：表里点名过的工具必须仍能从注册表渲染出来。"""
    bad = []
    for filename, skill, tools in DELETED_TABLES:
        text = (PROMPTS / filename).read_text(encoding="utf-8")
        if TABLE_HEADER in text:
            bad.append(f"{filename}: 手写速查表还在（应已换成生成式小抄）")
        rendered = set(rendered_tool_names(cs.render_cheatsheet(skill)))
        for tool in tools:
            if tool not in rendered:
                bad.append(f"{skill}: 表里点名过的 `{tool}` 没被渲染（真值随表消失）")
    assert bad == [], "删表后真值丢失：\n  " + "\n  ".join(bad)


def test_handwritten_tables_are_gone_from_prompts():
    """9 处手写速查表全部清零（`prompts/*.md` 与两处内联 prompt）。"""
    leftovers = []
    for path in sorted(PROMPTS.glob("*.md")):
        if TABLE_HEADER in path.read_text(encoding="utf-8"):
            leftovers.append(path.name)
    for path in INLINE_PROMPTS:
        if TABLE_HEADER in path.read_text(encoding="utf-8"):
            leftovers.append(path.name)
    assert leftovers == [], f"仍有手写速查表（应改由小抄渲染）：{leftovers}"


# ── ③ 字符数：小抄块预算（结构面）─────────────────────────────────────────
def test_cheatsheet_block_stays_within_budget():
    """小抄是**索引**不是第二份工具手册：每 skill ≤ `CHEATSHEET_BUDGET_CHARS`。"""
    over = {}
    for skill in MIBAO_SKILLS:
        size = len(cs.render_cheatsheet(skill))
        if size > CHEATSHEET_BUDGET_CHARS:
            over[skill] = size
    assert over == {}, (
        f"小抄块超预算（上限 {CHEATSHEET_BUDGET_CHARS} 字符）：{over} —— "
        f"精简触发词 / 跳转目标，别把 description 抄进来")


# ── ④ 红证已在 ②；⑤ 渲染确定性 ───────────────────────────────────────────
def test_rendering_is_byte_stable():
    """同一输入两次渲染**逐字节相同**（确定性是 `--check` 的前提）。"""
    unstable = []
    for skill in MIBAO_SKILLS:
        first = cs.render_cheatsheet(skill)
        if cs.render_cheatsheet(skill) != first:
            unstable.append(skill)
    assert unstable == [], f"渲染不确定：{unstable}"


def test_check_command_reports_determinism():
    """`python -m app.graph.skills.cheatsheet --check` 的真实读数必须是 `0`（通过）。"""
    assert cs.check_deterministic() == 0


def test_check_detects_a_drifting_renderer():
    """**红证**：让渲染结果漂移 ⇒ `--check` 必须判红（`1`）。"""
    calls = {"n": 0}

    def drifting(skill_name, **_kwargs):
        calls["n"] += 1
        return f"salt-{calls['n']}"

    with patch.object(cs, "render_cheatsheet", side_effect=drifting):
        assert cs.check_deterministic() == 1


def test_check_is_fail_closed_when_nothing_renders():
    """**红证**：一把工具都渲染不出来 ⇒ `--check` 判 `3`（不可判定），**不得当 0 读**。"""
    with patch.object(cs, "render_cheatsheet", return_value=""):
        assert cs.check_deterministic() == 3


# ── ⑥ 扫描面非空自证 ──────────────────────────────────────────────────────
def test_every_mibao_skill_renders_a_non_empty_scan_surface():
    """渲染出 0 把工具 ⇒ 红（不许「没渲染所以没不一致」）。"""
    empty = []
    total = 0
    for skill in MIBAO_SKILLS:
        names = rendered_tool_names(cs.render_cheatsheet(skill))
        total += len(names)
        if not names:
            empty.append(skill)
    assert empty == [], f"以下 skill 的小抄里一把工具都没有（判据会空跑）：{empty}"
    assert total >= len(MIBAO_SKILLS) * 2, f"扫描面太小（共 {total} 条），疑似渲染退化"


def test_empty_registry_renders_nothing_instead_of_an_empty_shell():
    """**fail-closed**：无可渲染工具 ⇒ 返回空串（不产出「空壳段」冒充已渲染）。"""
    class _EmptyRegistry:
        def get_all_tools(self):
            return []

    assert cs.render_cheatsheet("order", registry=_EmptyRegistry()) == ""


# ── 元数据：triggers / not_for 的覆盖面与投影性质 ─────────────────────────
def test_metadata_fields_are_projections_not_copies():
    """`triggers` / `not_for` 必须**就是** `description` 的段（改描述即改元数据）。"""
    class _Tool:
        description = "【触发】商家说「查订单」时调用。【不要用于】会话列表（用 session_manage）"
        read_only = True
        name = "zzz_probe"

    from app.tools.base import BaseTool

    probe = _Tool()
    projected = BaseTool.not_for.fget(probe)
    assert projected == cs.segment(_Tool.description, "【不要用于】")
    triggers = BaseTool.triggers.fget(probe)
    assert triggers == ["查订单"], f"触发词不是从 description 投影出来的：{triggers}"


def test_table_tools_declare_triggers_and_not_for_per_family():
    """五族逐族补全：每把工具都要有触发词与「不要用于」，且跳转目标**可达、非自指、跨域**。"""
    registry = get_tool_registry()
    registered = set(registry.get_tool_names())
    bad = []
    checked = 0
    for family, tools in FAMILY_TOOLS.items():
        for name in tools:
            tool = registry.get_tool(name)
            if tool is None:
                bad.append(f"{family}: `{name}` 不在注册表")
                continue
            checked += 1
            triggers = cs.quoted_phrases(cs.segment(tool.description, "【触发】"))
            if not triggers:
                bad.append(f"{family}/{name}: 没有触发词（商家这么说时模型没有锚点）")
            line = cs.segment(tool.description, "【不要用于】")
            if not line:
                bad.append(f"{family}/{name}: 没有 `【不要用于】` 段")
                continue
            if len(line) > 120:
                bad.append(f"{family}/{name}: `【不要用于】` 行 {len(line)} 字 > 120")
            entries = cs.not_for_entries(line)
            if not entries:
                bad.append(f"{family}/{name}: `【不要用于】` 解析不出任何跳转目标")
            targets = [target for _label, target in entries]
            if name in targets:
                bad.append(f"{family}/{name}: 把自己列为跳转目标")
            unknown = [t for t in targets if t not in registered]
            if unknown:
                bad.append(f"{family}/{name}: 跳转目标不在注册表 {unknown}")
            if not [t for t in targets if domain_of(t) != domain_of(name)]:
                bad.append(f"{family}/{name}: 跳转目标全是同域（等于没跳）{targets}")
    assert checked == sum(len(v) for v in FAMILY_TOOLS.values()), f"覆盖数不符：{checked}"
    assert bad == [], "逐族元数据不达标：\n  " + "\n  ".join(bad)


# ── 注入面：只给 mibao / 不污染 / 不写内部编号 ──────────────────────────────
@pytest.fixture(autouse=True)
def _clear_cache():
    _PROMPT_CACHE.clear()
    yield
    _PROMPT_CACHE.clear()


def test_cheatsheet_is_injected_for_mibao_only():
    """B 端每个 skill 的组装 prompt 都要有小抄；C 端（元元）**逐字节**不含该段。"""
    missing = [s for s in MIBAO_SKILLS if cs.MARKER not in _build_system_prompt(s)]
    assert missing == [], f"{missing} 的 system prompt 里没有【选工具小抄】"
    leaking = [cfg.name for cfg in get_skill_registry().get_all()
               if "xiaobu" in (cfg.system_prompts or {})
               and cs.MARKER in _build_system_prompt(cfg.name)]
    assert leaking == [], f"C 端 prompt 出现了小抄段（persona 边界被打破）：{leaking}"


ISSUE_REF = re.compile(r"#\d{4,}")


def test_rendered_text_is_denoised():
    """小抄会原样进 system prompt ⇒ 不得带内部编号 / HTML 注释（与去噪判据同口径）。"""
    bad = []
    for skill in MIBAO_SKILLS:
        text = cs.render_cheatsheet(skill)
        if "<!--" in text:
            bad.append(f"{skill}: 含 HTML 注释")
        for ref in ISSUE_REF.findall(text):
            bad.append(f"{skill}: 含内部编号 {ref}")
    assert bad == [], "小抄里混入不该给模型看的东西：\n  " + "\n  ".join(bad)


# ── derive 而非写死（合成事实自证）───────────────────────────────────────
def test_rendering_is_derived_not_hardcoded():
    """换成**合成**注册表/声明面/本体：小抄必须跟着变（写死真实工具名必红）。"""
    class _SyntheticTool:
        name = "zzz_manage"
        read_only = False
        description = "【触发】商家说「合成说法」时调用。【不要用于】合成反例（用 zzz_query）"

        @property
        def not_for(self) -> str:
            # 投影**只许有一处实现**：真工具走 `BaseTool.not_for`（同一份字节），合成工具照同一条口径投影。
            from app.tools.base import segment

            return segment(self.description, "【不要用于】")

    class _SyntheticRegistry:
        def get_all_tools(self):
            return [_SyntheticTool()]

    class _SyntheticOntology:
        objects = {}

    with patch.object(cs, "_declared", return_value=["zzz_manage"]):
        text = cs.render_cheatsheet("zzz_skill", registry=_SyntheticRegistry(),
                                    ontology=_SyntheticOntology())
    assert "zzz_manage" in text, f"合成注册表下没渲染出合成工具（写死了真实工具名）：{text}"
    assert "合成说法" in text and "zzz_query" in text, f"触发词/跳转目标没从元数据投影：{text}"


# ── 边界：渲染器只进 system prompt（不在用户可见路径）────────────────────────
def test_cheatsheet_renderer_is_only_referenced_by_base_skill():
    """`render_cheatsheet` 在 `app/**` 里只被 `base_skill` 引用（只进 system prompt）。

    `references/base/principles.md` 禁止**回复**里出现工具名；小抄是给模型看的地图，
    不是给商家说的文本。谁把它拿去拼用户可见话术，本判据当场红。
    """
    app_dir = SERVICE_ROOT / "app"
    callers = set()
    for path in sorted(app_dir.rglob("*.py")):
        if path.name == "cheatsheet.py":     # 渲染器自身（定义 + --check 的内部调用）
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == "render_cheatsheet":
                callers.add(path.name)
            elif isinstance(node, ast.Attribute) and node.attr == "render_cheatsheet":
                callers.add(path.name)
    assert callers == {"base_skill.py"}, (
        f"渲染器被 {sorted(callers)} 引用（只允许 base_skill.py，即只进 system prompt）")


def test_renderer_boundary_guard_has_red_power(tmp_path):
    """**红证**：把引用塞进替身目录 ⇒ 边界判据必报（否则上一条是永远绿的空判据）。"""
    (tmp_path / "follow_up.py").write_text(
        "from app.graph.skills.cheatsheet import render_cheatsheet\n"
        "\n"
        "def user_visible_hint():\n"
        "    return render_cheatsheet('order')\n",
        encoding="utf-8")
    hits = set()
    for path in sorted(tmp_path.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == "render_cheatsheet":
                hits.add(path.name)
    assert hits == {"follow_up.py"}, "植入「用户可见路径也调用渲染器」后判据仍不报 —— 空判据"
