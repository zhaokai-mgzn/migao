package com.migao.admin.controller;

import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.PageResponse;
import com.migao.admin.entity.KnowledgeCandidate;
import com.migao.admin.entity.KnowledgeCard;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.service.KnowledgeCandidateService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.*;

import java.util.Map;

/**
 * 知识提炼候选控制器（LLM WIKI 板块 P5，issue #3051 — 待确认队列闭环）
 *
 * - GET    /api/admin/knowledge/candidates             → 待确认队列分页（默认 status=pending）
 * - GET    /api/admin/knowledge/candidates/pending-count → 待确认数量（前端红点）
 * - POST   /api/admin/knowledge/candidates/{id}/adopt    → 采纳（转卡片 published）
 * - POST   /api/admin/knowledge/candidates/{id}/adopt-edited → 编辑后采纳（body 覆盖 title/answer 等）
 * - POST   /api/admin/knowledge/candidates/{id}/reject   → 拒绝（body 可带 note）
 */
@Slf4j
@RestController
@RequestMapping("/api/admin/knowledge/candidates")
@RequiredArgsConstructor
@RequirePermission("knowledge:manage")
public class KnowledgeCandidateController {

    private final KnowledgeCandidateService knowledgeCandidateService;

    @GetMapping
    public ApiResponse<PageResponse<KnowledgeCandidate>> page(
            @RequestParam(required = false) String status,
            @RequestParam(defaultValue = "1") long page,
            @RequestParam(defaultValue = "20") long size) {
        return ApiResponse.success(knowledgeCandidateService.page(status, page, size));
    }

    @GetMapping("/pending-count")
    public ApiResponse<Map<String, Long>> pendingCount() {
        return ApiResponse.success(Map.of("pending", knowledgeCandidateService.pendingCount()));
    }

    @PostMapping("/{id}/adopt")
    public ApiResponse<KnowledgeCard> adopt(@PathVariable String id) {
        return ApiResponse.success(knowledgeCandidateService.adopt(id));
    }

    @PostMapping("/{id}/adopt-edited")
    public ApiResponse<KnowledgeCard> adoptEdited(@PathVariable String id, @RequestBody KnowledgeCandidate patch) {
        return ApiResponse.success(knowledgeCandidateService.adoptEdited(id, patch));
    }

    @PostMapping("/{id}/reject")
    public ApiResponse<Void> reject(@PathVariable String id, @RequestBody(required = false) RejectRequest body) {
        knowledgeCandidateService.reject(id, body == null ? null : body.getNote());
        return ApiResponse.success();
    }

    public static class RejectRequest {
        private String note;
        public String getNote() { return note; }
        public void setNote(String note) { this.note = note; }
    }
}
