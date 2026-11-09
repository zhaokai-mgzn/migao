#!/usr/bin/env bash
# batch-merge.sh — 多 PR **集中合**（batch merge）的入口。实现体 = scripts/batch_merge_lib.py。
#
# 为什么要有这条入口（而不是直接跑 python）：铁律 10「一晚做过 ≥3 次的动作串 ⇒ 收敛成一条命令」——
# 合批时的**顺序即安全顺序**（校验 → 从 origin/main 重建 → 逐支合并且每支必须提交 → 让号 →
# 重渲染 + 实测重锚 → 复核 → push + draft PR），顺序错一步就是今晚那四个坑。
#
#   ./scripts/batch-merge.sh <PR号> [<PR号> ...] [--branch batch/<日期>] [--dry-run] [--no-push]
#
# 用法/口径/边界见 https://github.com/zhaokai-mgzn/migao/wiki/Development 的「批次合并（默认路径）」与
# `python3 scripts/batch_merge_lib.py --help`。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$(command -v python3.11 || command -v python3 || true)"
if [ -z "${PY}" ]; then
  echo "❌ 找不到 python3 —— 批次合并无法执行（fail-closed）" >&2
  exit 2
fi
exec "${PY}" "${ROOT}/scripts/batch_merge_lib.py" "$@"
