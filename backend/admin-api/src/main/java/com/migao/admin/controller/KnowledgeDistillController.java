package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.service.KnowledgeDistillService;
import lombok.Data;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.*;

import java.util.Map;

/**
 * 知识提炼控制器（LLM WIKI 板块 P5b/P6，issue #3051 — 会话/文档提炼触发）
 *
 * - POST /api/admin/knowledge/distill/conversations?hours=24 → 提炼最近 N 小时已结束人工会话 → 待确认队列
 * - POST /api/admin/knowledge/distill/documents            → 文档文本提炼 → 待确认队列（body: {title, content}）
 */
@Slf4j
@RestController
@RequestMapping("/api/admin/knowledge/distill")
@RequiredArgsConstructor
@RequirePermission("knowledge:manage")
public class KnowledgeDistillController {

    private final KnowledgeDistillService knowledgeDistillService;

    @PostMapping("/conversations")
    public ApiResponse<Map<String, Object>> distillConversations(
            @RequestParam(defaultValue = "24") int hours) {
        return ApiResponse.success(knowledgeDistillService.distillConversations(TenantContext.getTenantId(), hours));
    }

    @PostMapping("/documents")
    public ApiResponse<Map<String, Object>> distillDocument(@RequestBody DocumentDistillRequest body) {
        return ApiResponse.success(knowledgeDistillService.distillDocument(
                TenantContext.getTenantId(), body.getTitle(), body.getContent()));
    }

    @Data
    public static class DocumentDistillRequest {
        private String title;
        private String content;
    }
}
