#!/usr/bin/env bash
# 腿级失败反应（issue #6526 B）：**部署腿的某一次 run 挂了** ⇒ ① 出声（开/更值班 issue）
# ② 首次自动重跑一次（具名确定性闸门命中时不重跑）。
# 🔴 **现行默认（用户 2026-10-08 裁定「可以小改」）**：台账六条腿 `rerun` **全部 `false`**
#    ⇒ **只出声、不自动重跑**；要恢复某条腿的自动重跑 ⇔ 把台账里那一行改成 `true`
#    （**功能未删**，开关双向判据见 `tests/unit_ci_workflows/test_deploy_leg_failure_reaction.py`
#    的 `test_rerun_arm_is_off_by_default_for_every_leg` ⇄ `test_flipping_a_leg_to_true_re_enables_the_rerun_arm`）。
#
# ── 为什么承载面是 `deploy-reconcile.yml` 而不是三条部署腿 ──────────────────────
# 三条腿的 `permissions` 只有 `contents: read` / `actions: read`。给它们加 `issues: write`
# 会把它们变成「**无人值守 × 写作用域**」的维护类机制 ⇒ 被 `scripts/mechanism_liveness.py`
# 的发现规则抓住 ⇒ 必须登记 + 发存活读数。本单**有意避开**这条扩面：`deploy-reconcile.yml`
# **已经**有 `on.workflow_run: types=[completed]`（监听六条腿）、**已经**有 `issues: write`
# 与 `actions: write` ⇒ 零新增权限、零新增 mechanism 登记。
#
# ── 与 `[deploy-watchdog]` 的分工（两个出口判的是不同的东西，别读成一个）────────
#   · `[deploy-watchdog]`（`.github/workflows/deploy-reconcile.yml` 的「值守面」步）：判**状态**
#     「合并了但没上线」—— 宽限 N=2700s + `*/20` 的 cron（实测被 GitHub 节流到 2.5~8.6 小时）。
#   · `[deploy-leg]`（本脚本）：判**这一次 run 挂了** —— 事件驱动、准实时（`workflow_run.completed`）。
#     它**不**判线上状态，也**不**替值守面关单。
#
# ── 接口（全部走 env：本仓有执行式守卫会逐字渲染 `run` 正文 ⇒ `${{ }}` 一律不进正文）──
#   LEG_NAME / LEG_CONCLUSION / LEG_ATTEMPT / LEG_RUN_ID / LEG_HEAD_SHA / LEG_RUN_URL
#   DRY_RUN=1        —— 只打印，不调 `gh`（离线自测用）
#   REACT_LOG_FILE=<文件>  —— 直接读该文件当失败日志（**不调 `gh`**；守卫测试的离线驱动面）
#   GH_CALL_LOG=<文件>     —— 每次 `gh` 调用逐行追加（守卫测试的读数面）
#
# 🔴 本脚本**绝不许**让调用它的 job 判红（issue #6526 B）：所有失败路径都 `|| :` + `::warning::`，
# 唯一非零退出是**输入缺失**（`leg-name` 为空），而薄壳步只在事件匹配时才调用它。
set -uo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
#: 台账路径（`REACT_LEDGER` 可覆盖 —— 守卫测试把它指向 tmp 语料；生产走仓内那一份）。
LEDGER="${REACT_LEDGER:-$REPO_ROOT/tests/unit_ci_workflows/deploy_leg_failure_reaction_ledger.json}"

LEG="${LEG_NAME:-}"
CONCLUSION="${LEG_CONCLUSION:-}"
ATTEMPT="${LEG_ATTEMPT:-}"
RUN_ID="${LEG_RUN_ID:-}"
HEAD_SHA="${LEG_HEAD_SHA:-}"
RUN_URL="${LEG_RUN_URL:-}"

# gh 的薄封装：统一加 `|| :`（反应步**不许**把 job 判红）+ 记录调用（守卫测试读它）
ghc() {
  # ⚠️ 调用记录只记**第一行**（正文经 `--body-file -` 从 stdin 走 ⇒ 命令本身仍是单行）——
  #    否则多行正文会把 `GH_CALL_LOG` 撑成几十行，守卫的读数面（`any("issue create" in c)`）会失效。
  if [ -n "${GH_CALL_LOG:-}" ]; then printf 'gh %s\n' "${*%%$'\n'*}" >> "$GH_CALL_LOG" 2>/dev/null || :; fi
  if [ "${DRY_RUN:-}" = "1" ]; then printf '    [dry-run] gh %s\n' "${*%%$'\n'*}"; return 0; fi
  gh "$@" 2>&1 || { echo "::warning::gh $1 调用失败（反应步不判红，issue #6526 B）：${*%%$'\n'*}"; return 1; }
}

# 具名确定性闸门（**抑制重跑、但仍通知**，issue #6526 B）：这些结论是**确定性的** ——
# 重跑同一个 commit 只会再命中一次同一条闸门（磁盘水位 / 不可恢复终态 / 有意 skip /
# 产物陈旧判定 / 依赖升级跳过）⇒ 自动重跑是纯 churn，而且会与对账的断路器互相放大。
# 检出方式**可离线驱动**：`REACT_LOG_FILE=<文件>` 时直接读文件、**不调 `gh`**。
GATES=(
  "磁盘水位闸门|磁盘可用"
  "磁盘水位闸门|中止构建"
  "磁盘水位闸门|BUILD_MIN_FREE_MB"
  "不可恢复终态闸门|不可恢复的终态"
  "skip 自证|跳过本轮构建部署"
  "C 端产物陈旧判定|线上产物"
  "C 端产物陈旧判定|陈旧"
  "依赖升级跳过|dependabot"
)

read_ledger() {   # 打印 `<腿名>\t<true|false>`（离线、零依赖：无 python3 也能跑）
  # ⚠️ **两个真缺陷**（都在实测里踩过）：
  #   ① `name` 与 `rerun` 各占一行 ⇒ 单行 sed 匹配不到（首版）；
  #   ② 台账**顶层还有别的对象**（`rerun_default_off.not_a_feature_removal.evidence` 里逐字引用了
  #      判据名与 `rerun` 字样）⇒ 「按 `{`…`}` 取块」会把**非腿对象**也当成腿（实测：把某腿翻
  #      `true` 之后仍报「未登记」）。
  # ⇒ 锚在**本台账的稳定缩进契约**上：腿对象的字段缩进 6 空格、块结束 `}` 缩进 4 空格；
  #    顶层注解对象里不会出现 6 空格缩进的 `"name"`/`"rerun"` ⇒ 天然被跳过。
  #    改 JSON 缩进风格（如 4 空格）会让这里读空 ⇒ **判据会红**（`rerun` 一律读成非 true）。
  [ -f "$LEDGER" ] || return 0
  awk '
    {
      if ($0 ~ /^      "name"[[:space:]]*:[[:space:]]*"/ && n == "") {
        n = $0; sub(/^.*"name"[[:space:]]*:[[:space:]]*"/, "", n); sub(/".*$/, "", n)
      }
      if ($0 ~ /^      "rerun"[[:space:]]*:[[:space:]]*(true|false)/ && r == "") {
        r = $0; sub(/^.*"rerun"[[:space:]]*:[[:space:]]*/, "", r); sub(/[^a-z].*$/, "", r)
      }
      if ($0 ~ /^    \}[,]?[[:space:]]*$/ && n != "" && r != "") {
        printf "%s\t%s\n", n, r; n = ""; r = ""
      }
    }
  ' "$LEDGER"
}

ledger_legs() { read_ledger | awk -F'\t' '{print $1}'; }
ledger_rerun() { read_ledger | awk -F'\t' -v s="$1" '$1 == s { print $2; exit }'; }

# ── 通知臂（任何失败类结论）──────────────────────────────────────────────────
NOTIFY_OK=0
notify() {   # $1=动作描述（写进评论，幂等：同标题已开 ⇒ 评论，不重复开单）
  local act="$1" n body
  n="$(ghc issue list --state open --search "${TITLE} in:title" --json number --jq '.[0].number // empty')" || return 0
  n="$(printf '%s' "$n" | tr -dc '0-9')"
  # ⚠️ 正文一律走 `--body-file -`（stdin）：调用记录保持**单行**，且不用 `--body "…"` 背多行/引号。
  if [ -z "$n" ]; then
    n="$(issue_body "$act" | ghc issue create --title "$TITLE" --body-file - --label "priority/P1" | grep -oE '[0-9]+$' | tail -1)"
  else
    issue_body "$act" | ghc issue comment "$n" --body-file - >/dev/null || :
  fi
  [ -n "$n" ] && NOTIFY_OK=1
  return 0
}

issue_body() {   # $1=本次动作
  cat <<EOF
[deploy-leg] 部署腿失败值守（issue #6526 B：**某一次 run 挂了**）。

- 腿：\`${LEG}\`
- 结论：\`${CONCLUSION}\` · attempt：\`${ATTEMPT:-未知}\` · sha：\`${HEAD_SHA:-未知}\`
- run：${RUN_URL:-（未提供）}

### 与 \`[deploy-watchdog]\` 的分工（**两个出口判的不是同一件事**）
- \`[deploy-watchdog]\` 判的是**状态**：「合并了但没上线」（宽限 N=2700s，靠 \`*/20\` 的 cron，
  实测被 GitHub 节流到 2.5~8.6 小时）。
- 本单判的是**这一次 run 挂了**：事件驱动（\`workflow_run.completed\`）、准实时。
  它**不**判线上状态，也**不**替值守面关单。

### 本次动作
${act}

### 清零判据（不靠人记得）
- 该腿**下一次**成功（\`conclusion=success\`）⇒ 事件驱动到达本脚本 ⇒ **自动关闭本单**。
- 自动重跑**只做一次**（\`run_attempt == 1\` 才重跑；与 #4767/#5814 的断路器语义一致，
  用 GitHub 自己的 \`run_attempt\`，**不自建计数器**）。
- 人工出口：\`gh run rerun ${RUN_ID:-<run-id>} --failed\`，或在该 run 页面 Re-run；确属代码问题先修/回滚。
EOF
}

# ── 主流程 ───────────────────────────────────────────────────────────────────
if [ -z "$LEG" ]; then
  echo "::warning::反应步输入缺失（LEG_NAME 为空）—— 无法判定是哪条腿，本轮不动作（不判红）"
  exit 0
fi

TITLE="[deploy-leg] ${LEG} 部署失败（合并后未上线）"

case "$CONCLUSION" in
  failure | cancelled | timed_out | startup_failure | action_required) FAILED=1 ;;
  *) FAILED=0 ;;
esac

# 成功类结论 ⇒ **只清零**（不开单、不重跑）。成功类 = success / skipped / neutral（与对账
# 断路器的「允许名单」同一口径：`skipped` 是「有意跳过」，它**不是**失败）。
SUCCESS=0
case "$CONCLUSION" in
  success | skipped | neutral) SUCCESS=1 ;;
esac

# ① 台账（**未登记即红**，issue #6526 B：新腿没进台账 ⇒ 本脚本非零退出）
if [ ! -f "$LEDGER" ]; then
  echo "::error::反应步台账缺失：${LEDGER}（新增部署腿必须同批登记 rerun + 理由）"
  exit 1
fi
if ! ledger_legs | grep -qxF "$LEG"; then
  # ⚠️ 判红**归属**：本脚本以非零退出表态，但 `deploy-reconcile.yml` 的薄壳步把非零 rc
  #    吞成 `::warning::` + `exit 0`（**有意**语义：反应步自身不得让 reconcile job 判红）。
  #    ⇒ 运行期**不会**判红，红由 PR 面的
  #    `tests/unit_ci_workflows/test_deploy_leg_failure_reaction.py::test_unregistered_leg_is_red` 承担。
  echo "::error::部署腿 \`${LEG}\` 未登记在 $LEDGER —— 新腿必须同批登记（rerun + 理由）；未登记即红（issue #6526 B）"
  exit 1
fi
RERUN_ENABLED="$(ledger_rerun "$LEG")"
[ "$RERUN_ENABLED" = "true" ] || RERUN_ENABLED="false"

# ② 成功类 ⇒ 清零（不通知、不重跑）
if [ "$SUCCESS" = "1" ]; then
  n="$(ghc issue list --state open --search "${TITLE} in:title" --json number --jq '.[0].number // empty')" || n=""
  n="$(printf '%s' "$n" | tr -dc '0-9')"
  if [ -n "$n" ]; then
    printf '%s\n' "清零：\`${LEG}\` 部署成功（conclusion=${CONCLUSION}，sha=${HEAD_SHA:-未知}，run ${RUN_URL:-}）—— 本单由 \`deploy-reconcile.yml\` 的腿级反应步（issue #6526 B）自动关闭。" | ghc issue comment "$n" --body-file - >/dev/null || :
    ghc issue close "$n" --reason completed >/dev/null || :
    echo "✅ ${LEG} 成功 ⇒ 自动关闭值班单 #${n}"
  else
    echo "✅ ${LEG} 成功 ⇒ 无开放单需要清零"
  fi
  exit 0
fi

if [ "$FAILED" != "1" ]; then
  echo "ℹ️ ${LEG} 结论 \`${CONCLUSION}\` 既非失败类也非成功类（GitHub 新增的结论？）⇒ 本轮不通知、不重跑"
  exit 0
fi

# 读失败日志（闸门检出用）。`gh` 的 stderr 丢弃（它只是噪声；失败与否由 stdout 是否为空 +
# 闸门是否命中体现）。离线驱动面 REACT_LOG_FILE ⇒ 不调 gh。
read_log() {
  if [ -n "${REACT_LOG_FILE:-}" ]; then LOG="$(cat "$REACT_LOG_FILE" 2>/dev/null || :)"; return 0; fi
  [ -n "$RUN_ID" ] || return 0
  LOG="$(gh run view "$RUN_ID" --log-failed 2>/dev/null || :)"
  [ -n "$LOG" ] || LOG="$(gh run view "$RUN_ID" --log 2>/dev/null || :)"
}
read_log
LOG="${LOG:-}"

# ④ 具名确定性闸门 ⇒ **不重跑、但仍通知**
HIT=""
for g in "${GATES[@]}"; do
  label="${g%%|*}"; needle="${g##*|}"
  if printf '%s' "$LOG" | grep -qF -- "$needle"; then HIT="${label}（锚点：${needle}）"; break; fi
done

ACTION=""
if [ -n "$HIT" ]; then
  ACTION="**不自动重跑**（命中具名确定性闸门：${HIT}）—— 重跑只会再命中同一条闸门；已通知，请人工按 run 日志处置。"
elif [ "$RERUN_ENABLED" != "true" ]; then
  # 台账里 `rerun=false` 的腿。**当前六条腿全部如此** —— 用户 2026-10-08 裁定（逐字「可以小改」）：
  # 关掉自动重跑臂、**只保留通知**（详见台账 `rerun_default_off`：谁在什么时候为什么关、怎么翻回来）。
  # 翻回来 = 把该腿那一行的 `rerun` 改成 `true`（脚本逻辑一字未动，它只按这一列取值）。
  # ⚠️ `Publish C-end H5` 另有独立理由：它的发布只在 `workflow_dispatch` + `inputs.publish=='true'`
  # 时发生（用户 2026-09-27 裁定 B）⇒ 自动重跑不会有任何发布效果；该理由逐条写在台账 `reason` 里。
  ACTION="**不自动重跑**（台账登记 rerun=false：本轮按用户 2026-10-08 裁定只通知、不自动重跑；要恢复请改该腿那一行的数据）。"
elif [ "${ATTEMPT:-}" != "1" ]; then
  ACTION="**不自动重跑**（attempt=${ATTEMPT:-未知} ≠ 1）—— 自动重跑**只做一次**（与 #4767/#5814 的断路器语义一致；attempt 用 GitHub 自己的 \`run_attempt\`，不自建计数器）。"
else
  # `_rerun_rc` 的**唯一**用途：让「重跑臂」在守卫测试里可用一行注入关掉（`=1` ⇒ 走 else 分支
  # 并如实写「尝试失败」）—— 生产恒为 0，语义与直接 `if ghc run rerun …` 逐字相同。
  _rerun_rc=0
  if [ "$_rerun_rc" = "0" ] && ghc run rerun "$RUN_ID" --failed >/dev/null; then
    ACTION="**已自动重跑一次**（\`gh run rerun ${RUN_ID} --failed\`）。第二次仍失败 ⇒ 不再自动重跑。"
  else
    ACTION="**自动重跑尝试失败**（\`gh run rerun ${RUN_ID} --failed\` 非零返回，多为 \`actions: write\` 不可用或 run 太旧）—— 需人工 \`gh run rerun ${RUN_ID} --failed\`。"
  fi
fi

echo "🔴 ${LEG} 部署失败（conclusion=${CONCLUSION} · attempt=${ATTEMPT:-未知} · sha=${HEAD_SHA:-未知}）"
echo "   → ${ACTION}"
notify "$ACTION"
if [ "$NOTIFY_OK" = "1" ]; then
  echo "   → 值守单已开/更（标题：${TITLE}，label=priority/P1）"
else
  echo "::warning::值守单未能开/更（限流/权限？）—— 本轮失败只留在本 run 日志里"
fi
exit 0
