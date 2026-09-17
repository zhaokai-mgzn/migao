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
 * Agent 生产进度/计件（米宝工具消费，issue #3995，M4-G-2）
 *
 * ⚠️ 冻结契约（并行包消费）：路径/参数/返回字段不可改。
 *   GET /api/admin/agent/production/progress?order_no=xxx
 *     → {order_no, status, status_text, progress_percent, current_operation,
 *        pending_operations, total_operations, done_operations, expected_delivery_date}
 *   GET /api/admin/agent/production/piecework?worker_name=xxx&period=YYYY-MM
 *     → {worker_name, period, total, details:[{operation, qty, amount}]}
 * 只透出精简字段（不含内部单价/系数/租户字段）。
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
}
