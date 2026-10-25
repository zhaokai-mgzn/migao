#!/usr/bin/env bash
# ============================================================================
# 评测栈种子注入 —— **单一实现**（issue #3563）
# ============================================================================
# 为什么要有这个文件（根因，勿删注释）：
#   此前三个评测 workflow **各写一份**种子规则，且互不相等：
#     · xiaobu-acceptance.yml   只当 persona=mibao 时叠 B 端种子
#     · post-deploy-eval.yml    只当 matrix.persona=mibao 时叠 B 端种子
#     · agent-behavior-eval.yml **无条件**叠 B 端种子（一个 job 里跑双端分桶）
#       ⚠️ 该 workflow 已于 #4275 按用户裁定**整体删除**（承接 #4262）；这里保留它，是作为
#          **根因证据**（它正是"同一 persona 拿到不同栈"的那一路），不是"它还活着"。
#   于是同一个 persona 在不同 workflow 上拿到**不同的数据栈**，同一用例结论相反：
#     CH-010（persona=xiaobu）在 agent-behavior-eval 上 0%（栈里 products=4，
#     B 端 prod_eval_2699 因 created_at 更新而排在第一，「第一款」指到了它），
#     在 xiaobu-acceptance 上 100%（products=3，首条是 C 端「北欧风窗帘」）。
#   商品列表默认 `ORDER BY created_at DESC`，而 `mibao_eval_seed.sql` 在
#   `xiaobu_eval_seed.sql` **之后**执行（`created_at DEFAULT NOW()`）→ 叠加即改排序。
#
# 口径（单一真值，改这里就等于改所有**起栈**的评测 workflow —— 这正是本文件存在的意义；
#   两种 persona 的栈 = **同一个 C 端底座** + 「有没有 B 端那一层」的差：
#     · xiaobu：仅 C 端种子（+ B 端 = 污染 C 端选品链路 → CH-010 那类假失败）
#     · mibao ：C 端种子 + B 端种子（B 端点名数据缺失会被误判成能力回归，#3496/#3511）
#   这与 `docs/testing/eval-environments.md`（"每个 persona 一套独立栈、全新库"）
#   以及 §16.3「每个 OR 分支至少一端可跑」的既有约定一致。
#
# 用法（workflow 侧只调用它，**不得**自己内联 fixture）：
#   bash scripts/eval_stack_seed.sh --persona "$PERSONA"
#   迭代/自检（不起栈、不连库，只打印该 persona 会装哪些种子）：
#   bash scripts/eval_stack_seed.sh --persona xiaobu --dry-run
#   （`--dry-run` 档**额外**跑一条离线判据：夹具 ⇄ 用例机器断言 的数据依赖契约，
#     判据源 = tests/agent_eval/eval_fixture_case_contract.py，见该模块 docstring）
#
# compose/common 可用环境变量覆盖（默认即仓库/CI 口径）：
#   EVAL_COMPOSE_FILE（默认 deploy/docker-compose.yml）
#   EVAL_PG_USER / EVAL_PG_DB（默认 app_user / ai_customer_service）
# ----------------------------------------------------------------------------
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${EVAL_COMPOSE_FILE:-deploy/docker-compose.yml}"
PG_USER="${EVAL_PG_USER:-app_user}"
PG_DB="${EVAL_PG_DB:-ai_customer_service}"
FIXTURES="tests/agent_eval/fixtures"

PERSONA=""
DRY_RUN="false"
while [ $# -gt 0 ]; do
  case "$1" in
    --persona)
      PERSONA="${2:-}"
      shift 2
      ;;
    --persona=*)
      PERSONA="${1#--persona=}"
      shift
      ;;
    --dry-run)
      DRY_RUN="true"
      shift
      ;;
    -h|--help)
      echo "用法: $0 --persona {xiaobu|mibao} [--dry-run]"
      exit 0
      ;;
    *)
      echo "::error::未知参数 $1（用法: $0 --persona {xiaobu|mibao} [--dry-run]）" >&2
      exit 2
      ;;
  esac
done

cd "$REPO_ROOT"

# ── 口径实现（唯一一处"哪个 persona 装哪些种子"的判断）──
# ⚠️ fail-closed：非法/缺失 persona **报错退出**，不静默回落。
#    静默回落会让"该 persona 专属用例"跑在错栈上，正是本 issue 的形态。
if [ "$PERSONA" != "xiaobu" ] && [ "$PERSONA" != "mibao" ]; then
  echo "::error::--persona 必须是 xiaobu 或 mibao（收到 '${PERSONA}'）—— 禁止静默回落：错栈会让用例假失败" >&2
  exit 2
fi

SEED_FILES=("$FIXTURES/xiaobu_eval_seed.sql")
if [ "$PERSONA" = "mibao" ]; then
  SEED_FILES+=("$FIXTURES/mibao_eval_seed.sql")
fi

for f in "${SEED_FILES[@]}"; do
  if [ ! -f "$f" ]; then
    echo "::error::缺少种子文件 $f" >&2
    exit 1
  fi
done

echo "── 评测栈种子注入：persona=${PERSONA}（单一源 scripts/eval_stack_seed.sh）──"
if [ ${#SEED_FILES[@]} -eq 1 ]; then
  echo "   规则：仅 C 端种子（xiaobu 栈不含 B 端 —— 叠加会改 created_at 排序，污染 C 端选品链路）"
else
  echo "   规则：C 端种子 + B 端种子（B 端点名数据：2699 商品/ERP 加工项目录 16 项/客户张三/员工王五/历史订单）"
fi

if [ "$DRY_RUN" = "true" ]; then
  for f in "${SEED_FILES[@]}"; do
    echo "seed: $f"
  done
  # ── 夹具 ⇄ 用例机器断言 的**数据依赖契约**（离线判据，issue #7043）────────────────
  # 治的形态：用例的机器断言要求某张表**有数据**，而夹具没种 ⇒ 断言永远无解 ⇒ 评测假红，
  # 而假红在报告里长得像产品缺陷（FN-001 的 `items: __nonempty__` / 种子没种
  # `finance_transactions`）。判据本体与台账见
  # `tests/agent_eval/eval_fixture_case_contract.py`（未登记即红、豁免只许缩短）。
  # 放在 `--dry-run` 档：这是「不起栈、不连库」的自检档 ⇒ 契约判定与种子清单**同时**可读，
  # 不需要任何真环境（远程注入档的同一份保障由 SQL 内的终态对账块承担）。
  echo "── 数据依赖契约自检（夹具 ⇄ 用例非空断言）──"
  python3 "$REPO_ROOT/tests/agent_eval/eval_fixture_case_contract.py" --check
  exit 0
fi

# ── 注入（幂等：fixture 内均为 ON CONFLICT DO NOTHING / WHERE NOT EXISTS）──
for f in "${SEED_FILES[@]}"; do
  echo "── 注入 $f ──"
  # ON_ERROR_STOP=1：注入失败必须 fail-fast（否则空库上跑评测 = 把数据缺口伪装成能力回归）
  docker compose -f "$COMPOSE_FILE" exec -T postgres \
    psql -v ON_ERROR_STOP=1 -U "$PG_USER" -d "$PG_DB" < "$f"
done

# ── 数据核对（五类计数，0 行即红 —— issue #7583 缺陷 7）──────────────
# 为什么必须判红：种子缺 SKU / 缺订单明细时，注入**不报错**，于是「数据缺口」要么把应红的
# 断言逼成假红（用例拿不到数据 ⇒ 能力回归），要么让断言无数据可判 = 假绿。
# 旧形态只数 products：`product_colors` / `product_skus` / `users` / 订单金额段**静默 0 行也绿**。
# 五类 = 商品 / 颜色 / SKU / 用户 / 订单明细（金额 = 明细 subtotal 合计 > 0）。
# 判据 = tests/unit_ci_workflows/test_seed_data_quality.py（stub `docker` 跑本脚本，逐类注入 0）。
echo "── 数据核对（persona=${PERSONA}）──"
# 标签在 bash 侧拼：SQL 里不用「两竖线」做字符串拼接 —— CI helper 的管道规模守卫
# 把两竖线也当管道计数，而 SQL 的连接符不是 shell 管道（本条注释同样避开那两个字
# 符，否则守卫会把注释也算成一例）
# `deleted` 列：users / order_items 走软删（口径与 tests/agent_eval/fixtures/*.sql 一致）
SEED_COUNTS_SQL="SELECT
  (SELECT count(*) FROM products WHERE tenant_id=1),
  (SELECT count(*) FROM product_colors WHERE tenant_id=1),
  (SELECT count(*) FROM product_skus WHERE tenant_id=1),
  (SELECT count(*) FROM users WHERE tenant_id=1 AND deleted=0),
  (SELECT count(*) FROM order_items WHERE tenant_id=1 AND deleted=0),
  (SELECT coalesce(sum(subtotal),0) FROM order_items WHERE tenant_id=1 AND deleted=0)"
if ! COUNTS=$(docker compose -f "$COMPOSE_FILE" exec -T postgres \
  psql -U "$PG_USER" -d "$PG_DB" -tAc "$SEED_COUNTS_SQL"); then
  echo "::error::种子计数查询失败（DB 不可达 / 列已改名？）—— 核对没跑成 ≠ 核对通过" >&2
  exit 1
fi
IFS='|' read -r -a C <<< "$COUNTS" || true
if [ "${#C[@]}" -ne 6 ]; then
  echo "::error::种子计数输出不可解析（期望 6 个数，实得 ${#C[@]}）：'${COUNTS}' —— 读不到 ≠ 通过" >&2
  exit 1
fi
COUNT_LABELS=(products colors skus users order_items)
for i in 0 1 2 3 4; do
  v="${C[$i]}"
  case "$v" in
    ''|*[!0-9]*)
      echo "::error::种子计数不可解析：${COUNT_LABELS[$i]}='${v}' —— 读不到 ≠ 通过" >&2
      exit 1
      ;;
  esac
  if [ "$v" -lt 1 ]; then
    echo "::error::种子计数不合格：${COUNT_LABELS[$i]}=0（persona=${PERSONA}）—— 夹具缺数据会让评测假红/假绿（issue #7583 缺陷 7）" >&2
    exit 1
  fi
done
case "${C[5]}" in
  ''|*[!0-9.]*)
    echo "::error::种子金额不可解析：order_amount='${C[5]}' —— 读不到 ≠ 通过" >&2
    exit 1
    ;;
esac
if ! awk -v a="${C[5]}" 'BEGIN{exit !(a+0 > 0)}'; then
  echo "::error::种子金额不合格：order_amount=${C[5]}（要求 > 0）—— 订单明细金额链没有数据（issue #7583 缺陷 7）" >&2
  exit 1
fi
echo "seed_counts products=${C[0]} colors=${C[1]} skus=${C[2]} users=${C[3]} order_items=${C[4]} order_amount=${C[5]}"

# 既有读数（跨 workflow 对照用；口径不变）
PRODUCTS="${C[0]}"
FIRST_PRODUCT=$(docker compose -f "$COMPOSE_FILE" exec -T postgres \
  psql -U "$PG_USER" -d "$PG_DB" -tAc \
  "SELECT name FROM products WHERE tenant_id=1 ORDER BY created_at DESC LIMIT 1")
echo "products=$PRODUCTS"
echo "first_product_by_created_at=$FIRST_PRODUCT"
echo "✅ 种子注入完成（persona=${PERSONA}）"
