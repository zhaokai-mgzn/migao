#!/usr/bin/env bash
# 评测「被取代即抑制」判定（issue #3587）。
#
# 为什么单独一个脚本（而不是写死在 workflow 的 run 里）：
#   ① **可本地复跑**——判定逻辑是纯文本/纯 SHA 比对，不该只能"推上去赌一轮 CI"才验证得了
#      （本仓库的既有教训：不可复现的判定 = 不可验证的判定）；
#   ② 单测可以直接调它跑「被取代 / 未被取代」两种演练（tests/unit_ci_workflows/
#      test_post_deploy_eval_supersede.py），把判定口径钉死在测试里，而不是靠读 YAML 猜。
#
# 判据：本次 run 对应的 SHA 与**远端** main HEAD 比对，不等即"已被更新的 main 取代"。
#   · 相等 / 取值不可得（ls-remote 失败、空值）→ `run`（fail-open：宁可慢，不可漏评）；
#   · 不等                                      → `skip`（已被取代，跳过评测）。
#   ⚠️ 只有 `skip` 会抑制；一切异常都落到 `run` —— 判定逻辑本身绝不能成为"漏评"的来源。
#
# 退出码恒为 0：**抑制不是失败**（不得刷红、不得自动开 issue）。
#
# 输入（env）：
#   EVAL_SHA      被评 SHA（必填）
#   FORCE_EVAL    'true' → 强制评测，不抑制（手动补跑/回滚复验用）
#   REPO          owner/repo（默认取 GITHUB_REPOSITORY）
#   RUN_ID        本 run id（仅用于留档链接）
#   MAIN_SHA      可选覆盖：跳过 ls-remote，直接用它当 main HEAD（**给测试用**）
#   MAIN_REMOTE   可选覆盖远端地址（默认 https://github.com/<REPO>.git；测试用它构造
#                 "远端不可达"以演练 fail-open 分支）
#   MAIN_REF      远端 ref（默认 refs/heads/main）
set -uo pipefail

REPO="${REPO:-${GITHUB_REPOSITORY:-}}"
RUN_ID="${RUN_ID:-${GITHUB_RUN_ID:-unknown}}"
EVAL_SHA="${EVAL_SHA:-}"
MAIN_REF="${MAIN_REF:-refs/heads/main}"
MAIN_REMOTE="${MAIN_REMOTE:-https://github.com/${REPO}.git}"
FORCE_EVAL="${FORCE_EVAL:-false}"
SUPERSEDE_WORKFLOW="post-deploy-eval.yml"

RUN_URL="https://github.com/${REPO}/actions/runs/${RUN_ID}"

if [ -z "${MAIN_SHA:-}" ]; then
  # main HEAD 取自**远端**：workflow_run 的 checkout 显式指向被部署的旧 commit，
  # 它自己的 origin/main 只是那次 clone 的快照，不代表"现在"。
  MAIN_SHA=$(git ls-remote "${MAIN_REMOTE}" "${MAIN_REF}" 2>/dev/null | cut -f1)
fi

echo "被评 SHA   : ${EVAL_SHA:-（空）}"
echo "main HEAD  : ${MAIN_SHA:-（ls-remote 失败或为空）}"

if [ "$FORCE_EVAL" = "true" ]; then
  echo "FORCE_EVAL=true（手动强制评测）→ 不抑制"
  DECISION=run
elif [ -z "$MAIN_SHA" ] || [ -z "$EVAL_SHA" ]; then
  echo "判定不可得（ls-remote 失败/取值为空）→ fail-open，照常评测（宁可慢，不可漏评）"
  DECISION=run
elif [ "$EVAL_SHA" = "$MAIN_SHA" ]; then
  echo "本次 SHA == main HEAD → 未被取代，照常评测"
  DECISION=run
else
  DECISION=skip
fi

SUPERSEDED=false
[ "$DECISION" = "skip" ] && SUPERSEDED=true
if [ -n "${GITHUB_OUTPUT:-}" ]; then
  echo "superseded=${SUPERSEDED}" >> "$GITHUB_OUTPUT"
fi

if [ "$DECISION" = "skip" ]; then
  # ── 留档（这是"抑制不违反『结论档丢失』顾虑"的关键）──
  # 审计链：被抑制的 run → 被评 SHA（commit 链接）→ 取代它的 main SHA（commit 链接）
  #        → 取代它的 run 列表（真正给出结论的那次 run 在里面）。
  echo "════════════════════════════════════════════════════════════════"
  echo "⏭️ 抑制本次评测：本次 run 对应的 SHA 已被更新的 main 取代"
  echo "  · 本次评测对象 SHA : ${EVAL_SHA}"
  echo "    https://github.com/${REPO}/commit/${EVAL_SHA}"
  echo "  · 取代它的 main SHA: ${MAIN_SHA}"
  echo "    https://github.com/${REPO}/commit/${MAIN_SHA}"
  echo "  · 取代它的 run（该 SHA 的部署后回归，结论档在此）:"
  echo "    https://github.com/${REPO}/actions/workflows/${SUPERSEDE_WORKFLOW}?query=branch%3Amain"
  echo "  · 本 run（被抑制，留档于此）: ${RUN_URL}"
  echo ""
  echo "  为什么可以抑制（不违反『不 cancel-in-progress』那段的意图，见 workflow 文件头）："
  echo "  被抑制的 run 评价的那份镜像已被后续 commit 覆盖 —— 它的结论描述的是一个"
  echo "  *已经不是 main* 的状态。旧 run 在**花钱之前**被抑制，而不是跑到一半被取消；"
  echo "  结论由取代它的 run 承担，链接链在上面（可追、不丢）。"
  echo ""
  echo "  本次跳过**不计 failure**（job success，不建 issue）—— 省成本不该变成刷红。"
  echo "════════════════════════════════════════════════════════════════"
fi

exit 0
