#!/usr/bin/env python3
"""迁移链幂等性真库复现器（issue #3615）—— 无需 docker。

## 用途

在**本机真库**上复刻 `MigrationRunner` 的迁移执行语义，用来验证：

1. **bootstrap-first 全新库**：`docs/sql/schema.sql`（= docker `docker-entrypoint-initdb.d/
   001_schema.sql`）建出终态后，再跑一遍 `db/migration/*.sql` 迁移链 ——
   是否有迁移失败（有则 admin-api 启动打印「schema 可能与代码不一致」噪音）；
2. **幂等性**：清空 `schema_migrations` 后全量重跑，是否仍全绿。

## ⚠️ 现状与期望输出（issue #3615 尚未修复，本脚本当前必然 exit=1）

已发布迁移（V37/V42/V44）的幂等化受 `danger_scan`「已发布迁移只增不改」required 护栏约束，
**当前未修**，故本脚本在 `main`/现状上**如实报红**（这正是它作为证据的价值）：

```
现状（预期）：❌ 迁移失败（已跳过）: V37__rename_knowledge_entries_to_cards.sql
              ❌ 迁移失败（已跳过）: V44__create_daily_briefings.sql
              迁移文件 42 条 / schema_migrations 40 行   → exit=1（打印原告警）

修复后（预期）：迁移文件 42 条 / schema_migrations 42 行
              ✅ 无迁移失败 —— 不会打印「schema 可能与代码不一致」  → exit=0
              再跑 --rerun 亦 exit=0（幂等）
```

迁移植根因（issue #3615，真库实测）：`ALTER TABLE/INDEX ... IF EXISTS` **只守卫源对象、
不守卫目标**，`CREATE POLICY` 无守卫（PG 不支持 `IF NOT EXISTS`）→ bootstrap-first 库上
V37/V42/V44 失败 → 整文件回滚且**不写入 `schema_migrations`** → 每次启动重跑再报一次。
存量缺口清单与逐条证据见 `tests/unit_ci_workflows/test_migration_idempotency.py` 模块 docstring。

## 为什么本机无 docker 也能验证

`MigrationRunner` 的实际行为 = 逐文件 `jdbc.execute(整个文件文本)`：
PostgreSQL 扩展查询下多语句走**单一隐式事务**，任一句失败即整文件回滚。
本脚本用 `cur.execute(整文件文本)` 完整复刻该语义（与 psql `-f` 的分句行为**不同**）。

## 前置

需要一个可连的本机 PostgreSQL（无需 docker）：

    # macOS Homebrew 示例
    initdb -D /tmp/migao-pg && pg_ctl -D /tmp/migao-pg -o "-p 5433 -k /tmp/migao-pg" start

连接参数用环境变量覆盖（默认适配上面这条命令）：
    MIGAO_PG_HOST（默认 /tmp/migao-pg）MIGAO_PG_PORT（默认 5433）
    MIGAO_PG_USER（默认 app_user）MIGAO_PG_PASSWORD（默认空）
    MIGAO_PG_DB（默认 migao_migration_repro）

## 用法（仓库根目录）

    python3 scripts/migration_chain_repro.py            # 全新库跑一遍
    python3 scripts/migration_chain_repro.py --rerun    # 再清空 schema_migrations 全量重跑（幂等）

退出码：0 = 全绿（42/42 应用、零失败）；1 = 有迁移失败（会打印 MigrationRunner 的原告警文案）。
"""
import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MIG_DIR = ROOT / "backend/admin-api/src/main/resources/db/migration"
SCHEMA = ROOT / "docs/sql/schema.sql"

PG_HOST = os.environ.get("MIGAO_PG_HOST", "/tmp/migao-pg")
PG_PORT = os.environ.get("MIGAO_PG_PORT", "5433")
PG_USER = os.environ.get("MIGAO_PG_USER", "app_user")
PG_PASSWORD = os.environ.get("MIGAO_PG_PASSWORD", "")
DB = os.environ.get("MIGAO_PG_DB", "migao_migration_repro")

VERSION_RE = re.compile(r"^V(\d+)__")


def order_key(name: str) -> tuple:
    """与 MigrationRunner.sortKey 一致：不可解析版本号 → 排最后（不许插队到中间）。"""
    m = VERSION_RE.match(name)
    return (int(m.group(1)), name) if m else (2**31 - 1, name)


def _dsn(db: str) -> str:
    parts = [f"dbname={db}", f"user={PG_USER}", f"host={PG_HOST}", f"port={PG_PORT}"]
    if PG_PASSWORD:
        parts.append(f"password={PG_PASSWORD}")
    return " ".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser(description="迁移链幂等性真库复现器（issue #3615）")
    ap.add_argument("--rerun", action="store_true",
                    help="清空 schema_migrations 后全量重跑（幂等性验证）")
    args = ap.parse_args()

    try:
        import psycopg
    except ImportError:
        print("❌ 需要 psycopg：pip install 'psycopg[binary]'（ai-agent-service/.venv 已自带）")
        return 1

    try:
        with psycopg.connect(_dsn("postgres"), autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{DB}"')
            admin.execute(f'CREATE DATABASE "{DB}"')
    except Exception as e:  # noqa: BLE001
        print(f"❌ 无法连接本机 PostgreSQL（{PG_HOST}:{PG_PORT}）: {e}")
        print("   见本脚本文件头「前置」一节起库命令，或用 MIGAO_PG_* 环境变量指定连接。")
        return 1

    # ① bootstrap：等于 docker-entrypoint-initdb.d 的 psql -v ON_ERROR_STOP=1 -f schema.sql
    env = dict(os.environ, PGHOST=PG_HOST, PGPORT=PG_PORT, PGUSER=PG_USER)
    if PG_PASSWORD:
        env["PGPASSWORD"] = PG_PASSWORD
    proc = subprocess.run(
        ["psql", "-v", "ON_ERROR_STOP=1", "-q", "-d", DB, "-f", str(SCHEMA)],
        capture_output=True, text=True, env=env,
    )
    if proc.returncode != 0:
        print(f"❌ schema.sql（bootstrap）应用失败:\n{proc.stderr[:800]}")
        return 1
    print("✅ schema.sql（bootstrap）应用成功")

    with psycopg.connect(_dsn(DB)) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " version VARCHAR(255) PRIMARY KEY,"
            " applied_at TIMESTAMP WITH TIME ZONE DEFAULT NOW())"
        )
        conn.commit()
        if args.rerun:
            conn.execute("DELETE FROM schema_migrations")
            conn.commit()
            print("ℹ️  已清空 schema_migrations，开始全量重跑（幂等性验证）")

        files = sorted((p.name for p in MIG_DIR.glob("*.sql")), key=order_key)
        failed = []
        for name in files:
            sql = (MIG_DIR / name).read_text(encoding="utf-8")
            try:
                with conn.transaction():          # ← 复刻 jdbc.execute(整文件) 的单事务语义
                    conn.execute(sql)
                conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (name,))
                conn.commit()
            except Exception as e:  # noqa: BLE001 — 复刻 MigrationRunner「跳过并继续」
                failed.append(name)
                print(f"❌ 迁移失败（已跳过）: {name}\n     {str(e).strip().splitlines()[0]}")

        applied = conn.execute("SELECT count(*) FROM schema_migrations").fetchone()[0]
        print(f"\n迁移文件 {len(files)} 条 / schema_migrations {applied} 行")
        if failed:
            print(f"❌❌ MigrationRunner 将打印告警：本次有 {len(failed)} 条迁移失败，"
                  f"schema 可能与代码不一致（请立即修复并在修复后重跑）：{failed}")
            return 1
        print("✅ 无迁移失败 —— MigrationRunner 不会打印「schema 可能与代码不一致」告警")
        return 0


if __name__ == "__main__":
    sys.exit(main())
