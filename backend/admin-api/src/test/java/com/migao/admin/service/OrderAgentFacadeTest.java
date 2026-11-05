// case_ids: MC-242
package com.migao.admin.service;

import com.migao.admin.dto.OrderDetailResponse;
import com.migao.admin.dto.agent.AgentOrderUpdateRequest;
import com.migao.admin.exception.BusinessException;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.transaction.annotation.Transactional;

import java.lang.reflect.Method;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

/**
 * Agent BFF 编排实现点（issue #8681，P2-1e 第八批）：{@link OrderAgentFacade} 的直测判据。
 *
 * <p><b>为什么有这个类</b>：{@code updateOrderForAgent} 的实现体从门面整体搬到本类之后，
 * 「搬运逐字节 + 事务边界 + 第三参是谁」这三件事在新载体上没有任何判据 —— 行为面由
 * {@code AgentOrderServiceTest}（直接驱动实现点）承担，本类只钉那三条<b>结构性</b>的事实，
 * 每一条失去都会静默改变行为：</p>
 * <ol>
 *   <li><b>事务注解逐字跟随</b>：{@code @Transactional(rollbackFor = Exception.class)} 必须真的在方法上 ——
 *       注解只对「经代理的调用」生效，丢了它 = 五个 action 的失败回滚范围静默缩小，而所有既有功能测试
 *       仍然全绿（单测直接用 {@code new} 构造本类，本来就不经代理）；</li>
 *   <li><b>第三参恒为注入的门面实例</b>：生命周期入口的第三参是「建单 / 改单共用共享部件」的唯一来源
 *       （明细装配 / 取价 / 库存前置 / {@code batchStock()} 访问器）。若哪天改成自己新建一个
 *       {@code OrderService} 或传 {@code null}，共享口径就出现第二份 / 直接 NPE；</li>
 *   <li><b>非法输入在落到生命周期实现点之前就被拒</b>：解析不到订单号必须是 404 且话术给出可执行的下一步
 *       （AI 侧据此重试），非法 / 空 action 必须 422 且列出全部可选值 —— 且这些路径<b>一次都不许</b>
 *       碰生命周期实现点（否则「拒了但已经改了一半」）。</li>
 * </ol>
 *
 * <p><b>红证方向</b>：① 删掉方法上的注解 ⇒ 判据 1 红；② 把第三参改成 {@code null} 或新实例 ⇒ 判据 2 红；
 * ③ 把 action 校验挪到生命周期调用之后 ⇒ 判据 3 红。三条都在真实现上跑，不是内存谓词。</p>
 *
 * <p><b>复算</b>：{@code cd backend/admin-api && ./mvnw -Dtest=OrderAgentFacadeTest test}。</p>
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("#8681 P2-1e 第八批：Agent BFF 编排实现点（事务注解 / 第三参身份 / 拒绝路径）")
class OrderAgentFacadeTest {

    /** 共享部件的唯一实现点：本类只判「它是不是**被注入的那一份**」。 */
    @Mock
    private OrderService orderService;
    @Mock
    private OrderLifecycleService orderLifecycleService;
    @Mock
    private OrderQueryService orderQueryService;

    @InjectMocks
    private OrderAgentFacade facade;

    @Test
    @DisplayName("事务注解逐字跟随：@Transactional(rollbackFor = Exception.class) 原样在搬入的方法上")
    void updateOrderForAgentCarriesItsTransactionAnnotationVerbatim() throws NoSuchMethodException {
        Method method = OrderAgentFacade.class.getMethod("updateOrderForAgent",
                String.class, AgentOrderUpdateRequest.class, Long.class);

        Transactional tx = method.getAnnotation(Transactional.class);
        assertThat(tx).as("事务注解必须随方法搬入 —— 丢了它，五个 action 的失败回滚范围会静默缩小")
                .isNotNull();
        assertThat(tx.rollbackFor()).containsExactly(Exception.class);
        // 另一半：门面一侧不许还把注解 / 方法留着（退休后的声明加回来 = 两条写路径并存）
        assertThatThrownBy(() -> OrderService.class.getMethod("updateOrderForAgent",
                String.class, AgentOrderUpdateRequest.class, Long.class))
                .as("门面转发已退休：加回来 ⇒ 本判据当场红")
                .isInstanceOf(NoSuchMethodException.class);
    }

    @Test
    @DisplayName("每个 action 落到生命周期实现点，且第三参**恒为注入的门面实例**（共享部件不重搭）")
    void everyRoutePassesTheFacadeInstanceAsThirdArg() {
        when(orderQueryService.resolveOrderIdToUuid("ORD-1", 1L)).thenReturn("uuid-1");
        OrderDetailResponse detail = new OrderDetailResponse();
        when(orderQueryService.getOrderById("uuid-1")).thenReturn(detail);

        AgentOrderUpdateRequest status = new AgentOrderUpdateRequest();
        status.setAction("update_status");
        status.setStatus("confirmed");
        assertThat(facade.updateOrderForAgent("ORD-1", status, 1L)).isSameAs(detail);
        verify(orderLifecycleService).updateOrderStatus("uuid-1", "confirmed", orderService.sharedParts());

        AgentOrderUpdateRequest cancel = new AgentOrderUpdateRequest();
        cancel.setAction("cancel");
        cancel.setCancelReason("客户不要了");
        assertThat(facade.updateOrderForAgent("ORD-1", cancel, 1L)).isSameAs(detail);
        verify(orderLifecycleService).cancelOrder("uuid-1", "客户不要了", orderService.sharedParts());

        // 每个 action 之后都回读一次（返回值是 OrderDetailResponse，不是生命周期方法的返回值）
        verify(orderQueryService, times(2)).getOrderById("uuid-1");
    }

    @Test
    @DisplayName("非法 action / 缺参：在落到生命周期实现点之前就被拒（一次都不许碰实现点）")
    void invalidInputsAreRejectedBeforeAnyLifecycleCall() {
        when(orderQueryService.resolveOrderIdToUuid("ORD-1", 1L)).thenReturn("uuid-1");

        AgentOrderUpdateRequest blank = new AgentOrderUpdateRequest();
        assertThatThrownBy(() -> facade.updateOrderForAgent("ORD-1", blank, 1L))
                .isInstanceOfSatisfying(BusinessException.class, e -> {
                    assertThat(e.getCode()).isEqualTo("VALIDATION_ERROR");
                    assertThat(e.getMessage()).contains("action 不能为空");
                });

        AgentOrderUpdateRequest unknown = new AgentOrderUpdateRequest();
        unknown.setAction("explode");
        assertThatThrownBy(() -> facade.updateOrderForAgent("ORD-1", unknown, 1L))
                .isInstanceOfSatisfying(BusinessException.class, e -> {
                    assertThat(e.getCode()).isEqualTo("VALIDATION_ERROR");
                    assertThat(e.getMessage()).contains("不支持的操作类型: explode");
                    // 可选值必须逐个列出：AI 侧据此改一次就重试，而不是猜
                    assertThat(e.getMessage())
                            .contains("update_status/update_logistics/confirm_payment/cancel/refund");
                });

        verifyNoInteractions(orderLifecycleService);
    }

    @Test
    @DisplayName("订单号解析不到 ⇒ 404 ORDER_NOT_FOUND（话术给 AI 可执行的下一步），零生命周期调用")
    void unmatchedIdIsNotFound() {
        when(orderQueryService.resolveOrderIdToUuid("ORD-NOPE", 1L)).thenReturn(null);
        AgentOrderUpdateRequest request = new AgentOrderUpdateRequest();
        request.setAction("update_status");
        request.setStatus("confirmed");

        assertThatThrownBy(() -> facade.updateOrderForAgent("ORD-NOPE", request, 1L))
                .isInstanceOfSatisfying(BusinessException.class, e -> {
                    assertThat(e.getCode()).isEqualTo("ORDER_NOT_FOUND");
                    assertThat(e.getHttpStatus()).isEqualTo(404);
                    assertThat(e.getMessage()).contains("order_query");
                });

        verifyNoInteractions(orderLifecycleService);
    }
}
