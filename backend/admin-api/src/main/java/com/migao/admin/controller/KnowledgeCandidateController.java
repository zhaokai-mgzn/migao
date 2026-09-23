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
public class KnowledgeCandidateController {

    private final KnowledgeCandidateService knowledgeCandidateService;

    /**
     * 待确认队列分页
     *
     * issue #5246：类级 knowledge:manage 已移除 ⇒ 查看队列是**读**，用读码 knowledge:view
     * （采纳/拒绝才是写，见下方三个 POST）。
     */
    @GetMapping
    @RequirePermission("knowledge:view")
    public ApiResponse<PageResponse<KnowledgeCandidate>> page(
            @RequestParam(required = false) String status,
            @RequestParam(defaultValue = "1") long page,
            @RequestParam(defaultValue = "20") long size) {
        return ApiResponse.success(knowledgeCandidateService.page(status, page, size));
    }

    /** 待确认数量角标 —— issue #5246：同为**读**（侧边栏/知识库页角标）⇒ knowledge:view */
    @GetMapping("/pending-count")
    @RequirePermission("knowledge:view")
    public ApiResponse<Map<String, Long>> pendingCount() {
        return ApiResponse.success(Map.of("pending", knowledgeCandidateService.pendingCount()));
    }

    /** 采纳候选 → 建卡 —— issue #5246：写面保留 knowledge:manage */
    @PostMapping("/{id}/adopt")
    @RequirePermission("knowledge:manage")
    public ApiResponse<KnowledgeCard> adopt(@PathVariable String id) {
        return ApiResponse.success(knowledgeCandidateService.adopt(id));
    }

    /** 采纳并改写 → 建卡 —— issue #5246：写面保留 knowledge:manage */
    @PostMapping("/{id}/adopt-edited")
    @RequirePermission("knowledge:manage")
    public ApiResponse<KnowledgeCard> adoptEdited(@PathVariable String id, @RequestBody KnowledgeCandidate patch) {
        return ApiResponse.success(knowledgeCandidateService.adoptEdited(id, patch));
    }

    /** 拒绝候选 —— issue #5246：写面保留 knowledge:manage */
    @PostMapping("/{id}/reject")
    @RequirePermission("knowledge:manage")
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
