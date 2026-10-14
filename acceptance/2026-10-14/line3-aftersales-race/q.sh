#!/usr/bin/env bash
# 线③ 只读查库助手（本线自建工装，**非产品代码**）：psql 参数现取 backend/admin-api/.env
# 用法：bash q.sh "select ..."        （只读；勿用于写）
set -u
REPO="/Users/guangzhen.zk/ai native/migao"
ENVF="$REPO/backend/admin-api/.env"
get() { grep -m1 "^$1=" "$ENVF" | cut -d= -f2- | tr -d '"'"'"''; }
export PGPASSWORD="$(get RDS_PASSWORD)"
psql -h "$(get RDS_HOST)" -p "$(get RDS_PORT)" -U "$(get RDS_USER)" -d "$(get RDS_DB)" \
  -v ON_ERROR_STOP=1 -X -q -A -t -F'|' -c "$1"
