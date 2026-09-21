package com.migao.admin.controller.agent;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.service.ProductionService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/**
 * Agent 生产进度/计件/过程明细（米宝工具消费，issue #3995 / #4201，M4-G-2）
 *
 * ⚠️ 冻结契约（并行包消费）：路径/参数/返回字段不可改。
 *   GET /api/admin/agent/production/progress?order_no=xxx
 *     → {order_no, status, status_text, progress_percent, current_operation,
 *        pending_operations, total_operations, done_operations, expected_delivery_date}
 *   GET /api/admin/agent/production/piecework?worker_name=xxx&period=YYYY-MM
 *     → {worker_name, period, total, details:[{operation, qty, amount}]}
 *   GET /api/admin/agent/production/worklog?order_no=xxx
 *     → {order_no, processing_order_no, processing_status,
 *        operations:[{position, operation_name, logical_name, group_name, seq, status,
 *                     required_qty, qualified_qty, rework_qty, scrap_qty, is_must_finish,
 *                     workers, last_work_date}],
 *        work_logs:[{operation_name, logical_name, position, worker_name, qty, qualified_qty,
 *                    work_type, work_date}],
 *        totals:{qualified_qty, rework_qty, scrap_qty, piecework_amount}}
 * 只透出精简字段（不含内部单价/系数/租户字段）。
 * ⚠️ `operations[].is_must_finish` 是**历史载体键**，自 #4961 起**恒 false**（「必完工序」已退场；
 * 键保留只为不破既有消费者的键集）—— 真实完工口径 = 全部活跃工序实例完成，看 `progress.done == total`。
 * worklog 的量/额口径：合格 = work_type=normal 的合格数；返工/报废各取**报工数量**；
 * 计件金额走与 /piecework **同一份**聚合（`ProductionService.aggregate`）⇒ 两处恒等。
 * work_logs 为**倒序**（最近在前），与工人端「操作记录」同一约定。
 */
@Slf4j
@RestController
@RequestMapping("/api/admin/agent/production")
@RequiredArgsConstructor
@RequirePermission("order:list")
public class AgentProductionController {

    private final ProductionService productionService;

    /** 订单生产进度（按订单号，租户隔离） */
    @GetMapping("/progress")
    public ApiResponse<Map<String, Object>> progress(
            @RequestParam(value = "order_no", required = false) String orderNo) {
        return ApiResponse.success(productionService.progress(orderNo, TenantContext.getTenantId()));
    }

    /** 工人计件（按人 + 期间 YYYY-MM） */
    @GetMapping("/piecework")
    public ApiResponse<Map<String, Object>> piecework(
            @RequestParam(value = "worker_name", required = false) String workerName,
            @RequestParam(value = "period", required = false) String period) {
        return ApiResponse.success(
                productionService.workerPiecework(workerName, period, TenantContext.getTenantId()));
    }

    /**
     * 加工单过程明细（issue #4201）：工序实例（做到哪一步）+ 报工明细（谁报的）+ 数量/计件合计。
     *
     * <p>订单解析与 {@code /progress} 同口径（{@code resolveOrder} 四形态：内部 order_id /
     * 订单号 / 加工单 qr_token / 加工单号），租户隔离同口径。**只读**。</p>
     */
    @GetMapping("/worklog")
    public ApiResponse<Map<String, Object>> worklog(
            @RequestParam(value = "order_no", required = false) String orderNo) {
        return ApiResponse.success(productionService.worklog(orderNo, TenantContext.getTenantId()));
    }
}
