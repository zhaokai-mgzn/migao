#!/usr/bin/env python3
"""pg_orphan_sweep — 真库判据留下的**孤儿 PG 集群**的只读清点入口（issue #5263）。

## 病灶（issue #5263 本机实测，逐条可复算）

真库判据（`tests/unit_ci_workflows/**`）各自 `initdb` + `pg_ctl start` 起一次性集群；进程被中止 /
异常退出时 postmaster 由 `launchd`（ppid=1）收养，数据目录留在 `/tmp` 或 pytest tmp 下 —— **永不回收**。
实测现场：6 个全在、ppid 全 = 1、最久 **3 天 13 小时**、每个集群 ~69MB，且会带来
「临时 socket 目录复用 ⇒ 新用例连到旧集群」这类**不可解释的判据结果**。

## 三条判据（逐字落码，见 issue「建议判据」表）

| # | 判据 | 本脚本的落码 |
|---|---|---|
| ① | **只读清点**：列出「`ppid==1` 且数据目录在 `/tmp` 或 pytest tmp 下」的 `postgres -D` | 默认行为；**无残留时也打印计数 0**（不是静默无输出 —— 「没扫到」必须长得像「没扫到」） |
| ② | 默认 **dry-run**，`--apply` 才停 | 不加 `--apply` 时**零写操作**（不停、不删、不建文件），只在有孤儿时给出 `--apply` 提示 |
| ③ | **不得**停 `ppid≠1` 的进程（那是正在被用例使用的） | 分类只在 `pg_cluster.PgProcess.orphan` 一处实现；`--apply` 逐条**再核一次** `ppid==1` 才动手；另加**存活时长**闸（见下） |

## 🔴 实测口径修正（本单实测 —— 不读这段会误停正在跑的用例）

`ppid==1` **不等于**「没在用」：`pg_ctl start` 是 fork-and-exit，postmaster 的父进程**秒级**就变成
launchd。本机实测（发起集群的 python 进程**仍存活**）：

    68930     1       00:03 /opt/homebrew/Cellar/postgresql@16/16.15/bin/postgres -D /tmp/pg5263-probe/pgdata …

⇒ 判据③按 issue 原文**逐字实现**（`ppid≠1` 一律不动），但它**不足以**区分孤儿与在用集群。
issue 的「不做」条（**不动仍然活着的集群** —— 原文举的例就是那个 30 分钟的）因此**另用存活时长表达**：
`--apply` 只停存活 ≥ `--min-age`（默认 30 分钟）的孤儿；低龄的**列出但一律不动作**。

⇒ 本机的正确用法 = **先看 dry-run 清单里的存活时长**（`存活=16:39` 这种），确认与当前会话无关再 `--apply`；
两个数字（`ppid==1` 与 `≥30 分钟`）是**两道**闸，不是一道。

## 它**不**做什么（诚实登记，防被读成门禁或定时任务）

- **不**自动定时清理（本仓口径 = 事件驱动、不无人值守删东西，见 `scripts/issue-lifecycle.sh` 头注释）；
  本入口是**手动、attended** 的；
- **不**删数据目录（只停进程；`/tmp` 的回收交给 OS / 人 —— 「无人值守删东西」正是要避免的形态）；
- **不**动 `ppid≠1` 的集群（误停 = 制造假失败）；**不**改 CI runner 的清理策略（另立）。

## 用法（仓根）

    python3 scripts/pg_orphan_sweep.py            # 只读清点（默认 dry-run）
    python3 scripts/pg_orphan_sweep.py --apply    # 停掉清点到的孤儿（只停 ppid==1 **且**存活 ≥30 分钟的）
    python3 scripts/pg_orphan_sweep.py --apply --min-age 120

## 退出码（与仓内既有三态口径一致：`scripts/merge_gate.py` / `scripts/dangling_pr_scan.py`）

| 码 | 含义 |
|---|---|
| `0` | 扫到了、**没有**孤儿（输出里必然有一行计数 0） |
| `1` | 扫到了、**有**孤儿（dry-run 下逐条列出 + 给出 `--apply` 提示） |
| `3` | **无法判定**（`ps` 跑不起来 / 输出读不到）—— 「看不了」**不得**当「没问题」读 |

## 宿主选择 / 判据不复制

本仓 `scripts/**` 里没有同类「PG 进程清点」件（`issue-lifecycle.sh` 管分支与 worktree、
`dangling_pr_scan.py` 管 PR 悬空、`rework_hotspot_scan.py` 管 git 历史）⇒ 新建独立入口。
分类口径（`ps` 参数、`postgres -D` 解析、`ppid==1 且临时区` 判据、停库实现）**一律不复制**，
经 importlib 按路径复用 `tests/unit_ci_workflows/pg_cluster.py`（#5203/#5199 的教训：副本会各自演化）。

## 注入点（测试专用；沿用 `MG_GH_BIN` / `SBT_GH_BIN` 的「替身可执行文件」口径）

    PG_SWEEP_PS_BIN=<可执行文件>      替身 `ps`（喂受控进程表 ⇒ 判据①②③可复算）
    PG_SWEEP_PG_CTL_BIN=<可执行文件>  替身 `pg_ctl`（记录 argv ⇒ 断言「到底停没停、停了谁」）
    PG_SWEEP_FUNNEL=<pg_cluster.py>   替身收口件（注入式红证：对**副本**做单点变异后重跑）
"""
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FUNNEL_PATH = REPO_ROOT / "tests" / "unit_ci_workflows" / "pg_cluster.py"

ENV_PS_BIN = "PG_SWEEP_PS_BIN"
ENV_PG_CTL_BIN = "PG_SWEEP_PG_CTL_BIN"
ENV_FUNNEL = "PG_SWEEP_FUNNEL"

EXIT_CLEAN = 0
EXIT_ORPHANS = 1
EXIT_UNJUDGEABLE = 3

#: `--apply` 的存活时长下限（分钟）：低龄的**可能正被在跑的用例使用**（实测 `ppid==1` 证明不了没在用）
#: ⇒ 列出但一律不动作。30 分钟沿用 issue #5263 对「那个 30 分钟的未动」的谨慎口径。
DEFAULT_MIN_AGE_MINUTES = 30


def funnel():
    """按路径加载**收口件**（不复制它的 `BIN_DIRS` / 解析口径 / 停库实现 —— #5199 的教训）。"""
    path = Path(os.environ.get(ENV_FUNNEL) or FUNNEL_PATH)
    spec = spec_from_file_location("_pg_cluster_for_sweep", path)
    assert spec is not None and spec.loader is not None, f"加载不了收口件：{path}"
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def scan(pg, ps_bin: str) -> tuple[list, str]:
    """跑 `ps` 并解析 ⇒ `(全部 postgres -D 行, 失败原因)`；失败原因非空 = **无法判定**。"""
    try:
        proc = subprocess.run([ps_bin, *pg.PS_ARGS], capture_output=True, text=True)
    except OSError as exc:
        return [], f"`{ps_bin}` 跑不起来：{exc}"
    if proc.returncode != 0:
        return [], (f"`{ps_bin} {' '.join(pg.PS_ARGS)}` 非零退出（exit={proc.returncode}）："
                    f"{proc.stderr.strip()}")
    return pg.parse_pg_processes(proc.stdout), ""


def stop_one(pg, row, pg_ctl: str) -> str:
    """停一个**已核实 ppid==1** 的孤儿：优先 `pg_ctl`（收口件的同一份实现），否则退回 `SIGTERM`。"""
    if pg_ctl:
        pg.stop_cluster(pg_ctl, row.datadir)
        return f"pg_ctl -D {row.datadir} -m immediate stop"
    try:
        os.kill(row.pid, signal.SIGTERM)
    except OSError as exc:
        return f"SIGTERM 失败：{exc}"
    return f"kill -TERM {row.pid}"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="孤儿 PG 集群的只读清点（默认 dry-run；--apply 才停，且只停 ppid==1）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="判据：ppid==1 且数据目录在 /tmp 或 pytest tmp 下（issue #5263）",
    )
    parser.add_argument("--apply", action="store_true",
                        help="停掉清点到的孤儿（不加 = 只读清点，零写操作）")
    parser.add_argument("--min-age", type=int, default=DEFAULT_MIN_AGE_MINUTES, metavar="MINUTES",
                        help=f"只停存活 ≥ 这么多分钟的孤儿（默认 {DEFAULT_MIN_AGE_MINUTES}）—— "
                             f"低龄的**可能正被在跑的用例使用**，一律列出但不动作")
    args = parser.parse_args(argv)

    pg = funnel()
    ps_bin = os.environ.get(ENV_PS_BIN) or "ps"
    rows, error = scan(pg, ps_bin)
    if error:
        print(f"[pg-orphan-sweep] **无法判定**（{error}）—— 「看不了」不得当「没有孤儿」读",
              file=sys.stderr)
        return EXIT_UNJUDGEABLE

    orphans = pg.orphan_postmasters(rows)
    if orphans:
        print(f"[pg-orphan-sweep] 清点到孤儿集群（ppid==1 且在临时区）{len(orphans)} 个：")
        for row in orphans:
            print(f"  孤儿 pid={row.pid} ppid={row.ppid} 存活={row.etime} 数据目录={row.datadir}")

    if args.apply:
        pg_ctl = os.environ.get(ENV_PG_CTL_BIN) or pg.which("pg_ctl") or ""
        for row in orphans:
            if row.ppid != 1:            # 处置前**再核一次**（清点与处置之间父进程可能换了）
                print(f"  ⏸ 跳过 pid={row.pid}（ppid={row.ppid} ≠ 1 ⇒ 可能正被在跑的用例使用，**不动**）")
                continue
            age = row.age_seconds
            if age is None or age < args.min_age * 60:
                # 「不动仍然活着的集群」（issue #5263「不做」条）：ppid==1 **不足以**证明没在用
                # （实测见文件头）⇒ 低龄 / 时长读不到的一律不动作，只列出。
                why = "存活时长解析不了" if age is None else f"存活={row.etime} < {args.min_age} 分钟"
                print(f"  ⏸ 跳过 pid={row.pid}（{why} ⇒ 可能正被在跑的用例使用，**不动**）")
                continue
            print(f"  已停 pid={row.pid} 数据目录={row.datadir} ⇒ {stop_one(pg, row, pg_ctl)}")
        rows, error = scan(pg, ps_bin)   # 复查：停完**还剩几条**（这是 `--apply` 效果的正证）
        if error:
            print(f"[pg-orphan-sweep] **无法判定**（处置后复查失败：{error}）", file=sys.stderr)
            return EXIT_UNJUDGEABLE
        orphans = pg.orphan_postmasters(rows)

    in_use = [row for row in rows if not row.orphan]
    print(f"[pg-orphan-sweep] 孤儿集群 = {len(orphans)}"
          f"（扫到 postgres -D 进程 = {len(rows)} 条；ppid!=1（在用，**不动**）= {len(in_use)} 条；"
          f"本进程临时区根 = {pg.tmp_base()}）")
    if orphans and not args.apply:
        print("[pg-orphan-sweep] dry-run：**未做任何写操作**；"
              "处置 = `python3 scripts/pg_orphan_sweep.py --apply`（只停 ppid==1，不删目录）")
    return EXIT_ORPHANS if orphans else EXIT_CLEAN


if __name__ == "__main__":
    sys.exit(main())