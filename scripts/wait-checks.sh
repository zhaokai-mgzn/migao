#!/usr/bin/env bash
# case_ids: MC-012
# （CI/流程结构类 L0 不变式统一挂 MC-012，与 tests/unit_ci_workflows/** 的既有惯例同源。）
#
# wait-checks.sh — 「CI 全绿了吗」的**不可假绿**等待入口（issue #7009）。
#
# ## 病（PR #7003 实测**两次**，每次都差点把 pending 读成「CI 全绿」）
#
# `gh pr checks <PR> --watch` 在下面两种形态下都 **rc=0** 退出：
#   ① `PR Check` 还没**上报** check（later-created run / 刚 push）⇒ watch 认为「没有待跑的」⇒ rc=0；
#   ② 遇到 `Post graphql: read: connection reset by peer` ⇒ 仍 rc=0，而两条 required **还在 pending**。
# ⇒ **退出码不是「全绿」的判据**（而「CI 全绿」是合并/收口的放行依据 ⇒ 假绿会污染交付证据）。
#
# ## 判据（三态退出码，与 `merge_gate.py` / `land` 同口径）
#
#   0 = required 集合里**每一条**都拿到**终态 SUCCESS**（required 集合现取自分支保护，不写死清单）；
#   1 = 有 required 是**终态非 SUCCESS**（红 / 取消 / 超时 / 跳过）⇒ 具名打印，不重试、不猜；
#   3 = **无法判定** —— pending / queued / 尚未上报 / required 集合读不到 / 网络或 API 报错
#       （**与退出码无关**：读取到的文本里出现 `connection reset by peer` 之类字样就退 3）。
#   🔴 **3 绝不等于 0**：不许把「还没跑完」写成「CI 全绿」。
#
# ## 读数来源（每次判定都打印）
#
#   PR 号 + head sha + state（`gh pr view --json state,headRefOid`）· required 条数与出处
#   （`gh api repos/<owner>/<repo>/branches/main/protection/required_status_checks`）·
#   **每条 required 的 state** · 采样次数 · 读数时刻（本机时区，标注与 GitHub 的 UTC 之差）。
#
# ## 用法
#
#   ./scripts/wait-checks.sh <PR>                       # 等（默认上限 1800s、每 20s 采样一次）
#   ./scripts/wait-checks.sh <PR> --timeout 3600        # 加大上限
#   ./scripts/wait-checks.sh <PR> --once                # 只采样一次：仍 pending ⇒ 立即 3（不等待）
#   ./scripts/wait-checks.sh <PR> --repo owner/name     # 不在仓库目录里跑时指定仓库
#
# 判定本体**只有一份**：`scripts/merge_gate.py --wait-checks`（required 集合的解析、红/裸判据分类、
# pending 桶口径都复用它，**不另写第二套**）。本文件只是**命名的入口** + gh 替身注入点。
# 弃用：用 `gh pr checks <PR> --watch` 的**退出码**当「全绿」结论（issue #7009）。
set -uo pipefail

SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
# 替身注入点：WC_GH_BIN（本入口专用）> MG_GH_BIN（merge_gate 的既有约定）> gh
GH_BIN="${WC_GH_BIN:-${MG_GH_BIN:-gh}}"

if [ "$#" -eq 0 ] || [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
  sed -n '5,45p' "$0" | sed 's/^# \{0,1\}//'
  [ "$#" -eq 0 ] && exit 3   # 没给 PR 号 ⇒ 无法判定（不是「通过」）
  exit 0
fi

exec env "MG_GH_BIN=$GH_BIN" python3 "$SELF_DIR/merge_gate.py" --wait-checks "$@"
