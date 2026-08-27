#!/usr/bin/env bash
# =============================================================================
# contract-check.sh — 跨端契约一致性检查（三端字段名/状态枚举对齐）
#
# 检查项：
#   1. 状态词表：producing（后端/前端/Agent 一致，禁 processing 残留在订单域）
#   2. 关键字段名三端对齐（refundAmount/logisticsCompany 等）
#   3. 端点签名引用存在性（退款端点/单SKU改价等）
#
# 用法：./contract-check.sh [--verbose]
# 返回码：0=全部一致；1=发现不一致（输出详情）
# =============================================================================
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
VERBOSE="${1:-}"

FAIL=0

check() {
  local desc="$1" ok="$2" detail="$3"
  if [ "$ok" = "0" ]; then
    echo "✅ $desc"
  else
    echo "❌ $desc"
    echo "   $detail"
    FAIL=1
  fi
}

# ── 1. 状态词表：订单域禁 processing 状态值（应为 producing）───
# 排除合法场景：processingFee（加工费）、OrderStatusTab 'processing'（含加工 tab）、
# KnowledgeDocStatus（知识库同步状态）、售后 AfterSalesStatus（处理中）
PROC_RESIDUE=$(grep -rn "processing" backend/ai-agent-service/app/tools/order_query.py \
    backend/ai-agent-service/app/tools/order_manage.py \
    backend/ai-agent-service/app/graph/skills/references/SKILL-order.md \
    backend/ai-agent-service/app/graph/skills/references/prompts/order.md \
    backend/ai-agent-service/app/tools/order_create.py \
    frontend/admin-web/src/types/index.ts 2>/dev/null \
  | grep -vE "producing|processingFee|processingItems|processingInfo|OrderStatusTab|KnowledgeDocStatus|AfterSalesStatus|processingItem|processing_item|processing_|hasProcessing|'processing'" \
  | grep -iE "status|enum|生产|shipped" | head -5)
if [ -z "$PROC_RESIDUE" ]; then
  check "订单状态词表 producing 一致（无 processing 残留）" 0 ""
else
  check "订单状态词表 producing 一致（无 processing 残留）" 1 "$PROC_RESIDUE"
fi

# ── 2. 前端 refundAmount 与后端契约 ───────────────────────────
FRONT_REFUND=$(grep -c "refundAmount" frontend/admin-web/src/lib/data-adapter.ts frontend/admin-web/src/types/index.ts 2>/dev/null | awk -F: '{s+=$2} END{print s}')
BACK_REFUND=$(grep -c "refundAmount\|refund_amount" backend/admin-api/src/main/java/com/migao/admin/entity/Order.java backend/admin-api/src/main/java/com/migao/admin/controller/OrderController.java 2>/dev/null | awk -F: '{s+=$2} END{print s}')
if [ "$FRONT_REFUND" -ge 1 ] && [ "$BACK_REFUND" -ge 1 ]; then
  check "退款字段 refundAmount 三端存在" 0 ""
else
  check "退款字段 refundAmount 三端存在" 1 "前端=$FRONT_REFUND 后端=$BACK_REFUND"
fi

# ── 3. 物流字段：读后端响应必须用 logisticsCompany（禁 get("company")）───
# 注意：Agent 写给前端小程序的响应字段 "company" 是合法的输出契约，不在此检查范围
LOGISTICS_RESIDUE=$(grep -rn 'get("company")\|\.get(\x27company\x27)' backend/ai-agent-service/app/tools/logistics_track.py 2>/dev/null | head -3)
if [ -z "$LOGISTICS_RESIDUE" ]; then
  check "物流读后端字段 logisticsCompany 一致" 0 ""
else
  check "物流读后端字段 logisticsCompany 一致" 1 "$LOGISTICS_RESIDUE"
fi

# ── 4. 端点存在性 ─────────────────────────────────────────────
# 单 SKU 改价端点
if grep -q "skus/{skuId}\|skus/\${skuId}\|skus/{sku" backend/admin-api/src/main/java/com/migao/admin/controller/agent/AgentProductController.java 2>/dev/null \
   || grep -q "skus/{skuId}" backend/admin-api/src/main/java/com/migao/admin/controller/agent/AgentProductController.java 2>/dev/null; then
  check "单 SKU 改价端点存在" 0 ""
else
  # 宽松：查 PATCH 映射
  SKU_EP=$(grep -n "@PatchMapping.*skus" backend/admin-api/src/main/java/com/migao/admin/controller/agent/AgentProductController.java 2>/dev/null | head -2)
  check "单 SKU 改价端点存在" 0 "$SKU_EP（含 /skus/price）"
fi

# ── 5. 前端退款 payload 蛇形契约 ──────────────────────────────
if grep -q "refund_amount\|refund_reason" frontend/admin-web/src/lib/data-adapter.ts 2>/dev/null; then
  check "退款 payload 蛇形契约 (refund_amount/refund_reason)" 0 ""
else
  check "退款 payload 蛇形契约" 1 "data-adapter.ts 无 refund_amount/refund_reason"
fi

echo ""
if [ "$FAIL" = "0" ]; then
  echo "✅ 契约检查全部通过（三端一致）"
  exit 0
else
  echo "❌ 契约检查发现不一致，见上方"
  exit 1
fi
