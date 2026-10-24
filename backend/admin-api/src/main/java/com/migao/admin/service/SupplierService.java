package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.migao.admin.entity.Supplier;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.dto.SupplierPayable;
import com.migao.admin.dto.SupplierPayableSummary;
import com.migao.admin.dto.UnassignedInboundSupplier;
import com.migao.admin.mapper.InboundOrderMapper;
import com.migao.admin.mapper.SupplierMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * 供应商主数据服务（issue #7369，P0-1 段 1）。
 *
 * <h3>本段只做「档案」，不做任何单据联动</h3>
 * 入库单/采购单侧的 {@code supplier_id} 引用是**段 2**。这里刻意不含「停用后禁止收货」这类跨单据判定 ——
 * 那些判定的正确位置在单据写面（段 2 落地时加），提前写在这里只会变成第二套判定点。
 *
 * <h3>校验口径（逐条会红）</h3>
 * <ul>
 *   <li>名称去空白后不得为空（同一家被录成三种写法正是本表要治的病灶之一）；</li>
 *   <li>账期天数 0~365（NULL = 未设置；0 = 现结）；</li>
 *   <li>状态只接受 {@code active} / {@code inactive}（与 V170 的 CHECK 同域，服务层先拦以便给出可行动提示）。</li>
 * </ul>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class SupplierService {

    /** 与 V170 的 {@code ck_suppliers_status} 同域。 */
    public static final String STATUS_ACTIVE = "active";
    public static final String STATUS_INACTIVE = "inactive";

    private final SupplierMapper supplierMapper;

    /** 待指派清单的聚合查询落在单据侧（issue #7369 段 2）—— 语义属入库单，不在这里写第二份 SQL。 */
    private final InboundOrderMapper inboundOrderMapper;

    /** 本租户供应商列表：可按名称/联系人/电话模糊搜；在用在前、名称升序（停用的沉底，不平铺打扰）。 */
    public List<Supplier> list(Long tenantId, String keyword) {
        LambdaQueryWrapper<Supplier> wrapper = new LambdaQueryWrapper<Supplier>()
                .eq(Supplier::getTenantId, tenantId);
        if (StringUtils.hasText(keyword)) {
            String kw = keyword.trim();
            wrapper.and(w -> w.like(Supplier::getName, kw)
                    .or().like(Supplier::getContactName, kw)
                    .or().like(Supplier::getContactPhone, kw));
        }
        wrapper.orderByAsc(Supplier::getStatus).orderByAsc(Supplier::getName);
        return supplierMapper.selectList(wrapper);
    }

    public Supplier create(Long tenantId, Supplier input) {
        String name = normalizeName(input.getName());
        validateTerms(input.getPaymentTermsDays());
        String status = normalizeStatus(input.getStatus());
        Supplier supplier = Supplier.builder()
                .tenantId(tenantId)
                .name(name)
                .contactName(trimToNull(input.getContactName()))
                .contactPhone(trimToNull(input.getContactPhone()))
                .paymentTermsDays(input.getPaymentTermsDays())
                .status(status)
                .remark(trimToNull(input.getRemark()))
                .deleted(Boolean.FALSE)
                .build();
        supplierMapper.insert(supplier);
        log.info("[supplier] 建档 | tenant={} id={} name={}", tenantId, supplier.getId(), name);
        return supplier;
    }

    /**
     * 更新档案。**停用靠这里改 status**（不单独开端点：少一个写面就少一处权限/归属判定）。
     */
    public Supplier update(String id, Long tenantId, Supplier input) {
        Supplier existing = supplierMapper.selectById(id);
        if (existing == null || !tenantId.equals(existing.getTenantId())) {
            throw BusinessException.notFound("供应商");
        }
        String name = normalizeName(input.getName());
        validateTerms(input.getPaymentTermsDays());
        existing.setName(name);
        existing.setContactName(trimToNull(input.getContactName()));
        existing.setContactPhone(trimToNull(input.getContactPhone()));
        existing.setPaymentTermsDays(input.getPaymentTermsDays());
        existing.setStatus(normalizeStatus(input.getStatus()));
        existing.setRemark(trimToNull(input.getRemark()));
        supplierMapper.updateById(existing);
        log.info("[supplier] 更新 | tenant={} id={} status={}", tenantId, id, existing.getStatus());
        return existing;
    }

    /**
     * 「待指派」清单（issue #7369 段 2，A 口径的人工出口）：有供应商**文本**但没有档案**引用**的入库单。
     *
     * <p>为什么必须有这个出口：A 口径明令「匹配不上不猜」—— 不猜就必须**看得见**，否则那批单据
     * 永远停在「按供应商统计不到」的状态，而没有任何东西会提醒。按文本名分组、单数多的在前。</p>
     */
    public List<UnassignedInboundSupplier> unassignedInboundSuppliers(Long tenantId) {
        List<Map<String, Object>> rows = inboundOrderMapper.selectUnassignedSupplierNames(tenantId);
        List<UnassignedInboundSupplier> out = new ArrayList<>();
        for (Map<String, Object> row : rows) {
            Object date = row.get("last_inbound_date");
            out.add(new UnassignedInboundSupplier(
                    String.valueOf(row.get("supplier_name")),
                    ((Number) row.get("order_count")).intValue(),
                    date == null ? null : java.time.LocalDate.parse(String.valueOf(date))));
        }
        return out;
    }

    /**
     * 供应商应付对账（issue #7369 段 3-A，用户 2026-10-20 裁定「A（轻）」）。
     *
     * <h3>A 段只做对账视图，不做付款流水</h3>
     * <p>段 3-B 起 {@code paidAmount} 取**有效付款之和**（作废的付款不计），
     * {@code paymentsRecorded = true}。{@code outstanding = 收货额 − 已付}：**负数 = 预付**
     * （先打款后到货），这是合法状态，页面照样显示，不许截零。</p>
     *
     * <p>金额口径的唯一真值在 SQL（`InboundOrderMapper.selectSupplierPayables`：只算 posted），
     * 这里只做映射与总计，**不重算**。</p>
     */
    public SupplierPayableSummary payableSummary(Long tenantId) {
        List<Map<String, Object>> rows = inboundOrderMapper.selectSupplierPayables(tenantId);
        List<SupplierPayable> payables = new ArrayList<>();
        java.math.BigDecimal totalReceived = java.math.BigDecimal.ZERO;
        java.math.BigDecimal totalPaid = java.math.BigDecimal.ZERO;
        for (Map<String, Object> row : rows) {
            java.math.BigDecimal received = toAmount(row.get("received_amount"));
            java.math.BigDecimal paid = toAmount(row.get("paid_amount"));
            payables.add(new SupplierPayable(
                    String.valueOf(row.get("supplier_id")),
                    String.valueOf(row.get("supplier_name")),
                    String.valueOf(row.get("supplier_status")),
                    received,
                    ((Number) row.get("order_count")).intValue(),
                    toDate(row.get("first_inbound_date")),
                    toDate(row.get("last_inbound_date")),
                    paid,
                    true,
                    received.subtract(paid)));
            totalReceived = totalReceived.add(received);
            totalPaid = totalPaid.add(paid);
        }
        return new SupplierPayableSummary(payables, totalReceived, totalReceived.subtract(totalPaid), true);
    }

    private static java.math.BigDecimal toAmount(Object raw) {
        if (raw == null) {
            return java.math.BigDecimal.ZERO;
        }
        return raw instanceof java.math.BigDecimal bd ? bd : new java.math.BigDecimal(String.valueOf(raw));
    }

    private static java.time.LocalDate toDate(Object raw) {
        return raw == null ? null : java.time.LocalDate.parse(String.valueOf(raw));
    }

    private String normalizeName(String raw) {
        String name = raw == null ? "" : raw.trim();
        if (name.isEmpty()) {
            throw BusinessException.validationError("供应商名称不能为空");
        }
        if (name.length() > 128) {
            throw BusinessException.validationError("供应商名称过长（上限 128 字）：" + name.length());
        }
        return name;
    }

    private void validateTerms(Integer days) {
        if (days != null && (days < 0 || days > 365)) {
            throw BusinessException.validationError("账期天数须在 0~365 之间（0 = 现结）：" + days);
        }
    }

    private String normalizeStatus(String raw) {
        if (!StringUtils.hasText(raw)) {
            return STATUS_ACTIVE;
        }
        String status = raw.trim().toLowerCase();
        if (!STATUS_ACTIVE.equals(status) && !STATUS_INACTIVE.equals(status)) {
            throw BusinessException.validationError("供应商状态只接受 active / inactive：" + raw);
        }
        return status;
    }

    private String trimToNull(String raw) {
        if (raw == null) {
            return null;
        }
        String v = raw.trim();
        return v.isEmpty() ? null : v;
    }
}
