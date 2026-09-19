package com.migao.admin.controller;

// case_ids: PG-041

import com.migao.admin.security.RequirePermission;
import com.migao.admin.service.ProcessingFeeCalculator;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.test.web.servlet.MockMvc;

import java.math.BigDecimal;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.http.MediaType.APPLICATION_JSON;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * 加工费计价预览控制器测试（issue #4450 · 前置 #4406）
 *
 * <p>判据：
 * <ol>
 *   <li>端点 {@code POST /api/admin/orders/fee-preview} 返回 {@code {success,data}}，
 *       {@code data.items[i] = {processingFee, processingFeeDetail}} + {@code processingFeeTotal}
 *       （与订单详情行的键名**逐字一致**，页面与详情页可共用同一套渲染）；</li>
 *   <li><b>单一真值</b>：控制器只调 {@link ProcessingFeeCalculator#feesFor} —— 与创建订单**同一个**实现，
 *       自己不实现任何取价逻辑（第二份取价 = 页面与落库再次分叉，正是本单要消灭的形态）；</li>
 *   <li>逐行 {@code processingInfo} **原样**传给取价（含下标对齐：缺 {@code processingInfo} 的行给
 *       {@code null} 但**不跳过** —— 跳过会让页面下标与服务端错位）；</li>
 *   <li>缺 {@code items} / 空数组 ⇒ 返回空列表而非报错（下单页未选商品时本就会问）；</li>
 *   <li>租户从 {@code TenantContext} 取（价目表按租户隔离），不信任请求体。</li>
 * </ol>
 *
 * <p>红证（实现前）：{@code FeePreviewController} 不存在 ⇒ 本文件编译失败（找不到符号）。</p>
 */
@DisplayName("FeePreviewController 加工费计价预览端点（issue #4450）")
class FeePreviewControllerTest extends BaseControllerTest {

    private static final String URL = "/api/admin/orders/fee-preview";

    private ProcessingFeeCalculator calculator;
    private MockMvc mockMvc;

    @BeforeEach
    void setUp() {
        super.baseSetUp();
        calculator = mock(ProcessingFeeCalculator.class);
        mockMvc = buildMockMvc(new FeePreviewController(calculator));
    }

    /** 命中组合：¥10.00/米 × 13.3 米 = ¥133.00（与 #4406 的取价口径同形） */
    private static ProcessingFeeCalculator.Fee matched() {
        Map<String, Object> detail = new LinkedHashMap<>();
        detail.put("composition", "韩式褶");
        detail.put("items", List.of("韩式褶"));
        detail.put("matched_rule_id", "rule-1");
        detail.put("unit_price", new BigDecimal("10.00"));
        detail.put("price_source", "manual");
        detail.put("meters", new BigDecimal("13.3"));
        detail.put("meters_source", "processingMeters");
        detail.put("fee_source", "matched");
        detail.put("amount", new BigDecimal("133.00"));
        detail.put("hint", null);
        return new ProcessingFeeCalculator.Fee(
                new BigDecimal("133.00"), "matched", "韩式褶", List.of("韩式褶"), "rule-1",
                new BigDecimal("10.00"), "manual", new BigDecimal("13.3"), "processingMeters",
                detail, null);
    }

    private static ProcessingFeeCalculator.Fee unpriced() {
        Map<String, Object> detail = new LinkedHashMap<>();
        detail.put("composition", "韩式褶");
        detail.put("unit_price", null);
        detail.put("meters", new BigDecimal("13.3"));
        detail.put("fee_source", "unpriced");
        detail.put("amount", BigDecimal.ZERO);
        detail.put("hint", "该组合未定价，请到加工费组合里配置");
        return new ProcessingFeeCalculator.Fee(
                BigDecimal.ZERO, "unpriced", "韩式褶", List.of("韩式褶"), null,
                null, null, new BigDecimal("13.3"), "processingMeters", detail,
                "该组合未定价，请到加工费组合里配置");
    }

    @Test
    @DisplayName("命中组合 ⇒ 逐行 processingFee + processingFeeDetail，合计为逐行之和")
    void returnsPerLineFeeAndDetail() throws Exception {
        when(calculator.feesFor(any(), any())).thenReturn(List.of(matched()));

        mockMvc.perform(post(URL).contentType(APPLICATION_JSON).content("""
                        {"items":[{"processingInfo":{"processingItems":[{"name":"韩式褶"}]}}]}
                        """))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.items[0].processingFee").value(133.00))
                .andExpect(jsonPath("$.data.items[0].processingFeeDetail.fee_source").value("matched"))
                .andExpect(jsonPath("$.data.items[0].processingFeeDetail.unit_price").value(10.00))
                .andExpect(jsonPath("$.data.items[0].processingFeeDetail.meters").value(13.3))
                .andExpect(jsonPath("$.data.processingFeeTotal").value(133.00));
    }

    @Test
    @DisplayName("未定价 ⇒ 金额 0 + fee_source=unpriced + hint 原样透出（不静默、不回落 Σ 加工项）")
    void passesUnpricedThroughVerbatim() throws Exception {
        when(calculator.feesFor(any(), any())).thenReturn(List.of(unpriced()));

        mockMvc.perform(post(URL).contentType(APPLICATION_JSON).content("""
                        {"items":[{"processingInfo":{"processingItems":[{"name":"韩式褶"}]}}]}
                        """))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.items[0].processingFee").value(0))
                .andExpect(jsonPath("$.data.items[0].processingFeeDetail.fee_source").value("unpriced"))
                .andExpect(jsonPath("$.data.items[0].processingFeeDetail.hint")
                        .value("该组合未定价，请到加工费组合里配置"))
                .andExpect(jsonPath("$.data.processingFeeTotal").value(0));
    }

    @Test
    @DisplayName("单一真值：只调 ProcessingFeeCalculator.feesFor，租户取自 TenantContext")
    @SuppressWarnings("unchecked")
    void delegatesToSharedCalculatorWithTenantFromContext() throws Exception {
        when(calculator.feesFor(any(), any())).thenReturn(List.of(matched()));

        mockMvc.perform(post(URL).contentType(APPLICATION_JSON).content("""
                        {"items":[{"processingInfo":{"processingItems":[{"name":"韩式褶"}]}}]}
                        """))
                .andExpect(status().isOk());

        ArgumentCaptor<List<Object>> infos = ArgumentCaptor.forClass(List.class);
        verify(calculator).feesFor(infos.capture(), eq(TEST_TENANT_ID));
        // 逐行 processingInfo **原样**传下去（组合键由它的 processingItems[].name 派生）
        assertThat(infos.getValue()).hasSize(1);
        assertThat(infos.getValue().get(0)).isInstanceOf(Map.class);
        assertThat(((Map<String, Object>) infos.getValue().get(0)).get("processingItems"))
                .isInstanceOf(List.class);
    }

    @Test
    @DisplayName("下标对齐：缺 processingInfo 的行给 null 但**不跳过**（跳过会让页面下标与服务端错位）")
    @SuppressWarnings("unchecked")
    void keepsIndexAlignmentWhenProcessingInfoMissing() throws Exception {
        when(calculator.feesFor(any(), any())).thenReturn(List.of(matched(), unpriced()));

        mockMvc.perform(post(URL).contentType(APPLICATION_JSON).content("""
                        {"items":[{"processingInfo":null},{"processingInfo":{"processingItems":[]}}]}
                        """))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.items.length()").value(2));

        ArgumentCaptor<List<Object>> infos = ArgumentCaptor.forClass(List.class);
        verify(calculator).feesFor(infos.capture(), eq(TEST_TENANT_ID));
        assertThat(infos.getValue()).hasSize(2);
        assertThat(infos.getValue().get(0)).isNull();
        assertThat(infos.getValue().get(1)).isNotNull();
    }

    @Test
    @DisplayName("缺 items / 空数组 ⇒ 空列表 + 合计 0（下单页未选商品时本就会问，不报错）")
    void emptyRequestYieldsEmptyResult() throws Exception {
        when(calculator.feesFor(any(), any())).thenReturn(List.of());

        mockMvc.perform(post(URL).contentType(APPLICATION_JSON).content("{}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.items.length()").value(0))
                .andExpect(jsonPath("$.data.processingFeeTotal").value(0));
    }

    @Test
    @DisplayName("权限：@RequirePermission(\"order:list\")（与订单读域同权限，下单页商家本就持有）")
    void requiresOrderListPermission() throws Exception {
        RequirePermission annotation = FeePreviewController.class
                .getMethod("preview", Map.class)
                .getAnnotation(RequirePermission.class);
        assertThat(annotation).isNotNull();
        assertThat(annotation.value()).isEqualTo("order:list");
    }
}
