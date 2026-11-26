package com.migao.admin.controller;

import com.fasterxml.jackson.annotation.JsonProperty;
import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.service.kf.KfChannelAdminService;
import lombok.RequiredArgsConstructor;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

/** 微信客服渠道自助接入（issue #9230）；仅系统设置权限可用。 */
@RestController
@RequestMapping("/api/admin/kf/channels")
@RequiredArgsConstructor
@RequirePermission("system:manage")
@ConditionalOnProperty(prefix = "wechat.kf", name = "enabled", havingValue = "true")
public class KfChannelAdminController {

    private final KfChannelAdminService service;

    @GetMapping
    public ApiResponse<List<KfChannelAdminService.ChannelView>> list() {
        return ApiResponse.success(service.list(TenantContext.getTenantId()));
    }

    @PostMapping
    public ApiResponse<KfChannelAdminService.CreateResult> create(@RequestBody CreateRequest request) {
        return ApiResponse.success(service.create(TenantContext.getTenantId(),
                new KfChannelAdminService.CreateCommand(request.corpId(), request.openKfid(), request.secret())));
    }

    @PostMapping("/{id}/verify")
    public ApiResponse<KfChannelAdminService.ChannelView> verify(@PathVariable String id) {
        return ApiResponse.success(service.verify(TenantContext.getTenantId(), id));
    }

    @PostMapping("/{id}/disable")
    public ApiResponse<KfChannelAdminService.ChannelView> disable(@PathVariable String id) {
        return ApiResponse.success(service.disable(TenantContext.getTenantId(), id));
    }

    @PostMapping("/{id}/link")
    public ApiResponse<Map<String, String>> link(@PathVariable String id,
                                                 @RequestBody(required = false) LinkRequest request) {
        String scene = request == null ? null : request.sceneParam();
        return ApiResponse.success(Map.of("url", service.link(TenantContext.getTenantId(), id, scene)));
    }

    public record CreateRequest(@JsonProperty("corp_id") String corpId,
                                @JsonProperty("open_kfid") String openKfid,
                                String secret) {
    }

    public record LinkRequest(@JsonProperty("scene_param") String sceneParam) {
    }
}
