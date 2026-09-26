package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.InboundLabelPrintView;
import com.migao.admin.dto.InboundLabelView;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.service.InboundLabelService;
import com.migao.admin.worker.WorkerIdentity;
import com.migao.admin.worker.WorkerSessionService;
import jakarta.servlet.http.HttpServletRequest;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 工人可达的**入库标签**端点（issue #5052 <b>P2</b>）：{@code /api/worker/inbound/labels/**}。
 *
 * <h3>为什么是独立控制器（而不是挤进 {@code WorkerInboundController}）</h3>
 * <p>① P1 的结构守卫逐字钉住「{@code WorkerInboundController} 只有那三个 POST」
 * （{@code WorkerInboundSurfaceGuardTest.onlyTheThreeP1EndpointsExist}）—— 标签面挤进去会当场变红；
 * ② 两条链的**身份面与判据面不同**：入库是「写库存的窄接口」，标签是「读单据 + 留痕」，
 * 分开才能各自被独立守卫（判据见 {@code InboundLabelSurfaceGuardTest}）。</p>
 *
 * <h3>零商家权限码（设计 §9.3 红线，同 P1 一字不改）</h3>
 * <p>本控制器**不注入** {@code PermissionInterceptor}、**没有**任何 {@code @RequirePermission}：
 * 准入判据只有一条 —— <b>有效工人 session</b>（无 / 已结束 / 已闲置超时 ⇒ 401）。
 * 工人零商家权限码在这里是**结构事实**，不是配置。</p>
 *
 * <h3>状态码（设计 §5.2 拒绝口径，逐条可红）</h3>
 * <ul>
 *   <li>未登录（无 / 无效工人 session）⇒ <b>401</b>；</li>
 *   <li>跨租户 / 不存在 ⇒ <b>404</b>（**不是 403**：403 等于告诉对方「这个码存在，只是不归你」）；</li>
 *   <li>已撤销 ⇒ <b>410 Gone</b>（§7.3；不静默回落到别的标签）。</li>
 * </ul>
 */
@Slf4j
@RestController
@RequestMapping("/api/worker/inbound/labels")
@RequiredArgsConstructor
public class WorkerInboundLabelController {

    private final InboundLabelService inboundLabelService;
    private final WorkerSessionService workerSessionService;

    /**
     * 按短码读**单据业务详情**（功能②「拍照米高标签 → 显示单据详情 → 打印新标签」的读面）。
     *
     * <p>GET /api/worker/inbound/labels/{shortCode}</p>
     */
    @GetMapping("/{shortCode}")
    public ApiResponse<InboundLabelView> detail(
            @PathVariable("shortCode") String shortCode,
            @RequestHeader(value = WorkerSessionService.SESSION_HEADER, required = false) String sessionId) {
        requireWorker(sessionId);
        return ApiResponse.success(inboundLabelService.detail(shortCode, TenantContext.getTenantId()));
    }

    /**
     * **打印留痕**：计数原子自增 + 审计（设备侧打印**前**必须先调它，§7.3「打印必留痕」）。
     *
     * <p>POST /api/worker/inbound/labels/{shortCode}/print</p>
     */
    @PostMapping("/{shortCode}/print")
    public ApiResponse<InboundLabelPrintView> print(
            @PathVariable("shortCode") String shortCode,
            @RequestHeader(value = WorkerSessionService.SESSION_HEADER, required = false) String sessionId,
            HttpServletRequest request) {
        WorkerIdentity identity = requireWorker(sessionId);
        return ApiResponse.success(inboundLabelService.recordPrint(
                shortCode, TenantContext.getTenantId(), identity.workerId(), identity.workerName(),
                request.getRemoteAddr(), request.getHeader("User-Agent")));
    }

    /** 有效工人 session 或 401（与 P1 同一处判据：工人路径上「谁」没有第二条来源）。 */
    private WorkerIdentity requireWorker(String sessionId) {
        WorkerIdentity identity = workerSessionService.resolveIdentity(sessionId);
        if (identity == null) {
            throw BusinessException.authFailed("尚未登录工人身份，请先用工号 + PIN 登录");
        }
        return identity;
    }
}
