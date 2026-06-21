package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.PageResponse;
import com.migao.admin.entity.AuditLog;
import com.migao.admin.entity.Tenant;
import com.migao.admin.entity.TenantAiConfig;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.TenantAiConfigMapper;
import com.migao.admin.mapper.TenantMapper;
import com.migao.admin.mapper.UserMapper;
import com.migao.admin.security.SecurityUser;
import com.migao.admin.service.AuditLogService;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.Data;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.web.bind.annotation.*;

import java.util.HashMap;
import java.util.Map;

/**
 * 系统设置控制器
 * 提供系统设置、AI 配置、修改密码、登录日志等接口
 *
 * 前端对齐：settingsApi (frontend/admin-web/src/lib/api.ts)
 * - GET  /api/admin/settings              → getSettings
 * - PUT  /api/admin/settings              → updateSettings
 * - GET  /api/admin/tenant/ai-config      → getAiConfig
 * - PUT  /api/admin/tenant/ai-config      → updateAiConfig
 * - PUT  /api/admin/settings/password     → changePassword
 * - GET  /api/admin/settings/login-logs   → getLoginLogs
 */
@Slf4j
@RestController
@RequiredArgsConstructor
public class SettingsController {

    private final TenantMapper tenantMapper;
    private final TenantAiConfigMapper tenantAiConfigMapper;
    private final AuditLogService auditLogService;
    private final UserMapper userMapper;
    private final PasswordEncoder passwordEncoder;

    // ==================== 基本设置 ====================

    /**
     * 获取系统设置（返回当前租户信息）
     *
     * GET /api/admin/settings
     */
    @GetMapping("/api/admin/settings")
    public ApiResponse<Map<String, Object>> getSettings() {
        Long tenantId = TenantContext.getTenantId();
        log.info("获取系统设置: tenantId={}", tenantId);

        Tenant tenant = tenantMapper.selectById(tenantId);
        if (tenant == null) {
            throw BusinessException.notFound("租户");
        }

        Map<String, Object> settings = new HashMap<>();
        settings.put("tenantId", tenant.getId());
        settings.put("name", tenant.getName());
        settings.put("companyName", tenant.getName());  // 前端用 companyName
        settings.put("code", tenant.getCode());
        settings.put("industry", tenant.getIndustry());
        settings.put("status", tenant.getStatus());

        return ApiResponse.success(settings);
    }

    /**
     * 更新系统设置
     *
     * PUT /api/admin/settings
     */
    @PutMapping("/api/admin/settings")
    public ApiResponse<Map<String, Object>> updateSettings(@RequestBody Map<String, Object> data) {
        Long tenantId = TenantContext.getTenantId();
        log.info("更新系统设置: tenantId={}", tenantId);

        Tenant tenant = tenantMapper.selectById(tenantId);
        if (tenant == null) {
            throw BusinessException.notFound("租户");
        }

        // 兼容前端 companyName / name 两种字段名
        if (data.containsKey("companyName")) {
            tenant.setName((String) data.get("companyName"));
        } else if (data.containsKey("name")) {
            tenant.setName((String) data.get("name"));
        }
        if (data.containsKey("industry")) {
            tenant.setIndustry((String) data.get("industry"));
        }

        tenantMapper.updateById(tenant);

        // 返回更新后的设置
        Map<String, Object> settings = new HashMap<>();
        settings.put("tenantId", tenant.getId());
        settings.put("name", tenant.getName());
        settings.put("companyName", tenant.getName());
        settings.put("code", tenant.getCode());
        settings.put("industry", tenant.getIndustry());
        settings.put("status", tenant.getStatus());

        return ApiResponse.success(settings);
    }

    // ==================== AI 配置 ====================

    /**
     * 获取 AI 配置
     *
     * GET /api/admin/tenant/ai-config
     */
    @GetMapping("/api/admin/tenant/ai-config")
    public ApiResponse<TenantAiConfig> getAiConfig() {
        Long tenantId = TenantContext.getTenantId();
        log.info("获取AI配置: tenantId={}", tenantId);

        LambdaQueryWrapper<TenantAiConfig> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(TenantAiConfig::getTenantId, tenantId).last("LIMIT 1");
        TenantAiConfig config = tenantAiConfigMapper.selectOne(wrapper);

        if (config == null) {
            // 返回默认空配置
            config = TenantAiConfig.builder()
                    .tenantId(tenantId)
                    .build();
        }

        return ApiResponse.success(config);
    }

    /**
     * 更新 AI 配置
     *
     * PUT /api/admin/tenant/ai-config
     */
    @PutMapping("/api/admin/tenant/ai-config")
    public ApiResponse<TenantAiConfig> updateAiConfig(@RequestBody TenantAiConfig config) {
        Long tenantId = TenantContext.getTenantId();
        log.info("更新AI配置: tenantId={}", tenantId);

        LambdaQueryWrapper<TenantAiConfig> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(TenantAiConfig::getTenantId, tenantId).last("LIMIT 1");
        TenantAiConfig existing = tenantAiConfigMapper.selectOne(wrapper);

        if (existing == null) {
            // 创建新配置
            config.setTenantId(tenantId);
            config.setId(null);
            tenantAiConfigMapper.insert(config);
            return ApiResponse.success(config);
        }

        // 更新已有配置
        if (config.getBotName() != null) {
            existing.setBotName(config.getBotName());
        }
        if (config.getGreetingTemplate() != null) {
            existing.setGreetingTemplate(config.getGreetingTemplate());
        }
        if (config.getBusinessHours() != null) {
            existing.setBusinessHours(config.getBusinessHours());
        }
        if (config.getTimezone() != null) {
            existing.setTimezone(config.getTimezone());
        }
        if (config.getAutoHandoffKeywords() != null) {
            existing.setAutoHandoffKeywords(config.getAutoHandoffKeywords());
        }
        if (config.getEmotionHandoff() != null) {
            existing.setEmotionHandoff(config.getEmotionHandoff());
        }
        if (config.getAiFallbackHandoff() != null) {
            existing.setAiFallbackHandoff(config.getAiFallbackHandoff());
        }
        if (config.getAiFallbackThreshold() != null) {
            existing.setAiFallbackThreshold(config.getAiFallbackThreshold());
        }
        if (config.getAfterHoursMode() != null) {
            existing.setAfterHoursMode(config.getAfterHoursMode());
        }
        if (config.getAfterHoursMessage() != null) {
            existing.setAfterHoursMessage(config.getAfterHoursMessage());
        }
        if (config.getRecommendStrategy() != null) {
            existing.setRecommendStrategy(config.getRecommendStrategy());
        }
        if (config.getRecommendCount() != null) {
            existing.setRecommendCount(config.getRecommendCount());
        }
        if (config.getRecommendTrigger() != null) {
            existing.setRecommendTrigger(config.getRecommendTrigger());
        }
        if (config.getQuickReplies() != null) {
            existing.setQuickReplies(config.getQuickReplies());
        }

        tenantAiConfigMapper.updateById(existing);
        return ApiResponse.success(existing);
    }

    // ==================== 修改密码 ====================

    /**
     * 修改当前用户密码
     *
     * PUT /api/admin/settings/password
     */
    @PutMapping("/api/admin/settings/password")
    public ApiResponse<Void> changePassword(@RequestBody ChangePasswordRequest request) {
        Authentication authentication = SecurityContextHolder.getContext().getAuthentication();
        if (authentication == null || !(authentication.getPrincipal() instanceof SecurityUser securityUser)) {
            throw BusinessException.authFailed("用户未认证");
        }

        String userId = securityUser.getUserId();
        log.info("修改密码: userId={}", userId);

        com.migao.admin.entity.User user = userMapper.selectById(userId);
        if (user == null) {
            throw BusinessException.notFound("用户");
        }

        // 验证旧密码
        if (!passwordEncoder.matches(request.getOldPassword(), user.getPasswordHash())) {
            throw BusinessException.validationError("原密码不正确");
        }

        // 更新密码
        user.setPasswordHash(passwordEncoder.encode(request.getNewPassword()));
        userMapper.updateById(user);

        return ApiResponse.success();
    }

    // ==================== 登录日志 ====================

    /**
     * 查询登录日志
     *
     * GET /api/admin/settings/login-logs?page=1&size=10
     */
    @GetMapping("/api/admin/settings/login-logs")
    public ApiResponse<PageResponse<AuditLog>> getLoginLogs(
            @RequestParam(defaultValue = "1") long page,
            @RequestParam(defaultValue = "10") long size) {
        Long tenantId = TenantContext.getTenantId();
        log.info("查询登录日志: tenantId={}, page={}, size={}", tenantId, page, size);

        // 查询 action=login 的审计日志
        PageResponse<AuditLog> result = auditLogService.getAuditLogPage(
                page, size, "login", null, null, null, null, tenantId);
        return ApiResponse.success(result);
    }

    // ==================== 请求 DTO ====================

    @Data
    public static class ChangePasswordRequest {
        private String oldPassword;
        private String newPassword;
    }
}
