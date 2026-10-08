package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.WorkerLoginRequest;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.worker.WorkerSessionService;
import com.migao.admin.worker.WorkerTenantResolver;
import com.migao.admin.worker.WorkerTenantResolver.ResolvedWorkerLogin;
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
    private final WorkerTenantResolver workerTenantResolver;

    /**
     * 工号 + PIN 登录 ⇒ 签发工人 session。
     *
     * <p>租户判定（issue #6564）与小程序登录同口径、但多两档：域名/网关头（{@code X-Tenant-Id}）为**权威**，
     * 其次 body {@code enterpriseCode} 与 {@code 工号@企业编码}，body {@code tenantId} 仅兼容期兜底；
     * 四档皆无 ⇒ **显式拒绝**（422 可行动文案），不静默落入默认租户。
     * 解析口径**只有一份实现** = {@link WorkerTenantResolver}。</p>
     */
    @PostMapping("/login")
    public ApiResponse<Map<String, Object>> login(@Valid @RequestBody WorkerLoginRequest request,
                                                  HttpServletRequest httpRequest) {
        ResolvedWorkerLogin resolved = resolveOrReject(request, httpRequest);
        Long tenantId = resolved.tenantId();
        Long previous = TenantContext.getTenantId();
        TenantContext.setTenantId(tenantId);
        try {
            return ApiResponse.success(workerSessionService.login(
                    tenantId, resolved.workerNo(), request.getPin(), request.getDeviceLabel()));
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
        ResolvedWorkerLogin resolved = resolveOrReject(request, httpRequest);
        Long tenantId = resolved.tenantId();
        Long previous = TenantContext.getTenantId();
        TenantContext.setTenantId(tenantId);
        try {
            return ApiResponse.success(workerSessionService.switchWorker(
                    tenantId, sessionId, resolved.workerNo(), request.getPin(), request.getDeviceLabel()));
        } finally {
            if (previous == null) {
                TenantContext.clear();
            } else {
                TenantContext.setTenantId(previous);
            }
        }
    }

    /**
     * 解析租户与工号；解析不出时按「客户端是否**尝试**用企业编码定位租户」分流（反枚举，issue #6564）。
     *
     * <p>尝试过（送了 {@code enterpriseCode}，或工号带合法的 {@code @企业编码} 后缀）但解析不出
     * ⇒ 与「工号不存在 / PIN 错」返回**同一个 401 同一文案**（不泄露企业是否存在）；
     * 完全没提供任何租户来源 ⇒ 422 可行动文案（那是**输入缺失**，不是凭据错误）。</p>
     */
    private ResolvedWorkerLogin resolveOrReject(WorkerLoginRequest request, HttpServletRequest httpRequest) {
        ResolvedWorkerLogin resolved = workerTenantResolver.resolve(httpRequest, request);
        if (resolved.tenantId() != null) {
            return resolved;
        }
        if (workerTenantResolver.tenantSourceAttempted(request)) {
            throw BusinessException.authFailed(WorkerSessionService.AUTH_FAILED_MESSAGE);
        }
        throw BusinessException.validationError(
                "无法识别租户：请填写企业编码（向商家索取，例如 migao）");
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
