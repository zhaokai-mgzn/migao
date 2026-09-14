#!/usr/bin/env bash
# 评测「被取代即抑制」判定（issue #3587 / #3654 / #3709）。
#
# 为什么单独一个脚本（而不是写死在 workflow 的 run 里）：
#   ① **可本地复跑**——判定逻辑是纯文本/纯 SHA 比对，不该只能"推上去赌一轮 CI"才验证得了
#      （本仓库的既有教训：不可复现的判定 = 不可验证的判定）；
#   ② 单测可以直接调它跑「被取代 / 未被取代」两种演练（tests/unit_ci_workflows/
#      test_post_deploy_eval_supersede.py），把判定口径钉死在测试里，而不是靠读 YAML 猜。
#
# 两种模式的判据（方向**相反**，见各自分支注释）：
#   · MODE=deploy（部署后门禁，#3587）：本次 run 的 SHA 与**远端** main HEAD 比对，
#     不等 = 已被更新的 main 取代 → `skip`（在花钱之前抑制，结论由取代它的 run 承担）；
#   · MODE=schedule（每 3 天全量，#3654）：本次 schedule 的 SHA 与**上一次 schedule
#     全量**的 SHA 比对，相等 = main 自上次全量以来未变动 → `skip`（同一状态已有结论，
#     重跑是纯浪费）；不等 = main 前进了 → 跑这一轮全量。
#   ⚠️ 两种模式一致：**只有 `skip` 会抑制；一切异常都落到 `run`（fail-open）**——
#     判定逻辑本身绝不能成为"漏评"的来源。
#
# ⚠️ 手动 workflow_dispatch 默认**免抑制**（#3709，2026-09-15 修正）：
#   dispatch 是「人显式要求评这一条」（回滚复验/补跑），按定义不该被 deploy 判据
#   当成"已被取代"。此前它与部署门禁共用 `MODE=deploy` ⇒ 派发与执行之间只要 main
#   动过就**静默空转**：实测 run 34841093824（`tier=adversarial -f case_ids=DF-011`）
#   整体 `completed/success`、**每个评测步骤 skipped**、artifacts `total_count=0`
#   —— 一条用例都没跑却报绿（而 workflow 注释当时写着"永不抑制"，读者据此漏传逃生口）。
#   现在：`EVENT_NAME=workflow_dispatch` ⇒ 默认 `FORCE_EVAL=true`；
#   **要抑制必须显式传 `force_eval=false`**（逃生口保留，省成本路径不消失）。
#   自动门禁（workflow_run 部署后 / schedule 全量）**不受影响**：它们没有 inputs。
#
# 退出码恒为 0：**抑制不是失败**（不得刷红、不得自动开 issue）。
#
# 输入（env）：
#   EVAL_SHA        被评 SHA（必填）
#   MODE            deploy（默认，#3587 原判据）| schedule（#3654 每 3 天全量判据）
#   EVENT_NAME      GITHUB 事件名（#3709）：'workflow_dispatch' ⇒ 默认免抑制
#   FORCE_EVAL_INPUT  workflow_dispatch 的 force_eval **原始输入值**（#3709）。
#                   'false'（大小写无关）⇒ 允许抑制；其它/缺省 ⇒ 免抑制。
#                   ⚠️ 与 FORCE_EVAL 的分工：本变量只描述"人怎么选的"，由脚本决定默认；
#                   workflow **不得**再直接从该输入注入 FORCE_EVAL（它恒有值，会盖掉默认）。
#   FORCE_EVAL      'true'/'false' 显式覆盖（**给测试与兼容用**；设了它就不再走上面的默认）
#   REPO            owner/repo（默认取 GITHUB_REPOSITORY）
#   RUN_ID          本 run id（仅用于留档链接）
#   MAIN_SHA        可选覆盖：跳过 ls-remote，直接用它当 main HEAD（**给测试用**）
#   MAIN_REMOTE     可选覆盖远端地址（默认 https://github.com/<REPO>.git；测试用它构造
#                   "远端不可达"以演练 fail-open 分支）
#   MAIN_REF        远端 ref（默认 refs/heads/main）
#   LAST_EVAL_SHA   可选覆盖：schedule 模式下跳过 gh 查询，直接用它当"上次全量覆盖的 SHA"
#                   （**给测试用**；CI 里由脚本自己查本 workflow 上一次 schedule run）
#   LAST_EVAL_CMD   可选覆盖：schedule 模式下"取上次全量 SHA"的命令（默认 gh api ...；
#                   **给测试用**，如 `false` 演练查询失败 = fail-open 分支）
set -uo pipefail

REPO="${REPO:-${GITHUB_REPOSITORY:-}}"
RUN_ID="${RUN_ID:-${GITHUB_RUN_ID:-unknown}}"
EVAL_SHA="${EVAL_SHA:-}"
MAIN_REF="${MAIN_REF:-refs/heads/main}"
MAIN_REMOTE="${MAIN_REMOTE:-https://github.com/${REPO}.git}"
# FORCE_EVAL 不再是"默认 false"：空 = 未显式覆盖，由下面按事件名决定（#3709）。
FORCE_EVAL="${FORCE_EVAL:-}"
EVENT_NAME="${EVENT_NAME:-}"
FORCE_EVAL_INPUT="${FORCE_EVAL_INPUT:-}"
MODE="${MODE:-deploy}"
LAST_EVAL_SHA="${LAST_EVAL_SHA:-}"
LAST_EVAL_CMD="${LAST_EVAL_CMD:-}"
SUPERSEDE_WORKFLOW="post-deploy-eval.yml"

RUN_URL="https://github.com/${REPO}/actions/runs/${RUN_ID}"

# ── #3709：解析"手动 dispatch 默认免抑制" ──
# 大小写无关：GitHub 的 boolean input 可能以 'True'/'False' 出现（既有注释已记录该坑）。
if [ -z "$FORCE_EVAL" ]; then
  if [ "$EVENT_NAME" = "workflow_dispatch" ]; then
    case "$(printf '%s' "$FORCE_EVAL_INPUT" | tr '[:upper:]' '[:lower:]')" in
      false|no|0)
        FORCE_EVAL=false
        echo "workflow_dispatch + force_eval=${FORCE_EVAL_INPUT}（人显式要求抑制）→ 仍走『被取代即抑制』判据（#3709 逃生口）"
        ;;
      *)
        FORCE_EVAL=true
        echo "workflow_dispatch（人显式要求评测）→ **默认免抑制**（#3709）；要抑制请显式传 force_eval=false"
        ;;
    esac
  else
    # 自动门禁（workflow_run 部署后 / schedule 全量）语义不变：它们没有 inputs。
    FORCE_EVAL=false
  fi
fi

if [ "$MODE" = "schedule" ]; then
  # ── schedule（每 3 天全量，#3654）：main 未动即抑制 ──
  # 判据 = "main 自上次 schedule 全量以来是否前进"：
  #   · 上次全量覆盖的 SHA 取**本 workflow 上一次 schedule run** 的 head_sha
  #     （gh api 查 runs；首次运行/查询失败 → fail-open 照常跑 —— 第一轮必须跑）；
  #   · 相等（本次 == 上次）→ main 没动 → 同一状态结论已给出 → skip（省一整轮全量）；
  #   · 不等 → main 前进了 → 跑（这才是 schedule 全量存在的意义）。
  if [ "$FORCE_EVAL" = "true" ]; then
    echo "FORCE_EVAL=true（手动强制评测）→ 不抑制"
    DECISION=run
  elif [ -z "$EVAL_SHA" ]; then
    echo "EVAL_SHA 为空 → fail-open，照常评测（宁可慢，不可漏评）"
    DECISION=run
  else
    if [ -n "$LAST_EVAL_SHA" ]; then
      LAST="$LAST_EVAL_SHA"
      echo "LAST_EVAL_SHA 由环境注入（测试钩子）: ${LAST}"
    else
      if [ -z "$LAST_EVAL_CMD" ]; then
        # -f 展开为查询参数（不用 & 拼接，避免 eval 时被 bash 当命令分隔符）
        LAST_EVAL_CMD="gh api repos/${REPO}/actions/workflows/${SUPERSEDE_WORKFLOW}/runs -f event=schedule -f branch=main -f per_page=1 --jq '.workflow_runs[0].head_sha'"
      fi
      LAST=$(eval "$LAST_EVAL_CMD" 2>/dev/null || true)
    fi
    echo "本次 schedule SHA : ${EVAL_SHA}"
    echo "上次 schedule SHA : ${LAST:-（取不到 → fail-open 跑）}"
    if [ -z "${LAST:-}" ]; then
      echo "上次全量 SHA 不可得（gh 查询失败/首次运行）→ fail-open，照常评测（宁可慢，不可漏评）"
      DECISION=run
    elif [ "$EVAL_SHA" = "$LAST" ]; then
      echo "main 自上次 schedule 全量以来未变动 → 抑制（同一状态已有结论，重跑是纯浪费）"
      DECISION=skip
    else
      echo "main 已前进（上次全量 ${LAST} → 本次 ${EVAL_SHA}）→ 照常评测"
      DECISION=run
    fi
  fi
else
  # ── deploy（部署后门禁，#3587 原判据，保持不变）──
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
fi

SUPERSEDED=false
[ "$DECISION" = "skip" ] && SUPERSEDED=true
# stdout 恒输出 superseded=（测试/人工都能直接读判定结果）；
# GITHUB_OUTPUT 是 workflow 消费通道（下游 if 引用 steps.supersede.outputs.superseded）。
echo "superseded=${SUPERSEDED}"
if [ -n "${GITHUB_OUTPUT:-}" ]; then
  echo "superseded=${SUPERSEDED}" >> "$GITHUB_OUTPUT"
fi

if [ "$DECISION" = "skip" ]; then
  # ── 留档（这是"抑制不违反『结论档丢失』顾虑"的关键）──
  # 审计链：被抑制的 run → 被评 SHA（commit 链接）→ 取代它的 SHA（commit 链接）
  #        → 取代它的 run 列表（真正给出结论的那次 run 在里面）。
  echo "════════════════════════════════════════════════════════════════"
  if [ "$MODE" = "schedule" ]; then
    echo "⏭️ 抑制本次 schedule 全量：main 自上次全量以来未变动"
    echo "  · 本次 schedule SHA : ${EVAL_SHA}"
    echo "    https://github.com/${REPO}/commit/${EVAL_SHA}"
    echo "  · 上次全量覆盖的 SHA: ${LAST}"
    echo "    https://github.com/${REPO}/commit/${LAST}"
    echo "  · 本 run（被抑制，留档于此）: ${RUN_URL}"
    echo ""
    echo "  为什么可以抑制：全量评测回答的是「main 当前状态行为是否达标」——状态没变"
    echo "  （同一 SHA），结论已在上一轮 schedule 全量给出；重跑是纯浪费（#3654 每 3 天档）。"
    echo "  部署定向轮（#3654）已按改动点覆盖了这段时间合并的行为改动，宽度由本档补足。"
  else
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
  fi
  echo ""
  echo "  本次跳过**不计 failure**（job success，不建 issue）—— 省成本不该变成刷红。"
  echo "════════════════════════════════════════════════════════════════"
fi

exit 0
