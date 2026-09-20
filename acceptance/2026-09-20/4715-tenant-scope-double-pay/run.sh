#!/usr/bin/env bash
# issue #4715 真库核实 —— 只读运行器（复跑入口）。纯 SELECT，无写操作。
# 凭据来源：backend/admin-api/.env（与本机 admin-api 同源）。凭据**不写入任何产物**。
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
MAIN_WT="$(dirname "$(git -C "$REPO" rev-parse --path-format=absolute --git-common-dir)")"
ENV_FILE="${MIGAO_ADMIN_ENV:-$REPO/backend/admin-api/.env}"
[ -f "$ENV_FILE" ] || ENV_FILE="$MAIN_WT/backend/admin-api/.env"
[ -f "$ENV_FILE" ] || { echo "找不到 admin-api/.env" >&2; exit 1; }
set -a; . "$ENV_FILE"; set +a
export PGPASSWORD="$RDS_PASSWORD"; export PGSSLMODE="${PGSSLMODE:-prefer}"
psql -h "$RDS_HOST" -p "$RDS_PORT" -U "$RDS_USER" -d "$RDS_DB" -v ON_ERROR_STOP=1 -f "$HERE/recon.sql"
