# case_ids: MC-012
"""建库脚本 DDL + Java 实体列 的**单一解析实现点**（issue #5243 / #5245）。

## 为什么抽出来（issue #3570 的教训）

同一件事（「建库脚本里有哪些表 / 哪些列」「Java 实体声明了哪些列」）一旦有**两个实现**，
两套门禁必然口径漂移 —— 本仓最忌讳的形态是「两套门禁各管一摊，谁也没管住真值」。
⇒ 本模块是**唯一实现点**，被三处引用：

| 消费方 | 用途 |
|---|---|
| `tests/unit_ci_workflows/test_schema_integrity.py` | 「建库脚本 ⊇ 迁移链 / Java 实体终态」 |
| `tests/unit_ci_workflows/test_dropped_db_objects.py` | issue #5245 A 组「删干净」的**第 ① 面**（脚本里不再有该对象） |
| `tests/unit_ci_workflows/test_ontology_source_resolves.py` | issue #5245 **B7**：本体 `source` ↔ Java 实体字段 / DB 列 |

## 零依赖

只用 `re` / `pathlib`（**不** import `yaml` / pydantic / `app.*`）—— 必须能在只装
`pytest`(+`pyyaml`) 的 `ci workflow helper unit tests` job 里 import；引了别的依赖就会
**import 失败 ⇒ 静默 skip = 没跑**（本仓明令禁止的形态）。

## ⚠️ 边界（如实登记）

解析是**静态文本**层面的，不是 SQL 引擎：类型/约束/继承（`INHERITS`）/动态 SQL 它一概不懂。
它要回答的问题只有一个 ——「这个表 / 列在**可执行 DDL** 里出现没有」，
所以每条判据都配了注入式红证与**负控**（注释里提到 ⇒ 不许判红）。
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

#: 唯一的一份建库脚本（基线；`migao.migration.init-script` 的默认值）
SCHEMA = REPO / "backend/admin-api/src/main/resources/db/init/schema.sql"
#: Java 实体目录（`@TableName` 挂载点真值面）
ENTITY_DIR = (REPO / "backend" / "admin-api" / "src" / "main" / "java"
              / "com" / "migao" / "admin" / "entity")

_SQL_BLOCK_COMMENT_RE = re.compile(r"/\*[\s\S]*?\*/")
_SQL_LINE_COMMENT_RE = re.compile(r"--[^\n]*")


def strip_sql_comments(sql: str) -> str:
    """剥掉 SQL 注释（块注释 + `--` 行注释）。

    🔴 **必须剥**：本仓要求「删了要留说明」⇒ 建库脚本里每个被删对象都有一条解释性注释。
    不剥注释，任何「对象还在不在」的判据都会把**说明文字**读成**定义** ⇒ 只剩两条坏路：
    删掉注释（丢掉记录）或把注释特例掉（丢掉严格性）。
    """
    return _SQL_LINE_COMMENT_RE.sub(" ", _SQL_BLOCK_COMMENT_RE.sub(" ", sql))


def column_name_of_ddl_line(line: str):
    """从 `CREATE TABLE` 体内的一行解析列名；非列定义返回 None。

    ⚠️ 不能用"首词是关键字就跳过"的写法：`key` 既是 SQL 关键字又是合法列名
    （`user_memories.key VARCHAR(128)`）。首版即因此把该列判为"不存在"，
    产生假缺口。判据改为：**第二个词必须是类型名**，而 `PRIMARY KEY (...)` /
    `UNIQUE (...)` / `CONSTRAINT ...` 的第二个词是 `KEY`/`(` 这类，自然被排除。
    """
    m = re.match(r'\s*"?(\w+)"?\s+(\w+)', line)
    if not m:
        return None
    name, second = m.group(1).lower(), m.group(2).upper()
    if second in {"KEY", "CONSTRAINT", "INDEX", "CHECK", "UNIQUE", "PRIMARY",
                  "FOREIGN", "EXCLUDE", "LIKE", "AS"}:
        return None
    return name


def parse_schema_columns(sql: str | None = None) -> dict:
    """建库脚本 → `{表名: {列名}}`（`CREATE TABLE` 体 + `ALTER TABLE ... ADD COLUMN`）。

    原实现见 `test_schema_integrity.py::TestSchemaCoversMigrationChainColumns._schema_columns`
    （issue #5245 抽成共用件，**逐字搬迁、判据不变**）。
    """
    src = strip_sql_comments(sql if sql is not None else SCHEMA.read_text(encoding="utf-8"))
    tables: dict = {}
    for m in re.finditer(
            r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?\"?(\w+)\"?\s*\(([\s\S]*?)\n\)\s*;",
            src, re.I):
        name, body = m.group(1).lower(), m.group(2)
        cols = set()
        for line in body.splitlines():
            col = column_name_of_ddl_line(line)
            if col:
                cols.add(col)
        tables[name] = cols
    for m in re.finditer(
            r"ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?\"?(\w+)\"?[\s\S]*?;", src, re.I):
        t = m.group(1).lower()
        for cm in re.finditer(
                r"ADD\s+COLUMN\s+(?:IF\s+NOT\s+EXISTS\s+)?\"?(\w+)\"?", m.group(0), re.I):
            tables.setdefault(t, set()).add(cm.group(1).lower())
    return tables


class SchemaParseError(AssertionError):
    """建库脚本解析结果为空（fail-closed）。

    ⚠️ 继承 `AssertionError`：在 pytest 里它就是**判红**，不是 error 之外的第三种状态；
    在脚本里它是异常 —— 两条路都**不会**把「解析不到」读成「通过」。
    """


def parse_schema_columns_strict(sql: str | None = None, *, path: Path | None = None) -> dict:
    """`parse_schema_columns` 的**严格入口**：零表 / 零列 ⇒ 抛 `SchemaParseError`。

    为什么必须有它（而不是让每个调用方自己判空）：「解析不到 ⇒ 没得查 ⇒ 绿」正是本体挂载点
    长期无人校验、漂移得以存活的形状（**纪律不是机制** —— 下一个消费者一定会忘）。
    错误消息点名**读了哪个文件**，所以「绿」不可能是「我什么都没读到」的产物。

    需要解析**合成片段**（如注入用小样本）的调用方继续用宽松版 `parse_schema_columns`。
    """
    src_path = Path(path) if path is not None else (SCHEMA if sql is None else None)
    text = sql if sql is not None else src_path.read_text(encoding="utf-8")
    columns = parse_schema_columns(text)
    total = sum(len(v) for v in columns.values())
    if not columns or total == 0:
        raise SchemaParseError(
            f"fail-closed：建库脚本解析出 0 张表 / 0 列 —— 「解析不到」**不**等于「通过」"
            f"（读了：{src_path if src_path is not None else '<内存文本>'}）")
    return columns


def parse_created_tables(sql: str | None = None) -> set:
    """建库脚本 → **建出来的表名集合**（只看 `CREATE TABLE`，不看 ALTER；剥注释）。"""
    src = strip_sql_comments(sql if sql is not None else SCHEMA.read_text(encoding="utf-8"))
    return {m.lower() for m in re.findall(
        r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?\"?(\w+)\"?", src, re.I)}


# ── Java 实体（`@TableName` / `@TableField` / 字段声明）─────────────────────────────

#: 非列字段（MyBatis-Plus 约定 / Java 常量）
SKIP_FIELDS = {"serialVersionUID"}

_ENTITY_TABLE_RE = re.compile(r'@TableName\(\s*(?:value\s*=\s*)?"(\w+)"')
_ENTITY_FIELD_RE = re.compile(
    r'(?:@TableField\(\s*(?:value\s*=\s*)?"(\w+)"[^)]*\)\s*)?'
    r"private\s+[\w<>,\[\]\. ]+\s+(\w+)\s*;")
_TABLE_FIELD_NOT_A_COLUMN_RE = re.compile(
    r"@TableField\([^)]*exist\s*=\s*false[^)]*\)[\s\S]{0,120}?;")


def snake(name: str) -> str:
    """camelCase → snake_case（Java 字段名 → DB 列名的既有约定）。"""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def parse_entities(entity_dir: Path | None = None) -> dict:
    """Java 实体 → `{实体简单名: {"table": 表, "file": 文件名, "fields": {字段: 列}}}`。

    只收有 `@TableName` 的实体（原实现同口径）；`@TableField(exist = false)` 标注的字段
    不是列，先整段抹掉（原实现的 `_SKIP_FIELDS` / exist=false 两条口径都保留）。
    """
    directory = Path(entity_dir) if entity_dir else ENTITY_DIR
    out: dict = {}
    for f in sorted(directory.glob("*.java")):
        src = f.read_text(encoding="utf-8")
        tm = _ENTITY_TABLE_RE.search(src)
        if not tm:
            continue
        cleaned = _TABLE_FIELD_NOT_A_COLUMN_RE.sub("", src)
        fields: dict = {}
        for fm in _ENTITY_FIELD_RE.finditer(cleaned):
            explicit, field = fm.group(1), fm.group(2)
            if field in SKIP_FIELDS:
                continue
            fields.setdefault(field, explicit.lower() if explicit else snake(field))
        out[f.stem] = {"table": tm.group(1).lower(), "file": f.name, "fields": fields}
    return out


def entity_columns(entity_dir: Path | None = None) -> dict:
    """Java 实体 → `{表名: {列名: 'Entity.java#field'}}`（原 `_entities()` 的视图，判据不变）。"""
    out: dict = {}
    for ent in parse_entities(entity_dir).values():
        cols = out.setdefault(ent["table"], {})
        for field, col in ent["fields"].items():
            cols.setdefault(col, f"{ent['file']}#{field}")
    return out