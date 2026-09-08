package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.service.KnowledgeDeriveService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.*;

import java.util.Map;

/**
 * 知识派生对账控制器（LLM WIKI 板块 P2-1 收尾，issue #3051/#3063）
 *
 * 商品/加工项 → 知识卡片派生：商品变更已自动触发（P4），本端点提供**存量对账**——
 * 管理端手动触发全量重建（补偿历史存量商品/加工项未生成派生卡片）。
 * - POST /api/admin/knowledge/derive/rebuild → {products, processingItems}
 */
@Slf4j
@RestController
@RequestMapping("/api/admin/knowledge/derive")
@RequiredArgsConstructor
@RequirePermission("knowledge:manage")
public class KnowledgeDeriveController {

    private final KnowledgeDeriveService knowledgeDeriveService;

    @PostMapping("/rebuild")
    public ApiResponse<Map<String, Object>> rebuild() {
        Map<String, Object> result = knowledgeDeriveService.deriveAll(TenantContext.getTenantId());
        log.info("知识派生对账触发完成: tenantId={}, {}", TenantContext.getTenantId(), result);
        return ApiResponse.success(result);
    }
}
