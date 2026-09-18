#!/usr/bin/env bash
# issue #4299 真库取值分布复核 —— 只读运行器（复跑入口）。
#
# 凭据来源：backend/admin-api/.env（与本机 admin-api 同源，`spring.config.import` 用的就是它）。
#   worktree 里没有该文件（.env 被 gitignore）⇒ 自动回落到**主工作区**的同一路径。
#   也可显式覆盖：MIGAO_ADMIN_ENV=/path/to/.env ./run.sh
# 凭据**不写入任何产物**（本脚本与 sql 里都不含密钥）。
#
# 用法：./run.sh                 # 依次跑 survey.sql + survey2.sql
#       ./run.sh survey2.sql
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"

# 主工作区根（worktree 里 .env 被 gitignore ⇒ 要回落到主工作区那份）。
# 不用 `worktree list | awk '{print $2}'`：本机路径含空格（"ai native"）会被切断。
MAIN_WT="$(dirname "$(git -C "$REPO" rev-parse --path-format=absolute --git-common-dir)")"
ENV_FILE="${MIGAO_ADMIN_ENV:-$REPO/backend/admin-api/.env}"
[ -f "$ENV_FILE" ] || ENV_FILE="$MAIN_WT/backend/admin-api/.env"
[ -f "$ENV_FILE" ] || { echo "找不到 admin-api/.env（试过 \$REPO 与主工作区）" >&2; exit 1; }

# shellcheck disable=SC1090
set -a; . "$ENV_FILE"; set +a

export PGPASSWORD="$RDS_PASSWORD"
export PGSSLMODE="${PGSSLMODE:-prefer}"

SQL_FILES=("$@")
[ "${#SQL_FILES[@]}" -gt 0 ] || SQL_FILES=(survey.sql survey2.sql)

for sql in "${SQL_FILES[@]}"; do
  echo "### $sql"
  psql -h "$RDS_HOST" -p "$RDS_PORT" -U "$RDS_USER" -d "$RDS_DB" \
       -v ON_ERROR_STOP=1 -f "$HERE/$sql"
done
