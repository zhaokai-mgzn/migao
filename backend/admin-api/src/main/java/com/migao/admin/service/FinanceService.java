package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.migao.admin.dto.*;
import com.migao.admin.entity.FinanceTransaction;
import com.migao.admin.entity.Order;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.FinanceTransactionMapper;
import com.migao.admin.mapper.OrderMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.BeanUtils;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;
import java.util.Collections;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;
import java.util.stream.Collectors;

/**
 * 财务对账服务
 *
 * <p>职责：</p>
 * <ul>
 *   <li>资金流水（收款/退款）查询与手动登记</li>
 *   <li>收支汇总（收入/退款/净额 + 按支付方式 + 按日趋势）</li>
 *   <li>应收对账（订单维度应收/实收/已退/差额）</li>
 * </ul>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class FinanceService extends ServiceImpl<FinanceTransactionMapper, FinanceTransaction> {

    private final FinanceTransactionMapper financeTransactionMapper;
    private final OrderMapper orderMapper;

    private static final Set<String> VALID_TYPES = Set.of("income", "refund");
    private static final Set<String> VALID_METHODS = Set.of("wechat", "alipay", "bank_transfer", "cash", "other");

    // ==================== 资金流水 ====================

    /**
     * 分页查询资金流水
     */
    public PageResponse<FinanceTransactionListResponse> getTransactionPage(
            long page, long size, String type, String paymentMethod, String status,
            String startDate, String endDate, String keyword, Long tenantId) {
        LambdaQueryWrapper<FinanceTransaction> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(FinanceTransaction::getTenantId, tenantId);

        if (StringUtils.hasText(type)) {
            wrapper.eq(FinanceTransaction::getType, type);
        }
        if (StringUtils.hasText(paymentMethod)) {
            wrapper.eq(FinanceTransaction::getPaymentMethod, paymentMethod);
        }
        if (StringUtils.hasText(status)) {
            wrapper.eq(FinanceTransaction::getStatus, status);
        }
        if (StringUtils.hasText(startDate)) {
            wrapper.ge(FinanceTransaction::getOccurredAt, parseDateStart(startDate));
        }
        if (StringUtils.hasText(endDate)) {
            wrapper.le(FinanceTransaction::getOccurredAt, parseDateEnd(endDate));
        }
        if (StringUtils.hasText(keyword)) {
            wrapper.and(w -> w.like(FinanceTransaction::getTransactionNo, keyword)
                    .or().like(FinanceTransaction::getOrderNo, keyword));
        }

        wrapper.orderByDesc(FinanceTransaction::getOccurredAt)
                .orderByDesc(FinanceTransaction::getCreatedAt);

        Page<FinanceTransaction> txPage = new Page<>(page, size);
        Page<FinanceTransaction> result = financeTransactionMapper.selectPage(txPage, wrapper);

        List<FinanceTransactionListResponse> items = result.getRecords().stream()
                .map(this::toListResponse)
                .collect(Collectors.toList());

        return PageResponse.of(result.getTotal(), result.getCurrent(), result.getSize(), items);
    }

    /**
     * 手动登记一笔收支（线下收款/退款）
     */
    @Transactional(rollbackFor = Exception.class)
    public FinanceTransactionListResponse createTransaction(
            FinanceTransactionCreateRequest request, Long tenantId, String operator) {
        String type = request.getType();
        if (!VALID_TYPES.contains(type)) {
            throw BusinessException.validationError("收支类型无效，可选 income（收款）/ refund（退款）");
        }
        if (request.getAmount() == null || request.getAmount().compareTo(BigDecimal.ZERO) <= 0) {
            throw BusinessException.validationError("金额必须大于 0");
        }
        if (StringUtils.hasText(request.getPaymentMethod()) && !VALID_METHODS.contains(request.getPaymentMethod())) {
            throw BusinessException.validationError("支付方式无效，可选 wechat/alipay/bank_transfer/cash/other");
        }
        if (StringUtils.hasText(request.getRemark()) && request.getRemark().length() > 500) {
            throw BusinessException.validationError("备注不能超过 500 个字符");
        }

        // 关联订单（可选）：支持 UUID 或订单号，校验存在并冗余订单号
        String orderId = null;
        String orderNo = null;
        if (StringUtils.hasText(request.getOrderId())) {
            Order order = resolveOrder(request.getOrderId(), tenantId);
            if (order == null) {
                throw BusinessException.notFound("订单");
            }
            orderId = order.getId();
            orderNo = order.getOrderNo();
        }

        FinanceTransaction txn = FinanceTransaction.builder()
                .tenantId(tenantId)
                .transactionNo(generateTransactionNo(tenantId))
                .orderId(orderId)
                .orderNo(orderNo)
                .type(type)
                .amount(request.getAmount())
                .paymentMethod(StringUtils.hasText(request.getPaymentMethod()) ? request.getPaymentMethod() : "other")
                .status("success")
                .operator(operator)
                .occurredAt(parseOccurredAt(request.getOccurredAt()))
                .remark(request.getRemark())
                .build();

        financeTransactionMapper.insert(txn);
        log.info("登记资金流水成功: transactionNo={}, type={}, amount={}, operator={}",
                txn.getTransactionNo(), type, request.getAmount(), operator);

        return toListResponse(txn);
    }

    /**
     * 登记一笔订单退款流水（type=refund），供售后工单完结联动等业务调用。
     * 金额必须为正；amount ≤ 0 或 order 为空时直接忽略。
     */
    @Transactional(rollbackFor = Exception.class)
    public void recordRefund(Order order, BigDecimal amount, String remark) {
        if (order == null || amount == null || amount.compareTo(BigDecimal.ZERO) <= 0) {
            return;
        }
        FinanceTransaction txn = FinanceTransaction.builder()
                .tenantId(order.getTenantId())
                .transactionNo(generateTransactionNo(order.getTenantId()))
                .orderId(order.getId())
                .orderNo(order.getOrderNo())
                .type("refund")
                .amount(amount)
                .status("success")
                .operator("系统")
                .occurredAt(OffsetDateTime.now())
                .remark(remark)
                .build();
        financeTransactionMapper.insert(txn);
        log.info("登记退款流水: transactionNo={}, amount={}, orderNo={}, remark={}",
                txn.getTransactionNo(), amount, order.getOrderNo(), remark);
    }

    // ==================== 收支汇总 ====================

    /**
     * 收支汇总（按时间范围聚合流水 + 订单维度待收款）
     */
    public FinanceSummaryResponse getSummary(String startDate, String endDate, Long tenantId) {
        LambdaQueryWrapper<FinanceTransaction> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(FinanceTransaction::getTenantId, tenantId);
        if (StringUtils.hasText(startDate)) {
            wrapper.ge(FinanceTransaction::getOccurredAt, parseDateStart(startDate));
        }
        if (StringUtils.hasText(endDate)) {
            wrapper.le(FinanceTransaction::getOccurredAt, parseDateEnd(endDate));
        }
        List<FinanceTransaction> txns = financeTransactionMapper.selectList(wrapper);

        BigDecimal totalIncome = BigDecimal.ZERO;
        BigDecimal totalRefund = BigDecimal.ZERO;
        long incomeCount = 0;
        long refundCount = 0;
        Map<String, BigDecimal[]> byMethod = new LinkedHashMap<>();
        Map<String, BigDecimal[]> daily = new TreeMap<>();

        for (FinanceTransaction t : txns) {
            if (!"success".equals(t.getStatus())) {
                continue;
            }
            BigDecimal amt = nz(t.getAmount());
            boolean isIncome = "income".equals(t.getType());
            boolean isRefund = "refund".equals(t.getType());
            if (!isIncome && !isRefund) {
                continue;
            }

            if (isIncome) {
                totalIncome = totalIncome.add(amt);
                incomeCount++;
            } else {
                totalRefund = totalRefund.add(amt);
                refundCount++;
            }

            String method = StringUtils.hasText(t.getPaymentMethod()) ? t.getPaymentMethod() : "other";
            byMethod.computeIfAbsent(method, k -> new BigDecimal[]{BigDecimal.ZERO, BigDecimal.ZERO});
            BigDecimal[] methodAcc = byMethod.get(method);
            if (isIncome) {
                methodAcc[0] = methodAcc[0].add(amt);
            } else {
                methodAcc[1] = methodAcc[1].add(amt);
            }

            String date = toDate(t.getOccurredAt() != null ? t.getOccurredAt() : t.getCreatedAt());
            daily.computeIfAbsent(date, k -> new BigDecimal[]{BigDecimal.ZERO, BigDecimal.ZERO});
            BigDecimal[] dailyAcc = daily.get(date);
            if (isIncome) {
                dailyAcc[0] = dailyAcc[0].add(amt);
            } else {
                dailyAcc[1] = dailyAcc[1].add(amt);
            }
        }

        BigDecimal netIncome = totalIncome.subtract(totalRefund);

        List<FinanceSummaryResponse.MethodSummary> methods = byMethod.entrySet().stream()
                .map(e -> FinanceSummaryResponse.MethodSummary.builder()
                        .paymentMethod(e.getKey())
                        .income(e.getValue()[0])
                        .refund(e.getValue()[1])
                        .net(e.getValue()[0].subtract(e.getValue()[1]))
                        .build())
                .collect(Collectors.toList());

        List<FinanceSummaryResponse.DailySummary> dailyList = daily.entrySet().stream()
                .map(e -> FinanceSummaryResponse.DailySummary.builder()
                        .date(e.getKey())
                        .income(e.getValue()[0])
                        .refund(e.getValue()[1])
                        .net(e.getValue()[0].subtract(e.getValue()[1]))
                        .build())
                .collect(Collectors.toList());

        return FinanceSummaryResponse.builder()
                .startDate(startDate)
                .endDate(endDate)
                .totalIncome(totalIncome)
                .totalRefund(totalRefund)
                .netIncome(netIncome)
                .incomeCount(incomeCount)
                .refundCount(refundCount)
                .pendingReceivable(computePendingReceivable(tenantId))
                .byPaymentMethod(methods)
                .dailyTrend(dailyList)
                .build();
    }

    // ==================== 应收对账 ====================

    /**
     * 应收对账（订单维度）
     */
    public PageResponse<ReceivableReconciliationResponse> getReconciliation(
            long page, long size, String startDate, String endDate, String keyword, Long tenantId) {
        LambdaQueryWrapper<Order> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(Order::getTenantId, tenantId);
        if (StringUtils.hasText(startDate)) {
            wrapper.ge(Order::getCreatedAt, parseDateStart(startDate));
        }
        if (StringUtils.hasText(endDate)) {
            wrapper.le(Order::getCreatedAt, parseDateEnd(endDate));
        }
        if (StringUtils.hasText(keyword)) {
            wrapper.and(w -> w.like(Order::getOrderNo, keyword)
                    .or().like(Order::getCustomerName, keyword)
                    .or().like(Order::getCustomerPhone, keyword));
        }
        wrapper.orderByDesc(Order::getCreatedAt);

        Page<Order> orderPage = new Page<>(page, size);
        Page<Order> result = orderMapper.selectPage(orderPage, wrapper);

        List<String> orderIds = result.getRecords().stream()
                .map(Order::getId)
                .collect(Collectors.toList());
        Map<String, BigDecimal> refundMap = sumRefundByOrder(orderIds, tenantId);

        List<ReceivableReconciliationResponse> items = result.getRecords().stream()
                .map(o -> {
                    BigDecimal receivable = nz(o.getTotalAmount());
                    BigDecimal received = o.getActualAmount() != null ? o.getActualAmount() : receivable;
                    BigDecimal refund = refundMap.getOrDefault(o.getId(), BigDecimal.ZERO);
                    // 差额 = 应收 - 实收 + 已退（净应收口径：退款订单差额不为 0，标识资金未完全收回）
                    return ReceivableReconciliationResponse.builder()
                            .orderId(o.getId())
                            .orderNo(o.getOrderNo())
                            .customerName(o.getCustomerName())
                            .customerPhone(o.getCustomerPhone())
                            .status(o.getStatus())
                            .receivableAmount(receivable)
                            .receivedAmount(received)
                            .refundAmount(refund)
                            .difference(receivable.subtract(received).add(refund))
                            .createdAt(o.getCreatedAt())
                            .build();
                })
                .collect(Collectors.toList());

        return PageResponse.of(result.getTotal(), result.getCurrent(), result.getSize(), items);
    }

    // ==================== 私有工具方法 ====================

    /**
     * 订单维度待收款：非取消订单中「应收 > 实收」的差额累计（余额口径，不分时间范围）。
     */
    private BigDecimal computePendingReceivable(Long tenantId) {
        List<Order> orders = orderMapper.selectList(new LambdaQueryWrapper<Order>()
                .eq(Order::getTenantId, tenantId)
                .in(Order::getStatus, "confirmed", "producing", "shipped", "completed"));
        BigDecimal pending = BigDecimal.ZERO;
        for (Order o : orders) {
            BigDecimal receivable = nz(o.getTotalAmount());
            BigDecimal received = o.getActualAmount() != null ? o.getActualAmount() : receivable;
            if (receivable.compareTo(received) > 0) {
                pending = pending.add(receivable.subtract(received));
            }
        }
        return pending;
    }

    /**
     * 批量统计各订单的退款流水合计
     */
    private Map<String, BigDecimal> sumRefundByOrder(List<String> orderIds, Long tenantId) {
        if (orderIds == null || orderIds.isEmpty()) {
            return Collections.emptyMap();
        }
        List<FinanceTransaction> refunds = financeTransactionMapper.selectList(
                new LambdaQueryWrapper<FinanceTransaction>()
                        .eq(FinanceTransaction::getTenantId, tenantId)
                        .eq(FinanceTransaction::getType, "refund")
                        .eq(FinanceTransaction::getStatus, "success")
                        .in(FinanceTransaction::getOrderId, orderIds));
        Map<String, BigDecimal> refundMap = new HashMap<>();
        for (FinanceTransaction t : refunds) {
            refundMap.merge(t.getOrderId(), nz(t.getAmount()), BigDecimal::add);
        }
        return refundMap;
    }

    /**
     * 解析订单 ID：UUID 精确匹配 → 订单号匹配
     */
    private Order resolveOrder(String raw, Long tenantId) {
        Order byId = orderMapper.selectOne(new LambdaQueryWrapper<Order>()
                .eq(Order::getId, raw)
                .eq(Order::getTenantId, tenantId));
        if (byId != null) {
            return byId;
        }
        return orderMapper.selectOne(new LambdaQueryWrapper<Order>()
                .eq(Order::getTenantId, tenantId)
                .eq(Order::getOrderNo, raw));
    }

    /**
     * 生成流水号（防重启重复）：FIN-yyyyMMdd-XXXX，从 DB 查当天最大序号 +1
     */
    private String generateTransactionNo(Long tenantId) {
        String datePart = LocalDate.now().format(DateTimeFormatter.ofPattern("yyyyMMdd"));
        String prefix = "FIN-" + datePart + "-";
        int nextSeq = 1;
        try {
            FinanceTransaction latest = financeTransactionMapper.selectOne(
                    new LambdaQueryWrapper<FinanceTransaction>()
                            .eq(FinanceTransaction::getTenantId, tenantId)
                            .likeRight(FinanceTransaction::getTransactionNo, prefix)
                            .orderByDesc(FinanceTransaction::getTransactionNo)
                            .last("LIMIT 1"));
            if (latest != null && latest.getTransactionNo() != null) {
                String[] parts = latest.getTransactionNo().split("-");
                if (parts.length == 3) {
                    nextSeq = Integer.parseInt(parts[2]) + 1;
                }
            }
        } catch (Exception e) {
            log.warn("查询最新流水号失败，使用默认序号: {}", e.getMessage());
        }
        return String.format("FIN-%s-%04d", datePart, nextSeq % 10000);
    }

    private FinanceTransactionListResponse toListResponse(FinanceTransaction txn) {
        FinanceTransactionListResponse response = new FinanceTransactionListResponse();
        BeanUtils.copyProperties(txn, response);
        return response;
    }

    private BigDecimal nz(BigDecimal value) {
        return value != null ? value : BigDecimal.ZERO;
    }

    private String toDate(OffsetDateTime time) {
        return time != null ? time.toLocalDate().toString() : "";
    }

    private OffsetDateTime parseDateStart(String date) {
        return OffsetDateTime.parse(date + "T00:00:00Z");
    }

    private OffsetDateTime parseDateEnd(String date) {
        return OffsetDateTime.parse(date + "T23:59:59Z");
    }

    private OffsetDateTime parseOccurredAt(String value) {
        if (!StringUtils.hasText(value)) {
            return OffsetDateTime.now();
        }
        try {
            return OffsetDateTime.parse(value);
        } catch (DateTimeParseException e) {
            try {
                return LocalDateTime.parse(value, DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss"))
                        .atOffset(ZoneOffset.UTC);
            } catch (DateTimeParseException e2) {
                return OffsetDateTime.now();
            }
        }
    }
}
