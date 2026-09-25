# case_ids: PR-107
"""真库判据的 PG 二进制发现 + 「缺 PG」处置 + **临时集群起/停** 的**唯一收口**
（issue #5203 承 #5192；issue #5263 追加起/停与只读清点）。

## 病灶（2026-09-23 **实测**定性，不是风险预测）

`ci-workflow-tests` job（`.github/workflows/pr-check.yml`）**不装 PG**：真库判据各自跑一次性
`initdb` + `pg_ctl` 集群，要的是**二进制**而不是服务；二进制靠 `ubuntu-latest`（24.04）镜像
**恰好自带**（`/usr/lib/postgresql/16/bin`，本文件 `BIN_DIRS` 的 Debian 绝对路径命中）。

而 Python 侧的探测曾经只认 `PATH`（`all(shutil.which(b) …)`），runner **不把该目录加进 PATH**
⇒ 探测恒为 False ⇒ 每次 CI 都走 `pytest.skip` —— **绿着跳过**。四条独立实测证据（issue #5203）：

1. 探测口径：13 个模块 `shutil.which`（只认 PATH）；Java 侧 `PgCluster.BIN_DIRS` 有硬编码兜底；
2. runner 上 `command -v initdb` **找不到**（`#5199` 的前置断言打印出回落路径 = `/usr/lib/…/16/bin`）；
3. 受控实验（猴补 `shutil.which`，只藏三个 PG 二进制）：本机 3691 passed / **1** skipped → 3609 / **83**；
4. CI 实测（job `107162870891`）：3561 passed / **87** skipped（其中 83 条由 ③ 精确复现）。

这 13 个模块本机真跑 = **190 passed / 0 skipped**；藏掉 PG = **79 skipped**。⇒ 同一台 runner、
同一批判据类型：**Java 真库判据在跑，Python 真库判据在 skip**（迁移/回填/库存/幂等一族「钱与账」的读数）。

## 本模块收口什么（单一来源 —— 不许再有第 2 份拷贝）

| 收口物 | 内容 |
|---|---|
| `BIN_DIRS` | 候选目录，与 `backend/admin-api/src/test/java/com/migao/admin/service/PgCluster.java` 的 `BIN_DIRS` **同源**：`PATH` 优先 + Debian 绝对路径兜底 |
| `require_pg()` | 「缺 PG」的**唯一**处置点：未设标记 ⇒ `pytest.skip`（本机开发友好）；设了（CI）⇒ `pytest.fail`（**红**）—— skip ≠ pass，CI 上「没跑」绝不能是绿 |
| `binaries()` | 三个二进制的**绝对路径**（argv 必须用绝对路径：runner 的 PG **不在 PATH 里**，按名调用会 `FileNotFoundError`） |
| `REALDB_TEST_MODULES` | 依赖真 PG 的测试模块**冻结登记表**（删 / 改名 / 新增未登记 ⇒ 守卫判红） |
| `start_cluster()` / `stop_cluster()` | 起/停一次性集群的**唯一实现**（issue #5263）—— 15 个模块此前各持一份 ~12 行拷贝，连报错文案都有 15 份 |
| `parse_pg_processes()` / `is_tmp_datadir()` / `PgProcess.orphan` | **孤儿集群的判据**（`ppid==1` 且数据目录在临时区）—— 供 `scripts/pg_orphan_sweep.py` 与判据文件**共用同一份**口径 |

判据（能红）落在 `tests/unit_ci_workflows/test_realdb_failclosed.py` 的判据⑤~⑧；
本模块的默认行为在**生产 / CI 一字不变**（只有显式设了覆盖孔才换搜索路径）。

## issue #5263：起/停集群也收口到这里（病灶 = 孤儿 postmaster）

`pg_ctl start` 起的临时集群若只在**成功路径**上 `pg_ctl stop`，异常退出 / 被中止时就会留下
**孤儿 postmaster**：父 pytest 退出后被 `launchd`（ppid=1）收养，数据目录留在 `/tmp` 或 pytest tmp 下，
**永不回收**（issue #5263 本机实测 6 个全在、ppid 全 = 1、最久 **3 天 13 小时**、每个集群 ~69MB）。

⇒ **实现只许在这里**（不是「每个夹具自己记得加 `finally`」）：

- `start_cluster()`：任何失败路径（`initdb` 失败 / `pg_ctl start` 非零 / `ready` 探测抛错 / Ctrl-C）
  **先 `stop_cluster()` 再抛** —— 「起来了但后面失败」这一形态不再留进程；
- `stop_cluster()`：同一份停库实现（幂等、自身**不抛** —— teardown 里再抛会把真红读成「夹具坏了」）；
- 判据落码在 `tests/unit_ci_workflows/test_pg_orphan_sweep.py`：登记模块**不得**自己调 `pg_ctl start/stop`
  （AST 判 argv 里的 `"start"` / `"stop"` 字面量）、收口件本体必须「失败也停」、夹具的 `yield`
  必须被 teardown 覆盖 —— 三条各自带**注入式红证**。

只读清点的宿主 = `scripts/pg_orphan_sweep.py`（默认 dry-run；`--apply` 才停；**不动** ppid≠1 的在用集群）。

## 红证 A 的覆盖孔（测试专用）

`MIGAO_PG_BIN_DIRS`（对应 Java 侧 `-Dmigao.pg.bin.dirs`，issue #5192）：设了就**整体替换**候选
目录集 —— **连 `PATH` 一起替换**。为什么连 PATH 也换：本机 PG 通常就在 `PATH` 里，只换
`BIN_DIRS` 的话「指向空目录」复现不出「找不到 PG」，红证会变成**假绿**。
指向空目录 ⇒ 带标记 **FAIL** / 不带标记 **skip**（两条真的不同）。
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import NamedTuple

# ⚠️ `pytest` 有意**延迟导入**（见 `require_pg`）：本模块被 `scripts/pg_orphan_sweep.py` 复用
# （只读清点不该要求解释器里装了 pytest），顶层 `import pytest` 会让那条入口在裸 `python3` 上
# 直接 ImportError —— 而它恰恰要在「夹具崩了」的现场跑。

#: 三个二进制（与 Java 侧 `PgCluster` 用的同一集）
PG_BINARIES: tuple[str, ...] = ("initdb", "pg_ctl", "psql")

#: 候选目录 —— 与 `backend/admin-api/src/test/java/com/migao/admin/service/PgCluster.java`
#: 的 `BIN_DIRS` **同源**（先 `PATH`，再按这几条绝对路径兜底；runner 上 PG 就在
#: `/usr/lib/postgresql/16/bin`，**不在 PATH**）。
BIN_DIRS: tuple[str, ...] = (
    "/opt/homebrew/bin",
    "/usr/local/bin",
    "/usr/bin",
    "/usr/lib/postgresql/16/bin",
    "/usr/lib/postgresql/15/bin",
    "/usr/lib/postgresql/14/bin",
)

#: 测试专用覆盖孔（红证 A）；生产 / CI **一律不设**
ENV_BIN_DIRS_OVERRIDE = "MIGAO_PG_BIN_DIRS"

#: CI fail-closed 标记（与 Java 侧 `PgCluster.REQUIRE_REALDB_ENV` 同款语义：
#: 真值 = **非空且非 `0` / `false`**）
ENV_REQUIRE_REALDB = "MIGAO_REQUIRE_REALDB"

#: **冻结登记表**：依赖真 PG 的测试模块（判据⑤按它比对实际集合）。
#: 有意新增 / 删除 / 改名一份真库判据 ⇒ 同批更新这里（判据不许悄悄消失，也不许悄悄多一份拷贝）。
REALDB_TEST_MODULES: frozenset[str] = frozenset({
    "test_cutting_plan_meters_migration.py",
    "test_deposition_total_migration.py",
    "test_inbound_opening_register.py",
    "test_inbound_order_idempotency.py",
    "test_must_finish_retire_migration.py",
    "test_processing_item_route_rules_seed.py",
    "test_product_roll_length_migration.py",
    "test_restore_route_rule_positions_migration.py",
    "test_schema_bootstrap_order.py",
    "test_stock_quantity_decimal_migration.py",
    "test_v81_compensating_backfill.py",
    "test_v93_route_rules_backfill.py",
    "test_v96_operation_price_versions_backfill.py",
    "test_v97_orphan_positions_cleanup.py",
    # issue #5230：「接高」撤出加工项目录项（V123）—— 真库两遍幂等 + 存量组合不静默变价
    "test_v123_retire_join_height_item.py",
    # issue #5263：孤儿集群的判据文件 —— 其中两条**行为级**红证真起集群（失败用例 ⇒ 无残留 /
    # 去掉 teardown ⇒ 真残留），故它**本身就是**真库判据（也经 `realdb_binaries` 夹具取二进制）。
    "test_pg_orphan_sweep.py",
    # issue #5502：dollar-quoted 块内 `:变量` 的类级锁 —— 真库那一半在**全新库**上按文档用法跑
    # `docs/deployment/demo-seed.sql`（ON_ERROR_STOP=1 ⇒ exit 0 + 零 ERROR + 行数 == 语句数），
    # 外加一条把病灶段喂进同一批 psql 调用的红证。缺 PG ⇒ CI 判红（不是静默跳过）。
    "test_psql_vars_outside_dollar_quotes.py",
})

#: 标记的**假值**（与 Java 侧同款口径：非空且非 0/false 才算「要求真库」）
_FALSY: frozenset[str] = frozenset({"", "0", "false"})


def bin_search_dirs() -> list[str]:
    """候选目录（顺序即优先级）：设了覆盖孔 ⇒ **整体替换**（含 `PATH`）；否则 `PATH` + `BIN_DIRS`。"""
    override = os.environ.get(ENV_BIN_DIRS_OVERRIDE)
    if override is not None:
        return [d for d in override.split(os.pathsep) if d]
    dirs = [d for d in (os.environ.get("PATH") or "").split(os.pathsep) if d]
    dirs.extend(BIN_DIRS)
    return dirs


def which(name: str) -> str | None:
    """在候选目录里找**可执行的** `name`。

    ⚠️ 不能用 `shutil.which` —— 它只认 `PATH`，而这正是本 issue 的病灶
    （runner 的 PG 二进制在 `/usr/lib/postgresql/16/bin`，**不在 PATH**）。
    """
    seen: set[str] = set()
    for d in bin_search_dirs():
        if d in seen:
            continue
        seen.add(d)
        candidate = Path(d) / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def missing() -> list[str]:
    """解析不到的二进制（缺 PG 时的**唯一**判据）。"""
    return [b for b in PG_BINARIES if which(b) is None]


def require_realdb() -> bool:
    """`MIGAO_REQUIRE_REALDB` 是否要求「缺 PG 即判红」（真值 = 非空且非 0/false）。"""
    return (os.environ.get(ENV_REQUIRE_REALDB) or "").strip().lower() not in _FALSY


def require_pg() -> None:
    """缺 PG 的**唯一**处置点：CI（带标记）判 **FAIL**，本机（无标记）**显式 skip**。

    由 `tests/unit_ci_workflows/conftest.py` 的 `realdb_binaries` 夹具调用；
    任何测试模块**不得**自备这一判断（复制逻辑 = 下一份拷贝各自演化，#5199 已实证）。
    """
    import pytest  # 延迟导入：本模块也被 scripts/ 的只读入口复用（见文件头）

    absent = missing()
    if not absent:
        return
    detail = (
        f"缺 PG 二进制 {absent} ⇒ 真库判据无法执行。\n"
        f"  搜索路径（顺序即优先级）= {bin_search_dirs()}\n"
        f"  候选目录与 Java 侧 `PgCluster.BIN_DIRS` 同源；runner 镜像在 "
        f"/usr/lib/postgresql/<ver>/bin 自带二进制（issue #5203）"
    )
    if require_realdb():
        pytest.fail(
            f"{detail}\n"
            f"  `{ENV_REQUIRE_REALDB}` 已设 ⇒ 本判据判 **FAIL**（不是 skip）："
            f"CI 上「真库判据没跑」绝不能是**绿**。\n"
            f"  处置：修搜索路径，或在该 job 补装 PostgreSQL —— **不要**退回 pytest.skip。",
            pytrace=False,
        )
    pytest.skip(f"本机没有 PG 二进制 {absent} ⇒ 真库判据未跑（不是通过）")


def binaries() -> dict[str, str]:
    """三个二进制的**绝对路径**（argv 必须用它 —— runner 的 PG 不在 `PATH`）。"""
    resolved: dict[str, str | None] = {b: which(b) for b in PG_BINARIES}
    absent = sorted(b for b, path in resolved.items() if path is None)
    assert not absent, (
        f"缺 PG 二进制 {absent} —— 调用点必须先经收口夹具 `realdb_binaries`"
        f"（它在 `conftest.py` 里走 `require_pg()`：CI 判红 / 本机 skip）"
    )
    return {b: path for b, path in resolved.items() if path is not None}


# ══════════════════════════════════════════════════════════════════════════════════════
# 起 / 停一次性集群的唯一实现（issue #5263 判据①）
# ══════════════════════════════════════════════════════════════════════════════════════

class ClusterStartError(RuntimeError):
    """临时集群起不来（含 `ready` 探测失败）—— 抛出前**已经**把集群停掉（issue #5263）。"""


def _log_tail(log, limit: int = 1500) -> str:
    """集群日志尾部（起不来时唯一有用的证据）；读不到就给占位串，**不抛**。"""
    try:
        text = Path(log).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "<无日志>"
    return text[-limit:] if text else "<日志为空>"


def stop_cluster(pg_ctl: str, datadir, *, timeout: int = 120) -> None:
    """停一次性集群的**唯一**实现（幂等；自身**不抛** —— teardown 里再抛会把红读成「夹具坏了」）。

    `-m immediate`：夹具的库是一次性的，无需 clean shutdown（等 checkpoint 反而拖慢整套）。
    停不掉（进程已死 / 目录已删 / `pg_ctl` 报错）时静默返回 —— 调用方的判据结果不该被 teardown 改写。
    """
    try:
        subprocess.run([pg_ctl, "-D", str(datadir), "-m", "immediate", "stop"],
                       capture_output=True, timeout=timeout)
    except Exception:  # noqa: BLE001 —— 见 docstring：teardown 不抛
        pass


def start_cluster(bins: dict, datadir, *, sockdir, port: int, log,
                  user: str = "postgres", auth: str = "trust",
                  initdb_args: tuple[str, ...] = (), wait: bool = False,
                  ready=None, timeout: int = 120) -> subprocess.CompletedProcess:
    """起一次性 PG 集群（unix socket，不占 TCP 端口）；**失败 / 中止路径也停库**（issue #5263 判据①）。

    15 个真库模块的差异都收在这几个孔上（**不许**再有模块自己拼 argv）：

    - `bins`：`realdb_binaries` 夹具给的**绝对路径**字典（runner 的 PG 不在 PATH，issue #5203）；
    - `sockdir` / `port` / `log`：unix socket 目录（**必须短**，路径有 ~104 字节上限）/ 端口 / 日志；
    - `user` / `auth` / `initdb_args`：`initdb` 的用户、认证方式与附加参数（如 `-E UTF8 --locale=C`）；
    - `wait`：是否给 `pg_ctl start` 加 `-w`（本机实测：不加 `-w` 更可靠，改用 `ready` 探测就绪）；
    - `ready`：起完后的就绪探测（连不上就让它抛）—— 探测失败**同样**先停再抛。

    ⚠️ 本函数只保证「自己这一段」的清理；调用方夹具的 teardown（`yield` 后的 `finally`）**仍必须**
    调 `stop_cluster()` —— 两句合起来才覆盖「用例失败 / 用例内抛错」这条路径（判据①逐模块钉住）。
    """
    initdb_argv = [bins["initdb"], "-D", str(datadir), "-U", user, "-A", auth, *initdb_args]
    start_argv = [bins["pg_ctl"], "-D", str(datadir), "-l", str(log), "-o",
                  f"-k {sockdir} -p {port} -c listen_addresses=''"]
    if wait:
        start_argv.append("-w")
    start_argv.append("start")
    try:
        subprocess.run(initdb_argv, check=True, capture_output=True, timeout=timeout)
        started = subprocess.run(start_argv, capture_output=True, text=True, timeout=timeout)
        if started.returncode != 0:
            raise ClusterStartError(
                f"临时集群起不来：{started.stdout}\n{started.stderr}\n{_log_tail(log)}")
        if ready is not None:
            ready()
        return started
    except BaseException:            # 含 KeyboardInterrupt：中止路径也不许留孤儿
        stop_cluster(bins["pg_ctl"], datadir)
        raise


# ══════════════════════════════════════════════════════════════════════════════════════
# 孤儿集群的**只读清点**判据（issue #5263 判据②/③）
# 宿主 = `scripts/pg_orphan_sweep.py`；判据文件 = `tests/unit_ci_workflows/test_pg_orphan_sweep.py`
# ══════════════════════════════════════════════════════════════════════════════════════
#: 取数口径（`ps` 的参数与解析**同处** —— 分开放会各自演化）。
#: ⚠️ `-ww`（**不限宽**，BSD 与 procps 都认：BSD 单 `-w` 只到 132 列、`-ww` 不限；procps `-w` 加倍 = 不限）：
#: Linux procps 在**非 tty** 下默认按 ~80 列**截断 `command`** ⇒ 数据目录会被切掉尾部 ⇒ 清点**漏判真孤儿**
#: （本单 CI 实测踩过：`ci workflow helper unit tests` 里真残留被判成「无残留」）。**不许**去掉这个 `-ww`。
PS_ARGS: tuple[str, ...] = ("-A", "-ww", "-o", "pid=,ppid=,etime=,command=")

#: 数据目录落在这些根下 = 「临时区」。`/private/tmp` 是 macOS `/tmp` 的真实路径；
#: macOS 的 `$TMPDIR` 在 `/var/folders/**/T` 下。pytest 的 tmp 根（`pytest-of-<user>`）通常就在其中。
TMP_DATADIR_ROOTS: tuple[str, ...] = ("/tmp", "/private/tmp", "/var/folders")

#: pytest tmp 根的**跨 TMPDIR 兜底**：清点时的 `TMPDIR` 可能与被清对象的不是同一个（不同会话）。
PYTEST_TMP_MARKER = "/pytest-of-"

_PS_ROW = re.compile(r"^\s*(?P<pid>\d+)\s+(?P<ppid>\d+)\s+(?P<etime>\S+)\s+(?P<command>.*\S)\s*$")
_DATADIR_ARG = re.compile(r"(?:^|\s)-D\s+(?P<dir>\S+)")
_POSTGRES_CMD = re.compile(r"(?:^|/)postgres(?:\s|$)")
#: `ps -o etime=` 的形态（BSD 与 GNU 同款）：`MM:SS` / `HH:MM:SS` / `D-HH:MM:SS`（`DD-…` 也吃）。
_ETIME = re.compile(r"^(?:(?P<days>\d+)-)?(?:(?P<hours>\d+):)?(?P<minutes>\d+):(?P<seconds>\d+)$")


class PgProcess(NamedTuple):
    """`ps` 里的一条 `postgres -D <datadir>`（postmaster；后端进程的 argv 里没有 `-D`）。

    ⚠️ **`NamedTuple` 而不是 `@dataclass`**：本模块被 `scripts/pg_orphan_sweep.py` 与守卫测试按**路径**
    加载（`module_from_spec` + `exec_module`，不注册进 `sys.modules`）—— 而 `@dataclass` 会去
    `sys.modules[cls.__module__]` 解析注解 ⇒ 实测 `AttributeError: 'NoneType' object has no attribute
    '__dict__'`。`NamedTuple` 无此依赖（且本就不需要可变性）。
    """

    pid: int
    ppid: int
    etime: str
    datadir: str
    command: str

    @property
    def orphan(self) -> bool:
        """**孤儿判据本体**（issue #5263）：`ppid==1` **且** 数据目录在临时区。

        🔴 **实测警告（本单实测，别把它读成「没在用」）**：`pg_ctl start` 是 fork-and-exit ——
        postmaster 的父进程**秒级**就变成 launchd。本机实测：**发起集群的 python 进程仍存活**时，
        `ps` 里该 postmaster 已经是 `ppid=1` / 存活 3 秒 ⇒ **`ppid==1` 不足以区分孤儿与在用集群**。

        所以本判据只回答「**这条不在任何会话的父链上**」（issue 原文的口径），
        「**不动仍然活着的集群**」这条边界由 `scripts/pg_orphan_sweep.py` 的 `--min-age` 单独表达
        （存活时长低 ⇒ 可能正被在跑的用例使用 ⇒ 列出但不动）。两件事**不许合并成一个条件**。
        """
        return self.ppid == 1 and is_tmp_datadir(self.datadir)

    @property
    def age_seconds(self) -> int | None:
        """存活时长（秒）；`ps` 的形态解析不了 ⇒ `None`（调用方**不得**把 `None` 当「很久」）。"""
        return parse_etime_seconds(self.etime)


def parse_pg_processes(ps_text: str) -> list[PgProcess]:
    """从 `ps` 输出里挑出 `postgres -D <datadir>` 行（**纯函数**：注入 `ps` 文本即可判据）。"""
    rows: list[PgProcess] = []
    for line in ps_text.splitlines():
        row = _PS_ROW.match(line)
        if row is None:
            continue
        command = row.group("command")
        if _POSTGRES_CMD.search(command) is None:
            continue
        datadir = _DATADIR_ARG.search(command)
        if datadir is None:
            continue
        rows.append(PgProcess(pid=int(row.group("pid")), ppid=int(row.group("ppid")),
                              etime=row.group("etime"), datadir=datadir.group("dir"),
                              command=command))
    return rows


def parse_etime_seconds(etime: str) -> int | None:
    """`ps -o etime=` 的存活时长 → 秒（`MM:SS` / `HH:MM:SS` / `D-HH:MM:SS`）；解析不了 ⇒ `None`。

    ⚠️ `None` 的语义是「**不知道**」，调用方**不得**把它当「很久」（`scripts/pg_orphan_sweep.py`
    的处置逻辑对 `None` 一律不动作 —— fail-closed）。
    """
    row = _ETIME.match(etime.strip())
    if row is None:
        return None
    return (int(row.group("days") or 0) * 86400 + int(row.group("hours") or 0) * 3600
            + int(row.group("minutes")) * 60 + int(row.group("seconds")))


def is_tmp_datadir(datadir: str) -> bool:
    """数据目录是否在**临时区**（`/tmp` / macOS `$TMPDIR` / pytest 的 `pytest-of-*`）。"""
    path = os.path.realpath(datadir)
    if PYTEST_TMP_MARKER in path:
        return True
    for root in TMP_DATADIR_ROOTS:
        real = os.path.realpath(root).rstrip("/")
        if path == real or path.startswith(real + "/"):
            return True
    return False


def orphan_postmasters(rows: list[PgProcess]) -> list[PgProcess]:
    """孤儿集群 = `ppid==1` **且** 数据目录在临时区（清点与 `--apply` 处置**共用**这一条判据）。"""
    return [row for row in rows if row.orphan]


def tmp_base() -> str:
    """本进程的临时区根（清点输出里带上它：`/var/folders/...` 与 `/tmp` 的现场一眼可辨）。"""
    return os.path.realpath(tempfile.gettempdir())