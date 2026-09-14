#!/usr/bin/env bash
# ============================================================================
# 评测栈种子注入 —— **单一实现**（issue #3563）
# ============================================================================
# 为什么要有这个文件（根因，勿删注释）：
#   此前三个评测 workflow **各写一份**种子规则，且互不相等：
#     · xiaobu-acceptance.yml   只当 persona=mibao 时叠 B 端种子
#     · post-deploy-eval.yml    只当 matrix.persona=mibao 时叠 B 端种子
#     · agent-behavior-eval.yml **无条件**叠 B 端种子（一个 job 里跑双端分桶）
#   于是同一个 persona 在不同 workflow 上拿到**不同的数据栈**，同一用例结论相反：
#     CH-010（persona=xiaobu）在 agent-behavior-eval 上 0%（栈里 products=4，
#     B 端 prod_eval_2699 因 created_at 更新而排在第一，「第一款」指到了它），
#     在 xiaobu-acceptance 上 100%（products=3，首条是 C 端「北欧风窗帘」）。
#   商品列表默认 `ORDER BY created_at DESC`，而 `mibao_eval_seed.sql` 在
#   `xiaobu_eval_seed.sql` **之后**执行（`created_at DEFAULT NOW()`）→ 叠加即改排序。
#
# 口径（单一真值，改这里就等于改三个 workflow —— 这正是本文件存在的意义）：
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
  echo "   规则：C 端种子 + B 端种子（B 端点名数据：2699 商品/刺绣工艺/客户张三/员工王五/历史订单）"
fi

if [ "$DRY_RUN" = "true" ]; then
  for f in "${SEED_FILES[@]}"; do
    echo "seed: $f"
  done
  exit 0
fi

# ── 注入（幂等：fixture 内均为 ON CONFLICT DO NOTHING / WHERE NOT EXISTS）──
for f in "${SEED_FILES[@]}"; do
  echo "── 注入 $f ──"
  # ON_ERROR_STOP=1：注入失败必须 fail-fast（否则空库上跑评测 = 把数据缺口伪装成能力回归）
  docker compose -f "$COMPOSE_FILE" exec -T postgres \
    psql -v ON_ERROR_STOP=1 -U "$PG_USER" -d "$PG_DB" < "$f"
done

# ── 数据核对（把"栈里到底有什么"打进日志，供跨 workflow 对照 —— 本 issue 的取证手段）──
echo "── 数据核对（persona=${PERSONA}）──"
# 标签在 bash 侧拼：SQL 里不用「两竖线」做字符串拼接 —— CI helper 的管道规模守卫
# 把两竖线也当管道计数，而 SQL 的连接符不是 shell 管道（本条注释同样避开那两个字
# 符，否则守卫会把注释也算成一例）
PRODUCTS=$(docker compose -f "$COMPOSE_FILE" exec -T postgres \
  psql -U "$PG_USER" -d "$PG_DB" -tAc \
  "SELECT count(*) FROM products WHERE tenant_id=1")
FIRST_PRODUCT=$(docker compose -f "$COMPOSE_FILE" exec -T postgres \
  psql -U "$PG_USER" -d "$PG_DB" -tAc \
  "SELECT name FROM products WHERE tenant_id=1 ORDER BY created_at DESC LIMIT 1")
echo "products=$PRODUCTS"
echo "first_product_by_created_at=$FIRST_PRODUCT"
echo "✅ 种子注入完成（persona=${PERSONA}）"
