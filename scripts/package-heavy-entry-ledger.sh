#!/usr/bin/env bash
# =============================================================================
# package-heavy-entry-ledger.sh — 套件内全量入口的**角色判定台账**（issue #6084）
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
# ## 缺头自愈（issue #7655）
#
# 首行不是 schema 头时**不直接判 3**：先**逐行结构校验**（每行可解析 JSON 对象且带
# `id/ts/role/decision` 四键）—— 全部合格 ⇒ 补写首行头后继续追加（幂等、可重入）；
# 任何一行不合格 ⇒ 仍 `exit 3` + 原文案（**拒绝往一份不认识的账上追加**）。
# 判据是**逐行结构**，不是文件名 / 路径：换了路径的同一种账照样认，别人的账一行都不合格就照样拒。
# 边界：补头是「读 → 写临时文件 → rename」，**并发自愈**的窄窗口里另一侧追加可能落空
# （重启条件 = 观测到同一台账的并发自愈；届时再加锁，不提前造）。
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

#: 首行 schema 头（**单一出处**）：空台账创建与「缺头自愈」都只从这里取。
_header() {
  printf '%s\n' \
    "{\"_kind\":\"${LEDGER_KIND}\",\"_what\":\"套件内全量入口的角色判定台账（只追加）：每次 verify-all.sh 被角色守卫拒绝 / 被显式 --allow-package-heavy 放行，记一条。\",\"_judged_by\":\"tests/unit_ci_workflows/test_package_heavy_entry_ban.py · tests/unit_ci_workflows/test_package_heavy_entry_ledger_header.py\",\"_idempotency\":\"键 = MIGAO_ROLE_LEDGER_ID（同一进程树内只记一笔）\",\"_count\":\"./scripts/package-heavy-entry-ledger.sh count\"}"
}

#: 逐行结构校验（**只在「首行不是头」那条自愈分支上跑**）：每一行都是可解析的 JSON 对象且带
#: `id` / `ts` / `role` / `decision` 四键 ⇒ 0；否则 1（stderr 指出首条不合格行）。
#: ⚠️ 正常追加路径**不经过**这里 ⇒ 本文件「append 不引 python3」的约束不变。
_records_are_wellformed() {
  python3 - "$LEDGER" <<'PY'
import json
import sys

KEYS = ("id", "ts", "role", "decision")
for no, line in enumerate(open(sys.argv[1], encoding="utf-8"), 1):
    if not line.strip():
        print(f"第 {no} 行是空行（JSONL 不允许空行）", file=sys.stderr)
        sys.exit(1)
    try:
        rec = json.loads(line)
    except ValueError:
        print(f"第 {no} 行不是合法 JSON", file=sys.stderr)
        sys.exit(1)
    if not isinstance(rec, dict):
        print(f"第 {no} 行不是 JSON 对象", file=sys.stderr)
        sys.exit(1)
    missing = [k for k in KEYS if k not in rec]
    if missing:
        print(f"第 {no} 行缺键 {missing}（不是本台账的记录）", file=sys.stderr)
        sys.exit(1)
sys.exit(0)
PY
}

#: 文件不存在 / 空 ⇒ 写一次头；首行是头 ⇒ 直接继续；首行**不是**头 ⇒ **逐行结构校验全部合格才补头**
#: （自愈，issue #7655），任何一行不合格 ⇒ `exit 3`（绝不覆盖别人的台账）。
_ensure_header() {
  local dir
  dir="$(dirname "$LEDGER")"
  [ -d "$dir" ] || mkdir -p "$dir" 2>/dev/null || _die_undecidable "台账目录建不出来：$dir"
  if [ -s "$LEDGER" ]; then
    head -1 "$LEDGER" | grep -q "\"${LEDGER_KIND}\"" && return 0
    command -v python3 >/dev/null 2>&1 \
      || _die_undecidable "台账首行不是 ${LEDGER_KIND}（${LEDGER}）—— 无 python3 无法逐行校验，拒绝往一份不认识的账上追加"
    _records_are_wellformed \
      || _die_undecidable "台账首行不是 ${LEDGER_KIND}（${LEDGER}）—— 拒绝往一份不认识的账上追加"
    local tmp
    tmp="$(mktemp "${LEDGER}.heal.XXXXXX")" || _die_undecidable "台账自愈临时文件建不出来：${LEDGER}"
    { _header; cat "$LEDGER"; } > "$tmp" && mv -f "$tmp" "$LEDGER" \
      || { rm -f "$tmp"; _die_undecidable "台账首行补写失败：${LEDGER}"; }
    echo "🩹 自愈：台账首行缺 schema 头，已按逐行结构校验补齐后继续追加（${LEDGER}）" >&2
    return 0
  fi
  _header >> "$LEDGER" || _die_undecidable "台账首行写不进去：${LEDGER}"
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
