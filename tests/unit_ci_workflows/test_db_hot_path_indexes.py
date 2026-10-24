# case_ids: PR-056, MC-012
"""热点查询索引 ⇄ 建库脚本 的**单一真相**守卫（2026-10-20 索引审查第一刀）。

## 为什么要这条（不是「多一条索引测试」）

本仓的**唯一**建库脚本是 `backend/admin-api/src/main/resources/db/init/schema.sql`，
而**结构变更必须先落迁移、再同步进脚本**（`docs/wiki/Database.md` 的「切点」节）。
这条契约**没有机械判据**：迁移里写了 `CREATE INDEX`、脚本里忘了同步 ⇒
存量库升级后**有**索引，全新环境（CI / 新部署的站）**永远没有** —— 两份真相，
而且**没有任何东西会变红**（`MigrationRunner` 对内容类失败只跳过不阻塞）。

本次审查就撞到了 5 个已发布的实例（V148 / V165 / V166 / V167），最严重的一条是
`user_roles` 的全表 `UNIQUE(user_id, role_id)` 一直留在脚本里（V166 已在存量库删掉它）
⇒ 同一个「软删后重新授予同一角色」的动作，**新建库失败、存量库成功**。

## 判据（全部会红）

1. **活目录里每条 `CREATE INDEX` 的产成品都必须在建库脚本里逐字存在**
   （表名 / 列清单 / `WHERE` 谓词三面比对；被后续迁移 DROP 掉的对象按「表已不在脚本」自动豁免，
   **不维护人工豁免清单**）；
2. **本刀新增的索引**（迁移 `V171__add_hot_path_indexes.sql`）走查为「前导列 = `tenant_id`」
   —— 例外只有 `inbound_labels`（跨租户的全局码空间，按 `short_code` / `revoked_code` 定位）；
3. **幂等**：活目录里的 `CREATE INDEX` 必须带 `IF NOT EXISTS`、`DROP INDEX` 必须带 `IF EXISTS`
   （`MigrationRunner` 会在已建出终态的库上把活目录再跑一遍）；
4. **判别力自证**（注入式）：从脚本文本里抹掉一条索引 ⇒ 判据 1 必红并**具名**该索引；
   抹掉的是「本来就不在脚本里的名字」⇒ 不红（负控，防「恒红」）。

## 边界（如实登记，§19.1）

- 解析是**静态文本**层面的：不认 `EXECUTE` 动态 SQL、不认跨 schema 同名对象；
  它要回答的只有一个问题 ——「这条索引在**可执行 DDL** 里出现没有」。
- **不能**替代真库：索引是否真被规划器用上要 `EXPLAIN`（本守卫只管「有没有」与「两边一致」）。
- 不判索引**该不该**存在（那是评审）；不判重复索引 / 低选择性索引。
"""
from __future__ import annotations

import re
from pathlib import Path

from unit_ci_workflows._sql_schema import SCHEMA, parse_created_tables, strip_sql_comments

REPO = Path(__file__).resolve().parents[2]
LIVE_DIR = REPO / "backend/admin-api/src/main/resources/db/migration"

#: 本刀（2026-10-20）新增索引的载体 —— 迁移文件名按版本号定位，**不抄绝对路径**
HOT_PATH_MIGRATION = "V171__add_hot_path_indexes.sql"

#: 前导列不是 `tenant_id` 的**合法**例外（逐条给理由，**不做前缀通配**）
NON_TENANT_LEADING_ALLOWED = {
    # 跨租户的**全局码空间**：`/i/` 那一跳没有租户上下文，按印刷码反查（issue #5039 家族）
    "idx_labels_short_code",
    "idx_labels_revoked_code",
    # 权限判定的**连接列**（role_permissions ⋈ permissions ON permission_id），不是租户域读面
    "idx_role_permissions_permission",
}


def _norm(s: str) -> str:
    """SQL 片段归一：压空白 + 小写 + 去尾分号（两边写法不同、语义相同 ⇒ 视为一致）。"""
    return " ".join(s.split()).strip().rstrip(";").strip().lower()


def parse_indexes(sql: str) -> dict[str, tuple[str, str, str]]:
    """抽出 `CREATE [UNIQUE] INDEX …`：`{索引名: (表名, 列清单, WHERE 谓词)}`（均已归一）。

    ⚠️ **必须剥注释**：迁移与本脚本都会在注释里写「回滚 SQL / 已删除的索引」，
    不剥就会把**说明文字**读成**定义**（本仓的既有教训，见 `_sql_schema.strip_sql_comments`）。
    """
    text = strip_sql_comments(sql)
    out: dict[str, tuple[str, str, str]] = {}
    pattern = re.compile(
        r"CREATE\s+(UNIQUE\s+)?INDEX\s+(?:CONCURRENTLY\s+)?(?:IF\s+NOT\s+EXISTS\s+)?"
        r"(\w+)\s+ON\s+(?:ONLY\s+)?(?:public\.)?(\w+)\s*",
        re.I,
    )
    for m in pattern.finditer(text):
        i = m.end()
        rest = text[i:]
        using = re.match(r"USING\s+\w+\s*", rest, re.I)
        if using:
            i += using.end()
        if i >= len(text) or text[i] != "(":
            continue
        depth, j = 0, i
        while j < len(text):
            if text[j] == "(":
                depth += 1
            elif text[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        cols = text[i + 1:j]
        semi = text.find(";", j + 1)
        tail = text[j + 1: semi if semi != -1 else len(text)]
        where = re.search(r"\bWHERE\b(.*)", tail, re.I | re.S)
        out[m.group(2).lower()] = (
            m.group(3).lower(),
            _norm(cols),
            _norm(where.group(1)) if where else "",
        )
    return out


def live_migration_indexes() -> dict[str, tuple[str, str, str, str]]:
    """活目录全部迁移里的索引：`{索引名: (表名, 列, 谓词, 迁移文件名)}`。"""
    out: dict[str, tuple[str, str, str, str]] = {}
    for f in sorted(LIVE_DIR.glob("V*.sql")):
        for name, (table, cols, where) in parse_indexes(f.read_text(encoding="utf-8")).items():
            out[name] = (table, cols, where, f.name)
    return out


def schema_indexes(sql: str | None = None) -> dict[str, tuple[str, str, str]]:
    return parse_indexes(SCHEMA.read_text(encoding="utf-8") if sql is None else sql)


def drift_problems(schema_sql: str | None = None) -> list[str]:
    """返回「迁移里有、脚本里没有 / 两边定义不一致」的索引清单（空 = 无漂移）。

    被后续迁移 DROP 掉的对象**自动豁免**：判据 = 它所在的表已经不在建库脚本里
    （如 `V141` 建、`V154` 删表的 `worker_page_configs`）—— 不维护人工豁免清单。
    """
    text = (SCHEMA.read_text(encoding="utf-8") if schema_sql is None else schema_sql)
    known_tables = parse_created_tables(text)
    boot = parse_indexes(text)
    problems: list[str] = []
    for name, (table, cols, where, mig) in sorted(live_migration_indexes().items()):
        if table not in known_tables:
            continue  # 表已被后续迁移 DROP ⇒ 索引无处可落（合法）
        if name not in boot:
            problems.append(f"{name}: {mig} 建了，建库脚本里没有（表 {table}）")
        elif boot[name] != (table, cols, where):
            problems.append(
                f"{name}: 两边定义不一致 —— 迁移 {mig}={table}({cols}) {where} | "
                f"脚本={boot[name][0]}({boot[name][1]}) {boot[name][2]}"
            )
    return problems


# ── 判据 1：活目录 ⇄ 建库脚本 ──────────────────────────────────────────────

def test_every_live_migration_index_reaches_bootstrap():
    problems = drift_problems()
    assert not problems, (
        "活目录的索引没有同步进建库脚本（新环境会永久缺索引，而没有任何门禁会红）：\n  "
        + "\n  ".join(problems)
        + "\n出口：把该索引的终态 DDL 逐字补进 "
        "backend/admin-api/src/main/resources/db/init/schema.sql（第 15 节）。"
    )


def test_hot_path_migration_is_covered_by_its_own_file():
    """本刀迁移必须真存在，且它的每条索引都能在被守的那份脚本里找到。"""
    mig = LIVE_DIR / HOT_PATH_MIGRATION
    assert mig.is_file(), f"缺迁移文件：{HOT_PATH_MIGRATION}"
    idx = parse_indexes(mig.read_text(encoding="utf-8"))
    assert len(idx) >= 20, f"{HOT_PATH_MIGRATION} 的索引数异常（现 {len(idx)} 条）——不许空跑"
    boot = schema_indexes()
    missing = sorted(n for n in idx if n not in boot)
    assert not missing, f"迁移里的索引未进建库脚本：{missing}"


# ── 判据 2：前导列 = tenant_id（多租户读面的形态约束） ─────────────────────

def test_hot_path_indexes_lead_with_tenant_id():
    idx = parse_indexes((LIVE_DIR / HOT_PATH_MIGRATION).read_text(encoding="utf-8"))
    offenders = []
    for name, (table, cols, _where) in idx.items():
        if name in NON_TENANT_LEADING_ALLOWED:
            continue
        lead = cols.split(",")[0].strip().lstrip("(").strip()
        if lead != "tenant_id":
            offenders.append(f"{name}（首列 {lead}，表 {table}）")
    assert not offenders, (
        "多租户读面的索引必须以 tenant_id 打头，否则租户一多就退化成全库扫：\n  "
        + "\n  ".join(offenders)
        + "\n确实不该带租户前缀的，逐条登记到 NON_TENANT_LEADING_ALLOWED 并写明理由。"
    )


# ── 判据 3：幂等 ───────────────────────────────────────────────────────────

def test_live_migration_index_ddl_is_idempotent():
    offenders = []
    for f in sorted(LIVE_DIR.glob("V*.sql")):
        text = strip_sql_comments(f.read_text(encoding="utf-8"))
        for m in re.finditer(r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:CONCURRENTLY\s+)?(\w+)", text, re.I):
            if m.group(1).upper() != "IF":
                offenders.append(f"{f.name}: CREATE INDEX 缺 IF NOT EXISTS")
                break
        for m in re.finditer(r"DROP\s+INDEX\s+(CONCURRENTLY\s+)?(\w+)", text, re.I):
            if m.group(2).upper() != "IF":
                offenders.append(f"{f.name}: DROP INDEX 缺 IF EXISTS")
                break
    assert not offenders, "活目录迁移必须幂等（MigrationRunner 会在终态库上再跑一遍）：\n  " + "\n  ".join(offenders)


# ── 判据 4：判别力自证（注入式，两个方向） ────────────────────────────────

def test_injected_missing_index_is_detected():
    text = SCHEMA.read_text(encoding="utf-8")
    victim = "idx_orders_tenant_created"
    marker = "CREATE INDEX IF NOT EXISTS " + victim
    assert marker in text, f"注入前置不成立：脚本里找不到 {victim}（判据对象已漂移）"
    mutated = text.replace(marker, "CREATE INDEX IF NOT EXISTS " + victim + "_bogus")
    problems = drift_problems(mutated)
    assert any(victim + ":" in p for p in problems), (
        "判别力自证失败：把索引改名后漂移检测没报 —— 说明本判据是空断言。\n"
        f"实测 problems={problems[:3]}"
    )


def test_unrelated_mutation_does_not_trigger_false_positive():
    """负控：**新增**一条迁移里没有的索引 ⇒ 不许判红（防「恒红」/「任何改动都红」）。"""
    text = SCHEMA.read_text(encoding="utf-8")
    mutated = text + "\nCREATE INDEX IF NOT EXISTS idx_not_in_any_migration ON orders (id);\n"
    assert drift_problems(mutated) == []
