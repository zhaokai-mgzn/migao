package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.migao.admin.dto.ReceiptAllocationRequest;
import com.migao.admin.dto.ReceiptAllocationView;
import com.migao.admin.entity.FinanceTransaction;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.ReceiptAllocation;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.FinanceTransactionMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ReceiptAllocationMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 客户收款核销（issue #7370，P0-2 段 3）：**一笔收入流水冲抵多张订单**。
 *
 * <h3>现金真值源不复制</h3>
 * <p>金额/方式/日期只认 {@code finance_transactions}；本服务只写「这笔钱冲到哪张单、各多少」。
 * 表里若复制一份金额，就有两个会漂移的合计。</p>
 *
 * <h3>两条硬约束（都由纯函数 {@link ReceiptAllocationPolicy} 判定，逐格有判据）</h3>
 * <ol>
 *   <li>同一流水：Σ核销 ≤ 流水金额（差额 = 预收 / 待勾对，允许且必须能显示）；</li>
 *   <li>同一订单：Σ核销 ≤ 货值 − 退款（同一张单不许被重复收钱）。</li>
 * </ol>
 *
 * <h3>为什么批量一行一行判、且在事务里</h3>
 * <p>一次提交多行时，上一行**已经占用**了收款剩余 ⇒ 下一行必须在「含本批已判」的余量上再判，
 * 否则两行合起来超过流水金额。整批在同一事务里：任一行不合规 ⇒ 全部回滚（不留半笔核销）。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ReceiptAllocationService {

    private final ReceiptAllocationMapper allocationMapper;
    private final FinanceTransactionMapper financeTransactionMapper;
    private final OrderMapper orderMapper;

    /**
     * 核销一笔收入流水（可多行）。
     *
     * @param transactionId 收入流水 id（必须是 type=income ∧ status=success）
     * @param request       核销明细（至少一行）
     * @param tenantId      当前租户
     * @param operator      操作人（落 created_by，核销要能追到人）
     */
    @Transactional(rollbackFor = Exception.class)
    public ReceiptAllocationView allocate(String transactionId,
                                          ReceiptAllocationRequest request,
                                          Long tenantId,
                                          String operator) {
        FinanceTransaction transaction = requireIncomeReceipt(transactionId);

        List<ReceiptAllocationRequest.Line> lines = request == null ? null : request.getLines();
        if (lines == null || lines.isEmpty()) {
            throw BusinessException.validationError("核销至少要选一张订单");
        }

        // 同一批里对同一张单出现两次 ⇒ 直接拒：两张行的合计会绕过「单张单上限」的逐行判定
        Set<String> seen = new LinkedHashSet<>();
        for (ReceiptAllocationRequest.Line line : lines) {
            String orderId = trimToNull(line.getOrderId());
            if (orderId == null) {
                throw BusinessException.validationError("核销明细必须指定订单");
            }
            if (!seen.add(orderId)) {
                throw BusinessException.validationError("同一张订单在本批核销里出现了多次，请合并成一行");
            }
        }

        BigDecimal receiptAllocated = sumByTransaction(transactionId);
        boolean first = true;
        for (ReceiptAllocationRequest.Line line : lines) {
            String orderId = trimToNull(line.getOrderId());
            BigDecimal amount = line.getAmount();
            if (amount == null || amount.signum() <= 0) {
                throw BusinessException.validationError("核销金额必须大于 0");
            }
            // 金额准入（issue #6221）：钱只有两位小数的物理意义；超精度输入直接拒，不静默四舍五入
            amount = MoneyScale.requireTwoDecimalsOrNull(amount, "核销金额")
                    .setScale(2, RoundingMode.HALF_UP);   // 落库一律两位小数（列是 NUMERIC(16,4)，值不许带第三位）

            Order order = orderMapper.selectById(orderId);
            if (order == null) {
                throw BusinessException.notFound("订单");
            }
            if ("cancelled".equals(order.getStatus())) {
                throw BusinessException.validationError(
                        "已取消的订单不能核销收款：" + order.getOrderNo());
            }
            requireSameCustomer(transaction, order);

            BigDecimal orderRefunded = orderRefunded(order.getId(), tenantId);
            BigDecimal orderAllocated = sumByOrder(order.getId());
            ReceiptAllocationPolicy.Decision decision = ReceiptAllocationPolicy.evaluate(
                    transaction.getAmount(), receiptAllocated,
                    order.getTotalAmount(), orderRefunded, orderAllocated,
                    amount);
            if (!decision.allowed()) {
                throw BusinessException.validationError(String.format(
                        "核销金额超出可核销上限：本次 ¥%s，最多还能冲 ¥%s（收款剩余 ¥%s / 该单剩余 ¥%s）。%s",
                        amount.toPlainString(), decision.allocatable().toPlainString(),
                        receiptLeft(transaction, receiptAllocated).toPlainString(),
                        orderOutstanding(order, orderRefunded, orderAllocated).toPlainString(),
                        first ? "请先核对收款金额与订单余额，或减少核销金额。" : ""));
            }

            ReceiptAllocation allocation = new ReceiptAllocation();
            allocation.setTenantId(tenantId);
            allocation.setTransactionId(transaction.getId());
            allocation.setOrderId(order.getId());
            allocation.setAmount(amount);
            allocation.setCreatedBy(operator);
            allocation.setDeleted(Boolean.FALSE);
            allocationMapper.insert(allocation);

            // 下一行要在「包含本行」的余量上再判 —— 否则两行合起来超过流水金额
            receiptAllocated = receiptAllocated.add(amount);
            first = false;
        }

        log.info("[receipt] 核销 | tenant={} transaction={} lines={} allocated={}",
                tenantId, transaction.getTransactionNo(), lines.size(), receiptAllocated);
        return view(transactionId);
    }

    /** 读面：该流水的已核销明细 + 未核销余额（预收 / 待勾对）。 */
    public ReceiptAllocationView view(String transactionId) {
        FinanceTransaction transaction = financeTransactionMapper.selectById(transactionId);
        if (transaction == null) {
            throw BusinessException.notFound("收款流水");
        }
        List<ReceiptAllocation> rows = allocationMapper.selectList(
                new LambdaQueryWrapper<ReceiptAllocation>()
                        .eq(ReceiptAllocation::getTransactionId, transactionId)
                        .orderByAsc(ReceiptAllocation::getCreatedAt));

        List<ReceiptAllocationView.Line> lines = new ArrayList<>();
        BigDecimal allocated = BigDecimal.ZERO;
        for (ReceiptAllocation row : rows) {
            allocated = allocated.add(row.getAmount());
            Order order = orderMapper.selectById(row.getOrderId());
            BigDecimal refunded = order == null ? BigDecimal.ZERO : orderRefunded(order.getId(), order.getTenantId());
            BigDecimal otherAllocated = sumByOrder(row.getOrderId());
            lines.add(ReceiptAllocationView.Line.builder()
                    .id(row.getId())
                    .orderId(row.getOrderId())
                    .orderNo(order == null ? null : order.getOrderNo())
                    .amount(row.getAmount().setScale(2, RoundingMode.HALF_UP))
                    .orderOutstanding(order == null
                            ? BigDecimal.ZERO.setScale(2)
                            : orderOutstanding(order, refunded, otherAllocated))
                    .build());
        }
        return ReceiptAllocationView.builder()
                .transactionId(transaction.getId())
                .transactionNo(transaction.getTransactionNo())
                .transactionAmount(nz(transaction.getAmount()).setScale(2, RoundingMode.HALF_UP))
                .allocated(allocated.setScale(2, RoundingMode.HALF_UP))
                .unallocated(nz(transaction.getAmount()).subtract(allocated).setScale(2, RoundingMode.HALF_UP))
                .lines(lines)
                .build();
    }

    /** 某订单的已核销合计（账龄/应收余额要减掉它）。 */
    public BigDecimal sumByOrder(String orderId) {
        List<ReceiptAllocation> rows = allocationMapper.selectList(
                new LambdaQueryWrapper<ReceiptAllocation>().eq(ReceiptAllocation::getOrderId, orderId));
        BigDecimal sum = BigDecimal.ZERO;
        for (ReceiptAllocation row : rows) {
            sum = sum.add(row.getAmount());
        }
        return sum;
    }

    // ==================== 私有工具 ====================

    /** 收入类流水准入：只有 `type=income ∧ status=success` 才能被核销（退款/失败流水不许）。 */
    private FinanceTransaction requireIncomeReceipt(String transactionId) {
        FinanceTransaction transaction = financeTransactionMapper.selectById(transactionId);
        if (transaction == null) {
            throw BusinessException.notFound("收款流水");
        }
        if (!"income".equals(transaction.getType())) {
            throw BusinessException.validationError(
                    "只有收入流水可以核销：" + transaction.getTransactionNo() + "（type=" + transaction.getType() + "）");
        }
        if (!"success".equals(transaction.getStatus())) {
            throw BusinessException.validationError(
                    "只有成功的收款流水可以核销：" + transaction.getTransactionNo());
        }
        return transaction;
    }

    /** 同客户约束：流水的订单与目标订单必须是同一个客户电话（冲到别人单上 = 对账灾难）。 */
    private void requireSameCustomer(FinanceTransaction transaction, Order order) {
        if (!StringUtils.hasText(transaction.getOrderId())) {
            return; // 流水未挂订单（散客收款）⇒ 由订单侧约束兜住，不做额外推断
        }
        Order source = orderMapper.selectById(transaction.getOrderId());
        if (source == null || !StringUtils.hasText(source.getCustomerPhone())) {
            return;
        }
        if (!source.getCustomerPhone().equals(order.getCustomerPhone())) {
            throw BusinessException.validationError(
                    "这笔收款属于客户「" + source.getCustomerName() + "」，不能核销到其他客户的订单");
        }
    }

    /** 该流水的已核销合计。 */
    private BigDecimal sumByTransaction(String transactionId) {
        List<ReceiptAllocation> rows = allocationMapper.selectList(
                new LambdaQueryWrapper<ReceiptAllocation>().eq(ReceiptAllocation::getTransactionId, transactionId));
        BigDecimal sum = BigDecimal.ZERO;
        for (ReceiptAllocation row : rows) {
            sum = sum.add(row.getAmount());
        }
        return sum;
    }

    /** 该单退款合计（与账龄/对账同口径：只算 status=success 的退款流水）。 */
    private BigDecimal orderRefunded(String orderId, Long tenantId) {
        List<FinanceTransaction> refunds = financeTransactionMapper.selectList(
                new LambdaQueryWrapper<FinanceTransaction>()
                        .eq(FinanceTransaction::getTenantId, tenantId)
                        .eq(FinanceTransaction::getType, "refund")
                        .eq(FinanceTransaction::getStatus, "success")
                        .eq(FinanceTransaction::getOrderId, orderId));
        BigDecimal sum = BigDecimal.ZERO;
        for (FinanceTransaction row : refunds) {
            sum = sum.add(nz(row.getAmount()));
        }
        return sum;
    }

    private static BigDecimal receiptLeft(FinanceTransaction transaction, BigDecimal allocated) {
        BigDecimal left = nz(transaction.getAmount()).subtract(allocated);
        return (left.signum() < 0 ? BigDecimal.ZERO : left).setScale(2, RoundingMode.HALF_UP);
    }

    private static BigDecimal orderOutstanding(Order order, BigDecimal refunded, BigDecimal allocated) {
        BigDecimal left = nz(order.getTotalAmount()).subtract(nz(refunded)).subtract(nz(allocated));
        return (left.signum() < 0 ? BigDecimal.ZERO : left).setScale(2, RoundingMode.HALF_UP);
    }

    private static BigDecimal nz(BigDecimal value) {
        return value == null ? BigDecimal.ZERO : value;
    }

    private static String trimToNull(String value) {
        return StringUtils.hasText(value) ? value.trim() : null;
    }
}
