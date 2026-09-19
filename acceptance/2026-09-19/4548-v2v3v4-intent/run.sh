#!/usr/bin/env bash
# issue #4548 真库只读取值分布核对（V3/V4 意图是否已生效）。
# 凭据来源与 acceptance/2026-09-18/4299-db-distribution/run.sh 同源：backend/admin-api/.env
# 只读：脚本只跑 SELECT。凭据不写入任何产物。
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
MAIN_WT="$(dirname "$(git -C "$REPO" rev-parse --path-format=absolute --git-common-dir)")"
ENV_FILE="${MIGAO_ADMIN_ENV:-$REPO/backend/admin-api/.env}"
[ -f "$ENV_FILE" ] || ENV_FILE="$MAIN_WT/backend/admin-api/.env"
[ -f "$ENV_FILE" ] || { echo "找不到 admin-api/.env" >&2; exit 1; }
set -a; . "$ENV_FILE"; set +a
export PGPASSWORD="$RDS_PASSWORD"
export PGSSLMODE="${PGSSLMODE:-prefer}"
psql -h "$RDS_HOST" -p "$RDS_PORT" -U "$RDS_USER" -d "$RDS_DB" -v ON_ERROR_STOP=1 -f "$HERE/recon.sql"
