package com.migao.admin.controller.agent;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.agent.AgentScheduledTaskRequest;
import com.migao.admin.dto.agent.AgentScheduledTaskViews;
import com.migao.admin.entity.ScheduledTask;
import com.migao.admin.security.SecurityUser;
import com.migao.admin.service.ScheduledTaskService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.bind.annotation.DeleteMapping;
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
 * 定时任务（用户「预约」）端点 —— issue #6486 包 1（包 2 的米宝工具走这里）。
 *
 * <pre>
 * POST   /api/admin/agent/scheduled-tasks        建一条待办（幂等：同 dedupKey 返回既有行）
 * GET    /api/admin/agent/scheduled-tasks?status= 列本租户待办（status 可省）
 * DELETE /api/admin/agent/scheduled-tasks/{id}   取消一条待办（只对 pending 有效）
 * </pre>
 *
 * <h2>权限码：**不加**（自助语义，与通知中心同款）</h2>
 * <p>本能力是「**给自己设提醒**」：收件人 = 建单者自己（`currentUserId()`），
 * 既读不到别人的待办（RLS + 租户拦截器），也写不到别人名下（收件人取自认证上下文，**body 伪造不了**）。
 * 这与 {@code NotificationController} 的自助端点（`GET /notifications` / `PUT /{id}/read` /
 * `DELETE /{id}` 均**无** {@code @RequirePermission}）**逐条同构**；
 * 而它唯一带码的端点是 `POST /notifications`（= **群发**，影响他人）。
 * ⇒ 本类三个端点都不影响他人 ⇒ 不加码；将来若开放「给他人设提醒」，那才是新权限面，须另案裁定。</p>
 */
@Slf4j
@RestController
@RequestMapping("/api/admin/agent/scheduled-tasks")
@RequiredArgsConstructor
public class AgentScheduledTaskController {

    private final ScheduledTaskService scheduledTaskService;

    /** POST —— 建一条待办。 */
    @PostMapping
    public ApiResponse<AgentScheduledTaskViews.Task> create(
            @Valid @RequestBody AgentScheduledTaskRequest request) {
        Long tenantId = TenantContext.getTenantId();
        String userId = currentUserId();
        log.info("[Agent] 创建定时任务: type={}, fireAt={}, tenantId={}",
                request.getTaskType(), request.getFireAt(), tenantId);
        ScheduledTask created = scheduledTaskService.create(tenantId, userId, request);
        return ApiResponse.success(AgentScheduledTaskViews.Task.from(created));
    }

    /** GET —— 列本租户待办。 */
    @GetMapping
    public ApiResponse<List<AgentScheduledTaskViews.Task>> list(
            @RequestParam(required = false) String status) {
        List<AgentScheduledTaskViews.Task> tasks = scheduledTaskService
                .list(TenantContext.getTenantId(), status)
                .stream()
                .map(AgentScheduledTaskViews.Task::from)
                .toList();
        return ApiResponse.success(tasks);
    }

    /** DELETE —— 取消一条待办（只对 {@code pending} 有效；已投递的不可撤回）。 */
    @DeleteMapping("/{id}")
    public ApiResponse<Map<String, Object>> cancel(@PathVariable String id) {
        boolean cancelled = scheduledTaskService.cancel(TenantContext.getTenantId(), id);
        return ApiResponse.success(Map.of("id", id, "cancelled", cancelled));
    }

    /** 身份一律取自认证上下文（{@code X-User-Id} 经 ServiceTokenFilter 透传），**body 伪造不了**。 */
    private String currentUserId() {
        Authentication authentication = SecurityContextHolder.getContext().getAuthentication();
        if (authentication != null && authentication.getPrincipal() instanceof SecurityUser securityUser) {
            return securityUser.getUserId();
        }
        return null;
    }
}
