#!/usr/bin/env bash
# 部署腿 `Skip if already built` 命中时的**具名读数**（issue #9056）。
#
# ## 病（现场 run 45010592767，`schedule`）
#
# ```
# Skip if already built (schedule reconcile)   success
# Deploy to SWAS (测试环境)                      skipped
# ```
#
# 而 job 结论 = **success**。⇒ 读 run 列表的人（以及值守面的「下一次 conclusion=success」判据）
# 会把这条**一次没部署的空转**读成「已部署」，而线上仍是旧镜像（实证误导过一次归因）。
#
# ## 本脚本落什么（**只读数，不判红**）
#
# * `$GITHUB_OUTPUT`：`DEPLOY_SKIPPED=<原因码>`（下游/人工可读，具名到**哪一条跳过臂**）；
# * `$GITHUB_STEP_SUMMARY`：**部署步的结论**（本 run 的 `Deploy`/`Publish` 步 = skipped）+
#   跳过原因（码 + 中文）+ **复算命令**（白天自己核，不靠跑一次 CI）。
#
# rc **恒 0**：它是读数面，不是闸门 —— 闸门在值守面（`scripts/deploy_leg_failure_reaction.sh`
# 关单前必须自证 `DEPLOY_EXECUTED=1`，实现在 `.github/scripts/deploy_leg_deploy_evidence.py`）。
# 读数面把一条部署腿判红 = 让「跳过」这条**正常**路径变成失败（那是本单要治的假绿的反面）。
#
# ## 调用面（各腿 skip 步一行）
#
# ```bash
# skip_hit() {   # $1=原因码
#   echo "skip=true" >> "$GITHUB_OUTPUT"
#   bash .github/scripts/deploy_skip_attest.sh "$1" || :
# }
# ```
#
# 原因码必须登记在 `case` 里（未登记 ⇒ 仍然出声，并带出码本身，便于补登记）。
#
# 判据 = `tests/unit_ci_workflows/test_deploy_leg_failure_reaction.py` 的
# `test_every_skip_capable_leg_emits_the_named_skip_readout` /
# `test_skip_readout_lands_in_output_and_step_summary`。
set -uo pipefail

CODE="${1:-unknown}"
RUN_ID="${GITHUB_RUN_ID:-}"
SHORT="${GITHUB_SHA:0:7}"

case "$CODE" in
  duplicate_dispatch)
    HUMAN="\`workflow_dispatch\` 且未指定 \`image_tag\`，而该 commit 的镜像已存在 ⇒ 判定为**重复 dispatch**（#5078）" ;;
  image_exists)
    HUMAN="目标镜像已存在 ⇒ 该 commit 已构建过（判据 ①；C′ 下对 ACR **恒不成立**，保留待复活）" ;;
  same_sha_deployed)
    HUMAN="同 sha 的部署 run 结论 = \`success\` ⇒ 该 commit **已构建部署过**（判据 C′，#5814）" ;;
  unrecoverable_conclusion)
    HUMAN="镜像缺失且该 commit 最近一次部署是**不可恢复的终态** ⇒ 不重复部署（断路器，#5814 B）" ;;
  *)
    HUMAN="**未登记的原因码**（新增跳过臂必须同批登记本清单，issue #9056）" ;;
esac

RECIPE="gh run view ${RUN_ID:-<run-id>} --json jobs --jq '.jobs[].steps[] | select(.name|test(\"^(Deploy|Publish) \")) | \"\\(.name)\\t\\(.conclusion)\"'"

echo "⏭️ DEPLOY_SKIPPED=${CODE}（${HUMAN}）· sha=${SHORT:-未知} · run=${RUN_ID:-未知}"
echo "   部署步（\`Deploy …\` / \`Publish …\`）：本 run **skipped**（skip=true ⇒ 整段不执行）"
echo "   这不是「已部署」的证据 —— 值守面关单前置是 \`DEPLOY_EXECUTED=1\`（读部署步结论，issue #9056）"
echo "   复算：${RECIPE}"

if [ -n "${GITHUB_OUTPUT:-}" ]; then
  printf 'DEPLOY_SKIPPED=%s\n' "$CODE" >> "$GITHUB_OUTPUT" 2>/dev/null || {
    echo "::warning::写 \$GITHUB_OUTPUT 失败（读数只留在日志里）：$CODE"
  }
fi

if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
  {
    echo "## ⏭️ 本轮**未部署**（skip 非 deployed，issue #9056）"
    echo ""
    echo "- \`DEPLOY_SKIPPED=${CODE}\` —— ${HUMAN}"
    echo "- **部署步结论**：\`Deploy …\` / \`Publish …\` = **skipped**（\`skip=true\` ⇒ 整段不执行）"
    echo "- 身份：\`${GITHUB_WORKFLOW:-未知 workflow}\` · sha=\`${SHORT:-未知}\` · run=\`${RUN_ID:-未知}\`"
    echo "- 口径：本条读数**不是**「已部署」的证据；\`[deploy-leg]\` 值守单的关单前置是"
    echo "  \`DEPLOY_EXECUTED=1\`（读**部署步**结论，不是 job/run 结论）"
    echo "- 复算：\`${RECIPE}\`"
  } >> "$GITHUB_STEP_SUMMARY" 2>/dev/null || {
    echo "::warning::写 \$GITHUB_STEP_SUMMARY 失败（读数只留在日志里）：$CODE"
  }
fi

exit 0
