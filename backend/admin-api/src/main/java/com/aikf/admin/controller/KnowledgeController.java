package com.aikf.admin.controller;

import com.aikf.admin.config.TenantContext;
import com.aikf.admin.dto.ApiResponse;
import com.aikf.admin.dto.PageResponse;
import com.aikf.admin.entity.KnowledgeDocument;
import com.aikf.admin.exception.BusinessException;
import com.aikf.admin.mapper.KnowledgeDocumentMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import lombok.Data;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.util.StringUtils;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import java.util.List;
import java.util.Map;

/**
 * 知识库管理控制器
 * 提供知识库文档的 CRUD、向量同步、测试搜索等接口
 *
 * 前端对齐：knowledgeApi (frontend/admin-web/src/lib/api.ts)
 * - GET    /api/admin/knowledge/documents            → getDocuments
 * - POST   /api/admin/knowledge/documents            → uploadDocument
 * - DELETE /api/admin/knowledge/documents/{id}       → deleteDocument
 * - POST   /api/admin/knowledge/documents/{id}/embed → resyncDocument
 * - POST   /api/admin/knowledge/test-search          → searchKnowledge
 */
@Slf4j
@RestController
@RequestMapping("/api/admin/knowledge")
@RequiredArgsConstructor
public class KnowledgeController {

    private final KnowledgeDocumentMapper knowledgeDocumentMapper;

    /**
     * 分页查询知识库文档列表
     *
     * GET /api/admin/knowledge/documents?page=1&size=10&keyword=xxx&type=faq
     */
    @GetMapping("/documents")
    public ApiResponse<PageResponse<KnowledgeDocument>> getDocuments(
            @RequestParam(defaultValue = "1") long page,
            @RequestParam(defaultValue = "10") long size,
            @RequestParam(required = false) String keyword,
            @RequestParam(required = false) String type) {
        Long tenantId = TenantContext.getTenantId();
        log.info("查询知识库文档列表: page={}, size={}, keyword={}, tenantId={}", page, size, keyword, tenantId);

        LambdaQueryWrapper<KnowledgeDocument> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(KnowledgeDocument::getTenantId, tenantId);

        if (StringUtils.hasText(keyword)) {
            wrapper.like(KnowledgeDocument::getTitle, keyword);
        }
        if (StringUtils.hasText(type)) {
            wrapper.eq(KnowledgeDocument::getDocType, type);
        }

        wrapper.orderByDesc(KnowledgeDocument::getCreatedAt);

        Page<KnowledgeDocument> docPage = new Page<>(page, size);
        Page<KnowledgeDocument> resultPage = knowledgeDocumentMapper.selectPage(docPage, wrapper);

        return ApiResponse.success(PageResponse.of(resultPage));
    }

    /**
     * 上传知识库文档
     *
     * POST /api/admin/knowledge/documents
     * Content-Type: multipart/form-data
     */
    @PostMapping("/documents")
    public ApiResponse<KnowledgeDocument> uploadDocument(
            @RequestParam("name") String name,
            @RequestParam("type") String type,
            @RequestParam(value = "description", required = false) String description,
            @RequestParam(value = "file", required = false) MultipartFile file) {
        Long tenantId = TenantContext.getTenantId();
        log.info("上传知识库文档: name={}, type={}, tenantId={}", name, type, tenantId);

        KnowledgeDocument doc = KnowledgeDocument.builder()
                .tenantId(tenantId)
                .title(name)
                .docType(type)
                .category(description)
                .embeddingStatus("pending")
                .isActive(true)
                .chunkCount(0)
                .build();

        if (file != null) {
            doc.setFileType(file.getContentType());
            // TODO: 保存文件并设置 fileUrl
        }

        knowledgeDocumentMapper.insert(doc);
        return ApiResponse.success(doc);
    }

    /**
     * 删除知识库文档
     *
     * DELETE /api/admin/knowledge/documents/{id}
     */
    @DeleteMapping("/documents/{id}")
    public ApiResponse<Void> deleteDocument(@PathVariable String id) {
        Long tenantId = TenantContext.getTenantId();
        log.info("删除知识库文档: id={}, tenantId={}", id, tenantId);

        KnowledgeDocument doc = knowledgeDocumentMapper.selectById(id);
        if (doc == null) {
            throw BusinessException.notFound("知识库文档");
        }

        knowledgeDocumentMapper.deleteById(id);
        return ApiResponse.success();
    }

    /**
     * 重新同步文档向量嵌入
     *
     * POST /api/admin/knowledge/documents/{id}/embed
     */
    @PostMapping("/documents/{id}/embed")
    public ApiResponse<Void> resyncDocument(@PathVariable String id) {
        Long tenantId = TenantContext.getTenantId();
        log.info("重新同步文档嵌入: id={}, tenantId={}", id, tenantId);

        KnowledgeDocument doc = knowledgeDocumentMapper.selectById(id);
        if (doc == null) {
            throw BusinessException.notFound("知识库文档");
        }

        // 更新状态为 pending，等待后台任务重新嵌入
        doc.setEmbeddingStatus("pending");
        knowledgeDocumentMapper.updateById(doc);

        // TODO: 触发异步嵌入任务
        return ApiResponse.success();
    }

    /**
     * 测试知识库搜索
     *
     * POST /api/admin/knowledge/test-search
     */
    @PostMapping("/test-search")
    public ApiResponse<Map<String, Object>> searchKnowledge(@RequestBody SearchRequest request) {
        Long tenantId = TenantContext.getTenantId();
        log.info("测试知识库搜索: query={}, tenantId={}", request.getQuery(), tenantId);

        // TODO: 实际接入 RAG 搜索引擎
        // 当前返回简单的文档匹配结果
        LambdaQueryWrapper<KnowledgeDocument> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(KnowledgeDocument::getTenantId, tenantId)
                .eq(KnowledgeDocument::getIsActive, true);

        if (StringUtils.hasText(request.getQuery())) {
            wrapper.like(KnowledgeDocument::getTitle, request.getQuery())
                    .or()
                    .like(KnowledgeDocument::getContent, request.getQuery());
        }

        wrapper.last("LIMIT 10");
        List<KnowledgeDocument> docs = knowledgeDocumentMapper.selectList(wrapper);

        return ApiResponse.success(Map.of("results", docs));
    }

    @Data
    public static class SearchRequest {
        private String query;
        private Integer topK;
    }
}
