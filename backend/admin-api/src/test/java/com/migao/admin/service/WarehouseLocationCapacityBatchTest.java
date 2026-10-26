// case_ids: WH-010
package com.migao.admin.service;

import com.migao.admin.dto.WarehouseLocationBatchCreateRequest;
import com.migao.admin.dto.WarehouseLocationBatchCreateResult;
import com.migao.admin.dto.WarehouseLocationCreateRequest;
import com.migao.admin.dto.WarehouseLocationUpdateRequest;
import com.migao.admin.dto.WarehouseLocationView;
import com.migao.admin.entity.Warehouse;
import com.migao.admin.entity.WarehouseLocation;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.FinishedGoodsStockMapper;
import com.migao.admin.mapper.WarehouseLocationMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 成品仓容量 / 水位 / 批量建号（issue #7791 / 用例 WH-010）。
 *
 * <p>守五条：</p>
 * <ol>
 *   <li><b>容量按区域统一</b>：改一个仓的容量 ⇒ 本区所有仓一起改；</li>
 *   <li><b>新建沿用本区容量</b>：不传容量时用本区现有值，新区域缺省 10；</li>
 *   <li><b>批量建号幂等</b>：区间内已存在的跳过，返回新建 / 跳过计数；</li>
 *   <li><b>区间有界</b>：1~9999、单次 ≤500、结束不小于开始；</li>
 *   <li><b>容量有界</b>：1~999，非法在写库前拒绝。</li>
 * </ol>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("成品仓容量 / 水位 / 批量建号（issue #7791 / WH-010）")
class WarehouseLocationCapacityBatchTest {

    private static final Long TENANT = 1L;
    private static final Long WAREHOUSE = 9L;

    @Mock private WarehouseLocationMapper locationMapper;
    @Mock private FinishedGoodsStockMapper stockMapper;
    @Mock private WarehouseService warehouseService;

    @InjectMocks private WarehouseLocationService service;

    private static Warehouse warehouse() {
        Warehouse warehouse = new Warehouse();
        warehouse.setId(WAREHOUSE);
        warehouse.setTenantId(TENANT);
        warehouse.setCode("CP");
        warehouse.setName("成品仓");
        warehouse.setWarehouseType(Warehouse.TYPE_FINISHED);
        return warehouse;
    }

    private static WarehouseLocation bin(String code, long id, int capacity) {
        WarehouseLocation location = new WarehouseLocation();
        location.setId(id);
        location.setTenantId(TENANT);
        location.setWarehouseId(WAREHOUSE);
        location.setZoneCode("A");
        location.setZoneName("成品区");
        location.setBinCode(code);
        location.setCapacity(capacity);
        location.setStatus("active");
        return location;
    }

    private static WarehouseLocationBatchCreateRequest batch(int from, int to, Integer capacity) {
        WarehouseLocationBatchCreateRequest request = new WarehouseLocationBatchCreateRequest();
        request.setZoneCode("a");
        request.setNumberFrom(from);
        request.setNumberTo(to);
        request.setCapacity(capacity);
        return request;
    }

    @Test
    @DisplayName("新建不传容量 ⇒ 沿用本区现有容量（不是写死 10）")
    void createUsesZoneCapacity() {
        when(warehouseService.ensureFinishedWarehouse(TENANT)).thenReturn(warehouse());
        when(locationMapper.selectZoneCapacity(TENANT, WAREHOUSE, "A")).thenReturn(12);
        WarehouseLocationCreateRequest request = new WarehouseLocationCreateRequest();
        request.setBinCode("A-02");

        WarehouseLocationView view = service.create(request, TENANT);

        ArgumentCaptor<WarehouseLocation> saved = ArgumentCaptor.forClass(WarehouseLocation.class);
        verify(locationMapper).insert(saved.capture());
        assertThat(saved.getValue().getCapacity()).isEqualTo(12);
        assertThat(view.getCapacity()).isEqualTo(12);
        verify(locationMapper, never()).updateCapacityByZone(any(), any(), any(), any());
    }

    @Test
    @DisplayName("新建给了不同容量 ⇒ 同步本区所有仓位（区域统一）")
    void createWithCapacitySyncsZone() {
        when(warehouseService.ensureFinishedWarehouse(TENANT)).thenReturn(warehouse());
        when(locationMapper.selectZoneCapacity(TENANT, WAREHOUSE, "A")).thenReturn(10);
        WarehouseLocationCreateRequest request = new WarehouseLocationCreateRequest();
        request.setBinCode("A-02");
        request.setCapacity(5);

        service.create(request, TENANT);

        verify(locationMapper).updateCapacityByZone(TENANT, WAREHOUSE, "A", 5);
    }

    @Test
    @DisplayName("改容量 ⇒ 同步本区所有仓位（不是只改这一行）")
    void updateCapacitySyncsZone() {
        WarehouseLocation row = bin("A-01", 11L, 10);
        when(locationMapper.selectById(11L)).thenReturn(row);
        when(stockMapper.countInStockByBinCode(TENANT, "A-01")).thenReturn(0);
        WarehouseLocationUpdateRequest request = new WarehouseLocationUpdateRequest();
        request.setCapacity(6);

        WarehouseLocationView view = service.update(11L, request, TENANT);

        assertThat(view.getCapacity()).isEqualTo(6);
        verify(locationMapper).updateCapacityByZone(TENANT, WAREHOUSE, "A", 6);
    }

    @Test
    @DisplayName("改区域但不传容量 ⇒ 跟随新区域的现有容量（不破坏区域统一）")
    void zoneMoveAdoptsNewZoneCapacity() {
        WarehouseLocation row = bin("A-01", 11L, 10);
        when(locationMapper.selectById(11L)).thenReturn(row);
        when(stockMapper.countInStockByBinCode(TENANT, "A-01")).thenReturn(0);
        when(locationMapper.selectZoneCapacity(TENANT, WAREHOUSE, "B")).thenReturn(6);
        WarehouseLocationUpdateRequest request = new WarehouseLocationUpdateRequest();
        request.setZoneCode("B");

        WarehouseLocationView view = service.update(11L, request, TENANT);

        assertThat(view.getZoneCode()).isEqualTo("B");
        assertThat(view.getCapacity()).isEqualTo(6);
        verify(locationMapper, never()).updateCapacityByZone(any(), any(), any(), any());
    }

    @Test
    @DisplayName("容量越界（0 / 1000）⇒ 422，写库前拒绝")
    void capacityOutOfRangeRejected() {
        WarehouseLocationCreateRequest create = new WarehouseLocationCreateRequest();
        create.setBinCode("A-01");
        create.setCapacity(1000);
        assertThatThrownBy(() -> service.create(create, TENANT))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("1~999");
        verify(warehouseService, never()).ensureFinishedWarehouse(any());

        WarehouseLocation row = bin("A-01", 11L, 10);
        when(locationMapper.selectById(11L)).thenReturn(row);
        WarehouseLocationUpdateRequest update = new WarehouseLocationUpdateRequest();
        update.setCapacity(0);
        assertThatThrownBy(() -> service.update(11L, update, TENANT))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("1~999");
        verify(locationMapper, never()).updateById(any(WarehouseLocation.class));
    }

    @Test
    @DisplayName("批量 A 1~3：生成 A-01…A-03，已存在的跳过并计数")
    void batchCreatesRangeAndCountsSkipped() {
        when(warehouseService.ensureFinishedWarehouse(TENANT)).thenReturn(warehouse());
        when(locationMapper.selectZoneCapacity(TENANT, WAREHOUSE, "A")).thenReturn(null);
        when(locationMapper.claimBin(TENANT, WAREHOUSE, "A", "成品区", "A-01", 10)).thenReturn(1);
        when(locationMapper.claimBin(TENANT, WAREHOUSE, "A", "成品区", "A-02", 10)).thenReturn(0);
        when(locationMapper.claimBin(TENANT, WAREHOUSE, "A", "成品区", "A-03", 10)).thenReturn(1);

        WarehouseLocationBatchCreateResult result = service.batchCreate(batch(1, 3, null), TENANT);

        assertThat(result.getCreated()).isEqualTo(2);
        assertThat(result.getSkipped()).isEqualTo(1);
        assertThat(result.getFromCode()).isEqualTo("A-01");
        assertThat(result.getToCode()).isEqualTo("A-03");
        assertThat(result.getCapacity()).isEqualTo(10);
        verify(locationMapper).claimBin(TENANT, WAREHOUSE, "A", "成品区", "A-02", 10);
    }

    @Test
    @DisplayName("批量给了不同容量 ⇒ 同步本区所有仓位")
    void batchWithCapacitySyncsZone() {
        when(warehouseService.ensureFinishedWarehouse(TENANT)).thenReturn(warehouse());
        when(locationMapper.selectZoneCapacity(TENANT, WAREHOUSE, "A")).thenReturn(10);
        when(locationMapper.claimBin(eq(TENANT), eq(WAREHOUSE), eq("A"), eq("成品区"), any(), eq(4)))
                .thenReturn(1);

        WarehouseLocationBatchCreateResult result = service.batchCreate(batch(1, 2, 4), TENANT);

        assertThat(result.getCapacity()).isEqualTo(4);
        verify(locationMapper).updateCapacityByZone(TENANT, WAREHOUSE, "A", 4);
    }

    @Test
    @DisplayName("批量区间非法 / 超过 500 ⇒ 422，不建成品仓、不写库")
    void batchRangeRejected() {
        assertThatThrownBy(() -> service.batchCreate(batch(5, 2, null), TENANT))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("结束编号不能小于起始编号");
        assertThatThrownBy(() -> service.batchCreate(batch(1, 501, null), TENANT))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("最多创建 500");
        WarehouseLocationBatchCreateRequest missing = batch(1, 2, null);
        missing.setNumberFrom(null);
        assertThatThrownBy(() -> service.batchCreate(missing, TENANT))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("起始编号不能为空");

        verify(warehouseService, never()).ensureFinishedWarehouse(any());
        verify(locationMapper, never()).claimBin(any(), any(), any(), any(), any(), any());
    }

    @Test
    @DisplayName("批量编号上界 9999（A-9999 合法；10000 拒绝）")
    void batchNumberUpperBound() {
        assertThatThrownBy(() -> service.batchCreate(batch(9999, 10000, null), TENANT))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("1~9999");
    }
}
