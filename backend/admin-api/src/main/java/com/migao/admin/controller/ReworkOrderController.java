package com.migao.admin.controller;

import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.ReworkOrderView;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.security.SecurityUser;
import com.migao.admin.service.ApprovalService;
import com.migao.admin.service.ReworkOrderService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

/**
 * 返工单（issue #7377，P1-5 段 2）：售后 → 返工 → 完成回写。
 *
 * <p>授权零 delta：读面 `after-sales:view`、写面 `after-sales:create`（与售后工单同域）。</p>
 */
@Slf4j
@RestController
@RequestMapping("/api/admin/rework-orders")
@RequiredArgsConstructor
public class ReworkOrderController {

    private final ReworkOrderService reworkOrderService;

    /** 列表：`GET /api/admin/rework-orders?afterSalesTicketId=`。 */
    @GetMapping
    @RequirePermission("after_sales:view")
    public ApiResponse<List<ReworkOrderView>> list(
            @RequestParam(required = false) String afterSalesTicketId) {
        return ApiResponse.success(reworkOrderService.list(afterSalesTicketId));
    }

    /** 详情：`GET /api/admin/rework-orders/{id}`。 */
    @GetMapping("/{id}")
    @RequirePermission("after_sales:view")
    public ApiResponse<ReworkOrderView> detail(@PathVariable String id) {
        return ApiResponse.success(reworkOrderService.detail(id));
    }

    /**
     * 从售后单开返工单：`POST /api/admin/rework-orders?afterSalesTicketId=&reason=&processingOrderId=`。
     *
     * <p>🔴 已闭环/已驳回的售后单**拒开**；同一售后单已有未完结返工单也拒。</p>
     */
    @PostMapping
    @RequirePermission("order:refund")
    public ApiResponse<ReworkOrderView> create(@RequestParam String afterSalesTicketId,
                                               @RequestParam(required = false) String reason,
                                               @RequestParam(required = false) String processingOrderId) {
        log.info("[rework] 开单请求 ticket={}", afterSalesTicketId);
        return ApiResponse.success(reworkOrderService.create(afterSalesTicketId, reason,
                processingOrderId, currentOperator()));
    }

    /** 开工：`POST /api/admin/rework-orders/{id}/start`。 */
    @PostMapping("/{id}/start")
    @RequirePermission("order:refund")
    public ApiResponse<ReworkOrderView> start(@PathVariable String id) {
        return ApiResponse.success(reworkOrderService.start(id));
    }

    /**
     * 完成：`POST /api/admin/rework-orders/{id}/complete`（可选备注）。
     *
     * <p>完成时**回写售后状态**：仅当售后单当前是 `processing` 才推进到 `resolved`。</p>
     */
    @PostMapping("/{id}/complete")
    @RequirePermission("order:refund")
    public ApiResponse<ReworkOrderView> complete(@PathVariable String id,
                                                 @RequestBody(required = false) Map<String, Object> body) {
        return ApiResponse.success(reworkOrderService.complete(id));
    }

    /** 取消：`POST /api/admin/rework-orders/{id}/cancel`（取消不回退售后状态）。 */
    @PostMapping("/{id}/cancel")
    @RequirePermission("order:refund")
    public ApiResponse<ReworkOrderView> cancel(@PathVariable String id) {
        return ApiResponse.success(reworkOrderService.cancel(id));
    }

    private ApprovalService.Operator currentOperator() {
        var authentication = SecurityContextHolder.getContext().getAuthentication();
        if (authentication != null
                && authentication.getPrincipal() instanceof SecurityUser user) {
            return new ApprovalService.Operator(user.getUserId(), user.getDisplayName());
        }
        return null;
    }
}
