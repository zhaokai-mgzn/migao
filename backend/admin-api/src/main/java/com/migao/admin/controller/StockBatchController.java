package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.BatchStockViews;
import com.migao.admin.dto.PageResponse;
import com.migao.admin.entity.StockBatchConsumption;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.service.StockBatchConsumptionService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.math.BigDecimal;
import java.util.List;

/**
 * 批次账只读查询（V116，issue #5145 阶段 1）。
 *
 * <p>四个读面：① 批次余量（派生 = 入库量 − Σ消耗）；② 剩余量分布（四档）；
 * ③ 对账（{@code Σ批次余量} vs {@code product_skus.stock} 的差额 —— 路线 A 的交换条件）；
 * ④ 派工候选 + 建议值（生成加工单界面用）。另有一个消耗台账分页端点
 * （按批次 / 加工单 / 订单都能查回来）。</p>
 *
 * <p>本轮**只做只读端点**，不做写端点：批次账的写入方是库存变更的既有实现点
 * （{@code StockBatchConsumptionService} 的 plan/apply/reverse，由加工单生成与作废驱动），
 * 不经过本控制器 —— 同 {@code StockLedgerController} 的口径。</p>
 *
 * <p>权限复用商品域 {@code product:list}（批次/库存属于商品管理的读权限，不新造权限点 ——
 * 新权限点需要配角色/种子数据，本 issue 不含权限模型变更）。</p>
 */
@Slf4j
@RestController
@RequestMapping("/api/admin/batch-stock")
@RequiredArgsConstructor
public class StockBatchController {

    private final StockBatchConsumptionService stockBatchConsumptionService;

    /**
     * 批次余量列表（派生）。
     *
     * GET /api/admin/batch-stock/batches?productId=xxx&skuId=12&onlyAvailable=true
     *
     * @param onlyAvailable true ⇒ 只回余量 &gt; 0 的批次（「还有哪些能用」）
     */
    @RequirePermission("product:list")
    @GetMapping("/batches")
    public ApiResponse<List<BatchStockViews.BatchRemaining>> batches(
            @RequestParam(required = false) String productId,
            @RequestParam(required = false) Long skuId,
            @RequestParam(defaultValue = "false") boolean onlyAvailable) {
        Long tenantId = TenantContext.getTenantId();
        return ApiResponse.success(
                stockBatchConsumptionService.remaining(tenantId, productId, skuId, onlyAvailable));
    }

    /**
     * 剩余量分布（四档 `≤0.2m / 0.2~0.5m / 0.5~1m / &gt;1m`，按批次数与占比）。
     *
     * GET /api/admin/batch-stock/distribution?productId=xxx
     */
    @RequirePermission("product:list")
    @GetMapping("/distribution")
    public ApiResponse<BatchStockViews.Distribution> distribution(
            @RequestParam(required = false) String productId) {
        Long tenantId = TenantContext.getTenantId();
        return ApiResponse.success(stockBatchConsumptionService.distribution(tenantId, productId));
    }

    /**
     * 对账读面：{@code Σ批次余量} 与 {@code product_skus.stock} 的差额（可读出、可解释）。
     *
     * GET /api/admin/batch-stock/reconcile?productId=xxx&skuId=12
     */
    @RequirePermission("product:list")
    @GetMapping("/reconcile")
    public ApiResponse<BatchStockViews.Reconcile> reconcile(
            @RequestParam(required = false) String productId,
            @RequestParam(required = false) Long skuId) {
        Long tenantId = TenantContext.getTenantId();
        return ApiResponse.success(stockBatchConsumptionService.reconcile(tenantId, productId, skuId));
    }

    /**
     * 派工候选批次 + 建议值（生成加工单界面用）。
     *
     * GET /api/admin/batch-stock/candidates?productId=xxx&skuId=12&meters=2.7
     *
     * @param meters 该行需要的米数（用于算 `enough` 与建议值；可空 ⇒ 只按先进先出给建议）
     */
    @RequirePermission("product:list")
    @GetMapping("/candidates")
    public ApiResponse<BatchStockViews.Candidates> candidates(
            @RequestParam(required = false) String productId,
            @RequestParam(required = false) Long skuId,
            @RequestParam(required = false) BigDecimal meters) {
        Long tenantId = TenantContext.getTenantId();
        return ApiResponse.success(
                stockBatchConsumptionService.candidates(tenantId, productId, skuId, meters));
    }

    /**
     * 消耗台账分页（判据：按**批次 / 加工单 / 订单**查回来）。
     *
     * GET /api/admin/batch-stock/consumptions?batchNo=PC-20260923-0001&page=1&size=20
     */
    @RequirePermission("product:list")
    @GetMapping("/consumptions")
    public ApiResponse<PageResponse<StockBatchConsumption>> consumptions(
            @RequestParam(required = false) String batchNo,
            @RequestParam(required = false) String processingOrderNo,
            @RequestParam(required = false) String orderNo,
            @RequestParam(defaultValue = "1") long page,
            @RequestParam(defaultValue = "20") long size) {
        Long tenantId = TenantContext.getTenantId();
        log.info("查询批次消耗台账: batchNo={}, po={}, orderNo={}, page={}, size={}, tenantId={}",
                batchNo, processingOrderNo, orderNo, page, size, tenantId);
        return ApiResponse.success(stockBatchConsumptionService.consumptionPage(
                tenantId, batchNo, processingOrderNo, orderNo, page, size));
    }
}
