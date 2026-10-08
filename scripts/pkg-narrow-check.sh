#!/usr/bin/env bash
# =============================================================================
# pkg-narrow-check.sh — **包级定点清单**入口（issue #6250）
#
# ## 治的形态（本轮实测 4 次，逐字红因见 issue #6250）
#
# 两类改动会**必然**顶穿两条冻结台账，而它们此前只在**全量档**（`verify-all.sh gate|full`）跑到：
#
#   | 触发改动 | 会红的判据 | 逐字红因（实例） |
#   |---|---|---|
#   | 新增 / 修改 Java 测试 | `BusinessClockTestSourceGuardTest.outOfScopeSpellingsPresenceIsFrozen` | `Expecting empty but was: ["覆盖外拼写 \`System.nanoTime(\` 登记 presentInTree=false 而现取=true"]`（#6237） |
#   | 新增 `[backend-contract]` 用例且 `expectations: []` | `test_case_machine_fail_channel.py::test_i3_anchor_matches_reality_and_is_only_shrinking` | `实测 backend_contract_scoring_zero=117 与锚点 116 不一致`（#6231 / #6226 / #6224 / #6237 各一次） |
#
# 而并行修复包按「只跑定点」的纪律（`docs/wiki/Development.md`「批次统一验证」节 / D 口径）
# **必然漏掉**这两条 ⇒ 直到 CI 才红，且红因指向**包自己的 diff**（看起来像本包引入的缺陷）。
# ⇒ 本入口把那两条**必然项**提前到**本地**、并做成**零开关记忆负担**（自动探测）。
#
# ⛔ **本入口不改任何 CI 侧门禁的判据逻辑，也不替代 CI** —— 它只是把「包内定点」这份清单
#    从「人记得跑」变成「一条命令 + 自动探测」。CI 仍是权威（`migao-dev-flow` §2.1）。
#
# ## 用法
#
#   ./scripts/pkg-narrow-check.sh                       # 自动探测 + 三条轻量门禁
#   ./scripts/pkg-narrow-check.sh --java-tests          # **显式**带上「墙钟拼写台账」那条
#   ./scripts/pkg-narrow-check.sh --new-cases           # **显式**带上「用例锚点」那条
#   ./scripts/pkg-narrow-check.sh --base origin/main    # 换基准（默认 origin/main）
#   ./scripts/pkg-narrow-check.sh --dry-run             # 只打印**会跑什么 / 跳过什么 / 为什么**，不执行
#   ./scripts/pkg-narrow-check.sh --no-auto             # 关掉自动探测（只跑显式开关 + 三条轻量门禁）
#
# ## 自动探测（**默认开**；变更集 = `git diff --name-only <base>...HEAD` ∪ 工作区未提交改动）
#
#   · 出现 `src/test/**/*.java`（= Java 测试源码，Maven 标准目录）⇒ 自动带上 `--java-tests`
#   · 出现 `.github/cases/**` 或 `claims/**` 变动            ⇒ 自动带上 `--new-cases`
#
# ⚠️ 变更集按**路径**判，不看内容 —— 这是**宁滥勿缺**的方向：命中 ⇒ 多跑一条（慢，但不会漏）；
#    不命中 ⇒ 不跑并**显式打印「未跑 + 为什么」**（本仓口径：「没跑」必须长得像「没跑」）。
#    需要显式关掉自动探测时用 `--no-auto`（逃生口**只在命令行上可见**，与 `verify-all.sh --allow-package-heavy` 同口径）。
#
# ## 三条轻量门禁（**每次都跑**；都是秒级、都不拿机器级重活锁）
#
#   · `case_trust_gate --base <base>`          断言可信度（只判新增/改动的用例，不阻塞存量）
#   · `generated_artifacts_freshness.py`       生成物新鲜度（render + 逐字节比对）
#   · `test_realdb_failclosed.py`              真库判据「缺 PG ⇒ 静默变绿」的防回退锁
#
# ## 输出契约（**不许静默跳过**）
#
#   ① 每个**跑**的腿：`▶ 跑：<为什么> · <逐字命令>`；
#   ② 每个**不跑**的腿：`⏭️ 未跑：<判据名> · 触发面 = <面> · 本轮变更集里没有它 · <依据>`；
#   ③ 末尾一张**结果表**（跑了几条 / 未跑几条 / 未跑的是哪几条）。
#
# ## 退出码
#
#   0 = 所有**该跑**的腿都跑过且都绿；
#   1 = 有腿**真跑了**且非零（**只有这一种**会记 ❌）；
#   2 = 用法错误；
#   3 = **无法判定 ⇒ fail-closed**（基准取不到 / 变更集算不出来 / 变更集为空）——
#       ⚠️ `3` **不得当 `0` 读**（本仓「空跑 = 假绿」同族）。
#
# ## 测试用环境变量（默认值就是真命令；判据用它们注入桩/替身，**不改判定逻辑**）
#
#   MIGAO_PKG_JAVA_RUNNER  Java 腿的 runner（默认 `<repo>/backend/admin-api/mvnw`，cwd = backend/admin-api）
#   MIGAO_PKG_PYTHON       Python 腿的解释器（默认 = 仓库根 `.venv/bin/python`，没有则 `python3`）
# =============================================================================
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

BASE="origin/main"
DRY_RUN=0
NO_AUTO=0
FORCE_JAVA=0
FORCE_CASES=0
RC=0
RUN_N=0
declare -a RUN_LABELS=()
declare -a SKIP_LABELS=()

#: 两条必然项的**窄跑命令（逐字）** —— 文档（`docs/wiki/Development.md`）与本入口共用同一份文案。
JAVA_CMD_VERBATIM='cd backend/admin-api && MIGAO_REQUIRE_REALDB=1 ./mvnw -q -Dtest=BusinessClockTestSourceGuardTest test'
CASES_CMD_VERBATIM='MIGAO_REQUIRE_REALDB=1 python3 -m pytest tests/unit_ci_workflows/test_case_machine_fail_channel.py -q -p no:cacheprovider'

usage() {
  cat >&2 <<'USAGE'
用法：./scripts/pkg-narrow-check.sh [--java-tests] [--new-cases] [--base <ref>] [--dry-run] [--no-auto]

  --java-tests  显式带上「Java 测试树墙钟拼写台账」（BusinessClockTestSourceGuardTest）
  --new-cases   显式带上「用例锚点」（test_case_machine_fail_channel.py）
  --base <ref>  变更集基准（默认 origin/main）
  --dry-run     只打印会跑什么 / 跳过什么 / 为什么，不执行
  --no-auto     关掉自动探测（只跑显式开关 + 三条轻量门禁）

退出码：0 = 该跑的都绿；1 = 有腿跑了且非零；2 = 用法错误；3 = 无法判定 ⇒ fail-closed。
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
    --java-tests) FORCE_JAVA=1 ;;
    --new-cases)  FORCE_CASES=1 ;;
    --base)       shift; BASE="${1:-}" ;;
    --dry-run)    DRY_RUN=1 ;;
    --no-auto)    NO_AUTO=1 ;;
    -h|--help)    usage; exit 0 ;;
    *)            echo "❌ 用法错误：未知参数 '$1'" >&2; usage; exit 2 ;;
  esac
  shift
done
[ -n "$BASE" ] || { echo "❌ 用法错误：--base 需要非空 ref" >&2; exit 2; }

PY="${MIGAO_PKG_PYTHON:-}"
if [ -z "$PY" ]; then
  if [ -x "$ROOT/.venv/bin/python" ]; then PY="$ROOT/.venv/bin/python"; else PY="python3"; fi
fi
JAVA_RUNNER="${MIGAO_PKG_JAVA_RUNNER:-$ROOT/backend/admin-api/mvnw}"

echo "═══ 包级定点清单（issue #6250）· 基准 = $BASE · $(date '+%F %T %Z') ═══"

# ── 变更集（**单一来源**：已提交 ∪ 工作区未提交；与各方「禁空跑」同口径）─────────────
# ⚠️ `-uall` 不能省：默认 `--porcelain` 把整个未跟踪目录折叠成一行 `?? tests/` ⇒ 拿不到文件名
#    ⇒ 新增测试文件被漏扫（`verify-all.sh` 的同款血泪教训）。取不到 ⇒ **无法判定**（fail-closed）。
changed_file="$(mktemp)" || { echo "❌ 无法判定：mktemp 失败 ⇒ fail-closed（exit 3）。"; exit 3; }
trap 'rm -f "$changed_file"' EXIT

if ! git rev-parse --verify --quiet "$BASE" >/dev/null 2>&1; then
  echo "❌ 无法判定：基准 '$BASE' 取不到 ⇒ 变更集算不出来 ⇒ fail-closed（exit 3）。"
  echo "   复算：git rev-parse --verify --quiet '$BASE'"
  exit 3
fi
diff_committed="$(git diff --name-only "$BASE"...HEAD 2>/dev/null)" || {
  echo "❌ 无法判定：'git diff --name-only $BASE...HEAD' 失败 ⇒ fail-closed（exit 3）。"; exit 3; }
status_worktree="$(git status --porcelain -uall 2>/dev/null)" || {
  echo "❌ 无法判定：'git status --porcelain -uall' 失败 ⇒ fail-closed（exit 3）。"; exit 3; }

{
  printf '%s\n' "$diff_committed"
  printf '%s\n' "$status_worktree" | sed -E 's/^...//'
} | sed -E 's/^ *//; s/ *$//' | grep -v '^$' | sort -u > "$changed_file" || true
CHANGED_N="$(grep -c . "$changed_file" || true)"

echo "── 变更集：已提交（$BASE...HEAD）+ 工作区未提交，去重后 **$CHANGED_N** 个路径"
echo "   逐条：$(tr '\n' ' ' < "$changed_file" | cut -c1-400)"
echo "   复算：git diff --name-only $BASE...HEAD; git status --porcelain -uall"

if [ "$CHANGED_N" -eq 0 ]; then
  echo "❌ 无法判定：变更集为空 ⇒ 不跑任何腿（在零 diff 的树上跑验证没有边际信息）⇒ fail-closed（exit 3）。"
  exit 3
fi

# ── 自动探测（机械判定：只看 diff 路径；命中 ⇒ 该跑的腿一定会被带上）─────────────────
# 触发面（逐字）：
#   ① `src/test/**/*.java` —— Java 测试源码树（Maven 标准目录；打点 = 各模块自己的 src/test）
#   ② `.github/cases/**` 或 `claims/**` —— 用例库与取号台账
java_hits="$(grep -E '(^|/)src/test/.*\.java$' "$changed_file" || true)"
case_hits="$(grep -E '(^|/)\.github/cases/|(^|/)claims/' "$changed_file" || true)"

AUTO_JAVA=0; AUTO_CASES=0
[ -n "$java_hits" ] && AUTO_JAVA=1
[ -n "$case_hits" ] && AUTO_CASES=1

echo "── 自动探测（--no-auto 可关）："
if [ "$NO_AUTO" -eq 1 ]; then
  echo "   · **已按 --no-auto 关闭**（注意：这是「探测被关掉」，不是「没命中」）"
else
  echo "   · Java 测试源码触发面 '(^|/)src/test/.*\.java$'：$([ "$AUTO_JAVA" -eq 1 ] && echo '**命中** ⇒ 自动带上 --java-tests' || echo '未命中 ⇒ 不带 --java-tests')"
  [ -n "$java_hits" ] && printf '%s\n' "$java_hits" | sed -n '1,5p' | sed 's/^/       /'
  echo "   · 用例库/取号台账触发面 '(^|/)\.github/cases/|(^|/)claims/'：$([ "$AUTO_CASES" -eq 1 ] && echo '**命中** ⇒ 自动带上 --new-cases' || echo '未命中 ⇒ 不带 --new-cases')"
  [ -n "$case_hits" ] && printf '%s\n' "$case_hits" | sed -n '1,5p' | sed 's/^/       /'
fi

RUN_JAVA=$AUTO_JAVA; RUN_CASES=$AUTO_CASES
if [ "$NO_AUTO" -eq 1 ]; then RUN_JAVA=0; RUN_CASES=0; fi
[ "$FORCE_JAVA" -eq 1 ] && RUN_JAVA=1
[ "$FORCE_CASES" -eq 1 ] && RUN_CASES=1

# ── 腿（命令逐字；判据注入替身时只换 runner / 解释器，不换参数）────────────────────
JAVA_LABEL="必然项① Java 测试墙钟拼写台账（outOfScopeSpellingsPresenceIsFrozen）"
CASES_LABEL="必然项② 用例锚点（test_i3_anchor_matches_reality_and_is_only_shrinking）"
JAVA_WHY="两条必然项①：Java 测试树里新增/改写了一个「覆盖外墙钟入口」（如 System.nanoTime(）而台账没裁定 ⇒ outOfScopeSpellingsPresenceIsFrozen 判红（#6237 实例）"
JAVA_CMD="cd backend/admin-api && MIGAO_REQUIRE_REALDB=1 $JAVA_RUNNER -q -Dtest=BusinessClockTestSourceGuardTest test"
CASES_WHY="两条必然项②：新增 [backend-contract] 用例且 expectations: [] ⇒ backend_contract_scoring_zero 读数 +1 而锚点没动 ⇒ I3 判红（#6231/#6226/#6224/#6237 实例）"
CASES_CMD="MIGAO_REQUIRE_REALDB=1 $PY -m pytest tests/unit_ci_workflows/test_case_machine_fail_channel.py -q -p no:cacheprovider"

run_leg() {  # run_leg <标签> <为什么> <命令>
  local label="$1" why="$2" cmd="$3" out leg_rc
  echo "▶ 跑：$label"
  echo "      为什么跑：$why"
  echo "      逐字命令：$cmd"
  if [ "$DRY_RUN" -eq 1 ]; then echo "      （--dry-run：未执行）"; RUN_LABELS+=("$label"); RUN_N=$((RUN_N + 1)); return 0; fi
  out="$(mktemp)" || { echo "      ❌ 无法建临时输出文件 ⇒ fail-closed"; RC=3; return 0; }
  ( eval "$cmd" ) >"$out" 2>&1
  leg_rc=$?
  echo "      输出尾部（最后 6 行）："
  tail -n 6 "$out" | sed 's/^/      | /'
  rm -f "$out"
  # ⚠️ `${leg_rc}` 的花括号**不能省**：紧跟其后的是全角「（」，bash 3.2 在非 UTF-8 locale 下
  #    会把它算进变量名（`leg_rc<CJK>: unbound variable`）—— 实测踩过（桩 runner 非零时 100% 触发）。
  if [ "$leg_rc" -ne 0 ]; then echo "      ❌ 非零退出（rc=${leg_rc}）"; RC=1; else echo "      ✅ 通过"; fi
  RUN_LABELS+=("$label"); RUN_N=$((RUN_N + 1))
  return 0
}

skip_leg() {  # skip_leg <标签> <触发面> <依据>
  echo "⏭️  未跑：$1"
  echo "      触发面：$2"
  echo "      依据：$3"
  SKIP_LABELS+=("$1")
}

echo
echo "── 计划（该跑 / 未跑，逐条给依据）"

if [ "$RUN_JAVA" -eq 1 ]; then
  if [ "$FORCE_JAVA" -eq 1 ] && [ "$AUTO_JAVA" -eq 0 ]; then
    run_leg "$JAVA_LABEL" "显式 --java-tests（自动探测未命中，由命令行强制）" "$JAVA_CMD"
  else
    run_leg "$JAVA_LABEL" "自动探测命中 src/test/**/*.java" "$JAVA_CMD"
  fi
else
  skip_leg "$JAVA_LABEL" "src/test/**/*.java" \
    "$(if [ "$NO_AUTO" -eq 1 ]; then echo '--no-auto 已关闭自动探测（不是「没命中」）'; else echo "自动探测（$BASE...HEAD ∪ 工作区）里没有 src/test/**/*.java"; fi)"
fi

if [ "$RUN_CASES" -eq 1 ]; then
  if [ "$FORCE_CASES" -eq 1 ] && [ "$AUTO_CASES" -eq 0 ]; then
    run_leg "$CASES_LABEL" "显式 --new-cases（自动探测未命中，由命令行强制）" "$CASES_CMD"
  else
    run_leg "$CASES_LABEL" "自动探测命中 .github/cases/** 或 claims/**" "$CASES_CMD"
  fi
else
  skip_leg "$CASES_LABEL" ".github/cases/** 或 claims/**" \
    "$(if [ "$NO_AUTO" -eq 1 ]; then echo '--no-auto 已关闭自动探测（不是「没命中」）'; else echo "自动探测（$BASE...HEAD ∪ 工作区）里没有用例库 / 取号台账变动"; fi)"
fi

run_leg "轻量门禁①断言可信度（case_trust_gate）" \
  "每次都跑 · 只判新增/改动的用例，不阻塞存量；跑内建 burn-down 预算" \
  "$PY .github/case_trust_gate.py --base $BASE"
run_leg "轻量门禁②生成物新鲜度（render + 逐字节比对）" \
  "每次都跑 · 改了 .github/cases/** 却没提交生成物 ⇒ 具名报出（生成物 = tests/agent_eval/eval_cases.py / docs/testing/mibao-verification-cases.md）" \
  "$PY scripts/generated_artifacts_freshness.py"
run_leg "轻量门禁③真库判据防回退锁（缺 PG ⇒ 静默变绿）" \
  "每次都跑 · 判「缺 PG 时真库判据不许静默变绿」；注入了 MIGAO_REQUIRE_REALDB ⇒ 实测 skip 必须为 0" \
  "MIGAO_REQUIRE_REALDB=1 $PY -m pytest tests/unit_ci_workflows/test_realdb_failclosed.py -q -p no:cacheprovider"

echo
echo "── 结果表：跑 $RUN_N 条 / 未跑 ${#SKIP_LABELS[@]} 条"
for l in "${RUN_LABELS[@]}"; do [ -n "$l" ] && echo "   ▶ $l"; done
for l in "${SKIP_LABELS[@]}"; do [ -n "$l" ] && echo "   ⏭️  未跑：$l"; done
echo "   本入口**不做全量**：全量属于批次（scripts/batch-gate.sh）；CI 仍是权威。"
echo "   两条必然项的窄跑命令（逐字，便于人照抄）："
echo "     $JAVA_CMD_VERBATIM"
echo "     $CASES_CMD_VERBATIM"

if [ "$DRY_RUN" -eq 1 ]; then
  echo "（--dry-run：没有执行任何腿，退出码不表示红绿）"
  exit 0
fi
if [ "$RC" -eq 3 ]; then echo "❌ 无法判定 ⇒ fail-closed（exit 3）。"; exit 3; fi
if [ "$RC" -ne 0 ]; then
  echo "❌ 有腿真跑了且非零（见上面 ❌ 行）—— 先修它，别把「本地定点」交给 CI。"
  exit 1
fi
echo "✅ 该跑的腿全部通过（未跑的那几条已在上面逐条声明「未跑 + 为什么」）。"
exit 0
