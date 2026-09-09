package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.entity.KnowledgeCard;
import com.migao.admin.entity.ProcessingItem;
import com.migao.admin.mapper.KnowledgeCardMapper;
import com.migao.admin.mapper.ProcessingItemMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.util.List;
import java.util.Map;

/**
 * 加工项派生知识卡片服务（LLM WIKI 板块 P4，issue #3051 / #3083 — L2 本店事实层）
 *
 * 商品派生已移除（issue #3083）：价格等本店事实类问题由 ai-agent product_detail 工具
 * 实时查询（customer_product_skill 编排「必须通过工具查询，不编造价格」），派生卡片
 * 快照成为冗余第二数据源，故摘除商品 → 「{商品名}多少钱」派生链路。
 *
 * 保留加工项派生：
 * - 加工项 → 「{加工项名}怎么计价」卡片（answer 按 pricingMethod 生成）
 * 卡片 sourceType=config、status=published；同源（tenant+sourceType+sourceRef）upsert，人工可改（改后重建会覆盖——v1 约定）。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class KnowledgeDeriveService {

    private final ProcessingItemMapper processingItemMapper;
    private final KnowledgeCardMapper knowledgeCardMapper;
    private final ObjectMapper objectMapper;

    /** 对账：全量加工项派生（管理端手动触发，补偿漏触发） */
    public Map<String, Object> deriveAll(Long tenantId) {
        int items = deriveAllProcessingCards(tenantId);
        log.info("知识卡片对账派生: tenantId={}, processingItems={}", tenantId, items);
        return Map.of("processingItems", items);
    }

    /** 全量加工项派生（加工项变更时触发，数量少可全量） */
    public int deriveAllProcessingCards(Long tenantId) {
        List<ProcessingItem> items = processingItemMapper.selectList(new LambdaQueryWrapper<ProcessingItem>()
                .eq(ProcessingItem::getTenantId, tenantId));
        for (ProcessingItem item : items) {
            String methodText = methodText(item);
            StringBuilder answer = new StringBuilder(item.getName()).append("：").append(methodText).append("。");
            if (StringUtils.hasText(item.getDescription())) {
                answer.append(" 说明：").append(item.getDescription());
            }
            upsert(tenantId, "config", item.getId(), item.getName() + "怎么计价", "product",
                    answer.toString(), Map.of("itemId", item.getId(), "pricingMethod", item.getPricingMethod()));
        }
        return items.size();
    }

    /** 加工项计价方式 → 文案（契约 §六：per_meter/per_set/fixed/per_area） */
    private String methodText(ProcessingItem item) {
        String method = item.getPricingMethod();
        if (method == null) {
            return "以本店价格为准";
        }
        String unit = StringUtils.hasText(item.getUnit()) ? item.getUnit() : "";
        return switch (method) {
            case "per_meter" -> "按米计价" + (unit.isBlank() ? "" : "（单位：" + unit + "）");
            case "per_set" -> "按套计价";
            case "fixed" -> "固定价格" + (item.getUnitPrice() != null ? " " + item.getUnitPrice() + " 元" : "");
            case "per_area" -> "按面积计价";
            default -> "以本店价格为准";
        };
    }

    /** 按 (tenant_id, source_type, source_ref) upsert：存在则更新（version+1），否则插入 */
    private void upsert(Long tenantId, String sourceType, String sourceRef, String title,
                        String category, String answer, Map<String, Object> variables) {
        KnowledgeCard existing = knowledgeCardMapper.selectOne(new LambdaQueryWrapper<KnowledgeCard>()
                .eq(KnowledgeCard::getTenantId, tenantId)
                .eq(KnowledgeCard::getSourceType, sourceType)
                .eq(KnowledgeCard::getSourceRef, sourceRef)
                .last("LIMIT 1"));
        String variablesJson = writeJson(variables);
        if (existing == null) {
            KnowledgeCard card = KnowledgeCard.builder()
                    .tenantId(tenantId)
                    .title(title)
                    .category(category)
                    .industry("curtain")
                    .sourceType(sourceType)
                    .sourceRef(sourceRef)
                    .answer(answer)
                    .variables(variablesJson)
                    .status("published")
                    .version(1)
                    .createdBy("derive")
                    .build();
            knowledgeCardMapper.insert(card);
        } else {
            existing.setTitle(title);
            existing.setCategory(category);
            existing.setAnswer(answer);
            existing.setVariables(variablesJson);
            existing.setStatus("published");
            existing.setVersion(existing.getVersion() == null ? 1 : existing.getVersion() + 1);
            knowledgeCardMapper.updateById(existing);
        }
    }

    private String writeJson(Map<String, Object> map) {
        try {
            return objectMapper.writeValueAsString(map);
        } catch (Exception e) {
            log.warn("派生卡片 variables 序列化失败: {}", map, e);
            return "{}";
        }
    }
}
