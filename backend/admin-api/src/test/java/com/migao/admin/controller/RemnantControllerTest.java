// case_ids: PR-099
package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.RemnantViews;
import com.migao.admin.service.RemnantService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoMoreInteractions;
import static org.mockito.Mockito.when;

/**
 * {@link RemnantController} 的参数搬运判据（V122 / issue #5146）。
 *
 * <h2>判据</h2>
 * <ol>
 *   <li><b>租户上下文逐调用下传</b>：每个端点都必须把 {@link TenantContext} 里的租户 id 传给服务
 *       —— 跨租户读余料台账是**数据泄漏**，不是分页问题（同 {@code StockBatchControllerTest} 的纪律）；</li>
 *   <li><b>过滤 / 分页参数原样下传</b>（不重排、不取默认值、不吞掉空值）；</li>
 *   <li><b>请求体解析</b>：`items` / `orderItemId` / `orderNo` / `itemKey` / `reason` 逐键取，
 *       空串与缺键都归一为 `null`（**不把空串当成合法值**下传 —— 那会让服务端把「没填」当成「填了空」）；</li>
 *   <li><b>本控制器不判任何口径</b>：它不读也不写库存金额、不算回收额 —— 一切判定在服务端。</li>
 * </ol>
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("RemnantController 余料回收端点（参数搬运 + 租户上下文）")
class RemnantControllerTest {

    private static final Long TENANT = 5146L;

    @Mock
    private RemnantService remnantService;

    @InjectMocks
    private RemnantController controller;

    @AfterEach
    void clearTenant() {
        TenantContext.clear();
    }

    @Test
    @DisplayName("判据1/2：台账读面的租户与过滤参数**原样**下传（空值也照传）")
    void ledgerPassesTenantAndFilters() {
        TenantContext.setTenantId(TENANT);
        RemnantViews.LedgerView view = new RemnantViews.LedgerView(
                com.migao.admin.dto.PageResponse.of(3L, 2L, 50L, List.of()), null);
        when(remnantService.ledger(TENANT, "available", "PC-1", null, 2L, 50L)).thenReturn(view);

        ApiResponse<RemnantViews.LedgerView> response =
                controller.ledger("available", "PC-1", null, 2L, 50L);

        assertThat(response.isSuccess()).isTrue();
        assertThat(response.getData()).isSameAs(view);
        verify(remnantService).ledger(TENANT, "available", "PC-1", null, 2L, 50L);
        verifyNoMoreInteractions(remnantService);
    }

    @Test
    @DisplayName("判据3：写小件尺寸表 —— `items` 逐项原样下传；缺键 / 非数组 ⇒ 空列表（不是 null）")
    void putSmallItemSpecsParsesItems() {
        TenantContext.setTenantId(TENANT);
        RemnantViews.SpecsView saved = new RemnantViews.SpecsView(true,
                List.of(new RemnantViews.SpecLine("绑带-布", new BigDecimal("0.50"),
                        new BigDecimal("0.20"), null, "system", null)), null);
        when(remnantService.putSpecs(eq(TENANT), any())).thenReturn(saved);

        List<Map<String, Object>> items = List.of(
                Map.of("item_key", "绑带-布", "length_m", "0.50", "width_m", "0.20"));
        ApiResponse<RemnantViews.SpecsView> response =
                controller.putSmallItemSpecs(Map.of("items", items));

        assertThat(response.getData()).isSameAs(saved);
        @SuppressWarnings("unchecked")
        ArgumentCaptor<List<Map<String, Object>>> captor = ArgumentCaptor.forClass(List.class);
        verify(remnantService).putSpecs(eq(TENANT), captor.capture());
        assertThat(captor.getValue()).as("控制器只搬参数、不改造 body（键名归一在服务端）")
                .isEqualTo(items);

        // 缺 `items` 键 / 传的不是数组 ⇒ 归一为**空列表**（= 清空 = 回到未配置），不是 null
        controller.putSmallItemSpecs(Map.of());
        controller.putSmallItemSpecs(Map.of("items", "不是数组"));
        verify(remnantService, org.mockito.Mockito.times(2)).putSpecs(TENANT, List.of());
    }

    @Test
    @DisplayName("判据3：回收 / 报废的请求体逐键解析，空串归一为 null（不把「没填」当成「填了空」）")
    void recoverAndScrapParseBodies() {
        TenantContext.setTenantId(TENANT);
        RemnantViews.RemnantLine line = new RemnantViews.RemnantLine(9L, 1, "width",
                new BigDecimal("3.00"), new BigDecimal("0.30"), new BigDecimal("0.90"),
                "ORD-1", "JG-ORD-1", "PC-1", "LOT-1", "acc-prod", "SKU-1",
                "used", "ORD-1", "ITEM-1", "绑带-布",
                new BigDecimal("3.00"), new BigDecimal("12.5000"), new BigDecimal("37.500000"),
                null, "system", null, null, null, null);
        when(remnantService.recover(TENANT, 9L, "ITEM-1", "ORD-1", "绑带-布")).thenReturn(line);
        // 空串归一为 null 的那一次也要有替身：断言的是「服务端收到的是 null」而不是「拿回占位值」
        when(remnantService.recover(TENANT, 9L, "ITEM-1", null, "绑带-布")).thenReturn(line);
        when(remnantService.scrap(TENANT, 9L, "超期未用")).thenReturn(line);

        assertThat(controller.recover(9L, Map.of("orderItemId", "ITEM-1", "orderNo", "ORD-1",
                "itemKey", "绑带-布")).getData()).isSameAs(line);
        // 空串 / 空白 ⇒ null（服务端据此判「没填」，而不是拿空串去查库）
        assertThat(controller.recover(9L, Map.of("orderItemId", "ITEM-1", "orderNo", "   ",
                "itemKey", "绑带-布")).getData()).isSameAs(line);
        assertThat(controller.scrap(9L, Map.of("reason", "超期未用")).getData()).isSameAs(line);

        verify(remnantService).recover(TENANT, 9L, "ITEM-1", "ORD-1", "绑带-布");
        verify(remnantService).recover(TENANT, 9L, "ITEM-1", null, "绑带-布");
        verify(remnantService).scrap(TENANT, 9L, "超期未用");
        verify(remnantService, never()).recover(eq(TENANT), eq(9L), eq("ITEM-1"), eq("   "), any());
    }

    @Test
    @DisplayName("判据1：匹配读面同样逐调用下传租户（batchNo 可空 = 服务端从批次台账反查）")
    void matchPassesTenantAndOptionalBatch() {
        TenantContext.setTenantId(TENANT);
        RemnantViews.MatchView view = new RemnantViews.MatchView(false,
                RemnantService.NOTICE_SPECS_UNCONFIGURED, List.of("绑带-布"), List.of(), List.of(),
                List.of("绑带-布"));
        when(remnantService.match(TENANT, "ITEM-1", null)).thenReturn(view);
        when(remnantService.specs(TENANT)).thenReturn(new RemnantViews.SpecsView(false, List.of(),
                RemnantService.NOTICE_SPECS_UNCONFIGURED));

        ApiResponse<RemnantViews.MatchView> response = controller.match("ITEM-1", null);
        assertThat(response.getData()).isSameAs(view);
        assertThat(response.getData().notice())
                .as("「未配置不静默」的说明必须**原样**回给调用方（控制器不吞、不改写）")
                .isEqualTo(RemnantService.NOTICE_SPECS_UNCONFIGURED);
        assertThat(controller.smallItemSpecs().getData().configured()).isFalse();

        verify(remnantService).match(TENANT, "ITEM-1", null);
        verify(remnantService).specs(TENANT);
    }
}
