package com.migao.admin.controller;

import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.KnowledgeTemplateInfo;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.service.KnowledgeTemplateService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

/**
 * 行业模板控制器（LLM WIKI 板块 P3，issue #3051）
 *
 * 模板为平台资产（resources/knowledge-templates/），一键套用复制为租户知识卡片。
 * - GET  /api/admin/knowledge/templates              → 模板目录
 * - POST /api/admin/knowledge/templates/{id}/apply   → 一键套用（去重 + source=template）
 */
@Slf4j
@RestController
@RequestMapping("/api/admin/knowledge/templates")
@RequiredArgsConstructor
public class KnowledgeTemplateController {

    private final KnowledgeTemplateService knowledgeTemplateService;

    /**
     * 平台预置模板目录
     *
     * issue #5246：类级 knowledge:manage 已移除 ⇒ 看模板目录是**读**，用读码 knowledge:view
     * （套用模板才是写）。
     */
    @GetMapping
    @RequirePermission("knowledge:view")
    public ApiResponse<List<KnowledgeTemplateInfo>> list() {
        return ApiResponse.success(knowledgeTemplateService.listTemplates());
    }

    /** 一键套用模板到当前租户 —— issue #5246：写面保留 knowledge:manage */
    @PostMapping("/{templateId}/apply")
    @RequirePermission("knowledge:manage")
    public ApiResponse<Map<String, Object>> apply(@PathVariable String templateId) {
        return ApiResponse.success(knowledgeTemplateService.applyTemplate(templateId));
    }
}
