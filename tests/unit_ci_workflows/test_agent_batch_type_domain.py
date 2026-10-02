# case_ids: MC-069
"""**批次资源的取值白名单 ⊆ DB 约束** 的类级元守卫（issue #6044 缺陷 A，铁律 8）。

## 病（2026-10-02 B 端真实 LLM 评测实测）

米宝的「批量库存调整」在真库上**从未成功过一次**：

```
[admin-api] Caused by: org.postgresql.util.PSQLException: ERROR: new row for relation "agent_batches"
            violates check constraint "ck_agent_batch_type"
            详细：Failing row contains (3992547c-…, 1, inventory_stock, preview, 1, 0, 0, user_admin_001, …)
```

代码侧（issue #5950）已经能写 `batch_type='inventory_stock'` / `field='stock'`，而 V127 建的两条 CHECK
**只有两个值**（`product_price` / `product_status`、`basePrice` / `status`）—— 真库只读实测：

```
ck_agent_batch_type       | CHECK (batch_type = ANY (ARRAY['product_price','product_status']))
ck_agent_batch_item_field | CHECK (field      = ANY (ARRAY['basePrice','status']))
```

⇒ **「代码写入的取值集合 ⊆ DB 约束允许的取值集合」这条判据当时不存在**。它一旦存在，
「加一个新批量类型却忘了改约束」的瞬间就会红，而不是等真实评测撞 500 才发现。

## 本文件钉什么（四条，每条都能单独变红）

| # | 判据 | 取法 | 红证（`test_injected_bad_corpora_are_named`） |
|---|---|---|---|
| 1 | **值域 ⊆ 白名单**：Java `AgentBatchService` 的 `TYPE_*` 常量值 ⊆ `ck_agent_batch_type` 允许值；`field` 值域（`TYPE_FIELD` 里引用的 `FIELD_*` 常量）⊆ `ck_agent_batch_item_field` 允许值 | 纯静态解析两边文本 | 约束里删掉 `inventory_stock` ⇒ 红并具名 |
| 2 | **两条终态一致**：迁移链重放出的终态白名单 == `schema.sql` 的终态白名单（两条约束各判一次） | 重放 `V*` 的 `DROP/ADD CONSTRAINT` | 任一侧少一个值 ⇒ 红（全新安装 vs 迁移态漂移） |
| 3 | **fail-closed**：两个来源的取值集合解析为空 / 变量名解析不出字面量 / 约束在两处都不存在 ⇒ **一律判红**（不许读成「没问题」） | 同上 | 空集合 / 缺约束 ⇒ 红 |
| 4 | **负控**：只改与白名单无关的 Java 注释 / 只在注释里提一个没放行的取值 ⇒ **不红** | 同上 | `java_code()` 剥注释后不命中 |

## 为什么是纯静态（硬约束）

CI job `ci workflow helper unit tests` **只装 `pytest` + `pyyaml`** ⇒ 本文件**零** ai-agent 依赖、
零真库、零网络（自证 = `test_this_judgement_is_pure_static_and_never_skips`，AST 取 import 名）。
行为面（真库能不能落行）由 `backend/admin-api/src/test/java/com/migao/admin/migration/AgentBatchMigrationTest.java`
与 `AgentBatchServiceTest` 承担；本文件承担的是**类级**那一半：让「加类型忘改约束」进不来。

## 边界（照实登记，§19.1）

- 判据只认**落码形态**：Java `public static final String TYPE_x = "…";` 与
  `Map.of(TYPE_a, FIELD_b, …)`；经由**其它表达式**（拼接、枚举、反射、配置文件）派生的取值不在射程内
  （本仓没有这种写法，出现时也不会有东西提醒）。
- `schema.sql` 是**基线**（新建库路径），迁移链是**存量库路径** ⇒ 判据 2 只对账这两者；
  **归档链**（`db/migration-archive/`）有意不看（V127 已冻结在指纹账本里，且它的值被本迁移显式重建）。
- 它判不了「白名单**该**有哪些值」（那是产品口径）；判不了真库现状（那是真库判据的事）。
- 本判据**不改**任何门禁的通过条件、不新增豁免。
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from unit_ci_workflows._source_parsing import java_code  # noqa: E402
from unit_ci_workflows._sql_schema import strip_sql_comments  # noqa: E402

SERVICE_REL = "backend/admin-api/src/main/java/com/migao/admin/service/AgentBatchService.java"
SERVICE = REPO_ROOT / SERVICE_REL
#: `FIELD_*` 的词表真值源（`AgentBatchService` 的 `FIELD_*` 是**别名**：`= AgentWriteValues.FIELD_*`）。
FIELD_VALUES_REL = "backend/admin-api/src/main/java/com/migao/admin/service/AgentWriteValues.java"
FIELD_VALUES = REPO_ROOT / FIELD_VALUES_REL
SCHEMA = REPO_ROOT / "backend/admin-api/src/main/resources/db/init/schema.sql"
MIGRATION_DIR = REPO_ROOT / "backend/admin-api/src/main/resources/db/migration"

#: 两条约束各自的「值域」定义（表 → 约束名 → 列名）。
BATCH_TYPE_CONSTRAINT = "ck_agent_batch_type"
BATCH_ITEM_FIELD_CONSTRAINT = "ck_agent_batch_item_field"
CONSTRAINTS = {
    BATCH_TYPE_CONSTRAINT: ("agent_batches", "batch_type"),
    BATCH_ITEM_FIELD_CONSTRAINT: ("agent_batch_items", "field"),
}

#: Java 侧取值来源（两侧都点名，改名时判据会红而不是静默漏掉）。
TYPE_CONSTANT_PREFIX = "TYPE_"
FIELD_CONSTANT_PREFIX = "FIELD_"
TYPE_FIELD_MAP = "TYPE_FIELD"

_CONST_DECL = re.compile(
    r'public\s+static\s+final\s+String\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*"(?P<value>[^"]*)"\s*;')
#: 别名形态：`public static final String X = Other.X;`（常量**引用**，不是字面量）。
_CONST_ALIAS = re.compile(
    r'public\s+static\s+final\s+String\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*'
    r'(?P<target>[A-Za-z_][A-Za-z0-9_]*)\s*;')
_MAP_OF_BLOCK = re.compile(r"Map\.of\((.*?)\)\s*;", re.DOTALL)
_IDENT = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")
_CHECK_IN = re.compile(r"CHECK\s*\(\s*{col}\s+IN\s*\(([^)]*)\)\s*\)")
_VALUE = re.compile(r"'((?:[^']|'')*)'")
_DROP = re.compile(r"DROP\s+CONSTRAINT\s+(?:IF\s+EXISTS\s+)?(?P<name>[A-Za-z_][A-Za-z0-9_]*)")
_ADD = re.compile(r"ADD\s+CONSTRAINT\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)")
_VERSION = re.compile(r"^V(\d+)__")


# ══════════════════════════════════════════════════════════════════════════════
# 一、判据本体（纯函数：输入语料 ⇒ 具名问题清单）
# ══════════════════════════════════════════════════════════════════════════════


def code_values(text: str, aliases: dict[str, str] | None = None) -> dict[str, str]:
    """Java 侧常量的字面量取值（**剥注释**）。

    两段：① 本文件的 `= "…"` 字面量；② 本文件的 `= Other.X;` **别名**，用 `aliases`
    （= 词表真值源 `AgentWriteValues` 的字面量表）解析掉。
    🔴 必须解析别名：`AgentBatchService` 的 `FIELD_*` 全是别名（单一源在 `AgentWriteValues`），
    不解析就会把 `field` 值域读成空集 ⇒ 判据 fail-closed 判红（那是判据的缺陷，不是代码的）。
    """
    code = java_code(text)
    values = {m.group("name"): m.group("value") for m in _CONST_DECL.finditer(code)}
    table = dict(aliases or {})
    table.update(values)
    for m in _CONST_ALIAS.finditer(code):
        if m.group("target") in table:
            table.setdefault(m.group("name"), table[m.group("target")])
    return table


def type_domain(constants: dict[str, str]) -> set[str]:
    """代码写入的 `batch_type` 值域 = `TYPE_*` 常量的字面量集合。"""
    return {value for name, value in constants.items() if name.startswith(TYPE_CONSTANT_PREFIX)}


def field_domain(java_text: str, constants: dict[str, str]) -> set[str]:
    """代码写入的 `field` 值域 = `TYPE_FIELD` 映射里**引用到的** `FIELD_*` 常量的字面量。

    只取被 `Map.of(...)` 引用的那批 —— 一个声明了却没用上的 `FIELD_*` 不构成写入值域。
    """
    code = java_code(java_text)
    block = _MAP_OF_BLOCK.search(code)
    if block is None:
        return set()
    names = {n for n in _IDENT.findall(block.group(1)) if n.startswith(FIELD_CONSTANT_PREFIX)}
    return {constants[n] for n in names if n in constants}


def schema_constraints(schema_text: str) -> dict[str, set[str]]:
    """从建库脚本的**可执行 DDL** 解析两条 CHECK 的允许值（剥注释 ⇒ 说明文字不算定义）。"""
    code = strip_sql_comments(schema_text)
    out: dict[str, set[str]] = {}
    for name, (_, column) in CONSTRAINTS.items():
        pattern = re.compile(_CHECK_IN.pattern.format(col=re.escape(column)), re.IGNORECASE)
        match = pattern.search(code)
        if match is None:
            continue
        out[name] = {v.replace("''", "'") for v in _VALUE.findall(match.group(1))}
    return out


def migration_replay(migrations: dict[str, str]) -> dict[str, set[str]]:
    """按版本号顺序重放活迁移 ⇒ 两条白名单的**终态**。

    只看**可执行 SQL**（剥注释）：回滚段与说明文字是 `-- --` 行，剥掉后不参与重放。
    `DROP` 把该约束置为「不存在」，`ADD CONSTRAINT <名>` 时再取它后面 600 字符里的 `IN (...)`
    —— 这正好复刻「漏了重新 ADD」⇒ 判据 2 会判红。
    """
    ordered = sorted(
        ((m.group(1), name, text) for name, text in migrations.items()
         if (m := _VERSION.match(name))),
        key=lambda item: int(item[0]),
    )
    live: dict[str, set[str]] = {name: set() for name in CONSTRAINTS}
    for _, _, text in ordered:
        code = strip_sql_comments(text)
        for match in _DROP.finditer(code):
            if match.group("name") in live:
                live[match.group("name")] = set()
        for match in _ADD.finditer(code):
            name = match.group("name")
            if name not in CONSTRAINTS:
                continue
            _, column = CONSTRAINTS[name]
            tail = code[match.end():match.end() + 600]
            found = re.search(_CHECK_IN.pattern.format(col=re.escape(column)),
                              tail, re.IGNORECASE)
            live[name] = {v.replace("''", "'") for v in _VALUE.findall(found.group(1))} if found else set()
    return live


def domain_problems(java_text: str, schema_text: str,
                    migrations: dict[str, str],
                    field_values_text: str = "") -> list[str]:
    """四条判据合成一份具名问题清单（空 = 合规）。"""
    out: list[str] = []
    aliases = code_values(field_values_text) if field_values_text else {}
    constants = code_values(java_text, aliases)

    code_types = type_domain(constants)
    code_fields = field_domain(java_text, constants)
    if not code_types:
        out.append(f"解析不出代码侧 `batch_type` 值域（{SERVICE_REL} 里没有 "
                   f"{TYPE_CONSTANT_PREFIX}* 字面量常量）⇒ 判据本身失效（fail-closed）")
    if not code_fields:
        out.append(f"解析不出代码侧 `field` 值域（{SERVICE_REL} 的 {TYPE_FIELD_MAP} 里没有引用 "
                   f"{FIELD_CONSTANT_PREFIX}* 常量）⇒ 判据本身失效（fail-closed）")

    schema = schema_constraints(schema_text)
    replay = migration_replay(migrations)
    for name in CONSTRAINTS:
        if name not in schema:
            out.append(f"`schema.sql` 里找不到 {name} 的 `CHECK (<列> IN (...))`"
                       "（新建库路径失去这条白名单）")
        if not replay.get(name):
            out.append(f"活迁移链重放后 {name} 的允许值集合为空"
                       "（约束缺席、或 DROP 之后没有重新 ADD ⇒ 存量库拿不到白名单）")

    def subset(code_values_set: set[str], db_values: set[str], who: str,
               db_label: str, fix: str) -> None:
        if not code_values_set or not db_values:
            return  # 已在上面按 fail-closed 报过
        missing = sorted(code_values_set - db_values)
        if missing:
            out.append(
                f"🔴 代码写入的取值 {missing} 不在 {db_label} 的白名单里"
                f"（{who} 会直接撞 23514 ⇒ 500）。{fix}")

    subset(code_types, schema.get(BATCH_TYPE_CONSTRAINT, set()),
           f"{SERVICE_REL} 的 {TYPE_CONSTANT_PREFIX}* 常量",
           f"`schema.sql` 的 {BATCH_TYPE_CONSTRAINT}",
           "出口：加一条迁移 DROP + ADD 该约束并纳入这些取值，**同时**同步 schema.sql")
    subset(code_fields, schema.get(BATCH_ITEM_FIELD_CONSTRAINT, set()),
           f"{SERVICE_REL} 的 {TYPE_FIELD_MAP} 引用的 {FIELD_CONSTANT_PREFIX}* 常量",
           f"`schema.sql` 的 {BATCH_ITEM_FIELD_CONSTRAINT}",
           "出口：同上（明细行写不进去 = 同一个请求照样 500）")

    for name in CONSTRAINTS:
        live, base = replay.get(name, set()), schema.get(name, set())
        if live and base and live != base:
            out.append(
                f"`{name}` 两条终态不一致：迁移链重放 = {sorted(live)}，schema.sql = {sorted(base)}"
                f"（少的一侧 = {sorted(live ^ base)}）⇒ 存量库与全新安装两个终态分叉")
    return out


# ══════════════════════════════════════════════════════════════════════════════
# 二、读真语料
# ══════════════════════════════════════════════════════════════════════════════


def migration_texts() -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf8") for p in sorted(MIGRATION_DIR.glob("*.sql"))}


# ══════════════════════════════════════════════════════════════════════════════
# 三、判据
# ══════════════════════════════════════════════════════════════════════════════


def test_code_batch_domains_are_allowed_by_the_db_constraints() -> None:
    """值域 ⊆ 白名单 + 两条终态一致（真语料）。"""
    problems = domain_problems(SERVICE.read_text(encoding="utf8"),
                               SCHEMA.read_text(encoding="utf8"), migration_texts(),
                               field_values_text=FIELD_VALUES.read_text(encoding="utf8"))
    constants = code_values(SERVICE.read_text(encoding="utf8"),
                            code_values(FIELD_VALUES.read_text(encoding="utf8")))
    print(f"[MC-069] 代码 batch_type 值域 = {sorted(type_domain(constants))} · "
          f"迁移终态 = {sorted(migration_replay(migration_texts())[BATCH_TYPE_CONSTRAINT])} · "
          f"schema 终态 = {sorted(schema_constraints(SCHEMA.read_text(encoding='utf8'))[BATCH_TYPE_CONSTRAINT])}")
    assert problems == [], "\n".join(problems)


def test_this_judgement_is_pure_static_and_never_skips() -> None:
    """CI 那个 job 只装 `pytest` + `pyyaml` ⇒ 本文件不得 import ai-agent 依赖，也不许有 skip。"""
    forbidden = ("pydantic", "langchain", "langchain_core", "fastapi", "app")
    tree = ast.parse(Path(__file__).read_text(encoding="utf8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    bad = sorted(imported & set(forbidden))
    assert bad == [], f"本判据不得 import {bad}（那个 CI job 装不上 ⇒ 静默 skip = 没跑）"


# ══════════════════════════════════════════════════════════════════════════════
# 四、判别力自证（注入式红证，**内存语料**，不碰工作树）
# ══════════════════════════════════════════════════════════════════════════════

#: 词表真值源（`FIELD_*` 的字面量在这里；`AgentBatchService` 只写别名）。
_GOOD_FIELD_VALUES = (
    "public class AgentWriteValues {\n"
    '    public static final String FIELD_BASE_PRICE = "basePrice";\n'
    '    public static final String FIELD_STATUS = "status";\n'
    '    public static final String FIELD_STOCK = "stock";\n'
    "}\n")

_GOOD_JAVA = (
    "public class AgentBatchService {\n"
    '    public static final String TYPE_PRODUCT_PRICE = "product_price";\n'
    '    public static final String TYPE_PRODUCT_STATUS = "product_status";\n'
    '    public static final String TYPE_INVENTORY_STOCK = "inventory_stock";\n'
    "    public static final String FIELD_BASE_PRICE = AgentWriteValues.FIELD_BASE_PRICE;\n"
    "    public static final String FIELD_STATUS = AgentWriteValues.FIELD_STATUS;\n"
    "    public static final String FIELD_STOCK = AgentWriteValues.FIELD_STOCK;\n"
    "    private static final Map<String, String> TYPE_FIELD = Map.of(\n"
    "            TYPE_PRODUCT_PRICE, FIELD_BASE_PRICE,\n"
    "            TYPE_PRODUCT_STATUS, FIELD_STATUS,\n"
    "            TYPE_INVENTORY_STOCK, FIELD_STOCK);\n"
    "}\n")

_GOOD_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS agent_batches (\n"
    "    batch_type VARCHAR(32) NOT NULL,\n"
    "    CONSTRAINT ck_agent_batch_type\n"
    "        CHECK (batch_type IN ('product_price', 'product_status', 'inventory_stock'))\n"
    ");\n"
    "CREATE TABLE IF NOT EXISTS agent_batch_items (\n"
    "    field VARCHAR(32) NOT NULL,\n"
    "    CONSTRAINT ck_agent_batch_item_field\n"
    "        CHECK (field IN ('basePrice', 'status', 'stock'))\n"
    ");\n")

_GOOD_MIGRATIONS = {
    "V127__create_agent_batches.sql": (
        "CREATE TABLE IF NOT EXISTS agent_batches (\n"
        "    batch_type VARCHAR(32) NOT NULL,\n"
        "    CONSTRAINT ck_agent_batch_type\n"
        "        CHECK (batch_type IN ('product_price', 'product_status')),\n"
        "    CONSTRAINT ck_agent_batch_item_field\n"
        "        CHECK (field IN ('basePrice', 'status'))\n"
        ");\n"),
    "V146__add_inventory_stock_to_agent_batch_type.sql": (
        "BEGIN;\n"
        "ALTER TABLE agent_batches DROP CONSTRAINT IF EXISTS ck_agent_batch_type;\n"
        "ALTER TABLE agent_batch_items DROP CONSTRAINT IF EXISTS ck_agent_batch_item_field;\n"
        "ALTER TABLE agent_batches ADD CONSTRAINT ck_agent_batch_type\n"
        "    CHECK (batch_type IN ('product_price', 'product_status', 'inventory_stock'));\n"
        "ALTER TABLE agent_batch_items ADD CONSTRAINT ck_agent_batch_item_field\n"
        "    CHECK (field IN ('basePrice', 'status', 'stock'));\n"
        "COMMIT;\n"),
}


def _good() -> tuple[str, str, dict[str, str]]:
    return _GOOD_JAVA, _GOOD_SCHEMA, dict(_GOOD_MIGRATIONS)


def _problems(java: str, schema: str, migrations: dict[str, str]) -> list[str]:
    return domain_problems(java, schema, migrations, field_values_text=_GOOD_FIELD_VALUES)


def test_injected_bad_corpora_are_named() -> None:
    """六条坏形态各自判红且**具名**；两条负控不红。"""
    java, schema, migrations = _good()
    baseline = _problems(java, schema, migrations)
    assert baseline == [], f"合规语料不该报红：{baseline}"

    # ① 本单的真实缺陷形态：约束里没有 inventory_stock ⇒ 红且点名该取值 + 两条出口
    bad_schema = schema.replace("'inventory_stock'", "'product_status'")
    problems = _problems(java, bad_schema, migrations)
    assert any("inventory_stock" in p for p in problems), problems
    assert any(BATCH_TYPE_CONSTRAINT in p for p in problems), problems

    # ② 只补 batch_type、忘了明细字段 ⇒ 红（同一个请求的下一次写库照旧 23514）
    bad_field = schema.replace("'basePrice', 'status', 'stock'", "'basePrice', 'status'")
    problems = _problems(java, bad_field, migrations)
    assert any("stock" in p and BATCH_ITEM_FIELD_CONSTRAINT in p for p in problems), problems

    # ③ 迁移里 DROP 了却**没有**重新 ADD ⇒ 终态为空 + 两侧漂移 ⇒ 红
    dropped_only = {"V146__x.sql": "ALTER TABLE agent_batches DROP CONSTRAINT ck_agent_batch_type;\n"}
    problems = _problems(java, schema, dropped_only)
    assert any("为空" in p or "终态" in p for p in problems), problems

    # ④ 迁移与 schema 两条终态分叉（少的一侧具名） ⇒ 红
    divergent = {
        "V127__create_agent_batches.sql": _GOOD_MIGRATIONS["V127__create_agent_batches.sql"],
        "V146__x.sql": ("ALTER TABLE agent_batches DROP CONSTRAINT IF EXISTS ck_agent_batch_type;\n"
                        "ALTER TABLE agent_batches ADD CONSTRAINT ck_agent_batch_type\n"
                        "    CHECK (batch_type IN ('product_price', 'product_status'));\n"),
    }
    problems = _problems(java, schema, divergent)
    assert any("两条终态不一致" in p and "inventory_stock" in p for p in problems), problems

    # ⑤ fail-closed：Java 侧解析不出值域 ⇒ 红（不许读成"没问题"）
    assert _problems("public class X {}\n", schema, migrations), "零命中必须红（判据失效自曝）"

    # ⑥ fail-closed：schema 里两条约束都不见了 ⇒ 红
    assert _problems(java, "SELECT 1;\n", migrations), "约束缺席必须红"

    # ⑦ fail-closed：字段词表的**真值源**缺失（别名解析不出）⇒ 红，不许读成「没问题」
    assert domain_problems(java, schema, migrations, field_values_text="") != [], \
        "词表真值源缺失必须红（别名解析不出 = 判据失效自曝）"

    # ⑧ 负控：只改与白名单无关的**注释**（含在注释里提一个没放行的取值）⇒ 不红
    commented = java.replace("public class AgentBatchService {",
                             '// 说明：这里**不**允许出现 TYPE_LEGACY_DELETE = "legacy_delete";\n'
                             "public class AgentBatchService {")
    assert _problems(commented, schema, migrations) == [], "注释里的取值不算写入值域"
    commented_schema = schema.replace("CREATE TABLE IF NOT EXISTS agent_batches (",
                                      "-- 曾经只有 ('product_price', 'product_status')\n"
                                      "CREATE TABLE IF NOT EXISTS agent_batches (")
    assert _problems(java, commented_schema, migrations) == [], "注释不算约束定义"
