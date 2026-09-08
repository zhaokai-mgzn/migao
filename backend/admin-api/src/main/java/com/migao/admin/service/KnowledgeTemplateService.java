package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.KnowledgeTemplateInfo;
import com.migao.admin.entity.KnowledgeCard;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.KnowledgeCardMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.core.io.ClassPathResource;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.io.IOException;
import java.io.InputStream;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * 行业模板服务（LLM WIKI 板块 P3，issue #3051）
 *
 * 模板 = 平台预置资产（resources/knowledge-templates/<templateId>/template.json，jar 内可读）。
 * 一键套用 = 把模板知识卡片复制为当前租户词条（sourceType=template, sourceRef=templateId, status=published），
 * 按 (tenant_id, title) 去重：重复标题跳过。AI 只提供起点，商家可编辑。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class KnowledgeTemplateService {

    private static final String TEMPLATES_ROOT = "knowledge-templates";
    private static final String INDEX_FILE = TEMPLATES_ROOT + "/index.json";

    private final KnowledgeCardMapper knowledgeCardMapper;
    private final ObjectMapper objectMapper = new ObjectMapper();

    /** 平台预置模板目录 */
    public List<KnowledgeTemplateInfo> listTemplates() {
        List<KnowledgeTemplateInfo> result = new ArrayList<>();
        try {
            JsonNode index = readJson(INDEX_FILE);
            JsonNode templates = index.path("templates");
            for (JsonNode t : templates) {
                String templateId = t.path("templateId").asText();
                String file = t.path("file").asText();
                int entryCount = loadTemplateFile(file).path("entries").size();
                result.add(KnowledgeTemplateInfo.builder()
                        .templateId(templateId)
                        .industry(t.path("industry").asText())
                        .name(t.path("name").asText())
                        .version(t.path("version").asInt(1))
                        .description(t.path("description").asText())
                        .entryCount(entryCount)
                        .build());
            }
        } catch (IOException e) {
            log.error("读取行业模板目录失败", e);
        }
        return result;
    }

    /**
     * 一键套用模板到当前租户。
     *
     * @return {templateId, created, skipped}
     */
    public Map<String, Object> applyTemplate(String templateId) {
        JsonNode template = loadTemplate(templateId);
        Long tenantId = TenantContext.getTenantId();
        JsonNode entries = template.path("entries");
        String industry = template.path("industry").asText("curtain");

        int created = 0;
        int skipped = 0;
        for (JsonNode e : entries) {
            String title = e.path("title").asText("");
            String answer = e.path("answer").asText("");
            if (!StringUtils.hasText(title) || !StringUtils.hasText(answer)) {
                continue; // 模板脏数据防御
            }
            Long exists = knowledgeCardMapper.selectCount(new LambdaQueryWrapper<KnowledgeCard>()
                    .eq(KnowledgeCard::getTenantId, tenantId)
                    .eq(KnowledgeCard::getTitle, title));
            if (exists != null && exists > 0) {
                skipped++;
                continue;
            }
            KnowledgeCard card = KnowledgeCard.builder()
                    .tenantId(tenantId)
                    .title(title)
                    .category(e.path("category").asText("faq"))
                    .industry(industry)
                    .question(e.path("question").isMissingNode() ? null : e.path("question").asText())
                    .answer(answer)
                    .keywords(e.path("keywords").isMissingNode() ? null : e.path("keywords").asText())
                    .sourceType("template")
                    .sourceRef(templateId)
                    .status("published")
                    .version(1)
                    .createdBy("template")
                    .build();
            knowledgeCardMapper.insert(card);
            created++;
        }
        log.info("套用行业模板: templateId={}, tenantId={}, created={}, skipped={}", templateId, tenantId, created, skipped);
        return Map.of("templateId", templateId, "created", created, "skipped", skipped);
    }

    /** 读取模板根节点（未知模板 → 404） */
    private JsonNode loadTemplate(String templateId) {
        JsonNode index;
        try {
            index = readJson(INDEX_FILE);
        } catch (IOException e) {
            throw BusinessException.notFound("行业模板");
        }
        for (JsonNode t : index.path("templates")) {
            if (templateId.equals(t.path("templateId").asText())) {
                try {
                    return loadTemplateFile(t.path("file").asText());
                } catch (IOException e) {
                    log.error("读取模板文件失败: templateId={}", templateId, e);
                    throw BusinessException.notFound("行业模板");
                }
            }
        }
        throw BusinessException.notFound("行业模板");
    }

    private JsonNode loadTemplateFile(String file) throws IOException {
        return readJson(TEMPLATES_ROOT + "/" + file);
    }

    private JsonNode readJson(String classpath) throws IOException {
        ClassPathResource resource = new ClassPathResource(classpath);
        try (InputStream in = resource.getInputStream()) {
            return objectMapper.readTree(in);
        }
    }
}
