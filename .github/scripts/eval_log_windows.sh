#!/usr/bin/env bash
# =============================================================================
# eval_log_windows.sh — 从评测汇总里取出**按用例切片的证据窗口**（issue #3805）
#
# 病灶：失败后 dump 容器日志一直用固定行数（`--tail=100`/`--tail=60`），取到的是
# **dump 那一刻**的日志。实测（判定跑 34873715194）：`OR-014` 的执行窗口是
# 01:20–01:47 CST（runner 自己打印 `⏱ OR-014 start=2026-09-14T17:20:00+00:00`），
# 而 `aikf-ai-agent` 的 `--tail=100` 段起点是 **01:48:24** ⇒ 失败窗口的证据 **0 行**。
# runner 的 `⏱ start=` 锚点一直存在，但**没有任何步骤消费它** —— 本脚本就是那个消费者。
#
# 用法:
#   bash .github/scripts/eval_log_windows.sh <eval-summary.json> --failed
#   bash .github/scripts/eval_log_windows.sh <eval-summary.json> --all
#
# 输出: 每行 `"<since>\t<until>\t<case_id>"`（RFC3339，`docker logs --since/--until` 直接可用）
# 退出码: 0=有窗口；2=无汇总文件；3=汇总里没有窗口字段（调用方应回落固定 tail）
#
# 说明:
#   · 时间串由 runner 用 `datetime.now(timezone.utc).isoformat(timespec="seconds")` 生成，
#     格式恒为 `YYYY-MM-DDTHH:MM:SS+00:00`（定长 + 同一时区偏移）⇒ 字典序即时间序，
#     故 `min`/`max` 直接可用（不需要 date 解析，避免 macOS/Linux 差异）。
#   · 本脚本**只取数**，不改任何判定逻辑。
# =============================================================================
set -euo pipefail

f="${1:-}"
mode="${2:---failed}"
if [ -z "$f" ] || [ ! -f "$f" ]; then
  echo "⚠️ 无汇总文件：${f:-（空参数）}" >&2
  exit 2
fi

out=$(jq -r --arg mode "$mode" '
  [ .cases[]? | select(.started_at and .finished_at) ] as $c
  | if ($c | length) == 0 then empty
    elif $mode == "--all" then
      ([$c[].started_at] | min) + "\t" + ([$c[].finished_at] | max) + "\tALL"
    else
      $c[] | select((.score // 0) < 1)
          | .started_at + "\t" + .finished_at + "\t" + (.id | tostring)
    end' "$f" 2>/dev/null) || out=""

if [ -z "$out" ]; then
  echo "⚠️ 汇总里没有可用窗口（evaluation 未跑到写窗口处 / 旧版汇总无 started_at）" >&2
  exit 3
fi
printf '%s\n' "$out"
