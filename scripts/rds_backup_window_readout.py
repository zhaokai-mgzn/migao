#!/usr/bin/env python3
"""RDS 备份窗口**只读读数**（issue #8197 上线审计 P1-07）。

## 病（2026-10-31 审计读数，逐字）

- **C**：`docs/deployment/rollback.md::数据回滚` 的恢复路径 = **云控制台人工**
  （「RDS 自动备份恢复 … 恢复前确认备份策略 ≥14 天」）；
- **C**：`grep -rn "pg_dump\\|backup" deploy/ .github/workflows/` ⇒ 只有 H5 静态根备份，**无数据库备份代码**；
- ⇒ 误删 / 坏数据**不可自助恢复**，而且「备份策略是否 ≥14 天」**没有任何读数**
  （不可判定 ⇒ 不能算通过；`migao-acceptance`：不会红的断言 = 空断言）。

修法（审计给的）= **只读读数**：把「保留时长到底几天」变成一条能跑、能判三态的命令，
**不新增无人值守动作**（铁律 10），也不碰任何云侧配置（改保留时长是人的动作）。

## 读数从哪里来（两条面，本脚本都给）

| 面 | 命令 | 性质 |
|---|---|---|
| **CLI（默认）** | `aliyun rds DescribeBackupPolicy --DBInstanceId <id>` | **Describe 类 = 只读 API**，不修改任何配置 |
| **离线快照** | `--from-json <file>`（把上面那条命令的输出存成文件） | 零网络，便于复核 / 复盘 / 交接 |

控制台等价路径（拿不到 CLI 时用它）：阿里云控制台 → 云数据库 RDS → 实例 → 备份恢复 → 备份策略 →
「保留时长」。两条面取到的 `BackupRetentionPeriod`（天）是同一个值。

## 判据（三态，`3` **不得**当 `0` 读）

| rc | 含义 | 处置 |
|---|---|---|
| `0` | `retention_days ≥ --min-days`（默认 **14**） | 把 `retention_days` 写进当班记录 |
| `1` | `retention_days < 14` | **当班开单**：在云控制台把保留时长调到 ≥14 天（云侧动作，本脚本不改） |
| `3` | **无法判定**：缺 `MIGAO_RDS_INSTANCE_ID` / 找不到 `aliyun` CLI / 凭据或网络失败 / 返回不是合法 JSON / 缺保留时长字段 | 先修取数面，**不许**把它读成通过，也不许读成「窗口不够」 |

## 环境变量

| 变量 | 必需 | 说明 |
|---|---|---|
| `MIGAO_RDS_INSTANCE_ID` | 是（CLI 面） | RDS 实例 id（`rm-…`）；缺失 ⇒ `rc=3` |
| `MIGAO_ALIYUN_BIN` | 否 | `aliyun` 可执行文件的路径 / 名字（默认 `aliyun`，走 `PATH`） |
| `ALIBABA_CLOUD_ACCESS_KEY_ID` / `ALIBABA_CLOUD_ACCESS_KEY_SECRET` | 否 | `aliyun` CLI 自己的凭据面（本脚本不读、不打印；建议只读 RAM 用户） |

## 用法（仓根）

    # ① 正常读数（需要实例 id + 已配置的 aliyun CLI）
    MIGAO_RDS_INSTANCE_ID=rm-xxxx python3 scripts/rds_backup_window_readout.py

    # ② 离线复核（把上一次 API 响应存成文件，随时复算）
    aliyun rds DescribeBackupPolicy --DBInstanceId rm-xxxx > /tmp/rds-backup-policy.json
    python3 scripts/rds_backup_window_readout.py --from-json /tmp/rds-backup-policy.json

    # ③ 想换下限（默认 14 天）
    python3 scripts/rds_backup_window_readout.py --min-days 14

## 边界（照实登记，§19.1）

- **只读**：只用 `Describe*` 类 API；本脚本不写任何云侧配置、不落盘。
- 它证明的是「**这个实例的备份保留时长读数是多少**」；**不**证明「备份真的能恢复」
  —— 恢复演练记录是用户云侧动作，登记在 `docs/deployment/rollback.md` 的 §4（待补）。
- 不判「PITR 是否开启」（那是 `DescribeBackupPolicy` 的另一字段，属独立的取证面）。
- 判据 = `tests/unit_ci_workflows/test_ops_readouts.py`（替身 `aliyun` + 离线快照，零网络）。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

#: 实例 id（必需；缺失 ⇒ rc=3，不许绿）
ENV_INSTANCE_ID = "MIGAO_RDS_INSTANCE_ID"
#: `aliyun` 可执行文件覆盖（默认走 PATH）
ENV_ALIYUN_BIN = "MIGAO_ALIYUN_BIN"
#: 下限：备份窗口 ≥14 天（runbook 的原始口径；PITR 回滚点要覆盖「发现误删 → 定位 → 恢复」的窗口）
DEFAULT_MIN_DAYS = 14

RC_OK = 0
RC_SHORT = 1
RC_UNDECIDABLE = 3

#: 只读 API（Describe* 一族）
API = "DescribeBackupPolicy"
#: 保留时长的字段名（阿里云返回 `BackupRetentionPeriod`，单位 = 天；兼容小写驼峰）
RETENTION_KEYS = ("BackupRetentionPeriod", "backupRetentionPeriod")
#: 单次 API 调用的上限（避免读数把值班卡住）
TIMEOUT_SECONDS = 60


def find_retention_days(payload: Any) -> int | None:
    """→ 保留时长（天）；取不到 ⇒ ``None``（**缺值不是 0 天**，不许塌成「窗口不够」）。"""
    found: list[Any] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if str(key) in RETENTION_KEYS:
                    found.append(value)
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    for raw in found:
        try:
            days = int(str(raw).strip())
        except (TypeError, ValueError):
            continue
        if days > 0:
            return days
    return None


def _undecidable(source: str, why: str) -> int:
    """无法判定：**出声**（stdout 一行机器可读 + stderr 一句人话），并返回 rc=3。"""
    print(f"RDS-BACKUP-READOUT source={source} verdict=undecidable why={why}")
    print(f"无法判定（rc={RC_UNDECIDABLE}）：{why} —— 3 一律不得当 0 读", file=sys.stderr)
    return RC_UNDECIDABLE


def _read_snapshot(path: str) -> tuple[Any, str]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8")), ""
    except OSError as exc:
        return None, f"读不到快照文件 {path}：{exc}"
    except json.JSONDecodeError as exc:
        return None, f"快照不是合法 JSON（{path}）：{exc}"


def _fetch_policy(binary: str, instance_id: str) -> tuple[Any, str]:
    cmd = [binary, "rds", API, "--DBInstanceId", instance_id]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"调用 {binary} 失败：{exc}"
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        return None, f"{binary} rds {API} 退出码 {proc.returncode}：{detail[-1] if detail else '(无输出)'}"
    try:
        return json.loads(proc.stdout), ""
    except json.JSONDecodeError as exc:
        return None, f"{API} 的返回不是合法 JSON：{exc}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="RDS 备份窗口只读读数（P1-07；三态 0/1/3）")
    parser.add_argument("--from-json", default="", help="离线复核：喂 aliyun DescribeBackupPolicy 的响应文件")
    parser.add_argument("--min-days", type=int, default=DEFAULT_MIN_DAYS, help=f"下限（默认 {DEFAULT_MIN_DAYS} 天）")
    parser.add_argument("--instance-id", default="", help=f"RDS 实例 id（默认取环境变量 {ENV_INSTANCE_ID}）")
    parser.add_argument("--aliyun-bin", default="", help=f"aliyun 可执行文件（默认取 {ENV_ALIYUN_BIN} 或 PATH 上的 aliyun）")
    args = parser.parse_args(argv)

    instance_id = (args.instance_id or os.environ.get(ENV_INSTANCE_ID, "")).strip()
    source = "snapshot" if args.from_json else "cli"

    if args.from_json:
        payload, why = _read_snapshot(args.from_json)
        if payload is None:
            return _undecidable(source, why)
    else:
        if not instance_id:
            return _undecidable(source, f"缺环境变量 {ENV_INSTANCE_ID}（实例 id 是读数的必需入参）")
        binary = (args.aliyun_bin or os.environ.get(ENV_ALIYUN_BIN, "") or "aliyun").strip()
        if shutil.which(binary) is None:
            return _undecidable(source, f"找不到 {binary}（aliyun CLI 未安装 / PATH 不含它）")
        payload, why = _fetch_policy(binary, instance_id)
        if payload is None:
            return _undecidable(source, why)

    days = find_retention_days(payload)
    if days is None:
        return _undecidable(source, "读数里没有保留时长字段（BackupRetentionPeriod）—— 缺值不是 0 天")

    verdict = "ok" if days >= args.min_days else "short"
    print(
        f"RDS-BACKUP-READOUT source={source} instance={instance_id or '-'} "
        f"retention_days={days} min_days={args.min_days} verdict={verdict}"
    )
    if verdict == "short":
        print(
            f"  ⇒ 备份窗口只有 {days} 天 < 下限 {args.min_days} 天：覆盖不了「发现误删 → 定位 → 恢复」的窗口。"
            "处置 = 在云控制台把保留时长调到 ≥14 天（云侧动作，本脚本不改配置）"
        )
        return RC_SHORT
    print("  ⇒ 备份窗口满足下限；读数来源与值班复查步骤见 docs/deployment/rollback.md 的 §4")
    return RC_OK


if __name__ == "__main__":  # pragma: no cover - CLI 入口
    raise SystemExit(main())
