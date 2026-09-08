package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.service.KnowledgeDistillService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.*;

import java.util.Map;

/**
 * 知识提炼控制器（LLM WIKI 板块 P5b，issue #3051 — L3 会话提炼触发）
 *
 * - POST /api/admin/knowledge/distill/conversations?hours=24 → 提炼最近 N 小时已结束人工会话 → 待确认队列
 *   返回 {sessions, candidates, created, skipped}
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
}
