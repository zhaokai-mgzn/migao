# case_ids: CH-046
"""V220（`tenant_ai_configs.bot_name` 的**列默认值**：'米宝' → '智能客服'）的形态 + 真库判据（issue #9328）。

## 病根（为什么「改代码默认值」+「回填存量行」都堵不住新建行）

- #9304（`f9103e365`）改的是代码**兜底值**：`DEFAULT_BOT_NAME = "智能客服"`；
- #9311（V219）改的是**行值**：`UPDATE tenant_ai_configs SET bot_name='智能客服' WHERE bot_name='米宝'`；
- 读取侧 = **租户配置优先**：`backend/ai-agent-service/app/agents/agents/xiaobu.py` 的
  `bot_name = data.get("botName") or DEFAULT_BOT_NAME` —— 行里非空就照用，代码默认值压不过它；
- 而列默认值是 **V213** 设的 `'米宝'` ⇒ 新建配置行**没显式给** `botName` 时落库就是 '米宝'
  ⇒ 该租户的 C 端顾客照旧被退役品牌名问候。V219 只 `UPDATE`（改不动**将来插入**的行），
  这个缺口它自己登记在头注「边界」里。

## 本文件钉什么

| 面 | 判据 |
|---|---|
| 存在 / 账本 | 文件存在；版本号唯一且**不早于 V219**（`>=`，不是 `==`）；已登记进内容指纹账本 |
| 形态（静态） | 可执行语句**恰好一条**：`ALTER TABLE tenant_ai_configs ALTER COLUMN bot_name SET DEFAULT '智能客服'`；零 `UPDATE` / `INSERT` / `DELETE`；显式 `BEGIN;` / `COMMIT;` |
| 链尾守卫（静态） | 迁移链里**最后一条**设置该列默认值的迁移必须设成 '智能客服' —— 后人再加一条更晚的把默认值设回旧名，当场变红 |
| 真库 | 按 V213 之后的列定义（默认值 '米宝'）建表 ⇒ 跑迁移**前** `INSERT … RETURNING bot_name` 读到 '米宝'，跑**后**读到 '智能客服'；`information_schema.column_default` 同步；**存量行一个都没变** |
| 真库幂等 | 连跑两遍：列默认值 + 新建行读数逐值相同；迁移自己**零行写入** |
| 判别力（注入红证） | 把迁移里的默认值注入回 '米宝' ⇒ 新建行**读到 '米宝'** ⇒ 证明上面那条断言不是恒真 |

## 真库口径

照 `tests/unit_ci_workflows/test_v219_bot_name_backfill.py` 的范式：`initdb` / `pg_ctl` / `psql` 起**临时集群**
真跑（缺 PG 的处置收口在 `pg_cluster.py`：CI 判**红** / 本机显式 skip，issue #5203）。
静态文本判据不够 —— 「列默认值到底变成什么」只有在**真插入一行**之后才读得到。
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
from unit_ci_workflows.injection import inject  # noqa: E402  （注入的唯一原语：锚点漂移 / 不唯一 / 空操作都会抛错，issue #7017）

MIGRATION = _LIVE_DIR / "V220__set_tenant_bot_name_column_default_smart_service.sql"
LEDGER = Path(__file__).resolve().parent / "migration_fingerprints.json"
SCHEMA_SQL = REPO / "backend/admin-api/src/main/resources/db/init/schema.sql"

TABLE = "tenant_ai_configs"
COLUMN = "bot_name"
VERSION = 220

#: 退役品牌名 = V213 推到列上的**旧默认值**（本迁移唯一的匹配面）
OLD_NAME = "米宝"
#: 迁移链的终态默认值（= #9304 的 `DEFAULT_BOT_NAME`）
NEW_NAME = "智能客服"

#: 「设置本列默认值」的语句形态（静态判据与链尾守卫共用同一份正则）
_SET_DEFAULT_RE = re.compile(
    r"ALTER\s+TABLE\s+tenant_ai_configs\s+ALTER\s+COLUMN\s+bot_name\s+SET\s+DEFAULT\s+'([^']*)'",
    re.IGNORECASE,
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _strip_comments(sql: str) -> str:
    """SQL 注释 → 空，供**可执行语句**判据用。

    ⚠️ 必须去注释：迁移头注**故意**写着 `DEFAULT '小布'` / `SET DEFAULT '米宝'`（解释历史与回滚 SQL）——
    不剥注释会把说明文字当成真语句（#4595 同族）。
    """
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.S)
    return re.sub(r"--[^\n]*", "", sql)


def _code() -> str:
    return _strip_comments(_read(MIGRATION))


def _statements(sql: str) -> list:
    """可执行语句列表（去注释后按 `;` 切，去空白；大小写保留原文）。"""
    return [s.strip() for s in _strip_comments(sql).split(";") if s.strip()]


def _default_setters(sources) -> list:
    """`[(version, 设置成的默认值)]`，按版本号升序 —— 「迁移链里谁改过这个默认值」的唯一取法。

    `sources` 收 `(version, sql_text)` 序列（真链与合成链共用同一份实现，红证才能真打在这条逻辑上）。
    """
    found = []
    for version, text in sources:
        for value in _SET_DEFAULT_RE.findall(_strip_comments(text)):
            found.append((version, value))
    return sorted(found)


def _live_sources() -> list:
    """真迁移链（归档 ∪ 活目录，`_migration_paths` 的单一事实源）→ `[(version, sql)]`。"""
    out = []
    for path in _migration_files("V*.sql"):
        matched = re.match(r"^V(\d+)__", path.name)
        assert matched, f"迁移文件名不合 `V<n>__` 约定：{path.name}"
        out.append((int(matched.group(1)), _read(path)))
    return out


# ══════════════════════════ ① 存在性 / 账本 / 形态（静态，零 DB） ══════════════════════════

def test_migration_exists_with_a_unique_version_at_or_after_v219():
    assert MIGRATION.exists(), f"缺少迁移文件：{MIGRATION.name}"
    versions = [int(m.group(1)) for p in _migration_files("V*.sql")
                if (m := re.match(r"^V(\d+)__", p.name))]
    assert versions.count(VERSION) == 1, f"V{VERSION} 版本号重复（{versions.count(VERSION)} 份）"
    # ⚠️ 只许 `>=`，**不许** `== 220`：主张「我是当前最高迁移版本号」是**自毁式真值主张** ——
    # 下一个迁移一落地它必然变红，且报错文案把人指向「新迁移写错了」这个错误行动
    # （守卫 = `tests/unit_ci_workflows/test_self_destruct_assert_guard.py`，issue #5166/#5493）。
    assert max(versions) >= VERSION, (
        f"V{VERSION} 不在迁移链上（当前最大 V{max(versions)}）—— 同步 main 时若被并行包占号，"
        f"按 `test_migration_version_uniqueness.py` 的「后合入者让号」改名")


def test_migration_is_registered_in_the_fingerprint_ledger():
    """迁移不可变护栏：新增迁移必须在内容指纹账本里，否则它以后能被静默改。"""
    ledger = json.loads(_read(LEDGER))["migrations"]
    assert MIGRATION.name in ledger, (
        f"`{MIGRATION.name}` 未登记进 `tests/unit_ci_workflows/migration_fingerprints.json`。\n"
        f"  跑：python3 tests/unit_ci_workflows/test_migration_immutability.py --write-ledger")


def test_migration_sets_the_column_default_and_nothing_else():
    """核心形态判据：**恰好一条**可执行语句 = 把列默认值设成 '智能客服'。

    本迁移**只改列默认值**：任何 `UPDATE` / `INSERT` / `DELETE` 都属越界
    （存量行已由 V219 处理；再写一遍回填会把数据变化的来由搅乱）。
    """
    statements = [s for s in _statements(_read(MIGRATION)) if s.upper() not in ("BEGIN", "COMMIT")]
    expected = f"ALTER TABLE {TABLE} ALTER COLUMN {COLUMN} SET DEFAULT '{NEW_NAME}'"
    assert statements == [expected], (
        f"V{VERSION} 的可执行语句必须**恰好**是 `{expected}`（一条），实际 {statements}")

    code = _code().upper()
    for forbidden in ("UPDATE ", "INSERT ", "DELETE ", "DROP ", "TRUNCATE "):
        assert forbidden not in code, (
            f"V{VERSION} 的可执行语句里出现 `{forbidden.strip()}` —— 本迁移**只改列默认值**："
            f"存量行已由 V219 回填（见迁移头注「为什么只改 DEFAULT」）")


def test_migration_is_explicitly_transactional():
    """`psql -f` 默认逐条 autocommit ⇒ 不显式 `BEGIN/COMMIT` 会留半完成态（V97/V102 的实测口径）。"""
    body = _read(MIGRATION)
    assert re.search(r"^BEGIN;", body, re.M), f"V{VERSION} 缺显式 `BEGIN;`"
    assert re.search(r"^COMMIT;", body, re.M), f"V{VERSION} 缺显式 `COMMIT;`"


def test_migration_documents_why_it_only_moves_the_default():
    """注释里必须写清三件事（缺一项就去找下一个人重新考古）。"""
    body = _read(MIGRATION)
    assert "退役品牌名" in body, f"V{VERSION} 没写「为什么改」（产品改名，米宝已退役）"
    assert "V219" in body and "UPDATE" in body, (
        f"V{VERSION} 没写「为什么不动数据」（存量行已由 V219 的 UPDATE 处理）")
    assert "V213" in body and "不要回改" in body, (
        f"V{VERSION} 没写「与 V213 的关系」（明确覆盖它、不许回改 —— 否则下一个人会把默认值改回去）")


def test_schema_still_declares_the_column_it_targets():
    """真值锚：`bot_name` 列在**建库脚本**里真实存在（迁移的靶子必须在 bootstrap 终态里）。"""
    assert re.search(r"ALTER TABLE tenant_ai_configs ADD COLUMN IF NOT EXISTS bot_name", _read(SCHEMA_SQL)), (
        "`backend/admin-api/src/main/resources/db/init/schema.sql` 里找不到 "
        "`tenant_ai_configs.bot_name` 的声明 —— 迁移的靶子不成立了（口径已变，须重新核真值）")


# ══════════════════════════ ② 链尾守卫（防后人把默认值改回旧名） ══════════════════════════

def test_the_last_migration_setting_the_default_sets_the_new_name():
    """类级判据：迁移链里**最后**一条设置本列默认值的迁移必须设成 '智能客服'。

    为什么这条比「V220 文件里有 SET DEFAULT '智能客服'」更强：后者只钉住**我这一个文件**，
    后人完全可以在 V3xx 里再加一条把默认值设回旧名（单看 V220 依然绿）。
    判据只看**链尾**（不钉版本号）⇒ 不承担「我是最大号」这种自毁式主张。
    """
    setters = _default_setters(_live_sources())
    assert len(setters) >= 3, (
        f"迁移链里设置 `{TABLE}.{COLUMN}` 默认值的迁移只有 {setters} —— 扫描口径或靶子变了（V150/V213/V220 都动过它）")
    last_version, last_value = setters[-1]
    assert last_value == NEW_NAME, (
        f"迁移链里**最后**一条设置 `{TABLE}.{COLUMN}` 默认值的迁移是 V{last_version}，"
        f"它把默认值设成了 '{last_value}'（应为 '{NEW_NAME}'）—— "
        f"新增/更晚的迁移把默认值改回旧名了；不要回改 V213，也不要把 V220 的效果撤销")
    assert last_version >= 219, (
        f"链尾默认值来自 V{last_version}（早于 V219）⇒ 中间那条把默认值推到 '智能客服' 的迁移丢了")
    print(f"[#9328 静态] 迁移链里的默认值设置者（版本, 值）= {setters}")


def test_chain_guard_catches_a_later_regression():
    """判别力自证：合成一条**更晚**的「设回 '米宝'」迁移 ⇒ 链尾守卫必须点名它。

    注入锚在**逻辑**上（合成 sources），不在真文件上 —— 本条不需要改任何仓内文件。
    """
    synthetic = [
        (150, f"ALTER TABLE {TABLE} ALTER COLUMN {COLUMN} SET DEFAULT '元元';"),
        (213, f"ALTER TABLE {TABLE} ALTER COLUMN {COLUMN} SET DEFAULT '{OLD_NAME}';"),
        (220, f"ALTER TABLE {TABLE} ALTER COLUMN {COLUMN} SET DEFAULT '{NEW_NAME}';"),
        (999, f"ALTER TABLE {TABLE} ALTER COLUMN {COLUMN} SET DEFAULT '{OLD_NAME}';"),
    ]
    setters = _default_setters(synthetic)
    assert setters == [(150, "元元"), (213, OLD_NAME), (220, NEW_NAME), (999, OLD_NAME)], (
        f"链尾守卫的取数面不对（合成的 4 条迁移应全部命中）：{setters}")
    assert setters[-1] != (220, NEW_NAME), "合成链里更晚的那条没有影响到链尾 ⇒ 红证是空断言"
    # 真链的链尾仍是「智能客服」⇒ 同一个谓词对真链给绿、对合成链给红（判别力成立）
    assert _default_setters(_live_sources())[-1][1] == NEW_NAME


# ══════════════════════════ ③ 真库判据（临时 PG 集群） ══════════════════════════

#: 与 `backend/admin-api/src/main/resources/db/init/schema.sql` 同形的**最小** DDL：
#: 列默认值取 **V213 之后的真实形态**（'米宝'）—— 这正是「迁移前新插入行会落旧名」的证据面。
_DDL = f"""
CREATE TABLE tenants (id BIGINT PRIMARY KEY, deleted INTEGER NOT NULL DEFAULT 0);
CREATE TABLE {TABLE} (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id) UNIQUE,
    greeting_template VARCHAR(1024) DEFAULT '您好，我是 AI 客服助手，有什么可以帮您？',
    {COLUMN} VARCHAR(64) DEFAULT '{OLD_NAME}',
    channel_configs JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER DEFAULT 0);
"""

#: 存量行（V219 之前的状态）：一行旧默认值 + 一行商户自定义名（本迁移一行都不许动）
_SEED = f"""
INSERT INTO tenants (id) VALUES (1), (2), (3), (4), (5), (6), (7), (8);
INSERT INTO {TABLE} (id, tenant_id, {COLUMN}) VALUES
    ('cfg-legacy', 1, '{OLD_NAME}'),
    ('cfg-custom', 2, '小美');
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
    sockdir = Path(tempfile.mkdtemp(prefix="pg9328-"))
    log = tmp_path / "pg.log"
    port = _free_port()
    # 起集群的**唯一实现**（失败 / 中止路径也停库 —— issue #5263 判据①）
    pg_cluster.start_cluster(realdb_binaries, datadir, sockdir=sockdir, port=port, log=log)

    def _argv(*extra: str) -> list:
        return [realdb_binaries["psql"], "-h", str(sockdir), "-p", str(port), "-U", "postgres",
                "-d", "postgres", "-X", "-v", "ON_ERROR_STOP=1", *extra]

    def run(sql: str) -> str:
        proc = subprocess.run(_argv("-q", "-t", "-A"), input=sql, text=True, capture_output=True)
        assert proc.returncode == 0, f"psql 失败：\n{proc.stdout}\n{proc.stderr}"
        return proc.stdout

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


def _insert_default(run, tenant_id: int) -> str:
    """**只给 tenant_id** 插一行（不给 bot_name）⇒ 读回落库值 = 列默认值。"""
    out = run(f"INSERT INTO {TABLE} (id, tenant_id) VALUES ('cfg-new-{tenant_id}', {tenant_id}) "
              f"RETURNING {COLUMN};")
    return out.strip()


def _column_default(run) -> str:
    out = run("SELECT coalesce(column_default, '<NULL>') FROM information_schema.columns "
              f"WHERE table_name = '{TABLE}' AND column_name = '{COLUMN}';")
    return out.strip()


def _values(run) -> list:
    """逐行读数（`<NULL>` 显式可见，防「没配」被读成「改成了空」）。"""
    out = run(f"SELECT id || '=' || coalesce({COLUMN}, '<NULL>') FROM {TABLE} ORDER BY id;")
    return [line for line in out.splitlines() if line.strip()]


def test_new_row_gets_the_new_default_and_existing_rows_are_untouched(psql):
    """核心真库判据：迁移前新行落 '米宝'、迁移后落 '智能客服'；**存量行一个都不变**。"""
    psql(_DDL + _SEED)

    before_default = _column_default(psql)
    before_value = _insert_default(psql, 3)        # 迁移前插一行（= 洞的现场）
    before_values = _values(psql)

    psql(_as_runner_would(_read(MIGRATION)))

    after_default = _column_default(psql)
    after_value = _insert_default(psql, 4)         # 迁移后再插一行（= 修好后的现场）
    after_values = _values(psql)

    print(f"[#9328 真库] 迁移前 column_default = {before_default} ／ 新建行 bot_name = {before_value!r}")
    print(f"[#9328 真库] 迁移后 column_default = {after_default} ／ 新建行 bot_name = {after_value!r}")
    print(f"[#9328 真库] 迁移前逐行 = {before_values}")
    print(f"[#9328 真库] 迁移后逐行 = {after_values}")

    assert before_value == OLD_NAME, (
        f"夹具不成立：迁移**前**新插入的行应落旧默认值 '{OLD_NAME}'，实际 {before_value!r}"
        f"（column_default={before_default}）—— 靶子没造出来，后面的断言就是空的")
    assert after_value == NEW_NAME, (
        f"迁移后新插入的行应落 '{NEW_NAME}'：expected '{NEW_NAME}' but was '{after_value}'"
        f"（column_default={after_default}）—— 默认值没被改过来？")
    assert NEW_NAME in after_default, (
        f"`information_schema` 的 column_default 不是 '{NEW_NAME}'：{after_default}")
    assert after_values == [f"cfg-custom=小美", f"cfg-legacy={OLD_NAME}",
                            f"cfg-new-3={OLD_NAME}", f"cfg-new-4={NEW_NAME}"], (
        f"本迁移**只许改列默认值**：存量行/历史行一个字都不该动。实际 {after_values}")


def test_second_run_changes_nothing(psql):
    """真库两遍幂等：列默认值与新建行读数逐值相同，且迁移自己**零行写入**。"""
    psql(_DDL + _SEED)

    psql(_as_runner_would(_read(MIGRATION)))
    first_default, first_value = _column_default(psql), _insert_default(psql, 5)
    count_after_first = psql(f"SELECT count(*) FROM {TABLE};").strip()

    psql(_as_runner_would(_read(MIGRATION)))
    second_default, second_value = _column_default(psql), _insert_default(psql, 6)
    count_after_second = psql(f"SELECT count(*) FROM {TABLE};").strip()

    print(f"[#9328 真库] 第 1 遍：column_default={first_default} ／ 新建行={first_value!r} ／ 行数={count_after_first}")
    print(f"[#9328 真库] 第 2 遍：column_default={second_default} ／ 新建行={second_value!r} ／ 行数={count_after_second}")

    assert (first_default, first_value) == (second_default, second_value), (
        f"V{VERSION} **不幂等**：两遍的读数不同\n  第 1 遍：{(first_default, first_value)}\n"
        f"  第 2 遍：{(second_default, second_value)}")
    assert first_value == NEW_NAME, f"第 1 遍新行不是 '{NEW_NAME}'：{first_value!r}"
    assert int(count_after_second) == int(count_after_first) + 1, (
        f"迁移自己写了行：第 1 遍后 {count_after_first} 行 + 我插入的 1 行 ⇒ 应为 "
        f"{int(count_after_first) + 1} 行，实际 {count_after_second} 行")


def test_injection_back_to_the_old_default_is_visible_in_a_real_insert(psql):
    """注入式红证：把迁移里的默认值改回 '米宝' ⇒ **新建行读到 '米宝'**。

    这条证明「新建行 = '智能客服'」不是恒真：同一个判据在变异体上必然读到旧名
    （`test_new_row_gets_the_new_default_and_existing_rows_are_untouched` 会具名报出
    `expected '智能客服' but was '米宝'`）。
    """
    psql(_DDL + _SEED)
    # 注入原语 = `inject()`（不是裸 `str.replace`）：锚点漂移 / 命中不唯一 / 空操作**当场抛错**，
    # 否则「注入没生效」会被读成「判据没牙」（issue #7017；判据 =
    # `tests/unit_ci_workflows/test_red_proof_anchor_liveness.py`）。
    injected = inject(
        _read(MIGRATION),
        f"SET DEFAULT '{NEW_NAME}'",
        f"SET DEFAULT '{OLD_NAME}'",
        where=MIGRATION.name,
    )
    assert f"SET DEFAULT '{OLD_NAME}';" in _strip_comments(injected), "注入没生效 ⇒ 本红证是空断言"

    psql(_as_runner_would(injected))
    injected_value = _insert_default(psql, 7)
    print(f"[#9328 真库 · 红证] 注入回 '{OLD_NAME}' 后新建行 = {injected_value!r}")

    assert injected_value == OLD_NAME, (
        f"注入版迁移没有把默认值设回 '{OLD_NAME}' ⇒ 本红证是空断言（注入没落上）：{injected_value!r}")
    assert injected_value != NEW_NAME, "变异体与正常版读数相同 ⇒ 上一条核心判据无法区分两者"
