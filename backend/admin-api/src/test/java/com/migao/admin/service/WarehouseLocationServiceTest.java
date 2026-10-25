// case_ids: WH-003
package com.migao.admin.service;

import com.migao.admin.entity.WarehouseLocation;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.FinishedGoodsStockMapper;
import com.migao.admin.mapper.WarehouseLocationMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 成品仓位分配（V196，issue #7750 / 用例 WH-003）。
 *
 * <p>守三条：</p>
 * <ol>
 *   <li><b>先复用后新增</b>：已释放的仓位优先复用（否则一进一出就涨号，仓位上永远只增不减）；</li>
 *   <li><b>全占满才新增</b>：新号 = 本区域现有行数 + 1，格式 {@code A-01}；</li>
 *   <li><b>占号是原子的、冲突不抛异常</b>：{@code claimBin} 走 {@code ON CONFLICT DO NOTHING}
 *       （唯一冲突不会把事务打成 aborted），抢不到就重算下一轮。</li>
 * </ol>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("成品仓位分配（V196 / issue #7750）")
class WarehouseLocationServiceTest {

    private static final Long TENANT = 1L;
    private static final Long WAREHOUSE = 9L;

    @Mock private WarehouseLocationMapper locationMapper;
    @Mock private FinishedGoodsStockMapper stockMapper;
    @Mock private WarehouseService warehouseService;

    @InjectMocks private WarehouseLocationService service;

    private static WarehouseLocation bin(String code, long id) {
        WarehouseLocation location = new WarehouseLocation();
        location.setId(id);
        location.setTenantId(TENANT);
        location.setWarehouseId(WAREHOUSE);
        location.setZoneCode(WarehouseLocationService.DEFAULT_ZONE_CODE);
        location.setZoneName(WarehouseLocationService.DEFAULT_ZONE_NAME);
        location.setBinCode(code);
        location.setStatus("active");
        return location;
    }

    @Test
    @DisplayName("有空闲仓位 ⇒ 直接复用，**不**新增号（一进一出不涨号）")
    void reusesFreeBin() {
        when(locationMapper.selectFirstFreeBin(TENANT, WAREHOUSE)).thenReturn(bin("A-01", 11L));

        WarehouseLocation allocated = service.nextFreeBin(TENANT, WAREHOUSE);

        assertThat(allocated.getBinCode()).isEqualTo("A-01");
        verify(locationMapper, never()).claimBin(anyLong(), anyLong(), anyString(), anyString(), anyString());
    }

    @Test
    @DisplayName("全占满 ⇒ 按区域行数 + 1 新增下一个号（A-01 → A-02）")
    void createsNextBinWhenAllOccupied() {
        when(locationMapper.selectFirstFreeBin(TENANT, WAREHOUSE)).thenReturn(null, bin("A-02", 12L));
        when(locationMapper.countBinsInZone(TENANT, WAREHOUSE, WarehouseLocationService.DEFAULT_ZONE_CODE))
                .thenReturn(1);
        when(locationMapper.selectByBinCode(TENANT, "A-02")).thenReturn(bin("A-02", 12L));

        WarehouseLocation allocated = service.nextFreeBin(TENANT, WAREHOUSE);

        assertThat(allocated.getBinCode()).isEqualTo("A-02");
        verify(locationMapper).claimBin(TENANT, WAREHOUSE, "A", "成品区", "A-02");
    }

    @Test
    @DisplayName("🔴 占号撞车（并发建了同一个号）⇒ 换下一轮，不抛异常、不落重复号")
    void claimConflictRetriesThenSucceeds() {
        // 第一轮：无空闲、占 A-01 抢不到（selectByBinCode 返回 null）；第二轮：已有空闲 A-02
        when(locationMapper.selectFirstFreeBin(TENANT, WAREHOUSE))
                .thenReturn(null, bin("A-02", 22L));
        when(locationMapper.countBinsInZone(TENANT, WAREHOUSE, "A")).thenReturn(0);
        when(locationMapper.selectByBinCode(TENANT, "A-01")).thenReturn(null);

        WarehouseLocation allocated = service.nextFreeBin(TENANT, WAREHOUSE);

        assertThat(allocated.getBinCode()).isEqualTo("A-02");
        verify(locationMapper, times(1)).claimBin(eq(TENANT), eq(WAREHOUSE), eq("A"), eq("成品区"), eq("A-01"));
    }

    @Test
    @DisplayName("连续 8 次都抢不到 ⇒ 显式冲突（可重试），不静默返回一个可能被占的号")
    void exhaustedAttemptsThrows() {
        when(locationMapper.selectFirstFreeBin(TENANT, WAREHOUSE)).thenReturn(null);
        when(locationMapper.selectByBinCode(eq(TENANT), anyString())).thenReturn(null);

        assertThatThrownBy(() -> service.nextFreeBin(TENANT, WAREHOUSE))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("成品仓位分配失败");
    }
}
