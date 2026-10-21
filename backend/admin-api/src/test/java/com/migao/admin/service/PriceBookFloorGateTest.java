// case_ids: PRC-004
package com.migao.admin.service;

import com.migao.admin.entity.Approval;
import com.migao.admin.entity.ProductSku;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.ProductSkuMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.util.ReflectionTestUtils;

import java.math.BigDecimal;

import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.when;

/**
 * 改价闸门接在**价格本录入**上（issue #7375 段 4）：低于成本 ⇒ 没有已通过的 `price_change` 审批
 * 就**写面直接拒**；批过就用一次。
 *
 * <p>为什么接在这里：价格本是给客户让利的口子，让到低于成本就是亏本卖 —— 那必须有人明确同意过。
 * 改前没有任何闸门（谁有录入权限谁就能把价改到 0.01 元）。</p>
 */
@DisplayName("改价闸门：低于成本无审批即拒 / 批过放行并消费 / 成本未知放行")
class PriceBookFloorGateTest {

    private JdbcTemplate jdbcTemplate;
    private ProductSkuMapper productSkuMapper;
    private ApprovalService approvalService;
    private PriceBookService service;

    @BeforeEach
    void setUp() {
        jdbcTemplate = Mockito.mock(JdbcTemplate.class);
        productSkuMapper = Mockito.mock(ProductSkuMapper.class);
        approvalService = Mockito.mock(ApprovalService.class);
        service = new PriceBookService(jdbcTemplate);
        ReflectionTestUtils.setField(service, "productSkuMapper", productSkuMapper);
        ReflectionTestUtils.setField(service, "approvalService", approvalService);
        when(jdbcTemplate.update(anyString(), Mockito.<Object>any(), Mockito.<Object>any(),
                Mockito.<Object>any(), Mockito.<Object>any())).thenReturn(1);
        when(jdbcTemplate.update(anyString(), Mockito.<Object>any(), Mockito.<Object>any(),
                Mockito.<Object>any(), Mockito.<Object>any(), Mockito.<Object>any())).thenReturn(1);
    }

    private void skuWithCost(String cost) {
        ProductSku sku = new ProductSku();
        sku.setId(10L);
        sku.setTenantId(1L);
        sku.setAvgCost(cost == null ? null : new BigDecimal(cost));
        when(productSkuMapper.selectById(10L)).thenReturn(sku);
    }

    @Test
    @DisplayName("🔴 协议价低于成本且无审批 ⇒ 写面直接拒，并给出可行动的申请路径")
    void belowCostWithoutApprovalIsRejected() {
        skuWithCost("100.00");
        when(approvalService.consume(eq(Approval.TYPE_PRICE_CHANGE), anyString(), any(), any()))
                .thenReturn(null);

        assertThatThrownBy(() -> service.upsertProtocol(1L, "c-1", 10L, new BigDecimal("80"), null))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("低于该 SKU 成本")
                .hasMessageContaining("price_change");
    }

    @Test
    @DisplayName("低于成本但有已通过审批 ⇒ 放行并消费（一笔一批）")
    void belowCostWithApprovalPasses() {
        skuWithCost("100.00");
        when(approvalService.consume(eq(Approval.TYPE_PRICE_CHANGE), eq("10"), any(), any()))
                .thenReturn("AP-1");

        assertThatCode(() -> service.upsertTier(1L, 10L, BigDecimal.ONE, null, new BigDecimal("80")))
                .doesNotThrowAnyException();
        Mockito.verify(approvalService).consume(eq(Approval.TYPE_PRICE_CHANGE), eq("10"),
                eq(new BigDecimal("100.00")), eq("sku:10"));
    }

    @Test
    @DisplayName("不低于成本 ⇒ 不查审批（不给正常改价加一次写）")
    void atOrAboveCostNeverTouchesApprovals() {
        skuWithCost("100.00");

        assertThatCode(() -> service.upsertVipLevel(1L, "vip1", 10L, new BigDecimal("120")))
                .doesNotThrowAnyException();
        Mockito.verify(approvalService, Mockito.never()).consume(any(), any(), any(), any());
    }

    @Test
    @DisplayName("🔴 成本未知（没录进价）⇒ 放行且不查审批（否则存量商品全都改不了价）")
    void unknownCostPassesWithoutApproval() {
        skuWithCost(null);

        assertThatCode(() -> service.upsertProtocol(1L, "c-1", 10L, new BigDecimal("1"), null))
                .doesNotThrowAnyException();
        Mockito.verify(approvalService, Mockito.never()).consume(any(), any(), any(), any());
    }

    @Test
    @DisplayName("没有成本读数装置（切片上下文/老单测）⇒ 退回改前行为，不造一道假闸门")
    void withoutCostWiringGateIsAbsent() {
        PriceBookService bare = new PriceBookService(jdbcTemplate);
        assertThatCode(() -> bare.upsertProtocol(1L, "c-1", 10L, new BigDecimal("1"), null))
                .doesNotThrowAnyException();
    }
}
