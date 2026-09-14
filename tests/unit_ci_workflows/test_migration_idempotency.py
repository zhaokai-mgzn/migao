"""
数据库迁移链幂等性静态不变式（issue #3615）—— **前向防护**（只覆盖新增/未发布迁移）。

## 为什么需要这条不变式（真库实测根因）

独立栈全新库 bootstrap 走的是「**bootstrap-first**」路径：
`docs/sql/schema.sql` 由 docker `docker-entrypoint-initdb.d/001_schema.sql` 建出**终态**，
随后 admin-api 启动再跑一遍 `db/migration/V*__*.sql` 迁移链（`MigrationRunner`）。
⇒ 迁移链里每条语句都可能在「对象已经存在」的库上再执行一次，
即 `MigrationRunner` 类注释写死的约定：**所有 SQL 文件必须幂等**。

违反后果（issue #3615 实测，PG 16.15）：整文件回滚且**不写入 `schema_migrations`**
→ 每次重启重跑、再报一次 → admin-api 日志永久打印
「❌ 本次有 N 条迁移失败，schema 可能与代码不一致（请立即修复并在修复后重跑）」。
本仓库核心痛点是「归因层是最大失败模式」，这条永久红字噪音正是真失败被淹没的机制性原因。

## ⚠️ 射程说明（前向生效，不追溯已发布迁移）

本测试**只对「新增/未发布迁移」生效**，理由是仓库护栏优先级：
`.github/danger_scan.py:87-100` 把「已发布迁移只增不改」定为铁律，且 Danger Scan 是 main 的
9 项 `required_status_checks` 之一 ⇒ **已发布迁移在流程上不可修**。
若本测试对存量 offenders 直接报红，会卡死每一个 PR（包括无关 PR）却给不出可执行的修复路径。
故采用仓库既有的「**显式登记 + 理由**」范式（同 `qa-exemptions` / 用例覆盖存量豁免清单）：
把已诊断清楚的存量缺口逐条写进 `LEGACY_UNGUARDED`，并断言**实际扫描结果与登记表逐条相等** ——
① 新增同类写法 → 立刻红（这就是「这个类不会再增长」的保证）；
② 存量被修掉却忘了销账（CI 外手工修 migration / 豁免项过期）→ 也红（防登记表变垃圾场）。

## 已知存量缺口（8 处 / 3 个文件，逐条登记；修复受 required 护栏约束，待裁决）

| 迁移 | 处数 | kind | 真库实测错误 |
|---|---|---|---|
| `V44__create_daily_briefings.sql` | 1 | `create-policy-not-guarded` | 策略 "tenant_isolation_daily_briefings" 已经存在（`schema.sql:1211-1213` 已建同名策略） |
| `V37__rename_knowledge_entries_to_cards.sql` | 4 | `rename-not-guarded` | 关系 "knowledge_cards" 已经存在（表改名）+ 关系 "idx_knowledge_cards_tenant" 已经存在（索引改名） |
| `V42__reconcile_knowledge_table_name.sql` | 3 | `rename-not-guarded` | 关系 "idx_knowledge_cards_tenant" 已经存在（干净 bootstrap 顺序下靠上面 DO 块的 `DROP TABLE` 连带删源索引而**侥幸**不报错） |

**纠正一处常见误传**：`V37` 的失败**不是**策略错误 —— 该文件全文**没有** `CREATE POLICY`
（全仓 `grep -rn "CREATE POLICY" db/migration/*.sql` 仅命中 V44 一处）。
`V37` 真因是 `ALTER TABLE/INDEX ... IF EXISTS` **只守卫源对象、不守卫目标**。
`V42` 为本次全量扫描**新发现**（issue 原文只点了 V37/V44）。

**后果分级（如实分级，不夸大）**：**噪音 + `schema_migrations` 账本失真（40/42），非真实漏建** ——
逐条比对确认 `schema.sql` 已覆盖这 3 条迁移的全部业务对象
（`daily_briefings` 表/索引/RLS 策略、`tenants.briefing_enabled`/`briefing_generate_time`、
`knowledge_cards` 终态 + 3 索引），无表/列缺失。

## 复现与验证（真库实测，非静态推断）

`scripts/migration_chain_repro.py`（本机无 docker 也能跑，复刻 `MigrationRunner` 的
`jdbc.execute(整文件)` 单事务语义，与 psql `-f` 的分句行为**不同**）：

```
现状（origin/main，含 8 处存量缺口）：42 条迁移 → 2 条失败（V37/V44）、schema_migrations 40 行、打印原告警
```

**修复这 3 个文件所需的幂等守卫写法**（已真库验证可通过 42/42 + 幂等重跑 + 语义不变，
但因受 required 护栏约束**未包含在本次提交中**，仅作为可执行证据留给后续裁决）：
① `V44`：`DO $$ IF NOT EXISTS (SELECT 1 FROM pg_policies ...) THEN CREATE POLICY ... $$`
② `V37`/`V42`：`DO $$ IF EXISTS(源) AND NOT EXISTS(目标) THEN ALTER ... RENAME ... $$`
（PG **不支持** `CREATE POLICY IF NOT EXISTS` —— 实测 PG 16.15 报 `语法错误 在 "NOT" 或附近`。）

## 本测试锁什么

1. 新增/未发布迁移里 **`CREATE POLICY`** 必须与 `pg_policies` 存在性守卫**同块**；
2. 新增/未发布迁移里 **`RENAME`** 必须与目标存在性守卫同块
   （postgres 无 `ALTER TABLE IF NOT EXISTS`；`IF EXISTS` 只守卫源对象 —— V37 的真缺陷）；
3. 实际扫描结果必须与 `LEGACY_UNGUARDED` **逐条相等**（新增→红；存量销账未更新→也红）；
4. 检测器自身有正/负样本自测（防不变式被写弱成永远绿）。

L0 层（秒级、零外部依赖）拦住结构性缺陷，不让它流到真实 LLM 评测层去撞（`migao-dev-flow` §16.1）。
"""
# case_ids: DA-010, API-013
import re
from pathlib import Path

MIGRATION_DIR = (
    Path(__file__).parent.parent.parent
    / "backend" / "admin-api" / "src" / "main" / "resources" / "db" / "migration"
)

# ── 已发布迁移的存量缺口登记表（显式登记 + 理由，非 skip）──
# 修复这 3 个文件受 required 护栏（danger_scan「已发布迁移只增不改」）约束，需先裁决豁免机制；
# 详见模块 docstring「已知存量缺口」。**新增迁移一律不得进本表**（前向防护）。
LEGACY_UNGUARDED = {
    "V37__rename_knowledge_entries_to_cards.sql": {
        ("rename-not-guarded", "ALTER TABLE IF EXISTS knowledge_entries RENAME TO knowledge_cards"),
        ("rename-not-guarded", "ALTER INDEX IF EXISTS idx_knowledge_entries_tenant RENAME TO idx_knowledge_cards_tenant"),
        ("rename-not-guarded", "ALTER INDEX IF EXISTS idx_knowledge_entries_status RENAME TO idx_knowledge_cards_status"),
        ("rename-not-guarded", "ALTER INDEX IF EXISTS idx_knowledge_entries_category RENAME TO idx_knowledge_cards_category"),
    },
    "V42__reconcile_knowledge_table_name.sql": {
        ("rename-not-guarded", "ALTER INDEX IF EXISTS idx_knowledge_entries_tenant RENAME TO idx_knowledge_cards_tenant"),
        ("rename-not-guarded", "ALTER INDEX IF EXISTS idx_knowledge_entries_status RENAME TO idx_knowledge_cards_status"),
        ("rename-not-guarded", "ALTER INDEX IF EXISTS idx_knowledge_entries_category RENAME TO idx_knowledge_cards_category"),
    },
    "V44__create_daily_briefings.sql": {
        ("create-policy-not-guarded", "CREATE POLICY"),
    },
}

# 允许「非幂等写法」的业务豁免（须逐条写理由；当前为空）。
# 注：V29__rebuild_notification_tables.sql 的裸 `CREATE TABLE` **不算**非幂等 ——
# 其文件开头即 `DROP TABLE IF EXISTS ...`（同事务重建），重跑必成功、终态确定，
# 是仓库既有的合法重建范式（见该文件注释「幂等：DROP IF EXISTS + CREATE，重启安全」）。
GUARDED_DDL_EXEMPTIONS: set = set()

# 存量登记表涉及的已发布迁移（前向防护的射程边界）
_PUBLISHED_AT_ISSUE = set(LEGACY_UNGUARDED)

_POLICY_RE = re.compile(r"\bCREATE\s+POLICY\b", re.I)
_RENAME_RE = re.compile(r"\bRENAME\s+TO\b", re.I)
_RENAME_OBJECT_RE = re.compile(
    r"\bALTER\s+(?:TABLE|INDEX)\s+(?:IF\s+EXISTS\s+)?[\w.\"]+\s+RENAME\s+TO\s+[\w.\"]+", re.I
)
# 「条件守卫」的三种既有写法（仓库实际用到的全部形态）：
#   ① `IF NOT EXISTS (SELECT 1 FROM pg_policies ...) THEN ... CREATE POLICY ...`
#   ② `IF EXISTS (源) AND NOT EXISTS (目标) THEN ... RENAME ...`
#   ③ `IF has_entries AND NOT has_cards THEN ... RENAME ...`（V42：条件查进 BOOLEAN 变量后判断）
# 裸 `ALTER ... IF EXISTS ... RENAME` 落在 DO 块**外**，三者皆不命中 → 判非幂等（V37 形态）。
_GUARD_RE = re.compile(
    r"\bNOT\s+EXISTS\s*\(\s*SELECT\b"          # ①/②：内联存在性查询
    r"|\bIF\s+\w+\s+AND\s+NOT\s+\w+\s+THEN\b",  # ③：变量承载的存在性条件
    re.I,
)
_DO_START_RE = re.compile(r"^\s*DO\s*\$", re.I)


def _blocks(sql_text: str) -> list:
    """把文件切成「语句块」用于同块判定 → [(块文本, 是否 DO 块), ...]。

    规则：`DO $$ ... $$` 体整体算**一个**块（守卫与受守卫语句天然同块）；
    其余按 `;` 切分。先剥掉 `--` 行注释，避免注释里的示例语句被误判。
    """
    no_comments = "\n".join(
        line.split("--", 1)[0] for line in sql_text.splitlines()
    )
    blocks, buf, in_do, i = [], [], False, 0
    while i < len(no_comments):
        if no_comments.startswith("$$", i):
            j = no_comments.find("$$", i + 2)  # DO 体结束（$BODY$ 等未用于本仓库迁移）
            if j != -1:
                buf.append(no_comments[i:j + 2])
                i = j + 2
                in_do = True
                continue
        ch = no_comments[i]
        if ch == ";":
            text = "".join(buf)
            blocks.append((text, in_do or bool(_DO_START_RE.match(text))))
            buf, in_do = [], False
        else:
            buf.append(ch)
        i += 1
    text = "".join(buf)
    if text.strip():
        blocks.append((text, in_do or bool(_DO_START_RE.match(text))))
    return [(t, d) for t, d in blocks if t.strip()]


def find_non_idempotent(sql_text: str) -> list:
    """返回该迁移文件里的非幂等写法清单 [(kind, 片段), ...]。

    kind ∈ {"create-policy-not-guarded", "rename-not-guarded"}。
    """
    found = []
    for block, in_do in _blocks(sql_text):
        guarded = bool(_GUARD_RE.search(block))
        if _POLICY_RE.search(block) and not guarded:
            found.append(("create-policy-not-guarded", _POLICY_RE.search(block).group(0)))
        if _RENAME_RE.search(block):
            # DO 块内：由该块的 IF 条件守卫（含 V42 的变量式 `IF x AND NOT y THEN`）；
            # DO 块外：裸 `... IF EXISTS ... RENAME` 自守卫不足 → 必须报出（V37 形态）。
            if not (guarded if in_do else _GUARD_RE.search(block)):
                m = _RENAME_OBJECT_RE.search(block)
                snippet = m.group(0) if m else "RENAME TO"
                found.append(("rename-not-guarded", " ".join(snippet.split())))
    return found


def _scan_all() -> list:
    """全量扫 db/migration/*.sql → [(文件名, kind, 片段), ...]（不含业务豁免）。"""
    hits = []
    for path in sorted(MIGRATION_DIR.glob("*.sql")):
        for kind, snippet in find_non_idempotent(path.read_text(encoding="utf-8")):
            if (path.name, kind, snippet) in GUARDED_DDL_EXEMPTIONS:
                continue
            hits.append((path.name, kind, snippet))
    return hits


def _scan_forward() -> list:
    """只扫**未登记为存量**的迁移文件 → 前向防护射程内的非幂等写法。"""
    return [h for h in _scan_all() if h[0] not in _PUBLISHED_AT_ISSUE]


class TestMigrationIdempotencyInvariant:
    def test_migration_dir_is_present_and_parsed(self):
        """防解析失效：目录必须存在且扫到迁移文件（否则下面的断言永远绿）。"""
        files = sorted(MIGRATION_DIR.glob("*.sql"))
        assert len(files) >= 40, f"迁移文件过少（{len(files)}）—— 路径或解析疑似失效"
        v44 = (MIGRATION_DIR / "V44__create_daily_briefings.sql").read_text(encoding="utf-8")
        assert _blocks(v44), "语句切分结果为空 —— 解析疑似失效"

    def test_detector_catches_non_idempotent_forms(self):
        """检测器自测：负样本必红、正样本必绿（防不变式被写弱成永远绿）。"""
        unguarded_policy = (
            "ALTER TABLE daily_briefings ENABLE ROW LEVEL SECURITY;\n"
            "CREATE POLICY tenant_isolation_daily_briefings ON daily_briefings\n"
            "    USING (tenant_id::text = current_setting('app.current_tenant_id'));\n"
        )
        kinds = {k for k, _ in find_non_idempotent(unguarded_policy)}
        assert "create-policy-not-guarded" in kinds, "检测器漏报裸 CREATE POLICY"

        unguarded_rename = (
            "ALTER TABLE IF EXISTS knowledge_entries RENAME TO knowledge_cards;\n"
            "ALTER INDEX IF EXISTS idx_knowledge_entries_tenant RENAME TO idx_knowledge_cards_tenant;\n"
        )
        kinds = {k for k, _ in find_non_idempotent(unguarded_rename)}
        assert "rename-not-guarded" in kinds, "检测器漏报裸 RENAME"

        guarded_policy = (
            "DO $$\nBEGIN\n"
            "    IF NOT EXISTS (SELECT 1 FROM pg_policies\n"
            "                   WHERE tablename = 'daily_briefings') THEN\n"
            "        CREATE POLICY p ON daily_briefings USING (true);\n"
            "    END IF;\nEND $$;\n"
        )
        assert find_non_idempotent(guarded_policy) == [], "检测器对已守卫的 CREATE POLICY 误报"

        guarded_rename = (
            "DO $$\nBEGIN\n"
            "    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'a')\n"
            "       AND NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'b') THEN\n"
            "        ALTER TABLE a RENAME TO b;\n"
            "    END IF;\nEND $$;\n"
        )
        assert find_non_idempotent(guarded_rename) == [], "检测器对已守卫的 RENAME 误报"

        # V42 形态：条件查进 BOOLEAN 变量再 IF 判断（本仓库既有范式之一，必须不误报）
        var_guard_rename = (
            "DO $$\nDECLARE\n    has_entries BOOLEAN;\nBEGIN\n"
            "    IF has_entries AND NOT has_cards THEN\n"
            "        ALTER TABLE knowledge_entries RENAME TO knowledge_cards;\n"
            "    END IF;\nEND $$;\n"
        )
        assert find_non_idempotent(var_guard_rename) == [], "检测器对 V42 变量式守卫误报"

        # DO 体内无 IF 条件的裸 RENAME 仍须报出（仅「DO 块」本身不构成守卫）
        bare_in_do = (
            "DO $$\nBEGIN\n    ALTER TABLE knowledge_entries RENAME TO knowledge_cards;\nEND $$;\n"
        )
        kinds = {k for k, _ in find_non_idempotent(bare_in_do)}
        assert "rename-not-guarded" in kinds, "检测器漏报 DO 体内无 IF 条件的裸 RENAME"

        # 注释里的示例语句不得被当成真语句（否则纯文档改动会误红）
        commented = "-- CREATE POLICY p ON t USING (true);\n-- ALTER TABLE a RENAME TO b;\n"
        assert find_non_idempotent(commented) == [], "行注释里的示例语句被误判为真语句"

    def test_new_migrations_have_no_unguarded_policy(self):
        """**前向防护**：新增/未发布迁移的 `CREATE POLICY` 必须带 `pg_policies` 守卫。"""
        offenders = [
            f"{name}: {snippet}" for name, kind, snippet in _scan_forward()
            if kind == "create-policy-not-guarded"
        ]
        assert not offenders, (
            "新增迁移存在无幂等守卫的 CREATE POLICY —— bootstrap-first 库（schema.sql 已建同名策略）"
            "上必报「策略已存在」→ 整文件回滚且不写 schema_migrations → 每次启动重跑并打印"
            "「schema 可能与代码不一致」噪音（issue #3615 实测）。\n"
            "修复：照 V42/V25 的 DO $$ + pg_policies 范式包守卫"
            "（PG 不支持 CREATE POLICY IF NOT EXISTS）。\n  " + "\n  ".join(offenders)
        )

    def test_new_migrations_have_no_unguarded_rename(self):
        """**前向防护**：新增/未发布迁移的 `RENAME` 必须带目标存在性守卫。"""
        offenders = [
            f"{name}: {snippet}" for name, kind, snippet in _scan_forward()
            if kind == "rename-not-guarded"
        ]
        assert not offenders, (
            "新增迁移存在无守卫的 RENAME —— `ALTER TABLE/INDEX IF EXISTS` 只守卫**源**，"
            "目标已存在时报「关系 ... 已经存在」→ 整文件回滚且不写 schema_migrations "
            "→ 每次启动重跑并打印噪音（issue #3615：V37 的表改名与 3 条索引改名均属此类）。\n"
            "修复：DO $$ IF EXISTS(源) AND NOT EXISTS(目标) THEN ... END $$;（照 V42 范式）。\n  "
            + "\n  ".join(offenders)
        )

    def test_legacy_registry_matches_reality(self):
        """存量登记表必须与实际逐条相等：新增缺口→红；存量已销账却没更新登记→也红。"""
        actual = {}
        for name, kind, snippet in _scan_all():
            actual.setdefault(name, set()).add((kind, snippet))

        unregistered = {n: v for n, v in actual.items() if n not in LEGACY_UNGUARDED}
        assert not unregistered, (
            "出现**未登记**的非幂等迁移 —— 新增迁移不得进存量登记表（前向防护），"
            "请补幂等守卫而非登记：\n  "
            + "\n  ".join(
                f"{n}: {sorted(k for k, _ in v)}" for n, v in sorted(unregistered.items())
            )
        )

        stale = []
        for name, registered in LEGACY_UNGUARDED.items():
            found = actual.get(name, set())
            if found != registered:
                stale.append(
                    f"{name}: 登记 {len(registered)} 处 / 实际 {len(found)} 处\n"
                    f"      登记但已不存在: {sorted(registered - found)}\n"
                    f"      实际但未登记:   {sorted(found - registered)}"
                )
        assert not stale, (
            "存量登记表与实际不符 —— 若已修好这些迁移，请**同时删掉对应登记条目**"
            "（防登记表变垃圾场；这正是该断言的作用）：\n  " + "\n  ".join(stale)
        )

        # 射程边界自检：存量登记只允许覆盖已诊断的 3 个已发布迁移（前向防护不得被扩成「全部豁免」）
        assert len(LEGACY_UNGUARDED) == 3, (
            f"存量登记表应恰为已诊断的 3 个已发布迁移，实际 {len(LEGACY_UNGUARDED)} 个 —— "
            "新增条目等于把护栏放宽，需先走豁免机制裁决"
        )
        assert not GUARDED_DDL_EXEMPTIONS, "业务豁免清单应保持为空（有豁免必须逐条写理由）"
