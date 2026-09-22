package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.ProductionPoolRequest;
import com.migao.admin.dto.ProductionPoolViews;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.service.ProcessingOrderService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.math.BigDecimal;
import java.util.List;

/**
 * 待派池 + 成批派单（issue #5169 = 阶段 2b-1）。
 *
 * <p>三个端点对应本单的三件事：① 池子视图（单号 / 物料 / 需求米数 / 等待时长）；
 * ② 成批预览（预计领料 vs 逐单公式米数 = 预计节省）；③ **人工一次性触发**的成批派单
 * （跨订单成组排料）。</p>
 *
 * <p><b>权限</b>：读面复用 {@code processing:view}、写面复用 {@code processing:update}
 * —— 与 {@link ProcessingOrderController} 同口径，不新造权限点（新权限点需要配角色/种子数据，
 * 本单不含权限模型变更；同 {@code StockBatchController} 复用 {@code product:list} 的先例）。</p>
 *
 * <p>🔴 <b>池化开关缺省关</b>：{@code pooled} 不传（或传 {@code false}）时
 * {@code /dispatch} 的行为 = 逐单派 = 今天的形态（判据 1）。池**看得见**（{@code GET}）不等于
 * **已开启**（{@code pooled=true}）—— 记录期基线要的是「不启用就不变」。</p>
 */
@Slf4j
@RestController
@RequestMapping("/api/admin/production/pool")
@RequiredArgsConstructor
public class ProductionPoolController {

    private final ProcessingOrderService processingOrderService;

    /**
     * 待派池视图（权限 processing:view）。
     *
     * GET /api/admin/production/pool?maxWaitHours=24
     *
     * @param maxWaitHours 池内滞留上限（小时）。缺省 = {@code DEFAULT_POOL_MAX_WAIT_HOURS}；
     *                     非正数 ⇒ 显式拒绝（不静默回落缺省值 —— 静默回落会让看板以为在按
     *                     自己设的阈值告警）
     */
    @RequirePermission("processing:view")
    @GetMapping
    public ApiResponse<ProductionPoolViews.Pool> pool(
            @RequestParam(required = false) BigDecimal maxWaitHours) {
        Long tenantId = TenantContext.getTenantId();
        return ApiResponse.success(processingOrderService.pool(tenantId, maxWaitHours));
    }

    /**
     * 成批预览（权限 processing:view，**只读**）：池内选中的若干单**一起**求解后的应领米数
     * 与预计节省（判据 4：这个数必须与实际落账的 {@code Σ saved_meters} 逐值相等）。
     *
     * POST /api/admin/production/pool/preview
     */
    @RequirePermission("processing:view")
    @PostMapping("/preview")
    public ApiResponse<ProductionPoolViews.Preview> preview(@RequestBody ProductionPoolRequest request) {
        Long tenantId = TenantContext.getTenantId();
        return ApiResponse.success(processingOrderService.preview(tenantId, request.getOrderIds(),
                request.getBatches(), request.getAssignmentRule()));
    }

    /**
     * 成批派单（权限 processing:update）—— **一次动作批量生成多张加工单**。
     *
     * <p>🔴 「一单一加工单」的既有约束**不变**（{@code uk_processing_orders_active} 保持）：
     * 本端点产出的是 N 张**各自独立**的加工单，池化只改「排料与批次分配在池级求解」。</p>
     *
     * POST /api/admin/production/pool/dispatch   body 带 {@code pooled: true} 才跨订单成组
     */
    @RequirePermission("processing:update")
    @PostMapping("/dispatch")
    public ApiResponse<List<ProcessingOrderService.GenerateResult>> dispatch(
            @RequestBody ProductionPoolRequest request) {
        Long tenantId = TenantContext.getTenantId();
        return ApiResponse.success(processingOrderService.generate(request.getOrderIds(),
                request.getBatches(), tenantId, null, request.getAssignmentRule(), request.getPooled()));
    }
}
