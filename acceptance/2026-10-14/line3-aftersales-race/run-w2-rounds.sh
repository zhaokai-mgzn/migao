#!/usr/bin/env bash
# 线③ 独立复现的**多轮**运行器：把「过账 × 作废」严格同时起跑跑 N 轮，统计结局分布。
# 只碰本线自建探针入库单（remark 前缀 lb3-race）。
set -u
REPO="/Users/guangzhen.zk/ai native/migao"
N="${N:-20}"
OUT="$REPO/acceptance/2026-10-14/line3-aftersales-race/out/race"
mkdir -p "$OUT/W2-rounds"
for i in $(seq 1 "$N"); do
  OUT_DIR="$OUT" REPO_ROOT="$REPO" TENANT_ID=32 ADMIN_PHONE=13800138000 SMS_CODE=123456 \
    SKU_ID=2110348703040729089 PRODUCT_ID=3eec98bd01e59419d8041aff7f851da4 \
    node "$REPO/acceptance/2026-10-14/line3-aftersales-race/probe-w2-repro.mjs" \
    > "$OUT/W2-rounds/round-$(printf '%02d' "$i").json" 2>&1
  python3 - "$OUT/W2-rounds/round-$(printf '%02d' "$i").json" <<'PY'
import json,sys
p=sys.argv[1]
txt=open(p).read()
i=txt.find('{')
try:
    j=json.loads(txt[i:])
except Exception:
    print(f"{p}: PARSE_FAIL"); raise SystemExit
st=[r['status'] for r in j['requests']]
print(f"{p.split('/')[-1]}: post={st[0]} cancel={st[1]} db={j['db']['status']} delta={j['stockDelta']} ledger={j['ledgerRows']} verdict={j['verdict']} inconsistent={len(j['inconsistent'])}")
PY
done
