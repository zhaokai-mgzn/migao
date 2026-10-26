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
import static org.mockito.ArgumentMatchers.isNull;
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
    @DisplayName("PR-035 列表与建单都把当前租户透传给服务（跨租户读 = 数据泄漏；V196 起建单即过账）")
    void listAndCreatePassTenant() {
        TenantContext.setTenantId(7L);
        when(inboundOrderService.list(any(), any(), any(), any(), any())).thenReturn(List.of(new InboundOrderLine()));
        when(inboundOrderService.createAndPost(any(), any(), any())).thenReturn(new InboundOrderResponse());

        ApiResponse<List<InboundOrderLine>> list = controller.list("柯桥", "draft", "finished", null);
        assertThat(list.getData()).hasSize(1);
        // 类别维（V196 / issue #7794）：查询参数必须原样到服务层 —— 丢掉它 = 两个视图都拿全量（混排照旧）。
        verify(inboundOrderService).list(eq("柯桥"), eq("draft"), eq("finished"), isNull(), eq(7L));

        InboundOrderCreateRequest req = new InboundOrderCreateRequest();
        controller.create(req);
        // V194（issue #7750）：建单端点走 createAndPost（建单 + 过账一次请求）——
        // 不再是「先建草稿、再点过账」。判据 = 只允许调 createAndPost，调 create 即红。
        verify(inboundOrderService).createAndPost(eq(req), eq(7L), any());

        // 建单的操作人取自认证上下文；无认证时退化为 "system"（不写 null、不抛异常）
        verify(inboundOrderService).createAndPost(eq(req), eq(7L), eq("system"));
        verify(inboundOrderService, never()).create(any(), any(), any());
    }

    /**
     * issue #7807：列表要能**按仓库查单**（改前只有「仓库」文本列可看，查不了）。
     *
     * <p>守两条：① 查询参数 {@code warehouseId} 原样到服务层（丢掉 = 下拉选了仓也返回全部仓的单，
     * 而页面看起来一切正常）；② 与 {@code bizCategory} **同时**给时不得互相吞没
     * —— 两个筛选是「且」的关系（原料仓 + 某个仓），丢任一个都表现为「筛了没用」。</p>
     */
    @Test
    @DisplayName("#7807 ?warehouseId=12 ⇒ 服务层收到 12，且与 bizCategory 同时给时不互相吞")
    void listPassesWarehouseIdTogetherWithBizCategory() {
        TenantContext.setTenantId(7L);
        when(inboundOrderService.list(any(), any(), any(), any(), any())).thenReturn(List.of());

        controller.list(null, null, "fabric", 12L);
        verify(inboundOrderService).list(isNull(), isNull(), eq("fabric"), eq(12L), eq(7L));

        // 反向零回归：不传仓库 ⇒ 服务层收到 null（= 全部仓库）
        controller.list(null, null, "fabric", null);
        verify(inboundOrderService).list(isNull(), isNull(), eq("fabric"), isNull(), eq(7L));
    }

    /**
     * issue #7794：成品单详情要能看到**仓位号**（成品仓入库的全部意义）。
     *
     * <p>本用例只守 Controller 这一层的**不改写**契约：服务层给的明细（含 binCode / setNo / shortCode）
     * 必须原样出参。字段映射本体（{@code BeanUtils.copyProperties}）由
     * {@code InboundOrderServiceTest.InboundBizCategory#finishedDetailCarriesBinAndSetFields} 守 ——
     * 那里断到的是「实体列 → 响应字段」的真映射，这里断到的是「Controller 不吞字段」。</p>
     */
    @Test
    @DisplayName("#7794 成品单详情：仓位号 / 套号 / 短码原样出参（Controller 不改写服务层明细）")
    void finishedDetailKeepsBinAndSetFields() {
        TenantContext.setTenantId(7L);
        InboundOrderResponse resp = new InboundOrderResponse();
        resp.setBizCategory("finished");
        InboundOrderResponse.Item item = new InboundOrderResponse.Item();
        item.setBinCode("A-01");
        item.setSetNo("JG-20261026-001-001");
        item.setShortCode("AB12CD34");
        item.setUnit("set");
        // issue #7799：成品单明细要能看到「来源订单号」（回查是哪张订单的）
        item.setOrderNo("SO-20261026-0001");
        resp.setItems(List.of(item));
        when(inboundOrderService.detail(eq("o-finished-1"), eq(7L))).thenReturn(resp);

        ApiResponse<InboundOrderResponse> detail = controller.detail("o-finished-1");

        assertThat(detail.getData().getBizCategory()).isEqualTo("finished");
        assertThat(detail.getData().getItems()).hasSize(1);
        InboundOrderResponse.Item out = detail.getData().getItems().get(0);
        assertThat(out.getBinCode()).isEqualTo("A-01");
        assertThat(out.getSetNo()).isEqualTo("JG-20261026-001-001");
        assertThat(out.getShortCode()).isEqualTo("AB12CD34");
        assertThat(out.getOrderNo()).as("#7799 来源订单号原样出参（Controller 不改写）")
                .isEqualTo("SO-20261026-0001");
        assertThat(out.getUnit()).isEqualTo("set");
        // 租户上下文同样必须透传（跨租户读 = 数据泄漏）
        verify(inboundOrderService).detail(eq("o-finished-1"), eq(7L));
    }
}
