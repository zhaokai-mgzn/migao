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
# 检查项三态（2026-09-15 固化）：
#   ✅ 通过      —— **真跑了**且退出 0
#   ❌ 失败      —— **真跑了**且退出非 0（**只有这一种**会记 ❌）
#   ⏭️  未就绪    —— 运行环境没准备好（未建 venv / 未装 node_modules / 无 JDK），**根本没跑起来**，
#                  故既不是通过也不是失败；会打印「缺什么 + 实测可跑通的准备命令」。
#                  先例（日志原文）：`bash: .venv/bin/python: No such file or directory`（exit 127）、
#                  `Cannot find module 'vitest/config'`（exit 1）—— 旧版把二者记成 ❌ = **假红**。
# 另有第三类**失败**形态（不占 ✅/⏭️）：
#   ❌ 假绿（检查未生效）—— **跑了**却**什么都没检查**还退出 0。先例：无 node_modules 时
#                  `npx tsc --noEmit` 从 npm 拉到**同名占位包** `tsc`，打印
#                  "This is not the tsc command you are looking for" 后 **exit 0** ⇒ 旧版打 ✅。
#                  已由 `node_modules/.bin/<tool>` 精确探测**前置消除**，另留同族兜底判据。
#
# 禁空跑：跑之前先算变更集（`origin/main...HEAD` ∪ 工作区未提交改动，与 QA Growth Gate 预检
# **同一份判据**）。变更集为空 ⇒ **不跑任何检查**并**非零退出**——在零 diff 的树上跑验证没有边际
# 信息，把它的 ✅ 读成「验证通过」属 migao-acceptance v1.3 的「空跑」。
#
# 返回码：0=全部**真跑**的检查通过；1=有真跑的检查失败；2=用法错误；
#         3=无变更（未执行任何检查）；4=有变更但零项真跑（纯空跑）。开发自查与 CI 用同一命令。
# =============================================================================
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PASS=0
FAIL=0
READY=0
declare -a FAILED
declare -a NOT_READY

# ── 变更集来源（单一实现，issue #3724 + 本次抽公共）────────────────────────────
# 供「禁空跑」判据与 gate_check() 共用 —— ⚠️ **禁止在别处再写一套**：下面两条注释里的细节
# （`-uall` 不能省、路径取列）都是踩过坑的，复制一份必然漂移。
committed_changes() {
  git fetch origin main --quiet 2>/dev/null || true
  git diff --name-only origin/main...HEAD 2>/dev/null || true
}
worktree_changes() {
  # ⚠️ `-uall` 不能省：默认 `--porcelain` 会把**整个未跟踪目录**折叠成一行 `?? tests/`，
  #    既匹配不上测试文件过滤、也拿不到文件名 ⇒ 工作区新增测试被漏扫（缺陷原地复发，实测）。
  git status --porcelain -uall 2>/dev/null || true
}

# ── 「假绿」签名（退出 0 但工具根本没跑起来）──────────────────────────────────
# 三态之外的第三类**失败**形态：检查**跑了**却**没有真的检查**，还退出 0。
# 先例（2026-09-14 实测，日志原文）：无 node_modules 时 `npx tsc --noEmit` 从 npm 拉到**同名占位包**
# `tsc`，打印下面这句后 **exit 0** ⇒ 旧版打 ✅ 而什么都没检查。
# 处置：**归入 ❌**（`❌ … 假绿（检查未生效）`），**绝不**归 ✅ 或 ⏭️（⏭️ 只表示「根本没跑」）。
# 注：admin-web-tsc 已用 `.bin/tsc` 探测把它**前置消除**；此处是**同族兜底**（防新的假绿形态）。
FAKE_PASS_SIGNATURE="This is not the tsc command you are looking for"

# ── 运行环境就绪探测（**单一实现**）──────────────────────────────────────────
# 为什么需要（2026-09-14 实测，日志原文为证）：在**干净 worktree**（没建 ai-agent venv、
# 没装 admin-web node_modules）上跑 `./verify-all.sh quick` 得到
#   ❌ ai-agent 单测 (exit 127)   ← bash: .venv/bin/python: No such file or directory
#   ❌ admin-web vitest (exit 1)  ← Error: Cannot find module 'vitest/config'
#   ✅ admin-web tsc              ← **假的**（npx 从 npm 拉了同名占位包后 exit 0）
# 前两条是**假红**（检查没跑起来），第三条是**假绿**（跑了但什么都没检查）——都不构成验证结论。
# 故跑之前先探测该项**真正依赖的**运行环境；未就绪 → ⏭️ + 缺什么 + 实测可跑通的准备命令。
# ⚠️ 探的是**真正被调用的可执行文件**（`node_modules/.bin/<tool>`），不是目录：目录在、工具不在时
#    `npx` 仍会去 npm 拉同名包 ⇒ 假绿照旧。路径以现场日志原文为准（不猜）。
# 返回：0=就绪；1=未就绪（READY_MISSING/READY_HINT 已填）；2=key 未声明（脚本配置错误）。
probe_ready() {
  local key="$1"
  READY_MISSING=""
  READY_HINT=""
  case "$key" in
    ai-agent)
      if [ ! -x "$ROOT/backend/ai-agent-service/.venv/bin/python" ]; then
        READY_MISSING="缺 $ROOT/backend/ai-agent-service/.venv/bin/python（未建 venv；实测报错：bash: .venv/bin/python: No such file or directory）"
        READY_HINT="cd '$ROOT/backend/ai-agent-service' && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
        return 1
      fi
      ;;
    admin-web-vitest)
      if [ ! -x "$ROOT/frontend/admin-web/node_modules/.bin/vitest" ]; then
        READY_MISSING="缺 $ROOT/frontend/admin-web/node_modules/.bin/vitest（未装依赖；实测报错：Cannot find module 'vitest/config'）"
        READY_HINT="cd '$ROOT/frontend/admin-web' && npm ci"
        return 1
      fi
      ;;
    admin-web-tsc)
      # ⚠️ 必须探 `.bin/tsc` 本身：无 node_modules 时 `npx tsc --noEmit` 会从 npm 拉到**同名的占位包**
      #    `tsc` 并 **exit 0** ⇒ 控制台 ✅ 而**什么都没检查**（实测 2026-09-14）。这是假绿，
      #    比 vitest 那条假红隐蔽得多 —— 同一棵树上一个假红、一个假绿。
      if [ ! -x "$ROOT/frontend/admin-web/node_modules/.bin/tsc" ]; then
        READY_MISSING="缺 $ROOT/frontend/admin-web/node_modules/.bin/tsc（typescript 未装；不探则 npx 会拉到同名占位包并 exit 0 = 假绿）"
        READY_HINT="cd '$ROOT/frontend/admin-web' && npm ci"
        return 1
      fi
      ;;
    admin-api)
      if [ ! -x "$ROOT/backend/admin-api/mvnw" ]; then
        READY_MISSING="缺 $ROOT/backend/admin-api/mvnw（仓库自带；缺失说明工作区被破坏）"
        READY_HINT="git -C '$ROOT' checkout -- backend/admin-api/mvnw"
        return 1
      fi
      if ! command -v java >/dev/null 2>&1 && [ ! -x "${JAVA_HOME:-/nonexistent}/bin/java" ]; then
        READY_MISSING="PATH 与 JAVA_HOME 下都找不到 java（admin-api 无法构建）"
        READY_HINT="安装 JDK 21（本仓库 admin-api 需要 Java 21）"
        return 1
      fi
      ;;
    *)
      # 未声明的 key = 脚本配置错误（**不静默放行**：否则新增检查项会悄悄退回「未就绪即 ❌」）。
      READY_MISSING="report_env 的 env key '$key' 未在 probe_ready() 里声明"
      READY_HINT="在 probe_ready() 的 case 里补该 key 的分支"
      return 2
      ;;
  esac
  return 0
}

report() {
  # 用法：report "检查项名" 命令...
  # ⚠️ **签名是契约，不许改**：`test_step_exit_code_propagation.py` 的静态断言、
  #    `test_gate_uncommitted_noop.py` 场景 ⑧ 的 `report "%s" false` harness、以及全部调用点都按
  #    这个形态调用。三态里的「未就绪」由**独立包装** `report_env()` 表达（见下）——
  #    report() 只负责「真的跑了」之后的判定（✅ / ❌ / ❌ 假绿）。
  local name="$1"; shift
  # ⚠️ 日志路径必须**按检查项唯一**：此前是固定的 /tmp/verify-all-$$.log（$$ 是 shell PID，
  #    整个进程内不变）→ 每个检查项都覆盖同一个文件 → 多项失败时只剩最后一项的日志，
  #    "日志: xxx" 指向的内容与失败项对不上，现场排查当场被带偏。
  # ⚠️ slug 还必须**与环境 locale 无关**（2026-09-14 实证，issue #3724 的 CI 红）：
  #    `tr -c '[:alnum:]'` 的 `[:alnum:]` 随 locale 变 —— UTF-8 下 CJK 算 alnum（保留中文），
  #    C locale 下 CJK 逐字节变 `-`。同一句 `report "QA Growth Gate 预检"` 因此得到
  #    **不同**文件名：本机 `/tmp/verify-all-<PID>-QA-Growth-Gate-预检.log`、
  #    CI `/tmp/verify-all-<PID>-QA-Growth-Gate.log` ⇒ 任何按名重建路径的代码/人都会找错文件
  #    （「本地绿 / CI 红」）。故 `tr` 显式钉 `LC_ALL=C`。
  # ⚠️ 但钉了 C locale 之后，**纯 CJK 检查名**的 ASCII 部分为空（如「检查项甲」/「检查项乙」
  #    都退化成空 slug）⇒ 只靠 `tr` 会让两项**共用同一个日志文件**，唯一性丢失。
  #    故再拼 `cksum`（POSIX，macOS/GNU 均有）兜底：唯一性不依赖名字能否 ASCII 化。
  local slug
  slug="$(printf '%s' "$name" | LC_ALL=C tr -c '[:alnum:]' '-' | sed 's/-\{2,\}/-/g; s/^-//; s/-$//')"
  slug="${slug:+${slug}-}$(printf '%s' "$name" | cksum | awk '{print $1}')"
  local log="/tmp/verify-all-$$-${slug}.log"
  local rc=0
  "$@" > "$log" 2>&1
  rc=$?
  if [ "$rc" -eq 0 ]; then
    # 「假绿」兜底（见 FAKE_PASS_SIGNATURE 注释）：退出 0 但日志显示工具根本没跑起来 ⇒ **归入 ❌**。
    # ⚠️ 边界：这类「跑了但没生效」**绝不**归 ✅ 或 ⏭️ —— ⏭️ 只表示「**根本没跑**」（probe 未就绪）。
    # ⚠️ 只加在本函数**体内**：`report()` 的签名是契约，不动（见函数首行注释）。
    # ⚠️ 用 `${FAKE_PASS_SIGNATURE:-}` 取默认值：本函数会被外部 harness **单独抽出**执行
    #    （`test_gate_uncommitted_noop.py` 的 `set -uo pipefail` + 只带 report() 的片段），
    #    那里没有本文件的顶层变量 ⇒ 裸引用会 unbound variable 崩溃、把别人的守卫打红。
    local fakesig="${FAKE_PASS_SIGNATURE:-}"
    if [ -n "$fakesig" ] && grep -qF "$fakesig" "$log"; then
      echo "❌ $name — 假绿（检查未生效）：退出 0 但日志显示工具根本没跑起来 — 日志: $log"
      FAIL=$((FAIL + 1))
      FAILED+=("$name")
      return 0
    fi
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

# ── 三态包装：先探测运行环境，未就绪 ⇒ ⏭️ 跳过；就绪 ⇒ 交给 report() 原样执行 ────────────
# ⚠️ 反向红线：**不许**把「真跑了但失败」改成 ⏭️ —— ⏭️ 只能由 probe_ready() 的返回 1 产生。
# ⚠️ report() 的签名保持不动（既有契约）；这里只**新增**一个包装函数，不改任何既有调用形态。
report_env() {
  # 用法：report_env <env-key> "检查项名" 命令...      （env-key 见 probe_ready()）
  local env_key="$1"; shift
  local name="$1"; shift
  local probe_rc=0
  probe_ready "$env_key" || probe_rc=$?
  if [ "$probe_rc" -eq 1 ]; then
    echo "⏭️  $name — 未就绪（跳过；既不是通过也不是失败）"
    echo "     $READY_MISSING"
    echo "     准备：$READY_HINT"
    READY=$((READY + 1))
    NOT_READY+=("$name")
    return 0
  elif [ "$probe_rc" -ne 0 ]; then
    # ⚠️ 变量必须用 `${…}` 显式包裹：macOS 自带 bash 3.2 会把**紧跟 $VAR 的非 ASCII 字节**
    #    并进变量名（`$READY_MISSING（` → 变量名 `READY_MISSING\xef` → unbound variable 崩溃）。
    echo "❌ $name — 脚本配置错误：${READY_MISSING}（${READY_HINT}）"
    FAIL=$((FAIL + 1))
    FAILED+=("$name")
    return 0
  fi
  report "$name" "$@"
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
  # 变更集来源是**共享实现**（committed_changes/worktree_changes，见文件头）—— 别在这里另写一套。
  # 两条判据都必须拿：「因为没提交所以扫不到」与「确实没有变更」必须可区分
  # （issue #3724：旧实现把两者一视同仁地打印「跳过」+ return 0 = ✅ 假绿）。
  CHANGED=$(committed_changes)
  UNCOMMITTED=$(worktree_changes)
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
# ⚠️ 用法校验用 `if` 而不是第二个 `case "$MODE" in`：脚本里**只能有一个**顶层
#    `case "$MODE" in`（模式分支所属的那个）—— L0 守卫 `test_verify_all_quick_scope.py`
#    的 `_mode_block()` 按「第一个顶层 case」定位模式分支，多一个 case 会让它找不到 `quick)`。
if [ "$MODE" != quick ] && [ "$MODE" != full ] && [ "$MODE" != frontend ] && \
   [ "$MODE" != backend ] && [ "$MODE" != agent ] && [ "$MODE" != gate ]; then
  echo "用法: $0 {quick|full|frontend|backend|agent|gate}"
  exit 2
fi

# ── 禁空跑（2026-09-15 固化）────────────────────────────────────────────────
# 为什么（实测）：在**干净 worktree、detached HEAD == origin/main（零 diff）**上跑
# `./verify-all.sh quick` 会得到「5 通过 / 2 失败」—— 但那是一次**空跑**：
#   · `gate` 预检必然走「无变更…跳过」分支（它按 diff 扫描）；
#   · 其余检查对一棵与 main **完全一致**的树没有边际信息（绿了也不代表你的改动没问题 ——
#     你根本没有改动）。
# 把这种运行读成「验证通过」= migao-acceptance v1.3 的「空跑」（绿了但没跑）。
# 判据复用 gate_check() 的变更集来源（committed_changes/worktree_changes，**不写第二套**）。
CHANGE_SET="$( { committed_changes; worktree_changes | awk '{print $NF}'; } \
  | grep -v '^[[:space:]]*$' | sort -u )"
if [ -z "$CHANGE_SET" ]; then
  echo "⏭️  无变更 ⇒ 未执行任何检查（这不是通过）"
  echo "     判据：git diff --name-only origin/main...HEAD 与 git status --porcelain -uall 均为空"
  echo "     处置：先改代码并提交，再跑验证 —— 在零 diff 的树上跑验证没有边际信息（空跑）。"
  exit 3
fi
# ⚠️ 措辞避让：这行**不得**含「未提交」三字 —— `test_gate_uncommitted_noop.py` 用
# 「无未提交改动时控制台不得出现『未提交』」做**防误伤**断言，这里的结构性提示会误触它。
echo "变更集：$(printf '%s\n' "$CHANGE_SET" | grep -c .) 个文件（origin/main...HEAD ∪ 工作区改动）"

case "$MODE" in
  quick)
    echo "========== MIGAO 快速验证 =========="
    report_env admin-api "admin-api 单测"       bash -c "cd '$ROOT/backend/admin-api' && ./mvnw test -q"
    report_env ai-agent "ai-agent 单测"        bash -c "cd '$ROOT/backend/ai-agent-service' && .venv/bin/python -m pytest $AI_AGENT_TESTS"
    report_env admin-web-vitest "admin-web vitest"     bash -c "cd '$ROOT/frontend/admin-web' && npx vitest run"
    report_env admin-web-tsc "admin-web tsc"        bash -c "cd '$ROOT/frontend/admin-web' && npx tsc --noEmit"
    report "QA Growth Gate 预检"  gate_check
    report "UI 回退检测"        bash -c "cd '$ROOT' && ./check-ui-regression.sh"
    # 与 CI 的 Case Coverage Gate 同一脚本同一参数（判据单一实现在 scripts/case_coverage.py）
    report "评测覆盖体检（B/C 两端）" bash -c "cd '$ROOT' && for p in xiaobu mibao; do python3 scripts/\${p}_coverage.py --check || exit 1; done"
    ;;
  full)
    echo "========== MIGAO 全量验证 =========="
    report_env admin-api "admin-api 全量"       bash -c "cd '$ROOT/backend/admin-api' && ./mvnw test"
    report_env ai-agent "ai-agent 全量"        bash -c "cd '$ROOT/backend/ai-agent-service' && .venv/bin/python -m pytest $AI_AGENT_TESTS"
    report_env admin-web-vitest "admin-web vitest"     bash -c "cd '$ROOT/frontend/admin-web' && npx vitest run"
    report_env admin-web-tsc "admin-web tsc"        bash -c "cd '$ROOT/frontend/admin-web' && npx tsc --noEmit"
    report "QA Growth Gate 预检"  gate_check
    report "UI 回退检测"        bash -c "cd '$ROOT' && ./check-ui-regression.sh"
    # 与 CI 的 Case Coverage Gate 同一脚本同一参数（判据单一实现在 scripts/case_coverage.py）
    report "评测覆盖体检（B/C 两端）" bash -c "cd '$ROOT' && for p in xiaobu mibao; do python3 scripts/\${p}_coverage.py --check || exit 1; done"
    ;;
  frontend)
    report_env admin-web-vitest "admin-web vitest"     bash -c "cd '$ROOT/frontend/admin-web' && npx vitest run"
    report_env admin-web-tsc "admin-web tsc"        bash -c "cd '$ROOT/frontend/admin-web' && npx tsc --noEmit"
    ;;
  backend)
    report_env admin-api "admin-api 全量"       bash -c "cd '$ROOT/backend/admin-api' && ./mvnw test"
    ;;
  agent)
    report_env ai-agent "ai-agent 全量"        bash -c "cd '$ROOT/backend/ai-agent-service' && .venv/bin/python -m pytest $AI_AGENT_TESTS"
    ;;
  gate)
    report "QA Growth Gate 预检"  gate_check
    ;;
  *)
    echo "用法: $0 {quick|full|frontend|backend|agent|gate}"
    exit 2
    ;;
esac

# ── 汇总（把「真跑了几项」摆到台面上）────────────────────────────────────────
echo ""
EXECUTED=$((PASS + FAIL))
TOTAL=$((PASS + FAIL + READY))
echo "========== 结果: $PASS 通过, $FAIL 失败, $READY 未就绪（真跑 $EXECUTED 项 / 共 $TOTAL 项）=========="
if [ "$EXECUTED" -eq 0 ]; then
  # 有变更却零项真跑 = 纯空跑：本次没有任何东西被验证过 ⇒ **不得**当成通过。
  echo "❌ 无有效检查（纯空跑）—— 有变更，但 $TOTAL 项检查全部未就绪，本次没有验证任何东西"
  if [ "$READY" -gt 0 ]; then
    printf '未就绪（跳过）: %s\n' "${NOT_READY[@]}"
  fi
  exit 4
fi
if [ "$FAIL" -gt 0 ]; then
  printf '失败项: %s\n' "${FAILED[@]}"
fi
if [ "$READY" -gt 0 ]; then
  printf '未就绪（跳过）: %s\n' "${NOT_READY[@]}"
fi
if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
exit 0
