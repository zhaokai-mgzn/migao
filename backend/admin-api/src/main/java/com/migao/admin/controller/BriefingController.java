package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.entity.DailyBriefing;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.security.SecurityUser;
import com.migao.admin.service.AuditLogService;
import com.migao.admin.service.DailyBriefingService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.bind.annotation.*;

import java.util.HashMap;
import java.util.Map;

/**
 * 智能每日经营简报控制器（issue #3468，设计文档 docs/design/daily-briefing-design.md v0.2）
 *
 * 接口：
 * - GET  /api/admin/briefing/today      → 今日简报（未生成返回空态，前端引导）
 * - GET  /api/admin/briefing/config     → 简报配置（开关 + 生成时刻；菜单显隐用）
 * - PUT  /api/admin/briefing/config     → 更新配置（仅 admin，system:manage）
 * - POST /api/admin/briefing/generate   → 手动触发当日生成（仅 admin）
 *
 * 权限：查看 = dashboard:view（与看板同域）；配置读写/手动生成 = system:manage（admin）。
 */
@Slf4j
@RestController
@RequestMapping("/api/admin/briefing")
@RequiredArgsConstructor
public class BriefingController {

    private final DailyBriefingService dailyBriefingService;
    private final AuditLogService auditLogService;

    /**
     * 今日简报。未生成返回 data=null + generated=false，
     * 前端展示「今日简报尚未生成」引导空态（不展示假数据，红线 4）。
     */
    @RequirePermission("dashboard:view")
    @GetMapping("/today")
    public ApiResponse<Map<String, Object>> getToday() {
        Long tenantId = TenantContext.getTenantId();
        DailyBriefing briefing = dailyBriefingService.getTodayBriefing(tenantId);
        Map<String, Object> resp = new HashMap<>();
        resp.put("generated", briefing != null);
        resp.put("verifyStatus", briefing != null ? briefing.getVerifyStatus() : null);
        resp.put("content", briefing != null ? briefing.getContent() : null);
        resp.put("bizDate", briefing != null ? briefing.getBizDate().toString() : null);
        return ApiResponse.success(resp);
    }

    /**
     * 简报配置（开关 + 生成时刻）。前端菜单显隐 = 开关 ∧ 角色权限。
     */
    @RequirePermission("dashboard:view")
    @GetMapping("/config")
    public ApiResponse<Map<String, Object>> getConfig() {
        Long tenantId = TenantContext.getTenantId();
        return ApiResponse.success(dailyBriefingService.getConfig(tenantId));
    }

    /**
     * 更新简报配置（企业开关）。仅 admin（system:manage）。
     * 开启瞬间立即生成当日简报；关闭即熔断（调度跳过 + 生成入口拦截）。
     * 变更写操作日志（审计，设计文档 §8.4；开关变更记谁/何时/开或关）。
     */
    @RequirePermission("system:manage")
    @PutMapping("/config")
    public ApiResponse<Map<String, Object>> updateConfig(@RequestBody Map<String, Object> data) {
        Long tenantId = TenantContext.getTenantId();
        boolean enabled = Boolean.TRUE.equals(data.get("enabled"));
        String generateTime = data.get("generateTime") != null ? String.valueOf(data.get("generateTime")) : null;
        log.info("更新简报配置 tenantId={} enabled={} generateTime={}", tenantId, enabled, generateTime);
        Map<String, Object> config = dailyBriefingService.updateConfig(tenantId, enabled, generateTime);

        // 审计：开关变更（谁、何时、开/关）
        try {
            Authentication auth = SecurityContextHolder.getContext().getAuthentication();
            String userId = null, userName = null;
            if (auth != null && auth.getPrincipal() instanceof SecurityUser su) {
                userId = su.getUserId();
                userName = su.getUsername();
            }
            Map<String, Object> details = new HashMap<>();
            details.put("enabled", config.get("enabled"));
            details.put("generateTime", config.get("generateTime"));
            auditLogService.recordLogAsync(tenantId, userId, userName,
                    "update", "briefing_config", null, String.valueOf(tenantId), "智能每日经营简报配置",
                    details, null, null);
        } catch (Exception e) {
            log.warn("简报配置变更审计失败（不阻断）: {}", e.getMessage());
        }
        return ApiResponse.success(config);
    }

    /**
     * 手动触发当日生成（仅 admin）。生成失败/未开启时返回对应状态。
     */
    @RequirePermission("system:manage")
    @PostMapping("/generate")
    public ApiResponse<Map<String, Object>> generate() {
        Long tenantId = TenantContext.getTenantId();
        DailyBriefing briefing = dailyBriefingService.generateForTenant(tenantId);
        Map<String, Object> resp = new HashMap<>();
        if (briefing == null) {
            resp.put("generated", false);
            resp.put("reason", "BRIEFING_DISABLED");
        } else {
            resp.put("generated", true);
            resp.put("verifyStatus", briefing.getVerifyStatus());
            resp.put("content", briefing.getContent());
        }
        return ApiResponse.success(resp);
    }
}
