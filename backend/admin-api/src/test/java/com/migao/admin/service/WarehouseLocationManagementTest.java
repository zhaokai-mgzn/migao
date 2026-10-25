// case_ids: WH-009
package com.migao.admin.service;

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
import org.springframework.dao.DuplicateKeyException;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 成品仓仓位档案管理（issue #7785 / 用例 WH-009）。
 *
 * <p>守五条不变式：</p>
 * <ol>
 *   <li><b>仓位号归一</b>：`a-01` ⇒ `A-01`（否则唯一索引下会出现两个肉眼同号）；非法形态在**建仓之前**拒绝；</li>
 *   <li><b>成品仓按需建</b>：新建仓位时自动建成品仓（与打包同一 ensure），商家不用先建仓；</li>
 *   <li><b>占用中禁止改号 / 删除</b>：占用判定只看 `finished_goods_stock` 的 in_stock 行；备注 / 区域名可改；</li>
 *   <li><b>软删只删空闲</b>：占用中 ⇒ 409，不写库；</li>
 *   <li><b>跨租户不可见</b>：改 / 删命中别的租户一律 404，且零写入。</li>
 * </ol>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("成品仓仓位档案管理（issue #7785 / WH-009）")
class WarehouseLocationManagementTest {

    private static final Long TENANT = 1L;
    private static final Long WAREHOUSE = 9L;

    @Mock private WarehouseLocationMapper locationMapper;
    @Mock private FinishedGoodsStockMapper stockMapper;
    @Mock private WarehouseService warehouseService;

    @InjectMocks private WarehouseLocationService service;

    private static WarehouseLocation bin(String code, String status, long id) {
        WarehouseLocation location = new WarehouseLocation();
        location.setId(id);
        location.setTenantId(TENANT);
        location.setWarehouseId(WAREHOUSE);
        location.setZoneCode(WarehouseLocationService.DEFAULT_ZONE_CODE);
        location.setZoneName(WarehouseLocationService.DEFAULT_ZONE_NAME);
        location.setBinCode(code);
        location.setStatus(status);
        return location;
    }

    private static Warehouse finishedWarehouse() {
        Warehouse warehouse = new Warehouse();
        warehouse.setId(WAREHOUSE);
        warehouse.setTenantId(TENANT);
        warehouse.setCode("CP");
        warehouse.setName("成品仓");
        warehouse.setWarehouseType(Warehouse.TYPE_FINISHED);
        return warehouse;
    }

    private static WarehouseLocationCreateRequest createRequest(String binCode) {
        WarehouseLocationCreateRequest request = new WarehouseLocationCreateRequest();
        request.setBinCode(binCode);
        return request;
    }

    // ============================================================ 新建

    @Test
    @DisplayName("新建：仓位号统一大写，区域缺省 A / 成品区，落成品仓、active、空闲")
    void createNormalizesCodeAndDefaultsZone() {
        when(warehouseService.ensureFinishedWarehouse(TENANT)).thenReturn(finishedWarehouse());
        WarehouseLocationCreateRequest request = createRequest(" a-01 ");
        request.setRemark(" 靠门 ");

        WarehouseLocationView view = service.create(request, TENANT);

        ArgumentCaptor<WarehouseLocation> saved = ArgumentCaptor.forClass(WarehouseLocation.class);
        verify(locationMapper).insert(saved.capture());
        assertThat(saved.getValue().getBinCode()).isEqualTo("A-01");
        assertThat(saved.getValue().getZoneCode()).isEqualTo("A");
        assertThat(saved.getValue().getZoneName()).isEqualTo("成品区");
        assertThat(saved.getValue().getWarehouseId()).isEqualTo(WAREHOUSE);
        assertThat(saved.getValue().getTenantId()).isEqualTo(TENANT);
        assertThat(saved.getValue().getStatus()).isEqualTo("active");
        assertThat(saved.getValue().getRemark()).isEqualTo("靠门");
        assertThat(view.getBinCode()).isEqualTo("A-01");
        assertThat(view.getOccupied()).isFalse();
        assertThat(view.getStatus()).isEqualTo("active");
    }

    @Test
    @DisplayName("新建：区域可自定义（编码大写 / 名称原样）")
    void createAcceptsCustomZone() {
        when(warehouseService.ensureFinishedWarehouse(TENANT)).thenReturn(finishedWarehouse());
        WarehouseLocationCreateRequest request = createRequest("b-02");
        request.setZoneCode("b");
        request.setZoneName(" 挂衣区 ");

        WarehouseLocationView view = service.create(request, TENANT);

        assertThat(view.getBinCode()).isEqualTo("B-02");
        assertThat(view.getZoneCode()).isEqualTo("B");
        assertThat(view.getZoneName()).isEqualTo("挂衣区");
    }

    @Test
    @DisplayName("🔴 非法仓位号 ⇒ 422，且在建成品仓之前拒绝（不留下半截副作用）")
    void createRejectsInvalidCodeBeforeCreatingWarehouse() {
        assertThatThrownBy(() -> service.create(createRequest("A 01 / 一号架"), TENANT))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("仓位号只能包含");

        verify(warehouseService, never()).ensureFinishedWarehouse(any());
        verify(locationMapper, never()).insert(any(WarehouseLocation.class));
    }

    @Test
    @DisplayName("仓位号为空 ⇒ 422（不允许生成一个「无号」仓位）")
    void createRejectsBlankCode() {
        assertThatThrownBy(() -> service.create(createRequest("   "), TENANT))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("仓位号不能为空");
        verify(locationMapper, never()).insert(any(WarehouseLocation.class));
    }

    @Test
    @DisplayName("仓位号租户内唯一：DB 唯一索引撞车 ⇒ 可读 422，不冒成 5xx")
    void createDuplicateCodeIsReadableConflict() {
        when(warehouseService.ensureFinishedWarehouse(TENANT)).thenReturn(finishedWarehouse());
        when(locationMapper.insert(any(WarehouseLocation.class)))
                .thenThrow(new DuplicateKeyException("uk_warehouse_locations_bin"));

        assertThatThrownBy(() -> service.create(createRequest("A-01"), TENANT))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("仓位号 A-01 已存在");
    }

    // ============================================================ 编辑

    @Test
    @DisplayName("🔴 占用中改仓位号 ⇒ 409，且不写库（在库行与已贴标签认的是旧号）")
    void updateRejectsRenamingOccupiedBin() {
        WarehouseLocation occupied = bin("A-01", "active", 11L);
        when(locationMapper.selectById(11L)).thenReturn(occupied);
        when(stockMapper.countInStockByBinCode(TENANT, "A-01")).thenReturn(1);
        WarehouseLocationUpdateRequest request = new WarehouseLocationUpdateRequest();
        request.setBinCode("A-02");

        assertThatThrownBy(() -> service.update(11L, request, TENANT))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("不能改仓位号");
        verify(locationMapper, never()).updateById(any(WarehouseLocation.class));
    }

    @Test
    @DisplayName("占用中仍可改备注 / 区域名（这些不影响在库关联）")
    void updateAllowsRemarkAndZoneOnOccupiedBin() {
        WarehouseLocation occupied = bin("A-01", "active", 11L);
        when(locationMapper.selectById(11L)).thenReturn(occupied);
        when(stockMapper.countInStockByBinCode(TENANT, "A-01")).thenReturn(1);
        WarehouseLocationUpdateRequest request = new WarehouseLocationUpdateRequest();
        request.setRemark("靠门口");
        request.setZoneName("成品待发区");

        WarehouseLocationView view = service.update(11L, request, TENANT);

        assertThat(view.getRemark()).isEqualTo("靠门口");
        assertThat(view.getZoneName()).isEqualTo("成品待发区");
        assertThat(view.getOccupied()).isTrue();
        verify(locationMapper).updateById(occupied);
    }

    @Test
    @DisplayName("空闲仓位可改号：归一后写回")
    void updateRenamesFreeBin() {
        WarehouseLocation free = bin("A-01", "active", 11L);
        when(locationMapper.selectById(11L)).thenReturn(free);
        when(stockMapper.countInStockByBinCode(TENANT, "A-01")).thenReturn(0);
        when(stockMapper.countInStockByBinCode(TENANT, "B-02")).thenReturn(0);
        WarehouseLocationUpdateRequest request = new WarehouseLocationUpdateRequest();
        request.setBinCode("b-02");

        WarehouseLocationView view = service.update(11L, request, TENANT);

        assertThat(view.getBinCode()).isEqualTo("B-02");
        assertThat(free.getBinCode()).isEqualTo("B-02");
        verify(locationMapper).updateById(free);
    }

    @Test
    @DisplayName("停用 / 启用：只改状态，不影响已占用库存")
    void updateTogglesStatus() {
        WarehouseLocation location = bin("A-01", "active", 11L);
        when(locationMapper.selectById(11L)).thenReturn(location);
        when(stockMapper.countInStockByBinCode(TENANT, "A-01")).thenReturn(1);
        WarehouseLocationUpdateRequest request = new WarehouseLocationUpdateRequest();
        request.setStatus("inactive");

        WarehouseLocationView view = service.update(11L, request, TENANT);

        assertThat(view.getStatus()).isEqualTo("inactive");
        assertThat(view.getOccupied()).isTrue();
    }

    @Test
    @DisplayName("非法状态 ⇒ 422（只认 active / inactive，与表 CHECK 同一份）")
    void updateRejectsInvalidStatus() {
        WarehouseLocation location = bin("A-01", "active", 11L);
        when(locationMapper.selectById(11L)).thenReturn(location);
        WarehouseLocationUpdateRequest request = new WarehouseLocationUpdateRequest();
        request.setStatus("broken");

        assertThatThrownBy(() -> service.update(11L, request, TENANT))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("active / inactive");
        verify(locationMapper, never()).updateById(any(WarehouseLocation.class));
    }

    // ============================================================ 删除

    @Test
    @DisplayName("🔴 占用中删除 ⇒ 409，且不软删（仓位仍在，库存可追溯）")
    void deleteRejectsOccupiedBin() {
        WarehouseLocation occupied = bin("A-01", "active", 11L);
        when(locationMapper.selectById(11L)).thenReturn(occupied);
        when(stockMapper.countInStockByBinCode(TENANT, "A-01")).thenReturn(1);

        assertThatThrownBy(() -> service.delete(11L, TENANT))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("不能删除");
        verify(locationMapper, never()).deleteById(anyLong());
    }

    @Test
    @DisplayName("空闲仓位删除 ⇒ 软删（历史单据保留 bin_code 快照）")
    void deleteSoftDeletesFreeBin() {
        WarehouseLocation free = bin("A-01", "active", 11L);
        when(locationMapper.selectById(11L)).thenReturn(free);
        when(stockMapper.countInStockByBinCode(TENANT, "A-01")).thenReturn(0);
        when(locationMapper.deleteById(11L)).thenReturn(1);

        service.delete(11L, TENANT);

        verify(locationMapper).deleteById(11L);
    }

    @Test
    @DisplayName("并发双删：删除影响 0 行 ⇒ 404（不把「没删到」谎报成成功）")
    void deleteLostRaceIsNotFound() {
        WarehouseLocation free = bin("A-01", "active", 11L);
        when(locationMapper.selectById(11L)).thenReturn(free);
        when(stockMapper.countInStockByBinCode(TENANT, "A-01")).thenReturn(0);
        when(locationMapper.deleteById(11L)).thenReturn(0);

        assertThatThrownBy(() -> service.delete(11L, TENANT))
                .isInstanceOf(BusinessException.class)
                .hasMessage("仓位不存在")
                .satisfies(ex -> assertThat(((BusinessException) ex).getSuggestion())
                        .contains("可能刚被其他人删除"));
    }

    // ============================================================ 租户隔离 / 清单

    @Test
    @DisplayName("🔴 跨租户改 / 删 ⇒ 404，零写入（不泄露存在性）")
    void crossTenantIsInvisible() {
        WarehouseLocation foreign = bin("A-01", "active", 11L);
        foreign.setTenantId(2L);
        when(locationMapper.selectById(11L)).thenReturn(foreign);

        assertThatThrownBy(() -> service.update(11L, new WarehouseLocationUpdateRequest(), TENANT))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("仓位不存在");
        assertThatThrownBy(() -> service.delete(11L, TENANT))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("仓位不存在");

        verify(locationMapper, never()).updateById(any(WarehouseLocation.class));
        verify(locationMapper, never()).deleteById(anyLong());
    }

    @Test
    @DisplayName("清单：一次查全租户占用号（不按 500 行截断），并可按需带出停用仓位")
    void listViewMarksOccupancyAndIncludesInactive() {
        when(locationMapper.selectList(any()))
                .thenReturn(List.of(bin("A-01", "active", 11L), bin("A-02", "inactive", 12L)));
        when(stockMapper.selectOccupiedBinCodes(TENANT)).thenReturn(List.of("A-01"));

        List<WarehouseLocationView> views = service.listView(TENANT, null, true);

        assertThat(views).hasSize(2);
        assertThat(views.get(0).getBinCode()).isEqualTo("A-01");
        assertThat(views.get(0).getOccupied()).isTrue();
        assertThat(views.get(1).getBinCode()).isEqualTo("A-02");
        assertThat(views.get(1).getStatus()).isEqualTo("inactive");
        assertThat(views.get(1).getOccupied()).isFalse();
        verify(stockMapper).selectOccupiedBinCodes(eq(TENANT));
    }
}
