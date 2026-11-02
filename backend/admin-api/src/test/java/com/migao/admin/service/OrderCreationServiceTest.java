// case_ids: OR-061
package com.migao.admin.service;

import com.migao.admin.dto.OrderCreateRequest;
import com.migao.admin.dto.OrderDetailResponse;
import com.migao.admin.dto.agent.AgentOrderCreateRequest;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.util.ReflectionTestUtils;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 接线判据（issue #8191，P2-1b）：{@link OrderService} 的**创建门面**真的委托到
 * {@link OrderCreationService}（同名方法 + 同参 + 把 {@code this} 作为第三参传下去）。
 *
 * <p><b>为什么需要它</b>：本单拆的是「位置」—— 既有 {@code OrderServiceTest} 的 152 条全部走门面，
 * 它们<b>无论实现留在本类还是搬到新类都会绿</b>。所以「拆成功了吗」这件事行为面判据看不见，
 * 必须单独钉一条<b>交互面</b>的目。</p>
 *
 * <p><b>红证（把委托改回内联实现 ⇒ 这里必红）</b>：门面改回内联后会走真 Mapper
 * （本类只给了 {@code @Mock OrderCreationService}，其余协作者为 {@code null}）⇒
 * ① NPE 或 ② {@code verify(...)} 拿不到交互 ⇒ 红。实测见 PR body。</p>
 *
 * <p><b>边界（照实登记）</b>：本判据只管<b>门面 → 服务</b>这一次跳转；不判
 * {@link OrderCreationService} 内部实现对不对（既有 {@code OrderServiceTest} 逐条承担），
 * 也不覆盖「创建服务在 Spring 装配下确实是 bean」这一层（由启动/集成测试覆盖）。</p>
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("接线判据：OrderService 创建门面必须委托 OrderCreationService（#8191 P2-1b）")
class OrderCreationServiceTest {

    @Mock
    private OrderCreationService orderCreationService;

    @InjectMocks
    private OrderService orderService;

    @BeforeEach
    void wireCreationService() {
        // @InjectMocks 只做构造注入；orderCreationService 是字段注入（理由见 OrderService 的
        // creationService() 注释：构造签名被多处测试显式装配）⇒ 显式装配。
        ReflectionTestUtils.setField(orderService, "orderCreationService", orderCreationService);
    }

    @Test
    @DisplayName("🔴 建单门面 createOrder ⇒ 委托（第三参必须是本实例，保证共享同一份口径）")
    void createOrderDelegates() {
        OrderCreateRequest request = new OrderCreateRequest();
        OrderDetailResponse expected = new OrderDetailResponse();
        when(orderCreationService.createOrder(request, 7L, orderService)).thenReturn(expected);

        OrderDetailResponse actual = orderService.createOrder(request, 7L);

        assertThat(actual).isSameAs(expected);
        verify(orderCreationService).createOrder(request, 7L, orderService);
    }

    @Test
    @DisplayName("🔴 Agent 建单门面 createOrderForAgent ⇒ 委托（同样带 this）")
    void createOrderForAgentDelegates() {
        AgentOrderCreateRequest request = new AgentOrderCreateRequest();
        OrderDetailResponse expected = new OrderDetailResponse();
        when(orderCreationService.createOrderForAgent(request, 9L, orderService)).thenReturn(expected);

        OrderDetailResponse actual = orderService.createOrderForAgent(request, 9L);

        assertThat(actual).isSameAs(expected);
        verify(orderCreationService).createOrderForAgent(request, 9L, orderService);
    }
}
