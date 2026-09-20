package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.config.TenantDomainResolver;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.WorkerLoginRequest;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.worker.WorkerSessionService;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.util.StringUtils;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/**
 * 工人认证控制器（issue #4733）：`/api/worker/**` —— **与商家账号彻底分离**。
 *
 * <p>为什么必须是新路径而不是复用 {@code /api/admin/**}：报工端点今天挂在
 * {@code /api/admin/production/**} 下（类级 {@code @RequirePermission("order:list")}），
 * 而 {@code /api/admin/**} 的门禁把「其余角色视为商户员工」放行 ⇒ 工人若持
 * {@code role=worker} 会**进入管理后台**（设计 §2.4 实测冲突 P2）。本单的修法 =
 * 新路径 {@code /api/worker/**}（不匹配 {@code /api/admin/**} ⇒ 落
 * {@code anyRequest().authenticated()}）+ 在 {@code adminApiAuthorizationManager} 的
 * **拒绝集合追加 {@code worker}**（既有三个分支逻辑一字不改）。</p>
 *
 * <p>工人 session **不是** JWT：载体是不可猜的 {@code worker_sessions.id}，随
 * {@code X-Worker-Session-Id} 回传。这样商家 JWT 与工人身份在传输层就是两回事，
 * 不存在「工人 token 被当成商家 token 用」的形态。</p>
 */
@Slf4j
@RestController
@RequestMapping("/api/worker")
@RequiredArgsConstructor
public class WorkerAuthController {

    private final WorkerSessionService workerSessionService;
    private final TenantDomainResolver tenantDomainResolver;

    /**
     * 工号 + PIN 登录 ⇒ 签发工人 session。
     *
     * <p>租户判定与小程序登录同口径：域名/网关头（{@code X-Tenant-Id}）为**权威**，
     * body {@code tenantId} 仅兼容期兜底；两者皆无 ⇒ **显式拒绝**，不静默落入默认租户。</p>
     */
    @PostMapping("/login")
    public ApiResponse<Map<String, Object>> login(@Valid @RequestBody WorkerLoginRequest request,
                                                  HttpServletRequest httpRequest) {
        Long tenantId = tenantDomainResolver.resolve(httpRequest).orElse(request.getTenantId());
        if (tenantId == null) {
            throw BusinessException.validationError(
                    "无法识别租户：请通过 <租户ID>.app.migaozn.com 域名访问或提供 tenantId");
        }
        Long previous = TenantContext.getTenantId();
        TenantContext.setTenantId(tenantId);
        try {
            return ApiResponse.success(workerSessionService.login(
                    tenantId, request.getWorkerNo(), request.getPin(), request.getDeviceLabel()));
        } finally {
            // 登录接口本身是 permitAll（无 JWT 过滤器设的租户上下文）⇒ 必须自己清，
            // 否则线程复用会把租户上下文泄漏给下一个请求
            if (previous == null) {
                TenantContext.clear();
            } else {
                TenantContext.setTenantId(previous);
            }
        }
    }

    /**
     * 快速切换工人（共用 PAD，设计 W2）：结束旧 session（{@code switched}）+ 建新 session。
     *
     * <p>旧 session **立即失效** ⇒ 用旧 id 报工必 401（不把活记到上一个人头上）。
     * 扫码上下文由前端保留（本端点不碰报工上下文）。</p>
     */
    @PostMapping("/session/switch")
    public ApiResponse<Map<String, Object>> switchWorker(
            @Valid @RequestBody WorkerLoginRequest request,
            @RequestHeader(value = WorkerSessionService.SESSION_HEADER, required = false) String sessionId,
            HttpServletRequest httpRequest) {
        Long tenantId = tenantDomainResolver.resolve(httpRequest).orElse(request.getTenantId());
        if (tenantId == null) {
            throw BusinessException.validationError(
                    "无法识别租户：请通过 <租户ID>.app.migaozn.com 域名访问或提供 tenantId");
        }
        Long previous = TenantContext.getTenantId();
        TenantContext.setTenantId(tenantId);
        try {
            return ApiResponse.success(workerSessionService.switchWorker(
                    tenantId, sessionId, request.getWorkerNo(), request.getPin(), request.getDeviceLabel()));
        } finally {
            if (previous == null) {
                TenantContext.clear();
            } else {
                TenantContext.setTenantId(previous);
            }
        }
    }

    /** 主动登出（幂等）。 */
    @PostMapping("/session/logout")
    public ApiResponse<Void> logout(
            @RequestHeader(value = WorkerSessionService.SESSION_HEADER, required = false) String sessionId) {
        workerSessionService.logout(sessionId);
        return ApiResponse.success();
    }

    /**
     * 当前工人（报工页页头「当前工人：张三」的数据来源）。
     *
     * <p>🔴 数据来源是**服务端 session**，不是前端 state：前端 state 可被改，
     * 而页头显示的正是「这笔活会记到谁头上」。</p>
     */
    @PostMapping("/session/current")
    public ApiResponse<Map<String, Object>> current(
            @RequestHeader(value = WorkerSessionService.SESSION_HEADER, required = false) String sessionId) {
        if (!StringUtils.hasText(sessionId)) {
            throw BusinessException.authFailed("尚未登录工人身份，请先用工号 + PIN 登录");
        }
        return ApiResponse.success(workerSessionService.currentWorker(sessionId));
    }
}
