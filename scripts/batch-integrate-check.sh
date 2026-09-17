#!/usr/bin/env bash
# batch-integrate-check.sh — 批量修复的集成验证（#4009 / #4023 防复发纪律的机械检查入口）
#
# 用途：对**一批**并行修复包逐分支跑同一套检查，回答「这个 PR 会不会把问题越修越多」。
# 背景：见 issue #4009「防复发执行纪律」R1~R7。纪律若只写在技能里而不落成命令，
#       就等于「加一节散文」——正是本次审计判定为「元层面重演事故点加门」的反模式。
#
# 用法:
#   ./scripts/batch-integrate-check.sh <branch> [pr_number]
#   ./scripts/batch-integrate-check.sh --all <b1> <b2> ...        # 批量（任一 FAIL ⇒ exit 1）
#   ./scripts/batch-integrate-check.sh --base <ref> <branch>      # 换基准（默认 origin/main）
#   环境变量 BIC_BASE=<ref> 等价于 --base
#
# 退出码: 0=无 FAIL；1=有 FAIL（R4 新增豁免 / 分支已落后 base / PR body 缺红证段）
#
# 自测（红证）：`./scripts/batch-integrate-check.sh origin/main` ⇒ R6 全 0 / R4 未新增 / exit=0。
#   判别力红证：分支多出豁免条目 ⇒ R4 报「新增(用例,规则)对=N」+ exit=1；只删不增 ⇒ 「移除=N / OK」。
#
# ⚠️ 比较一律用**两点** `base..branch`（tip 对 tip = 合入会产生什么），**不是三点** `base...branch`：
#    三点以 **merge-base** 为左端 ⇒ 回答的是「本分支相对 fork 点改了什么」，**不是**「合入后 base 变什么样」。
#    实证（#4023）：`origin/fix/p5-bend-order-assertions` 的 merge-base 是 `c0be8e35`，而 main 其后**已独立删掉
#    同一批豁免**（`OR-009/010/011/015 :: CASE-TRUST-NO-EFFECT-ASSERTION`）⇒ 三点会说「该分支移除=4」
#    （其实是 main 自己删的），两点才如实报「净变化 0」。用三点做前向比较 = **把别人已修好的算成本分支功劳**（假绿）。
#
# 未覆盖项（**照实登记，不把"写进技能"写成"有门禁"**；同 §19 表口径）：R1 修机制不修事故点 / R3 失败集只许收敛
#   —— 需读评测 artifact 或人工裁定，**本脚本不判**。本脚本机械覆盖 R2（PR body）/ R4 / R5 / R6 / R7（新鲜度）。
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

BASE="${BIC_BASE:-origin/main}"
while [ $# -gt 0 ]; do
  case "$1" in
    --base) BASE="${2:?--base 需要一个 ref}"; shift 2 ;;
    --all)  shift; ALL=1; BRANCHES=("$@"); break ;;
    --help|-h) sed -n 's/^# \{0,1\}//p' "$0" | sed -n '1,16p'; exit 0 ;;
    *) break ;;
  esac
done
[ -n "${ALL:-}" ] || BRANCHES=("${1:?用法: $0 <branch> [pr]}")

check_one() {
  local BR="$1" PR="${2:-}"
  git fetch origin --quiet 2>/dev/null
  local rc=0
  echo "======== $BR  (base=$BASE@$(git rev-parse --short "$BASE" 2>/dev/null || echo '?')) ========"

  echo "-- R7 前提新鲜度（分支是否基于当前 base；落后 ⇒ 后面所有 diff 都不可信）--"
  local STALE=""
  if git merge-base --is-ancestor "$BASE" "$BR" 2>/dev/null; then
    echo "  OK base 是 ${BR} 的祖先（未落后）"
  else
    # ⚠️ 变量后紧跟中文必须用 ${var} 包裹：macOS bash 3.2 会把中文首字节并入变量名（同 dev-worktree.sh 注释）
    echo "  FAIL ${BR} 落后于 ${BASE}（或无法判定）⇒ 先 rebase 到 ${BASE} 再跑本检查"
    STALE="（⚠️ 本分支落后，以下差值含 base 单方前进的部分，不可读成本分支的净贡献）"
    rc=1
  fi

  echo "-- R6 净变更量 ${STALE}--"
  git diff --numstat "$BASE..$BR" -- backend/ 2>/dev/null > "$TMP/ns.txt"
  python3 - "$TMP/ns.txt" <<'PY'
import sys
a=d=pa=pd=ta=td=0
for line in open(sys.argv[1]):
    p=line.split('\t')
    if len(p)<3: continue
    try: add,dele=int(p[0]),int(p[1])
    except ValueError: continue
    path=p[2]; a+=add; d+=dele
    if path.startswith('backend/ai-agent-service/app/'): pa+=add; pd+=dele
    if '/tests/' in path and path.endswith('.py'): ta+=add; td+=dele
print(f"  backend 全部: +{a}/-{d} (净{a-d:+d})")
print(f"  app/** 产品代码: +{pa}/-{pd} (净{pa-pd:+d})   <- R6 要求 <=0")
print(f"  tests/**: +{ta}/-{td} (净{ta-td:+d})")
PY

  echo "-- R4 豁免清单只许删除（解析后按「(用例,规则) 对」比较，不用行正则）--"
  if git diff --quiet "$BASE..$BR" -- .github/case-trust-baseline.json 2>/dev/null; then
    echo "  OK 合入不改变 case-trust-baseline.json（= 未新增豁免）"
  else
    git show "$BASE:.github/case-trust-baseline.json" > "$TMP/bo.json" 2>/dev/null
    git show "$BR:.github/case-trust-baseline.json"   > "$TMP/bn.json" 2>/dev/null
    python3 - "$TMP/bo.json" "$TMP/bn.json" <<'PY' || rc=1
import sys, json
def load(p):
    d=json.load(open(p)); s=set()
    for c,v in (d.get('violations') or {}).items():
        for code in (v.get('codes') or []): s.add((c,code))
    return s,d
try: old,do=load(sys.argv[1]); new,dn=load(sys.argv[2])
except Exception as e: print(f"  FAIL 解析失败: {e}"); raise SystemExit(1)
added=sorted(new-old); removed=sorted(old-new)
print(f"  新增(用例,规则)对={len(added)} 移除={len(removed)}")
for c,r in removed[:8]: print(f"    - {c} :: {r}")
if added:
    print("  FAIL 违规：新增了豁免条目（R4：新发现的违规只有两个出口 = 本次修掉 / 登记独立 issue）")
    for c,r in added[:10]: print(f"    + {c} :: {r}")
    print("  ⚠️ 若本分支落后 base（见 R7）：这些多半是 base 单方删掉、而本分支快照里还在 ⇒ 先 rebase 再判")
    raise SystemExit(1)
print("  OK 只删不增")
print(f"  meta: 违规用例数 {do.get('violation_case_count')} -> {dn.get('violation_case_count')}"
      f" | case_total {do.get('case_total')} -> {dn.get('case_total')}"
      f" | anchor {str(do.get('anchor_sha'))[:8]} -> {str(dn.get('anchor_sha'))[:8]}")
PY
  fi

  echo "-- R5a 新增 fail-closed 是否带 suggestion --"
  local D; D=$(git diff "$BASE..$BR" -- 'backend/ai-agent-service/app/tools/*.py' 2>/dev/null)
  if [ -z "$D" ]; then echo "  (未改 app/tools/*.py)"; else
    local NF NS
    NF=$(printf '%s\n' "$D" | grep -cE '^\+.*success=False' || true)
    NS=$(printf '%s\n' "$D" | grep -cE '^\+.*suggestion=' || true)
    echo "  新增 success=False: $NF  新增 suggestion=: $NS"
    [ "${NF:-0}" -le "${NS:-0}" ] && echo "  OK" || echo "  WARN 需 PR 说明是否为配置错误级拒绝"
  fi

  echo "-- R5b 新增中文词表常量（三点：只看本分支自己新增的行）--"
  git diff "$(git merge-base "$BASE" "$BR" 2>/dev/null || echo "$BASE")".."$BR" \
      -- 'backend/ai-agent-service/app' 2>/dev/null > "$TMP/ad.txt"
  python3 - "$TMP/ad.txt" <<'PY'
import sys, re
add=[l[1:] for l in open(sys.argv[1],errors='ignore') if l.startswith('+') and not l.startswith('+++')]
pat=re.compile(r'^[A-Z_]{3,}\s*[:=]'); cjk=re.compile(r'[\u4e00-\u9fff]')
h=[l.rstrip() for l in add if pat.match(l) and cjk.search(l)]
print("  OK 未新增" if not h else f"  WARN 新增 {len(h)} 条（R5：判据应建立在已有事实上，不靠措辞语料）")
for x in h[:5]: print("     ", x[:100])
PY

  echo "-- R2 红证面：PR body 证据段 --"
  if [ -n "$PR" ]; then
    local BODY; BODY=$(gh pr view "$PR" --json body --jq .body 2>/dev/null)
    for k in 红证 负例 净行数; do
      printf '%s' "$BODY" | grep -q "${k}" && echo "  OK 含「${k}」" || { echo "  MISS 缺「${k}」段"; rc=1; }
    done
    printf '%s' "$BODY" | grep -qE 'Closes #[0-9]+' && echo "  OK 含 Closes #N" || echo "  MISS 缺 Closes #N"
  else echo "  (未给 PR 号，跳过)"; fi

  echo "-- 改动文件（核查越界；两点 = 合入后 base 的实际差异）--"
  git diff --name-only "$BASE..$BR" 2>/dev/null | sed 's/^/  /' | head -25
  echo
  return $rc
}

if [ -n "${ALL:-}" ]; then
  fail=0
  for b in "${BRANCHES[@]}"; do
    check_one "$b" || fail=1
    echo
  done
  exit $fail
fi
check_one "${BRANCHES[0]}" "${2:-}"