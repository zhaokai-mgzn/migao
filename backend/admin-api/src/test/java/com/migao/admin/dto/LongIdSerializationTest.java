package com.migao.admin.dto;
// case_ids: OR-006

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;

import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Long 主键序列化精度测试（订单确认付款扣库存链路）
 *
 * <p>product_skus.id / product_colors.id 为 BIGSERIAL，实际值已超过 JS 安全整数
 * 2^53（9007199254740992）。若以 JSON number 返回，前端 JS 解析会失真
 * （2093675370043592706 → 2093675370043592704），订单创建后 processingInfo.skuId
 * 失真 → 确认付款时 matchSkuId 查不到 SKU → 库存视为 0 件 → 拒绝确认支付。
 *
 * <p>修复：对 id/colorId 字段使用 ToStringSerializer 序列化为字符串，前端原样回传。
 */
class LongIdSerializationTest {

    private final ObjectMapper mapper = new ObjectMapper();

    @Test
    @DisplayName("ProductSkuResponse.id/colorId 超过 2^53 应以字符串序列化")
    void productSkuId_above2pow53_shouldSerializeAsString() throws Exception {
        ProductSkuResponse sku = new ProductSkuResponse();
        sku.setId(2093675370043592706L);
        sku.setProductId("p-001");
        sku.setColorId(2093675369993261000L);
        sku.setSellingMethod("bulk_cut");
        sku.setDoorWidth("2.8米");
        sku.setPrice(new BigDecimal("88.00"));
        sku.setStock(100);

        String json = mapper.writeValueAsString(sku);
        // id 必须原样可读回（字符串形式），否则 JS 端精度丢失
        assertTrue(json.contains("\"id\":\"2093675370043592706\""),
            "Long id 超过 2^53 应以字符串序列化，实际: " + json);
        assertTrue(json.contains("\"colorId\":\"2093675369993261000\""),
            "colorId 超过 2^53 应以字符串序列化，实际: " + json);
        // 普通数字字段（库存/价格）保持数值类型，不受影响
        assertTrue(json.contains("\"stock\":100"), "库存应保持 number: " + json);
    }

    @Test
    @DisplayName("ProductColorResponse.id 超过 2^53 应以字符串序列化")
    void productColorId_above2pow53_shouldSerializeAsString() throws Exception {
        ProductColorResponse color = new ProductColorResponse();
        color.setId(2093675369993261000L);
        color.setProductId("p-001");
        color.setColorName("验收米白");

        String json = mapper.writeValueAsString(color);
        assertTrue(json.contains("\"id\":\"2093675369993261000\""),
            "ProductColor.id 超过 2^53 应以字符串序列化，实际: " + json);
    }
}
