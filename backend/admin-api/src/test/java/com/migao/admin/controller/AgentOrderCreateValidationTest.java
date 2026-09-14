// case_ids: OR-008, OR-011
package com.migao.admin.controller;

import com.migao.admin.controller.agent.AgentOrderController;
import com.migao.admin.dto.OrderDetailResponse;
import com.migao.admin.mapper.UserMapper;
import com.migao.admin.service.OrderService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

/**
 * Agent 下单入口的**参数范围闸门**（issue #3622）——负数量/负单价必须被拒。
 *
 * 为什么这是资金/库存完整性缺陷（修复前）：
 * <ul>
 *   <li>Agent 路径是 ai-agent 唯一实走的路径（`order_create` → POST /api/admin/agent/orders）；</li>
 *   <li>该路径的 DTO（`AgentOrderCreateRequest.AgentOrderItem`）**零约束注解**，
 *       Controller `createOrder` **没有 `@Valid`** → 负数量/负单价一路落库：</li>
 *   <li>`OrderService.createOrder()`（:413）直接 `unitPrice.multiply(BigDecimal.valueOf(quantity))`
 *       → **负金额**写进 `orders.total_amount`；</li>
 *   <li>库存前置校验（:437 `validateStockSufficientForRequest`）判据是「需求量 ≤ 库存」，
 *       对**负需求恒真** → **超卖防线被绕过**。</li>
 * </ul>
 *
 * 表单路径（`OrderCreateRequest` + `OrderController` 的 `@Valid`）本来就有 `@NotNull/@Positive`；
 * 本测试锁的是「**Agent 路径与表单路径同口径**」。
 *
 * <p><b>「注解真的执行」怎么验</b>：断言 HTTP **422** + `error.code=VALIDATION_ERROR` +
 * `error.details[i].message` 是**注解上的 message 原文**（"数量不能小于 1" / "单价必须大于 0"）
 * + `orderService` **完全没被调用**。这三条只有 Bean Validation 在控制器层真的跑了才会同时成立
 * —— 只要有人去掉 `@Valid` 或注解，报文立刻退化成 200 且 service 被调用，本测试变红。</p>
 *
 * <p>数量下限从「&gt; 0」收紧为「≥ 1」（issue #3682）：0.5 会被服务端按整数件算成 0 件
 * （`OrderService` `intValue()`：`needed=0` 校验恒通过、`deductStock(0)` 不减库存、销量 +0），
 * 订单成交却零扣减且无告警。下限与表单页 `min={1}` 同口径。</p>
 *
 * <p>为什么还需要 Service 层测试：`createOrderForAgent` 是**手工 `new OrderCreateRequest()`**
 * 再转交 `createOrder()`，程序化构造的 Bean **不经过 Bean Validation** —— 故 Service 层另有
 * 显式判定，由 {@code AgentOrderServiceTest} 锁（双保险；本类不重复覆盖）。</p>
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("Agent 下单参数范围闸门（#3622）")
class AgentOrderCreateValidationTest extends BaseControllerTest {

    private static final String CREATE = "/api/admin/agent/orders";

    private MockMvc mockMvc;

    @Mock private OrderService orderService;
    @Mock private UserMapper userMapper;

    @InjectMocks private AgentOrderController agentOrderController;

    @BeforeEach
    void setUp() {
        super.baseSetUp();
        mockMvc = buildMockMvc(agentOrderController);
    }

    /** 组请求体：quantity/unitPrice 用原文（null 表示不传该字段） */
    private String createBody(String quantity, String unitPrice) {
        StringBuilder item = new StringBuilder("{\"productName\":\"遮光窗帘\"");
        if (quantity != null) {
            item.append(",\"quantity\":").append(quantity);
        }
        if (unitPrice != null) {
            item.append(",\"unitPrice\":").append(unitPrice);
        }
        item.append("}");
        return "{\"customerName\":\"张三\",\"customerPhone\":\"13800138000\",\"items\":["
                + item + "]}";
    }

    @Nested
    @DisplayName("拒绝：负数量 / 0 数量 / <1 的小数（负金额 + 超卖防线被绕过 + 静默漏扣库存）")
    class QuantityRange {

        @Test
        @DisplayName("quantity=-3 → 422 VALIDATION_ERROR（不落库、不调 service）")
        void negativeQuantityRejected() throws Exception {
            mockMvc.perform(post(CREATE).contentType(MediaType.APPLICATION_JSON)
                            .content(createBody("-3", "168")))
                    .andExpect(status().isUnprocessableEntity())
                    .andExpect(jsonPath("$.success").value(false))
                    .andExpect(jsonPath("$.error.code").value("VALIDATION_ERROR"))
                    .andExpect(jsonPath("$.error.details[0].field").value("items[0].quantity"))
                    .andExpect(jsonPath("$.error.details[0].message").value("数量不能小于 1"));

            verifyNoInteractions(orderService);
        }

        @Test
        @DisplayName("quantity=0 → 422 VALIDATION_ERROR（0 元明细同样不该落库）")
        void zeroQuantityRejected() throws Exception {
            mockMvc.perform(post(CREATE).contentType(MediaType.APPLICATION_JSON)
                            .content(createBody("0", "168")))
                    .andExpect(status().isUnprocessableEntity())
                    .andExpect(jsonPath("$.error.details[0].message").value("数量不能小于 1"));

            verifyNoInteractions(orderService);
        }

        @Test
        @DisplayName("quantity=0.5 → 422（issue #3682：服务端会按整数件算成 0 件 → 不扣库存、销量 +0）")
        void subOneQuantityRejected() throws Exception {
            mockMvc.perform(post(CREATE).contentType(MediaType.APPLICATION_JSON)
                            .content(createBody("0.5", "168")))
                    .andExpect(status().isUnprocessableEntity())
                    .andExpect(jsonPath("$.error.code").value("VALIDATION_ERROR"))
                    .andExpect(jsonPath("$.error.details[0].field").value("items[0].quantity"))
                    .andExpect(jsonPath("$.error.details[0].message").value("数量不能小于 1"));

            verifyNoInteractions(orderService);
        }

        @Test
        @DisplayName("缺 quantity → 422「数量不能为空」（@NotNull 真的执行）")
        void missingQuantityRejected() throws Exception {
            mockMvc.perform(post(CREATE).contentType(MediaType.APPLICATION_JSON)
                            .content(createBody(null, "168")))
                    .andExpect(status().isUnprocessableEntity())
                    .andExpect(jsonPath("$.error.details[0].message").value("数量不能为空"));

            verifyNoInteractions(orderService);
        }
    }

    @Nested
    @DisplayName("拒绝：负单价 / 0 单价")
    class UnitPriceRange {

        @Test
        @DisplayName("unitPrice=-168 → 422 VALIDATION_ERROR（负单价 → 负金额）")
        void negativeUnitPriceRejected() throws Exception {
            mockMvc.perform(post(CREATE).contentType(MediaType.APPLICATION_JSON)
                            .content(createBody("3", "-168")))
                    .andExpect(status().isUnprocessableEntity())
                    .andExpect(jsonPath("$.error.code").value("VALIDATION_ERROR"))
                    .andExpect(jsonPath("$.error.details[0].field").value("items[0].unitPrice"))
                    .andExpect(jsonPath("$.error.details[0].message").value("单价必须大于 0"));

            verifyNoInteractions(orderService);
        }

        @Test
        @DisplayName("unitPrice=0 → 422 VALIDATION_ERROR")
        void zeroUnitPriceRejected() throws Exception {
            mockMvc.perform(post(CREATE).contentType(MediaType.APPLICATION_JSON)
                            .content(createBody("3", "0")))
                    .andExpect(status().isUnprocessableEntity())
                    .andExpect(jsonPath("$.error.details[0].message").value("单价必须大于 0"));

            verifyNoInteractions(orderService);
        }

        @Test
        @DisplayName("缺 unitPrice → 422「单价不能为空」")
        void missingUnitPriceRejected() throws Exception {
            mockMvc.perform(post(CREATE).contentType(MediaType.APPLICATION_JSON)
                            .content(createBody("3", null)))
                    .andExpect(status().isUnprocessableEntity())
                    .andExpect(jsonPath("$.error.details[0].message").value("单价不能为空"));

            verifyNoInteractions(orderService);
        }
    }

    @Nested
    @DisplayName("放行：合法下单不受影响（防过严）")
    class ValidRequestsStillPass {

        private OrderDetailResponse stubOrder(String id) {
            OrderDetailResponse d = new OrderDetailResponse();
            d.setId(id);
            d.setOrderNo("ORD-" + id);
            d.setCustomerName("张三");
            d.setCustomerPhone("13800138000");
            d.setStatus("pending");
            return d;
        }

        @Test
        @DisplayName("正整数数量 + 正单价 → 200 且 service 真的被调用一次")
        void validOrderPassesValidation() throws Exception {
            when(orderService.createOrderForAgent(any(), anyLong()))
                    .thenReturn(stubOrder("o-1"));

            mockMvc.perform(post(CREATE).contentType(MediaType.APPLICATION_JSON)
                            .content(createBody("3", "168")))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.success").value(true));

            verify(orderService, times(1)).createOrderForAgent(any(), eq(TEST_TENANT_ID));
        }

        @Test
        @DisplayName("quantity=1 → 200（下限值本身必须放行，防「闸门把正常订单挡在门外」）")
        void minimumQuantityOnePasses() throws Exception {
            when(orderService.createOrderForAgent(any(), anyLong()))
                    .thenReturn(stubOrder("o-min"));

            mockMvc.perform(post(CREATE).contentType(MediaType.APPLICATION_JSON)
                            .content(createBody("1", "168")))
                    .andExpect(status().isOk());

            verify(orderService, times(1)).createOrderForAgent(any(), eq(TEST_TENANT_ID));
        }

        @Test
        @DisplayName("quantity=8.4 → 200（issue #3682：≥1 的小数（per_area 面积）不误伤）")
        void decimalQuantityPasses() throws Exception {
            when(orderService.createOrderForAgent(any(), anyLong()))
                    .thenReturn(stubOrder("o-dec"));

            mockMvc.perform(post(CREATE).contentType(MediaType.APPLICATION_JSON)
                            .content(createBody("8.4", "168")))
                    .andExpect(status().isOk());

            verify(orderService, times(1)).createOrderForAgent(any(), eq(TEST_TENANT_ID));
        }

        @Test
        @DisplayName("负数量拒绝后，合法请求仍能下单（守卫不是「永远下不了单」）")
        void validAfterRejection() throws Exception {
            mockMvc.perform(post(CREATE).contentType(MediaType.APPLICATION_JSON)
                            .content(createBody("-3", "168")))
                    .andExpect(status().isUnprocessableEntity());
            verifyNoInteractions(orderService);

            when(orderService.createOrderForAgent(any(), anyLong()))
                    .thenReturn(stubOrder("o-3"));

            mockMvc.perform(post(CREATE).contentType(MediaType.APPLICATION_JSON)
                            .content(createBody("3", "168")))
                    .andExpect(status().isOk());

            verify(orderService, times(1)).createOrderForAgent(any(), eq(TEST_TENANT_ID));
        }
    }
}
