#!/usr/bin/env bash
# issue #4777 真库核实 —— 只读运行器（复跑入口）。**纯 SELECT，无写操作。**
#
# 凭据来源：`backend/admin-api/.env`（与本机 admin-api 同源）；worktree 里没有该文件
# （`.env` 被 gitignore）⇒ 自动回落到**主工作区**的同一路径。
# 也可显式覆盖：`MIGAO_ADMIN_ENV=/path/to/.env ./run.sh`
# 凭据**不写入任何产物**（本脚本与 recon.sql 里都不含密钥）。
#
# ⚠️ RDS 对本机**间歇可用**（#4741 / #4672 同款）⇒ 本脚本内建**重试循环**（默认 12 次 × 5s）。
#    连不上时**非零退出**并打印「未取到读数」—— 不把「没查」写成「没问题」。
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
MAIN_WT="$(dirname "$(git -C "$REPO" rev-parse --path-format=absolute --git-common-dir)")"
ENV_FILE="${MIGAO_ADMIN_ENV:-$REPO/backend/admin-api/.env}"
[ -f "$ENV_FILE" ] || ENV_FILE="$MAIN_WT/backend/admin-api/.env"
[ -f "$ENV_FILE" ] || { echo "找不到 admin-api/.env（试过 \$REPO 与主工作区）" >&2; exit 1; }
set -a; . "$ENV_FILE"; set +a
export PGPASSWORD="$RDS_PASSWORD"
export PGSSLMODE="${PGSSLMODE:-prefer}"
export PGCONNECT_TIMEOUT="${PGCONNECT_TIMEOUT:-5}"

ATTEMPTS="${ATTEMPTS:-12}"
for i in $(seq 1 "$ATTEMPTS"); do
  echo "### 连接尝试 $i/$ATTEMPTS …" >&2
  if psql -w -h "$RDS_HOST" -p "$RDS_PORT" -U "$RDS_USER" -d "$RDS_DB" \
        -v ON_ERROR_STOP=1 -f "$HERE/recon.sql"; then
    exit 0
  fi
  sleep 5
done
echo "❌ $ATTEMPTS 次均连不上 RDS（本机间歇可用）—— **未取到真库读数**，不得读成「没问题」" >&2
exit 3
