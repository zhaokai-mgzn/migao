#!/usr/bin/env python3
"""只增表**体量 / 最老行年龄**读数（issue #8218 上线审计 P1-11）。

## 病（2026-10-31 审计读数，逐字）

- **C**：`deploy/ops/db-retention.sql` 文件头逐字「**人工执行**，不是定时任务」；
  `audit_logs` 保留 365 天 / `notifications` 保留 180 天；
- **C**：仓库内**无任何值守面**（无告警、无读数、无到期提醒）；
- ⇒ 两张只增表**无界增长**（索引体积 / 备份窗口 / 查询变慢），而「**没有清理**这件事不会有人知道」。

## 修法（只读读数，不新增无人值守删除）

⛔ 不新增 schedule / cron（铁律 10：无人值守删除不安全）。删除仍是**人工执行**
`deploy/ops/db-retention.sql`（先 count 看量、再低峰 purge）。本脚本只补两件读数：
「**表多大**」与「**多久没清了**」—— 超限就红（rc=1），读不到就**无法判定**（rc=3）。

## 三态退出码（`3` **不得**当 `0` 读）

| rc | 含义 | 处置 |
|---|---|---|
| `0` | 两张表都在默认保留期内，且体量未超体量阈值 | 写进当班记录 |
| `1` | `oldest_age_days` 超过该表保留期（365 / 180）**或** `total_bytes` 超过阈值（默认 512 MiB） | 当班开单：按 `deploy/ops/db-retention.sql` **人工执行**（先 count 看量，再低峰 purge） |
| `3` | **无法判定**：缺 `DATABASE_URL` / 找不到 `psql` / 连接或 SQL 失败 / 少一张表的读数行 / CSV 解析不了 | 修取数面；**读不到 ≠ 通过**（`DQ-U` 同族） |

## 读数列

`table_name` / `total_bytes`（`pg_total_relation_size`）/ `row_count` / `oldest_created_at` /
`oldest_age_days`（`now() - min(created_at)` 的天数）。SQL 见 `deploy/ops/db-growth-readout.sql`（**只有 SELECT**）。

## 环境变量与用法（仓根）

| 变量 | 必需 | 说明 |
|---|---|---|
| `DATABASE_URL` | 是（默认面） | 只读账号的连接串；缺失 ⇒ `rc=3` |

    # ① 正常读数（需要 DATABASE_URL）
    python3 scripts/db_growth_readout.py

    # ② 值班直接看表（只读 SQL）
    psql "$DATABASE_URL" -f deploy/ops/db-growth-readout.sql

    # ③ 离线复核（零网络）
    psql "$DATABASE_URL" -v ON_ERROR_STOP=1 --csv -f deploy/ops/db-growth-readout.sql > /tmp/db-growth.csv
    python3 scripts/db_growth_readout.py --from-csv /tmp/db-growth.csv

## 期望阈值 / 告警口径

`docs/deployment/production-deployment.md` 的 §5.3（**真值源**：那里写阈值与值班动作，本脚本的默认值与其同源）。

## 边界（照实登记，§19.1）

- **只读**：只 SELECT；不删、不改、不建表，也不落盘。
- 不判「该不该清」—— 保留期是业务/合规口径（`deploy/ops/db-retention.sql` 头部），本脚本只报「超没超」。
- 不判「真库上的列形态是否与建库脚本一致」—— 那是 `docs/testing/production-readonly-verification-pack.md` 的面。
- 判据 = `tests/unit_ci_workflows/test_ops_readouts.py`（替身 `psql` + 离线 CSV，零网络、零真库）。
"""
from __future__ import annotations

import argparse
import csv
import io
import os
import shutil
import subprocess
import sys
from pathlib import Path

#: 只读账号的连接串（必需；缺失 ⇒ rc=3，不许绿）
ENV_DATABASE_URL = "DATABASE_URL"
#: 只读 SQL（**只有 SELECT**；判据会静态核它的可执行面）
SQL_PATH = Path(__file__).resolve().parents[1] / "deploy" / "ops" / "db-growth-readout.sql"
#: 期望阈值 = 各表保留期（天）。与 deploy/ops/db-retention.sql 的默认值同源
DEFAULT_MAX_AGE_DAYS = {
    "audit_logs": 365,
    "notifications": 180,
}
#: 体量阈值：超过就说明索引/备份窗口开始受拖累（单表 512 MiB）
DEFAULT_WARN_BYTES = 512 * 1024 * 1024
#: 两张只增表**都必须**有读数行（少一张 ⇒ 无法判定，不许当通过）
REQUIRED_TABLES = ("audit_logs", "notifications")
#: psql 输出列（顺序无关，按列名取）
REQUIRED_COLUMNS = ("table_name", "total_bytes", "row_count", "oldest_age_days")

RC_OK = 0
RC_OVER = 1
RC_UNDECIDABLE = 3
TIMEOUT_SECONDS = 120


def _as_int(raw: object) -> int | None:
    text = str(raw if raw is not None else "").strip()
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _as_float(raw: object) -> float | None:
    text = str(raw if raw is not None else "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_rows(csv_text: str) -> tuple[list[dict[str, object]] | None, str]:
    """把 `psql --csv` 的输出解析成读数行；解析不了 ⇒ ``(None, 原因)``（不猜）。"""
    reader = csv.DictReader(io.StringIO(csv_text))
    fieldnames = [(name or "").strip() for name in (reader.fieldnames or [])]
    missing = [column for column in REQUIRED_COLUMNS if column not in fieldnames]
    if missing:
        return None, f"CSV 头缺列 {missing}（读数器读不出体量 / 最老行年龄）"
    rows: list[dict[str, object]] = []
    for raw in reader:
        table = str(raw.get("table_name") or "").strip()
        if not table:
            continue
        rows.append(
            {
                "table_name": table,
                "total_bytes": _as_int(raw.get("total_bytes")),
                "row_count": _as_int(raw.get("row_count")),
                "oldest_created_at": str(raw.get("oldest_created_at") or "").strip() or None,
                "oldest_age_days": _as_float(raw.get("oldest_age_days")),
            }
        )
    if not rows:
        return None, "CSV 里没有任何读数行（空结果不是通过）"
    return rows, ""


def _undecidable(why: str) -> int:
    print(f"DB-GROWTH-READOUT verdict=undecidable why={why}")
    print(f"无法判定（rc={RC_UNDECIDABLE}）：{why} —— 3 一律不得当 0 读", file=sys.stderr)
    return RC_UNDECIDABLE


def _parse_age_overrides(specs: list[str], base: dict[str, int]) -> tuple[dict[str, int] | None, str]:
    limits = dict(base)
    for spec in specs:
        table, _, raw = spec.partition("=")
        table, raw = table.strip(), raw.strip()
        if not table or not raw:
            return None, f"--max-age-days 需要 `表=天数` 形态（现取 {spec!r}）"
        try:
            limits[table] = int(raw)
        except ValueError:
            return None, f"--max-age-days 的天数不是整数（现取 {spec!r}）"
    return limits, ""


def report(rows: list[dict[str, object]], *, source: str, detail: str, limits: dict[str, int], warn_bytes: int) -> int:
    head = f"DB-GROWTH-READOUT source={source}"
    if detail:
        head += f" path={detail}"
    print(head)

    present = {str(row["table_name"]) for row in rows}
    missing = [table for table in REQUIRED_TABLES if table not in present]
    over = 0
    for row in rows:
        table = str(row["table_name"])
        age = row["oldest_age_days"]
        size = row["total_bytes"]
        limit_age = limits.get(table)
        flags: list[str] = []
        if limit_age is not None and isinstance(age, float) and age > limit_age:
            flags.append("over-age")
        if isinstance(size, int) and size > warn_bytes:
            flags.append("over-size")
        if flags:
            over += 1
        verdict = ",".join(flags) if flags else "ok"
        age_txt = "-" if age is None else f"{float(age):g}"
        size_txt = "-" if size is None else str(size)
        rows_txt = "-" if row["row_count"] is None else str(row["row_count"])
        limit_txt = "n/a" if limit_age is None else str(limit_age)
        print(
            f"  table={table} rows={rows_txt} total_bytes={size_txt} "
            f"oldest={row['oldest_created_at'] or '-'} oldest_age_days={age_txt} "
            f"max_age_days={limit_txt} verdict={verdict}"
        )

    if missing:
        for table in missing:
            print(f"  ⇒ 缺 `{table}` 的读数行：**读不到 ≠ 通过**（DQ-U 同族），判 rc=3 无法判定")
        print(f"DB-GROWTH-READOUT-SUMMARY tables={len(rows)} over={over} undecidable=1 rc={RC_UNDECIDABLE}")
        missing_txt = ",".join(missing)
        print(f"无法判定（rc={RC_UNDECIDABLE}）：读不到 {missing_txt} 的读数行", file=sys.stderr)
        return RC_UNDECIDABLE

    rc = RC_OVER if over else RC_OK
    print(f"DB-GROWTH-READOUT-SUMMARY tables={len(rows)} over={over} undecidable=0 rc={rc}")
    if over:
        print(
            "  ⇒ 超限：按 docs/deployment/production-deployment.md §5.3 的告警口径当班开单；"
            "清理仍是**人工执行** deploy/ops/db-retention.sql（先 count 看量，再低峰 purge）"
        )
    return rc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="只增表体量 / 最老行年龄只读读数（P1-11；三态 0/1/3）")
    parser.add_argument("--from-csv", default="", help="离线复核：喂 `psql --csv` 的输出文件")
    parser.add_argument("--database-url", default="", help=f"连接串（默认取环境变量 {ENV_DATABASE_URL}）")
    parser.add_argument("--max-age-days", action="append", default=[], metavar="表=天数",
                        help="覆盖某表的保留期（默认 audit_logs=365 / notifications=180）")
    parser.add_argument("--warn-bytes", type=int, default=DEFAULT_WARN_BYTES,
                        help=f"单表体量阈值（默认 {DEFAULT_WARN_BYTES} = 512 MiB）")
    args = parser.parse_args(argv)

    limits, why = _parse_age_overrides(args.max_age_days, DEFAULT_MAX_AGE_DAYS)
    if limits is None:
        return _undecidable(why)

    if args.from_csv:
        try:
            text = Path(args.from_csv).read_text(encoding="utf-8")
        except OSError as exc:
            return _undecidable(f"读不到 CSV 文件 {args.from_csv}：{exc}")
        rows, why = parse_rows(text)
        if rows is None:
            return _undecidable(why)
        return report(rows, source="csv-file", detail=str(args.from_csv), limits=limits, warn_bytes=args.warn_bytes)

    url = (args.database_url or os.environ.get(ENV_DATABASE_URL, "")).strip()
    if not url:
        return _undecidable(f"缺环境变量 {ENV_DATABASE_URL}（只读连接串是读数的必需入参）")
    psql = shutil.which("psql")
    if psql is None:
        return _undecidable("找不到 psql（PostgreSQL 客户端未安装 / PATH 不含它）")
    if not SQL_PATH.is_file():
        return _undecidable(f"找不到只读 SQL {SQL_PATH}")

    rel_sql = f"deploy/ops/{SQL_PATH.name}"
    print(f"DB-GROWTH-READOUT source=psql cmd=psql -v ON_ERROR_STOP=1 --csv -f {rel_sql}")
    try:
        proc = subprocess.run(
            [psql, url, "-v", "ON_ERROR_STOP=1", "--csv", "-f", str(SQL_PATH)],
            capture_output=True, text=True, timeout=TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _undecidable(f"调用 psql 失败：{exc}")
    passthrough = (proc.stderr or "").strip()
    if passthrough:
        print(passthrough, file=sys.stderr)
    if proc.returncode != 0:
        tail = passthrough.splitlines()
        return _undecidable(f"psql 退出码 {proc.returncode}：{tail[-1] if tail else '(无输出)'}")

    rows, why = parse_rows(proc.stdout)
    if rows is None:
        return _undecidable(why)
    return report(rows, source="psql", detail="", limits=limits, warn_bytes=args.warn_bytes)


if __name__ == "__main__":  # pragma: no cover - CLI 入口
    raise SystemExit(main())
