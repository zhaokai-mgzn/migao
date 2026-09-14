#!/usr/bin/env bash
# =============================================================================
# verify-all.sh — MIGAO 三模块一键测试（开发自查用）
#
# 用法：
#   ./verify-all.sh quick          # 快速：三模块核心测试（~3-5 分钟）
#   ./verify-all.sh full           # 全量：三模块全量单测（~10-15 分钟）
#   ./verify-all.sh frontend       # 仅前端（vitest + tsc）
#   ./verify-all.sh backend        # 仅 Java 后端
#   ./verify-all.sh agent          # 仅 AI Agent
#   ./verify-all.sh gate           # 仅 QA Growth Gate 预检（本地跑 CI 规则）
#
# ⚠️ gate 档的扫描源是**已提交**的 diff（`git diff … origin/main...HEAD`）：工作区有未提交改动
#    时，按已提交 diff 扫描的部分（缺测/case_ids 追溯）**覆盖不到它们** —— 脚本会**点名该范围**
#    并打 `::warning::`（在控制台可见），**不因「未提交」本身失败**；弱断言检查已改成
#    「已提交新增 ∪ 工作区新增」，所以提交前跑也真的有效（issue #3724：旧实现把空集静默当通过）。
#
# 返回码：全部通过=0，任一失败=1。开发自查与 CI 用同一命令。
# =============================================================================
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PASS=0
FAIL=0
declare -a FAILED

report() {
  local name="$1"; shift
  # ⚠️ 日志路径必须**按检查项唯一**：此前是固定的 /tmp/verify-all-$$.log（$$ 是 shell PID，
  #    整个进程内不变）→ 每个检查项都覆盖同一个文件 → 多项失败时只剩最后一项的日志，
  #    "日志: xxx" 指向的内容与失败项对不上，现场排查当场被带偏。
  local slug
  slug="$(printf '%s' "$name" | tr -c '[:alnum:]' '-' | sed 's/-\{2,\}/-/g; s/^-//; s/-$//')"
  local log="/tmp/verify-all-$$-${slug}.log"
  local rc=0
  "$@" > "$log" 2>&1
  rc=$?
  if [ "$rc" -eq 0 ]; then
    # 「带条件的通过」必须看得见（issue #3724）：检查项可在日志里用 `::warning::` 行声明
    # 「本次通过**未覆盖**哪些范围」，这里把它抬到控制台 —— 否则告警只躺在日志里，
    # 而控制台只有 ✅，等于**事实上的静默通过**（本 issue 要消除的正是这个形态）。
    sed -n 's/^::warning:: *//p' "$log" | sed 's/^/  ⚠️ /'
    echo "✅ $name"
    PASS=$((PASS + 1))
  else
    echo "❌ $name (exit $rc) — 日志: $log"
    FAIL=$((FAIL + 1))
    FAILED+=("$name")
  fi
}

# 评测用例覆盖体检（B/C 两端）—— 与 pr-check 的 `Case Coverage Gate` job **同一脚本、
# 同一参数**（判据在 scripts/case_coverage.py 单一实现），避免「本地绿 CI 红」。
# 拦什么（结构性缺失）：工具 0 用例 / 只有拒绝式断言而没有任何正向用例 / 用例挂错端 /
#                      断言了两端都没有的工具 / 端用例集为空。
# 不拦什么（活指标）：某工具仅 1 条用例的"厚度不足"——缺口数是随迭代收敛的活指标，
#                    硬编码阈值会制造返工式门禁（issue #3555 判据设计；旧注释见下）。
# 不加 --max-uncovered：同上，缺口数不设硬阈值。
case_coverage_check() {
  local persona
  for persona in xiaobu mibao; do
    echo "  🔍 ${persona} 评测覆盖体检"
    python3 "scripts/${persona}_coverage.py" --check || return 1
  done
}

gate_check() {
  echo "── [QA Growth Gate] 本地预检（与 pr-check qa-growth-gate 同规则，含 G5 case_ids 追溯）──"
  git fetch origin main --quiet 2>/dev/null || true
  CHANGED=$(git diff --name-only origin/main...HEAD 2>/dev/null || echo "")
  # 未提交改动（issue #3724）：本函数的扫描源 `git diff … origin/main...HEAD` **只含已提交内容**。
  # 「因为没提交所以扫不到」与「确实没有变更」必须可区分 —— 旧实现把两者一视同仁地打印
  # 「跳过」+ return 0（✅ 假绿：绿了但没跑，与 migao-acceptance v1.3「空跑」同族）；
  # 后果是「本地绿 / CI 红」（新增测试里的弱断言在提交后才被 CI 的同一检查抓到）。
  # ⚠️ `-uall` 不能省：默认 `--porcelain` 会把**整个未跟踪目录**折叠成一行 `?? tests/`，
  #    新增测试所在的目录若本身还没入库，这一行既匹配不上测试文件过滤、也拿不到文件名
  #    ⇒ 工作区新增测试又被漏扫（缺陷原地复发，实测）。`-uall` 展开到文件级。
  UNCOMMITTED=$(git status --porcelain -uall 2>/dev/null || echo "")
  # 工作区新增/未跟踪的测试文件（弱断言扫描必须能看到它们，见下）
  # ⚠️ 用 `awk`（POSIX）而非 `sed 's/^\(A\|??\)…'`：`\|` 交替是 GNU 扩展，macOS 自带
  #    BSD sed 不认（静默不匹配 ⇒ 工作区新增文件又被漏扫，缺陷原地复发，实测）。
  WORKTREE_NEW_TESTS=$(printf '%s\n' "$UNCOMMITTED" | awk '$1=="A"||$1=="??"{print $2}' \
    | grep -E '\.(py|java|ts|tsx)$' | grep -iE 'test|spec' || true)
  GATE_RC=0
  BLOCKERS=0
  if [ -n "$CHANGED" ]; then
    python3 .github/growth_gate.py --files $CHANGED \
      --tech-stack .github/tech-stack.yml \
      --exemptions .github/qa-exemptions.yml \
      --check-cases .github/cases \
      --json --json-file /tmp/growth-gate-local.json
    GATE_RC=$?
    BLOCKERS=$(python3 -c "import json;print(json.load(open('/tmp/growth-gate-local.json')).get('blocker_count',0))" 2>/dev/null || echo 1)
  elif [ -z "$UNCOMMITTED" ]; then
    echo "  ⚠️ 无变更或无法对比 origin/main，跳过"
    return 0
  fi
  # 覆盖范围声明（issue #3724）：按已提交 diff 扫描的部分看不到未提交改动 ——
  # 必须**点名**这个范围，否则「没提交」会退化成「没有变更」（旧实现在这里打印「跳过」+ return 0）。
  # ⚠️ 「仅未提交」**不构成失败**：`quick` 在第一次 commit 之前跑是正当工作流，
  #    只因「还没提交」就 ❌ 是**假红**。失败必须意味着一件真事 —— 扫到了问题（弱断言命中 /
  #    blocker），所以本函数对未提交只做三件事：并入弱断言扫描集、如实声明未覆盖范围、给出处置。
  if [ -n "$UNCOMMITTED" ]; then
    echo "::warning:: gate 预检**未覆盖**未提交改动：工作区有未提交改动，而「缺测/case_ids 追溯」按已提交 diff（origin/main...HEAD）扫描 ⇒ 这部分**未被检查**（原因：尚未提交 ≠ 没有变更；弱断言检查已改成同时看工作区）。处置：git commit 后重跑，可覆盖全部范围（migao-dev-flow §2.1）。"
  fi
  # 弱断言检查（与 pr-check 的 Check weak asserts step 语义一致：只扫「新增测试文件」）。
  # 与 CI 的唯一差别是扫描源：CI 上 PR 的改动必然已提交；本地可能还没提交 ⇒ 这里把
  # **工作区新增/未跟踪**的测试文件一并纳入，使「提交前跑」也真的有效（issue #3724）。
  NEW_TESTS=$( { git diff --diff-filter=A --name-only origin/main...HEAD 2>/dev/null || true; \
                 printf '%s\n' "$WORKTREE_NEW_TESTS"; } | sort -u | grep -v '^$' || true)
  if [ -n "$NEW_TESTS" ]; then
    echo "  🔍 扫描新增测试文件的弱断言"
    if [ -n "$WORKTREE_NEW_TESTS" ]; then
      echo "  ⚠️ 扫描集已并入工作区未提交的新增测试文件（未 commit，CI 尚看不到）："
      printf '%s\n' "$WORKTREE_NEW_TESTS" | sed 's/^/     /'
    fi
    python3 .github/growth_gate.py --check-weak --files $NEW_TESTS || GATE_RC=1
  fi
  case_coverage_check || GATE_RC=1
  [ "$GATE_RC" -eq 0 ] && [ "$BLOCKERS" = "0" ]
}

# ai-agent 测试选择（2026-09-14，issue #3680）：quick 与 full 共用**同一选择集**。
# ⚠️ 禁止改回 glob 白名单（旧写法：`tests/unit tests/test_tools_*.py tests/test_graph_*.py
#    tests/test_intent_router.py`）——那是**失败开放**的：当时 `tests/` 顶层 169 个测试文件，
#    白名单只匹配 42 个，其余 127 个（~75%）被**静默跳过**（不报错、无提示、退出码 0）。
#    实证：PR #3674 本地 quick 绿、CI 红在 `tests/test_order_create_quantity_bounds.py`
#    （#3622 的 L0 静态不变式），本地没有任何一层能看到它。
#    `tests/` 目录选择是**失败关闭**的（新增顶层文件默认被覆盖）⇒ 缺陷不会复发。
#    守卫：tests/unit_ci_workflows/test_verify_all_quick_scope.py（L0 静态不变式，必红）。
#    （上表的文件数会随迭代漂移，守卫锁的是"选择集 = tests/ 目录"这一不变式，不是数字。）
AI_AGENT_TESTS="tests/ -q --no-cov -n 4"

MODE="${1:-quick}"
case "$MODE" in
  quick)
    echo "========== MIGAO 快速验证 =========="
    report "admin-api 单测"       bash -c "cd '$ROOT/backend/admin-api' && ./mvnw test -q"
    report "ai-agent 单测"        bash -c "cd '$ROOT/backend/ai-agent-service' && .venv/bin/python -m pytest $AI_AGENT_TESTS"
    report "admin-web vitest"     bash -c "cd '$ROOT/frontend/admin-web' && npx vitest run"
    report "admin-web tsc"        bash -c "cd '$ROOT/frontend/admin-web' && npx tsc --noEmit"
    report "QA Growth Gate 预检"  gate_check
    report "UI 回退检测"        bash -c "cd '$ROOT' && ./check-ui-regression.sh"
    # 与 CI 的 Case Coverage Gate 同一脚本同一参数（判据单一实现在 scripts/case_coverage.py）
    report "评测覆盖体检（B/C 两端）" bash -c "cd '$ROOT' && for p in xiaobu mibao; do python3 scripts/\${p}_coverage.py --check || exit 1; done"
    ;;
  full)
    echo "========== MIGAO 全量验证 =========="
    report "admin-api 全量"       bash -c "cd '$ROOT/backend/admin-api' && ./mvnw test"
    report "ai-agent 全量"        bash -c "cd '$ROOT/backend/ai-agent-service' && .venv/bin/python -m pytest $AI_AGENT_TESTS"
    report "admin-web vitest"     bash -c "cd '$ROOT/frontend/admin-web' && npx vitest run"
    report "admin-web tsc"        bash -c "cd '$ROOT/frontend/admin-web' && npx tsc --noEmit"
    report "QA Growth Gate 预检"  gate_check
    report "UI 回退检测"        bash -c "cd '$ROOT' && ./check-ui-regression.sh"
    # 与 CI 的 Case Coverage Gate 同一脚本同一参数（判据单一实现在 scripts/case_coverage.py）
    report "评测覆盖体检（B/C 两端）" bash -c "cd '$ROOT' && for p in xiaobu mibao; do python3 scripts/\${p}_coverage.py --check || exit 1; done"
    ;;
  frontend)
    report "admin-web vitest"     bash -c "cd '$ROOT/frontend/admin-web' && npx vitest run"
    report "admin-web tsc"        bash -c "cd '$ROOT/frontend/admin-web' && npx tsc --noEmit"
    ;;
  backend)
    report "admin-api 全量"       bash -c "cd '$ROOT/backend/admin-api' && ./mvnw test"
    ;;
  agent)
    report "ai-agent 全量"        bash -c "cd '$ROOT/backend/ai-agent-service' && .venv/bin/python -m pytest $AI_AGENT_TESTS"
    ;;
  gate)
    report "QA Growth Gate 预检"  gate_check
    ;;
  *)
    echo "用法: $0 {quick|full|frontend|backend|agent|gate}"
    exit 2
    ;;
esac

echo ""
echo "========== 结果: $PASS 通过, $FAIL 失败 =========="
if [ "$FAIL" -gt 0 ]; then
  printf '失败项: %s\n' "${FAILED[@]}"
  exit 1
fi
exit 0
