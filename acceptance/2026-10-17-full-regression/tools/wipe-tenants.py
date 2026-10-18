#!/usr/bin/env python3
"""清空指定租户的全部数据（按 FK 拓扑序，子表优先）—— 2026-10-14 环境重建。

口径（与 2026-10-04 重建同族）：
  · 只删 `tenants` 里**点名**的那几行，及其 `tenant_id` 落在点名集合内的子表数据；
  · 拓扑序由 `pg_constraint` 现取（不硬编码表名 —— 表会随迁移漂移）；
  · 整体一个事务：任一语句失败 ⇒ 全量回滚（不留半清空状态）；
  · 默认 **dry-run**（只打印将要删的行数，不写库）；`--apply` 才真删。

用法：
  python3 acceptance/2026-10-14/tools/wipe-tenants.py --tenant-ids 25,31            # dry-run
  python3 acceptance/2026-10-14/tools/wipe-tenants.py --tenant-ids 25,31 --apply    # 真删
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


ENV = load_env(REPO / "backend/admin-api/.env")


def psql(sql: str, *, tuples_only: bool = True) -> str:
    cmd = [
        "psql",
        "-h", ENV["RDS_HOST"],
        "-p", ENV.get("RDS_PORT", "5432"),
        "-U", ENV["RDS_USER"],
        "-d", ENV["RDS_DB"],
        "-v", "ON_ERROR_STOP=1",
        "-X", "-q", "-A", "-t",
    ]
    if not tuples_only:
        cmd = [c for c in cmd if c not in ("-A", "-t")]
    proc = subprocess.run(
        cmd, input=sql, capture_output=True, text=True,
        env={**os.environ, "PGPASSWORD": ENV["RDS_PASSWORD"]},
    )
    if proc.returncode != 0:
        raise SystemExit(f"psql 失败（rc={proc.returncode}）:\n{proc.stderr.strip()}")
    return proc.stdout


def q(sql: str) -> list[str]:
    return [r for r in psql(sql).splitlines() if r != ""]


def q1(sql: str) -> str:
    rows = q(sql)
    return rows[0] if rows else ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant-ids", required=True, help="逗号分隔的租户 id")
    ap.add_argument("--apply", action="store_true", help="真删（默认 dry-run）")
    args = ap.parse_args()

    tids = [int(x) for x in args.tenant_ids.split(",") if x.strip()]
    tid_list = ",".join(str(t) for t in tids)

    tenants = q(f"select id||'|'||name||'|'||coalesce(code,'') from tenants where id in ({tid_list}) order by id")
    if not tenants:
        raise SystemExit(f"❌ tenants 里没有 id ∈ {{{tid_list}}} 的行")

    # 有 tenant_id 列的表（现取）
    tables = q(
        "select table_name from information_schema.columns "
        "where column_name='tenant_id' and table_schema='public' order by table_name"
    )
    # 引用 tenants 的表 —— 两集合必须一致，否则有「无 tenant_id 却挂在租户上」的表要单独处置
    fk_tables = q(
        "select distinct conrelid::regclass::text from pg_constraint "
        "where contype='f' and confrelid='tenants'::regclass order by 1"
    )
    only_fk = sorted(set(fk_tables) - set(tables))
    if only_fk:
        print(f"⚠️  引用 tenants 但没有 tenant_id 列的表（需人工处置）：{only_fk}")

    # 拓扑序：子表优先（Kahn）。边 = 子表 → 父表（psql -A 的字段分隔符 = |）
    parent_of: dict[str, set[str]] = {t: set() for t in tables}
    for row in q(
        "select conrelid::regclass::text, confrelid::regclass::text from pg_constraint where contype='f'"
    ):
        parts = row.split("|")
        if len(parts) != 2:
            continue
        child, parent = parts[0].strip(), parts[1].strip()
        if child in parent_of and parent in parent_of and parent != child:
            parent_of[child].add(parent)

    # Kahn：先输出「没有未被处理的子表引用它」的表（= 叶子/子表优先）
    children_of: dict[str, set[str]] = {t: set() for t in tables}
    for child, parents in parent_of.items():
        for p in parents:
            children_of[p].add(child)
    remaining = set(tables)
    order: list[str] = []
    while remaining:
        ready = sorted(t for t in remaining if not (children_of[t] & remaining))
        if not ready:
            print(f"❌ 存在环，无法拓扑排序：{sorted(remaining)}")
            print("   处理办法：对环内表用 `UPDATE ... SET <fk>=NULL` 打散，或确认 migao_admin 有超级用户权限后用 session_replication_role=replica")
            return 2
        for t in ready:
            order.append(t)
            remaining.discard(t)

    counts = {t: int(q1(f"select count(*) from {t} where tenant_id in ({tid_list})")) for t in order}

    total = sum(counts.values())
    print("── 将清空（子表优先，共 %d 张表 / %d 行）──" % (len(order), total))
    for t in order:
        if counts[t]:
            print(f"  {counts[t]:>7}  {t}")
    print(f"  {'—':>7}  tenants (id ∈ {{{tid_list}}}) → 删除 {len(tenants)} 行")
    for row in tenants:
        print(f"          · {row}")

    if not args.apply:
        print("\n（dry-run：未写库；加 --apply 真删）")
        return 0

    sql = ["BEGIN;"]
    for t in order:
        sql.append(f'DELETE FROM "{t}" WHERE tenant_id IN ({tid_list});')
    sql.append(f"DELETE FROM tenants WHERE id IN ({tid_list});")
    sql.append("COMMIT;")
    psql("\n".join(sql), tuples_only=False)

    # 残留自证（现取）
    resid = {t: int(q1(f"select count(*) from {t} where tenant_id in ({tid_list})")) for t in order}
    left = sum(resid.values())
    still = q(f"select id from tenants where id in ({tid_list})")
    print("\n── 残留自证（现取）──")
    print(f"  点名租户的子表残留行数合计 = {left}")
    print(f"  tenants 里仍存在的点名行 = {still if still else '无'}")
    out = {
        "wiped_tenant_ids": tids,
        "rows_deleted_by_table": {t: c for t, c in counts.items() if c},
        "rows_deleted_total": total,
        "residue_rows_after": left,
        "residue_tenants_rows_after": still,
        "tenants_before": tenants,
    }
    out_path = REPO / "acceptance/2026-10-17-full-regression/evidence/wipe-tenants.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  读数落盘：{out_path.relative_to(REPO)}")
    return 0 if left == 0 and not still else 1


if __name__ == "__main__":
    sys.exit(main())
