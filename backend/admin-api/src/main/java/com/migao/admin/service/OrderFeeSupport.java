package com.migao.admin.service;

import com.migao.admin.entity.FinanceTransaction;
import com.migao.admin.entity.Order;
import com.migao.admin.mapper.FinanceTransactionMapper;
import com.migao.admin.time.BusinessClock;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.time.format.DateTimeFormatter;

/**
 * 订单<b>财务流水族</b>服务（issue #8191，P2-1c）。
 *
 * <p>从 {@link OrderService}（2,685 行）拆出的<b>记账面</b>：实收金额取数口径
 * （{@code actualAmount} 兜底 {@code totalAmount}）、收款/退款流水登记、流水号生成。
 * 收款点被确认支付调用，退款点被取消/退款调用 —— 三处都是「失败不影响主流程」的辅助数据，
 * 该语义逐字保留。</p>
 *
 * <p>拆的是<b>位置</b>，<b>不是行为</b>：方法体逐字搬运（金额口径 / 早退条件 / 异常吞掉的范围
 * 与日志话术不变）；{@link OrderService} 保留同名门面委托，现有调用方零改动。</p>
 *
 * <p><b>单向依赖</b>：本类只依赖 {@link FinanceTransactionMapper} 与业务时钟，<b>不</b>反向引用
 * {@link OrderService}。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class OrderFeeSupport {

    private final FinanceTransactionMapper financeTransactionMapper;
    private final BusinessClock businessClock;

    /**
     * 订单实际应收（实收）金额：actualAmount 兜底 totalAmount。
     */
    BigDecimal effectiveActualAmount(Order order) {
        return order.getActualAmount() != null ? order.getActualAmount() : order.getTotalAmount();
    }

    /**
     * 登记一笔订单关联的资金流水（收款/退款），金额取订单实收款。
     * 失败仅告警，不影响订单主流程（对账流水为辅助数据）。
     */
    void recordFinanceTransaction(Order order, String type, String remark) {
        BigDecimal amount = effectiveActualAmount(order);
        recordFinanceTransaction(order, amount, type, remark);
    }

    /**
     * 登记一笔订单关联的资金流水（收款/退款），金额显式指定（支持部分退款）。
     * 失败仅告警，不影响订单主流程（对账流水为辅助数据）。
     */
    void recordFinanceTransaction(Order order, BigDecimal amount, String type, String remark) {
        try {
            if (order == null) {
                return;
            }
            if (amount == null || amount.compareTo(BigDecimal.ZERO) <= 0) {
                return;
            }
            FinanceTransaction txn = FinanceTransaction.builder()
                    .tenantId(order.getTenantId())
                    .transactionNo(generateFinanceTransactionNo(order.getTenantId()))
                    .orderId(order.getId())
                    .orderNo(order.getOrderNo())
                    .type(type)
                    .amount(amount)
                    .status("success")
                    .operator("系统")
                    .occurredAt(OffsetDateTime.now())
                    .remark(remark)
                    .build();
            financeTransactionMapper.insert(txn);
            log.info("登记资金流水: transactionNo={}, type={}, amount={}, orderNo={}",
                    txn.getTransactionNo(), type, amount, order.getOrderNo());
        } catch (Exception e) {
            log.warn("登记资金流水失败（不影响订单主流程）: orderNo={}, type={}, error={}",
                    order != null ? order.getOrderNo() : null, type, e.getMessage());
        }
    }

    /**
     * 生成资金流水号（防重启重复）：FIN-yyyyMMdd-XXXX，从 DB 查当天最大序号 +1
     */
    String generateFinanceTransactionNo(Long tenantId) {
        String datePart = businessClock.today().format(DateTimeFormatter.ofPattern("yyyyMMdd"));
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
}
