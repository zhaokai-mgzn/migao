package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.migao.admin.dto.SupplierPaymentRequest;
import com.migao.admin.dto.SupplierPaymentView;
import com.migao.admin.entity.InboundOrder;
import com.migao.admin.entity.Supplier;
import com.migao.admin.entity.SupplierPayment;
import com.migao.admin.entity.SupplierPaymentAllocation;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.InboundOrderMapper;
import com.migao.admin.mapper.SupplierMapper;
import com.migao.admin.mapper.SupplierPaymentAllocationMapper;
import com.migao.admin.mapper.SupplierPaymentMapper;
import com.migao.admin.time.BusinessClock;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 供应商付款（issue #7369，P0-1 段 3-B）—— **按实际业务**：一笔付款可冲抵多张入库单（用户 2026-10-20 裁定）。
 *
 * <h3>为什么「差额」是合法状态而不是错误</h3>
 * <p>现实里常见的三种情形都要能记：
 * <ol>
 *   <li>一笔转账覆盖好几张入库单 ⇒ 冲抵合计 = 付款额；</li>
 *   <li>先打款、货后到（预付）⇒ 冲抵合计 &lt; 付款额，差额 = 未冲抵；</li>
 *   <li>分几次打款付一张单 ⇒ 同一张单被多笔付款冲抵（每笔各自 ≤ 该单余额）。</li>
 * </ol>
 *
 * <h3>四条硬约束（每条都有判据）</h3>
 * <ul>
 *   <li><b>Σ冲抵 ≤ 付款额</b>：否则「付出的钱」与「冲掉的账」对不上，差额方向反了；</li>
 *   <li><b>单张单累计冲抵 ≤ 该单金额</b>：否则同一张单被付了两次 —— 账实不符且**不可逆**；</li>
 *   <li><b>只能冲本供应商的 posted 单</b>：跨供应商 = 把 A 家的钱记到 B 家头上；</li>
 *   <li><b>作废留痕</b>：{@code status = voided} + 谁/何时/为什么；作废后金额与冲抵同时失效
 *       （聚合按 {@code status = 'posted'} 过滤，不物理删）。</li>
 * </ul>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class SupplierPaymentService {

    /** 付款方式域（与迁移里的 CHECK 逐值同域）。 */
    public static final java.util.Set<String> METHODS = SupplierPayment.METHODS;

    private static final DateTimeFormatter NO_DATE = DateTimeFormatter.ofPattern("yyyyMMdd");

    private final SupplierPaymentMapper paymentMapper;
    private final SupplierPaymentAllocationMapper allocationMapper;
    private final SupplierMapper supplierMapper;
    private final InboundOrderMapper inboundOrderMapper;

    /** 业务「今天」单点（issue #3802）：`LocalDate.now()` 取的是 JVM 默认时区（容器 = UTC）⇒ 与业务日差一天。 */
    private final BusinessClock businessClock;

    /**
     * 登记一笔付款（可选同时冲抵若干入库单）。
     *
     * @param req      请求（供应商 / 金额 / 日期 / 方式 / 冲抵）
     * @param tenantId 当前租户
     * @param operator 操作人
     */
    @Transactional(rollbackFor = Exception.class)
    public SupplierPaymentView create(SupplierPaymentRequest req, Long tenantId, String operator) {
        String supplierId = trimToNull(req.supplierId());
        if (supplierId == null) {
            throw BusinessException.validationError("付款必须指定供应商");
        }
        // selectById 走租户插件 ⇒ 他租户的档案查不到（与「跨租户 = 不存在」同源，不泄露存在性）
        Supplier supplier = supplierMapper.selectById(supplierId);
        if (supplier == null) {
            throw BusinessException.notFound("供应商");
        }

        BigDecimal amount = req.amount();
        if (amount == null || amount.signum() <= 0) {
            throw BusinessException.validationError("付款金额必须大于 0");
        }
        // 金额准入（issue #6221）：钱只有两位小数的物理意义；超精度输入直接拒，不静默四舍五入
        amount = MoneyScale.requireTwoDecimalsOrNull(amount, "付款金额");
        String method = trimToNull(req.method());
        if (method == null || !METHODS.contains(method)) {
            throw BusinessException.validationError("付款方式只接受 " + String.join(" / ", METHODS.stream().sorted().toList()));
        }

        LocalDate paidAt = req.paidAt() != null ? req.paidAt() : businessClock.today();
        List<SupplierPaymentRequest.Allocation> allocations =
                req.allocations() == null ? List.of() : req.allocations();

        // 先把冲抵算清楚再落库：任何一条不合法都不许留下半张付款单
        List<String> orderIds = new ArrayList<>();
        Map<String, BigDecimal> allocationAmounts = new HashMap<>();
        BigDecimal allocatedTotal = BigDecimal.ZERO;
        for (SupplierPaymentRequest.Allocation a : allocations) {
            String orderId = trimToNull(a.inboundOrderId());
            if (orderId == null) {
                throw BusinessException.validationError("冲抵缺少入库单 id");
            }
            BigDecimal part = a.amount();
            if (part == null || part.signum() <= 0) {
                throw BusinessException.validationError("冲抵金额必须大于 0（入库单 " + orderId + "）");
            }
            part = MoneyScale.requireTwoDecimalsOrNull(part, "冲抵金额");
            if (orderIds.contains(orderId)) {
                throw BusinessException.validationError("同一张入库单在一笔付款里只能冲一次：" + orderId);
            }
            orderIds.add(orderId);

            InboundOrder order = inboundOrderMapper.selectById(orderId);
            if (order == null) {
                throw BusinessException.notFound("入库单");
            }
            if (!InboundOrder.STATUS_POSTED.equals(order.getStatus())) {
                throw BusinessException.validationError(
                        "只能冲抵**已过账**的入库单：" + order.getInboundNo() + "（当前 " + order.getStatus() + "）");
            }
            if (!supplierId.equals(order.getSupplierId())) {
                throw BusinessException.validationError(
                        "入库单 " + order.getInboundNo() + " 不属于该供应商，不能冲抵");
            }
            BigDecimal alreadyAllocated = allocatedSumOf(orderId, tenantId);
            BigDecimal remaining = order.getTotalAmount() == null
                    ? BigDecimal.ZERO : order.getTotalAmount().subtract(alreadyAllocated);
            if (part.compareTo(remaining) > 0) {
                throw BusinessException.validationError(
                        "冲抵超出该入库单未付金额：" + order.getInboundNo()
                        + "（可冲 " + remaining.stripTrailingZeros().toPlainString()
                        + "，本次 " + part.stripTrailingZeros().toPlainString() + "）");
            }
            allocatedTotal = allocatedTotal.add(part);
            allocationAmounts.put(orderId, part);
        }
        if (allocatedTotal.compareTo(amount) > 0) {
            throw BusinessException.validationError(
                    "冲抵合计（" + allocatedTotal.stripTrailingZeros().toPlainString()
                    + "）不能超过付款金额（" + amount.stripTrailingZeros().toPlainString() + "）");
        }

        SupplierPayment payment = SupplierPayment.builder()
                .tenantId(tenantId)
                .supplierId(supplierId)
                .paymentNo(nextPaymentNo(tenantId, paidAt))
                .paidAt(paidAt)
                .amount(amount)
                .method(method)
                .referenceNo(trimToNull(req.referenceNo()))
                .remark(req.remark())
                .status(SupplierPayment.STATUS_POSTED)
                .createdBy(operator)
                .build();
        paymentMapper.insert(payment);

        int seq = 0;
        for (SupplierPaymentRequest.Allocation a : allocations) {
            allocationMapper.insert(SupplierPaymentAllocation.builder()
                    .tenantId(tenantId)
                    .paymentId(payment.getId())
                    .inboundOrderId(a.inboundOrderId())
                    .amount(allocationAmounts.get(a.inboundOrderId()))
                    .build());
            seq++;
        }
        log.info("登记供应商付款: tenant={}, paymentNo={}, supplier={}, amount={}, 冲抵={} 笔",
                tenantId, payment.getPaymentNo(), supplierId, amount, seq);
        return detail(payment.getId(), tenantId);
    }

    /**
     * 作废一笔付款（**留痕**，不物理删）。
     *
     * <p>作废后该笔金额与它的冲抵同时失效（聚合按 {@code status = 'posted'} 过滤）——
     * 于是「这张单又变成未付」。这正是财务要的语义：错记一笔，作废重记，账与凭证都可追溯。</p>
     */
    @Transactional(rollbackFor = Exception.class)
    public SupplierPaymentView voidPayment(String id, String reason, Long tenantId, String operator) {
        SupplierPayment payment = paymentMapper.selectById(id);
        if (payment == null) {
            throw BusinessException.notFound("付款单");
        }
        if (SupplierPayment.STATUS_VOIDED.equals(payment.getStatus())) {
            throw BusinessException.validationError("该付款单已作废：" + payment.getPaymentNo());
        }
        String why = trimToNull(reason);
        if (why == null) {
            throw BusinessException.validationError("作废必须写原因（付款凭证要能追溯）");
        }
        payment.setStatus(SupplierPayment.STATUS_VOIDED);
        payment.setVoidedAt(OffsetDateTime.now());
        payment.setVoidedBy(operator);
        payment.setVoidedReason(why);
        paymentMapper.updateById(payment);
        return detail(id, tenantId);
    }

    /** 某供应商的付款流水（新的在前）；某租户全部付款可传 null。 */
    public List<SupplierPaymentView> list(Long tenantId, String supplierId) {
        LambdaQueryWrapper<SupplierPayment> wrapper = new LambdaQueryWrapper<SupplierPayment>()
                .eq(SupplierPayment::getTenantId, tenantId)
                .eq(StringUtils.hasText(supplierId), SupplierPayment::getSupplierId, supplierId)
                .orderByDesc(SupplierPayment::getPaidAt)
                .orderByDesc(SupplierPayment::getCreatedAt)
                .last("LIMIT 200");
        List<SupplierPaymentView> out = new ArrayList<>();
        for (SupplierPayment payment : paymentMapper.selectList(wrapper)) {
            out.add(detail(payment.getId(), tenantId));
        }
        return out;
    }

    /** 单张付款单读面（含冲抵明细与「未冲抵」= 预付/待勾对）。 */
    public SupplierPaymentView detail(String id, Long tenantId) {
        SupplierPayment payment = paymentMapper.selectById(id);
        if (payment == null) {
            throw BusinessException.notFound("付款单");
        }
        List<SupplierPaymentAllocation> allocations = allocationMapper.selectList(
                new LambdaQueryWrapper<SupplierPaymentAllocation>()
                        .eq(SupplierPaymentAllocation::getTenantId, tenantId)
                        .eq(SupplierPaymentAllocation::getPaymentId, id)
                        .orderByAsc(SupplierPaymentAllocation::getCreatedAt));

        List<SupplierPaymentView.AllocationView> views = new ArrayList<>();
        BigDecimal allocated = BigDecimal.ZERO;
        for (SupplierPaymentAllocation a : allocations) {
            InboundOrder order = inboundOrderMapper.selectById(a.getInboundOrderId());
            views.add(new SupplierPaymentView.AllocationView(
                    a.getInboundOrderId(),
                    order == null ? null : order.getInboundNo(),
                    a.getAmount()));
            allocated = allocated.add(a.getAmount());
        }
        BigDecimal amount = payment.getAmount() == null ? BigDecimal.ZERO : payment.getAmount();
        return new SupplierPaymentView(
                payment.getId(),
                payment.getPaymentNo(),
                payment.getSupplierId(),
                payment.getPaidAt(),
                amount,
                allocated,
                amount.subtract(allocated),
                payment.getMethod(),
                payment.getReferenceNo(),
                payment.getRemark(),
                payment.getStatus(),
                payment.getVoidedAt(),
                payment.getVoidedReason(),
                views);
    }

    /** 某张入库单已被**有效**付款冲抵的合计（作废的付款不计）。 */
    private BigDecimal allocatedSumOf(String orderId, Long tenantId) {
        List<SupplierPaymentAllocation> rows = allocationMapper.selectList(
                new LambdaQueryWrapper<SupplierPaymentAllocation>()
                        .eq(SupplierPaymentAllocation::getTenantId, tenantId)
                        .eq(SupplierPaymentAllocation::getInboundOrderId, orderId));
        if (rows.isEmpty()) {
            return BigDecimal.ZERO;
        }
        Map<String, SupplierPayment> payments = new HashMap<>();
        BigDecimal sum = BigDecimal.ZERO;
        for (SupplierPaymentAllocation row : rows) {
            SupplierPayment payment = payments.computeIfAbsent(row.getPaymentId(),
                    pid -> paymentMapper.selectById(pid));
            if (payment != null && SupplierPayment.STATUS_POSTED.equals(payment.getStatus())) {
                sum = sum.add(row.getAmount());
            }
        }
        return sum;
    }

    /**
     * 付款单号 {@code FK-yyyyMMdd-NNNN}（租户内唯一）。
     *
     * <p>与入库单同法：不看总数、只看当天序号 —— 历史单被作废后号也不回收
     * （回收号会让「上个月那张 FK-20261020-0007」指错单）。并发同号的兜底是 DB 唯一索引。</p>
     */
    private String nextPaymentNo(Long tenantId, LocalDate paidAt) {
        String prefix = "FK-" + paidAt.format(NO_DATE) + "-";
        long count = paymentMapper.selectCount(new LambdaQueryWrapper<SupplierPayment>()
                .eq(SupplierPayment::getTenantId, tenantId)
                .likeRight(SupplierPayment::getPaymentNo, prefix));
        return prefix + String.format("%04d", count + 1);
    }

    private static String trimToNull(String raw) {
        if (raw == null) {
            return null;
        }
        String trimmed = raw.trim();
        return trimmed.isEmpty() ? null : trimmed;
    }
}
