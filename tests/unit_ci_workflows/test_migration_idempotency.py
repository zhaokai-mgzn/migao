"""
数据库迁移链幂等性静态不变式（issue #3615）。

## 背景（真库实测根因）

独立栈全新库 bootstrap 的路径是「**bootstrap-first**」：
`docs/sql/schema.sql` 由 docker `docker-entrypoint-initdb.d/001_schema.sql` 建出**终态**，
随后 admin-api 启动再跑一遍 `db/migration/V*__*.sql` 迁移链（`MigrationRunner`）。
⇒ 迁移链里的每条语句都可能在「对象已经存在」的库上再执行一次，
即 `MigrationRunner` 类注释写死的约定：**所有 SQL 文件必须幂等**。

实测（Homebrew PostgreSQL 16.15，issue #3615 复现脚本）有 2 条迁移违反该约定，
每次启动都失败并打印：

    ❌ 本次有 2 条迁移失败，schema 可能与代码不一致（请立即修复并在修复后重跑）：
       [V44__create_daily_briefings.sql, V37__rename_knowledge_entries_to_cards.sql]

| 迁移 | 非幂等写法 | bootstrap-first 库上的实测错误 |
|---|---|---|
| `V44` | 裸 `CREATE POLICY tenant_isolation_daily_briefings` | 策略 already exists（schema.sql 已建同名策略） |
| `V37` | `ALTER TABLE IF EXISTS ... RENAME TO knowledge_cards` | 关系 "knowledge_cards" 已经存在（**IF EXISTS 只守卫源，不守卫目标**） |
| `V37` | `ALTER INDEX IF EXISTS ... RENAME TO idx_knowledge_cards_*` | 关系 "idx_knowledge_cards_tenant" 已经存在（同上，同源缺陷） |

**危害是「归因污染」而非数据漏建**：失败文件整条回滚且**不写入 `schema_migrations`**
（实测 42 个迁移文件只记 40 行）→ 每次重启重跑再报一次 → admin-api 日志永久留红字
「schema 可能与代码不一致」，把真失败（如 issue #3270 的 V28）淹没在噪音里。
本仓库核心痛点即「归因层是最大失败模式」，故用 L0 静态不变式（秒级、零外部依赖）拦死复发。

## 本测试锁什么

1. `db/migration/*.sql` 内**所有 `CREATE POLICY`** 必须与 `pg_policies` 存在性守卫**同块**
   （PG 不支持 `CREATE POLICY IF NOT EXISTS` —— 实测 PG 16.15 报语法错误，
   故只有 `DO $$ ... IF NOT EXISTS (SELECT 1 FROM pg_policies ...) $$` 一种合法写法）；
2. `db/migration/*.sql` 内**所有 `RENAME`** 必须与目标存在性守卫同块
   （postgres 没有 `ALTER TABLE IF NOT EXISTS`；`IF EXISTS` 只守卫源对象，
   目标已存在时必报错 —— 这正是 V37 的真缺陷）；
3. **已知缺口清单**必须为空（当前为 0 条）—— 修复前本测试正好列出 V37/V44 的 3 处；
4. 检测器自身有正/负样本自测（防「不变式被写弱到永远绿」）。

修复后若新增同类非幂等写法，本测试立即变红（L0 拦住，不流到真实 LLM 评测层去撞）。

**验证方式（本地真库实测，非静态推断）**：本机无 docker，用 Homebrew `initdb` 起 PG 16.15，
`psql -v ON_ERROR_STOP=1 -f docs/sql/schema.sql` 后按版本号数值序逐文件执行迁移链
（复刻 `MigrationRunner` 的 `jdbc.execute(整文件)` 单事务语义）：
修复前 42 文件中 2 条失败（V37/V44）、`schema_migrations` 40 行；
修复后 **42/42 成功、42 行、零告警**，且「清空 `schema_migrations` 全量重跑」仍全绿（幂等），
「只有 `knowledge_entries` 的老库」V37 仍正确改名、「无 `daily_briefings` 的库」V44 仍建表+索引+策略
（首次执行语义未变）。
"""
# case_ids: DA-010, API-013
import re
from pathlib import Path

MIGRATION_DIR = (
    Path(__file__).parent.parent.parent
    / "backend" / "admin-api" / "src" / "main" / "resources" / "db" / "migration"
)

# ── 已知缺口清单（工作清单：修完即删条目；新增同类写法一律拦截）──
# 修复前此处应为：
#   ("V37__rename_knowledge_entries_to_cards.sql", "rename-not-guarded"),
#   ("V44__create_daily_briefings.sql", "create-policy-not-guarded"),
# 修复（issue #3615）后已全部销账 → 空。
KNOWN_GAPS: set = set()

# 允许「非幂等写法」的场景（须逐条写理由；当前为空）
# 注：V29__rebuild_notification_tables.sql 的裸 `CREATE TABLE` **不算**非幂等 ——
# 其文件开头即 `DROP TABLE IF EXISTS ...`（同事务重建），重跑必成功、终态确定，
# 是仓库既有的合法重建范式（见该文件注释「幂等：DROP IF EXISTS + CREATE，重启安全」）。
GUARDED_DDL_EXEMPTIONS: set = set()

_POLICY_RE = re.compile(r"\bCREATE\s+POLICY\b", re.I)
_RENAME_RE = re.compile(r"\bRENAME\s+TO\b", re.I)
_RENAME_OBJECT_RE = re.compile(
    r"\bALTER\s+(?:TABLE|INDEX)\s+(?:IF\s+EXISTS\s+)?[\w.\"]+\s+RENAME\s+TO\s+[\w.\"]+", re.I
)
# 「条件守卫」的三种既有写法（仓库实际用到的全部形态）：
#   ① `IF NOT EXISTS (SELECT 1 FROM pg_policies ...) THEN ... CREATE POLICY ...`
#   ② `IF EXISTS (源) AND NOT EXISTS (目标) THEN ... RENAME ...`
#   ③ `IF has_entries AND NOT has_cards THEN ... RENAME ...`（V42：条件查进 BOOLEAN 变量后判断）
# ①/② 认 `NOT EXISTS (SELECT`；③ 认 `IF <cond> THEN`（DO 体内用变量承载存在性判断）。
# 裸 `ALTER ... IF EXISTS ... RENAME` 落在 DO 块**外**，三者皆不命中 → 判非幂等（V37 原形态）。
_GUARD_RE = re.compile(
    r"\bNOT\s+EXISTS\s*\(\s*SELECT\b"      # ①/②：内联存在性查询
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
            # DO 块外：裸 `... IF EXISTS ... RENAME` 自守卫不足 → 必须报出（V37 原形态）。
            if not (guarded if in_do else _GUARD_RE.search(block)):
                m = _RENAME_OBJECT_RE.search(block)
                snippet = m.group(0) if m else "RENAME TO"
                found.append(("rename-not-guarded", " ".join(snippet.split())))
    return found


def _scan_all() -> list:
    """全量扫 db/migration/*.sql → [(文件名, kind, 片段), ...]（不含已知豁免）。"""
    hits = []
    for path in sorted(MIGRATION_DIR.glob("*.sql")):
        for kind, snippet in find_non_idempotent(path.read_text(encoding="utf-8")):
            if (path.name, kind, snippet) in GUARDED_DDL_EXEMPTIONS:
                continue
            hits.append((path.name, kind, snippet))
    return hits


class TestMigrationIdempotencyInvariant:
    def test_migration_dir_is_present_and_parsed(self):
        """防解析失效：目录必须存在且扫到迁移文件（否则下面的断言永远绿）。"""
        files = sorted(MIGRATION_DIR.glob("*.sql"))
        assert len(files) >= 40, f"迁移文件过少（{len(files)}）—— 路径或解析疑似失效"
        # 解析器必须真的能扫出东西：拿一条真实迁移自证
        v44 = (MIGRATION_DIR / "V44__create_daily_briefings.sql").read_text(encoding="utf-8")
        assert _blocks(v44), "语句切分结果为空 —— 解析疑似失效"

    def test_no_unguarded_create_policy(self):
        """`CREATE POLICY` 必须与 `pg_policies` 存在性守卫同块（PG 无 IF NOT EXISTS 语法）。"""
        offenders = [
            f"{name}: {snippet}" for name, kind, snippet in _scan_all()
            if kind == "create-policy-not-guarded"
        ]
        assert not offenders, (
            "db/migration/*.sql 存在无幂等守卫的 CREATE POLICY —— bootstrap-first 库"
            "（schema.sql 已建同名策略）上必报「策略已存在」→ 整文件回滚且不写 schema_migrations "
            "→ 每次启动重跑并打印「schema 可能与代码不一致」噪音（issue #3615 实测）。\n"
            "修复：照 V42/V25 的 DO $$ + pg_policies 范式包守卫（PG 不支持 CREATE POLICY IF NOT EXISTS）。\n  "
            + "\n  ".join(offenders)
        )

    def test_no_unguarded_rename(self):
        """`RENAME` 必须与目标存在性守卫同块（`IF EXISTS` 只守卫源对象，不守卫目标）。"""
        offenders = [
            f"{name}: {snippet}" for name, kind, snippet in _scan_all()
            if kind == "rename-not-guarded"
        ]
        assert not offenders, (
            "db/migration/*.sql 存在无守卫的 RENAME —— `ALTER TABLE/INDEX IF EXISTS` 只守卫**源**，"
            "目标已存在时报「关系 ... 已经存在」→ 整文件回滚且不写 schema_migrations "
            "→ 每次启动重跑并打印噪音（issue #3615：V37 的表改名与 3 条索引改名均属此类）。\n"
            "修复：DO $$ IF EXISTS(源) AND NOT EXISTS(目标) THEN ... END $$;（照 V42 范式）。\n  "
            + "\n  ".join(offenders)
        )

    def test_known_gaps_are_empty(self):
        """已知缺口清单必须为空 —— 修复前本测试正好列出 V37/V44 的 3 处非幂等写法。"""
        hits = {kind for _n, kind, _s in _scan_all()}
        assert not hits, (
            f"db/migration/*.sql 仍有非幂等写法（kind={sorted(hits)}）—— "
            "见 test_no_unguarded_create_policy / test_no_unguarded_rename 的明细"
        )
        assert not GUARDED_DDL_EXEMPTIONS, "豁免清单应保持为空（有豁免必须逐条写理由）"

    def test_detector_catches_regression_samples(self):
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

        # 裸 RENAME 落在 DO 块外（V37 原形态）必须报出
        bare_in_do = (
            "DO $$\nBEGIN\n    ALTER TABLE knowledge_entries RENAME TO knowledge_cards;\nEND $$;\n"
        )
        kinds = {k for k, _ in find_non_idempotent(bare_in_do)}
        assert "rename-not-guarded" in kinds, "检测器漏报 DO 体内无 IF 条件的裸 RENAME"

        # 注释里的示例语句不得被当成真语句（否则纯文档改动会误红）
        commented = "-- CREATE POLICY p ON t USING (true);\n-- ALTER TABLE a RENAME TO b;\n"
        assert find_non_idempotent(commented) == [], "行注释里的示例语句被误判为真语句"

    def test_fixed_migrations_keep_their_guards(self):
        """回归锚点：V37/V44 的守卫原样保留（防被后来者改回裸写法）。"""
        v37 = (MIGRATION_DIR / "V37__rename_knowledge_entries_to_cards.sql").read_text(encoding="utf-8")
        assert "knowledge_entries" in v37 and "knowledge_cards" in v37
        assert v37.count("information_schema.tables") + v37.count("pg_class") >= 4, (
            "V37 表/索引改名缺少源+目标双向守卫"
        )
        v44 = (MIGRATION_DIR / "V44__create_daily_briefings.sql").read_text(encoding="utf-8")
        assert "pg_policies" in v44, "V44 RLS 策略缺少 pg_policies 存在性守卫"
        assert "ENABLE ROW LEVEL SECURITY" in v44, "V44 不得丢掉 RLS 启用语句（语义不许变）"
