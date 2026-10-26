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
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 成品仓位分配（V196 / issue #7750；V198 / issue #7791 改水位口径）。
 *
 * <p>守四条：</p>
 * <ol>
 *   <li><b>先复用再新增</b>：本区还有未满仓位（水位最低）就直接用它，不涨号；</li>
 *   <li><b>全满才新增</b>：新号 = 本区域现有行数 + 1，格式 {@code A-02}，容量沿用本区容量；</li>
 *   <li><b>占号是原子的、冲突不抛异常</b>：{@code claimBin} 走 {@code ON CONFLICT DO NOTHING}
 *       （唯一冲突不会把事务打成 aborted），抢不到就重算下一轮；</li>
 *   <li><b>新建的号不直接返回</b>：下一轮会带行锁与容量复核（并发下刚建的号可能已被填满）。</li>
 * </ol>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("成品仓位分配（V196 / issue #7750；V198 水位）")
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
        location.setCapacity(WarehouseLocationService.DEFAULT_CAPACITY);
        location.setStatus("active");
        return location;
    }

    @Test
    @DisplayName("有水位最低的未满仓位 ⇒ 直接复用，**不**新增号（一进一出不涨号）")
    void reusesLowestWaterBin() {
        when(locationMapper.selectBestBinForAllocation(TENANT, WAREHOUSE)).thenReturn(bin("A-02", 12L));

        WarehouseLocation allocated = service.nextFreeBin(TENANT, WAREHOUSE);

        assertThat(allocated.getBinCode()).isEqualTo("A-02");
        verify(locationMapper, never()).claimBin(anyLong(), anyLong(), anyString(), anyString(),
                anyString(), eq(10));
    }

    @Test
    @DisplayName("🔴 等锁期间候选仓被填满 ⇒ 复核件数后换下一个（不把已满仓当候选）")
    void fullCandidateAfterLockRetries() {
        WarehouseLocation almostFull = bin("A-01", 11L);
        almostFull.setCapacity(2);
        WarehouseLocation next = bin("A-02", 12L);
        when(locationMapper.selectBestBinForAllocation(TENANT, WAREHOUSE))
                .thenReturn(almostFull, next);
        when(stockMapper.countInStockByBinCode(TENANT, "A-01")).thenReturn(2);
        when(stockMapper.countInStockByBinCode(TENANT, "A-02")).thenReturn(0);

        WarehouseLocation allocated = service.nextFreeBin(TENANT, WAREHOUSE);

        assertThat(allocated.getBinCode()).isEqualTo("A-02");
        verify(locationMapper, never()).claimBin(anyLong(), anyLong(), anyString(), anyString(),
                anyString(), eq(10));
    }

    @Test
    @DisplayName("本区全满 ⇒ 按区域行数 + 1 新增下一个号（A-01 → A-02，容量沿用本区）")
    void createsNextBinWhenAllCapacityFull() {
        when(locationMapper.selectBestBinForAllocation(TENANT, WAREHOUSE))
                .thenReturn(null, bin("A-02", 12L));
        when(locationMapper.countBinsInZone(TENANT, WAREHOUSE, WarehouseLocationService.DEFAULT_ZONE_CODE))
                .thenReturn(1);
        when(locationMapper.selectZoneCapacity(TENANT, WAREHOUSE, WarehouseLocationService.DEFAULT_ZONE_CODE))
                .thenReturn(10);

        WarehouseLocation allocated = service.nextFreeBin(TENANT, WAREHOUSE);

        assertThat(allocated.getBinCode()).isEqualTo("A-02");
        verify(locationMapper).claimBin(TENANT, WAREHOUSE, "A", "成品区", "A-02", 10);
    }

    @Test
    @DisplayName("新号沿用本区域容量（区域容量不是默认 10 时也用本区的值）")
    void newBinUsesZoneCapacity() {
        when(locationMapper.selectBestBinForAllocation(TENANT, WAREHOUSE))
                .thenReturn(null, bin("A-01", 11L));
        when(locationMapper.countBinsInZone(TENANT, WAREHOUSE, "A")).thenReturn(0);
        when(locationMapper.selectZoneCapacity(TENANT, WAREHOUSE, "A")).thenReturn(20);

        service.nextFreeBin(TENANT, WAREHOUSE);

        verify(locationMapper).claimBin(TENANT, WAREHOUSE, "A", "成品区", "A-01", 20);
    }

    @Test
    @DisplayName("🔴 占号撞车（并发建了同一个号）⇒ 换下一轮，不抛异常、不落重复号")
    void claimConflictRetriesThenSucceeds() {
        // 第一轮：无未满仓位、占 A-01 抢不到（0 行）；第二轮：A-02 已是水位最低的未满仓
        when(locationMapper.selectBestBinForAllocation(TENANT, WAREHOUSE))
                .thenReturn(null, bin("A-02", 22L));
        when(locationMapper.countBinsInZone(TENANT, WAREHOUSE, "A")).thenReturn(0);
        when(locationMapper.selectZoneCapacity(TENANT, WAREHOUSE, "A")).thenReturn(10);

        WarehouseLocation allocated = service.nextFreeBin(TENANT, WAREHOUSE);

        assertThat(allocated.getBinCode()).isEqualTo("A-02");
        verify(locationMapper, times(1)).claimBin(eq(TENANT), eq(WAREHOUSE), eq("A"), eq("成品区"),
                eq("A-01"), eq(10));
    }

    @Test
    @DisplayName("连续 8 次都抢不到 ⇒ 显式冲突（可重试），不静默返回一个可能被占的号")
    void exhaustedAttemptsThrows() {
        when(locationMapper.selectBestBinForAllocation(TENANT, WAREHOUSE)).thenReturn(null);
        when(locationMapper.selectZoneCapacity(TENANT, WAREHOUSE, "A")).thenReturn(10);

        assertThatThrownBy(() -> service.nextFreeBin(TENANT, WAREHOUSE))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("成品仓位分配失败");
    }
}
