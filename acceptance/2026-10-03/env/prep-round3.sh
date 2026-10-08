#!/usr/bin/env bash
# 第三轮深度测试（2026-10-03 下午/晚）环境准备：
#   ① main-live 检出到 origin/main（记录前后 SHA）
#   ② 重编译 admin-api 并重启 :8080（单一稳定构建点，避免批内切换）
#   ③ 重启 worker-h5 静态服务 :3100（原进程 cwd 已被替换 ⇒ 全 404）
# 证据落 acceptance/2026-10-03/env/（前后读数 + 日志尾部）
set -uo pipefail

LIVE=/Users/guangzhen.zk/migao-wt/main-live
ROUND="/Users/guangzhen.zk/ai native/migao/acceptance/2026-10-03"
ENVDIR="$ROUND/env"
API_LOG="$ROUND/out/main-live-round3-api.log"
H5_LOG="$ROUND/out/worker-h5-3100-round3.log"
mkdir -p "$ENVDIR" "$ROUND/out"

say() { printf '[%s] %s\n' "$(date '+%H:%M:%S')" "$*"; }

say "=== 前置状态 ==="
BEFORE=$(git -C "$LIVE" rev-parse HEAD)
say "main-live before = $BEFORE"
git -C "$LIVE" status --short | head -5
lsof -ti :8080 | tr '\n' ' ' | sed 's/^/api pid: /'; echo

say "=== 备份 main-live 的唯一脏文件（heavy-entry 台账追加 2 行）==="
cp "$LIVE/tests/unit_ci_workflows/package_heavy_entry_ledger.jsonl" "$ENVDIR/main-live-heavy-ledger.before.jsonl"
cp "$LIVE/tests/unit_ci_workflows/package_heavy_entry_ledger.jsonl" /tmp/main-live-heavy-ledger.bak

say "=== fetch + 检出 origin/main ==="
git -C "$LIVE" fetch origin main 2>&1 | tail -2
TARGET=$(git -C "$LIVE" rev-parse origin/main)
say "target = $TARGET"
git -C "$LIVE" checkout -f "$TARGET" 2>&1 | tail -2
cp /tmp/main-live-heavy-ledger.bak "$LIVE/tests/unit_ci_workflows/package_heavy_entry_ledger.jsonl"
AFTER=$(git -C "$LIVE" rev-parse HEAD)
say "main-live after = $AFTER (dirty: $(git -C "$LIVE" status --porcelain | wc -l | tr -d ' ') 项)"

say "=== 编译 admin-api ==="
cd "$LIVE/backend/admin-api" || exit 1
ls mvnw >/dev/null 2>&1 && MVN=./mvnw || MVN=mvn
if ! $MVN -q -DskipTests compile >"$ENVDIR/compile.log" 2>&1; then
  say "编译失败，见 $ENVDIR/compile.log"
  tail -30 "$ENVDIR/compile.log"
  exit 1
fi
say "编译完成"

say "=== 重启 :8080 ==="
OLDPID=$(lsof -ti :8080 | head -1)
[ -n "${OLDPID:-}" ] && kill "$OLDPID" && say "killed old api pid=$OLDPID"
for i in $(seq 1 30); do lsof -ti :8080 >/dev/null 2>&1 || break; sleep 1; done
nohup $MVN -q spring-boot:run >"$API_LOG" 2>&1 &
say "api launcher pid=$!"

say "=== 重启 worker-h5 :3100 ==="
OLDH5=$(lsof -ti :3100 | head -1)
[ -n "${OLDH5:-}" ] && kill "$OLDH5" && say "killed old h5 pid=$OLDH5"
for i in $(seq 1 10); do lsof -ti :3100 >/dev/null 2>&1 || break; sleep 1; done
cd "$LIVE/frontend/worker-h5" || exit 1
nohup python3 -m http.server 3100 >"$H5_LOG" 2>&1 &
say "h5 pid=$!"

say "=== 等待 :8080 就绪（最多 180s）==="
OK=0
for i in $(seq 1 90); do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 http://127.0.0.1:8080/api/admin/health 2>/dev/null)
  if [ "$code" = "200" ] || [ "$code" = "401" ] || [ "$code" = "403" ]; then OK=1; break; fi
  sleep 2
done
say "api ready=$OK code=${code:-none} pid=$(lsof -ti :8080 | tr '\n' ' ')"

H5CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 http://127.0.0.1:3100/index.html)
say "worker-h5 /index.html => $H5CODE"

cat > "$ENVDIR/env-round3.json" <<EOF
{
  "preparedAt": "$(date '+%F %T %z')",
  "mainLiveBefore": "$BEFORE",
  "mainLiveAfter": "$AFTER",
  "originMain": "$(git -C "$LIVE" rev-parse origin/main)",
  "apiPid": "$(lsof -ti :8080 | head -1)",
  "apiHealth": "${code:-none}",
  "apiLog": "$API_LOG",
  "workerH5Pid": "$(lsof -ti :3100 | head -1)",
  "workerH5Index": "$H5CODE",
  "workerH5Log": "$H5_LOG",
  "agent8001": "$(lsof -ti :8001 | head -1)",
  "adminWeb3001": "$(lsof -ti :3001 | head -1)"
}
EOF
say "=== DONE ==="
cat "$ENVDIR/env-round3.json"
