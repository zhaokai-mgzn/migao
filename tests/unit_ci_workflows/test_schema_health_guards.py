# case_ids: MC-119
"""schema 形态的**三条健康判据**（issue #7359，防 ERP 化）。

## 这一条要治什么

用户的判断（逐字）：「传统 ERP 软件就是堆积各种单据……一个单据几十几百个字段，领域建模很弱」。
臃肿的三个根因都不是「单据多」，而是**加列式演进**、**派生量落库**、**用 JSON 桶逃避建模**。
后者尤其危险：它把「加 300 列」换成「一个 200 个 key 的 JSON，谁都不知道里面有什么」。本判据把三种形态
钉成**可机械判定的读数**：

| 判据 | 形态（会红的写法） | 治法 |
|---|---|---|
| **列预算** | 单表列数 > `column_ceiling`（现 30），且未在台账具名例外 | 拆聚合 / 派生量不落库（见 `docs/wiki/Domain-Modeling.md` §一） |
| **零孤儿列增长** | 生产代码语料里**零引用**的列（谁都不读、谁都不写） | 删列（迁移幂等）/ 补真实读面 |
| **JSONB 必须登记** | 新增 JSONB 列却没进台账 | 一次**显式决策**：能排序/聚合/约束的应该是一列 |

## 基线（2026-10-20 实取，复算命令在文件末）

`db/init/schema.sql`：**84 张表 / 1140 列 / 平均 13.6 列**；超预算 1 张（`customer_profiles` 42，已具名登记）；
孤儿列 **0**；JSONB **48** 列（已全部登记）。台账 = `tests/unit_ci_workflows/schema_health_ledger.json`。

**台账只许缩短**（本仓既有口径，同 `gate-exemption-ledger`）：超限表被拆到 ≤ 预算后，对应例外条目**必须删除**
（不删 ⇒ 判据红）；孤儿列 / JSONB 条目的陈旧同样判红。

## 覆盖不到什么（照实登记）

- **判不了设计判断**：「这张表该不该有」「这个字段该不该拆」不是可正则化的形态 —— 那是评审与
  `docs/wiki/Domain-Modeling.md` 的「准入判据」。
- **列预算的单位是「聚合」，不是「业务复杂度」**：一张合法的宽表（如路由版本快照）可以通过台账例外放行，
  但**必须写出收敛计划**。
- **孤儿语的料口径是冻结的**（`CORPUS_ROOTS`）：新增一个服务目录而不把它加进语料 ⇒ 那个服务的引用看不见
  ⇒ 会**假红**（判「零引用」）。这是有意的 fail-closed 方向：改语料必须同 PR 说明。
- 不查 GitHub / 不联网 / 不连库；纯静态（`ci workflow helper unit tests` 只装 `pytest` + `pyyaml`）。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "backend" / "admin-api" / "src" / "main" / "resources" / "db" / "init" / "schema.sql"
LEDGER_PATH = REPO_ROOT / "tests" / "unit_ci_workflows" / "schema_health_ledger.json"

#: 孤儿列语料（**生产代码**，不含 tests / docs —— 文档提一句不算「有人用」）
CORPUS_ROOTS = (
    "backend/admin-api/src/main/java",
    "backend/admin-api/src/main/resources",
    "backend/ai-agent-service/app",
    "frontend/admin-web/src",
    "frontend/mini-app/src",
    "frontend/bmini-app/src",
)
CORPUS_SUFFIXES = (".java", ".py", ".ts", ".tsx", ".js", ".jsx", ".xml", ".yml", ".yaml", ".sql")

_NON_COLUMN_HEADS = frozenset({"CONSTRAINT", "PRIMARY", "UNIQUE", "FOREIGN", "CHECK", "INDEX"})


def parse_schema(text: str) -> dict[str, list[tuple[str, str]]]:
    """`CREATE TABLE` 块 → {表名: [(列名, 类型小写), ...]}（表级约束行剔除）。"""
    tables: dict[str, list[tuple[str, str]]] = {}
    for raw_name, body in re.findall(
        r"CREATE TABLE(?: IF NOT EXISTS)?\s+\"?([\w]+)\"?\s*\((.*?)\n\);", text, re.S
    ):
        cols: list[tuple[str, str]] = []
        for line in body.split("\n"):
            m = re.match(r'\s*"?([a-z_][\w]*)"?\s+([A-Za-z][\w ()\[\]]*)', line)
            if not m or m.group(1).upper() in _NON_COLUMN_HEADS:
                continue
            cols.append((m.group(1), m.group(2).strip().lower()))
        tables[raw_name] = cols
    assert tables, "schema.sql 里解析不到 CREATE TABLE（判据在空跑）"
    return tables


def _camel(name: str) -> str:
    parts = name.split("_")
    return parts[0] + "".join(p[:1].upper() + p[1:] for p in parts[1:])


def production_corpus() -> str:
    chunks: list[str] = []
    for rel in CORPUS_ROOTS:
        for path in (REPO_ROOT / rel).rglob("*"):
            if path.is_file() and path.suffix in CORPUS_SUFFIXES:
                chunks.append(path.read_text(encoding="utf-8", errors="ignore"))
    assert len(chunks) > 500, f"生产代码语料过小（{len(chunks)} 个文件）—— 语料口径坏了，判据会假绿"
    return "\n".join(chunks)


def orphan_columns(tables: dict[str, list[tuple[str, str]]], blob: str) -> list[str]:
    """生产代码语料里零引用的列（`snake_case` 与 `camelCase` 都算引用）。"""
    found: list[str] = []
    for table, cols in sorted(tables.items()):
        for col, _type in cols:
            if col in blob or _camel(col) in blob:
                continue
            found.append(f"{table}.{col}")
    return found


def jsonb_columns(tables: dict[str, list[tuple[str, str]]]) -> list[str]:
    return sorted(f"{t}.{c}" for t, cols in tables.items() for c, typ in cols if "jsonb" in typ)


def budget_offenders(
    tables: dict[str, list[tuple[str, str]]], ledger: dict
) -> tuple[list[str], list[str]]:
    """返回 (未登记的裸超限表, 台账里的陈旧/失真条目)。"""
    ceiling = ledger["column_ceiling"]
    overrides = ledger["column_overrides"]
    naked: list[str] = []
    stale: list[str] = []
    for table, cols in sorted(tables.items()):
        width = len(cols)
        if width > ceiling and table not in overrides:
            naked.append(f"{table}：{width} 列 > 预算 {ceiling}（拆聚合或写进台账并给收敛计划）")
        if table in overrides and overrides[table]["columns"] != width:
            stale.append(
                f"{table}：台账写 {overrides[table]['columns']} 列，现取 {width} 列"
                f"（{'增宽' if width > overrides[table]['columns'] else '已收窄 ⇒ 请缩短台账'}）"
            )
    for table in overrides:
        if table not in tables:
            stale.append(f"{table}：台账里有、schema 里没有（陈旧条目）")
        elif len(tables[table]) <= ceiling:
            stale.append(f"{table}：已收窄到 ≤ {ceiling} 列 ⇒ 例外条目必须删除（台账只许缩短）")
    return naked, stale


def _load_ledger() -> dict:
    return json.loads(LEDGER_PATH.read_text(encoding="utf-8"))


# ────────────────────────── 判据（真语料） ──────────────────────────


def test_no_table_exceeds_the_column_budget() -> None:
    """判据 1：列预算 + 具名例外（宽度现取，不收窄就不删台账）。"""
    naked, stale = budget_offenders(parse_schema(SCHEMA_PATH.read_text(encoding="utf-8")), _load_ledger())
    assert not naked, "超列预算的表没有具名登记：\n" + "\n".join(naked)
    assert not stale, "列预算台账已失真：\n" + "\n".join(stale)


def test_orphan_columns_do_not_grow() -> None:
    """判据 2：零孤儿列增长（基线现取 × 台账；多一列就红）。"""
    tables = parse_schema(SCHEMA_PATH.read_text(encoding="utf-8"))
    actual = orphan_columns(tables, production_corpus())
    ledger = _load_ledger()["orphan_columns"]
    new = [c for c in actual if c not in ledger]
    gone = [c for c in ledger if c not in actual]
    assert not new, "出现生产代码零引用的列（要么补读面、要么删列）：\n" + "\n".join(new)
    assert not gone, "台账里的孤儿列已消失/已被引用 ⇒ 请缩短台账：\n" + "\n".join(gone)


def test_every_jsonb_column_is_registered() -> None:
    """判据 3：JSONB 双向对账 —— 未登记即红，陈旧条目也红。"""
    tables = parse_schema(SCHEMA_PATH.read_text(encoding="utf-8"))
    actual = jsonb_columns(tables)
    ledger = _load_ledger()["jsonb_columns"]
    new = [c for c in actual if c not in ledger]
    gone = [c for c in ledger if c not in actual]
    assert not new, (
        "新增了未登记的 JSONB 列（先回答：它要排序/聚合/唯一约束吗？要 ⇒ 应该是列）：\n" + "\n".join(new)
    )
    assert not gone, "JSONB 台账陈旧（列已删或已改为标量类型）⇒ 请缩短台账：\n" + "\n".join(gone)


# ────────────────────────── 注入式红证（判据 4） ──────────────────────────


def _toy_tables() -> dict[str, list[tuple[str, str]]]:
    return {
        "narrow": [("id", "uuid"), ("name", "varchar(32)")],
        "wide": [("id", "uuid")] + [(f"c{i}", "int") for i in range(30)],
        "keeper": [("id", "uuid"), ("payload", "jsonb")],
    }


def _toy_ledger() -> dict:
    return {
        "column_ceiling": 30,
        "column_overrides": {"wide": {"columns": 31, "why": "测试世界", "plan": "测试世界"}},
        "orphan_columns": [],
        "jsonb_columns": ["keeper.payload"],
    }


def test_toy_world_is_green() -> None:
    """负控：未注入 ⇒ 合成世界与真语料都必须绿（否则下面的红证是空跑）。"""
    naked, stale = budget_offenders(_toy_tables(), _toy_ledger())
    assert not naked and not stale
    # 合成语料：把三张表的列都引用一遍（含 31 列的 wide）⇒ 零孤儿
    blob = " ".join(f"wide.c{i}" for i in range(30)) + " narrow.id name keeper.payload"
    assert orphan_columns(_toy_tables(), blob) == []
    # 真语料负控
    tables = parse_schema(SCHEMA_PATH.read_text(encoding="utf-8"))
    naked, stale = budget_offenders(tables, _load_ledger())
    assert not naked and not stale


def test_unregistered_wide_table_goes_red() -> None:
    """判据 1 红证：拆掉台账例外 ⇒ 具名判红。"""
    ledger = _toy_ledger()
    ledger["column_overrides"] = {}
    naked, _ = budget_offenders(_toy_tables(), ledger)
    assert any("wide：31 列 > 预算 30" in n for n in naked), naked


def test_wide_table_shrinking_forces_ledger_shrink() -> None:
    """判据 1 红证（只许缩短）：表已收窄到预算内而台账还写着 ⇒ 判红。"""
    ledger = _toy_ledger()
    tables = _toy_tables()
    tables["wide"] = tables["wide"][:20]
    naked, stale = budget_offenders(tables, ledger)
    assert any("already" not in s and "已收窄" in s for s in stale), stale
    assert not naked


def test_new_orphan_column_goes_red() -> None:
    """判据 2 红证：给某表加一列而无人引用 ⇒ 具名判红。"""
    tables = _toy_tables()
    tables["narrow"].append(("nobody_reads_me", "int"))
    orphans = orphan_columns(tables, "wide.c0 id name payload")
    assert "narrow.nobody_reads_me" in orphans, orphans


def test_unregistered_jsonb_goes_red() -> None:
    """判据 3 红证：悄悄加一个 JSONB 列 ⇒ 具名判红。"""
    tables = _toy_tables()
    tables["narrow"].append(("bag", "jsonb"))
    actual = jsonb_columns(tables)
    assert [c for c in actual if c not in _toy_ledger()["jsonb_columns"]] == ["narrow.bag"]


def test_stale_jsonb_entry_goes_red() -> None:
    """判据 3 红证（反向）：台账里留着已删除的 JSONB 列 ⇒ 判红。"""
    ledger = _toy_ledger()
    ledger["jsonb_columns"].append("gone.removed")
    actual = jsonb_columns(_toy_tables())
    assert [c for c in ledger["jsonb_columns"] if c not in actual] == ["gone.removed"]


# 复算命令（不写死数字，现取）：
#   python3 - <<'PY'
#   import re; s=open('backend/admin-api/src/main/resources/db/init/schema.sql').read()
#   print('tables', len(re.findall(r'CREATE TABLE', s)))
#   PY
