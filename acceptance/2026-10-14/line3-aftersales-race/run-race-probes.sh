#!/usr/bin/env bash
# 线③ 复算入口：race-sweep 的 4 个探针（底座 run-all.sh 有路径缺陷，见 REPORT §3 G6 ⇒ 这里用绝对/仓库根相对路径）。
# 不修改底座任何文件。
set -u
REPO="/Users/guangzhen.zk/ai native/migao"
OUT="${OUT_DIR:-$REPO/acceptance/2026-10-14/line3-aftersales-race/out/race}"
export REPO_ROOT="$REPO" LIVE_WORKTREE="$REPO" ALLOW_LOCAL_API=1 \
       API_BASE="${API_BASE:-http://127.0.0.1:8080}" AGENT_BASE="${AGENT_BASE:-http://127.0.0.1:8001}" \
       TENANT_ID="${TENANT_ID:-32}" ADMIN_PHONE="${ADMIN_PHONE:-13800138000}" SMS_CODE="${SMS_CODE:-123456}"
cd "$REPO" || exit 1
mkdir -p "$OUT"
LOG="$OUT/run-all.log"
H=acceptance/2026-10-04/race-sweep/harness
for p in probe-write probe-idem probe-cross probe-redproof; do
  echo "=== $(date '+%F %T %Z') 运行 $p ===" | tee -a "$LOG"
  node "$H/$p.mjs" >> "$LOG" 2>&1
  echo "--- $p exit=$? ---" | tee -a "$LOG"
done
