package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.FinishedGoodsView;
import com.migao.admin.entity.Warehouse;
import com.migao.admin.entity.WarehouseLocation;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.service.FinishedGoodsService;
import com.migao.admin.service.WarehouseLocationService;
import com.migao.admin.service.WarehouseService;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/**
 * 成品库存与仓位读面（V196，issue #7750）。
 *
 * <p>三个端点的权限码都复用 {@code inbound:view}（仓管/财务既有权限；零授权 delta）：
 * ① 在库成品（带**仓位号**）；② 仓位清单；③ 成品仓（打包自动建的那个）—— 商家面据此解释
 * 「仓位号是从哪来的」。</p>
 */
@RestController
@RequestMapping("/api/admin")
@RequiredArgsConstructor
public class FinishedGoodsController {

    private final FinishedGoodsService finishedGoodsService;
    private final WarehouseLocationService warehouseLocationService;
    private final WarehouseService warehouseService;

    /**
     * 成品库存（在库行 + 仓位号）
     * GET /api/admin/finished-goods
     */
    @GetMapping("/finished-goods")
    @RequirePermission("inbound:view")
    public ApiResponse<List<FinishedGoodsView>> listInStock() {
        return ApiResponse.success(finishedGoodsService.listInStock(TenantContext.getTenantId()));
    }

    /**
     * 仓位清单（可按仓过滤）
     * GET /api/admin/warehouse-locations?warehouseId=
     */
    @GetMapping("/warehouse-locations")
    @RequirePermission("inbound:view")
    public ApiResponse<List<WarehouseLocation>> listLocations(@RequestParam(required = false) Long warehouseId) {
        return ApiResponse.success(
                warehouseLocationService.list(TenantContext.getTenantId(), warehouseId));
    }

    /**
     * 成品仓（找不到 ⇒ 返回 null，**不**顺手建仓：读面不写库）
     * GET /api/admin/warehouses/finished
     */
    @GetMapping("/warehouses/finished")
    @RequirePermission("inbound:view")
    public ApiResponse<Warehouse> finishedWarehouse() {
        return ApiResponse.success(
                warehouseService.firstOfType(TenantContext.getTenantId(), Warehouse.TYPE_FINISHED));
    }
}
