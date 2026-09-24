# case_ids: DA-017
"""**声明点的「未登记即红」元守卫**（issue #5389）。

## 病根（一类缺陷，不是一个缺陷）

主动发现的每条规则要**逐条人工登记**两处声明：`judgeable_fields`（行级可判定性 = 「没数据
≠ 没问题」的**行级**版本）与 `enabled_by`（租户级前置 = 「系统有、你没开」）。**漏登记不会有
东西变红** —— 表现是该规则**静默落 `wired`**：

- 行级：某行成本价为空（拿不到值）却照旧按「没命中 = 没问题」读；
- 租户级：租户没开成本核算，规则却报 `wired`（空命中被读成「今天没问题」）。

「**声明了 ≠ 声明全了**」，而「没声明全」在旧口径下**不可见**（issue #5389 的原话：
这是**判断力缺口**，不是能机械兜住的接线缺口）。

## 本元守卫钉的形态（形态学 = `test_guard_parsing_is_comment_aware.py`）

| # | 判据 | 语义 |
|---|---|---|
| 1 | 装配层声明 ≡ 登记册 `row_fields`（**逐字相等**） | 新增一个行字段而没登记 ⇒ 红 |
| 2 | 规则 `requires` 的字段必须**被装配层产出**（或该数组登记在 `unwired_arrays`） | 读一个装配层不产出的字段 = 死绑定 ⇒ 红 |
| 3 | `nullable` 字段被某规则 requires ⇒ 该规则**必须**登记 `judgeable_fields` | **本单的强判据**（漏登记 ⇒ 红） |
| 4 | `judgeable_fields ⊆ requires[1]`、`dimensions ⊆ requires[1]` | 打字错 ⇒ 红（廉价判据那一半） |
| 5 | 装配层下发的事实 ≡ 登记册 `tenant_facts`（逐字相等）；`enabled_by[0]` 必须在册且真下发 | 指向一个装配层根本不发的事实 ⇒ 红 |
| 6 | `tenant_facts[*].gates` 的字段被某规则 requires ⇒ 该规则必须声明 `enabled_by` | 租户级前置漏登记 ⇒ 红 |
| 7 | 条目必须带 `reason` + `issue`；两个豁免台账**今天为空**、只许缩短 | §23 G2 燃尽靶子 |
| 8 | 反空跑读数（规则数 / 行字段数 / 事实数 / nullable 数 / gated 数） | 「扫不到」不许长得像「通过」 |

**输入同刻**（§23 G4）：Python 侧（`proactive.py`）与 Java 侧（`DailyBriefingService.java`）
的源码都在**同一次读数**里取，判据里没有一半快照一半实时。

## 红证（逐条，见文件尾 `TestRedProofs`；注入先自证 `mutated != src`）

① 删掉规则的 `judgeable_fields=("cost_amount",)` ⇒ 必红（**漏登记**的真形态）；
② 往装配层加一个行字段（未登记）⇒ 必红；③ 往装配层加一个租户事实（未登记）⇒ 必红；
④ 把 `enabled_by` 指向不存在的事实 ⇒ 必红；⑤ 删掉规则的 `enabled_by` ⇒ 必红（gated 字段）；
⑥ 把某字段标成 nullable 而消费规则未登记 ⇒ 必红（判据 3 的判别力）；
⑦ 抹掉一条 reason ⇒ 必红。

## 真实现场读数（上线当天就抓到一次，不是只有合成注入）

本判据合入后第一次 rebase（把 `#5369`「族 3 包 2 · 具名视图 product_health」并进来）即**当场判红**：
装配层新增了 `skus.sales_count` / `skus.price` / `skus.avg_cost` 与 `product_return_stats.{product_id,
return_tickets, order_lines}` 六个行字段（**未登记**）⇒ 「未登记即红」按设计生效（逐条补登记，
`nullable` 逐一裁定，其中 `skus.avg_cost` 依装配层注释「原样透出 null…不得被 0 冒充成本为零」判**可空**）。
同一次 rebase 还暴露了本判据初版的一处**假红**：`snapshot.put("product_return_stats", …)` 是**行数组**
（在 `SNAPSHOT_ROW_FIELDS` 里），初版把它读成了「租户事实」⇒ 判据口径已修（事实 = 结构键与行数组之外的那些键，
行数组由 `SNAPSHOT_ROW_FIELDS` 现取，不写死清单）。

## 未固化 / 边界（照实登记，别把「登记了」读成「治住了」）

- **`nullable` 是显式裁定，不是从代码派生**：本守卫机械保证「**每新增/改动一个字段都必须显式
  裁定可空性 + 写理由**（未登记即红）」，**不保证裁定正确** —— 除 `orders.cost_amount`（#5348
  已取证）外，其余字段的「不可空」是人工裁定 + 「未逐列核对 DB 约束」如实写法。
  从装配层 builder / DB 约束**派生**可空性 = 下一步（owner = 简报装配层 owner，见 PR body 残余）。
- **`enabled_by` 那一半只做到「登记了才受管」的一半**：判据 6 靠**人**在 `tenant_facts[*].gates`
  里声明「这个事实 gate 了哪些字段」—— 那个映射本身仍是判断（#5389 正文已承认：
  「哪条规则该有租户前置」部分需要人判断）。**未固化项**：没有东西会拦住「新增一条依赖
  租户能力的规则，而没人往 gates 里加字段」。
- 面 = `app/briefing/proactive.py` 的 `RuleSpec` + Java 装配层的一处快照构造。**其它**域
  （其它服务的装配/声明点）不在面内。
- 本文件**不改任何门禁的通过条件、不新增豁免**（除两个今天为空的台账，且只许缩短）。

判据 = 本文件；一键复算：
`python3 -m pytest tests/unit_ci_workflows/test_proactive_declarations_are_registered.py -q -s`
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# append（**不是** insert）：只作脚本模式的兜底解析路径，避免遮蔽同名模块（与 conftest 同款理由）。
sys.path.append(str(REPO_ROOT / "tests"))

from unit_ci_workflows._source_parsing import (  # noqa: E402  （#5323 收敛：Java 取值唯一实现）
    java_code,
    java_literals,
)

ENGINE = (REPO_ROOT / "backend" / "ai-agent-service" / "app" / "briefing" / "proactive.py")
ASSEMBLY = (REPO_ROOT / "backend" / "admin-api" / "src" / "main" / "java" / "com" / "migao"
            / "admin" / "service" / "DailyBriefingService.java")
REGISTRY_PATH = Path(__file__).resolve().parent / "proactive_declaration_registry.json"

#: 快照里**结构性**的键（不是「租户级事实」，不被 `enabled_by` 消费）—— 唯一一份排除口径。
#: 行数组（如 `orders` / `skus` / `product_return_stats`）不在这里写死：它们由
#: `SNAPSHOT_ROW_FIELDS` **现取**（新增数组不必回来改这份清单）。
STRUCTURAL_KEYS = frozenset({"metrics", "facts", "row_fields", "row_meta",
                             "orders", "skus", "returns"})


def engine_source() -> str:
    if not ENGINE.is_file():
        raise AssertionError(f"引擎源码不存在：{ENGINE}（fail-closed，不静默跳过）")
    return ENGINE.read_text(encoding="utf8")


def assembly_source() -> str:
    if not ASSEMBLY.is_file():
        raise AssertionError(f"装配层源码不存在：{ASSEMBLY}（fail-closed，不静默跳过）")
    return ASSEMBLY.read_text(encoding="utf8")


# ══════════════════════════════════════════════════════════════════════════════
# 一、两侧声明点的现取读数（纯函数：文本 → 声明；注入式红证 = 换文本重算）
# ══════════════════════════════════════════════════════════════════════════════


def parse_rules(source: str) -> dict[str, dict]:
    """`规则 id → {requires:[数组, 字段…], judgeable_fields, enabled_by, dimensions}`。"""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise AssertionError(f"引擎源码无法解析（{exc}）⇒ 判据失配 ⇒ 红") from exc
    out: dict[str, dict] = {}
    for node in ast.walk(tree):
        # `RULES: Tuple[RuleSpec, ...] = (...)` 是 AnnAssign（不是 Assign）—— 只认 Assign 会
        # 直接空跑（实测踩到：解析出 0 条规则 ⇒ fail-closed 报错，但那已是"判据失配"）
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign):
            target, value = node.target, node.value
        else:
            continue
        if getattr(target, "id", None) != "RULES" or not isinstance(value, ast.Tuple):
            continue
        for element in value.elts:
            kwargs = {kw.arg: kw.value for kw in element.keywords}

            def value(name, default=None):
                if name not in kwargs:
                    return default
                try:
                    return ast.literal_eval(kwargs[name])
                except (ValueError, SyntaxError):
                    return default

            rule_id = value("rule_id")
            requires = value("requires") or ("", ())
            out[str(rule_id)] = {
                "array": str(requires[0]),
                "fields": list(requires[1]),
                "judgeable_fields": list(value("judgeable_fields") or ()),
                "enabled_by": value("enabled_by"),
                "dimensions": list(value("dimensions") or ()),
            }
    if not out:
        raise AssertionError("解析不出任何 RULES ⇒ 判据会空跑（fail-closed）")
    return out


def parse_assembly(source: str) -> tuple[dict[str, list[str]], set[str]]:
    """装配层现取读数：`{行数组: [字段…]}` + 下发的**租户级事实**键集。

    **取值靠词法、不靠「按引号扫原文」的正则**（`#5323` 收敛）：字面量由
    `_source_parsing.java_literals` 按**位置**交付（注释里的字面量不算），
    前缀判定用 `原文[:位置].rstrip()`（共享模块 docstring 给出的同款用法），
    并**用注释已抹除的 `java_code` 视角做计数对账**（见末尾 fail-closed 段）。

    ⚠️ 本函数初版是引号定界的正则（`fields\.put\("(\w+)"`）—— 上线当天被类级元守卫
    `test_guard_parsing_is_comment_aware.py` 判红挡下（issue #5338 的机制**当场生效**）。
    这次是**改实现**，不是往台账里加豁免。
    """
    code = java_code(source)                     # 唯一一份 Java 剥注释实现（引号感知）
    literals = java_literals(source)             # ((起点, 值), …) —— 注释里的不算
    row_fields: dict[str, list[str]] = {}
    puts: list[str] = []
    for idx, (start, value) in enumerate(literals):
        if source[:start].rstrip().endswith("snapshot.put("):
            puts.append(value)
        if not source[:start].rstrip().endswith("fields.put("):
            continue
        names: list[str] = []
        prev_end = start + len(value) + 2        # 跳过两侧引号
        for pos, later in literals[idx + 1:]:
            if ")" in source[prev_end:pos]:      # `List.of(…)` 收尾 ⇒ 字段名到头
                break
            names.append(later)
            prev_end = pos + len(later) + 2
        row_fields[value] = names
    # fail-closed：注释里写一句同形的 `fields.put("x", List.of("y"))` 会让上面多认出一个数组 ⇒
    # 与「注释已抹除」的视角**计数不等** ⇒ 当场红（而不是把注释里的东西静默读成声明）。
    if code.count("fields.put(") != len(row_fields):
        raise AssertionError(
            f"行字段解析对账失败：注释外 `fields.put(` 出现 {code.count('fields.put(')} 次，"
            f"而按字面量位置解析出 {len(row_fields)} 个数组 ⇒ 原文口径已不可信（fail-closed）")
    if code.count("snapshot.put(") != len(puts):
        raise AssertionError(
            f"租户事实解析对账失败：注释外 `snapshot.put(` 出现 {code.count('snapshot.put(')} 次，"
            f"而按字面量位置解析出 {len(puts)} 处 ⇒ 原文口径已不可信（fail-closed）")
    # 🔴 「租户事实」= `snapshot.put(<key>, …)` 里**既不是结构键、也不是已声明的行数组**的那些键。
    # 少了 `- set(row_fields)` 这一项，`product_return_stats`（#5369 新增的**行数组**）会被读成
    # 租户事实 ⇒ 假红（实测：本判据上线后第一次 rebase 就撞上）。
    facts = {value for value in puts
             if value not in STRUCTURAL_KEYS and value not in row_fields}
    if len(row_fields) < 3:
        raise AssertionError(f"装配层只解析出 {len(row_fields)} 个行数组 ⇒ 判据会空跑（fail-closed）")
    if not facts:
        raise AssertionError("装配层解析出 0 个租户级事实 ⇒ 判据会空跑（fail-closed）")
    return row_fields, facts


def load_registry(path: Path | None = None) -> dict:
    where = path or REGISTRY_PATH
    raw = json.loads(where.read_text(encoding="utf8"))
    for section in ("row_fields", "unwired_arrays", "tenant_facts",
                    "judgeable_exemptions", "enabled_by_exemptions"):
        if not isinstance(raw.get(section), (dict, list)):
            raise AssertionError(f"登记册缺 {section} 段（结构损坏）：{where}")
    return raw


def live_fields(row_fields: dict[str, list[str]]) -> set[str]:
    return {f"{array}.{name}" for array, names in row_fields.items() for name in names}


# ══════════════════════════════════════════════════════════════════════════════
# 二、判据（纯函数：输入两侧文本 + 登记册，输出问题清单 —— 空 = 绿）
# ══════════════════════════════════════════════════════════════════════════════


def problems_field_registry(registry: dict, row_fields: dict[str, list[str]]) -> list[str]:
    """① 装配层声明 ≡ 登记册（逐字相等）；② requires 的字段必须被产出或数组已登记未接线。"""
    out: list[str] = []
    live = live_fields(row_fields)
    known = set(registry["row_fields"])
    for field in sorted(live - known):
        out.append(f"装配层新声明了行字段 `{field}`，但**未登记** ⇒ 在 row_fields 里补一格"
                   f"（nullable 裁定 + reason + issue）—— 未登记即红")
    for field in sorted(known - live):
        out.append(f"登记册里的 `{field}` 在装配层**已不存在** ⇒ 陈旧条目必须销账")
    rules = parse_rules(engine_source())
    unwired = set(registry["unwired_arrays"])
    for rule_id, spec in sorted(rules.items()):
        if spec["array"] in unwired:
            continue
        for field in spec["fields"]:
            key = f"{spec['array']}.{field}"
            if key not in live:
                out.append(f"规则 `{rule_id}` 的 requires 读了 `{key}`，但装配层**不产出**它 "
                           f"（也不是登记在册的未接线数组）⇒ 死绑定")
    return out


def problems_judgeable(registry: dict, source: str) -> list[str]:
    """③ nullable 字段被 requires ⇒ 必须登记 judgeable_fields（漏登记 ⇒ 红）；④ 打字错 ⇒ 红。"""
    out: list[str] = []
    rules = parse_rules(source)
    exempt = registry["judgeable_exemptions"]
    for rule_id, spec in sorted(rules.items()):
        for key in (spec["judgeable_fields"] + spec["dimensions"]):
            if key not in spec["fields"]:
                out.append(f"规则 `{rule_id}` 登记了 `{key}`，但它**不在 requires 的字段里** "
                           f"⇒ 打字错/口径漂移（requires={spec['fields']}）")
        for field in spec["fields"]:
            entry = registry["row_fields"].get(f"{spec['array']}.{field}") or {}
            if not entry.get("nullable"):
                continue
            if field in spec["judgeable_fields"] or f"{rule_id}:{field}" in exempt:
                continue
            out.append(f"规则 `{rule_id}` 读了**可空**字段 `{field}`，却没登记 `judgeable_fields` "
                       f"⇒ 该字段为空的行会被读成「没命中 = 没问题」（漏登记即红）")
    return out


def problems_tenant_facts(registry: dict, source: str, facts: set[str], facts_java: set[str]) -> list[str]:
    """⑤ 事实登记册 ≡ 装配层；⑥ gated 字段的规则必须声明 enabled_by。"""
    out: list[str] = []
    known = set(registry["tenant_facts"])
    for fact in sorted(facts_java - known):
        out.append(f"装配层新下发了租户事实 `{fact}`，但**未登记** ⇒ 在 tenant_facts 里补一格"
                   f"（gates 声明 + reason + issue）—— 未登记即红")
    for fact in sorted(known - facts_java):
        out.append(f"登记册里的租户事实 `{fact}` 装配层**已不下发** ⇒ 陈旧条目必须销账")
    rules = parse_rules(source)
    exempt = registry["enabled_by_exemptions"]
    for rule_id, spec in sorted(rules.items()):
        if not spec["enabled_by"]:
            continue
        fact = str(spec["enabled_by"][0])
        if fact not in known:
            out.append(f"规则 `{rule_id}` 的 enabled_by 指向 `{fact}`，但它**不在登记册**里 "
                       f"⇒ 指向一个没人担保存在的事实（静默落 wired）")
        elif fact not in facts_java:
            out.append(f"规则 `{rule_id}` 的 enabled_by 指向 `{fact}`，但装配层**不下发**这个键 "
                       f"⇒ 该规则在未开启租户上静默落 wired")
    for fact, entry in sorted(registry["tenant_facts"].items()):
        for gated in entry.get("gates") or []:
            for rule_id, spec in sorted(rules.items()):
                if gated not in [f"{spec['array']}.{f}" for f in spec["fields"]]:
                    continue
                if spec["enabled_by"] and str(spec["enabled_by"][0]) == fact:
                    continue
                if f"{rule_id}:{fact}" in exempt:
                    continue
                out.append(f"规则 `{rule_id}` 读了被 `{fact}` gate 的 `{gated}`，却没声明 "
                           f"`enabled_by` ⇒ 未开启的租户上会静默落 wired（漏登记即红）")
    return out


def problems_ledger_shape(registry: dict) -> list[str]:
    """⑦ 条目带 reason + issue；豁免台账只许为空（缩短）。"""
    out: list[str] = []
    for section in ("row_fields", "unwired_arrays", "tenant_facts"):
        for key, entry in sorted(registry[section].items()):
            if not isinstance(entry, dict):
                out.append(f"`{section}.{key}` 不是对象 ⇒ 登记条目必须自描述")
                continue
            for field in ("reason", "issue"):
                if not str(entry.get(field) or "").strip():
                    out.append(f"`{section}.{key}` 缺 `{field}`（没有理由/单号的登记等于没人看）")
    for section in ("judgeable_exemptions", "enabled_by_exemptions"):
        for key, reason in sorted(registry[section].items()):
            if not str(reason).strip() or "#" not in str(reason):
                out.append(f"豁免条目 `{section}.{key}` 的理由={reason!r} 不合格 ⇒ "
                           "必须写「为什么可以豁免 + 单号（#NNNN）」")
    return out


def problems_exemptions_are_empty(registry: dict) -> list[str]:
    """燃尽靶子：两个豁免台账**今天必须为空**（只许缩短；加到非空必须在 diff 里看得见）。"""
    out: list[str] = []
    for section in ("judgeable_exemptions", "enabled_by_exemptions"):
        if registry[section]:
            out.append(f"豁免台账 `{section}` 非空（{len(registry[section])} 条）⇒ "
                       "要么修掉对应缺口，要么在本 PR 的 diff 里显式说明为何必须豁免")
    return out


def mechanism_reading(registry: dict, row_fields: dict[str, list[str]], facts: set[str]) -> str:
    rules = parse_rules(engine_source())
    nullable = sum(1 for e in registry["row_fields"].values() if e.get("nullable"))
    gated = sum(len(e.get("gates") or []) for e in registry["tenant_facts"].values())
    return (f"读数：规则 {len(rules)} 条 / 装配层行字段 {len(live_fields(row_fields))} 个"
            f"（{len(row_fields)} 个数组）/ 租户事实 {len(facts)} 个 / nullable 登记 {nullable} 个 / "
            f"gated 字段 {gated} 个 / 豁免 {len(registry['judgeable_exemptions'])} + "
            f"{len(registry['enabled_by_exemptions'])} 条")


# ══════════════════════════════════════════════════════════════════════════════
# 三、判据（真语料）
# ══════════════════════════════════════════════════════════════════════════════


def test_assembly_row_fields_are_registered():
    registry, row_fields, _ = load_registry(), *parse_assembly(assembly_source())
    problems = problems_field_registry(registry, row_fields)
    if problems:
        raise AssertionError("行字段声明与登记册不一致：\n  - " + "\n  - ".join(problems))


def test_nullable_fields_are_judgeable():
    """**本单的强判据**：读了可空字段却没登记 judgeable_fields ⇒ 红（#5389 判据 1）。"""
    problems = problems_judgeable(load_registry(), engine_source())
    if problems:
        raise AssertionError("judgeable_fields 漏登记：\n  - " + "\n  - ".join(problems))


def test_tenant_facts_are_registered_and_gated():
    registry = load_registry()
    _, facts = parse_assembly(assembly_source())
    problems = problems_tenant_facts(registry, engine_source(), facts, facts)
    if problems:
        raise AssertionError("租户事实/enabled_by 声明不一致：\n  - " + "\n  - ".join(problems))


def test_ledger_entries_carry_reason_and_issue():
    problems = problems_ledger_shape(load_registry())
    if problems:
        raise AssertionError("登记条目形态不合格：\n  - " + "\n  - ".join(problems))


def test_exemption_ledgers_are_empty():
    registry = load_registry()
    print(mechanism_reading(registry, *parse_assembly(assembly_source())[:1],
                            parse_assembly(assembly_source())[1]))
    problems = problems_exemptions_are_empty(registry)
    if problems:
        raise AssertionError("\n  - ".join(problems))


def test_mechanism_is_not_vacuous():
    """反空跑：规则 / 行字段 / 事实 / nullable / gated 都必须有正读数（判据不靠「扫不到」通过）。"""
    registry = load_registry()
    row_fields, facts = parse_assembly(assembly_source())
    reading = mechanism_reading(registry, row_fields, facts)
    print(reading)
    rules = parse_rules(engine_source())
    nullable = [k for k, e in registry["row_fields"].items() if e.get("nullable")]
    gated = [g for e in registry["tenant_facts"].values() for g in (e.get("gates") or [])]
    if len(rules) < 3 or len(live_fields(row_fields)) < 10 or len(facts) < 1:
        raise AssertionError(f"{reading} ⇒ 读数过小，判据会空跑（fail-closed）")
    if not nullable or not gated:
        raise AssertionError(f"{reading} ⇒ 没有可空/gated 字段 ⇒ 判据 3/6 无从判别（是空判据）")


# ══════════════════════════════════════════════════════════════════════════════
# 四、注入式红证（§23 G7：注入先自证生效，再要求判据变红）
# ══════════════════════════════════════════════════════════════════════════════


def _mutate(text: str, old: str, new: str, where: str) -> str:
    if old not in text:
        raise AssertionError(f"注入锚点未命中（注入未生效 ⇒ 该红证是空断言）：{where} 里找不到 {old!r}")
    mutated = text.replace(old, new, 1)
    if mutated == text:
        raise AssertionError(f"注入未生效（mutated == src）：{where}")
    return mutated


def _drop_block(text: str, marker: str) -> str:
    """删掉 `marker` 所在的那**一整条**表达式（多行调用 ⇒ 删到以 `),` 收尾的那一行为止）。

    为什么不用「注释掉首行」：多行实参被注释掉一半会留下**悬空续行** ⇒ 源码语法错、
    判据当场报「无法解析」（实测踩到）—— 那证的不是判别力，是自己的注入写坏了。
    """
    lines = text.splitlines(keepends=True)
    start = next((i for i, line in enumerate(lines) if marker in line), None)
    if start is None:
        raise AssertionError(f"注入锚点未命中（注入未生效 ⇒ 该红证是空断言）：找不到 {marker!r}")
    end = start
    while end < len(lines) and not lines[end].rstrip().endswith("),"):
        end += 1
    if end >= len(lines):
        raise AssertionError(f"注入锚点 {marker!r} 之后找不到表达式收尾（`),`）⇒ 注入未生效")
    mutated = "".join(lines[:start] + lines[end + 1:])
    if mutated == text:
        raise AssertionError(f"注入未生效（mutated == src）：{marker!r}")
    return mutated


def _registry(**overrides) -> dict:
    reg = load_registry()
    for key, value in overrides.items():
        if key not in ("row_fields", "tenant_facts", "judgeable_exemptions",
                       "enabled_by_exemptions", "unwired_arrays"):
            raise AssertionError(f"未知覆盖字段 {key}")
        reg[key] = value
    return reg


def _copy(section: dict) -> dict:
    return {k: (dict(v) if isinstance(v, dict) else v) for k, v in section.items()}


class TestRedProofs:
    """每条判据的判别力：注入 ⇒ 对应的问题清单**必须**非空（不是"一起红"）。"""

    def test_dropping_judgeable_registration_is_red(self):
        """**漏登记**的真形态：删掉规则的 judgeable_fields ⇒ 判据 3 必须红。"""
        mutated = _mutate(engine_source(), 'judgeable_fields=("cost_amount",),', "", "proactive.py")
        if "judgeable_fields" in parse_rules(mutated)["below_cost_price"]["judgeable_fields"]:
            raise AssertionError("注入未生效：judgeable_fields 仍在")
        problems = problems_judgeable(load_registry(), mutated)
        if not any("below_cost_price" in p and "cost_amount" in p for p in problems):
            raise AssertionError(f"漏登记 judgeable_fields 后判据未变红 ⇒ 空断言：{problems}")

    def test_new_assembly_field_unregistered_is_red(self):
        mutated = _mutate(assembly_source(), '"sale_amount", "cost_amount"));',
                          '"sale_amount", "cost_amount", "discount_amount"));',
                          "DailyBriefingService")
        row_fields, _ = parse_assembly(mutated)
        if "orders.discount_amount" not in live_fields(row_fields):
            raise AssertionError("注入未生效：新字段没被解析出来")
        problems = problems_field_registry(load_registry(), row_fields)
        if not any("discount_amount" in p for p in problems):
            raise AssertionError(f"装配层新增字段后判据未变红 ⇒ 空断言：{problems}")

    def test_new_tenant_fact_unregistered_is_red(self):
        mutated = _mutate(assembly_source(),
                          'snapshot.put("cost_accounting", costsAreTracked(tenantId));',
                          'snapshot.put("cost_accounting", costsAreTracked(tenantId));\n'
                          '        snapshot.put("inventory_tracking", costsAreTracked(tenantId));',
                          "DailyBriefingService")
        _, facts = parse_assembly(mutated)
        problems = problems_tenant_facts(load_registry(), engine_source(), facts, facts)
        if not any("inventory_tracking" in p for p in problems):
            raise AssertionError(f"装配层新增事实后判据未变红 ⇒ 空断言：{problems}")

    def test_enabled_by_pointing_nowhere_is_red(self):
        mutated = _mutate(engine_source(), 'enabled_by=("cost_accounting"',
                          'enabled_by=("no_such_fact"', "proactive.py")
        _, facts = parse_assembly(assembly_source())
        problems = problems_tenant_facts(load_registry(), mutated, facts, facts)
        if not any("no_such_fact" in p for p in problems):
            raise AssertionError(f"enabled_by 指向不存在的事实后判据未变红 ⇒ 空断言：{problems}")

    def test_dropping_enabled_by_is_red(self):
        """删掉 enabled_by ⇒ gated 字段失去租户前置 ⇒ 判据 6 红（静默落 wired 的真形态）。"""
        mutated = _drop_block(engine_source(), 'enabled_by=("cost_accounting"')
        if parse_rules(mutated)["below_cost_price"]["enabled_by"]:
            raise AssertionError("注入未生效：enabled_by 仍在")
        _, facts = parse_assembly(assembly_source())
        problems = problems_tenant_facts(load_registry(), mutated, facts, facts)
        if not any("gate" in p and "below_cost_price" in p for p in problems):
            raise AssertionError(f"删掉 enabled_by 后判据未变红 ⇒ 空断言：{problems}")

    def test_marking_a_field_nullable_is_red(self):
        """⑥ 判据 3 的判别力：把某字段标成 nullable 而消费规则未登记 ⇒ 红。"""
        row_fields = _copy(load_registry()["row_fields"])
        row_fields["orders.status"] = {**row_fields["orders.status"], "nullable": True}
        problems = problems_judgeable(_registry(row_fields=row_fields), engine_source())
        if not any("unshipped_overdue" in p and "status" in p for p in problems):
            raise AssertionError(f"把 status 标成可空后判据未变红 ⇒ 空断言：{problems}")

    def test_comment_cannot_feed_the_parser(self):
        """注释里写一句同形的取值文本 ⇒ **喂不动**取值；若真喂动了，对账闸**必红**（fail-closed）。

        这是本文件被类级元守卫 `test_guard_parsing_is_comment_aware.py` 判红后的落地口径：
        取值靠 `java_literals` 的**位置**（注释里的字面量不算），前缀判定再用
        `java_code` 视角的计数对账 —— 两条路都不吃注释。
        """
        # ① 注释里的同形文本：不得被读成声明（注释里的字面量不进 java_literals）
        mutated = _mutate(assembly_source(), 'snapshot.put("cost_accounting"',
                          '// snapshot.put("ghost_fact", costsAreTracked(tenantId));\n'
                          '        snapshot.put("cost_accounting"', "DailyBriefingService")
        _, facts = parse_assembly(mutated)
        if "ghost_fact" in facts:
            raise AssertionError(f"注释里的同形文本被读成了声明（正是 #5323 的病灶）：{facts}")
        # ② 前缀启发式被注释喂中 ⇒ 计数对账必须**当场红**（而不是静默多认一个数组）
        # 锚点选在**不是**数组名的那一行：注释紧贴其后的字面量（`"sale_amount"`）才不会被
        # 真数组名覆盖（选在数组名那一行会因 dict 同键覆盖而"看不出来"，实测踩到）
        poisoned = _mutate(assembly_source(), '"shipped_at", "sale_amount", "cost_amount"));',
                           '"shipped_at",\n                // 这里**不要**再写 fields.put(\n'
                           '                "sale_amount", "cost_amount"));',
                           "DailyBriefingService")
        try:
            parse_assembly(poisoned)
        except AssertionError as exc:
            if "对账失败" not in str(exc):
                raise AssertionError(f"注释喂中后报的不是对账闸：{exc}") from exc
        else:
            raise AssertionError("注释喂中前缀启发式后没有红 ⇒ 对账闸是空判据")

    def test_missing_reason_is_red(self):
        row_fields = _copy(load_registry()["row_fields"])
        row_fields["orders.order_no"] = {**row_fields["orders.order_no"], "reason": ""}
        problems = problems_ledger_shape(_registry(row_fields=row_fields))
        if not any("reason" in p for p in problems):
            raise AssertionError(f"抹掉 reason 后判据未变红 ⇒ 空断言：{problems}")

    def test_exemption_ledger_nonempty_is_red(self):
        problems = problems_exemptions_are_empty(
            _registry(judgeable_exemptions={"below_cost_price:cost_amount": "先豁免（#5389）"}))
        if not problems:
            raise AssertionError("豁免台账非空后判据未变红 ⇒ 空断言")
        shape = problems_ledger_shape(
            _registry(judgeable_exemptions={"below_cost_price:cost_amount": "先豁免"}))
        if not any("不合格" in p for p in shape):
            raise AssertionError(f"豁免条目缺单号后判据未变红 ⇒ 空断言：{shape}")