package com.migao.admin.controller.agent;

// case_ids: OR-016

import com.migao.admin.controller.BaseControllerTest;
import com.migao.admin.dto.OrderDetailResponse;
import com.migao.admin.dto.agent.AgentOrderCreateRequest;
import com.migao.admin.mapper.UserMapper;
import com.migao.admin.service.OrderService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * Agent 下单端点的幂等键入口契约（issue #4037，F19）。
 *
 * <p>锁两条（都能红）：</p>
 * <ol>
 *   <li>请求头 {@code X-Client-Request-Id} 必须**原样透传**到
 *       {@link AgentOrderCreateRequest#getClientRequestId()}（否则服务层无从去重）；</li>
 *   <li>幂等键**只认请求头**：请求体里的同名 JSON 字段一律忽略
 *       （DTO 上 {@code @JsonIgnore}）—— 否则调用方可自选键绕过「同键只执行一次」；</li>
 *   <li>缺省请求头 ⇒ 不报错、照常下单（向后兼容未升级的 ai-agent）。</li>
 * </ol>
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("Agent 下单幂等键入口契约（issue #4037）")
class AgentOrderControllerTest extends BaseControllerTest {

    private static final String URL = "/api/admin/agent/orders";

    @Mock
    private OrderService orderService;
    @Mock
    private UserMapper userMapper;

    @InjectMocks
    private AgentOrderController controller;

    private MockMvc mockMvc;

    @BeforeEach
    void setUp() {
        // 注：BaseControllerTest 的 @BeforeEach（TenantContext + SecurityContext）由 JUnit 自动继承执行，
        // 无需（也无法：跨包不可见）显式调用 super.baseSetUp()
        mockMvc = buildMockMvc(controller);
        OrderDetailResponse detail = new OrderDetailResponse();
        detail.setId("order-1");
        detail.setOrderNo("ORD-1");
        when(orderService.createOrderForAgent(any(AgentOrderCreateRequest.class), eq(TEST_TENANT_ID)))
                .thenReturn(detail);
    }

    @Test
    @DisplayName("请求头 X-Client-Request-Id 透传到 DTO（服务层据此去重）")
    void headerIsPassedIntoRequest() throws Exception {
        mockMvc.perform(post(URL)
                        .header("X-Client-Request-Id", "req-key-1")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(body(false)))
                .andExpect(status().isOk());

        ArgumentCaptor<AgentOrderCreateRequest> captor =
                ArgumentCaptor.forClass(AgentOrderCreateRequest.class);
        verify(orderService).createOrderForAgent(captor.capture(), eq(TEST_TENANT_ID));
        assertThat(captor.getValue().getClientRequestId()).isEqualTo("req-key-1");
    }

    @Test
    @DisplayName("请求体里的 clientRequestId 被忽略（幂等键只认请求头，防伪造）")
    void bodyCannotForgeKey() throws Exception {
        mockMvc.perform(post(URL)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(body(true)))
                .andExpect(status().isOk());

        ArgumentCaptor<AgentOrderCreateRequest> captor =
                ArgumentCaptor.forClass(AgentOrderCreateRequest.class);
        verify(orderService).createOrderForAgent(captor.capture(), eq(TEST_TENANT_ID));
        assertThat(captor.getValue().getClientRequestId()).isNull();
    }

    @Test
    @DisplayName("无请求头（老调用方）：不报错、照常下单，键为 null")
    void absentHeaderStillCreatesOrder() throws Exception {
        mockMvc.perform(post(URL)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(body(false)))
                .andExpect(status().isOk());

        ArgumentCaptor<AgentOrderCreateRequest> captor =
                ArgumentCaptor.forClass(AgentOrderCreateRequest.class);
        verify(orderService).createOrderForAgent(captor.capture(), eq(TEST_TENANT_ID));
        assertThat(captor.getValue().getClientRequestId()).isNull();
    }

    /** 合法下单请求体；{@code withBodyKey} 时额外塞一个 body 里的 clientRequestId（应被忽略） */
    private static String body(boolean withBodyKey) {
        return """
                {
                  "customerName": "张三",
                  "customerPhone": "13800001111",
                  "customerAddress": "上海市浦东新区",
                  "clientRequestId": %s,
                  "items": [
                    {"productName": "遮光窗帘", "quantity": 2, "unitPrice": 150}
                  ]
                }
                """.formatted(withBodyKey ? "\"body-forged-key\"" : "null");
    }
}