package com.migao.admin.controller;

import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.PageResponse;
import com.migao.admin.dto.RegistrationRequest;
import com.migao.admin.dto.RegistrationResponse;
import com.migao.admin.dto.RegistrationReviewRequest;
import com.migao.admin.entity.TenantApplication;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.security.SecurityUser;
import com.migao.admin.service.RegistrationService;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.util.StringUtils;
import org.springframework.web.bind.annotation.*;

/**
 * 企业入驻控制器
 * 包含公开的注册接口和超管的审批接口
 */
@Slf4j
@RestController
@RequiredArgsConstructor
public class RegistrationController {

    private final RegistrationService registrationService;

    // ======================== 公开接口（无需认证） ========================

    /**
     * 提交企业入驻申请
     *
     * POST /api/auth/register
     *
     * 需要先通过短信验证码验证；提交后由 AI 自动甄别：
     * - 合法合规无敏感信息 → 自动通过（status=approved，自动创建租户+管理员）
     * - 含法律风险/敏感内容 → 自动驳回（status=rejected，返回驳回原因）
     *
     * 安全防护：蜜罐字段、手机号/企业名查重、频率限制、驳回冷却
     */
    @PostMapping("/api/auth/register")
    public ApiResponse<RegistrationResponse> submitRegistration(
            @Valid @RequestBody RegistrationRequest request,
            HttpServletRequest httpRequest) {
        String clientIp = resolveClientIp(httpRequest);
        log.info("收到企业入驻申请: companyName={}, phone={}, ip={}",
                request.getCompanyName(), request.getPhone(), clientIp);
        RegistrationResponse response = registrationService.submitApplication(request, clientIp);
        return ApiResponse.success(response);
    }

    // ======================== 超管接口（需要认证 + 超管权限） ========================

    /**
     * 查询入驻申请列表
     *
     * GET /api/super-admin/registrations?status=pending&page=1&size=10
     */
    @GetMapping("/api/super-admin/registrations")
    public ApiResponse<PageResponse<TenantApplication>> getRegistrations(
            @RequestParam(required = false) String status,
            @RequestParam(defaultValue = "1") int page,
            @RequestParam(defaultValue = "10") int size) {
        checkSuperAdminPermission();
        PageResponse<TenantApplication> result = registrationService.getApplications(status, page, size);
        return ApiResponse.success(result);
    }

    /**
     * 查看入驻申请详情
     *
     * GET /api/super-admin/registrations/{id}
     */
    @GetMapping("/api/super-admin/registrations/{id}")
    public ApiResponse<TenantApplication> getRegistrationDetail(@PathVariable Long id) {
        checkSuperAdminPermission();
        TenantApplication application = registrationService.getApplicationDetail(id);
        return ApiResponse.success(application);
    }

    /**
     * 审批通过
     *
     * PUT /api/super-admin/registrations/{id}/approve
     */
    @PutMapping("/api/super-admin/registrations/{id}/approve")
    public ApiResponse<Void> approveRegistration(@PathVariable Long id) {
        SecurityUser currentUser = checkSuperAdminPermission();
        registrationService.approveApplication(id, currentUser.getUserId());
        return ApiResponse.success();
    }

    /**
     * 驳回申请
     *
     * PUT /api/super-admin/registrations/{id}/reject
     */
    @PutMapping("/api/super-admin/registrations/{id}/reject")
    public ApiResponse<Void> rejectRegistration(
            @PathVariable Long id,
            @RequestBody RegistrationReviewRequest request) {
        SecurityUser currentUser = checkSuperAdminPermission();
        registrationService.rejectApplication(id, currentUser.getUserId(), request.getRejectReason());
        return ApiResponse.success();
    }

    // ======================== 内部辅助方法 ========================

    /**
     * 解析客户端 IP（防伪造，Issue #2661）：
     * 1. 优先 X-Real-IP —— nginx 用 `proxy_set_header X-Real-IP $remote_addr` 覆盖，
     *    客户端传入值会被 nginx 替换为真实 TCP 对端地址，不可伪造
     * 2. 回退 X-Forwarded-For 首位（兼容未设 X-Real-IP 的部署形态；
     *    nginx 现也已将该头覆盖为 $remote_addr，非 $proxy_add_x_forwarded_for）
     * 3. 回退 remoteAddr
     */
    private String resolveClientIp(HttpServletRequest request) {
        String realIp = request.getHeader("X-Real-IP");
        if (StringUtils.hasText(realIp)) {
            return realIp.trim();
        }
        String forwarded = request.getHeader("X-Forwarded-For");
        if (StringUtils.hasText(forwarded)) {
            String first = forwarded.split(",")[0].trim();
            if (StringUtils.hasText(first)) {
                return first;
            }
        }
        return request.getRemoteAddr();
    }

    /**
     * 校验当前用户是否为超级管理员
     *
     * @return 当前用户信息
     */
    private SecurityUser checkSuperAdminPermission() {
        Authentication authentication = SecurityContextHolder.getContext().getAuthentication();
        if (authentication == null || !authentication.isAuthenticated()) {
            throw BusinessException.authFailed("用户未认证");
        }

        Object principal = authentication.getPrincipal();
        if (!(principal instanceof SecurityUser securityUser)) {
            throw BusinessException.authFailed("无法获取用户信息");
        }

        // 检查是否拥有管理员角色
        if (!securityUser.getRoles().contains("super_admin")) {
            throw BusinessException.permissionDenied();
        }

        return securityUser;
    }
}
