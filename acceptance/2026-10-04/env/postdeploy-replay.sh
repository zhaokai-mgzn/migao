#!/usr/bin/env bash
# acceptance/2026-10-04/env/postdeploy-replay.sh
# 部署把云测试环境从 de614623d 切到 main 之后，用**各线自己的 harness 原样重放**（同判据、同夹具、同环境口径），
# 产出 after 读数，与 before 成对。各步失败不中断（逐条记退出码），全部日志落在 replay-postdeploy/。
#
# 用法（仓库根）：bash acceptance/2026-10-04/env/postdeploy-replay.sh
set -uo pipefail
cd "$(dirname "$0")/../../.."
BASE=acceptance/2026-10-04
OUT="$BASE/replay-postdeploy"
mkdir -p "$OUT"
export API_BASE=https://api.migaozn.com TENANT_ID=25 ADMIN_PHONE=13800138000 SMS_CODE=123456
export PROBE_PREFIX=ZR
LOG="$OUT/run.log"
: > "$LOG"

step() { # step <name> <logfile> <cmd...>
  local name=$1; shift; local logf=$1; shift
  echo "=== [$name] $(date '+%F %T %z') → $logf" | tee -a "$LOG"
  "$@" > "$logf" 2>&1
  local rc=$?
  echo "    [$name] exit=$rc" | tee -a "$LOG"
  return 0
}

# 0) 构建点自证：必须先确认已切到新 tag（并把读数**落盘**供复核，见 00-buildpoint.json）
{
  echo "== 重放开跑 $(date '+%F %T %z') =="
  RAW=$(bash "$BASE/env/swas-run.sh" "docker ps --format '{{.Image}}' | grep admin-api; cat /opt/migao-deploy/.last-good-tag" 120 | tail -2 | tr '\n' ' ')
  echo "admin-api 运行镜像 tag: $RAW"
  python3 - "$OUT/00-buildpoint.json" "$RAW" <<'PYEOF'
import json, sys, datetime
tag = sys.argv[2].split()[0].rsplit(':', 1)[-1] if sys.argv[2].strip() else ''
json.dump({"at": datetime.datetime.now().astimezone().strftime('%F %T %z'),
           "admin_api_running_tag": tag, "raw": sys.argv[2].strip(),
           "source": "SWAS 云助手 docker ps + /opt/migao-deploy/.last-good-tag"},
          open(sys.argv[1], "w"), ensure_ascii=False, indent=1)
print("buildpoint →", sys.argv[1], tag)
PYEOF
} | tee -a "$LOG"

# 1) 集成侧重放 R1–R4（MIME / 并发完结 / 退款精度 / 分页下限）
step "R1-R4 集成侧重放" "$OUT/10-integration.log" \
  env PHASE=postdeploy OUT_DIR="$BASE/env/out" node "$BASE/env/postdeploy-replay.mjs"

# 2) 线② 全档重放（含 F1 并发完结 / F2 退款精度 / F3 分页）
step "线② 售后退款全档" "$OUT/20-aftersales-full.log" \
  env OUT_DIR="$OUT/aftersales" node "$BASE/aftersales-refund-sweep/harness/run-all.mjs"

# 3) 线③ 并发写面 + 幂等重放（F1 台账同基 / F2 超卖 / F3 盘点 500 / F4 发货幂等）
step "线③ 并发写面" "$OUT/30-race-write.log" \
  env OUT_DIR="$OUT/race" node "$BASE/race-sweep/harness/probe-write.mjs"
step "线③ 幂等面" "$OUT/31-race-idem.log" \
  env OUT_DIR="$OUT/race" node "$BASE/race-sweep/harness/probe-idem.mjs"

# 4) 线① 部署面身份探针（#6219 裁高）+ MIME 探针（#6293）
step "线① #6219 身份探针" "$OUT/40-identity.log" \
  env OUT_DIR="$OUT/worker" node "$BASE/worker-miniapp-sweep/harness/p0d-deployed-identity-probe.mjs"
step "线① #6293 MIME 探针" "$OUT/41-mime.log" \
  env OUT_DIR="$OUT/worker" node "$BASE/worker-miniapp-sweep/harness/ui-deployed-mime.mjs"

# 5) 清理（两条线的探针命名域）
# ⚠️ 线② 的 cleanup 段在**底座**目录（2026-10-03），不在本线 overlay 目录 —— 第二轮独立复核抓到本行原写错路径，
#    导致该步 MODULE_NOT_FOUND（exit=1）后无人发现（如实登记）。
step "线② 清理" "$OUT/50-cleanup-aftersales.log" \
  env OUT_DIR="$OUT/aftersales" node "$BASE/../2026-10-03/aftersales-concurrency-sweep/harness/p9-cleanup.mjs"
step "线③ 清理" "$OUT/51-cleanup-race.log" \
  env OUT_DIR="$OUT/race" node "$BASE/race-sweep/harness/cleanup.mjs"

# 6) 收尾读数：租户 25 探针残留 + tenants 列表
{
  echo "== 收尾 $(date '+%F %T %z') =="
  set -a; . backend/admin-api/.env; set +a
  PGPASSWORD="$RDS_PASSWORD" psql -h "$RDS_HOST" -p "$RDS_PORT" -U "$RDS_USER" -d "$RDS_DB" -Atc \
    "select 'tenants='||(select count(*) from tenants)||' ids='||(select string_agg(id::text,',') from tenants)||' t25_products='||(select count(*) from products where tenant_id=25)||' t25_orders='||(select count(*) from orders where tenant_id=25)||' t25_tickets='||(select count(*) from after_sales_tickets where tenant_id=25);"
} | tee -a "$LOG"

echo "== 重放结束 $(date '+%F %T %z') ==" | tee -a "$LOG"
grep -h "exit=" "$LOG"
echo "日志目录: $OUT"
