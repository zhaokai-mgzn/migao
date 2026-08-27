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
  local log="/tmp/verify-all-$$.log"
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

gate_check() {
  echo "── [QA Growth Gate] 本地预检（与 CI 同规则）──"
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
  BLOCKERS=$(python3 -c "import json;print(json.load(open('/tmp/growth-gate-local.json')).get('blocker_count',0))" 2>/dev/null || echo 1)
  [ "$BLOCKERS" = "0" ]
}

MODE="${1:-quick}"
case "$MODE" in
  quick)
    echo "========== MIGAO 快速验证 =========="
    report "admin-api 单测"       bash -c "cd '$ROOT/backend/admin-api' && ./mvnw test -q"
    report "ai-agent 单测"        bash -c "cd '$ROOT/backend/ai-agent-service' && .venv/bin/python -m pytest tests/unit tests/test_tools_*.py tests/test_graph_*.py tests/test_intent_router.py -q"
    report "admin-web vitest"     bash -c "cd '$ROOT/frontend/admin-web' && npx vitest run"
    report "admin-web tsc"        bash -c "cd '$ROOT/frontend/admin-web' && npx tsc --noEmit"
    report "QA Growth Gate 预检"  gate_check
    ;;
  full)
    echo "========== MIGAO 全量验证 =========="
    report "admin-api 全量"       bash -c "cd '$ROOT/backend/admin-api' && ./mvnw test"
    report "ai-agent 全量"        bash -c "cd '$ROOT/backend/ai-agent-service' && .venv/bin/python -m pytest tests/ -q"
    report "admin-web vitest"     bash -c "cd '$ROOT/frontend/admin-web' && npx vitest run"
    report "admin-web tsc"        bash -c "cd '$ROOT/frontend/admin-web' && npx tsc --noEmit"
    report "QA Growth Gate 预检"  gate_check
    ;;
  frontend)
    report "admin-web vitest"     bash -c "cd '$ROOT/frontend/admin-web' && npx vitest run"
    report "admin-web tsc"        bash -c "cd '$ROOT/frontend/admin-web' && npx tsc --noEmit"
    ;;
  backend)
    report "admin-api 全量"       bash -c "cd '$ROOT/backend/admin-api' && ./mvnw test"
    ;;
  agent)
    report "ai-agent 全量"        bash -c "cd '$ROOT/backend/ai-agent-service' && .venv/bin/python -m pytest tests/ -q"
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
