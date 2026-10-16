package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.security.SecurityUser;
import com.migao.admin.service.QualityCheckService;
import com.migao.admin.time.BusinessClock;
import lombok.RequiredArgsConstructor;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

/**
 * 质检记录（**成品帘级**）Controller —— issue #5652 的第一刀。
 *
 * <p>端点：{@code POST /api/admin/quality-inspections}（录入判定）·
 * {@code GET /api/admin/quality-inspections}（读记录）。</p>
 *
 * <p>🔴 <b>口径（用户 2026-10-16 逐字裁定）</b>：一条记录 = <b>一件成品帘</b>
 * （{@code order_item_id} 级，「是按成品帘来检查的」）；录入者 = <b>独立质检员</b>
 * （「B 独立质检员」）。</p>
 *
 * <p>🔴 <b>权限（判据 2 的承载体）</b>：两个端点都声明
 * {@code @RequirePermission("production:inspect")} —— 该码<b>只</b>授给
 * 独立质检员岗位（{@code inspector}，见
 * {@code backend/admin-api/src/main/java/com/migao/admin/service/RegistrationService.java} 的岗位种子
 * 与 {@code rbac/manifest.json} 的 {@code roles.seed}），外加运行时恒 {@code ["*"]} 的 {@code admin}。
 * 「无该角色 ⇒ 必须被拒」是一条<b>真判据</b>（端点注解 + 岗位矩阵），<b>不是</b>前端不显示按钮
 * —— 判据见 {@code QualityCheckPermissionTest}。</p>
 *
 * <p>🔴 <b>本类不碰报工</b>：不读写 {@code production_work_logs}、不重算任何数量、不参与计件
 * —— 报工 = 数量事实、质检 = 成品帘判定，两套口径并存（本单红线）。</p>
 *
 * <p>检验人身份只由服务端从 {@code SecurityContext} 解（body 里的同名字段一律忽略）——
 * 与报工身份同款纪律（前端可被改，责任凭证不能信前端）。</p>
 */
@RestController
@RequestMapping("/api/admin/quality-inspections")
@RequiredArgsConstructor
public class QualityCheckController {

    private final QualityCheckService qualityInspectionService;
    private final BusinessClock businessClock;

    /**
     * 录入一条质检记录（成品帘级）。
     *
     * <p>body = {@code {order_item_id, result, reason?}}；{@code result ∈ pass|rework|scrap}；
     * 判定 ≠ 合格时 {@code reason} 必填（缺 ⇒ 422 具名报错，不静默存）。</p>
     */
    @PostMapping
    @RequirePermission("production:inspect")
    public ApiResponse<Map<String, Object>> create(@RequestBody(required = false) Map<String, Object> body) {
        Long tenantId = TenantContext.getTenantId();
        SecurityUser me = currentUser();
        Map<String, Object> record = qualityInspectionService.create(
                tenantId,
                str(body, "order_item_id"),
                str(body, "result"),
                str(body, "reason"),
                me.getUserId(),
                me.getDisplayName(),
                // 🔴 业务时钟单点（issue #3802 / BusinessClockSourceGuardTest）：不在本类写时区字面量、不调无参 now()
                businessClock.nowOffset());
        return ApiResponse.success(record);
    }

    /** 质检记录读面（按加工单 / 成品帘过滤，时间倒序；同件可多条 = 返工后重检）。 */
    @GetMapping
    @RequirePermission("production:inspect")
    public ApiResponse<List<Map<String, Object>>> list(
            @RequestParam(name = "processing_order_id", required = false) String processingOrderId,
            @RequestParam(name = "order_item_id", required = false) String orderItemId) {
        return ApiResponse.success(qualityInspectionService.list(
                TenantContext.getTenantId(), processingOrderId, orderItemId));
    }

    /** body 取值（缺键 ⇒ null；**不**从 body 取租户 / 检验人身份）。 */
    private String str(Map<String, Object> body, String key) {
        if (body == null) {
            return null;
        }
        Object v = body.get(key);
        return v == null ? null : String.valueOf(v);
    }

    /** 当前认证用户（检验人的**唯一**来源；未认证 ⇒ 401 fail-closed）。 */
    private SecurityUser currentUser() {
        Authentication auth = SecurityContextHolder.getContext().getAuthentication();
        if (auth == null || !(auth.getPrincipal() instanceof SecurityUser securityUser)) {
            throw BusinessException.authFailed("用户未认证");
        }
        return securityUser;
    }
}
