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
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 订单毛利（issue #7371，P0-3 段 1 + 段 2）：收入 − 退款 − 面料成本 − 加工成本。
 *
 * <h3>取数（每一条都复用既有口径，不新造第二套）</h3>
 * <ul>
 *   <li>面料成本：`stock_batch_consumptions` 的扣料行（`reason = 'processing_order'`，按 `order_no` 归属）
 *       × 该行 `unit_cost`（**当时**的批次进价快照，V119 起就有了）；</li>
 *   <li>加工成本（段 2）：`ProductionService.piecework(...)` 的 `total` —— 与计件工资 / 期间报表
 *       **同一份聚合**；该聚合的 `unpriced` 块给出**未定价报工**的数量（issue #4696 的既有口径：
 *       未定价**不进金额**，但必须能被数出来）⇒ 有未定价 ⇒ **加工成本未知**；</li>
 *   <li>退款：`finance_transactions` 的 `refund ∧ success` 合计；</li>
 *   <li>运费：**系统未采集**（表里没有运费字段）⇒ `freightCaptured = false`，**不按 0 计入**；</li>
 *   <li>判定：纯函数 {@link OrderMargin}（任一成本未知 ⇒ 毛利 null，绝不当 0）。</li>
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

    /**
     * 计件金额的唯一聚合口径（issue #4205 / #4696）：加工成本**复用**它，不在这里重算一遍
     * —— 重算就是第二条会漂移的真相（车间工资单与毛利会是两个数）。
     */
    private final ProductionService productionService;

    /** 单个订单的毛利。 */
    public OrderMarginView margin(String orderId) {
        Order order = orderMapper.selectById(orderId);
        if (order == null) {
            throw BusinessException.notFound("订单");
        }
        Long tenantId = order.getTenantId();

        Map<String, Object> fabric = orderMapper.selectFabricCost(tenantId, order.getOrderNo());
        BigDecimal refunded = sumRefund(order.getId(), tenantId);
        return assemble(order, fabric, refunded, productionService.piecework(order.getId(), tenantId));
    }

    /**
     * **批量**毛利（issue #7582，报表中心的订单毛利）：面料 1 条 `GROUP BY`、退款 1 条 `IN`、计件 4 条
     * —— 合计 6 条 SQL 与订单数**无关**，替代原来「每单 8 条」的 N+1（500 单上界 ≈ 4000 条）。
     *
     * <p>🔴 只是**取数**变了：逐单仍交给 {@link #assemble} → {@link OrderMargin#compute} 这唯一一份口径 ⇒
     * 批量与逐单逐字段相同。判据 = {@code OrderMarginBatchTest}（同一批订单两条路径逐单比对，
     * 任一字段不等即红）。</p>
     *
     * @param orders 调用方已查出的订单（本方法不回查订单 —— 单条路径在这里还要多一条）
     */
    public List<OrderMarginView> margins(List<Order> orders) {
        if (orders == null || orders.isEmpty()) {
            return List.of();
        }
        Long tenantId = orders.get(0).getTenantId();
        List<String> orderNos = new ArrayList<>(orders.size());
        List<String> orderIds = new ArrayList<>(orders.size());
        for (Order order : orders) {
            if (order.getOrderNo() != null) {
                orderNos.add(order.getOrderNo());
            }
            orderIds.add(order.getId());
        }

        // ① 面料：一次 GROUP BY（三元组与 selectFabricCost 逐字相同）
        Map<String, Map<String, Object>> fabricByOrderNo = new HashMap<>();
        if (!orderNos.isEmpty()) {
            for (Map<String, Object> row : orderMapper.selectFabricCosts(tenantId, orderNos)) {
                fabricByOrderNo.put(String.valueOf(row.get("order_no")), row);
            }
        }
        // ② 退款：一次 IN + 内存分组（条件与 sumRefund 相同：refund ∧ success ∧ 同租户）
        Map<String, BigDecimal> refundByOrderId = new HashMap<>();
        for (FinanceTransaction txn : financeTransactionMapper.selectList(
                new LambdaQueryWrapper<FinanceTransaction>()
                        .eq(FinanceTransaction::getTenantId, tenantId)
                        .eq(FinanceTransaction::getType, "refund")
                        .eq(FinanceTransaction::getStatus, "success")
                        .in(FinanceTransaction::getOrderId, orderIds))) {
            if (txn.getOrderId() == null) {
                continue;
            }
            refundByOrderId.merge(txn.getOrderId(),
                    txn.getAmount() == null ? BigDecimal.ZERO : txn.getAmount(), BigDecimal::add);
        }
        // ③ 计件：4 条批量（ProductionService 里仍是同一份聚合，见 pieceworkByOrders）
        Map<String, Map<String, Object>> pieceworkByOrderId =
                productionService.pieceworkByOrders(orders, tenantId);

        List<OrderMarginView> views = new ArrayList<>(orders.size());
        for (Order order : orders) {
            views.add(assemble(order, fabricByOrderNo.get(order.getOrderNo()),
                    refundByOrderId.getOrDefault(order.getId(), BigDecimal.ZERO),
                    pieceworkByOrderId.get(order.getId())));
        }
        return views;
    }

    /** 单张订单的**唯一装配处**：{@link #margin} 与 {@link #margins} 共用（口径只此一份）。 */
    private OrderMarginView assemble(Order order, Map<String, Object> fabric,
                                     BigDecimal refunded, Map<String, Object> piecework) {
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
        BigDecimal refundedAmount = refunded == null ? BigDecimal.ZERO : refunded;
        BigDecimal laborCost = toDecimal(piecework == null ? null : piecework.get("total"))
                .setScale(2, RoundingMode.HALF_UP);
        int unpricedLines = countUnpricedLabor(piecework);
        if (unpricedLines > 0) {
            laborCost = null;   // 有未定价报工 ⇒ 加工成本未知（不按 0 计入）
        }
        OrderMargin.Result result = OrderMargin.compute(
                order.getTotalAmount(), refundedAmount, fabricCost, unknownLines, laborCost, unpricedLines);

        return OrderMarginView.builder()
                .orderId(order.getId())
                .orderNo(order.getOrderNo())
                .status(order.getStatus())
                .scope(OrderMargin.SCOPE_FABRIC_AND_LABOR)
                .revenue(scale(order.getTotalAmount()))
                .refunded(scale(refundedAmount))
                .fabricCost(result.fabricCost())
                .laborCost(result.laborCost())
                .unpricedLaborLines(unpricedLines)
                .freightCaptured(false)
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

    /**
     * 未定价报工**行数**（issue #4696 的口径：未定价不进金额，但必须能被数出来）。
     *
     * <p>取 `piecework` 返回里 `unpriced.qty` 的数量类读数：&gt; 0 表示「有活儿干了但没定价」
     * ⇒ 加工成本**未知**（不是 0）。</p>
     */
    private static int countUnpricedLabor(Map<String, Object> piecework) {
        Object unpriced = piecework == null ? null : piecework.get("unpriced");
        if (!(unpriced instanceof Map<?, ?> block)) {
            return 0;
        }
        Object qty = block.get("qty");
        if (qty instanceof Number number) {
            return number.doubleValue() > 0 ? 1 : 0;   // 有数量 ⇒ 至少一行未定价
        }
        if (qty instanceof BigDecimal decimal) {
            return decimal.signum() > 0 ? 1 : 0;
        }
        return 0;
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
