package com.migao.admin.controller;

// case_ids=[PR-005]

import com.migao.admin.controller.agent.AgentProductController;
import com.migao.admin.dto.ProductResponse;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.service.ProductService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.test.web.servlet.MockMvc;

import java.math.BigDecimal;

import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.patch;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * AgentProductController 库存调整端点测试（生产回归：假成功修复）。
 * PATCH /api/admin/agent/products/{id}/stock
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("AgentProductController 库存调整端点")
class AgentProductControllerTest extends BaseControllerTest {

    private MockMvc mockMvc;

    @Mock
    private ProductService productService;

    @InjectMocks
    private AgentProductController controller;

    private static final String BASE = "/api/admin/agent/products";
    private static final String PROD_ID = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6";

    @BeforeEach
    void setUp() {
        super.baseSetUp();
        mockMvc = buildMockMvc(controller);
    }

    private ProductResponse responseWithStock(int stock) {
        ProductResponse p = new ProductResponse();
        p.setId(PROD_ID);
        p.setName("遮光窗帘");
        p.setStock(stock);
        p.setTotalStock(stock);
        p.setBasePrice(new BigDecimal("99.00"));
        return p;
    }

    @Nested
    @DisplayName("PATCH /{id}/stock — 库存调整")
    class AdjustStock {

        @Test
        @DisplayName("调整成功 — 返回更新后 stock（供 agent 读回校验）")
        void success() throws Exception {
            when(productService.resolveProductId(eq(PROD_ID), eq(TEST_TENANT_ID))).thenReturn(PROD_ID);
            when(productService.adjustStockForAgent(eq(PROD_ID), eq(30), eq("盘点"), eq(TEST_TENANT_ID)))
                    .thenReturn(responseWithStock(80));

            mockMvc.perform(patch(BASE + "/" + PROD_ID + "/stock")
                            .contentType("application/json")
                            .content("{\"adjustment\": 30, \"reason\": \"盘点\"}"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.success").value(true))
                    .andExpect(jsonPath("$.data.stock").value(80));
        }

        @Test
        @DisplayName("缺少 adjustment — 参数错误")
        void missingAdjustment() throws Exception {
            mockMvc.perform(patch(BASE + "/" + PROD_ID + "/stock")
                            .contentType("application/json")
                            .content("{\"reason\": \"盘点\"}"))
                    .andExpect(status().is4xxClientError());
        }

        @Test
        @DisplayName("库存不足 — 422 且返回错误信息")
        void insufficientStock() throws Exception {
            when(productService.resolveProductId(eq(PROD_ID), eq(TEST_TENANT_ID))).thenReturn(PROD_ID);
            when(productService.adjustStockForAgent(eq(PROD_ID), eq(-999), any(), eq(TEST_TENANT_ID)))
                    .thenThrow(new BusinessException("INSUFFICIENT_STOCK", "库存不足：当前总库存 50，无法减少 999", 422));

            mockMvc.perform(patch(BASE + "/" + PROD_ID + "/stock")
                            .contentType("application/json")
                            .content("{\"adjustment\": -999, \"reason\": \"报损\"}"))
                    .andExpect(status().isUnprocessableEntity());
        }
    }
}
