#!/usr/bin/env bash
# 试用前 UI 验收 —— **一条命令跑完整轮**（铁律 10：同一串动作做过 ≥3 次 ⇒ 收敛成一条命令，顺序即安全顺序）
#
#   bash acceptance/2026-10-10-ui-trial-readiness/run-all.sh            # 直接跑（假定 3001 上已有一份健康实例）
#   RESET=1 bash acceptance/2026-10-10-ui-trial-readiness/run-all.sh    # 先复位 dev server（清缓存 + 单实例 + 等 200）再跑
#   PHASE=post-fix RESET=1 bash acceptance/.../run-all.sh                # 给本轮读数起名（落到 evidence/S12-<PHASE>.json；不给则 latest）
#
# 退出码：0 = 五支运行器全绿；1 = 有红（逐支列出）。
# 顺序即安全顺序：先本地三支（需 :3001）→ 纸面（需 :3001）→ 线上（走公网，不需要本地服务）。
# ⚠️ 不要用管道包住本脚本（`| tail` 会吞掉退出码 —— 本批实测踩过两次）。
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"

if [ "${RESET:-0}" = "1" ]; then
  echo "=== 复位 dev server（清 .next / node_modules/.cache / .turbo，起单实例并等 /login 与 /dashboard 双 200）==="
  WEB_DIR="${WEB_DIR:-/Users/guangzhen.zk/ai native/migao/frontend/admin-web}" bash "$ROOT/scripts/dev-web-reset.sh" || {
    echo "❌ 复位失败（它自带断言，失败会非零退出）—— 不复位就继续跑会得到**假绿/假红**，故此处直接停"; exit 1; }
fi

FAILS=0
run_one() {
  local name="$1"; shift
  echo ""; echo "============================== $name =============================="
  # ⚠️ 必须用 ${name} 大括号：`${name}（` 会把全角「（」的字节折进变量名 ⇒ set -u 下 unbound variable。
  #    本脚本首跑实测：**绿的路能走、红的路当场崩**（而它存在的意义就是报红）。
  if "$@"; then echo "✅ ${name}"; else echo "❌ ${name}（退出码非零）"; FAILS=$((FAILS + 1)); fi
}

run_one "S1–S6 真机金路径（登录零额度 / 无菌值 / 浮球 / 分页 / 锚点 / 八页卫生）" node "$HERE/run.mjs"
run_one "S7 计数行（读面故障下 6 页不得印「共 0 条」）"                        node "$HERE/run-count-row.mjs"
run_one "V17–V22 + 版面（读失败⇄空态 / 冷启动 / 宽表可达性 / 冻结列选中态 / 侧栏显眼度）" node "$HERE/run-findings-6713-6717.mjs"
run_one "S21b 打印纸面（报价单/加工单/销售单：缺值印 —、未知不得传染出数字）"      node "$HERE/run-print-doc-verify.mjs"
run_one "S31 线上层（官网四页 / bmini / worker-h5 / 商家域）"                  node "$HERE/run-live-reprobe.mjs"

echo ""; echo "==================== 汇总 ===================="
if [ "$FAILS" -eq 0 ]; then echo "✅ 五支全绿（证据在 $HERE/evidence/，含逐条读数与截图）"; exit 0; fi
echo "🔴 有 $FAILS 支非绿 —— 看上文逐条 ❌ 与 evidence/ 里的读数；**不要**在未归因的情况下把它读成「通过」"
exit 1
