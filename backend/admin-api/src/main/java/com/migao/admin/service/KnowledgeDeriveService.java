package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.entity.KnowledgeCard;
import com.migao.admin.entity.ProcessingItem;
import com.migao.admin.entity.Product;
import com.migao.admin.entity.ProductSku;
import com.migao.admin.mapper.KnowledgeCardMapper;
import com.migao.admin.mapper.ProcessingItemMapper;
import com.migao.admin.mapper.ProductMapper;
import com.migao.admin.mapper.ProductSkuMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

/**
 * 商品/配置派生知识卡片服务（LLM WIKI 板块 P4，issue #3051 — L2 本店事实层）
 *
 * 商品/加工项是结构化数据，直接「生成」知识卡片而非检索（替代 RAG 的本店事实层）：
 * - 商品 → 「{商品名}多少钱」卡片（answer 含 SKU 价格区间，随商品变更自动更新，保证与商品页一致）
 * - 加工项 → 「{加工项名}怎么计价」卡片（answer 按 pricingMethod 生成）
 * 卡片 sourceType=product/config、status=published；同源（tenant+sourceType+sourceRef）upsert，人工可改（改后重建会覆盖——v1 约定）。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class KnowledgeDeriveService {

    private final ProductMapper productMapper;
    private final ProductSkuMapper productSkuMapper;
    private final ProcessingItemMapper processingItemMapper;
    private final KnowledgeCardMapper knowledgeCardMapper;
    private final ObjectMapper objectMapper;

    /** 对账：全量商品 + 加工项派生（管理端手动触发，补偿漏触发） */
    public Map<String, Object> deriveAll(Long tenantId) {
        int products = deriveAllProductCards(tenantId);
        int items = deriveAllProcessingCards(tenantId);
        log.info("知识卡片对账派生: tenantId={}, products={}, processingItems={}", tenantId, products, items);
        return Map.of("products", products, "processingItems", items);
    }

    /** 单商品派生（商品创建/更新/上下架时触发） */
    public void deriveProductCard(Long tenantId, String productId) {
        Product product = productMapper.selectById(productId);
        if (product == null || !product.getTenantId().equals(tenantId)) {
            return;
        }
        List<ProductSku> skus = productSkuMapper.selectList(new LambdaQueryWrapper<ProductSku>()
                .eq(ProductSku::getTenantId, tenantId)
                .eq(ProductSku::getProductId, productId));
        String priceRange = buildPriceRange(skus, product.getUnit());
        String answer = product.getName() + "：" + priceRange
                + "。具体规格、颜色、库存请以商品页为准。"
                + (StringUtils.hasText(product.getDescription())
                        ? " 简介：" + product.getDescription().replaceAll("\\s+", " ").substring(0, Math.min(80, product.getDescription().length()))
                        : "");
        upsert(tenantId, "product", productId, product.getName() + "多少钱", "product", answer,
                Map.of("productId", productId, "priceRange", priceRange));
    }

    /** 全量商品派生 */
    public int deriveAllProductCards(Long tenantId) {
        List<Product> products = productMapper.selectList(new LambdaQueryWrapper<Product>()
                .eq(Product::getTenantId, tenantId));
        for (Product p : products) {
            deriveProductCard(tenantId, p.getId());
        }
        return products.size();
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

    /** SKU 价格区间文案 */
    private String buildPriceRange(List<ProductSku> skus, String unit) {
        if (skus == null || skus.isEmpty()) {
            return "价格以商品页为准";
        }
        BigDecimal min = null;
        BigDecimal max = null;
        for (ProductSku sku : skus) {
            if (sku.getPrice() == null) {
                continue;
            }
            min = min == null ? sku.getPrice() : min.min(sku.getPrice());
            max = max == null ? sku.getPrice() : max.max(sku.getPrice());
        }
        if (min == null) {
            return "价格以商品页为准";
        }
        String unitText = StringUtils.hasText(unit) ? " 元/" + unit : " 元";
        return min.equals(max) ? min.toPlainString() + unitText : min.toPlainString() + "-" + max.toPlainString() + unitText;
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
