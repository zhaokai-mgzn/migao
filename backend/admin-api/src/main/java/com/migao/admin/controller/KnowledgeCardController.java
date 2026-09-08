package com.migao.admin.controller;

import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.PageResponse;
import com.migao.admin.entity.KnowledgeCard;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.service.KnowledgeCardService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/**
 * 知识卡片管理控制器（LLM WIKI 板块，issue #3051）
 *
 * 替代旧 KnowledgeController（文档 CRUD/embed/test-search）成为知识域唯一入口。
 * 知识卡片生命周期闭环：创建(draft/published) → 编辑(version+1) → 发布(published) → 归档(archived) → 删除。
 *
 * 前端对齐：entriesApi (frontend/admin-web/src/lib/api.ts)
 * - GET    /api/admin/knowledge/cards          → page（筛选/分页）
 * - GET    /api/admin/knowledge/cards/search   → search（仅 published + 租户隔离）
 * - POST   /api/admin/knowledge/cards          → create
 * - PUT    /api/admin/knowledge/cards/{id}     → update
 * - DELETE /api/admin/knowledge/cards/{id}     → delete
 * - POST   /api/admin/knowledge/cards/{id}/publish → publish
 * - POST   /api/admin/knowledge/cards/{id}/archive → archive
 */
@Slf4j
@RestController
@RequestMapping("/api/admin/knowledge/cards")
@RequiredArgsConstructor
@RequirePermission("knowledge:manage")
public class KnowledgeCardController {

    private final KnowledgeCardService knowledgeCardService;

    /** 分页查询知识卡片列表 */
    @GetMapping
    public ApiResponse<PageResponse<KnowledgeCard>> page(
            @RequestParam(defaultValue = "1") long page,
            @RequestParam(defaultValue = "10") long size,
            @RequestParam(required = false) String keyword,
            @RequestParam(required = false) String category,
            @RequestParam(required = false) String sourceType,
            @RequestParam(required = false) String status) {
        return ApiResponse.success(knowledgeCardService.page(page, size, keyword, category, sourceType, status));
    }

    /** 知识卡片检索（仅本租户 published 知识卡片，供 Agent knowledge_search 与管理后台） */
    @GetMapping("/search")
    public ApiResponse<List<KnowledgeCard>> search(
            @RequestParam(required = false) String query,
            @RequestParam(required = false) String productId,
            @RequestParam(required = false) String category) {
        return ApiResponse.success(knowledgeCardService.search(query, productId, category));
    }

    /** 创建知识卡片 */
    @PostMapping
    public ApiResponse<KnowledgeCard> create(@RequestBody KnowledgeCard body) {
        return ApiResponse.success(knowledgeCardService.create(body));
    }

    /** 编辑知识卡片（version+1） */
    @PutMapping("/{id}")
    public ApiResponse<KnowledgeCard> update(@PathVariable String id, @RequestBody KnowledgeCard body) {
        return ApiResponse.success(knowledgeCardService.update(id, body));
    }

    /** 删除知识卡片（逻辑删除） */
    @DeleteMapping("/{id}")
    public ApiResponse<Void> delete(@PathVariable String id) {
        knowledgeCardService.delete(id);
        return ApiResponse.success();
    }

    /** 发布知识卡片：draft/pending_review → published */
    @PostMapping("/{id}/publish")
    public ApiResponse<KnowledgeCard> publish(@PathVariable String id) {
        return ApiResponse.success(knowledgeCardService.publish(id));
    }

    /** 归档知识卡片：published → archived */
    @PostMapping("/{id}/archive")
    public ApiResponse<KnowledgeCard> archive(@PathVariable String id) {
        return ApiResponse.success(knowledgeCardService.archive(id));
    }
}
