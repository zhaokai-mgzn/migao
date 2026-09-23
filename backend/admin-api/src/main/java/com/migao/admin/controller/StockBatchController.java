package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.BatchStockViews;
import com.migao.admin.dto.PageResponse;
import com.migao.admin.dto.SavingMetricViews;
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
     * GET /api/admin/batch-stock/candidates?productId=xxx&skuId=12&meters=2.7&assignmentRule=best_fit
     *
     * @param meters         该行需要的米数（用于算 `enough` 与建议值；可空 ⇒ 只按先进先出给建议）
     * @param assignmentRule 指派规则（issue #5167）：`fifo`（**缺省**，入库日期早者优先）/
     *                       `best_fit`（余量最接近需求者优先，让批次被用尽）。未知取值 ⇒ **400 显式拒绝**
     *                       （不静默回落 fifo）；当前生效的规则由响应 `suggestionRule` 回口径。
     */
    @RequirePermission("product:list")
    @GetMapping("/candidates")
    public ApiResponse<BatchStockViews.Candidates> candidates(
            @RequestParam(required = false) String productId,
            @RequestParam(required = false) Long skuId,
            @RequestParam(required = false) BigDecimal meters,
            @RequestParam(required = false) String assignmentRule) {
        Long tenantId = TenantContext.getTenantId();
        return ApiResponse.success(stockBatchConsumptionService.candidates(
                tenantId, productId, skuId, meters, assignmentRule));
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

    /**
     * **省料度量看板**（L2 批次结构性 + L1 汇总，issue #5159）。
     *
     * <p>聚合面 = <b>（时间桶 × 来源组 × 物料）</b>：分档 `≤0.2m / 0.2~0.5 / 0.5~1 / &gt;1`
     * 按批次**余量**四档统计；来源组 = {@code inbound_orders.source}。
     * 🔴 <b>存量导入（{@code opening}）恒为独立分组</b>：混进「切换后」的分子分母 ⇒
     * 历史包袱把改善吃掉，看板永远看不出变化。</p>
     *
     * GET /api/admin/batch-stock/saving-board?productId=xxx&amp;granularity=month
     *
     * @param granularity `month`（缺省，{@code YYYY-MM}）/ `week`（ISO 周，{@code YYYY-Www}）；
     *                    未知取值 ⇒ <b>400 显式拒绝</b>（不静默回落 month：静默回落会让看板显示的
     *                    口径与请求的不是一回事）
     */
    @RequirePermission("product:list")
    @GetMapping("/saving-board")
    public ApiResponse<SavingMetricViews.Board> savingBoard(
            @RequestParam(required = false) String productId,
            @RequestParam(required = false) String granularity) {
        Long tenantId = TenantContext.getTenantId();
        return ApiResponse.success(
                stockBatchConsumptionService.savingBoard(tenantId, productId, granularity));
    }

    /**
     * **省料趋势**（L3 采购/财务口径，issue #5159）：逐周/月的
     * 入库/采购总米数（**不含存量导入**）、存量导入入库米数（单列）、消耗米数、
     * 产出面积与**单位产出的面料消耗**（米/㎡）。
     *
     * GET /api/admin/batch-stock/saving-trend?granularity=month
     */
    @RequirePermission("product:list")
    @GetMapping("/saving-trend")
    public ApiResponse<SavingMetricViews.Trend> savingTrend(
            @RequestParam(required = false) String granularity) {
        Long tenantId = TenantContext.getTenantId();
        return ApiResponse.success(stockBatchConsumptionService.savingTrend(tenantId, granularity));
    }
}
