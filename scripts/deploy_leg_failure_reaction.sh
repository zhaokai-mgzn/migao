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
# ── issue #6556：cron 驱动的腿完成**不发出 `workflow_run`** ⇒ 上面那条「成功即清零」的事件面
# 对 `schedule` 触发的腿**一次都不生效**（实测 15/15 条 `push` 完成在 1~3s 内触发对账腿；
# 2/2 条 `schedule` 完成一次都没触发 ⇒ #6544 / #6548 两条单在各自腿成功之后仍挂着）。
# ⇒ 清零改成**两条入口**（缺一条即红，元守卫见判据 ④）：
#   ① **事件快路径**（`workflow_run` + 成功类结论）—— 只在 `push` 面有效，保留；
#   ② **状态兜底**（本脚本在**非** `workflow_run` 事件下跑，逐腿读对账步落的
#      `.deploy-watchdog-state.tsv`，状态 = `deployed` 且那条腿有开放单 ⇒ 关）。
# **状态来源复用既有物**：TSV 由 `scripts/deploy_reconcile_state.sh` 的 `watchdog_note` 写、
# 由 `deploy-reconcile.yml` 的 `Reconcile deploys` 步落 —— **不另立第二份腿清单 / 第二套状态**。
#
# ── 接口（全部走 env：本仓有执行式守卫会逐字渲染 `run` 正文 ⇒ `${{ }}` 一律不进正文）──
#   LEG_NAME / LEG_CONCLUSION / LEG_ATTEMPT / LEG_RUN_ID / LEG_HEAD_SHA / LEG_RUN_URL
#   LEG_RUN_EVENT=<该 run 自己的触发事件>  —— ① 的**判别力**（见下「为什么成功 ≠ 已部署」）
#   STATE_FALLBACK=1 / STATE_FILE=<tsv> / TARGET_SHA=<对账基准>  —— ② 的入口
#   DRY_RUN=1        —— 只打印，不调 `gh`（离线自测用）
#   REACT_LOG_FILE=<文件>  —— 直接读该文件当失败日志（**不调 `gh`**；守卫测试的离线驱动面）
#   GH_CALL_LOG=<文件>     —— 每次 `gh` 调用逐行追加（守卫测试的读数面）
#
# ── 🔴 为什么「run 结论 = success」**不能**单独当清零依据（issue #6556 判据 ③）──────────
# 每条镜像腿 `deploy-*.yml` 的 `Skip if already built` 判「已部署」**只看 run 结论**（#6294）：
# 命中 ⇒ `skip=true` ⇒ `Deploy to SWAS` 整段 skipped，而 **run 结论仍是 success**。
# 那条路径上「线上到底在跑什么」由 `Assert running tag == target (skip 不得冒充已部署，issue #6294)`
# 自证（`deploy/scripts/swas_deploy_running_tag.sh`：在跑 tag ≠ 目标 tag ⇒ **exit 1** ⇒ job 判红）。
# ⇒ **本脚本不改那条 wiring**，只在① 里加**判别阀**：`success` 只有在「该 run 的目标 tag 就是
# 它的 head sha」时才等价于「目标 tag 已在跑」——
#   · `push` / `schedule`：`Resolve image tag` 取 `sha-${GITHUB_SHA::7}`，`GITHUB_SHA` = main HEAD
#     ⇒ 自证通过 ≡ 线上在跑 `sha-<head7>`（**或**该 tag 的部署已成功过 ⇒ 同一条运行面结论）；
#   · `workflow_dispatch -f image_tag=<tag>`（**回滚**路径，`deploy-admin-api.yml` 的
#     `MODE=rollback`）：自证比的是**回滚 tag**，与「main HEAD 已上线」无关
#     ⇒ **不构成清零依据**，本脚本按 `LEG_RUN_EVENT` 把它挡掉。
# ② 的状态判据里，`deployed` 两条来源逐条同源（对账步落的）：
#   · `镜像已存在：<image>`（判据 ①，C′ 后对 ACR 恒不成立、保留待复活）；
#   · `无漂移：自 <p>（上次成功部署）起 <svc_path> 无代码改动`（判据 ②=有效判据）。
#     ⚠️ 边界（照实登记）：判据 ② 的基准可能是**回滚 run** 的 sha ⇒ 它自身不区分回滚。
#     本单**不动**对账步的判定语义（那是 #5929/#5814 的契约）⇒ 该残余只在「人工回滚 +
#     code path 自那以后无改动」时成立，逐条登记在守卫测试的 docstring 里。
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
# issue #6556：① 的判别阀（该 run 自己的触发事件）+ ② 的两个入口。
RUN_EVENT="${LEG_RUN_EVENT:-}"
STATE_FALLBACK="${STATE_FALLBACK:-0}"
STATE_FILE="${STATE_FILE:-.deploy-watchdog-state.tsv}"
TARGET_SHA="${TARGET_SHA:-}"

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

# ── 腿标识 ⇄ 对账腿键（issue #6556）──────────────────────────────────────────
# 值守单标题用的是**腿的 workflow 名**（`github.event.workflow_run.name` ⇒ 线上既有单的形态，
# 本单**不改**它）；而 ② 的入口读的是对账步的状态文件，那里的键是 `reconcile_one` 的**服务名**
# （`admin-api` / `admin-web` / `bmini-h5-hosting` …）。两套键必须**显式对齐**，否则
# 状态兜底会去查一个**不存在的标题** ⇒ 静默不清零（正是本单要治的形态）。
# ⇒ 对本表 = **唯一一份**映射；两侧的「是不是都对得上」由守卫测试逐条现取核对
#   （① 服务键 ⇄ `deploy-reconcile.yml` 的 `reconcile_one` 调用；② workflow 名 ⇄ 该文件的 `name:` 行）。
LEG_KEYS="admin-api:deploy-admin-api.yml \
ai-agent-service:deploy-ai-agent-service.yml \
admin-web:deploy-frontend.yml \
worker-h5:worker-h5-publish.yml \
bmini-h5-hosting:bmini-h5-publish.yml \
c-end-h5:c-end-h5-publish.yml"

LEG_TITLE_PREFIX="[deploy-leg]"
WATCHDOG_TITLE_PREFIX="[deploy-watchdog]"

leg_workflow_file() {   # $1=服务键 ⇒ 该腿的 workflow 文件名（空 = 未登记）
  for _p in $LEG_KEYS; do
    case "$_p" in "$1":*) printf '%s' "${_p#*:}"; return 0 ;; esac
  done
  return 0
}

# 腿的 workflow 名 = 该 workflow 文件第一行 `name:`（**真值源就是那个文件**，不另抄一份）。
leg_display_name() {   # $1=服务键
  local wf; wf="$(leg_workflow_file "$1")"
  [ -n "$wf" ] || return 0
  [ -f ".github/workflows/$wf" ] || return 0
  grep -m1 '^name:' ".github/workflows/$wf" 2>/dev/null | sed 's/^name:[[:space:]]*//' || :
}

# 给一条腿算它值守单的**标题**（开单/查单/关单**同一份**）：$1=服务键（可空 ⇒ 回落到 LEG）
leg_title() {
  local key="$1" name
  [ -n "$key" ] || key=""
  if [ -n "$key" ]; then name="$(leg_display_name "$key")"; else name=""; fi
  [ -n "$name" ] || name="$LEG"
  printf '%s %s 部署失败（合并后未上线）' "$LEG_TITLE_PREFIX" "$name"
}

# ── 通知臂（任何失败类结论）──────────────────────────────────────────────────
NOTIFY_OK=0
notify() {   # $1=动作描述（写进评论，幂等：同标题已开 ⇒ 评论，不重复开单）【事件快路径专用】
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

# ── issue #6556 的两个新出口（② 状态兜底 / 通知补齐）──────────────────────────
open_issue_of_title() {   # $1=标题 ⇒ 该标题下**开放**单的编号（无 ⇒ 空）
  local n
  n="$(ghc issue list --state open --search "$1 in:title" --json number --jq '.[0].number // empty')" || n=""
  printf '%s' "$n" | tr -dc '0-9'
}

# 把一条腿的单**清零**（状态驱动，issue #6556）。只关**本出口**那一族（`[deploy-leg]`）——
# `[deploy-watchdog]` 的单归值守面自己关（**并存 + 去重，不代关**，见文件头的分工）。
clear_leg() {   # $1=服务键（可空=事件快路径） $2=清零依据（写进评论）
  local key="$1" why="$2" t n close_reason=""
  t="$(leg_title "$key")"
  n="$(open_issue_of_title "$t")"
  if [ -z "$n" ]; then
    echo "✅ 腿 ${key:-$LEG} 已收敛 ⇒ 无开放的 \`${LEG_TITLE_PREFIX}\` 单需要清零"
    return 0
  fi
  printf '%s\n' "清零：\`${key:-$LEG}\` 已收敛（${why}）—— 本单由 \`deploy-reconcile.yml\` 的腿级反应步（issue #6526 B / #6556）自动关闭。" \
    | ghc issue comment "$n" --body-file - >/dev/null || :
  case "$why" in
    *success*) close_reason="completed" ;;
    *)         close_reason="" ;;   # 状态兜底：该 commit 已上线 ⇒ 按「不再计划」关
  esac
  if [ -n "$close_reason" ]; then
    ghc issue close "$n" --reason "$close_reason" >/dev/null || :
  else
    ghc issue close "$n" --reason not_planned >/dev/null || :
  fi
  echo "✅ 腿 ${key:-$LEG} 已收敛 ⇒ 自动关闭值守单 #${n}（${why}）"
  return 0
}

# 通知补齐（issue #6556）：值守面判到 `terminal`（该 commit 的部署**不会再自动重试**）而这条腿
# **没有**开放的 `[deploy-leg]` 单 ⇒ 开一条。补的是「纯 cron 失败没有即时面」这个缺口
# （事件面只在 `workflow_run` 到达时才有，而 cron 完成**不投递**该事件）。
# 🔴 去重（按 `deploy-reconcile.yml` 既有口径）：取值守面**同一份**状态文件里的 `terminal` —— 它
# **同时**会开 `[deploy-watchdog]` 单（宽限期 N 内不报、超期报）⇒ 本出口**只在两件事同时成立**时开单：
#   ① 有开放单可挂时**不**另开（幂等：已有 `[deploy-leg]` 单 ⇒ 评论）；
#   ② 已经存在开放的 `[deploy-watchdog]` 单 ⇒ 值守面已在叫这一条腿 ⇒ **不重复出声**。
notify_terminal_leg() {   # $1=服务键 $2=状态依据
  local key="$1" why="$2" t n wd
  local state; state="$(leg_state "$key")"
  # 只有在「值守面口径的告警桶」里才补通知（`terminal` = 断路器：不会再自动重试）；与值守面
  # 的 `case "${state}"` 逐值同口径 —— `deployed` / `inflight` / `notarget` / `unrecorded` 都不开。
  [ "$state" = "terminal" ] || return 0
  t="$(leg_title "$key")"
  n="$(open_issue_of_title "$t")"
  if [ -n "$n" ]; then
    printf '%s\n' "仍失败：\`${key}\` 状态=\`terminal\`（${why}）。本单由 \`deploy-reconcile.yml\` 的腿级反应步（issue #6556）复核后追加。" \
      | ghc issue comment "$n" --body-file - >/dev/null || :
    echo "🔁 腿 ${key} 仍为 terminal ⇒ 已在单 #${n} 上追加（不重复开单）"
    return 0
  fi
  wd="$(open_issue_of_title "$WATCHDOG_TITLE_PREFIX")"
  if [ -n "$wd" ]; then
    echo "ℹ️ 腿 ${key} 为 terminal，但已有开放的 \`${WATCHDOG_TITLE_PREFIX}\` 单 #${wd} ⇒ 不重复出声（去重，issue #6556）"
    return 0
  fi
  LEG="$key"   # `issue_body` 复用事件面的正文模板（它读的是全局 LEG / CONCLUSION / …）
  CONCLUSION="terminal"
  HEAD_SHA="${TARGET_SHA:-$HEAD_SHA}"
  {
    issue_body "**状态兜底判红**（issue #6556）：对账步把这条腿判成 \`terminal\` —— 该 commit 的部署落在不可恢复终态、**不会再自动重试**，而 \`workflow_run\` 事件面在 **cron 触发的完成**上**不投递**（实测 2/2 条 schedule 完成零触发）⇒ 本单由**状态兜底**这条入口补开。"
  } | ghc issue create --title "$t" --body-file - --label "priority/P1" >/dev/null || :
  echo "🔴 腿 ${key} 判到 terminal 且无开放单 ⇒ 已由状态兜底开单（标题：${t}）"
  return 0
}

# 读对账步落的状态（**唯一来源** = `.deploy-watchdog-state.tsv`，issue #5935）：$1=服务键
leg_state() {
  awk -F'\t' -v s="$1" '$1 == s { print $2; exit }' "$STATE_FILE" 2>/dev/null || true
}
leg_state_why() {
  awk -F'\t' -v s="$1" '$1 == s { print $3; exit }' "$STATE_FILE" 2>/dev/null || true
}

issue_body() {   # $1=本次动作
  # ⚠️ 赋值而不是只靠调用方同名的全局（issue #6556 实测）：`set -u` 下 heredoc 里的 `${act}`
  #    若未定义 ⇒ `act: unbound variable` ⇒ 那段正文**一个字都发不出去**（gh 调用被吞）。
  act="${1:-}"
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
- 该腿**下一次**成功（\`conclusion=success\`）⇒ 事件驱动到达本脚本 ⇒ **自动关闭本单**；
  非 \`workflow_run\` 事件（\`schedule\` / \`workflow_dispatch\`）下，\`schedule\` 触发的完成
  **不投递** \`workflow_run\`（issue #6556 实测：15/15 条 push 完成触发、**2/2** 条 schedule 完成
  零触发）⇒ 由**状态兜底**那条入口关闭（对账步把该腿判成 \`deployed\` 即关）。
- 自动重跑**只做一次**（\`run_attempt == 1\` 才重跑；与 #4767/#5814 的断路器语义一致，
  用 GitHub 自己的 \`run_attempt\`，**不自建计数器**）。
- 人工出口：\`gh run rerun ${RUN_ID:-<run-id>} --failed\`，或在该 run 页面 Re-run；确属代码问题先修/回滚。
EOF
}

# ② 状态兜底（issue #6556）─────────────────────────────────────────────────
# 在**非** `workflow_run` 事件下逐腿判：对账步已判「这条腿的 main HEAD 代码状态已上线」
# （`deployed`）且该腿有开放的 `[deploy-leg]` 单 ⇒ 关。**不做**任何新的状态判定
# （不查 `gh run list`、不算漂移 —— 判定本体只在对账步里，本步只消费它的结论）。
#
# ⚠️ **状态 ⇄ commit 的绑定**（如实登记）：本入口**不**拿 `TARGET_SHA` 去逐条比对 ——
#    那条状态是**同一个 job 的 `Reconcile deploys` 步**落的，而它对账的基准就是它自己的
#    checkout（`ref: main`）的 HEAD，也就是对账腿**本轮读到的那个 main HEAD**。
#    ⇒ 状态文件**没有「陈旧到另一个 commit」这个面**（`watchdog_note` 每轮先播种 `unrecorded`
#    再整行替换，见 `scripts/deploy_reconcile_state.sh`）。
#    `TARGET_SHA` 照旧由薄壳步传进来并**打进取数行**（可追溯 / 便于对账），但**不当判据** ——
#    多立一条比不出差别的判据只会让读者以为它更强。
state_fallback_arm() {
  if [ ! -f "$STATE_FILE" ]; then
    echo "::warning::状态兜底入口：读不到对账状态文件 \`${STATE_FILE}\`（对账步未落状态？）—— 本入口弃权，不判红"
    return 0
  fi
  echo "── 状态兜底清零（issue #6556：cron 完成的腿不投递 \`workflow_run\`）基准=${TARGET_SHA:-未知} ──"
  local key state why _pair
  # ⚠️ `$LEG_KEYS` **不加引号**（按空白分词 —— 每项 `<服务键>:<wf 文件>`；**不用 `declare -A`**，
  #    macOS bash 3.2）；`${_pair%%:*}` 取服务键。**别写成 `printf '%s' "$LEG_KEYS" | cut -d: -f1`**：
  #    那样 `printf` 的第一个参数不是格式串 ⇒ 多行内容被拼成 `%s` 的**一个**参数、`cut` 只看到一行
  #    （本包实测：只跑第一条腿，其余五条**静默不判**）。
  for _pair in $LEG_KEYS; do
    key="${_pair%%:*}"
    state="$(leg_state "$key")"
    why="$(leg_state_why "$key")"
    case "$state" in
      deployed)
        clear_leg "$key" "对账步判该 commit 的代码状态已上线（状态=\`deployed\`：${why:-无依据}）"
        ;;
      terminal)
        notify_terminal_leg "$key" "${why:-无依据}"
        ;;
      *)
        echo "ℹ️ 腿 ${key}：状态=\`${state:-缺失}\` ⇒ 本轮不清零、不通知（只有 \`deployed\` 才清零）"
        ;;
    esac
  done
  return 0
}

# ── 主流程 ───────────────────────────────────────────────────────────────────
# issue #6556：**无腿信息**不再等于「不动作」—— `schedule` / `workflow_dispatch` 触发的本步
# 拿不到 `workflow_run` 载荷 ⇒ 走**状态兜底**那条入口（②）。两条入口**缺一不可**（元守卫判据 ④）。
if [ -z "$LEG" ]; then
  if [ "$STATE_FALLBACK" = "1" ]; then
    state_fallback_arm
    exit 0
  fi
  echo "::warning::反应步输入缺失（LEG_NAME 为空且未开状态兜底）—— 无法判定是哪条腿，本轮不动作（不判红）"
  exit 0
fi

TITLE="$(leg_title "")"

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

# ① 成功类 ⇒ 清零（不通知、不重跑），**但先过判别阀**（issue #6556 判据 ③）
if [ "$SUCCESS" = "1" ]; then
  # `success` 只在「该 run 的目标 tag 就是它自己的 head sha」时才等价于「线上已部署目标 tag」
  # —— 见文件头「为什么 run 结论 = success 不能单独当清零依据」。
  # 反例（真实存在）：`workflow_dispatch -f image_tag=<tag>` 的人工**回滚** run（`MODE=rollback`）
  # 结论也是 success，而它自证/部署的是**回滚 tag** ⇒ 拿它关「main HEAD 未上线」的单是错的。
  case "${RUN_EVENT:-}" in
    "" | push | schedule) ;;   # 空 = 本机/离线调用面（守卫测试的既有驱动面）；两者 = head sha 就是目标 tag
    *)
      echo "ℹ️ ${LEG} 结论 success，但该 run 的触发事件是 \`${RUN_EVENT}\`（目标 tag 未必是 head sha）⇒ **不当清零依据**，不清零"
      exit 0
      ;;
  esac
  clear_leg "" "部署成功（conclusion=${CONCLUSION}，sha=${HEAD_SHA:-未知}，run ${RUN_URL:-}）"
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

# ② **状态兜底入口**（issue #6556）：与上面的事件快路径**并存**（元守卫判据 ④ 要求两条入口同时在位）。
# 本步在 `workflow_run` 事件下也会跑（`STATE_FALLBACK=1`）：本轮的腿已按**事件**判过，这里再按
# **状态**兜一遍 **其它**腿 —— 那正是「cron 完成的腿不投递 `workflow_run`」留下的缺口。
[ "$STATE_FALLBACK" = "1" ] && state_fallback_arm
exit 0
