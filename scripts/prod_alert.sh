#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════
# 生产告警**投递**（只发通知，**不做判定**；上线审计 P0-04，issue #8203）
#
# ## 它解决的问题：判定红/绿 ≠ 有人被惊动
#
# 审计 P0-04 的原文：三类事件（5xx / 证书到期 / 发布失败）**必须落到一个有人看的通道**，
# 而当时的形态是「只有腿本身红/绿」。本脚本是**唯一**的投递出口（一处实现、一条去重规则），
# 判定本体各自留在自己的判据脚本里（`deploy/scripts/prod-5xx-window.sh` /
# `deploy/scripts/tls-expiry-check.sh` / `scripts/deploy_leg_failure_reaction.sh`）。
#
# ## 通道（按优先级；默认第一项）
#
# | 通道 | 何时用 | 需要的配置 | 缺失时 |
# |---|---|---|---|
# | GitHub Issue（`priority/P1` + 标题去重）| 默认（Actions 里 `gh` 始终可用）| 无（`GITHUB_TOKEN` + `issues: write`）| `gh` 调不通 ⇒ **rc=3 + 出声**（不静默）|
# | Webhook（群机器人 / 邮件转发）| `MIGAO_ALERT_WEBHOOK_URL` 有值 ⇒ **附加**发一份；或 `MIGAO_ALERT_CHANNEL=webhook` ⇒ 只走它 | `MIGAO_ALERT_WEBHOOK_URL` secret | 显式选了 webhook 却没有 URL ⇒ **rc=3 + 出声** |
#
# ⚠️ **不发邮件 / 不发短信**：那两类要外部账号（SMTP / 短信签名），登记为「需用户配置」
# （见 docs/deployment/observability-minimum.md 的「仍需人工配置」）。webhook 留的是通用口。
#
# ## 幂等 / 去重（同一事件不许每轮刷屏）
#
# 身份 = `--key`（事件类）+ `--bucket`（**读数分级**，不是精确读数）。指纹
# `fp = <key>_<bucket>`（只保留 `[A-Za-z0-9._-]`）写进正文的 HTML 注释：
#
#     <!-- migao-alert fp=tls-expiry_rc1_... -->
#
# 投递规则：
#   ① 同标题**没有** open issue ⇒ 开一条（带 `priority/P1`），正文带指纹；
#   ② 同标题**有** open issue 且正文/评论里**已有同一指纹** ⇒ 什么都不写（`delivered=deduped`）；
#   ③ 同标题有 open issue 但指纹不同 ⇒ **评论**追加（读数分级变了 = 事件真的变重/变轻）。
#   ⇒ 「同一个事件每轮都红」只会有一条单、零条新评论；`bucket` 由调用方按**分级**给，
#     不许把逐轮会抖的精确值（如 5xx 的确切条数）直接塞进 bucket。
#
# ## 退出码（`3` 不得当 0 读；但**告警投递失败不改腿色** —— 见下）
#
# | 码 | 含义 |
# |---|---|
# | 0 | 已投递（新建 / 评论 / 去重命中）或 `--dry-run` 打印成功 |
# | 1 | 入参非法 / **疑似凭据**（拒绝发送，fail-closed）|
# | 3 | **无法投递**：通道不可用（gh 调不通 / 显式选 webhook 但没 URL / webhook POST 失败）|
#
# 🔴 **设计选择（二选一，这里明确选「不改腿色」）**：调用方一律
# `bash scripts/prod_alert.sh … || echo "::warning::告警投递失败"` —— **告警投递的成败
# 不参与 job 的红/绿判定**。理由：腿的红/绿必须只由**事件本身**的判据决定（否则一次
# GitHub API 抖动就会制造第二套失败语义 —— 正是 P1-04「成功即红」那种告警疲劳的近亲）；
# 而事件判红的腿本来就是红的，投递失败只降级为 `::warning::` + 本脚本的 `PROD-ALERT-SUMMARY rc=3`。
#
# ## 不泄密（机械守卫）
#
# 正文命中疑似凭据（`password=` / `secret=` / `token=` / `LTAI` / `AKIA` / `BEGIN … PRIVATE KEY`）
# ⇒ **拒绝发送**（rc=1），既不建 issue 也不发 webhook。判据 =
# tests/unit_ci_workflows/test_prod_alerting.py 的「不泄密」用例（真跑本脚本 + stub gh）。
#
# ## 用法
#
#   bash scripts/prod_alert.sh --key 5xx-window --title '[prod-alert] …' \
#        --bucket 'rc1_5xx_1-5' --body-file /tmp/body.md [--dry-run]
#
#   --key        事件类（稳定、短；进指纹）
#   --title      通道去重键（**稳定**标题；事件类变了才改它）
#   --bucket     读数分级（稳定值；同一分级 ⇒ 不重复评论）
#   --body-file  正文文件；`-` = stdin
#   --label      附加标签（默认 priority/P1）
#   --dry-run    只打印将发送的内容（演练 / 判据用），**不调** gh / curl
#
# 判据 = tests/unit_ci_workflows/test_prod_alerting.py
# ══════════════════════════════════════════════════════════════════════════
set -uo pipefail

KEY=''
TITLE=''
BUCKET='active'
BODY_FILE=''
LABEL=${MIGAO_ALERT_LABEL:-priority/P1}
CHANNEL=${MIGAO_ALERT_CHANNEL:-auto}
WEBHOOK_URL=${MIGAO_ALERT_WEBHOOK_URL:-}
CURL_BIN=${MIGAO_ALERT_CURL_BIN:-curl}
GH_BIN=${MIGAO_ALERT_GH_BIN:-gh}
DRY_RUN=${MIGAO_ALERT_DRY_RUN:-0}
RUN_URL=${MIGAO_ALERT_RUN_URL:-}

usage() {
  sed -n '2,80p' "$0" | sed 's/^# \{0,1\}//'
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --help|-h) usage; exit 0 ;;
    --key) KEY=${2:-}; shift 2 ;;
    --key=*) KEY=${1#--key=}; shift ;;
    --title) TITLE=${2:-}; shift 2 ;;
    --title=*) TITLE=${1#--title=}; shift ;;
    --bucket) BUCKET=${2:-}; shift 2 ;;
    --bucket=*) BUCKET=${1#--bucket=}; shift ;;
    --body-file) BODY_FILE=${2:-}; shift 2 ;;
    --body-file=*) BODY_FILE=${1#--body-file=}; shift ;;
    --label) LABEL=${2:-}; shift 2 ;;
    --label=*) LABEL=${1#--label=}; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    *)
      echo "::error::未知参数：${1}（--help 看用法）"
      exit 1
      ;;
  esac
done

say() { printf '   %s\n' "$*"; }

if [ -z "$KEY" ] || [ -z "$TITLE" ] || [ -z "$BODY_FILE" ]; then
  echo "::error::--key / --title / --body-file 三者必填（key 进指纹、title 是通道去重键、body 是正文）"
  echo "PROD-ALERT-SUMMARY rc=1 reason=missing_args"
  exit 1
fi

BODY=''
if [ "$BODY_FILE" = '-' ]; then
  BODY=$(cat)
elif [ -r "$BODY_FILE" ]; then
  BODY=$(cat "$BODY_FILE")
else
  echo "::error::正文文件不存在：${BODY_FILE}"
  echo "PROD-ALERT-SUMMARY rc=1 reason=body_file_missing"
  exit 1
fi

# ── 不泄密（机械守卫，先于任何外发动作）───────────────────────────────────────
SECRET_HIT=$(printf '%s' "$BODY" | grep -Eio 'password=|passwd=|secret=|token=|LTAI[0-9A-Za-z]{8,}|AKIA[0-9A-Z]{8,}|BEGIN [A-Z ]*PRIVATE KEY' | head -1 || true)
if [ -n "$SECRET_HIT" ]; then
  echo "::error::拒绝发送：告警正文命中疑似凭据（${SECRET_HIT}）—— 凭据不进 issue / 不进 webhook（issue #8203）"
  echo "PROD-ALERT-SUMMARY rc=1 reason=suspected_secret key=${KEY}"
  exit 1
fi

# 指纹：只保留安全字符（**可读**，不用哈希 ⇒ 排查时能一眼看出是哪个事件哪个分级）
FP=$(printf '%s_%s' "$KEY" "$BUCKET" | tr -c 'A-Za-z0-9._-' '-' | cut -c1-120)
FP=${FP%-}
MARKER="<!-- migao-alert fp=${FP} -->"

# 正文尾部带 run 链接（**可归因**：读者从单里一步就能到判红的那次 run）+ 指纹标记（去重身份）
if [ -n "$RUN_URL" ]; then
  FULL_BODY=$(printf '%s\n\n- run：%s\n\n%s\n' "${BODY%$'\n'}" "$RUN_URL" "$MARKER")
else
  FULL_BODY=$(printf '%s\n\n%s\n' "${BODY%$'\n'}" "$MARKER")
fi

echo '=============================================================='
echo "生产告警投递（issue #8203 审计 P0-04）"
echo "  key=${KEY} · bucket=${BUCKET} · fp=${FP} · 通道=${CHANNEL}"
echo "  标题=${TITLE}"
echo '=============================================================='

if [ "$DRY_RUN" = '1' ]; then
  say "[dry-run] 不调 gh / curl；以下是将要发送的正文："
  printf '%s\n' "$FULL_BODY"
  echo "PROD-ALERT-SUMMARY rc=0 delivered=dry-run channel=${CHANNEL} key=${KEY} fp=${FP}"
  exit 0
fi

# ── 通道选择（显式指定却缺配置 ⇒ rc=3，不静默）─────────────────────────────────
WANT_ISSUE=0
WANT_WEBHOOK=0
case "$CHANNEL" in
  issue) WANT_ISSUE=1 ;;
  webhook) WANT_WEBHOOK=1 ;;
  auto)
    WANT_ISSUE=1
    [ -n "$WEBHOOK_URL" ] && WANT_WEBHOOK=1
    ;;
  *)
    echo "::error::MIGAO_ALERT_CHANNEL 只认 issue / webhook / auto（实测：${CHANNEL}）"
    echo "PROD-ALERT-SUMMARY rc=1 reason=bad_channel"
    exit 1
    ;;
esac

if [ "$WANT_WEBHOOK" = '1' ] && [ -z "$WEBHOOK_URL" ]; then
  echo "::error::选了 webhook 通道但没有 MIGAO_ALERT_WEBHOOK_URL ⇒ 这条告警**送不出去**（rc=3，不当 0 读）"
  echo "PROD-ALERT-SUMMARY rc=3 delivered=none reason=webhook_unconfigured key=${KEY} fp=${FP}"
  exit 3
fi

if [ "$WANT_ISSUE" = '1' ] && [ "$CHANNEL" = 'issue' ] && ! command -v "$GH_BIN" >/dev/null 2>&1; then
  echo "::error::issue 通道不可用（找不到 \`${GH_BIN}\`）⇒ 这条告警**送不出去**（rc=3，不当 0 读）"
  echo "PROD-ALERT-SUMMARY rc=3 delivered=none reason=gh_missing key=${KEY} fp=${FP}"
  exit 3
fi

DELIVERED='none'
ISSUE_NO=''
CHANNELS_USED=''

# ── 通道 ①：GitHub Issue（标题去重 + 指纹去重）──────────────────────────────────
if [ "$WANT_ISSUE" = '1' ]; then
  GH_RC=0
  EXIST=$("$GH_BIN" issue list --state open --search "${TITLE} in:title" --json number --jq '.[0].number // empty' 2>/dev/null) || GH_RC=$?
  EXIST=$(printf '%s' "$EXIST" | tr -dc '0-9')
  if [ "$GH_RC" != '0' ]; then
    echo "::warning::gh issue list 调用失败（rc=${GH_RC}）⇒ 本次告警**未投递**到 issue 通道"
    echo "PROD-ALERT-SUMMARY rc=3 delivered=none channel=issue reason=gh_list_failed key=${KEY} fp=${FP}"
    exit 3
  fi

  if [ -z "$EXIST" ]; then
    if printf '%s\n' "$FULL_BODY" | "$GH_BIN" issue create --title "$TITLE" --body-file - --label "$LABEL" >/dev/null 2>&1; then
      DELIVERED='created'
      CHANNELS_USED="${CHANNELS_USED}issue "
      say "🔴 已新建值班单（标题：${TITLE}，标签：${LABEL}）"
    else
      echo "::warning::gh issue create 失败 ⇒ 本次告警**未投递**（限流 / 权限 / 标签不存在）"
      echo "PROD-ALERT-SUMMARY rc=3 delivered=none channel=issue reason=gh_create_failed key=${KEY} fp=${FP}"
      exit 3
    fi
  else
    ISSUE_NO=$EXIST
    SEEN=$("$GH_BIN" issue view "$EXIST" --json body,comments \
      --jq '(.body // "") + "\n" + ((.comments // []) | map(.body // "") | join("\n"))' 2>/dev/null) || SEEN=''
    case "$SEEN" in
      *"$MARKER"*)
        DELIVERED='deduped'
        CHANNELS_USED="${CHANNELS_USED}issue "
        say "⏭️ 已在单 #${EXIST} 上报过同一分级（fp=${FP}）⇒ 本轮**不写**任何内容（不刷屏）"
        ;;
      *)
        if printf '%s\n' "$FULL_BODY" | "$GH_BIN" issue comment "$EXIST" --body-file - >/dev/null 2>&1; then
          DELIVERED='commented'
          CHANNELS_USED="${CHANNELS_USED}issue "
          say "🔁 已在单 #${EXIST} 追加本轮读数（分级变了：fp=${FP}）"
        else
          echo "::warning::gh issue comment 失败 ⇒ 本次告警**未投递**到单 #${EXIST}"
          echo "PROD-ALERT-SUMMARY rc=3 delivered=none channel=issue reason=gh_comment_failed key=${KEY} fp=${FP}"
          exit 3
        fi
        ;;
    esac
    # 值班单必须带 priority/P1（不许因为「标签已存在」之类的原因悄悄没打上）
    "$GH_BIN" issue edit "$EXIST" --add-label "$LABEL" >/dev/null 2>&1 \
      || echo "::warning::无法给单 #${EXIST} 补标签 ${LABEL}（限流 / 权限）—— 单已存在，按标题可检索"
  fi
fi

# ── 通道 ②：Webhook（可选；只发**单行**摘要，正文/读数留在 issue）──────────────────────
if [ "$WANT_WEBHOOK" = '1' ]; then
  json_escape() {
    printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' | tr '\n' ' '
  }
  PAYLOAD=$(printf '{"source":"migao","key":"%s","bucket":"%s","fp":"%s","title":"%s","run_url":"%s"}' \
    "$(json_escape "$KEY")" "$(json_escape "$BUCKET")" "$(json_escape "$FP")" \
    "$(json_escape "$TITLE")" "$(json_escape "$RUN_URL")")
  if printf '%s' "$PAYLOAD" | "$CURL_BIN" -sS -m 20 -X POST \
      -H 'Content-Type: application/json' --data-binary @- "$WEBHOOK_URL" >/dev/null 2>&1; then
    CHANNELS_USED="${CHANNELS_USED}webhook "
    [ "$DELIVERED" = 'none' ] && DELIVERED='webhook'
    say "📣 webhook 已发出（群机器人 / 邮件转发由接收侧决定）"
  else
    echo "::warning::webhook POST 失败 ⇒ 本次告警**未投递**到 webhook"
    echo "PROD-ALERT-SUMMARY rc=3 delivered=${DELIVERED} channel=webhook reason=webhook_failed key=${KEY} fp=${FP}"
    exit 3
  fi
fi

say "通道=${CHANNELS_USED:-none} · 结果=${DELIVERED}"
echo "PROD-ALERT-SUMMARY rc=0 delivered=${DELIVERED} channels=$(printf '%s' "$CHANNELS_USED" | tr ' ' ',') issue=${ISSUE_NO:--} key=${KEY} fp=${FP}"
exit 0
