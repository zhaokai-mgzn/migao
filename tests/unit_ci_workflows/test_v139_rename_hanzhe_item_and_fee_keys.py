# case_ids: PG-044
"""「韩折」→「韩褶」统一（V139，issue 关联本单）的承重判据 + 真库两遍幂等 + **不改价**。

用户裁定原文（2026-09-28，逐字）：「**把加工项和加工费组合里面叫韩折的都改成韩褶**」。

## 本文件钉的事

| 面 | 判据 | 红证方向（怎么写歪会红） |
|---|---|---|
| 形态（静态 ①） | 显式 `BEGIN;` / `COMMIT;`；可执行语句**只写** `processing_items` 与 `processing_fee_combinations` 两张表 | 写语句落到第三张表（含迁移头红线点名的 `order_items` / `processing_fee_combination_versions` / `production_route_rules`）⇒ 写目标集合 != 两张表 ⇒ 红 |
| 列白名单（静态 ②） | `SET` 子句只许：目录表 `name` / `updated_at`；组合表 `items` / `composition_key` / `updated_at` | `SET` 里出现 `unit_price` / `status` / `sort_order` / `source` ⇒ 红（**不许改价**：键跟着改，价与状态一字不动） |
| 排序口径（静态 ③） | `COLLATE "C"` 在位（前置撞键检查 / `items` 规范化 / 终态对账三处都要） | 抹掉 ⇒ 中文按库默认 locale 序（本机 `zh_CN.UTF-8`：`打孔` < `定型` < `韩褶`）排，与 Java `TreeSet` 的**码点序**（`定型` < `打孔` < `韩褶`）不一致 ⇒ 同一组合两个键 ⇒ 红 |
| 真库（④） | 目录那行改名、同名并存行与已软删行不动；组合 `items` 去重 + 码点升序、`composition_key` 重算；三个租户都覆盖 | 谓词丢 `deleted = 0` / 漏去重 / 用 locale 序 ⇒ 逐行终态断言当场红 |
| **不改价**（④） | `unit_price` / `status` / `sort_order` / `source` / `id` **逐值不变**；不含旧名的组合**整行指纹逐字节不变** | 任一列被写 ⇒ 钱/状态投影 before != after ⇒ 红 |
| 幂等（④） | 第二遍净效果相同（存活行 `updated_at` 逐字不变），且第二遍谓词匹配 **0 行** | `updated_at` 被重写 / 第二遍抛 ⇒ 红 |
| 撞键 fail-closed（④） | 同租户里「改名后会同名」的两行 ⇒ 抛异常并**点名租户与那两个键**，**整份回滚** | 不检查 ⇒ 撞 `(tenant_id, composition_key) WHERE deleted = 0` 唯一键报错（消息不可行动）/ 只回滚一半 ⇒ 红 |
| 终态对账有牙（⑤） | 把改名 UPDATE 注释掉（**临时副本**）⇒ 对账必须抛 | 对账是空跑 ⇒ 注释掉也照样绿 ⇒ 红 |

## 🔴 本判据首次真库执行时抓到的**真实缺陷**（2026-09-28，V139 首版，留下当记录）

`ORDER BY 1 COLLATE "C"`（首版三处：前置撞键检查 / `items` 规范化 / 终态对账）在 PG 上是**类型错误**：
`ORDER BY` 里的序号被解析成**整数字面量**，而整数不能带排序规则 ⇒
`错误: 类型integer不能使用排序规则` ⇒ 迁移在**第一条 DO 块**就抛、整份回滚；而 `MigrationRunner`
对非连接类失败是「记日志 + 跳过这一条」⇒ 生产上这次改名**等于没发生**，部署照样 success。
最小复现（PG 16.15 实测，带不带 `DISTINCT` 都一样）：

```bash
psql -c 'SELECT x FROM (VALUES (''a'')) t(x) ORDER BY 1 COLLATE "C";'   # 错误: 类型integer不能使用排序规则
```

**可用**写法（本文件真跑验证过，且与 Java `TreeSet` 的码点序一致；本机默认 locale `zh_CN.UTF-8`
给的是 `打孔/定型/韩褶`，`COLLATE "C"` 给的是 `定型/打孔/韩褶` —— 两序确实不同）：
① `SELECT DISTINCT (expr) COLLATE "C" AS nm … ORDER BY 1`；② 两层子查询 `… ORDER BY nm COLLATE "C"`；
③ 无 `DISTINCT` 时 `ORDER BY e COLLATE "C"`。静态锁 = `_INT_ORDINAL_COLLATE`（真库层由执行判据兜底）。

## 为什么必须真跑

`MigrationRunner` 要求**所有**迁移可重复执行，而「幂等 / fail-closed 的回滚半径 / 同事务原子性」只有真库能判：
两条 `UPDATE` 的谓词与 `deleted` / `jsonb` 的交互、`DO $$ … RAISE EXCEPTION` 是否让**整份**迁移回滚、
`WITH … UPDATE` 与唯一索引的相互作用 —— 都是**运行期**语义（与 V123 同族）。

## 真库判据（本机 PG 二进制；缺则**显式 skip**，不伪装成通过）

照 `tests/unit_ci_workflows/test_v123_retire_join_height_item.py` 的范式（`initdb` / `pg_ctl` / `psql`
起一次性临时集群真跑；二进制一律取 `realdb_binaries` 夹具给的**绝对路径**）。**权威仍在 CI**：
本文件把「迁移在真库上的终态」变成可本地复算的读数。
"""
from __future__ import annotations

import re
import shutil
import socket
import subprocess
import tempfile
from pathlib import Path

import pytest
from unit_ci_workflows import pg_cluster  # noqa: E402  （起/停集群的唯一收口，issue #5263）

REPO = Path(__file__).resolve().parents[2]
MIGRATION_DIR = REPO / "backend/admin-api/src/main/resources/db/migration"
V139 = MIGRATION_DIR / "V139__rename_hanzhe_item_and_fee_keys.sql"

ITEM_TABLE = "processing_items"
COMBO_TABLE = "processing_fee_combinations"
OLD_NAME = "韩折"
NEW_NAME = "韩褶"

#: **红线**：本迁移一字不许写的表（价 / 历史快照 / 工艺 / 版本账 —— 见迁移头注释的「红线」段）
RED_LINE_TABLES = (
    "order_items",                             # 已成交订单的加工项快照（历史事实，不可改写）
    "processing_fee_combination_versions",     # 组合版本账（历史）
    "processing_route_rules",                  # 工艺规则（本来就写「韩褶」）
    "production_route_rules",                  # 部位/工艺规则
    "production_routings",                     # 工艺路线（本来就写「韩褶」）
    "processing_orders",                       # 加工单快照
    "production_operations",                   # 工序库（`韩褶-布` / `韩褶-纱` 早已是这个写法）
)

#: 列白名单（**不改价**的机械落点）：`SET` 子句里只许出现这些列
ALLOWED_SET_COLUMNS = {
    ITEM_TABLE: {"name", "updated_at"},
    COMBO_TABLE: {"items", "composition_key", "updated_at"},
}

#: 不许被写（也不许作为赋值目标出现）的列 —— 改键 ≠ 改钱
FORBIDDEN_COLUMNS = ("unit_price", "status", "sort_order", "source")

C_COLLATE = 'COLLATE "C"'

#: 写语句（含 `DROP`）的目标表名
_WRITE_STMT = re.compile(
    r"\b(?:UPDATE|INSERT\s+INTO|DELETE\s+FROM|ALTER\s+TABLE|TRUNCATE|DROP\s+TABLE)\s+(\w+)", re.I)

#: `UPDATE <表> [AS alias] SET <子句>` —— 子句止于顶层 `FROM` / `WHERE` / `;`
_SET_CLAUSE = re.compile(r"\bUPDATE\s+(\w+)(?:\s+\w+)?\s+SET\s+(.*?)(?=\s+FROM\s|\s+WHERE\s|;)", re.I | re.S)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _strip_comments(sql: str) -> str:
    """去掉 `--` 行注释与 `/* */` 块注释（判据读**可执行**语句，不读解释性文字）。"""
    without_block = re.sub(r"/\*.*?\*/", "", sql, flags=re.S)
    return "\n".join(re.sub(r"--.*$", "", line) for line in without_block.splitlines())


# ══════════════════════════ ① 静态形态判据（纯函数 + 注入式自证） ══════════════════════════


def _write_targets(body: str) -> set[str]:
    """可执行语句里出现的**写目标表名**（第三张表 = 越界）。"""
    return set(_WRITE_STMT.findall(body))


def _set_columns_by_table(body: str) -> dict[str, set[str]]:
    """每条 `UPDATE … SET …` 的**列名**（顶层 `标识符 =`，括号内的 `=` 不算）。"""
    out: dict[str, set[str]] = {}
    for match in _SET_CLAUSE.finditer(body):
        table, clause = match.group(1), match.group(2)
        cols: set[str] = set()
        depth = 0
        for i, ch in enumerate(clause):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            elif ch == "=" and depth == 0:
                name = re.search(r"([A-Za-z_]\w*)\s*$", clause[:i])
                if name:
                    cols.add(name.group(1))
        out[table] = cols
    return out


def _shape_problems(body: str) -> list[str]:
    """形态判据的**纯函数**（注入式红证直接喂变异文本；判据自己不读文案）。"""
    problems: list[str] = []
    if not re.search(r"^\s*BEGIN\s*;", body, re.M | re.I):
        problems.append("缺少显式 BEGIN;")
    if not re.search(r"^\s*COMMIT\s*;", body, re.M | re.I):
        problems.append("缺少显式 COMMIT;")
    targets = _write_targets(body)
    extra = targets - {ITEM_TABLE, COMBO_TABLE}
    if extra:
        problems.append(f"写语句落在第三张表上：{sorted(extra)}")
    missing = {ITEM_TABLE, COMBO_TABLE} - targets
    if missing:
        problems.append(f"没写到该写的表：{sorted(missing)}")
    if re.search(r"\bDROP\b", body, re.I):
        problems.append("出现了 DROP —— 本迁移只改行内容")
    return problems


def _column_problems(body: str) -> list[str]:
    """列白名单的**纯函数**（两把锁：SET 列解析 + 全 body 的赋值目标扫描）。"""
    problems: list[str] = []
    for table, cols in _set_columns_by_table(body).items():
        allowed = ALLOWED_SET_COLUMNS.get(table)
        if allowed is None:
            problems.append(f"{table} 不在白名单里（只许 {sorted(ALLOWED_SET_COLUMNS)}）")
            continue
        outside = cols - allowed
        if outside:
            problems.append(f"{table} 的 SET 写了白名单外的列：{sorted(outside)}")
        if not cols:
            problems.append(f"{table} 的 SET 解析不出列名（判据可能失效，先修判据）")
    # 独立第二把锁：任何位置的 `unit_price = …` / `status = …` 等赋值目标都必须为零
    for column in FORBIDDEN_COLUMNS:
        if re.search(rf"\b{column}\s*=", body, re.I):
            problems.append(f"出现了对 `{column}` 的赋值目标（**不许改价**）")
    return problems


#: `ORDER BY <序号> COLLATE …` —— 把排序规则贴在**整数字面量**上 ⇒ PG 恒报
#: `类型integer不能使用排序规则`（本单真库实测：V139 首版三处都这么写 ⇒ 整份迁移跑不起来，
#: 而 `MigrationRunner` 会**静默跳过**失败迁移 ⇒ 改名在生产上等于没发生）。这是**类级**错误形态，
#: 故在静态层也钉一条（真库层由本文件的执行判据兜底）。
_INT_ORDINAL_COLLATE = re.compile(r"ORDER\s+BY\s+\d+\s+COLLATE", re.I)


def _collate_problems(body: str) -> list[str]:
    """`COLLATE "C"` 的**纯函数**：三处都要钉住，且**不许贴在序号字面量上**。"""
    problems: list[str] = []
    total = body.count(C_COLLATE)
    if total < 3:
        problems.append(f'`COLLATE "C"` 只出现 {total} 次（前置撞键检查 / items 规范化 / 终态对账各需一处）')
    marker = "UPDATE processing_fee_combinations"
    if marker not in body:
        problems.append("找不到组合表的 UPDATE")
        return problems
    # 组合表那条语句（含 `WITH normalized …`）直到文件末尾：规范化 + 终态对账两处 COLLATE 都在这段里
    statement_start = body.rindex(";", 0, body.index(marker)) + 1
    tail = body[statement_start:]
    if tail.count(C_COLLATE) < 2:
        problems.append('组合表 UPDATE 之后不足两处 `COLLATE "C"`（规范化与终态对账各需一处）')
    if _INT_ORDINAL_COLLATE.search(body):
        problems.append(
            '`ORDER BY <序号> COLLATE "C"` —— 排序规则被贴在**整数字面量**上：PG 恒报 '
            '`类型integer不能使用排序规则`（真库实测），整份迁移跑不起来。'
            '写法：把 collation 挂到**排序表达式**上（`SELECT DISTINCT (expr) COLLATE "C" AS nm … ORDER BY 1`，'
            '或 `ORDER BY nm COLLATE "C"` / 无 DISTINCT 时 `ORDER BY e COLLATE "C"`）')
    return problems


def test_migration_file_exists_and_declares_case_ids():
    """迁移文件在，且本判据文件头部按仓规声明 `# case_ids:`。

    ⚠️ **刻意不写「V139 必须是最新迁移」**：那是**自毁式真值主张** —— 下一号迁移一落库，这条断言必红，
    而修它的活会落到来加 V140 的人头上。版本唯一性由 `test_migration_immutability.py` 的指纹账本管。

    `PG-044` = 本单（「加工项名与加工费组合键统一为『韩褶』」，`truths_ref: order.processing-item-name-canonical`）
    的**专属用例**，其 `traces.tests` 第一条就是本文件、`data_checks` 判据 1~7 与本文件 12 条一一对应。
    （取号沿革：本文件初稿写的是当时已存在的同域 id `PG-043`；该号是「特殊选项按套计价」，与本文件判据无对应
    ⇒ 专属用例 `PG-044` 落地后按实声明。）
    """
    assert V139.exists(), f"缺少改名迁移：{V139.name}"
    header = _read(Path(__file__)).splitlines()[0]
    assert header.startswith("# case_ids:"), "本判据文件头部没有按仓规声明 `# case_ids:`"
    assert "PG-044" in header, (
        "case_ids 未声明 PG-044（本单专属用例：`.github/cases/processing.yml` 的 `PG-044`，"
        "其 `traces.tests` 第一条即本文件）")


def test_explicit_transaction_and_only_two_tables_are_written():
    """形态：显式事务 + **只写**两张表（第三张表 ⇒ 红，含迁移头点名的红线表）。"""
    body = _strip_comments(_read(V139))
    problems = _shape_problems(body)
    # 红线表逐个点名（比「集合不等」更可行动）
    for table in RED_LINE_TABLES:
        hits = re.findall(rf"\b(?:UPDATE|INSERT\s+INTO|DELETE\s+FROM|ALTER\s+TABLE)\s+{table}\b", body, re.I)
        if hits:
            problems.append(f"触碰了红线表 `{table}`（不改价 / 不改历史快照）：{hits[0]}")
    assert problems == [], "V139 的形态不对：\n  " + "\n  ".join(problems)
    assert _write_targets(body) == {ITEM_TABLE, COMBO_TABLE}, (
        f"写目标集合 != 两张表：{sorted(_write_targets(body))}")


def test_only_allowed_columns_are_written():
    """列白名单：`name`/`updated_at` + `items`/`composition_key`/`updated_at`；碰价 ⇒ 红。"""
    body = _strip_comments(_read(V139))
    problems = _column_problems(body)
    assert problems == [], "V139 写了白名单外的列：\n  " + "\n  ".join(problems)
    assert _set_columns_by_table(body) == ALLOWED_SET_COLUMNS, (
        f"SET 列与白名单不逐字相等：{_set_columns_by_table(body)}（期望 {ALLOWED_SET_COLUMNS}）")


def test_collate_c_is_pinned_everywhere_it_sorts():
    """排序口径：中文必须按**码点序**（`COLLATE "C"`）—— 否则与 Java `TreeSet` 不一致 ⇒ 两个键。"""
    body = _strip_comments(_read(V139))
    problems = _collate_problems(body)
    assert problems == [], "`COLLATE \"C\"` 没钉住：\n  " + "\n  ".join(problems)


def test_shape_guard_has_teeth():
    """注入红证：塞一条写第三张表（红线表）的语句 ⇒ 形态判据必须读得出来。"""
    injected = ("BEGIN;\nUPDATE processing_fee_combinations SET items = '[]' WHERE deleted = 0;\n"
                "UPDATE order_items SET processing_info = NULL WHERE id = 'x';\nCOMMIT;\n")
    assert _shape_problems(injected), "形态判据读不出注入的第三张表 ⇒ 判据是空跑"
    assert "order_items" in _write_targets(injected)


def test_column_guard_has_teeth():
    """注入红证：`SET unit_price = 0` ⇒ 列判据必须读得出来（「不改价」不是空断言）。"""
    injected = "BEGIN;\nUPDATE processing_fee_combinations SET unit_price = 0 WHERE deleted = 0;\nCOMMIT;\n"
    problems = _column_problems(injected)
    assert problems, "列判据读不出注入的 `unit_price =` ⇒ 判据是空跑"
    assert any("unit_price" in p for p in problems), f"红的原因不是「碰价」：{problems}"


def test_collate_guard_has_teeth():
    """注入红证：抹掉所有 `COLLATE "C"` ⇒ 排序口径判据必须红；序号粘连形态检测器也要有牙。"""
    body = _strip_comments(_read(V139))
    mutated = body.replace(C_COLLATE, "")
    assert mutated != body, "注入无效：源文件里没有 `COLLATE \"C\"`"
    assert _collate_problems(mutated), "抹掉 `COLLATE \"C\"` 判据仍绿 ⇒ 判据是空跑"
    # 病灶形态（真库实测：PG 恒报「类型integer不能使用排序规则」）——独立于源文件当前内容
    assert _INT_ORDINAL_COLLATE.search('ORDER BY 1 COLLATE "C"'), (
        "`ORDER BY <序号> COLLATE` 检测器读不出病灶形态 ⇒ 这条静态锁是空跑")


# ══════════════════════════ ② 真库判据（临时 PG 集群） ══════════════════════════
# ⚠️ 「缺 PG 怎么办」**不在本文件判**：一律经 `conftest.py::realdb_binaries`
#    （session 级夹具 ⇒ `pg_cluster.require_pg()`：CI 带 `MIGAO_REQUIRE_REALDB` ⇒ **判红** /
#     本机 ⇒ 显式 skip），argv **必须用它给的绝对路径**（runner 的 PG 在
#     `/usr/lib/postgresql/16/bin`，**不在 PATH** ⇒ 按裸名调用必 `FileNotFoundError`）。

#: 与建库脚本 `backend/admin-api/src/main/resources/db/init/schema.sql` 同形的**最小** DDL。
#: ⚠️ `processing_items` **有意不建** `(tenant_id, name) WHERE deleted = 0` 唯一索引 —— 与真库同形
#: （`schema.sql` 只有 `idx_processing_items_*` 普通索引；迁移头也点明了这一点）⇒ 「同名并存」可表达。
_DDL = """
CREATE TABLE tenants (id BIGINT PRIMARY KEY, deleted INTEGER NOT NULL DEFAULT 0);
CREATE TABLE processing_items (
    id VARCHAR(64) PRIMARY KEY, tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    name VARCHAR(128) NOT NULL, craft_hint VARCHAR(16),
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0);
CREATE INDEX idx_processing_items_tenant ON processing_items(tenant_id);
CREATE TABLE processing_fee_combinations (
    id VARCHAR(64) PRIMARY KEY, tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    composition_key VARCHAR(256) NOT NULL, items JSONB NOT NULL DEFAULT '[]',
    unit_price DECIMAL(10, 2) NOT NULL, status VARCHAR(16) NOT NULL DEFAULT 'active',
    sort_order INT NOT NULL DEFAULT 0, source VARCHAR(16),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0,
    CONSTRAINT ck_processing_fee_combinations_unit_price CHECK (unit_price >= 0),
    CONSTRAINT ck_processing_fee_combinations_key_not_blank CHECK (btrim(composition_key) <> ''));
CREATE UNIQUE INDEX uk_processing_fee_combinations_tenant_key
    ON processing_fee_combinations (tenant_id, composition_key) WHERE deleted = 0;
"""

#: 真库形态的种子（覆盖六条边界）：
#:   · **1 号租户**：`韩折`（改名）+ **已存在的同名 `韩褶`**（评测种子那种同名并存，三列都不许动）
#:     + `定型`（一字不动）+ **已软删的 `韩折`**（留痕，谓词丢 `deleted = 0` 就会被改 ⇒ 该断言红）；
#:   · **2 号租户**：`韩折`（证明不按租户硬编码 1）；
#:   · 组合四条会被改：① `定型+韩折`（顺序本已码点序，只改名）；② `韩折+超高`（**非码点序** ⇒ 序会翻）；
#:     ③ `打孔+定型+韩折`（**locale 序**，本机 `zh_CN.UTF-8` 下与码点序不同 ⇒ `COLLATE "C"` 的运行时红证）；
#:     ④ `韩折+韩折+打孔`（**有重复成员** ⇒ 去重）；
#:   · 组合一条不许动：`定型+打孔`（不含旧名，整行指纹逐字节不变）；
#:   · 每条被改的组合都带**价 / 状态 / 排序 / source** ⇒ 「不改价」逐值可核。
_SEED = """
INSERT INTO tenants (id) VALUES (1), (2);
INSERT INTO processing_items (id, tenant_id, name, craft_hint, status, deleted) VALUES
    ('pi-1-02',      1, '韩折', '韩褶', 'active', 0),
    ('pi-1-19',      1, '韩褶', '韩褶', 'active', 0),
    ('pi-1-keep',    1, '定型', '定型', 'active', 0),
    ('pi-1-deleted', 1, '韩折', '韩褶', 'active', 1),
    ('pi-2-02',      2, '韩折', '韩褶', 'active', 0);
INSERT INTO processing_fee_combinations
    (id, tenant_id, composition_key, items, unit_price, status, sort_order, source, deleted) VALUES
    ('c-1-dingxing', 1, '定型+韩折',      '["定型","韩折"]'::jsonb,          5.00, 'active',   7,  'observed',  0),
    ('c-1-chaogao',  1, '韩折+超高',      '["韩折","超高"]'::jsonb,          3.00, 'disabled', 3,  'derived',   0),
    ('c-1-scrambled',1, '打孔+定型+韩折', '["打孔","定型","韩折"]'::jsonb,   6.50, 'active',   11, NULL,        0),
    ('c-1-dupe',     1, '打孔+韩折',      '["韩折","韩折","打孔"]'::jsonb,   2.50, 'active',   5,  NULL,        0),
    ('c-1-plain',    1, '定型+打孔',      '["定型","打孔"]'::jsonb,          8.00, 'active',   0,  'synthetic', 0),
    ('c-2-keep',     2, '定型+韩折',      '["定型","韩折"]'::jsonb,          4.00, 'active',   2,  'observed',  0);
"""


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def psql(tmp_path, realdb_binaries):
    """临时 PG 集群（unix socket，不占 TCP 端口）；退出时停库删目录。

    ⚠️ 二进制一律取 `realdb_binaries[...]` 的**绝对路径**；起/停只经 `pg_cluster` 收口件。
    """
    datadir = tmp_path / "pgdata"
    # ⚠️ socket 目录必须**短**：unix socket 路径有 ~104 字节上限。
    sockdir = Path(tempfile.mkdtemp(prefix="pgv139-"))
    log = tmp_path / "pg.log"
    port = _free_port()
    pg_cluster.start_cluster(realdb_binaries, datadir, sockdir=sockdir, port=port, log=log)

    def psql_raw(sql: str):
        """不抛异常的入口（红证要断言「迁移**确实**失败并回滚」）。"""
        return subprocess.run(
            [realdb_binaries["psql"], "-h", str(sockdir), "-p", str(port), "-U", "postgres",
             "-d", "postgres", "-X", "-q", "-t", "-A", "-v", "ON_ERROR_STOP=1"],
            input=sql, text=True, capture_output=True)

    def run(sql: str) -> str:
        proc = psql_raw(sql)
        assert proc.returncode == 0, f"psql 失败：\n{proc.stdout}\n{proc.stderr}"
        return proc.stdout

    run.raw = psql_raw
    try:
        yield run
    finally:
        pg_cluster.stop_cluster(realdb_binaries["pg_ctl"], datadir)
        shutil.rmtree(sockdir, ignore_errors=True)


def _as_runner_would(sql: str) -> str:
    """把迁移包进**一个事务**执行 —— 复现 `MigrationRunner` 的 `jdbc.execute(整份文件)` 语义。

    ⚠️ 文件内另有自己的 `BEGIN; … COMMIT;` ⇒ 外层再包一层会得到 PG 的
    `WARNING: there is already a transaction in progress`（**不是错误**，无害）。
    """
    return "BEGIN;\n" + sql + "\nCOMMIT;\n"


#: 按 jsonb **数组顺序**取成员（`WITH ORDINALITY` ⇒ 顺序不靠运气）
_ORDERED_ITEMS = ("(SELECT string_agg(e, ',' ORDER BY ord) "
                  "FROM jsonb_array_elements_text(c.items) WITH ORDINALITY AS t(e, ord))")

#: 组合表终态视图：id | 键 | items（数组序） | 价 | 状态 | 排序 | source
_COMBO_VIEW = (
    "SELECT c.id || '|' || c.composition_key || '|' || " + _ORDERED_ITEMS + " || '|' || "
    "c.unit_price || '|' || c.status || '|' || c.sort_order || '|' || coalesce(c.source, '∅') "
    "FROM processing_fee_combinations c ORDER BY c.id;")

#: **钱/状态投影**（刻意不含 `updated_at`）：用来判「逐值不变」
_COMBO_MONEY = (
    "SELECT c.id || '|' || c.unit_price || '|' || c.status || '|' || c.sort_order || '|' || "
    "coalesce(c.source, '∅') || '|' || c.deleted "
    "FROM processing_fee_combinations c ORDER BY c.id;")

#: 目录表终态视图：id | name | craft_hint | status | deleted
_ITEM_VIEW = (
    "SELECT id || '|' || name || '|' || coalesce(craft_hint, '∅') || '|' || status || '|' || deleted "
    "FROM processing_items ORDER BY id;")


def _fingerprint(run, table: str) -> str:
    """表内容指纹（按行文本排序逐行拼接**全部列**，含 `updated_at`）—— 判「一字不动」。"""
    return run(f"SELECT coalesce(string_agg(t::text, E'\\n' ORDER BY t::text), '') FROM {table} t;")


def _row_fingerprint(run, table: str, row_id: str) -> str:
    """单行全列指纹（判「这一行一字不动」）。"""
    return run(f"SELECT t::text FROM {table} t WHERE t.id = '{row_id}';")


def _c_order_recompute(run) -> str:
    """**独立复算**：现存组合的 `items`（去重去空）按 `COLLATE "C"`（= 码点序）排后 `+` 连接。

    ⚠️ 排序写成两层子查询 + `ORDER BY nm COLLATE "C"` —— **不许**写 `ORDER BY 1 COLLATE "C"`：
    后者把排序规则贴在整数字面量上，PG 恒报 `类型integer不能使用排序规则`（本单真库实测；
    V139 首版三处都这么写，**本文件第一版**也在这一句上栽了同一形态，故留痕）。
    """
    return run(
        "SELECT c.id || '|' || c.composition_key || '|' || array_to_string(ARRAY(\n"
        "    SELECT nm FROM (\n"
        "        SELECT DISTINCT e AS nm FROM jsonb_array_elements_text(c.items) AS e\n"
        "         WHERE btrim(e) <> '') s\n"
        "     ORDER BY nm COLLATE \"C\"), '+') "
        "  FROM processing_fee_combinations c "
        " WHERE c.deleted = 0 AND c.items @> '[\"" + NEW_NAME + "\"]'::jsonb "
        " ORDER BY c.id;")


@pytest.fixture
def seeded(psql):
    psql(_DDL + _SEED)
    return psql


def test_real_db_shape_allows_same_name_items(seeded):
    """前提自证：测试库与真库同形 —— `processing_items` 上**没有** `(tenant_id, name)` 唯一索引。

    否则「同名并存」这条边界根本造不出来（判据会一路绿着跳过真实形态）；真库的该前提见
    `schema.sql`（只有普通索引）与 V139 头注释第 ③ 段。
    """
    run = seeded
    extra_unique = run(
        "SELECT count(*) FROM pg_indexes WHERE tablename = 'processing_items' "
        "AND indexdef ILIKE '%UNIQUE%' AND indexname <> 'processing_items_pkey';")
    assert extra_unique.strip() == "0", (
        "测试库给 `processing_items` 建了 name 唯一索引 ⇒ 与真库不同形，「同名并存」边界造假")
    assert run("SELECT count(*) FROM processing_items WHERE name = '韩褶' AND deleted = 0;").strip() == "1"


def test_real_db_renames_catalog_and_normalizes_combo_keys(seeded):
    """真库主判据：目录改名（同名并存 / 已软删行不动）+ 组合 items 去重&码点序 + 键重算 + **不改价**。"""
    run = seeded
    items_before = _fingerprint(run, ITEM_TABLE)
    conflated_before = _row_fingerprint(run, ITEM_TABLE, "pi-1-19")   # 同名并存行
    deleted_before = _row_fingerprint(run, ITEM_TABLE, "pi-1-deleted")  # 已软删的同名行
    money_before = run(_COMBO_MONEY)
    plain_before = _row_fingerprint(run, COMBO_TABLE, "c-1-plain")

    run(_as_runner_would(_read(V139)))

    # ── 目录：旧名退场、同名并存行与已软删行一字不动 ─────────────────────────────
    assert items_before != _fingerprint(run, ITEM_TABLE), "指纹没变 ⇒ 迁移根本没生效（本判据会假绿）"
    assert run(_ITEM_VIEW).splitlines() == [
        "pi-1-02|韩褶|韩褶|active|0",        # ← 改名
        "pi-1-19|韩褶|韩褶|active|0",        # ← 本来就是「韩褶」：一字不动
        "pi-1-deleted|韩折|韩褶|active|1",   # ← 已软删：**不许被复活 / 改名**（谓词带 deleted = 0）
        "pi-1-keep|定型|定型|active|0",      # ← 其它目录项：一字不动
        "pi-2-02|韩褶|韩褶|active|0",        # ← 非 1 号租户也覆盖
    ], f"目录终态不对：\n{run(_ITEM_VIEW)}"
    assert run(f"SELECT count(*) FROM processing_items WHERE name = '{OLD_NAME}' AND deleted = 0;"
               ).strip() == "0", "终态仍有存活的旧名目录项"
    assert _row_fingerprint(run, ITEM_TABLE, "pi-1-19") == conflated_before, (
        "既有的同名「韩褶」行被改了（updated_at 被重写？）—— 迁移只该改旧名那行")
    assert _row_fingerprint(run, ITEM_TABLE, "pi-1-deleted") == deleted_before, (
        "已软删的旧名行被改了 ⇒ 谓词丢了 `deleted = 0`")

    # ── 组合：items 去重 + 码点序 + 键重算；价 / 状态 / 排序 / source / id 逐值不变 ──────
    assert run(_COMBO_VIEW).splitlines() == [
        "c-1-chaogao|超高+韩褶|超高,韩褶|3.00|disabled|3|derived",       # ← 序翻了（非码点序 ⇒ 码点序）
        "c-1-dingxing|定型+韩褶|定型,韩褶|5.00|active|7|observed",        # ← 只改名，序本已码点序
        "c-1-dupe|打孔+韩褶|打孔,韩褶|2.50|active|5|∅",                  # ← 重复成员被去重（3 → 2）
        "c-1-plain|定型+打孔|定型,打孔|8.00|active|0|synthetic",          # ← 不含旧名：不变
        "c-1-scrambled|定型+打孔+韩褶|定型,打孔,韩褶|6.50|active|11|∅",   # ← locale 序 → 码点序
        "c-2-keep|定型+韩褶|定型,韩褶|4.00|active|2|observed",            # ← 非 1 号租户也覆盖
    ], f"组合终态不对：\n{run(_COMBO_VIEW)}"
    # 独立复算（自带 `COLLATE "C"`）逐行等于落库的 composition_key
    recomputed = _c_order_recompute(run)
    assert recomputed.splitlines() == [
        "c-1-chaogao|超高+韩褶|超高+韩褶",
        "c-1-dingxing|定型+韩褶|定型+韩褶",
        "c-1-dupe|打孔+韩褶|打孔+韩褶",
        "c-1-scrambled|定型+打孔+韩褶|定型+打孔+韩褶",
        "c-2-keep|定型+韩褶|定型+韩褶",
    ], f"落库键 != 码点序复算键（COLLATE \"C\" 没生效？）：\n{recomputed}"
    # **不改价**：钱/状态投影逐值不变（`unit_price` / `status` / `sort_order` / `source` / `id` / `deleted`）
    assert run(_COMBO_MONEY) == money_before, (
        f"迁移动了钱/状态：\n改前 {money_before}\n改后 {run(_COMBO_MONEY)}")
    # 不含旧名的组合：整行（含 updated_at）逐字节不变
    assert _row_fingerprint(run, COMBO_TABLE, "c-1-plain") == plain_before, (
        "不含旧名的组合行被改了（不该被 UPDATE 命中）")


def test_real_db_two_passes_are_idempotent(seeded):
    """幂等：第二遍谓词匹配 0 行、净效果相同（存活行 `updated_at` 也逐字不变），对账两遍都过。"""
    run = seeded
    sql = _as_runner_would(_read(V139))
    run(sql)
    items_after_first = _fingerprint(run, ITEM_TABLE)
    combos_after_first = _fingerprint(run, COMBO_TABLE)
    money_after_first = run(_COMBO_MONEY)

    matched_second_pass = run(
        f"SELECT count(*) FROM processing_items WHERE name = '{OLD_NAME}' AND deleted = 0;")
    matched_combos_second_pass = run(
        f"SELECT count(*) FROM processing_fee_combinations WHERE deleted = 0 AND items @> '[\"{OLD_NAME}\"]'::jsonb;")
    run(sql)   # 第二遍：两条谓词都匹配 0 行 ⇒ 空操作，且**不得**抛（对账块两遍都成立）

    assert matched_second_pass.strip() == "0" and matched_combos_second_pass.strip() == "0", (
        "第二遍的谓词读数不为 0 —— 幂等闸不成立（`更新` 会重复命中）")
    assert _fingerprint(run, ITEM_TABLE) == items_after_first, "第二遍改动了目录项（`updated_at` 被重写？）"
    assert _fingerprint(run, COMBO_TABLE) == combos_after_first, "第二遍改动了组合表（`updated_at` 被重写？）"
    assert run(_COMBO_MONEY) == money_after_first


def test_real_db_conflicting_key_fails_closed_and_rolls_back(seeded):
    """撞键 fail-closed：同租户里「改名后同名」的两行 ⇒ 抛异常 + **点名租户与键** + **整份回滚**。

    不 fail-closed 的形态：改到一半撞 `uk_processing_fee_combinations_tenant_key` ⇒ 报的是唯一键冲突
    （不可行动，商家不知道该处置哪条），或只回滚一半（目录已改名、组合没改）⇒ 半成品。
    """
    run = seeded
    run("INSERT INTO tenants (id) VALUES (3);"
        "INSERT INTO processing_fee_combinations "
        "(id, tenant_id, composition_key, items, unit_price, status, sort_order, source, deleted) VALUES "
        "('c-3-old', 3, '定型+韩折', '[\"定型\",\"韩折\"]'::jsonb, 6.00, 'active', 0, 'observed', 0), "
        "('c-3-new', 3, '定型+韩褶', '[\"定型\",\"韩褶\"]'::jsonb, 6.50, 'active', 0, 'observed', 0);")
    items_before = _fingerprint(run, ITEM_TABLE)
    combos_before = _fingerprint(run, COMBO_TABLE)

    proc = run.raw(_as_runner_would(_read(V139)))

    assert proc.returncode != 0, (
        "同租户「定型+韩折」与「定型+韩褶」并存时迁移照样通过 ⇒ fail-closed 检查缺失（下游会撞唯一键报错）")
    seen = proc.stderr + proc.stdout
    assert "撞上已存在的加工费组合键" in seen, f"失败原因不是既定的 fail-closed 文案：\n{seen}"
    assert "tenant=3" in seen, f"异常没点名租户（不可行动）：\n{seen}"
    assert "定型+韩褶" in seen and "定型+韩折" in seen, f"异常没点名那两个会撞的键：\n{seen}"
    # 整份回滚：两张表（含刚插进去的冲突租户两行）逐字节回到执行前
    assert _fingerprint(run, COMBO_TABLE) == combos_before, "撞键后组合表没整份回滚 —— 迁移不是原子的"
    assert _fingerprint(run, ITEM_TABLE) == items_before, (
        "撞键后目录表仍被改了 —— 只回滚了一半（半成品：目录已是「韩褶」、组合还是「韩折」）")
    assert run("SELECT count(*) FROM processing_fee_combinations WHERE tenant_id = 3 AND deleted = 0;"
               ).strip() == "2", "冲突租户的两行不见了（回滚半径过大 = 数据丢失）"


def test_terminal_reconciliation_catches_missing_rename(seeded):
    """注入红证 ⑤：把改名 UPDATE 注释掉（**临时副本**，不动仓库文件）⇒ 终态对账必须抛。

    证明文末的终态对账**不是空跑**：它抓得住「没写 / 漏写」（本迁移刻意**不能**用
    「认领 0 行 ⇒ 抛」的空跑自证 —— 第二遍本来就该匹配 0 行，见迁移头「幂等」段）。
    """
    run = seeded
    items_before = _fingerprint(run, ITEM_TABLE)
    combos_before = _fingerprint(run, COMBO_TABLE)

    source = _read(V139)
    start = source.index("UPDATE processing_items")
    end = source.index(";", start) + 1
    statement = source[start:end]
    assert "name = '韩折'" in statement, "待注释的片段里没有改名谓词（注入坐标漂了）"
    mutated = source[:start] + "\n".join("-- " + line for line in statement.splitlines()) + source[end:]
    assert mutated != source, "注入无效：源文件里没有可注释的改名 UPDATE"

    proc = run.raw(_as_runner_would(mutated))
    assert proc.returncode != 0, "没写改名 UPDATE 却通过了 ⇒ 终态对账形同虚设"
    seen = proc.stderr + proc.stdout
    assert "终态对账未通过" in seen, f"失败原因不是终态对账：\n{seen}"
    assert "目录仍剩" in seen, f"对账没点名「目录仍剩旧名」这条：\n{seen}"
    # 整份回滚：目录与组合都回到执行前（含被改的组合 —— 注入后它们也不许留下半成品）
    assert _fingerprint(run, ITEM_TABLE) == items_before, "对账抛了但目录表变了 —— 不是同一事务"
    assert _fingerprint(run, COMBO_TABLE) == combos_before, "对账抛了但组合表变了 —— 不是同一事务"
