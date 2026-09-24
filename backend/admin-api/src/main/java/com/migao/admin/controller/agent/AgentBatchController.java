package com.migao.admin.controller.agent;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.agent.AgentBatchCreateRequest;
import com.migao.admin.dto.agent.AgentBatchViews;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.security.SecurityUser;
import com.migao.admin.service.AgentBatchService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 批量更新的批次资源（issue #5314 服务端包；冻结契约逐字见 issue #5314 评论 2026-09-24）。
 *
 * <pre>
 * POST /api/admin/agent/batches                  创建批次（= 预演）
 *                                                req  {batchType, items:[{resourceId, field, oldValue, newValue}]}
 *                                                resp {batchId, itemCount, status:"preview"}
 * POST /api/admin/agent/batches/{batchId}/execute 执行 → {batchId, status, results:[{resourceId, success, error?}]}
 * POST /api/admin/agent/batches/{batchId}/revert  撤销 → {batchId, status, results:[...]}
 * GET  /api/admin/agent/batches/{batchId}         查询进度 / 结果 / 可撤销性
 * </pre>
 *
 * <h2>权限码：与逐条写**同码**，不新开权限面</h2>
 * <p>类级 {@code @RequirePermission("product:create")} —— 与 {@code AgentProductController} 的逐条写
 * 端点（改价 / 上下架 / 改库存）**逐字同码**：批量不是新权限面，是同一件事的多条形态，
 * 能改一条的人才能改一批。⚠️ 契约文本里写的 {@code product:update} 在本仓库**不存在**
 * （全仓零命中）⇒ 照字面落码会让端点在所有角色上永久 403；此处按契约的**意图**
 * （「与逐条写同码」）落码，差异已在 PR body 登记。</p>
 *
 * <p>身份（tenant_id / created_by）一律取自认证上下文
 * （{@code X-Tenant-Id} / {@code X-User-Id} 经 ServiceTokenFilter 透传），**body 伪造不了**。</p>
 */
@Slf4j
@RestController
@RequestMapping("/api/admin/agent/batches")
@RequiredArgsConstructor
@RequirePermission("product:create")
public class AgentBatchController {

    private final AgentBatchService batchService;

    /** POST /api/admin/agent/batches —— 创建批次（= 预演，逐条采集 old_value）。 */
    @PostMapping
    public ApiResponse<AgentBatchViews.Batch> create(@Valid @RequestBody AgentBatchCreateRequest request) {
        Long tenantId = TenantContext.getTenantId();
        String userId = currentUserId();
        log.info("[Agent] 创建批量更新批次: type={}, items={}, tenantId={}",
                request.getBatchType(), request.getItems().size(), tenantId);
        return ApiResponse.success(batchService.create(tenantId, userId, request));
    }

    /** POST /api/admin/agent/batches/{batchId}/execute —— 执行（逐条落 status / error）。 */
    @PostMapping("/{batchId}/execute")
    public ApiResponse<AgentBatchViews.Batch> execute(@PathVariable String batchId) {
        return ApiResponse.success(batchService.execute(TenantContext.getTenantId(), batchId));
    }

    /** POST /api/admin/agent/batches/{batchId}/revert —— 撤销（逐条还原 old_value）。 */
    @PostMapping("/{batchId}/revert")
    public ApiResponse<AgentBatchViews.Batch> revert(@PathVariable String batchId) {
        return ApiResponse.success(batchService.revert(TenantContext.getTenantId(), batchId));
    }

    /** GET /api/admin/agent/batches/{batchId} —— 查询进度 / 结果 / 可撤销性。 */
    @GetMapping("/{batchId}")
    public ApiResponse<AgentBatchViews.Batch> get(@PathVariable String batchId) {
        return ApiResponse.success(batchService.get(TenantContext.getTenantId(), batchId));
    }

    /**
     * 发起人（{@code X-User-Id} 透传后由 ServiceTokenFilter 写入 SecurityUser）。
     *
     * <p>为什么不留空：批次是「谁按下了这一键」的取证面（批量 = 盲签的主要来源）。</p>
     */
    private String currentUserId() {
        Authentication authentication = SecurityContextHolder.getContext().getAuthentication();
        if (authentication != null && authentication.getPrincipal() instanceof SecurityUser securityUser) {
            return securityUser.getUserId();
        }
        return null;
    }
}