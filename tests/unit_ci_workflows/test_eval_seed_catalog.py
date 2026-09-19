# case_ids: PG-043
"""评测栈种子**只提供 3 条带价夹具**，ERP 加工项目录**一律由 V83 迁移提供**（issue #4571 / #4572）。

## 病灶（用户提问：「加工项的测试数据为嘛还未重建完」→ 真库实测暴露重名冲突）

2026-09-19 按壁达 ERP 附件重建加工项目录时**只覆盖了两处**（V83 迁移 + e2e fixture），
**评测栈种子仍是编造名单**（3 + 1 项）⇒ 评测里的目录与真实店铺目录**两份口径**。

第一轮修法是「往两个评测种子各插 16 行」—— **真库实测证明这个修法本身是错的**：
`docs/sql/schema.sql` / 迁移链**已经**由 V83 为每个活跃租户种了那 16 项 ⇒ 评测栈上
`processing_items` = **32 行**，其中 `打孔`/`韩折`/`定型` **各重名 2 条**
（`pi_eval_punch` ¥8 与 `pi-v83-1-01` ¥0）⇒
① `processing_item_query(打孔)` 返 2 条、金额断言不确定；
② `processing_item_count_for_keyword: 打孔, expect: 1`（**PP-008 的前置**）**运行期必红**。
⚠️ 当时**全部静态守卫都是绿的** —— 这正是 #4514 同族（静态守卫不执行 SQL）。

## 裁定口径（2026-09-19，本文件锁定它）

| 谁提供 | 内容 |
|---|---|
| **V83 迁移**（产品口径不动：目录无价，R10） | ERP 目录 **16 项**（`打孔`/`韩折`/`韩定+S钩`/`穿杆`/`平幔`/`定型`/`花边`/`扣环`/`接高`/`拼接`/`双眼皮`/`缎带`/`换货`/`超高`/`超宽`/`倒幅`） |
| **评测种子**（两个文件各一份） | **只有 3 条带价夹具**：`打孔` ¥8/米 · `韩折` ¥12/米 · `定型` ¥10/米（id 仍是 `pi_eval_punch`/`pi_eval_hem`/`pi_eval_iron`）—— 夹具的职责是给 eval 断言提供**金额接地**；**id 保留** ⇒ 引用面最小（`528 = 168×3 + 8×3` 等金额逐值不变） |

**去冲突**：种子在插入**之前**先 `DELETE … WHERE tenant_id = 1 AND name IN (…) AND id LIKE 'pi-v83-%'`
⇒ 同名只有一行。**两种执行顺序都安全**（双保险）：先种子后 V83 ⇒ V83 的业务键 `NOT EXISTS`
跳过这 3 项；先 V83 后种子 ⇒ 本 DELETE 删掉 V83 那 3 行。`processing_items` **无外键引用它**。

`刺绣工艺`（`pi_eval_embroidery`，`per_area`）**已按用户裁定真删** —— 原接地对象
（PP-009 的 `calculate_price` `totalPrice=240.00`、OR-028 的 per_area 8.4㎡=252.00、
`local_runner` 的 `processingItemConfigs.<项>.finalPrice`）已按 **per_meter** 重算改判。

## 本文件锁定什么（每条都对应一条**可红**判据）

| 判据 | 内容 |
|---|---|
| a | **无重名**：`V83 的 16 个名字` 与 `种子插入的名字` 的交集**恰好**是那 3 条带价夹具（且被 DELETE 覆盖）⇒ 并集无重复 |
| b | 3 条带价夹具**在**且带价（8/12/10）、id 保留、`per_meter`/米/active/未删 |
| c | 种子**不**重复插 V83 已种的名字（那 13 项由 V83 提供；种子出现 `pi_eval_cat_*` 即红） |
| d | `DELETE … pi-v83-%` 那行**在**且在 INSERT **之前**（去冲突机制没被删掉） |
| e | V83 解析出的目录 == ERP 附件 16 项（V83 漂了而种子没跟 ⇒ 红） |

⚠️ **运行期那一半**（静态看不见 SQL 执行结果）落在种子的 `DO $$ … $$` 自检块里：
真库跑完种子后 `GROUP BY tenant_id, name HAVING count(*)>1` 为空 + 3 项各恰好 1 行且带价；
不成立即 `RAISE EXCEPTION`（fail-fast）。本文件按文本核该块**必须在**。

## 红证（`migao-acceptance`：不会红的断言 = 空断言）

`test_parsers_detect_injected_drift` 在**真实种子/V83 文本**上注入：改名字 / 改价 /
**删掉那行 DELETE** / **重新插一行 V83 已种的名字**（重演真库那个 32 行形态）/ 把旧编造名
加回来 / 去掉 `craft_hint` 列 / 在真实 V83 上改一处 —— 解析函数与判据必须**读得出差异**。
没有它，上面的比对可能「绿了但没跑」。

## 解析口径

只认 `INSERT INTO processing_items (列清单) …`（**按列名**取值）：字面量 `VALUES (…), (…)`
（两个种子的写法）+ V83 的 `JOIN (VALUES (…)) AS v(seq, name, craft_hint, description)`
（按别名列名映射）。字面量剥掉尾部 `::type`；`NULL` → `None`；字段数 ≠ 列数 ⇒ 该行丢弃
（fail-closed）。`craft_hint` 列缺席 ⇒ 落哨兵 `_NO_COLUMN`（与 `None` = 显式未声明**不同**）。
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "tests" / "agent_eval" / "fixtures"
V83 = (REPO / "backend" / "admin-api" / "src" / "main" / "resources" / "db"
       / "migration" / "V83__seed_processing_item_catalog.sql")

#: 两个评测种子（xiaobu 栈只注 C 端；mibao 栈 = C 端 + B 端）—— 两份都只该有那 3 条带价夹具。
SEED_FILES = ("xiaobu_eval_seed.sql", "mibao_eval_seed.sql")

#: 权威清单（ERP 附件逐字照抄）—— **本文件独立重写一份**，不从 V83 或任何生成器 import：
#: 那两处改了这里不改 ⇒ 红。
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

#: 评测种子**只**提供这 3 条带价夹具：名字 → (id, 单价)。id **保留**（引用面最小）。
PRICED_FIXTURES = {"打孔": ("pi_eval_punch", 8.00),
                   "韩折": ("pi_eval_hem", 12.00),
                   "定型": ("pi_eval_iron", 10.00)}
#: 其余 13 项**由 V83 提供**，评测种子**不得**重复插入（真库实测的 32 行/重名 2 条就是这么来的）。
V83_ONLY = tuple(sorted(set(EXPECTED_HINTS) - set(PRICED_FIXTURES)))

#: 目录行沿用**既有评测分类**（定义在 C 端种子里）—— 本单**不新造分类**。
CATEGORY_ID = "pcat_eval_curtain"
#: 目录行 id 的旧槽位前缀（第一轮修法的产物）—— 再出现即「重复插 V83 已种的名字」。
STALE_CATALOG_ID_PREFIX = "pi_eval_cat_"

#: 用户裁定必须删掉的旧编造**名字**（issue #4571 + 二次裁定「真删」）。
OLD_FABRICATED_NAMES = ("纳米圈打孔", "韩式波浪折边", "高温定型", "刺绣工艺")
#: 被真删的 `per_area` 夹具。
DELETED_PER_AREA = {"name": "刺绣工艺", "id": "pi_eval_embroidery"}

#: 覆盖损失必须**逐条写进**这些 case 的文件（按文本核，防「悄悄删掉接地对象」）。
COVERAGE_LOSS_CASES = {"PP-009": "processing.yml", "OR-028": "order.yml"}
COVERAGE_LOSS_TEXT = "per_area 计价路径的评测覆盖随"

#: `craft_hint` 列**缺席**的哨兵 —— 与 `None`（= 显式未声明）**不同**，别让两者混成一个值。
_NO_COLUMN = "<craft_hint 列缺失>"
#: 非 SQL 字面量（表达式 / 列引用）的哨兵：只认字面量行，动态行**不假装读过**。
_DYNAMIC = "<非字面量>"

_INSERT_RE = re.compile(r"INSERT\s+INTO\s+processing_items\s*\(([^)]*)\)(.*?);", re.S | re.I)
#: 去冲突语句：`DELETE FROM processing_items WHERE tenant_id = 1 AND name IN (…) AND id LIKE 'pi-v83-%'`
_DELETE_RE = re.compile(
    r"DELETE\s+FROM\s+processing_items\s+WHERE\s+tenant_id\s*=\s*1\s+"
    r"AND\s+name\s+IN\s*\(([^)]*)\)\s+AND\s+id\s+LIKE\s*'([^']*)'", re.I)
#: `JOIN (VALUES (…), (…)) [AS] v(seq, name, craft_hint, description)` —— V83 的种子形态。
_ALIAS_VALUES_RE = re.compile(r"\(\s*VALUES\b(.*?)\)\s*(?:AS\s+)?(\w+)\s*\(([^)]*)\)", re.S | re.I)
#: 尾部 `::type` / `::varchar(16)` 转换 —— 读字面量前先剥掉。
_CAST_RE = re.compile(r"::\s*[A-Za-z_][A-Za-z0-9_ ]*(\(\s*\d+(\s*,\s*\d+)?\s*\))?$")


# ══════════════════════════ 解析器（各带注入式自证）══════════════════════════

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
    """`VALUES` 段 → 行（只认**顶层**括号组；`'[]'::jsonb` 无括号、`::varchar(16)` 由深度吃掉）。"""
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


def _literal(raw: str):
    """SQL 字面量 → Python 值：`NULL`（含 `::type`）→ `None`；`'x'` → `x`；数字 → `int`/`float`。"""
    raw = _CAST_RE.sub("", raw.strip()).strip()
    if raw.upper() == "NULL":
        return None
    if len(raw) >= 2 and raw.startswith("'") and raw.endswith("'"):
        return raw[1:-1].replace("''", "'")
    if re.fullmatch(r"-?\d+", raw):
        return int(raw)
    if re.fullmatch(r"-?\d+\.\d+", raw):
        return float(raw)
    return _DYNAMIC


def _strip_comment_lines(sql: str) -> str:
    """剥掉整行 `--` 注释（V83 的文件头注释里**合法地**写着反例 ``JOIN (VALUES …) AS v(…)``）。"""
    return "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--"))


def _literal_value_rows(body: str, column_count: int) -> list:
    """字面量形态 → 行：`VALUES (…), (…)`（`ON CONFLICT` 之前的部分）；字段数 ≠ 列数 ⇒ 丢弃。"""
    values = re.search(r"\bVALUES\b", body, re.I)
    if not values:
        return []
    tail = re.split(r"\bON\s+CONFLICT\b", body[values.end():], maxsplit=1, flags=re.I)[0]
    return [row for row in _top_level_rows(tail) if len(row) == column_count]


def seed_rows(text: str) -> list:
    """评测种子文本 → `[{列名: 值}]`（**只**取 `INSERT INTO processing_items` 的语句）。"""
    statements = _INSERT_RE.findall(text)
    assert statements, (
        "种子里没有 `INSERT INTO processing_items (列…) …;` 段 —— 种子形态变了？"
        "（期望形态：显式列清单 + 字面量 `VALUES (…), (…)` + `ON CONFLICT (id) DO NOTHING`）")
    rows = []
    for columns_raw, body in statements:
        columns = [c.strip().strip('"').strip("`").lower() for c in columns_raw.split(",")]
        assert "name" in columns, f"processing_items 的 INSERT 没有 `name` 列：{columns}"
        parsed = _literal_value_rows(body, len(columns))
        assert parsed, (
            f"这一段 INSERT 一行都读不出（列数 {len(columns)}）—— 解析口径与种子形态脱钩了，"
            "必须同步本文件，不许让判据静默空跑")
        for fields in parsed:
            record = {column: _literal(field) for column, field in zip(columns, fields)}
            if "craft_hint" not in columns:
                record["craft_hint"] = _NO_COLUMN
            rows.append(record)
    return rows


def seed_catalog(text: str) -> dict:
    """评测种子文本 → `{name: craft_hint}`（名字非字面量的行跳过）。"""
    catalog = {}
    for record in seed_rows(text):
        name = record.get("name", _DYNAMIC)
        if name is _DYNAMIC or name is None:
            continue
        catalog[name] = record.get("craft_hint", _NO_COLUMN)
    return catalog


def v83_catalog(text: str) -> dict:
    """V83 迁移文本 → `{name: craft_hint}`（**只读解析**；别名 VALUES 形态，按别名列名映射）。"""
    match = _ALIAS_VALUES_RE.search(_strip_comment_lines(text))
    assert match, (
        "V83 里没找到 `JOIN (VALUES …) AS v(seq, name, craft_hint, description)` 形态 —— "
        "迁移形态变了 ⇒ 本判据的前提失效，必须同步本文件（**不要**改迁移）")
    alias_columns = [c.strip().lower() for c in match.group(3).split(",")]
    assert "name" in alias_columns and "craft_hint" in alias_columns, alias_columns
    catalog = {}
    for row in _top_level_rows(match.group(1)):
        if len(row) != len(alias_columns):
            continue
        by_alias = dict(zip(alias_columns, row))
        name = _literal(by_alias["name"])
        if name is _DYNAMIC or name is None:
            continue
        catalog[name] = _literal(by_alias["craft_hint"])
    return catalog


def deconflict_delete(text: str):
    """种子文本 → 去冲突 DELETE 的 `(名字元组, LIKE 模式)`；没有 ⇒ `None`。"""
    match = _DELETE_RE.search(_strip_comment_lines(text))
    if not match:
        return None
    names = tuple(n.strip().strip("'") for n in match.group(1).split(",") if n.strip())
    return names, match.group(2)


def _seed_text(name: str) -> str:
    path = FIXTURES / name
    assert path.is_file(), f"评测种子缺失：{path}"
    return path.read_text(encoding="utf-8")


def _v83_text() -> str:
    assert V83.is_file(), f"V83 迁移缺失：{V83}（本判据的对照源，只读）"
    return V83.read_text(encoding="utf-8")


# ══════════════════════════ 判据 e：V83 提供整个 ERP 目录 ══════════════════════════

def test_v83_provides_the_whole_erp_catalog():
    """V83 解析出的目录 == ERP 附件 16 项（逐值含 `craft_hint`）—— 它现在是**唯一**目录来源。"""
    source = v83_catalog(_v83_text())
    assert len(source) == 16, f"V83 解析出 {len(source)} 项（应为 16）：{sorted(source)}"
    assert source == EXPECTED_HINTS, (
        "V83 的目录 ≠ 本文件自持的 ERP 附件清单（两者必有一个错了）：\n"
        f"  多出：{sorted(set(source) - set(EXPECTED_HINTS))}\n"
        f"  缺少：{sorted(set(EXPECTED_HINTS) - set(source))}\n"
        f"  craft_hint 不同：{ {n: (source.get(n), EXPECTED_HINTS.get(n)) for n in set(source) & set(EXPECTED_HINTS) if source.get(n) != EXPECTED_HINTS.get(n)} }")
    assert set(V83_ONLY) == set(EXPECTED_HINTS) - set(PRICED_FIXTURES) and len(V83_ONLY) == 13


# ══════════════════════════ 判据 c/d：种子只补 3 条带价夹具 + 去冲突 ══════════════════════════

def test_seeds_only_add_the_three_priced_fixtures():
    """种子**不**重复插 V83 已种的名字 —— 只补那 3 条带价夹具（真库 32 行/重名 2 条的病根）。"""
    for seed in SEED_FILES:
        rows = seed_rows(_seed_text(seed))
        names = [record["name"] for record in rows]
        ids = [record["id"] for record in rows]
        assert len(names) == len(set(names)) == 3, (
            f"{seed} 的 `processing_items` 行应**恰好 3 条**（带价夹具），实为 {len(names)} 条：{names}\n"
            "—— V83 已为每个活跃租户种过那 16 项 ⇒ 再插一遍会让每个名字**两行**"
            "（`processing_item_query(打孔)` 返 2 条、`processing_item_count_for_keyword: 打孔, expect: 1` 运行期必红）")
        assert set(names) == set(PRICED_FIXTURES), (
            f"{seed} 插入的名字 {sorted(names)} ≠ 3 条带价夹具 {sorted(PRICED_FIXTURES)}")
        re_seeded = sorted(set(names) & set(V83_ONLY))
        assert not re_seeded, (
            f"{seed} 重复插入了 V83 已种的目录项 {re_seeded} —— 那 13 项**由 V83 提供**，"
            "评测种子不得重复（这正是真库实测的 32 行/重名形态）")
        stale = [i for i in ids if str(i).startswith(STALE_CATALOG_ID_PREFIX)]
        assert not stale, (
            f"{seed} 还留着第一轮修法的槽位 id {stale} —— 它们与 V83 的同名行构成重名对")


def test_deconflict_delete_is_present_and_precedes_the_insert():
    """判据 d：`DELETE … pi-v83-%` 那行**在**，且位置在 INSERT **之前**（去冲突没被删掉）。"""
    for seed in SEED_FILES:
        text = _seed_text(seed)
        parsed = deconflict_delete(text)
        assert parsed is not None, (
            f"{seed} 里没有去冲突语句 `DELETE FROM processing_items WHERE tenant_id = 1 AND "
            "name IN ('打孔','韩折','定型') AND id LIKE 'pi-v83-%'` —— 没有它，V83 先跑时"
            "（评测栈的常态：admin-api 启动即跑迁移）同名就是**两行**，PP-008 的前置恒红")
        names, pattern = parsed
        assert set(names) == set(PRICED_FIXTURES), (
            f"{seed} 的 DELETE 名字集 {sorted(names)} ≠ 3 条带价夹具 {sorted(PRICED_FIXTURES)}")
        assert pattern == "pi-v83-%", \
            f"{seed} 的 DELETE 模式是 {pattern!r}，应为 'pi-v83-%'（只删 V83 的行）"
        stripped = _strip_comment_lines(text)
        assert stripped.index("DELETE FROM processing_items") < \
            stripped.index("INSERT INTO processing_items"), (
            f"{seed} 的 DELETE 在 INSERT **之后** —— 那样插入时 V83 的行还在"
            "（id 不同，不会撞 ON CONFLICT）⇒ 同名两行依旧")


# ══════════════════════════ 判据 b：3 条带价夹具的值 ══════════════════════════

def test_priced_fixtures_carry_their_prices_and_ids():
    """判据 b：3 条带价夹具**在**且带价（8/12/10）、id 保留、per_meter/米/active/未删。"""
    for seed in SEED_FILES:
        rows = {record["name"]: record for record in seed_rows(_seed_text(seed))}
        for name, (item_id, price) in PRICED_FIXTURES.items():
            assert name in rows, f"{seed} 里没有带价夹具 {name}"
            record = rows[name]
            assert record["id"] == item_id, (
                f"{seed}/{name} 的 id={record['id']!r}，应为 {item_id!r} —— **id 保留**是"
                "「只动 name、金额断言逐值不变」的前提（14+ 个文件按 id 引用）")
            assert (record["pricing_method"], record["unit_price"], record["unit"]) == \
                ("per_meter", price, "米"), (
                f"{seed}/{name} 的计价口径漂了：{record['pricing_method']!r}/"
                f"{record['unit_price']!r}/{record['unit']!r}，应为 per_meter/{price}/米")
            assert record["tenant_id"] == 1 and record["category_id"] == CATEGORY_ID, record
            assert record["status"] == "active" and record["deleted"] == 0, record
            assert record["craft_hint"] == EXPECTED_HINTS[name], (
                f"{seed}/{name} 的 craft_hint={record['craft_hint']!r}，应为 {EXPECTED_HINTS[name]!r}")
        assert not [r for r in rows.values() if r["pricing_method"] == "per_area"], (
            f"{seed} 里还有 `per_area` 加工项 —— `刺绣工艺` 已按用户裁定真删，"
            "且 ERP 目录 16 项全是 per_meter")


# ══════════════════════════ 判据 a：无重名（静态）══════════════════════════

def test_catalog_names_have_no_duplicate_across_v83_and_seeds():
    """判据 a（静态）：V83 的 16 个名字 ∪ 种子插入的名字 **无重复**。

    真实去重由种子里的 `DELETE … pi-v83-%` + V83 的业务键 `NOT EXISTS` 保证；
    本判据钉住**前提**：两者名字的交集恰好是那 3 条（= 会被 DELETE 覆盖的那 3 条）。
    """
    v83_names = set(v83_catalog(_v83_text()))
    assert set(PRICED_FIXTURES) <= v83_names, (
        f"带价夹具的名字 {sorted(set(PRICED_FIXTURES) - v83_names)} 不在 V83 目录里 —— "
        "那样 DELETE 删不到东西、同名会变成「V83 一行 + 夹具一行」两行（除非 V83 先跑）")
    for seed in SEED_FILES:
        seed_names = set(seed_catalog(_seed_text(seed)))
        overlap = seed_names & v83_names
        assert overlap == set(PRICED_FIXTURES), (
            f"{seed} 与 V83 的名字交集 {sorted(overlap)} ≠ 3 条带价夹具 "
            f"{sorted(PRICED_FIXTURES)} —— 多出来的名字就是**重名对**（必须由 DELETE 覆盖或干脆不插）")
        assert len(v83_names | seed_names) == 16, (
            f"并集应有 16 个名字，实为 {len(v83_names | seed_names)}：{sorted(v83_names | seed_names)}")


# ══════════════════════════ 旧编造名 + per_area 覆盖损失 ══════════════════════════

def test_old_fabricated_names_are_gone():
    """旧编造名（含真删的 `刺绣工艺`）一个不剩。"""
    assert not (set(OLD_FABRICATED_NAMES) & set(EXPECTED_HINTS)), \
        "本文件自己的旧名单写错了（与 ERP 目录重名 ⇒ 恒红；自检）"
    for seed in SEED_FILES:
        text = _seed_text(seed)
        still = sorted(set(seed_catalog(text)) & set(OLD_FABRICATED_NAMES))
        assert not still, (
            f"{seed} 里还留着旧编造名 {still} —— 用户裁定（#4571 + 二次「真删」）："
            "改名到 ERP 逐字名 / 删除")
        assert DELETED_PER_AREA["id"] not in {r["id"] for r in seed_rows(text)}, seed


def test_per_area_coverage_loss_is_registered():
    """`per_area` 夹具真删 ⇒ **覆盖损失逐条登记**在相关 case（防「悄悄删掉接地对象」）。"""
    for seed in SEED_FILES:
        assert DELETED_PER_AREA["name"] not in seed_catalog(_seed_text(seed)), seed
    for case_id, case_file in COVERAGE_LOSS_CASES.items():
        text = (REPO / ".github" / "cases" / case_file).read_text(encoding="utf-8")
        assert case_id in text, f"{case_file} 里没有用例 {case_id}"
        assert COVERAGE_LOSS_TEXT in text, (
            f"{case_id}（{case_file}）没有登记「{COVERAGE_LOSS_TEXT}…」这条**覆盖损失** —— "
            "删掉金额接地对象必须逐处登记（用户裁定要求「不许粉饰」）")


# ══════════════════════════ 红证：注入式自证 ══════════════════════════

def _inject_price(text: str, item_id: str, new_price: str) -> str:
    """把某条夹具行的 `unit_price` 改掉（该字段紧邻 `'米'` 单位字面量）。"""
    pattern = (r"(\('" + re.escape(item_id) + r"',.*?)(\d+\.\d+)(,\s*'米')")
    # ⚠️ 替换必须用 lambda：`r"\1" + "9.99" + r"\3"` 会拼成 `\19.99\3`，
    # 正则把 `\19` 读成第 19 个捕获组 ⇒ `invalid group reference`（本判据自己踩过）。
    injected, count = re.subn(pattern, lambda m: m.group(1) + new_price + m.group(3),
                              text, count=1, flags=re.S)
    assert count == 1, f"注入失败：没定位到 {item_id} 的 unit_price"
    return injected


def _append_row(text: str, record: dict) -> str:
    """把一条行加回**最后一段 `processing_items` INSERT** 的 `VALUES` 末尾。

    ⚠️ **不许**用「全文第一个 `ON CONFLICT (id) DO NOTHING;`」定位：种子里
    `processing_categories` 的 INSERT 排在 `processing_items` **之前** ⇒ 会把行加到**别的表**上。
    """
    statements = list(_INSERT_RE.finditer(text))
    assert statements, "注入失败：文本里没有 `INSERT INTO processing_items` 段"
    last = statements[-1]
    tail = re.search(r"\nON\s+CONFLICT\s*\(id\)\s*DO\s+NOTHING\s*;\s*$", last.group(0), re.I)
    assert tail, "注入失败：最后一段 processing_items INSERT 末尾不是 `ON CONFLICT (id) DO NOTHING;`"
    values = [f"'{record['id']}'", "1", f"'{record['name']}'", f"'{CATEGORY_ID}'",
              f"'{record['pricing_method']}'", str(record["unit_price"]), f"'{record['unit']}'",
              "1", "999", "'注入行（红证）'", "NULL", "'[]'::jsonb", "TRUE", "'active'", "0"]
    row = "\n  (" + ", ".join(values) + ")"
    cut = last.start() + tail.start()
    return text[:cut] + "," + row + text[cut:]


def _catalog_or_none_on_fail(text: str):
    """解析结果；解析 fail-closed 报错 ⇒ `None`（同样是「读得出差异」的一种形态）。"""
    try:
        return seed_catalog(text)
    except AssertionError:
        return None


def test_parsers_detect_injected_drift():
    """在**真实种子/V83 文本**上注入一处 ⇒ 解析函数/判据必须**读得出差异**。"""
    v83_text = _v83_text()
    source = v83_catalog(v83_text)
    assert source == EXPECTED_HINTS, "起点就不等 ⇒ 先修 V83 或本文件的对照表"

    for seed in SEED_FILES:
        text = _seed_text(seed)
        base = seed_catalog(text)
        assert base == {name: EXPECTED_HINTS[name] for name in PRICED_FIXTURES}, \
            f"{seed} 的起点不是那 3 条带价夹具：{sorted(base)}"

        # ① 改名字（`打孔` → `打洞`）⇒ 读得出
        renamed = seed_catalog(text.replace("('pi_eval_punch', 1, '打孔'",
                                            "('pi_eval_punch', 1, '打洞'", 1))
        assert renamed != base and "打洞" in renamed, f"{seed}: 改名字读不出差异"

        # ② 改价（8.00 → 9.99）⇒ 读得出（判据 b 不是空断言）
        repriced = {r["name"]: r["unit_price"]
                    for r in seed_rows(_inject_price(text, "pi_eval_punch", "9.99"))}
        assert repriced["打孔"] == 9.99 != PRICED_FIXTURES["打孔"][1], \
            f"{seed}: 改价读不出差异（{repriced['打孔']}）"

        # ③ **删掉那行 DELETE** ⇒ 去冲突判据必须红（判据 d 不是空断言）
        assert deconflict_delete(text) is not None, f"{seed}: 起点就没有 DELETE"
        without_delete = re.sub(r"DELETE\s+FROM\s+processing_items.*?;", "", text,
                                count=1, flags=re.S | re.I)
        assert deconflict_delete(without_delete) is None, f"{seed}: 删掉 DELETE 读不出差异"

        # ④ **重新插一行 V83 已种的名字**（重演真库那个 32 行/重名形态）⇒ 判据 c 必须红
        for name in V83_ONLY[:3]:
            re_seeded = seed_catalog(_append_row(text, {
                "id": f"pi_eval_cat_{name}", "name": name, "pricing_method": "per_meter",
                "unit_price": 0, "unit": "米"}))
            assert name in re_seeded, f"{seed}: 重新插 V83 已种的名字 {name} 读不出差异"
            assert set(re_seeded) & set(V83_ONLY), f"{seed}: 重名对没被读出来"
            assert set(re_seeded) != set(PRICED_FIXTURES), f"{seed}: 重名对没被读出来"

        # ⑤ 把旧编造名加回来 ⇒ 判据「旧名已删」必须红
        for index, old_name in enumerate(OLD_FABRICATED_NAMES, start=1):
            re_added = _catalog_or_none_on_fail(_append_row(text, {
                "id": f"pi_eval_reinjected_{index:02d}", "name": old_name,
                "pricing_method": "per_meter", "unit_price": 8, "unit": "米"}))
            assert re_added is not None and old_name in re_added, \
                f"{seed}: 把旧编造名 {old_name} 加回来读不出差异"

        # ⑥ 去掉 `craft_hint` 列 ⇒ 字段数 ≠ 列数 ⇒ 整段读不出行 ⇒ **直接报错**（fail-closed）
        try:
            seed_catalog(text.replace("description, craft_hint, options",
                                      "description, options", 1))
        except AssertionError:
            pass
        else:                                        # pragma: no cover - 走到这里说明判据失效
            raise AssertionError(f"{seed}: 去掉 `craft_hint` 列后解析器没有 fail-closed")

    # ⑦ **真实 V83** 上注入一处漂移也必须读得出（样本自证不替代真文件）
    assert v83_catalog(v83_text.replace("'韩褶'::varchar(16)", "'打孔'::varchar(16)", 1)) != source, \
        "在真实 V83 上改一个 craft_hint 读不出差异"
    drifted = v83_catalog(v83_text.replace("'打孔'::text", "'打洞'::text", 1))
    assert drifted != source, "在真实 V83 上改一个 name 读不出差异"
    # ⚠️ 对照的是 **V83 自己的基线**（`EXPECTED_HINTS`），不是种子：裁定后种子只带 3 条
    # 带价夹具，其余 13 项由 V83 提供 ⇒ 「V83 漂了」只能由判据 e 在 V83 上读出。
    assert "打洞" in drifted and "打孔" not in drifted, \
        f"V83 改名后读出的集合不对：{sorted(set(drifted) ^ set(source))}"
    assert sorted(set(drifted) - set(EXPECTED_HINTS)) == ["打洞"], \
        "V83 漂了名字 ⇒ 判据 e 必须把多出的名字报出来（对照表 = EXPECTED_HINTS）"


def test_parser_is_not_vacuous_on_the_real_files():
    """**防空跑**：解析器在真实文件上必须真的读出「3 条带价夹具」与「V83 的 16 项」。"""
    for seed in SEED_FILES:
        text = _seed_text(seed)
        rows = seed_rows(text)
        assert {record["name"] for record in rows} == set(PRICED_FIXTURES), \
            sorted(record["name"] for record in rows)
        assert deconflict_delete(text) is not None, seed
        # 运行期自检块必须在种子里（静态判据看不见 SQL 执行结果 ⇒ 那一半靠它 fail-fast）
        assert "GROUP BY name HAVING count(*) > 1" in text, (
            f"{seed} 缺少**运行期**去冲突自检块（`GROUP BY name HAVING count(*)>1`）—— "
            "静态守卫不执行 SQL（#4514 同族），运行期那一半必须有")
    assert len(v83_catalog(_v83_text())) == 16
