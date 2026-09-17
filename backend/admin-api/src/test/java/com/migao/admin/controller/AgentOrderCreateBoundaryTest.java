// case_ids: OR-008, OR-016
package com.migao.admin.controller;

import com.migao.admin.controller.agent.AgentOrderController;
import com.migao.admin.mapper.UserMapper;
import com.migao.admin.service.OrderService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import static org.mockito.Mockito.verifyNoInteractions;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * 「校验双写」的红证与验收判据（issue #4089 · A17 订单 DTO 收敛）。
 *
 * <p><b>病根</b>：{@code OrderService.createOrderForAgent} 手工 {@code new OrderCreateRequest}
 * 逐字段搬运后转交 {@code createOrder()} —— 程序化构造的 Bean **不过 Bean Validation**，
 * 于是 Service 只好把那套判定**再写一遍**（「手工 new 使 Bean Validation 失效 ⇒ service 必须再判
 * 一遍 ⇒ 两处口径必然漂移」）。本类锁的判据是：**Bean Validation 真的在 agent 端点上执行**，
 * 而不是靠 Service 补判。</p>
 *
 * <p><b>红证（收敛前 @ da9d66e8，实测）</b>：同一个 payload（{@code items: []}）在
 * **表单路径** {@code POST /api/admin/orders} 被 {@code items@NotEmpty} 拦成 422；
 * 在 **agent 路径** {@code POST /api/admin/agent/orders} 却连 Bean Validation 都没触发
 * —— 该 payload 一路进 Service，由手工判定才抛 400/500。于是「422 + 字段级 details +
 * service 零调用」这组断言在收敛前**必然红**（见 PR 证据表的红证输出）。</p>
 *
 * <p><b>为什么断言"service 零调用"</b>：这才是"校验在边界且只有一处"的机器判据 ——
 * 只要有人把 {@code @Valid} 去掉、或把请求类型换回平行 DTO，报文立刻退化成 200/500 且
 * service 被调用，本类变红。</p>
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("Agent 下单请求的 Bean Validation 边界（issue #4089 校验双写消除）")
class AgentOrderCreateBoundaryTest extends BaseControllerTest {

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

    @Test
    @DisplayName("items 为空 ⇒ 422 + 字段级 details（共享类型 @NotEmpty 真的执行），service 零调用")
    void emptyItemsRejectedBeforeService() throws Exception {
        mockMvc.perform(post(CREATE).contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"customerName":"张三","customerPhone":"13800138000","items":[]}
                                """))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.error.code").value("VALIDATION_ERROR"))
                .andExpect(jsonPath("$.error.details[0].field").value("items"))
                .andExpect(jsonPath("$.error.details[0].message").value("订单明细不能为空"));

        verifyNoInteractions(orderService);
    }

    @Test
    @DisplayName("手机号非法 ⇒ 422「手机号格式不正确…」（共享类型 @Pattern 真的执行），service 零调用")
    void invalidPhoneRejectedBeforeService() throws Exception {
        mockMvc.perform(post(CREATE).contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"customerName":"张三","customerPhone":"12345",
                                 "items":[{"productName":"遮光窗帘","quantity":3,"unitPrice":168,"subtotal":504}]}
                                """))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.error.code").value("VALIDATION_ERROR"))
                .andExpect(jsonPath("$.error.details[0].field").value("customerPhone"))
                .andExpect(jsonPath("$.error.details[0].message")
                        .value("手机号格式不正确，请输入11位中国大陆手机号"));

        verifyNoInteractions(orderService);
    }

    @Test
    @DisplayName("缺 subtotal ⇒ 422「小计不能为空」（D3 收敛：agent 侧不再可选），service 零调用")
    void missingSubtotalRejectedBeforeService() throws Exception {
        mockMvc.perform(post(CREATE).contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"customerName":"张三","customerPhone":"13800138000",
                                 "items":[{"productName":"遮光窗帘","quantity":3,"unitPrice":168}]}
                                """))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.error.code").value("VALIDATION_ERROR"))
                .andExpect(jsonPath("$.error.details[0].field").value("items[0].subtotal"))
                .andExpect(jsonPath("$.error.details[0].message").value("小计不能为空"));

        verifyNoInteractions(orderService);
    }

    @Test
    @DisplayName("负宽度 ⇒ 422（D6 收敛：服务端不再裸 BigDecimal），service 零调用")
    void negativeWidthRejectedBeforeService() throws Exception {
        mockMvc.perform(post(CREATE).contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"customerName":"张三","customerPhone":"13800138000",
                                 "items":[{"productName":"遮光窗帘","quantity":3,"unitPrice":168,
                                           "subtotal":504,"width":-2.8}]}
                                """))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.error.code").value("VALIDATION_ERROR"))
                .andExpect(jsonPath("$.error.details[0].field").value("items[0].width"))
                .andExpect(jsonPath("$.error.details[0].message").value("宽度不能为负数"));

        verifyNoInteractions(orderService);
    }
}