package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.service.WorkerPageConfigService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/**
 * 工人端**页面开关**读写端点（V141，母单 #5161；商家面「设置 → 工人端页面」）。
 *
 * <ul>
 *   <li>{@code GET /api/admin/worker-page-config} —— 本租户生效的页面集合；
 *       无配置行 ⇒ <b>默认全开</b> + {@code source='default'}</li>
 *   <li>{@code PUT} —— upsert（<b>全量替换</b>）；未知页面键 / 缺键 ⇒
 *       {@code 422 + error.details:[{field,message}]} 逐条理由</li>
 * </ul>
 *
 * <p><b>权限</b>：<b>读面</b>（{@code GET}）挂生产域<b>读</b>码 {@code production:view}；
 * <b>写面</b>（{@code PUT}）是类级 {@code processing:manage}（与工序库 / 工艺路线 / 算料配置 /
 * 裁高配置的写面同口径）。</p>
 *
 * <p>🔴 <b>本控制器不签发任何权限</b>：它改的是商家侧的页面开关，<b>不</b>写
 * {@code users.permissions}、<b>不</b>参与工人授权判定 —— 工人 session 的
 * {@code permissions} 恒为 {@code []}（{@code WorkerSessionService}）。</p>
 */
@Slf4j
@RestController
@RequestMapping("/api/admin/worker-page-config")
@RequiredArgsConstructor
@RequirePermission("processing:manage")
public class WorkerPageConfigController {

    private final WorkerPageConfigService workerPageConfigService;

    /** 读本租户生效的工人端页面集合（{@code data = {source, pages, labels}}）。 */
    @RequirePermission("production:view")
    @GetMapping
    public ApiResponse<Map<String, Object>> get() {
        return ApiResponse.success(workerPageConfigService.get(TenantContext.getTenantId()));
    }

    /** 写本租户工人端页面集合（upsert，**全量替换**）。 */
    @PutMapping
    public ApiResponse<Map<String, Object>> put(@RequestBody Map<String, Object> body) {
        return ApiResponse.success(workerPageConfigService.put(TenantContext.getTenantId(), body));
    }
}
