// case_ids: SP-001

package com.migao.admin.service;

import com.migao.admin.entity.Supplier;
import com.migao.admin.exception.BusinessException;
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
