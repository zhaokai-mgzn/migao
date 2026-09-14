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
  if [ -z "$CHANGED" ]; then
    echo "  ⚠️ 无变更或无法对比 origin/main，跳过"
    return 0
  fi
  python3 .github/growth_gate.py --files $CHANGED \
    --tech-stack .github/tech-stack.yml \
    --exemptions .github/qa-exemptions.yml \
    --check-cases .github/cases \
    --json --json-file /tmp/growth-gate-local.json
  GATE_RC=$?
  BLOCKERS=$(python3 -c "import json;print(json.load(open('/tmp/growth-gate-local.json')).get('blocker_count',0))" 2>/dev/null || echo 1)
  # 弱断言检查（与 pr-check 的 Check weak asserts step 一致：只扫新增测试文件）
  NEW_TESTS=$(git diff --diff-filter=A --name-only origin/main...HEAD 2>/dev/null | grep -E '\.(py|java|ts|tsx)$' | grep -iE 'test|spec' || true)
  if [ -n "$NEW_TESTS" ]; then
    echo "  🔍 扫描新增测试文件的弱断言"
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
