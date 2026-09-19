"""算料配置**跨源契约**守卫（issue #4528 = 包 E）：五个源必须逐键一致。

## 为什么需要这条（本包的静默失效形态）

算料公式参数的键集被**五处**各自声明，任一处漂移都**不会让别的门禁变红**：

| # | 源 | 漂移后的后果 |
|---|---|---|
| 1 | 算料引擎 `curtain_calc.DEFAULT_CRAFT_CALC_CONFIG`（**真值源**） | —— |
| 2 | 迁移 `V80__create_craft_calc_configs.sql` 的列 | 少一列 ⇒ 该口径**永远存不下来**（商家改了没生效） |
| 3 | `docs/sql/schema.sql` 的列（bootstrap 终态） | 少一列 ⇒ 新建库缺列 ⇒ 配置端点 500（#3270 形态） |
| 4 | Java 实体 `CraftCalcConfig` 的字段 | 少一个 ⇒ 读回时丢值（静默用默认算） |
| 5 | Java 写面 `CraftCalcConfigService.CONFIG_KEYS` | 少一个 ⇒ PUT 报「缺键」；多一个 ⇒ 收下永不生效的键 |

另有三处**取值**必须同源：褶倍下限红线（Java 护栏 vs 引擎 `MIN_FULLNESS`）、
公式枚举（Java `FORMULAS` vs 引擎 `FORMULA_LABELS` 键集）、
以及**设计文档 §4.2 的提案键 `default_fabric_width` 不得凭空出现在任何一源**
（包 D 的实现里不存在该键 ⇒ 「以实现为准」是本单的开工要求）。

## 红证（逐条可注入）

- 在 V80 里删掉 `side_margin` 列 ⇒ 判据 2 红；
- 在 `schema.sql` 里删掉 `tiers` 列 ⇒ 判据 3 红；
- 在实体里删掉 `metersRoundingStep` 字段 ⇒ 判据 4 红；
- 在 `CONFIG_KEYS` 里加 `"default_fabric_width"` ⇒ 判据 5 红；
- 把 `MIN_FULLNESS_RED_LINE` 改成 `1.2` ⇒ 判据 6 红；
- 把 `FORMULAS` 改成 `Set.of("pleat")` ⇒ 判据 7 红；
- 在迁移里 `INSERT INTO craft_calc_configs …` 播种 ⇒ 判据 8 红（缺行 = 默认值是本包的口径）。
"""

# case_ids: OR-041

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
ENGINE = REPO / "backend/ai-agent-service/app/tools/curtain_calc.py"
MIGRATION = REPO / "backend/admin-api/src/main/resources/db/migration/V80__create_craft_calc_configs.sql"
SCHEMA = REPO / "docs/sql/schema.sql"
ENTITY = REPO / "backend/admin-api/src/main/java/com/migao/admin/entity/CraftCalcConfig.java"
SERVICE = REPO / "backend/admin-api/src/main/java/com/migao/admin/service/CraftCalcConfigService.java"

#: 非配置键的结构列（表范式要求，不参与「配置键集」比对）
STRUCTURAL_COLUMNS = {"id", "tenant_id", "status", "created_at", "updated_at", "deleted"}


def _create_table_columns(sql: str, table: str) -> set:
    """从 `CREATE TABLE [IF NOT EXISTS] <table> (…)` 块里取列名（跳过表级约束行）。"""
    m = re.search(
        r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?" + re.escape(table) + r"\s*\((.*?)\n\);",
        sql, re.I | re.S)
    assert m, f"{table} 的 CREATE TABLE 块没找到（表被删/改名？）"
    cols = set()
    for line in m.group(1).split("\n"):
        line = line.split("--")[0].strip().rstrip(",")
        if not line:
            continue
        # 只认「列名 + 类型」形态：多行 DEFAULT 的**续行**（以 `'{"standard": …` 开头）
        # 与表级约束（PRIMARY KEY / UNIQUE …）都不匹配 ⇒ 自然被排除。
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*\s+[A-Za-z]", line):
            continue
        first = line.split()[0].lower()
        if first in {"primary", "unique", "constraint", "foreign", "check", "references"}:
            continue
        cols.add(first)
    return cols


def _engine_config_keys() -> list:
    """引擎 `DEFAULT_CRAFT_CALC_CONFIG` 的键（**真值源**；按源码顺序）。"""
    src = ENGINE.read_text(encoding="utf-8")
    m = re.search(
        r"DEFAULT_CRAFT_CALC_CONFIG[^=]*=\s*MappingProxyType\(\{(.*?)\n\}\)", src, re.S)
    assert m, "引擎里找不到 DEFAULT_CRAFT_CALC_CONFIG（改名？那是本守卫的定位锚点）"
    return re.findall(r'"(\w+)":', m.group(1))


def _java_service_list(name: str) -> list:
    src = SERVICE.read_text(encoding="utf-8")
    m = re.search(name + r"\s*=\s*List\.of\(([^;]*?)\);", src, re.S)
    assert m, f"Java 里找不到 {name}"
    return re.findall(r'"(\w+)"', m.group(1))


def _java_entity_config_fields() -> set:
    """实体字段 → 列名（驼峰转下划线），去掉结构列。"""
    src = ENTITY.read_text(encoding="utf-8")
    fields = re.findall(r"private\s+[\w<>,\[\]\. ]+\s+(\w+)\s*;", src)
    cols = {re.sub(r"(?<!^)(?=[A-Z])", "_", f).lower() for f in fields}
    return cols - STRUCTURAL_COLUMNS


def test_engine_key_set_is_non_trivial():
    """自检：解析真的拿到了键（否则下面全是空跑 = 假绿）。"""
    keys = _engine_config_keys()
    assert len(keys) == 9, f"引擎配置键应为 9 个（issue #4528 契约），实测 {keys}"
    assert "per_fold_single" in keys and "meters_rounding_step" in keys


def test_migration_columns_match_engine_keys():
    """判据 2：迁移 V80 的配置列 == 引擎配置键（逐键，不多不少）。"""
    sql = MIGRATION.read_text(encoding="utf-8")
    cols = _create_table_columns(sql, "craft_calc_configs") - STRUCTURAL_COLUMNS
    assert cols == set(_engine_config_keys()), (
        f"V80 列与引擎配置键不一致：多 {sorted(cols - set(_engine_config_keys()))} / "
        f"少 {sorted(set(_engine_config_keys()) - cols)}"
    )


def test_schema_sql_columns_match_engine_keys():
    """判据 3：`docs/sql/schema.sql`（bootstrap 终态）的列 == 引擎配置键。

    红证：只改迁移不同步 schema.sql ⇒ 新建库缺列 ⇒ 配置端点 500（#3270 形态，不是账面问题）。
    """
    cols = _create_table_columns(SCHEMA.read_text(encoding="utf-8"), "craft_calc_configs") - STRUCTURAL_COLUMNS
    assert cols == set(_engine_config_keys()), (
        f"schema.sql 的 craft_calc_configs 列与引擎配置键不一致：多 "
        f"{sorted(cols - set(_engine_config_keys()))} / 少 {sorted(set(_engine_config_keys()) - cols)}"
    )


def test_java_entity_fields_match_engine_keys():
    """判据 4：Java 实体声明的列 == 引擎配置键（少一个 ⇒ 读回时丢值 ⇒ 静默用默认算）。"""
    fields = _java_entity_config_fields()
    assert fields == set(_engine_config_keys()), (
        f"CraftCalcConfig 实体字段与引擎配置键不一致：多 "
        f"{sorted(fields - set(_engine_config_keys()))} / 少 {sorted(set(_engine_config_keys()) - fields)}"
    )


def test_java_config_keys_match_engine_keys():
    """判据 5：写面 `CONFIG_KEYS` == 引擎配置键（PUT 全量替换的键集口径）。"""
    keys = _java_service_list("CONFIG_KEYS")
    assert keys == _engine_config_keys(), (
        f"CONFIG_KEYS 与引擎配置键不一致（顺序也须一致）：{keys} vs {_engine_config_keys()}"
    )


def test_design_doc_proposal_key_absent_everywhere():
    """判据 5b：设计文档 §4.2 的提案键 `default_fabric_width` **不得**出现在任何一源。

    「以代码事实为准」的落点：包 D 的实现里没有这个键（门幅是 `build_quote(fabric_width=…)` 的入参）
    ⇒ 本包不得凭空加一个没有消费者的配置键（issue #4528 开工要求：有出入 ⇒ 以实现为准并登记差异）。
    """
    for path in (MIGRATION, SCHEMA, ENTITY, SERVICE, ENGINE):
        src = path.read_text(encoding="utf-8")
        # 允许出现在注释里（差异登记），但不得出现在**代码**（非注释）行
        code = "\n".join(l for l in src.split("\n") if not l.strip().startswith(("--", "//", "*", "#")))
        assert "default_fabric_width" not in code, f"{path.name} 的代码里出现了提案键 default_fabric_width"


def test_red_line_matches_engine_min_fullness():
    """判据 6：Java 护栏的行业红线 == 引擎 `MIN_FULLNESS` == 引擎默认 `min_fullness`。

    红证：引擎把红线抬到 1.6 而 Java 仍是 1.5 ⇒ 红（商家能存下低于新红线的值）。
    """
    engine_src = ENGINE.read_text(encoding="utf-8")
    m = re.search(r"^MIN_FULLNESS\s*=\s*([\d.]+)", engine_src, re.M)
    assert m, "引擎里找不到 MIN_FULLNESS"
    service_src = SERVICE.read_text(encoding="utf-8")
    red = re.search(r"MIN_FULLNESS_RED_LINE\s*=\s*new BigDecimal\(\"([\d.]+)\"\)", service_src)
    assert red, "Java 里找不到 MIN_FULLNESS_RED_LINE"
    assert red.group(1) == m.group(1), (
        f"行业红线漂移：Java {red.group(1)} vs 引擎 {m.group(1)}"
    )


def test_formula_enum_matches_engine():
    """判据 7：Java `FORMULAS` == 引擎 `FORMULA_LABELS` 的键集（pleat / fullness）。"""
    engine_src = ENGINE.read_text(encoding="utf-8")
    m = re.search(r"FORMULA_LABELS[^=]*=\s*\{(.*?)\n\}", engine_src, re.S)
    assert m, "引擎里找不到 FORMULA_LABELS"
    engine_formulas = set(re.findall(r"(FORMULA_\w+)\s*:", m.group(1)))
    # FORMULA_PLEAT / FORMULA_FULLNESS 的值
    values = set()
    for name in engine_formulas:
        vm = re.search(rf"^{name}\s*=\s*\"(\w+)\"", engine_src, re.M)
        assert vm, f"引擎里找不到 {name} 的字面量"
        values.add(vm.group(1))
    service_src = SERVICE.read_text(encoding="utf-8")
    sm = re.search(r"FORMULAS\s*=\s*Set\.of\(([^)]*)\)", service_src)
    assert sm, "Java 里找不到 FORMULAS"
    java_formulas = set(re.findall(r'"(\w+)"', sm.group(1)))
    assert java_formulas == values, (
        f"公式枚举漂移：Java {sorted(java_formulas)} vs 引擎 {sorted(values)}"
    )


def test_migration_is_idempotent_and_does_not_seed():
    """判据 8：迁移幂等（IF NOT EXISTS）且**不插种子行**。

    口径：缺行 = 用引擎默认值（`source='default'`）—— 播种 = 第二份会漂的默认值。
    """
    sql = MIGRATION.read_text(encoding="utf-8")
    code = "\n".join(l for l in sql.split("\n") if not l.strip().startswith("--"))
    assert "CREATE TABLE IF NOT EXISTS craft_calc_configs" in code
    assert "CREATE UNIQUE INDEX IF NOT EXISTS uk_craft_calc_configs_tenant" in code
    assert not re.search(r"INSERT\s+INTO\s+craft_calc_configs", code, re.I), (
        "迁移里出现了种子 INSERT —— 本包口径是「缺行 = 用引擎默认值」，不做开租播种"
    )
