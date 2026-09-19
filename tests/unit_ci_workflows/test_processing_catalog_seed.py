# case_ids: PG-043
"""加工项目录（**按 ERP 附件重建**，issue #4566）的三源收敛守卫：生成器 ↔ fixture ↔ 迁移 V83。

## 病灶（本单要挡的形态）

用户 2026-09-19 裁定：「**加工项以及加工项费用的数据没有根据这个附件重建，现在立刻重建**」
（附件 = 壁达 ERP「窗帘货号资料」页的加工费 91 项列表，设计 §1 逐条实证）。重建前
`tests/e2e/fixtures/processing-list.json`（e2e 的 L2 特征词典）里是 **14 条合成特征名、逐条无工艺声明**，
`combination_names()` 的 91 个组合名是**确定性枚举的合成集** ⇒ 与 ERP 真名不等。

| 形态 | 后果 | 本文件的判据 |
|---|---|---|
| 目录多一项 / 少一项 / `craftHint` 写错 | 加工项与 ERP 对不上（**名字是 join key**，差一个字取不到工艺路线） | `test_catalog_constant_is_exactly_the_erp_attachment` |
| fixture 手改过（与生成器分叉） | 「生成一次、写死」这条硬约束失效 ⇒ 两个消费侧读到两份真值 | `test_fixture_matches_the_generator_and_the_catalog` |
| 旧的编造条目回流 | e2e 断言在**编造数据**上绿（假证据） | `test_fixture_has_no_stale_fabricated_entries` |
| 工艺项 / 特征项的划分漂了 | 5 项带工艺声明是路线键的受控来源，漂了就静默错配路线 | `test_craft_declaration_split_is_exactly_five` |
| 迁移 V83 与 fixture 分叉 | 库里目录与测试目录**两份真值**（bootstrap 与迁移链各自漂移） | `test_v83_migration_converges_with_fixture` |

## 红证（不会红的断言 = 空断言）

`test_parsers_detect_injected_drift` 是**注入式自证**：改 fixture 一个字（`craftHint` / 名字）、
删掉 `craftHint` 键、以及在**同形态样本 SQL** 上改一个字（名字 / 工艺 / 加一行 / 少一行 / 去掉
`craft_hint` 列 / 把别名列映射改掉）后，两个解析函数必须**读得出差异**（缺键还必须直接报错）。
没有它，上面的逐值比对可能「绿了但没跑」。样本 SQL 同时把 **V83 期望的种子形态**写成契约：
按租户循环 `INSERT INTO processing_items (列…) SELECT … FROM tenants t JOIN (VALUES (…)) AS v(seq, name, craft_hint, description)`
（V83 实际形态）+ 字面量 `VALUES (…) ON CONFLICT … DO NOTHING` + 单行 `SELECT … FROM tenants t`。

## ⚠️ 已知边界（**别把组合价目读成真实数据**）

`combination_names()` / `combination_rows()`（91 组合 + `缎带` = 92 行）**本次不动**：用户裁定
组合价目**等 ERP 导出后再重建** ⇒ 那 91 个名字仍是**合成枚举**（ERP 真名例：`打孔+拼接+倒幅+定型`）。
本文件只守**加工项目录**这一层；组合价目的守卫仍在 `test_option_fee_seed.py`。

## 口径：`craftHint` 缺失 = **显式 `null`**（不是省略键）

每条 fixture 条目**都带** `craftHint` 键，未声明者落 `null`（= V78 的 `NULL = 商家没声明`，
**不是**「工艺 = 空」）。故本文件的 fixture 解析器对**缺键**直接 fail-closed
（`test_parsers_detect_injected_drift` 有对应用例），避免「键缺失」被静默当成「未声明」。
"""
from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import synthetic_processing_fee_data as synthetic  # noqa: E402

FIXTURE = REPO / "tests/e2e/fixtures/processing-list.json"
MIGRATION_DIR = REPO / "backend/admin-api/src/main/resources/db/migration"
#: 期望的迁移文件名（主会话落地的那个）；解析时按 `V83__*.sql` 发现 ⇒ 文件名微调不至于让本判据静默跳过。
MIGRATION_NAME = "V83__seed_processing_item_catalog.sql"

#: 权威清单（ERP 附件逐字照抄）—— **本文件独立重写一份**，不从生成器 import：
#: 生成器改了这里不改 ⇒ 红。这就是判据 a 的可红性来源。
EXPECTED_CATALOG = (
    ("打孔", "打孔"),
    ("韩折", "韩褶"),
    ("韩定+S钩", "韩褶"),
    ("穿杆", "穿杆"),
    ("平幔", "平幔"),
    ("定型", None),
    ("花边", None),
    ("扣环", None),
    ("接高", None),
    ("拼接", None),
    ("双眼皮", None),
    ("缎带", None),
    ("换货", None),
    ("超高", None),
    ("超宽", None),
    ("倒幅", None),
)
EXPECTED_HINTS = dict(EXPECTED_CATALOG)
#: 带**工艺声明**的 5 项（路线键「工艺」维的受控来源）；其余 11 项 = 未声明（`None`）。
CRAFT_DECLARED = {"打孔", "韩折", "韩定+S钩", "穿杆", "平幔"}
#: **不在**目录里：`四爪钩` 是配件、不是打褶方式（归属 issue #4365 阶段 2）⇒ 出现即红。
OUT_OF_CATALOG_BY_DESIGN = ("四爪钩",)

#: 旧 fixture 的**编造条目**（来源 = git 历史 `5287ad24a` / `17b84451f` / `df3623466^` 的 10 条
#: 真实快照；判据同 `test_option_fee_seed.py`，但**本文件自己重写一份** —— 两个守卫互相独立
#: 才有交叉校验价值）。任一名字回到 fixture 即红。
STALE_FABRICATED = (
    "魔术贴安装", "铅坠安装", "高温定型", "普通定型", "罗马杆环安装",
    "S钩安装", "四爪钩安装", "包边处理", "双折边", "单折边",
)

#: `craftHint` 键**缺失**的哨兵 —— 与 `None`（= 显式未声明）**不同**，别让两者混成一个值。
_MISSING = "<craftHint 键缺失>"
#: 非 SQL 字面量（表达式 / 列引用）的哨兵：本判据只认字面量种子行，动态行**不假装读过**。
_DYNAMIC = "<非字面量>"

_INSERT_RE = re.compile(r"INSERT\s+INTO\s+processing_items\s*\(([^)]*)\)(.*?);", re.S | re.I)
#: `JOIN (VALUES (…), (…)) [AS] v(seq, name, craft_hint, description)` —— **V83 的种子形态**
#: （值在 VALUES 行里，外层 `SELECT` 列表只负责列映射）。
_VALUES_ALIAS_RE = re.compile(r"\(\s*VALUES\b(.*?)\)\s*(?:AS\s+)?(\w+)\s*\(([^)]*)\)", re.S | re.I)
#: `v.name` 这类「别名.列」引用（外层列 ← VALUES 行里的哪一列）。
_ALIAS_REF_RE = re.compile(r"^\w+\.\w+$")
#: 尾部 `::type` / `::varchar(16)` / `::numeric(12,2)` 转换 —— 读字面量前先剥掉。
_CAST_RE = re.compile(r"::\s*[A-Za-z_][A-Za-z0-9_ ]*(\(\s*\d+(\s*,\s*\d+)?\s*\))?$")


# ══════════════════════════ 解析器（两个，各带注入式自证）══════════════════════════

def _split_fields(raw: str) -> list:
    """行字段切分：只认**顶层**逗号（认字符串字面量与 `''` 转义、吃掉嵌套括号）。"""
    fields, current, depth, in_string, index = [], "", 0, False, 0
    while index < len(raw):
        char = raw[index]
        if char == "'":
            if in_string and index + 1 < len(raw) and raw[index + 1] == "'":
                current += "''"
                index += 2
                continue
            in_string = not in_string
            current += char
        elif in_string:
            current += char
        elif char == "(":
            depth += 1
            current += char
        elif char == ")":
            depth -= 1
            current += char
        elif char == "," and depth == 0:
            fields.append(current.strip())
            current = ""
        else:
            current += char
        index += 1
    fields.append(current.strip())
    return fields


def _top_level_rows(body: str) -> list:
    """`VALUES` 段 → 行（只认**顶层**括号组；`now()` 这类嵌套括号由深度吃掉）。"""
    rows, depth, start, in_string, index = [], 0, None, False, 0
    while index < len(body):
        char = body[index]
        if char == "'":
            if in_string and index + 1 < len(body) and body[index + 1] == "'":
                index += 2
                continue
            in_string = not in_string
        elif not in_string:
            if char == "(":
                if depth == 0:
                    start = index + 1
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0 and start is not None:
                    rows.append(_split_fields(body[start:index]))
                    start = None
        index += 1
    return rows


def _aliased_values_rows(body: str):
    """`JOIN (VALUES (…), (…)) [AS] v(列, 列, …)` → `(别名列, 行)`；无此形态 ⇒ `(None, [])`。"""
    match = _VALUES_ALIAS_RE.search(body)
    if not match:
        return None, []
    return ([c.strip().lower() for c in match.group(3).split(",")],
            _top_level_rows(match.group(1)))


def _literal_rows(body: str, column_count: int) -> list:
    """**字面量**形态 → 行：`VALUES (…), (…)`（顶层括号 = 行）或 `SELECT …, … FROM …`（单行）。

    只认「每个字段数都等于列数」的候选集合；解析错位 ⇒ 返回空 ⇒ 比对判红（fail-closed）。
    """
    values = re.search(r"\bVALUES\b", body, re.I)
    if values:
        tail = re.split(r"\bON\s+CONFLICT\b", body[values.end():], maxsplit=1, flags=re.I)[0]
        candidates = [_top_level_rows(tail)]
    else:
        select = re.search(r"\bSELECT\b(.*?)\bFROM\b", body, re.S | re.I)
        candidates = [[_split_fields(select.group(1))]] if select else []
    return next((c for c in candidates if c and all(len(f) == column_count for f in c)), [])


def _literal(raw: str):
    """SQL 字面量 → Python 值：`NULL`（含 `::type` 尾缀）→ `None`；`'x'` → `x`；其余 → `_DYNAMIC`。"""
    raw = _CAST_RE.sub("", raw.strip()).strip()
    if raw.upper() == "NULL":
        return None
    if len(raw) >= 2 and raw.startswith("'") and raw.endswith("'"):
        return raw[1:-1].replace("''", "'")
    return _DYNAMIC


def _statement_records(columns: list, body: str) -> list:
    """一条 `INSERT INTO processing_items …` 的语句体 → `[{列名: 值}]`。

    认三种形态（本仓种子迁移的写法）：
    ① 按租户循环 + `JOIN (VALUES (…)) AS v(seq, name, craft_hint, …)`（**V83 的形态**）——
       值在 VALUES 行里，外层 `SELECT` 列表负责列映射（`v.name` ⇒ 外层 `name` 列）；
    ② `VALUES (…), (…) ON CONFLICT … DO NOTHING`（字面量种子行，V79 的 1 号租户段形态）；
    ③ `SELECT …, … FROM tenants t …`（单行字面量，字段按列序对齐）。
    """
    alias_cols, alias_rows = _aliased_values_rows(body)
    select = re.search(r"\bSELECT\b(.*?)\bFROM\b", body, re.S | re.I)
    if alias_cols and select:
        exprs = _split_fields(select.group(1))
        if len(exprs) == len(columns):
            records = []
            for row in alias_rows:
                if len(row) != len(alias_cols):
                    continue
                by_alias = dict(zip(alias_cols, row))
                records.append({
                    column: (_literal(by_alias.get(expr.strip().split(".")[-1], _DYNAMIC))
                             if _ALIAS_REF_RE.match(expr.strip()) else _literal(expr))
                    for column, expr in zip(columns, exprs)})
            if records:
                return records
    rows = _literal_rows(body, len(columns))
    return [dict(zip(columns, [_literal(f) for f in row])) for row in rows]


def migration_catalog(sql: str) -> dict:
    """迁移文本 → `{name: craftHint}`。

    * `craft_hint` 列**缺席** ⇒ 全部落 `_MISSING`（列集漂移必须判红，不能当成"未声明"）；
    * 名字是表达式/列引用的行**跳过**（不是字面量种子行）；
    * 行字段数与列数不等 / 形态不认识 ⇒ 读不到 ⇒ 比对判红（fail-closed，**不**静默返回空）。
    """
    statements = _INSERT_RE.findall(sql)
    assert statements, (
        "迁移里没有 `INSERT INTO processing_items (列…) …;` 段 —— 种子形态变了？"
        "期望形态见本文件 docstring（显式列 + VALUES/SELECT + 别名 VALUES 子查询）")
    catalog = {}
    for columns_raw, body in statements:
        columns = [c.strip().strip('"').strip("`").lower() for c in columns_raw.split(",")]
        assert "name" in columns, f"processing_items 的 INSERT 没有 `name` 列：{columns}"
        for record in _statement_records(columns, body):
            name = record.get("name", _DYNAMIC)
            if name is _DYNAMIC or name is None:
                continue
            catalog[name] = (record.get("craft_hint", _MISSING)
                             if "craft_hint" in columns else _MISSING)
    return catalog


def fixture_catalog(document: dict) -> dict:
    """fixture 文档 → `{name: craftHint}`（**缺 `craftHint` 键 ⇒ 直接红**，口径 = 显式 `null`）。"""
    items = document["data"]["items"]
    assert items, "fixture 一条都没有 ⇒ 本判据是空跑"
    catalog = {}
    for item in items:
        assert "craftHint" in item, (
            f"{item.get('name')} 缺 `craftHint` 键 —— 口径是**显式 `null`**（不是省略键），"
            f"见 synthetic_processing_fee_data.fixture_items 的 docstring")
        catalog[item["name"]] = item["craftHint"]
    return catalog


def fixture_document() -> dict:
    assert FIXTURE.exists(), f"fixture 缺失：{FIXTURE}"
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def migration_path():
    """按 `V83__*.sql` 发现迁移（文件名微调 ⇒ 仍然收敛，不静默跳过）；不存在 ⇒ `None`。"""
    hits = sorted(MIGRATION_DIR.glob("V83__*.sql"))
    return hits[0] if hits else None


def _sample_sql(catalog, columns=("id", "tenant_id", "name", "craft_hint")) -> str:
    """把 `catalog` 渲染成**字面量 VALUES 形态**的样本 SQL（供解析器自证）。"""
    values = ",\n".join(
        "  ('pi-v83-%02d', 1, '%s', %s)" % (index, name, f"'{hint}'" if hint else "NULL")
        for index, (name, hint) in enumerate(catalog, start=1))
    return (f"INSERT INTO processing_items ({', '.join(columns)})\nVALUES\n{values}\n"
            "ON CONFLICT (tenant_id, name) WHERE deleted = 0 DO NOTHING;")


def _sample_alias_sql(catalog) -> str:
    """把 `catalog` 渲染成**V83 的别名 VALUES 形态**的样本 SQL（按租户循环 + `JOIN (VALUES …)`）。"""
    values = ",\n".join(
        "      ('%02d'::text, '%s'::text, %s, 'd'::text)" % (
            index, name, f"'{hint}'::varchar(16)" if hint else "NULL::varchar(16)")
        for index, (name, hint) in enumerate(catalog, start=1))
    return ("INSERT INTO processing_items\n"
            "    (id, tenant_id, name, category_id, pricing_method, unit_price, unit,\n"
            "     description, craft_hint, status)\n"
            "SELECT 'pi-v83-' || t.id || '-' || v.seq, t.id, v.name, 'pc-v83-' || t.id || '-fee',\n"
            "       'per_meter', 0, '米', v.description, v.craft_hint, 'active'\n"
            "  FROM tenants t\n"
            "  JOIN (VALUES\n" + values + "\n"
            "  ) AS v(seq, name, craft_hint, description)\n"
            " WHERE t.deleted = 0;")


# ══════════════════════════ ① 目录逐字（判据 a / d）══════════════════════════

def test_catalog_constant_is_exactly_the_erp_attachment():
    """生成器的目录常量 = ERP 附件 **16 项逐字**（名字集合 + 每个名字的 `craftHint`）。

    多一项 / 少一项 / `craftHint` 写错 / 重名（dict 化会静默吞掉一条）⇒ 红。
    """
    assert len(EXPECTED_CATALOG) == 16 and len(EXPECTED_HINTS) == 16, \
        "本文件自己的对照表写错了（有重名或条数不是 16）⇒ 先修对照表"
    got = dict(synthetic.PROCESSING_CATALOG)
    assert len(got) == len(synthetic.PROCESSING_CATALOG), \
        f"加工项目录里有重名项：{sorted(synthetic.PROCESSING_CATALOG)}"
    assert got == EXPECTED_HINTS, (
        "加工项目录 ≠ ERP 附件（issue #4566）：\n"
        f"  多出：{sorted(set(got) - set(EXPECTED_HINTS))}\n"
        f"  缺少：{sorted(set(EXPECTED_HINTS) - set(got))}\n"
        f"  craftHint 不同：{ {n: (got.get(n), EXPECTED_HINTS.get(n)) for n in set(got) & set(EXPECTED_HINTS) if got.get(n) != EXPECTED_HINTS.get(n)} }")
    for name in OUT_OF_CATALOG_BY_DESIGN:
        assert name not in got, f"`{name}` 不在 ERP 加工项目录里（配件不是打褶方式，issue #4365 阶段 2）"


def test_craft_declaration_split_is_exactly_five():
    """工艺项 / 特征项的划分**可判**：恰好 5 项带 `craftHint`，其余 11 项为 `None`。"""
    catalog = fixture_catalog(fixture_document())
    declared = {name for name, hint in catalog.items() if hint is not None}
    assert declared == CRAFT_DECLARED, \
        f"带工艺声明的项不是那 5 项：多出 {sorted(declared - CRAFT_DECLARED)}、缺少 {sorted(CRAFT_DECLARED - declared)}"
    assert len(declared) == 5 and len(catalog) == 16 and len(catalog) - len(declared) == 11
    assert {name for name, hint in catalog.items() if hint is None} == set(EXPECTED_HINTS) - CRAFT_DECLARED


# ══════════════════════════ ② fixture 与生成器逐值一致（判据 b / c）══════════════════════════

def test_fixture_matches_the_generator_and_the_catalog():
    """fixture 是**生成物**（不手改）：逐值等于生成器，且逐值等于 ERP 附件目录。"""
    document = fixture_document()
    items = document["data"]["items"]
    assert items == synthetic.fixture_items(), \
        "fixture 与生成器不一致 ⇒ 重跑 `python3 tests/unit_ci_workflows/synthetic_processing_fee_data.py --write-fixture`"
    assert document["data"]["total"] == len(items) == 16
    assert {item["source"] for item in items} == {synthetic.SOURCE}
    assert fixture_catalog(document) == EXPECTED_HINTS, "fixture 的 (name, craftHint) ≠ ERP 附件目录"
    for item in items:
        assert (item["pricingMethod"], item["unitPrice"], item["unit"]) == ("per_meter", 0, "米"), \
            f"{item['name']} 的计价口径漂了（单位米 / 无价 / per_meter）"


def test_fixture_has_no_stale_fabricated_entries():
    """旧 fixture 的**编造条目**一条不剩（判据同 `test_option_fee_seed.py`，名单本文件自持）。"""
    names = {item["name"] for item in fixture_document()["data"]["items"]}
    assert len(STALE_FABRICATED) == 10 and not (set(STALE_FABRICATED) & set(EXPECTED_HINTS)), \
        "stale 名单本身写错了（含真实目录名 ⇒ 恒红；本判据自检）"
    assert not (names & set(STALE_FABRICATED)), \
        f"旧的编造数据还在 fixture 里：{sorted(names & set(STALE_FABRICATED))}"


# ══════════════════════════ ③ 迁移 V83 收敛（判据 e）══════════════════════════

def test_v83_migration_converges_with_fixture():
    """V83 的 `(name, craft_hint)` 集合 == fixture 的 `(name, craftHint)` 集合（逐条同源）。

    V83 由**另一个包**落地；此刻还没落地 ⇒ **显式 skip**（不伪造通过）。
    """
    path = migration_path()
    if path is None:
        pytest.skip("V83 尚未落地")
    parsed = migration_catalog(path.read_text(encoding="utf-8"))
    assert parsed == EXPECTED_HINTS, (
        f"{path.name} 的种子行 ≠ ERP 附件目录（issue #4566）：\n"
        f"  多出：{sorted(set(parsed) - set(EXPECTED_HINTS))}\n"
        f"  缺少：{sorted(set(EXPECTED_HINTS) - set(parsed))}\n"
        f"  craftHint 不同：{ {n: (parsed.get(n), EXPECTED_HINTS.get(n)) for n in set(parsed) & set(EXPECTED_HINTS) if parsed.get(n) != EXPECTED_HINTS.get(n)} }")
    assert parsed == fixture_catalog(fixture_document()), "迁移与 fixture 分叉（两份真值）"


# ══════════════════════════ ④ 注入式自证（判据 f，红证）══════════════════════════

def test_parsers_detect_injected_drift():
    """改一个字 ⇒ 两个解析函数必须**读得出差异**（否则上面的逐值比对是空断言）。"""
    document = fixture_document()
    base = fixture_catalog(document)
    assert base == EXPECTED_HINTS, "起点就不等 ⇒ 先修 fixture/生成器"

    # ① fixture：改一项的 craftHint（未声明 → 声明 / 声明 → 未声明，两个方向都读得出）
    for name, new_hint in (("定型", "韩褶"), ("打孔", None)):
        drifted = copy.deepcopy(document)
        next(i for i in drifted["data"]["items"] if i["name"] == name)["craftHint"] = new_hint
        assert fixture_catalog(drifted) != base, f"改 {name} 的 craftHint 读不出差异"

    # ② fixture：改名字（join key）⇒ 读得出；且多出的名字会被判成"不在目录里"
    renamed = copy.deepcopy(document)
    next(i for i in renamed["data"]["items"] if i["name"] == "缎带")["name"] = "四爪钩"
    assert fixture_catalog(renamed) != base, "改名字读不出差异"

    # ③ fixture：**删掉 `craftHint` 键** ⇒ 必须直接报错（口径 = 显式 null，缺键 ≠ 未声明）
    dropped = copy.deepcopy(document)
    dropped["data"]["items"][0].pop("craftHint")
    with pytest.raises(AssertionError):
        fixture_catalog(dropped)

    # ④ 迁移解析器：用同形态样本 SQL 自证（不依赖 V83 是否已落地）
    sample = _sample_sql(EXPECTED_CATALOG)
    assert migration_catalog(sample) == EXPECTED_HINTS, "解析器连样本都读不对 ⇒ 后面全是空断言"
    assert migration_catalog(sample)["定型"] is None, "`NULL` 必须读成 None（未声明），不是字符串 'NULL'"
    assert migration_catalog(sample.replace("'韩褶'", "'韩折'", 1)) != EXPECTED_HINTS, "改 craft_hint 读不出差异"
    assert migration_catalog(sample.replace("'打孔'", "'打洞'", 1)) != EXPECTED_HINTS, "改 name 读不出差异"
    assert migration_catalog(_sample_sql(EXPECTED_CATALOG[:-1])) != EXPECTED_HINTS, "少一行读不出差异"
    assert migration_catalog(_sample_sql(EXPECTED_CATALOG + (("四爪钩", None),))) != EXPECTED_HINTS, \
        "多一行读不出差异"
    assert migration_catalog(_sample_sql(EXPECTED_CATALOG, columns=("id", "tenant_id", "name"))) != EXPECTED_HINTS, \
        "去掉 `craft_hint` 列（列集漂移）读不出差异"

    # ⑤ **V83 的别名 VALUES 形态**（值在 VALUES 行、外层 SELECT 只做列映射）也必须解析得出来
    alias_sample = _sample_alias_sql(EXPECTED_CATALOG)
    assert migration_catalog(alias_sample) == EXPECTED_HINTS, "别名 VALUES 形态解析不出来"
    assert migration_catalog(alias_sample)["韩折"] == "韩褶", "别名映射错位（名字↔craft_hint 串了）"
    assert migration_catalog(alias_sample.replace("'韩褶'::varchar(16)", "'打孔'::varchar(16)", 1)) != EXPECTED_HINTS, \
        "别名形态改 craft_hint 读不出差异"
    assert migration_catalog(alias_sample.replace("'打孔'::text", "'打洞'::text", 1)) != EXPECTED_HINTS, \
        "别名形态改 name 读不出差异"
    assert migration_catalog(alias_sample.replace("v.craft_hint", "NULL", 1)) != EXPECTED_HINTS, \
        "别名形态把 craft_hint 整列改成 NULL 读不出差异"

    # ⑥ 按租户 `SELECT` 循环形态（无别名子查询）也要能解析
    loop = ("INSERT INTO processing_items (id, tenant_id, name, craft_hint)\n"
            "SELECT 'pi-v83-' || t.id || '-01', t.id, '打孔', '打孔' FROM tenants t WHERE t.deleted = 0;")
    assert migration_catalog(loop) == {"打孔": "打孔"}, "按租户 SELECT 循环的行解析不出来"

    # ⑦ **真实 V83**（已落地时）上注入一处漂移也必须读得出 —— 样本自证不替代真文件
    path = migration_path()
    if path is not None:
        real = path.read_text(encoding="utf-8")
        assert migration_catalog(real) == EXPECTED_HINTS, "真实 V83 与 ERP 附件目录不等"
        assert migration_catalog(real.replace("'韩褶'::varchar(16)", "'打孔'::varchar(16)", 1)) != EXPECTED_HINTS, \
            "在真实 V83 上改一个 craft_hint 读不出差异"


# ══════════════════════════ ⑤ 可执行形态 + 双保险幂等（真库实测缺陷的文本判据）══════════════════════════

def executability_defects(sql: str) -> list:
    """**文本层可判**的可执行性 / 幂等缺陷（空列表 = 通过）。

    ⚠️ **本函数只做文本判据**，它拦得住下面这两个**真库实测过的具体形态**，
    **拦不住**其它 SQL 语法错 —— 「静态守卫不执行 SQL」这一族根因见 #4514（本单不根治）。
    """
    defects = []
    # 先剥掉**整行注释**：本文件的文件头注释里就写着 `AS v(…)` 缺 `ON` 这个反例
    # ⇒ 不剥注释会把「文档里描述缺陷」误判成「代码里有缺陷」（门禁逼人不敢写文档）。
    body = "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--"))
    # ① `JOIN (VALUES …) AS v(…)` 必须有 `ON`：PostgreSQL 不允许无 ON/USING 的 JOIN。
    #    真库实测（issue #4566 验证轮）：缺它 ⇒ 语法错误 ⇒ **整份迁移回滚 + schema_migrations 不写**
    #    ⇒ 每次启动重跑报 ERROR、目录永不落库（#4514 / V74 同族）。仓库既有合法范式 = V79 的 `ON TRUE`。
    for match in re.finditer(r"\)\s*AS\s+\w+\s*\([^)]*\)(.*)", body, re.S):
        if not match.group(1).lstrip().startswith("ON"):
            defects.append("`AS v(…)` 之后缺 `ON`（JOIN 必须带 ON/USING）")
    # ② 每段 INSERT 都要**双保险**：业务键 `NOT EXISTS` + `ON CONFLICT (id) DO NOTHING`。
    #    本迁移的 id 是**按槽位**派生的 ⇒ 商家**改名/软删**某项后重跑时，`NOT EXISTS` 判「该插」
    #    而槽位 id 仍被占用 ⇒ PK 冲突 ⇒ 整份回滚（真库实测）。`ON CONFLICT` 把它收敛成无操作。
    inserts = body.count("INSERT INTO")
    if inserts == 0:
        defects.append("没扫到任何 INSERT ⇒ 本判据是空跑")
    if body.count("ON CONFLICT (id) DO NOTHING") < inserts:
        defects.append(f"{inserts} 段 INSERT 里不足 {inserts} 段带 `ON CONFLICT (id) DO NOTHING`（槽位 id 兜底）")
    if body.count("NOT EXISTS") < inserts:
        defects.append(f"{inserts} 段 INSERT 里不足 {inserts} 段带 `NOT EXISTS`（业务键去重）")
    return defects


def test_v83_is_executable_shaped_and_idempotent_by_double_guard():
    """V83（及其 bootstrap 同源块）必须**可执行形态** + **双保险幂等** —— 带注入式红证。"""
    path = migration_path()
    if path is None:
        pytest.skip("V83 尚未落地")
    sql = path.read_text(encoding="utf-8")
    assert executability_defects(sql) == [], (
        f"{path.name} 存在可执行性/幂等缺陷：{executability_defects(sql)}")

    # 红证 ①：拿掉 `ON TRUE` ⇒ 必须报出「缺 ON」（这正是真库实测的那个 P0）
    assert executability_defects(sql.replace("ON TRUE", "")) != [], \
        "删掉 `ON TRUE` 读不出差异 ⇒ 本判据对那个 P0 是空断言"
    # 红证 ②：拿掉 `ON CONFLICT (id) DO NOTHING` ⇒ 必须报出槽位 id 兜底缺失
    assert executability_defects(sql.replace("ON CONFLICT (id) DO NOTHING", "")) != [], \
        "删掉 `ON CONFLICT (id) DO NOTHING` 读不出差异 ⇒ 对 PK 冲突那一族是空断言"
    # 红证 ③：拿掉 `NOT EXISTS` ⇒ 必须报出业务键去重缺失
    assert executability_defects(sql.replace("NOT EXISTS", "")) != [], \
        "删掉 `NOT EXISTS` 读不出差异 ⇒ 对「覆盖商家数据」那一族是空断言"

    # bootstrap 同源块：JOIN 形态必须同样合法（该路径不跑迁移链，坏了不会被迁移守卫发现）
    schema = (REPO / "docs/sql/schema.sql").read_text(encoding="utf-8")
    join_defects = [d for d in executability_defects(schema) if "缺 `ON`" in d]
    assert join_defects == [], f"docs/sql/schema.sql 的 JOIN 形态不合法：{join_defects}"
