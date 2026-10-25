package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.FinishedGoodsView;
import com.migao.admin.dto.WarehouseLocationBatchCreateRequest;
import com.migao.admin.dto.WarehouseLocationBatchCreateResult;
import com.migao.admin.dto.WarehouseLocationCreateRequest;
import com.migao.admin.dto.WarehouseLocationUpdateRequest;
import com.migao.admin.dto.WarehouseLocationView;
import com.migao.admin.entity.Warehouse;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.service.FinishedGoodsService;
import com.migao.admin.service.WarehouseLocationService;
import com.migao.admin.service.WarehouseService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import com.migao.admin.security.TenantOwnedResource;

import java.util.List;

/**
 * 成品库存与仓位（V196，issue #7750；仓位档案管理 = issue #7785）。
 *
 * <p>读面权限码复用 {@code inbound:view}、写面复用 {@code inbound:create}（仓管/财务既有权限；
 * 零授权 delta，不新造权限码 —— 新码会让现网种子岗位全体失效）：</p>
 * <ol>
 *   <li>在库成品（带**仓位号**）；</li>
 *   <li>仓位清单 / 新建 / 编辑 / 删除（出库单页的「仓位管理」视图）；</li>
 *   <li>成品仓（打包自动建的那个）—— 商家面据此解释「仓位号是从哪来的」。</li>
 * </ol>
 *
 * <p>🔴 「成品仓」读面**只读不建**（GET 不许有副作用）；第一次新建仓位时由写面自动建成品仓
 * （与打包同一 {@code ensureFinishedWarehouse}）。</p>
 */
@Slf4j
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
     * 仓位清单（可按仓过滤；`includeInactive=true` = 管理模式，带占用态并可看到停用仓位）
     * GET /api/admin/warehouse-locations?warehouseId=&includeInactive=
     */
    @GetMapping("/warehouse-locations")
    @RequirePermission("inbound:view")
    public ApiResponse<List<WarehouseLocationView>> listLocations(
            @RequestParam(required = false) Long warehouseId,
            @RequestParam(required = false, defaultValue = "false") boolean includeInactive) {
        return ApiResponse.success(warehouseLocationService.listView(
                TenantContext.getTenantId(), warehouseId, includeInactive));
    }

    /**
     * 新建仓位（成品仓不存在时自动建；仓位号租户内唯一）
     * POST /api/admin/warehouse-locations
     */
    @PostMapping("/warehouse-locations")
    @RequirePermission("inbound:create")
    public ApiResponse<WarehouseLocationView> createLocation(
            @RequestBody WarehouseLocationCreateRequest request) {
        Long tenantId = TenantContext.getTenantId();
        log.info("[仓位] 新建请求 | tenant={} bin={} capacity={}",
                tenantId, request.getBinCode(), request.getCapacity());
        return ApiResponse.success(warehouseLocationService.create(request, tenantId));
    }

    /**
     * 批量新建仓位（issue #7791：输入数字区间，如 A 区 1~20 ⇒ A-01…A-20；已存在的跳过）
     * POST /api/admin/warehouse-locations/batch
     */
    @PostMapping("/warehouse-locations/batch")
    @RequirePermission("inbound:create")
    public ApiResponse<WarehouseLocationBatchCreateResult> batchCreateLocations(
            @RequestBody WarehouseLocationBatchCreateRequest request) {
        Long tenantId = TenantContext.getTenantId();
        log.info("[仓位] 批量新建请求 | tenant={} zone={} from={} to={}",
                tenantId, request.getZoneCode(), request.getNumberFrom(), request.getNumberTo());
        return ApiResponse.success(warehouseLocationService.batchCreate(request, tenantId));
    }

    /**
     * 编辑仓位（占用中禁止改仓位号；区域 / 备注 / 容量 / 停用可改）
     * PATCH /api/admin/warehouse-locations/{id}
     */
    @TenantOwnedResource("warehouse-location")
    @PatchMapping("/warehouse-locations/{id}")
    @RequirePermission("inbound:create")
    public ApiResponse<WarehouseLocationView> updateLocation(
            @PathVariable Long id,
            @RequestBody WarehouseLocationUpdateRequest request) {
        Long tenantId = TenantContext.getTenantId();
        log.info("[仓位] 编辑请求 | tenant={} id={}", tenantId, id);
        return ApiResponse.success(warehouseLocationService.update(id, request, tenantId));
    }

    /**
     * 删除仓位（软删；占用中 ⇒ 409）
     * DELETE /api/admin/warehouse-locations/{id}
     */
    @DeleteMapping("/warehouse-locations/{id}")
    @RequirePermission("inbound:create")
    public ApiResponse<Void> deleteLocation(@PathVariable Long id) {
        Long tenantId = TenantContext.getTenantId();
        log.info("[仓位] 删除请求 | tenant={} id={}", tenantId, id);
        warehouseLocationService.delete(id, tenantId);
        return ApiResponse.success();
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
