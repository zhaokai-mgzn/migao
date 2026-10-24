package com.migao.admin.controller;

import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.ApprovalRequest;
import com.migao.admin.dto.ApprovalView;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.security.SecurityUser;
import com.migao.admin.service.ApprovalService;
import com.migao.admin.config.TenantContext;
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
 * 具名审批（issue #7374，P1-2 段 1）：申请 / 通过 / 驳回 / 撤回 / 列表。
 *
 * <p>授权：读面沿用既有 `finance:view`（审批是财务相关读面），写面 `finance:create` —— **不新造码**
 * （新码会让现网种子岗位全体失效）。「谁能批」的额外约束在服务层：申请人不能批自己的单。</p>
 */
@Slf4j
@RestController
@RequestMapping("/api/admin/approvals")
@RequiredArgsConstructor
// 读面码抬到类级（列表 / 详情继承），写面逐个覆写成 finance:create —— 与 FinanceController 同款。
@RequirePermission("finance:view")
public class ApprovalController {

    private final ApprovalService approvalService;

    /** 提交申请：`POST /api/admin/approvals`。 */
    @PostMapping
    @RequirePermission("finance:create")
    public ApiResponse<ApprovalView> submit(@RequestBody ApprovalRequest request) {
        request.setTenantId(TenantContext.getTenantId());
        log.info("[approval] 提交申请 type={} ref={}", request.getObjectType(), request.getObjectRef());
        return ApiResponse.success(approvalService.submit(request, currentOperator()));
    }

    /** 通过：`POST /api/admin/approvals/{id}/approve`。 */
    @PostMapping("/{id}/approve")
    @RequirePermission("finance:create")
    public ApiResponse<ApprovalView> approve(@PathVariable String id,
                                             @RequestBody(required = false) Map<String, String> body) {
        return ApiResponse.success(approvalService.decide(id, true, noteOf(body), currentOperator()));
    }

    /** 驳回：`POST /api/admin/approvals/{id}/reject`。 */
    @PostMapping("/{id}/reject")
    @RequirePermission("finance:create")
    public ApiResponse<ApprovalView> reject(@PathVariable String id,
                                            @RequestBody(required = false) Map<String, String> body) {
        return ApiResponse.success(approvalService.decide(id, false, noteOf(body), currentOperator()));
    }

    /** 撤回（申请人自己）：`POST /api/admin/approvals/{id}/withdraw`。 */
    @PostMapping("/{id}/withdraw")
    @RequirePermission("finance:create")
    public ApiResponse<ApprovalView> withdraw(@PathVariable String id) {
        return ApiResponse.success(approvalService.withdraw(id, currentOperator()));
    }

    /** 列表：`GET /api/admin/approvals?objectType=&status=`。 */
    @GetMapping
    public ApiResponse<List<ApprovalView>> list(@RequestParam(required = false) String objectType,
                                                @RequestParam(required = false) String status) {
        return ApiResponse.success(approvalService.list(objectType, status));
    }

    /** 详情：`GET /api/admin/approvals/{id}`。 */
    @GetMapping("/{id}")
    public ApiResponse<ApprovalView> view(@PathVariable String id) {
        return ApiResponse.success(approvalService.view(id));
    }

    private static String noteOf(Map<String, String> body) {
        return body == null ? null : body.get("note");
    }

    /** 当前操作人（只从服务端安全上下文取；内部服务令牌 ⇒ 无，服务层据 null 跳过「自批」判定）。 */
    private ApprovalService.Operator currentOperator() {
        var authentication = SecurityContextHolder.getContext().getAuthentication();
        if (authentication != null
                && authentication.getPrincipal() instanceof SecurityUser user) {
            return new ApprovalService.Operator(user.getUserId(), user.getDisplayName());
        }
        return null;
    }
}
