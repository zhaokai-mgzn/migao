// case_ids: MC-199
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.migao.admin.dto.OrderCreateRequest;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.ProductSku;
import com.migao.admin.entity.StockLedger;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProductMapper;
import com.migao.admin.mapper.ProductSkuMapper;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.math.BigDecimal;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

/**
 * {@link OrderStockService}（issue #8191，P2-1c 从 {@code OrderService} 搬出的库存与销量族）的**行为判据**。
 *
 * <p>判据只钉搬过来的那四件事：① 扣减/回补按**真实米数**（含 0.5 这种小数）走原子语句，台账读数**来自该语句的
 * RETURNING**；② 并发下扣减返回 0 行 ⇒ **显式失败**（不静默钳 0）；③ 售后回补（`ledgerReason = null`）**不落订单腿台账行**
 * （同一次变更只由上游站点记账，否则 delta 翻倍）；④ SKU 定位键族命中唯一才放行，多行歧义 ⇒ 显式拒绝。</p>
 *
 * <p><b>红证</b>：把扣减的 `StockChange` 换成自己读库存、或把「0 行」改成静默继续、或让回补也落台账行，
 * 对应用例当场红（这些正是 issue #6299 / #6300 / #4137 / #4090 的回归面）。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class OrderStockServiceTest {

    @Mock
    private OrderMapper orderMapper;
    @Mock
    private OrderItemMapper orderItemMapper;
    @Mock
    private ProductMapper productMapper;
    @Mock
    private ProductSkuMapper productSkuMapper;
    @Mock
    private StockLedgerService stockLedgerService;

    private OrderStockService stockService;
    private Order order;

    @BeforeEach
    void setUp() {
        MybatisConfiguration configuration = new MybatisConfiguration();
        MapperBuilderAssistant assistant = new MapperBuilderAssistant(configuration, "");
        TableInfoHelper.initTableInfo(assistant, Order.class);
        TableInfoHelper.initTableInfo(assistant, OrderItem.class);
        TableInfoHelper.initTableInfo(assistant, ProductSku.class);

        stockService = new OrderStockService(orderMapper, orderItemMapper, productMapper,
                productSkuMapper, stockLedgerService);

        order = Order.builder()
                .id("order-1")
                .tenantId(1L)
                .orderNo("ORD-1")
                .status("pending")
                .build();
    }

    @Test
    @DisplayName("扣减：按真实米数（2.5 米）调原子语句，台账读数取该语句的 RETURNING，销量同步")
    void deductUsesAtomicStatementAndLedgerComesFromIt() {
        when(orderItemMapper.selectList(any(LambdaQueryWrapper.class)))
                .thenReturn(List.of(item("prod-1", "2.5", Map.of("skuId", 12L))));
        when(orderMapper.selectById("order-1")).thenReturn(order);
        when(productSkuMapper.selectById(12L)).thenReturn(sku(12L, "prod-1", "10.0"));
        when(productSkuMapper.deductStock(12L, new BigDecimal("2.5"), 1L)).thenReturn(row("10.0", "7.5", "SKU-12"));

        stockService.deductStockAndIncreaseSales("order-1");

        verify(productSkuMapper).deductStock(12L, new BigDecimal("2.5"), 1L);
        verify(productSkuMapper).increaseSalesCount(12L, new BigDecimal("2.5"));
        verify(stockLedgerService).record(1L, "prod-1", 12L, "SKU-12",
                new BigDecimal("10.0"), new BigDecimal("7.5"), StockLedger.REASON_ORDER, "ORD-1",
                "订单确认支付扣减库存");
        verify(productMapper).increaseSales("prod-1", new BigDecimal("2.5"), new BigDecimal("99.00"));
    }

    @Test
    @DisplayName("扣减：原子语句返回 0 行（并发占用）⇒ 显式失败，绝不静默继续")
    void deductFailsExplicitlyWhenAtomicStatementChangedNothing() {
        when(orderItemMapper.selectList(any(LambdaQueryWrapper.class)))
                .thenReturn(List.of(item("prod-1", "2.5", Map.of("skuId", 12L))));
        when(orderMapper.selectById("order-1")).thenReturn(order);
        when(productSkuMapper.selectById(12L)).thenReturn(sku(12L, "prod-1", "1.0"));
        when(productSkuMapper.deductStock(anyLong(), any(), anyLong())).thenReturn(null);

        assertThatThrownBy(() -> stockService.deductStockAndIncreaseSales("order-1"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("库存不足")
                .hasMessageContaining("已被并发订单占用");

        verify(stockLedgerService, never()).record(any(), any(), any(), any(), any(), any(), any(), any(), any());
        verify(productMapper, never()).increaseSales(any(), any(), any());
    }

    @Test
    @DisplayName("售后回补：ledgerReason 为 null ⇒ 不落订单腿台账行（该次变更由上游站点记账）")
    void restoreForReturnDoesNotWriteOrderLegLedger() {
        when(orderItemMapper.selectList(any(LambdaQueryWrapper.class)))
                .thenReturn(List.of(item("prod-0", "1.5", Map.of("skuId", 40L))));
        when(orderMapper.selectById("order-1")).thenReturn(order);
        when(productSkuMapper.selectById(40L)).thenReturn(sku(40L, "prod-0", "12.0"));

        stockService.restoreStockForReturn("order-1");

        verify(productSkuMapper).restoreStock(40L, new BigDecimal("1.5"));
        verify(productSkuMapper).decreaseSalesCount(40L, new BigDecimal("1.5"));
        verify(productMapper).decreaseSales("prod-0", new BigDecimal("1.5"), new BigDecimal("99.00"));
        verifyNoInteractions(stockLedgerService);
    }

    @Test
    @DisplayName("库存校验：小数需求按真实米数比较（0.5 米 vs 剩 0.2 米 ⇒ 拒绝；够 ⇒ 放行）")
    void validationComparesRealDecimalQuantity() {
        OrderCreateRequest request = new OrderCreateRequest();
        OrderCreateRequest.OrderItemRequest line = new OrderCreateRequest.OrderItemRequest();
        line.setProductId("prod-2");
        line.setProductName("蜂巢帘");
        line.setQuantity(new BigDecimal("0.5"));
        line.setProcessingInfo(new HashMap<>(Map.of("skuId", 9L)));
        request.setItems(List.of(line));
        when(productSkuMapper.selectById(9L)).thenReturn(sku(9L, "prod-2", "0.2"));

        assertThatThrownBy(() -> stockService.validateStockSufficientForRequest(request, "下单"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("需要 0.5 米")
                .hasMessageContaining("当前仅剩 0.2 米");

        when(productSkuMapper.selectById(9L)).thenReturn(sku(9L, "prod-2", "5.0"));
        assertThatCode(() -> stockService.validateStockSufficientForRequest(request, "下单"))
                .as("库存 5 米 ≥ 需求 0.5 米 ⇒ 必须放行")
                .doesNotThrowAnyException();
    }

    @Test
    @DisplayName("SKU 定位：字符串族唯一命中 ⇒ 返回该 SKU；多行歧义 ⇒ 显式拒绝（不任取一条）")
    void skuMatchingIsUniqueOrRejects() {
        OrderItem line = item("prod-1", "1.0", Map.of("skuCode", "SKU-7", "doorWidth", "2.8米"));
        when(productSkuMapper.selectList(any(LambdaQueryWrapper.class)))
                .thenReturn(List.of(sku(7L, "prod-1", "40.0")));

        assertThat(stockService.matchSkuId(line, "确认支付")).isEqualTo(7L);

        when(productSkuMapper.selectList(any(LambdaQueryWrapper.class)))
                .thenReturn(List.of(sku(7L, "prod-1", "40.0"), sku(8L, "prod-1", "1.0")));
        assertThatThrownBy(() -> stockService.matchSkuId(line, "确认支付"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("无法定位到 SKU");
    }

    @Test
    @DisplayName("未声明 SKU 身份 ⇒ 返回 null（唯一合法的跳过），不做任何 SKU 级库存调整")
    void undeclaredSkuIdentityReturnsNull() {
        OrderItem line = item("prod-1", "1.0", Map.of("sellingMethod", "散剪"));

        assertThat(stockService.matchSkuId(line, "确认支付")).isNull();
        verify(productSkuMapper, times(0)).selectById(any());
    }

    private static OrderItem item(String productId, String qty, Map<String, Object> info) {
        return OrderItem.builder()
                .id("item-" + productId)
                .tenantId(1L)
                .orderId("order-1")
                .productId(productId)
                .productName("商品-" + productId)
                .quantity(new BigDecimal(qty))
                .subtotal(new BigDecimal("99.00"))
                .processingInfo(new HashMap<>(info))
                .build();
    }

    private static ProductSku sku(Long id, String productId, String stock) {
        return ProductSku.builder()
                .id(id)
                .productId(productId)
                .skuCode("SKU-" + id)
                .colorId(3L)
                .colorName("米白")
                .doorWidth("2.8")
                .stock(new BigDecimal(stock))
                .build();
    }

    private static Map<String, Object> row(String before, String after, String skuCode) {
        Map<String, Object> row = new HashMap<>();
        row.put("beforeQuantity", new BigDecimal(before));
        row.put("afterQuantity", new BigDecimal(after));
        row.put("skuCode", skuCode);
        return row;
    }
}
