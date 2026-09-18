#!/usr/bin/env bash
# 独立 oracle：**绕过 Java** 直调 ai-agent 端点，隔离「Java 送对 calc_info」与「端点答得对」。
# 凭据：ai-agent 的 SERVICE_TOKEN（worktree 无该文件 ⇒ 回落主工作区）。
# 用法：./oracle.sh            # 默认喂 fabric_meters=3
#       ./oracle.sh 12.3
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
MAIN_WT="$(dirname "$(git -C "$REPO" rev-parse --path-format=absolute --git-common-dir)")"
ENV_FILE="${MIGAO_AGENT_ENV:-$REPO/backend/ai-agent-service/.env}"
[ -f "$ENV_FILE" ] || ENV_FILE="$MAIN_WT/backend/ai-agent-service/.env"
[ -f "$ENV_FILE" ] || { echo "找不到 ai-agent/.env" >&2; exit 1; }
TOK="$(grep '^SERVICE_TOKEN=' "$ENV_FILE" | cut -d= -f2-)"
METERS="${1:-3}"
curl -s -m 20 -X POST "${AI_AGENT_URL:-http://localhost:8001}/api/internal/production/operation-qty" \
  -H "X-Service-Token: ${TOK}" -H 'Content-Type: application/json' \
  -d "{\"positions\":[{\"position_name\":\"oracle-probe\",\"operations\":[\"精裁-布\",\"布三边\",\"韩褶-布\",\"外帘装袋\"],\"calc_info\":{\"fabric_meters\":${METERS}}}]}" \
  | jq '.data.positions[0]'
