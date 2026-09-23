# case_ids: DA-010, API-013
#   ⚠️ case_ids 必须在文件前 50 行内 —— `.github/growth_gate.py:extract_case_ids()` 只扫前 50 行
#   （本地实测：本行原放在 docstring 之后第 71 行 → QA Growth Gate 报
#    「新增测试未声明 case_ids」block。docstring 较长时尤其注意）。
"""
数据库迁移链幂等性静态不变式（issue #3615）—— **前向防护**（只覆盖新增/未发布迁移）。

## 为什么需要这条不变式（真库实测根因）

独立栈全新库 bootstrap 走的是「**bootstrap-first**」路径：
`backend/admin-api/src/main/resources/db/init/schema.sql` 由 docker `docker-entrypoint-initdb.d/001_schema.sql` 建出**终态**，
随后 admin-api 启动再跑一遍 `db/migration/V*__*.sql` 迁移链（`MigrationRunner`）。
⇒ 迁移链里每条语句都可能在「对象已经存在」的库上再执行一次，
即 `MigrationRunner` 类注释写死的约定：**所有 SQL 文件必须幂等**。

违反后果（issue #3615 实测，PG 16.15）：整文件回滚且**不写入 `schema_migrations`**
→ 每次重启重跑、再报一次 → admin-api 日志永久打印
「❌ 本次有 N 条迁移失败，schema 可能与代码不一致（请立即修复并在修复后重跑）」。
本仓库核心痛点是「归因层是最大失败模式」，这条永久红字噪音正是真失败被淹没的机制性原因。

## ⚠️ 射程说明（前向生效，不追溯已发布迁移）

本测试**只对「新增/未发布迁移」生效**，理由是仓库护栏优先级：
`.github/danger_scan.py` 把「已发布迁移只增不改」定为铁律，且 Danger Scan 是 main 的
9 项 `required_status_checks` 之一 ⇒ **已发布迁移在流程上不可修**。
若本测试对存量 offenders 直接报红，会卡死每一个 PR（包括无关 PR）却给不出可执行的修复路径。
故采用仓库既有的「**显式登记 + 理由**」范式（同 `qa-exemptions` / 用例覆盖存量豁免清单）：
把已诊断清楚的存量缺口逐条写进 `LEGACY_UNGUARDED`，并断言**实际扫描结果与登记表逐条相等** ——
① 新增同类写法 → 立刻红（这就是「这个类不会再增长」的保证）；
② 存量被修掉却忘了销账（CI 外手工修 migration / 豁免项过期）→ 也红（防登记表变垃圾场）。

## 已知存量缺口（8 处 / 3 个文件，逐条登记；修复受 required 护栏约束，待裁决）

| 迁移 | 处数 | kind | 真库实测错误 |
|---|---|---|---|
| `V44__create_daily_briefings.sql` | 1 | `create-policy-not-guarded` | 策略 "tenant_isolation_daily_briefings" 已经存在（`schema.sql` 里已建同名策略） |
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
4. 检测器自身有正/负样本自测（防不变式被写弱成永远绿）；
5. `MigrationRunner.KNOWN_BENIGN_LEGACY` ↔ `BENIGN_LEGACY_FAILURES` **键集合相等**，
   且**两条护栏**成立（#4991）：登记必须写明可机械核验的「目标态由谁达成」（补偿迁移须真实存在
   且晚于被补偿者）、每条必须有非空且形态合法的 **SQLSTATE 错误签名**（防退化成「只按文件名降级」）。

L0 层（秒级、零外部依赖）拦住结构性缺陷，不让它流到真实 LLM 评测层去撞（`migao-dev-flow` §16.1）。
"""
import re
from pathlib import Path

MIGRATION_DIR = (

    Path(__file__).parent.parent.parent
    / "backend" / "admin-api" / "src" / "main" / "resources" / "db" / "migration-archive"
)

# ── 迁移文件的**两个**载体目录（issue #5243）—— 单一事实源 = `_migration_paths.py`
# 共享件（issue #5243）：`tests/` 上 sys.path 才能按**包名**导入；直接以脚本运行时
#（如 `python3 tests/unit_ci_workflows/test_migration_immutability.py --write-ledger`）
# 包不在路径上，故显式补一次 —— 两种入口都要能跑。
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))
from unit_ci_workflows._migration_paths import LIVE_DIR as _LIVE_MIGRATION_DIR, migration_files as _migration_files

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

# ── 单一事实源：Java `MigrationRunner.KNOWN_BENIGN_LEGACY`（issue #3714 / #4991）──
# 背景：评测栈 bootstrap-first 起栈时，MigrationRunner 逐条执行迁移链，在册的存量迁移必失败
# → 每次起栈都打印 `❌ 本次有 N 条迁移失败，schema 可能与代码不一致（请立即修复并在修复后重跑）`。
# 这句行动指令**必然为假**（无物可修、重跑必复现）→ 告警疲劳 → 真失败与永久噪音**同形**，
# 正是本仓库自认的最大失败模式（归因层失效）。
#
# 修法（不触碰已发布迁移：`.github/danger_scan.py` 的「已发布迁移只增不改」是 required 护栏）：
# Java 侧 `KNOWN_BENIGN_LEGACY` 命中即降级为 INFO + 汇总行分开计数，**真失败仍 ERROR**。
#
# ⚠️ **与 `LEGACY_UNGUARDED` 是两件事（#4991 解耦）**：
#   · `LEGACY_UNGUARDED` = **静态 DDL 守卫缺口**（检测器按 kind 发现：裸 CREATE POLICY / 裸 RENAME）；
#   · `BENIGN_LEGACY_FAILURES` = **运行期失败良性**（目标态已由 schema.sql 或补偿迁移达成）。
# 两者今天**不相等**：V40/V72/V74/V79 是「引用不存在的列 / ON CONFLICT 仲裁列不全 / VALUES 整列 NULL
# 被推断成 text」—— 本检测器**根本不检测**这些形态，塞进 `LEGACY_UNGUARDED` 会当场破
# `test_legacy_registry_matches_reality` 与「恰为 3 个」的射程断言。故拆成两份登记表，各锁各的纪律。
#
# ⚠️ 解析口径（#4991 起）：标记区间内每条必须写成
#   `"<文件名>", new BenignLegacy("<目标态由谁达成>", List.of("<SQLSTATE>[:<标识符>]"…), "<理由>")`
# **内容（目标态由谁达成 / 签名 / 理由）一律以 Java 为权威**，本模块只镜像**键集合**
# （避免「同一判据两份实现必然漂移」#3701）。
# 解析器对「区间内出现 `V{n}__x.sql` 形态的字面量却没被解析成键」**fail-closed 报错** ——
# 那正是「理由 / 字段里写了完整迁移文件名 ⇒ 键集合虚假膨胀」的形态判据。
_REPO_ROOT = Path(__file__).parent.parent.parent
_MIGRATION_RUNNER_JAVA = (
    _REPO_ROOT
    / "backend" / "admin-api" / "src" / "main" / "java" / "com" / "migao" / "admin"
    / "config" / "MigrationRunner.java"
)
_SCHEMA_SQL = _REPO_ROOT / "backend/admin-api/src/main/resources/db/init/schema.sql"
_JAVA_KEY_MARKER = "MIGAO_BENIGN_LEGACY_BEGIN"
_JAVA_KEY_END_MARKER = "MIGAO_BENIGN_LEGACY_END"
# 键形态 = 迁移文件名（V{n}__desc.sql）—— **按文本出现**取，不是只取「整条字面量」：
# 后者抓不到「理由里嵌了一个完整迁移文件名」（那正是键集合虚假膨胀的形态）。
_JAVA_MIGRATION_FILENAME_IN_TEXT_RE = re.compile(r"V\d+__[\w.]+\.sql")
# 条目形态（勿改形状）：`"<文件名>", new BenignLegacy("<目标态由谁达成>", List.of(<签名…>), "<理由>")`
_JAVA_BENIGN_ENTRY_RE = re.compile(
    r'"([^"\\]+\.sql)"\s*,\s*new\s+BenignLegacy\(\s*"([^"\\]*)"\s*,\s*'
    r'List\.of\(([^)]*)\)\s*,\s*"((?:[^"\\]|\\.)*)"\s*\)',
    re.S,
)
# 错误签名形态：`<5 位 SQLSTATE>` 或 `<SQLSTATE>:<标识符子串>`。
# ⚠️ SQLSTATE 是**大写字母数字**（如 `42P07` / `42703` / `23505`），不是纯数字。
_SQLSTATE_SIG_RE = re.compile(r"[0-9A-Z]{5}(:.+)?")

# ── 镜像键集合：Java `KNOWN_BENIGN_LEGACY` 的键必须与本表**完全相等**（#4991）──
# 只镜像键；目标态 / 签名 / 理由以 Java 为权威（解析见 `parse_java_known_benign`）。
# ⚠️ **本表只能变短**：某条被新迁移补齐 / 被裁决修好后两边同时销账；
# **新增迁移一律不得进本表**（前向防护：新迁移必须自带幂等守卫）。
BENIGN_LEGACY_FAILURES = {
    "V37__rename_knowledge_entries_to_cards.sql",
    "V42__reconcile_knowledge_table_name.sql",
    "V44__create_daily_briefings.sql",
    "V40__seed_default_tenant_and_roles.sql",
    "V72__switch_routing_model_consumers.sql",
    "V74__backfill_legacy_special_option_names.sql",
    "V79__seed_fabric_route_and_packing_operation.sql",
}


def parse_java_known_benign(java_text: str) -> dict:
    """从 `MigrationRunner.java` 源码文本提取登记表 → {文件名: {terminal_state_by, signatures, reason}}。

    标记缺失 / 重复 → 抛错（fail-closed，**不得**静默返回空 dict —— 空 dict 会让
    「两边集合相等」断言在空集上恒真，那正是空断言）。
    """
    # 防误命中：两个标记都必须**恰好出现一次**且顺序正确 —— 0 次 = 边界不可知；
    # 多次 = 可能有多份集合。两种情况都必须响（fail-closed，不能猜、不能静默返回空集）
    n_start, n_end = java_text.count(_JAVA_KEY_MARKER), java_text.count(_JAVA_KEY_END_MARKER)
    if n_start != 1 or n_end != 1:
        raise AssertionError(
            f"`{_JAVA_KEY_MARKER}` / `{_JAVA_KEY_END_MARKER}` 在 MigrationRunner.java 里"
            f"出现次数应各为 1，实际 {n_start} / {n_end} —— 缺失或重复都让键边界不可知"
            "（重复会静默合并多份集合，判据失守）"
        )
    start = java_text.find(_JAVA_KEY_MARKER)
    end = java_text.find(_JAVA_KEY_END_MARKER)
    if end < start:
        raise AssertionError(
            f"`{_JAVA_KEY_END_MARKER}` 出现在 `{_JAVA_KEY_MARKER}` 声明之前 —— "
            "解析区间为空（fail-closed）"
        )
    body = java_text[start:end]
    entries = {}
    for m in _JAVA_BENIGN_ENTRY_RE.finditer(body):
        name, terminal, sigs_raw, reason = m.group(1), m.group(2), m.group(3), m.group(4)
        entries[name] = {
            "terminal_state_by": terminal,
            "signatures": re.findall(r'"([^"]*)"', sigs_raw),
            "reason": reason,
        }
    # fail-closed：区间内**所有** `V{n}__x.sql` 形态的文本都必须恰好是被解析到的**键** ——
    # 多出来的必然是「理由 / 字段里写了完整迁移文件名」（键集合虚假膨胀的形态判据）。
    literals = set(_JAVA_MIGRATION_FILENAME_IN_TEXT_RE.findall(body))
    if literals != set(entries):
        raise AssertionError(
            "标记区间内的迁移文件名字面量与解析到的键不相等 —— 解析口径失效，或"
            "「理由 / 字段里写了完整迁移文件名」（会让键集合虚假膨胀）。\n"
            f"  字面量但未解析成键: {sorted(literals - set(entries))}\n"
            f"  解析成键但无字面量: {sorted(set(entries) - literals)}"
        )
    return entries


def find_terminal_state_problems(entries: dict) -> list:
    """护栏①（#4991）的**唯一实现点**：登记条目必须给出可机械核验的「目标态由谁达成」。

    `schema.sql` = bootstrap 终态达成；裸版本号 `V<n>` = 由该**补偿迁移**达成
    （必须真实存在且**晚于**被补偿者）。
    """
    problems = []
    for name, entry in sorted(entries.items()):
        broken = int(re.match(r"^V(\d+)__", name).group(1))
        by = entry["terminal_state_by"]
        if by == "schema.sql":
            if not _SCHEMA_SQL.exists():
                problems.append(f"{name}: 声称目标态由 schema.sql 达成，但该文件不存在")
            continue
        m = re.fullmatch(r"V(\d+)", by)
        if not m:
            problems.append(
                f"{name}: `terminal_state_by` 必须是 `schema.sql` 或裸版本号 `V<n>`，实际 {by!r}"
            )
            continue
        comp = int(m.group(1))
        if not sorted(_migration_files(f"V{comp}__*.sql")):
            problems.append(f"{name}: 登记的补偿迁移 V{comp} 在迁移链里**不存在** —— 登记必须有据")
        elif comp <= broken:
            problems.append(f"{name}: 补偿迁移 V{comp} 必须**晚于**被补偿的 V{broken}")
    return problems


def find_signature_problems(entries: dict) -> list:
    """护栏②（#4991）的**唯一实现点**：每条必须有合法（非空、SQLSTATE 形态）的错误签名。

    空签名 = 退化成「命中文件名即降级」—— 同一文件换一个错因会被静默吞掉（本仓最大的失败模式）。
    """
    problems = []
    for name, entry in sorted(entries.items()):
        sigs = entry["signatures"]
        if not sigs:
            problems.append(f"{name}: 没有任何错误签名 ⇒ 退化成「命中文件名即降级」")
            continue
        for sig in sigs:
            if not _SQLSTATE_SIG_RE.fullmatch(sig):
                problems.append(
                    f"{name}: 签名 {sig!r} 形态非法（应为 `<5 位 SQLSTATE>` 或 `<SQLSTATE>:<标识符>`）"
                )
    return problems


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
    for path in sorted(_migration_files("*.sql")):
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
        files = sorted(_migration_files("*.sql"))
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


class TestKnownBenignLegacyRegistry:
    """Java `KNOWN_BENIGN_LEGACY` ↔ Python `BENIGN_LEGACY_FAILURES` 的键集合 + 两条护栏（#3714 / #4991）。

    为什么需要（#3701 教训）：同一个判据两份实现 ⇒ 必然漂移。Java 侧降级谁、Python 侧登记谁，
    是同一个事实（「哪些存量失败已诊断且目标态已达成」）；两边各自维护 = 迟早一边降级了
    而另一边没登记（或反之）。漂移后果是**假绿**：
      · Java 多降级一条 → 真失败被当噪音吞掉（告警失效）；
      · Python 多登记一条 → 前向防护的射程边界被悄悄放宽（新迁移漏网）。
    """

    def _java_entries(self) -> dict:
        assert _MIGRATION_RUNNER_JAVA.exists(), (
            f"找不到 MigrationRunner.java: {_MIGRATION_RUNNER_JAVA}"
        )
        return parse_java_known_benign(_MIGRATION_RUNNER_JAVA.read_text(encoding="utf-8"))

    def test_java_and_python_key_sets_are_equal(self):
        java_keys = set(self._java_entries())
        py_keys = set(BENIGN_LEGACY_FAILURES)

        # 非空前提（防「空集上恒真」的空断言）：两边都必须真解析出东西
        assert java_keys, (
            "MigrationRunner.java 的 `KNOWN_BENIGN_LEGACY` 解析结果为空 —— "
            "要么集合被删空（噪音修法退化）、要么解析口径失效（fail-closed）"
        )
        assert py_keys, "镜像键集合为空 —— 本测试失去被测对象（存量若真已清空，请一并删本测试）"

        assert java_keys == py_keys, (
            "Java `KNOWN_BENIGN_LEGACY` 与 Python `BENIGN_LEGACY_FAILURES` **键集合不相等** —— "
            "两边是同一个判据的两份实现，漂移即假绿（#3714 / #3701）。\n"
            f"  只在 Java（会被降级为 INFO，但 Python 未登记）: {sorted(java_keys - py_keys)}\n"
            f"  只在 Python（前向防护射程被放宽，Java 未降级）: {sorted(py_keys - java_keys)}\n"
            "  修复：两边同步增删；若某迁移已被新迁移补齐/已修好，**两边同时销账**（该集合只能变短）。"
        )

    def test_every_entry_names_a_real_terminal_state(self):
        """护栏①（#4991）：登记必须有据 —— 「目标态由谁达成」必须可机械核验。"""
        problems = find_terminal_state_problems(self._java_entries())
        assert not problems, (
            "「已知存量非幂等」登记表里有条目**给不出目标态达成的依据**（#4991 护栏①）——"
            "「目标态已达成」不是一句可以随手写的话，它必须指向 `schema.sql` 或一条**真实存在且"
            "晚于被补偿者**的补偿迁移：\n  " + "\n  ".join(problems)
        )

    def test_every_entry_has_an_sqlstate_signature(self):
        """护栏②（#4991）：判定不得退化成「只按文件名降级」。"""
        problems = find_signature_problems(self._java_entries())
        assert not problems, (
            "「已知存量非幂等」登记表里有条目的**错误签名**缺失或非法（#4991 护栏②）——"
            "没有签名 = 命中文件名就降级 ⇒ 同一文件换一个错因（真病灶）会被静默吞掉：\n  "
            + "\n  ".join(problems)
        )

    def test_registry_has_not_grown(self):
        """只能变短：新增条目等于把护栏放宽，必须先走裁决（#4991 已裁决的存量 = 7 条）。"""
        assert len(BENIGN_LEGACY_FAILURES) == 7, (
            f"`BENIGN_LEGACY_FAILURES` 应有 7 条（#4991 已裁决的存量），"
            f"实际 {len(BENIGN_LEGACY_FAILURES)} 条 —— **新增条目等于把护栏放宽**"
            "（新迁移必须自带幂等守卫，不得进本表）；缩短请同步改这个数字（防登记表变垃圾场）"
        )

    def test_registry_entries_are_all_published_migrations(self):
        """登记项必须**真实存在**于迁移链（防「登记了一个不存在的文件名」⇒ 哨兵永远不触发）。"""
        missing = sorted(n for n in BENIGN_LEGACY_FAILURES if not (MIGRATION_DIR / n).exists())
        assert not missing, f"登记表里有迁移链中不存在的文件名：{missing}"

    # ── 注入式红证（不依赖仓库真值；形态见 migao-acceptance v1.4「断言形态」）──

    def test_terminal_state_guard_has_red_control(self):
        """护栏①的红证：引用不存在的补偿迁移 / 补偿早于被补偿 / 取值非法 ⇒ 必被判出。"""
        assert find_terminal_state_problems({
            "V99__injected_broken.sql": {"terminal_state_by": "V999", "signatures": ["42703:x"]},
        }), "「引用了不存在的补偿迁移」未被判出 —— 护栏① 失效"
        assert find_terminal_state_problems({
            "V99__injected_broken.sql": {"terminal_state_by": "V44", "signatures": ["42703:x"]},
        }), "「补偿迁移早于被补偿者」未被判出 —— 护栏① 失效"
        assert find_terminal_state_problems({
            "V99__injected_broken.sql": {"terminal_state_by": "猜的", "signatures": ["42703:x"]},
        }), "非 `schema.sql` / 非 `V<n>` 的取值未被判出 —— 护栏① 失效"
        # 正向：合法条目不得被误报
        assert find_terminal_state_problems({
            "V99__ok.sql": {"terminal_state_by": "schema.sql", "signatures": ["42P07"]},
        }) == [], "合法条目被误报 —— 判据过严（会逼出「为过门禁而改文案」）"

    def test_signature_guard_has_red_control(self):
        """护栏②的红证：空签名 / 非法签名 ⇒ 必被判出。"""
        assert find_signature_problems({
            "V99__injected_broken.sql": {"terminal_state_by": "schema.sql", "signatures": []},
        }), "空签名未被判出 —— 退化成「只按文件名降级」"
        assert find_signature_problems({
            "V99__injected_broken.sql": {"terminal_state_by": "schema.sql", "signatures": ["字段不存在"]},
        }), "非 SQLSTATE 形态的签名未被判出 —— 护栏② 失效"
        assert find_signature_problems({
            "V99__ok.sql": {"terminal_state_by": "schema.sql", "signatures": ["42P07", "23505:a"]},
        }) == [], "合法签名被误报"

    def test_parser_fails_closed_on_polluted_reason(self):
        """解析口径的红证：理由里写完整迁移文件名 ⇒ 键集合虚假膨胀 ⇒ 必抛错。

        形态选择：**注入式红证** 而非「真值主张」——后者（`assert 仓库当下恰有该缺陷`）会在
        缺陷被修好的那一刻自毁、并把报错指向无关 PR（migao-acceptance v1.4「断言形态」）。
        """
        base = "V44__create_daily_briefings.sql"
        good = (
            "    // MIGAO_BENIGN_LEGACY_BEGIN\n"
            "    static final Map<String, BenignLegacy> KNOWN_BENIGN_LEGACY = Map.ofEntries(\n"
            f'            Map.entry("{base}",\n'
            '                    new BenignLegacy("schema.sql", List.of("42710:p"), "理由（见 #3714）")));\n'
            "    // MIGAO_BENIGN_LEGACY_END\n"
        )
        parsed = parse_java_known_benign(good)
        assert set(parsed) == {base}, "合法条目解析出的键不对"
        assert parsed[base]["terminal_state_by"] == "schema.sql"
        assert parsed[base]["signatures"] == ["42710:p"]

        # ① 理由里写了完整迁移文件名 ⇒ 键集合被撑大 ⇒ 必须 fail-closed
        polluted = good.replace("理由（见 #3714）", "理由：由 V76__redo_v72_with_sort_order_fix.sql 补偿")
        try:
            parse_java_known_benign(polluted)
        except AssertionError:
            pass
        else:
            raise AssertionError(
                "理由里的完整迁移文件名未被判出 —— 键集合会虚假膨胀（两边相等断言被污染）"
            )

        # ② 多签名条目必须被完整解析（V79 形态：一条目两种真库错误）
        multi = good.replace(
            'List.of("42710:p")', 'List.of("42804:unit_price", "23505:production_operations_pkey")'
        )
        assert parse_java_known_benign(multi)[base]["signatures"] == [
            "42804:unit_price", "23505:production_operations_pkey",
        ], "多签名条目被截断（V79 的第二种真库形态会漏判 ⇒ 假红）"

        # ③ 声明标记缺失 / 重复 ⇒ 必须抛错，不得静默返回空 dict（否则相等断言在空集上恒真）
        for broken, why in [
            (good.replace("// MIGAO_BENIGN_LEGACY_BEGIN\n", ""), "声明标记缺失"),
            (good.replace("MIGAO_BENIGN_LEGACY_END", "（无结束标记）"), "结束标记缺失"),
            # 标记重复：两份集合若被静默合并，等于判据失守
            (good + good, "标记重复"),
        ]:
            try:
                parse_java_known_benign(broken)
            except AssertionError:
                continue
            raise AssertionError(f"{why} 时解析器未 fail-closed（静默返回了集合）")
