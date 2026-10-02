#!/usr/bin/env bash
# =============================================================================
# batch-gate.sh — 批次统一验证入口：**N 个包只跑一次全量 `gate`**（issue #6012）
#
# ## 治的形态（2026-10-02 17:24–17:29 CST 现场，读数现取，不是推断）
#
#   机器级重活锁：1 个 `gate` 持锁、**7 个 gate 在跑**（6 个在排队：已等 40 / 31 / 20 / 12 / 7 / 2 分钟）、
#   日志里最高排队读数 `已等 2354s / 上限 2400s`；`load average` **21.6 / 43.6 / 61.3**（8 核）。
#   ⇒ 类级病 = **「每个包各自跑一遍全量」× 「本机 8 核只装得下一份全量」**。
#   排他锁（`machine-heavy-lock.sh`，#5814/#5863）治的是 CPU 争用，治不了「份数」。
#
#   本命令治**份数**：把 N 个包合到一个**集成工作区**，全量只跑**一次**。
#   实测对照（同一天）：现状 = N × gate（单包进程寿命 49 分钟，其中 33 分钟在等锁）；
#   本命令 = merge N 次 + gate **1** 次。
#
# ## 为什么「一次」是这条命令的全部意义
#
#   `gate` 档里唯一的重活是 `ci workflow helper 判据集`（整目录 `tests/unit_ci_workflows`），
#   而它的触发面 = 变更集命中 `.github/**` 或 `tests/unit_ci_workflows/**` —— 今天的包**几乎每个**
#   都在加类级判据/台账（AGENTS.md 铁律 8）⇒ 每包都必然触发那条最重的腿。故「N 份全量」是
#   **结构性**的，不是偶发。集成层本来就是这些判据互相影响的地方 ⇒ 一次跑在**合起来之后**更有效。
#
# ## 用法
#
#   ./scripts/batch-gate.sh <branch> [<branch> ...]   # 建临时集成 worktree → 串行 merge → **一次** gate → 逐包归因
#   ./scripts/batch-gate.sh --in <worktree> <branch> ...   # 在**既有**集成 worktree 里只跑那一次（环境已备时用）
#   ./scripts/batch-gate.sh --keep <branch> ...       # 保留集成 worktree（默认结束即删）
#   ./scripts/batch-gate.sh --base <ref> <branch> ... # 换基准（默认 origin/main）
#
#   环境变量：`MIGAO_HEAVY_WAIT=<秒>`（默认 2700）—— 透传给 gate 的排队上限。
#
# ## 退出码（三态，与 merge_gate.py / stranding-check.sh 同口径）
#
#   0 = 那一次 gate 全绿
#   1 = 红（**整合冲突** / gate 非零）—— 冲突时**不跑** gate：「没跑」必须长得像「没跑」
#   3 = 无法判定（分支不存在 / 建不出 worktree / gate 自己 exit 3）—— **不得当 0 读**
#
# ## 边界（照实登记）
#
#   - 归因是**面级映射**（算的是「这个包碰没碰失败腿的触发面」），**不是**「这个包就是真凶」的证明；
#     面内多于一个包时**不许**指认唯一真凶，具名打印 `无法唯独归因`。
#   - 集成 worktree 里 merge ≠ GitHub squash 合并后的 main，是**起飞前**的近似（冲突照实报）。
#   - 本脚本**不自己拿锁**：那一次全量由 `verify-all.sh gate` 自己 acquire/release（#5814 接线）。
#   - 本脚本**不改**任何门禁的通过条件、不新增豁免；CI 仍是权威。
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BASE="${BATCH_GATE_BASE:-origin/main}"
KEEP=0
IN_WT=""
BRANCHES=()

while [ $# -gt 0 ]; do
  case "$1" in
    --in)   IN_WT="${2:-}"; [ -n "$IN_WT" ] || { echo "用法: $0 --in <worktree>" >&2; exit 2; }; shift 2 ;;
    --base) BASE="${2:-}"; [ -n "$BASE" ] || { echo "用法: $0 --base <ref>" >&2; exit 2; }; shift 2 ;;
    --keep) KEEP=1; shift ;;
    -h|--help) sed -n 's/^# \{0,1\}//p' "$0" | sed -n '1,36p'; exit 0 ;;
    -*)     echo "未知参数：$1（用法见 $0 --help）" >&2; exit 2 ;;
    *)      BRANCHES+=("$1"); shift ;;
  esac
done

if [ "${#BRANCHES[@]}" -eq 0 ]; then
  echo "用法: $0 <branch> [<branch> ...] ｜ $0 --in <worktree> <branch> ..." >&2
  echo "      （本命令的全部意义 = 让这批包的全量**只跑一次**，见文件头）" >&2
  exit 2
fi

TMP="$(mktemp -d)"
WT=""
OWNS_WT=0
cleanup() {
  if [ "$OWNS_WT" = 1 ] && [ "$KEEP" = 0 ]; then
    git -C "$ROOT" worktree remove --force "$WT" >/dev/null 2>&1 || true
  fi
  rm -rf "$TMP"
}
trap cleanup EXIT

# 无法判定 ⇒ 出声 + 非零（**不是**「通过」）
die() { echo "❌ $*" >&2; echo "exit=3（无法判定 —— 不是「通过」）" >&2; exit 3; }

# ── 1) 解析每个包分支到 commit（本地优先，其次 origin/<branch>）────────────────
for b in "${BRANCHES[@]}"; do
  sha="$(git -C "$ROOT" rev-parse --verify --quiet "${b}^{commit}" \
      || git -C "$ROOT" rev-parse --verify --quiet "origin/${b}^{commit}" || true)"
  # ⚠️ 变量后紧跟中文必须用 ${var} 包裹：macOS bash 3.2 会把中文首字节并入变量名（同 dev-worktree.sh）
  [ -n "$sha" ] || die "分支不存在（本地与 origin 都没有）：${b}"
  printf '%s\t%s\n' "$b" "$sha" >> "$TMP/branches.tsv"
done

BASE_SHA="$(git -C "$ROOT" rev-parse --short "$BASE" 2>/dev/null || echo '?')"
echo "批次数：${#BRANCHES[@]} 个包｜基准：${BASE}@${BASE_SHA}"
echo "包：${BRANCHES[*]}"

# ── 2) 集成工作区 + 串行 merge（合并串行 = §17.1 第 4 步）───────────────────────
if [ -n "$IN_WT" ]; then
  WT="$IN_WT"
  [ -d "$WT" ] || die "--in 的目录不存在：${WT}"
  echo "集成工作区（既有）：${WT}"
else
  WT="$ROOT/../migao-wt/batch-$(date +%m%d-%H%M%S)"
  git -C "$ROOT" worktree add --detach "$WT" "$BASE" >/dev/null 2>&1 \
    || die "建不出集成 worktree（${WT}；基准 ${BASE} 可解析吗）"
  OWNS_WT=1
  echo "集成工作区（临时，结束即删；--keep 保留）：${WT}"
fi

merge_failed=""
while IFS=$'\t' read -r b sha; do
  if git -C "$WT" merge --no-edit --no-ff "$sha" >"$TMP/merge.log" 2>&1; then
    echo "  merge ✅ ${b}"
  else
    git -C "$WT" merge --abort >/dev/null 2>&1 || true
    echo "  merge ❌ ${b}（整合冲突）—— 冲突行："
    grep -E '^CONFLICT' "$TMP/merge.log" | sed 's/^/     /' | head -10
    merge_failed="$b"
    break
  fi
done < "$TMP/branches.tsv"

if [ -n "$merge_failed" ]; then
  echo "⛔ 整合失败（${merge_failed}）⇒ **没有跑**那一次 gate。没跑 ≠ 通过。"
  echo "   出口：解冲突（./scripts/sync-main.sh --rebase 或人工）后重跑本条命令"
  [ "$OWNS_WT" = 1 ] && echo "   集成工作区：${WT}（加 --keep 可保留现场）"
  exit 1
fi

# ── 3) **那一次**全量（本命令的全部意义；锁由 verify-all.sh gate 自己拿）────────
LOG="$TMP/gate.log"
echo "── 一次 gate（本批唯一一次全量；MIGAO_HEAVY_WAIT=${MIGAO_HEAVY_WAIT:-2700}）──"
( cd "$WT" && MIGAO_HEAVY_WAIT="${MIGAO_HEAVY_WAIT:-2700}" ./verify-all.sh gate ) >"$LOG" 2>&1
gate_rc=$?
tail -30 "$LOG" | sed 's/^/  | /'

# ── 4) 逐包归因（面级映射；多于一个候选 ⇒ 不指认唯一真凶）──────────────────────
python3 - "$TMP" "$BASE" "$ROOT" "$LOG" <<'PY'
import re, subprocess, sys, pathlib

tmp, base, root, log_path = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
branches = [ln.split("\t") for ln in pathlib.Path(tmp, "branches.tsv").read_text().split("\n") if ln]
log = pathlib.Path(log_path).read_text(errors="ignore")

#: 面 → 触发前缀（与 verify-all.sh 的 *_face_paths() 同源语义；这里是**归因用**的粗映射）
FACES = [
    ("ci workflow helper", (".github/", "tests/unit_ci_workflows/")),
    ("cases 面门禁", (".github/cases/", ".github/case-trust-", "tests/agent_eval/eval_cases.py",
                    "docs/testing/mibao-verification-cases.md")),
    ("bmini-app", ("frontend/bmini-app/", "frontend/admin-web/src/lib/print-media.json")),
    ("admin-api", ("backend/admin-api/",)),
    ("ai-agent", ("backend/ai-agent-service/",)),
    ("admin-web", ("frontend/admin-web/",)),
]

files = {}
for name, sha in branches:
    out = subprocess.run(["git", "-C", root, "diff", "--name-only", f"{base}...{sha}"],
                         capture_output=True, text=True).stdout
    files[name] = [f for f in out.split("\n") if f]

print("── 逐包改动面 ──")
for name, sha in branches:
    fs = files[name]
    print(f"  {name}: {len(fs)} 个文件" + (f"（{', '.join(fs[:4])}{' …' if len(fs) > 4 else ''}）" if fs else ""))

def candidates(prefixes):
    return [n for n, _ in branches if any(f.startswith(prefixes) for f in files[n])]

fails = [ln.strip() for ln in log.split("\n")
         if ln.strip().startswith("❌") or ln.strip().startswith("失败项:")]
print("── 逐包归因（面级映射，不是「真凶」的证明）──")
if not fails:
    print("  本次没有具名失败项（gate 全绿或未产出失败项）")
seen = set()
for f in fails:
    if f in seen:
        continue
    seen.add(f)
    hit = [name for name, segs in FACES if name in f]
    print(f"  失败项：{f}")
    if not hit:
        print("     面：**无法映射**（不认识这项）⇒ 不猜，见上面的失败项原文")
        continue
    for h in hit:
        cands = candidates(dict(FACES)[h])
        print(f"     面：{h}（触发前缀：{'、'.join(dict(FACES)[h])}）")
        if not cands:
            print("     面内包：**无**（本批没有包碰这个面 ⇒ 该红可能来自基准侧或环境）")
        elif len(cands) == 1:
            print(f"     面内包（可能引入方）：{cands[0]}")
        else:
            print(f"     面内包：{'、'.join(cands)} —— **无法唯独归因**（面内多于一个包）")
PY
attr_rc=$?

echo "── 结论 ──"
if [ "$gate_rc" -eq 0 ]; then
  echo "✅ 本批 ${#BRANCHES[@]} 个包 = **1 次** gate（绿）。判别力：包数变而 gate 调用数不变。"
  exit 0
fi
if [ "$gate_rc" -eq 3 ]; then
  echo "⚠️ 那一次 gate exit=3（**无法判定**：零变更 / 门禁未就绪等）—— 不得当「通过」读。"
  exit 3
fi
echo "❌ 那一次 gate exit=${gate_rc} ⇒ 本批未通过（逐包归因见上；面级映射 ≠ 真凶证明）"
[ "$attr_rc" -ne 0 ] && echo "   （归因段自身退出码非零：${attr_rc}）"
exit 1
