// case_ids: WH-009
package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.WarehouseLocationBatchCreateRequest;
import com.migao.admin.dto.WarehouseLocationBatchCreateResult;
import com.migao.admin.dto.WarehouseLocationCreateRequest;
import com.migao.admin.dto.WarehouseLocationUpdateRequest;
import com.migao.admin.dto.WarehouseLocationView;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.service.FinishedGoodsService;
import com.migao.admin.service.WarehouseLocationService;
import com.migao.admin.service.WarehouseService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.lang.reflect.Method;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 仓位档案管理端点（issue #7785 / 用例 WH-009）。
 *
 * <p>守三条：</p>
 * <ol>
 *   <li>五个端点都把**当前租户**透传（仓位是租户私有主数据）；</li>
 *   <li>读面复用 {@code inbound:view}、写面复用 {@code inbound:create}（零授权 delta）；</li>
 *   <li>管理清单请求把 {@code includeInactive} 原样透传（停用仓位要能被看到并重新启用）。</li>
 * </ol>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("仓位档案管理 Controller（issue #7785 / WH-009）")
class WarehouseLocationControllerTest {

    @Mock private FinishedGoodsService finishedGoodsService;
    @Mock private WarehouseLocationService warehouseLocationService;
    @Mock private WarehouseService warehouseService;

    @InjectMocks private FinishedGoodsController controller;

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    @Test
    @DisplayName("清单：当前租户 + 仓过滤 + includeInactive 原样透传")
    void listLocationsScopesTenantAndPassesIncludeInactive() {
        TenantContext.setTenantId(7L);
        WarehouseLocationView row = new WarehouseLocationView();
        row.setBinCode("A-01");
        when(warehouseLocationService.listView(any(), any(), eq(true))).thenReturn(List.of(row));

        var res = controller.listLocations(9L, true);

        assertThat(res.getData()).extracting(WarehouseLocationView::getBinCode).containsExactly("A-01");
        verify(warehouseLocationService).listView(eq(7L), eq(9L), eq(true));
    }

    @Test
    @DisplayName("新建：租户透传 + 回填视图")
    void createLocationScopesTenant() {
        TenantContext.setTenantId(7L);
        WarehouseLocationCreateRequest request = new WarehouseLocationCreateRequest();
        request.setBinCode("A-01");
        WarehouseLocationView view = new WarehouseLocationView();
        view.setBinCode("A-01");
        when(warehouseLocationService.create(any(), eq(7L))).thenReturn(view);

        var res = controller.createLocation(request);

        assertThat(res.getData().getBinCode()).isEqualTo("A-01");
        verify(warehouseLocationService).create(request, 7L);
    }

    @Test
    @DisplayName("批量新建：租户透传 + 回填新建/跳过计数")
    void batchCreateScopesTenant() {
        TenantContext.setTenantId(7L);
        WarehouseLocationBatchCreateRequest request = new WarehouseLocationBatchCreateRequest();
        request.setZoneCode("A");
        request.setNumberFrom(1);
        request.setNumberTo(3);
        WarehouseLocationBatchCreateResult result =
                new WarehouseLocationBatchCreateResult(2, 1, "A-01", "A-03", 10);
        when(warehouseLocationService.batchCreate(request, 7L)).thenReturn(result);

        var res = controller.batchCreateLocations(request);

        assertThat(res.getData().getCreated()).isEqualTo(2);
        assertThat(res.getData().getSkipped()).isEqualTo(1);
        verify(warehouseLocationService).batchCreate(request, 7L);
    }

    @Test
    @DisplayName("编辑 / 删除：租户透传")
    void updateAndDeleteScopeTenant() {
        TenantContext.setTenantId(7L);
        WarehouseLocationUpdateRequest request = new WarehouseLocationUpdateRequest();
        request.setStatus("inactive");
        when(warehouseLocationService.update(eq(11L), any(), eq(7L)))
                .thenReturn(new WarehouseLocationView());

        controller.updateLocation(11L, request);
        controller.deleteLocation(11L);

        verify(warehouseLocationService).update(11L, request, 7L);
        verify(warehouseLocationService).delete(11L, 7L);
    }

    @Test
    @DisplayName("权限边界：读 inbound:view / 写 inbound:create")
    void permissionCodes() throws Exception {
        assertThat(permissionOf("listLocations", Long.class, boolean.class)).isEqualTo("inbound:view");
        assertThat(permissionOf("createLocation", WarehouseLocationCreateRequest.class))
                .isEqualTo("inbound:create");
        assertThat(permissionOf("batchCreateLocations", WarehouseLocationBatchCreateRequest.class))
                .isEqualTo("inbound:create");
        assertThat(permissionOf("updateLocation", Long.class, WarehouseLocationUpdateRequest.class))
                .isEqualTo("inbound:create");
        assertThat(permissionOf("deleteLocation", Long.class)).isEqualTo("inbound:create");
    }

    private static String permissionOf(String method, Class<?>... params) throws Exception {
        Method m = FinishedGoodsController.class.getDeclaredMethod(method, params);
        RequirePermission annotation = m.getAnnotation(RequirePermission.class);
        assertThat(annotation).as("%s 必须声明 @RequirePermission", method).isNotNull();
        return annotation.value();
    }
}
