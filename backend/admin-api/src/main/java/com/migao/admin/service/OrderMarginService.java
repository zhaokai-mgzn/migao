package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.migao.admin.dto.OrderMarginView;
import com.migao.admin.entity.FinanceTransaction;
import com.migao.admin.entity.Order;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.FinanceTransactionMapper;
import com.migao.admin.mapper.OrderMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.List;
import java.util.Map;

/**
 * 订单毛利（issue #7371，P0-3 段 1）：收入 − 退款 − 面料成本。
 *
 * <h3>取数</h3>
 * <ul>
 *   <li>面料成本：`stock_batch_consumptions` 的扣料行（`reason = 'processing_order'`，按 `order_no` 归属）
 *       × 该行 `unit_cost`（**当时**的批次进价快照，V119 起就有了）；</li>
 *   <li>退款：`finance_transactions` 的 `refund ∧ success` 合计；</li>
 *   <li>判定：纯函数 {@link OrderMargin}（未知成本绝不当 0）。</li>
 * </ul>
 *
 * <p>⚠️ 本服务**只读**：不改任何金额、不落任何派生列（毛利是算出来的，不是存出来的 ——
 * 存一份就有两个会漂移的真相）。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class OrderMarginService {

    private final OrderMapper orderMapper;
    private final FinanceTransactionMapper financeTransactionMapper;

    /** 单个订单的毛利。 */
    public OrderMarginView margin(String orderId) {
        Order order = orderMapper.selectById(orderId);
        if (order == null) {
            throw BusinessException.notFound("订单");
        }
        Long tenantId = order.getTenantId();

        Map<String, Object> fabric = orderMapper.selectFabricCost(tenantId, order.getOrderNo());
        BigDecimal fabricCost = fabric == null ? BigDecimal.ZERO : toDecimal(fabric.get("fabric_cost"));
        int unknownLines = fabric == null ? 0 : ((Number) fabric.getOrDefault("unknown_lines", 0)).intValue();
        int lines = fabric == null ? 0 : ((Number) fabric.getOrDefault("lines", 0)).intValue();
        // 没有任何扣料行 ⇒ 面料成本 = 0（真 0：还没领料），不是「未知」
        if (lines == 0) {
            fabricCost = BigDecimal.ZERO.setScale(2, RoundingMode.HALF_UP);
            unknownLines = 0;
        } else if (unknownLines > 0) {
            fabricCost = null;   // 有行缺进价 ⇒ 成本未知（绝不当 0）
        }

        BigDecimal refunded = sumRefund(order.getId(), tenantId);
        OrderMargin.Result result = OrderMargin.compute(
                order.getTotalAmount(), refunded, fabricCost, unknownLines);

        return OrderMarginView.builder()
                .orderId(order.getId())
                .orderNo(order.getOrderNo())
                .status(order.getStatus())
                .scope(OrderMargin.SCOPE_FABRIC_ONLY)
                .revenue(scale(order.getTotalAmount()))
                .refunded(scale(refunded))
                .fabricCost(result.fabricCost())
                .grossMargin(result.grossMargin())
                .marginRate(result.marginRate())
                .costKnown(result.costKnown())
                .fabricLines(lines)
                .unknownFabricLines(unknownLines)
                .build();
    }

    private BigDecimal sumRefund(String orderId, Long tenantId) {
        List<FinanceTransaction> refunds = financeTransactionMapper.selectList(
                new LambdaQueryWrapper<FinanceTransaction>()
                        .eq(FinanceTransaction::getTenantId, tenantId)
                        .eq(FinanceTransaction::getType, "refund")
                        .eq(FinanceTransaction::getStatus, "success")
                        .eq(FinanceTransaction::getOrderId, orderId));
        BigDecimal sum = BigDecimal.ZERO;
        for (FinanceTransaction row : refunds) {
            sum = sum.add(row.getAmount() == null ? BigDecimal.ZERO : row.getAmount());
        }
        return sum;
    }

    private static BigDecimal toDecimal(Object value) {
        if (value == null) {
            return BigDecimal.ZERO;
        }
        return value instanceof BigDecimal decimal ? decimal : new BigDecimal(value.toString());
    }

    private static BigDecimal scale(BigDecimal value) {
        return (value == null ? BigDecimal.ZERO : value).setScale(2, RoundingMode.HALF_UP);
    }
}
