// case_ids: SP-004
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
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
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 供应商付款（issue #7369 段 3-B）—— **按实际业务**：一笔付款可冲抵多张入库单。
 *
 * <p>本判据守四条硬约束（用户 2026-10-20 裁定「按实际的来」）：
 * ① Σ冲抵 ≤ 付款额（差额 = 预付/待勾对，合法）；② 单张单累计冲抵 ≤ 该单金额（**防同一张单被付两次**）；
 * ③ 只能冲本供应商的 posted 单（跨供应商 = 把 A 家的钱记到 B 家头上）；④ 作废留痕且必须写原因。</p>
 *
 * <p>红证方向：把「单张单累计冲抵」那条判据删掉 ⇒ {@link #allocationCannotExceedOrderRemaining} 当场红。</p>
 */
@ExtendWith(MockitoExtension.class)
class SupplierPaymentServiceTest {

    private static final Long TENANT = 2001L;
    private static final String SUPPLIER = "sup-1";

    @Mock
    private SupplierPaymentMapper paymentMapper;
    @Mock
    private SupplierPaymentAllocationMapper allocationMapper;
    @Mock
    private SupplierMapper supplierMapper;
    @Mock
    private InboundOrderMapper inboundOrderMapper;
    @Mock
    private BusinessClock businessClock;

    @InjectMocks
    private SupplierPaymentService service;

    @BeforeEach
    void setUp() {
        // 业务「今天」单点（issue #3802）：未传 paidAt 时由它给出 —— 测试里固定成 2026-10-20
        lenient().when(businessClock.today()).thenReturn(LocalDate.of(2026, 10, 20));
        // MyBatis-Plus 的 LambdaQueryWrapper 需要实体元数据（不开 Spring 容器，直接喂一次）
        TableInfoHelper.initTableInfo(new MapperBuilderAssistant(new MybatisConfiguration(), ""), SupplierPayment.class);
        TableInfoHelper.initTableInfo(new MapperBuilderAssistant(new MybatisConfiguration(), ""), SupplierPaymentAllocation.class);
    }

    private void givenSupplier() {
        lenient().when(supplierMapper.selectById(SUPPLIER))
                .thenReturn(Supplier.builder().id(SUPPLIER).tenantId(TENANT).name("杭州染整一厂").build());
    }

    private InboundOrder postedOrder(String id, String no, String supplierId, String amount) {
        return InboundOrder.builder()
                .id(id).inboundNo(no).supplierId(supplierId)
                .status(InboundOrder.STATUS_POSTED)
                .totalAmount(new BigDecimal(amount))
                .build();
    }

    /** 让 insert 把生成的 id 写回实体（真实 Mapper 由 MyBatis 赋值），并让 detail() 能读回来。 */
    private void givenInsertAssignsId() {
        // 落库的冲抵行要能被 detail() 读回来（真实 Mapper 是同一个事务里的两条 INSERT → SELECT）
        java.util.List<SupplierPaymentAllocation> persisted = new java.util.ArrayList<>();
        when(paymentMapper.insert(any(SupplierPayment.class))).thenAnswer(inv -> {
            SupplierPayment p = inv.getArgument(0);
            p.setId("pay-1");
            lenient().when(paymentMapper.selectById("pay-1")).thenReturn(p);
            return 1;
        });
        lenient().when(allocationMapper.insert(any(SupplierPaymentAllocation.class))).thenAnswer(inv -> {
            persisted.add(inv.getArgument(0));
            return 1;
        });
        lenient().when(allocationMapper.selectList(any())).thenAnswer(inv -> new java.util.ArrayList<>(persisted));
        lenient().when(paymentMapper.selectCount(any())).thenReturn(0L);
    }

    @Test
    @DisplayName("一笔付款冲两张单：单号 FK-yyyyMMdd-NNNN、两行冲抵、未冲抵 = 差额（预付，合法）")
    void createAllocatesAcrossTwoOrders() {
        givenSupplier();
        givenInsertAssignsId();
        when(inboundOrderMapper.selectById("in-1")).thenReturn(postedOrder("in-1", "RK-1", SUPPLIER, "1000"));
        when(inboundOrderMapper.selectById("in-2")).thenReturn(postedOrder("in-2", "RK-2", SUPPLIER, "800"));

        SupplierPaymentView view = service.create(new SupplierPaymentRequest(
                SUPPLIER, LocalDate.of(2026, 10, 20), new BigDecimal("1500"), "transfer", "回单-001", null,
                List.of(new SupplierPaymentRequest.Allocation("in-1", new BigDecimal("1000")),
                        new SupplierPaymentRequest.Allocation("in-2", new BigDecimal("500")))), TENANT, "acct");

        assertThat(view.paymentNo()).startsWith("FK-20261020-");
        assertThat(view.amount()).isEqualByComparingTo("1500");
        assertThat(view.allocatedAmount()).isEqualByComparingTo("1500");
        assertThat(view.unallocatedAmount()).isEqualByComparingTo("0");
        assertThat(view.status()).isEqualTo(SupplierPayment.STATUS_POSTED);
        verify(allocationMapper, org.mockito.Mockito.times(2)).insert(any(SupplierPaymentAllocation.class));
    }

    @Test
    @DisplayName("允许「先打款后勾对」：不冲任何单 ⇒ 全额记为未冲抵（预付），不是错误")
    void paymentWithoutAllocationIsPrepayment() {
        givenSupplier();
        givenInsertAssignsId();

        SupplierPaymentView view = service.create(new SupplierPaymentRequest(
                SUPPLIER, null, new BigDecimal("3000"), "cash", null, "预付", List.of()), TENANT, "acct");

        assertThat(view.allocatedAmount()).isEqualByComparingTo("0");
        assertThat(view.unallocatedAmount()).isEqualByComparingTo("3000");
        verify(allocationMapper, never()).insert(any(SupplierPaymentAllocation.class));
    }

    @Test
    @DisplayName("付款额非法 / 付款方式不在域内 / 供应商不存在（含跨租户）⇒ 422/404，不落库")
    void invalidPaymentIsRejectedBeforeAnyWrite() {
        givenSupplier();
        assertThatThrownBy(() -> service.create(new SupplierPaymentRequest(
                SUPPLIER, null, BigDecimal.ZERO, "cash", null, null, List.of()), TENANT, "acct"))
                .isInstanceOf(BusinessException.class).hasMessageContaining("必须大于 0");

        assertThatThrownBy(() -> service.create(new SupplierPaymentRequest(
                SUPPLIER, null, new BigDecimal("10"), "bitcoin", null, null, List.of()), TENANT, "acct"))
                .isInstanceOf(BusinessException.class).hasMessageContaining("付款方式");

        assertThatThrownBy(() -> service.create(new SupplierPaymentRequest(
                "sup-other", null, new BigDecimal("10"), "cash", null, null, List.of()), TENANT, "acct"))
                .isInstanceOf(BusinessException.class).hasMessageContaining("供应商");

        verify(paymentMapper, never()).insert(any(SupplierPayment.class));
    }

    @Test
    @DisplayName("冲抵合计不得超过付款金额（否则「付出的钱」与「冲掉的账」方向反了）")
    void allocationCannotExceedPaymentAmount() {
        givenSupplier();
        when(inboundOrderMapper.selectById("in-1")).thenReturn(postedOrder("in-1", "RK-1", SUPPLIER, "5000"));
        when(allocationMapper.selectList(any())).thenReturn(List.of());

        assertThatThrownBy(() -> service.create(new SupplierPaymentRequest(
                SUPPLIER, null, new BigDecimal("100"), "cash", null, null,
                List.of(new SupplierPaymentRequest.Allocation("in-1", new BigDecimal("300")))), TENANT, "acct"))
                .isInstanceOf(BusinessException.class).hasMessageContaining("不能超过付款金额");
        verify(paymentMapper, never()).insert(any(SupplierPayment.class));
    }

    @Test
    @DisplayName("单张单累计冲抵不得超过该单金额（**防同一张单被付两次**，不可逆）")
    void allocationCannotExceedOrderRemaining() {
        givenSupplier();
        when(inboundOrderMapper.selectById("in-1")).thenReturn(postedOrder("in-1", "RK-1", SUPPLIER, "1000"));
        // 已有一笔 900 冲在这张单上（其它有效付款）
        SupplierPaymentAllocation previous = SupplierPaymentAllocation.builder()
                .id("al-0").tenantId(TENANT).paymentId("pay-old").inboundOrderId("in-1")
                .amount(new BigDecimal("900")).build();
        when(allocationMapper.selectList(any())).thenReturn(List.of(previous));
        when(paymentMapper.selectById("pay-old")).thenReturn(SupplierPayment.builder()
                .id("pay-old").tenantId(TENANT).supplierId(SUPPLIER).status(SupplierPayment.STATUS_POSTED).build());

        assertThatThrownBy(() -> service.create(new SupplierPaymentRequest(
                SUPPLIER, null, new BigDecimal("500"), "cash", null, null,
                List.of(new SupplierPaymentRequest.Allocation("in-1", new BigDecimal("200")))), TENANT, "acct"))
                .isInstanceOf(BusinessException.class).hasMessageContaining("超出该入库单未付金额");
        verify(paymentMapper, never()).insert(any(SupplierPayment.class));
    }

    @Test
    @DisplayName("作废的付款不再占用该单的已付额度（作废 = 金额与冲抵同时失效）")
    void voidedPaymentNoLongerOccupiesOrder() {
        givenSupplier();
        givenInsertAssignsId();
        when(inboundOrderMapper.selectById("in-1")).thenReturn(postedOrder("in-1", "RK-1", SUPPLIER, "1000"));
        SupplierPaymentAllocation voidedAllocation = SupplierPaymentAllocation.builder()
                .id("al-0").tenantId(TENANT).paymentId("pay-void").inboundOrderId("in-1")
                .amount(new BigDecimal("1000")).build();
        when(allocationMapper.selectList(any())).thenReturn(List.of(voidedAllocation));
        when(paymentMapper.selectById("pay-void")).thenReturn(SupplierPayment.builder()
                .id("pay-void").tenantId(TENANT).supplierId(SUPPLIER).status(SupplierPayment.STATUS_VOIDED).build());

        // 这张单的 1000 全被作废付款冲过 ⇒ 剩余额度回到 1000，本次可再冲
        SupplierPaymentView view = service.create(new SupplierPaymentRequest(
                SUPPLIER, null, new BigDecimal("1000"), "cash", null, null,
                List.of(new SupplierPaymentRequest.Allocation("in-1", new BigDecimal("1000")))), TENANT, "acct");
        assertThat(view.status()).isEqualTo(SupplierPayment.STATUS_POSTED);
    }

    @Test
    @DisplayName("只能冲本供应商的**已过账**单（跨供应商 / 草稿单都拒）")
    void onlyOwnPostedOrdersCanBeAllocated() {
        givenSupplier();
        when(inboundOrderMapper.selectById("in-draft")).thenReturn(InboundOrder.builder()
                .id("in-draft").inboundNo("RK-D").supplierId(SUPPLIER)
                .status(InboundOrder.STATUS_DRAFT).totalAmount(new BigDecimal("100")).build());
        assertThatThrownBy(() -> service.create(new SupplierPaymentRequest(
                SUPPLIER, null, new BigDecimal("100"), "cash", null, null,
                List.of(new SupplierPaymentRequest.Allocation("in-draft", new BigDecimal("100")))), TENANT, "acct"))
                .isInstanceOf(BusinessException.class).hasMessageContaining("已过账");
        verify(paymentMapper, never()).insert(any(SupplierPayment.class));

        when(inboundOrderMapper.selectById("in-other")).thenReturn(postedOrder("in-other", "RK-O", "sup-other", "100"));
        assertThatThrownBy(() -> service.create(new SupplierPaymentRequest(
                SUPPLIER, null, new BigDecimal("100"), "cash", null, null,
                List.of(new SupplierPaymentRequest.Allocation("in-other", new BigDecimal("100")))), TENANT, "acct"))
                .isInstanceOf(BusinessException.class).hasMessageContaining("不属于该供应商");
    }

    @Test
    @DisplayName("作废：必须写原因、只能作废一次；作废后状态与痕迹留在单上（不物理删）")
    void voidRequiresReasonAndIsIdempotentGuarded() {
        SupplierPayment posted = SupplierPayment.builder()
                .id("pay-1").tenantId(TENANT).supplierId(SUPPLIER).paymentNo("FK-20261020-0001")
                .paidAt(LocalDate.of(2026, 10, 20)).amount(new BigDecimal("100"))
                .status(SupplierPayment.STATUS_POSTED).build();
        when(paymentMapper.selectById("pay-1")).thenReturn(posted);
        lenient().when(allocationMapper.selectList(any())).thenReturn(List.of());

        assertThatThrownBy(() -> service.voidPayment("pay-1", "  ", TENANT, "acct"))
                .isInstanceOf(BusinessException.class).hasMessageContaining("必须写原因");

        SupplierPaymentView view = service.voidPayment("pay-1", "转错账户", TENANT, "acct");
        assertThat(view.status()).isEqualTo(SupplierPayment.STATUS_VOIDED);
        assertThat(view.voidedReason()).isEqualTo("转错账户");

        assertThatThrownBy(() -> service.voidPayment("pay-1", "再作一次", TENANT, "acct"))
                .isInstanceOf(BusinessException.class).hasMessageContaining("已作废");
    }
}
