// case_ids: WH-004
package com.migao.admin.service;

import com.migao.admin.dto.OutboundOrderCreateRequest;
import com.migao.admin.dto.OutboundOrderView;
import com.migao.admin.entity.FinishedGoodsStock;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OutboundOrder;
import com.migao.admin.entity.OutboundOrderItem;
import com.migao.admin.entity.ProductSku;
import com.migao.admin.entity.StockLedger;
import com.migao.admin.entity.Warehouse;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.OutboundOrderItemMapper;
import com.migao.admin.mapper.OutboundOrderMapper;
import com.migao.admin.mapper.OutboundOrderQueryMapper;
import com.migao.admin.mapper.ProductSkuMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.math.BigDecimal;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 出库单服务（V196，issue #7750 / 用例 WH-004）。
 *
 * <p>守四条：</p>
 * <ol>
 *   <li><b>建单即过账</b>：响应/落库状态都是 {@code posted}（没有草稿态）；</li>
 *   <li><b>库存不足不许过</b>：原子扣减返回 0 行 ⇒ 抛 422，且**不**落台账、**不**落明细；</li>
 *   <li><b>数量粒度</b>：&gt; 0 且最多 1 位小数（与 {@code product_skus.stock} 的 NUMERIC(12,1) 同粒度）；</li>
 *   <li><b>台账口径</b>：{@code reason=outbound}、{@code refNo=出库单号}、before/after 来自扣减语句的 RETURNING。</li>
 * </ol>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("出库单服务（V196 / issue #7750）")
class OutboundOrderServiceTest {

    private static final Long TENANT = 1L;

    @Mock private OutboundOrderMapper outboundOrderMapper;
    @Mock private OutboundOrderItemMapper outboundOrderItemMapper;
    @Mock private OutboundOrderQueryMapper outboundOrderQueryMapper;
    @Mock private ProductSkuMapper productSkuMapper;
    @Mock private StockLedgerService stockLedgerService;
    @Mock private WarehouseService warehouseService;

    @InjectMocks private OutboundOrderService service;

    private static ProductSku sku(long id, long tenantId, String code) {
        ProductSku sku = new ProductSku();
        sku.setId(id);
        sku.setTenantId(tenantId);
        sku.setSkuCode(code);
        sku.setProductId("prod-1");
        sku.setStock(new BigDecimal("10.0"));
        sku.setAvgCost(new BigDecimal("12.5000"));
        return sku;
    }

    private static OutboundOrderCreateRequest request(String qty) {
        OutboundOrderCreateRequest req = new OutboundOrderCreateRequest();
        OutboundOrderCreateRequest.Item item = new OutboundOrderCreateRequest.Item();
        item.setSkuId(11L);
        item.setQuantity(new BigDecimal(qty));
        req.setItems(List.of(item));
        return req;
    }

    private static Map<String, Object> deducted(String before, String after, String code) {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("skuCode", code);
        row.put("beforeQuantity", new BigDecimal(before));
        row.put("afterQuantity", new BigDecimal(after));
        return row;
    }

    @Test
    @DisplayName("建单即过账：扣库存 + 落台账（reason=outbound，refNo=出库单号）+ 单头 posted")
    void createAndPostDeductsAndRecordsLedger() {
        when(productSkuMapper.selectById(11L)).thenReturn(sku(11L, TENANT, "H-01"));
        when(productSkuMapper.deductStock(eq(11L), any(), eq(TENANT)))
                .thenReturn(deducted("10.0", "5.0", "H-01"));

        OutboundOrderView view = service.createAndPost(request("5.0"), TENANT, "仓管A");

        ArgumentCaptor<OutboundOrder> orderCap = ArgumentCaptor.forClass(OutboundOrder.class);
        verify(outboundOrderMapper).insert(orderCap.capture());
        OutboundOrder saved = orderCap.getValue();
        assertThat(saved.getStatus()).isEqualTo(OutboundOrder.STATUS_POSTED);
        assertThat(saved.getOutboundNo()).startsWith("CK-").matches("CK-\\d{8}-\\d{4}");
        assertThat(saved.getBizCategory()).isEqualTo(OutboundOrder.BIZ_FABRIC);
        assertThat(saved.getSource()).isEqualTo(OutboundOrder.SOURCE_MANUAL);
        assertThat(saved.getPostedBy()).isEqualTo("仓管A");

        ArgumentCaptor<OutboundOrderItem> itemCap = ArgumentCaptor.forClass(OutboundOrderItem.class);
        verify(outboundOrderItemMapper).insert(itemCap.capture());
        assertThat(itemCap.getValue().getQuantity()).isEqualByComparingTo("5.0");
        assertThat(itemCap.getValue().getUnit()).isEqualTo("m");
        assertThat(itemCap.getValue().getSkuCode()).isEqualTo("H-01");

        // 台账：来源/单号/前后值三件事都必须对得上（对账靠它）
        verify(stockLedgerService).record(eq(TENANT), eq("prod-1"), eq(11L), eq("H-01"),
                eq(new BigDecimal("10.0")), eq(new BigDecimal("5.0")),
                eq(StockLedger.REASON_OUTBOUND), eq(saved.getOutboundNo()), eq("出库单过账"),
                eq(new BigDecimal("12.5000")), eq(new BigDecimal("12.5000")), eq(new BigDecimal("12.5000")));

        assertThat(view.getStatus()).isEqualTo(OutboundOrder.STATUS_POSTED);
        assertThat(view.getTotalQuantity()).isEqualByComparingTo("5.0");
    }

    @Test
    @DisplayName("🔴 库存不足 ⇒ 拒绝（不许负库存），且不落台账、不落明细")
    void insufficientStockRejected() {
        when(productSkuMapper.selectById(11L)).thenReturn(sku(11L, TENANT, "H-01"));
        when(productSkuMapper.deductStock(eq(11L), any(), eq(TENANT))).thenReturn(null);

        assertThatThrownBy(() -> service.createAndPost(request("11.0"), TENANT, "仓管A"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("库存不足");

        verify(stockLedgerService, never()).record(anyLong(), anyString(), anyLong(), anyString(),
                any(), any(), anyString(), any(), any(), any(), any(), any());
        verify(outboundOrderItemMapper, never()).insert(any(OutboundOrderItem.class));
    }

    @Test
    @DisplayName("数量粒度：1.5 米可以；1.55 米 / 0 米 一律拒（不静默取整）")
    void quantityPrecisionGate() {
        when(productSkuMapper.selectById(11L)).thenReturn(sku(11L, TENANT, "H-01"));
        when(productSkuMapper.deductStock(eq(11L), any(), eq(TENANT)))
                .thenReturn(deducted("10.0", "8.5", "H-01"));

        service.createAndPost(request("1.5"), TENANT, "op");

        assertThatThrownBy(() -> service.createAndPost(request("1.55"), TENANT, "op"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("最多 1 位小数");
        assertThatThrownBy(() -> service.createAndPost(request("0"), TENANT, "op"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("必须大于 0");
    }

    @Test
    @DisplayName("跨租户 SKU ⇒ 当「不存在」拒绝（不泄露对方存在性）")
    void foreignTenantSkuRejected() {
        when(productSkuMapper.selectById(11L)).thenReturn(sku(11L, 999L, "OTHER"));

        assertThatThrownBy(() -> service.createAndPost(request("1.0"), TENANT, "op"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("SKU 不存在");
        verify(productSkuMapper, never()).deductStock(anyLong(), any(), anyLong());
    }

    @Test
    @DisplayName("成品发货出库单：source=ship、逐行带仓位号、数量取在库行（不碰 SKU 库存）")
    void finishedOutboundCarriesBins() {
        Order order = Order.builder().id("order-1").orderNo("DD-1").tenantId(TENANT).build();
        FinishedGoodsStock row = FinishedGoodsStock.builder()
                .orderItemId("item-1").productName("遮光布帘").binCode("A-01")
                .locationId(7L).quantity(new BigDecimal("1.00")).unit("set").build();
        Warehouse warehouse = new Warehouse();
        warehouse.setId(9L);
        warehouse.setName("成品仓");

        service.createFinishedOutbound(order, List.of(row), warehouse, TENANT, "工人甲");

        ArgumentCaptor<OutboundOrder> orderCap = ArgumentCaptor.forClass(OutboundOrder.class);
        verify(outboundOrderMapper).insert(orderCap.capture());
        assertThat(orderCap.getValue().getBizCategory()).isEqualTo(OutboundOrder.BIZ_FINISHED);
        assertThat(orderCap.getValue().getSource()).isEqualTo(OutboundOrder.SOURCE_SHIP);
        assertThat(orderCap.getValue().getOrderNo()).isEqualTo("DD-1");

        ArgumentCaptor<OutboundOrderItem> itemCap = ArgumentCaptor.forClass(OutboundOrderItem.class);
        verify(outboundOrderItemMapper).insert(itemCap.capture());
        assertThat(itemCap.getValue().getBinCode()).isEqualTo("A-01");
        assertThat(itemCap.getValue().getUnit()).isEqualTo("set");
        // 成品无成本口径 ⇒ 单价留空，不伪造 0
        assertThat(itemCap.getValue().getUnitCost()).isNull();
        verify(productSkuMapper, never()).deductStock(anyLong(), any(), anyLong());
    }
}
