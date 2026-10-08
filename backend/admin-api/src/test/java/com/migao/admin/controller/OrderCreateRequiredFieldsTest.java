// case_ids: OR-054
package com.migao.admin.controller;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.config.GlobalExceptionHandler;
import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.OrderCreateRequest;
import com.migao.admin.dto.OrderDetailResponse;
import com.migao.admin.service.OrderService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * 建单**必填字段**闸门（issue #5840）—— **表单路径**（{@code @Valid @RequestBody}）那一侧。
 *
 * <p>用户 2026-10-01 逐字：「物流信息改成客户信息，不能只校验物流，**客户信息都是必填**」，
 * 并就本题选定「两个物流字段也必填」。收敛前 {@code customerAddress} / {@code logisticsType} /
 * {@code logisticsCompany} 三个字段**零注解** ⇒ 绕过前端直调 API 即可落一张没有收货地址、
 * 没有物流信息的单（地址是发货的唯一依据）。</p>
 *
 * <p><b>为什么判在 DTO 而不是 Service</b>（本文件同时是这条口径的承载体）：
 * agent 路径 {@code OrderService.createOrderForAgent} 是<b>手工 new {@link OrderCreateRequest}</b>
 * 再调 service ⇒ <b>不经过 Bean Validation</b>；而 C 端元元/黄金策的自助下单**不采集**这三个字段
 * （{@code order_create} 工具 schema 的 required 只有 name/phone/items）。把必填下沉到 Service
 * 会把整条 agent 下单路径打死。⇒ 本闸门的射程**就是** HTTP 表单路径，这是**有意为之**，
 * 不是漏判。前端一半的判据 = {@code frontend/admin-web/tests/unit/pages/orders-new-submit-gate.test.tsx}。</p>
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("建单必填字段（#5840）：客户信息 + 物流两项")
class OrderCreateRequiredFieldsTest {

    private static final String CREATE = "/api/admin/orders";

    private MockMvc mockMvc;

    private final ObjectMapper objectMapper = new ObjectMapper();

    @Mock
    private OrderService orderService;

    @InjectMocks
    private OrderController orderController;

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(1L);
        mockMvc = MockMvcBuilders.standaloneSetup(orderController)
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    /** 一份**完整合法**的表单请求（每个用例只摘掉它要验的那一个字段） */
    private Map<String, Object> validPayload() {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("customerName", "张三");
        body.put("customerPhone", "13800138000");
        body.put("customerAddress", "北京市朝阳区");
        body.put("logisticsType", "express");
        body.put("logisticsCompany", "顺丰");
        body.put("items", List.of(Map.of(
                "productId", "prod-001",
                "productName", "遮光窗帘",
                "quantity", 2,
                "unitPrice", 500,
                "width", 2.5,
                "height", 2.8,
                "subtotal", 1000
        )));
        return body;
    }

    private void assertRejected(String missingField, String expectedMessage) throws Exception {
        Map<String, Object> body = validPayload();
        body.remove(missingField);

        mockMvc.perform(post(CREATE).contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(body)))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.error.code").value("VALIDATION_ERROR"))
                .andExpect(jsonPath("$.error.details[0].field").value(missingField))
                .andExpect(jsonPath("$.error.details[0].message").value(expectedMessage));

        // 闸门必须**在调 service 之前**拦住（落库 = 已经晚了）
        verifyNoInteractions(orderService);
    }

    @Test
    @DisplayName("缺 customerAddress ⇒ 422「客户地址不能为空」（收敛前零注解 ⇒ 可落空地址单）")
    void missingCustomerAddressRejected() throws Exception {
        assertRejected("customerAddress", "客户地址不能为空");
    }

    @Test
    @DisplayName("缺 logisticsType ⇒ 422「常用物流/快递不能为空」")
    void missingLogisticsTypeRejected() throws Exception {
        assertRejected("logisticsType", "常用物流/快递不能为空");
    }

    @Test
    @DisplayName("缺 logisticsCompany ⇒ 422「常用物流公司不能为空」")
    void missingLogisticsCompanyRejected() throws Exception {
        assertRejected("logisticsCompany", "常用物流公司不能为空");
    }

    @Test
    @DisplayName("空白串也算缺（@NotBlank，不是 @NotNull）")
    void blankLogisticsCompanyRejected() throws Exception {
        Map<String, Object> body = validPayload();
        body.put("logisticsCompany", "   ");

        mockMvc.perform(post(CREATE).contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(body)))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.error.details[0].message").value("常用物流公司不能为空"));

        verifyNoInteractions(orderService);
    }

    @Test
    @DisplayName("放行：三个字段齐备 ⇒ 200 且 service 真的被调用一次（防「闸门把正常单挡在门外」）")
    void completeRequestPasses() throws Exception {
        OrderDetailResponse response = new OrderDetailResponse();
        response.setId("a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6");
        response.setOrderNo("ORD20261001001");
        response.setStatus("pending");
        when(orderService.createOrder(any(OrderCreateRequest.class), eq(1L))).thenReturn(response);

        mockMvc.perform(post(CREATE).contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(validPayload())))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.orderNo").value("ORD20261001001"));

        verify(orderService, times(1)).createOrder(any(OrderCreateRequest.class), eq(1L));
    }
}
