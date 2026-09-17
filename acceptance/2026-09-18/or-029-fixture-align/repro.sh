#!/usr/bin/env bash
# OR-029 证据①②③ 一键复现（只读；零 LLM、不连库）
W="${1:-$PWD}"
A=/tmp/or029
python3 "$A/seed_truth.py" "$W"    # 证据①：seed 真值实测（规格/库存/加工项名目与单价/客户）
python3 "$A/satisfiable.py"        # 证据③：逐项可满足自证（含旧值 0 命中红证）
grep -n "2699-03暖米色\|2699-01本白" "$W/tests/agent_eval/fixtures/mibao_eval_seed.sql"
grep -n "'per_meter', 8.00\|'per_meter', 12.00\|'per_meter', 10.00\|'per_area', 30.00" \
     "$W/tests/agent_eval/fixtures/xiaobu_eval_seed.sql" "$W/tests/agent_eval/fixtures/mibao_eval_seed.sql"
