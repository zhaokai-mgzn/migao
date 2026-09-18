#!/usr/bin/env bash
# 评测槽位占用查询 —— **派发前守卫**（issue #3761）。
#
# 用途：派发任何评测 run **之前**，先查 `eval-stack-global*` 槽位是否已有 run 在跑或在排队。
#
# 为什么放在派发侧（而不是再改 concurrency）：实测（2026-09-14 14:18–14:33 UTC）
#   · 该时段有 **10 个** post-deploy-eval run 被 cancelled；
#   · 其中 7 个在 pending 期就被后进的 pending 取代（**0 建栈成本**）；
#   · 2 个已经进到 `Start local stack` 并跑了 ~1.6min 才被杀（真浪费：栈建到一半、零结论）；
#   · 3 个被记成「部署后回归失败」假评论，落进 issue #3534（见 workflow 的「被取消记录」段）。
#   而**建栈层的 concurrency 已经是 `cancel-in-progress: false`**（post-deploy-eval.yml:160-167
#   workflow 级、xiaobu-acceptance.yml job 级；#4275 前还有 agent-behavior-eval.yml（已删）），
#   GitHub 的语义也不会用新 run 去取消一个 **running** run ⇒ 取消动作来自 **workflow 之外**
#   （派发侧并发互杀）。所以省成本的位置在派发侧：**先查槽位，别堆队列**。
#
# 判据：会起独立 docker 栈、共用同一评测槽位的 workflow 里，是否存在
#   status ∈ {queued, in_progress, pending, requested, waiting} 的 run。
#   （`waiting` = 环境审批等待；`requested`/`pending` = 并发组排队中。）
#
# 退出码（**调用方据此决定是否派发**）：
#   0 = 槽位空闲，可以派发
#   2 = 槽位被占用 —— **不要**派发（只会堆队列 + 冒互杀风险；等它跑完，或直接引用它的结论）
#   3 = 无法判定（gh 不可用/未登录/查询失败）—— **不谎报"空闲"**，由调用方决定
#
# 输入（env）：
#   SLOT_WORKFLOWS  可选：要检查的 workflow 文件名（空格分隔；默认两个共用槽位的 workflow）
#   GH_RUNS_CMD     可选：取 run 列表的命令模板，`%s` 会被替换成 workflow 文件名
#                   （**给测试用**，如 `printf '[]'`；默认走 `gh run list`）
set -uo pipefail

# ⚠️ #4275（2026-09-18）：原第三项 `agent-behavior-eval.yml` 已**删除**（它早已不起栈、
#   不占槽位；剩下的 map job 零 LLM 且随文件一并移除）⇒ 槽位持有者收敛为这两个。
SLOT_WORKFLOWS="${SLOT_WORKFLOWS:-post-deploy-eval.yml xiaobu-acceptance.yml}"
GH_RUNS_CMD="${GH_RUNS_CMD:-gh run list --workflow=%s --limit 20 --json databaseId,status,conclusion,event,headBranch,createdAt,url}"

BUSY_STATUSES='["queued","in_progress","pending","requested","waiting"]'

busy_total=0
unknown_total=0
report=""

for wf in $SLOT_WORKFLOWS; do
  cmd="${GH_RUNS_CMD//%s/$wf}"
  if ! raw=$(eval "$cmd" 2>/dev/null); then
    echo "⚠️ 查询失败：${wf}（命令：${cmd}）"
    unknown_total=$((unknown_total + 1))
    continue
  fi
  if ! busy=$(printf '%s' "$raw" \
      | jq -c --argjson busy "$BUSY_STATUSES" '[.[] | select(.status as $s | $busy | index($s))]' 2>/dev/null); then
    echo "⚠️ 返回内容不是合法 JSON 数组：${wf}"
    unknown_total=$((unknown_total + 1))
    continue
  fi
  n=$(printf '%s' "$busy" | jq 'length')
  busy_total=$((busy_total + n))
  if [ "$n" -gt 0 ]; then
    lines=$(printf '%s' "$busy" | jq -r --arg wf "$wf" \
      '.[] | "  · \($wf)  run \(.databaseId)  status=\(.status)  event=\(.event)  branch=\(.headBranch)  created=\(.createdAt)\n    \(.url)"')
    report="${report}${lines}"$'\n'
  fi
done

echo "════════ 评测槽位 eval-stack-global* 占用（派发前守卫，#3761）════════"
echo "检查的 workflow：${SLOT_WORKFLOWS}"
if [ -n "$report" ]; then
  echo "占用中的 run："
  printf '%s' "$report"
else
  echo "占用中的 run：（无）"
fi
echo "── 判定 ──"

if [ "$unknown_total" -gt 0 ]; then
  echo "❓ 无法判定（${unknown_total} 个 workflow 查询失败）—— 不谎报「空闲」；请确认 gh 可用/已登录后重查"
  exit 3
fi

if [ "$busy_total" -gt 0 ]; then
  echo "🚫 槽位被占用（${busy_total} 个 run 在跑/排队）—— **不要派发**："
  echo "   并发派发只会堆队列并冒互杀风险（实测 10 连 cancelled，其中 2 个死在建栈中途、3 个被记成假失败）。"
  echo "   选择：① 等它跑完；② 直接引用它的 run/artifact 作为结论（cancelled 的 run 不是结论）。"
  exit 2
fi

echo "✅ 槽位空闲（无 in_progress/queued run）—— 可以派发"
exit 0
