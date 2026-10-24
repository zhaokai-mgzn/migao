package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.StockTransferRequest;
import com.migao.admin.dto.StockTransferView;
import com.migao.admin.dto.WarehouseCreateRequest;
import com.migao.admin.entity.Warehouse;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.service.StockTransferService;
import com.migao.admin.service.WarehouseService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/**
 * 多仓与调拨（issue #7373，P1-1 段 1）。
 *
 * <p>授权零 delta：仓与库存同域 ⇒ 读面 `inbound:view`、写面 `inbound:create`（与既有入库/批次读面一致），
 * 不新造权限码（新码会让现网种子岗位全体失效）。</p>
 */
@Slf4j
@RestController
@RequestMapping("/api/admin")
@RequiredArgsConstructor
public class WarehouseController {

    private final WarehouseService warehouseService;
    private final StockTransferService stockTransferService;

    /** 仓库列表：`GET /api/admin/warehouses`（默认仓排最前）。 */
    @GetMapping("/warehouses")
    @RequirePermission("inbound:view")
    public ApiResponse<List<Warehouse>> listWarehouses() {
        return ApiResponse.success(warehouseService.list());
    }

    /** 建仓：`POST /api/admin/warehouses`（`isDefault` 为真时把旧的默认仓取消）。 */
    @PostMapping("/warehouses")
    @RequirePermission("inbound:create")
    public ApiResponse<Warehouse> createWarehouse(@RequestBody WarehouseCreateRequest request) {
        Long tenantId = TenantContext.getTenantId();
        log.info("[warehouse] 建仓请求 code={} default={}", request.getCode(), request.getIsDefault());
        return ApiResponse.success(warehouseService.create(request, tenantId));
    }

    /**
     * 调拨（即时完成）：`POST /api/admin/stock-transfers`。
     *
     * <p>库里守恒：同一批次行只改归属仓、不改数量；缸号随行不丢。</p>
     */
    @PostMapping("/stock-transfers")
    @RequirePermission("inbound:create")
    public ApiResponse<StockTransferView> transfer(@RequestBody StockTransferRequest request) {
        Long tenantId = TenantContext.getTenantId();
        log.info("[transfer] 调拨请求 from={} to={} lines={}",
                request.getFromWarehouseId(), request.getToWarehouseId(),
                request.getItems() == null ? 0 : request.getItems().size());
        return ApiResponse.success(stockTransferService.transfer(request, tenantId));
    }

    /** 调拨单详情：`GET /api/admin/stock-transfers/{id}`。 */
    @GetMapping("/stock-transfers/{id}")
    @RequirePermission("inbound:view")
    public ApiResponse<StockTransferView> viewTransfer(@PathVariable String id) {
        return ApiResponse.success(stockTransferService.view(id));
    }
}
