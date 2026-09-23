# case_ids: PR-107
"""真库判据的 PG 二进制发现 + 「缺 PG」处置的**唯一收口**（issue #5203，承 #5192）。

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

判据（能红）落在 `tests/unit_ci_workflows/test_realdb_failclosed.py` 的判据⑤~⑧；
本模块的默认行为在**生产 / CI 一字不变**（只有显式设了覆盖孔才换搜索路径）。

## 红证 A 的覆盖孔（测试专用）

`MIGAO_PG_BIN_DIRS`（对应 Java 侧 `-Dmigao.pg.bin.dirs`，issue #5192）：设了就**整体替换**候选
目录集 —— **连 `PATH` 一起替换**。为什么连 PATH 也换：本机 PG 通常就在 `PATH` 里，只换
`BIN_DIRS` 的话「指向空目录」复现不出「找不到 PG」，红证会变成**假绿**。
指向空目录 ⇒ 带标记 **FAIL** / 不带标记 **skip**（两条真的不同）。
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

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
