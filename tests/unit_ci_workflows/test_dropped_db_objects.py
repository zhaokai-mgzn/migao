# case_ids: MC-012
"""issue #5245 A 组：「**删干净**」的三面证明 —— 每个被删对象的三面各有一条**会红**的判据。

## 三面（本单的验收口径：把任一面加回去 ⇒ 红）

| 面 | 判据 | 落点 |
|---|---|---|
| ① **建库脚本** | **解析后的 DDL** 里不再有该对象（建表 / 建列） | `tests/unit_ci_workflows/_sql_schema.py`（共用解析件） |
| ② **新迁移** | `V126__drop_zombie_db_objects.sql` 里有对应的**幂等 DROP** | 该迁移文本 |
| ③ **全仓生产源码** | Java main / ai-agent app / admin-web src **零访问路径引用** + 实体/Mapper 已删 | 结构化扫描（见下） |

被删对象（issue #5245 用户裁定）：
`processing_items.per_meter_quantity`（A1）/ `orders.stock_deducted`（A2）/
`orders.payment_status`（A3）/ `production_option_routings` + `production_option_factors`（A4）/
`processing_rules`（A5）；另加 C1：**不删列**，只在 V126 里用 `COMMENT ON COLUMN` 纠正 V51 的陈旧注释。

## ⚠️ 面 ① 必须**看解析后的 DDL**，不能裸 grep 文件

本仓要求「删了要留说明」⇒ 建库脚本里每个被删对象都有一条**解释为什么删**的注释
（这是记录，不是残留）。裸 grep 会把那些注释判成「对象还在」，只剩两条坏路：
删注释（丢掉记录）或把注释特例掉（丢掉严格性）。
⇒ 本文件的负控断言：往脚本文本里追加一条**只提名字的注释** ⇒ 判据必须仍**绿**；
而把同一个对象作为**活的 DDL** 加回去 ⇒ 必须**红**（两个方向都钉住）。

## ⚠️ 面 ③ 的口径（如实登记边界 —— 判**访问路径**，不判散文）

「零引用」判在**生产源码树**上：`backend/admin-api/src/main/java/**`、
`backend/ai-agent-service/app/**`、`frontend/admin-web/src/**`，且**先剥注释**，再按对象分档：

| 对象类 | 什么算「引用」 | 为什么 |
|---|---|---|
| 被删的**列** | 列名本身（SQL 名 `per_meter_quantity` + 驼峰名 `perMeterQuantity`）**任何**出现 | 列名就是访问路径（实体字段 / DTO 键 / SQL 列），没有「只是提到」的正当形态 |
| 被删的**表** | **SQL 子句上下文**（`FROM`/`JOIN`/`INSERT INTO`/`UPDATE`/`DELETE FROM`/`ALTER TABLE`/`DROP TABLE`）与 `@TableName("…")` 挂载 | 表名可以合法地出现在**归因证据**里 |
| 已退场的 **Java 类型** | `ProductionOptionRouting` / `ProductionOptionFactor`（读表必然经它们）**任何**出现 | 悬空映射 = 「能编译、一跑就报错」 |

**散文提及（注释、诊断消息串）不算引用**，这是**有意**的：本仓要求「删了要留记录」——
`MigrationRunner` 的 `KNOWN_BENIGN_LEGACY` 就逐字解释「V72 为何引用 `production_option_factors`
的不存在列」，把它算成「还在读」会逼人删掉归因证据（`migao-dev-flow` §17.3 记下的
「判据被自己的文案喂红」同族）。两个方向都由红证 + 负控钉住。

**不含**测试与用例文本 —— 那些地方**应当**继续提到这些名字（负向断言 `assert "x" not in ...`、
`KNOWN_BROKEN_PUBLISHED` 的理由、真实迁移的历史说明）。
"""
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent

# 共享解析件（issue #5245）：`tests/` 上 sys.path 才能按**包名**导入；直接以脚本运行时也补一次。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from unit_ci_workflows._migration_paths import LIVE_DIR  # noqa: E402
from unit_ci_workflows._sql_schema import (  # noqa: E402
    SCHEMA,
    SchemaParseError,
    parse_created_tables,
    parse_schema_columns,
    parse_schema_columns_strict,
    strip_sql_comments,
)

#: A 组新增的那条迁移（编号由 issue #5245 的补充评论冻结：V126）
V126 = LIVE_DIR / "V126__drop_zombie_db_objects.sql"

#: 被删的列 → 条目号
DROPPED_COLUMNS = {
    ("processing_items", "per_meter_quantity"): "A1",
    ("orders", "stock_deducted"): "A2",
    ("orders", "payment_status"): "A3",
}
#: 被删的表 → 条目号
DROPPED_TABLES = {
    "production_option_routings": "A4",
    "production_option_factors": "A4",
    "processing_rules": "A5",
}
#: C1 的纠正对象（**绝不删**这两列 —— 删了 admin-web 商品页崩）
C1_COLUMNS = ("stock_warning_threshold", "stock_deduction_mode")

#: 生产源码树（面 ③ 的射程）
SOURCE_TREES = (
    REPO / "backend" / "admin-api" / "src" / "main" / "java",
    REPO / "backend" / "ai-agent-service" / "app",
    REPO / "frontend" / "admin-web" / "src",
)
SOURCE_SUFFIXES = {".java", ".py", ".ts", ".tsx", ".js", ".jsx"}
#: 已随表退场的实体 / Mapper（面 ③ 的「对象本体已删」）
RETIRED_CODE_FILES = (
    REPO / "backend/admin-api/src/main/java/com/migao/admin/entity/ProductionOptionRouting.java",
    REPO / "backend/admin-api/src/main/java/com/migao/admin/entity/ProductionOptionFactor.java",
    REPO / "backend/admin-api/src/main/java/com/migao/admin/mapper/ProductionOptionRoutingMapper.java",
    REPO / "backend/admin-api/src/main/java/com/migao/admin/mapper/ProductionOptionFactorMapper.java",
)

ALL_DROPPED = set(DROPPED_TABLES) | {c for _, c in DROPPED_COLUMNS}


# ── 面 ③ 用的源码引用扫描（纯函数 ⇒ 注入式红证复用同一份判据）──────────────────────

def strip_source_comments(text: str, prefixes=("#", "//", "*")) -> str:
    """剥掉源码注释（块注释 + 以注释起始符开头的整行）。

    边界（如实登记）：只处理**整行注释**与块注释 —— 行尾的 `// ...` / `# ...` 不剥
    （剥它需要词法分析，且会把字符串里的 `https://` 误伤）。本仓的引用几乎都在 javadoc 块、
    `//` 整行或 `#` 整行里，实测足够；误判方向是**更严**（把行尾注释算成引用 ⇒ 红），
    不会把真引用放过。
    """
    text = re.sub(r"/\*[\s\S]*?\*/", " ", text)
    return "\n".join(line for line in text.splitlines()
                     if not line.lstrip().startswith(prefixes))


#: 被删的列 → 访问路径标识符（SQL 名 + Java/TS 驼峰名）
DROPPED_COLUMN_IDENTIFIERS = {
    "per_meter_quantity": ("per_meter_quantity", "perMeterQuantity"),
    "stock_deducted": ("stock_deducted", "stockDeducted"),
    "payment_status": ("payment_status", "paymentStatus"),
}
#: 已退场的 Java 类型名（读表必然经它们）
RETIRED_TYPE_NAMES = ("ProductionOptionRouting", "ProductionOptionFactor")


def _table_access_patterns(name: str):
    """被删表的**访问路径**形态（SQL 子句 + `@TableName` 挂载）——散文提及不在此列。"""
    esc = re.escape(name)
    return (
        re.compile(rf"\b(?:FROM|JOIN|INTO|UPDATE|DELETE\s+FROM|ALTER\s+TABLE|DROP\s+TABLE)\s+{esc}\b",
                   re.I),
        re.compile(rf'@TableName\(\s*(?:value\s*=\s*)?"{esc}"', re.I),
    )


def source_references(text: str) -> set:
    """该源码文本里的被删对象**访问路径**引用（注释剥离后）→ 命中说明集合。

    口径见文件头「面 ③」表：列名按标识符判，表名按 SQL/挂载上下文判，类型名按标识符判。
    """
    code = strip_source_comments(text)
    hits = set()
    for col, idents in DROPPED_COLUMN_IDENTIFIERS.items():
        for ident in idents:
            if re.search(rf"\b{re.escape(ident)}\b", code):
                hits.add(f"{col}（列标识符 {ident}）")
    for table in DROPPED_TABLES:
        if any(pat.search(code) for pat in _table_access_patterns(table)):
            hits.add(f"{table}（SQL/挂载上下文）")
    for type_name in RETIRED_TYPE_NAMES:
        if re.search(rf"\b{type_name}\b", code):
            hits.add(f"{type_name}（已退场类型名）")
    return hits


def scan_source_trees(trees=SOURCE_TREES) -> dict:
    """扫生产源码树 → `{文件相对路径: {命中的对象名}}`（只含有命中的文件）。"""
    hits: dict = {}
    for tree in trees:
        assert Path(tree).is_dir(), f"fail-closed：源码树不存在（读了 {tree}）—— 扫描会空转=假绿"
        for f in sorted(Path(tree).rglob("*")):
            if f.suffix not in SOURCE_SUFFIXES or not f.is_file():
                continue
            found = source_references(f.read_text(encoding="utf-8"))
            if found:
                hits[str(f.relative_to(REPO))] = found
    return hits


# ══════════════════════════════════════════════════════════════════════════════════
# 自检 + 面 ①（建库脚本）
# ══════════════════════════════════════════════════════════════════════════════════

def test_face1_parser_is_non_trivial_and_strict():
    """自检：解析件真的产出了表/列（否则面 ① 空转 = 假绿），且**严格入口**会 fail-closed。"""
    columns = parse_schema_columns_strict()
    assert len(columns) >= 30, f"建库脚本只解析出 {len(columns)} 张表 —— 解析疑似失效"
    assert "orders" in columns and "order_no" in columns["orders"], \
        "解析结果里没有已知存在的表/列 ⇒ 解析器坏了（不是对象被删了）"
    with pytest.raises(SchemaParseError, match="fail-closed"):
        parse_schema_columns_strict("-- 只有注释，没有任何 CREATE TABLE\n")


def test_face1_dropped_tables_absent_from_build_script():
    """面 ①-a：三张被删的表**不再由建库脚本建出**（看解析结果，不看文本）。"""
    tables = parse_created_tables()
    still = sorted(t for t in DROPPED_TABLES if t in tables)
    assert not still, (
        f"建库脚本仍在建这些已裁定的删表：{still}（issue #5245 A4/A5）——"
        f"新建库会照样把它们建出来，僵尸对象从后门回来。"
        f"（判据看的是**解析后的 DDL**；注释里提到不算 —— 见负控用例）")


def test_face1_dropped_columns_absent_from_build_script():
    """面 ①-b：三个被删的列**不再由建库脚本建出**。"""
    columns = parse_schema_columns_strict()
    still = [f"{t}.{c}" for (t, c) in DROPPED_COLUMNS if c in columns.get(t, set())]
    assert not still, f"建库脚本仍在建这些已裁定的删列：{still}（issue #5245 A1/A2/A3）"


def test_face1_judgement_is_ddl_scoped_not_a_comment_grep():
    """面 ① 的**负控 + 正控**（两个方向都钉住）。

    · 负控：往脚本文本里追加**只提名字的注释** ⇒ 判据必须**仍绿**（否则「删了要留说明」这条纪律
      与判据打架，最后一定是判据逼人删掉记录）；
    · 正控：把同一个对象作为**活的 DDL** 加回去 ⇒ 必须**红**（否则面 ① 是空断言）。
    """
    sql = SCHEMA.read_text(encoding="utf-8")

    commented = sql + "\n" + "\n".join(
        f"-- 历史说明：{name} 已由 V126 删除（这里只是记录）"
        for name in sorted(ALL_DROPPED)) + "\n"
    assert parse_created_tables(commented) == parse_created_tables(sql), \
        "注释改变了「建了哪些表」的解析结果 ⇒ 面 ① 会被自己的文案喂红"
    cc = parse_schema_columns(commented)
    for (t, c) in DROPPED_COLUMNS:
        assert c not in cc.get(t, set()), f"注释里的 {t}.{c} 被当成了建列"

    injected = sql + ("\nCREATE TABLE IF NOT EXISTS processing_rules (\n"
                      "    id VARCHAR(64) PRIMARY KEY,\n"
                      "    tenant_id BIGINT NOT NULL REFERENCES tenants(id)\n);\n")
    assert "processing_rules" in parse_created_tables(injected), \
        "把表作为**活 DDL** 加回去却读不出来 ⇒ 面 ① 的判据是空断言（永远不会红）"
    injected_col = sql + "\nALTER TABLE orders ADD COLUMN IF NOT EXISTS stock_deducted BOOLEAN;\n"
    assert "stock_deducted" in parse_schema_columns(injected_col).get("orders", set()), \
        "把列作为**活 DDL** 加回去却读不出来 ⇒ 面 ① 的判据是空断言"


# ══════════════════════════════════════════════════════════════════════════════════
# 面 ②（新迁移里的幂等 DROP）
# ══════════════════════════════════════════════════════════════════════════════════

def _v126_code() -> str:
    assert V126.is_file(), (
        f"fail-closed：找不到 {V126} —— issue #5245 的 A 组删对象必须由**新迁移**（V126）落地，"
        f"只改建库脚本 ⇒ 存量库永远拿不到（台账按文件名整份跳过）")
    return strip_sql_comments(V126.read_text(encoding="utf-8"))


def test_face2_v126_drops_every_object_idempotently():
    """面 ②：每个被删对象都有一条**幂等** DROP（`IF EXISTS`）在 V126 里。"""
    code = _v126_code()
    missing = []
    for table in sorted(DROPPED_TABLES):
        if not re.search(rf"DROP\s+TABLE\s+IF\s+EXISTS\s+{table}\b", code, re.I):
            missing.append(f"DROP TABLE IF EXISTS {table};")
    for (t, c) in sorted(DROPPED_COLUMNS):
        if not re.search(rf"ALTER\s+TABLE\s+{t}\s+DROP\s+COLUMN\s+IF\s+EXISTS\s+{c}\b", code, re.I):
            missing.append(f"ALTER TABLE {t} DROP COLUMN IF EXISTS {c};")
    assert not missing, (
        f"V126（{V126.name}）缺少这些**幂等**删对象语句：\n  " + "\n  ".join(missing)
        + "\n⇒ 存量库拿不到该改动（建库脚本只管新库），僵尸对象在存量库里继续活着。"
          "\n写法：`DROP TABLE IF EXISTS x;` / `ALTER TABLE t DROP COLUMN IF EXISTS c;`"
          "（裸 `DROP` 不幂等 —— 重复执行即报错，见负控用例）。")


def test_face2_bare_drop_would_not_satisfy_the_judgement():
    """面 ② 的负控：**非幂等**写法（裸 `DROP TABLE x` / `DROP COLUMN c`）不得被放行。"""
    bare = "DROP TABLE processing_rules;\nALTER TABLE orders DROP COLUMN stock_deducted;\n"
    assert not re.search(r"DROP\s+TABLE\s+IF\s+EXISTS\s+processing_rules\b", bare, re.I), \
        "裸 DROP TABLE 被当成幂等写法 ⇒ 面 ② 的判据太松（重复执行会报错）"
    assert not re.search(r"ALTER\s+TABLE\s+orders\s+DROP\s+COLUMN\s+IF\s+EXISTS\s+stock_deducted\b",
                         bare, re.I), "裸 DROP COLUMN 被当成幂等写法"


# ══════════════════════════════════════════════════════════════════════════════════
# 面 ③（全仓生产源码零引用 + 实体/Mapper 已删）
# ══════════════════════════════════════════════════════════════════════════════════

def test_face3_zero_references_in_production_source():
    """面 ③-a：生产源码树里**零引用**（注释剥离后）。"""
    hits = scan_source_trees()
    assert not hits, (
        "这些生产源码仍在引用**已删**的 DB 对象（issue #5245 A 组）：\n  "
        + "\n  ".join(f"{f}: {sorted(names)}" for f, names in sorted(hits.items()))
        + "\n⇒ 表/列已物理删除 ⇒ 这类引用在运行时是 `relation/column does not exist`（不是无害的注释）。"
          "\n修法：把读点改到真值源（如 `production_route_rules`），或按产品裁定移除该读点。"
          "\n（射程 = 生产源码树；测试与用例文本**应当**继续提到这些名字，见文件头边界）")


def test_face3_retired_entities_and_mappers_are_gone():
    """面 ③-b：实体 / Mapper 本体已删（「表没了但实体还在」= 只删了一半）。"""
    alive = [str(p.relative_to(REPO)) for p in RETIRED_CODE_FILES if p.exists()]
    assert not alive, (
        f"这些实体/Mapper 仍然存在：{alive} —— 它们的表已被 V126 物理删除 ⇒ "
        f"留着就是「能编译、一跑就报错」的悬空映射")


def test_face3_scanner_can_go_red():
    """面 ③ 的**红证（注入式）**：给扫描器一段含真引用的源码 ⇒ 必须命中。

    没有这条，面 ③ 可能只是「扫描器扫了个空目录」——本仓最忌讳的空断言形态。
    """
    # 红证一：SQL 上下文的表引用
    assert any("production_option_routings" in h for h in source_references(
        'String q = "SELECT 1 FROM production_option_routings";\n')), \
        "SQL 里的表引用没被抓到 ⇒ 面 ③ 是空断言"
    # 红证二：`@TableName` 挂载
    assert any("production_option_factors" in h for h in source_references(
        '@TableName("production_option_factors")\npublic class Ghost {}\n')), \
        "`@TableName` 挂载没被抓到 ⇒ 面 ③ 漏掉「实体还挂着已删表」这一形态"
    # 红证三：列标识符（驼峰形态也算）
    assert any("per_meter_quantity" in h for h in source_references(
        "    private BigDecimal perMeterQuantity;\n")), "驼峰列标识符没被抓到"
    # 红证四：已退场的类型名
    assert any("ProductionOptionRouting" in h for h in source_references(
        "public interface Ghost extends BaseMapper<ProductionOptionRouting> {}\n")), \
        "已退场类型名没被抓到 ⇒ 悬空映射会溜过"

    # 负控（有意为之的边界）：散文提及 —— 注释与**诊断消息串** —— 不算引用
    prose = ("// 曾经读 production_option_routings，现已改读 production_route_rules\n"
             "new BenignLegacy(\"V76\", List.of(\"42703:f.sort_order\"),\n"
             "    \"引用不存在的列 f.sort_order（production_option_factors 自 V59 建表起就没有该列）\")\n")
    assert source_references(prose) == set(), (
        "散文提及被当成引用 ⇒ 面 ③ 会逼人删掉归因证据（`MigrationRunner` 的 "
        "`KNOWN_BENIGN_LEGACY` 逐字解释 V72 为何引用旧表的不存在列）——假红比没有守卫更糟")
    # 反向自检：生产树真的被读到了（不是「目录不存在 ⇒ 空集 ⇒ 绿」）
    assert all(Path(t).is_dir() for t in SOURCE_TREES), f"源码树缺失：{SOURCE_TREES}"


# ══════════════════════════════════════════════════════════════════════════════════
# C1：不删列，只纠正 V51 的陈旧注释
# ══════════════════════════════════════════════════════════════════════════════════

def test_c1_comment_correction_present_and_columns_survive():
    """C1：`COMMENT ON COLUMN` 纠正 V51 的「无消费方」注释，且**两列都不删**。

    已发布迁移（V51）逐字节冻结 ⇒ 纠正只能落在新迁移的 COMMENT 上（DB 注释是可被 `\\d+`
    看到的真值面）。判据双向：**必须写**纠正 ∧ **必须不删**这两列。
    """
    code = _v126_code()
    for col in C1_COLUMNS:
        assert re.search(rf"COMMENT\s+ON\s+COLUMN\s+products\.{col}\s+IS", code, re.I), (
            f"V126 没有为 products.{col} 写 COMMENT ON COLUMN —— V51 的「无消费方」注释"
            f"（与代码事实相反）就还挂在库里")
        assert not re.search(rf"DROP\s+COLUMN\s+(?:IF\s+EXISTS\s+)?{col}\b", code, re.I), (
            f"V126 删掉了 products.{col} —— C1 明文「列本身绝不删」（admin-web 商品页在读它）")
    # 列仍在建库脚本里（终态面：删列是 A1/A2/A3 的事，与 C1 的两列无关）
    columns = parse_schema_columns_strict()
    for col in C1_COLUMNS:
        assert col in columns["products"], f"products.{col} 不在建库脚本里（C1 明文不得删）"
    assert "无消费方" not in code or "为假" in code, (
        "V126 的注释文案必须**明确否证** V51 的「无消费方」，而不是复述它")