// case_ids: WH-006, WH-011
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.migao.admin.dto.InboundOrderCreateRequest;
import com.migao.admin.dto.InboundOrderResponse;
import com.migao.admin.entity.FinishedGoodsStock;
import com.migao.admin.entity.InboundOrder;
import com.migao.admin.entity.InboundOrderItem;
import com.migao.admin.entity.Product;
import com.migao.admin.entity.ProductSku;
import com.migao.admin.entity.StockBatch;
import com.migao.admin.entity.WarehouseLocation;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.FinishedGoodsStockMapper;
import com.migao.admin.mapper.InboundOrderItemMapper;
import com.migao.admin.mapper.InboundOrderMapper;
import com.migao.admin.mapper.InboundOrderQueryMapper;
import com.migao.admin.mapper.ProductMapper;
import com.migao.admin.mapper.ProductSkuMapper;
import com.migao.admin.mapper.StockBatchMapper;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.Mockito;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.math.BigDecimal;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doReturn;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 入库单的两处 V196 行为（issue #7750 / 用例 WH-006）：
 *
 * <ol>
 *   <li><b>建单即过账</b>：{@code createAndPost} = create → post（同一次请求、同一个事务）；</li>
 *   <li><b>成品单过账走另一条语义</b>：分配仓位 + 写 {@code finished_goods_stock}，
 *       **不**碰 SKU 米数库存 / 批次 / 移动加权成本（布料单的口径一字不动）。</li>
 * </ol>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("入库单 V194：建单即过账 + 成品过账语义（issue #7750）")
class InboundStockDocumentTest {

    private static final Long TENANT = 1L;

    @Mock private InboundOrderMapper inboundOrderMapper;
    @Mock private InboundOrderItemMapper inboundOrderItemMapper;
    @Mock private InboundOrderQueryMapper inboundOrderQueryMapper;
    @Mock private StockBatchMapper stockBatchMapper;
    @Mock private ProductSkuMapper productSkuMapper;
    @Mock private ProductMapper productMapper;
    @Mock private StockLedgerService stockLedgerService;
    @Mock private WarehouseLocationService warehouseLocationService;
    @Mock private FinishedGoodsStockMapper finishedGoodsStockMapper;
    @Mock private NotificationService notificationService;

    @InjectMocks private InboundOrderService service;

    @BeforeEach
    void setUp() {
        MybatisConfiguration conf = new MybatisConfiguration();
        MapperBuilderAssistant asst = new MapperBuilderAssistant(conf, "");
        TableInfoHelper.initTableInfo(asst, InboundOrder.class);
        TableInfoHelper.initTableInfo(asst, InboundOrderItem.class);
        TableInfoHelper.initTableInfo(asst, Product.class);
        TableInfoHelper.initTableInfo(asst, ProductSku.class);
        TableInfoHelper.initTableInfo(asst, StockBatch.class);
        org.springframework.test.util.ReflectionTestUtils.setField(service, "notificationService", notificationService);
    }

    private static InboundOrder draftFinished(String warehouseId) {
        InboundOrder order = InboundOrder.builder()
                .id("doc-1")
                .tenantId(TENANT)
                .inboundNo("RK-20261025-0001")
                .inboundDate(java.time.LocalDate.of(2026, 10, 25))
                .status(InboundOrder.STATUS_DRAFT)
                .bizCategory(InboundOrder.BIZ_FINISHED)
                .source(InboundOrder.SOURCE_PACKING)
                .totalAmount(BigDecimal.ZERO)
                .build();
        order.setWarehouseId(warehouseId == null ? null : Long.valueOf(warehouseId));
        return order;
    }

    private static InboundOrderItem finishedLine(String itemId) {
        return InboundOrderItem.builder()
                .id(itemId.equals("item-1") ? 1L : 2L)
                .tenantId(TENANT)
                .inboundOrderId("doc-1")
                .orderId("order-1")
                .orderNo("DD-20261025-0001")
                .orderItemId(itemId)
                .productId("prod-1")
                .productName("遮光布帘")
                .quantity(BigDecimal.ONE)
                .build();
    }

    private static WarehouseLocation bin(String code, long id) {
        return WarehouseLocation.builder()
                .id(id).tenantId(TENANT).warehouseId(9L)
                .zoneCode("A").zoneName("成品区").binCode(code).status("active").build();
    }

    @Test
    @DisplayName("🔴 建单即过账：createAndPost = create → post（同一个事务，响应 posted）")
    void createAndPostComposesCreateThenPost() {
        InboundOrderCreateRequest req = new InboundOrderCreateRequest();
        InboundOrderService spy = Mockito.spy(service);
        InboundOrderResponse created = new InboundOrderResponse();
        created.setId("doc-1");
        created.setStatus(InboundOrder.STATUS_DRAFT);
        InboundOrderResponse posted = new InboundOrderResponse();
        posted.setId("doc-1");
        posted.setStatus(InboundOrder.STATUS_POSTED);
        doReturn(created).when(spy).create(eq(req), eq(TENANT), eq("op"));
        doReturn(posted).when(spy).post(eq("doc-1"), eq(TENANT), eq("op"));

        InboundOrderResponse result = spy.createAndPost(req, TENANT, "op");

        assertThat(result.getStatus()).isEqualTo(InboundOrder.STATUS_POSTED);
        verify(spy).create(req, TENANT, "op");
        verify(spy).post("doc-1", TENANT, "op");
    }

    @Test
    @DisplayName("🔴 同单同仓（issue #8103）：两行同一订单 ⇒ 仓位只取一次，两行都落 A-01；不碰 SKU 库存/批次/台账")
    void finishedPostKeepsWholeOrderInOneBin() {
        when(inboundOrderMapper.selectOne(any())).thenReturn(draftFinished("9"));
        when(inboundOrderItemMapper.selectList(any())).thenReturn(List.of(
                finishedLine("item-1"), finishedLine("item-2")));
        when(inboundOrderMapper.markPosted(any(), any(), any(), any())).thenReturn(1);
        when(warehouseLocationService.binForOrder(TENANT, 9L, "order-1")).thenReturn(bin("A-01", 7L));
        when(finishedGoodsStockMapper.claimInStock(any(), any(), any(), anyString(), any(), any(), any(),
                any(), any(), any(), any())).thenReturn(42L, 43L);

        InboundOrderResponse response = service.post("doc-1", TENANT, "op");

        assertThat(response.getStatus()).isEqualTo(InboundOrder.STATUS_POSTED);
        // 同单同仓：仓位只取一次，且两件都进同一个 bin（不再逐行按水位换仓）
        verify(warehouseLocationService, times(1)).binForOrder(TENANT, 9L, "order-1");
        verify(warehouseLocationService, never()).nextFreeBin(anyLong(), anyLong());
        verify(finishedGoodsStockMapper, times(2)).claimInStock(eq(TENANT), eq(9L), eq(7L), eq("A-01"),
                eq("order-1"), eq("DD-20261025-0001"), any(), eq("prod-1"), eq("遮光布帘"),
                eq(BigDecimal.ONE), eq("doc-1"));
        // 明细行回写的是同一个仓位
        verify(inboundOrderItemMapper, times(2)).updateById(
                org.mockito.ArgumentMatchers.<InboundOrderItem>argThat(
                        line -> "A-01".equals(line.getBinCode()) && Long.valueOf(7L).equals(line.getLocationId())));
        // 布料口径一字不动：不建批次、不加米数库存、不落台账
        verify(productSkuMapper, never()).receiveStock(anyLong(), any(), any(), anyString(), anyLong());
        verify(stockBatchMapper, never()).update(any(StockBatch.class));
        verify(stockLedgerService, never()).record(anyLong(), anyString(), anyLong(), anyString(),
                any(), any(), anyString(), any(), any(), any(), any(), any());
    }

    @Test
    @DisplayName("同一件成品已在库（占位 0 行）⇒ 显式冲突、整笔回滚，不换下一个仓位重试")
    void finishedPostRejectsDuplicatePiece() {
        when(inboundOrderMapper.selectOne(any())).thenReturn(draftFinished("9"));
        when(inboundOrderItemMapper.selectList(any())).thenReturn(List.of(finishedLine("item-1")));
        when(inboundOrderMapper.markPosted(any(), any(), any(), any())).thenReturn(1);
        when(warehouseLocationService.binForOrder(TENANT, 9L, "order-1")).thenReturn(bin("A-01", 7L));
        // claimInStock 返回 null = 这件已在库（唯一索引兜住）；Mockito 对 Long 的默认值是 0L，必须显式钉 null
        when(finishedGoodsStockMapper.claimInStock(any(), any(), any(), anyString(), any(), any(), any(),
                any(), any(), any(), any())).thenReturn(null);

        assertThatThrownBy(() -> service.post("doc-1", TENANT, "op"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("已在库");
        verify(inboundOrderItemMapper, never()).updateById(
                org.mockito.ArgumentMatchers.<InboundOrderItem>any());
    }

    @Test
    @DisplayName("成品单缺仓库 ⇒ 拒绝过账（不猜仓库、不分配一个孤儿仓位）")
    void finishedPostWithoutWarehouseRejected() {
        when(inboundOrderMapper.selectOne(any())).thenReturn(draftFinished(null));
        when(inboundOrderItemMapper.selectList(any())).thenReturn(List.of(finishedLine("item-1")));
        when(inboundOrderMapper.markPosted(any(), any(), any(), any())).thenReturn(1);

        assertThatThrownBy(() -> service.post("doc-1", TENANT, "op"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("缺少成品仓");
        verify(finishedGoodsStockMapper, never()).claimInStock(any(), any(), any(), anyString(), any(), any(),
                any(), any(), any(), any(), any());
    }

    @Test
    @DisplayName("成品单明细缺订单行引用 ⇒ 拒绝过账（仓位无法对应到成品）")
    void finishedPostWithoutOrderItemRejected() {
        InboundOrderItem bad = finishedLine("item-1");
        bad.setOrderItemId(null);
        when(inboundOrderMapper.selectOne(any())).thenReturn(draftFinished("9"));
        when(inboundOrderItemMapper.selectList(any())).thenReturn(List.of(bad));
        when(inboundOrderMapper.markPosted(any(), any(), any(), any())).thenReturn(1);
        when(warehouseLocationService.nextFreeBin(TENANT, 9L)).thenReturn(bin("A-01", 7L));

        assertThatThrownBy(() -> service.post("doc-1", TENANT, "op"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("缺少订单行引用");
    }

    @Test
    @DisplayName("成品在库行的 status 常量与 DB CHECK 三态一致（in_stock / shipped / unpacked）")
    void stockStatusConstants() {
        assertThat(FinishedGoodsStock.STATUS_IN_STOCK).isEqualTo("in_stock");
        assertThat(FinishedGoodsStock.STATUS_SHIPPED).isEqualTo("shipped");
        assertThat(FinishedGoodsStock.STATUS_UNPACKED).isEqualTo("unpacked");
    }
}
