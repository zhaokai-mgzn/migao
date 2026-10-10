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
  # 复位 = 用**自愈脚本**起一个"路由完备"的实例（它自带：杀端口 → 清三类缓存 → 起 → 校验**四个业务路由** → 不齐重来 ≤3 次）。
  # ⚠️ 2026-10-11 修：本行原先指向 `$ROOT/scripts/dev-web-reset.sh` —— 那个文件**在本仓与包里都不存在** ⇒ `RESET=1` 一按就停
  #    （README 却把它写成了可用路径）。改为指向包内真实存在的自愈脚本，并用 nohup 脱离本 shell（否则它会 `wait` 住、本脚本再也走不到下一步）。
  SRV="$HERE/scripts/serve-admin-web-3001.sh"
  [ -f "$SRV" ] || { echo "❌ 找不到自愈脚本 $SRV ⇒ 不复位就继续跑会得到假绿/假红，故停"; exit 1; }
  # 版本自证：读数只在"工作树干净且 == origin/main"时可归因
  TREE_HEAD="$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo '?')"
  TREE_DIRTY="$(git -C "$ROOT" status --porcelain 2>/dev/null | wc -l | tr -d ' ')"
  MAIN_HEAD="$(git -C "$ROOT" rev-parse --short origin/main 2>/dev/null || echo '?')"
  echo "=== 起一个路由完备的 admin-web（自愈：杀端口→清缓存→起→校验四路由→不齐重来≤3 次）==="
  echo "    工作树 HEAD=${TREE_HEAD}（脏文件 ${TREE_DIRTY} 个） ｜ origin/main=${MAIN_HEAD}"
  [ "$TREE_HEAD" != "$MAIN_HEAD" ] && echo "    ⚠️ 工作树与 origin/main 不一致 ⇒ 本轮读数**只能归因到 ${TREE_HEAD}**，别写进 main 的结论里"
  nohup bash "$SRV" > /tmp/srv3001-nohup.log 2>&1 &
  for i in 1 2 3 4 5 6 7 8 9 10 11 12; do
    ok=1
    for p in /login /dashboard /products /about; do
      c=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "http://localhost:3001${p}" 2>/dev/null || true)
      [ "${c}" = "200" ] || ok=0
    done
    [ "$ok" = "1" ] && { echo "    ✅ 四路由全 200（/login /dashboard /products /about）"; break; }
    sleep 10
  done
  [ "$ok" = "1" ] || { echo "❌ 复位后四路由仍不齐 ⇒ 拒绝继续（否则读数假）—— 看 /tmp/srv3001-nohup.log"; exit 1; }
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
