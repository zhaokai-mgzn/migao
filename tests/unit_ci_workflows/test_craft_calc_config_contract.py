"""算料配置**跨源契约**守卫（issue #4528 = 包 E）：五个源必须逐键一致。

## 为什么需要这条（本包的静默失效形态）

算料公式参数的键集被**五处**各自声明，任一处漂移都**不会让别的门禁变红**：

| # | 源 | 漂移后的后果 |
|---|---|---|
| 1 | 算料引擎 `curtain_calc.DEFAULT_CRAFT_CALC_CONFIG`（**真值源**） | —— |
| 2 | 迁移 `V80__create_craft_calc_configs.sql` 的列 | 少一列 ⇒ 该口径**永远存不下来**（商家改了没生效） |
| 3 | `backend/admin-api/src/main/resources/db/init/schema.sql` 的列（bootstrap 终态） | 少一列 ⇒ 新建库缺列 ⇒ 配置端点 500（#3270 形态） |
| 4 | Java 实体 `CraftCalcConfig` 的字段 | 少一个 ⇒ 读回时丢值（静默用默认算） |
| 5 | Java 写面 `CraftCalcConfigService.CONFIG_KEYS` | 少一个 ⇒ PUT 报「缺键」；多一个 ⇒ 收下永不生效的键 |

另有三处**取值**必须同源：褶倍下限红线（Java 护栏 vs 引擎 `MIN_FULLNESS`）、
公式枚举（Java `FORMULAS` vs 引擎 `FORMULA_LABELS` 键集）、
以及**设计文档 §4.2 的提案键 `default_fabric_width` 不得凭空出现在任何一源**
（包 D 的实现里不存在该键 ⇒ 「以实现为准」是本单的开工要求）。

## 红证（逐条可注入）

- 在 V80 里删掉 `hem_margin` 列 ⇒ 判据 2 红；
- 在 `schema.sql` 里删掉 `tiers` 列 ⇒ 判据 3 红；
- 在实体里删掉 `metersRoundingStep` 字段 ⇒ 判据 4 红；
- 把 `sideMargin` 字段（或 `CONFIG_KEYS` 的 `"side_margin"`）加回来 ⇒ 判据 4c 红
  （issue #5030：该键已整体退场）；
- 删掉 V112 的 `DROP COLUMN side_margin` ⇒ 判据 4d 红；
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
MIGRATIONS_DIR = REPO / "backend/admin-api/src/main/resources/db/migration-archive"

# ── 迁移文件的**两个**载体目录（issue #5243）—— 单一事实源 = `_migration_paths.py`
# 共享件（issue #5243）：`tests/` 上 sys.path 才能按**包名**导入；直接以脚本运行时
#（如 `python3 tests/unit_ci_workflows/test_migration_immutability.py --write-ledger`）
# 包不在路径上，故显式补一次 —— 两种入口都要能跑。
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))
from unit_ci_workflows._migration_paths import LIVE_DIR as _LIVE_MIGRATION_DIR, migration_files as _migration_files
from unit_ci_workflows._source_parsing import (  # noqa: E402  （#5323 收敛：唯一取值口径）
    assigned_mapping_keys,
    java_code,
    java_literals,
)



#: 建表迁移 —— ⚠️ 它**不是**配置列的唯一来源（增量列走新迁移，见 `_migration_config_columns`）
MIGRATION = MIGRATIONS_DIR / "V80__create_craft_calc_configs.sql"
SCHEMA = REPO / "backend/admin-api/src/main/resources/db/init/schema.sql"
ENTITY = REPO / "backend/admin-api/src/main/java/com/migao/admin/entity/CraftCalcConfig.java"
SERVICE = REPO / "backend/admin-api/src/main/java/com/migao/admin/service/CraftCalcConfigService.java"

#: 非配置键的结构列（表范式要求，不参与「配置键集」比对）
STRUCTURAL_COLUMNS = {"id", "tenant_id", "status", "created_at", "updated_at", "deleted"}

#: 多语言注释/文档串（判据 4c 只认**代码**：口径退场要在注释/docstring 里留档说明，本仓惯例）
_TRIPLE = re.compile(r'"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'')
_BLOCK = re.compile(r"/\*[\s\S]*?\*/")
_LINE_COMMENT = re.compile(r"(?:^|\s)(?:\*/?\s*)?(?://|--|#)[^\n]*", re.M)
#: SQL 里还有第三种「散文载体」：**单引号字符串字面量**（`COMMENT ON COLUMN … IS '…'`）。
#: 实测 `backend/admin-api/src/main/resources/db/init/schema.sql` 的 `hem_margin` 列注释里逐字写着「`side_margin` 已随 issue #5030
#: 退场」—— 那是**注释正文**，不是列定义。不排除它 ⇒ 判据**误红**（误红即坏断言）。
_SQL_STRING = re.compile(r"'(?:[^']|'')*'")


def _code_only(path: Path) -> str:
    """去掉注释 / 文档串 / SQL 字符串字面量 —— 判据 4c 只判**代码**里的标识符。

    ⚠️ 不用「按行前缀过滤」那种弱形态：实测 `schema.sql` 的多行 `COMMENT ON` 续行、
    字符串字面量，以及 `curtain_calc.py` 的 **docstring** 都不以 `--`/`#` 开头
    ⇒ 弱过滤会**误红**（误红即坏断言，`migao-acceptance`）。
    """
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".sql":
        # SQL：先剔 `--` 注释行与单引号字面量（**列定义行**不含单引号 ⇒ 真复活仍会被抓到）
        text = "\n".join(l for l in text.split("\n") if not l.strip().startswith("--"))
        text = _SQL_STRING.sub("", text)
        return _BLOCK.sub("", text)
    out = _TRIPLE.sub("", text)
    out = _BLOCK.sub("", out)
    return _LINE_COMMENT.sub("", out)


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


#: 配置列可以**分多次迁移**长出：已发布迁移不可改（`MigrationRunner` 按文件名整份跳过 ⇒
#: 改旧文件只对全新库生效，issue #4235）⇒ 新增配置键**必然**落在新迁移里。
#: ⚠️ 分隔符一律 `\s+`（**不是单个空格**）：实测 V110 的 `ALTER TABLE craft_calc_configs`
#: 与 `ADD COLUMN IF NOT EXISTS hem_margin` **分两行** —— 单空格正则读不到 ⇒ 判据 2 假红。
_ALTER_COLUMN_RE = re.compile(
    r"ALTER\s+TABLE\s+craft_calc_configs\s+ADD\s+COLUMN\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)", re.I)
#: 配置列也可以**分多次迁移退场**（issue #5030：`side_margin` 由 **V112** 删列）——
#: 只聚合 `ADD COLUMN` 会把已删的列算成「仍在」（V80 建列 + V112 删列 ⇒ 净结果 = 无）。
#: 与 `ADD` 同族：**按内容聚合**，不写死「哪一份迁移删了哪一列」。
_DROP_COLUMN_RE = re.compile(
    r"ALTER\s+TABLE\s+craft_calc_configs\s+DROP\s+COLUMN\s+(?:IF\s+EXISTS\s+)?(\w+)", re.I)


def _sql_code(sql: str) -> str:
    """去掉 SQL 注释行 —— 迁移文件里**注释掉的** `ALTER TABLE …` 不算真实迁移语句。

    实测（本仓）：V110 的 `-- -- ALTER TABLE craft_calc_configs DROP COLUMN IF EXISTS hem_margin;`
    与 V112 的 `-- ALTER TABLE … ADD COLUMN IF NOT EXISTS side_margin …;` 都是**留档注释**
    ⇒ 不剔掉 ⇒ 聚合出「`hem_margin` 被删了」「`side_margin` 又被加回来了」两个**假事实**（误红即坏断言）。
    """
    text = _BLOCK.sub("", sql)
    return "\n".join(line for line in text.split("\n") if not line.strip().startswith("--"))


def _migration_config_columns() -> set:
    """**迁移链终态**的配置列 = 建表迁移的列 ∪ `ADD COLUMN` − `DROP COLUMN`（按文件名顺序）。

    为什么不只看建表迁移（旧口径）：把来源写死成 `V80` ⇒ 一加键守卫就红，逼人改判据
    （而「改判据」等于自己给自己发通行证）—— 本仓反复踩过的形态。
    为什么还要减去 `DROP COLUMN`（issue #5030）：`side_margin` 由 V80 建、V112 删 ⇒
    只看 `ADD` 会把一个**已不存在**的列算进键集 ⇒ 判据 2 恒红且无法靠真值源修好。
    ⇒ 按**内容**聚合（同族先例：种子守卫按集合聚合，不再写死 V54）；**注释掉的语句不算**（`_sql_code`）。
    """
    cols = _create_table_columns(MIGRATION.read_text(encoding="utf-8"), "craft_calc_configs")
    for path in sorted(_migration_files("V*.sql")):
        code = _sql_code(path.read_text(encoding="utf-8"))
        cols |= {n.lower() for n in _ALTER_COLUMN_RE.findall(code)}
        cols -= {n.lower() for n in _DROP_COLUMN_RE.findall(code)}
    return cols - STRUCTURAL_COLUMNS


def _engine_config_keys_of(src: str) -> list:
    """**纯函数**：引擎 `DEFAULT_CRAFT_CALC_CONFIG` 的键（按源码顺序）。

    `#5323` 第 3 条（**涉钱面**）：旧口径
    `re.search(r"DEFAULT_CRAFT_CALC_CONFIG[^=]*=\\s*MappingProxyType\\(\\{(.*?)\\n\\}\\)")`
    + `re.findall(r'"(\\w+)":')` 在**原文**上取键 ⇒ 该 dict 的**注释**里写一行
    `# "old_key": 弃用` 就被执行成「引擎有该键」⇒ 与 DB 列集对账时**假红**
    （"引擎有键、库里没列"）。现口径 = `ast` 读 dict 字面量键 —— 注释不是 AST 节点。
    """
    return list(assigned_mapping_keys(
        src, "DEFAULT_CRAFT_CALC_CONFIG", "backend/ai-agent-service/app/tools/curtain_calc.py"))


def _engine_config_keys() -> list:
    """引擎 `DEFAULT_CRAFT_CALC_CONFIG` 的键（**真值源**；按源码顺序）。"""
    return _engine_config_keys_of(ENGINE.read_text(encoding="utf-8"))


def _java_list_of(src: str, name: str) -> tuple:
    """**纯函数**：Java `name = List.of(…)` 里的字符串字面量（按源码顺序）；**未声明 ⇒ `()`**。

    先剥 Java 注释（`java_code`，**引号感知**）再取字面量（`java_literals` 词法走查）——
    注释里出现引号键不再被读成声明（`#5323` 第 3 条的 Java 侧，方向同 Python 侧）。
    取字面量**不用**「按引号扫原文」的正则：那种 pattern 本身在注释 / 文档字符串语料上就会命中
    （元守卫 `test_guard_parsing_is_comment_aware.py` 按 **pattern 形态**判，不看它被套在什么文本上）。
    """
    code = java_code(src)
    m = re.search(name + r"\s*=\s*List\.of\(([^;]*?)\);", code, re.S)
    if not m:
        return ()
    return tuple(value for _pos, value in java_literals(m.group(1)))


def _java_service_list(name: str) -> list:
    found = _java_list_of(SERVICE.read_text(encoding="utf-8"), name)
    assert found, f"Java 里找不到 {name}（未声明，或只在注释里声明）"
    return list(found)


def _config_put_keys(method_body: str) -> list:
    """**纯函数**：Java `config.put("k", …)` 的键（按源码顺序）。

    `#5323` 第 3 条：旧口径 `re.findall(r'config\\.put\\("(\\w+)"', body)` 按引号扫原文
    ⇒ 注释里的 `config.put("ghost", …)` 被读成「实体真的发了这个键」（发往引擎的键集**涉钱**）。
    现口径 = 先剥注释（`java_code`）+ 词法取字面量并按**前缀**归属到 `config.put(`。
    """
    return [value for pos, value in java_literals(method_body)
            if method_body[:pos].rstrip().endswith("config.put(")]


def _java_entity_config_fields() -> set:
    """实体字段 → 列名（驼峰转下划线），去掉结构列。"""
    src = ENTITY.read_text(encoding="utf-8")
    fields = re.findall(r"private\s+[\w<>,\[\]\. ]+\s+(\w+)\s*;", src)
    cols = {re.sub(r"(?<!^)(?=[A-Z])", "_", f).lower() for f in fields}
    return cols - STRUCTURAL_COLUMNS


def test_engine_key_set_is_non_trivial():
    """自检：解析真的拿到了键（否则下面全是空跑 = 假绿）。

    ⚠️ **不写死条数**：旧版写死「恰好 9 个」（#4528 时的读数）⇒ 加一个配置键就得改判据，
    而判据一改就等于自己给自己发通行证。⇒ 只断言解析面非空 + 两个锚点键在；
    条数由**真值源**（引擎配置字典）说了算，其余各源与它逐键对齐。
    """
    keys = _engine_config_keys()
    assert len(keys) >= 9, f"引擎配置键解析异常（只拿到 {keys}）"
    assert "per_fold_single" in keys and "meters_rounding_step" in keys


def test_migration_columns_match_engine_keys():
    """判据 2：**迁移链**的配置列 == 引擎配置键（逐键，不多不少）。

    来源 = 建表迁移 ∪ 后续 ALTER 迁移（见 `_migration_config_columns` 的理由）。
    """
    cols = _migration_config_columns()
    assert cols == set(_engine_config_keys()), (
        f"迁移链列与引擎配置键不一致：多 {sorted(cols - set(_engine_config_keys()))} / "
        f"少 {sorted(set(_engine_config_keys()) - cols)}"
    )


def test_schema_sql_columns_match_engine_keys():
    """判据 3：`backend/admin-api/src/main/resources/db/init/schema.sql`（bootstrap 终态）的列 == 引擎配置键。

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
    service_src = java_code(SERVICE.read_text(encoding="utf-8"))
    sm = re.search(r"FORMULAS\s*=\s*Set\.of\(([^)]*)\)", service_src)
    assert sm, "Java 里找不到 FORMULAS"
    java_formulas = {value for _pos, value in java_literals(sm.group(1))}
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


def test_java_to_config_map_matches_engine_keys():
    """判据 4b：实体 `toConfigMap()` 的键集 == 引擎配置键（**发往引擎的那一份**）。

    红证：只加实体字段与 `CONFIG_KEYS`、忘了 `toConfigMap` ⇒ 商家改的值**发不出去**
    （引擎回落默认值、界面却显示改过了）⇒ 本断言红。

    ⚠️ **这条判据此前不存在**（#4528 只钉了 `CONFIG_KEYS`）⇒ 上面那种漏法不会被任何门禁抓到。
    """
    src = java_code(ENTITY.read_text(encoding="utf-8"))
    m = re.search(r"toConfigMap\(\)\s*\{(.*?)\n    \}", src, re.S)
    assert m, "实体里找不到 toConfigMap()（改名？那是本判据的定位锚点）"
    keys = _config_put_keys(m.group(1))
    assert keys == _engine_config_keys(), (
        f"toConfigMap 的键与引擎配置键不一致（顺序也须一致）：{keys} vs {_engine_config_keys()}"
    )


def test_java_entity_side_margin_is_gone_everywhere():
    """判据 4c（issue #5030 **改判**）：`side_margin` 在**全仓配置源**里都不得再出现。

    旧判据（#4940）钉的是「实体里 `sideMargin` 的注释不得写『上下卷边』」—— 那是
    「同名不同义」的文案漂移守卫，前提 = **该字段还存在**。
    用户 2026-09-21 裁定（issue #5030，逐字）：「订单这里的**宽和高是窗户的宽高**」⇒
    成品宽 = 净窗宽 ⇒ 常量 `SIDE_MARGIN` 与配置键 `side_margin` **整体退场**
    ⇒ 旧判据的前提消失，**改判为反向守卫**（不留一条不会红的空断言）。

    判据面（**逐文件**，少一个 = 那一源永久免检且无人知）：
    引擎常量/配置字典、`schema.sql`、Java 实体字段、`CONFIG_KEYS`、前端键集。

    红证：把 `sideMargin` 字段（或 `CONFIG_KEYS` 里的 `"side_margin"`、前端
    `types/index.ts` 的该键）加回任一源 ⇒ 红。
    ⚠️ **迁移链**（`db/migration/**`）有意不在判据面里：V80 建列、V112 删列是**历史留档**
    （已发布迁移不可改，issue #4235）⇒ 终态由 `test_migration_columns_match_engine_keys` 判。
    """
    sources = {
        "引擎常量/配置字典": ENGINE,
        "schema.sql": SCHEMA,
        "Java 实体": ENTITY,
        "Java 写面 CONFIG_KEYS": SERVICE,
        "前端键集": REPO / "frontend/admin-web/src/types/index.ts",
    }
    hits: list[str] = []
    for label, path in sources.items():
        assert path.exists(), f"被判据引用的文件不存在：{path}（路径漂移 ⇒ 红，不得静默跳过）"
        code = _code_only(path)
        for ident in ("SIDE_MARGIN", "side_margin", "sideMargin"):
            if ident in code:
                hits.append(f"{label}（{path.relative_to(REPO)}）的代码里出现 `{ident}`")
    assert hits == [], (
        "宽方向余量（常量 `SIDE_MARGIN` / 配置键 `side_margin`）已按用户 2026-09-21 裁定"
        "（issue #5030）**整体退场** —— 它一旦回到任一源，`用料 = 窗宽 × 褶倍` 这条 R1 口径"
        "就被静默破坏（成品宽 ≠ 净窗宽 = 静默改钱）：\n  " + "\n  ".join(hits)
    )


def test_side_margin_column_is_dropped_by_a_migration():
    """判据 4d：`side_margin` 列**真的**被迁移删掉（否则存量库永远留着这列）。

    红证：把 V112 删掉（或改成注释）⇒ 迁移链终态里 `side_margin` 复现 ⇒ 本断言红。
    ⚠️ 判据**不写死迁移文件名**（与 `_migration_config_columns` 同族：按内容聚合，
    不写死「哪一份迁移干了这件事」—— 写死文件名会逼下一个人改判据）。
    """
    dropped = set()
    for path in sorted(_migration_files("V*.sql")):
        dropped |= {n.lower() for n in _DROP_COLUMN_RE.findall(_sql_code(path.read_text(encoding="utf-8")))}
    assert "side_margin" in dropped, (
        "迁移链里没有任何 `ALTER TABLE craft_calc_configs DROP COLUMN side_margin` —— "
        "存量库会永远留着这个**没有任何消费者**的列（issue #5030 要求它整体退场）⇒ 红"
    )
    assert "side_margin" not in _migration_config_columns(), (
        "迁移链**终态**里 `side_margin` 仍在（建列迁移没被删列迁移抵消）⇒ 判据 2 会红"
    )


def test_alter_migrations_are_idempotent():
    """判据 8b：后续 ALTER 迁移必须幂等（`ADD COLUMN IF NOT EXISTS`）。

    红证：写成裸 `ADD COLUMN` ⇒ 重复执行报错（`MigrationRunner` 硬要求所有迁移可重复执行）。
    """
    for path in sorted(_migration_files("V*.sql")):
        code = "\n".join(
            line for line in path.read_text(encoding="utf-8").split("\n")
            if not line.strip().startswith("--")
        )
        for m in re.finditer(
            r"ALTER\s+TABLE\s+craft_calc_configs\s+ADD\s+COLUMN\s+([^;]*);", code, re.I
        ):
            assert "IF NOT EXISTS" in m.group(1).upper(), (
                f"{path.name} 的 ADD COLUMN 不是幂等的（缺 IF NOT EXISTS）：{m.group(0)}"
            )


class TestMoneyFacingParsingIsSyntaxBased:
    """`#5323` 第 3 条（**涉钱面**）成对红证：配置键 / 公式串只认**代码里**的声明。"""

    #: 引擎配置字典的真声明（`MappingProxyType({…})` 形态；键顺序 = 源码顺序）。
    REAL_ENGINE = (
        "DEFAULT_CRAFT_CALC_CONFIG: MappingProxyType = MappingProxyType({\n"
        '    "per_fold_single": 2.0,\n'
        '    "tiers": 1,\n'
        "})\n"
    )

    #: 旧口径会读成「引擎有该键」的两个陷阱：dict 内注释 + 模块文档字符串举例（**代码零改动**）。
    COMMENTED_ENGINE = (
        '# "ghost_key": 1,  ← 留档注释：该键已弃用（这不是声明）\n'
        '"""示例（说明文字，不是代码）：\n'
        'DEFAULT_CRAFT_CALC_CONFIG = MappingProxyType({"ghost_key": 1})\n'
        '"""\n' + REAL_ENGINE
    )

    def test_comment_and_docstring_keys_are_not_engine_keys(self):
        """负例：注释 / 文档字符串里的键 ⇒ **不得**被读成引擎配置键（修前此断言必红）。"""
        keys = _engine_config_keys_of(self.COMMENTED_ENGINE)
        assert keys == ["per_fold_single", "tiers"], keys
        assert "ghost_key" not in keys, "注释里的键被读成引擎配置键 ⇒ 与库列集对账假红（涉钱面）"

    def test_real_key_drift_still_reds(self):
        """正例（防修过头）：把键**真**写进 dict ⇒ 读到，且「逐键相等」判据照旧红。"""
        real = set(_engine_config_keys_of(self.REAL_ENGINE))
        assert real == {"per_fold_single", "tiers"}, sorted(real)
        drifted = set(_engine_config_keys_of(
            self.REAL_ENGINE.replace('    "tiers": 1,\n', '    "ghost_key": 1,\n')))
        assert drifted == {"per_fold_single", "ghost_key"}, sorted(drifted)
        assert drifted != real, (
            "真写进 dict 的键读数不变 ⇒ 判据恒真；判据 2（迁移列 == 引擎键）也不会报这次漂移")

    def test_java_comment_declarations_are_not_read(self):
        """负例（Java 侧）：注释里的 `List.of("…")` / `config.put("…")` 不算声明。"""
        commented = (
            "public class S {\n"
            '    // static final List<String> CONFIG_KEYS = List.of("ghost_key");  ← 留档注释\n'
            "    static final List<String> CONFIG_KEYS = List.of(\n"
            '        "per_fold_single",\n'
            '        "tiers");\n'
            "}\n"
        )
        assert _java_list_of(commented, "CONFIG_KEYS") == ("per_fold_single", "tiers")
        assert _java_list_of('    // CONFIG_KEYS = List.of("ghost_key");\n', "CONFIG_KEYS") == (), (
            "只在注释里的 Java 声明被读成了真声明"
        )
        assert _config_put_keys('    // config.put("ghost_key", 1);\n') == [], (
            "注释里的 config.put 被读成了「实体真的发了这个键」（发往引擎的键集涉钱）"
        )

    def test_real_java_declaration_is_read(self):
        """正例（防修过头）：Java 真声明 ⇒ 读到；真删一个键 ⇒ 读数跟着变。"""
        src = (
            "public class S {\n"
            '    static final List<String> CONFIG_KEYS = List.of("per_fold_single", "tiers");\n'
            '    void toConfigMap() { config.put("per_fold_single", a); config.put("tiers", b); }\n'
            "}\n"
        )
        assert _java_list_of(src, "CONFIG_KEYS") == ("per_fold_single", "tiers")
        assert _config_put_keys(src) == ["per_fold_single", "tiers"]
        assert _config_put_keys(src.replace('config.put("tiers", b); ', "")) == ["per_fold_single"], (
            "真删一个 config.put ⇒ 读数不变 ⇒ 判据恒真（空断言）"
        )
