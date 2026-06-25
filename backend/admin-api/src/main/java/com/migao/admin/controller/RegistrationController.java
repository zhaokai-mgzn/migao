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
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
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
     * 需要先通过短信验证码验证
     */
    @PostMapping("/api/auth/register")
    public ApiResponse<RegistrationResponse> submitRegistration(
            @Valid @RequestBody RegistrationRequest request) {
        log.info("收到企业入驻申请: companyName={}, phone={}", request.getCompanyName(), request.getPhone());
        RegistrationResponse response = registrationService.submitApplication(request);
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
