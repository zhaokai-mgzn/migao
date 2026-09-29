package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.service.WorkerPageConfigService;
import com.migao.admin.worker.WorkerIdentity;
import com.migao.admin.worker.WorkerSessionService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 工人端**身份 + 页面**只读端点（V141，母单 #5161）：{@code GET /api/worker/me}。
 *
 * <h3>它回答什么</h3>
 * <p>「我是谁 + 本租户给我开了哪几个工人端页面」—— 工人端 H5 / 车间一体机登录后**第一件事**就是
 * 拉它决定渲染哪些页。</p>
 *
 * <h3>🔴 它不下发任何权限（本类的存在理由就是不下发权限）</h3>
 * <ul>
 *   <li>响应里的 {@code pages} 是**页面可见性**（租户级开关），<b>不是</b>权限码，
 *       <b>不得</b>被写进 {@code users.permissions}；</li>
 *   <li>工人 session 的 {@code permissions} <b>恒为 {@code []}</b>、{@code roles} 恒为
 *       {@code ["worker"]}（{@code WorkerSessionService}），工人可达面恒为 {@code /api/worker/**}，
 *       {@code /api/admin/**} 对 {@code worker} 一律 403（{@code SecurityConfig}）；</li>
 *   <li>把某个页面从 {@code pages} 里去掉<b>不等于</b>挡住对应接口 —— 服务端对每个工人都仍然
 *       按同一套授权判（页面开关只是「看不看得见」）。</li>
 * </ul>
 *
 * <h3>租户取自会话行，不取自请求</h3>
 * <p>{@link WorkerSessionService#tenantIdOf} 与 {@link WorkerSessionService#resolveIdentity} 走
 * **同一处**读行/定租户 ⇒ 「会话租户必须与请求租户一致」那条 fail-closed 判定不会在这里被绕过。</p>
 *
 * <p>⚠️ 本控制器**独立**于 {@code WorkerProductionController}（报工面）：报工面只回答「这笔活记到谁头上」，
 * 本面只回答「工人端有哪些页面」—— 两件事分开，改一处不影响另一处的判据。</p>
 */
@Slf4j
@RestController
@RequestMapping("/api/worker")
@RequiredArgsConstructor
public class WorkerProfileController {

    private final WorkerSessionService workerSessionService;
    private final WorkerPageConfigService workerPageConfigService;

    /**
     * 当前工人身份 + 本租户开通的工人端页面。
     *
     * <p>无有效工人 session ⇒ 服务层抛 401（**不降级**成匿名或 body 口径）。</p>
     */
    @GetMapping("/me")
    public ApiResponse<Map<String, Object>> me(
            @RequestHeader(value = WorkerSessionService.SESSION_HEADER, required = false) String sessionId) {
        WorkerIdentity identity = workerSessionService.resolveIdentity(sessionId);
        Long tenantId = workerSessionService.tenantIdOf(identity.sessionId());

        Map<String, Object> data = new LinkedHashMap<>();
        data.put("worker_id", identity.workerId());
        data.put("worker_name", identity.workerName());
        data.put("session_id", identity.sessionId());
        data.put("identity_source", identity.source());
        // 页面集：只回**本租户本工人**的那一份（无行 ⇒ 默认全开）。
        data.put("pages", workerPageConfigService.pagesFor(tenantId));
        return ApiResponse.success(data);
    }
}
