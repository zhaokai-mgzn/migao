// case_ids: SP-001

package com.migao.admin.service;

import com.migao.admin.entity.Supplier;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.dto.UnassignedInboundSupplier;
import com.migao.admin.mapper.InboundOrderMapper;
import com.migao.admin.mapper.SupplierMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 供应商主数据的服务层判据（issue #7369，P0-1 段 1）。
 *
 * <p>守的是三件**会算错/会静默**的事：
 * <ol>
 *   <li><b>名称</b>：去空白后不得为空 —— 空名档案件会变成「谁都对不上」的幽灵供应商；</li>
 *   <li><b>账期</b>：0~365（NULL = 未设置、0 = 现结）—— 越界必须拒，不许静默存；</li>
 *   <li><b>状态</b>：只接受 active / inactive（与 V170 的 CHECK 同域）—— 其他值一律拒（防「停用」被写成
 *       {@code disabled} 后既不在用也不在停用，筛都筛不出来）。</li>
 * </ol>
 * 另守一条**归属**：跨租户 id 更新必须 404（不泄露存在性），且**不得**落库。
 */
@ExtendWith(MockitoExtension.class)
class SupplierServiceTest {

    private static final Long TENANT = 1001L;

    @Mock
    private SupplierMapper supplierMapper;

    @Mock
    private InboundOrderMapper inboundOrderMapper;

    @InjectMocks
    private SupplierService supplierService;

    @Test
    @DisplayName("建档：名称去空白、状态缺省 active、字段原样落库")
    void createNormalizesNameAndDefaultsStatus() {
        Supplier created = supplierService.create(TENANT, Supplier.builder()
                .name("  杭州染整一厂  ")
                .contactName(" 张厂长 ")
                .contactPhone("13900000000")
                .paymentTermsDays(30)
                .build());

        ArgumentCaptor<Supplier> captor = ArgumentCaptor.forClass(Supplier.class);
        verify(supplierMapper).insert(captor.capture());
        Supplier saved = captor.getValue();
        assertThat(saved.getName()).isEqualTo("杭州染整一厂");
        assertThat(saved.getContactName()).isEqualTo("张厂长");
        assertThat(saved.getStatus()).isEqualTo("active");
        assertThat(saved.getTenantId()).isEqualTo(TENANT);
        assertThat(saved.getDeleted()).isFalse();
        assertThat(created.getName()).isEqualTo("杭州染整一厂");
    }

    @Test
    @DisplayName("建档：名称为空/纯空白 ⇒ 拒，且不落库")
    void createRejectsBlankName() {
        assertThatThrownBy(() -> supplierService.create(TENANT, Supplier.builder().name("   ").build()))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("供应商名称不能为空");
        verify(supplierMapper, never()).insert(any(Supplier.class));
    }

    @Test
    @DisplayName("账期越界（-1 / 366）⇒ 拒；0 与 365 是合法边界")
    void paymentTermsRangeIsEnforced() {
        assertThatThrownBy(() -> supplierService.create(TENANT,
                Supplier.builder().name("A").paymentTermsDays(-1).build()))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("账期天数");
        assertThatThrownBy(() -> supplierService.create(TENANT,
                Supplier.builder().name("A").paymentTermsDays(366).build()))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("账期天数");

        supplierService.create(TENANT, Supplier.builder().name("现结厂").paymentTermsDays(0).build());
        supplierService.create(TENANT, Supplier.builder().name("年结厂").paymentTermsDays(365).build());
        verify(supplierMapper, org.mockito.Mockito.times(2)).insert(any(Supplier.class));
    }

    @Test
    @DisplayName("状态只接受 active / inactive ⇒ 别的值拒（防「停用」写成 disabled 后筛不出来）")
    void statusDomainIsEnforced() {
        assertThatThrownBy(() -> supplierService.create(TENANT,
                Supplier.builder().name("A").status("disabled").build()))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("active / inactive");

        supplierService.create(TENANT, Supplier.builder().name("B").status("INACTIVE").build());
        ArgumentCaptor<Supplier> captor = ArgumentCaptor.forClass(Supplier.class);
        verify(supplierMapper).insert(captor.capture());
        assertThat(captor.getValue().getStatus()).isEqualTo("inactive");
    }

    @Test
    @DisplayName("更新：跨租户 id ⇒ 404，且不落库（不泄露存在性）")
    void updateRejectsForeignTenantRow() {
        when(supplierMapper.selectById("sup-1")).thenReturn(
                Supplier.builder().id("sup-1").tenantId(9999L).name("别家的厂").status("active").build());

        assertThatThrownBy(() -> supplierService.update("sup-1", TENANT,
                Supplier.builder().name("改名").build()))
                .isInstanceOf(BusinessException.class);
        verify(supplierMapper, never()).updateById(any(Supplier.class));
    }

    @Test
    @DisplayName("待指派清单：按文本名分组映射（名字 / 单数 / 最近入库日），空值不掉行")
    void unassignedInboundSuppliersMapsRows() {
        // ⚠️ 不能用 Map.of：它不接受 null 值（第二行的 last_inbound_date 就是 null）⇒ 直接在构造时就 NPE。
        java.util.Map<String, Object> withDate = new java.util.HashMap<>();
        withDate.put("supplier_name", "没建过档的厂");
        withDate.put("order_count", 3L);
        withDate.put("last_inbound_date", "2026-10-01");
        java.util.Map<String, Object> withoutDate = new java.util.HashMap<>();
        withoutDate.put("supplier_name", "老数据厂");
        withoutDate.put("order_count", 1L);
        withoutDate.put("last_inbound_date", null);
        when(inboundOrderMapper.selectUnassignedSupplierNames(TENANT))
                .thenReturn(java.util.List.of(withDate, withoutDate));

        java.util.List<UnassignedInboundSupplier> rows = supplierService.unassignedInboundSuppliers(TENANT);

        assertThat(rows).hasSize(2);
        assertThat(rows.get(0).supplierName()).isEqualTo("没建过档的厂");
        assertThat(rows.get(0).orderCount()).isEqualTo(3);
        assertThat(rows.get(0).lastInboundDate()).isEqualTo(java.time.LocalDate.of(2026, 10, 1));
        assertThat(rows.get(1).lastInboundDate()).isNull();
    }

    @Test
    @DisplayName("应付对账：逐家映射 + 合计 + 诚实标记 paymentsRecorded=false（A 段没有付款登记）")
    void payableSummaryMapsRowsAndTotals() {
        java.util.Map<String, Object> withOrders = new java.util.HashMap<>();
        withOrders.put("supplier_id", "sup-1");
        withOrders.put("supplier_name", "杭州染整一厂");
        withOrders.put("supplier_status", "active");
        withOrders.put("received_amount", new java.math.BigDecimal("12500.4000"));
        withOrders.put("order_count", 4L);
        withOrders.put("first_inbound_date", "2026-09-01");
        withOrders.put("last_inbound_date", "2026-10-10");
        // 刚建档还没收过货：金额 0、日期 null（LEFT JOIN 才看得见「建档了但没录单」）
        java.util.Map<String, Object> empty = new java.util.HashMap<>();
        empty.put("supplier_id", "sup-2");
        empty.put("supplier_name", "宏达布行");
        empty.put("supplier_status", "inactive");
        empty.put("received_amount", java.math.BigDecimal.ZERO);
        empty.put("order_count", 0L);
        empty.put("first_inbound_date", null);
        empty.put("last_inbound_date", null);
        when(inboundOrderMapper.selectSupplierPayables(TENANT))
                .thenReturn(java.util.List.of(withOrders, empty));

        var summary = supplierService.payableSummary(TENANT);

        assertThat(summary.suppliers()).hasSize(2);
        var first = summary.suppliers().get(0);
        assertThat(first.supplierName()).isEqualTo("杭州染整一厂");
        assertThat(first.receivedAmount()).isEqualByComparingTo("12500.40");
        assertThat(first.orderCount()).isEqualTo(4);
        assertThat(first.lastInboundDate()).isEqualTo(java.time.LocalDate.of(2026, 10, 10));
        assertThat(first.paidAmount()).isEqualByComparingTo("0");
        assertThat(first.outstanding()).isEqualByComparingTo("12500.40");
        assertThat(first.paymentsRecorded()).isFalse();
        // 空档案：日期为 null、金额 0，不掉行
        assertThat(summary.suppliers().get(1).lastInboundDate()).isNull();
        assertThat(summary.suppliers().get(1).receivedAmount()).isEqualByComparingTo("0");
        // 合计与「A 段恒等」：totalReceived == totalOutstanding（没有付款登记）
        assertThat(summary.totalReceived()).isEqualByComparingTo("12500.40");
        assertThat(summary.totalOutstanding()).isEqualByComparingTo("12500.40");
        assertThat(summary.paymentsRecorded()).isFalse();
    }

    @Test
    @DisplayName("更新：停用走同一条写面（status=inactive 落库）")
    void updateCanDeactivate() {
        when(supplierMapper.selectById("sup-1")).thenReturn(
                Supplier.builder().id("sup-1").tenantId(TENANT).name("杭州染整一厂").status("active").build());

        Supplier updated = supplierService.update("sup-1", TENANT, Supplier.builder()
                .name("杭州染整一厂").status("inactive").paymentTermsDays(45).build());

        assertThat(updated.getStatus()).isEqualTo("inactive");
        assertThat(updated.getPaymentTermsDays()).isEqualTo(45);
        verify(supplierMapper).updateById(any(Supplier.class));
    }
}
