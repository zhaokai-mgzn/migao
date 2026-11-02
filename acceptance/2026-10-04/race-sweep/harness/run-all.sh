#!/usr/bin/env bash
# 线③ 并发竞态 —— 顺序跑全部探针（逐条落盘 out/*.json + run-all.log）
set -u
# 🔴 修 #6938（装置缺陷，不改任何判定）：原实现 `cd` 到仓根后仍以**相对路径**
#    `acceptance/2026-10-04/race-sweep/harness/$p.mjs` 调 node ⇒ 与已 cd 的 cwd 重复拼接成
#    `acceptance/acceptance/…` ⇒ 三个探针全部 `Cannot find module`（exit 1），**一条判据都跑不出来**
#    （2026-10-04 报告与 2026-10-14 线③ §3-G6 两轮自曝同形；线③ 当时只能绕开逐个手跑）。
#    另：`tee -a "$LOG"` 在 out/ 不存在时直接 ENOENT —— 连原始失败都留不下来。
#    ⇒ ① 仓根 / harness 目录 / 日志路径**都先解析成绝对路径**（与 cwd 解耦）；
#       ② 相对 OUT_DIR 相对**仓根**解析（cd 之后语义稳定，保持既有调用口径）；
#       ③ 日志目录不存在就建。
SELF_DIR="$(cd "$(dirname "$0")" && pwd)" || exit 1
H="$SELF_DIR"
ROOT="$(cd "$SELF_DIR/../../.." && pwd)" || exit 1
cd "$ROOT" || exit 1
export API_BASE="${API_BASE:-https://api.migaozn.com}"
export TENANT_ID="${TENANT_ID:-25}"
export ADMIN_PHONE="${ADMIN_PHONE:-13800138000}"
export SMS_CODE="${SMS_CODE:-123456}"
export LIVE_WORKTREE="${LIVE_WORKTREE:-/Users/guangzhen.zk/migao-wt/main-live}"
OUT_DIR="${OUT_DIR:-acceptance/2026-10-04/race-sweep/out}"
case "$OUT_DIR" in /*) ;; *) OUT_DIR="$ROOT/$OUT_DIR" ;; esac
export OUT_DIR
mkdir -p "$OUT_DIR" || exit 1
LOG="$OUT_DIR/run-all.log"
for p in probe-write probe-idem probe-cross; do
  echo "=== $(date '+%F %T %Z') 运行 $p ===" | tee -a "$LOG"
  node "$H/$p.mjs" "$@" >> "$LOG" 2>&1
  echo "--- $p exit=$? ---" | tee -a "$LOG"
done
