#!/usr/bin/env bash
# 线③ 并发竞态 —— 顺序跑全部探针（逐条落盘 out/*.json + run-all.log）
set -u
cd "$(dirname "$0")/../../.." || exit 1
export API_BASE="${API_BASE:-https://api.migaozn.com}"
export TENANT_ID="${TENANT_ID:-25}"
export ADMIN_PHONE="${ADMIN_PHONE:-13800138000}"
export SMS_CODE="${SMS_CODE:-123456}"
export LIVE_WORKTREE="${LIVE_WORKTREE:-/Users/guangzhen.zk/migao-wt/main-live}"
export OUT_DIR="${OUT_DIR:-acceptance/2026-10-04/race-sweep/out}"
H=acceptance/2026-10-04/race-sweep/harness
LOG="$OUT_DIR/run-all.log"
for p in probe-write probe-idem probe-cross; do
  echo "=== $(date '+%F %T %Z') 运行 $p ===" | tee -a "$LOG"
  node "$H/$p.mjs" "$@" >> "$LOG" 2>&1
  echo "--- $p exit=$? ---" | tee -a "$LOG"
done
