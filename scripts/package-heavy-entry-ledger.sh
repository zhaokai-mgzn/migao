#!/usr/bin/env bash
# =============================================================================
# package-heavy-entry-ledger.sh — 套件内全量入口的**角色判定台账**（issue #6078）
#
# ## 这条命令治什么
#
# `verify-all.sh` 现在会**拒绝**在**子包 worktree** 里直跑全量（那里的那一次全量属于**批次**，
# 见 `scripts/batch-gate.sh`）。「拒绝 / 显式放行」这类**判定**必须留读数 —— 否则它和
# 「什么都没发生」在事后长得一模一样（本仓反复踩过的形态：**没跑**必须长得像**没跑**）。
#
# ## 台账形态（**只追加**）
#
# JSON Lines：第 1 行是人类可读的 schema 头（`_kind` / `_what` / `_invariants`），其余每行一条
# **判定记录**。为什么是 JSONL 而不是一个 JSON 数组：
#   ① **只追加**（O_APPEND 是原子的，短行 < PIPE_BUF）⇒ 并发写不互相踩、也不丢历史；
#   ② 判据要能「只看新增的那一条」而不必解析整份文件（`tail -1`）。
#
# ## 幂等（同一次调用不重复计数）
#
# 键 = `MIGAO_ROLE_LEDGER_ID`（`verify-all.sh` 在**顶层**初始化一次并 export）。
# 本脚本按该键**先在文件里找**：已有同 id 的记录 ⇒ **不重复追加**（`dup`）。子 shell / 重复调用
# 因此不会给同一次调用记两笔；而**重新跑一次命令**（新的进程 ⇒ 新的 id）照旧记一笔新的 ——
# 「幂等」的射程是**同一次调用**，不是「永远只记一笔」（后者会把台账变成一次性开关）。
#
# ## 现取计数（拒绝 / 放行**分开**报）
#
#   ./scripts/package-heavy-entry-ledger.sh count
#
# 输出两行（`refused=<n>` / `override=<n>`），各自**现取**。为什么要分两类：本台账正是
# `docs/wiki/Dev-Mode-Balance.md` §10 那条「批次粒度」优化的**重启条件**（≥5 次批次记录）要用的
# 读数 —— 把「被拦下的浪费」和「人类明知故犯的放行」混成一个数，两者都读不出来。
#
# 退出码：0 = 成功（含「台账里还没有本 id 的记录」这种正常情形）；
#         2 = 用法错误；3 = 无法判定（台账文件 / 目录写不进去 —— fail-closed，**不得当 0 读**）。
# =============================================================================
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LEDGER="${MIGAO_PACKAGE_HEAVY_LEDGER:-$ROOT/tests/unit_ci_workflows/package_heavy_entry_ledger.jsonl}"

#: 台账首行（schema 头）。判据与读出口径都按 `_kind` 认对象 —— 换文件不会静默读错东西。
readonly LEDGER_KIND="migao.package-heavy-entry-ledger"

_usage() {
  cat >&2 <<'USAGE'
用法：
  ./scripts/package-heavy-entry-ledger.sh append <role> <decision> [<why>]
      追加一条**判定记录**（幂等键 = MIGAO_ROLE_LEDGER_ID；重复调用同 id ⇒ 不重复追加）
        role     = primary | batch-integration | package | ci | unknown
        decision = refused | override
  ./scripts/package-heavy-entry-ledger.sh count
      现取计数（refused=<n> / override=<n>），**两类分开报**
  ./scripts/package-heavy-entry-ledger.sh cat
      打印台账全文（第 1 行为 schema 头）

环境变量：
  MIGAO_PACKAGE_HEAVY_LEDGER  台账路径（判据把它指到 tmp_path；**不改默认路径**）
  MIGAO_ROLE_LEDGER_ID        幂等键（verify-all.sh 顶层生成并 export）

退出码：0 = 成功；2 = 用法错误；3 = 无法判定（写不进去 ⇒ fail-closed，不得当 0 读）。
USAGE
}

_die_undecidable() {
  echo "❌ 无法判定（exit 3）：$*" >&2
  echo "   （这不是「通过」—— 台账不可用 ⇒ 判定读数会**静默消失**，先修路径/权限再跑）" >&2
  exit 3
}

#: 首行 schema 头（**创建时写一次**；已存在且首行不同 ⇒ 判 3，绝不覆盖别人的台账）。
_ensure_header() {
  local dir
  dir="$(dirname "$LEDGER")"
  [ -d "$dir" ] || mkdir -p "$dir" 2>/dev/null || _die_undecidable "台账目录建不出来：$dir"
  if [ -s "$LEDGER" ]; then
    head -1 "$LEDGER" | grep -q "\"${LEDGER_KIND}\"" \
      || _die_undecidable "台账首行不是 ${LEDGER_KIND}（${LEDGER}）—— 拒绝往一份不认识的账上追加"
    return 0
  fi
  printf '%s\n' \
    "{\"_kind\":\"${LEDGER_KIND}\",\"_what\":\"套件内全量入口的角色判定台账（只追加）：每次 verify-all.sh 被角色守卫拒绝 / 被显式 --allow-package-heavy 放行，记一条。\",\"_judged_by\":\"tests/unit_ci_workflows/test_package_heavy_entry_ban.py\",\"_idempotency\":\"键 = MIGAO_ROLE_LEDGER_ID（同一进程树内只记一笔）\",\"_count\":\"./scripts/package-heavy-entry-ledger.sh count\"}" \
    >> "$LEDGER" || _die_undecidable "台账首行写不进去：$LEDGER"
}

#: 本 id 是否已在账上（幂等）。⚠️ `grep -F` 用**整串**（id 形如 `<epoch>.<pid>.<rand>`，
#: 含 `.` ⇒ 用正则会把 `.` 当通配符，可能命中别人的 id = 假幂等）。
_seen() {
  [ -s "$LEDGER" ] || return 1
  grep -qF "\"id\":\"$1\"" "$LEDGER" 2>/dev/null
}

_cmd_append() {
  local role="${1:-}" decision="${2:-}" why="${3:-}"
  [ -n "$role" ] && [ -n "$decision" ] || { _usage; exit 2; }
  case "$role" in
    primary|batch-integration|package|ci|unknown) ;;
    *) echo "未知 role：${role}（见 --help 用法）" >&2; exit 2 ;;
  esac
  case "$decision" in
    refused|override) ;;
    *) echo "未知 decision：${decision}（只认 refused / override）" >&2; exit 2 ;;
  esac
  _ensure_header
  local id="${MIGAO_ROLE_LEDGER_ID:-}"
  if [ -z "$id" ]; then
    # 没有幂等键 ⇒ 现场生成一个（独立调用本命令的形态；同一次调用仍只记一笔）。
    id="$(date +%s).$$"
  fi
  if _seen "$id"; then
    echo "dup（同一次调用已记过，不重复追加）：id=${id}"
    return 0
  fi
  local cwd_raw
  cwd_raw="$(git -C "$ROOT" rev-parse --show-toplevel 2>/dev/null || echo "$ROOT")"
  #: ⚠️ 这里**手写** JSON 转义（只有 `\` 与 `"` 两种在路径/说明里可能出现；`\n` 不进这一列）。
  #: 不引 python3 是为了让 `append` 在**任何**环境都能跑（它是拒绝路径上的记账，不是重活）。
  local cwd why_esc
  cwd="$(printf '%s' "$cwd_raw" | sed 's/\\/\\\\/g; s/"/\\"/g')"
  why_esc="$(printf '%s' "$why" | tr '\n' ' ' | sed 's/\\/\\\\/g; s/"/\\"/g')"
  printf '{"id":"%s","ts":"%s","role":"%s","decision":"%s","at":"%s","why":"%s"}\n' \
    "$id" "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$role" "$decision" "$cwd" "$why_esc" >> "$LEDGER" \
    || _die_undecidable "台账追加失败：$LEDGER"
  echo "recorded（role=${role} / decision=${decision}）：$LEDGER"
}

#: 计数：**两类分开报**（把基线（表头）那行排除掉 —— 它没有 `"decision"` 键）。
_cmd_count() {
  [ -f "$LEDGER" ] || { echo "refused=0"; echo "override=0"; echo "（台账尚不存在：${LEDGER}）" >&2; return 0; }
  local refused override
  refused="$(grep -c '"decision":"refused"' "$LEDGER" 2>/dev/null || true)"
  override="$(grep -c '"decision":"override"' "$LEDGER" 2>/dev/null || true)"
  echo "refused=${refused:-0}"
  echo "override=${override:-0}"
}

_cmd_cat() {
  [ -f "$LEDGER" ] || { echo "（台账尚不存在：${LEDGER}）" >&2; return 0; }
  cat "$LEDGER"
}

case "${1:-}" in
  append) shift; _cmd_append "$@" ;;
  count)  _cmd_count ;;
  cat)    _cmd_cat ;;
  -h|--help|"") _usage; [ -z "${1:-}" ] && exit 2 || exit 0 ;;
  *) echo "未知子命令：$1" >&2; _usage; exit 2 ;;
esac
