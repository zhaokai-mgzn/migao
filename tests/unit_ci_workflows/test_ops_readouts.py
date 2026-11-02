# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI/流程结构类 L0 不变式统一挂 MC-012 ——
#   见 .github/cases/misc.yml 的 MC-012「CI workflow 行为由 tests/unit_ci_workflows/ 单测验证」。）
"""P1-07 / P1-11 的**只读读数**：备份窗口 ≥14 天、只增表体量 / 最老行年龄（issue #8197 上线审计）。

## 病（2026-10-31 审计读数，逐字）

| ID | 现取读数 | 后果 |
|---|---|---|
| **P1-07** | `docs/deployment/rollback.md::误删/坏数据` 的恢复路径 = **云控制台人工**；`grep -rn "pg_dump\\|backup" deploy/ .github/workflows/` ⇒ 只有 H5 静态根备份，**无数据库备份代码** | 误删 / 坏数据**不可自助恢复**，而且「备份策略是否 ≥14 天」**没有任何读数**（不可判定 ⇒ 不能算通过） |
| **P1-11** | `deploy/ops/db-retention.sql` 文件头逐字「**人工执行**，不是定时任务」；两张只增表 365 / 180 天保留期；仓内**无任何值守面**（无告警、无读数、无到期提醒） | 表无界增长（索引体积 / 备份窗口 / 查询变慢），且「**没有清理**这件事不会有人知道**」 |

审计给的修法都是「**只读读数**」：**不新增无人值守删除**（铁律 10），只把「取不到数」和
「超限」变成一条能跑的读数（三态 `0/1/3`）。本文件锁七件事（每条都能单独变红）：

| # | 断言 | 变红形态 |
|---|---|---|
| 1 | `scripts/rds_backup_window_readout.py` 三态语义：`≥14 天` ⇒ `0`、`<14 天` ⇒ `1`、**取不到 ⇒ `3`** | 缺 `MIGAO_RDS_INSTANCE_ID` 却返回 `0`（假绿）；CLI 报错被读成通过 |
| 2 | `scripts/db_growth_readout.py` 三态语义 + 阈值：超最老行年龄 / 超体量 ⇒ `1`，**读不到表 / 解析不了 ⇒ `3`** | 空结果当通过（`DQ-U` 同族）；超限只打印不改退出码 |
| 3 | `deploy/ops/db-growth-readout.sql` **只有 SELECT**（无 DELETE / UPDATE / TRUNCATE / DROP / ALTER / CREATE / VACUUM …），且覆盖两张表 | 有人把「读数」写成删除入口 ⇒ 红（铁律 10 的对象正是无人值守删除） |
| 4 | 读数**落进人读的文档**：`docs/deployment/rollback.md` §4（P1-07）+ `docs/deployment/production-deployment.md` §5.3（P1-11）各带读数来源 / 命令 / 阈值 / 值班步骤 / 告警口径 | 删掉任一段 ⇒ 红（`docs/testing/` 与 `deploy/` 里的读数不许只活在本文件） |
| 5 | **文档声明的环境变量必须真被脚本读取**（`声明存在 ≠ 可达`，铁律 11） | 文档写 `MIGAO_RDS_INSTANCE_ID` / `DATABASE_URL` 而脚本不读 ⇒ 红 |
| 6 | **恢复演练记录列为待补**（P1-07 的用户云侧事项，`有意不做` 不许被读成 `已解决`） | 删掉「待补（用户云侧）」标记 ⇒ 红；把它写成「已完成」⇒ 红 |
| 7 | 判别力自证（注入式红证）+ 负控（只加无关注释 ⇒ 不红） | 判据退化成恒绿 ⇒ 红 |

## 只读与零网络（为什么判据本身不联网、不连库）

读数器的**运行期**取值（`aliyun rds DescribeBackupPolicy` / `psql`）不在 CI 里跑 —— 那会让 PR 取决于
云凭据与生产状态，等于把「能不能合并」交给外部环境。判据的做法是：
**替身可执行文件**（`tmp_path` 里造一个 `aliyun` / `psql`，`PATH` 指过去）+ 离线快照
（`--from-json` / `--from-csv`）⇒ 判定**逻辑**（三态、阈值、解析），零网络、零真库、确定性。

## 覆盖面（照实登记，§19.1）

- 判不了「云侧保留时长**今天**真的 ≥14 天」—— 那是运行期读数，由值班按
  `docs/deployment/rollback.md` §4 的复查步骤取数并留痕；本判据只保证「取不到就红」。
- 判不了「值班有没有按时复查」；两条读数的**触达面**仍是「人去跑」（铁律 10：不新增 schedule）。
- 判不了 SQL 在真库上的**语义**（列名 / schema 差异）—— 只判它是只读的、且覆盖两张表；
  真库语法与命中行数的取证口径见 `docs/testing/production-readonly-verification-pack.md`（同一套做法）。
- `restore_drill`（恢复演练记录）仍是**待补**：它是用户云侧动作，本包只登记，不伪造读数。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BACKUP_SCRIPT = REPO / "scripts" / "rds_backup_window_readout.py"
GROWTH_SCRIPT = REPO / "scripts" / "db_growth_readout.py"
GROWTH_SQL = REPO / "deploy" / "ops" / "db-growth-readout.sql"
ROLLBACK_DOC = REPO / "docs" / "deployment" / "rollback.md"
PROD_DOC = REPO / "docs" / "deployment" / "production-deployment.md"

#: P1-07：rollback.md 里必须有的锚（读数来源 / 命令 / 阈值 / 值班步骤 / 待补）
BACKUP_DOC_MARKERS = (
    "云数据库 RDS",
    "备份恢复 → 备份策略",
    "DescribeBackupPolicy",
    "scripts/rds_backup_window_readout.py",
    "MIGAO_RDS_INSTANCE_ID",
    "retention_days",
    "≥14 天",
    "值班复查",
    "无法判定",
    "恢复演练记录",
    "待补",
    "用户云侧",
    "tests/unit_ci_workflows/test_ops_readouts.py",
)
#: P1-11：production-deployment.md §5.3 里必须有的锚（读数 / 阈值 / 告警口径 / 人工执行）
GROWTH_DOC_MARKERS = (
    "deploy/ops/db-growth-readout.sql",
    "scripts/db_growth_readout.py",
    "DATABASE_URL",
    "oldest_age_days",
    "total_bytes",
    "365",
    "180",
    "512 MiB",
    "告警口径",
    "无法判定",
    "人工执行",
    "铁律 10",
    "tests/unit_ci_workflows/test_ops_readouts.py",
)
#: 只读面：SQL 里**不许**出现的写 / DDL 动词（读数器一律只 SELECT）
WRITE_VERBS = (
    "INSERT",
    "UPDATE",
    "DELETE",
    "TRUNCATE",
    "DROP",
    "ALTER",
    "CREATE",
    "GRANT",
    "REVOKE",
    "VACUUM",
    "REINDEX",
    "CLUSTER",
    "COMMENT",
)
_MIGAO_ENV_RE = re.compile(r"\bMIGAO_[A-Z0-9_]+\b")


# ══════════════════════════════════════════════════════════════════════════
# 纯函数判据（注入式红证直接喂变异文本）
# ══════════════════════════════════════════════════════════════════════════


def strip_sql_comments(text: str) -> str:
    """剥 `--` 行注释与 `/* … */` 块注释（只判**可执行面**，不吃自己的说明文字）。"""
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"--[^\n]*", " ", text)


def sql_write_problems(sql_text: str) -> list[str]:
    v: list[str] = []
    body = strip_sql_comments(sql_text).upper()
    lower = body.lower()
    for verb in WRITE_VERBS:
        if re.search(rf"(?<![A-Z_]){verb}(?![A-Z_])", body):
            v.append(
                f"deploy/ops/db-growth-readout.sql 的可执行面里出现了 `{verb}` ⇒ "
                "只读读数不许含写 / DDL（删除仍是人工执行 deploy/ops/db-retention.sql，铁律 10）"
            )
    if "SELECT" not in body:
        v.append("deploy/ops/db-growth-readout.sql 里没有 `SELECT`（读数器退化成空文件）")
    for table in ("audit_logs", "notifications"):
        if table not in lower:
            v.append(f"deploy/ops/db-growth-readout.sql 没有覆盖表 `{table}`（两张只增表都必须有读数）")
    for token in ("pg_total_relation_size", "min(created_at)"):
        if token not in lower:
            v.append(f"deploy/ops/db-growth-readout.sql 缺读数表达式 `{token}`（体量 / 最老行年龄必须各有一列）")
    return v


def script_write_problems(script_text: str, name: str) -> list[str]:
    v: list[str] = []
    body = script_text.upper()
    for verb in ("DELETE", "TRUNCATE", "DROP TABLE", "UPDATE ", "INSERT INTO"):
        if verb in body:
            v.append(f"`{name}` 里出现了写 SQL 动词 `{verb.strip()}` ⇒ 读数器必须只读（不看写面）")
    return v


def doc_markers_problems(doc_text: str, markers: tuple[str, ...], label: str) -> list[str]:
    return [f"{label} 里缺少锚 `{marker}`（读数/阈值/值班步骤不许只活在脚本里）" for marker in markers if marker not in doc_text]


def env_contract_problems(script_text: str, env_var: str, label: str) -> list[str]:
    """文档声明的环境变量必须**真被脚本读取**（声明存在 ≠ 可达）。"""
    if env_var in script_text:
        return []
    return [f"{label} 的文档要求环境变量 `{env_var}`，但脚本里根本没有它 ⇒ 声明与实现分叉（缺变量时不会真的 rc=3）"]


def pending_restore_drill_problems(doc_text: str) -> list[str]:
    """P1-07 的恢复演练记录仍是**待补**：既不许消失，也不许被写成已完成。"""
    v: list[str] = []
    if "恢复演练记录" not in doc_text:
        v.append("rollback.md 里没有「恢复演练记录」这一项 ⇒ 未取证的云侧事项被静默抹掉了")
    for claim in ("恢复演练已完成", "演练已通过", "restore drill passed"):
        if claim in doc_text:
            v.append(f"rollback.md 声称「{claim}」—— 恢复演练是用户云侧动作，本仓无读数，不许写成就绪")
    return v


# ══════════════════════════════════════════════════════════════════════════
# 运行辅助（零网络：替身可执行文件 + 离线快照）
# ══════════════════════════════════════════════════════════════════════════


def _script_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """剥掉本机可能存在的云 / 库变量（否则「缺环境变量」测的就是开发机的运气）。"""
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("MIGAO_") and k not in ("DATABASE_URL", "PGURL", "PGHOST")
    }
    env.setdefault("PATH", os.defpath)
    env["PYTHONIOENCODING"] = "utf-8"
    if extra:
        env.update(extra)
    return env


def _fake_bin(directory: Path, name: str, body: str) -> Path:
    path = directory / name
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)
    return path


def _run(script: Path, args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    assert script.is_file(), f"读数脚本不存在：{script}（这是本判据要守的对象）"
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO),
        timeout=120,
    )


def _out(proc: subprocess.CompletedProcess[str]) -> str:
    return proc.stdout + proc.stderr


def _write_rows(path: Path, rows: list[dict[str, object]]) -> Path:
    """把读数行写成 `psql --csv` 形态（列序固定）。"""
    cols = ("table_name", "total_bytes", "row_count", "oldest_created_at", "oldest_age_days")
    lines = [",".join(cols)]
    for row in rows:
        lines.append(",".join(str(row.get(col, "")) for col in cols))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


GOOD_ROWS = [
    {"table_name": "audit_logs", "total_bytes": 1048576, "row_count": 100,
     "oldest_created_at": "2025-11-01T00:00:00Z", "oldest_age_days": 364.0},
    {"table_name": "notifications", "total_bytes": 524288, "row_count": 42,
     "oldest_created_at": "2026-06-01T00:00:00Z", "oldest_age_days": 120.0},
]


# ══════════════════════════════════════════════════════════════════════════
# P1-07：RDS 备份窗口读数（三态）
# ══════════════════════════════════════════════════════════════════════════


def test_backup_readout_without_env_is_undecidable(tmp_path: Path):
    """环境变量缺失 ⇒ rc=3「无法判定」，**不得**绿（审计原文：不可判定 ⇒ 不能算通过）。"""
    proc = _run(BACKUP_SCRIPT, [], _script_env({"PATH": f"{tmp_path}:/usr/bin:/bin", "HOME": str(tmp_path)}))
    out = _out(proc)
    assert proc.returncode == 3, f"缺 MIGAO_RDS_INSTANCE_ID 时退出码应为 3（无法判定），实测 {proc.returncode}：\n{out}"
    assert "MIGAO_RDS_INSTANCE_ID" in out, f"未点名缺的那个环境变量：\n{out}"
    assert "无法判定" in out, f"未输出「无法判定」字样：\n{out}"


def test_backup_readout_snapshot_meets_floor(tmp_path: Path):
    """≥14 天 ⇒ rc=0，且读数（retention_days）必须打在输出里（只有 rc 没有读数 = 无法复核）。"""
    snap = tmp_path / "policy.json"
    snap.write_text(json.dumps({"BackupRetentionPeriod": 30, "PreferredBackupPeriod": "Monday,Tuesday"}),
                    encoding="utf-8")
    proc = _run(BACKUP_SCRIPT, ["--from-json", str(snap)],
                _script_env({"PATH": f"{tmp_path}:/usr/bin:/bin", "HOME": str(tmp_path)}))
    out = _out(proc)
    assert proc.returncode == 0, f"30 天 ≥ 14 天应为 0，实测 {proc.returncode}：\n{out}"
    assert "retention_days=30" in out and "verdict=ok" in out, f"读数/结论未落进输出：\n{out}"


def test_backup_readout_snapshot_below_floor_is_red(tmp_path: Path):
    """<14 天 ⇒ rc=1（备份窗口覆盖不了「发现误删 → 定位 → 恢复」的窗口）。"""
    snap = tmp_path / "policy.json"
    snap.write_text(json.dumps({"BackupRetentionPeriod": 7}), encoding="utf-8")
    proc = _run(BACKUP_SCRIPT, ["--from-json", str(snap)],
                _script_env({"PATH": f"{tmp_path}:/usr/bin:/bin", "HOME": str(tmp_path)}))
    out = _out(proc)
    assert proc.returncode == 1, f"7 天 < 14 天应为 1，实测 {proc.returncode}：\n{out}"
    assert "retention_days=7" in out and "verdict=short" in out, f"读数/结论未落进输出：\n{out}"


def test_backup_readout_live_cli_path(tmp_path: Path):
    """真路径（替身 `aliyun`）：只读 API 的返回被解析成读数。"""
    _fake_bin(tmp_path, "aliyun", '#!/bin/sh\ncat <<\'EOF\'\n{"BackupRetentionPeriod": 21}\nEOF\n')
    proc = _run(BACKUP_SCRIPT, [],
                _script_env({"PATH": f"{tmp_path}:/usr/bin:/bin", "HOME": str(tmp_path),
                             "MIGAO_RDS_INSTANCE_ID": "rm-test-instance"}))
    out = _out(proc)
    assert proc.returncode == 0, f"替身 CLI 返回 21 天应为 0，实测 {proc.returncode}：\n{out}"
    assert "source=cli" in out and "retention_days=21" in out, f"未标出读数来源（无法复核是哪一面给的数）：\n{out}"


def test_backup_readout_cli_error_is_undecidable(tmp_path: Path):
    """CLI 报错（凭据 / 网络 / 权限）⇒ rc=3，**不得**当通过、也不得当成「备份窗口不够」。"""
    _fake_bin(tmp_path, "aliyun", '#!/bin/sh\necho "ERROR: Forbidden.RAM" >&2\nexit 1\n')
    proc = _run(BACKUP_SCRIPT, [],
                _script_env({"PATH": f"{tmp_path}:/usr/bin:/bin", "HOME": str(tmp_path),
                             "MIGAO_RDS_INSTANCE_ID": "rm-test-instance"}))
    out = _out(proc)
    assert proc.returncode == 3, f"CLI 失败应为 3（无法判定），实测 {proc.returncode}：\n{out}"
    assert "verdict=undecidable" in out, f"未标出「无法判定」：\n{out}"


def test_backup_readout_unparsable_snapshot_is_undecidable(tmp_path: Path):
    """快照里没有保留时长字段 ⇒ rc=3（缺值不是「0 天」）。"""
    snap = tmp_path / "policy.json"
    snap.write_text(json.dumps({"RequestId": "x"}), encoding="utf-8")
    proc = _run(BACKUP_SCRIPT, ["--from-json", str(snap)],
                _script_env({"PATH": f"{tmp_path}:/usr/bin:/bin", "HOME": str(tmp_path)}))
    assert proc.returncode == 3, f"字段缺失应为 3，实测 {proc.returncode}：\n{_out(proc)}"


# ══════════════════════════════════════════════════════════════════════════
# P1-11：只增表体量 / 最老行年龄读数（三态 + 阈值）
# ══════════════════════════════════════════════════════════════════════════


def test_growth_readout_without_env_is_undecidable(tmp_path: Path):
    proc = _run(GROWTH_SCRIPT, [], _script_env({"PATH": f"{tmp_path}:/usr/bin:/bin", "HOME": str(tmp_path)}))
    out = _out(proc)
    assert proc.returncode == 3, f"缺 DATABASE_URL 时退出码应为 3（无法判定），实测 {proc.returncode}：\n{out}"
    assert "DATABASE_URL" in out and "无法判定" in out, f"未点名缺的变量 / 未标「无法判定」：\n{out}"


def test_growth_readout_within_thresholds(tmp_path: Path):
    csv_path = _write_rows(tmp_path / "growth.csv", GOOD_ROWS)
    proc = _run(GROWTH_SCRIPT, ["--from-csv", str(csv_path)],
                _script_env({"PATH": f"{tmp_path}:/usr/bin:/bin", "HOME": str(tmp_path)}))
    out = _out(proc)
    assert proc.returncode == 0, f"两条都在保留期内应为 0，实测 {proc.returncode}：\n{out}"
    assert "audit_logs" in out and "notifications" in out, f"两张表都必须有读数行：\n{out}"
    assert "verdict=ok" in out, f"结论未落进输出：\n{out}"


def test_growth_readout_over_age_is_flagged(tmp_path: Path):
    rows = [dict(GOOD_ROWS[0], oldest_age_days=400.0), GOOD_ROWS[1]]
    csv_path = _write_rows(tmp_path / "growth.csv", rows)
    proc = _run(GROWTH_SCRIPT, ["--from-csv", str(csv_path)],
                _script_env({"PATH": f"{tmp_path}:/usr/bin:/bin", "HOME": str(tmp_path)}))
    out = _out(proc)
    assert proc.returncode == 1, f"audit_logs 最老行 400 天 > 365 应为 1，实测 {proc.returncode}：\n{out}"
    assert "verdict=over-age" in out and "audit_logs" in out, f"未点名超期表：\n{out}"


def test_growth_readout_over_bytes_is_flagged(tmp_path: Path):
    rows = [GOOD_ROWS[0], dict(GOOD_ROWS[1], total_bytes=1024 * 1024 * 1024)]
    csv_path = _write_rows(tmp_path / "growth.csv", rows)
    proc = _run(GROWTH_SCRIPT, ["--from-csv", str(csv_path)],
                _script_env({"PATH": f"{tmp_path}:/usr/bin:/bin", "HOME": str(tmp_path)}))
    out = _out(proc)
    assert proc.returncode == 1, f"notifications 1 GiB > 512 MiB 应为 1，实测 {proc.returncode}：\n{out}"
    assert "verdict=over-size" in out and "notifications" in out, f"未点名超体量表：\n{out}"


def test_growth_readout_missing_table_is_undecidable(tmp_path: Path):
    """**读不到 ≠ 通过**（`DQ-U` 同族）：少一张表 ⇒ rc=3，不是 rc=0。"""
    csv_path = _write_rows(tmp_path / "growth.csv", [GOOD_ROWS[1]])
    proc = _run(GROWTH_SCRIPT, ["--from-csv", str(csv_path)],
                _script_env({"PATH": f"{tmp_path}:/usr/bin:/bin", "HOME": str(tmp_path)}))
    out = _out(proc)
    assert proc.returncode == 3, f"缺 audit_logs 读数应为 3（无法判定），实测 {proc.returncode}：\n{out}"
    assert "audit_logs" in out, f"未点名缺的那张表：\n{out}"


def test_growth_readout_live_psql_path(tmp_path: Path):
    """真路径（替身 `psql`）：只读 SQL 的输出被解析成读数，且 psql 被要求 `ON_ERROR_STOP=1`。"""
    csv_text = _write_rows(tmp_path / "rows.csv", GOOD_ROWS).read_text(encoding="utf-8")
    _fake_bin(tmp_path, "psql",
              "#!/bin/sh\n"
              "for a in \"$@\"; do\n"
              "  [ \"$a\" = \"ON_ERROR_STOP=1\" ] && echo '-v ON_ERROR_STOP=1' >&2\n"
              "done\n"
              f"cat <<'EOF'\n{csv_text}EOF\n")
    proc = _run(GROWTH_SCRIPT, [],
                _script_env({"PATH": f"{tmp_path}:/usr/bin:/bin", "HOME": str(tmp_path),
                             "DATABASE_URL": "postgresql://readonly@example/db"}))
    out = _out(proc)
    assert proc.returncode == 0, f"替身 psql 返回正常读数为 0，实测 {proc.returncode}：\n{out}"
    assert "source=psql" in out, f"未标出读数来源：\n{out}"
    assert "ON_ERROR_STOP=1" in out, f"调用 psql 时必须要求 ON_ERROR_STOP=1（否则错语句会被静默跳过）：\n{out}"


def test_growth_readout_psql_failure_is_undecidable(tmp_path: Path):
    _fake_bin(tmp_path, "psql", '#!/bin/sh\necho "psql: error: connection refused" >&2\nexit 2\n')
    proc = _run(GROWTH_SCRIPT, [],
                _script_env({"PATH": f"{tmp_path}:/usr/bin:/bin", "HOME": str(tmp_path),
                             "DATABASE_URL": "postgresql://readonly@example/db"}))
    out = _out(proc)
    assert proc.returncode == 3, f"psql 失败应为 3（无法判定），实测 {proc.returncode}：\n{out}"
    assert "verdict=undecidable" in out, f"未标出「无法判定」：\n{out}"


def test_growth_readout_unparsable_csv_is_undecidable(tmp_path: Path):
    csv_path = tmp_path / "growth.csv"
    csv_path.write_text("this is not,csv\nat all\n", encoding="utf-8")
    proc = _run(GROWTH_SCRIPT, ["--from-csv", str(csv_path)],
                _script_env({"PATH": f"{tmp_path}:/usr/bin:/bin", "HOME": str(tmp_path)}))
    assert proc.returncode == 3, f"解析不了应为 3，实测 {proc.returncode}：\n{_out(proc)}"


# ══════════════════════════════════════════════════════════════════════════
# 只读性 / 文档接线 / 声明 ⇄ 实现
# ══════════════════════════════════════════════════════════════════════════


def test_growth_sql_is_read_only():
    v = sql_write_problems(GROWTH_SQL.read_text(encoding="utf-8"))
    assert not v, "只读读数 SQL 未通过：\n- " + "\n- ".join(v)


def test_readout_scripts_contain_no_write_sql():
    v = script_write_problems(BACKUP_SCRIPT.read_text(encoding="utf-8"), "rds_backup_window_readout.py")
    v += script_write_problems(GROWTH_SCRIPT.read_text(encoding="utf-8"), "db_growth_readout.py")
    assert not v, "读数脚本里出现写 SQL：\n- " + "\n- ".join(v)


def test_docs_register_readouts():
    v = doc_markers_problems(ROLLBACK_DOC.read_text(encoding="utf-8"), BACKUP_DOC_MARKERS,
                             "docs/deployment/rollback.md（P1-07）")
    v += doc_markers_problems(PROD_DOC.read_text(encoding="utf-8"), GROWTH_DOC_MARKERS,
                              "docs/deployment/production-deployment.md（P1-11）")
    assert not v, "读数未落进文档：\n- " + "\n- ".join(v)


def test_doc_env_vars_are_really_read():
    """判据 5：文档声明的环境变量必须真被脚本读取（声明存在 ≠ 可达）。"""
    v = env_contract_problems(BACKUP_SCRIPT.read_text(encoding="utf-8"), "MIGAO_RDS_INSTANCE_ID",
                              "scripts/rds_backup_window_readout.py")
    v += env_contract_problems(GROWTH_SCRIPT.read_text(encoding="utf-8"), "DATABASE_URL",
                               "scripts/db_growth_readout.py")
    assert not v, "文档声明的环境变量与实现分叉：\n- " + "\n- ".join(v)


def test_doc_thresholds_match_script_defaults():
    """期望阈值是**真值源**：文档写的 14 天 / 365 / 180 / 512 MiB 必须与脚本默认值一致。"""
    backup = BACKUP_SCRIPT.read_text(encoding="utf-8")
    growth = GROWTH_SCRIPT.read_text(encoding="utf-8")
    v: list[str] = []
    if "DEFAULT_MIN_DAYS = 14" not in backup:
        v.append("rds_backup_window_readout.py 的默认下限不是 14 天（`DEFAULT_MIN_DAYS = 14`）")
    for token in ('"audit_logs": 365', '"notifications": 180'):
        if token not in growth:
            v.append(f"db_growth_readout.py 的默认保留期缺 `{token}`")
    if "512 * 1024 * 1024" not in growth:
        v.append("db_growth_readout.py 的默认体量阈值不是 512 MiB（`512 * 1024 * 1024`）")
    assert not v, "阈值与文档口径不一致：\n- " + "\n- ".join(v)


def test_restore_drill_is_registered_as_pending():
    """判据 6：恢复演练记录列为**待补（用户云侧）** —— 「有意不做」不许被读成「已解决」。"""
    v = pending_restore_drill_problems(ROLLBACK_DOC.read_text(encoding="utf-8"))
    assert not v, "恢复演练记录未正确登记为待补：\n- " + "\n- ".join(v)


# ══════════════════════════════════════════════════════════════════════════
# 注入式红证 + 负控
# ══════════════════════════════════════════════════════════════════════════


def test_injection_missing_backup_command_is_caught():
    doc = ROLLBACK_DOC.read_text(encoding="utf-8")
    needle = "scripts/rds_backup_window_readout.py"
    assert needle in doc, f"注入点定位失败：rollback.md 里本来就没有 `{needle}`"
    mutated = doc.replace(needle, "（读数器名称略）")  # 全文替换：只替一处时另一处仍会命中锚
    assert needle not in mutated, "变异未生效"
    v = doc_markers_problems(mutated, BACKUP_DOC_MARKERS, "rollback")
    assert any("读数器名称略" in x or needle in x for x in v), v


def test_injection_relaxed_backup_floor_is_caught():
    doc = ROLLBACK_DOC.read_text(encoding="utf-8")
    mutated = doc.replace("≥14 天", "≥7 天")
    assert "≥14 天" not in mutated, "变异未生效（文档里本来就没有 `≥14 天`）"
    v = doc_markers_problems(mutated, BACKUP_DOC_MARKERS, "rollback")
    assert any("≥14 天" in x for x in v), v


def test_injection_write_verb_in_growth_sql_is_caught():
    sql = GROWTH_SQL.read_text(encoding="utf-8")
    mutated = sql + "\nDELETE FROM audit_logs WHERE created_at < now() - interval '400 days';\n"
    v = sql_write_problems(mutated)
    assert any("DELETE" in x and "只读" in x for x in v), v


def test_injection_script_env_divergence_is_caught():
    script = BACKUP_SCRIPT.read_text(encoding="utf-8")
    mutated = script.replace("MIGAO_RDS_INSTANCE_ID", "SOME_OTHER_VAR")
    assert mutated != script, "变异未生效"
    v = env_contract_problems(mutated, "MIGAO_RDS_INSTANCE_ID", "script")
    assert any("MIGAO_RDS_INSTANCE_ID" in x for x in v), v


def test_injection_fake_completion_of_restore_drill_is_caught():
    doc = ROLLBACK_DOC.read_text(encoding="utf-8") + "\n恢复演练已完成。\n"
    v = pending_restore_drill_problems(doc)
    assert any("恢复演练已完成" in x for x in v), v


def test_negative_control_unrelated_doc_line_stays_green():
    """负控：只加一句无关说明 ⇒ 判据必须保持绿（不许被自己的文案喂红）。"""
    v = doc_markers_problems(ROLLBACK_DOC.read_text(encoding="utf-8") + "\n（负控：这句与本判据无关）\n",
                             BACKUP_DOC_MARKERS, "rollback")
    assert not v, "无关注释不该判红：\n- " + "\n- ".join(v)
