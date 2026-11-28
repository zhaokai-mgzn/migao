# case_ids: CH-046
"""V219（存量租户 `bot_name` 回填：'米宝' → '智能客服'）的形态 + 真库两遍幂等判据（issue #9308）。

## 病根（为什么"只改代码默认值"不够）

`backend/ai-agent-service/app/agents/agents/xiaobu.py` 里 `DEFAULT_BOT_NAME = "智能客服"`
（issue #9304）只改了**默认值**；而 `get_xiaobu_greeting()` 的取值是
`bot_name = data.get("botName") or DEFAULT_BOT_NAME` —— **租户配置优先**。
`tenant_ai_configs.bot_name` 里的 '米宝' 是 V213（「元元 → 米宝」）当年**物化**进表里的行值
⇒ 存量商户的顾客照旧被退役品牌名问候。

## 本文件钉什么

| 面 | 判据 |
|---|---|
| 存在 / 账本 | 迁移文件存在、版本号唯一且是最大号、已登记进内容指纹账本（否则以后能被静默改） |
| 形态（静态） | `WHERE` 是**逐字相等**（`bot_name = '米宝'`），**不许** `LIKE` / `ILIKE` / `~` / `%`；只写 `bot_name` + `updated_at` 两列；不 INSERT / DELETE / ALTER（不改列定义、不改默认值）；显式 `BEGIN;` / `COMMIT;` |
| 真库（临时 PG） | 四行夹具：'米宝' 变 '智能客服'、'小美' 原样、**'米宝小助手' 原样**（含旧品牌名子串的自定义名必须被保护）、NULL 原样；行数不变 |
| 真库幂等 | 连跑两遍：第一遍 `UPDATE 1`、第二遍 **`UPDATE 0`**，净效果逐值相同 |
| 判别力（注入红证） | 把 `WHERE` 注入成 `LIKE '%米宝%'` ⇒ '米宝小助手' **会被改**（而 '小美' 仍不受影响）⇒ 证明「保护自定义值」这条断言**不是恒真** |

## 真库口径

照 `tests/unit_ci_workflows/test_must_finish_retire_migration.py` 的范式：`initdb` / `pg_ctl` / `psql`
起**临时集群**真跑（缺 PG 的处置收口在 `pg_cluster.py`：CI 判**红** / 本机显式 skip，issue #5203）。
静态文本判据不够 —— 「逐字相等 vs 模糊匹配」的差别只有在**真行**上才看得见。
"""
from __future__ import annotations

import json
import re
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

# 共享件（同族测试的统一写法）：按**包名**导入迁移路径事实源 + 真库收口件。
# 直接以脚本方式运行时包不在路径上，故显式补一次。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from unit_ci_workflows._migration_paths import LIVE_DIR as _LIVE_DIR  # noqa: E402
from unit_ci_workflows._migration_paths import migration_files as _migration_files  # noqa: E402
from unit_ci_workflows import pg_cluster  # noqa: E402  （起/停集群的唯一收口，issue #5263）
from unit_ci_workflows.injection import inject  # noqa: E402  （注入的唯一原语：锚点漂移 / 不唯一 / 空操作都会抛错，不用裸 str.replace —— issue #7017）

MIGRATION = _LIVE_DIR / "V219__backfill_tenant_bot_name_to_smart_service.sql"
LEDGER = Path(__file__).resolve().parent / "migration_fingerprints.json"
SCHEMA_SQL = REPO / "backend/admin-api/src/main/resources/db/init/schema.sql"

TABLE = "tenant_ai_configs"
COLUMN = "bot_name"

#: 旧默认值 = V213 物化进表里的退役品牌名（本迁移的唯一匹配面）
OLD_NAME = "米宝"
#: issue #9304 起的 C 端默认身份
NEW_NAME = "智能客服"
#: 商户自定义名（不含旧名子串）：一个字都不许动
CUSTOM_NAME = "小美"
#: 商户自定义名但**含**旧名子串 ⇒ 「逐字相等 vs 模糊匹配」的判别力靶子
DECOY_NAME = "米宝小助手"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _strip_comments(sql: str) -> str:
    """SQL 注释 → 空，供**可执行语句**判据用。

    ⚠️ 必须去注释：本迁移的头注**故意**写着 `LIKE '%米宝%'`（解释为什么不用它）与
    `SET DEFAULT '米宝'`（边界登记）—— 不剥注释会把这些说明文字当成真语句（#4595 同族）。
    """
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.S)
    return re.sub(r"--[^\n]*", "", sql)


def _code() -> str:
    return _strip_comments(_read(MIGRATION))


def _update_stmts(sql: str) -> list:
    return [u for u in re.findall(r"UPDATE\s+tenant_ai_configs[\s\S]*?;", sql) if "SET" in u]


# ══════════════════════════ ① 存在性 / 账本 / 形态（静态，零 DB） ══════════════════════════

def test_migration_exists_with_a_unique_and_highest_version():
    assert MIGRATION.exists(), f"缺少迁移文件：{MIGRATION.name}"
    versions = [int(m.group(1)) for p in _migration_files("V*.sql")
               if (m := re.match(r"^V(\d+)__", p.name))]
    assert versions.count(219) == 1, f"V219 版本号重复（{versions.count(219)} 份）"
    # ⚠️ 只许 `>=`，**不许** `== 219`：主张「我是当前最高迁移版本号」是**自毁式真值主张** ——
    # 下一个迁移一落地它必然变红，且报错文案把人指向「新迁移写错了」这个错误行动
    # （守卫 = `tests/unit_ci_workflows/test_self_destruct_assert_guard.py`，issue #5166/#5493）。
    assert max(versions) >= 219, (
        f"V219 不在迁移链上（当前最大 V{max(versions)}）—— 同步 main 时若被并行包占号，"
        f"按 `test_migration_version_uniqueness.py` 的「后合入者让号」改名")


def test_migration_is_registered_in_the_fingerprint_ledger():
    """迁移不可变护栏：新增迁移必须在内容指纹账本里，否则它以后能被静默改。"""
    ledger = json.loads(_read(LEDGER))["migrations"]
    assert MIGRATION.name in ledger, (
        f"`{MIGRATION.name}` 未登记进 `tests/unit_ci_workflows/migration_fingerprints.json`。\n"
        f"  跑：python3 tests/unit_ci_workflows/test_migration_immutability.py --write-ledger")


def test_where_clause_is_literal_equality_not_fuzzy():
    """核心判据：`WHERE bot_name = '米宝'` —— 逐字相等，**不是**模糊匹配。

    为什么这一条是硬要求：'米宝' 是**旧默认值**，而商户自定义名里可能含这两个字
    （如「米宝小助手」）⇒ 模糊匹配会把商户自己起的名字一起改掉。
    """
    sql = _code()
    stmts = _update_stmts(sql)
    assert len(stmts) == 1, f"V219 应恰好一条 UPDATE（实际 {len(stmts)}）"
    stmt = stmts[0]
    assert f"WHERE {COLUMN} = '{OLD_NAME}'" in stmt, (
        f"V219 的 WHERE 不是逐字相等匹配（`WHERE {COLUMN} = '{OLD_NAME}'`）：\n{stmt}")
    for fuzzy in ("LIKE", "ILIKE", "~", "%"):
        assert fuzzy not in stmt, (
            f"V219 的 UPDATE 里出现模糊匹配关键字 `{fuzzy}` ⇒ 会把含「{OLD_NAME}」的"
            f"**商户自定义名**（如「{DECOY_NAME}」）一起改掉：\n{stmt}")


def test_migration_only_writes_bot_name_and_updated_at():
    """只许改值：写面 = `bot_name` + `updated_at`；不碰列定义 / 默认值 / 行数。"""
    sql = _code()
    stmt = _update_stmts(sql)[0]
    assert re.search(r"SET\s+bot_name\s*=\s*'智能客服'\s*,\s*updated_at\s*=\s*NOW\(\)", stmt), (
        f"V219 的 SET 子句不是「显式写 bot_name + updated_at」：\n{stmt}")
    upper = sql.upper()
    for forbidden in ("INSERT ", "DELETE ", "ALTER TABLE", "SET DEFAULT", "DROP "):
        assert forbidden not in upper, (
            f"V219 的可执行语句里出现 `{forbidden}` —— 本迁移只回填**行值**："
            f"列定义 / 默认值属另一件事（见迁移头注「边界」）")


def test_migration_is_explicitly_transactional():
    """`psql -f` 默认逐条 autocommit ⇒ 不显式 `BEGIN/COMMIT` 会留半完成态（V97/V102 的实测口径）。"""
    body = _read(MIGRATION)
    assert re.search(r"^BEGIN;", body, re.M), "V219 缺显式 `BEGIN;`"
    assert re.search(r"^COMMIT;", body, re.M), "V219 缺显式 `COMMIT;`"


def test_migration_documents_why_it_matches_literal_equality_and_how_to_observe():
    """注释里必须写清三件事：产品改名来由 / 为什么逐字相等 / 可观测性（`UPDATE n`）。"""
    body = _read(MIGRATION)
    assert "退役品牌名" in body, "V219 没写「为什么改」（产品改名，米宝已退役）"
    assert "LIKE" in body and "自定义" in body, (
        "V219 没写「为什么只匹配逐字相等」（含旧名子串的自定义名必须被保护）")
    assert "UPDATE n" in body or "UPDATE 0" in body, (
        "V219 没写可观测性（psql 的 `UPDATE n` 命令标签 / 幂等时 `UPDATE 0`）")


def test_schema_still_defines_the_column_it_backfills():
    """真值锚：`bot_name` 列在**建库脚本**里真实存在（本迁移引用的列必须在 bootstrap 终态里）。"""
    assert re.search(r"ALTER TABLE tenant_ai_configs ADD COLUMN IF NOT EXISTS bot_name", _read(SCHEMA_SQL)), (
        "`backend/admin-api/src/main/resources/db/init/schema.sql` 里找不到 "
        "`tenant_ai_configs.bot_name` 的声明 —— 迁移的匹配面不成立了（口径已变，须重新核真值）")


# ══════════════════════════ ② 真库判据（临时 PG 集群） ══════════════════════════

#: 与 `backend/admin-api/src/main/resources/db/init/schema.sql` 同形的**最小** DDL：
#: 只建本迁移触碰的列（含 V213 推出来的 `DEFAULT '米宝'` —— 本条正是「行值 ≠ 默认值」的证据面）。
_DDL = """
CREATE TABLE tenants (id BIGINT PRIMARY KEY, deleted INTEGER NOT NULL DEFAULT 0);
CREATE TABLE tenant_ai_configs (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id) UNIQUE,
    greeting_template VARCHAR(1024) DEFAULT '您好，我是 AI 客服助手，有什么可以帮您？',
    bot_name VARCHAR(64) DEFAULT '米宝',
    channel_configs JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER DEFAULT 0);
"""

#: 真库夹具：四行覆盖「旧默认值 / 自定义名 / 含旧名子串的自定义名 / 未配置」
_SEED = """
INSERT INTO tenants (id) VALUES (1), (2), (3), (4);
INSERT INTO tenant_ai_configs (id, tenant_id, bot_name) VALUES
    ('cfg-legacy', 1, '米宝'),
    ('cfg-custom', 2, '小美'),
    ('cfg-decoy',  3, '米宝小助手'),
    ('cfg-null',   4, NULL);
"""


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def psql(tmp_path, realdb_binaries):
    """临时 PG 集群（unix socket，不占 TCP 端口）；退出时停库删目录。"""
    datadir = tmp_path / "pgdata"
    # ⚠️ socket 目录必须**短**：unix socket 路径有 ~104 字节上限。
    sockdir = Path(tempfile.mkdtemp(prefix="pg9308-"))
    log = tmp_path / "pg.log"
    port = _free_port()
    # 起集群的**唯一实现**（失败 / 中止路径也停库 —— issue #5263 判据①）
    pg_cluster.start_cluster(realdb_binaries, datadir, sockdir=sockdir, port=port, log=log)

    def _argv(*extra: str) -> list:
        return [realdb_binaries["psql"], "-h", str(sockdir), "-p", str(port), "-U", "postgres",
                "-d", "postgres", "-X", "-v", "ON_ERROR_STOP=1", *extra]

    def psql_raw(sql: str, *extra: str):
        """不抛异常的入口（红证要断言「注入版**确实**改了不该改的行」）。"""
        return subprocess.run(_argv(*extra), input=sql, text=True, capture_output=True)

    def run(sql: str) -> str:
        proc = psql_raw(sql, "-q", "-t", "-A")
        assert proc.returncode == 0, f"psql 失败：\n{proc.stdout}\n{proc.stderr}"
        return proc.stdout

    def tags(sql: str) -> list:
        """读 psql 的**命令标签**（`UPDATE n` / `BEGIN` / `COMMIT`）—— 就是迁移日志里那一行。"""
        proc = psql_raw(sql)
        assert proc.returncode == 0, f"psql 失败：\n{proc.stdout}\n{proc.stderr}"
        return [line.strip() for line in proc.stdout.splitlines()
                if re.fullmatch(r"(UPDATE|INSERT|DELETE|BEGIN|COMMIT) ?\d*", line.strip())]

    run.raw = psql_raw
    run.tags = tags
    try:
        yield run
    finally:
        pg_cluster.stop_cluster(realdb_binaries["pg_ctl"], datadir)
        shutil.rmtree(sockdir, ignore_errors=True)


def _as_runner_would(sql: str) -> str:
    """复现 `MigrationRunner` 的 `jdbc.execute(整份文件)` 语义（整份文件一个事务）。

    ⚠️ 文件内另有自己的 `BEGIN; … COMMIT;` ⇒ 外层再包一层会得到 PG 的
    `WARNING: there is already a transaction in progress`（**不是错误**，无害）。
    """
    return "BEGIN;\n" + sql + "\nCOMMIT;\n"


def _values(run) -> list:
    """逐行读数（`<NULL>` 显式可见，防「没配」被读成「改成了空」）。"""
    out = run(f"SELECT id || '=' || coalesce({COLUMN}, '<NULL>') FROM {TABLE} ORDER BY id;")
    return [line for line in out.splitlines() if line.strip()]


def test_backfills_only_the_literal_legacy_default(psql):
    """核心：只把逐字等于 '米宝' 的行改成 '智能客服'；自定义名（含子串的）与 NULL 原样。"""
    psql(_DDL + _SEED)
    before = _values(psql)
    assert before == [
        f"cfg-custom={CUSTOM_NAME}",
        f"cfg-decoy={DECOY_NAME}",
        "cfg-legacy=米宝",
        "cfg-null=<NULL>",
    ], f"夹具没造出预期的四行：{before}（红证前提不成立）"

    psql(_as_runner_would(_read(MIGRATION)))
    after = _values(psql)

    print(f"[#9308 真库] 改前 = {before}")
    print(f"[#9308 真库] 改后 = {after}")
    assert f"cfg-legacy={NEW_NAME}" in after, (
        f"旧默认值 '米宝' 没被回填成 '{NEW_NAME}'：{after}")
    assert f"cfg-custom={CUSTOM_NAME}" in after, (
        f"商户自定义名被改了（'{CUSTOM_NAME}' 必须原样）：{after}")
    assert f"cfg-decoy={DECOY_NAME}" in after, (
        f"含旧名子串的**商户自定义名**被改了（'{DECOY_NAME}' 必须原样）—— "
        f"这说明匹配面变成了模糊匹配：{after}")
    assert "cfg-null=<NULL>" in after, f"未配置（NULL）的行被写了值：{after}"
    assert psql(f"SELECT count(*) FROM {TABLE};").strip() == "4", "V219 增删了行（它只许改值）"


def test_second_run_updates_zero_rows_and_net_effect_is_identical(psql):
    """真库两遍幂等：第一遍 `UPDATE 1`、第二遍 **`UPDATE 0`**，净效果逐值相同。

    `UPDATE n` 是 psql 的命令标签 —— 也就是**迁移日志里那一行**；本判据直接把它当读数
    （`MigrationRunner` 走 `jdbc.execute` 不回显行数，见迁移头注「可观测性」）。
    """
    psql(_DDL + _SEED)

    first_tags = psql.tags(_as_runner_would(_read(MIGRATION)))
    after_first = _values(psql)
    second_tags = psql.tags(_as_runner_would(_read(MIGRATION)))
    after_second = _values(psql)

    first_update = [t for t in first_tags if t.startswith("UPDATE")]
    second_update = [t for t in second_tags if t.startswith("UPDATE")]

    print(f"[#9308 真库] 第 1 遍命令标签 = {first_tags}")
    print(f"[#9308 真库] 第 2 遍命令标签 = {second_tags}  （UPDATE 0 ⇒ 幂等闸生效）")

    assert first_update == ["UPDATE 1"], (
        f"第一遍应恰好改 1 行（只有 '米宝' 那行），实际 {first_update}")
    assert second_update == ["UPDATE 0"], (
        f"第二遍命中 {second_update} 行 ⇒ 幂等闸失效（旧值谓词丢了？）")
    assert after_first == after_second, (
        f"V219 **不幂等**：第二遍改了净效果\n  第一遍：{after_first}\n  第二遍：{after_second}")


def test_like_injection_would_clobber_a_name_containing_the_old_brand(psql):
    """注入式红证：把 WHERE 换成 `LIKE '%米宝%'` ⇒ '米宝小助手' **会被改**（'小美' 仍不受影响）。

    这条证明「保护含旧名子串的自定义值」不是一句注释、也不是恒真断言 ——
    匹配面一旦变成模糊匹配，上一条测试会**具名**报出 `cfg-decoy` 被改。
    """
    psql(_DDL + _SEED)
    # 注入原语 = `inject()`（不是裸 `str.replace`）：锚点漂移 / 命中不唯一 / 空操作**当场抛错**，
    # 否则「注入没生效」会被读成「判据没牙」（issue #7017；判据 =
    # `tests/unit_ci_workflows/test_red_proof_anchor_liveness.py`）。
    injected = inject(
        _read(MIGRATION),
        f"WHERE {COLUMN} = '{OLD_NAME}'",
        f"WHERE {COLUMN} LIKE '%{OLD_NAME}%'",
        where=MIGRATION.name,
    )
    assert "LIKE" in _strip_comments(injected), "注入没生效 ⇒ 本红证是空断言"

    psql(_as_runner_would(injected))
    after = _values(psql)
    print(f"[#9308 真库 · 红证] 注入 LIKE 后 = {after}")

    assert f"cfg-decoy={NEW_NAME}" in after, (
        "注入模糊匹配后 '米宝小助手' **没有**被改 ⇒ 上一条测试里的保护断言是恒真的（红证失败）")
    assert f"cfg-custom={CUSTOM_NAME}" in after, (
        f"'{CUSTOM_NAME}' 不含旧名子串，本就不该被任何匹配面命中：{after}")
