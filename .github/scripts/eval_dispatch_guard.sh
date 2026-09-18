#!/usr/bin/env bash
# 评测**派发前守卫**（issue #3761/#3769）—— A 统一入口 + B 结论复用 + C 空跑守卫。
#
# 用户裁定（本轮）：「不要空跑消耗 token；统一评测」。三条规则全部**落在代码里**，
# 不靠文档约定（文档约定拦不住派发）：
#
#   A 统一入口：判定用途的评测**只允许**走 post-deploy-eval.yml 的**分层（档内）全库**跑
#     （`tier=normal`，一次覆盖 mibao + xiaobu 两条腿）。⚠️ 这里的「全库」= **该档**全库
#     （`normal` **只跑 NORMAL 档**，不含 smoke/adversarial，三档互斥）——**不等于**
#     「覆盖全部用例」；判定用途的 normal 跑**只代表 NORMAL 档的结论**。`case_ids` 只留给"定点复现/调试"，
#     且必须声明 `PURPOSE=debug`。**收窄跑不构成判定结论**（summary 的 total 只反映那几条）。
#     ⇒ `CASE_IDS` 非空 且 `PURPOSE=determination` ⇒ **退出码 1（拒绝派发）**。
#   B 结论复用：先查 verdict ledger —— 键 = (sha, tier, case_ids 收窄输入, 用例库指纹,
#     跑批策略版本)。命中（存在同 SHA 的**已完成全库** run，其 persona 汇总的 run_key 与
#     `completion.ok=true` 同时成立）⇒ **不跑**，直接引用上次 run id + 时间 + 结论（退出码 2）。
#     这是真正的省钱点：判定类全库跑是真 LLM，重复跑零边际信息。
#   C 空跑守卫：算「评测相关路径」的变更集（runner / 用例库 / ai-agent 行为源 / 评测 workflow）。
#     **为空 ⇒ 不派发**，打印 `⏭️ 评测相关代码无变更 ⇒ 未跑（引用 <run_id>）`（退出码 2）。
#
# 「没跑」必须**看起来像没跑**：本脚本的所有"跳过"输出都以 `⏭️` 开头并显式给出可引用的 run id，
# 绝不复用"绿"的字样；CI 侧另有 `eval_run_telemetry` 计数把 skipped 与真跑分开（见 workflow）。
#
# 退出码：
#   0 = 可以派发（规则允许，且没有可复用的结论）
#   1 = 派发**不合规**（A 违规：判定用途被收窄）—— 调用方必须停下并改派发方式
#   2 = **不必派发**（B 命中结论 / C 无评测相关变更）—— 调用方直接引用给出的 run id
#   3 = 无法判定（git/gh 不可用、SHA 不存在）—— 不谎报"可以派发"
#
# 输入（env）：
#   EVAL_SHA        打算评测的对象 SHA（必填；`git rev-parse` 可解析即可）
#   EVAL_TIER       评测档位（默认 normal）—— 判定用途只认 normal **档**全库（只跑 NORMAL 档；
#                   不含 smoke/adversarial，勿据以声称覆盖两者）
#   CASE_IDS        收窄用例（逗号分隔；空 = 该档全库跑）
#   PURPOSE         determination（默认）| debug
#   BASE_REF        变更集计算的基底（默认 origin/main）
#   REPO            owner/repo（默认 GITHUB_REPOSITORY 或本仓库）
#   RUNS_CMD        【测试钩子】取候选 run 列表的命令（默认 gh api ...；见 _candidates）
#   ARTIFACT_CMD    【测试钩子】取某个 run 的汇总 JSON 的命令模板（%s = run id）
#   DIFF_CMD        【测试钩子】取变更集的命令模板（%s = BASE...SHA）
set -uo pipefail

# MODE=ci ⇒ 只执行 A（workflow 内硬拦：判定用途被收窄 ⇒ 直接 fail）；
# MODE=dispatch（默认）⇒ A + B（结论复用）+ C（空跑守卫），供派发方在**建 run 之前**调用。
MODE="${MODE:-dispatch}"

EVAL_SHA="${EVAL_SHA:-}"
EVAL_TIER="${EVAL_TIER:-normal}"
CASE_IDS="${CASE_IDS:-}"
PURPOSE="${PURPOSE:-determination}"
BASE_REF="${BASE_REF:-origin/main}"
REPO="${REPO:-${GITHUB_REPOSITORY:-zhaokai-mgzn/migao}}"
WORKFLOW_FILE="post-deploy-eval.yml"

# ── 评测相关路径（runner / 用例库 / ai-agent 行为源 / 评测 workflow 与脚本）──
# 口径与 tests/agent_eval/behavior_mapping.py 的 BEHAVIOR_SOURCE_PREFIXES 同源（行为源），
# 另加 runner 与用例库：这三类变了才可能改变"评测结论"。
# ⚠️ #4275（2026-09-18）：原列出的 `agent-behavior-eval.yml` 已删除，从正则里移除
#   （它只剩零 LLM 的 map job，从来不是评测结论的产出方）。
EVAL_RELEVANT_RE='^(tests/agent_eval/|backend/ai-agent-service/|\.github/cases/|\.github/scripts/eval_|\.github/workflows/(post-deploy-eval|xiaobu-acceptance)\.yml)'

say() { echo "$@"; }

# ── A：统一入口（判定用途不得收窄）────────────────────────────────────────
if [ -n "$CASE_IDS" ] && [ "$PURPOSE" = "determination" ]; then
  say "❌ 派发不合规（A 统一入口）：CASE_IDS 非空 + PURPOSE=determination。"
  say "   判定用途只允许**全库**跑（tier=normal，一次覆盖 mibao+xiaobu 两条腿）——"
  say "   收窄跑（--case-ids）只用于定点复现/调试，其 summary 的 total 只反映那几条，"
  say "   拿它下判定结论就是假绿。"
  say "   要么去掉 CASE_IDS，要么显式声明 PURPOSE=debug（并在 PR/证据里标注「非判定用途」）。"
  exit 1
fi

if [ "$MODE" = "ci" ]; then
  # workflow 内只拦 A：B/C 需要"派发前"的变更集与候选 run 查询，属派发侧职责
  # （CI 里跑它们等于把"该不该派发"推迟到钱已经花了之后）。
  say "✅ A 合规（统一入口：判定用途未被收窄；case_ids='${CASE_IDS}' purpose=${PURPOSE}）"
  exit 0
fi

# ── C：空跑守卫（评测相关路径无变更 ⇒ 不派发）──────────────────────────────
if [ -z "$EVAL_SHA" ]; then
  say "❓ 无法判定：EVAL_SHA 为空（不给默认值 —— 猜一个 SHA 去查复用/变更集是假绿来源）"
  exit 3
fi

DIFF_CMD="${DIFF_CMD:-git diff --name-only %s}"
difftarget="${BASE_REF}...${EVAL_SHA}"
if ! changed=$(eval "${DIFF_CMD//%s/$difftarget}" 2>/dev/null); then
  say "❓ 无法判定：变更集算不出来（命令：${DIFF_CMD//%s/$difftarget}）—— 先 git fetch origin"
  exit 3
fi
relevant=$(printf '%s\n' "$changed" | grep -E "$EVAL_RELEVANT_RE" || true)

# ── B：verdict ledger 查询 ────────────────────────────────────────────────
# 候选 = 同一 SHA 上本 workflow 的**已完成** run（新的在前）。命中条件（全部成立才算命中）：
#   ① 每个 persona 的汇总里都有 run_key，且 sha/tier/cases_fingerprint/policy_version 与
#      "本次要跑的形态"一致；② run_key.case_ids 为空（**全库跑**才算判定结论）；
#   ③ 该 persona 的 completion.ok == true。
# 任何一个条件取不到（旧 run 无 run_key / artifact 缺失）⇒ 不命中（宁可多跑，不可复用过期结论）。
_policy_version() {
  python3 "$(dirname "$0")/../../tests/agent_eval/eval_policy_version.py" 2>/dev/null | tr -d '\n'
}
_cases_fingerprint() {
  git rev-parse "${EVAL_SHA}:.github/cases" 2>/dev/null | tr -d '\n'
}

RUNS_CMD="${RUNS_CMD:-gh api repos/${REPO}/actions/workflows/${WORKFLOW_FILE}/runs?head_sha=${EVAL_SHA}\&status=completed\&per_page=10 --jq '.workflow_runs[].id'}"
ARTIFACT_CMD="${ARTIFACT_CMD:-gh run download %s -n post-deploy-eval-PERSONA -D /tmp/eval-ledger-%s-PERSONA}"

lookup_hit_run=""
lookup_detail=""
if candidates=$(eval "$RUNS_CMD" 2>/dev/null); then
  want_pv=$(_policy_version)
  want_fp=$(_cases_fingerprint)
  if [ -n "$want_pv" ] && [ -n "$want_fp" ] && [ "$want_pv" != "unknown" ]; then
    for rid in $candidates; do
      ok_all=true
      detail=""
      for persona in mibao xiaobu; do
        tmp="/tmp/eval-ledger-${rid}-${persona}"
        rm -rf "$tmp"
        acmd="${ARTIFACT_CMD//%s/$rid}"
        acmd="${acmd//PERSONA/$persona}"
        if ! eval "$acmd" >/dev/null 2>&1; then ok_all=false; detail="${persona}:取不到汇总（artifact 下载失败）"; break; fi
        # 递归找（`gh run download -n` 的落盘层级随版本/参数变化；报告 job 的 findSummary 同款理由）
        f=$(find "$tmp" -name "eval-summary-${persona}.json" 2>/dev/null | head -1)
        [ -n "$f" ] && [ -f "$f" ] || { ok_all=false; detail="${persona}:无 summary"; break; }
        # 逐条比对键（缺 run_key 的旧 run 一律不命中）
        got=$(jq -r '[.run_key.sha, .run_key.tier, .run_key.case_ids, .run_key.cases_fingerprint, .run_key.policy_version, .completion.ok] | @tsv' "$f" 2>/dev/null)
        [ -n "$got" ] || { ok_all=false; detail="${persona}:summary 无 run_key"; break; }
        want=$(printf '%s\t%s\t\t%s\t%s\ttrue' "$EVAL_SHA" "$EVAL_TIER" "$want_fp" "$want_pv")
        if [ "$got" != "$want" ]; then ok_all=false; detail="${persona}:键不匹配（got=${got}）"; break; fi
        rm -rf "$tmp"
      done
      if [ "$ok_all" = true ]; then lookup_hit_run="$rid"; break; fi
      lookup_detail="run ${rid} 未命中：${detail}"
    done
  else
    lookup_detail="策略版本或用例库指纹不可得 ⇒ 不做复用（宁可多跑）"
  fi
else
  lookup_detail="候选 run 查询失败 ⇒ 不做复用（宁可多跑）"
fi

if [ -n "$relevant" ]; then
  if [ -n "$lookup_hit_run" ]; then
    say "⏭️ 同一 SHA 已有判定结论 ⇒ **不重复跑**（B 结论复用，issue #3769）"
    say "   引用：run ${lookup_hit_run}（sha=${EVAL_SHA} tier=${EVAL_TIER} 全库跑，两个 persona 的 completion.ok=true）"
    say "   查看：https://github.com/${REPO}/actions/runs/${lookup_hit_run}"
    say "   键 = (sha, tier, case_ids=空, cases_fingerprint=$(_cases_fingerprint), policy_version=$(_policy_version))"
    exit 2
  fi
  say "✅ 可以派发（A 合规 + C 有评测相关变更 + B 无可用旧结论）"
  say "   本次变更集里与评测相关的文件："
  printf '%s\n' "$relevant" | sed 's/^/     · /'
  [ -n "$lookup_detail" ] && say "   （复用未命中原因：${lookup_detail}）"
  exit 0
fi

# 评测相关路径无变更 ⇒ 空跑守卫拦下（但仍给出可引用的 run id，方便直接复用）
say "⏭️ 评测相关代码无变更 ⇒ **未跑**（C 空跑守卫，issue #3769）"
say "   变更集（${difftarget}）里没有任何评测相关路径（runner / 用例库 / ai-agent 行为源 / 评测 workflow）。"
if [ -n "$lookup_hit_run" ]; then
  say "   引用：run ${lookup_hit_run}（同 SHA 的判定结论，可直接复用）"
  say "   查看：https://github.com/${REPO}/actions/runs/${lookup_hit_run}"
elif [ -n "$candidates" ]; then
  first=$(printf '%s' "$candidates" | head -1)
  say "   引用：同 SHA 最近一次 run ${first}（未命中复用键：${lookup_detail:-见上}）"
  say "   查看：https://github.com/${REPO}/actions/runs/${first}"
else
  # 本 SHA 没有已完成 run ⇒ 退一步给出「最近一次 main 上**成功**的判定全库跑」作为上下文，
  # ⚠️ 两个纪律：① 必须**显式标注对象 SHA 不同**（拿别的 SHA 的结论当本 SHA 的结论正是假绿，
  # migao-acceptance v1.4「陈旧产物被当结论」），故只作参考、不作复用；② 只挑
  # `conclusion == success` —— **cancelled 不是结果**（#3761：cancelled 的 run 零结论，
  # 首版实测就挑中了一个 cancelled run，正是本条要防的"把取消读成结论"）。
  LATEST_CMD="${LATEST_CMD:-gh api repos/${REPO}/actions/workflows/${WORKFLOW_FILE}/runs?status=completed\&branch=main\&per_page=20 --jq '[.workflow_runs[] | select(.conclusion==\"success\")][0].id'}"
  latest=$(eval "$LATEST_CMD" 2>/dev/null || true)
  if [ -n "$latest" ]; then
    say "   引用：本 SHA 暂无已完成 run；最近一次 main 上的判定全库跑 = run ${latest}"
    say "         https://github.com/${REPO}/actions/runs/${latest}"
    say "         ⚠️ 对象 SHA **不同** ⇒ 仅供参考（不得作为本 SHA 的评测结论复用）"
  else
    say "   注：本 SHA 暂无已完成 run，最近一次 run 也查不到（${lookup_detail:-无候选}）—— 本次仍**不派发**"
  fi
fi
exit 2
