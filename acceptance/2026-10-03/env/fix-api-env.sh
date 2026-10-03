#!/usr/bin/env bash
# 修正 :8080 的环境注入：首版重启**没有加载 .env** ⇒ sms.bypass-code 为空 ⇒ dev 登录 401
#   （同族事实上一批已留档于 acceptance/2026-10-03/INTEGRATION-LOG.md：
#    "按 Quick-Start 起进程时 sms.bypass-code 为空 ⇒ dev 登录 401；set -a; . ./.env 后即通"）。
# 本脚本：记录旧进程环境 → 带 .env 重启 → 自证（登录 200 + DB peer = 云 RDS）。
set -uo pipefail
LIVE=/Users/guangzhen.zk/migao-wt/main-live
ROUND="/Users/guangzhen.zk/ai native/migao/acceptance/2026-10-03"
ENVDIR="$ROUND/env"
API_LOG="$ROUND/out/main-live-round3-api-envfix.log"
say() { printf '[%s] %s\n' "$(date '+%H:%M:%S')" "$*"; }

mkdir -p "$ENVDIR"
say "=== 旧进程（无 .env）环境取证 ==="
OLDPID=$(lsof -ti :8080 | head -1)
ps eww -p "$OLDPID" 2>/dev/null | tr ' ' '\n' | grep -E '^(RDS_HOST|SMS_BYPASS_CODE|JWT_PUBLIC_KEY)=' | sed 's/=.*/=<set>/' > "$ENVDIR/api-env-before.txt" || true
say "旧 pid=${OLDPID}；取证：$(tr '\n' ' ' < "$ENVDIR/api-env-before.txt")（空 = 未注入）"
say "旧进程 DB peer：$(lsof -p "$OLDPID" -i :5432 -n -P 2>/dev/null | grep ESTABLISHED | head -1 | awk '{print $9}')"

say "=== 带 .env 重启 ==="
kill "$OLDPID" 2>/dev/null
for i in $(seq 1 30); do lsof -ti :8080 >/dev/null 2>&1 || break; sleep 1; done
cd "$LIVE/backend/admin-api" || exit 1
set -a; . ./.env; set +a
say "注入后本 shell：RDS_HOST=${RDS_HOST:0:12}… SMS_BYPASS_CODE=${SMS_BYPASS_CODE:-<空>}"
nohup ./mvnw -q spring-boot:run >"$API_LOG" 2>&1 &
say "launcher pid=$!"

say "=== 等待就绪 ==="
OK=0
for i in $(seq 1 90); do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 http://127.0.0.1:8080/api/admin/health 2>/dev/null)
  [ -n "$code" ] && [ "$code" != "000" ] && { OK=1; break; }
  sleep 2
done
NEWPID=$(lsof -ti :8080 | head -1)
say "ready=$OK pid=$NEWPID"
sleep 2
say "POC 告警：" ; grep -c "POC 模式" "$API_LOG" 2>/dev/null || true

say "=== 登录自证（万能码 123456）==="
LOGIN=$(curl -s -X POST http://127.0.0.1:8080/api/auth/sms/login -H 'Content-Type: application/json' -d '{"phone":"13870217889","code":"123456"}')
echo "$LOGIN" | head -c 160 > "$ENVDIR/login-proof.json"
say "login: $(head -c 120 "$ENVDIR/login-proof.json")"

say "=== 新进程 DB peer ==="
lsof -p "$NEWPID" -i :5432 -n -P 2>/dev/null | grep ESTABLISHED | head -2

cat > "$ENVDIR/env-round3-envfix.json" <<EOF
{
  "fixedAt": "$(date '+%F %T %z')",
  "oldPid": "$OLDPID",
  "newPid": "$NEWPID",
  "envInjected": true,
  "loginOk": $(echo "$LOGIN" | grep -q '"success":true' && echo true || echo false),
  "apiLog": "$API_LOG"
}
EOF
say "=== DONE ==="
