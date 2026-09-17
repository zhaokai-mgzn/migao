package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.PageResponse;
import com.migao.admin.entity.StockLedger;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.service.StockLedgerService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * 库存流水/台账只读查询（issue #4055）。
 *
 * <p>本轮**只做只读端点**，不做前端页面；台账的写入方在库存变更的既有实现点
 * （{@link StockLedgerService} 类注释列了站点清单），不经过本控制器。</p>
 *
 * <p>权限复用商品域 {@code product:list}（库存属于商品管理的读权限，不新造权限点 —— 
 * 新权限点需要配角色/种子数据，本 issue 不含权限模型变更）。</p>
 */
@Slf4j
@RestController
@RequestMapping("/api/admin/stock-ledger")
@RequiredArgsConstructor
public class StockLedgerController {

    private final StockLedgerService stockLedgerService;

    /**
     * 分页查询库存流水（按 id 倒序：最新在前）。
     *
     * GET /api/admin/stock-ledger?skuId=12&productId=xxx&refNo=AS-20260918-0001&page=1&size=20
     *
     * @param skuId     SKU 主键过滤（对账单条 SKU 的变化链）
     * @param productId 商品 ID 过滤（查某商品所有 SKU 的变化）
     * @param refNo     业务单据号过滤（订单号 / 工单号，一单改了哪些 SKU）
     */
    @RequirePermission("product:list")
    @GetMapping
    public ApiResponse<PageResponse<StockLedger>> getLedger(
            @RequestParam(required = false) Long skuId,
            @RequestParam(required = false) String productId,
            @RequestParam(required = false) String refNo,
            @RequestParam(defaultValue = "1") long page,
            @RequestParam(defaultValue = "20") long size) {
        Long tenantId = TenantContext.getTenantId();
        log.info("查询库存流水: skuId={}, productId={}, refNo={}, page={}, size={}, tenantId={}",
                skuId, productId, refNo, page, size, tenantId);
        return ApiResponse.success(
                stockLedgerService.getLedgerPage(tenantId, skuId, productId, refNo, page, size));
    }
}