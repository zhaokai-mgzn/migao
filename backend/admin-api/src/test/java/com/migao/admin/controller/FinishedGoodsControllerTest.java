// case_ids: WH-005
package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.FinishedGoodsView;
import com.migao.admin.entity.Warehouse;
import com.migao.admin.entity.WarehouseLocation;
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
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 成品库存 / 仓位读面 Controller（V196，issue #7750 / 用例 WH-005）。
 *
 * <p>守三条：</p>
 * <ol>
 *   <li>三个端点都把**当前租户**透传（成品在库与仓位都是租户私有数据）；</li>
 *   <li>🔴 「成品仓」读面**只读不建**：没有成品仓时返回 null，**不**顺手调
 *       {@code ensureFinishedWarehouse}（读面写库 = GET 有副作用）；</li>
 *   <li>权限码全部复用 {@code inbound:view}（仓管/财务既有权限，零授权 delta）。</li>
 * </ol>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("成品库存 / 仓位 Controller（V196 / issue #7750）")
class FinishedGoodsControllerTest {

    @Mock private FinishedGoodsService finishedGoodsService;
    @Mock private WarehouseLocationService warehouseLocationService;
    @Mock private WarehouseService warehouseService;

    @InjectMocks private FinishedGoodsController controller;

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    @Test
    @DisplayName("成品库存读面：按当前租户读在库行（带仓位号）")
    void listInStockScopesTenant() {
        TenantContext.setTenantId(7L);
        FinishedGoodsView row = new FinishedGoodsView();
        row.setBinCode("A-01");
        when(finishedGoodsService.listInStock(any())).thenReturn(List.of(row));

        var res = controller.listInStock();

        assertThat(res.getData()).extracting(FinishedGoodsView::getBinCode).containsExactly("A-01");
        verify(finishedGoodsService).listInStock(eq(7L));
    }

    @Test
    @DisplayName("仓位清单：按仓过滤 + 当前租户")
    void listLocationsScopesTenantAndWarehouse() {
        TenantContext.setTenantId(7L);
        when(warehouseLocationService.list(any(), any())).thenReturn(List.of(new WarehouseLocation()));

        controller.listLocations(9L);

        verify(warehouseLocationService).list(eq(7L), eq(9L));
    }

    @Test
    @DisplayName("🔴 成品仓读面**只读不建**：没有就返回 null，不调 ensure（GET 不许有副作用）")
    void finishedWarehouseIsReadOnly() {
        TenantContext.setTenantId(7L);
        when(warehouseService.firstOfType(any(), any())).thenReturn(null);

        var res = controller.finishedWarehouse();

        assertThat(res.getData()).isNull();
        verify(warehouseService).firstOfType(eq(7L), eq(Warehouse.TYPE_FINISHED));
        verify(warehouseService, never()).ensureFinishedWarehouse(any());
    }

    @Test
    @DisplayName("权限边界：三个读端点都是 inbound:view")
    void permissionCodesAreInboundView() throws Exception {
        assertThat(permissionOf("listInStock")).isEqualTo("inbound:view");
        assertThat(permissionOf("listLocations", Long.class)).isEqualTo("inbound:view");
        assertThat(permissionOf("finishedWarehouse")).isEqualTo("inbound:view");
    }

    private static String permissionOf(String method, Class<?>... params) throws Exception {
        Method m = FinishedGoodsController.class.getDeclaredMethod(method, params);
        RequirePermission annotation = m.getAnnotation(RequirePermission.class);
        assertThat(annotation).as("%s 必须声明 @RequirePermission", method).isNotNull();
        return annotation.value();
    }
}
