package com.migao.admin.controller;

// case_ids=[PR-034, PR-035]

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.InboundOrderActionRequest;
import com.migao.admin.dto.InboundOrderCreateRequest;
import com.migao.admin.dto.InboundOrderLine;
import com.migao.admin.dto.InboundOrderResponse;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.service.InboundOrderService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 入库单 Controller 契约（V111，issue #5034）。
 *
 * <p>守两条判据：</p>
 * <ol>
 *   <li><b>动作端点只认 post / cancel</b>：未知 action 必须被拒（fail-closed）。
 *       放行的后果是「传错动作词静默什么都不做」，调用方以为过账成功了 ——
 *       而库存没加，且没有任何报错。</li>
 *   <li><b>列表把租户上下文透传给服务</b>：跨租户读是数据泄漏，不是过滤问题。</li>
 * </ol>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("入库单 Controller（V111 / issue #5034）")
class InboundOrderControllerTest {

    @Mock private InboundOrderService inboundOrderService;

    @InjectMocks private InboundOrderController controller;

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    @Test
    @DisplayName("PR-034 action=post ⇒ 调过账；action=cancel ⇒ 调作废；未知 action ⇒ 拒绝且不调服务")
    void actRoutesToPostAndCancelOnly() {
        TenantContext.setTenantId(7L);
        when(inboundOrderService.post(any(), any(), any())).thenReturn(new InboundOrderResponse());
        when(inboundOrderService.cancel(any(), any(), any(), any())).thenReturn(new InboundOrderResponse());

        InboundOrderActionRequest post = new InboundOrderActionRequest();
        post.setAction("post");
        ApiResponse<InboundOrderResponse> posted = controller.act("RK-20260923-0001", post);
        assertThat(posted.isSuccess()).isTrue();
        verify(inboundOrderService).post(eq("RK-20260923-0001"), eq(7L), any());

        InboundOrderActionRequest cancel = new InboundOrderActionRequest();
        cancel.setAction("cancel");
        cancel.setReason("录错");
        controller.act("RK-20260923-0001", cancel);
        verify(inboundOrderService).cancel(eq("RK-20260923-0001"), eq("录错"), eq(7L), any());

        InboundOrderActionRequest bogus = new InboundOrderActionRequest();
        bogus.setAction("submit");
        assertThatThrownBy(() -> controller.act("RK-20260923-0001", bogus))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("只支持 post");
    }

    @Test
    @DisplayName("PR-035 列表与建单都把当前租户透传给服务（跨租户读 = 数据泄漏）")
    void listAndCreatePassTenant() {
        TenantContext.setTenantId(7L);
        when(inboundOrderService.list(any(), any(), any())).thenReturn(List.of(new InboundOrderLine()));
        when(inboundOrderService.create(any(), any(), any())).thenReturn(new InboundOrderResponse());

        ApiResponse<List<InboundOrderLine>> list = controller.list("柯桥", "draft");
        assertThat(list.getData()).hasSize(1);
        verify(inboundOrderService).list(eq("柯桥"), eq("draft"), eq(7L));

        InboundOrderCreateRequest req = new InboundOrderCreateRequest();
        controller.create(req);
        verify(inboundOrderService).create(eq(req), eq(7L), any());

        // 建单的操作人取自认证上下文；无认证时退化为 "system"（不写 null、不抛异常）
        verify(inboundOrderService).create(eq(req), eq(7L), eq("system"));
    }
}
